"""
Review and approval tools — request_review, await_approval for plans and tasks.

Uses desktop-notifier with action buttons that publish directly to bus topics.
"""

from typing import Optional
from pathlib import Path
from datetime import datetime, timezone
import subprocess
import threading
import time
import asyncio
import sys

from ._db import _db_read_artifact, _db_get_task, _db_update_task_status, _db_list_tasks, _db_get_cc_session_num
from ._bus import (
    ATYPE_TASK, ATYPE_PLAN,
    PLAN_PENDING_APPROVAL, PLAN_APPROVED, PLAN_REJECTED,
    _TOPIC_REVIEW_REQUEST, _TOPIC_APPROVED, _TOPIC_FEEDBACK, _TOPIC_REJECTED,
    _bus_pub, _bus_poll, _ARTIFACTS_ROOT,
)
from ._artifacts import _upsert_artifact
from ._registry import _registry_ws_id
from ._task import _pack_summary, _get_plan_status
from ._phase import set_phase, ws_id_from_cwd, set_override, check_write_gate
import json

# =============================================================================
# Event Loop Thread for Desktop-Notifier Callbacks
# =============================================================================

class DNEventLoop(threading.Thread):
    """Background thread running an asyncio event loop for notification callbacks."""
    
    def __init__(self):
        super().__init__(daemon=True)
        self.loop = asyncio.new_event_loop()
        self.started = threading.Event()
        self._notifier = None
        
    def run(self):
        asyncio.set_event_loop(self.loop)
        self.started.set()
        self.loop.run_forever()
        
    def run_coroutine(self, coro):
        """Schedule a coroutine to run in this loop."""
        if self.loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, self.loop)
            return future.result(timeout=30)
        else:
            return self.loop.run_until_complete(coro)


# Global event loop instance
_dn_event_loop = None

def _get_dn_event_loop() -> DNEventLoop:
    global _dn_event_loop
    if _dn_event_loop is None or not _dn_event_loop.is_alive():
        _dn_event_loop = DNEventLoop()
        _dn_event_loop.start()
        time.sleep(0.5)  # Wait for loop to start
    return _dn_event_loop


# =============================================================================
# Desktop Notifier Helper
# =============================================================================

def _ensure_desktop_notifier_setup():
    """Setup desktop_notifier and vendor paths, return the module."""
    termpipe_mcp_path = Path(__file__).parent.parent.parent
    
    # Add vendor directory (immutabledict, bidict, dbus-fast deps)
    vendor_path = termpipe_mcp_path / "vendor"
    if str(vendor_path) not in sys.path:
        sys.path.insert(0, str(vendor_path))
    
    # Add desktop_notifier source
    dn_path = termpipe_mcp_path / "desktop-notifier" / "src"
    if str(dn_path) not in sys.path:
        sys.path.insert(0, str(dn_path))
    
    from desktop_notifier import DesktopNotifier, Urgency, Button
    return DesktopNotifier, Urgency, Button


# =============================================================================
# Notification Functions
# =============================================================================

def _send_review_notification(
    project_name: str,
    plan_path: str,
    view_cmd: Optional[str] = None,
) -> bool:
    """
    Send a rich desktop notification with action buttons for plan review.
    
    Buttons:
    - Approve: Publish to approved topic
    - View Plan: Open the plan file for review
    - Reject: Publish to rejected topic
    
    Args:
        project_name: Name of the project
        plan_path: Path to the implementation_plan.md file
        view_cmd: Optional command to open the plan
        
    Returns:
        True if notification was sent successfully
    """
    try:
        DesktopNotifier, Urgency, Button = _ensure_desktop_notifier_setup()
        
        # Build the view command (open in default editor)
        if not view_cmd:
            view_cmd = f"xdg-open '{plan_path}'"
        
        loop_thread = _get_dn_event_loop()
        
        async def send():
            notifier = DesktopNotifier(app_name="TermPipe")
            
            # Set up button press handler
            notifier.on_button_pressed = lambda nid, key: _log_button_press(key)
            notifier.on_clicked = lambda nid: _log_button_press("clicked")
            
            await notifier.send(
                title=f"⚠️ Review Required: {project_name}",
                message="Implementation plan awaiting your review\nClick a button to respond",
                urgency=Urgency.Critical,
                buttons=[
                    Button(title="✓ Approve", on_pressed=lambda: _bus_pub(_TOPIC_APPROVED, "lgtm")),
                    Button(title="📄 View Plan", on_pressed=lambda: _view_plan(view_cmd)),
                    Button(title="✗ Reject", on_pressed=lambda: _bus_pub(_TOPIC_REJECTED, "rejected")),
                ],
                timeout=0  # 0 = don't auto-dismiss
            )
        
        loop_thread.run_coroutine(send())
        return True
        
    except Exception as e:
        print(f"[_send_review_notification] Error: {e}", file=sys.stderr)
        return False


def _send_task_notification(
    project_name: str,
    task_id: int,
    task_title: str,
    task_path: str,
) -> bool:
    """
    Send a rich desktop notification for task review.
    """
    try:
        DesktopNotifier, Urgency, Button = _ensure_desktop_notifier_setup()
        
        loop_thread = _get_dn_event_loop()
        
        _TASK_APPROVED = "termpipe.workspace.task.approved"
        _TASK_FEEDBACK = "termpipe.workspace.task.feedback"
        _TASK_REJECTED = "termpipe.workspace.task.rejected"
        
        async def send():
            notifier = DesktopNotifier(app_name="TermPipe")
            
            notifier.on_button_pressed = lambda nid, key: _log_button_press(key)
            notifier.on_clicked = lambda nid: _log_button_press("clicked")
            
            await notifier.send(
                title=f"⏳ Task Review: {project_name}",
                message=f"Task #{task_id}: {task_title}\nClick a button to respond",
                urgency=Urgency.Critical,
                buttons=[
                    Button(title="✓ Approve", on_pressed=lambda: _bus_pub(_TASK_APPROVED, "lgtm")),
                    Button(title="📋 View Task", on_pressed=lambda: _view_plan(task_path)),
                    Button(title="✗ Reject", on_pressed=lambda: _bus_pub(_TASK_REJECTED, "rejected")),
                ],
                timeout=0
            )
        
        loop_thread.run_coroutine(send())
        return True
        
    except Exception as e:
        print(f"[_send_task_notification] Error: {e}", file=sys.stderr)
        return False


def _log_button_press(key: str):
    """Log button press for debugging."""
    print(f"[DN Button] {key}", file=sys.stderr)


def _view_plan(cmd: str):
    """Open the plan file for viewing."""
    try:
        subprocess.run(f"bash -c '{cmd}'", shell=True, capture_output=True, timeout=5)
    except Exception as e:
        print(f"[_view_plan] Error: {e}", file=sys.stderr)


# =============================================================================
# MCP Tools
# =============================================================================

def workspace_request_review(
    cwd: str,
    message: Optional[str] = None,
) -> str:
    """
    Submit implementation_plan.md for human review.

    Args:
        cwd:     Project directory.
        message: Optional note to the reviewer.
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
    plan_path = str(_ARTIFACTS_ROOT / project_name / "implementation_plan.md")

    # Bump status to pending_approval in DB + bus
    packed = _pack_summary(message, PLAN_PENDING_APPROVAL)
    _upsert_artifact(ws_id, project_name, ATYPE_PLAN,
                     "implementation_plan.md", plan_content, summary=packed)

    # Publish review request to bus
    payload = json.dumps({
        "ws_id": ws_id,
        "project": project_name,
        "message": message or "",
        "plan_path": plan_path,
        "plan_content": plan_content,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    })
    _bus_pub(_TOPIC_REVIEW_REQUEST, payload, mime="application/json")

    # Advance phase
    set_phase(ws_id, "pending_approval")

    # Build terminal commands for fallback
    approve_cmd = f'kb pub {_TOPIC_APPROVED} "lgtm"'
    view_cmd = f'xdg-open "{plan_path}"'
    reject_cmd = f'kb pub {_TOPIC_REJECTED} "rejected"'

    # Send rich desktop notification with buttons
    _send_review_notification(project_name, plan_path, view_cmd)

    return (
        f"📋 Review requested for implementation_plan.md\n"
        f"   project : {project_name}\n"
        f"   file    : {plan_path}\n"
        f"   status  : pending_approval\n"
        f"   bus     : {_TOPIC_REVIEW_REQUEST}\n"
        + (f"   note    : {message}\n" if message else "")
        + f"\n"
        f"🔔 Rich notification sent!\n"
        f"   Buttons: [✓ Approve] [📄 View Plan] [✗ Reject]\n"
        f"\n"
        f"Or use terminal:\n"
        f"   Approve : {approve_cmd}\n"
        f"   View    : {view_cmd}\n"
        f"   Reject  : {reject_cmd}\n"
        f"\n"
        f"➡️  Now call workspace_await_approval(cwd=\"{cwd}\") to block until response."
    )


def workspace_await_approval(
    cwd: str,
    timeout_ms: int = 180000,
) -> str:
    """
    Block until the human approves, sends feedback, or rejects the plan.

    Returns: APPROVED | FEEDBACK: <text> | REJECTED: <reason>

    Args:
        cwd:        Project directory.
        timeout_ms: Max wait in milliseconds (default 3 minutes).
    """
    ws_id = _registry_ws_id(cwd)
    if not ws_id:
        return f"[workspace_await_approval] No workspace for {cwd}"

    project_name = Path(cwd).name

    # Verify plan is actually pending
    current_status = _get_plan_status(ws_id)
    if current_status == PLAN_APPROVED:
        return (
            f"APPROVED (already approved)\n"
            f"Proceed to execution."
        )
    if current_status not in (PLAN_PENDING_APPROVAL, PLAN_DRAFT):
        return (
            f"[workspace_await_approval] Plan status is '{current_status}'. "
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
            f"Review request republished. Please prompt the user to review."
        )

    topic, data = result

    if topic == _TOPIC_APPROVED:
        row = _db_read_artifact(ws_id, "implementation_plan.md")
        plan_content = row["content"] if row else ""
        packed = _pack_summary(f"Approved: {data}", PLAN_APPROVED)
        _upsert_artifact(ws_id, project_name, ATYPE_PLAN,
                         "implementation_plan.md", plan_content, summary=packed)
        set_phase(ws_id, "approved")
        return (
            f"APPROVED ✅\n"
            f"Human message: {data}\n"
            f"Plan status set to 'approved'. Proceed to EXECUTION."
        )

    elif topic == _TOPIC_FEEDBACK:
        row = _db_read_artifact(ws_id, "implementation_plan.md")
        plan_content = row["content"] if row else ""
        packed = _pack_summary(f"Feedback: {data}", PLAN_PENDING_APPROVAL)
        _upsert_artifact(ws_id, project_name, ATYPE_PLAN,
                         "implementation_plan.md", plan_content, summary=packed)
        return (
            f"FEEDBACK received — revise the plan before proceeding.\n\n"
            f"Human feedback:\n{data}\n\n"
            f"Required steps:\n"
            f"  1. Revise implementation_plan.md\n"
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
        set_phase(ws_id, "plan_draft")
        return (
            f"REJECTED — plan has been rejected. Return to PLANNING mode.\n\n"
            f"Reason: {data}\n\n"
            f"Start over: revise the approach."
        )

    return f"[workspace_await_approval] Unexpected topic: {topic}"


def workspace_task_request_review(
    cwd: str,
    task_id: int,
    message: Optional[str] = None,
) -> str:
    """
    Submit a task for human review.

    Args:
        cwd:     Project directory.
        task_id: Task to submit for review.
        message: Optional note to the reviewer.
    """
    ws_id = _registry_ws_id(cwd)
    if not ws_id:
        return f"[workspace_task_request_review] No workspace for {cwd}"

    task = _db_get_task(ws_id, task_id)
    if not task:
        return f"[workspace_task_request_review] Task [{task_id}] not found."

    _db_update_task_status(ws_id, task_id, "needs_review")

    project_name = Path(cwd).name
    task_path = str(_ARTIFACTS_ROOT / project_name / "task.md")

    payload = json.dumps({
        "ws_id": ws_id,
        "task_id": task_id,
        "title": task["title"],
        "completion_requirements": task.get("completion_requirements", ""),
        "output_format": task.get("output_format", ""),
        "message": message or "",
        "requested_at": datetime.now(timezone.utc).isoformat(),
    })
    _bus_pub("termpipe.workspace.task_review_request", payload, mime="application/json")

    # Send rich desktop notification
    _send_task_notification(project_name, task_id, task["title"], task_path)

    return (
        f"⏳ Review requested for task [{task_id}]: {task['title']}\n"
        f"   status           : needs_review\n"
        + (f"   reviewer note    : {message}\n" if message else "")
+ (f"   done when        : {task.get('completion_requirements', '(not specified)')}\n")
        + (f"   expected output  : {task.get('output_format', '(not specified)')}\n")
        + f"\n"
        f"🔔 Rich notification sent!\n"
        f"   Buttons: [✓ Approve] [📋 View Task] [✗ Reject]\n"
        f"\n"
        f"Or use terminal:\n"
        f"  Approve  : kb pub termpipe.workspace.task.approved \"lgtm\"\n"
        f"  Reject   : kb pub termpipe.workspace.task.rejected \"rejected\"\n"
        f"\n"
        f"➡️  Now call workspace_await_task_approval(cwd=\"{cwd}\", task_id={task_id})"
    )


def workspace_await_task_approval(
    cwd: str,
    task_id: int,
    timeout_ms: int = 180000,
) -> str:
    """
    Block until the human approves, gives feedback, or rejects a task.

    Returns: APPROVED | FEEDBACK: <text> | REJECTED: <reason>

    Args:
        cwd:        Project directory.
        task_id:    Task ID submitted for review.
        timeout_ms: Max wait in milliseconds.
    """
    from ._artifacts import _upsert_artifact
    from ._bus import ATYPE_TASK
    from ._db import _render_task_md

    ws_id = _registry_ws_id(cwd)
    if not ws_id:
        return f"[workspace_await_task_approval] No workspace for {cwd}"

    task = _db_get_task(ws_id, task_id)
    if not task:
        return f"[workspace_await_task_approval] Task [{task_id}] not found."

    _TASK_APPROVED = "termpipe.workspace.task.approved"
    _TASK_FEEDBACK = "termpipe.workspace.task.feedback"
    _TASK_REJECTED = "termpipe.workspace.task.rejected"

    result = _bus_poll(
        [_TASK_APPROVED, _TASK_FEEDBACK, _TASK_REJECTED],
        timeout_ms=timeout_ms,
    )

    if result is None:
        return (
            f"TIMEOUT — no response after {timeout_ms // 1000}s.\n"
            f"Task [{task_id}] remains in needs_review. Prompt the user to review."
        )

    topic, data = result
    project_name = Path(cwd).name

    if topic == _TASK_APPROVED:
        session_done = _db_get_cc_session_num(ws_id)
        _db_update_task_status(ws_id, task_id, "done", session_done=session_done)
        all_tasks = _db_list_tasks(ws_id)
        md = _render_task_md(all_tasks)
        _upsert_artifact(ws_id, project_name, ATYPE_TASK, "task.md", md,
                         summary=f"Task [{task_id}] approved → done")
        wire = f"  context-core session_done={session_done}" if session_done else ""
        return f"APPROVED ✅\nTask [{task_id}] marked done.{wire}\nHuman: {data}"

    elif topic == _TASK_FEEDBACK:
        return (
            f"FEEDBACK — revise task [{task_id}] before marking done.\n\n"
            f"Human feedback:\n{data}\n\n"
            f"Update your work, then call workspace_task_request_review() again."
        )

    elif topic == _TASK_REJECTED:
        _db_update_task_status(ws_id, task_id, "todo")
        return (
            f"REJECTED — task [{task_id}] reset to todo.\n\n"
            f"Reason: {data}\n\n"
            f"Revise your approach and redo the work."
        )

    return f"[workspace_await_task_approval] Unexpected topic: {topic}"


def workspace_override(cwd: str, reason: str) -> str:
    """
    Request a one-time or session-duration write gate override via DN notification.
    Model must provide a reason. Human chooses: Allow Once / Allow Session / Reject.

    Args:
        cwd:    Project directory.
        reason: Why the model needs to bypass the write gate.
    """
    ws_id = _registry_ws_id(cwd)
    if not ws_id:
        return f"[workspace_override] No workspace for {cwd}"

    project_name = Path(cwd).name

    _OVERRIDE_ONCE    = "termpipe.workspace.override.once"
    _OVERRIDE_SESSION = "termpipe.workspace.override.session"
    _OVERRIDE_REJECT  = "termpipe.workspace.override.rejected"

    try:
        DesktopNotifier, Urgency, Button = _ensure_desktop_notifier_setup()
        loop_thread = _get_dn_event_loop()

        async def send():
            notifier = DesktopNotifier(app_name="TermPipe")
            await notifier.send(
                title=f"⚠️ Write Gate Override: {project_name}",
                message=f"Claude wants to bypass the write gate.\n\nReason: {reason}",
                urgency=Urgency.Critical,
                buttons=[
                    Button(title="✓ Allow Once",    on_pressed=lambda: _bus_pub(_OVERRIDE_ONCE, "once")),
                    Button(title="✓ Allow Session", on_pressed=lambda: _bus_pub(_OVERRIDE_SESSION, "session")),
                    Button(title="✗ Reject",         on_pressed=lambda: _bus_pub(_OVERRIDE_REJECT, "rejected")),
                ],
                timeout=0,
            )

        loop_thread.run_coroutine(send())
    except Exception as e:
        return f"[workspace_override] Failed to send notification: {e}"

    result = _bus_poll(
        [_OVERRIDE_ONCE, _OVERRIDE_SESSION, _OVERRIDE_REJECT],
        timeout_ms=120000,
    )

    if result is None:
        return (
            "TIMEOUT — no override response after 120s.\n"
            "Write gate remains active. Complete the required workspace steps."
        )

    topic, data = result

    if topic == _OVERRIDE_ONCE:
        set_override(ws_id, "once")
        return (
            "OVERRIDE GRANTED (once) ✅\n"
            "You may perform ONE write operation. The gate re-activates immediately after.\n"
            f"Reason on record: {reason}"
        )
    elif topic == _OVERRIDE_SESSION:
        set_override(ws_id, "session")
        return (
            "OVERRIDE GRANTED (session) ✅\n"
            "Write tools are unlocked for the remainder of this session.\n"
            f"Reason on record: {reason}"
        )
    elif topic == _OVERRIDE_REJECT:
        return (
            "OVERRIDE REJECTED ⛔\n"
            "Human declined the bypass request.\n"
            "Complete the required workspace flow before using write tools."
        )

    return f"[workspace_override] Unexpected topic: {topic}"
