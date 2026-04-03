"""
MCP tool registration — all workspace_* tools.
"""
import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

try:
    from termpipe_mcp.helpers import TERMPIPE_DIR
except ImportError:
    from helpers import TERMPIPE_DIR

from ._bus import (
    _bus_pub, _bus_poll, _bus_get, _ATYPE_TO_TOPIC, _CC_DIR,
    _ARTIFACTS_ROOT, _TOPIC_ACTIVE, _TOPIC_REVIEW_REQUEST,
    _TOPIC_APPROVED, _TOPIC_FEEDBACK, _TOPIC_REJECTED,
    ATYPE_TASK, ATYPE_PLAN, ATYPE_WALK, ATYPE_OTHER,
    PLAN_DRAFT, PLAN_PENDING_APPROVAL, PLAN_APPROVED, PLAN_REJECTED
)
from ._db import _db_read_artifact, _db_write_artifact, _db_list_artifacts
from ._files import _artifact_dir, _write_artifact_files, _write_metadata
from ._registry import _registry_ws_id, _registry_all_workspaces
from ._task import (
    _get_plan_status, _pack_summary, _unpack_summary,
    _next_task_id, _set_task_status,
)
from ._artifacts import _upsert_artifact, workspace_resume

def register_tools(mcp):

    @mcp.tool()
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

        The project must already exist in context_core's registry — i.e. any
        model must have called list_tools(cwd=...) at least once for this path.

        Args:
            cwd:        Absolute path to the project directory.
            goal:       One-sentence description of the current task/goal.
            task_items: Optional newline-separated task strings to seed task.md.
                        Each becomes '- [ ] <item> <!-- id: N -->'. If omitted
                        a single placeholder is created.
        """
        ws_id = _registry_ws_id(cwd)
        if not ws_id:
            return (
                f"[workspace_init] No context_core workspace found for {cwd}.\n"
                "Call list_tools(cwd=<path>) first to register the workspace."
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

        return (
            f"workspace_init ✅  ws_{ws_id}  project={project_name}\n"
            + "\n".join(results)
            + f"\n\nArtifacts dir: {_ARTIFACTS_ROOT / project_name}"
        )

    @mcp.tool()
    def workspace_task_update(
        cwd: str,
        action: str,
        item_text: Optional[str] = None,
        item_id: Optional[int] = None,
        summary: Optional[str] = None,
    ) -> str:
        """
        Mutate task.md for the active workspace.

        Actions:
          add         — append a new task item (requires item_text)
          done        — mark item [x] complete  (requires item_id)
          in_progress — mark item [/] in-progress (requires item_id)
          todo        — mark item [ ] todo       (requires item_id)
          replace     — replace full content     (requires item_text as full markdown)

        Every mutation bumps version, writes .resolved.N snapshot, publishes
        to termpipe.workspace.task on the bus.

        Args:
            cwd:       Project directory (must be in context_core registry).
            action:    add | done | in_progress | todo | replace
            item_text: New task text (add) or full markdown (replace).
            item_id:   Numeric id from <!-- id: N --> comment (status changes).
            summary:   Optional summary stored in metadata.
        """
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

    @mcp.tool()
    def workspace_plan_update(
        cwd: str,
        content: str,
        summary: Optional[str] = None,
        status: str = PLAN_DRAFT,
    ) -> str:
        """
        Replace implementation_plan.md for the active workspace.

        Bumps version, writes .resolved.N snapshot, publishes to
        termpipe.workspace.plan on the bus.

        After writing the plan, call workspace_request_review() to enter the
        HITL gate — do NOT proceed to execution without an APPROVED response
        from workspace_await_approval().

        Args:
            cwd:     Project directory.
            content: Full markdown content for the implementation plan.
            summary: Optional one-line summary stored in metadata.
            status:  Plan lifecycle state: draft | pending_approval | approved | rejected
                     Defaults to 'draft'. Set by workspace_request_review automatically.
        """
        ws_id = _registry_ws_id(cwd)
        if not ws_id:
            return f"[workspace_plan_update] No workspace for {cwd}"

        project_name = Path(cwd).name
        packed = _pack_summary(summary, status)
        r = _upsert_artifact(ws_id, project_name, ATYPE_PLAN,
                             "implementation_plan.md", content, summary=packed)
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

    @mcp.tool()
    def workspace_walkthrough_update(
        cwd: str,
        content: str,
        summary: Optional[str] = None,
    ) -> str:
        """
        Replace walkthrough.md for the active workspace.

        Bumps version, writes .resolved.N snapshot, publishes to
        termpipe.workspace.walkthrough on the bus.

        Args:
            cwd:     Project directory.
            content: Full markdown content for the walkthrough.
            summary: Optional one-line summary stored in metadata.
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

    @mcp.tool()
    def workspace_doc_update(
        cwd: str,
        name: str,
        content: str,
        summary: Optional[str] = None,
    ) -> str:
        """
        Create or update an arbitrary markdown artifact (ARTIFACT_TYPE_OTHER).

        Any research doc, analysis notes, session log, etc. Persisted to DB,
        written to disk with .resolved.N snapshots, published to
        termpipe.workspace.<name-without-.md> on the bus.

        Args:
            cwd:     Project directory.
            name:    Filename, e.g. 'dbus_analysis.md'. Auto-appends .md if missing.
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

    @mcp.tool()
    def workspace_request_review(
        cwd: str,
        message: Optional[str] = None,
    ) -> str:
        """
        Submit implementation_plan.md for human review — sets status to
        pending_approval, publishes to termpipe.workspace.review_request,
        and instructs the model to call workspace_await_approval() next.

        This is the PLANNING → HITL gate. Do NOT write any code or call any
        file-editing tools until workspace_await_approval() returns APPROVED.

        Args:
            cwd:     Project directory.
            message: Optional note to the reviewer (e.g. confidence level,
                     specific areas to focus on).
        """
        ws_id = _registry_ws_id(cwd)
        if not ws_id:
            return f"[workspace_request_review] No workspace for {cwd}"

        project_name = Path(cwd).name
        row = _db_read_artifact(ws_id, "implementation_plan.md")
        if not row:
            return (
                "[workspace_request_review] No implementation_plan.md found. "
                "Call workspace_plan_update(cwd, content) first."
            )

        plan_content = row["content"]
        _, old_status = _unpack_summary(row.get("summary"))

        # Bump status to pending_approval in DB + bus
        packed = _pack_summary(message, PLAN_PENDING_APPROVAL)
        _upsert_artifact(ws_id, project_name, ATYPE_PLAN,
                         "implementation_plan.md", plan_content, summary=packed)

        # Publish review request to bus
        payload = json.dumps({
            "ws_id": ws_id,
            "project": project_name,
            "message": message or "",
            "plan_path": str(_ARTIFACTS_ROOT / project_name / "implementation_plan.md"),
            "plan_content": plan_content,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        })
        _bus_pub(_TOPIC_REVIEW_REQUEST, payload, mime="application/json")

        art_path = _ARTIFACTS_ROOT / project_name / "implementation_plan.md"
        return (
            f"📋 Review requested for implementation_plan.md\n"
            f"   project : {project_name}\n"
            f"   file    : {art_path}\n"
            f"   status  : pending_approval\n"
            f"   bus     : {_TOPIC_REVIEW_REQUEST}\n"
            + (f"   note    : {message}\n" if message else "")
            + f"\n"
            f"Waiting for human review. To respond from the terminal:\n"
            f"  Approve  : kc-bus pub {_TOPIC_APPROVED} \"lgtm\"\n"
            f"  Feedback : kc-bus pub {_TOPIC_FEEDBACK} \"<your comments>\"\n"
            f"  Reject   : kc-bus pub {_TOPIC_REJECTED} \"<reason>\"\n"
            f"  Or run   : workspace-review  (interactive CLI)\n"
            f"\n"
            f"➡️  Now call workspace_await_approval(cwd=\"{cwd}\") to block until response."
        )

    @mcp.tool()
    def workspace_await_approval(
        cwd: str,
        timeout_ms: int = 180000,
    ) -> str:
        """
        Block until the human approves, sends feedback, or rejects the plan.

        This is the hard HITL gate. The tool suspends execution and waits for
        a human to publish to one of:
          termpipe.workspace.approved  → returns APPROVED — proceed to execution
          termpipe.workspace.feedback  → returns FEEDBACK: <text> — revise plan,
                                         call workspace_plan_update + workspace_request_review,
                                         then workspace_await_approval again
          termpipe.workspace.rejected  → returns REJECTED: <reason> — start over

        DO NOT proceed to execution unless this tool returns a string starting
        with "APPROVED". On FEEDBACK or REJECTED, you must stay in PLANNING mode.

        Args:
            cwd:        Project directory.
            timeout_ms: Max wait in milliseconds (default 3 minutes).
                        On timeout the review request is republished and the
                        model must re-call this tool or prompt the user.
        """
        ws_id = _registry_ws_id(cwd)
        if not ws_id:
            return f"[workspace_await_approval] No workspace for {cwd}"

        project_name = Path(cwd).name

        # Verify plan is actually pending
        current_status = _get_plan_status(ws_id)
        if current_status == PLAN_APPROVED:
            return (
                f"APPROVED (already approved — status was {PLAN_APPROVED})\n"
                f"Proceed to execution."
            )
        if current_status not in (PLAN_PENDING_APPROVAL, PLAN_DRAFT):
            return (
                f"[workspace_await_approval] Plan status is \'{current_status}\'. "
                f"Call workspace_request_review(cwd) first."
            )

        # Block on bus
        result = _bus_poll(
            [_TOPIC_APPROVED, _TOPIC_FEEDBACK, _TOPIC_REJECTED],
            timeout_ms=timeout_ms,
        )

        if result is None:
            # Timeout — republish review request
            row = _db_read_artifact(ws_id, "implementation_plan.md")
            plan_content = row["content"] if row else ""
            payload = json.dumps({
                "ws_id": ws_id,
                "project": project_name,
                "message": "Re-requesting review after timeout",
                "plan_path": str(_ARTIFACTS_ROOT / project_name / "implementation_plan.md"),
                "plan_content": plan_content,
                "requested_at": datetime.now(timezone.utc).isoformat(),
            })
            _bus_pub(_TOPIC_REVIEW_REQUEST, payload, mime="application/json")
            return (
                f"TIMEOUT — no response after {timeout_ms // 1000}s.\n"
                f"Review request republished to {_TOPIC_REVIEW_REQUEST}.\n"
                f"Please prompt the user to review the plan, then call "
                f"workspace_await_approval(cwd) again.\n"
                f"  File: {_ARTIFACTS_ROOT / project_name / 'implementation_plan.md'}"
            )

        topic, data = result

        if topic == _TOPIC_APPROVED:
            # Persist approved status
            row = _db_read_artifact(ws_id, "implementation_plan.md")
            plan_content = row["content"] if row else ""
            packed = _pack_summary(f"Approved: {data}", PLAN_APPROVED)
            _upsert_artifact(ws_id, project_name, ATYPE_PLAN,
                             "implementation_plan.md", plan_content, summary=packed)
            return (
                f"APPROVED ✅\n"
                f"Human message: {data}\n"
                f"Plan status set to \'approved\'. Proceed to EXECUTION."
            )

        elif topic == _TOPIC_FEEDBACK:
            # Persist feedback in summary, keep pending status
            row = _db_read_artifact(ws_id, "implementation_plan.md")
            plan_content = row["content"] if row else ""
            packed = _pack_summary(f"Feedback: {data}", PLAN_PENDING_APPROVAL)
            _upsert_artifact(ws_id, project_name, ATYPE_PLAN,
                             "implementation_plan.md", plan_content, summary=packed)
            return (
                f"FEEDBACK received — revise the plan before proceeding.\n"
                f"\n"
                f"Human feedback:\n{data}\n"
                f"\n"
                f"Required steps:\n"
                f"  1. Revise implementation_plan.md incorporating the feedback\n"
                f"  2. Call workspace_plan_update(cwd, revised_content)\n"
                f"  3. Call workspace_request_review(cwd)\n"
                f"  4. Call workspace_await_approval(cwd)\n"
                f"Do NOT proceed to execution until you receive APPROVED."
            )

        elif topic == _TOPIC_REJECTED:
            row = _db_read_artifact(ws_id, "implementation_plan.md")
            plan_content = row["content"] if row else ""
            packed = _pack_summary(f"Rejected: {data}", PLAN_REJECTED)
            _upsert_artifact(ws_id, project_name, ATYPE_PLAN,
                             "implementation_plan.md", plan_content, summary=packed)
            return (
                f"REJECTED — plan has been rejected. Return to PLANNING mode.\n"
                f"\n"
                f"Reason: {data}\n"
                f"\n"
                f"Start over: revise the approach, call workspace_plan_update,\n"
                f"workspace_request_review, then workspace_await_approval."
            )

        return f"[workspace_await_approval] Unexpected topic: {topic}"

    @mcp.tool()
    def workspace_status(cwd: str) -> str:
        """
        Show current artifact state for a workspace — DB version + bus status.

        Args:
            cwd: Project directory.
        """
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
                f"       Or run   : workspace-review\n"
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

    @mcp.tool()
    def workspace_list(filter: str = "") -> str:
        """
        List workspaces known to context_core with artifact counts.

        Args:
            filter: Optional substring to filter by workspace name (case-insensitive).
                    Omit or pass "" to list all workspaces.
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

    @mcp.tool()
    def workspace_load(cwd: str) -> str:
        """
        Explicitly reload a workspace — republishes all artifacts to the bus.

        Normally happens automatically via list_tools. Use this on demand when
        bus topics have gone cold (e.g. after daemon restart).

        Args:
            cwd: Project directory.
        """
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

