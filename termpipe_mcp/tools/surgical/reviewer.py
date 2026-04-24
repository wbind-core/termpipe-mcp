"""
surgical/reviewer.py — Pre-commit review gate (model-agnostic).

Every write-path tool calls pre_commit_gate() BEFORE atomic_write().
The reviewer gets the proposed change + intelligent context and may:
  - APPROVE  → original write proceeds unchanged
  - CORRECT  → reviewer writes its own corrected version directly to disk
               and sets reviewer_wrote so the write-path skips atomic_write
  - BLOCKED  → reviewer found an error and claimed FIXED but file was
               unchanged after the attempt (ghost-write). Write is blocked
               entirely — the bad content is NOT committed.

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
    """Register OpenRouter via ~/.omniproxy/keys.json as the reviewer backend."""
    _register_openrouter()


def _register_openrouter(model: str = None):
    """Register OpenRouter as the reviewer backend via ~/.omniproxy/keys.json."""
    import json
    import random
    import httpx
    from pathlib import Path

    def _load_keys():
        for p in [Path.home() / ".omniproxy" / "keys.json",
                  Path.home() / ".termpipe-mcp" / "keys.json",
                  Path.home() / ".termpipe" / "keys.json"]:
            if p.exists():
                try:
                    data = json.loads(p.read_text())
                    if data:
                        return data
                except Exception:
                    pass
        return {}

    def _load_models():
        for p in [Path.home() / ".omniproxy" / "models01.json",
                  Path.home() / ".termpipe-mcp" / "models.json"]:
            if p.exists():
                try:
                    data = json.loads(p.read_text())
                    if data:
                        return [m.split(":", 1)[1] if ":" in m else m for m in data]
                except Exception:
                    pass
        return ["qwen/qwen3-coder:free"]

    keys = _load_keys()
    api_key = keys.get("openrouter", "")
    use_model = model or random.choice(_load_models())

    def _fn(prompt: str, timeout: float) -> str:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": use_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 800,
            "temperature": 0.0,
        }
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()

    register_reviewer("openrouter", _fn)


def _register_groq(model: str = "llama-3.1-8b-instant"):
    """Register Groq as the reviewer backend via HTTP API."""
    import json
    import httpx
    from pathlib import Path

    keys_file = Path.home() / ".termpipe" / "keys.json"
    keys = json.loads(keys_file.read_text())
    api_key = keys.get("groq", "")

    def _fn(prompt: str, timeout: float) -> str:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 800,
            "temperature": 0.0,
        }
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()

    register_reviewer("groq", _fn)




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
You are the final authority in a two-stage agentic coding system. Your role is pre-commit validation with surgical correction authority.
FILE: {path}
LANGUAGE: {lang}
--- PROPOSED CHANGE ---
REMOVED LINES:
{old_text}
ADDED LINES:
{new_text}
--- END ---
SURROUNDING CONTEXT (EDIT START/EDIT END mark the changed region):
{context_block}

YOUR MANDATE:
You have final write authority. When you write, it's final—no review loop.
You MUST evaluate the ADDED LINES for:
1. **Syntax validity** — does the ADDED block, when inserted, create invalid syntax in {lang}?
   - Check bracket/parenthesis/brace matching across the edit boundary
   - Check string literals (unclosed quotes, improper escapes)
   - Check language-specific structures (indentation in Python, semicolons in JS, etc.)
2. **Exact duplicates** — does the ADDED block contain a line or multi-line block that exists *identically* in the SURROUNDING CONTEXT (excluding the REMOVED LINES)?
3. **Import/definition duplicates** — does the ADDED block:
   - Add an import statement for a module already imported in the SURROUNDING CONTEXT?
   - Add a function/class/variable that shadows a definition in the SURROUNDING CONTEXT at the same scope?
4. **Structural integrity** — does the ADDED block break:
   - Indentation consistency with the surrounding code?
   - Block termination (unclosed blocks, missing braces/end statements)?
5. **Hidden errors from the REMOVE block** — if the REMOVED LINES contained errors that the ADDED LINES inherit or interact with, flag these.
DECISION RULES:
**IF NO ISSUES FOUND** → Reply with exactly:
APPROVED
**IF ISSUE(S) FOUND** → You MUST:
   a. Fix the minimal set of lines required to resolve ALL identified issues
   b. Use your file tools to write the correction to {path}
   c. Your correction must modify ONLY the lines introduced by this edit (you may extend correction beyond the exact INSERT lines if the issue spans the edit boundary, but document this)
   d. After writing, reply with exactly one line:
      FIXED: {{brief description of what was fixed}}
**CRITICAL CONSTRAINTS:**
- You are the authority, not a suggester. If you write, your version stands.
- Do NOT refactor. Do NOT improve style. Do NOT optimize.
- Do NOT reject changes for subjective reasons (naming, architecture, preference).
- Do NOT add functionality beyond fixing concrete errors.
- If an issue requires more context than provided → FAIL OPEN: write the fix based on available context, annotate with a comment if needed.
- If you cannot confidently fix (e.g., ambiguous dependency conflict), write a minimal fix that preserves original intent and add a comment: "# FIXME: review needed"
You operate with surgical precision. Your goal is to let correct edits pass and silently correct unambiguous errors—no negotiation, no back-and-forth.

LANGUAGE-SPECIFIC RULES:
- Python: check for mixing tabs/spaces in the ADDED block, verify __future__ imports come first
- JavaScript/TypeScript: check for missing semicolons if they break ASI, verify JSX tag closure
- Go: verify unused imports are NOT added (Go won't compile), check error handling patterns
"""


# ---------------------------------------------------------------------------
# Public API — called by every write-path tool
# ---------------------------------------------------------------------------

class ReviewResult:
    """
    Three mutually-exclusive outcomes from pre_commit_gate():

      reviewer_wrote=True, blocked=False
          → Reviewer identified an error and successfully wrote the corrected
            file to disk. Caller MUST skip atomic_write.

      reviewer_wrote=False, blocked=True
          → Reviewer identified an error and claimed FIXED, but the file was
            unchanged after the attempt (ghost-write). Caller MUST abort the
            write entirely and surface the error to the user.

      reviewer_wrote=False, blocked=False
          → Either APPROVED or no reviewer configured. Caller proceeds with
            the original atomic_write unchanged.
    """
    __slots__ = ("approved", "reviewer_wrote", "blocked", "note")

    def __init__(self, approved: bool, reviewer_wrote: bool, blocked: bool, note: str):
        self.approved = approved
        self.reviewer_wrote = reviewer_wrote  # True → reviewer already wrote file
        self.blocked = blocked                # True → ghost-write detected, abort
        self.note = note                      # Human-readable summary


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

    Returns a ReviewResult. The caller must check in this order:
      1. rev.reviewer_wrote → reviewer already committed; skip atomic_write
      2. rev.blocked        → ghost-write detected; abort and return error to user
      3. otherwise          → proceed with original atomic_write
    """
    # Single-pass guard: if we're already inside a review, skip
    if _is_reviewing():
        return ReviewResult(approved=True, reviewer_wrote=False, blocked=False, note="")

    reviewer = _get_reviewer()
    if reviewer is None:
        return ReviewResult(approved=True, reviewer_wrote=False, blocked=False,
                            note="[no reviewer configured]")

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
        return ReviewResult(approved=True, reviewer_wrote=False, blocked=False,
                            note=f"[reviewer error: {e}]")
    finally:
        _set_reviewing(False)

    response = response.strip()

    if response.upper() == "APPROVED":
        return ReviewResult(approved=True, reviewer_wrote=False, blocked=False, note="")

    if response.upper().startswith("FIXED:") or response.upper().startswith("FIXED "):
        # Ghost-write detection: verify the reviewer actually changed the file.
        #
        # BUG HISTORY: The original comparison used "".join(lines_before) which
        # concatenated lines WITHOUT newline separators, producing a string that
        # could never equal Path(path).read_text() (which has "\n" between lines).
        # The comparison always evaluated False, so ghost-write was never detected
        # and reviewer_wrote=True was returned unconditionally — even when the
        # reviewer's write silently failed and the file was left unchanged.
        #
        # FIX: Use "\n".join(lines_before) to reconstruct the pre-edit file
        # content with proper newline separators, matching what atomic_write
        # produces and what read_text() returns.
        try:
            current = Path(path).read_text()
            original = "\n".join(lines_before)  # FIX: was "".join() — wrong, no newlines
            if current.strip() == original.strip():
                # Reviewer claimed FIXED but file is byte-for-byte identical to
                # the pre-edit content. The write never happened.
                # BLOCK the write — do NOT fall through to the original bad content.
                return ReviewResult(
                    approved=False,
                    reviewer_wrote=False,
                    blocked=True,
                    note=(
                        f"[reviewer ghost-write: claimed FIXED but file is unchanged. "
                        f"Write BLOCKED to prevent committing unreviewed content. "
                        f"Reviewer said: {response[:120]}]"
                    ),
                )
        except Exception:
            # If we can't read the file at all, trust the reviewer rather than
            # blocking a potentially valid write.
            pass

        # File is different from lines_before — reviewer successfully wrote.
        return ReviewResult(approved=False, reviewer_wrote=True, blocked=False, note=response)

    # Unexpected response — treat as approved to avoid blocking writes
    return ReviewResult(
        approved=True,
        reviewer_wrote=False,
        blocked=False,
        note=f"[reviewer gave unexpected response, proceeding: {response[:80]}]",
    )
