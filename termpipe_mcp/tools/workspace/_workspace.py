"""
Workspace management tools — status, list, load.
"""
from pathlib import Path

from ._db import _db_list_artifacts, _db_read_artifact
from ._bus import (
    _bus_get, _ARTIFACTS_ROOT, _CC_DIR, _ATYPE_TO_TOPIC,
)
from ._registry import _registry_ws_id, _registry_all_workspaces
from ._task import _get_plan_status, _unpack_summary, _pack_summary
from ._bus import (
    PLAN_DRAFT, PLAN_PENDING_APPROVAL, PLAN_APPROVED, PLAN_REJECTED,
    ATYPE_PLAN, _TOPIC_APPROVED, _TOPIC_FEEDBACK, _TOPIC_REJECTED,
)


def workspace_status(cwd: str) -> str:
    """
    Show current artifact state for a workspace — DB version + bus status.

    Args:
        cwd: Project directory.
    """
    from ._artifacts import workspace_resume

    ws_id = _registry_ws_id(cwd)
    if not ws_id:
        return f"[workspace_status] No context_core workspace found for {cwd}"

    project_name = Path(cwd).name
    artifacts = _db_list_artifacts(ws_id)

    plan_status = _get_plan_status(ws_id)
    status_icon = {
        PLAN_DRAFT:            "📝 draft",
        PLAN_PENDING_APPROVAL: "⏳ PENDING APPROVAL — awaiting human review",
        PLAN_APPROVED:         "✅ APPROVED — execution unlocked",
        PLAN_REJECTED:         "❌ REJECTED — return to planning",
    }.get(plan_status, plan_status)

    out = f"Workspace: {project_name}  (ws_{ws_id})\n"
    out += f"Artifacts dir: {_ARTIFACTS_ROOT / project_name}\n"
    out += f"Plan status  : {status_icon}\n"

    if plan_status == PLAN_PENDING_APPROVAL:
        out += (
            f"\n  ⚠️  BLOCKED — do not proceed to execution.\n"
            f"     Human must respond on the bus:\n"
            f"       Approve  : kc-bus pub {_TOPIC_APPROVED} \"lgtm\"\n"
            f"       Feedback : kc-bus pub {_TOPIC_FEEDBACK} \"<comments>\"\n"
            f"       Reject   : kc-bus pub {_TOPIC_REJECTED} \"<reason>\"\n"
        )
    elif plan_status == PLAN_DRAFT:
        out += (
            f"\n  ℹ️  Plan not yet submitted for review.\n"
            f"     Call workspace_request_review(cwd) when plan is ready.\n"
        )

    out += "=" * 60 + "\n\n"

    if not artifacts:
        out += "No artifacts yet — call workspace_init() first.\n"
    else:
        for art in artifacts:
            row = _db_read_artifact(ws_id, art["name"])
            preview = ""
            if row:
                lines = row["content"].strip().splitlines()
                preview = "\n    ".join(lines[:6])
                if len(lines) > 6:
                    preview += f"\n    … ({len(lines) - 6} more lines)"

            topic = _ATYPE_TO_TOPIC.get(
                art["artifact_type"],
                f"termpipe.workspace.{art['name'].removesuffix('.md')}"
            )
            bus_live = "✓" if _bus_get(topic) else "✗ (not on bus)"

            # Unpack summary for display
            human_summary, art_status = _unpack_summary(art.get("summary"))
            display_summary = human_summary or "—"
            if art["artifact_type"] == ATYPE_PLAN:
                display_summary = f"[{art_status}] {human_summary}" if human_summary else f"[{art_status}]"

            out += (
                f"📄 {art['name']}  [{art['artifact_type']}]\n"
                f"   version : {art['version']}\n"
                f"   updated : {art['updated_at']}\n"
                f"   summary : {display_summary}\n"
                f"   bus     : {topic}  {bus_live}\n"
                f"   preview :\n    {preview}\n\n"
            )

    return out.rstrip()


def workspace_list(filter: str = "") -> str:
    """
    List workspaces known to context_core with artifact counts.

    Args:
        filter: Optional substring to filter by workspace name.
    """
    workspaces = _registry_all_workspaces()
    if not workspaces:
        return "No workspaces found in context_core registry."

    if filter:
        workspaces = [ws for ws in workspaces
                      if filter.lower() in ws["display_name"].lower()]
        if not workspaces:
            return f"No workspaces matching '{filter}'."

    active_file = _CC_DIR / "current_workspace"
    active = active_file.read_text().strip() if active_file.exists() else None

    header = f"Workspaces (filter='{filter}')" if filter else "Workspaces"
    out = header + "\n" + "=" * 50 + "\n\n"

    for ws in workspaces:
        ws_id = ws["workspace_id"]
        name  = ws["display_name"]
        arts  = _db_list_artifacts(ws_id)
        art_str = ", ".join(a["name"] for a in arts) if arts else "no artifacts"
        flag = "◀ active" if (active and Path(active).name == name) else ""

        out += (
            f"  {'▶' if flag else '·'} {name}  (ws_{ws_id})  {flag}\n"
            f"    last accessed : {ws.get('last_accessed', '?')}\n"
            f"    artifacts ({len(arts)}) : {art_str}\n\n"
        )

    total = len(workspaces)
    out += f"({total} workspace{'s' if total != 1 else ''})"
    return out.rstrip()


def workspace_load(cwd: str) -> str:
    """
    Explicitly reload a workspace — republishes all artifacts to the bus.

    Args:
        cwd: Project directory.
    """
    from ._artifacts import workspace_resume

    ws_id = _registry_ws_id(cwd)
    if not ws_id:
        return f"[workspace_load] No context_core workspace for {cwd}"

    workspace_resume(cwd)

    artifacts = _db_list_artifacts(ws_id)
    project_name = Path(cwd).name
    out = f"workspace_load ✅  ws_{ws_id}  project={project_name}\n"
    out += f"Republished {len(artifacts)} artifact(s) to bus:\n"

    for art in artifacts:
        topic = _ATYPE_TO_TOPIC.get(
            art["artifact_type"],
            f"termpipe.workspace.{art['name'].removesuffix('.md')}"
        )
        out += f"  · {art['name']}  →  {topic}\n"

    return out
