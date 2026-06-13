"""
telemetry.py — Tool-call telemetry for TermPipe MCP
=====================================================
Wraps every @mcp.tool() registration transparently so every invocation
(success or failure) is recorded to ~/.termpipe/telemetry.db (SQLite).

Model/environment-agnostic: the intercept lives at the FastMCP dispatch
layer, so it fires regardless of whether the caller is Claude Desktop,
iFlow, Gemini CLI, or any future client.

Usage — in server.py, immediately after mcp = FastMCP("termpipe"):

    from termpipe_mcp.telemetry import install_telemetry_middleware
    install_telemetry_middleware(mcp)

That's it. Every subsequent @mcp.tool() call will be wrapped.
"""

import functools
import inspect
import json
import os
import sqlite3
import threading
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# DB PATH & SCHEMA
# ---------------------------------------------------------------------------

_DB_PATH = Path.home() / ".termpipe" / "telemetry.db"
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tool_calls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT    NOT NULL,               -- ISO-8601 UTC
    session_id    TEXT,                           -- from env/file if available
    tool_name     TEXT    NOT NULL,
    category      TEXT,                           -- FILE, GIT, SYSTEM, …
    args_json     TEXT,                           -- sanitised arg keys+values
    duration_ms   REAL,
    success       INTEGER NOT NULL DEFAULT 1,     -- 1=ok, 0=error
    error_msg     TEXT,
    result_len    INTEGER                         -- len(str(result)) proxy for output size
);

CREATE TABLE IF NOT EXISTS edit_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT    NOT NULL,               -- ISO-8601 UTC
    session_id    TEXT    NOT NULL,
    tool_call_no  INTEGER,                        -- per-session incrementing counter
    tool_name     TEXT    NOT NULL,               -- write_file, smart_replace, etc.
    path          TEXT    NOT NULL,               -- absolute resolved file path
    cwd           TEXT,                           -- working directory at time of edit
    old_content   BLOB,                           -- plain text or zlib bytes
    new_content   BLOB,
    compressed    INTEGER NOT NULL DEFAULT 0      -- 0=plain text, 1=zlib compressed
);

CREATE INDEX IF NOT EXISTS idx_tool_name  ON tool_calls   (tool_name);
CREATE INDEX IF NOT EXISTS idx_tc_ts      ON tool_calls   (ts);
CREATE INDEX IF NOT EXISTS idx_success    ON tool_calls   (success);
CREATE INDEX IF NOT EXISTS idx_eh_session ON edit_history (session_id);
CREATE INDEX IF NOT EXISTS idx_eh_path    ON edit_history (path);
CREATE INDEX IF NOT EXISTS idx_eh_ts      ON edit_history (ts);
"""

# Module → category mapping (mirrors system.py MODULE_CAT)
_MOD_CAT = {
    "git": "GIT", "process": "PROCESS", "termf": "TERMF", "iflow": "IFLOW",
    "files": "FILE", "surgical": "SURGICAL", "apps": "APPS", "wbind": "WBIND",
    "search": "SEARCH", "thread": "THREAD", "system": "SYSTEM", "debug": "DEBUG",
    "gemini_debug": "GEMINI", "web_search": "WEB_SEARCH", "web_fetch": "WEB_FETCH",
    "workspace": "TOOLS", "writers": "WRITERS", "readers": "READERS",
    "replacers": "REPLACERS", "formatters": "FORMATTERS",
}

# ---------------------------------------------------------------------------
# THREAD-LOCAL CONNECTION POOL
# ---------------------------------------------------------------------------

_local = threading.local()


def _conn() -> sqlite3.Connection:
    if not getattr(_local, "conn", None):
        _local.conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _local.conn.executescript(_SCHEMA)
        _local.conn.commit()
    return _local.conn


# ---------------------------------------------------------------------------
# SANITISE ARGS  (strip large blobs, keep keys + short values)
# ---------------------------------------------------------------------------

_MAX_VALUE_LEN = 300  # chars before truncation
_BLOB_KEYS = {"content", "file_text", "text", "data", "output", "result"}


def _sanitise_args(kwargs: dict) -> str:
    out = {}
    for k, v in kwargs.items():
        if k in _BLOB_KEYS:
            s = str(v)
            out[k] = f"<{len(s)} chars>" if len(s) > _MAX_VALUE_LEN else s
        else:
            s = str(v)
            out[k] = s[:_MAX_VALUE_LEN] + "…" if len(s) > _MAX_VALUE_LEN else s
    try:
        return json.dumps(out)
    except Exception:
        return "{}"


# ---------------------------------------------------------------------------
# SESSION ID  (stable per server process, optionally from workspace file)
# ---------------------------------------------------------------------------

_SESSION_ID: Optional[str] = None


def _get_session_id() -> str:
    global _SESSION_ID
    if _SESSION_ID:
        return _SESSION_ID
    # Try to read from context-core current session marker
    try:
        f = Path.home() / ".context-core" / "current_session_id"
        if f.exists():
            _SESSION_ID = f.read_text().strip()[:64]
            return _SESSION_ID
    except Exception:
        pass
    # Fallback: PID-based stable ID for this server process
    import os
    _SESSION_ID = f"pid-{os.getpid()}"
    return _SESSION_ID


# ---------------------------------------------------------------------------
# RECORD
# ---------------------------------------------------------------------------

def record(
    tool_name: str,
    category: str,
    args_json: str,
    duration_ms: float,
    success: bool,
    error_msg: Optional[str],
    result_len: int,
) -> None:
    """Insert one row into tool_calls. Fire-and-forget; never raises."""
    try:
        c = _conn()
        c.execute(
            """INSERT INTO tool_calls
               (ts, session_id, tool_name, category, args_json,
                duration_ms, success, error_msg, result_len)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                _get_session_id(),
                tool_name,
                category,
                args_json,
                round(duration_ms, 2),
                1 if success else 0,
                error_msg,
                result_len,
            ),
        )
        c.commit()
    except Exception:
        pass  # telemetry must never crash the tool


# ---------------------------------------------------------------------------
# MIDDLEWARE INSTALLER
# ---------------------------------------------------------------------------

def install_telemetry_middleware(mcp) -> None:
    """
    Monkey-patch mcp.tool so every @mcp.tool() decorated function is
    transparently wrapped with before/after telemetry hooks.

    Call once, immediately after mcp = FastMCP("termpipe").
    """
    original_tool_decorator = mcp.tool

    def _patched_tool(*dec_args, **dec_kwargs):
        # mcp.tool() can be called as @mcp.tool or @mcp.tool(name=...) etc.
        # We handle both: if the first positional arg is callable it's the
        # function itself; otherwise it's decorator-with-args.
        original_decorator = original_tool_decorator(*dec_args, **dec_kwargs)

        if callable(original_decorator) and not isinstance(original_decorator, type):
            # @mcp.tool() with args → returns a decorator
            def _wrapper(fn: Callable) -> Callable:
                return _wrap_fn(mcp, fn, original_decorator)
            return _wrapper
        else:
            # @mcp.tool (no args) — original_decorator IS the wrapped fn
            # This branch is less common with FastMCP but handle it anyway
            return original_decorator

    mcp.tool = _patched_tool


def _category_for(fn: Callable) -> str:
    mod = (fn.__module__ or "").split(".")[-1]
    return _MOD_CAT.get(mod, mod.upper() or "OTHER")


def _wrap_fn(mcp, fn: Callable, original_decorator: Callable) -> Callable:
    """Wrap fn with telemetry then hand it to the real FastMCP decorator."""
    tool_name = fn.__name__
    category = _category_for(fn)

    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def _async_instrumented(*args, **kwargs):
            t0 = time.perf_counter()
            args_json = _sanitise_args(kwargs)
            try:
                result = await fn(*args, **kwargs)
                ms = (time.perf_counter() - t0) * 1000
                record(tool_name, category, args_json, ms, True, None,
                       len(str(result)) if result is not None else 0)
                return result
            except Exception as exc:
                ms = (time.perf_counter() - t0) * 1000
                record(tool_name, category, args_json, ms, False,
                       f"{type(exc).__name__}: {exc}"[:500], 0)
                raise

        return original_decorator(_async_instrumented)
    else:
        @functools.wraps(fn)
        def _sync_instrumented(*args, **kwargs):
            t0 = time.perf_counter()
            args_json = _sanitise_args(kwargs)
            try:
                result = fn(*args, **kwargs)
                ms = (time.perf_counter() - t0) * 1000
                record(tool_name, category, args_json, ms, True, None,
                       len(str(result)) if result is not None else 0)
                return result
            except Exception as exc:
                ms = (time.perf_counter() - t0) * 1000
                record(tool_name, category, args_json, ms, False,
                       f"{type(exc).__name__}: {exc}"[:500], 0)
                raise

        return original_decorator(_sync_instrumented)


# ---------------------------------------------------------------------------
# EDIT HISTORY — persistent undo store
# ---------------------------------------------------------------------------

_DAYS_BEFORE_COMPRESS = 45
_tool_call_counter = 0
_counter_lock = threading.Lock()


def _next_tool_call_no() -> int:
    global _tool_call_counter
    with _counter_lock:
        _tool_call_counter += 1
        return _tool_call_counter


def record_edit_to_db(
    tool_name: str,
    path: str,
    old_content: str,
    new_content: str,
    cwd: Optional[str] = None,
) -> None:
    """Persist one edit to edit_history. Never raises."""
    try:
        c = _conn()
        c.execute(
            """INSERT INTO edit_history
               (ts, session_id, tool_call_no, tool_name, path, cwd,
                old_content, new_content, compressed)
               VALUES (?,?,?,?,?,?,?,?,0)""",
            (
                datetime.now(timezone.utc).isoformat(),
                _get_session_id(),
                _next_tool_call_no(),
                tool_name,
                str(Path(path).expanduser().resolve()),
                cwd or os.getcwd(),
                old_content,
                new_content,
            ),
        )
        c.commit()
    except Exception:
        pass


def get_undo_edits(session_id: str, n: int = 1) -> list[dict]:
    """Return last N edit rows for session, newest first, with content decompressed."""
    try:
        c = _conn()
        c.row_factory = sqlite3.Row
        rows = c.execute(
            """SELECT id, path, old_content, new_content, compressed, ts, tool_name
               FROM edit_history
               WHERE session_id = ?
               ORDER BY id DESC
               LIMIT ?""",
            (session_id, n),
        ).fetchall()
        result = []
        for r in rows:
            old = r["old_content"]
            new = r["new_content"]
            if r["compressed"]:
                old = zlib.decompress(old).decode("utf-8") if old else ""
                new = zlib.decompress(new).decode("utf-8") if new else ""
            else:
                old = old or ""
                new = new or ""
            result.append({
                "id": r["id"],
                "path": r["path"],
                "old_content": old,
                "new_content": new,
                "ts": r["ts"],
                "tool_name": r["tool_name"],
            })
        return result
    except Exception:
        return []


def get_edit_history_db(session_id: str, limit: int = 50) -> list[dict]:
    """Return edit history metadata (no content blobs) for display."""
    try:
        c = _conn()
        c.row_factory = sqlite3.Row
        rows = c.execute(
            """SELECT id, ts, tool_name, path, cwd, tool_call_no
               FROM edit_history
               WHERE session_id = ?
               ORDER BY id DESC
               LIMIT ?""",
            (session_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def compress_old_edits() -> None:
    """Compress old_content/new_content for rows older than 45 days. Safe to run in background thread."""
    try:
        import os as _os
        c = _conn()
        c.row_factory = sqlite3.Row
        cutoff = datetime.now(timezone.utc).isoformat()[:10]  # YYYY-MM-DD
        rows = c.execute(
            """SELECT id, old_content, new_content
               FROM edit_history
               WHERE compressed = 0
               AND DATE(ts) < DATE(?, ? || ' days')""",
            (cutoff, f"-{_DAYS_BEFORE_COMPRESS}"),
        ).fetchall()
        for r in rows:
            old_c = zlib.compress(r["old_content"].encode("utf-8")) if r["old_content"] else b""
            new_c = zlib.compress(r["new_content"].encode("utf-8")) if r["new_content"] else b""
            c.execute(
                "UPDATE edit_history SET old_content=?, new_content=?, compressed=1 WHERE id=?",
                (old_c, new_c, r["id"]),
            )
        if rows:
            c.commit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# QUERY HELPERS  (used by the telemetry_report MCP tool in system.py)
# ---------------------------------------------------------------------------

def query(sql: str, params: tuple = ()) -> list[dict]:
    """Run an arbitrary SELECT and return rows as dicts."""
    c = _conn()
    c.row_factory = sqlite3.Row
    rows = c.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def top_tools(limit: int = 20) -> list[dict]:
    return query("""
        SELECT tool_name, category,
               COUNT(*)                              AS calls,
               ROUND(AVG(duration_ms), 1)            AS avg_ms,
               ROUND(MIN(duration_ms), 1)            AS min_ms,
               ROUND(MAX(duration_ms), 1)            AS max_ms,
               SUM(CASE WHEN success=0 THEN 1 END)   AS errors,
               ROUND(100.0 * SUM(CASE WHEN success=0 THEN 1 END) / COUNT(*), 1) AS error_pct
        FROM tool_calls
        GROUP BY tool_name
        ORDER BY calls DESC
        LIMIT ?
    """, (limit,))


def failure_report(limit: int = 30) -> list[dict]:
    return query("""
        SELECT tool_name, error_msg, COUNT(*) AS occurrences,
               MAX(ts) AS last_seen
        FROM tool_calls
        WHERE success = 0
        GROUP BY tool_name, error_msg
        ORDER BY occurrences DESC
        LIMIT ?
    """, (limit,))


def never_called() -> list[dict]:
    """Tools registered but never invoked (requires tool registry cross-ref)."""
    return query("""
        SELECT DISTINCT tool_name FROM tool_calls
    """)


def slowest_tools(limit: int = 10) -> list[dict]:
    return query("""
        SELECT tool_name, ROUND(AVG(duration_ms), 1) AS avg_ms,
               COUNT(*) AS calls
        FROM tool_calls
        GROUP BY tool_name
        HAVING calls >= 3
        ORDER BY avg_ms DESC
        LIMIT ?
    """, (limit,))


def daily_volume(days: int = 14) -> list[dict]:
    return query("""
        SELECT DATE(ts) AS day,
               COUNT(*) AS calls,
               SUM(CASE WHEN success=0 THEN 1 END) AS errors
        FROM tool_calls
        WHERE ts >= DATE('now', ? || ' days')
        GROUP BY day
        ORDER BY day DESC
    """, (f"-{days}",))


def category_breakdown() -> list[dict]:
    return query("""
        SELECT category,
               COUNT(*) AS calls,
               ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM tool_calls), 1) AS pct,
               ROUND(AVG(duration_ms), 1) AS avg_ms
        FROM tool_calls
        GROUP BY category
        ORDER BY calls DESC
    """)
