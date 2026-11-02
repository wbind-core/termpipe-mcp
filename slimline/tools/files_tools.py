import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional
from mcp.server.fastmcp import FastMCP
from slimline.undo_store import save_edit_for_undo

KB_BIN = "/home/craig/.local/bin/kb"
DEFAULT_LPT = 150
MAX_LPT = 450
BATCH_CAP = 20


def _slug(path: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_")
    return s[:80] or "root"


def _kb_get(topic: str) -> str:
    try:
        r = subprocess.run([KB_BIN, "get", topic],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _kb_pub(topic: str, data: str) -> None:
    try:
        subprocess.run([KB_BIN, "pub", topic, data],
                       capture_output=True, text=True, timeout=5)
    except Exception:
        pass


def _lines_per_turn(lpt: Optional[int]) -> int:
    """Effective lines-per-turn: explicit arg, else kb topic, else 150. Clamped to [1, 450]."""
    if lpt is not None:
        try:
            return max(1, min(MAX_LPT, int(lpt)))
        except Exception:
            pass
    try:
        return max(1, min(MAX_LPT, int(_kb_get("tps.read.lns-per-turn") or DEFAULT_LPT)))
    except Exception:
        return DEFAULT_LPT


def _read_range(path: str, ln_start: Optional[int], ln_end: Optional[int],
                auto_advance: bool, lines_per_turn: Optional[int]) -> str:
    p = Path(path).resolve()
    if not p.exists():
        return f"[Error] File not found: {path}"
    try:
        text = p.read_text(encoding="utf-8")
    except Exception as e:
        return f"[Error] Failed to read file {path}: {e}"
    lines = text.splitlines()
    total = len(lines)
    if total == 0:
        return f"[{path} — empty file]"

    slug = _slug(str(p))
    cursor_topic = f"tps.read.{slug}.ln-end"
    lpt = _lines_per_turn(lines_per_turn)

    if ln_start is None:
        if auto_advance:
            try:
                cursor = int(_kb_get(cursor_topic) or 0)
            except Exception:
                cursor = 0
            ln_start = cursor + 1
        else:
            ln_start = 1
    try:
        ln_start = int(ln_start)
    except Exception:
        ln_start = 1
    if ln_end is None:
        ln_end = ln_start + lpt - 1
    try:
        ln_end = int(ln_end)
    except Exception:
        ln_end = ln_start + lpt - 1

    ln_start = max(1, ln_start)
    if ln_start > total:
        _kb_pub(cursor_topic, "0")
        return (f"[{path} — EOF: file has {total} lines, "
                f"you asked for line {ln_start}. Cursor reset — "
                f"next read starts at line 1.]")
    ln_end = min(ln_end, total)

    _kb_pub(cursor_topic, str(ln_end))
    width = len(str(ln_end))
    numbered = "\n".join(f"{i:>{width}}|{lines[i - 1]}"
                         for i in range(ln_start, ln_end + 1))
    head = f"[{path} — lines {ln_start}-{ln_end} of {total}]"
    tail = ""
    if ln_end < total:
        tail = (f"\n[... {total - ln_end} more lines — call read_file(path) "
                f"to continue, or read_file(path, ln_start, ln_end) for a range]")
    return f"{head}\n{numbered}{tail}"


def _write_one(path: str, content: str) -> str:
    try:
        p = Path(path).resolve()
        old_content = ""
        if p.exists():
            old_content = p.read_text(encoding="utf-8")

        # Save state for undo
        # Note: mcp context doesn't expose a session ID easily in simple tool definitions,
        # so we'll use a fixed identifier or rely on kb session isolation
        session_id = "slimline_session"
        save_edit_for_undo(session_id, old_content, str(p))

        # Ensure directory exists
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

        return f"✅ Successfully wrote to {path}"
    except Exception as e:
        return f"[Error] Failed to write file {path}: {e}"


def register_tools(mcp: FastMCP):
    @mcp.tool()
    def read_file(path: str, ln_start: Optional[int] = None,
                  ln_end: Optional[int] = None, auto_advance: bool = True,
                  lines_per_turn: Optional[int] = None) -> str:
        """
        Read a file with line paging — output is always bounded and labeled,
        never a silent unbounded dump.

        Tip: call read_file(path) with no range and you get lines 1-150.
        Call it again with just the path and you get 151-300, and so on —
        the cursor lives per file on the kb bus and auto-advances. You only
        ever need to specify ln_start/ln_end on the first read (or to jump).

        Args:
            path: Absolute or relative path to the file.
            ln_start: First line to read (1-indexed). If omitted and
                auto_advance is true, continues after the last line
                previously served for this file; otherwise starts at 1.
            ln_end: Last line to read (inclusive). If omitted, reads
                lines_per_turn lines starting at ln_start.
            auto_advance: When true (default) and no range is given, serve
                the next chunk after the cursor. Cursor is tracked per file
                on kb topic tps.read.<file>.ln-end.
            lines_per_turn: Lines per chunk when ln_end is omitted.
                Default 150, maximum 450. The persistent default can be set
                with: kb pub tps.read.lns-per-turn "<n>".
        """
        return _read_range(path, ln_start, ln_end, auto_advance, lines_per_turn)

    @mcp.tool()
    def write_file(path: str, content: str) -> str:
        """
        Write content to a file, completely overwriting it.
        Saves the previous state for undo.

        Args:
            path: Absolute or relative path to the file
            content: The new content to write
        """
        return _write_one(path, content)

    @mcp.tool()
    def batch_read(paths: List[str], lines_per_turn: Optional[int] = None) -> str:
        """
        Read the next auto-advance chunk of each file in paths (max 20).
        Each file advances its own kb cursor, exactly as if you called
        read_file(path) on each one. For an explicit range on a single
        file, use read_file instead.

        Args:
            paths: List of absolute or relative file paths.
            lines_per_turn: Lines per chunk (default 150, max 450).
        """
        if not paths:
            return "[batch_read] no paths given"
        sections = [_read_range(p, None, None, True, lines_per_turn)
                    for p in paths[:BATCH_CAP]]
        return "\n\n".join(sections)

    @mcp.tool()
    def batch_write(writes: List[Dict[str, str]]) -> str:
        """
        Write several files in one call (max 20). Each write saves its
        previous state for undo, exactly like write_file.

        Args:
            writes: List of {"path": ..., "content": ...} objects.
        """
        if not writes:
            return "[batch_write] nothing to write"
        results = []
        for w in writes[:BATCH_CAP]:
            if not isinstance(w, dict) or "path" not in w:
                results.append("[Error] each entry needs a 'path' key")
                continue
            results.append(_write_one(w["path"], w.get("content", "")))
        return "\n".join(results)
