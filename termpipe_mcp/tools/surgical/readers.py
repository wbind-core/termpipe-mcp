"""
surgical/readers.py — read-only surgical tools.
Tools: read_lines, find_in_file, read_multiple_files
"""

from pathlib import Path
from typing import Optional
from .helpers import read_file_lines, find_similar_lines


def register_tools(mcp):

    @mcp.tool()
    def read_lines(path: str, start_line: int, end_line: Optional[int] = None) -> str:
        """Read specific line range from a file (0-based)."""
        try:
            lines = read_file_lines(path)
            if end_line is None:
                end_line = start_line + 1
            if start_line < 0 or start_line >= len(lines):
                return f"[Error: Line {start_line} out of range (file has {len(lines)} lines)]"
            output = f"Lines {start_line}-{min(end_line, len(lines))-1} of {path} (total: {len(lines)}):\n\n"
            for i, line in enumerate(lines[start_line:end_line], start_line):
                output += f"{i:4d} | {line}\n"
            return output
        except Exception as e:
            return f"[Error: {e}]"

    @mcp.tool()
    def find_in_file(path: str, pattern: str,
                     max_matches: int = 50, context: int = 0) -> str:
        """Find pattern in file with line numbers and optional context lines."""
        try:
            lines = read_file_lines(path)
            matches = [i for i, l in enumerate(lines)
                       if pattern.lower() in l.lower()][:max_matches]
            if not matches:
                similar = find_similar_lines(lines, pattern)
                if similar:
                    return (f"No exact matches for '{pattern}'\n💡 Similar:\n"
                            + "\n".join(
                                f"  Line {i} ({s:.0%}): {l.strip()[:60]}"
                                for i, l, s in similar))
                return f"No matches for: {pattern}"
            out = f"Found {len(matches)} match(es) for '{pattern}' (file: {len(lines)} lines):\n\n"
            for m in matches:
                if context > 0:
                    s, e = max(0, m - context), min(len(lines), m + context + 1)
                    out += f"--- Line {m} ---\n"
                    for i in range(s, e):
                        out += f"{'→' if i == m else ' '} {i:4d} | {lines[i]}\n"
                    out += "\n"
                else:
                    out += f"Line {m}: {lines[m].strip()[:80]}\n"
            return out
        except Exception as e:
            return f"[Error: {e}]"

    @mcp.tool()
    def read_multiple_files(paths: list[str]) -> str:
        """Read contents of multiple files at once."""
        results = []
        for path in paths:
            p = Path(path).expanduser()
            try:
                if p.suffix.lower() in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp']:
                    import base64
                    b64 = base64.b64encode(p.read_bytes()).decode()
                    results.append(f"=== {path} ===\n[Image: {p.suffix} ({len(b64)} bytes)]\n")
                else:
                    results.append(f"=== {path} ===\n{p.read_text()}\n")
            except Exception as e:
                results.append(f"=== {path} ===\n[Error: {e}]\n")
        return "\n".join(results)
