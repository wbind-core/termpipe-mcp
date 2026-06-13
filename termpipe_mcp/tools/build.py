"""
Build & deploy tool for TermPipe MCP Server.

Uses termf_live_exec as the execution engine so builds run in a real
terminal with live output streaming via the kb bus.

Model provides: cwd + language (+ optional manager for Python).
Tool handles: pre-build steps, build command, service detection, restart/register.
"""

import subprocess
import json
import re
from pathlib import Path
from typing import Optional

from termpipe_mcp.tools.termf import get_terminator


# ── Language build configs ────────────────────────────────────────────────────

_LANG = {
    "go": {
        "pre_build": lambda cwd: "go mod tidy" if (Path(cwd) / "go.mod").exists() else None,
        "cmd":       lambda cwd, _: f"go build -o {Path(cwd).name} .",
        "entry":     lambda cwd: str(Path(cwd) / Path(cwd).name),
    },
    "rust": {
        "pre_build": lambda cwd: None,
        "cmd":       lambda cwd, _: "cargo build --release",
        "entry":     lambda cwd: str(Path(cwd) / "target" / "release" / Path(cwd).name),
    },
    "typescript": {
        "pre_build": lambda cwd: "npm install" if (Path(cwd) / "package.json").exists() else None,
        "cmd":       lambda cwd, _: "npm run build",
        "entry":     None,  # model must supply entry_point
    },
    "python": {
        "pre_build": lambda cwd: None,
        "cmd":       lambda cwd, mgr: (
            "pipx install -e . --force" if mgr == "pipx"
            else "pip install -e . --break-system-packages"
        ),
        "entry":     None,  # model must supply entry_point
    },
}

# ── Output truncation limits ──────────────────────────────────────────────────

_TRUNCATE = {"go": None, "rust": None, "typescript": 3000, "python": 3000}

# ── Service restart registry (cwd substring → service name) ──────────────────

_SERVICE_REGISTRY = {
    "kernclip/bus": "kbd",
}


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


def _find_registered_service(cwd: str) -> Optional[str]:
    for key, svc in _SERVICE_REGISTRY.items():
        if key in cwd:
            return svc
    return None


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
        # fallback: plain text search
        if name in out:
            return True, name
    return False, ""


def _create_service(name: str, exec_start: str) -> tuple[bool, str]:
    """Create and enable a systemd user service."""
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


def register_tools(mcp):

    @mcp.tool()
    def build(
        cwd: str,
        language: str,
        manager: Optional[str] = None,
        register_service: bool = False,
        entry_point: Optional[str] = None,
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

        Examples:
            build("/home/craig/kernclip/bus", "go")
            build("/home/craig/termpipe-mcp", "python", manager="pipx")
            build("/home/craig/myapp", "rust", register_service=True)
            build("/home/craig/webapp", "typescript", entry_point="node dist/index.js")
        """
        lang = language.lower().strip()
        cwd  = str(Path(cwd).expanduser().resolve())

        if lang not in _LANG:
            return (
                f"[build] Unknown language: {language}\n"
                f"Supported: {', '.join(_LANG.keys())}"
            )

        cfg      = _LANG[lang]
        mgr      = (manager or "pip").lower()
        lines    = [f"🔨 Building ({lang}) {Path(cwd).name}..."]
        terminator = get_terminator()

        # ── Pre-build ─────────────────────────────────────────────────────────
        pre_cmd = cfg["pre_build"](cwd)
        if pre_cmd:
            lines.append(f"📦 Pre-build: {pre_cmd}")
            result = terminator.execute_live(pre_cmd, workspace_dir=cwd)
            if not result["success"]:
                lines.append(f"⚠️  Pre-build warning: {result.get('error', '')}")
            elif result["output"].strip():
                lines.append(result["output"].strip()[:500])

        # ── Build ─────────────────────────────────────────────────────────────
        build_cmd = cfg["cmd"](cwd, mgr)
        lines.append(f"⚙️  {build_cmd}")

        result = terminator.execute_live(build_cmd, workspace_dir=cwd, timeout_ms=120000)
        output = result.get("output", "") or ""

        limit = _TRUNCATE.get(lang)
        if limit and len(output) > limit:
            output = output[:limit] + f"\n... [truncated at {limit} chars]"

        if not result["success"] or any(
            x in output.lower() for x in ["error:", "build failed", "cannot", "undefined:"]
        ):
            lines.append("❌ Build failed")
            if output: lines.append(output)
            return "\n".join(lines)

        lines.append("✅ Build succeeded")
        if output.strip(): lines.append(output.strip()[:1000])

        # ── Derive entry point ────────────────────────────────────────────────
        if not entry_point and cfg["entry"]:
            entry_point = cfg["entry"](cwd)

        # ── Service detection + restart/register ──────────────────────────────
        svc_name = _find_registered_service(cwd) or Path(cwd).name
        exists, matched = _service_exists(svc_name)

        if exists:
            lines.append(f"🔁 Restarting service: {matched or svc_name}")
            _, err, rc = _run(f"systemctl --user restart {svc_name}", cwd, timeout=15)
            if rc != 0:
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
                    _SERVICE_REGISTRY[cwd] = svc_name
                else:
                    lines.append(f"❌ Service creation failed: {info}")

        return "\n".join(lines)
