# TermPipe Reviewer — Gemini Direct Backend Handoff

**Date:** April 12, 2026  
**Author:** Claude (session audit)  
**Project:** `~/termpipe-mcp/`  
**Target file:** `termpipe_mcp/tools/surgical/reviewer.py`

---

## Context

TermPipe's pre-commit reviewer gate (`reviewer.py`) calls an LLM after every
write-path tool call to check for syntax errors, duplicates, import issues, etc.
It supports multiple backends via auto-detection at startup (`_get_reviewer()`):

```
Priority order (first available wins):
  1. omniproxy agentic loop  → http://127.0.0.1:8743  (tools-capable, full agentic loop)
  2. iflow direct            → http://127.0.0.1:8421  (text-only)
  3. gemini CLI              → subprocess: gemini -p <prompt> -o stream-json
```

**Problem:** iflow is shutting down in 7 days. omniproxy requires a running
`omni serve --bus` or `omni serve` process. Both are indirection layers.

**Solution:** Craig has effectively unlimited Gemini capacity (~6k req/hr on a
free .edu-linked Pro tier). The goal is to make Gemini the primary/default
reviewer backend, using the `@google/genai` SDK approach directly — the same
pattern AionUi uses (`GeminiRotatingClient` + `OpenAI2GeminiConverter`).

---

## What AionUi Does (the reference pattern)

AionUi source: `/media/craig/Linux-SSD/Downloads-SSD-Linux/aion/src/common/api/`

Key files:
- `GeminiRotatingClient.ts` — wraps `@google/genai`'s `GoogleGenAI`, handles
  multi-key rotation, exposes `createChatCompletion(OpenAIChatCompletionParams)`
- `OpenAI2GeminiConverter.ts` — converts OpenAI message/tool format ↔ Gemini format
- `RotatingApiClient.ts` — base class: key rotation, retry logic (3 retries, 1s delay)

**The key insight:** AionUi calls `client.models.generateContent(geminiRequest)`
directly via the `@google/genai` SDK — no OAuth dance, no CLI subprocess, no
intermediate HTTP server. Just `GEMINI_API_KEY` env var (or blank string for
the .edu/OAuth path, which the CLI handles transparently).

**Python equivalent:** `google-genai` package (`pip install google-genai`)
Same SDK, Python bindings. `GoogleGenAI` → `genai.Client`.

```python
import google.genai as genai

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=[{"role": "user", "parts": [{"text": prompt}]}],
    tools=[{"function_declarations": [...]}],   # optional
)
text = response.candidates[0].content.parts[0].text
```

**Auth for the .edu/no-API-key path:** When `api_key=""`, the SDK falls back
to Application Default Credentials (ADC) — same as `gemini` CLI uses.
Run `gcloud auth application-default login` once; after that it just works.
Craig's .edu account already has this set up (the `gemini` CLI works today).

---

## Current State of `reviewer.py`

- `_register_gemini_cli()` exists and works — it shells out to `gemini -p ...`
  subprocess. This is fragile (stream-json parsing, subprocess overhead, no
  tool-calling support).
- `_get_reviewer()` auto-detects backends in priority order; gemini CLI is last.
- The reviewer's tool set (for agentic FIXED writes) is: `read_file`,
  `find_in_file`, `read_lines`, `smart_replace`. **`write_file` was removed
  this session** — it was the root cause of `overwrite_lines` dupe bugs.

---

## Implementation Plan

### Option A: Gemini Direct (recommended)

Replace `_register_gemini_cli()` with `_register_gemini_direct()` using
`google-genai` SDK. Make it the **first** probe in `_get_reviewer()`, ahead
of omniproxy and iflow. Keep the CLI fallback.

**Step 1 — Add dependency**
```bash
pip install google-genai
# or add to ~/termpipe-mcp/pyproject.toml:
# "google-genai>=1.0.0"
```

**Step 2 — Add `_register_gemini_direct()` to `reviewer.py`**

```python
def _probe_gemini_sdk() -> bool:
    """Return True if google-genai SDK is available."""
    try:
        import google.genai
        return True
    except ImportError:
        return False


def _register_gemini_direct(model: str = "gemini-2.5-flash"):
    """
    Register Google Gemini SDK as the reviewer backend.
    
    Uses google-genai SDK directly — same approach as AionUi's
    GeminiRotatingClient. No subprocess, no OAuth dance, no HTTP server.
    
    Auth: GEMINI_API_KEY env var, or ADC (gcloud auth application-default login)
    for the .edu/free-tier path. Empty string triggers ADC fallback.
    """
    import google.genai as genai
    import os

    api_key = os.environ.get("GEMINI_API_KEY", "")
    client = genai.Client(api_key=api_key if api_key else None)

    def _fn(prompt: str, timeout: float) -> str:
        # Non-agentic: single-turn text only (reviewer doesn't need tools
        # for APPROVED/FIXED decisions — smart_replace handles the write).
        # For tool-capable agentic loop, see Option B below.
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=800,
            ),
        )
        return response.text.strip() if response.text else ""

    register_reviewer("gemini-direct", _fn)
```

**Step 3 — Promote to top of `_get_reviewer()` priority chain**

In `_get_reviewer()`, change the auto-detect block:

```python
# BEFORE:
if _probe_http("http://127.0.0.1:8743/health"):
    _register_omniproxy()
elif _probe_http("http://127.0.0.1:8421/health"):
    _register_iflow()
elif _probe_gemini_cli():
    _register_gemini_cli()

# AFTER:
if _probe_gemini_sdk():
    _register_gemini_direct()          # Primary: direct SDK, always available
elif _probe_http("http://127.0.0.1:8743/health"):
    _register_omniproxy()              # Fallback 1: omniproxy (tools-capable)
elif _probe_gemini_cli():
    _register_gemini_cli()             # Fallback 2: CLI subprocess
# iflow intentionally dropped (shutting down)
```

---

### Option B: Gemini Direct + Agentic Tool Loop (full parity with omniproxy path)

If you want the reviewer to actually *call* `smart_replace` to fix issues
(not just report them), you need a tool-calling loop. The `google-genai` SDK
supports function calling natively — same as AionUi's `OpenAI2GeminiConverter`
handles `functionDeclarations`.

```python
def _register_gemini_direct_agentic(model: str = "gemini-2.5-flash"):
    import google.genai as genai
    import google.genai.types as gtypes
    import os, json

    api_key = os.environ.get("GEMINI_API_KEY", "")
    client = genai.Client(api_key=api_key if api_key else None)

    # Convert reviewer tool defs (OpenAI format) to Gemini functionDeclarations
    def _to_gemini_tools(openai_tools):
        return gtypes.Tool(function_declarations=[
            gtypes.FunctionDeclaration(
                name=t["function"]["name"],
                description=t["function"].get("description", ""),
                parameters=t["function"].get("parameters"),
            )
            for t in openai_tools
        ])

    def _fn(prompt: str, timeout: float) -> str:
        tools = _to_gemini_tools(_reviewer_tool_defs())
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        MAX_TURNS = 8

        for _ in range(MAX_TURNS):
            response = client.models.generate_content(
                model=model,
                contents=contents,
                tools=[tools],
                config=gtypes.GenerateContentConfig(temperature=0.0, max_output_tokens=800),
            )
            candidate = response.candidates[0]
            part = candidate.content.parts[0]

            # Tool call?
            if hasattr(part, "function_call") and part.function_call:
                fc = part.function_call
                args = dict(fc.args)
                result = _call_termcp(fc.name, args)
                # Append model turn + tool result
                contents.append({"role": "model", "parts": [{"function_call": fc}]})
                contents.append({"role": "user", "parts": [{"function_response": {
                    "name": fc.name, "response": {"result": result}
                }}]})
                continue

            # Text response — done
            return part.text.strip() if part.text else ""

        return "[reviewer: max turns reached]"

    register_reviewer("gemini-direct-agentic", _fn)
```

---

### Option C: Route Through omniproxy bus (simplest, no new code)

Since omniproxy's `bus_core.py` now defaults tools=True and routes to Gemini
(`gemini_cli` backend) via `providers.py`, you can just point the reviewer at
the bus instead of HTTP:

```python
def _register_omniproxy_bus(model: str = "gemini/gemini-2.5-flash"):
    import sys, os, json
    sys.path.insert(0, os.path.expanduser("~/kernclip/bus/sdk/python"))
    from kernclip_bus import Bus

    bus = Bus()

    def _fn(prompt: str, timeout: float) -> str:
        from uuid import uuid4
        reply_topic = f"llm.omni.response.reviewer.{uuid4().hex[:8]}"
        bus.pub("llm.omni.request", json.dumps({
            "prompt": prompt,
            "model": model,
            "reply_to": reply_topic,
            "tools": False,   # reviewer just needs text, no tools on this path
            "session_id": "reviewer",
        }))
        msg = bus.wait(reply_topic, timeout_ms=int(timeout * 1000))
        if not msg:
            raise RuntimeError("reviewer: omniproxy bus timeout")
        data = json.loads(msg.data)
        return data.get("text", "").strip()

    register_reviewer("omniproxy-bus", _fn)
```

Probe: `kc-bus status` exit code 0 + `kc-bus get llm.omni.status` returns ready.

---

## Recommendation

**Start with Option A** (Gemini direct, text-only). It's 30 lines, no new
architecture, handles 95% of reviewer cases — syntax errors, dupes, imports
don't need tool calls to fix. The reviewer's `smart_replace` write path
handles the actual correction.

**Upgrade to Option B** if you find the reviewer is flagging issues it can't
fix without reading more context (rare given the scope-aware `build_context_block`
already provides good context).

**Option C** is attractive if `omni serve --bus` is always running anyway —
zero new code, just a bus pub. Downside: adds a dependency on omniproxy being up.

---

## Files to Touch

| File | Change |
|------|--------|
| `termpipe_mcp/tools/surgical/reviewer.py` | Add `_probe_gemini_sdk()`, `_register_gemini_direct()`, reorder `_get_reviewer()` |
| `pyproject.toml` | Add `google-genai>=1.0.0` to dependencies |

**No other files need changes.** The reviewer API (`pre_commit_gate()`,
`ReviewResult`) is unchanged. All write-path tools (`smart_replace`,
`insert_lines`, `delete_lines`, `patch_line`, `overwrite_lines`) call
`pre_commit_gate()` identically regardless of which backend is registered.

---

## Quick Smoke Test

After implementing:
```bash
cd ~/termpipe-mcp
python3 -c "
from termpipe_mcp.tools.surgical.reviewer import _get_reviewer
r = _get_reviewer()
print('Reviewer:', r)
# Should print: <function _fn at 0x...> registered as gemini-direct
result = r('Is 2+2=4? Reply APPROVED if yes.', 5.0)
print('Response:', result)
# Should print: APPROVED
"
```
