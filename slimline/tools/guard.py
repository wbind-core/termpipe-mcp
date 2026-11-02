"""
slimline/tools/guard.py — dangerous-command approval gate for termf_exec.

Every command the adapter is asked to run passes screen() first. Benign
commands run immediately. A command matching the dangerous set blocks on
a kb rich-notification approval — the same wire kb itself uses for its
own approval gating (kernclip/bus pw_topics.go):

  - notification fired via `kb notify` with two buttons:
        "Approve Once:topic:termf.guard.<id>.approve_once"
        "Reject Once:topic:termf.guard.<id>.reject_once"
    A topic: button click publishes the payload "button_clicked" to that
    topic (see kernclip/bus cmd/kb/kb-notify.py, make_button_callback).
  - the gate listens on both topics with `kb wait`, started BEFORE the
    notification fires so no click can be missed, for a 120s window —
    the same decision window kb's secret-approval flow uses.
  - approve -> the command runs exactly once. Reject, dismissal, timeout,
    or kb unreachable -> the command NEVER runs (fail closed).

Every request and decision is published as JSON to termf.guard.audit.

Craig can also decide from any shell (the id is in the notification body):
  kb pub termf.guard.<id>.approve_once button_clicked
  kb pub termf.guard.<id>.reject_once  button_clicked

Chat-routed override (for when Craig is away from his desk): every blocked
command's id, exact command string, reasons, and timestamp are published to
termf.guard.pending.<id>. The agent files a request_override with the reason,
asks Craig in chat, and on his explicit "approve <id>" reply publishes the
verdict to termf.guard.<id>.override, then re-invokes the command with
override_id=<id>. The override is one-shot, bound to the exact command
string, expires after OVERRIDE_WINDOW seconds, and is audit-logged like every
other decision. See slimline/tools/override_tools.py for the agent protocol.
The chat transcript is the authorization record: resolve_override must only
be called after an explicit approve/deny message from Craig himself.

Scope: this gates commands arriving via the adapter (termf_exec) only.

Craig's own terminal use of `kb exec` is not the adapter and is unaffected.

Stdlib only.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

KB_DEFAULT = "/home/craig/.local/bin/kb"
WAIT_SECONDS = 120
AUDIT_TOPIC = "termf.guard.audit"
CLICK_PAYLOAD = "button_clicked"

# Chat-routed override: a filed override id stays usable this long.
OVERRIDE_WINDOW = 900
PENDING_PREFIX = "termf.guard.pending."
OVERRIDE_REQUEST_TOPIC = "termf.guard.override.request"


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# Command-position dangerous binaries (basename match).
_DESTRUCTIVE = {
    "rm", "rmdir", "unlink", "shred", "wipe", "srm", "truncate",
    "dd", "mke2fs", "fdisk", "parted", "sgdisk", "blkdiscard",
}
_KILL = {"kill", "pkill", "killall"}
_POWER = {"shutdown", "reboot", "poweroff", "halt"}
_PRIV = {"sudo", "doas", "su"}
_MISC = {"mount", "umount", "iptables", "nft"}
_ALWAYS = _DESTRUCTIVE | _KILL | _POWER | _PRIV | _MISC

# Dangerous even in argument position (xargs rm, find -exec rm, env rm).
_ANYWHERE = {"rm", "shred", "wipe", "srm", "truncate", "dd"}

# Tokens skipped while walking to a segment's effective command word.
_SKIP_WORDS = {
    "command", "builtin", "exec", "nohup", "nice", "time", "stdbuf",
    "then", "do", "else", "elif", "if", "while", "until", "!", "{", "}",
}
_OPERATORS = {";", "&", "|", "&&", "||", "(", ")", "$(", "`",
              "<", ">", ">>", ";;"}

_SYSTEMCTL_BENIGN = {
    "status", "show", "is-active", "is-enabled", "is-system-running",
    "is-failed", "list-units", "list-timers", "list-sockets",
    "list-jobs", "cat", "help", "--help", "--version", "get-default",
    "show-environment",
}


def _base(tok: str) -> str:
    return tok.rsplit("/", 1)[-1]


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _raw_reasons(command: str):
    """Pattern scans over the raw command string."""
    reasons = []
    if re.search(r"(?<!\S)-delete(?!\S)", command):
        reasons.append("find -delete")
    if "--delete" in command:
        reasons.append("--delete (bulk delete)")
    if "super+Delete" in command:
        reasons.append("wput super+Delete (permanently banned)")
    # Truncating redirection `>` to a real file outside /tmp and /dev/null.
    # Quoted spans are stripped first so `echo "a > b"` does not trip it;
    # stderr redirects (2>) and >& are excluded by the lookbehind/ahead.
    stripped = re.sub(r"'[^']*'|\"[^\"]*\"", "''", command)
    for m in re.finditer(r"(?<![0-9>&])>(?![>&])\s*([^\s;|&]+)", stripped):
        tgt = m.group(1)
        if tgt == "/dev/null" or tgt == "/tmp" or tgt.startswith("/tmp/"):
            continue
        reasons.append(f"overwrite redirection to {tgt}")
        break
    return reasons


def _segments(tokens):
    segs, cur = [], []
    for tok in tokens:
        if tok in _OPERATORS:
            if cur:
                segs.append(cur)
                cur = []
        else:
            cur.append(tok)
    if cur:
        segs.append(cur)
    return segs


def _first_verb(args, value_flags=()):
    """First positional (non-flag) token, skipping flags and the values
    of flags named in value_flags. Returns (verb, rest)."""
    i = 0
    while i < len(args):
        t = args[i]
        if t in value_flags:
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        return t, args[i + 1:]
    return None, []


def _segment_reasons(seg, depth):
    reasons = []
    i = 0
    priv = False
    while i < len(seg):
        tok = seg[i]
        if _ASSIGN_RE.match(tok):
            i += 1
            continue
        base = _base(tok)
        if base in ("sudo", "doas"):
            priv = True
            i += 1
            continue
        if base in _SKIP_WORDS or base == "env":
            i += 1
            continue
        if base == "timeout":
            i += 1
            while i < len(seg) and seg[i].startswith("-"):
                i += 1
            if i < len(seg):
                i += 1  # duration token
            continue
        if base == "xargs":
            i += 1
            while i < len(seg) and seg[i].startswith("-"):
                i += 1
            continue
        break
    if priv:
        reasons.append("privilege escalation (sudo/doas)")
    if i >= len(seg):
        return reasons

    cmd = _base(seg[i])
    args = seg[i + 1:]

    if cmd in _ALWAYS or cmd.startswith("mkfs"):
        reasons.append(f"dangerous command: {cmd}")
    elif cmd == "cryptsetup" and ("luksFormat" in args or "erase" in args):
        reasons.append("dangerous command: cryptsetup (format/erase)")
    elif cmd == "systemctl":
        verb, _ = _first_verb(args)
        if verb is not None and verb not in _SYSTEMCTL_BENIGN:
            reasons.append(f"systemctl mutation: {verb}")
    elif cmd == "git":
        verb, rest = _first_verb(args, value_flags=("-C", "-c"))
        if verb == "clean":
            reasons.append("git clean (deletes untracked files)")
        elif verb == "reset" and "--hard" in rest:
            reasons.append("git reset --hard (discards work)")
        elif verb == "checkout" and ("--" in rest or "." in rest):
            reasons.append("git checkout (discards work)")
        elif verb == "restore":
            reasons.append("git restore (discards work)")
        elif verb == "stash" and rest and rest[0] in ("drop", "clear"):
            reasons.append(f"git stash {rest[0]}")
        elif verb == "branch" and "-D" in rest:
            reasons.append("git branch -D (force delete)")
        elif verb == "push":
            reasons.append("git push (leaves this machine)")
    elif cmd in ("chmod", "chown"):
        home = str(Path.home())
        for t in args:
            if t.startswith("-") and "R" in t[1:]:
                reasons.append(f"{cmd} -R (recursive permission change)")
                break
            if t.startswith("/") and not t.startswith(home) \
                    and not t.startswith("/tmp/"):
                reasons.append(f"{cmd} on path outside home: {t}")
                break
    elif cmd == "crontab":
        if "-r" in args:
            reasons.append("crontab -r (deletes all cron jobs)")
        elif any(not t.startswith("-") for t in args):
            reasons.append("crontab replace (overwrites all cron jobs)")
    elif cmd in ("apt", "apt-get"):
        verb, _ = _first_verb(args)
        if verb in ("remove", "purge", "autoremove"):
            reasons.append(f"{cmd} {verb} (package removal)")
    elif cmd == "dpkg":
        if any(t in ("--remove", "--purge", "-r", "-P") for t in args):
            reasons.append("dpkg remove/purge (package removal)")
    elif cmd in ("dnf", "yum"):
        verb, _ = _first_verb(args)
        if verb in ("remove", "erase"):
            reasons.append(f"{cmd} {verb} (package removal)")
    elif cmd == "pacman":
        if any(t.startswith("-R") for t in args):
            reasons.append("pacman -R (package removal)")
    elif cmd in ("docker", "podman"):
        if any(t in ("rm", "rmi", "prune") for t in args):
            reasons.append(f"{cmd} removal/prune")
    elif cmd == "ip":
        if any(t in ("set", "add", "del", "delete", "flush", "replace")
               for t in args):
            reasons.append("ip mutation (link/route/addr change)")
    elif cmd in ("bash", "sh", "zsh", "dash", "ksh", "fish"):
        if "-c" in args:
            j = args.index("-c")
            if j + 1 < len(args):
                if depth >= 3:
                    reasons.append("nested shell beyond screening depth")
                else:
                    reasons += [f"nested: {r}"
                                for r in screen(args[j + 1], depth + 1)]
    elif cmd == "eval":
        if depth >= 3:
            reasons.append("eval beyond screening depth")
        elif args:
            reasons += [f"nested: {r}"
                        for r in screen(" ".join(args), depth + 1)]
    elif cmd == "kb" and len(args) > 1 and args[0] == "exec":
        if depth >= 3:
            reasons.append("nested kb exec beyond screening depth")
        else:
            reasons += [f"nested: {r}" for r in screen(args[1], depth + 1)]
    return reasons


def screen(command: str, _depth: int = 0):
    """Return a list of danger reasons for `command` ([] = benign)."""
    reasons = _raw_reasons(command)
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return reasons + ["unparseable command (fail closed)"]
    for seg in _segments(tokens):
        reasons += _segment_reasons(seg, _depth)
    for tok in tokens:
        b = _base(tok)
        if b in _ANYWHERE:
            reasons.append(f"dangerous binary referenced: {b}")
            break
    # Dedupe, preserving order.
    seen = set()
    out = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


class _Kb:
    """Minimal kb CLI client, mirroring slimline/agent_mode.py's KbClient."""

    def __init__(self, kb_bin=None):
        self.kb_bin = kb_bin or self._resolve()

    @staticmethod
    def _resolve():
        env = os.environ.get("TERMF_GUARD_KB_BIN")
        if env:
            return env
        if Path(KB_DEFAULT).exists():
            return KB_DEFAULT
        return shutil.which("kb") or KB_DEFAULT

    def pub(self, topic, data):
        try:
            subprocess.run([self.kb_bin, "pub", topic, data],
                           capture_output=True, text=True, timeout=10)
        except Exception:
            pass  # audit is best-effort; the waiters decide the outcome

    def get_json(self, topic):
        """Return the parsed `kb get <topic> --json` dict, or None when the
        topic is missing, kb is unreachable, or the output is unparsable."""
        try:
            res = subprocess.run(
                [self.kb_bin, "get", topic, "--json"],
                capture_output=True, text=True, timeout=10)
        except Exception:
            return None
        try:
            payload = json.loads(res.stdout)
        except Exception:
            return None
        if not isinstance(payload, dict) or not payload.get("ok") \
                or "data" not in payload:
            return None
        return payload


    def notify_detached(self, argv):
        subprocess.Popen([self.kb_bin, *argv],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         start_new_session=True)

    def wait_proc(self, topic, timeout_ms):
        return subprocess.Popen(
            [self.kb_bin, "wait", topic, "--timeout", str(int(timeout_ms))],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)


def _audit(client, event, rid, command, reasons, decision=None):
    payload = {
        "event": event,
        "id": rid,
        "command": command,
        "reasons": reasons,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if decision is not None:
        payload["decision"] = decision
    client.pub(AUDIT_TOPIC, json.dumps(payload))


def _deny(rid, command, reasons, why):
    return (
        f"[Guard: command NOT executed — {why}. "
        f"Flagged as dangerous ({', '.join(reasons)}). "
        f"Command: {command} | request id: {rid}. "
        f"Do not retry or work around this; surface it to Craig. "
        f"If he is away from his desk, file request_override with this id "
        f"and a reason, then ask him in chat.]"
    )


def _use_override(command: str, override_id: str, client: _Kb):
    """Chat-routed override path. The agent re-invokes the blocked command
    with override_id=<rid> after Craig explicitly approved it in chat; the
    approval itself was recorded on the override topic by resolve_override.
    Every failure mode denies (fail closed) — no notification is fired."""
    rid = override_id
    rec = client.get_json(PENDING_PREFIX + rid)
    if rec is None:
        _audit(client, "override_rejected", rid, command, [],
               "unknown or expired override id")
        return _deny(rid, command, [], "unknown or expired override id")
    try:
        pending = json.loads(rec.get("data") or "")
    except Exception:
        pending = None
    if not isinstance(pending, dict):
        _audit(client, "override_rejected", rid, command, [],
               "corrupt override record")
        return _deny(rid, command, [], "corrupt override record — fail closed")
    if time.time() - float(pending.get("ts", 0)) > OVERRIDE_WINDOW:
        _audit(client, "override_rejected", rid, command, [],
               "override id expired")
        return _deny(rid, command, [],
                     f"override id expired (> {OVERRIDE_WINDOW}s old)")
    if pending.get("command") != command:
        _audit(client, "override_rejected", rid, command, [],
               "override id bound to a different command")
        return _deny(rid, command, [],
                     "override id does not match this exact command")
    verdict_rec = client.get_json(override_topic(rid))
    verdict = (verdict_rec or {}).get("data", "")
    if verdict != "approve":
        _audit(client, "override_rejected", rid, command, [],
               f"no chat approval recorded (verdict={verdict!r})")
        return _deny(rid, command, [],
                     "no chat approval recorded for this override id — "
                     f"ask Craig to reply approve {rid} first")
    # One-shot: consume before running so a second re-invocation with the
    # same id cannot double-spend the approval.
    client.pub(override_topic(rid), "consumed")
    _audit(client, "guard_decision", rid, command,
           pending.get("reasons", []), "approved via chat override")
    return None



def override_topic(rid: str) -> str:
    return f"termf.guard.{rid}.override"


def gate(command: str, kb_bin=None, wait_seconds: int = WAIT_SECONDS,
         override_id: str = None):
    """Screen `command`. Returns None if it may run (benign, Craig approved
    it via the kb notification, or a valid chat-routed override was supplied
    via override_id), otherwise a denial string. Fail closed on every error
    path."""
    reasons = screen(command)
    if not reasons:
        return None

    client = _Kb(kb_bin)
    if override_id is not None:
        return _use_override(command, override_id, client)

    rid = uuid.uuid4().hex[:12]
    approve_topic = f"termf.guard.{rid}.approve_once"
    reject_topic = f"termf.guard.{rid}.reject_once"
    _audit(client, "guard_request", rid, command, reasons)
    # Pending record: lets a later re-invocation with override_id=<rid> prove
    # the exact command Craig approved in chat. Best-effort like the audit
    # publish; a missing record fails closed at override time.
    try:
        client.pub(PENDING_PREFIX + rid, json.dumps({
            "command": command,
            "reasons": reasons,
            "ts": time.time(),
        }))
    except Exception:
        pass


    try:
        procs = {
            "approve": client.wait_proc(approve_topic,
                                        wait_seconds * 1000 + 5000),
            "reject": client.wait_proc(reject_topic,
                                       wait_seconds * 1000 + 5000),
        }
    except Exception as e:
        _audit(client, "guard_decision", rid, command, reasons,
               f"denied (kb wait failed to start: {e})")
        return _deny(rid, command, reasons, f"kb unavailable ({e})")

    body_cmd = command if len(command) <= 1000 else \
        command[:1000] + " …[truncated — full text in termf.guard.audit]"
    body = (
        f"{body_cmd}\n\n"
        f"Flagged: {', '.join(reasons)}\n"
        f"Request id: {rid}\n"
        f"Or decide from a shell:\n"
        f"kb pub {approve_topic} button_clicked\n"
        f"Away from your desk? Reply approve {rid} / deny {rid} in chat."
        f"No decision in {wait_seconds}s = denied."
    )
    argv = [
        "notify", "Dangerous command — approval required",
        "--body", body,
        "--urgency", "c",
        "--app-name", "TermPipe Guard",
        "--thread", "termf-guard",
        "--timeout", str(wait_seconds),
        "--button", f"Approve Once:topic:{approve_topic}",
        "--button", f"Reject Once:topic:{reject_topic}",
    ]
    try:
        client.notify_detached(argv)
    except Exception as e:
        for p in procs.values():
            try:
                p.terminate()
            except Exception:
                pass
        _audit(client, "guard_decision", rid, command, reasons,
               f"denied (kb notify failed: {e})")
        return _deny(rid, command, reasons, f"kb notify failed ({e})")

    outputs = {}
    deadline = time.monotonic() + wait_seconds + 10
    outcome = None
    while time.monotonic() < deadline:
        alive = False
        for key, proc in procs.items():
            if key in outputs:
                continue
            rc = proc.poll()
            if rc is None:
                alive = True
                continue
            try:
                out, _ = proc.communicate(timeout=2)
            except Exception:
                out = ""
            outputs[key] = (rc, _strip_ansi(out or "").strip())
        if outputs.get("approve", (None, ""))[1] == CLICK_PAYLOAD:
            outcome = "approved"
            break
        if outputs.get("reject", (None, ""))[1] == CLICK_PAYLOAD:
            outcome = "rejected"
            break
        if not alive:
            break
        time.sleep(0.2)
    for proc in procs.values():
        if proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    if outcome == "approved":
        _audit(client, "guard_decision", rid, command, reasons, "approved")
        return None
    if outcome == "rejected":
        _audit(client, "guard_decision", rid, command, reasons, "rejected")
        return _deny(rid, command, reasons, "rejected by Craig")
    if outputs and all(rc not in (0, None) for rc, _ in outputs.values()):
        _audit(client, "guard_decision", rid, command, reasons,
               "denied (kb wait failed)")
        return _deny(rid, command, reasons,
                     "kb wait failed (kb unreachable) — fail closed")
    _audit(client, "guard_decision", rid, command, reasons,
           "denied (timeout)")
    return _deny(rid, command, reasons,
                 f"no decision within {wait_seconds}s (timeout = deny)")
