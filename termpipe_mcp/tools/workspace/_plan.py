"""
Plan and document management tools — init, plan, walkthrough, doc update.
"""
from typing import Optional
from pathlib import Path
from datetime import datetime, timezone

from ._db import _db_read_artifact
from ._bus import (
    ATYPE_TASK, ATYPE_PLAN, ATYPE_WALK, ATYPE_OTHER,
    PLAN_DRAFT,
)
from ._artifacts import _upsert_artifact
from ._registry import _registry_ws_id
from ._task import _pack_summary, _unpack_summary, _get_plan_status
from ._phase import set_phase, ws_id_from_cwd


def workspace_init(
    cwd: str,
    goal: str,
    task_items: Optional[str] = None,
) -> str:
    """
    Initialise workspace artifacts for a project.

    Creates task.md, implementation_plan.md, and walkthrough.md under
    ~/Documents/TermPipe/Workspaces/<project>/, persists them to the
    context_core per-workspace DB, and publishes all three to kc-bus.

    Args:
        cwd:        Absolute path to the project directory.
        goal:       One-sentence description of the current task/goal.
        task_items: Optional newline-separated task strings to seed task.md.
    """
    from ._bus import _ARTIFACTS_ROOT, _bus_pub
    import json

    ws_id = _registry_ws_id(cwd)
    if not ws_id:
        return (
            f"[workspace_init] No context_core workspace found for {cwd}.\n"
            "Call list_tools(cwd=...) first to register the workspace."
        )

    project_name = Path(cwd).name

    # Build task.md
    items = []
    if task_items:
        for i, line in enumerate(task_items.strip().splitlines(), start=1):
            line = line.strip().lstrip("-").strip()
            if line:
                items.append(f"- [ ] {line} <!-- id: {i} -->")
    if not items:
        items = [f"- [ ] Define tasks for: {goal} <!-- id: 1 -->"]
    task_content = "\n".join(items) + "\n"

    plan_content = (
        f"# {goal}\n\n"
        "## Goal Description\n"
        f"{goal}\n\n"
        "## Proposed Changes\n\n"
        "<!-- Add implementation details here -->\n"
    )

    walk_content = (
        f"# {project_name} Walkthrough\n\n"
        "## Key Accomplishments\n\n"
        "<!-- Document progress here -->\n"
    )

    results = []
    for atype, name, content in [
        (ATYPE_TASK, "task.md",                task_content),
        (ATYPE_PLAN, "implementation_plan.md", plan_content),
        (ATYPE_WALK, "walkthrough.md",          walk_content),
    ]:
        r = _upsert_artifact(ws_id, project_name, atype, name, content,
                             summary=f"Initial {name} for: {goal}")
        results.append(
            f"  ✅ {name}  v{r['version']}  "
            f"bus={'✓' if r['bus_ok'] else '✗'}  {r['file_path']}"
        )

    _bus_pub(_TOPIC_ACTIVE, json.dumps({
        "ws_id": ws_id, "project": project_name, "path": cwd,
        "resumed_at": datetime.now(timezone.utc).isoformat(),
    }), mime="application/json")

    # Initialise phase state machine
    set_phase(ws_id, "no_plan")

    return (
        f"workspace_init ✅  ws_{ws_id}  project={project_name}\n"
        + "\n".join(results)
        + f"\n\nArtifacts dir: {_ARTIFACTS_ROOT / project_name}"
    )


def workspace_plan_update(
    cwd: str,
    content: str,
    summary: Optional[str] = None,
    status: str = PLAN_DRAFT,
) -> str:
    """
    Replace implementation_plan.md for the active workspace.

    Args:
        cwd:     Project directory.
        content: Full markdown content for the implementation plan.
        summary: Optional one-line summary stored in metadata.
        status:  Plan lifecycle state: draft | pending_approval | approved | rejected
    """
    from ._bus import PLAN_DRAFT

    ws_id = _registry_ws_id(cwd)
    if not ws_id:
        return f"[workspace_plan_update] No workspace for {cwd}"

    project_name = Path(cwd).name
    packed = _pack_summary(summary, status)
    r = _upsert_artifact(ws_id, project_name, ATYPE_PLAN,
                         "implementation_plan.md", content, summary=packed)

    # Advance phase to plan_draft
    set_phase(ws_id, "plan_draft")

    bus_flag = '✓' if r['bus_ok'] else '✗'
    base_msg = (
        f"implementation_plan.md updated  v{r['version']}  status={status}  "
        f"bus={bus_flag}  {r['file_path']}"
    )
    if status == PLAN_DRAFT:
        return (
            base_msg
            + f"\n\n⚠️  Plan is in status='{status}'. "
              f"Call workspace_request_review(cwd) "
              f"then workspace_await_approval(cwd) before proceeding to execution."
        )
    return base_msg


def workspace_walkthrough_update(
    cwd: str,
    content: str,
    summary: Optional[str] = None,
) -> str:
    """
    Replace walkthrough.md for the active workspace.

    Args:
        cwd:     Project directory.
        content: Full markdown content for the walkthrough.
        summary: Optional one-line summary.
    """
    ws_id = _registry_ws_id(cwd)
    if not ws_id:
        return f"[workspace_walkthrough_update] No workspace for {cwd}"

    project_name = Path(cwd).name
    r = _upsert_artifact(ws_id, project_name, ATYPE_WALK,
                         "walkthrough.md", content, summary=summary)
    return (
        f"walkthrough.md updated  v{r['version']}  "
        f"bus={'✓' if r['bus_ok'] else '✗'}  {r['file_path']}"
    )


def workspace_doc_update(
    cwd: str,
    name: str,
    content: str,
    summary: Optional[str] = None,
) -> str:
    """
    Create or update an arbitrary markdown artifact.

    Args:
        cwd:     Project directory.
        name:    Filename, e.g. 'dbus_analysis.md'.
        content: Full markdown content.
        summary: Optional one-line summary.
    """
    if not name.endswith(".md"):
        name = name + ".md"

    ws_id = _registry_ws_id(cwd)
    if not ws_id:
        return f"[workspace_doc_update] No workspace for {cwd}"

    project_name = Path(cwd).name
    r = _upsert_artifact(ws_id, project_name, ATYPE_OTHER,
                         name, content, summary=summary)
    return (
        f"{name} updated  v{r['version']}  "
        f"bus={'✓' if r['bus_ok'] else '✗'}  "
        f"topic={r['topic']}  {r['file_path']}"
    )


# Topic used in workspace_init - import here to avoid circular
_TOPIC_ACTIVE = "termpipe.workspace.active"
