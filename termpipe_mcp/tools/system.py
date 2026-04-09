"""
System, config, and usage tools for TermPipe MCP Server.
"""

import os
import importlib
import sys
import platform
import json as _json
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

# ---------------------------------------------------------------------------
# VERSION
# ---------------------------------------------------------------------------

def _read_version() -> str:
    """Read version from VERSION file at project root."""
    try:
        v = (Path(__file__).parent.parent.parent / "VERSION").read_text().strip()
        return v or "unknown"
    except Exception:
        return "unknown"

# ---------------------------------------------------------------------------
# Open tasks summary (injected into list_tools / boot output)
# ---------------------------------------------------------------------------

def _open_tasks_summary(cwd: str) -> str:
    """
    Return a formatted block of open task items for the workspace, or ''
    if there is no workspace / task.md yet. Never raises.
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
            id_match = re.search(r"<!--\s*id:\s*(\d+)", line)
            item_id = id_match.group(1) if id_match else "?"
            text = re.sub(r"<!--.*?-->", "", line).strip()
            text = re.sub(r"^-\s*\[\s*\]\s*", "", text)
            text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
            text = text.split(" — ")[0].strip()
            open_items.append((item_id, text))
        if not open_items:
            return "\n✅ No open tasks\n"
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


# ---------------------------------------------------------------------------
# Tool call history — persisted to disk so it survives server restarts [#13]
# ---------------------------------------------------------------------------

_HISTORY_FILE = Path.home() / ".termpipe" / "tool_call_history.jsonl"
_tool_call_history = []
_history_loaded = False


def _ensure_history_loaded():
    global _history_loaded
    if _history_loaded:
        return
    _history_loaded = True
    try:
        _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        if _HISTORY_FILE.exists():
            lines = _HISTORY_FILE.read_text().splitlines()
            for line in lines[-1000:]:  # cap at last 1000 on load
                line = line.strip()
                if line:
                    try:
                        _tool_call_history.append(_json.loads(line))
                    except Exception:
                        pass
    except Exception:
        pass


def log_tool_call(tool_name: str, args: dict, result: str):
    """Log a tool call to memory and persist to disk."""
    _ensure_history_loaded()
    entry = {
        "timestamp": datetime.now().isoformat(),
        "tool": tool_name,
        "args": args,
        "result_preview": result[:200] if result else "",
    }
    _tool_call_history.append(entry)
    # Keep in-memory list capped
    if len(_tool_call_history) > 1000:
        _tool_call_history.pop(0)
    # Persist
    try:
        _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_HISTORY_FILE, "a") as f:
            f.write(_json.dumps(entry) + "\n")
        # Trim file if it gets large (keep last 1000 lines)
        _trim_history_file()
    except Exception:
        pass


def _trim_history_file():
    """Keep history file to last 1000 entries."""
    try:
        lines = _HISTORY_FILE.read_text().splitlines()
        if len(lines) > 1000:
            _HISTORY_FILE.write_text("\n".join(lines[-1000:]) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register_tools(mcp):
    """Register system tools with the MCP server."""

    @mcp.tool()
    def system_info() -> str:
        """Get system information including TermPipe version and active reviewer backend."""
        version = _read_version()

        # Active reviewer backend [#12]
        reviewer_backend = "[none configured]"
        try:
            from termpipe_mcp.tools.surgical.reviewer import _active_backend, _backends
            if _active_backend and _active_backend in _backends:
                reviewer_backend = _active_backend
            elif _active_backend:
                reviewer_backend = f"{_active_backend} (registered but not in backends?)"
        except Exception as e:
            reviewer_backend = f"[error reading reviewer: {e}]"

        info  = f"🖥️  TermPipe MCP v{version}\n"
        info += "=" * 40 + "\n"
        info += f"OS:               {platform.system()} {platform.release()}\n"
        info += f"Python:           {platform.python_version()}\n"
        info += f"Machine:          {platform.machine()}\n"
        info += f"User:             {os.environ.get('USER', 'unknown')}\n"
        info += f"Home:             {Path.home()}\n"
        info += f"CWD:              {os.getcwd()}\n"
        info += f"TermPipe Dir:     {TERMPIPE_DIR}\n"
        info += f"Reviewer backend: {reviewer_backend}\n"
        return info

    @mcp.tool()
    def get_config() -> str:
        """Get current TermPipe configuration."""
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH) as f:
                    config = _json.load(f)
                if "api_key" in config:
                    key = config["api_key"]
                    config["api_key"] = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "***"
                return f"📋 Configuration:\n{_json.dumps(config, indent=2)}"
            else:
                return "[No configuration file found]"
        except Exception as e:
            return f"[Error reading config: {str(e)}]"

    @mcp.tool()
    def get_recent_tool_calls(limit: int = 20) -> str:
        """
        Get recent tool call history (persisted across server restarts).

        Args:
            limit: Number of recent calls to return
        """
        _ensure_history_loaded()
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
        _resolved_cwd = str(Path(cwd).expanduser().resolve())
        try:
            _cc_path = Path.home() / ".context-core" / "current_workspace"
            _cc_path.parent.mkdir(parents=True, exist_ok=True)
            _cc_path.write_text(_resolved_cwd)
        except Exception:
            pass
        try:
            if _workspace_resume:
                _workspace_resume(cwd)
        except Exception:
            pass

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
            "workspace":    "TOOLS",
            "writers":      "WRITERS",
            "readers":      "READERS",
            "replacers":    "REPLACERS",
            "formatters":   "FORMATTERS",
        }

        tools_by_category: dict[str, list[str]] = {}
        try:
            raw = mcp._tool_manager._tools
            for tool_name in sorted(raw.keys()):
                fn = getattr(raw[tool_name], 'fn', None)
                mod = ""
                if fn:
                    mod_full = getattr(fn, '__module__', '')
                    mod = mod_full.split('.')[-1] if mod_full else ''
                cat = MODULE_CATEGORY.get(mod, mod.upper() or "OTHER")
                tools_by_category.setdefault(cat, []).append(tool_name)
        except Exception as e:
            return f"[Error reading live registry: {e}]\nFalling back — restart server to refresh."

        import inspect

        def _schema_for(tool_name):
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
                        _is_union = (
                            origin is getattr(__import__('typing'), 'Union', None)
                            or isinstance(hint, _types.UnionType)
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

        version = _read_version()
        out = f"TermPipe MCP Tools (v{version} — live registry)\n"
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
        tasks_block = _open_tasks_summary(_resolved_cwd)
        if tasks_block:
            out += f"\n{tasks_block}"
        out += f"\n\n▶ NEXT: call context-core:session(directory=\"{_resolved_cwd}\") to load project memory."
        return out

    @mcp.tool()
    def boot(cwd: str, task: str = "") -> str:
        """
        Mid-session context refresh — emits the context-core trigger directive.

        Args:
            cwd:  Absolute path to the project root.
            task: Optional — what you're about to work on.
        """
        _resolved_cwd = str(Path(cwd).expanduser().resolve())
        try:
            _cc_path = Path.home() / ".context-core" / "current_workspace"
            _cc_path.parent.mkdir(parents=True, exist_ok=True)
            _cc_path.write_text(_resolved_cwd)
        except Exception:
            pass
        try:
            import json as _j
            _log_path = Path.home() / ".context-core" / "boot_log.jsonl"
            _log_entry = _j.dumps({
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

        try:
            importlib.reload(_tools_pkg)
            results.append("✅ termpipe_mcp.tools.__init__ reloaded")
        except Exception as e:
            return f"❌ __init__.py reload failed: {e}\nRegistry unchanged."

        MODULE_OBJECTS = [
            mod for _, mod in inspect.getmembers(_tools_pkg, inspect.ismodule)
        ]

        for mod in MODULE_OBJECTS:
            try:
                importlib.reload(mod)
                results.append(f"✅ {mod.__name__}")
            except Exception as e:
                results.append(f"❌ {mod.__name__}: {e}")

        try:
            mcp._tool_manager._tools.clear()
            results.append("🗑️  Registry cleared")
        except Exception as e:
            results.append(f"⚠️  Could not clear registry: {e}")

        for mod in MODULE_OBJECTS:
            try:
                mod.register_tools(mcp)
            except Exception as e:
                results.append(f"❌ re-register {mod.__name__}: {e}")

        tool_count = len(getattr(mcp._tool_manager, '_tools', {}))
        results.append(f"\n✅ Done — {tool_count} tools live")
        return "\n".join(results)
