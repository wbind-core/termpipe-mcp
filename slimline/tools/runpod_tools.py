"""
slimline/tools/runpod_tools.py — RunPod pod/account tools.

Craig's call (2026-10-14): don't port the official MCP server's
54 tools into the slim set — wrap runpodctl (RunPod's official
CLI, the same v2 REST API underneath) in a few simplified tools
instead. Equipping the tools = this module's presence in
server.py's module list; remove the module and they're gone.

Deliberately NOT exposed: pod create / delete / reset / update,
and everything serverless / template / registry / hub. Delete
terminates the pod; it stays a console act, not a tool call.

The API key is never a tool argument. runpodctl resolves it from
the RUNPOD_API_KEY environment variable or ~/.runpod/config.toml
(written by `runpodctl doctor`). Until one exists, commands
return runpodctl's own no-key error, passed through as-is.
"""

import os
import shutil
import subprocess

_MAX_OUT = 4000
_POD_ID_ACTIONS = ("get", "start", "stop", "restart", "logs")


def _bin() -> str:
    return (os.environ.get("RUNPODCTL_BIN")
            or shutil.which("runpodctl")
            or "/home/craig/.local/bin/runpodctl")


def _run(args, timeout=90) -> str:
    try:
        r = subprocess.run([_bin()] + args, capture_output=True,
                           text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return ("[Error] runpodctl not found. Install it from the "
                "runpod/runpodctl releases.")
    except subprocess.TimeoutExpired:
        return (f"[Error] runpodctl {' '.join(args)} timed out "
                f"after {timeout}s.")
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    if r.returncode != 0:
        return (f"[Error] runpodctl {' '.join(args)} failed "
                f"(exit {r.returncode}): "
                f"{(err or out)[:_MAX_OUT]}")
    return (out or "(no output)")[:_MAX_OUT]


def register_tools(mcp):

    @mcp.tool()
    def runpod_pod(action: str, pod_id: str = "") -> str:
        """
        Manage RunPod pods through runpodctl.

        Actions:
          list    — all pods on the account.
          get     — one pod's details (ports, SSH info, state).
          start   — start a stopped pod.
          stop    — stop a running pod (volume persists; this is
                    the safe off switch, NOT delete).
          restart — restart a pod.
          logs    — read a pod's logs.

        There is deliberately no delete: terminating a pod is a
        console act, never a tool call.

        Args:
            action: list | get | start | stop | restart | logs
            pod_id: Pod id (required for all but list).
        """
        if action == "list":
            # --all: runpodctl defaults to running pods only, and
            # ours spends its life stopped — a list that hides it
            # is useless for the wake/status work these tools serve.
            return _run(["pod", "list", "--all"])
        if action in _POD_ID_ACTIONS:
            if not pod_id:
                return f"[Error] runpod_pod {action} needs a pod_id."
            return _run(["pod", action, pod_id])
        return (f"[Error] Unknown action '{action}'. Use list | "
                f"get | start | stop | restart | logs. (No delete "
                f"by design.)")

    @mcp.tool()
    def runpod_info(action: str) -> str:
        """
        Read-only RunPod account and discovery information.

        Actions:
          doctor     — diagnose the CLI setup (API key, SSH keys).
          user       — account info and balance.
          gpus       — GPU types, availability, prices.
          volumes    — network volumes.
          billing    — billing history.
          datacenters — data centers and their GPU availability.

        Args:
            action: doctor | user | gpus | volumes | billing |
                    datacenters
        """
        table = {
            "doctor": ["doctor"],
            "user": ["user"],
            "gpus": ["gpu", "list"],
            "volumes": ["network-volume", "list"],
            "billing": ["billing"],
            "datacenters": ["datacenter", "list"],
        }
        args = table.get(action)
        if args is None:
            return (f"[Error] Unknown action '{action}'. Use "
                    f"doctor | user | gpus | volumes | billing | "
                    f"datacenters.")
        return _run(args)

    @mcp.tool()
    def runpod_ssh(action: str, pod_id: str = "", key: str = "") -> str:
        """
        RunPod SSH keys and per-pod SSH info.

        Actions:
          keys    — list the SSH public keys on the account. Keys
                    saved here are installed on pods at start,
                    which is the durable fix for a pod restart
                    wiping ~/.ssh/authorized_keys.
          add_key — add a public key to the account.
          info    — SSH connection info for one pod.

        Args:
            action: keys | add_key | info
            pod_id: Pod id (info).
            key: The public key text (add_key). Public keys are
                 not secrets; the API key is never passed here.
        """
        if action == "keys":
            return _run(["ssh", "list-keys"])
        if action == "add_key":
            if not key:
                return "[Error] runpod_ssh add_key needs the public key text."
            return _run(["ssh", "add-key", "--key", key])
        if action == "info":
            if not pod_id:
                return "[Error] runpod_ssh info needs a pod_id."
            return _run(["ssh", "info", pod_id])
        return (f"[Error] Unknown action '{action}'. Use keys | "
                f"add_key | info.")
