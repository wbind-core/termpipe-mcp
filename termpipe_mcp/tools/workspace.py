"""
Workspace Artifact Tools for TermPipe MCP Server.

Implements Antigravity-style persistent markdown artifacts (task, implementation
plan, walkthrough, and arbitrary "other" docs) with two-layer durability:

  Layer 1 — kc-bus (volatile, live):
      termpipe.workspace.active      published by list_tools on session start
      termpipe.workspace.task        current task.md content
      termpipe.workspace.plan        current implementation_plan.md content
      termpipe.workspace.walkthrough current walkthrough.md content
      termpipe.workspace.<name>      any ARTIFACT_TYPE_OTHER doc

  Layer 2 — per-workspace SQLite (durable, versioned):
      ~/.context-core/workspaces/ws_<id>/workspace.db  ← artifacts table
      ~/Documents/TermPipe/Workspaces/<project>/        ← human-readable files
        task.md, task.md.resolved.0, task.md.resolved.1 …
        implementation_plan.md, implementation_plan.md.resolved.N …
        walkthrough.md, walkthrough.md.resolved.N …

Integration with context_core:
  - list_tools writes ~/.context-core/current_workspace (already done in system.py)
  - workspace_resume(cwd) is called by list_tools to republish live artifacts
    to the bus so every session gets current state for free, zero extra calls
  - Workspace ID is looked up from context_core's registry.db by project path
"""

from __future__ import annotations

import json
import os
import re
import socket
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HOME          = Path.home()
_CC_DIR        = _HOME / ".context-core"
_CC_REGISTRY   = _CC_DIR / "registry.db"
_CC_WORKSPACES = _CC_DIR / "workspaces"
_ARTIFACTS_ROOT = _HOME / "Documents" / "TermPipe" / "Workspaces"
_KC_SOCK       = Path(f"/run/user/{os.getuid()}/kernclip-bus.sock")

# Bus topic namespace
_TOPIC_ACTIVE      = "termpipe.workspace.active"
_TOPIC_TASK        = "termpipe.workspace.task"
_TOPIC_PLAN        = "termpipe.workspace.plan"
_TOPIC_WALKTHROUGH = "termpipe.workspace.walkthrough"

# Artifact type constants (mirrors Antigravity metadata)
ATYPE_TASK  = "ARTIFACT_TYPE_TASK"
ATYPE_PLAN  = "ARTIFACT_TYPE_IMPLEMENTATION_PLAN"
ATYPE_WALK  = "ARTIFACT_TYPE_WALKTHROUGH"
ATYPE_OTHER = "ARTIFACT_TYPE_OTHER"

_ATYPE_TO_TOPIC = {
    ATYPE_TASK: _TOPIC_TASK,
    ATYPE_PLAN: _TOPIC_PLAN,
    ATYPE_WALK: _TOPIC_WALKTHROUGH,
}

# ---------------------------------------------------------------------------
# kc-bus low-level (no SDK dependency — raw socket)
# ---------------------------------------------------------------------------

def _bus_send(op: str, topic: str, data: str, mime: str = "text/plain") -> dict | None:
    if not _KC_SOCK.exists():
        return None
    try:
        msg = json.dumps({"op": op, "topic": topic, "mime": mime, "data": data}) + "\n"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            s.connect(str(_KC_SOCK))
            s.sendall(msg.encode())
            buf = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
                if b"\n" in buf:
                    break
        return json.loads(buf.split(b"\n")[0])
    except Exception:
        return None


def _bus_pub(topic: str, data: str, mime: str = "text/plain") -> bool:
    r = _bus_send("pub", topic, data, mime)
    return bool(r and r.get("ok"))


def _bus_get(topic: str) -> str | None:
    r = _bus_send("get", topic, "")
    if r and r.get("ok") and r.get("data"):
        return r["data"]
    return None


# ---------------------------------------------------------------------------
# context_core registry helpers
# ---------------------------------------------------------------------------

def _registry_ws_id(project_path: str) -> str | None:
    """Look up workspace_id for a project path from context_core registry."""
    if not _CC_REGISTRY.exists():
        return None
    try:
        conn = sqlite3.connect(str(_CC_REGISTRY))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT workspace_id FROM workspace_folders WHERE folder_path = ?",
            (str(Path(project_path).resolve()),)
        ).fetchone()
        conn.close()
        return row["workspace_id"] if row else None
    except Exception:
        return None


def _registry_all_workspaces() -> list[dict]:
    if not _CC_REGISTRY.exists():
        return []
    try:
        conn = sqlite3.connect(str(_CC_REGISTRY))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT workspace_id, display_name, last_accessed FROM workspaces "
            "ORDER BY last_accessed DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _ws_db_path(ws_id: str) -> Path:
    return _CC_WORKSPACES / f"ws_{ws_id}" / "workspace.db"


# ---------------------------------------------------------------------------
# Per-workspace DB — artifacts table
# ---------------------------------------------------------------------------

def _ensure_artifacts_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS artifacts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            artifact_type TEXT NOT NULL,
            name          TEXT NOT NULL,
            content       TEXT NOT NULL DEFAULT '',
            version       INTEGER NOT NULL DEFAULT 0,
            summary       TEXT,
            updated_at    TEXT NOT NULL,
            UNIQUE(name)
        )
    """)
    conn.commit()


def _get_ws_conn(ws_id: str) -> sqlite3.Connection | None:
    db = _ws_db_path(ws_id)
    if not db.exists():
        return None
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    _ensure_artifacts_table(conn)
    return conn


def _db_read_artifact(ws_id: str, name: str) -> dict | None:
    conn = _get_ws_conn(ws_id)
    if not conn:
        return None
    row = conn.execute("SELECT * FROM artifacts WHERE name = ?", (name,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _db_write_artifact(
    ws_id: str,
    artifact_type: str,
    name: str,
    content: str,
    summary: str | None = None,
) -> int:
    """Upsert artifact, bump version, return new version number."""
    conn = _get_ws_conn(ws_id)
    if not conn:
        raise RuntimeError(f"No workspace DB for ws_{ws_id}")
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT version FROM artifacts WHERE name = ?", (name,)
    ).fetchone()
    if existing:
        new_version = existing["version"] + 1
        conn.execute(
            "UPDATE artifacts SET content=?, version=?, summary=?, updated_at=? WHERE name=?",
            (content, new_version, summary, now, name),
        )
    else:
        new_version = 0
        conn.execute(
            "INSERT INTO artifacts (artifact_type, name, content, version, summary, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (artifact_type, name, content, new_version, summary, now),
        )
    conn.commit()
    conn.close()
    return new_version


def _db_list_artifacts(ws_id: str) -> list[dict]:
    conn = _get_ws_conn(ws_id)
    if not conn:
        return []
    rows = conn.execute(
        "SELECT artifact_type, name, version, summary, updated_at "
        "FROM artifacts ORDER BY artifact_type"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# File-layer (human-readable + .resolved.N versioned snapshots)
# ---------------------------------------------------------------------------

def _artifact_dir(project_name: str) -> Path:
    d = _ARTIFACTS_ROOT / project_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_artifact_files(project_name: str, name: str, content: str, version: int) -> Path:
    d = _artifact_dir(project_name)
    main = d / name
    main.write_text(content, encoding="utf-8")
    snapshot = d / f"{name}.resolved.{version}"
    snapshot.write_text(content, encoding="utf-8")
    return main


def _write_metadata(
    project_name: str, name: str, artifact_type: str,
    summary: str | None, version: int
) -> None:
    d = _artifact_dir(project_name)
    meta = {
        "artifactType": artifact_type,
        "summary": summary or "",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "version": str(version),
    }
    (d / f"{name}.metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Core upsert — single entry point for all artifact mutations
# ---------------------------------------------------------------------------

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
    Side-effect of list_tools. Announces active workspace and republishes
    all current artifacts to their bus topics. Zero-cost if bus is down or
    workspace is unknown.
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

    for art in _db_list_artifacts(ws_id):
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


# ---------------------------------------------------------------------------
# Task item helpers
# ---------------------------------------------------------------------------

def _next_task_id(content: str) -> int:
    ids = re.findall(r"<!--\s*id:\s*(\d+)\s*-->", content)
    return max((int(i) for i in ids), default=0) + 1


def _set_task_status(content: str, item_id: int, status: str) -> tuple[str, bool]:
    marker = {"done": "[x]", "in_progress": "[/]", "todo": "[ ]"}.get(status, "[ ]")
    pattern = re.compile(
        r"(-\s*)\[[x/ ]\](\s*.+?)(<!--\s*id:\s*" + str(item_id) + r"\s*-->)",
        re.IGNORECASE
    )
    new, count = pattern.subn(
        lambda m: f"{m.group(1)}{marker}{m.group(2)}{m.group(3)}", content
    )
    return new, count > 0


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

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
    ) -> str:
        """
        Replace implementation_plan.md for the active workspace.

        Bumps version, writes .resolved.N snapshot, publishes to
        termpipe.workspace.plan on the bus.

        Args:
            cwd:     Project directory.
            content: Full markdown content for the implementation plan.
            summary: Optional one-line summary stored in metadata.
        """
        ws_id = _registry_ws_id(cwd)
        if not ws_id:
            return f"[workspace_plan_update] No workspace for {cwd}"

        project_name = Path(cwd).name
        r = _upsert_artifact(ws_id, project_name, ATYPE_PLAN,
                             "implementation_plan.md", content, summary=summary)
        return (
            f"implementation_plan.md updated  v{r['version']}  "
            f"bus={'✓' if r['bus_ok'] else '✗'}  {r['file_path']}"
        )

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

        out = f"Workspace: {project_name}  (ws_{ws_id})\n"
        out += f"Artifacts dir: {_ARTIFACTS_ROOT / project_name}\n"
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

                out += (
                    f"📄 {art['name']}  [{art['artifact_type']}]\n"
                    f"   version : {art['version']}\n"
                    f"   updated : {art['updated_at']}\n"
                    f"   summary : {art['summary'] or '—'}\n"
                    f"   bus     : {topic}  {bus_live}\n"
                    f"   preview :\n    {preview}\n\n"
                )

        return out.rstrip()

    @mcp.tool()
    def workspace_list() -> str:
        """
        List all workspaces known to context_core with artifact counts.
        """
        workspaces = _registry_all_workspaces()
        if not workspaces:
            return "No workspaces found in context_core registry."

        active_file = _CC_DIR / "current_workspace"
        active = active_file.read_text().strip() if active_file.exists() else None

        out = "Workspaces\n" + "=" * 50 + "\n\n"
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
