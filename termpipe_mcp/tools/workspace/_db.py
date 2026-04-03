"""
SQLite artifact DB helpers — read, write, list workspace artifacts.
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone

from ._registry import _ws_db_path

# ---------------------------------------------------------------------------
# Per-workspace DB — artifacts table
# ---------------------------------------------------------------------------

def _ensure_artifacts_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS artifacts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            artifact_type TEXT NOT NULL,
            name          TEXT NOT NULL,
            content       TEXT NOT NULL DEFAULT '',
            version       INTEGER NOT NULL DEFAULT 0,
            summary       TEXT,
            updated_at    TEXT NOT NULL,
            UNIQUE(name)
        )
    """)
    conn.commit()


def _get_ws_conn(ws_id: str) -> sqlite3.Connection | None:
    db = _ws_db_path(ws_id)
    if not db.exists():
        return None
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    _ensure_artifacts_table(conn)
    return conn


def _db_read_artifact(ws_id: str, name: str) -> dict | None:
    conn = _get_ws_conn(ws_id)
    if not conn:
        return None
    row = conn.execute("SELECT * FROM artifacts WHERE name = ?", (name,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _db_write_artifact(
    ws_id: str,
    artifact_type: str,
    name: str,
    content: str,
    summary: str | None = None,
) -> int:
    """Upsert artifact, bump version, return new version number."""
    conn = _get_ws_conn(ws_id)
    if not conn:
        raise RuntimeError(f"No workspace DB for ws_{ws_id}")
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT version FROM artifacts WHERE name = ?", (name,)
    ).fetchone()
    if existing:
        new_version = existing["version"] + 1
        conn.execute(
            "UPDATE artifacts SET content=?, version=?, summary=?, updated_at=? WHERE name=?",
            (content, new_version, summary, now, name),
        )
    else:
        new_version = 0
        conn.execute(
            "INSERT INTO artifacts (artifact_type, name, content, version, summary, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (artifact_type, name, content, new_version, summary, now),
        )
    conn.commit()
    conn.close()
    return new_version


def _db_list_artifacts(ws_id: str) -> list[dict]:
    conn = _get_ws_conn(ws_id)
    if not conn:
        return []
    rows = conn.execute(
        "SELECT artifact_type, name, version, summary, updated_at "
        "FROM artifacts ORDER BY artifact_type"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


