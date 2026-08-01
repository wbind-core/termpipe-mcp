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

    Automatically fires a desktop notification with Approve/View/Reject buttons
    whenever the plan is updated, regardless of which status is passed. This
    ensures the human is always notified even when the model skips
    workspace_request_review().

    Args:
        cwd:     Project directory.
        content: Full markdown content for the implementation plan.
        summary: Optional one-line summary stored in metadata.
        status:  Plan lifecycle state: draft | pending_approval | approved | rejected
    """
    from ._bus import PLAN_DRAFT, PLAN_PENDING_APPROVAL, PLAN_APPROVED, PLAN_REJECTED, _TOPIC_LATEST, _bus_pub
    from ._review import _send_review_notification
    import json as _json

    _VALID_STATUSES = (PLAN_DRAFT, PLAN_PENDING_APPROVAL, PLAN_APPROVED, PLAN_REJECTED)
    if status not in _VALID_STATUSES:
        return (
            f"[workspace_plan_update] Invalid status '{status}'. "
            f"Must be one of: {', '.join(_VALID_STATUSES)}."
        )

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
    plan_path = r['file_path']
    base_msg = (
        f"implementation_plan.md updated  v{r['version']}  status={status}  "
        f"bus={bus_flag}  {plan_path}"
    )

    # Fire desktop notification for any status that warrants human review.
    # Skip only if the plan is already in a terminal state (approved/rejected)
    # — those don't need a new review prompt.
    if status not in (PLAN_APPROVED, PLAN_REJECTED):
        notif_ok = _send_review_notification(project_name, plan_path)
        notif_flag = "🔔 notification sent" if notif_ok else "⚠️  notification failed"

        # Publish the stable "latest pending plan" pointer for external
        # consumers (hotkey scripts, etc.) regardless of which call path
        # (plan_update vs request_review) triggered the notification.
        _bus_pub(_TOPIC_LATEST, _json.dumps({
            "ws_id": ws_id,
            "project": project_name,
            "plan_path": plan_path,
        }), mime="application/json")

        next_step = (
            f"➡️  Call workspace_await_approval(cwd=\"{cwd}\") to block until response."
            if status == PLAN_PENDING_APPROVAL else
            f"➡️  Call workspace_request_review(cwd=\"{cwd}\") first, "
            f"then workspace_await_approval(cwd=\"{cwd}\")."
        )
        return (
            base_msg
            + f"\n{notif_flag} — Buttons: [✓ Approve] [📄 View Plan] [✗ Reject]\n"
            + next_step
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


def workspace_init_and_review(
    cwd: str,
    goal: Optional[str] = None,
    plan_content: Optional[str] = None,
    task_items: Optional[str] = None,
) -> str:
    """
    Single entry point for starting or revising a workspace's implementation plan.
    Replaces workspace_init + workspace_request_review + workspace_await_approval.

    First call for a given cwd (no workspace yet): `goal` and `plan_content` are
    both required. Initialises task.md/implementation_plan.md/walkthrough.md via
    workspace_init, then immediately overwrites implementation_plan.md with the
    real `plan_content`.

    Subsequent calls (workspace already exists — i.e. a revise loop after a
    REJECT verdict): only `plan_content` is required; `goal`/`task_items` are
    ignored.

    Either way, this call:
      1. Persists the plan as pending_approval and publishes it for review
         (desktop notification + termpipe.workspace.review_request/latest, so
         any external consumer such as a hotkey script can resolve what's
         pending and where, independent of the verdict channel).
      2. Blocks indefinitely (no timeout) on termpipe.workspace.status — the
         single verdict channel a human-side review sidecar publishes to.
      3. Parses the verdict:
           "APPROVE"                      -> plan approved, phase -> approved
           "REJECT SEE FEEDBACK <path>"   -> reads the unified-diff feedback
                                             artifact at <path> and returns it
                                             inline, phase -> plan_draft

    Args:
        cwd:          Absolute path to the project directory.
        goal:         One-sentence goal. Required only on the first call.
        plan_content: Full markdown content for implementation_plan.md. Always required.
        task_items:   Optional newline-separated seed tasks. Only used on first call.
    """
    from ._bus import (
        PLAN_PENDING_APPROVAL, PLAN_APPROVED, PLAN_REJECTED,
        _TOPIC_REVIEW_REQUEST, _TOPIC_LATEST, _TOPIC_STATUS,
        _bus_pub, _bus_poll,
    )
    from ._review import _send_review_notification
    import json as _json

    if plan_content is None or not plan_content.strip():
        return (
            "[workspace_init_and_review] plan_content is required — write the actual "
            "implementation plan markdown and pass it here."
        )

    ws_id = _registry_ws_id(cwd)
    project_name = Path(cwd).name

    if not ws_id:
        if not goal:
            return (
                "[workspace_init_and_review] No workspace exists yet for this cwd — "
                "`goal` is required on the first call."
            )
        init_result = workspace_init(cwd=cwd, goal=goal, task_items=task_items)
        ws_id = _registry_ws_id(cwd)
        if not ws_id:
            return f"[workspace_init_and_review] workspace_init failed:\n{init_result}"

    # Persist the real plan content — overwrites the workspace_init skeleton on
    # a first call, or replaces the previous draft on a revise loop.
    packed = _pack_summary(None, PLAN_PENDING_APPROVAL)
    r = _upsert_artifact(ws_id, project_name, ATYPE_PLAN,
                         "implementation_plan.md", plan_content, summary=packed)
    plan_path = r["file_path"]
    set_phase(ws_id, "pending_approval")

    review_payload = _json.dumps({
        "ws_id": ws_id,
        "project": project_name,
        "plan_path": plan_path,
        "plan_content": plan_content,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    })
    _bus_pub(_TOPIC_REVIEW_REQUEST, review_payload, mime="application/json")
    _bus_pub(_TOPIC_LATEST, _json.dumps({
        "ws_id": ws_id, "project": project_name, "plan_path": plan_path,
    }), mime="application/json")
    _send_review_notification(project_name, plan_path)

    # Block indefinitely — human review time is unbounded, same rationale as
    # the old workspace_await_approval(timeout_ms=None) behavior.
    result = _bus_poll([_TOPIC_STATUS], timeout_ms=None)

    if result is None:
        return (
            "[workspace_init_and_review] Verdict channel closed unexpectedly. "
            "Call workspace_init_and_review(cwd, plan_content=...) again to re-publish."
        )

    _topic, data = result
    verdict = (data or "").strip()

    if verdict.upper().startswith("APPROVE"):
        packed = _pack_summary("Approved", PLAN_APPROVED)
        _upsert_artifact(ws_id, project_name, ATYPE_PLAN,
                         "implementation_plan.md", plan_content, summary=packed)
        set_phase(ws_id, "approved")
        return (
            f"PLAN APPROVED ✅  ws_{ws_id}  project={project_name}\n"
            f"   {plan_path}\n\n"
            f"➡️  REQUIRED NEXT STEP: call workspace_task (action=create) to register "
            f"at least one task. Write tools remain gated until a task exists."
        )

    if verdict.upper().startswith("REJECT SEE FEEDBACK"):
        feedback_path = verdict[len("REJECT SEE FEEDBACK"):].strip()
        diff_text = None
        if feedback_path:
            try:
                diff_text = Path(feedback_path).expanduser().read_text()
            except Exception as e:
                diff_text = f"[workspace_init_and_review] Could not read feedback file at {feedback_path}: {e}"
        packed = _pack_summary(f"Rejected — feedback at {feedback_path}", PLAN_REJECTED)
        _upsert_artifact(ws_id, project_name, ATYPE_PLAN,
                         "implementation_plan.md", plan_content, summary=packed)
        set_phase(ws_id, "plan_draft")
        return (
            f"REJECTED — feedback attached below.\n"
            f"   feedback file: {feedback_path}\n\n"
            f"{diff_text}\n\n"
            f"➡️  REQUIRED NEXT STEP: revise implementation_plan.md addressing the "
            f"feedback above, then call workspace_init_and_review(cwd=\"{cwd}\", "
            f"plan_content=<revised plan>) again."
        )

    return (
        f"[workspace_init_and_review] Unrecognised verdict on {_TOPIC_STATUS}: {verdict!r}\n"
        f"Expected 'APPROVE' or 'REJECT SEE FEEDBACK <path>'."
    )


# Topic used in workspace_init - import here to avoid circular
_TOPIC_ACTIVE = "termpipe.workspace.active"
