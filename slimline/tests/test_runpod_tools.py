"""runpod_tools tests (Craig's CLI-wrap build, 2026-10-14).

Hermetic: a stub runpodctl shell script stands in for the real
binary — it echoes its argv, or fails the way the real one does
when no API key is saved. No network, no key.
"""
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from slimline.tools import runpod_tools  # noqa: E402


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


STUB = """#!/bin/sh
if [ -n "$FAKE_RP_FAIL" ]; then
  echo "no api key: run runpodctl doctor" >&2
  exit 3
fi
echo "ARGS: $*"
"""


class RunpodToolsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        stub = Path(self.tmp) / "runpodctl"
        stub.write_text(STUB)
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        self._old_bin = os.environ.get("RUNPODCTL_BIN")
        os.environ["RUNPODCTL_BIN"] = str(stub)
        os.environ.pop("FAKE_RP_FAIL", None)
        mcp = FakeMCP()
        runpod_tools.register_tools(mcp)
        self.pod = mcp.tools["runpod_pod"]
        self.info = mcp.tools["runpod_info"]
        self.ssh = mcp.tools["runpod_ssh"]

    def tearDown(self):
        if self._old_bin is None:
            os.environ.pop("RUNPODCTL_BIN", None)
        else:
            os.environ["RUNPODCTL_BIN"] = self._old_bin
        os.environ.pop("FAKE_RP_FAIL", None)

    def test_pod_list(self):
        self.assertEqual(self.pod("list"), "ARGS: pod list --all")

    def test_pod_actions_pass_id(self):
        for action in ("get", "start", "stop", "restart", "logs"):
            self.assertEqual(self.pod(action, "abc123"),
                             f"ARGS: pod {action} abc123")

    def test_pod_action_needs_id(self):
        self.assertIn("needs a pod_id", self.pod("start"))

    def test_no_delete_by_design(self):
        r = self.pod("delete", "abc123")
        self.assertIn("Unknown action", r)
        self.assertIn("No delete", r)

    def test_info_actions(self):
        self.assertEqual(self.info("gpus"), "ARGS: gpu list")
        self.assertEqual(self.info("volumes"),
                         "ARGS: network-volume list")
        self.assertEqual(self.info("doctor"), "ARGS: doctor")
        self.assertIn("Unknown action", self.info("serverless"))

    def test_ssh_actions(self):
        self.assertEqual(self.ssh("keys"), "ARGS: ssh list-keys")
        self.assertEqual(self.ssh("add_key", key="ssh-ed25519 AAAA x"),
                         "ARGS: ssh add-key --key ssh-ed25519 AAAA x")
        self.assertEqual(self.ssh("info", pod_id="abc123"),
                         "ARGS: ssh info abc123")
        self.assertIn("needs the public key", self.ssh("add_key"))

    def test_failure_passthrough(self):
        os.environ["FAKE_RP_FAIL"] = "1"
        r = self.pod("list")
        self.assertIn("failed (exit 3)", r)
        self.assertIn("no api key", r)

    def test_missing_binary(self):
        os.environ["RUNPODCTL_BIN"] = "/nonexistent/runpodctl"
        self.assertIn("not found", self.pod("list"))


if __name__ == "__main__":
    unittest.main()
