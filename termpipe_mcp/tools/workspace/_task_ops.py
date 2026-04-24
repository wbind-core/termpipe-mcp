"""
Task management tools — create, update, query, set_status.
"""
from typing import Optional
from pathlib import Path

from ._db import (
    _db_create_task, _db_get_task, _db_list_tasks, _db_update_task_status,
    _db_update_task, _db_check_deps_done, _db_get_cc_session_num,
    _render_task_md, VALID_STATUSES, VALID_PRIORITIES, VALID_TASK_TYPES,
    _db_read_artifact,
)
from ._artifacts import _upsert_artifact
from ._bus import ATYPE_TASK
from ._registry import _registry_ws_id
from ._phase import set_phase, ws_id_from_cwd


def workspace_task_create(
    cwd: str,
    title: str,
    description: Optional[str] = None,
    priority: str = "medium",
    task_type: Optional[str] = None,
    completion_requirements: Optional[str] = None,
    output_format: Optional[str] = None,
    depends_on: Optional[str] = None,
    tags: Optional[str] = None,
    notes: Optional[str] = None,
) -> str:
    """
    Create a structured task in the workspace task DB.

    Args:
        cwd:                     Project directory.
        title:                   Short task title (required).
        description:             Detailed description of what needs doing.
        priority:                critical | high | medium (default) | low
        task_type:               research | implementation | test | review | config | docs | fix
        completion_requirements: Explicit, measurable criteria for done.
        output_format:           What the deliverable looks like.
        depends_on:              Comma-separated task IDs that must be done first (e.g. "1,2,3").
        tags:                    Comma-separated tags (e.g. "auth,backend").
        notes:                   Any extra notes or context.
    """
    ws_id = _registry_ws_id(cwd)
    if not ws_id:
        return f"[workspace_task_create] No workspace for {cwd}"

    if priority not in VALID_PRIORITIES:
        return f"[workspace_task_create] Invalid priority '{priority}'. Use: {', '.join(sorted(VALID_PRIORITIES))}"
    if task_type and task_type not in VALID_TASK_TYPES:
        return f"[workspace_task_create] Invalid task_type '{task_type}'. Use: {', '.join(sorted(VALID_TASK_TYPES))}"

    dep_ids = []
    if depends_on:
        try:
            dep_ids = [int(x.strip()) for x in depends_on.split(",") if x.strip()]
        except ValueError:
            return f"[workspace_task_create] depends_on must be comma-separated integers, got: {depends_on}"

    tag_list = [t.strip() for t in tags.split(",")] if tags else []

    task = _db_create_task(
        ws_id=ws_id,
        title=title,
        description=description,
        priority=priority,
        task_type=task_type,
        completion_requirements=completion_requirements,
        output_format=output_format,
        depends_on=dep_ids,
        tags=tag_list,
        notes=notes,
    )

    # Re-render and publish task.md from DB
    project_name = Path(cwd).name
    all_tasks = _db_list_tasks(ws_id)
    md = _render_task_md(all_tasks)
    r = _upsert_artifact(ws_id, project_name, ATYPE_TASK, "task.md", md,
                         summary=f"Added task [{task['id']}]: {title}")

    return (
        f"✅ Task [{task['id']}] created  priority={priority}  status=todo\n"
        f"   title   : {title}\n"
        + (f"   type    : {task_type}\n" if task_type else "")
        + (f"   deps    : {dep_ids}\n" if dep_ids else "")
        + (f"   done when: {completion_requirements}\n" if completion_requirements else "")
        + (f"   output  : {output_format}\n" if output_format else "")
        + f"\ntask.md  v{r['version']}  bus={'✓' if r['bus_ok'] else '✗'}"
    )


def workspace_task_update(
    cwd: str,
    action: str,
    item_text: Optional[str] = None,
    item_id: Optional[int] = None,
    summary: Optional[str] = None,
) -> str:
    """
    Mutate task.md for the active workspace (legacy markdown-based).

    Actions:
      add         — append a new task item (requires item_text)
      done        — mark item [x] complete  (requires item_id)
      in_progress — mark item [/] in-progress (requires item_id)
      todo        — mark item [ ] todo       (requires item_id)
      replace     — replace full content     (requires item_text as full markdown)

    Args:
        cwd:       Project directory.
        action:    add | done | in_progress | todo | replace
        item_text: New task text (add) or full markdown (replace).
        item_id:   Numeric id from <!-- id: N --> comment (status changes).
        summary:   Optional summary stored in metadata.
    """
    from ._task import _next_task_id, _set_task_status

    ws_id = _registry_ws_id(cwd)
    if not ws_id:
        return f"[workspace_task_update] No workspace for {cwd}"

    project_name = Path(cwd).name
    row = _db_read_artifact(ws_id, "task.md")
    content = row["content"] if row else ""

    if action == "add":
        if not item_text:
            return "[workspace_task_update] item_text required for action=add"
        new_id = _next_task_id(content)
        content = content.rstrip("\n") + \
                  f"\n- [ ] {item_text.strip()} <!-- id: {new_id} -->\n"

    elif action in ("done", "in_progress", "todo"):
        if item_id is None:
            return f"[workspace_task_update] item_id required for action={action}"
        content, found = _set_task_status(content, item_id, action)
        if not found:
            return f"[workspace_task_update] item id:{item_id} not found in task.md"

    elif action == "replace":
        if not item_text:
            return "[workspace_task_update] item_text required for action=replace"
        content = item_text

    else:
        return (
            f"[workspace_task_update] Unknown action '{action}'. "
            "Use: add | done | in_progress | todo | replace"
        )

    r = _upsert_artifact(ws_id, project_name, ATYPE_TASK, "task.md",
                         content, summary=summary)
    return (
        f"task.md updated  v{r['version']}  action={action}  "
        f"bus={'✓' if r['bus_ok'] else '✗'}\n\n{content}"
    )


def workspace_task_set_status(
    cwd: str,
    task_id: int,
    status: str,
    notes: Optional[str] = None,
) -> str:
    """
    Update the status of a structured task, with dependency enforcement.

    Statuses: todo | in_progress | needs_review | done | blocked

    Transitions to in_progress / needs_review / done are blocked if any
    depends_on tasks are not yet done. When status=done, the current
    context-core session_num is automatically stamped.

    Args:
        cwd:     Project directory.
        task_id: Numeric task ID.
        status:  New status value.
        notes:   Optional note stored on the task.
    """
    ws_id = _registry_ws_id(cwd)
    if not ws_id:
        return f"[workspace_task_set_status] No workspace for {cwd}"

    if status not in VALID_STATUSES:
        return f"[workspace_task_set_status] Invalid status '{status}'. Use: {', '.join(sorted(VALID_STATUSES))}"

    task = _db_get_task(ws_id, task_id)
    if not task:
        return f"[workspace_task_set_status] Task [{task_id}] not found."

    # Dependency enforcement for forward transitions
    if status in ("in_progress", "needs_review", "done"):
        blockers = _db_check_deps_done(ws_id, task_id)
        if blockers:
            lines = "\n".join(
                f"  [{b['id']}] {b['title']}  (status={b['status']})" for b in blockers
            )
            return (
                f"BLOCKED — cannot set task [{task_id}] to '{status}'.\n"
                f"These dependencies are not done yet:\n{lines}\n\n"
                f"Complete them first, or set status='blocked' to flag the hold."
            )

    # Stamp context-core session when marking done
    session_done = None
    if status == "done":
        session_done = _db_get_cc_session_num(ws_id)

    if notes:
        _db_update_task(ws_id, task_id, notes=notes)

    updated = _db_update_task_status(ws_id, task_id, status, session_done=session_done)

    # Advance phase state machine
    if status == "in_progress":
        set_phase(ws_id, "task_in_progress", current_task_id=task_id)
    elif status == "needs_review":
        set_phase(ws_id, "task_needs_review", current_task_id=task_id)
    elif status == "done":
        set_phase(ws_id, "approved")  # back to approved, ready for next task
    # blocked/todo don't change the high-level phase

    # Re-render task.md
    project_name = Path(cwd).name
    all_tasks = _db_list_tasks(ws_id)
    md = _render_task_md(all_tasks)
    r = _upsert_artifact(ws_id, project_name, ATYPE_TASK, "task.md", md,
                         summary=f"Task [{task_id}] → {status}")

    wire_note = f"  context-core session_done={session_done}\n" if session_done else ""
    return (
        f"✅ Task [{task_id}] → {status}\n"
        f"   title: {updated['title']}\n"
        + wire_note
        + f"\ntask.md  v{r['version']}  bus={'✓' if r['bus_ok'] else '✗'}"
    )


def workspace_task_query(
    cwd: str,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    task_type: Optional[str] = None,
) -> str:
    """
    List and filter structured tasks from the workspace DB.

    Results are sorted: needs_review → blocked → in_progress → todo → done,
    then by priority (critical first).

    Args:
        cwd:       Project directory.
        status:    Filter by status.
        priority:  Filter by priority.
        task_type: Filter by type.
    """
    ws_id = _registry_ws_id(cwd)
    if not ws_id:
        return f"[workspace_task_query] No workspace for {cwd}"

    tasks = _db_list_tasks(ws_id, status=status, priority=priority, task_type=task_type)

    if not tasks:
        filters = " | ".join(filter(None, [status, priority, task_type]))
        return f"No tasks found" + (f" matching ({filters})" if filters else "") + "."

    STATUS_ICON = {
        "done":         "✅",
        "in_progress":  "🔄",
        "needs_review": "⏳",
        "blocked":      "🚫",
        "todo":         "📝",
    }
    PRIORITY_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪"}

    # Summary line
    from collections import Counter
    counts = Counter(t["status"] for t in tasks)
    summary = "  ·  ".join(f"{v} {k}" for k, v in counts.items())

    lines = [f"📋 TASKS ({len(tasks)})  {summary}\n"]
    for t in tasks:
        si = STATUS_ICON.get(t["status"], "·")
        pi = PRIORITY_ICON.get(t["priority"], "")
        tt = f"  [{t['task_type']}]" if t.get("task_type") else ""
        lines.append(f"  {si} [{t['id']}] {pi} {t['title']}{tt}")
        if t.get("completion_requirements"):
            lines.append(f"       ✓ {t['completion_requirements']}")
        if t.get("depends_on"):
            lines.append(f"       ← needs {t['depends_on']}")
        if t.get("session_done"):
            lines.append(f"       📎 cc session {t['session_done']}")

    return "\n".join(lines)
