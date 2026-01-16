"""
Thread coordination tools for TermPipe MCP Server.
"""

from pathlib import Path
from datetime import datetime
from termpipe_mcp.helpers import THREAD_FILE


def register_tools(mcp):
    """Register thread coordination tools with the MCP server."""
    
    @mcp.tool()
    def thread_log(message: str, sender: str = "MCP") -> str:
        """
        Log a message to the coordination thread file.
        
        Args:
            message: Message to log
            sender: Who is logging (default: MCP)
        """
        try:
            THREAD_FILE.parent.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            entry = f"\n[{timestamp}] **{sender}**: {message}\n"
            
            with open(THREAD_FILE, "a") as f:
                f.write(entry)
            
            return f"✅ Logged to thread: {message[:50]}..."
            
        except Exception as e:
            return f"[Error: {str(e)}]"

    @mcp.tool()
    def thread_read(last_n: int = 20) -> str:
        """
        Read recent entries from the coordination thread.
        
        Args:
            last_n: Number of lines to read from end
        """
        try:
            if not THREAD_FILE.exists():
                return "[No thread file found]"
            
            content = THREAD_FILE.read_text()
            lines = content.strip().split("\n")
            
            if last_n and len(lines) > last_n:
                lines = lines[-last_n:]
            
            return "\n".join(lines)
            
        except Exception as e:
            return f"[Error: {str(e)}]"
