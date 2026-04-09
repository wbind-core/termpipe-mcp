"""
surgical/writers.py — line-level write tools.

Tool routing guide
------------------
Pick the right tool for the job:

  patch_line(path, line_number, old_text, new_text)
      → Intra-line substring surgery. You know the exact line number AND
        the substring to change within it. Most surgical option.
        Example: fix a typo, change one variable name on a known line.

  overwrite_lines(path, start_line, end_line, content)
      → Swap out a contiguous block of lines with new content. You know
        the line range. Good for replacing a whole function body, block, etc.
        NOTE: end_line is EXCLUSIVE (Python slice semantics: start..end-1).

  insert_lines(path, line_number, content)
      → Insert new lines BEFORE line_number without removing anything.
        NOTE: line numbers are 0-based.

  delete_lines(path, start_line, end_line)
      → Remove lines start_line..end_line-1.
        NOTE: end_line is EXCLUSIVE.

When you don't know the exact line number, prefer smart_replace (replacers.py)
which is content-addressed and idempotent.
"""

from typing import Optional
from .helpers import (
    read_file_lines, atomic_write, generate_diff,
    generate_inline_diff, find_similar_lines,
    line_delta_summary, ai_analyze_error, record_edit,
)
from .reviewer import pre_commit_gate


def register_tools(mcp):

    @mcp.tool()
    def insert_lines(path: str, line_number: int, content: str,
                   dry_run: bool = False) -> str:
        """
        Insert lines BEFORE line_number (0-based).

        Args:
            path:        File to edit.
            line_number: 0-based index. New lines appear BEFORE this line.
                         Use 0 to prepend; use len(file) to append.
            content:     Text to insert. Use '\\n' to insert multiple lines.
            dry_run:     If True, show diff preview without writing. Default: False.
        """
        try:
            lines = read_file_lines(path)
            old_count = len(lines)
            new_lines_in = content.split("\n")
            line_number = max(0, min(line_number, len(lines)))
            old_copy = lines.copy()
            new_lines_list = lines[:line_number] + new_lines_in + lines[line_number:]
            edit_end = line_number + len(new_lines_in)
            rev = pre_commit_gate(path, old_copy, line_number, line_number, "", content)
            if rev.reviewer_wrote:
                note = f"\n🤖 reviewer: {rev.note}" if rev.note else ""
                return f"✅ Inserted {len(new_lines_in)} line(s) before line {line_number} (reviewer corrected){note}"
            if rev.blocked:
                return f"🚫 Write blocked: reviewer identified an error but failed to commit the fix.\n🤖 {rev.note}"
            
            # Dry run - show preview without writing
            if dry_run:
                diff = generate_diff(old_copy, new_lines_list)
                return (f"🔍 Dry run — would insert {len(new_lines_in)} line(s) before line {line_number}\n\n"
                        f"```diff\n{diff}\n```\n\nFile NOT modified.")
            
            atomic_write(path, new_lines_list)
            record_edit(path, "\n".join(old_copy), "\n".join(new_lines_list))
            lines = new_lines_list
            diff = generate_diff(old_copy, lines)
            out = (f"✅ Inserted {len(new_lines_in)} line(s) before line {line_number}\n"
                   f"{line_delta_summary(old_count, len(lines), line_number)}\n\n"
                   f"```diff\n{diff}\n```")
            if rev.note:
                out += f"\n🤖 reviewer: {rev.note}"
            return out
        except Exception as e:
            return f"[Error: {e}]"

    @mcp.tool()
    def delete_lines(path: str, start_line: int, end_line: int,
                    dry_run: bool = False) -> str:
        """
        Delete lines start_line..end_line-1 (0-based, end exclusive).

        Args:
            path:       File to edit.
            start_line: 0-based index of first line to delete (inclusive).
            end_line:   0-based index — deletion stops BEFORE this line (exclusive).
                        Like Python slicing: delete_lines(f, 5, 8) removes lines 5, 6, 7.
            dry_run:   If True, show diff preview without writing. Default: False.
        """
        try:
            lines = read_file_lines(path)
            old_count = len(lines)
            if start_line < 0 or start_line >= old_count:
                return f"[Error: start_line {start_line} out of range (file has {old_count} lines)]"
            deleted = lines[start_line:end_line]
            new_lines_del = lines[:start_line] + lines[end_line:]
            old_text_del = "\n".join(deleted)
            rev = pre_commit_gate(path, lines, start_line, end_line, old_text_del, "")
            if rev.reviewer_wrote:
                note = f"\n🤖 reviewer: {rev.note}" if rev.note else ""
                out = f"✅ Deleted {len(deleted)} line(s) ({start_line}\u2013{end_line - 1}) (reviewer corrected){note}"
                return out
            if rev.blocked:
                return f"🚫 Write blocked: reviewer identified an error but failed to commit the fix.\n🤖 {rev.note}"
            
            # Dry run - show preview without writing
            if dry_run:
                new_lines = lines[:start_line] + lines[end_line:]
                diff = generate_diff(lines, new_lines)
                deleted_preview = "\n".join(f"{i+start_line}: {l}" for i, l in enumerate(deleted))
                return (f"🔍 Dry run — would delete lines {start_line}–{end_line - 1}\n"
                        f"({len(deleted)} line(s))\n\n"
                        f"```diff\n{diff}\n```\n\n"
                        f"🗑️ Would delete:\n{deleted_preview}\n\n"
                        f"File NOT modified.")
            
            lines = new_lines_del
            atomic_write(path, lines)
            record_edit(path, "\n".join(old_copy), "\n".join(lines))
            out = f"✅ Deleted {len(deleted)} line(s) ({start_line}\u2013{end_line - 1})\n"
            out += line_delta_summary(old_count, len(lines), start_line) + "\n\n"
            out += "🗑️ Deleted:\n```\n"
            for i, l in enumerate(deleted, start_line):
                out += f"{i:4d} | {l}\n"
            out += "```"
            return out
        except Exception as e:
            return f"[Error: {e}]"

    @mcp.tool()
    def overwrite_lines(path: str, start_line: int, end_line: int, content: str,
                       dry_run: bool = False) -> str:
        """
        Replace a contiguous block of lines with new content (formerly replace_lines).

        Use this when you know the exact line range to swap out — e.g. replacing a
        function body, a config block, or any multi-line region.

        Prefer smart_replace when you don't know exact line numbers (it's content-
        addressed and idempotent). Prefer patch_line for intra-line substring edits.

        Args:
            path:       File to edit.
            start_line: 0-based index of first line to replace (inclusive).
            end_line:   0-based index — replacement stops BEFORE this line (exclusive).
                        Like Python slicing: overwrite_lines(f, 5, 8, ...) replaces lines 5, 6, 7.
            content:    Replacement text. Use '\\n' for multiple lines.
                        Can expand or contract the block (different line count is fine).
            dry_run:   If True, show diff preview without writing. Default: False.
        """
        try:
            lines = read_file_lines(path)
            old_count = len(lines)
            if start_line < 0 or start_line >= len(lines):
                return f"[Error: start_line {start_line} out of range (file has {old_count} lines)]"
            if end_line < start_line:
                return "[Error: end_line must be >= start_line]"
            new_lines_in = content.split("\n")
            old_copy = lines.copy()
            old_replaced = end_line - start_line
            old_block = "\n".join(lines[start_line:end_line])
            rev = pre_commit_gate(path, old_copy, start_line, end_line, old_block, content)
            if rev.reviewer_wrote:
                note = f"\n🤖 reviewer: {rev.note}" if rev.note else ""
                return (f"✅ Replaced lines {start_line}\u2013{end_line - 1} "
                        f"({old_replaced} \u2192 {len(new_lines_in)} lines) (reviewer corrected){note}")
            if rev.blocked:
                return f"🚫 Write blocked: reviewer identified an error but failed to commit the fix.\n🤖 {rev.note}"
            
            # Dry run - show preview without writing
            if dry_run:
                new_lines = lines[:start_line] + new_lines_in + lines[end_line:]
                diff = generate_diff(old_copy, new_lines)
                return (f"🔍 Dry run — would replace lines {start_line}–{end_line - 1}\n"
                        f"({old_replaced} → {len(new_lines_in)} lines)\n\n"
                        f"```diff\n{diff}\n```\n\nFile NOT modified.")
            
            lines = lines[:start_line] + new_lines_in + lines[end_line:]
            atomic_write(path, lines)
            record_edit(path, "\n".join(old_copy), "\n".join(lines))
            edit_end = start_line + len(new_lines_in)
            diff = generate_diff(old_copy, lines)
            out = (f"✅ Replaced lines {start_line}\u2013{end_line - 1} "
                   f"({old_replaced} \u2192 {len(new_lines_in)} lines)\n"
                   f"{line_delta_summary(old_count, len(lines), start_line)}\n\n"
                   f"```diff\n{diff}\n```")
            return out
        except Exception as e:
            return f"[Error: {e}]"

    @mcp.tool()
    def patch_line(path: str, line_number: int,
                   old_text: str, new_text: str,
                   replace_all: bool = False,
                   dry_run: bool = False) -> str:
        """
        Replace a substring within a single known line (formerly replace_at_line).

        The most surgical writer tool — touches exactly one line and only the
        matching substring within it. Requires knowing the line number.

        Prefer smart_replace when you don't know the line number (it searches
        the whole file). Prefer overwrite_lines to swap out a multi-line block.

        Args:
            path:        File to edit.
            line_number: 0-based line index.
            old_text:    Substring to find within that line.
            new_text:    Replacement substring.
            replace_all: If True, replace all occurrences on the line.
                         Default (False) replaces only the first occurrence.
            dry_run:     If True, show diff preview without writing. Default: False.

        Errors: If old_text is not found on line_number, returns diagnostics
        including similar nearby lines and AI analysis to help locate the right target.
        """
        try:
            lines = read_file_lines(path)
            if line_number < 0 or line_number >= len(lines):
                return (f"[Error: Line {line_number} out of range "
                        f"(file has {len(lines)} lines)]\n"
                        f"💡 Use find_in_file('{path}', '{old_text[:40]}') to locate.")
            line = lines[line_number]
            if old_text not in line:
                error = (f"[Error: Text not found on line {line_number}]\n"
                         f"📍 Line contains: {line}\n🔍 Searched: {old_text}\n")
                matches = [(i, l.strip()[:60]) for i, l in enumerate(lines) if old_text in l]
                if matches:
                    error += "💡 Found on: " + ", ".join(f"line {i}" for i, _ in matches[:5])
                else:
                    similar = find_similar_lines(lines, old_text)
                    if similar:
                        error += "💡 Similar: " + ", ".join(
                            f"line {i} ({s:.0%})" for i, _, s in similar[:3])
                ai = ai_analyze_error("text_not_found", {
                    "searched_for": old_text, "line_number": line_number,
                    "actual_line": line,
                    "char_diff": (generate_inline_diff(old_text, line.strip())
                                  if line.strip() else "N/A"),
                })
                if ai:
                    error += f"\n🤖 {ai}"
                return error
            count = line.count(old_text)
            old_line = line
            new_line = line.replace(old_text, new_text) if (replace_all or count == 1) \
                else line.replace(old_text, new_text, 1)
            rev = pre_commit_gate(path, lines, line_number, line_number + 1, old_line, new_line)
            if rev.reviewer_wrote:
                note = f"\n🤖 reviewer: {rev.note}" if rev.note else ""
                return f"✅ Line {line_number} (reviewer corrected){note}"
            if rev.blocked:
                return f"🚫 Write blocked: reviewer identified an error but failed to commit the fix.\n🤖 {rev.note}"
            
            # Dry run - show preview without writing
            if dry_run:
                new_lines = lines.copy()
                new_lines[line_number] = new_line
                diff = generate_diff(lines, new_lines)
                inline = generate_inline_diff(old_line, new_line)
                return (f"🔍 Dry run — would modify line {line_number}\n\n"
                        f"📐 {inline}\n"
                        f"Before: {old_line.strip()}\n"
                        f"After:  {new_line.strip()}\n\n"
                        f"```diff\n{diff}\n```\n\nFile NOT modified.")
            
            lines[line_number] = new_line
            atomic_write(path, lines)
            record_edit(path, old_line, new_line)
            inline = generate_inline_diff(old_line, new_line)
            note = (f" (replaced {'all ' + str(count) if replace_all and count > 1 else 'first'}"
                    f" of {count} occurrence(s))") if count > 1 else ""
            out = (f"✅ Line {line_number}{note}\n"
                   f"📐 {inline}\n"
                   f"Before: {old_line.strip()}\n"
                   f"After:  {new_line.strip()}")
            return out
        except Exception as e:
            return f"[Error: {e}]"
