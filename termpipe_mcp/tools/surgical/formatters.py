"""
surgical/formatters.py — indent and unindent tools.
"""

from .helpers import (
    read_file_lines, atomic_write, generate_diff, post_write_review,
)


def register_tools(mcp):

    @mcp.tool()
    def indent(path: str, start_line: int, end_line: int, spaces: int = 4) -> str:
        """Indent a range of lines by N spaces (0-based, end exclusive)."""
        try:
            lines = read_file_lines(path)
            old_copy = lines.copy()
            pad = " " * spaces
            for i in range(start_line, min(end_line, len(lines))):
                lines[i] = pad + lines[i]
            atomic_write(path, lines)
            diff = generate_diff(old_copy, lines)
            out = (f"✅ Indented lines {start_line}–{end_line - 1} by {spaces} spaces\n\n"
                   f"```diff\n{diff}\n```")
            out += post_write_review(path, start_line, end_line)
            return out
        except Exception as e:
            return f"[Error: {e}]"

    @mcp.tool()
    def unindent(path: str, start_line: int, end_line: int, spaces: int = 4) -> str:
        """Remove up to N leading spaces from a range of lines (0-based, end exclusive)."""
        try:
            lines = read_file_lines(path)
            old_copy = lines.copy()
            for i in range(start_line, min(end_line, len(lines))):
                stripped = lines[i].lstrip(' ')
                removed = len(lines[i]) - len(stripped)
                lines[i] = lines[i][min(removed, spaces):]
            atomic_write(path, lines)
            diff = generate_diff(old_copy, lines)
            out = (f"✅ Unindented lines {start_line}–{end_line - 1} by up to {spaces} spaces\n\n"
                   f"```diff\n{diff}\n```")
            out += post_write_review(path, start_line, end_line)
            return out
        except Exception as e:
            return f"[Error: {e}]"
