"""
Workspace tools for TermPipe Slimline — consolidated surface.

15 registered tools → 3, each dispatching on ``action``:

  workspace_plan(cwd, action, ...)     — plan / docs lifecycle
  workspace_task(cwd, action, ...)     — task lifecycle
  workspace_session(cwd?, action, ...)  — session, orientation, human gates

All behavior lives in Craig's ``termpipe_mcp.tools.workspace`` underscore
modules; this file is a thin dispatcher and imports them directly — no
logic is duplicated here ("inherit automatically"). Return strings are
passed through verbatim: the kb-backed flows (blocking verdict polls,
notification fallbacks, terminal ``kb pub`` commands) are load-bearing UX.

Grouping principle: plan lifecycle / task lifecycle / session+human.

Deferred (documented, not changed — consolidation is surface-only):
  - legacy markdown task model vs structured DB task model can diverge
    (``task.update`` is the legacy regex path; prefer ``task.create`` /
    ``task.set_status`` which use the structured DB);
  - multi-topic ``_bus_poll`` falls back to sequential get-polling;
  - ``session.ask`` has no correlation ID (single shared response topic).
"""
import sys
from pathlib import Path

_TERMPPIPE_ROOT = Path("/home/craig/termpipe-mcp")
if str(_TERMPPIPE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TERMPPIPE_ROOT))

# The workspace subpackage's own tools.py inserts its vendor/ and
# desktop-notifier/ paths on import, so these resolve on their own.
from termpipe_mcp.tools.workspace import _plan, _task_ops, _review, _workspace
from termpipe_mcp.tools.workspace.tools import _gated as _ws_gated


_PLAN_ACTIONS = """workspace_plan actions:
  init_review         goal?, plan_content!, task_items?      — submit plan, block until human verdict
  update              content!, summary?, status="draft"     — replace implementation_plan.md (write-gated)
  update_walkthrough  content!, summary?                    — replace walkthrough.md (write-gated)
  doc                 name!, content!, summary?             — create/update an .md artifact (write-gated)
"""

_TASK_ACTIONS = """workspace_task actions:
  create          title!, description?, priority?, task_type?, completion_requirements?,
                  output_format?, depends_on?, tags?, notes?
  update          update_action!, item_text?, item_id?, summary?   — legacy markdown task.md ops (write-gated)
  set_status      task_id!, status!, notes?                       — structured status, drives phase machine (write-gated)
  query           status?, priority?, task_type?                   — filtered task list
  request_review  task_id!, message?                              — submit task for human review
  await_approval  task_id!, timeout_ms=180000                    — block until task verdict arrives
"""

_SESSION_ACTIONS = """workspace_session actions:
  status   cwd!                                  — full workspace dump (phase, plan, artifacts)
  list     filter?                               — context_core registry listing (cwd not required)
  load     cwd!                                  — republish all artifacts to the bus
  override cwd!, reason!                         — request write-gate override via notification
  ask      cwd!, question!, options!, timeout_ms=120000  — ask the human, block for a button click
"""


def register_tools(mcp):
    """Register the 3 consolidated workspace tools with the MCP server."""

    @mcp.tool()
    def workspace_plan(
        cwd: str,
        action: str,
        goal: str = None,
        plan_content: str = None,
        task_items: str = None,
        content: str = None,
        summary: str = None,
        status: str = "draft",
        name: str = None,
    ) -> str:
        """
        Plan / docs lifecycle for a workspace. Dispatches on `action`.

        Args:
            cwd:          Project directory.
            action:       init_review | update | update_walkthrough | doc
            goal:         One-sentence goal (init_review, first call only).
            plan_content: Full plan markdown (init_review, always required).
            task_items:   Newline-separated seed tasks (init_review, first call only).
            content:      Full markdown for update / update_walkthrough / doc.
            summary:      One-line summary stored in metadata.
            status:       Plan lifecycle state for update: draft | pending_approval | approved | rejected.
            name:         Filename for doc (e.g. 'notes.md').
        """
        if action == "init_review":
            return _plan.workspace_init_and_review(
                cwd=cwd, goal=goal, plan_content=plan_content, task_items=task_items,
            )
        if action == "update":
            if not content:
                return "[workspace_plan] action='update' requires content."
            return _ws_gated(
                cwd, _plan.workspace_plan_update,
                content=content, summary=summary, status=status,
            )
        if action == "update_walkthrough":
            if not content:
                return "[workspace_plan] action='update_walkthrough' requires content."
            return _ws_gated(
                cwd, _plan.workspace_walkthrough_update,
                content=content, summary=summary,
            )
        if action == "doc":
            if not name:
                return "[workspace_plan] action='doc' requires name."
            if not content:
                return "[workspace_plan] action='doc' requires content."
            return _ws_gated(
                cwd, _plan.workspace_doc_update,
                name=name, content=content, summary=summary,
            )
        return f"[workspace_plan] Unknown action '{action}'.\n\n{_PLAN_ACTIONS}"

    @mcp.tool()
    def workspace_task(
        cwd: str,
        action: str,
        title: str = None,
        description: str = None,
        priority: str = "medium",
        task_type: str = None,
        completion_requirements: str = None,
        output_format: str = None,
        depends_on: str = None,
        tags: str = None,
        notes: str = None,
        update_action: str = None,
        item_text: str = None,
        item_id: int = None,
        summary: str = None,
        task_id: int = None,
        status: str = None,
        message: str = None,
        timeout_ms: int = 180000,
    ) -> str:
        """
        Task lifecycle for a workspace. Dispatches on `action`.

        Args:
            cwd:                     Project directory.
            action:                  create | update | set_status | query | request_review | await_approval
            title:                   Task title (create).
            description:             Detailed description (create).
            priority:                 critical | high | medium | low (create).
            task_type:               research | implementation | test | review | config | docs | fix (create).
            completion_requirements: Measurable done criteria (create).
            output_format:           What the deliverable looks like (create).
            depends_on:              Comma-separated task IDs (create).
            tags:                    Comma-separated tags (create).
            notes:                   Extra notes (create, set_status).
            update_action:           add | done | in_progress | todo | replace (update; legacy markdown path).
            item_text:               New task text / full markdown (update).
            item_id:                 Numeric <!-- id: N --> marker (update).
            summary:                 Summary stored in metadata (update).
            task_id:                 Task ID (set_status, request_review, await_approval).
            status:                  todo | in_progress | needs_review | done | blocked (set_status).
            message:                 Note to the reviewer (request_review).
            timeout_ms:               Max wait for a verdict in ms (await_approval).
        """
        if action == "create":
            if not title:
                return "[workspace_task] action='create' requires title."
            return _task_ops.workspace_task_create(
                cwd=cwd, title=title, description=description, priority=priority,
                task_type=task_type, completion_requirements=completion_requirements,
                output_format=output_format, depends_on=depends_on, tags=tags,
                notes=notes,
            )
        if action == "update":
            if not update_action:
                return "[workspace_task] action='update' requires update_action."
            return _ws_gated(
                cwd, _task_ops.workspace_task_update,
                action=update_action, item_text=item_text, item_id=item_id,
                summary=summary,
            )
        if action == "set_status":
            if task_id is None:
                return "[workspace_task] action='set_status' requires task_id."
            if not status:
                return "[workspace_task] action='set_status' requires status."
            return _ws_gated(
                cwd, _task_ops.workspace_task_set_status,
                task_id=task_id, status=status, notes=notes,
            )
        if action == "query":
            return _task_ops.workspace_task_query(
                cwd=cwd, status=status, priority=priority, task_type=task_type,
            )
        if action == "request_review":
            if task_id is None:
                return "[workspace_task] action='request_review' requires task_id."
            return _review.workspace_task_request_review(
                cwd=cwd, task_id=task_id, message=message,
            )
        if action == "await_approval":
            if task_id is None:
                return "[workspace_task] action='await_approval' requires task_id."
            return _review.workspace_await_task_approval(
                cwd=cwd, task_id=task_id, timeout_ms=timeout_ms,
            )
        return f"[workspace_task] Unknown action '{action}'.\n\n{_TASK_ACTIONS}"

    @mcp.tool()
    def workspace_session(
        cwd: str = None,
        action: str = "status",
        filter: str = "",
        reason: str = None,
        question: str = None,
        options: list = None,
        timeout_ms: int = 120000,
    ) -> str:
        """
        Session, orientation, and human gates. Dispatches on `action`.

        Args:
            cwd:        Project directory (not required for action='list').
            action:     status | list | load | override | ask
            filter:     Substring filter for list.
            reason:     Why the write gate should be bypassed (override).
            question:   Question to ask the human (ask).
            options:    Button labels, max ~3 (ask).
            timeout_ms: How long to wait for an answer in ms (ask).
        """
        if action == "list":
            return _workspace.workspace_list(filter=filter)
        if cwd is None:
            return f"[workspace_session] action='{action}' requires cwd."
        if action == "status":
            return _workspace.workspace_status(cwd=cwd)
        if action == "load":
            return _workspace.workspace_load(cwd=cwd)
        if action == "override":
            if not reason:
                return "[workspace_session] action='override' requires reason."
            return _review.workspace_override(cwd=cwd, reason=reason)
        if action == "ask":
            if not question:
                return "[workspace_session] action='ask' requires question."
            if not options:
                return "[workspace_session] action='ask' requires options."
            return _review.workspace_ask(
                cwd=cwd, question=question, options=options,
                timeout_ms=timeout_ms,
            )
        return f"[workspace_session] Unknown action '{action}'.\n\n{_SESSION_ACTIONS}"
