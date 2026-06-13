"""
surgical/helpers.py — shared utilities for all surgical editing tools.
Includes: file I/O, diff generation, fuzzy matching, line-delta summary,
          AI error analysis, atomic write, and post-write iflow review.
"""

from pathlib import Path
from typing import Optional, Tuple
import difflib
import json
import os

import shutil
import tempfile
import threading

import httpx


# ---------------------------------------------------------------------------
# LLM query — always routes to omniproxy local (port 9916)
# ---------------------------------------------------------------------------

_OMNI_URL = "http://127.0.0.1:9920/v1/chat/completions"


def llm_query(prompt: str, model: str = None,
              max_tokens: int = 500, temperature: float = 0.2,
              timeout: int = 30, rotate: bool = True) -> str:
    """Query omniproxy local endpoint at 9916."""
    payload = {
        "model": "",
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(_OMNI_URL, json=payload)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return "[Error: omniproxy not available — run 'omni serve --local']"
    except Exception as e:
        return f"[Error: {type(e).__name__}: {e}]"


def omniproxy_query(prompt: str, model: str = None,
                    max_tokens: int = 500, temperature: float = 0.2,
                    timeout: int = 30) -> str:
    """Legacy alias for llm_query()."""
    return llm_query(prompt, model=model, timeout=timeout)

_llm_lock = threading.Lock()


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def read_file_lines(path: str) -> list[str]:
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return p.read_text().split("\n")


def write_file_lines(path: str, lines: list[str]) -> None:
    Path(path).expanduser().write_text("\n".join(lines))


def atomic_write(path: str, lines: list[str]) -> None:
    """Write lines to path atomically via temp file + os.replace."""
    p = Path(path).expanduser()
    tmp_fd, tmp_path = tempfile.mkstemp(dir=p.parent, prefix=".surgical_")
    try:
        with os.fdopen(tmp_fd, 'w') as f:
            f.write("\n".join(lines))
        os.replace(tmp_path, p)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Diff helpers
# ---------------------------------------------------------------------------

def generate_diff(old_lines: list[str], new_lines: list[str], context: int = 3) -> str:
    diff = difflib.unified_diff(old_lines, new_lines,
                                fromfile='before', tofile='after',
                                lineterm='', n=context)
    return '\n'.join(diff)


def generate_inline_diff(old: str, new: str) -> str:
    matcher = difflib.SequenceMatcher(None, old, new)
    result = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == 'equal':
            result.append(old[i1:i2])
        elif op == 'replace':
            result.append(f'{{-{old[i1:i2]}-}}{{+{new[j1:j2]}+}}')
        elif op == 'delete':
            result.append(f'{{-{old[i1:i2]}-}}')
        elif op == 'insert':
            result.append(f'{{+{new[j1:j2]}+}}')
    return ''.join(result)


# ---------------------------------------------------------------------------
# Fuzzy matching
# ---------------------------------------------------------------------------

def find_similar_lines(lines: list[str], target: str,
                       threshold: float = 0.6) -> list[Tuple[int, str, float]]:
    results = []
    target_lower = target.lower().strip()
    for i, line in enumerate(lines):
        line_lower = line.lower().strip()
        if not line_lower:
            continue
        if target_lower in line_lower or line_lower in target_lower:
            results.append((i, line, 0.9))
            continue
        ratio = difflib.SequenceMatcher(None, target_lower, line_lower).ratio()
        if ratio >= threshold:
            results.append((i, line, ratio))
    return sorted(results, key=lambda x: -x[2])[:5]


# ---------------------------------------------------------------------------
# Line-delta summary
# ---------------------------------------------------------------------------

def line_delta_summary(old_count: int, new_count: int, edit_start: int) -> str:
    delta = new_count - old_count
    sign = f"+{delta}" if delta >= 0 else str(delta)
    msg = f"\n📊 File: {old_count} → {new_count} lines (delta: {sign})"
    if delta != 0:
        msg += f"\n⚠️  Line numbers from line {edit_start} onward shifted by {sign}"
    return msg


# ---------------------------------------------------------------------------
# AI error analysis
# ---------------------------------------------------------------------------

def ai_analyze_error(error_type: str, context: dict) -> str:
    try:
        prompt = f"Code editing error analyst. Error: {error_type}\n"
        if error_type == "text_not_found":
            prompt += (f"Searched for:\n{context.get('searched_for', '')}\n"
                       f"Line {context.get('line_number', '?')} contains:\n"
                       f"{context.get('actual_line', '')}\n"
                       f"Char diff: {context.get('char_diff', 'N/A')}\n")
        elif error_type == "ambiguous":
            prompt += (f"Text appears {context.get('match_count', 0)} times. "
                       f"Lines: {context.get('match_lines', [])}. "
                       f"Text: {context.get('searched_for', '')[:100]}\n")
        prompt += "\nRespond:\n❌ PROBLEM: [one sentence]\n✅ FIX: [one sentence]"
        return omniproxy_query(prompt, max_tokens=150)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Undo support — backed by telemetry.db edit_history
# ---------------------------------------------------------------------------

def record_edit(path: str, old_content: str, new_content: str, cwd: Optional[str] = None) -> None:
    """Record an edit for potential undo. Called by writers after successful writes."""
    import traceback as _tb
    from termpipe_mcp.telemetry import record_edit_to_db, _get_session_id
    frame = _tb.extract_stack()
    tool_name = "unknown"
    for f in reversed(frame):
        if f.name not in ("record_edit", "<module>") and not f.name.startswith("_"):
            tool_name = f.name
            break
    record_edit_to_db(
        tool_name=tool_name,
        path=path,
        old_content=old_content,
        new_content=new_content,
        cwd=cwd or os.getcwd(),
    )


def get_edit_history() -> list[dict]:
    from termpipe_mcp.telemetry import get_edit_history_db, _get_session_id
    return get_edit_history_db(_get_session_id())


def get_edit_count() -> int:
    from termpipe_mcp.telemetry import get_edit_history_db, _get_session_id
    rows = get_edit_history_db(_get_session_id(), limit=1000)
    return len(rows)


def undo_last_edit(n: int = 1) -> str:
    from termpipe_mcp.telemetry import get_undo_edits, _get_session_id
    session_id = _get_session_id()
    edits = get_undo_edits(session_id, n)
    if not edits:
        return "[Error] No edits to undo in this session."

    # The oldest of the N edits holds the content we want to restore to
    oldest = edits[-1]
    path = oldest["path"]
    p = Path(path)

    if not p.exists():
        return f"[Error] File no longer exists: {path}"

    try:
        p.write_text(oldest["old_content"])
        return f"✅ Undo successful: reverted {p.name} by {n} edit(s)\nℹ️  Restored to state before edit #{oldest['id']}."
    except Exception as e:
        return f"[Error] Undo failed: {e}"


def clear_history() -> str:
    rows = get_edit_history_db(_get_session_id(), limit=1000)
    return f"✅ {len(rows)} edit(s) in session history (DB-backed; use SQL to purge if needed)"


def get_last_edit() -> Optional[dict]:
    edits = get_undo_edits(_get_session_id(), 1)
    return edits[0] if edits else None
