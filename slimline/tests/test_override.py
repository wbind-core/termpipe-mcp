"""Tests for the chat-routed override path: guard._use_override plus
override_tools.file_override / resolve_verdict, against a stateful fake kb
binary (pub persists, get --json reads back).

Run: python3 -m pytest slimline/tests/test_override.py -q
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from slimline.tools import guard
from slimline.tools import override_tools

FAKE_KB = r'''
import json, os, sys

state = os.environ.get("FAKE_KB_STATE", "")
args = sys.argv[1:]

def state_path(topic):
    return os.path.join(state, topic.replace("/", "_"))

if not args:
    sys.exit(0)
if args[0] == "pub" and len(args) >= 3:
    with open(state_path(args[1]), "w") as f:
        f.write(args[2])
elif args[0] == "get" and len(args) >= 2 and "--json" in args:
    topic = args[1]
    p = state_path(topic)
    if os.path.exists(p):
        with open(p) as f:
            data = f.read()
        print(json.dumps({"ok": True, "topic": topic, "data": data}))
    else:
        print(json.dumps({"ok": False, "topic": topic,
                          "error": "no such topic"}))
elif args[0] == "wait":
    pass
sys.exit(0)
'''

CMD = "rm -rf /tmp/override-probe"


def _fake_kb(tmp_path, monkeypatch):
    kb = tmp_path / "fake-kb"
    kb.write_text("#!/usr/bin/env python3\n" + FAKE_KB)
    kb.chmod(0o755)
    state = tmp_path / "kb-state"
    state.mkdir()
    monkeypatch.setenv("FAKE_KB_STATE", str(state))
    return str(kb)


def _block(tmp_path, monkeypatch, cmd=CMD):
    """Run gate() to a timeout denial; return (kb, rid)."""
    kb = _fake_kb(tmp_path, monkeypatch)
    out = guard.gate(cmd, kb_bin=kb, wait_seconds=1)
    assert out is not None and "request id:" in out, out
    rid = out.split("request id:")[1].split(".")[0].strip()
    assert len(rid) == 12
    return kb, rid


def test_override_happy_path(tmp_path, monkeypatch):
    kb, rid = _block(tmp_path, monkeypatch)
    # Pending record was published by gate().
    rec = guard._Kb(kb).get_json(guard.PENDING_PREFIX + rid)
    assert rec is not None and rec["ok"]
    pending = json.loads(rec["data"])
    assert pending["command"] == CMD

    msg = override_tools.file_override(rid, "test reason", kb_bin=kb)
    assert "filed" in msg and rid in msg

    # No verdict yet -> re-invocation denies.
    out = guard.gate(CMD, kb_bin=kb, override_id=rid)
    assert out is not None and "no chat approval" in out

    # Record approval -> re-invocation is allowed.
    msg2 = override_tools.resolve_verdict(rid, "approve", kb_bin=kb)
    assert "recorded" in msg2
    assert guard.gate(CMD, kb_bin=kb, override_id=rid) is None

    # One-shot: a second use of the same id denies.
    out2 = guard.gate(CMD, kb_bin=kb, override_id=rid)
    assert out2 is not None and "NOT executed" in out2


def test_override_wrong_command_denied(tmp_path, monkeypatch):
    kb, rid = _block(tmp_path, monkeypatch)
    assert "filed" in override_tools.file_override(rid, "r", kb_bin=kb)
    assert "recorded" in override_tools.resolve_verdict(
        rid, "approve", kb_bin=kb)
    out = guard.gate("rm -rf /tmp/something-else", kb_bin=kb,
                     override_id=rid)
    assert out is not None and "does not match this exact command" in out


def test_override_unknown_id_denied(tmp_path, monkeypatch):
    kb = _fake_kb(tmp_path, monkeypatch)
    out = guard.gate(CMD, kb_bin=kb, override_id="deadbeef1234")
    assert out is not None and "unknown or expired" in out


def test_override_deny_verdict_stays_denied(tmp_path, monkeypatch):
    kb, rid = _block(tmp_path, monkeypatch)
    assert "recorded" in override_tools.resolve_verdict(
        rid, "deny", kb_bin=kb)
    out = guard.gate(CMD, kb_bin=kb, override_id=rid)
    assert out is not None and "NOT executed" in out


def test_override_expired(tmp_path, monkeypatch):
    kb = _fake_kb(tmp_path, monkeypatch)
    rid = "stale00rid00"
    guard._Kb(kb).pub(guard.PENDING_PREFIX + rid, json.dumps({
        "command": CMD, "reasons": ["test"],
        "ts": time.time() - guard.OVERRIDE_WINDOW - 60,
    }))
    out = guard.gate(CMD, kb_bin=kb, override_id=rid)
    assert out is not None and "expired" in out


def test_file_override_unknown_id(tmp_path, monkeypatch):
    kb = _fake_kb(tmp_path, monkeypatch)
    msg = override_tools.file_override("nope-not-real", "r", kb_bin=kb)
    assert "cannot file" in msg


def test_resolve_verdict_rejects_garbage(tmp_path, monkeypatch):
    kb, rid = _block(tmp_path, monkeypatch)
    msg = override_tools.resolve_verdict(rid, "maybe", kb_bin=kb)
    assert "must be exactly" in msg
    # Nothing was recorded: still no approval.
    out = guard.gate(CMD, kb_bin=kb, override_id=rid)
    assert out is not None and "no chat approval" in out


def test_benign_command_ignores_override_id(tmp_path, monkeypatch):
    kb = _fake_kb(tmp_path, monkeypatch)
    assert guard.gate("ls -la /tmp", kb_bin=kb,
                      override_id="whatever") is None
