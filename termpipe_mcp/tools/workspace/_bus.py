"""
Bus helpers — kernclip-bus send/publish/get/poll primitives.
"""
import json
import os
import socket
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HOME          = Path.home()
_CC_DIR        = _HOME / ".context-core"
_CC_REGISTRY   = _CC_DIR / "registry.db"
_CC_WORKSPACES = _CC_DIR / "workspaces"
_ARTIFACTS_ROOT = _HOME / "Documents" / "TermPipe" / "Workspaces"
_KC_SOCK       = Path(f"/run/user/{os.getuid()}/kernclip-bus.sock")

# Bus topic namespace
_TOPIC_ACTIVE      = "termpipe.workspace.active"
_TOPIC_TASK        = "termpipe.workspace.task"
_TOPIC_INIT        = "termpipe.workspace.init"  # omniproxys subscribe here
_TOPIC_PLAN        = "termpipe.workspace.plan"
_TOPIC_WALKTHROUGH = "termpipe.workspace.walkthrough"

# Artifact type constants (mirrors Antigravity metadata)
ATYPE_TASK  = "ARTIFACT_TYPE_TASK"
ATYPE_PLAN  = "ARTIFACT_TYPE_IMPLEMENTATION_PLAN"
ATYPE_WALK  = "ARTIFACT_TYPE_WALKTHROUGH"
ATYPE_OTHER = "ARTIFACT_TYPE_OTHER"

# Review-gate bus topics
_TOPIC_REVIEW_REQUEST = "termpipe.workspace.review_request"
_TOPIC_FEEDBACK       = "termpipe.workspace.feedback"
_TOPIC_APPROVED       = "termpipe.workspace.approved"
_TOPIC_REJECTED       = "termpipe.workspace.rejected"

# Plan status constants
PLAN_DRAFT            = "draft"
PLAN_PENDING_APPROVAL = "pending_approval"
PLAN_APPROVED         = "approved"
PLAN_REJECTED         = "rejected"

_ATYPE_TO_TOPIC = {
    ATYPE_TASK: _TOPIC_TASK,
    ATYPE_PLAN: _TOPIC_PLAN,
    ATYPE_WALK: _TOPIC_WALKTHROUGH,
}

# ---------------------------------------------------------------------------
# kc-bus low-level (no SDK dependency — raw socket)
# ---------------------------------------------------------------------------

def _bus_send(op: str, topic: str, data: str, mime: str = "text/plain") -> dict | None:
    if not _KC_SOCK.exists():
        return None
    try:
        msg = json.dumps({"op": op, "topic": topic, "mime": mime, "data": data}) + "\n"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            s.connect(str(_KC_SOCK))
            s.sendall(msg.encode())
            buf = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
                if b"\n" in buf:
                    break
        return json.loads(buf.split(b"\n")[0])
    except Exception:
        return None


def _bus_pub(topic: str, data: str, mime: str = "text/plain") -> bool:
    r = _bus_send("pub", topic, data, mime)
    return bool(r and r.get("ok"))


def _bus_get(topic: str) -> str | None:
    r = _bus_send("get", topic, "")
    if r and r.get("ok") and r.get("data"):
        return r["data"]
    return None


def _bus_poll(topics: list[str], timeout_ms: int = 180000) -> tuple[str, str] | None:
    """
    Block until any of the given topics receives a new message.
    Returns (topic, data) or None on timeout.
    Uses sequential polling with short waits — avoids needing multi-socket select.
    """
    import time
    # Snapshot current seq for each topic so we only catch NEW messages
    seqs: dict[str, int] = {}
    for t in topics:
        try:
            msg = json.dumps({"op": "get", "topic": t}) + "\n"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect(str(_KC_SOCK))
                s.sendall(msg.encode())
                buf = b""
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                    if b"\n" in buf:
                        break
            r = json.loads(buf.split(b"\n")[0])
            seqs[t] = r.get("seq", 0) if r.get("ok") else 0
        except Exception:
            seqs[t] = 0

    deadline = time.monotonic() + timeout_ms / 1000.0
    poll_interval = 0.5  # seconds between checks

    while time.monotonic() < deadline:
        for t in topics:
            try:
                after = seqs.get(t, 0)
                msg = json.dumps({"op": "poll", "topic": t,
                                  "after_seq": after, "timeout_ms": 500}) + "\n"
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(3.0)
                    s.connect(str(_KC_SOCK))
                    s.sendall(msg.encode())
                    buf = b""
                    while True:
                        chunk = s.recv(65536)
                        if not chunk:
                            break
                        buf += chunk
                        if b"\n" in buf:
                            break
                r = json.loads(buf.split(b"\n")[0])
                if r.get("ok") and r.get("data") and r.get("seq", 0) > after:
                    return (t, r["data"])
            except Exception:
                pass
        time.sleep(poll_interval)
    return None


