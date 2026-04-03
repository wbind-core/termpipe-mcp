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

try:
    from termpipe_mcp.tools.workspace._bus import _ARTIFACTS_ROOT as _WS_ARTIFACTS_ROOT
except ImportError:
    try:
        from tools.workspace._bus import _ARTIFACTS_ROOT as _WS_ARTIFACTS_ROOT
    except ImportError:
        _WS_ARTIFACTS_ROOT = None


def _open_tasks_summary(cwd: str) -> str:
    """
    Return a formatted block of open task items for the workspace, or ''
    if there is no workspace / task.md yet. Never raises.

    Output example:
        📋 OPEN TASKS (3):
          [11] Surgical sub-tools lack grouping in list_tools
          [12] system_info() doesn't show active reviewer backend
          [13] get_recent_tool_calls() history resets on server restart
    """
    try:
        if _WS_ARTIFACTS_ROOT is None:
            return ""
        import re
        task_file = _WS_ARTIFACTS_ROOT / Path(cwd).name / "task.md"
        if not task_file.exists():
            return ""
        lines = task_file.read_text(encoding="utf-8").splitlines()
        open_items = []
        for line in lines:
            if not line.strip().startswith("- [ ]"):
                continue
            # Extract id from <!-- id: N -->
            id_match = re.search(r"<!--\s*id:\s*(\d+)", line)
            item_id = id_match.group(1) if id_match else "?"
            # Strip markdown: remove "- [ ] **text**" → "text", drop HTML comment
            text = re.sub(r"<!--.*?-->", "", line).strip()
            text = re.sub(r"^-\s*\[\s*\]\s*", "", text)
            text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
            # Trim to just the bold label (before " — ")
            text = text.split(" — ")[0].strip()
            open_items.append((item_id, text))
        if not open_items:
            return "\n✅ No open tasks\n"
        # Cap at 15 items to avoid context bloat
        shown = open_items[:15]
        extra = len(open_items) - len(shown)
        out = f"\n📋 OPEN TASKS ({len(open_items)}):\n"
        for item_id, text in shown:
            out += f"  [{item_id}] {text}\n"
        if extra:
            out += f"  … and {extra} more (read task.md for full list)\n"
        return out
    except Exception:
        return ""


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
        _resolved_cwd = str(Path(cwd).expanduser().resolve())
        try:
            _cc_path = Path.home() / ".context-core" / "current_workspace"
            _cc_path.parent.mkdir(parents=True, exist_ok=True)
            _cc_path.write_text(_resolved_cwd)
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
            "git":          "GIT",
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
        # ── Open tasks ────────────────────────────────────────────────────────
        tasks_block = _open_tasks_summary(_resolved_cwd)
        if tasks_block:
            out += f"\n{tasks_block}"
        # ── Context-Core trigger ──────────────────────────────────────────────
        # cwd is the cross-MCP trigger signal. Now that you have the tool list,
        # call context-core:session(directory="{cwd}") to load project memory:
        # session history, LTM key facts, and open tasks. This is the handoff.
        out += f"\n\n▶ NEXT: call context-core:session(directory=\"{_resolved_cwd}\") to load project memory."
        return out

    @mcp.tool()
    def boot(cwd: str, task: str = "") -> str:
        """
        Mid-session context refresh — emits the context-core trigger directive.

        Use when you already know the tools (skipping list_tools) and just need
        to load project memory. Writes cwd to the workspace slot and resumes bus
        artifacts, then tells you exactly what to call next on context-core.

        The actual memory (session history, LTM key facts, open tasks) lives in
        the context-core MCP server — this tool hands off to it via the directive.

        Args:
            cwd:  Absolute path to the project root.
            task: Optional — what you're about to work on (passed to context-core:session).
        """
        # Write cwd to known location for context-core middleware
        _resolved_cwd = str(Path(cwd).expanduser().resolve())
        try:
            _cc_path = Path.home() / ".context-core" / "current_workspace"
            _cc_path.parent.mkdir(parents=True, exist_ok=True)
            _cc_path.write_text(_resolved_cwd)
        except Exception:
            pass
        # Log the boot event for cross-environment validation
        try:
            import json as _json
            _log_path = Path.home() / ".context-core" / "boot_log.jsonl"
            _log_entry = _json.dumps({
                "event": "boot",
                "cwd_raw": cwd,
                "cwd_resolved": _resolved_cwd,
                "task": task,
                "timestamp": datetime.now().isoformat(),
                "env": os.environ.get("TERM_PROGRAM") or os.environ.get("DISPLAY") or "unknown",
            })
            with open(_log_path, "a") as _lf:
                _lf.write(_log_entry + "\n")
        except Exception:
            pass
        # Resume workspace artifacts onto bus
        try:
            if _workspace_resume:
                _workspace_resume(cwd)
        except Exception:
            pass

        task_hint = f", task=\"{task}\"" if task else ""
        tasks_block = _open_tasks_summary(_resolved_cwd)
        return (
            f"Workspace armed: {_resolved_cwd}\n"
            f"{tasks_block}\n"
            f"▶ NOW CALL: context-core:session(directory=\"{_resolved_cwd}\"{task_hint})\n"
            f"\n"
            f"That will load: session history, LTM key facts, and open tasks for this project."
        )


    @mcp.tool()
    def reload_tools() -> str:
        """
        Hot-reload all tool modules without restarting Claude Desktop.
        Re-imports every module in termpipe_mcp/tools/ and re-registers all
        tools in-place. Use this after editing any tool file.
        """
        import inspect
        import termpipe_mcp.tools as _tools_pkg

        results = []

        # 0. Reload __init__.py first — picks up any modules that were
        #    commented or uncommented since the server started.
        try:
            importlib.reload(_tools_pkg)
            results.append("✅ termpipe_mcp.tools.__init__ reloaded")
        except Exception as e:
            # Bail early — don't clear registry if __init__ is broken.
            return f"❌ __init__.py reload failed: {e}\nRegistry unchanged."

        # Dynamically discover modules from freshly reloaded package
        MODULE_OBJECTS = [
            mod for _, mod in inspect.getmembers(_tools_pkg, inspect.ismodule)
        ]

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
