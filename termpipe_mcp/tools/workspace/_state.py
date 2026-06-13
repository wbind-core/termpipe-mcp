"""
workspace.state.json — portable, filesystem-only state file.

Written alongside artifacts in ~/Documents/TermPipe/Workspaces/<project>/
so any model in any environment can orient itself without SQLite or context_core.

Schema:
{
  "ws_id":           str,
  "project":         str,
  "cwd":             str,
  "phase":           str,
  "plan_status":     str,
  "current_task_id": int | null,
  "current_task":    str | null,   -- task title
  "override_active": bool,
  "override_scope":  str | null,
  "write_op_count":  int,
  "summary":         str,          -- LMS-generated natural language status
  "updated_at":      str           -- ISO8601
}
"""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import urllib.request
import urllib.error

from ._bus import _ARTIFACTS_ROOT

_OMNI_LOCAL_URL = "http://127.0.0.1:9920/v1/chat/completions"


def _omni_query(prompt: str, system: str = "", max_tokens: int = 256, temperature: float = 0.3, timeout: int = 45) -> Optional[str]:
    """Synchronous inference via OmniProxy local endpoint."""
    import json as _j
    payload = _j.dumps({
        "messages": (
            [{"role": "system", "content": system}] if system else []
        ) + [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode()
    try:
        req = urllib.request.Request(
            _OMNI_LOCAL_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = _j.loads(resp.read())
            return data["choices"][0]["message"]["content"]
    except Exception:
        return None


def _omni_query_async(prompt: str, callback, system: str = "", max_tokens: int = 256, temperature: float = 0.3) -> None:
    """Fire-and-forget inference. Calls callback(result) on completion."""
    def _run():
        result = _omni_query(prompt, system=system, max_tokens=max_tokens, temperature=temperature)
        try:
            callback(result)
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()

_STATE_FILE = "workspace.state.json"

# ---------------------------------------------------------------------------
# Build prompt for LMS summary generation
# ---------------------------------------------------------------------------

def _build_summary_prompt(
    project: str,
    phase: str,
    plan_status: str,
    plan_goal: str,
    task_title: Optional[str],
    task_status: Optional[str],
    recent_tasks: list[dict],
) -> str:
    done   = [t["title"] for t in recent_tasks if t.get("status") == "done"]
    active = [t["title"] for t in recent_tasks if t.get("status") == "in_progress"]
    todo   = [t["title"] for t in recent_tasks if t.get("status") == "todo"]

    parts = [
        f"Project: {project}",
        f"Phase: {phase} | Plan status: {plan_status}",
        f"Goal: {plan_goal}" if plan_goal else "",
        f"Active task: {task_title} [{task_status}]" if task_title else "No active task.",
        f"Done: {', '.join(done)}" if done else "",
        f"Todo: {', '.join(todo[:3])}" if todo else "",
    ]
    context = "\n".join(p for p in parts if p)

    return (
        f"{context}\n\n"
        "Write a single paragraph (2-3 sentences) summarising: what has been completed, "
        "what is currently in progress, and what comes next. "
        "Be specific and concise. No bullet points. No preamble."
    )


# ---------------------------------------------------------------------------
# Core write — call after every phase/state mutation
# ---------------------------------------------------------------------------

def write_state(
    ws_id: str,
    project_name: str,
    phase_row: dict,
    plan_status: str = "unknown",
    plan_goal: str = "",
    task_title: Optional[str] = None,
    task_status: Optional[str] = None,
    recent_tasks: Optional[list] = None,
    summary: Optional[str] = None,    # pass pre-generated or None to generate
    async_summary: bool = False,       # True = fire-and-forget LMS call
) -> Path:
    """
    Write workspace.state.json. If summary is None and LMS is available:
      - async_summary=False → generate synchronously (for phase transitions)
      - async_summary=True  → fire-and-forget, write placeholder then update
    Returns path to the written file.
    """
    d = _ARTIFACTS_ROOT / project_name
    d.mkdir(parents=True, exist_ok=True)
    state_path = d / _STATE_FILE

    state = {
        "ws_id":           ws_id,
        "project":         project_name,
        "phase":           phase_row.get("phase", "unknown"),
        "plan_status":     plan_status,
        "current_task_id": phase_row.get("current_task_id"),
        "current_task":    task_title,
        "override_active": bool(phase_row.get("override_active", False)),
        "override_scope":  phase_row.get("override_scope"),
        "write_op_count":  phase_row.get("write_op_count", 0),
        "summary":         summary or "",
        "updated_at":      datetime.now(timezone.utc).isoformat(),
    }

    def _write(s: dict) -> None:
        state_path.write_text(json.dumps(s, indent=2), encoding="utf-8")

    if summary is not None:
        # Caller supplied summary — just write
        _write(state)
        return state_path

    # Build LMS prompt
    prompt = _build_summary_prompt(
        project=project_name,
        phase=state["phase"],
        plan_status=plan_status,
        plan_goal=plan_goal,
        task_title=task_title,
        task_status=task_status,
        recent_tasks=recent_tasks or [],
    )

    if async_summary:
        # Write immediately with empty summary, update when LMS responds
        _write(state)
        def _on_result(result: Optional[str]) -> None:
            if result:
                try:
                    existing = json.loads(state_path.read_text(encoding="utf-8"))
                    existing["summary"] = result
                    existing["updated_at"] = datetime.now(timezone.utc).isoformat()
                    state_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
                except Exception:
                    pass
        _omni_query_async(prompt, callback=_on_result, max_tokens=200)
    else:
        # Synchronous — generate then write
        result = _omni_query(prompt, max_tokens=200)
        state["summary"] = result or ""
        _write(state)

    return state_path


# ---------------------------------------------------------------------------
# Read — used by phase_briefing and any external consumer
# ---------------------------------------------------------------------------

def read_state(project_name: str) -> Optional[dict]:
    """Read workspace.state.json for a project. Returns None if missing/corrupt."""
    path = _ARTIFACTS_ROOT / project_name / _STATE_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Backfill — called once at session start for workspaces missing state files
# ---------------------------------------------------------------------------

def backfill_all_states() -> None:
    """
    For every workspace dir that has artifacts but no workspace.state.json,
    generate one from SQLite. Silent — never raises.
    """
    if not _ARTIFACTS_ROOT.exists():
        return

    for project_dir in _ARTIFACTS_ROOT.iterdir():
        if not project_dir.is_dir():
            continue
        state_path = project_dir / _STATE_FILE
        if state_path.exists():
            continue
        project_name = project_dir.name

        # Need ws_id — look up via registry
        try:
            from ._registry import _registry_all_workspaces, _ws_db_path
            all_ws = _registry_all_workspaces()
            ws_id = next(
                (w["workspace_id"] for w in all_ws
                 if w.get("display_name") == project_name),
                None
            )
            if not ws_id:
                continue

            from ._phase import get_phase
            from ._task import _get_plan_status
            from ._db import _db_get_task, _db_list_tasks, _db_read_artifact

            phase_row  = get_phase(ws_id)
            plan_status = _get_plan_status(ws_id)
            task_id    = phase_row.get("current_task_id")
            task_title = None
            task_status = None
            plan_goal  = ""

            if task_id:
                t = _db_get_task(ws_id, task_id)
                if t:
                    task_title  = t.get("title")
                    task_status = t.get("status")

            plan_art = _db_read_artifact(ws_id, "implementation_plan.md")
            if plan_art:
                content = plan_art.get("content", "")
                # First non-empty non-heading line as goal approximation
                for line in content.splitlines():
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
                async_summary=True,   # fire-and-forget, don't block startup
            )
        except Exception:
            continue
