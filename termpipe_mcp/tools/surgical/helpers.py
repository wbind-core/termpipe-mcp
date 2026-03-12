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
        from termpipe_mcp.tools.iflow import iflow_query
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
        return iflow_query(prompt, model="qwen3-coder-plus", max_tokens=150, temperature=0.1)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Post-write iflow review — the crown jewel
# ---------------------------------------------------------------------------

_REVIEW_PROMPT = """\
You are a surgical post-write duplicate-detection agent.

An automated edit tool just modified this file:
  FILE: {abs_path}
  EDITED LINES: {ctx_start} – {ctx_end} (0-based, with {ctx} lines of context each side)

Open the file, read it, and inspect that region carefully.

YOUR ONLY JOB: detect and eliminate duplicate blocks introduced by the edit.
Duplicates can be:
  - Exact repeated lines or blocks (consecutive or nearby)
  - A function / class / section that now appears twice in the file
  - Repeated import statements
  - Any block semantically identical to another nearby block

RULES:
  1. If you find duplicates → edit the file directly to remove them. \
Then reply with a brief one-line summary of what you removed.
  2. If the region is clean → reply with exactly: CLEAN
  3. Do NOT refactor, fix bugs, or change anything except true duplicates.
  4. Preserve indentation and surrounding code exactly.
"""

REVIEW_CONTEXT_LINES = 10   # lines of context each side of edit region


def post_write_review(path: str, edit_start: int, edit_end: int) -> str:
    """
    Ask iflow to open the file directly, inspect the edited region,
    and fix any duplicates it finds. Non-fatal — silently skips if
    iflow is unavailable.
    """
    try:
        from termpipe_mcp.tools.iflow import iflow_query
    except ImportError:
        return ""

    try:
        abs_path  = str(Path(path).expanduser().resolve())
        lines     = read_file_lines(path)
        total     = len(lines)
        ctx_start = max(0, edit_start - REVIEW_CONTEXT_LINES)
        ctx_end   = min(total, edit_end + REVIEW_CONTEXT_LINES)

        prompt = _REVIEW_PROMPT.format(
            abs_path=abs_path,
            ctx_start=ctx_start,
            ctx_end=ctx_end,
            ctx=REVIEW_CONTEXT_LINES,
        )

        response = iflow_query(
            prompt,
            model="qwen3-coder-plus",
            max_tokens=400,
            temperature=0.0,
            timeout=3.0,  # non-blocking: don't stall writes if iflow is slow
        ).strip()

        if not response or response.upper() == "CLEAN":
            return ""

        # iflow edited the file itself — just report what it did
        return f"\n🤖 iflow post-write review: {response}"

    except Exception as e:
        return f"\n⚠️  iflow post-write review error (non-fatal): {e}"
