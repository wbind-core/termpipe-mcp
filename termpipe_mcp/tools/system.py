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

try:
    from termpipe_mcp.tools.workspace import workspace_resume as _workspace_resume
except ImportError:
    try:
        from tools.workspace import workspace_resume as _workspace_resume
    except ImportError:
        _workspace_resume = None

# Context-Core integration — imported lazily so TermPipe works without it
def _cc_session(directory: str, task: str = "") -> dict:
    """Call context-core session() if available, return {} on any failure."""
    try:
        from context_core import session as cc_session
        return cc_session(directory=directory, task=task) or {}
    except Exception:
        return {}

def _cc_retrieve(query: str, session_id: str = "default") -> list:
    """Call context-core retrieve_context() if available, return [] on any failure."""
    try:
        from context_core import retrieve_context
        return retrieve_context(query=query, session_id=session_id, sources="stm,ltm", max_results=8) or []
    except Exception:
        return []

def _build_context_block(cwd: str, task: str = "") -> str:
    """
    Bootstrap a Context-Core session and retrieve LTM, then format
    a clean WORKSPACE CONTEXT block ready to append to any tool output.
    Returns an empty string if Context-Core is unavailable or returns nothing useful.
    """
    project_name = Path(cwd).name
    session_data = _cc_session(directory=cwd, task=task)
    if not session_data:
        return ""

    lines = []
    lines.append("")
    lines.append("=" * 50)
    lines.append(f"WORKSPACE CONTEXT  •  {session_data.get('display_name', project_name)}  •  Session #{session_data.get('session_num', '?')}")
    lines.append("=" * 50)

    # Recent session history
    history = session_data.get("history_summary", [])
    if history:
        lines.append("RECENT SESSIONS:")
        for h in history[:3]:
            summary = h.get("summary", "(no summary)")
            if summary and summary != "(no summary)":
                lines.append(f"  #{h['session']}  {summary[:120]}{'...' if len(summary) > 120 else ''}")
        lines.append("")

    # LTM key facts
    ltm_items = _cc_retrieve(query=f"{project_name} architecture tools decisions", session_id=str(session_data.get("workspace_id", "default")))
    if ltm_items:
        lines.append("KEY FACTS (from memory):")
        seen = set()
        for item in ltm_items:
            content = item.get("content", "").strip()
            if content and content not in seen:
                seen.add(content)
                snippet = content[:160] + ("..." if len(content) > 160 else "")
                lines.append(f"  • {snippet}")
        lines.append("")

    lines.append("=" * 50)
    return "\n".join(lines)


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
    def list_tools(cwd: str, category: Optional[str] = None, include_schemas: bool = False) -> str:
        """
        List available MCP tools — dynamically read from live registry.

        Args:
            cwd: Absolute path to the current working directory (project root). Required.
            category: Filter by category name, or 'all' / omit for everything.
            include_schemas: If True, include full JSON parameter schemas for each tool.
        """
        # Write cwd to known location so context_core middleware can pick it up
        try:
            _cc_path = Path.home() / ".context-core" / "current_workspace"
            _cc_path.parent.mkdir(parents=True, exist_ok=True)
            _cc_path.write_text(cwd)
        except Exception:
            pass  # Never let this break list_tools
        # Resume workspace artifacts onto bus
        try:
            if _workspace_resume:
                _workspace_resume(cwd)
        except Exception:
            pass  # Never let this break list_tools
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
            "workspace":    "WORKSPACE",
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
        # Append workspace context block (A/B hybrid: auto-boot on list_tools)
        context_block = _build_context_block(cwd)
        if context_block:
            out += context_block
        return out

    @mcp.tool()
    def boot(cwd: str, task: str = "") -> str:
        """
        One-shot session bootstrap — returns full WORKSPACE CONTEXT without the tool list.

        Use this at the start of a session when you already know the tools and just
        want the project memory: recent session history, key architectural facts, and
        open tasks from Context-Core LTM.

        Equivalent to calling list_tools(cwd=...) and reading only the WORKSPACE
        CONTEXT block at the bottom — but faster and less noisy.

        Args:
            cwd:  Absolute path to the project root (same as list_tools).
            task: Optional description of what you're about to work on.
                  Used to seed context retrieval for better relevance.
        """
        # Write cwd to known location so context_core middleware can pick it up
        try:
            _cc_path = Path.home() / ".context-core" / "current_workspace"
            _cc_path.parent.mkdir(parents=True, exist_ok=True)
            _cc_path.write_text(cwd)
        except Exception:
            pass
        # Resume workspace artifacts onto bus
        try:
            if _workspace_resume:
                _workspace_resume(cwd)
        except Exception:
            pass

        block = _build_context_block(cwd, task=task)
        if block:
            return block.strip()
        return f"[No Context-Core data found for {cwd}. Run list_tools(cwd=...) first to initialize.]"


    @mcp.tool()
    def reload_tools() -> str:
        """
        Hot-reload all tool modules without restarting Claude Desktop.
        Re-imports every module in termpipe_mcp/tools/ and re-registers all
        tools in-place. Use this after editing any tool file.
        """
        import inspect
        import termpipe_mcp.tools as _tools_pkg

        # Dynamically discover modules — respects __init__.py comments
        MODULE_OBJECTS = [
            mod for _, mod in inspect.getmembers(_tools_pkg, inspect.ismodule)
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
