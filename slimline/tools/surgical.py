"""
slimline/tools/surgical.py — smart_replace / patch_line / undo.

Simplified surgical editors plus a lightweight in-memory undo stack.
No reviewer gate, no workspace gate, no diff rendering, no AI-assisted
"similar line" suggestions. Just: find text, replace text, report
success/fail plainly. Leanest possible surface for a 7b local model to
reason about.

Undo model: a single process-lifetime stack of (path, previous_content)
snapshots, pushed by smart_replace/patch_line before they write. undo()
pops the most recent snapshot and restores it. Not persisted across
server restarts — intentionally simple.
"""

from pathlib import Path
from typing import Optional

_UNDO_STACK: list[tuple[str, str]] = []
_UNDO_STACK_MAX = 50


def _read_lines(path: str) -> list[str]:
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return p.read_text().split("\n")


def _atomic_write(path: str, lines: list[str]) -> None:
    p = Path(path).expanduser()
    p.write_text("\n".join(lines))


def _push_undo(path: str, previous_content: str) -> None:
    _UNDO_STACK.append((str(Path(path).expanduser()), previous_content))
    if len(_UNDO_STACK) > _UNDO_STACK_MAX:
        _UNDO_STACK.pop(0)


def register_tools(mcp):

    @mcp.tool()
    def smart_replace(path: str, old_text: str, new_text: str,
                       expected_line: Optional[int] = None) -> str:
        """
        Content-addressed find-and-replace. Finds old_text anywhere in the
        file (single or multi-line spans) and replaces it. Idempotent: if
        old_text is absent but new_text is already present, reports success
        without modifying the file.

        Args:
            path:          File to edit.
            old_text:      Text to find. Can span multiple lines.
            new_text:      Replacement text.
            expected_line: If old_text appears more than once, target the
                           occurrence starting at this 0-based line number.
                           Omit to auto-resolve (errors if ambiguous).
        """
        try:
            lines = _read_lines(path)
            content = "\n".join(lines)

            if old_text not in content:
                if new_text and new_text in content:
                    return "✅ Already done (old_text not found, new_text already present). File not modified."
                return f"[Error: text not found in {path}]"

            occ_count = content.count(old_text)

            if occ_count > 1:
                if expected_line is None:
                    occ_lines, pos = [], 0
                    for _ in range(occ_count):
                        idx = content.find(old_text, pos)
                        if idx == -1:
                            break
                        occ_lines.append(content[:idx].count("\n"))
                        pos = idx + 1
                    return (f"[Error: {occ_count} occurrences found on lines {occ_lines[:10]}. "
                            f"Rerun with expected_line=<N> to target one.]")
                pos = 0
                target_pos = None
                for _ in range(occ_count):
                    idx = content.find(old_text, pos)
                    if idx == -1:
                        break
                    if content[:idx].count("\n") == expected_line:
                        target_pos = idx
                        break
                    pos = idx + 1
                if target_pos is None:
                    return f"[Error: no occurrence of old_text starts at line {expected_line}]"
                _push_undo(path, content)
                new_content = content[:target_pos] + new_text + content[target_pos + len(old_text):]
                _atomic_write(path, new_content.split("\n"))
                return f"✅ Replaced occurrence at line {expected_line} in {path}"

            # Unique occurrence
            _push_undo(path, content)
            new_content = content.replace(old_text, new_text, 1)
            _atomic_write(path, new_content.split("\n"))
            return f"✅ Replaced in {path}"

        except Exception as e:
            return f"[Error: {e}]"

    @mcp.tool()
    def patch_line(path: str, line_number: int, old_text: str, new_text: str,
                    replace_all: bool = False) -> str:
        """
        Replace a substring within a single known line (0-based).

        Args:
            path:        File to edit.
            line_number: 0-based line index.
            old_text:    Substring to find within that line.
            new_text:    Replacement substring.
            replace_all: If True, replace all occurrences on the line.
                         Default (False) replaces only the first.
        """
        try:
            lines = _read_lines(path)
            if line_number < 0 or line_number >= len(lines):
                return f"[Error: line {line_number} out of range ({len(lines)} lines in file)]"

            line = lines[line_number]
            if old_text not in line:
                return f"[Error: text not found on line {line_number}. Line contains: {line.strip()[:100]}]"

            _push_undo(path, "\n".join(lines))

            count = line.count(old_text)
            new_line = line.replace(old_text, new_text) if (replace_all or count == 1) \
                else line.replace(old_text, new_text, 1)
            lines[line_number] = new_line
            _atomic_write(path, lines)
            return f"✅ Line {line_number} patched in {path}"

        except Exception as e:
            return f"[Error: {e}]"

    @mcp.tool()
    def undo() -> str:
        """
        Undo the most recent smart_replace or patch_line edit, restoring
        the file to its content before that edit. Single-level-per-call;
        call again to keep popping further back. Stack is in-memory only
        (cleared on server restart).
        """
        if not _UNDO_STACK:
            return "[Error: nothing to undo]"
        path, previous_content = _UNDO_STACK.pop()
        try:
            Path(path).write_text(previous_content)
            return f"✅ Undid last edit to {path}"
        except Exception as e:
            return f"[Error restoring {path}: {e}]"
