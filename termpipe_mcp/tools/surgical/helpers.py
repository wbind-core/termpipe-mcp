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
import random
import shutil
import subprocess
import tempfile
import threading
import time

import httpx


# ---------------------------------------------------------------------------
# ~/.omniproxy integration — canonical key + model source
# ---------------------------------------------------------------------------

def _load_api_keys() -> dict:
    """Load API keys — ~/.omniproxy/keys.json first, fallback ~/.termpipe-mcp/keys.json"""
    for p in [Path.home() / ".omniproxy" / "keys.json",
              Path.home() / ".termpipe-mcp" / "keys.json"]:
        if p.exists():
            try:
                data = json.loads(p.read_text())
                if data:
                    return data
            except Exception:
                pass
    return {}


def _load_models() -> list:
    """Load models — ~/.omniproxy/models01.json first, fallback ~/.termpipe-mcp/models.json"""
    for p in [Path.home() / ".omniproxy" / "models01.json",
              Path.home() / ".termpipe-mcp" / "models.json"]:
        if p.exists():
            try:
                data = json.loads(p.read_text())
                if data:
                    # Strip provider prefix e.g. "openrouter:qwen/..." -> "qwen/..."
                    return [m.split(":", 1)[1] if ":" in m else m for m in data]
            except Exception:
                pass
    return ["qwen/qwen3-coder:free"]


def _call_openrouter(prompt: str, model: str = None, timeout: float = 30.0) -> Optional[str]:
    """Call OpenRouter directly using ~/.omniproxy/keys.json."""
    keys = _load_api_keys()
    api_key = keys.get("openrouter")
    if not api_key:
        return None
    if not model:
        model = random.choice(_load_models())
    try:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}]}
        with httpx.Client(timeout=timeout) as client:
            resp = client.post("https://openrouter.ai/api/v1/chat/completions",
                               headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[OpenRouter error: {e}]"


def llm_query(prompt: str, model: str = None,
              max_tokens: int = 500, temperature: float = 0.2,
              timeout: int = 30, rotate: bool = True) -> str:
    """Call OpenRouter directly using ~/.omniproxy/keys.json + models01.json."""
    result = _call_openrouter(prompt, model=model, timeout=timeout)
    if result:
        return result
    return "[Error: OpenRouter call failed — check ~/.omniproxy/keys.json]"


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
# Undo support — multi-level edit history
# ---------------------------------------------------------------------------

_edit_stack: list[dict] = []
_stack_lock = threading.Lock()
MAX_HISTORY = 50


def record_edit(path: str, old_content: str, new_content: str) -> None:
    """Record an edit for potential undo. Called by writers after successful writes."""
    with _stack_lock:
        entry = {
            "path": str(Path(path).expanduser().resolve()),
            "old_content": old_content,
            "new_content": new_content,
            "timestamp": time.time(),
            "line_count": len(new_content.split("\n")),
        }
        _edit_stack.append(entry)
        while len(_edit_stack) > MAX_HISTORY:
            _edit_stack.pop(0)


def get_edit_history() -> list[dict]:
    with _stack_lock:
        return list(_edit_stack)


def get_edit_count() -> int:
    with _stack_lock:
        return len(_edit_stack)


def undo_last_edit(n: int = 1) -> str:
    global _edit_stack
    with _stack_lock:
        if not _edit_stack:
            return "[Error] No edits to undo. You haven't made any edits in this session."
        n = min(n, len(_edit_stack))
        edits_to_undo = _edit_stack[-n:]

    oldest_edit = edits_to_undo[0]
    path = oldest_edit["path"]
    p = Path(path)

    if not p.exists():
        return f"[Error] File no longer exists: {path}"

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=p.parent, capture_output=True, text=True,
        )
        if result.returncode != 0 or result.stdout.strip() != "true":
            return f"[Error] File is not in a git repository: {path}"
    except Exception as e:
        return f"[Error] Cannot check git status: {e}"

    with _stack_lock:
        idx = _edit_stack.index(oldest_edit)
        target_old = _edit_stack[idx - 1]["old_content"] if idx > 0 else None

    try:
        if target_old is not None:
            p.write_text(target_old)
        else:
            result = subprocess.run(
                ["git", "checkout", "HEAD", "--", str(p.name)],
                cwd=p.parent, capture_output=True, text=True,
            )
            if result.returncode != 0:
                return f"[Error] Git checkout failed: {result.stderr}"

        with _stack_lock:
            for _ in range(n):
                if _edit_stack:
                    _edit_stack.pop()

        return f"✅ Undo successful: reverted {p.name} by {n} edit(s)\nℹ️  Restored to state before your edits."
    except Exception as e:
        return f"[Error] Undo failed: {e}"


def clear_history() -> str:
    global _edit_stack
    with _stack_lock:
        count = len(_edit_stack)
        _edit_stack.clear()
    return f"✅ Cleared {count} edit(s) from history"


def get_last_edit() -> Optional[dict]:
    with _stack_lock:
        return _edit_stack[-1] if _edit_stack else None
