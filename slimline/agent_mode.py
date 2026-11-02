"""
slimline/agent_mode.py — kb-backed workspace agent-mode whitelist.

Standing autonomy modes per workspace directory, stored on the KernClip
bus (kb) so any agent session resolves the same answer:

  Topics (each holds one JSON doc: {"records": [{cwd, set_at, set_via}]}):
    agent.workspace.full      Allow Full Agent Mode
    agent.workspace.balanced  Allow Balanced Agent Mode
    agent.workspace.minimal   Allow Minimal Agent Mode
    agent.workspace.hitl      Full HITL Mode
    agent.workspace.denied    explicit "do not auto-continue / do not work"
    agent.workspace.pending   notification fired, awaiting a decision
    agent.workspace.decision  one JSON event per decision (list_tools waits on it)
    agent.workspace.audit     latest decision event (audit trail via kb tail)

Resolution (deterministic):
  - cwd is canonicalized (realpath) before matching.
  - Longest matching ancestor record wins (a subdirectory inherits its
    project's mode; a denied subdirectory carves out an exception).
  - At equal scope, denied beats any allow.
  - kb unreachable -> fail closed: HITL. An allow is never inferred.

list_tools probe is BLOCKING by design (Craig, 2026-09-30): for a brand-new
workspace it fires the rich kb notification, then waits up to WAIT_SECONDS
for the button click so the decision lands in that same list_tools output.
On timeout the call falls back to pending/HITL; the notification stays
clickable for its display lifetime and a click still sets the standing mode.

Button grammar (kb native): "<label>:cmd:<shell>". Each button runs
  /home/craig/.local/bin/agent-mode set <mode> <cwd> --via notify-button
which performs the topic writes (move semantics: a cwd lives in exactly one
mode topic), clears the pending record, and publishes the decision event.

Stdlib only — safe to run under the system python3 from a desktop
notification click, where ~/.local/bin may not be on PATH (kb is therefore
resolved by absolute path first).
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

KB_DEFAULT = "/home/craig/.local/bin/kb"
AGENT_MODE_BIN = "/home/craig/.local/bin/agent-mode"

TOPIC_BY_KEY = {
    "full": "agent.workspace.full",
    "balanced": "agent.workspace.balanced",
    "minimal": "agent.workspace.minimal",
    "hitl": "agent.workspace.hitl",
    "denied": "agent.workspace.denied",
    "pending": "agent.workspace.pending",
}
DECISION_TOPIC = "agent.workspace.decision"
AUDIT_TOPIC = "agent.workspace.audit"
INBOX_TOPIC = "agent.inbox"

MODE_KEYS = ("full", "balanced", "minimal", "hitl")
ALL_KEYS = MODE_KEYS + ("denied",)

BUTTON_LABELS = {
    "full": "Allow Full Agent Mode",
    "balanced": "Allow Balanced Agent Mode",
    "minimal": "Allow Minimal Agent Mode",
    "hitl": "Full HITL Mode",
}

WAIT_SECONDS = 15            # blocking decision window per notification fire
NOTIFY_TIMEOUT_SECONDS = 300  # notification display lifetime
PENDING_TTL_SECONDS = 300     # pending record suppresses re-firing this long

CEILINGS = {
    "full": [
        "Self-resolve any decision whose effects stay inside this workspace and are git-reversible; ambiguity count is uncapped.",
        "Writing work to disk is authorized. Local git commit is authorized and is the closing checkpoint of an autonomous run: record the pre-run HEAD first, commit only files the run touched, never sweep in pre-existing dirty work.",
        "Push is NOT authorized. Nothing leaves this machine under a standing mode; push, publish, external messages, money, sudo, and secrets access always escalate for fresh authorization.",
        "Verification failure: work through up to 3 distinct approaches, then escalate.",
    ],
    "balanced": [
        "Continue only work that already has a spec, handoff, or TODO.",
        "Self-resolve only decisions that are reversible AND verifiable AND do not change public API, schema, or dependencies.",
        "Escalate at the first ambiguity where two readings produce materially different behavior.",
        "Verification failure: try one alternative approach, then escalate.",
        "No commit or push without fresh authorization.",
    ],
    "minimal": [
        "Execute only the literal next step already named in the handoff or TODO.",
        "Zero discretionary decisions: any ambiguity, any new file, any dependency escalates.",
        "A verification failure stops the work and is reported.",
        "No commit or push without fresh authorization.",
    ],
    "hitl": [
        "Nothing auto-continues. State the intended actions and wait for the user.",
        "No commit or push without fresh authorization.",
    ],
    "denied": [
        "Do not auto-continue and do not work in this workspace. The user has explicitly denied this directory.",
    ],
}

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class KbUnavailable(Exception):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(ts: str):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text or "")


def canonicalize(cwd: str) -> str:
    return str(Path(cwd).expanduser().resolve())


def parse_records(raw: str):
    """Parse a topic payload into a list of {cwd, set_at, set_via} records.

    Tolerates: the canonical {"records": [...]} JSON doc, a bare JSON list,
    kb's "(empty)" marker, and legacy newline-separated cwd lists.
    """
    text = strip_ansi(raw or "").strip()
    if not text or text == "(empty)":
        return []
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            items = data.get("records", [])
        elif isinstance(data, list):
            items = data
        else:
            items = []
        records = []
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("cwd"), str):
                records.append({
                    "cwd": item["cwd"],
                    "set_at": str(item.get("set_at", "")),
                    "set_via": str(item.get("set_via", "")),
                })
        return records
    except (json.JSONDecodeError, ValueError):
        return [
            {"cwd": line.strip(), "set_at": "", "set_via": "legacy"}
            for line in text.splitlines() if line.strip()
        ]


def serialize_records(records) -> str:
    return json.dumps({"records": records})


def resolve_mode(cwd: str, state: dict):
    """Resolve a canonical cwd against {key: records}. Pure function.

    Returns (key, record) for the winning record, or None if unregistered.
    Longest ancestor match wins; denied beats allows at equal scope; ties
    among allows at equal scope go to the newest set_at.
    """
    candidates = []
    for key in ALL_KEYS:
        for rec in state.get(key, []):
            rc = rec["cwd"].rstrip("/") or "/"
            if cwd == rc or cwd.startswith(rc + "/"):
                candidates.append((len(rc), key, rec))
    if not candidates:
        return None
    best_len = max(c[0] for c in candidates)
    top = [c for c in candidates if c[0] == best_len]
    for _, key, rec in top:
        if key == "denied":
            return ("denied", rec)
    top.sort(key=lambda c: c[2].get("set_at", ""), reverse=True)
    return (top[0][1], top[0][2])


def is_workspace(cwd: str) -> bool:
    """A workspace is a directory in or under a git work tree (walking up
    to, and including, the user's home directory)."""
    p = Path(cwd)
    home = Path.home()
    for anc in [p, *p.parents]:
        if (anc / ".git").exists():
            return True
        if anc == home or anc == Path("/"):
            return False
    return False


class KbClient:
    """Thin kb CLI wrapper. All bus I/O for this module goes through here
    so tests can substitute a fake."""

    def __init__(self, kb_bin: str = None):
        self.kb_bin = kb_bin or self._resolve_kb_bin()

    @staticmethod
    def _resolve_kb_bin() -> str:
        env = os.environ.get("AGENT_MODE_KB_BIN")
        if env:
            return env
        if Path(KB_DEFAULT).exists():
            return KB_DEFAULT
        return shutil.which("kb") or KB_DEFAULT

    def _run(self, args, timeout=10):
        try:
            res = subprocess.run(
                [self.kb_bin, *args],
                capture_output=True, text=True, timeout=timeout,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            raise KbUnavailable(str(e))
        if res.returncode != 0:
            raise KbUnavailable(f"kb {' '.join(args[:2])} exited {res.returncode}: {res.stderr.strip()}")
        return strip_ansi(res.stdout).strip()

    def get(self, topic: str) -> str:
        return self._run(["get", topic])

    def pub(self, topic: str, data: str):
        self._run(["pub", topic, data])

    def wait(self, topic: str, timeout_ms: int) -> str:
        """Block until the next message on topic, or timeout. Returns the
        payload ('' on timeout — kb wait exits 0 either way)."""
        try:
            res = subprocess.run(
                [self.kb_bin, "wait", topic, "--timeout", str(int(timeout_ms))],
                capture_output=True, text=True,
                timeout=(timeout_ms / 1000.0) + 10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            raise KbUnavailable(str(e))
        return strip_ansi(res.stdout).strip()

    def notify_detached(self, argv):
        """Fire kb notify without blocking: kb notify itself waits for
        dismissal/timeout, which must not stall the probe."""
        try:
            subprocess.Popen(
                [self.kb_bin, *argv],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError as e:
            raise KbUnavailable(str(e))


def load_state(client: KbClient) -> dict:
    state = {}
    for key, topic in TOPIC_BY_KEY.items():
        state[key] = parse_records(client.get(topic))
    return state


def _save(client: KbClient, key: str, records):
    client.pub(TOPIC_BY_KEY[key], serialize_records(records))


def set_mode(client: KbClient, mode: str, cwd: str, via: str = "cli") -> dict:
    """Move cwd into exactly one mode topic (or denied/pending-free state),
    clear its pending record, and publish decision + audit + inbox events."""
    if mode not in TOPIC_BY_KEY or mode == "pending":
        raise ValueError(f"unknown mode: {mode}")
    cwd = canonicalize(cwd)
    if not Path(cwd).is_dir():
        raise ValueError(f"not a directory: {cwd}")
    state = load_state(client)
    ts = _now_iso()
    record = {"cwd": cwd, "set_at": ts, "set_via": via}
    for key in ALL_KEYS:
        before = state[key]
        after = [r for r in before if r["cwd"] != cwd]
        if key == mode:
            after = [*after, record]
        if after != before:
            _save(client, key, after)
    if state.get("pending"):
        remaining = [r for r in state["pending"] if r["cwd"] != cwd]
        if remaining != state["pending"]:
            _save(client, "pending", remaining)
    event = {"cwd": cwd, "mode": mode, "set_at": ts, "set_via": via}
    client.pub(DECISION_TOPIC, json.dumps(event))
    client.pub(AUDIT_TOPIC, json.dumps({"event": "agent_mode_set", **event}))
    client.pub(INBOX_TOPIC, f"agent-mode: {mode} set for {cwd} (via {via})")
    return event


def build_notify_argv(cwd: str):
    body = (
        f"{cwd}\n"
        "This workspace has no standing agent mode. The agent can continue "
        "working toward the goal in this directory, using its best judgment "
        "up to the chosen mode's ceiling.\n"
        "Full: autonomous — disk writes and a local git commit checkpoint "
        "(never push). Balanced: continue specified work; reversible, "
        "verifiable calls only. Minimal: only the literal next specified "
        "step. Full HITL: nothing auto-continues."
    )
    argv = [
        "notify", "New workspace — set agent mode",
        "--body", body,
        "--app-name", "Hank",
        "--thread", "agent-workspace-mode",
        "--timeout", str(NOTIFY_TIMEOUT_SECONDS),
        "--urgency", "n",
    ]
    for mode in MODE_KEYS:
        action = "cmd:" + shlex.join(
            [AGENT_MODE_BIN, "set", mode, cwd, "--via", "notify-button"]
        )
        argv += ["--button", f"{BUTTON_LABELS[mode]}:{action}"]
    return argv


def format_block(cwd: str, key: str, record: dict, note: str = "") -> str:
    machine = {
        "cwd": cwd,
        "mode": key,
        "source_topic": TOPIC_BY_KEY.get(key, ""),
        "matched_record": record.get("cwd", "") if record else "",
        "set_at": record.get("set_at", "") if record else "",
        "set_via": record.get("set_via", "") if record else "",
    }
    lines = [
        "Agent Workspace Mode:",
        f"AGENT_MODE {json.dumps(machine)}",
    ]
    if note:
        lines.append(f"- note: {note}")
    lines.append("- judgment ceiling for this mode:")
    for line in CEILINGS[key]:
        lines.append(f"  - {line}")
    return "\n".join(lines)


def _pending_note(cwd: str) -> str:
    return (
        "no standing mode is set for this workspace and no decision was "
        "received inside the blocking window; default to Full HITL for this "
        "call. The notification remains clickable — a click sets the "
        "standing mode for future calls."
    )


def probe(client: KbClient, cwd: str, wait_seconds: int = WAIT_SECONDS,
          allow_notify: bool = True) -> str:
    """Resolve the workspace mode for list_tools. Blocks up to wait_seconds
    for a button decision when the workspace is brand new. Never raises:
    every failure path fails closed to HITL."""
    cwd = canonicalize(cwd)
    try:
        state = load_state(client)
    except KbUnavailable as e:
        return format_block(
            cwd, "hitl", {},
            note=f"kb unreachable ({e}); mode unknown — fail closed to Full HITL. Never infer an allow.",
        )
    resolved = resolve_mode(cwd, state)
    if resolved:
        key, record = resolved
        return format_block(cwd, key, record)
    if not is_workspace(cwd):
        return format_block(
            cwd, "hitl", {},
            note="unregistered directory and not a git workspace; no mode prompt fired. Default Full HITL.",
        )

    # Brand-new workspace: pending record gates re-firing.
    now = datetime.now(timezone.utc)
    pending_rec = next((r for r in state.get("pending", []) if r["cwd"] == cwd), None)
    pending_age = None
    if pending_rec:
        ts = _parse_iso(pending_rec.get("set_at", ""))
        if ts is not None:
            pending_age = (now - ts).total_seconds()
    fresh_pending = pending_age is not None and pending_age < PENDING_TTL_SECONDS

    wait_budget = 0
    if not fresh_pending:
        try:
            records = [r for r in state.get("pending", []) if r["cwd"] != cwd]
            records.append({"cwd": cwd, "set_at": _now_iso(), "set_via": "list_tools"})
            _save(client, "pending", records)
            if allow_notify:
                client.notify_detached(build_notify_argv(cwd))
        except KbUnavailable as e:
            return format_block(
                cwd, "hitl", {},
                note=f"kb failed while registering the mode prompt ({e}); fail closed to Full HITL.",
            )
        wait_budget = wait_seconds
    elif pending_age < wait_seconds:
        # A concurrent call fired the notification moments ago; share the
        # remainder of its decision window instead of firing again.
        wait_budget = int(wait_seconds - pending_age)

    if wait_budget > 0:
        deadline = time.monotonic() + wait_budget
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                # Wait in short slices and re-read state each time. kb wait
                # only observes messages published after it starts, so a
                # click that lands just before a slice starts would
                # otherwise be missed until the whole window expired.
                client.wait(DECISION_TOPIC, int(min(0.5, remaining) * 1000))
                state = load_state(client)
            except KbUnavailable:
                break
            resolved = resolve_mode(cwd, state)
            if resolved:
                key, record = resolved
                return format_block(
                    cwd, key, record,
                    note="decision received during this list_tools call (blocking wait).",
                )
    return format_block(cwd, "hitl", {}, note=_pending_note(cwd))


# ---------------------------------------------------------------------------
# CLI — installed as /home/craig/.local/bin/agent-mode (thin wrapper).
#   agent-mode set <full|balanced|minimal|hitl|denied> <cwd> [--via X]
#   agent-mode resolve <cwd> [--no-wait]   (the list_tools probe)
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    via = "cli"
    if "--via" in rest:
        i = rest.index("--via")
        via = rest[i + 1] if i + 1 < len(rest) else "cli"
        rest = rest[:i] + rest[i + 2:]
    client = KbClient()
    try:
        if cmd == "set" and len(rest) == 2:
            event = set_mode(client, rest[0], rest[1], via=via)
            print(json.dumps(event))
            return 0
        if cmd == "resolve" and len(rest) >= 1:
            wait = 0 if "--no-wait" in rest else WAIT_SECONDS
            print(probe(client, rest[0], wait_seconds=wait))
            return 0
        print(f"usage error: {argv}", file=sys.stderr)
        return 2
    except KbUnavailable as e:
        print(f"agent-mode: kb unavailable: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"agent-mode: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
