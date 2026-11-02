from pathlib import Path
from typing import Optional
from mcp.server.fastmcp import FastMCP
from slimline.undo_store import save_edit_for_undo, pop_last_edits

def register_tools(mcp: FastMCP):
    @mcp.tool()
    def patch_line(path: str, line_number: int, old_text: str, new_text: str) -> str:
        """
        Replace a specific substring on a single line.
        Saves the previous state for undo.

        Args:
            path: Target file
            line_number: Line number (1-indexed)
            old_text: Exact string to replace on that line
            new_text: New string to replace it with
        """
        try:
            p = Path(path).resolve()
            if not p.exists():
                return f"[Error] File not found: {path}"
            
            lines = p.read_text(encoding='utf-8').splitlines(keepends=True)
            if line_number < 1 or line_number > len(lines):
                return f"[Error] Invalid line number {line_number}. File has {len(lines)} lines."
                
            idx = line_number - 1
            if old_text not in lines[idx]:
                return f"[Error] Target text not found on line {line_number}."
                
            old_content = "".join(lines)
            save_edit_for_undo("slimline_session", old_content, str(p))
            
            lines[idx] = lines[idx].replace(old_text, new_text)
            p.write_text("".join(lines), encoding='utf-8')
            return f"✅ Patched line {line_number} in {path}"
        except Exception as e:
            return f"[Error] Failed to patch line: {e}"

    @mcp.tool()
    def smart_replace(path: str, old_content: str, new_content: str) -> str:
        """
        Find and replace a block of code within the file.
        Saves the previous state for undo.
        
        Args:
            path: Target file
            old_content: The exact block of text to be replaced
            new_content: The new block of text
        """
        try:
            p = Path(path).resolve()
            if not p.exists():
                return f"[Error] File not found: {path}"
            
            current_text = p.read_text(encoding='utf-8')
            if old_content not in current_text:
                return f"[Error] Could not find exact matching block to replace."
                
            save_edit_for_undo("slimline_session", current_text, str(p))
            
            updated_text = current_text.replace(old_content, new_content, 1)
            p.write_text(updated_text, encoding='utf-8')
            return f"✅ Block replaced in {path}"
        except Exception as e:
            return f"[Error] Failed to smart replace: {e}"

    @mcp.tool()
    def undo(n: int = 1) -> str:
        """
        Undo the last N edits made by tools in this session.
        
        Args:
            n: Number of edits to undo (default 1)
        """
        edits = pop_last_edits("slimline_session", n)
        if not edits:
            return "[Error] No edits found to undo."
            
        # edits is a list from oldest to newest of the popped N edits.
        # To undo N edits, we actually just need to restore the oldest edit's old_content
        # since it represents the state before the block of N edits started.
        # Wait, if they are different files, we must restore each file's oldest state.
        
        restored = []
        # Group by file path, grab the oldest (first in list)
        files_to_restore = {}
        for edit in edits:
            path = edit["path"]
            if path not in files_to_restore:
                files_to_restore[path] = edit["old_content"]
                
        for path, old_content in files_to_restore.items():
            try:
                Path(path).write_text(old_content, encoding='utf-8')
                restored.append(path)
            except Exception as e:
                return f"[Error] Failed to restore {path}: {e}"
                
        return f"✅ Undid {len(edits)} edit(s). Restored files: {', '.join(restored)}"
