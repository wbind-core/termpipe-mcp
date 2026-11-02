"""Tests for slimline/agent_mode.py — pure resolver logic plus an end-to-end
probe/set cycle against a fake kb binary (JSON-file backed).

Run: python3 -m pytest slimline/tests/test_agent_mode.py -q
(or plain: python3 slimline/tests/test_agent_mode.py)
"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from slimline import agent_mode as am

FAKE_KB = r'''
import json, os, sys, time

STORE = os.environ["FAKE_KB_STORE"]
NOTIFY_LOG = os.environ["FAKE_KB_NOTIFY_LOG"]

def load():
    try:
        return json.load(open(STORE))
    except Exception:
        return {}

def save(data):
    json.dump(data, open(STORE, "w"))

args = sys.argv[1:]
data = load()
if args[0] == "get":
    print(data.get(args[1], {}).get("value", "(empty)"))
elif args[0] == "pub":
    topic, value = args[1], args[2]
    seq = data.get(topic, {}).get("seq", 0) + 1
    data[topic] = {"value": value, "seq": seq}
    save(data)
    print(f"ok {topic} seq={seq}")
elif args[0] == "wait":
    topic = args[1]
    timeout_ms = int(args[args.index("--timeout") + 1])
    start_seq = data.get(topic, {}).get("seq", 0)
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        cur = load()
        if cur.get(topic, {}).get("seq", 0) != start_seq:
            print(cur[topic]["value"])
            break
        time.sleep(0.05)
elif args[0] == "notify":
    with open(NOTIFY_LOG, "a") as f:
        f.write(json.dumps(args[1:]) + "\n")
else:
    sys.exit(3)
'''


def rec(cwd, ts="2026-09-30T00:00:00+00:00", via="test"):
    return {"cwd": cwd, "set_at": ts, "set_via": via}


# ---------------- pure logic ----------------

def test_parse_records_variants():
    assert am.parse_records("") == []
    assert am.parse_records("(empty)") == []
    doc = json.dumps({"records": [rec("/a/b")]})
    assert am.parse_records(doc)[0]["cwd"] == "/a/b"
    assert am.parse_records(json.dumps([rec("/x")]))[0]["cwd"] == "/x"
    legacy = am.parse_records("/one\n/two\n")
    assert [r["cwd"] for r in legacy] == ["/one", "/two"]
    assert am.parse_records("\x1b[2m(empty)\x1b[0m") == []


def test_resolve_exact_and_inherit():
    state = {"full": [rec("/proj")]}
    assert am.resolve_mode("/proj", state)[0] == "full"
    assert am.resolve_mode("/proj/sub/dir", state)[0] == "full"
    assert am.resolve_mode("/project-other", state) is None
    assert am.resolve_mode("/other", state) is None


def test_resolve_longest_prefix_and_denied_carveout():
    state = {
        "full": [rec("/proj")],
        "denied": [rec("/proj/secret")],
        "balanced": [rec("/proj/sub", ts="2026-09-30T01:00:00+00:00")],
    }
    assert am.resolve_mode("/proj/sub", state)[0] == "balanced"
    assert am.resolve_mode("/proj/secret/x", state)[0] == "denied"
    assert am.resolve_mode("/proj/elsewhere", state)[0] == "full"


def test_resolve_denied_wins_equal_scope_and_newest_allow_wins():
    state = {"full": [rec("/p")], "denied": [rec("/p")]}
    assert am.resolve_mode("/p", state)[0] == "denied"
    state2 = {
        "full": [rec("/p", ts="2026-09-30T00:00:00+00:00")],
        "minimal": [rec("/p", ts="2026-09-30T02:00:00+00:00")],
    }
    assert am.resolve_mode("/p", state2)[0] == "minimal"


# ---------------- fake-kb integration ----------------

def make_env(tmp):
    kb = tmp / "fake-kb"
    kb.write_text("#!/usr/bin/env python3\n" + FAKE_KB)
    kb.chmod(0o755)
    store = tmp / "store.json"
    notify_log = tmp / "notify.log"
    env = dict(os.environ)
    env["FAKE_KB_STORE"] = str(store)
    env["FAKE_KB_NOTIFY_LOG"] = str(notify_log)
    env["AGENT_MODE_KB_BIN"] = str(kb)
    return env, store, notify_log


def make_workspace(tmp):
    ws = tmp / "proj"
    (ws / ".git").mkdir(parents=True)
    return ws


def client_for(env):
    return am.KbClient(kb_bin=env["AGENT_MODE_KB_BIN"])


def with_env(env):
    """am.KbClient + subprocess children must see the fake-kb env."""
    old = dict(os.environ)
    os.environ.update(env)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old)


def test_set_mode_move_semantics_and_events(tmp_path):
    env, store, _ = make_env(tmp_path)
    ws = make_workspace(tmp_path)
    for _ in with_env(env):
        client = client_for(env)
        am.set_mode(client, "full", str(ws), via="test")
        state = am.load_state(client)
        assert [r["cwd"] for r in state["full"]] == [str(ws)]
        am.set_mode(client, "minimal", str(ws), via="test")
        state = am.load_state(client)
        assert state["full"] == []
        assert [r["cwd"] for r in state["minimal"]] == [str(ws)]
        decision = json.loads(client.get(am.DECISION_TOPIC))
        assert decision["mode"] == "minimal" and decision["cwd"] == str(ws)
        assert "agent-mode: minimal" in client.get(am.INBOX_TOPIC)


def test_probe_registered_workspace_no_notify(tmp_path):
    env, store, notify_log = make_env(tmp_path)
    ws = make_workspace(tmp_path)
    for _ in with_env(env):
        client = client_for(env)
        am.set_mode(client, "balanced", str(ws), via="test")
        block = am.probe(client, str(ws), wait_seconds=5)
        assert '"mode": "balanced"' in block
        assert not notify_log.exists()


def test_probe_brand_new_blocks_and_catches_click(tmp_path):
    env, store, notify_log = make_env(tmp_path)
    ws = make_workspace(tmp_path)
    for _ in with_env(env):
        client = client_for(env)

        def click():
            time.sleep(1.0)
            am.set_mode(client_for(env), "full", str(ws), via="notify-button")

        t = threading.Thread(target=click)
        t.start()
        start = time.monotonic()
        block = am.probe(client, str(ws), wait_seconds=10)
        elapsed = time.monotonic() - start
        t.join()
        assert '"mode": "full"' in block
        assert "decision received during this list_tools call" in block
        assert elapsed < 8
        assert notify_log.exists()
        argv = json.loads(notify_log.read_text().splitlines()[0])
        buttons = [argv[i + 1] for i, a in enumerate(argv) if a == "--button"]
        assert len(buttons) == 4
        assert any(b.startswith("Allow Full Agent Mode:cmd:") and " set full " in b for b in buttons)


def test_probe_brand_new_timeout_falls_back_hitl(tmp_path):
    env, store, notify_log = make_env(tmp_path)
    ws = make_workspace(tmp_path)
    for _ in with_env(env):
        client = client_for(env)
        start = time.monotonic()
        block = am.probe(client, str(ws), wait_seconds=2)
        elapsed = time.monotonic() - start
        assert '"mode": "hitl"' in block
        assert "no decision was received" in block
        assert 1.5 < elapsed < 6
        # Second immediate probe: fresh pending suppresses re-fire and wait.
        block2 = am.probe(client, str(ws), wait_seconds=2)
        assert '"mode": "hitl"' in block2
        assert len(notify_log.read_text().splitlines()) == 1


def test_probe_non_workspace_no_prompt(tmp_path):
    env, store, notify_log = make_env(tmp_path)
    plain = tmp_path / "plain"
    plain.mkdir()
    for _ in with_env(env):
        client = client_for(env)
        block = am.probe(client, str(plain), wait_seconds=2)
        assert '"mode": "hitl"' in block
        assert "not a git workspace" in block
        assert not notify_log.exists()


def test_probe_kb_unavailable_fails_closed(tmp_path):
    client = am.KbClient(kb_bin="/nonexistent/kb")
    block = am.probe(client, "/tmp", wait_seconds=1)
    assert '"mode": "hitl"' in block
    assert "fail closed" in block


if __name__ == "__main__":
    import tempfile

    failures = 0
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            try:
                if fn.__code__.co_argcount:
                    with tempfile.TemporaryDirectory() as td:
                        fn(Path(td))
                else:
                    fn()
                print(f"PASS {name}")
            except Exception as e:
                failures += 1
                print(f"FAIL {name}: {e!r}")
    sys.exit(1 if failures else 0)
