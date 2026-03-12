"""
File operation tools for TermPipe MCP Server.
"""

from pathlib import Path
from typing import Optional
from termpipe_mcp.tools.surgical.reviewer import pre_commit_gate


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
        try:
            p = Path(path).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
            return f"✅ Written {len(content)} chars to {path}"
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
        try:
            p = Path(path).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a") as f:
                f.write(content)
            return f"✅ Appended {len(content)} chars to {path}"
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
        Search for pattern in file contents (grep-like).
        
        Args:
            path: File or directory path
            pattern: Text pattern to search
            max_results: Maximum number of results
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
        try:
            src = Path(source).expanduser()
            dst = Path(destination).expanduser()
            
            if not src.exists():
                return f"[Error: Source not found: {source}]"
            
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            
            return f"✅ Moved {source} → {destination}"
            
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
