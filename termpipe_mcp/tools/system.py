"""
System, config, and usage tools for TermPipe MCP Server.
"""

import os
import importlib
import sys
import platform
from datetime import datetime
from pathlib import Path
from typing import Optional
try:
    from termpipe_mcp.helpers import TERMPIPE_DIR, CONFIG_PATH
except ImportError:
    from helpers import TERMPIPE_DIR, CONFIG_PATH


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
    def list_tools(category: Optional[str] = None, include_schemas: bool = False) -> str:
        """
        List available MCP tools — dynamically read from live registry.

        Args:
            category: Filter by category name, or 'all' / omit for everything.
            include_schemas: If True, include full JSON parameter schemas for each tool.
        """
        # Module-name → category label mapping
        MODULE_CATEGORY = {
            "process":      "PROCESS",
            "termf":        "TERMF",
            "iflow":        "IFLOW",
            "files":        "FILE",
            "surgical":     "SURGICAL",
            "apps":         "APPS",
            "wbind":        "WBIND",
            "search":       "SEARCH",
            "thread":       "THREAD",
            "system":       "SYSTEM",
            "debug":        "DEBUG",
            "gemini_debug": "GEMINI",
            "web_search":   "WEB_SEARCH",
            "gtt":          "GTT",
        }

        # Build registry dynamically from FastMCP internals
        tools_by_category: dict[str, list[str]] = {}
        try:
            # FastMCP stores tools in ._tool_manager.tools (dict name->tool)
            raw = mcp._tool_manager._tools  # {tool_name: Tool}
            for tool_name in sorted(raw.keys()):
                # Resolve which module registered it via __module__ on the fn
                fn = getattr(raw[tool_name], 'fn', None)
                mod = ""
                if fn:
                    qname = getattr(fn, '__qualname__', '')
                    # qualname like "register_tools.<locals>.read_lines"
                    # __module__ like "tools.surgical"
                    mod_full = getattr(fn, '__module__', '')
                    mod = mod_full.split('.')[-1] if mod_full else ''
                cat = MODULE_CATEGORY.get(mod, mod.upper() or "OTHER")
                tools_by_category.setdefault(cat, []).append(tool_name)
        except Exception as e:
            return f"[Error reading live registry: {e}]\nFalling back — restart server to refresh."

        import inspect, json as _json

        def _schema_for(tool_name):
            """Extract JSON schema for a tool's parameters."""
            try:
                tool_obj = raw[tool_name]
                fn = getattr(tool_obj, 'fn', None)
                if fn is None:
                    return {}
                sig = inspect.signature(fn)
                props = {}
                required = []
                hints = fn.__annotations__ if hasattr(fn, '__annotations__') else {}
                for pname, param in sig.parameters.items():
                    if pname in ('self', 'return'):
                        continue
                    hint = hints.get(pname, None)
                    ptype = "string"
                    if hint is not None:
                        import types as _types
                        origin = getattr(hint, '__origin__', None)
                        args = getattr(hint, '__args__', ())
                        # Python 3.10+ uses types.UnionType for X | Y; older uses typing.Union
                        _is_union = (
                            origin is getattr(__import__('typing'), 'Union', None)
                            or isinstance(hint, _types.UnionType)  # 3.10+
                        )
                        if hint in (int,) or (origin is None and hint == int): ptype = "integer"
                        elif hint in (bool,): ptype = "boolean"
                        elif hint in (float,): ptype = "number"
                        elif origin is list: ptype = "array"
                        elif _is_union:
                            non_none = [a for a in args if a is not type(None)]
                            if non_none:
                                ptype = {int: "integer", bool: "boolean", float: "number", str: "string"}.get(non_none[0], "string")
                    prop = {"type": ptype}
                    if param.default is inspect.Parameter.empty:
                        required.append(pname)
                    else:
                        prop["default"] = None if param.default is None else param.default
                    props[pname] = prop
                schema = {"type": "object", "properties": props}
                if required:
                    schema["required"] = required
                return schema
            except Exception:
                return {}

        filter_cat = category.upper() if category and category.lower() != "all" else None

        if filter_cat:
            if filter_cat not in tools_by_category:
                available = ", ".join(sorted(tools_by_category.keys()))
                return f"[Error: Unknown category '{category}']. Available: {available}"
            tools = tools_by_category[filter_cat]
            out = f"Category: {filter_cat} ({len(tools)} tools)\n\n"
            for t in tools:
                out += f"  - {t}\n"
                if include_schemas:
                    schema = _schema_for(t)
                    out += f"    schema: {_json.dumps(schema)}\n"
            return out

        out = "TermPipe MCP Tools (Modular v2.3 — live registry)\n"
        out += "=" * 50 + "\n\n"
        total = 0
        for cat_name in sorted(tools_by_category.keys()):
            tools = tools_by_category[cat_name]
            total += len(tools)
            out += f"{cat_name} ({len(tools)} tools)\n"
            for t in tools:
                out += f"   - {t}\n"
                if include_schemas:
                    schema = _schema_for(t)
                    out += f"     schema: {_json.dumps(schema)}\n"
            out += "\n"
        out += f"Total: {total} tools\n\n"
        out += "Use list_tools(category='surgical') for a specific category"
        return out

    @mcp.tool()
    def reload_tools() -> str:
        """
        Hot-reload all tool modules without restarting Claude Desktop.
        Re-imports every module in termpipe_mcp/tools/ and re-registers all
        tools in-place. Use this after editing any tool file.
        """
        from termpipe_mcp.tools import (
            process, termf, iflow, files, surgical, apps, wbind,
            search, thread, system, debug, gemini_debug, web_search, gtt,
        )
        MODULE_OBJECTS = [
            process, termf, iflow, files, surgical, apps, wbind,
            search, thread, system, debug, gemini_debug, web_search, gtt,
        ]

        results = []

        # 1. Reload each module
        for mod in MODULE_OBJECTS:
            try:
                importlib.reload(mod)
                results.append(f"✅ {mod.__name__}")
            except Exception as e:
                results.append(f"❌ {mod.__name__}: {e}")

        # 2. Clear existing tool registrations
        try:
            mcp._tool_manager._tools.clear()
            results.append("🗑️  Registry cleared")
        except Exception as e:
            results.append(f"⚠️  Could not clear registry: {e}")

        # 3. Re-register all modules
        for mod in MODULE_OBJECTS:
            try:
                mod.register_tools(mcp)
            except Exception as e:
                results.append(f"❌ re-register {mod.__name__}: {e}")

        tool_count = len(getattr(mcp._tool_manager, '_tools', {}))
        results.append(f"\n✅ Done — {tool_count} tools live")
        return "\n".join(results)
