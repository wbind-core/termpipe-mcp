#!/usr/bin/env python3
"""
telem_daemon.py — TermPipe Tool-Call Telemetry Daemon
======================================================
Runs as a background process. Never exposes anything to the model.

Responsibilities:
  1. Tail ~/.termpipe/telemetry.db for new tool_call rows (written by
     the telemetry middleware in server.py).
  2. Every ANALYSIS_INTERVAL new rows (or ANALYSIS_INTERVAL_SECS wall-clock
     seconds, whichever comes first), ship a summary to omniproxy for LLM
     analysis and append the result to ~/.termpipe/telem_analysis.md.
  3. Maintain ~/.termpipe/telem_daemon.log as a rolling plaintext log of
     everything it does (max ~2 MB, auto-rotated).

Usage:
    python3 -m termpipe_mcp.telem_daemon          # foreground / via systemd
    python3 ~/termpipe-mcp/termpipe_mcp/telem_daemon.py   # direct

Omniproxy endpoint is auto-selected from the running ports in OMNI_PORTS.
Falls back down the list until one responds.
"""

import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

HOME = Path.home()
DB_PATH        = HOME / ".termpipe" / "telemetry.db"
LOG_PATH       = HOME / ".termpipe" / "telem_daemon.log"
ANALYSIS_PATH  = HOME / ".termpipe" / "telem_analysis.md"
PID_PATH       = HOME / ".termpipe" / "telem_daemon.pid"

LOG_MAX_BYTES   = 2 * 1024 * 1024   # 2 MB before rotation
ANALYSIS_INTERVAL      = 50          # rows between LLM analyses
ANALYSIS_INTERVAL_SECS = 600         # 10 min wall-clock max between analyses
POLL_SECS       = 5                  # how often to check DB for new rows

OMNI_URL = "http://127.0.0.1:9916/v1/chat/completions"

ANALYSIS_SYSTEM = (
    "You are a tool-call telemetry analyst for a developer's personal AI assistant "
    "infrastructure (TermPipe MCP). You receive batches of tool invocation records "
    "and produce concise, actionable markdown reports. Focus on: which tools are "
    "called most and why, which fail and at what rate, which are suspiciously slow, "
    "which appear redundant or unused, and any patterns worth optimising. "
    "Be direct. No filler. Output markdown only."
)

ANALYSIS_PROMPT = """\
Analyse the following batch of {n} tool-call records from the TermPipe MCP server.

Batch window: {window_start} → {window_end}
Total calls in DB so far: {total}

## Call Summary (this batch)
{summary_table}

## Failure Detail
{failure_detail}

## Slow Calls (>500 ms)
{slow_calls}

Produce a markdown report with these sections:
1. **Key Findings** (3–5 bullet points, most important observations)
2. **Failure Analysis** (patterns in errors; which tools are fragile)
3. **Performance Hotspots** (slowest tools, outliers)
4. **Redundancy / Dead Weight** (tools that appear unnecessary or overlap)
5. **Recommendations** (concrete, prioritised — what to fix or remove)

Keep each section tight. Total report under 600 words.
"""

# ---------------------------------------------------------------------------
# Logging setup (file + stderr)
# ---------------------------------------------------------------------------

def _setup_logging():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stderr),
        ],
    )
    # File handler with manual rotation check
    _rotate_log_if_needed()
    fh = logging.FileHandler(str(LOG_PATH), encoding="utf-8")
    fh.setFormatter(logging.Formatter(fmt))
    logging.getLogger().addHandler(fh)


def _rotate_log_if_needed():
    if LOG_PATH.exists() and LOG_PATH.stat().st_size > LOG_MAX_BYTES:
        backup = LOG_PATH.with_suffix(".log.1")
        backup.unlink(missing_ok=True)
        LOG_PATH.rename(backup)


log = logging.getLogger("telem_daemon")

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def _ensure_schema(c: sqlite3.Connection):
    """Ensure DB + table exist (daemon may start before any tool calls)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c.executescript("""
        CREATE TABLE IF NOT EXISTS tool_calls (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            ts            TEXT    NOT NULL,
            session_id    TEXT,
            tool_name     TEXT    NOT NULL,
            category      TEXT,
            args_json     TEXT,
            duration_ms   REAL,
            success       INTEGER NOT NULL DEFAULT 1,
            error_msg     TEXT,
            result_len    INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_tool_name ON tool_calls (tool_name);
        CREATE INDEX IF NOT EXISTS idx_ts        ON tool_calls (ts);
        CREATE INDEX IF NOT EXISTS idx_success   ON tool_calls (success);
    """)
    c.commit()


def _fetch_new_rows(c: sqlite3.Connection, since_id: int) -> list[dict]:
    rows = c.execute(
        "SELECT * FROM tool_calls WHERE id > ? ORDER BY id ASC",
        (since_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def _total_rows(c: sqlite3.Connection) -> int:
    return c.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0]


# ---------------------------------------------------------------------------
# Build analysis payload from a batch of rows
# ---------------------------------------------------------------------------

def _build_summary_table(rows: list[dict]) -> str:
    from collections import defaultdict
    counts: dict = defaultdict(lambda: {"calls": 0, "errors": 0, "total_ms": 0.0, "max_ms": 0.0})
    for r in rows:
        t = r["tool_name"]
        counts[t]["calls"] += 1
        if not r["success"]:
            counts[t]["errors"] += 1
        ms = r["duration_ms"] or 0
        counts[t]["total_ms"] += ms
        if ms > counts[t]["max_ms"]:
            counts[t]["max_ms"] = ms

    lines = ["tool_name | calls | errors | avg_ms | max_ms",
             "--------- | ----- | ------ | ------ | ------"]
    for name, d in sorted(counts.items(), key=lambda x: -x[1]["calls"]):
        avg = d["total_ms"] / d["calls"] if d["calls"] else 0
        lines.append(f"{name} | {d['calls']} | {d['errors']} | {avg:.1f} | {d['max_ms']:.1f}")
    return "\n".join(lines)


def _build_failure_detail(rows: list[dict]) -> str:
    failures = [r for r in rows if not r["success"] and r.get("error_msg")]
    if not failures:
        return "None in this batch."
    from collections import Counter
    counts = Counter((r["tool_name"], r["error_msg"][:120]) for r in failures)
    lines = [f"- **{t}** × {n}: `{msg}`" for (t, msg), n in counts.most_common(15)]
    return "\n".join(lines)


def _build_slow_calls(rows: list[dict]) -> str:
    slow = [r for r in rows if (r["duration_ms"] or 0) > 500]
    if not slow:
        return "None above 500 ms."
    slow.sort(key=lambda r: -(r["duration_ms"] or 0))
    lines = []
    for r in slow[:20]:
        lines.append(f"- **{r['tool_name']}** {r['duration_ms']:.0f} ms — args: `{str(r.get('args_json',''))[:80]}`")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Omniproxy — pick first live port and call it
# ---------------------------------------------------------------------------

def _omni_chat(prompt: str, system: str) -> str:
    """Send a chat completion request to omniproxy local at 9916."""
    payload = json.dumps({
        "model": "",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        "max_tokens": 1200,
        "stream": False,
    }).encode()

    req = urllib.request.Request(
        OMNI_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode())
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.debug("omni_chat failed: %s", e)
        return "[omniproxy unavailable — is 'omni serve --local' running?]"


# ---------------------------------------------------------------------------
# Run one analysis cycle
# ---------------------------------------------------------------------------

def _run_analysis(rows: list[dict], total: int):
    if not rows:
        return

    ts_vals = [r["ts"] for r in rows if r.get("ts")]
    window_start = min(ts_vals) if ts_vals else "?"
    window_end   = max(ts_vals) if ts_vals else "?"

    prompt = ANALYSIS_PROMPT.format(
        n=len(rows),
        window_start=window_start,
        window_end=window_end,
        total=total,
        summary_table=_build_summary_table(rows),
        failure_detail=_build_failure_detail(rows),
        slow_calls=_build_slow_calls(rows),
    )

    log.info("Sending %d rows to omniproxy for analysis…", len(rows))
    t0 = time.perf_counter()
    report = _omni_chat(prompt, ANALYSIS_SYSTEM)
    elapsed = time.perf_counter() - t0
    log.info("Analysis received in %.1fs (%d chars)", elapsed, len(report))

    _append_analysis(report, len(rows), window_start, window_end)


def _append_analysis(report: str, n: int, ws: str, we: str):
    ANALYSIS_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = f"\n\n---\n## Telemetry Analysis — {now}  ({n} calls, {ws[:16]} → {we[:16]})\n\n"
    with open(ANALYSIS_PATH, "a", encoding="utf-8") as f:
        f.write(header + report + "\n")
    log.info("Analysis appended to %s", ANALYSIS_PATH)


# ---------------------------------------------------------------------------
# PID file
# ---------------------------------------------------------------------------

def _write_pid():
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()))


def _clear_pid():
    PID_PATH.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run():
    _setup_logging()
    _write_pid()
    log.info("telem_daemon started (pid %d)", os.getpid())
    log.info("DB: %s | Analysis: %s", DB_PATH, ANALYSIS_PATH)

    c = _conn()
    _ensure_schema(c)

    # Start from the current high-water mark so we don't re-analyse history
    last_id: int = c.execute("SELECT COALESCE(MAX(id), 0) FROM tool_calls").fetchone()[0]
    log.info("Starting from row id %d", last_id)

    batch: list[dict] = []
    last_analysis_time = time.time()

    try:
        while True:
            time.sleep(POLL_SECS)
            _rotate_log_if_needed()

            try:
                new_rows = _fetch_new_rows(c, last_id)
            except sqlite3.OperationalError:
                # DB may be locked briefly by the MCP server; retry next cycle
                log.debug("DB locked, retrying…")
                continue

            if new_rows:
                last_id = new_rows[-1]["id"]
                batch.extend(new_rows)
                log.info("+%d rows (batch=%d, last_id=%d)", len(new_rows), len(batch), last_id)

            age = time.time() - last_analysis_time
            should_analyse = (
                len(batch) >= ANALYSIS_INTERVAL
                or (batch and age >= ANALYSIS_INTERVAL_SECS)
            )

            if should_analyse:
                total = _total_rows(c)
                _run_analysis(batch, total)
                batch = []
                last_analysis_time = time.time()

    except KeyboardInterrupt:
        log.info("telem_daemon stopped by user")
    finally:
        _clear_pid()
        c.close()


if __name__ == "__main__":
    run()
