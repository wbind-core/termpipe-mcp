"""
Session state machine for workspace tool enforcement.

Phase flow:
  no_plan → plan_draft → pending_approval
  → approved → task_in_progress → task_needs_review → approved (loop)

Write tools are only unlocked in task_in_progress (or with an active override).
Override scopes: 'once' (consumed after one write op), 'session' (until session_end).
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ._registry import _ws_db_path, _registry_ws_id

# ---------------------------------------------------------------------------
# Valid phases
# ---------------------------------------------------------------------------

PHASES = {
    "no_plan",
    "plan_draft",
    "pending_approval",
    "approved",
    "task_in_progress",
    "task_needs_review",
}

WRITE_UNLOCKED_PHASES = PHASES  # gate disabled — all phases allow writes

NEXT_ACTION = {
    "no_plan": (
        "No implementation plan exists yet.\n"
        "   ➡️  REQUIRED: Call workspace_plan_update(cwd=..., content=..., status='active') "
        "before any write tools can be used."
    ),
    "plan_draft": (
        "Implementation plan is drafted but not yet reviewed.\n"
        "   ➡️  REQUIRED: Call workspace_request_review(cwd=...) to submit for approval."
    ),
    "pending_approval": (
        "Plan submitted — awaiting human approval.\n"
        "   ➡️  REQUIRED: Call workspace_await_approval(cwd=...) to block until approved."
    ),
    "approved": (
        "Plan approved. Create or select a task to begin work.\n"
        "   ➡️  REQUIRED: Call workspace_task_create(cwd=...) or "
        "workspace_task_set_status(cwd=..., task_id=..., status='in_progress')."
    ),
    "task_in_progress": (
        "Task in progress — write tools UNLOCKED.\n"
        "   ➡️  When done: Call workspace_task_set_status(cwd=..., task_id=..., status='needs_review')."
    ),
    "task_needs_review": (
        "Task complete — awaiting review.\n"
        "   ➡️  REQUIRED: Call workspace_task_request_review(cwd=..., task_id=...) "
        "then workspace_await_task_approval(...)."
    ),
}

CHECKPOINT_INTERVAL = 5


# ---------------------------------------------------------------------------
# DB bootstrap
# ---------------------------------------------------------------------------

def _ensure_phase_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workspace_phase (
            id               INTEGER PRIMARY KEY CHECK (id = 1),
            phase            TEXT NOT NULL DEFAULT 'no_plan',
            current_task_id  INTEGER,
            override_scope   TEXT,
            override_active  INTEGER NOT NULL DEFAULT 0,
            write_op_count   INTEGER NOT NULL DEFAULT 0,
            last_checkpoint  INTEGER NOT NULL DEFAULT 0,
            updated_at       TEXT NOT NULL
        )
    """)
    conn.execute("""
        INSERT OR IGNORE INTO workspace_phase (id, phase, updated_at)
        VALUES (1, 'no_plan', ?)
    """, (datetime.now(timezone.utc).isoformat(),))
    conn.commit()


def _get_conn(ws_id: str) -> sqlite3.Connection:
    db = _ws_db_path(ws_id)
    if not db.exists():
        raise RuntimeError(f"No workspace DB for ws_{ws_id}. Run workspace_init first.")
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    _ensure_phase_tables(conn)
    return conn


# ---------------------------------------------------------------------------
# Phase read / write
# ---------------------------------------------------------------------------

def get_phase(ws_id: str) -> dict:
    conn = _get_conn(ws_id)
    row = conn.execute("SELECT * FROM workspace_phase WHERE id = 1").fetchone()
    conn.close()
    return dict(row)


def set_phase(ws_id: str, phase: str, current_task_id: int | None = None) -> dict:
    if phase not in PHASES:
        raise ValueError(f"Invalid phase: {phase!r}. Must be one of {sorted(PHASES)}")
    conn = _get_conn(ws_id)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE workspace_phase SET phase=?, current_task_id=?, updated_at=? WHERE id=1",
        (phase, current_task_id, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM workspace_phase WHERE id = 1").fetchone()
    conn.close()
    result = dict(row)
    _emit_state(ws_id, result, async_summary=False)
    return result


# ---------------------------------------------------------------------------
# Write-op counter + checkpoint
# ---------------------------------------------------------------------------

def record_write_op(ws_id: str) -> dict:
    """
    Increment write_op_count. Returns:
      checkpoint_due: bool  — True if model should be prompted to summarize
      write_op_count: int
    """
    conn = _get_conn(ws_id)
    row = conn.execute(
        "SELECT write_op_count, last_checkpoint FROM workspace_phase WHERE id=1"
    ).fetchone()
    new_count = (row["write_op_count"] or 0) + 1
    last_cp   = row["last_checkpoint"] or 0
    checkpoint_due = (new_count - last_cp) >= CHECKPOINT_INTERVAL
    new_last_cp = new_count if checkpoint_due else last_cp
    conn.execute(
        "UPDATE workspace_phase SET write_op_count=?, last_checkpoint=?, updated_at=? WHERE id=1",
        (new_count, new_last_cp, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    updated_row = dict(conn.execute("SELECT * FROM workspace_phase WHERE id=1").fetchone())
    conn.close()
    # Async — write ops fire frequently, never block the tool response
    _emit_state(ws_id, updated_row, async_summary=True)
    return {"write_op_count": new_count, "checkpoint_due": checkpoint_due}


CHECKPOINT_PROMPT = (
    "\n\n⚠️  SESSION CHECKPOINT ({count} write ops): "
    "Call workspace_doc_update or session_end with a 2-3 sentence summary "
    "of what has been accomplished. Do not skip this."
)


def checkpoint_suffix(ws_id: str) -> str:
    """Call after a write op. Returns checkpoint prompt string if due, else ''."""
    result = record_write_op(ws_id)
    if result["checkpoint_due"]:
        return CHECKPOINT_PROMPT.format(count=result["write_op_count"])
    return ""


# ---------------------------------------------------------------------------
# Override management
# ---------------------------------------------------------------------------

def set_override(ws_id: str, scope: str) -> None:
    if scope not in ("once", "session"):
        raise ValueError(f"Invalid override scope: {scope!r}")
    conn = _get_conn(ws_id)
    conn.execute(
        "UPDATE workspace_phase SET override_active=1, override_scope=?, updated_at=? WHERE id=1",
        (scope, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    row = dict(conn.execute("SELECT * FROM workspace_phase WHERE id=1").fetchone())
    conn.close()
    _emit_state(ws_id, row, async_summary=False)


def clear_override(ws_id: str) -> None:
    conn = _get_conn(ws_id)
    conn.execute(
        "UPDATE workspace_phase SET override_active=0, override_scope=NULL, updated_at=? WHERE id=1",
        (datetime.now(timezone.utc).isoformat(),),
    )
    conn.commit()
    row = dict(conn.execute("SELECT * FROM workspace_phase WHERE id=1").fetchone())
    conn.close()
    _emit_state(ws_id, row, async_summary=False)


def consume_once_override(ws_id: str) -> None:
    """If override scope is 'once', clear it after the write op completes."""
    conn = _get_conn(ws_id)
    row = conn.execute(
        "SELECT override_scope FROM workspace_phase WHERE id=1"
    ).fetchone()
    if row and row["override_scope"] == "once":
        conn.execute(
            "UPDATE workspace_phase SET override_active=0, override_scope=NULL, updated_at=? WHERE id=1",
            (datetime.now(timezone.utc).isoformat(),),
        )
        conn.commit()
        updated = dict(conn.execute("SELECT * FROM workspace_phase WHERE id=1").fetchone())
        conn.close()
        _emit_state(ws_id, updated, async_summary=False)
    else:
        conn.close()


# ---------------------------------------------------------------------------
# Gate check — called by every write tool wrapper
# ---------------------------------------------------------------------------

def check_write_gate(ws_id: str) -> dict:
    """
    Returns:
      allowed: bool
      reason:  str | None  (set if blocked)
      phase:   str
      override_active: bool
    """
    row = get_phase(ws_id)
    phase = row["phase"]
    override_active = bool(row["override_active"])

    if phase in WRITE_UNLOCKED_PHASES or override_active:
        return {"allowed": True, "reason": None, "phase": phase, "override_active": override_active}

    return {
        "allowed": False,
        "reason": (
            f"⛔ WRITE BLOCKED [phase: {phase}]\n"
            f"{NEXT_ACTION.get(phase, 'Complete the required workspace steps first.')}\n\n"
            "If you have a legitimate reason to bypass this gate, "
            "call workspace_override(cwd=..., reason=...) to request human approval via notification."
        ),
        "phase": phase,
        "override_active": False,
    }


# ---------------------------------------------------------------------------
# Tactical briefing fragment — injected into list_tools output
# ---------------------------------------------------------------------------

def phase_briefing(ws_id: str) -> str:
    """Return formatted briefing string for injection into list_tools.
    Reads workspace.state.json first (portable, filesystem-only).
    Falls back to SQLite and self-heals the missing file.
    """
    phase     = "unknown"
    plan_st   = "unknown"
    task_id   = None
    task_title = None
    override  = False
    override_scope = None
    op_count  = 0
    summary   = ""

    # --- Primary: read from state file ---
    try:
        project_name = _project_name_for(ws_id)
        if project_name:
            from ._state import read_state
            state = read_state(project_name)
            if state:
                phase          = state.get("phase", "unknown")
                plan_st        = state.get("plan_status", "unknown")
                task_id        = state.get("current_task_id")
                task_title     = state.get("current_task")
                override       = bool(state.get("override_active", False))
                override_scope = state.get("override_scope")
                op_count       = state.get("write_op_count", 0)
                summary        = state.get("summary", "")
            else:
                raise FileNotFoundError("state file missing")
    except Exception:
        # --- Fallback: SQLite + self-heal ---
        try:
            row = get_phase(ws_id)
            phase          = row["phase"]
            task_id        = row["current_task_id"]
            override       = bool(row["override_active"])
            override_scope = row.get("override_scope")
            op_count       = row["write_op_count"]
            from ._task import _get_plan_status
            plan_st = _get_plan_status(ws_id)
            if task_id:
                from ._db import _db_get_task
                t = _db_get_task(ws_id, task_id)
                if t:
                    task_title = t.get("title")
            # self-heal
            _emit_state(ws_id, row, async_summary=True)
        except Exception:
            return ""

    task_note = f"  (task #{task_id})" if task_id else ""
    override_note = ""
    if override:
        override_note = f"\n   ⚠️  Override active ({override_scope or 'once'}) — write tools temporarily unlocked."

    task_line = ""
    if task_id and task_title:
        task_line = f"\n   📋 Task #{task_id}: {task_title}"
    elif task_id:
        task_line = f"\n   📋 Task #{task_id}"

    summary_line = f"\n   💬 {summary}" if summary else ""

    return (
        f"\n{'='*60}\n"
        f"⚙️  WORKSPACE PHASE: {phase.upper()}{task_note}"
        f"  |  plan: {plan_st}"
        f"{task_line}"
        f"{summary_line}\n"
        f"{NEXT_ACTION.get(phase, '')}{override_note}\n"
        f"   Write ops this session: {op_count}\n"
        f"{'='*60}\n"
    )


# ---------------------------------------------------------------------------
# Session-approve bus listener
# ---------------------------------------------------------------------------

_TOPIC_SESSION_APPROVE = "termpipe.workspace.session_approve"
_active_listeners: set[str] = set()   # ws_ids with a running listener thread


def _start_session_approve_listener(ws_id: str, project_name: str = "") -> bool:
    """
    Start a daemon thread that watches termpipe.workspace.session_approve.
    When a message arrives, calls set_override(ws_id, 'session') — dropping
    all write gates for the remainder of the session.
    Also fires a desktop notification with an 'Approve Session' button.
    Safe to call multiple times; only one thread per ws_id ever runs.
    Returns True if a new thread was started, False if already running.
    """
    if ws_id in _active_listeners:
        return False
    _active_listeners.add(ws_id)

    # Fire desktop notification with approve button
    try:
        import subprocess
        label = project_name or ws_id[:8]
        subprocess.Popen([
            "kb", "notify", f"TermPipe — {label}",
            "--body", "Click to drop all write gates for this session.",
            "--button", f"Approve Session:{_TOPIC_SESSION_APPROVE}",
            "--urgency", "normal",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

    def _listen():
        try:
            from ._bus import _bus_poll
            result = _bus_poll([_TOPIC_SESSION_APPROVE], timeout_ms=7_200_000)  # 2hr TTL
            if result:
                set_override(ws_id, "session")
        except Exception:
            pass
        finally:
            _active_listeners.discard(ws_id)

    import threading
    t = threading.Thread(target=_listen, daemon=True, name=f"session-approve-{ws_id}")
    t.start()
    return True


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def ws_id_from_cwd(cwd: str) -> str | None:
    return _registry_ws_id(cwd)


# ---------------------------------------------------------------------------
# Internal — resolve project name from registry for state file writes
# ---------------------------------------------------------------------------

def _project_name_for(ws_id: str) -> Optional[str]:
    """Look up display_name for a ws_id from the registry. Returns None on miss."""
    try:
        from ._registry import _registry_all_workspaces
        for w in _registry_all_workspaces():
            if w.get("workspace_id") == ws_id:
                return w.get("display_name")
    except Exception:
        pass
    return None


def _emit_state(ws_id: str, phase_row: dict, async_summary: bool = False) -> None:
    """
    Write workspace.state.json after any phase mutation.
    Pulls plan_status, task info, and plan goal from DB.
    Silently no-ops if project_name cannot be resolved.
    """
    try:
        project_name = _project_name_for(ws_id)
        if not project_name:
            return

        from ._task import _get_plan_status
        from ._db import _db_get_task, _db_list_tasks, _db_read_artifact
        from ._state import write_state

        plan_status = _get_plan_status(ws_id)
        task_id     = phase_row.get("current_task_id")
        task_title  = None
        task_status = None
        plan_goal   = ""

        if task_id:
            t = _db_get_task(ws_id, task_id)
            if t:
                task_title  = t.get("title")
                task_status = t.get("status")

        plan_art = _db_read_artifact(ws_id, "implementation_plan.md")
        if plan_art:
            for line in (plan_art.get("content") or "").splitlines():
                stripped = line.strip().lstrip("#").strip()
                if stripped:
                    plan_goal = stripped
                    break

        recent_tasks = _db_list_tasks(ws_id)[:8]

        write_state(
            ws_id=ws_id,
            project_name=project_name,
            phase_row=phase_row,
            plan_status=plan_status,
            plan_goal=plan_goal,
            task_title=task_title,
            task_status=task_status,
            recent_tasks=recent_tasks,
            async_summary=async_summary,
        )
    except Exception:
        pass
