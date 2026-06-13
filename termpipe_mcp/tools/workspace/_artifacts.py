"""
Core artifact upsert and workspace resume logic.
"""
import json
from pathlib import Path
from datetime import datetime, timezone

from ._bus import _bus_pub, _bus_get, _ATYPE_TO_TOPIC, _ARTIFACTS_ROOT, _TOPIC_ACTIVE, _TOPIC_INIT
from ._db import _db_read_artifact, _db_write_artifact, _db_list_artifacts, _db_list_tasks
from ._files import _artifact_dir, _write_artifact_files, _write_metadata
from ._registry import _registry_ws_id
from ._task import _get_plan_status, _pack_summary

def _upsert_artifact(
    ws_id: str,
    project_name: str,
    artifact_type: str,
    name: str,
    content: str,
    summary: str | None = None,
) -> dict:
    """Persist artifact to DB + files + bus. Returns result dict."""
    version = _db_write_artifact(ws_id, artifact_type, name, content, summary)
    _write_artifact_files(project_name, name, content, version)
    _write_metadata(project_name, name, artifact_type, summary, version)

    topic = _ATYPE_TO_TOPIC.get(
        artifact_type,
        f"termpipe.workspace.{name.removesuffix('.md')}"
    )
    payload = json.dumps({
        "ws_id": ws_id,
        "project": project_name,
        "artifact_type": artifact_type,
        "name": name,
        "version": version,
        "content": content,
        "summary": summary or "",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    bus_ok = _bus_pub(topic, payload, mime="application/json")

    return {
        "version": version,
        "bus_ok": bus_ok,
        "file_path": str(_ARTIFACTS_ROOT / project_name / name),
        "topic": topic,
    }


# ---------------------------------------------------------------------------
# Session-start resume hook — called by list_tools in system.py
# ---------------------------------------------------------------------------

def workspace_resume(cwd: str) -> None:
    """
    Side-effect of list_tools. Announces active workspace, republishes
    all current artifacts to their bus topics, and backfills any missing
    workspace.state.json files. Zero-cost if bus is down or workspace unknown.
    """
    ws_id = _registry_ws_id(cwd)
    if not ws_id:
        return

    project_name = Path(cwd).name

    _bus_pub(_TOPIC_ACTIVE, json.dumps({
        "ws_id": ws_id,
        "project": project_name,
        "path": cwd,
        "resumed_at": datetime.now(timezone.utc).isoformat(),
    }), mime="application/json")

    # Publish init event with full context for omnis agent
    try:
        tasks = _db_list_tasks(ws_id) or []
    except Exception:
        tasks = []
    try:
        artifacts = _db_list_artifacts(ws_id) or []
    except Exception:
        artifacts = []

    init_payload = {
        "ws_id": ws_id,
        "project": project_name,
        "path": cwd,
        "is_new": False,
        "tasks": tasks,
        "artifacts": [a.get("name", str(a)) for a in artifacts],
        "instruction": f"Workspace '{project_name}' at {cwd}. You will receive task updates.",
    }

    _bus_pub(_TOPIC_INIT, json.dumps(init_payload), mime="application/json")

    for art in artifacts:
        row = _db_read_artifact(ws_id, art["name"])
        if not row:
            continue
        topic = _ATYPE_TO_TOPIC.get(
            art["artifact_type"],
            f"termpipe.workspace.{art['name'].removesuffix('.md')}"
        )
        payload = json.dumps({
            "ws_id": ws_id,
            "project": project_name,
            "artifact_type": art["artifact_type"],
            "name": art["name"],
            "version": art["version"],
            "content": row["content"],
            "summary": art["summary"] or "",
            "updated_at": art["updated_at"],
        })
        _bus_pub(topic, payload, mime="application/json")

    # Backfill missing workspace.state.json files — fire-and-forget
    try:
        from ._state import backfill_all_states
        import threading
        threading.Thread(target=backfill_all_states, daemon=True).start()
    except Exception:
        pass
