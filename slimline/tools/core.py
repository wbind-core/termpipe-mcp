"""
slimline/tools/core.py — read_file / write_file.

Stripped-down versions of termpipe_mcp's file tools: no workspace_gate,
no record_edit/undo history, no reviewer. Just direct filesystem I/O.
Kept intentionally minimal for a 7b local model — fewer moving parts,
fewer ways to get confused.
"""

from pathlib import Path
from typing import Optional

MAX_READ_CHARS = 50_000


def register_tools(mcp):

    @mcp.tool()
    def read_file(path: str, offset: Optional[int] = None, length: Optional[int] = None) -> str:
        """
        Read contents of a file. Supports partial reads.

        Args:
            path:   File path (supports ~ for home)
            offset: Start line (0-based). Negative = from end
            length: Max lines to read
        """
        try:
            p = Path(path).expanduser()
            if not p.exists():
                return f"[Error: File not found: {path}]"
            if p.is_dir():
                return f"[Error: Path is a directory, not a file: {path}]"

            content = p.read_text()

            if offset is not None:
                lines = content.split("\n")
                off = int(offset)
                if off < 0:
                    off = max(0, len(lines) + off)
                end = len(lines) if length is None else off + int(length)
                content = "\n".join(lines[off:end])

            if len(content) > MAX_READ_CHARS:
                content = content[:MAX_READ_CHARS] + f"\n\n[... truncated, {len(content)} total chars]"

            return content
        except Exception as e:
            return f"[Error: {e}]"

    @mcp.tool()
    def write_file(path: str, content: str) -> str:
        """
        Write content to a file (overwrites, creates parent dirs as needed).

        Args:
            path:    File path (supports ~ for home)
            content: Content to write
        """
        try:
            p = Path(path).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
            return f"✅ Written {len(content)} chars to {path}"
        except Exception as e:
            return f"[Error: {e}]"
