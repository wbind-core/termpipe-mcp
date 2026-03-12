"""
surgical/replacers.py — smart_replace and remove_duplicates.
Both call post_write_review() after committing changes.
"""

from pathlib import Path
from typing import Optional
from .helpers import (
    read_file_lines, atomic_write, generate_diff,
    find_similar_lines, line_delta_summary,
    ai_analyze_error, post_write_review,
)
from .reviewer import pre_commit_gate
import os
import tempfile


def register_tools(mcp):

    @mcp.tool()
    def smart_replace(path: str, old_text: str, new_text: str,
                      expected_line: Optional[int] = None) -> str:
        """
        Find-and-replace with full diagnostics. Supports multi-line spans.
        Idempotent: if old_text absent but new_text already present → returns success.
        Calls iflow post-write review to catch any introduced duplicates.
        """
        try:
            lines = read_file_lines(path)
            content = "\n".join(lines)

            if old_text not in content:
                if new_text in content and new_text != old_text:
                    return ("✅ Already done (old_text not found, new_text already present)\n"
                            "ℹ️  File was NOT modified.")
                error = f"[Error: Text not found]\n🔍 Searched: {old_text[:100]}\n"
                similar = find_similar_lines(lines, old_text.split("\n")[0])
                if similar:
                    error += "💡 Similar:\n" + "\n".join(
                        f"  Line {i} ({s:.0%}): {l.strip()[:60]}" for i, l, s in similar)
                ai = ai_analyze_error("text_not_found", {
                    "searched_for": old_text[:200],
                    "line_number": similar[0][0] if similar else "N/A",
                    "actual_line": similar[0][1] if similar else "none",
                    "char_diff": "N/A",
                })
                if ai:
                    error += f"\n🤖 {ai}"
                return error

            occ_count = content.count(old_text)

            if occ_count > 1:
                occ_lines, search_pos = [], 0
                for _ in range(occ_count):
                    pos = content.find(old_text, search_pos)
                    if pos == -1:
                        break
                    occ_lines.append(content[:pos].count("\n"))
                    search_pos = pos + 1

                if expected_line is not None and expected_line in occ_lines:
                    occ_idx = occ_lines.index(expected_line)
                    search_pos = 0
                    for i in range(occ_idx + 1):
                        pos = content.find(old_text, search_pos)
                        search_pos = pos + 1
                    new_content = content[:pos] + new_text + content[pos + len(old_text):]
                    new_lines = new_content.split("\n")
                    old_count = len(lines)
                    rev = pre_commit_gate(path, lines, expected_line,
                                          expected_line + len(old_text.split("\n")),
                                          old_text, new_text)
                    if rev.reviewer_wrote:
                        note = f"\n🤖 reviewer: {rev.note}" if rev.note else ""
                        return f"✅ Replaced occurrence at line {expected_line} (reviewer corrected){note}"
                    atomic_write(path, new_lines)
                    diff = generate_diff(lines, new_lines)
                    edit_end = expected_line + len(new_text.split("\n"))
                    out = (f"✅ Replaced occurrence at line {expected_line}\n"
                           f"{line_delta_summary(old_count, len(new_lines), expected_line)}\n\n"
                           f"```diff\n{diff}\n```")
                    if rev.note:
                        out += f"\n🤖 reviewer: {rev.note}"
                    out += post_write_review(path, expected_line, edit_end)
                    return out
                else:
                    out = f"[Ambiguous: {occ_count} occurrences on lines: {occ_lines[:10]}]\n"
                    out += "💡 Rerun with expected_line=<N> to target one.\n"
                    ai = ai_analyze_error("ambiguous", {
                        "match_count": occ_count, "match_lines": occ_lines[:10],
                        "searched_for": old_text[:100],
                    })
                    if ai:
                        out += f"🤖 {ai}"
                    return out

            # Unique occurrence
            old_count = len(lines)
            start_line_no = content[:content.find(old_text)].count("\n")
            new_content = content.replace(old_text, new_text, 1)
            new_lines = new_content.split("\n")

            # Verify before atomic write
            verify = new_content
            expected_remaining = new_text.count(old_text) if old_text in new_text else 0
            if old_text not in new_text and old_text in verify:
                return "[Error: Replacement verification failed. File NOT modified.]"
            if verify.count(old_text) != expected_remaining:
                return (f"[Error: Duplicate detection — expected {expected_remaining} "
                        f"remaining occurrences, found {verify.count(old_text)}. "
                        f"File NOT modified.]")

            rev = pre_commit_gate(path, lines, start_line_no,
                                  start_line_no + len(old_text.split("\n")),
                                  old_text, new_text)
            if rev.reviewer_wrote:
                note = f"\n🤖 reviewer: {rev.note}" if rev.note else ""
                return f"✅ Replaced at line {start_line_no} (reviewer corrected){note}"
            atomic_write(path, new_lines)
            edit_end = start_line_no + len(new_text.split("\n"))
            diff = generate_diff(lines, new_lines)
            out = (f"✅ Replaced at line {start_line_no}\n"
                   f"{line_delta_summary(old_count, len(new_lines), start_line_no)}\n\n"
                   f"```diff\n{diff}\n```")
            out += post_write_review(path, start_line_no, edit_end)
            return out

        except Exception as e:
            return f"[Error: {e}]"

    @mcp.tool()
    def remove_duplicates(path: str, start_line: int, end_line: int,
                          notes: Optional[str] = "") -> str:
        """Remove consecutive duplicate lines in range. AI-guided when notes provided."""
        try:
            lines = read_file_lines(path)
            old_count = len(lines)
            if start_line < 0 or start_line >= old_count:
                return "[Error: start_line out of range]"
            prefix, target, suffix = (lines[:start_line],
                                      lines[start_line:end_line],
                                      lines[end_line:])
            if notes:
                try:
                    from termpipe_mcp.tools.iflow import iflow_query
                    prompt = (f"Remove duplicates per instructions: {notes}\n\n"
                              + "\n".join(f"{i + start_line}: {l}"
                                          for i, l in enumerate(target))
                              + "\n\nReturn cleaned lines only, no line numbers.")
                    processed = iflow_query(
                        prompt, model="qwen3-coder-plus",
                        max_tokens=500, temperature=0.1,
                    ).split('\n')
                except Exception:
                    processed = _remove_basic_duplicates(target)
            else:
                processed = _remove_basic_duplicates(target)

            old_copy = lines.copy()
            lines = prefix + processed + suffix
            atomic_write(path, lines)
            removed = len(target) - len(processed)
            diff = generate_diff(old_copy, lines)
            out = (f"✅ Removed {removed} duplicate(s)\n"
                   f"{line_delta_summary(old_count, len(lines), start_line)}\n\n"
                   f"```diff\n{diff}\n```")
            out += post_write_review(path, start_line, start_line + len(processed))
            return out
        except Exception as e:
            return f"[Error: {e}]"


def _remove_basic_duplicates(lines: list[str]) -> list[str]:
    if not lines:
        return lines
    result = [lines[0]]
    for line in lines[1:]:
        if line != result[-1]:
            result.append(line)
    return result
