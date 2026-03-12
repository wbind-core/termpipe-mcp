"""
surgical/reviewer.py — Pre-commit review gate (model-agnostic).

Every write-path tool calls pre_commit_gate() BEFORE atomic_write().
The reviewer gets the proposed change + intelligent context and may:
  - APPROVE  → original write proceeds unchanged
  - CORRECT  → reviewer writes its own corrected version directly to disk
               and sets _review_in_progress so the write-path skips atomic_write

Single-pass rule: if the reviewer commits anything, the path is done.
No re-review. No recursion. _review_in_progress flag enforces this.

Reviewer backends are registered via register_reviewer(). The active
backend is whatever was registered last (or the built-in iflow adapter
if iflow credentials are available and nothing else was registered).

To register a custom backend (e.g. Anthropic, Gemini, local Ollama):

    from termpipe_mcp.tools.surgical.reviewer import register_reviewer

    def my_reviewer(prompt: str, timeout: float) -> str:
        # call your model, return response text
        ...

    register_reviewer("my_model", my_reviewer)
"""

from __future__ import annotations

import ast
import threading
import textwrap
from pathlib import Path
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Single-pass recursion guard
# ---------------------------------------------------------------------------

_tls = threading.local()


def _is_reviewing() -> bool:
    return getattr(_tls, "in_review", False)


def _set_reviewing(v: bool):
    _tls.in_review = v


# ---------------------------------------------------------------------------
# Backend registry
# ---------------------------------------------------------------------------

_backends: dict[str, Callable[[str, float], str]] = {}
_active_backend: Optional[str] = None
_auto_detected: bool = False  # auto-detection runs once, lazily


def register_reviewer(name: str, fn: Callable[[str, float], str]):
    """
    Register a review backend and make it active.

    fn(prompt: str, timeout: float) -> str
      Return the reviewer's response text.
      Raise any exception to signal the reviewer is unavailable (gate skips).

    Priority order for auto-detection (highest to lowest):
      1. CLIProxyAPI (:7599)  — full multi-provider, account rotation
      2. iflow direct (:8421) — iflow FastAPI backend
      3. gemini CLI           — `gemini -p <prompt> -o stream-json`
      4. Nothing              — gate passes through silently
    """
    global _active_backend
    _backends[name] = fn
    _active_backend = name


def _get_reviewer() -> Optional[Callable[[str, float], str]]:
    """Return the active reviewer callable, running auto-detection if needed."""
    global _auto_detected
    if _active_backend and _active_backend in _backends:
        return _backends[_active_backend]
    if not _auto_detected:
        _auto_detected = True
        _auto_detect_backend()
    if _active_backend and _active_backend in _backends:
        return _backends[_active_backend]
    return None


# ---------------------------------------------------------------------------
# Auto-detection chain
# ---------------------------------------------------------------------------

def _probe_http(url: str, timeout: float = 2.0) -> bool:
    """Return True if url responds with HTTP 2xx."""
    try:
        import httpx
        r = httpx.get(url, timeout=timeout)
        return r.status_code < 400
    except Exception:
        return False


def _auto_detect_backend():
    """Defer to bootstrap.maybe_bootstrap() for provider detection."""
    try:
        from termpipe_mcp.bootstrap import maybe_bootstrap
        maybe_bootstrap()
    except Exception:
        # Fallback: inline probe if bootstrap unavailable
        if _probe_http("http://127.0.0.1:7599/health"):
            _register_cliproxy()
            return
        if _probe_http("http://127.0.0.1:8421/health"):
            _register_iflow()
            return
        if _probe_gemini_cli():
            _register_gemini_cli()
            return


def _register_cliproxy(url: str = "http://127.0.0.1:7599", model: str = "auto"):
    """Register CLIProxyAPI as the reviewer backend."""
    import httpx

    def _fn(prompt: str, timeout: float) -> str:
        resp = httpx.post(
            f"{url}/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 600,
                "temperature": 0.0,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    register_reviewer("cliproxy", _fn)


def _register_iflow(model: str = "qwen3-coder-plus"):
    """Register iflow direct as the reviewer backend."""
    from termpipe_mcp.tools.iflow import iflow_query

    def _fn(prompt: str, timeout: float) -> str:
        return iflow_query(
            prompt,
            model=model,
            max_tokens=600,
            temperature=0.0,
            timeout=int(timeout),
        )

    register_reviewer("iflow", _fn)


def _probe_gemini_cli() -> bool:
    """Return True if `gemini` binary is on PATH."""
    import shutil
    return shutil.which("gemini") is not None


def _register_gemini_cli(model: str = "gemini-2.5-flash"):
    """Register gemini CLI subprocess as the reviewer backend."""
    import subprocess
    import json as _json

    def _fn(prompt: str, timeout: float) -> str:
        result = subprocess.run(
            ["gemini", "-p", prompt, "-o", "stream-json", "-m", model],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        # Parse stream-json: find the assistant message
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = _json.loads(line)
                if obj.get("type") == "message" and obj.get("role") == "assistant":
                    content = obj.get("content", "")
                    # content may be a string or list of parts
                    if isinstance(content, list):
                        return "".join(
                            p.get("text", "") for p in content
                            if isinstance(p, dict)
                        ).strip()
                    return str(content).strip()
            except _json.JSONDecodeError:
                continue
        raise RuntimeError(f"gemini CLI gave no assistant message. stdout={result.stdout[:200]}")

    register_reviewer("gemini-cli", _fn)


# ---------------------------------------------------------------------------
# Intelligent context extraction
# ---------------------------------------------------------------------------

def _enclosing_scope_bounds(lines: list[str], edit_start: int, edit_end: int) -> tuple[int, int]:
    """
    For .py content: walk outward from the edit region until we hit a
    top-level def/class boundary or a configurable line cap (60 lines
    each direction). Returns (ctx_start, ctx_end) as line indices.

    For non-Python content: returns a fixed ±40-line window.
    """
    MAX_WALK = 60
    n = len(lines)

    # Try AST-based scope detection on the full file
    try:
        source = "\n".join(lines)
        tree = ast.parse(source)
        # Find the innermost function/class that contains the edit region
        best_start, best_end = 0, n
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                ns = node.lineno - 1          # 0-based
                ne = (node.end_lineno or n)    # 0-based exclusive
                if ns <= edit_start and ne >= edit_end:
                    # Tightest enclosing scope wins
                    if (ne - ns) < (best_end - best_start):
                        best_start, best_end = ns, ne
        # Add a small outer buffer but cap it
        ctx_start = max(0, best_start - 3)
        ctx_end = min(n, best_end + 3)
        return ctx_start, ctx_end
    except SyntaxError:
        pass

    # Fallback: fixed window
    ctx_start = max(0, edit_start - MAX_WALK)
    ctx_end = min(n, edit_end + MAX_WALK)
    return ctx_start, ctx_end


def build_context_block(
    path: str,
    lines: list[str],
    edit_start: int,
    edit_end: int,
    old_text: str,
    new_text: str,
) -> str:
    """
    Build the context block shown to the reviewer.
    Highlights the edit region with >>>/<<< markers.
    """
    ctx_start, ctx_end = _enclosing_scope_bounds(lines, edit_start, edit_end)

    annotated = []
    for i in range(ctx_start, ctx_end):
        if i == edit_start:
            annotated.append(f">>> EDIT START (line {i}) >>>")
        line_marker = "→" if edit_start <= i < edit_end else " "
        annotated.append(f"{line_marker} {i:4d} | {lines[i]}")
        if i == edit_end - 1:
            annotated.append(f"<<< EDIT END (line {i}) <<<")

    return "\n".join(annotated)


# ---------------------------------------------------------------------------
# The prompt
# ---------------------------------------------------------------------------

_REVIEW_PROMPT = """\
You are a pre-commit code reviewer with write access to the filesystem.

FILE: {path}
LANGUAGE: {lang}

PROPOSED CHANGE:
--- REMOVE ---
{old_text}
--- INSERT ---
{new_text}
--- END ---

SURROUNDING CONTEXT (annotated, EDIT START/END markers show the changed region):
```
{context_block}
```

YOUR TASK:
Inspect the proposed change for these issues (ranked by severity):
  1. Syntax errors in the inserted block
  2. Duplicate code — the block (or something semantically equivalent) already
     exists in the surrounding context or elsewhere in the file
  3. Import problems — missing import for a symbol used in new_text, or a
     duplicate import being introduced
  4. Obvious structural errors — mismatched brackets, wrong indentation level

RULES:
  - If you find NO issues → reply with exactly the single word: APPROVED
  - If you find issues → fix them yourself:
      a. Write the corrected file directly using your available shell/file tools
         (you have full write access to {path})
      b. After writing, reply with a brief one-line summary starting with FIXED:
         e.g. "FIXED: removed duplicate import of os on line 4"
  - Do NOT refactor, rename, or change anything beyond the identified issue
  - Do NOT explain at length — one line summary is enough
  - CRITICAL: if you write the file, your version is final. Do not re-review.
"""


# ---------------------------------------------------------------------------
# Public API — called by every write-path tool
# ---------------------------------------------------------------------------

class ReviewResult:
    __slots__ = ("approved", "reviewer_wrote", "note")

    def __init__(self, approved: bool, reviewer_wrote: bool, note: str):
        self.approved = approved          # True → proceed with original write
        self.reviewer_wrote = reviewer_wrote  # True → reviewer already wrote file
        self.note = note                  # Human-readable summary


def pre_commit_gate(
    path: str,
    lines_before: list[str],
    edit_start: int,
    edit_end: int,
    old_text: str,
    new_text: str,
    timeout: float = 8.0,
) -> ReviewResult:
    """
    Run the pre-commit review gate.

    Returns a ReviewResult. The caller must check .reviewer_wrote:
      - True  → reviewer already committed the file; skip atomic_write
      - False → reviewer approved; proceed with original atomic_write
    """
    # Single-pass guard: if we're already inside a review, skip
    if _is_reviewing():
        return ReviewResult(approved=True, reviewer_wrote=False, note="")

    reviewer = _get_reviewer()
    if reviewer is None:
        return ReviewResult(approved=True, reviewer_wrote=False, note="[no reviewer configured]")

    lang = Path(path).suffix.lstrip(".") or "text"
    context_block = build_context_block(
        path, lines_before, edit_start, edit_end, old_text, new_text
    )

    prompt = _REVIEW_PROMPT.format(
        path=path,
        lang=lang,
        old_text=textwrap.indent(old_text[:800], "  "),
        new_text=textwrap.indent(new_text[:800], "  "),
        context_block=context_block,
    )

    _set_reviewing(True)
    try:
        response = reviewer(prompt, timeout)
    except Exception as e:
        return ReviewResult(approved=True, reviewer_wrote=False, note=f"[reviewer error: {e}]")
    finally:
        _set_reviewing(False)

    response = response.strip()

    if response.upper() == "APPROVED":
        return ReviewResult(approved=True, reviewer_wrote=False, note="")

    if response.upper().startswith("FIXED:") or response.upper().startswith("FIXED "):
        return ReviewResult(approved=False, reviewer_wrote=True, note=response)

    # Unexpected response — treat as approved to avoid blocking writes
    return ReviewResult(
        approved=True,
        reviewer_wrote=False,
        note=f"[reviewer gave unexpected response, proceeding: {response[:80]}]",
    )
