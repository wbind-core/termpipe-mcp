"""
System, config, and usage tools for TermPipe MCP Server.
"""

import os
import platform
from datetime import datetime
from pathlib import Path
from typing import Optional
from termpipe_mcp.helpers import TERMPIPE_DIR, CONFIG_PATH


# Tool call history tracking
_tool_call_history = []


def log_tool_call(tool_name: str, args: dict, result: str):
    """Log a tool call for history tracking."""
    _tool_call_history.append({
        "timestamp": datetime.now().isoformat(),
        "tool": tool_name,
        "args": args,
        "result_preview": result[:200] if result else ""
    })
    # Keep only last 1000
    if len(_tool_call_history) > 1000:
        _tool_call_history.pop(0)


def register_tools(mcp):
    """Register system tools with the MCP server."""
    
    @mcp.tool()
    def system_info() -> str:
        """Get system information."""
        info = f"🖥️  System Information\n"
        info += "=" * 40 + "\n"
        info += f"OS: {platform.system()} {platform.release()}\n"
        info += f"Python: {platform.python_version()}\n"
        info += f"Machine: {platform.machine()}\n"
        info += f"User: {os.environ.get('USER', 'unknown')}\n"
        info += f"Home: {Path.home()}\n"
        info += f"CWD: {os.getcwd()}\n"
        info += f"TermPipe Dir: {TERMPIPE_DIR}\n"
        
        return info

    @mcp.tool()
    def get_config() -> str:
        """Get current TermPipe configuration."""
        try:
            if CONFIG_PATH.exists():
                import json
                with open(CONFIG_PATH) as f:
                    config = json.load(f)
                
                # Mask sensitive data
                if "api_key" in config:
                    key = config["api_key"]
                    config["api_key"] = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "***"
                
                import json
                return f"📋 Configuration:\n{json.dumps(config, indent=2)}"
            else:
                return "[No configuration file found]"
        except Exception as e:
            return f"[Error reading config: {str(e)}]"

    @mcp.tool()
    def get_recent_tool_calls(limit: int = 20) -> str:
        """
        Get recent tool call history.
        
        Args:
            limit: Number of recent calls to return
        """
        if not _tool_call_history:
            return "📭 No tool calls recorded yet"
        
        recent = _tool_call_history[-limit:]
        
        output = f"Recent Tool Calls (last {min(limit, len(_tool_call_history))}):\n"
        output += "=" * 50 + "\n"
        
        for call in reversed(recent):
            output += f"\n{call['timestamp']}: {call['tool']}\n"
            output += f"  Args: {call['args']}\n"
        
        return output

    @mcp.tool()
    def list_tools(category: Optional[str] = None) -> str:
        """
        List available MCP tools.
        
        Args:
            category: Filter by category (file, process, ai, etc)
        """
        tools_by_category = {
            "process": ["list_sessions", "read_process_output", "interact_with_process", "force_terminate", "list_processes"],
            "termf": ["termf_exec", "termf_nlp", "termf_nlp_alias"],
            "iflow": ["ifp_send", "ifp_model", "ifp_status"],
            "file": ["read_file", "write_file", "append_file", "list_directory", "glob_files", "search_file_content", "get_file_info", "move_file", "create_directory"],
            "surgical": ["read_lines", "insert_lines", "replace_lines", "replace_at_line", "smart_replace", "delete_lines", "find_in_file", "read_multiple_files"],
            "apps": ["launch_app", "list_apps"],
            "wbind": ["wbind_action", "wbind_launch_and_focus"],
            "search": ["start_search", "get_more_search_results", "stop_search", "list_searches"],
            "thread": ["thread_log", "thread_read"],
            "system": ["system_info", "get_config", "get_recent_tool_calls", "list_tools"],
            "debug": ["debug_assist", "analyze_file_structure", "suggest_edit_approach"],
            "gemini": ["gemini_debug", "gemini_analyze", "gemini_suggest"]
        }
        
        if category:
            cat = category.lower()
            if cat not in tools_by_category:
                available = ", ".join(tools_by_category.keys())
                return f"[Error: Unknown category '{category}']. Available: {available}"
            
            tools = tools_by_category[cat]
            output = f"Category: {category}\n\n"
            for name in tools:
                output += f"  - {name}\n"
            return output
        
        output = "TermPipe MCP Tools (Modular v2.2)\n"
        output += "=" * 50 + "\n\n"
        
        total = 0
        for cat_name, tools in sorted(tools_by_category.items()):
            count = len(tools)
            total += count
            output += f"{cat_name.upper()} ({count} tools)\n"
            for name in tools:
                output += f"   - {name}\n"
            output += "\n"
        
        output += f"Total: {total} tools\n\n"
        output += "Use list_tools(category='file') for detailed info"
        
        return output
