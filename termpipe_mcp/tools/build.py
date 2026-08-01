"""
Build & deploy tool for TermPipe MCP Server.

Handles pre-build steps, compilation, process teardown, binary installation,
service management, and optional .desktop file creation.
"""

import subprocess
import json
import re
import time
from pathlib import Path
from typing import Optional

# ── Language build configs ────────────────────────────────────────────────────

_LANG = {
    "go": {
        "pre_build": lambda cwd: "go mod tidy" if (Path(cwd) / "go.mod").exists() else None,
        "cmd":       lambda cwd, _: f"go build -o {Path(cwd).name} .",
        "entry":     lambda cwd: str(Path(cwd) / Path(cwd).name),
        "installs":  True,   # binary goes to ~/.local/bin
    },
    "rust": {
        "pre_build": lambda cwd: None,
        "cmd":       lambda cwd, _: "cargo build --release",
        "entry":     lambda cwd: str(Path(cwd) / "target" / "release" / Path(cwd).name),
        "installs":  True,
    },
    "typescript": {
        "pre_build": lambda cwd: "npm install" if (Path(cwd) / "package.json").exists() else None,
        "cmd":       lambda cwd, _: "npm run build",
        "entry":     None,
        "installs":  False,
    },
    "python": {
        "pre_build": lambda cwd: None,
        "cmd":       lambda cwd, mgr: (
            "pipx install -e . --force" if mgr == "pipx"
            else "pip install -e . --break-system-packages"
        ),
        "entry":     None,
        "installs":  False,
    },
}

# ── Output truncation limits ──────────────────────────────────────────────────

_TRUNCATE = {"go": None, "rust": None, "typescript": 3000, "python": 3000}

# ── Service registry ──────────────────────────────────────────────────────────
# cwd substring → { services: [...], kill_patterns: [...] }

_SERVICE_REGISTRY = {
    "kernclip/bus": {
        "services":      ["kbd", "kernclip-busd"],
        "kill_patterns": ["kbd", "kernclip-busd", "^kb$", "/home/craig/.local/bin/kb"],
    },
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(cmd: str, cwd: str, timeout: int = 120) -> tuple[str, str, int]:
    try:
        r = subprocess.run(
            cmd, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        return "", f"Timed out after {timeout}s", 1
    except Exception as e:
        return "", str(e), 1


def _find_registry_entry(cwd: str) -> Optional[dict]:
    for key, entry in _SERVICE_REGISTRY.items():
        if key in cwd:
            return entry
    return None


def _service_is_active(name: str) -> bool:
    _, _, rc = _run(f"systemctl --user is-active --quiet {name}", "/tmp", timeout=5)
    return rc == 0


def _service_is_enabled(name: str) -> bool:
    _, _, rc = _run(f"systemctl --user is-enabled --quiet {name}", "/tmp", timeout=5)
    return rc == 0


def _service_exists(name: str) -> tuple[bool, str]:
    """Check if a systemd user service exists via cond --service-list <name>."""
    out, _, rc = _run(f"cond --service-list {name}", "/tmp")
    if rc != 0 or not out.strip():
        return False, ""
    try:
        data = json.loads(re.sub(r'\x1B[^m]*m', '', out))
        services = data if isinstance(data, list) else data.get("services", [])
        for svc in services:
            n = svc.get("name", "") or svc.get("unit", "") or str(svc)
            if name in n:
                return True, n
    except Exception:
        if name in out:
            return True, name
    return False, ""


def _stop_services(names: list[str], lines: list[str]) -> None:
    for name in names:
        if _service_is_active(name):
            lines.append(f"🛑 Stopping {name}...")
            _, err, rc = _run(f"systemctl --user stop {name}", "/tmp", timeout=10)
            if rc != 0:
                lines.append(f"  ⚠️  Could not stop {name}: {err.strip()}")


def _kill_patterns(patterns: list[str], lines: list[str]) -> None:
    lines.append("💀 Killing remaining processes...")
    for pat in patterns:
        _run(f"pkill -9 -f '{pat}' 2>/dev/null || true", "/tmp", timeout=5)


def _install_binary(src: Path, lines: list[str]) -> None:
    bin_dir = Path.home() / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    dest = bin_dir / src.name
    _, err, rc = _run(f"install -m 755 {src} {dest}", str(src.parent), timeout=10)
    if rc != 0:
        lines.append(f"⚠️  Failed to install {src.name} to {bin_dir}: {err.strip()}")
    else:
        lines.append(f"📦 Installed {src.name} → {dest}")


def _start_services(names: list[str], lines: list[str]) -> None:
    for name in names:
        if _service_is_enabled(name):
            lines.append(f"🔄 Starting {name}...")
            _, err, rc = _run(f"systemctl --user start {name}", "/tmp", timeout=15)
            if rc != 0:
                lines.append(f"  ⚠️  Failed to start {name}: {err.strip()}")
                # show last few log lines
                out, _, _ = _run(
                    f"journalctl --user -u {name} -n 5 --no-pager", "/tmp", timeout=5
                )
                if out.strip():
                    lines.append(out.strip())
            else:
                lines.append(f"  ✅ {name} started")


def _create_service(name: str, exec_start: str) -> tuple[bool, str]:
    unit = f"""[Unit]
Description={name}
After=default.target
StartLimitIntervalSec=0

[Service]
Type=simple
ExecStart={exec_start}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""
    unit_path = Path.home() / ".config" / "systemd" / "user" / f"{name}.service"
    unit_path.parent.mkdir(parents=True, exist_ok=True)
    unit_path.write_text(unit)
    _, err, rc = _run(
        f"systemctl --user daemon-reload && systemctl --user enable --now {name}",
        "/tmp", timeout=15
    )
    if rc != 0:
        return False, err
    return True, str(unit_path)


def _write_desktop_file(name: str, desktop_entry: dict, lines: list[str]) -> None:
    required = {"Name", "Exec"}
    if not required.issubset(desktop_entry.keys()):
        lines.append(f"⚠️  desktop_entry missing required keys: {required - desktop_entry.keys()}")
        return

    apps_dir = Path.home() / ".local" / "share" / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    dest = apps_dir / f"{name}.desktop"

    fields = {
        "Type":       "Application",
        "Version":    "1.0",
        "Name":       desktop_entry["Name"],
        "Exec":       desktop_entry["Exec"],
        "Icon":       desktop_entry.get("Icon", ""),
        "Comment":    desktop_entry.get("Comment", ""),
        "Categories": desktop_entry.get("Categories", "Utility;"),
        "Terminal":   str(desktop_entry.get("Terminal", False)).lower(),
    }

    content = "[Desktop Entry]\n" + "\n".join(f"{k}={v}" for k, v in fields.items() if v != "") + "\n"
    dest.write_text(content)
    _run(f"chmod +x {dest}", str(apps_dir), timeout=5)
    lines.append(f"🖥️  Desktop entry written: {dest}")


# ── Tool registration ─────────────────────────────────────────────────────────

def register_tools(mcp):

    @mcp.tool()
    def build(
        cwd: str,
        language: str,
        manager: Optional[str] = None,
        register_service: bool = False,
        entry_point: Optional[str] = None,
        desktop_entry: Optional[dict] = None,
    ) -> str:
        """
        Build and deploy a project in a live terminal. Handles pre-build steps,
        compilation, service detection, restart, and optional service registration.

        Args:
            cwd:              Absolute path to the project source root.
            language:         One of: go, rust, python, typescript
            manager:          Python only — "pip" (default) or "pipx"
            register_service: If True and no service exists, create + enable one.
            entry_point:      Binary/script path for service ExecStart.
                              Auto-derived for Go/Rust. Required for Python/TS
                              if register_service=True.
            desktop_entry:    Optional dict to create a .desktop file. Required keys:
                              Name, Exec. Optional: Icon, Comment, Categories, Terminal.
                              Omit for CLI tools.

        Examples:
            build("/home/craig/kernclip/bus", "go")
            build("/home/craig/termpipe-mcp", "python", manager="pipx")
            build("/home/craig/myapp", "rust", register_service=True)
            build("/home/craig/webapp", "typescript", entry_point="node dist/index.js")
            build("/home/craig/myapp", "go", desktop_entry={"Name": "MyApp", "Exec": "myapp", "Icon": "myapp"})
        """
        lang = language.lower().strip()
        cwd  = str(Path(cwd).expanduser().resolve())

        if lang not in _LANG:
            return (
                f"[build] Unknown language: {language}\n"
                f"Supported: {', '.join(_LANG.keys())}"
            )

        cfg   = _LANG[lang]
        mgr   = (manager or "pip").lower()
        lines = [f"🔨 Building ({lang}) {Path(cwd).name}..."]

        # ── Teardown: stop services + kill processes ───────────────────────────
        reg = _find_registry_entry(cwd)
        if reg:
            _stop_services(reg["services"], lines)
            _kill_patterns(reg["kill_patterns"], lines)
            time.sleep(1)

        # ── Pre-build ─────────────────────────────────────────────────────────
        pre_cmd = cfg["pre_build"](cwd)
        if pre_cmd:
            lines.append(f"📦 Pre-build: {pre_cmd}")
            stdout, stderr, rc = _run(pre_cmd, cwd, timeout=60)
            output_pre = (stdout + stderr).strip()
            if rc != 0:
                lines.append(f"⚠️  Pre-build warning: {output_pre[:500]}")
            elif output_pre:
                lines.append(output_pre[:500])

        # ── Build ─────────────────────────────────────────────────────────────
        build_cmd = cfg["cmd"](cwd, mgr)
        lines.append(f"⚙️  {build_cmd}")

        stdout, stderr, rc = _run(build_cmd, cwd, timeout=120)
        output = (stdout + stderr).strip()

        limit = _TRUNCATE.get(lang)
        if limit and len(output) > limit:
            output = output[:limit] + f"\n... [truncated at {limit} chars]"

        if rc != 0 or any(
            x in output.lower() for x in ["error:", "build failed", "cannot", "undefined:"]
        ):
            lines.append("❌ Build failed")
            if output:
                lines.append(output)
            return "\n".join(lines)

        lines.append("✅ Build succeeded")
        if output.strip():
            lines.append(output.strip()[:1000])

        # ── Derive entry point ────────────────────────────────────────────────
        if not entry_point and cfg["entry"]:
            entry_point = cfg["entry"](cwd)

        # ── Install binary to ~/.local/bin ────────────────────────────────────
        if cfg["installs"]:
            # entry_point is the full path to the built binary
            binary = Path(entry_point) if entry_point else Path(cwd) / Path(cwd).name
            if binary.exists():
                _install_binary(binary, lines)
            else:
                lines.append(f"⚠️  Binary not found at {binary}, skipping install")

        # ── Service management ────────────────────────────────────────────────
        if reg:
            _start_services(reg["services"], lines)
        else:
            # Fall back to single-service logic (name = project dir name)
            svc_name = Path(cwd).name
            exists, matched = _service_exists(svc_name)

            if exists:
                lines.append(f"🔁 Restarting service: {matched or svc_name}")
                _, err, rc2 = _run(f"systemctl --user restart {svc_name}", cwd, timeout=15)
                if rc2 != 0:
                    lines.append(f"❌ Restart failed: {err.strip()}")
                else:
                    lines.append("✅ Service restarted")

            elif register_service:
                if not entry_point:
                    lines.append(
                        "⚠️  register_service=True but entry_point not provided and could not be derived.\n"
                        "    Pass entry_point='<absolute path or command>' and retry."
                    )
                else:
                    lines.append(f"🆕 Registering new user service: {svc_name}")
                    ok, info = _create_service(svc_name, entry_point)
                    if ok:
                        lines.append(f"✅ Service created and started: {info}")
                        _SERVICE_REGISTRY[cwd] = {
                            "services": [svc_name],
                            "kill_patterns": [svc_name],
                        }
                    else:
                        lines.append(f"❌ Service creation failed: {info}")

        # ── .desktop file ─────────────────────────────────────────────────────
        if desktop_entry:
            _write_desktop_file(Path(cwd).name, desktop_entry, lines)

        return "\n".join(lines)
