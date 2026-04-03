"""
Registry helpers — look up and list workspaces in context_core.
"""
import sqlite3
from pathlib import Path

try:
    from termpipe_mcp.helpers import TERMPIPE_DIR
    from termpipe_mcp.tools.workspace._bus import _CC_REGISTRY, _CC_WORKSPACES
except ImportError:
    from helpers import TERMPIPE_DIR
    from _bus import _CC_REGISTRY, _CC_WORKSPACES

# ---------------------------------------------------------------------------
# context_core registry helpers
# ---------------------------------------------------------------------------

def _registry_ws_id(project_path: str) -> str | None:
    """Look up workspace_id for a project path from context_core registry."""
    if not _CC_REGISTRY.exists():
        return None
    try:
        conn = sqlite3.connect(str(_CC_REGISTRY))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT workspace_id FROM workspace_folders WHERE folder_path = ?",
            (str(Path(project_path).resolve()),)
        ).fetchone()
        conn.close()
        return row["workspace_id"] if row else None
    except Exception:
        return None


def _registry_all_workspaces() -> list[dict]:
    if not _CC_REGISTRY.exists():
        return []
    try:
        conn = sqlite3.connect(str(_CC_REGISTRY))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT workspace_id, display_name, last_accessed FROM workspaces "
            "ORDER BY last_accessed DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _ws_db_path(ws_id: str) -> Path:
    return _CC_WORKSPACES / f"ws_{ws_id}" / "workspace.db"

