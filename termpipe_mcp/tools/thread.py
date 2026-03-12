"""
Thread coordination tools for TermPipe MCP Server.

Publishes/subscribes via kernclip-bus (kc-bus) when the daemon is running.
Falls back to the flat ~/claude-antig/thread.md file when the bus is unavailable.

Topics:
  conduit.mcp.thread_log     — messages logged from any MCP client
  conduit.mcp.thread_read    — not published; read uses get() from bus store
"""

import json
import socket
import os
from pathlib import Path
from datetime import datetime
from termpipe_mcp.helpers import THREAD_FILE

# kernclip-bus socket path
_KC_SOCK = Path(f"/run/user/{os.getuid()}/kernclip-bus.sock")
_TOPIC_LOG = "conduit.mcp.thread_log"


# ---------------------------------------------------------------------------
# kc-bus helpers
# ---------------------------------------------------------------------------

def _kc_send(op: str, topic: str, data: str, mime: str = "text/plain") -> dict | None:
    """
    Send a single newline-delimited JSON message to kernclip-busd.
    Returns the parsed response dict, or None on any failure.
    """
    if not _KC_SOCK.exists():
        return None
    try:
        msg = json.dumps({"op": op, "topic": topic, "mime": mime, "data": data}) + "\n"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            s.connect(str(_KC_SOCK))
            s.sendall(msg.encode())
            resp = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                resp += chunk
                if b"\n" in resp:
                    break
        return json.loads(resp.split(b"\n")[0])
    except Exception:
        return None


def _kc_get(topic: str) -> list[dict]:
    """
    Retrieve stored messages for a topic via op=get.
    Returns list of message dicts (newest last), or [] on failure.
    """
    resp = _kc_send("get", topic, "")
    if resp and isinstance(resp.get("data"), list):
        return resp["data"]
    # Some bus versions return data as a JSON string
    if resp and isinstance(resp.get("data"), str):
        try:
            return json.loads(resp["data"])
        except Exception:
            pass
    return []


# ---------------------------------------------------------------------------
# Flat-file helpers (fallback)
# ---------------------------------------------------------------------------

def _file_log(entry: str):
    THREAD_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(THREAD_FILE, "a") as f:
        f.write(entry)


def _file_read(last_n: int) -> str:
    if not THREAD_FILE.exists():
        return "[No thread file found]"
    lines = THREAD_FILE.read_text().strip().split("\n")
    if last_n and len(lines) > last_n:
        lines = lines[-last_n:]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register_tools(mcp):
    """Register thread coordination tools with the MCP server."""

    @mcp.tool()
    def thread_log(message: str, sender: str = "MCP", topic: str = _TOPIC_LOG) -> str:
        """
        Log a message to the coordination thread.

        Publishes to kernclip-bus topic (default: conduit.mcp.thread_log) when
        the bus daemon is running, and always appends to the flat thread file as
        a durable backup.

        Args:
            message: Message to log
            sender:  Who is logging (default: MCP)
            topic:   kc-bus topic to publish on (default: conduit.mcp.thread_log)
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"\n[{timestamp}] **{sender}**: {message}\n"

        # Always write to flat file
        try:
            _file_log(entry)
        except Exception as e:
            return f"[Error writing thread file: {e}]"

        # Also publish to bus if available
        payload = json.dumps({"timestamp": timestamp, "sender": sender, "message": message})
        resp = _kc_send("pub", topic, payload, mime="application/json")
        bus_note = f" + published to {topic}" if resp else " (bus unavailable, file only)"

        return f"✅ Logged{bus_note}: {message[:60]}"

    @mcp.tool()
    def thread_read(last_n: int = 20, from_bus: bool = True) -> str:
        """
        Read recent entries from the coordination thread.

        Reads from kernclip-bus store when available (most recent messages),
        falls back to the flat thread file.

        Args:
            last_n:    Number of recent entries to return
            from_bus:  Prefer kc-bus store over flat file (default: True)
        """
        if from_bus:
            msgs = _kc_get(_TOPIC_LOG)
            if msgs:
                entries = msgs[-last_n:]
                lines = []
                for m in entries:
                    # m may be a dict (structured) or raw string
                    if isinstance(m, dict):
                        ts = m.get("timestamp", "")
                        sender = m.get("sender", "?")
                        msg = m.get("message", str(m))
                        lines.append(f"[{ts}] **{sender}**: {msg}")
                    else:
                        lines.append(str(m))
                return "\n".join(lines) or "[No bus messages found]"

        # Fallback to flat file
        return _file_read(last_n)
