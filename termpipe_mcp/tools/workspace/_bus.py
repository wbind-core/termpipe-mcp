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
_TOPIC_HB          = "lms.daemon.heartbeat"

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

# Single-topic verdict channel — the PySide6 review sidecar publishes here.
# Payload is either the literal string "APPROVE", or "REJECT SEE FEEDBACK <path>"
# where <path> points to a unified-diff artifact with the reviewer's inline
# comments interwoven. workspace_init_and_review is the sole consumer.
_TOPIC_STATUS         = "termpipe.workspace.status"

# Stable pointer to whichever plan is currently pending review — lets external
# consumers (hotkey scripts, etc.) resolve "what's pending and where's the file"
# without depending on the internal review_request JSON schema.
_TOPIC_LATEST         = "termpipe.workspace.latest"

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


def _bus_get_multi(topics: list[str]) -> dict[str, str]:
    """
    Get the latest message for multiple topics in a single call.
    Returns a dict mapping topic name to its latest message data.
    """
    if not topics:
        return {}
    try:
        msg = json.dumps({"op": "get", "topics": topics}) + "\n"
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
        if r.get("ok") and r.get("messages"):
            return {m["topic"]: m["data"] for m in r["messages"] if "topic" in m and "data" in m}
    except Exception:
        pass
    return {}


def _bus_get_pattern(pattern: str) -> dict[str, str]:
    """
    Get the latest messages for all topics matching the glob pattern.
    Returns a dict mapping topic name to its latest message data.
    """
    import fnmatch
    # 1. Get all active topics
    r = _bus_send("topics", "", "")
    if not (r and r.get("ok") and r.get("topics")):
        return {}
    
    # 2. Filter with pattern
    matched = fnmatch.filter(r["topics"], pattern)
    if not matched:
        return {}
    
    # 3. Batch get
    return _bus_get_multi(matched)


def _bus_poll(topics: list[str], timeout_ms: int | None = 45000) -> tuple[str, str] | None:
    """
    Block until any of the given topics receives a new message.
    Returns (topic, data) or None on timeout.

    timeout_ms=None means block indefinitely (no timeout at all) —
    used for approval gates where the human review time is unbounded.

    This implementation uses 'sub' (streaming) to wait for the next message.
    """
    import time
    if not topics:
        return None
    
    # For multiple topics, we'd need multiple sockets or a pattern.
    # If it's just one topic, we can do it simply.
    if len(topics) == 1:
        t = topics[0]
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(None if timeout_ms is None else timeout_ms / 1000.0)
                s.connect(str(_KC_SOCK))
                # Send 'sub' for the topic
                msg = json.dumps({"op": "sub", "topic": t}) + "\n"
                s.sendall(msg.encode())
                
                buf = b""
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                    if b"\n" in buf:
                        lines = buf.split(b"\n")
                        for line in lines[:-1]:
                            if not line: continue
                            r = json.loads(line)
                            # Skip initial 'ok' ack
                            if r.get("ok") and not r.get("data") and r.get("seq") == 0:
                                continue
                            if r.get("data"):
                                return (r.get("topic", t), r["data"])
                        buf = lines[-1]
        except Exception:
            pass
        return None

    # For multiple topics, we use 'sub' with a pattern if they share a prefix,
    # or we fall back to the sequential 'get' poll.
    # Given the current use cases, we'll implement a robust sequential poll
    # but try to use 'sub' where possible.
    
    deadline = None if timeout_ms is None else time.monotonic() + timeout_ms / 1000.0
    while deadline is None or time.monotonic() < deadline:
        for t in topics:
            data = _bus_get(t)
            if data:
                return (t, data)
        time.sleep(0.5)
    return None


def _bus_sub_pattern(pattern: str, timeout_ms: int = 45000) -> tuple[str, str] | None:
    """
    Block until any topic matching the glob pattern receives a message.
    Returns (topic, data) or None on timeout.
    """
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout_ms / 1000.0)
            s.connect(str(_KC_SOCK))
            msg = json.dumps({"op": "sub", "pattern": pattern}) + "\n"
            s.sendall(msg.encode())
            
            buf = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
                if b"\n" in buf:
                    lines = buf.split(b"\n")
                    for line in lines[:-1]:
                        if not line: continue
                        r = json.loads(line)
                        if r.get("data"):
                            return (r.get("topic"), r["data"])
                    buf = lines[-1]
    except Exception:
        pass
    return None


