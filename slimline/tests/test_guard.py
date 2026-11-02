"""Tests for slimline/tools/guard.py — pure screen() cases plus gate()
approve/reject/timeout/kb-down against a fake kb binary.

Run: python3 -m pytest slimline/tests/test_guard.py -q
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from slimline.tools import guard

BENIGN = [
    "ls -la /home/craig",
    "echo hello",
    "git status",
    "git log --oneline -5",
    "git diff HEAD",
    "git checkout main",
    "git branch -d old-feature",
    "cat file.txt",
    "grep -rn pattern src/",
    "echo hi > /tmp/scratch.txt",
    "echo hi 2>/dev/null",
    "make build 2>&1 | tee build.log",
    "systemctl status kb",
    "systemctl is-active kb",
    "kb get sys.metrics",
    "cp a.txt b.txt",
    "mv a.txt b.txt",
    "python3 -m pytest -q",
    'echo "a > b"',
    "crontab -l",
    "apt list --installed",
    "docker ps",
    "chmod 755 script.sh",
    "find . -name '*.py'",
    "ls /home/craig/termpipe-mcp",
]

DANGEROUS = [
    "rm file.txt",
    "rm -rf /home/craig/src",
    "/usr/bin/rm -rf x",
    "sudo rm -rf /",
    "sudo ls",
    "ls && rm x",
    "ls; rm -rf build",
    "cat list.txt | xargs rm",
    "find . -name '*.tmp' -delete",
    "find . -exec rm {} +",
    "rsync -a --delete src/ dst/",
    "dd if=/dev/zero of=/dev/sda",
    "echo x | dd of=/tmp/img",
    "shred -u secret.txt",
    "truncate -s 0 data.db",
    "mkfs.ext4 /dev/sdb1",
    "kill 1234",
    "pkill -f python",
    "systemctl stop kb",
    "systemctl restart kb",
    "systemctl --user disable kb",
    "git clean -fd",
    "git reset --hard HEAD~1",
    "git checkout -- .",
    "git restore src/",
    "git stash clear",
    "git branch -D feature",
    "git push origin main",
    "chmod -R 777 dir",
    "chown root:root /etc/passwd",
    "crontab -r",
    "apt-get purge vim",
    "dpkg --purge vim",
    "docker rm container1",
    "docker system prune",
    "cat > /home/craig/important.txt",
    "echo data > config.yaml",
    "bash -c 'rm -rf /tmp/x'",
    "kb exec 'rm x'",
    "eval rm x",
    "wput --key super+Delete",
    "shutdown now",
    "ip link set eth0 down",
    "mount /dev/sdb1 /mnt",
]

FAKE_KB = r'''
import os, sys

mode = os.environ.get("FAKE_KB_DECISION", "none")
log = os.environ.get("FAKE_KB_LOG", "")
args = sys.argv[1:]

def record(line):
    if log:
        with open(log, "a") as f:
            f.write(line + "\n")

if not args:
    sys.exit(0)
if args[0] == "pub":
    record("pub " + " ".join(args[1:]))
elif args[0] == "notify":
    record("notify " + " ".join(args[1:]))
elif args[0] == "wait":
    topic = args[1]
    if mode == "approve" and topic.endswith(".approve_once"):
        print("button_clicked")
    elif mode == "reject" and topic.endswith(".reject_once"):
        print("button_clicked")
sys.exit(0)
'''


def test_screen_benign():
    for cmd in BENIGN:
        assert guard.screen(cmd) == [], cmd


def test_screen_dangerous():
    for cmd in DANGEROUS:
        assert guard.screen(cmd) != [], cmd


def _fake_kb(tmp_path, monkeypatch, decision):
    kb = tmp_path / "fake-kb"
    kb.write_text("#!/usr/bin/env python3\n" + FAKE_KB)
    kb.chmod(0o755)
    log = tmp_path / "kb.log"
    monkeypatch.setenv("FAKE_KB_DECISION", decision)
    monkeypatch.setenv("FAKE_KB_LOG", str(log))
    return str(kb), log


def test_gate_benign_never_touches_kb(tmp_path, monkeypatch):
    kb, log = _fake_kb(tmp_path, monkeypatch, "none")
    assert guard.gate("ls -la", kb_bin=kb, wait_seconds=5) is None
    assert not log.exists()


def test_gate_approve(tmp_path, monkeypatch):
    kb, log = _fake_kb(tmp_path, monkeypatch, "approve")
    assert guard.gate("rm /tmp/x", kb_bin=kb, wait_seconds=5) is None
    text = log.read_text()
    assert "notify" in text
    assert "Approve Once:topic:termf.guard." in text


def test_gate_reject(tmp_path, monkeypatch):
    kb, log = _fake_kb(tmp_path, monkeypatch, "reject")
    out = guard.gate("rm /tmp/x", kb_bin=kb, wait_seconds=5)
    assert out is not None and "rejected by Craig" in out
    assert "NOT executed" in out


def test_gate_timeout_denies(tmp_path, monkeypatch):
    kb, log = _fake_kb(tmp_path, monkeypatch, "none")
    out = guard.gate("rm /tmp/x", kb_bin=kb, wait_seconds=5)
    assert out is not None and "no decision" in out


def test_gate_kb_down_denies():
    out = guard.gate("rm /tmp/x", kb_bin="/nonexistent/kb", wait_seconds=5)
    assert out is not None and "kb unavailable" in out
