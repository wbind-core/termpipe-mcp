"""
surgical/workspace_gate.py — Workspace phase gate for all write tools.

Every write-path tool calls workspace_gate(path) BEFORE doing any work.
If the path falls under a registered workspace that is not in an
write-unlocked phase, the gate returns a blocking error string.
If no workspace is found for the path (e.g. editing files outside any
project), the gate passes through silently — it does not block work
that was never under workspace management.

Usage in a write tool:
    from .workspace_gate import workspace_gate

    block = workspace_gate(path)
    if block:
        return block
    # ... proceed with write

Design notes
------------
- Gate resolution walks UP from the file's directory looking for a
  registered workspace. This means editing any file under a project
  root will be caught, even deeply nested ones.
- The gate imports only _registry and _phase from the workspace module
  tree to keep the dependency surface minimal and avoid circular imports.
- Failures in gate resolution (DB missing, import error, etc.) are
  treated as pass-through — the gate never blocks due to its own errors.
"""

from __future__ import annotations

from pathlib import Path


def workspace_gate(path: str) -> str | None:
    """
    Check whether a write operation on `path` is permitted under the
    workspace phase state machine.

    Returns:
        None        — write is allowed (approved phase, override active,
                      or path is not under any managed workspace)
        str         — a ⛔ block message; the caller must return this
                      string immediately without performing the write
    """
    try:
        from termpipe_mcp.tools.workspace._registry import _registry_ws_id
        from termpipe_mcp.tools.workspace._phase import check_write_gate
    except ImportError:
        # Workspace module not available — pass through
        return None

    ws_id = _resolve_ws_id(path, _registry_ws_id)
    if ws_id is None:
        # File is not under any registered workspace — no gate applies
        return None

    result = check_write_gate(ws_id)
    if result["allowed"]:
        return None

    return result["reason"]


def workspace_gate_consume(path: str) -> None:
    """
    Called AFTER a successful write to consume a 'once' override if active.
    Also records the write op for checkpoint tracking.
    Safe to call unconditionally — silently no-ops if not under a workspace.
    """
    try:
        from termpipe_mcp.tools.workspace._registry import _registry_ws_id
        from termpipe_mcp.tools.workspace._phase import consume_once_override, checkpoint_suffix
    except ImportError:
        return

    ws_id = _resolve_ws_id(path, _registry_ws_id)
    if ws_id is None:
        return

    consume_once_override(ws_id)


def workspace_gate_checkpoint(path: str) -> str:
    """
    Called AFTER a successful write. Returns a checkpoint prompt string
    if the write-op counter threshold has been reached, else ''.
    """
    try:
        from termpipe_mcp.tools.workspace._registry import _registry_ws_id
        from termpipe_mcp.tools.workspace._phase import checkpoint_suffix
    except ImportError:
        return ""

    ws_id = _resolve_ws_id(path, _registry_ws_id)
    if ws_id is None:
        return ""

    return checkpoint_suffix(ws_id)


def _resolve_ws_id(path: str, lookup_fn) -> str | None:
    """
    Walk up the directory tree from `path` looking for a registered
    workspace. Returns the first ws_id found, or None.

    We walk up rather than just checking the immediate parent because
    files can be deeply nested inside a project (e.g.
    /home/craig/myproject/src/pkg/module.py should still be gated if
    /home/craig/myproject is a registered workspace).
    """
    try:
        p = Path(path).expanduser().resolve()
        # Start from the file's directory (or the path itself if it's a dir)
        candidate = p if p.is_dir() else p.parent
        # Walk up to filesystem root
        while True:
            ws_id = lookup_fn(str(candidate))
            if ws_id:
                return ws_id
            parent = candidate.parent
            if parent == candidate:
                # Reached filesystem root
                break
            candidate = parent
    except Exception:
        pass
    return None
