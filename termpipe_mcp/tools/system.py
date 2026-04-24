"""
System, config, and usage tools for TermPipe MCP Server.
"""

import os
import inspect
import importlib
import sys
import platform
import json as _json
import subprocess
import getpass
import socket
import urllib.request
import threading
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
# GLOBAL PATHS & CONSTANTS
# ---------------------------------------------------------------------------

_LOCAL_BIN = Path.home() / ".local" / "bin"
KB_PATH = str(_LOCAL_BIN / "kb")
KC_BUS_PATH = str(_LOCAL_BIN / "kc-bus")
KBD_PATH = str(_LOCAL_BIN / "kbd")
TERMCP_PATH = str(_LOCAL_BIN / "termcp")
CONDD_PATH = str(_LOCAL_BIN / "condd")
GTTINFORM_PATH = str(_LOCAL_BIN / "gttinform")
WBIND_PATH = str(_LOCAL_BIN / "wbind")
GRUS_PATH = str(_LOCAL_BIN / "grus")
GTT_PORTAL_PATH = str(_LOCAL_BIN / "gtt-portal")
RUSTUP_PATH = str(Path.home() / ".cargo" / "bin" / "rustup")

# Context-Core Bootstrap (Integrated project memory)
CC_PYTHON_PATH = "/home/craig/.local/share/pipx/venvs/context-core-mcp/bin/python"

_HISTORY_FILE = Path.home() / ".termpipe" / "tool_call_history.jsonl"
_tool_call_history = []
_history_loaded = False


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _read_version() -> str:
    """Read version from VERSION file at project root."""
    try:
        v = (Path(__file__).parent.parent.parent / "VERSION").read_text().strip()
        return v or "unknown"
    except Exception:
        return "unknown"


def _open_tasks_summary(cwd: str) -> str:
    """Return formatted block of open task items."""
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


def _reconcile_tasks(cwd: str) -> int:
    """Auto-close tasks mentioned in recent git commits."""
    try:
        import re
        if _WS_ARTIFACTS_ROOT is None:
            return 0
        task_file = _WS_ARTIFACTS_ROOT / Path(cwd).name / "task.md"
        if not task_file.exists():
            return 0
        result = subprocess.run(
            ["git", "log", "--pretty=%B", "-n", "30"],
            cwd=cwd, capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return 0
        referenced_ids = set(re.findall(r'\[(\d+)\]', result.stdout))
        if not referenced_ids:
            return 0
        lines = task_file.read_text(encoding="utf-8").splitlines()
        closed = 0
        new_lines = []
        for line in lines:
            if line.strip().startswith("- [ ]"):
                id_match = re.search(r'<!--\s*id:\s*(\d+)', line)
                if id_match and id_match.group(1) in referenced_ids:
                    line = line.replace("- [ ]", "- [x]", 1)
                    closed += 1
            new_lines.append(line)
        if closed:
            task_file.write_text("\n".join(new_lines), encoding="utf-8")
        return closed
    except Exception:
        return 0


def _ensure_history_loaded():
    global _history_loaded
    if _history_loaded: return
    _history_loaded = True
    try:
        if _HISTORY_FILE.exists():
            lines = _HISTORY_FILE.read_text().splitlines()
            for line in lines[-1000:]:
                try:
                    _tool_call_history.append(_json.loads(line))
                except Exception: pass
    except Exception: pass


def log_tool_call(tool_name: str, args: dict, result: str):
    _ensure_history_loaded()
    entry = {
        "timestamp": datetime.now().isoformat(),
        "tool": tool_name,
        "args": args,
        "result_preview": result[:200] if result else "",
    }
    _tool_call_history.append(entry)
    if len(_tool_call_history) > 1000: _tool_call_history.pop(0)
    try:
        _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_HISTORY_FILE, "a") as f:
            f.write(_json.dumps(entry) + "\n")
        # Trim file logic (simplified)
        if len(_tool_call_history) % 100 == 0:
            lines = _HISTORY_FILE.read_text().splitlines()
            if len(lines) > 1200:
                _HISTORY_FILE.write_text("\n".join(lines[-1000:]) + "\n")
    except Exception: pass


def _get_tactical_insights(cwd: str) -> str:
    """Aggregate live system telemetry from a single kb get sys.metrics call."""
    import json as _j, re
    insights = ["--- TACTICAL ENVIRONMENT INSIGHTS (Model Hints) ---"]

    # Single bus call — CollectMetricsOnce runs on-demand inside kbd
    data = {}
    try:
        res = subprocess.run([KB_PATH, "get", "sys.metrics", "--json"],
                             capture_output=True, text=True, timeout=6)
        if res.returncode == 0:
            ansi_strip = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', res.stdout).strip()
            envelope = _j.loads(ansi_strip)
            raw = envelope.get("data", "")
            if isinstance(raw, str):
                data = _j.loads(raw)
            elif isinstance(raw, dict):
                data = raw
    except Exception as e:
        insights.append(f"⚠️  Bus error: {e}")
        insights.append("-" * 50)
        return "\n".join(insights)

    # Identity
    user     = data.get("username", getpass.getuser())
    host     = data.get("hostname", socket.gethostname())
    session  = data.get("session_type", os.environ.get("XDG_SESSION_TYPE", "")).title()
    shell    = data.get("shell", os.environ.get("SHELL", "").split("/")[-1])
    os_info  = f"{platform.system()} {platform.release()}"
    insights.append(f"👤 USER: {user} @ {host} ({session}) | 💻 OS: {os_info} | Shell: {shell}")

    # Python (still local — not in bus payload)
    python_v = platform.python_version()
    venv     = os.environ.get("VIRTUAL_ENV")
    venv_str = f" | Venv: {venv}" if venv else ""
    insights.append(f"🐍 ENV: Python {python_v}{venv_str}")

    # SDKs
    sdks = []
    if data.get("go_version"):   sdks.append(data["go_version"])
    
    rust_v = data.get("rust_version")
    if not rust_v:
        # Fallback to local RUSTUP_PATH probe if bus is missing it
        try:
            res = subprocess.run([RUSTUP_PATH, "run", "stable", "rustc", "--version"], capture_output=True, text=True, timeout=0.5)
            if res.returncode == 0:
                rust_v = res.stdout.strip().split()[1]
        except: pass
    if rust_v: sdks.append(f"Rust {rust_v}")
    
    if data.get("node_version"): sdks.append(f"Node {data['node_version']}")
    if sdks: insights.append(f"🛠️  SDKs: {' | '.join(sdks)}")

    # 3. Networking
    ssid     = data.get("ssid", "")
    signal   = data.get("ssid_signal", 0)
    wifi_str = f"\"{ssid}\" ({signal}%) | " if ssid else ""
    local_ip = data.get("local_ip", "unknown")
    ext_ip   = data.get("ext_ip", "unknown")
    
    net_test = data.get("net_test_mbps", 0)
    net_str  = f" | Speed: {net_test:.1f} Mbps" if net_test > 0 else ""
    insights.append(f"🌐 NET: {wifi_str}Local: {local_ip} | Ext: {ext_ip}{net_str}")

    # 4. System metrics
    ru  = data.get("ram_used", 0) / (1024**3)
    rt  = data.get("ram_total", 0) / (1024**3)
    rp  = data.get("ram_used_percent", 0)
    cpu = data.get("cpu_percent", 0)
    insights.append(f"🧠 SYS: RAM: {ru:.1f}G/{rt:.1f}G ({rp:.1f}%) | CPU: {cpu:.1f}%")


    # Git (still local — cwd-specific, not in bus payload)
    try:
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=cwd, capture_output=True, text=True, timeout=1).stdout.strip()
        if branch:
            dirty  = subprocess.run(["git", "status", "--short"], cwd=cwd, capture_output=True, text=True, timeout=1).stdout.strip()
            status = f"Dirty: {len(dirty.splitlines())} files" if dirty else "No changes"
            insights.append(f"🌿 GIT: [{branch}] ({status})")
    except Exception: pass

    insights.append("-" * 50)
    return "\n".join(insights)


def _bootstrap_context_core(directory: str) -> str:
    """Programmatically trigger context-core:session logic."""
    script = f"""
import asyncio, json
from context_core_mcp.server import session
async def main():
    res = await session(directory="{directory}")
    print(res)
asyncio.run(main())
"""
    try:
        res = subprocess.run([CC_PYTHON_PATH, "-c", script], capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            data = _json.loads(res.stdout)
            block = ["\n🧠 PROJECT MEMORY (Context-Core Integrated)", "=" * 50]
            block.append(f"Workspace: {data.get('display_name')} (ID: {data.get('workspace_id')})")
            block.append(f"Session: #{data.get('session_num')} | Status: {data.get('mode')}")
            history = data.get("history_summary", [])
            if history:
                block.append("\n📜 Recent History:")
                for h in history[:3]: block.append(f"  • {h['started'][:10]}: {h['summary']} ({h['changes']} changes)")
            ctx = data.get("context", "")
            if ctx and "No prior context" not in ctx:
                block.append("\n💡 Relevant Context (LTM):")
                lines = ctx.splitlines()
                for l in lines[:8]: block.append(f"  {l}")
                if len(lines) > 8: block.append(f"  ... ({len(lines)-8} more lines in full session)")
            block.append("\n▶ TIP: " + data.get("tip", "")); block.append("-" * 50)
            return "\n".join(block)
    except Exception as e: return f"\n⚠️  Context-Core bootstrap failed: {e}"
    return ""


def _ensure_daemons():
    """Ensure critical TermPipe daemons are active."""
    import time
    for path, name in [(KBD_PATH, "kbd"), (TERMCP_PATH, "termcp"), (CONDD_PATH, "condd"), (GTTINFORM_PATH, "gttinform"), (KB_PATH, "kb")]:
        if subprocess.run(["pgrep", "-f", name], capture_output=True).returncode != 0:
            cmd = [path] if name != "termcp" else [path, "server"]
            if name == "kb": cmd = [path, "start"]
            subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
# TOOL REGISTRATION
# ---------------------------------------------------------------------------

def register_tools(mcp):
    """Register all system tools with the MCP server."""

    @mcp.tool()
    def system_info() -> str:
        """Get high-level system and TermPipe metadata."""
        version = _read_version()
        info = f"🖥️  TermPipe MCP v{version}\n" + "=" * 40 + "\n"
        info += f"OS:               {platform.system()} {platform.release()}\n"
        info += f"Python:           {platform.python_version()}\n"
        info += f"User:             {getpass.getuser()}\n"
        info += f"CWD:              {os.getcwd()}\n"
        return info

    @mcp.tool()
    def get_config() -> str:
        """Get current TermPipe configuration."""
        try:
            if CONFIG_PATH.exists():
                config = _json.loads(CONFIG_PATH.read_text())
                if "api_key" in config:
                    key = config["api_key"]
                    config["api_key"] = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "***"
                return f"📋 Configuration:\n{_json.dumps(config, indent=2)}"
            return "[No configuration file found]"
        except Exception as e: return f"[Error: {e}]"

    @mcp.tool()
    def get_recent_tool_calls(limit: int = 20) -> str:
        """Get recent tool call history."""
        _ensure_history_loaded()
        if not _tool_call_history: return "📭 No history yet"
        recent = _tool_call_history[-limit:]
        out = f"Recent Tool Calls (last {len(recent)}):\n" + "=" * 50 + "\n"
        for call in reversed(recent):
            out += f"\n{call['timestamp']}: {call['tool']}\n  Args: {call['args']}\n"
        return out

    @mcp.tool()
    def list_tools(cwd: Optional[str] = None, category: Optional[str] = None, include_schemas: bool = False) -> str:
        """List available tools with tactical briefing and auto-context."""
        # ⚓ Physical Anchor
        if not cwd:
            try:
                res = subprocess.run([KB_PATH, "exec", "pwd"], capture_output=True, text=True, timeout=1)
                cwd = res.stdout.strip().splitlines()[-1] if res.returncode == 0 else "."
            except: cwd = "."
        res_cwd = str(Path(cwd).expanduser().resolve())
        
        # Sync workspace markers
        try:
            (Path.home() / ".context-core" / "current_workspace").write_text(res_cwd)
            if _workspace_resume: _workspace_resume(cwd)
        except: pass

        threading.Thread(target=_ensure_daemons, daemon=True).start()

        MODULE_CAT = {"git":"GIT","process":"PROCESS","termf":"TERMF","iflow":"IFLOW","files":"FILE","surgical":"SURGICAL","apps":"APPS","wbind":"WBIND","search":"SEARCH","thread":"THREAD","system":"SYSTEM","debug":"DEBUG","gemini_debug":"GEMINI","web_search":"WEB_SEARCH","gtt":"GTT","workspace":"TOOLS","writers":"WRITERS","readers":"READERS","replacers":"REPLACERS","formatters":"FORMATTERS"}
        
        tools_by_cat = {}
        try:
            raw = mcp._tool_manager._tools
            for name in sorted(raw.keys()):
                fn = getattr(raw[name], 'fn', None)
                mod = fn.__module__.split('.')[-1] if fn else ""
                tools_by_cat.setdefault(MODULE_CAT.get(mod, mod.upper() or "OTHER"), []).append(name)
        except Exception as e: return f"[Error: {e}]"

        import inspect
        def _schema_for(name):
            try:
                sig = inspect.signature(raw[name].fn)
                props, req = {}, []
                for pn, p in sig.parameters.items():
                    if pn in ('self', 'return'): continue
                    props[pn] = {"type": "string"} # Simplified
                    if p.default is inspect.Parameter.empty: req.append(pn)
                    else: props[pn]["default"] = p.default
                s = {"type": "object", "properties": props}
                if req: s["required"] = req
                return s
            except: return {}

        filter_cat = category.upper() if category and category.lower() != "all" else None
        if filter_cat:
            if filter_cat not in tools_by_cat: return f"Unknown category. Available: {', '.join(sorted(tools_by_cat.keys()))}"
            out = f"Category: {filter_cat}\n"
            for t in tools_by_cat[filter_cat]:
                out += f"  - {t}\n"
                if include_schemas: out += f"    schema: {_json.dumps(_schema_for(t))}\n"
            return out

        out = f"TermPipe MCP Tools (v{_read_version()} — live registry)\n" + "=" * 50 + "\n\n"
        total = 0
        for cat in sorted(tools_by_cat.keys()):
            tools = tools_by_cat[cat]; total += len(tools)
            out += f"{cat} ({len(tools)} tools)\n"
            for t in tools:
                out += f"   - {t}\n"
                if include_schemas: out += f"     schema: {_json.dumps(_schema_for(t))}\n"
            out += "\n"
        out += f"Total: {total} tools\n\n--- TACTICAL BRIEFING ---\n"
        
        _reconcile_tasks(res_cwd)
        try: subprocess.run([KC_BUS_PATH, "pub", "termpipe.workspace.init", _json.dumps({"cwd": res_cwd})], timeout=2, capture_output=True)
        except: pass
        
        out += _get_tactical_insights(res_cwd)
        out += "\n" + _bootstrap_context_core(res_cwd)

        # Phase state machine briefing
        try:
            try:
                from termpipe_mcp.tools.workspace._phase import phase_briefing, ws_id_from_cwd
            except ImportError:
                from tools.workspace._phase import phase_briefing, ws_id_from_cwd
            ws_id = ws_id_from_cwd(res_cwd)
            if ws_id:
                out += phase_briefing(ws_id)
        except Exception as _phase_err:
            out += f"\n[phase briefing error: {_phase_err}]\n"

        out += f"\n🕒 {datetime.now().strftime('%Y-%m-%d %I:%M %p')}"
        return out

    @mcp.tool()
    def boot(cwd: str, task: str = "") -> str:
        """Mid-session context refresh with integrated briefing."""
        res_cwd = str(Path(cwd).expanduser().resolve())
        _reconcile_tasks(res_cwd)
        return f"Workspace armed: {res_cwd}\n{_open_tasks_summary(res_cwd)}\n{_bootstrap_context_core(res_cwd)}\nBriefing complete."

    @mcp.tool()
    def reload_tools() -> str:
        """Hot-reload all tool modules."""
        import termpipe_mcp.tools as tp
        try: importlib.reload(tp); out = ["✅ termpipe_mcp.tools reloaded"]
        except Exception as e: return f"❌ Failed: {e}"
        mods = [m for _, m in inspect.getmembers(tp, inspect.ismodule)]
        for m in mods:
            try: importlib.reload(m); out.append(f"✅ {m.__name__}")
            except Exception as e: out.append(f"❌ {m.__name__}: {e}")
        try:
            mcp._tool_manager._tools.clear()
            for m in mods:
                try: m.register_tools(mcp)
                except: pass
            out.append(f"\n✅ Registry refreshed — {len(mcp._tool_manager._tools)} tools live")
        except Exception as e: out.append(f"⚠️  Registry reset failed: {e}")
        return "\n".join(out)
