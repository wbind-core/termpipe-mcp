"""
MCP tool registration — minimal dispatcher, imports from modular files.
"""
import sys
from pathlib import Path

# Add vendor dependencies (immutabledict, bidict, dbus-fast)
sys.path.insert(0, str(Path(__file__).parent.parent / "vendor"))

# Add desktop_notifier source (vendored in termpipe_mcp)
sys.path.insert(0, str(Path(__file__).parent.parent / "desktop-notifier" / "src"))

from ._plan import (
    workspace_init as _workspace_init,
    workspace_plan_update as _workspace_plan_update,
    workspace_walkthrough_update as _workspace_walkthrough_update,
    workspace_doc_update as _workspace_doc_update,
)
from ._review import (
    workspace_request_review as _workspace_request_review,
    workspace_await_approval as _workspace_await_approval,
    workspace_task_request_review as _workspace_task_request_review,
    workspace_await_task_approval as _workspace_await_task_approval,
)
from ._task_ops import (
    workspace_task_create as _workspace_task_create,
    workspace_task_update as _workspace_task_update,
    workspace_task_set_status as _workspace_task_set_status,
    workspace_task_query as _workspace_task_query,
)
from ._workspace import (
    workspace_status as _workspace_status,
    workspace_list as _workspace_list,
    workspace_load as _workspace_load,
)
from ._phase import check_write_gate, consume_once_override, ws_id_from_cwd, checkpoint_suffix
from ._review import workspace_override as _workspace_override


def _gated(cwd: str, fn, *args, **kwargs):
    """
    Gate wrapper for write tools. Checks phase, enforces override lifecycle,
    appends checkpoint prompt if due.
    """
    ws_id = ws_id_from_cwd(cwd)
    if not ws_id:
        return f"⛔ WRITE BLOCKED — no workspace found for {cwd}. Run workspace_init first."
    gate = check_write_gate(ws_id)
    if not gate["allowed"]:
        return gate["reason"]
    result = fn(*args, **kwargs)
    consume_once_override(ws_id)
    cp = checkpoint_suffix(ws_id)
    return f"{result}{cp}" if cp else result


def register_tools(mcp):
    """Register all workspace_* tools with the MCP server."""

    @mcp.tool()
    def workspace_init(cwd: str, goal: str, task_items: str = None):
        return _workspace_init(cwd=cwd, goal=goal, task_items=task_items)

    @mcp.tool()
    def workspace_plan_update(cwd: str, content: str, summary: str = None, status: str = None):
        return _workspace_plan_update(cwd=cwd, content=content, summary=summary, status=status)

    @mcp.tool()
    def workspace_walkthrough_update(cwd: str, content: str, summary: str = None):
        return _workspace_walkthrough_update(cwd=cwd, content=content, summary=summary)

    @mcp.tool()
    def workspace_doc_update(cwd: str, name: str, content: str, summary: str = None):
        return _workspace_doc_update(cwd=cwd, name=name, content=content, summary=summary)

    @mcp.tool()
    def workspace_request_review(cwd: str, message: str = None):
        return _workspace_request_review(cwd=cwd, message=message)

    @mcp.tool()
    def workspace_await_approval(cwd: str, timeout_ms: int = 180000):
        return _workspace_await_approval(cwd=cwd, timeout_ms=timeout_ms)

    @mcp.tool()
    def workspace_task_request_review(cwd: str, task_id: int, message: str = None):
        return _workspace_task_request_review(cwd=cwd, task_id=task_id, message=message)

    @mcp.tool()
    def workspace_await_task_approval(cwd: str, task_id: int, timeout_ms: int = 180000):
        return _workspace_await_task_approval(cwd=cwd, task_id=task_id, timeout_ms=timeout_ms)

    @mcp.tool()
    def workspace_task_create(
        cwd: str,
        title: str,
        description: str = None,
        priority: str = "medium",
        task_type: str = None,
        completion_requirements: str = None,
        output_format: str = None,
        depends_on: str = None,
        tags: str = None,
        notes: str = None,
    ):
        return _workspace_task_create(
            cwd=cwd, title=title, description=description, priority=priority,
            task_type=task_type, completion_requirements=completion_requirements,
            output_format=output_format, depends_on=depends_on, tags=tags, notes=notes,
        )

    @mcp.tool()
    def workspace_task_update(cwd: str, action: str, item_text: str = None, item_id: int = None, summary: str = None):
        return _workspace_task_update(cwd=cwd, action=action, item_text=item_text, item_id=item_id, summary=summary)

    @mcp.tool()
    def workspace_task_set_status(cwd: str, task_id: int, status: str, notes: str = None):
        return _workspace_task_set_status(cwd=cwd, task_id=task_id, status=status, notes=notes)

    @mcp.tool()
    def workspace_task_query(cwd: str, status: str = None, priority: str = None, task_type: str = None):
        return _workspace_task_query(cwd=cwd, status=status, priority=priority, task_type=task_type)

    @mcp.tool()
    def workspace_status(cwd: str):
        return _workspace_status(cwd=cwd)

    @mcp.tool()
    def workspace_list(filter: str = ""):
        return _workspace_list(filter=filter)

    @mcp.tool()
    def workspace_load(cwd: str):
        return _workspace_load(cwd=cwd)

    @mcp.tool()
    def workspace_override(cwd: str, reason: str):
        return _workspace_override(cwd=cwd, reason=reason)
