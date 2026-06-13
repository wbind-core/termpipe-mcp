"""
File operation tools for TermPipe MCP Server.
"""

from pathlib import Path
from typing import Optional
from termpipe_mcp.tools.surgical.helpers import record_edit
from termpipe_mcp.tools.surgical.reviewer import pre_commit_gate
from termpipe_mcp.tools.surgical.workspace_gate import (
    workspace_gate, workspace_gate_consume, workspace_gate_checkpoint,
)


def register_tools(mcp):
    """Register file tools with the MCP server."""
    
    @mcp.tool()
    def read_file(path: str, offset: Optional[float] = None, length: Optional[float] = None) -> str:
        """
        Read contents of a file. Supports partial reads.
        
        Args:
            path: File path (supports ~ for home)
            offset: Start line (0-based). Negative = from end
            length: Max lines to read
        """
        try:
            # Coerce float→int: some MCP clients send JSON numbers as floats
            offset_i: Optional[int] = int(offset) if offset is not None else None
            length_i: Optional[int] = int(length) if length is not None else None

            p = Path(path).expanduser()
            if not p.exists():
                return f"[Error: File not found: {path}]"
            
            content = p.read_text()
            
            if offset_i is not None:
                lines = content.split("\n")
                if offset_i < 0:
                    offset_i = max(0, len(lines) + offset_i)
                end = len(lines) if length_i is None else offset_i + length_i
                content = "\n".join(lines[offset_i:end])
            
            if len(content) > 50000:
                content = content[:50000] + f"\n\n[... truncated, {len(content)} total chars]"
            
            return content
            
        except Exception as e:
            return f"[Error: {str(e)}]"

    @mcp.tool()
    def write_file(path: str, content: str) -> str:
        """
        Write content to a file (overwrites).
        
        Args:
            path: File path (supports ~ for home)
            content: Content to write
        """
        block = workspace_gate(path)
        if block:
            return block
        try:
            p = Path(path).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            old_content = p.read_text() if p.exists() else ""
            p.write_text(content)
            record_edit(str(p), old_content, content)
            workspace_gate_consume(path)
            cp = workspace_gate_checkpoint(path)
            return f"✅ Written {len(content)} chars to {path}{cp}"
        except Exception as e:
            return f"[Error: {str(e)}]"

    @mcp.tool()
    def append_file(path: str, content: str) -> str:
        """
        Append content to a file.
        
        Args:
            path: File path (supports ~ for home)
            content: Content to append
        """
        block = workspace_gate(path)
        if block:
            return block
        try:
            p = Path(path).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            old_content = p.read_text() if p.exists() else ""
            with open(p, "a") as f:
                f.write(content)
            new_content = old_content + content
            record_edit(str(p), old_content, new_content)
            workspace_gate_consume(path)
            cp = workspace_gate_checkpoint(path)
            return f"✅ Appended {len(content)} chars to {path}{cp}"
        except Exception as e:
            return f"[Error: {str(e)}]"

    @mcp.tool()
    def list_directory(path: str) -> str:
        """
        List files and directories in a path.
        
        Args:
            path: Directory path (supports ~ for home)
        """
        try:
            p = Path(path).expanduser()
            if not p.exists():
                return f"[Error: Directory not found: {path}]"
            if not p.is_dir():
                return f"[Error: Not a directory: {path}]"
            
            entries = []
            for item in sorted(p.iterdir()):
                prefix = "[DIR]" if item.is_dir() else "[FILE]"
                entries.append(f"{prefix} {item.name}")
            
            return "\n".join(entries) or "[Empty directory]"
            
        except Exception as e:
            return f"[Error: {str(e)}]"

    @mcp.tool()
    def glob_files(pattern: str, path: str = ".") -> str:
        """
        Find files matching a glob pattern.
        
        Args:
            pattern: Glob pattern (e.g., "*.py", "**/*.json")
            path: Root directory
        """
        try:
            p = Path(path).expanduser()
            matches = list(p.glob(pattern))[:100]
            
            if not matches:
                return f"No files matching '{pattern}'"
            
            result = f"🔍 Found {len(matches)} files matching '{pattern}':\n"
            for m in matches:
                result += f"  {m}\n"
            
            if len(matches) == 100:
                result += "\n   ... (limited to 100 results)"
            
            return result
            
        except Exception as e:
            return f"[Error: {str(e)}]"

    @mcp.tool()
    def search_file_content(path: str, pattern: str, max_results: int = 200) -> str:
        """
        Synchronous grep-like search — returns results immediately in one call.

        USE THIS for most searches. Results are returned directly with no
        session management required.

        Prefer search_file_content when:
          • Searching a single file or a small/medium directory
          • You want results inline without extra tool calls
          • You don't need pagination (up to max_results matches)

        Use start_search instead when:
          • Searching a very large codebase (10k+ files)
          • You need pagination across thousands of results
          • You want ripgrep's advanced filtering (file globs, context lines)

        Args:
            path:        File or directory to search (recursive for directories).
            pattern:     Text to search for (case-insensitive).
            max_results: Stop after this many matches (default 200).
        """
        import re
        
        try:
            p = Path(path).expanduser()
            
            if p.is_file():
                files = [p]
            else:
                files = list(p.rglob("*"))
            
            results = []
            for f in files:
                if not f.is_file():
                    continue
                try:
                    content = f.read_text()
                    for i, line in enumerate(content.split("\n"), 1):
                        if pattern.lower() in line.lower():
                            results.append(f"{f}:{i}: {line.strip()[:100]}")
                            if len(results) >= max_results:
                                break
                except:
                    continue
                
                if len(results) >= max_results:
                    break
            
            if not results:
                return f"No matches found for: {pattern}"
            
            output = f"🔍 Found {len(results)} matches for '{pattern}':\n\n"
            for r in results:
                output += f"{r}\n"
            
            return output
            
        except Exception as e:
            return f"[Error: {str(e)}]"

    @mcp.tool()
    def get_file_info(path: str) -> str:
        """
        Get file metadata (size, modified time, etc).
        
        Args:
            path: File path
        """
        try:
            p = Path(path).expanduser()
            if not p.exists():
                return f"[Error: File not found: {path}]"
            
            stat = p.stat()
            size = stat.st_size
            
            if size > 1024*1024*1024:
                size_str = f"{size / (1024*1024*1024):.2f} GB"
            elif size > 1024*1024:
                size_str = f"{size / (1024*1024):.2f} MB"
            elif size > 1024:
                size_str = f"{size / 1024:.2f} KB"
            else:
                size_str = f"{size} B"
            
            from datetime import datetime
            mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()
            
            info = f"📄 {path}\n"
            info += f"   Size: {size_str}\n"
            info += f"   Modified: {mtime}\n"
            info += f"   Type: {'directory' if p.is_dir() else 'file'}\n"
            
            if p.is_file() and size < 1024*1024:
                try:
                    with open(p) as f:
                        line_count = sum(1 for _ in f)
                    info += f"   Lines: {line_count}\n"
                except:
                    pass
            
            return info
            
        except Exception as e:
            return f"[Error: {str(e)}]"

    @mcp.tool()
    def move_file(source: str, destination: str) -> str:
        """
        Move or rename a file/directory.
        
        Args:
            source: Source path
            destination: Destination path
        """
        block = workspace_gate(source)
        if block:
            return block
        try:
            src = Path(source).expanduser()
            dst = Path(destination).expanduser()

            if not src.exists():
                return f"[Error: Source not found: {source}]"

            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            workspace_gate_consume(source)
            cp = workspace_gate_checkpoint(source)
            return f"✅ Moved {source} → {destination}{cp}"

        except Exception as e:
            return f"[Error: {str(e)}]"

    @mcp.tool()
    def create_directory(path: str) -> str:
        """
        Create a directory (including parents).
        
        Args:
            path: Directory path to create
        """
        try:
            p = Path(path).expanduser()
            p.mkdir(parents=True, exist_ok=True)
            return f"✅ Created directory: {path}"
        except Exception as e:
            return f"[Error: {str(e)}]"


    @mcp.tool()
    def write_batch(files: list, dry_run: bool = False) -> str:
        """
        Write multiple files atomically — all succeed or none do.

        Takes a list of {path, content} dicts and writes them as a single
        unit. If any write fails, every file already written in this batch
        is rolled back to its original state (or deleted if it was new).

        Use this instead of multiple write_file calls when:
          • A refactor touches more than one file
          • You need consistency — partial writes would leave a broken state
          • You want a dry-run pass to validate paths before committing

        Args:
            files:   List of dicts, each with "path" (str) and "content" (str).
            dry_run: If True, validate all paths/permissions without writing.
                     Returns a preview of what would be written.
        """
        # ── Validate input ──────────────────────────────────────────────────
        if not isinstance(files, list) or not files:
            return "[Error: files must be a non-empty list of {path, content} dicts]"

        entries = []
        for i, item in enumerate(files):
            if not isinstance(item, dict):
                return f"[Error: files[{i}] is not a dict — expected {{path, content}}]"
            if "path" not in item or "content" not in item:
                return f"[Error: files[{i}] missing 'path' or 'content' key]"
            p = Path(str(item["path"])).expanduser()
            entries.append((p, str(item["content"])))

        # ── Workspace gate — check on first path (walks up to find workspace) ──
        if not dry_run:
            block = workspace_gate(str(entries[0][0]))
            if block:
                return block

        # ── Dry-run: report what would happen ───────────────────────────────
        if dry_run:
            lines = [f"🔍 Dry-run — {len(entries)} file(s) would be written:\n"]
            for p, content in entries:
                status = "overwrite" if p.exists() else "create"
                lines.append(f"  [{status}] {p}  ({len(content)} chars)")
            return "\n".join(lines)

        # ── Snapshot originals for rollback ─────────────────────────────────
        originals: dict = {}   # path → original bytes, or None if file was new
        for p, _ in entries:
            if p.exists():
                originals[p] = p.read_bytes()
            else:
                originals[p] = None

        # ── Write phase ──────────────────────────────────────────────────────
        written = []
        error_msg = None
        for p, content in entries:
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
                written.append(p)
            except Exception as e:
                error_msg = f"[Error writing {p}: {e}]"
                break

        if error_msg is None:
            for p, content in entries:
                orig = originals.get(p)
                record_edit(str(p), orig.decode("utf-8") if isinstance(orig, bytes) else (orig or ""), content)
            workspace_gate_consume(str(entries[0][0]))
            cp = workspace_gate_checkpoint(str(entries[0][0]))
            summary = f"✅ write_batch: {len(entries)} file(s) written\n"
            for p, content in entries:
                summary += f"   {p}  ({len(content)} chars)\n"
            return summary + cp

        # ── Rollback ─────────────────────────────────────────────────────────
        rollback_errors = []
        for p in written:
            try:
                original = originals.get(p)
                if original is None:
                    p.unlink(missing_ok=True)      # file didn't exist before — delete it
                else:
                    p.write_bytes(original)        # restore prior content
            except Exception as rb_err:
                rollback_errors.append(f"   rollback failed for {p}: {rb_err}")

        result = f"❌ write_batch aborted — {error_msg}\n"
        result += f"   Rolled back {len(written)} already-written file(s).\n"
        if rollback_errors:
            result += "   ⚠️  Rollback errors:\n" + "\n".join(rollback_errors)
        return result
