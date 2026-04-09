"""
surgical/replacers.py — content-addressed replace tools.

Tool routing guide
------------------
  smart_replace(path, old_text, new_text)
      → Best default for most edits. Finds old_text anywhere in the file
        (single or multi-line spans), replaces it, and is idempotent. Does not
        require knowing line numbers. Use dry_run=True to preview changes
        without writing.

        When to prefer something else:
          - You know the exact line number and need intra-line surgery
            → use patch_line (writers.py)
          - You know the exact line range to overwrite
            → use overwrite_lines (writers.py)
          - You need to replace across many files in a directory
            → use start_search with a replace_with param (search.py) [TODO]

  remove_duplicates(path, start_line, end_line)
      → Remove consecutive duplicate lines in a range. Pass notes= for
        AI-guided dedup (e.g. "keep the version with the type annotation").

For single-file search without replacement, prefer find_in_file (readers.py)
over search_file_content (files.py) — find_in_file supports context lines
and fuzzy matching.
"""

from pathlib import Path
from typing import Optional
from .helpers import (
    read_file_lines, atomic_write, generate_diff,
    find_similar_lines, line_delta_summary,
    ai_analyze_error, undo_last_edit, get_last_edit,
    get_edit_history, get_edit_count, record_edit,
)
from .reviewer import pre_commit_gate
import os
import tempfile


def register_tools(mcp):

    @mcp.tool()
    def smart_replace(path: str, old_text: str, new_text: str,
                      expected_line: Optional[int] = None,
                      dry_run: bool = False) -> str:
        """
        Content-addressed find-and-replace with full diagnostics.

        Searches the entire file for old_text (single or multi-line spans),
        replaces it with new_text, and writes atomically. Idempotent: if
        old_text is absent but new_text is already present, returns success
        without modifying the file.

        This is the recommended default replace tool when you don't know
        the exact line number. For line-number-based edits, see overwrite_lines
        and patch_line in writers.py.

        Args:
            path:          File to edit.
            old_text:      Text to find. Can span multiple lines.
            new_text:      Replacement text.
            expected_line: If old_text appears more than once, target the
                           occurrence starting at this 0-based line number.
                           Omit to let the tool auto-resolve (errors if ambiguous).
            dry_run:       If True, show what would change without writing the file.
                           Returns a diff preview. Default: False.
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
                    if dry_run:
                        diff = generate_diff(lines, new_lines)
                        return (f"🔍 Dry run — occurrence at line {expected_line} would be replaced\n\n"
                                f"```diff\n{diff}\n```\n\nFile NOT modified.")
                    rev = pre_commit_gate(path, lines, expected_line,
                                          expected_line + len(old_text.split("\n")),
                                          old_text, new_text)
                    if rev.reviewer_wrote:
                        note = f"\n🤖 reviewer: {rev.note}" if rev.note else ""
                        return f"✅ Replaced occurrence at line {expected_line} (reviewer corrected){note}"
                    if rev.blocked:
                        return f"🚫 Write blocked: reviewer identified an error but failed to commit the fix.\n🤖 {rev.note}"
                    atomic_write(path, new_lines)
                    record_edit(path, "\n".join(lines), "\n".join(new_lines))
                    diff = generate_diff(lines, new_lines)
                    edit_end = expected_line + len(new_text.split("\n"))
                    out = (f"✅ Replaced occurrence at line {expected_line}\n"
                           f"{line_delta_summary(old_count, len(new_lines), expected_line)}\n\n"
                           f"```diff\n{diff}\n```")
                    if rev.note:
                        out += f"\n🤖 reviewer: {rev.note}"
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

            # Verify before write
            verify = new_content
            expected_remaining = new_text.count(old_text) if old_text in new_text else 0
            if old_text not in new_text and old_text in verify:
                return "[Error: Replacement verification failed. File NOT modified.]"
            if verify.count(old_text) != expected_remaining:
                return (f"[Error: Duplicate detection \u2014 expected {expected_remaining} "
                        f"remaining occurrences, found {verify.count(old_text)}. "
                        f"File NOT modified.]")

            if dry_run:
                diff = generate_diff(lines, new_lines)
                return (f"🔍 Dry run — would replace at line {start_line_no}\n\n"
                        f"```diff\n{diff}\n```\n\nFile NOT modified.")

            rev = pre_commit_gate(path, lines, start_line_no,
                                  start_line_no + len(old_text.split("\n")),
                                  old_text, new_text)
            if rev.reviewer_wrote:
                note = f"\n🤖 reviewer: {rev.note}" if rev.note else ""
                return f"✅ Replaced at line {start_line_no} (reviewer corrected){note}"
            if rev.blocked:
                return f"🚫 Write blocked: reviewer identified an error but failed to commit the fix.\n🤖 {rev.note}"
            atomic_write(path, new_lines)
            record_edit(path, "\n".join(lines), "\n".join(new_lines))
            edit_end = start_line_no + len(new_text.split("\n"))
            diff = generate_diff(lines, new_lines)
            out = (f"✅ Replaced at line {start_line_no}\n"
                   f"{line_delta_summary(old_count, len(new_lines), start_line_no)}\n\n"
                   f"```diff\n{diff}\n```")
            return out

        except Exception as e:
            return f"[Error: {e}]"

    @mcp.tool()
    def remove_duplicates(path: str, start_line: int, end_line: int,
                          notes: Optional[str] = "") -> str:
        """
        Remove consecutive duplicate lines in a range.

        Args:
            path:       File to edit.
            start_line: 0-based start of range (inclusive).
            end_line:   0-based end of range (exclusive).
            notes:      Optional natural language instructions for AI-guided dedup.
                        Example: "keep the version with the type annotation".
                        When omitted, removes strict consecutive duplicates only.
        """
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
                    from termpipe_mcp.tools.surgical.helpers import omniproxy_query
                    prompt = (f"Remove duplicates per instructions: {notes}\n\n"
                              + "\n".join(f"{i + start_line}: {l}"
                                          for i, l in enumerate(target))
                              + "\n\nReturn cleaned lines only, no line numbers.")
                    processed = omniproxy_query(
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
            record_edit(path, "\n".join(old_copy), "\n".join(lines))
            removed = len(target) - len(processed)
            diff = generate_diff(old_copy, lines)
            out = (f"✅ Removed {removed} duplicate(s)\n"
                   f"{line_delta_summary(old_count, len(lines), start_line)}\n\n"
                   f"```diff\n{diff}\n```")
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



    @mcp.tool()
    def undo(n: int = 1) -> str:
        """
        Undo the last N edits.
        
        By default undoes the last edit. Use n=N to undo N edits.
        Uses git to restore file to state before your edits.
        
        Args:
            n: Number of edits to undo (default: 1)
        """
        return undo_last_edit(n=n)

    @mcp.tool()
    def history() -> str:
        """
        Show edit history for this session.
        
        Returns the list of edits made in this session with timestamps.
        """
        import time
        
        count = get_edit_count()
        if count == 0:
            return "No edits in session history."
        
        edits = get_edit_history()
        lines = [f"📜 Edit History ({count} edits):"]
        for i, e in enumerate(reversed(edits), 1):
            ts = time.strftime("%H:%M:%S", time.localtime(e.get("timestamp", 0)))
            lines.append(f"  {i}. {e['path'].split('/')[-1]} @ {ts} ({e.get('line_count', '?')} lines)")
        
        return "\n".join(lines)

