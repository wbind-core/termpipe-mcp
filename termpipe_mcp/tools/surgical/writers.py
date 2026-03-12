"""
surgical/writers.py — line-level write tools.
Tools: insert_lines, delete_lines, replace_lines, replace_at_line
Every tool calls post_write_review() after committing changes.
"""

from typing import Optional
from .helpers import (
    read_file_lines, atomic_write, generate_diff,
    generate_inline_diff, find_similar_lines,
    line_delta_summary, ai_analyze_error, post_write_review,
)
from .reviewer import pre_commit_gate


def register_tools(mcp):

    @mcp.tool()
    def insert_lines(path: str, line_number: int, content: str) -> str:
        """Insert lines BEFORE line_number (0-based)."""
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
            atomic_write(path, new_lines_list)
            lines = new_lines_list
            diff = generate_diff(old_copy, lines)
            out = (f"✅ Inserted {len(new_lines_in)} line(s) before line {line_number}\n"
                   f"{line_delta_summary(old_count, len(lines), line_number)}\n\n"
                   f"```diff\n{diff}\n```")
            if rev.note:
                out += f"\n🤖 reviewer: {rev.note}"
            out += post_write_review(path, line_number, edit_end)
            return out
        except Exception as e:
            return f"[Error: {e}]"

    @mcp.tool()
    def delete_lines(path: str, start_line: int, end_line: int) -> str:
        """Delete lines start_line..end_line-1 (0-based, end exclusive)."""
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
                out = f"✅ Deleted {len(deleted)} line(s) ({start_line}–{end_line - 1}) (reviewer corrected){note}"
                return out
            lines = new_lines_del
            atomic_write(path, lines)
            out = f"✅ Deleted {len(deleted)} line(s) ({start_line}–{end_line - 1})\n"
            out += line_delta_summary(old_count, len(lines), start_line) + "\n\n"
            out += "🗑️ Deleted:\n```\n"
            for i, l in enumerate(deleted, start_line):
                out += f"{i:4d} | {l}\n"
            out += "```"
            # post-review on the region just above/below deletion point
            out += post_write_review(path, max(0, start_line - 1), start_line + 1)
            return out
        except Exception as e:
            return f"[Error: {e}]"

    @mcp.tool()
    def replace_lines(path: str, start_line: int, end_line: int, content: str) -> str:
        """Replace lines start_line..end_line-1 with content."""
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
                return (f"✅ Replaced lines {start_line}–{end_line - 1} "
                        f"({old_replaced} → {len(new_lines_in)} lines) (reviewer corrected){note}")
            lines = lines[:start_line] + new_lines_in + lines[end_line:]
            atomic_write(path, lines)
            edit_end = start_line + len(new_lines_in)
            diff = generate_diff(old_copy, lines)
            out = (f"✅ Replaced lines {start_line}–{end_line - 1} "
                   f"({old_replaced} → {len(new_lines_in)} lines)\n"
                   f"{line_delta_summary(old_count, len(lines), start_line)}\n\n"
                   f"```diff\n{diff}\n```")
            out += post_write_review(path, start_line, edit_end)
            return out
        except Exception as e:
            return f"[Error: {e}]"

    @mcp.tool()
    def replace_at_line(path: str, line_number: int,
                        old_text: str, new_text: str,
                        replace_all: bool = False) -> str:
        """Replace text within a specific line (0-based). Most surgical tool."""
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
            lines[line_number] = new_line
            atomic_write(path, lines)
            inline = generate_inline_diff(old_line, new_line)
            note = (f" (replaced {'all ' + str(count) if replace_all and count > 1 else 'first'}"
                    f" of {count} occurrence(s))") if count > 1 else ""
            out = (f"✅ Line {line_number}{note}\n"
                   f"📐 {inline}\n"
                   f"Before: {old_line.strip()}\n"
                   f"After:  {new_line.strip()}")
            out += post_write_review(path, line_number, line_number + 1)
            return out
        except Exception as e:
            return f"[Error: {e}]"
