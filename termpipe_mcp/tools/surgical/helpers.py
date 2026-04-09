"""
surgical/helpers.py — shared utilities for all surgical editing tools.
Includes: file I/O, diff generation, fuzzy matching, line-delta summary,
          AI error analysis, atomic write, and post-write iflow review.
"""

from pathlib import Path
from typing import Optional, Tuple
import difflib
import os
import tempfile

OMNIPROXY_URL = os.environ.get("OMNIPROXY_URL", "http://127.0.0.1:8743")


def omniproxy_query(prompt: str, model: str = "qwen3-coder-plus",
                    max_tokens: int = 500, temperature: float = 0.2,
                    timeout: int = 30) -> str:
    """Send a completion request through omniproxy. Never calls iflow directly."""
    import httpx
    try:
        resp = httpx.post(
            f"{OMNIPROXY_URL}/v1/chat/completions",
            json={
                "model": model,
                "provider": "auto",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[Error: {e}]"


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
# AI error analysis (iflow)
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
        return omniproxy_query(prompt, model="qwen3-coder-plus", max_tokens=150, temperature=0.1)
    except Exception:
        return ""


