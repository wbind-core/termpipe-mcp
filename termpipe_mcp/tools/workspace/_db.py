"""
SQLite artifact DB helpers — read, write, list workspace artifacts.
Also owns the structured tasks table introduced in the Upgrade 1 refactor.
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


# ---------------------------------------------------------------------------
# Per-workspace DB — structured tasks table
# ---------------------------------------------------------------------------

def _ensure_tasks_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            title                   TEXT NOT NULL,
            description             TEXT,
            priority                TEXT NOT NULL DEFAULT 'medium',
            status                  TEXT NOT NULL DEFAULT 'todo',
            task_type               TEXT,
            completion_requirements TEXT,
            output_format           TEXT,
            depends_on              TEXT NOT NULL DEFAULT '[]',
            tags                    TEXT NOT NULL DEFAULT '[]',
            notes                   TEXT,
            session_done            INTEGER,
            created_at              TEXT NOT NULL,
            updated_at              TEXT NOT NULL
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
    _ensure_tasks_table(conn)
    return conn


# ---------------------------------------------------------------------------
# Artifact helpers (unchanged API)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Task helpers — structured CRUD
# ---------------------------------------------------------------------------

VALID_STATUSES  = {"todo", "in_progress", "needs_review", "done", "blocked"}
VALID_PRIORITIES = {"critical", "high", "medium", "low"}
VALID_TASK_TYPES = {"research", "implementation", "test", "review", "config", "docs", "fix"}


def _db_create_task(
    ws_id: str,
    title: str,
    description: str | None = None,
    priority: str = "medium",
    task_type: str | None = None,
    completion_requirements: str | None = None,
    output_format: str | None = None,
    depends_on: list[int] | None = None,
    tags: list[str] | None = None,
    notes: str | None = None,
) -> dict:
    """Insert a new task. Returns the created task as dict."""
    conn = _get_ws_conn(ws_id)
    if not conn:
        raise RuntimeError(f"No workspace DB for ws_{ws_id}")
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        """
        INSERT INTO tasks
            (title, description, priority, status, task_type,
             completion_requirements, output_format,
             depends_on, tags, notes, created_at, updated_at)
        VALUES (?, ?, ?, 'todo', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            description,
            priority,
            task_type,
            completion_requirements,
            output_format,
            json.dumps(depends_on or []),
            json.dumps(tags or []),
            notes,
            now,
            now,
        ),
    )
    conn.commit()
    task_id = cursor.lastrowid
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return _task_row_to_dict(row)


def _db_get_task(ws_id: str, task_id: int) -> dict | None:
    conn = _get_ws_conn(ws_id)
    if not conn:
        return None
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return _task_row_to_dict(row) if row else None


def _db_list_tasks(
    ws_id: str,
    status: str | None = None,
    priority: str | None = None,
    task_type: str | None = None,
) -> list[dict]:
    """Return tasks, optionally filtered. Always sorted: blocked/needs_review first, then by priority."""
    conn = _get_ws_conn(ws_id)
    if not conn:
        return []
    clauses = []
    params: list = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if priority:
        clauses.append("priority = ?")
        params.append(priority)
    if task_type:
        clauses.append("task_type = ?")
        params.append(task_type)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    priority_order = "CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END"
    status_order   = "CASE status WHEN 'needs_review' THEN 0 WHEN 'blocked' THEN 1 WHEN 'in_progress' THEN 2 WHEN 'todo' THEN 3 ELSE 4 END"
    rows = conn.execute(
        f"SELECT * FROM tasks {where} ORDER BY {status_order}, {priority_order}, id",
        params,
    ).fetchall()
    conn.close()
    return [_task_row_to_dict(r) for r in rows]


def _db_update_task_status(
    ws_id: str,
    task_id: int,
    status: str,
    session_done: int | None = None,
) -> dict | None:
    """
    Update task status. If status=done and session_done is provided,
    stamps the context-core session_num — this is the missing wire.
    Returns updated task dict or None if not found.
    """
    conn = _get_ws_conn(ws_id)
    if not conn:
        return None
    now = datetime.now(timezone.utc).isoformat()
    if session_done is not None:
        conn.execute(
            "UPDATE tasks SET status=?, session_done=?, updated_at=? WHERE id=?",
            (status, session_done, now, task_id),
        )
    else:
        conn.execute(
            "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
            (status, now, task_id),
        )
    conn.commit()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return _task_row_to_dict(row) if row else None


def _db_update_task(ws_id: str, task_id: int, **fields) -> dict | None:
    """Partial update of any task fields. Returns updated task or None."""
    allowed = {
        "title", "description", "priority", "task_type",
        "completion_requirements", "output_format",
        "depends_on", "tags", "notes",
    }
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return _db_get_task(ws_id, task_id)
    conn = _get_ws_conn(ws_id)
    if not conn:
        return None
    now = datetime.now(timezone.utc).isoformat()
    # JSON-encode list fields
    for list_field in ("depends_on", "tags"):
        if list_field in updates and isinstance(updates[list_field], list):
            updates[list_field] = json.dumps(updates[list_field])
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [now, task_id]
    conn.execute(
        f"UPDATE tasks SET {set_clause}, updated_at = ? WHERE id = ?", values
    )
    conn.commit()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return _task_row_to_dict(row) if row else None


def _db_check_deps_done(ws_id: str, task_id: int) -> list[dict]:
    """
    Returns list of incomplete dependency tasks blocking this one.
    Empty list means all deps are done (or there are none) — safe to proceed.
    """
    task = _db_get_task(ws_id, task_id)
    if not task or not task["depends_on"]:
        return []
    blockers = []
    for dep_id in task["depends_on"]:
        dep = _db_get_task(ws_id, dep_id)
        if dep and dep["status"] != "done":
            blockers.append(dep)
    return blockers


def _db_get_cc_session_num(ws_id: str) -> int | None:
    """
    Look up the current context-core session_num for this workspace.
    Reads from ~/.context-core/workspaces/ws_<id>/workspace.db.
    Returns None if context-core DB not found or no sessions yet.
    """
    try:
        cc_db = Path.home() / ".context-core" / "workspaces" / f"ws_{ws_id}" / "workspace.db"
        if not cc_db.exists():
            return None
        conn = sqlite3.connect(str(cc_db))
        row = conn.execute("SELECT MAX(session_num) FROM work_sessions").fetchone()
        conn.close()
        return row[0] if row and row[0] is not None else None
    except Exception:
        return None


def _task_row_to_dict(row) -> dict:
    """Convert a sqlite3.Row to a clean dict with parsed JSON fields."""
    d = dict(row)
    for field in ("depends_on", "tags"):
        if isinstance(d.get(field), str):
            try:
                d[field] = json.loads(d[field])
            except Exception:
                d[field] = []
    return d


def _render_task_md(tasks: list[dict]) -> str:
    """
    Render tasks list as task.md markdown. This is the auto-generated
    view — the DB is the source of truth, not this file.
    """
    if not tasks:
        return "<!-- No tasks yet. Use workspace_task_create() to add tasks. -->\n"

    STATUS_MARKER = {
        "done":         "[x]",
        "in_progress":  "[/]",
        "needs_review": "[?]",
        "blocked":      "[!]",
        "todo":         "[ ]",
    }
    PRIORITY_ICON = {
        "critical": "🔴",
        "high":     "🟠",
        "medium":   "🟡",
        "low":      "⚪",
    }

    lines = []
    for t in tasks:
        marker   = STATUS_MARKER.get(t["status"], "[ ]")
        priority = PRIORITY_ICON.get(t["priority"], "")
        ttype    = f"  [{t['task_type']}]" if t.get("task_type") else ""
        deps     = f"  ← needs {t['depends_on']}" if t.get("depends_on") else ""
        cr       = f"\n    ✓ done when: {t['completion_requirements']}" if t.get("completion_requirements") else ""
        lines.append(
            f"- {marker} {priority} **{t['title']}** <!-- id: {t['id']} -->{ttype}{deps}{cr}"
        )
    return "\n".join(lines) + "\n"
