"""
Search tools for TermPipe MCP Server.
"""

import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional

_HAS_RG = shutil.which("rg") is not None

# Active searches storage — max 50 entries, 1-hour TTL
_active_searches = {}
_SEARCH_TTL_SECS = 3600
_SEARCH_MAX = 50


def _evict_searches():
    """Remove expired and excess searches."""
    import time
    now = time.time()
    expired = [k for k, v in _active_searches.items()
               if now - v.get("created_at", now) > _SEARCH_TTL_SECS]
    for k in expired:
        del _active_searches[k]
    # Trim to max if still over
    while len(_active_searches) >= _SEARCH_MAX:
        oldest = min(_active_searches, key=lambda k: _active_searches[k].get("created_at", 0))
        del _active_searches[oldest]


def register_tools(mcp):
    """Register search tools with the MCP server."""
    
    @mcp.tool()
    def start_search(
        pattern: str,
        path: str = ".",
        searchType: str = "content",
        filePattern: Optional[str] = None,
        ignoreCase: bool = True,
        literalSearch: bool = False,
        maxResults: int = 100,
        contextLines: int = 0,
        timeout_ms: int = 30000
    ) -> str:
        """
        Start a streaming search.
        
        Args:
            pattern: What to search for
            path: Root directory
            searchType: "files" or "content"
            filePattern: Filter to specific file types
            ignoreCase: Case-insensitive search
            literalSearch: Exact string matching
            maxResults: Maximum results
            contextLines: Lines of context around matches
            timeout_ms: Timeout in milliseconds
        """
        search_id = f"search_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        
        try:
            p = Path(path).expanduser()
            if not p.exists():
                return f"[Error: Path not found: {path}]"
            
            if searchType == "files":
                if filePattern:
                    find_cmd = f"find {path} -type f -name '{filePattern}' 2>/dev/null | head -100"
                else:
                    find_cmd = f"find {path} -type f 2>/dev/null | head -100"
                result = subprocess.run(
                    find_cmd, shell=True, capture_output=True, text=True, timeout=15
                )
                files = [f for f in result.stdout.strip().split("\n") if f and pattern in f]
                import time
                _evict_searches()
                _active_searches[search_id] = {
                    "type": "files",
                    "pattern": pattern,
                    "results": [{"file": f} for f in files[:maxResults]],
                    "path": path,
                    "created_at": time.time(),
                }
            else:
                # Content search: prefer ripgrep, fall back to grep
                if _HAS_RG:
                    cmd = ["rg", "--color=never"]
                    if ignoreCase:
                        cmd.append("-i")
                    if contextLines > 0:
                        cmd.extend(["-A", str(contextLines), "-B", str(contextLines)])
                    if filePattern:
                        cmd.extend(["-g", filePattern])
                    cmd.extend(["-e", pattern, path])
                else:
                    cmd = ["grep", "-r", "--include=" + (filePattern or "*")]
                    if ignoreCase:
                        cmd.append("-i")
                    if contextLines > 0:
                        cmd.extend([f"-A{contextLines}", f"-B{contextLines}"])
                    cmd.extend([pattern, path])

                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout_ms/1000
                )
                lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
                results = []
                for line in lines[:maxResults * 2]:
                    if line:
                        results.append(line)
                
                _active_searches[search_id] = {
                    "type": "content",
                    "pattern": pattern,
                    "results": results[:maxResults],
                    "path": path,
                    "created_at": time.time(),
                }
            
            count = len(_active_searches[search_id]["results"])
            return f"🔍 Search started: {search_id}\n   Found {count} results for '{pattern}'\n   Use get_more_search_results('{search_id}') to view"
            
        except subprocess.TimeoutExpired:
            return f"[Error: Search timed out after {timeout_ms}ms]"

        except Exception as e:
            return f"[Error: {str(e)}]"

    @mcp.tool()
    def get_more_search_results(sessionId: str, offset: int = 0, length: int = 50) -> str:
        """
        Get results from an active search.
        
        Args:
            sessionId: Search ID from start_search
            offset: Start index
            length: Number of results to return
        """
        if sessionId not in _active_searches:
            return f"[Error: Search '{sessionId}' not found or expired]"
        
        search = _active_searches[sessionId]
        results = search["results"]
        total = len(results)
        
        selected = results[offset:offset + length]
        remaining = total - offset - len(selected)
        
        if not selected:
            return f"No more results (showing all {total} total)"
        
        output = f"Results {offset} to {offset + len(selected) - 1} of {total}\n"
        if remaining > 0:
            output += f"({remaining} remaining)\n"
        output += "-" * 50 + "\n"
        
        if search["type"] == "files":
            for r in selected:
                output += f"{r['file']}\n"
        else:
            for r in selected:
                output += f"{r}\n"
        
        return output

    @mcp.tool()
    def stop_search(sessionId: str) -> str:
        """
        Stop and clean up a search.
        
        Args:
            sessionId: Search ID to stop
        """
        if sessionId in _active_searches:
            del _active_searches[sessionId]
            return f"✅ Search {sessionId} stopped and cleaned up"
        return f"[Warning: Search '{sessionId}' not found]"

    @mcp.tool()
    def list_searches() -> str:
        """List all active searches."""
        if not _active_searches:
            return "📭 No active searches"
        
        output = "Active Searches:\n" + "=" * 50 + "\n"
        for sid, search in _active_searches.items():
            count = len(search["results"])
            output += f"\n  {sid}\n"
            output += f"  Pattern: {search['pattern']}\n"
            output += f"  Type: {search['type']}\n"
            output += f"  Results: {count}\n"
        
        return output
