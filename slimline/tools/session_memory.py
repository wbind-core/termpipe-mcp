"""
Per-cwd session memory for TermPipe Slimline — a context-core-compatible slice.

Transferred ideas (from vocoder's context_core, primitive version):
- Workspace = the project directory. Every workspace is scoped by its cwd;
  the slug is sha1(resolved cwd). Mirrors workspace.py's directory-centric
  paradigm and registry.
- list_tools() is the semantic trigger: touching a session and assembling the
  resume briefing happens there (runtime query assembles context, cf.
  retrieval.py's multi-source assembly: STM = this visit, LTM = past notes).
- Significance is scored deterministically AT WRITE TIME (ingestion.py's
  write-time judgment), with recency decay applied at read time. No
  embeddings, no black box: the scorer is five lines and fully explainable.
  (Craig's standing rule: deterministic techniques first; the model is not
  load-bearing. The seam for a future embedding_fn is left open, mirroring
  ContextRetriever's pluggable embedding_fn.)
- Outcome feedback: errors and task completions are logged as events; the
  briefing surfaces recent errors (telemetry-lite, cf. ingestion.py's
  TelemetryEntry and pattern_detector.py).

Schema (sqlite, one file):
  workspaces(slug PK, cwd, first_seen, last_seen, visits)
  events(id, slug, ts, kind, summary, detail)      # kind: note|decision|error|task
  notes(id, slug, ts, kind, text, significance, pinned)
"""

from __future__ import annotations

import hashlib
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def _db_path() -> Path:
    override = os.environ.get("SLIMLINE_SESSIONS_DB")
    if override:
        return Path(override)
    p = Path.home() / ".local" / "share" / "termpipe-slim" / "sessions.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(_db_path()))
    con.execute(
        "CREATE TABLE IF NOT EXISTS workspaces("
        "slug TEXT PRIMARY KEY, cwd TEXT NOT NULL,"
        "first_seen TEXT, last_seen TEXT, visits INTEGER DEFAULT 0)")
    con.execute(
        "CREATE TABLE IF NOT EXISTS events("
        "id INTEGER PRIMARY KEY, slug TEXT NOT NULL, ts TEXT NOT NULL,"
        "kind TEXT NOT NULL, summary TEXT NOT NULL, detail TEXT DEFAULT '')")
    con.execute(
        "CREATE TABLE IF NOT EXISTS notes("
        "id INTEGER PRIMARY KEY, slug TEXT NOT NULL, ts TEXT NOT NULL,"
        "kind TEXT NOT NULL, text TEXT NOT NULL,"
        "significance REAL NOT NULL, pinned INTEGER DEFAULT 0)")
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_slug_ts ON events(slug, ts)")
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_notes_slug ON notes(slug)")
    return con


def _slug(cwd: str) -> str:
    return hashlib.sha1(str(Path(cwd).resolve()).encode()).hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Significance — deterministic, explainable, scored at write time
# ---------------------------------------------------------------------------

KIND_BASE = {
    "decision": 0.9,   # a choice that constrains future work
    "error": 0.75,     # something that failed — worth not repeating
    "task": 0.7,       # a completed task (outcome feedback)
    "note": 0.6,       # general observation
    "tool": 0.3,       # routine tool activity (rarely pinned)
}

RECENCY_HALFLIFE_DAYS = 14.0


def score_significance(kind: str, pinned: bool = False) -> float:
    """Write-time significance in [0, 1]. Pinned always wins."""
    if pinned:
        return 1.0
    return max(0.0, min(1.0, KIND_BASE.get(kind, 0.5)))


def _effective_score(significance: float, ts: str, pinned: int) -> float:
    """Read-time score: pinned first, then significance with recency decay."""
    if pinned:
        return 2.0  # sorts above everything unpinned
    try:
        age_days = (datetime.now(timezone.utc)
                    - datetime.fromisoformat(ts)).total_seconds() / 86400.0
    except Exception:
        age_days = 0.0
    return significance * math.exp(-max(0.0, age_days) / RECENCY_HALFLIFE_DAYS)


def _rel(ts: str) -> str:
    try:
        age = (datetime.now(timezone.utc)
               - datetime.fromisoformat(ts)).total_seconds()
    except Exception:
        return "?"
    if age < 90:
        return "just now"
    if age < 3600:
        return f"{int(age // 60)}m ago"
    if age < 86400:
        return f"{int(age // 3600)}h ago"
    return f"{int(age // 86400)}d ago"


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------

def touch_session(cwd: str) -> str:
    """Record a visit. Called by list_tools — the semantic resume trigger."""
    slug = _slug(cwd)
    now = _now()
    try:
        con = _connect()
        row = con.execute(
            "SELECT visits FROM workspaces WHERE slug=?", (slug,)).fetchone()
        if row:
            con.execute(
                "UPDATE workspaces SET last_seen=?, visits=visits+1 WHERE slug=?",
                (now, slug))
        else:
            con.execute(
                "INSERT INTO workspaces(slug, cwd, first_seen, last_seen, visits)"
                " VALUES(?,?,?,?,1)",
                (slug, str(Path(cwd).resolve()), now, now))
        con.commit()
    except Exception:
        pass
    finally:
        try:
            con.close()
        except Exception:
            pass
    return slug


def log_event(cwd: str, kind: str, summary: str, detail: str = "") -> None:
    slug = _slug(cwd)
    try:
        con = _connect()
        con.execute(
            "INSERT INTO events(slug, ts, kind, summary, detail)"
            " VALUES(?,?,?,?,?)",
            (slug, _now(), kind, summary[:500], detail[:2000]))
        con.commit()
        con.close()
    except Exception:
        pass


def add_note(cwd: str, kind: str, text: str, pinned: bool = False) -> float:
    """Pin a note/decision. Returns its write-time significance."""
    sig = score_significance(kind, pinned)
    slug = _slug(cwd)
    try:
        con = _connect()
        con.execute(
            "INSERT INTO notes(slug, ts, kind, text, significance, pinned)"
            " VALUES(?,?,?,?,?,?)",
            (slug, _now(), kind, text[:2000], sig, 1 if pinned else 0))
        con.execute(
            "INSERT INTO events(slug, ts, kind, summary) VALUES(?,?,?,?)",
            (slug, _now(), kind, text[:500]))
        con.commit()
        con.close()
    except Exception:
        pass
    return sig


# ---------------------------------------------------------------------------
# Read path — the resume briefing assembled at list_tools time
# ---------------------------------------------------------------------------

def _ranked_notes(slug: str, limit: int,
                  query: Optional[str] = None) -> List[dict]:
    try:
        con = _connect()
        rows = con.execute(
            "SELECT ts, kind, text, significance, pinned FROM notes"
            " WHERE slug=? ORDER BY ts DESC LIMIT 500", (slug,)).fetchall()
        con.close()
    except Exception:
        return []
    items = []
    for ts, kind, text, sig, pinned in rows:
        if query and query.lower() not in text.lower():
            continue
        items.append({
            "ts": ts, "kind": kind, "text": text,
            "score": _effective_score(sig, ts, pinned),
            "pinned": bool(pinned),
        })
    items.sort(key=lambda i: (i["score"], i["ts"]), reverse=True)
    return items[:limit]


def briefing(cwd: str, limit: int = 5) -> str:
    """One compact resume block for list_tools. Zero-cost on failure."""
    slug = _slug(cwd)
    try:
        con = _connect()
        ws = con.execute(
            "SELECT cwd, first_seen, last_seen, visits FROM workspaces"
            " WHERE slug=?", (slug,)).fetchone()
        errs = con.execute(
            "SELECT ts, summary FROM events WHERE slug=? AND kind='error'"
            " ORDER BY ts DESC LIMIT 3", (slug,)).fetchall()
        n_notes = con.execute(
            "SELECT COUNT(*) FROM notes WHERE slug=?", (slug,)).fetchone()[0]
        con.close()
    except Exception:
        return ""
    if not ws:
        return ""
    _, _, last_seen, visits = ws
    lines = [f"Session memory — visit #{visits}"
             + (f", last here {_rel(last_seen)}" if visits > 1 else " (first visit)") + ":"]
    notes = _ranked_notes(slug, limit)
    for n in notes:
        pin = "📌 " if n["pinned"] else ""
        lines.append(f"• {pin}[{n['kind']}] {n['text'][:160]} ({_rel(n['ts'])})")
    if errs:
        lines.append("Recent errors:")
        for ts, summary in errs:
            lines.append(f"• {summary[:160]} ({_rel(ts)})")
    extra = n_notes - len(notes)
    if extra > 0:
        lines.append(f"({extra} more — session_recall(cwd) for the full list)")
    if not notes and not errs and visits <= 1:
        lines.append("(nothing recorded yet — pin decisions with session_note(cwd, text, kind='decision'))")
    return "\n".join(lines)


def recall(cwd: str, limit: int = 20,
           query: Optional[str] = None) -> str:
    """Fuller list for session_recall: notes + recent events."""
    slug = _slug(cwd)
    notes = _ranked_notes(slug, limit, query)
    if not notes:
        return f"[session_recall] nothing recorded for {cwd}" + (
            f" matching '{query}'" if query else "")
    lines = [f"Session recall — {cwd}" + (f" (filter: '{query}')" if query else "") + ":"]
    for n in notes:
        pin = "📌 " if n["pinned"] else ""
        lines.append(f"• {pin}[{n['kind']}] {n['text'][:300]} ({_rel(n['ts'])})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

def register_tools(mcp: FastMCP):
    @mcp.tool()
    def session_note(cwd: str, text: str, kind: str = "note",
                     pinned: bool = False) -> str:
        """
        Pin a note or decision to this workspace's session memory (scoped by
        cwd). Decisions shape future work; errors keep you from repeating
        them. Significance is scored at write time; the resume briefing in
        list_tools surfaces the highest-scoring items automatically.

        Args:
            cwd: Project directory (the workspace scope).
            text: The note text (what was decided, learned, or went wrong).
            kind: note | decision | error | task. Defaults to note.
            pinned: Pin it — pinned items always sort first in recalls.
        """
        kind = kind if kind in KIND_BASE else "note"
        sig = add_note(cwd, kind, text, pinned)
        return (f"📌 Noted [{kind}] significance={sig:.2f}"
                f" for {Path(cwd).resolve()}")

    @mcp.tool()
    def session_recall(cwd: str, limit: int = 20,
                       query: Optional[str] = None) -> str:
        """
        Recall this workspace's session memory (scoped by cwd): pinned
        decisions, notes, and errors, ranked by significance with recency
        decay. Deeper layer beneath the list_tools resume briefing.

        Args:
            cwd: Project directory (the workspace scope).
            limit: Max items (default 20).
            query: Optional keyword filter.
        """
        return recall(cwd, limit=max(1, min(100, limit)), query=query)
