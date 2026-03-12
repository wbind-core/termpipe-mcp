"""
first_run.py — Cross-platform first-run setup for TermPipe MCP.

Handles:
  - Platform detection (Windows / macOS / Linux)
  - Config/settings directory creation
  - Default config.json + settings.json scaffolding
  - MCP client detection and auto-registration
    (Claude Desktop, iFlow CLI, Gemini CLI, opencode)
  - Autostart setup (systemd / launchd / Windows Task Scheduler)
  - gtt detection and PATH report

Entry points:
  termcp setup          (via cli.py)
  python -m termpipe_mcp.first_run   (standalone)
"""

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# ── Platform detection ────────────────────────────────────────────────────────

SYSTEM   = platform.system()   # "Linux" | "Darwin" | "Windows"
IS_WIN   = SYSTEM == "Windows"
IS_MAC   = SYSTEM == "Darwin"
IS_LINUX = SYSTEM == "Linux"
HOME     = Path.home()


def get_config_dir() -> Path:
    from termpipe_mcp.helpers import get_config_dir as _gcd
    return _gcd()


# ── MCP client config paths ───────────────────────────────────────────────────

def _mcp_client_paths() -> dict[str, Path]:
    """Return known MCP client config file paths for this platform."""
    paths = {}

    if IS_WIN:
        appdata = Path(os.environ.get("APPDATA", HOME / "AppData" / "Roaming"))
        paths["claude_desktop"] = appdata / "Claude" / "claude_desktop_config.json"
        paths["opencode"]       = appdata / "opencode" / "config.json"

    elif IS_MAC:
        support = HOME / "Library" / "Application Support"
        paths["claude_desktop"] = support / "Claude" / "claude_desktop_config.json"
        paths["opencode"]       = support / "opencode" / "config.json"
        paths["iflow_cli"]      = HOME / ".iflow" / "mcp_servers.json"
        paths["gemini_cli"]     = HOME / ".gemini" / "mcp_servers.json"

    else:  # Linux
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))
        paths["claude_desktop"] = config_home / "Claude" / "claude_desktop_config.json"
        paths["opencode"]       = config_home / "opencode" / "config.json"
        paths["iflow_cli"]      = HOME / ".iflow" / "mcp_servers.json"
        paths["gemini_cli"]     = HOME / ".gemini" / "mcp_servers.json"

    return paths


# ── Directory / file scaffolding ──────────────────────────────────────────────

def ensure_dirs() -> list[str]:
    """Create all required directories. Returns list of created paths."""
    created = []
    dirs = [
        get_config_dir(),
        get_config_dir() / "logs",
    ]
    for d in dirs:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(str(d))
    return created


def scaffold_config() -> bool:
    """Write default config.json if missing. Returns True if written."""
    cfg_path = get_config_dir() / "config.json"
    if cfg_path.exists():
        return False
    default = {
        "api_key":     "",
        "api_base":    "https://apis.iflow.cn/v1",
        "server_host": "127.0.0.1",
        "server_port": 8421,
    }
    cfg_path.write_text(json.dumps(default, indent=2))
    cfg_path.chmod(0o600)
    return True


def scaffold_settings() -> bool:
    """Write default settings.json if missing. Returns True if written."""
    from termpipe_mcp.settings import SETTINGS_PATH, DEFAULTS, save_settings
    if SETTINGS_PATH.exists():
        return False
    save_settings(dict(DEFAULTS))
    return True


# ── MCP client registration ───────────────────────────────────────────────────

def _termpipe_server_entry() -> dict:
    """Build the MCP server entry for termpipe-mcp."""
    python = sys.executable
    # Prefer the pipx-installed termf binary if available
    termf_bin = shutil.which("termf") or shutil.which("termcp")
    if termf_bin:
        cmd  = [termf_bin, "mcp"]
    else:
        cmd  = [python, "-m", "termpipe_mcp.server"]
    return {
        "command": cmd[0],
        "args":    cmd[1:],
        "env":     {},
    }


def _register_in_client(client_name: str, config_path: Path) -> str:
    """
    Upsert the termpipe-mcp entry into a client's MCP server config.
    Returns a status string: "registered" | "already_present" | "skipped:<reason>"
    """
    if not config_path.parent.exists():
        return f"skipped:parent dir missing ({config_path.parent})"

    entry = _termpipe_server_entry()

    # Load existing config or start fresh
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text())
        except json.JSONDecodeError:
            return "skipped:config file is invalid JSON"
    else:
        data = {}

    # Claude Desktop uses {"mcpServers": {...}}
    # iFlow / Gemini / opencode use {"mcpServers": {...}} or {"servers": {...}}
    # We normalise to mcpServers for all of them
    key = "mcpServers"
    if key not in data:
        data[key] = {}

    if "termpipe-mcp" in data[key]:
        return "already_present"

    data[key]["termpipe-mcp"] = entry

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, indent=2))
    return "registered"


def register_mcp_clients(auto: bool = False) -> dict[str, str]:
    """
    Detect installed MCP clients and register termpipe-mcp with each.

    auto=True  → register without prompting (used from bootstrap / CI)
    auto=False → prompt user for each detected client

    Returns dict of {client_name: status}.
    """
    results = {}
    paths   = _mcp_client_paths()

    for client, path in paths.items():
        detected = path.exists() or path.parent.exists()
        if not detected:
            results[client] = "not_detected"
            continue

        if not auto:
            ans = input(f"  Register with {client}? ({path}) [Y/n]: ").strip().lower()
            if ans == "n":
                results[client] = "skipped:user"
                continue

        status = _register_in_client(client, path)
        results[client] = status

    return results


# ── Autostart setup ───────────────────────────────────────────────────────────

def _setup_systemd() -> str:
    """Install and enable a systemd user service for the FastAPI backend."""
    service_dir  = HOME / ".config" / "systemd" / "user"
    service_file = service_dir / "termpipe-mcp.service"

    python   = sys.executable
    termf    = shutil.which("termf") or shutil.which("termcp") or f"{python} -m termpipe_mcp.fastapi_server"
    exec_cmd = f"{termf} server" if shutil.which("termf") or shutil.which("termcp") else \
               f"{python} -m termpipe_mcp.fastapi_server"

    unit = f"""[Unit]
Description=TermPipe MCP FastAPI Backend
After=network.target

[Service]
Type=simple
ExecStart={exec_cmd}
Restart=on-failure
RestartSec=3
Environment=PATH={os.environ.get('PATH', '/usr/bin:/bin')}

[Install]
WantedBy=default.target
"""
    service_dir.mkdir(parents=True, exist_ok=True)
    service_file.write_text(unit)

    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, capture_output=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", "termpipe-mcp"], check=True, capture_output=True)
        return "enabled"
    except subprocess.CalledProcessError as e:
        return f"failed:{e.stderr.decode().strip()[:120]}"


def _setup_launchd() -> str:
    """Install a launchd plist for the FastAPI backend on macOS."""
    plist_dir  = HOME / "Library" / "LaunchAgents"
    plist_file = plist_dir / "com.termpipe.mcp.plist"

    python  = sys.executable
    termf   = shutil.which("termf") or shutil.which("termcp")
    if termf:
        prog_args = [termf, "server"]
    else:
        prog_args = [python, "-m", "termpipe_mcp.fastapi_server"]

    args_xml = "\n".join(f"        <string>{a}</string>" for a in prog_args)
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.termpipe.mcp</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{get_config_dir()}/logs/server.log</string>
    <key>StandardErrorPath</key>
    <string>{get_config_dir()}/logs/server.err</string>
</dict>
</plist>
"""
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_file.write_text(plist)

    try:
        subprocess.run(["launchctl", "load", "-w", str(plist_file)], check=True, capture_output=True)
        return "loaded"
    except subprocess.CalledProcessError as e:
        return f"failed:{e.stderr.decode().strip()[:120]}"


def _setup_windows_task() -> str:
    """Register a Windows Task Scheduler task for the FastAPI backend."""
    python = sys.executable
    termf  = shutil.which("termf") or shutil.which("termcp")
    if termf:
        action = f'"{termf}" server'
    else:
        action = f'"{python}" -m termpipe_mcp.fastapi_server'

    cmd = [
        "schtasks", "/create", "/f",
        "/tn",  "TermPipeMCP",
        "/tr",  action,
        "/sc",  "ONLOGON",
        "/rl",  "HIGHEST",
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return "registered"
    except subprocess.CalledProcessError as e:
        return f"failed:{e.stderr.decode().strip()[:120]}"


def setup_autostart(auto: bool = False) -> str:
    """Set up autostart for the FastAPI backend. Returns status string."""
    if not auto:
        ans = input("  Set up autostart for the FastAPI backend? [Y/n]: ").strip().lower()
        if ans == "n":
            return "skipped:user"

    if IS_LINUX:
        return _setup_systemd()
    elif IS_MAC:
        return _setup_launchd()
    elif IS_WIN:
        return _setup_windows_task()
    return "skipped:unsupported_platform"


# ── GTT detection ─────────────────────────────────────────────────────────────

def check_gtt() -> dict:
    gtt = shutil.which("gtt")
    gttd = shutil.which("gttd")
    result = {"gtt": gtt or "not found", "gttd": gttd or "not found"}
    if gtt:
        try:
            out = subprocess.run([gtt, "--version"], capture_output=True, text=True, timeout=3)
            result["version"] = out.stdout.strip() or out.stderr.strip()
        except Exception:
            result["version"] = "unknown"
    return result


# ── Main entry point ──────────────────────────────────────────────────────────

def run(auto: bool = False, quiet: bool = False) -> dict:
    """
    Run full first-run setup. Returns a results dict.

    auto=True  → non-interactive (for CI or bootstrap)
    quiet=True → suppress print output
    """
    def p(*args): 
        if not quiet:
            print(*args)

    results = {}

    p()
    p("╔══════════════════════════════════════════════════════════╗")
    p("║          TermPipe MCP — First-Run Setup                  ║")
    p(f"║  Platform: {SYSTEM:<46} ║")
    p("╚══════════════════════════════════════════════════════════╝")
    p()

    # 1. Directories
    p("📁 Creating config directories...")
    created = ensure_dirs()
    for d in created:
        p(f"   ✅ Created: {d}")
    if not created:
        p(f"   ✓  Already exists: {get_config_dir()}")
    results["dirs"] = created

    # 2. Config scaffolding
    p()
    p("📄 Scaffolding config files...")
    cfg_written      = scaffold_config()
    settings_written = scaffold_settings()
    p(f"   config.json:   {'✅ written' if cfg_written else '✓  exists'}")
    p(f"   settings.json: {'✅ written' if settings_written else '✓  exists'}")
    results["config_written"]   = cfg_written
    results["settings_written"] = settings_written

    # 3. GTT detection
    p()
    p("🔍 Checking gtt...")
    gtt_info = check_gtt()
    p(f"   gtt:  {gtt_info['gtt']}")
    p(f"   gttd: {gtt_info['gttd']}")
    if "version" in gtt_info:
        p(f"   ver:  {gtt_info['version']}")
    results["gtt"] = gtt_info

    # 4. MCP client registration
    p()
    p("🔌 MCP client registration...")
    client_results = register_mcp_clients(auto=auto)
    for client, status in client_results.items():
        icon = "✅" if status == "registered" else "✓ " if status == "already_present" else "⚠️ "
        p(f"   {icon} {client}: {status}")
    results["clients"] = client_results

    # 5. Autostart
    p()
    p("🚀 Autostart setup...")
    autostart = setup_autostart(auto=auto)
    icon = "✅" if autostart in ("enabled", "loaded", "registered") else \
           "✓ " if "already" in autostart else "⚠️ "
    p(f"   {icon} {autostart}")
    results["autostart"] = autostart

    p()
    p("════════════════════════════════════════════════════════════")
    p("✅ First-run setup complete!")
    p(f"   Config dir: {get_config_dir()}")
    p()
    p("Next: run 'termcp setup' to enter your iFlow API key.")
    p("════════════════════════════════════════════════════════════")
    p()

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="TermPipe MCP first-run setup")
    parser.add_argument("--auto",  action="store_true", help="Non-interactive mode")
    parser.add_argument("--quiet", action="store_true", help="Suppress output")
    args = parser.parse_args()
    run(auto=args.auto, quiet=args.quiet)
