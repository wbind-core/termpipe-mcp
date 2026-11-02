"""
slimline/tools/kb_tools.py — kb bus tools.

Craig's call (2026-10-30): every harness pointed at TermPipe needs the
bus as tools, not just Hank. These wrap kbd's wire protocol directly
(newline-delimited JSON over /run/user/$UID/kernclip-bus.sock, the
protocol printed by `kb --help`):

  pub / get / poll          immediate ops, one connection per call
  watch_register / _list / _stop / _start / _unregister
                            the daemon-side watch manager: kbd polls a
                            command (or static data) on an interval and
                            publishes changes to a topic. The registry
                            persists on the bus, so watches survive
                            daemon restarts and are shared by every
                            model on the machine.

Deliberately NOT a tool: sub. A subscription held inside a model call
blocks the model; subscriptions belong to the daemon side (watches and
actions), never to a tool call. kb_poll is the bounded model-side read
(seconds, caller's timeout), not a subscription.

Reactor rules (sub + value match + trigger) are a separate piece,
pending Craig's placement call: a second rule kind in kbd's watch
manager, or a sidecar process on the same bus.

Stdlib only, like the rest of the slim set.
"""

import json
import os
import socket

_MAX_OUT = 4000
_DEFAULT_TIMEOUT_S = 10.0


def _sock_path() -> str:
    return f"/run/user/{os.getuid()}/kernclip-bus.sock"


def _call(obj: dict, timeout_s: float = _DEFAULT_TIMEOUT_S) -> dict:
    """One wire-protocol round trip: send one JSON line, read one back."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout_s)
    try:
        s.connect(_sock_path())
        s.sendall((json.dumps(obj) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    finally:
        s.close()
    line = buf.split(b"\n", 1)[0].decode("utf-8", errors="replace")
    return json.loads(line)


def _data_or_empty(reply: dict) -> str:
    data = reply.get("data")
    if data is None:
        return "(empty)"
    if len(data) > _MAX_OUT:
        return data[:_MAX_OUT] + f"\n[truncated at {_MAX_OUT} chars]"
    return data


def register_tools(mcp):

    @mcp.tool()
    def kb_get(topic: str) -> str:
        """Read the current value of a kb bus topic.

        Returns the topic's data payload, or (empty) when the topic
        has no value yet.
        """
        try:
            reply = _call({"op": "get", "topic": topic})
        except Exception as e:
            return f"[Error] kb daemon unreachable: {e}"
        if not reply.get("ok"):
            return f"[Error] get {topic}: {reply.get('error', reply)}"
        return _data_or_empty(reply)

    @mcp.tool()
    def kb_pub(topic: str, data: str) -> str:
        """Publish data to a kb bus topic. Fire and forget: the value
        lands on the topic and every subscriber and action sees it."""
        try:
            reply = _call({"op": "pub", "topic": topic,
                           "mime": "text/plain", "data": data})
        except Exception as e:
            return f"[Error] kb daemon unreachable: {e}"
        if not reply.get("ok"):
            return f"[Error] pub {topic}: {reply.get('error', reply)}"
        return f"published to {topic}"

    @mcp.tool()
    def kb_poll(topic: str, timeout_ms: int = 5000) -> str:
        """Wait for the next message on a kb topic, up to timeout_ms.

        A bounded read, not a subscription: returns the message data
        when one arrives, or a timeout note. For standing waits, arm a
        watch or an action instead of polling.
        """
        timeout_ms = max(0, int(timeout_ms))
        try:
            reply = _call({"op": "poll", "topic": topic,
                           "timeout_ms": timeout_ms},
                          timeout_s=(timeout_ms / 1000.0) + 5.0)
        except Exception as e:
            return f"[Error] kb daemon unreachable: {e}"
        if not reply.get("ok"):
            if reply.get("error") == "timeout":
                return f"(timeout: no message on {topic} within {timeout_ms}ms)"
            return f"[Error] poll {topic}: {reply.get('error', reply)}"
        return _data_or_empty(reply)

    @mcp.tool()
    def kb_status() -> str:
        """kb daemon status: reachable or not, how many watches are
        registered, and the compositor/session facts from sys.metrics
        when the bus carries them."""
        lines = []
        try:
            reply = _call({"op": "watch_list"})
        except Exception as e:
            return f"kb daemon: unreachable at {_sock_path()} ({e})"
        lines.append(f"kb daemon: reachable at {_sock_path()}")
        rules = []
        if reply.get("ok"):
            try:
                rules = json.loads(reply.get("data") or "[]")
            except json.JSONDecodeError:
                rules = []
        lines.append(f"watches registered: {len(rules)}")
        try:
            metrics = _call({"op": "get", "topic": "sys.metrics"})
            raw = metrics.get("data")
            if raw:
                parsed = json.loads(raw)
                comp = parsed.get("compositor")
                sess = parsed.get("session_type")
                if comp or sess:
                    lines.append(f"compositor: {comp} (session: {sess})")
        except Exception:
            pass
        return "\n".join(lines)

    @mcp.tool()
    def kb_watch_register(id: str, topic: str, cmd: str = "",
                          data: str = "", interval_ms: int = 1000,
                          republish_on_startup: bool = False) -> str:
        """Register a daemon-side watch: kbd runs cmd on an interval
        (or republishes static data) and publishes the output to
        topic when it changes. Exactly one of cmd / data is used;
        cmd wins when both are given. The watch persists across
        daemon restarts. Re-registering an id replaces the watch."""
        if not cmd and not data:
            return "[Error] watch needs a cmd or static data."
        rule = {"id": id, "topic": topic, "cmd": cmd, "data": data,
                "interval_ms": int(interval_ms),
                "republish_on_startup": bool(republish_on_startup)}
        try:
            reply = _call({"op": "watch_register",
                           "rule": json.dumps(rule)})
        except Exception as e:
            return f"[Error] kb daemon unreachable: {e}"
        if not reply.get("ok"):
            return f"[Error] watch_register {id}: {reply.get('error', reply)}"
        return f"watch {id} registered: every {interval_ms}ms -> {topic}"

    @mcp.tool()
    def kb_watch_list() -> str:
        """List all registered kb watches with their rules."""
        try:
            reply = _call({"op": "watch_list"})
        except Exception as e:
            return f"[Error] kb daemon unreachable: {e}"
        if not reply.get("ok"):
            return f"[Error] watch_list: {reply.get('error', reply)}"
        try:
            rules = json.loads(reply.get("data") or "[]")
        except json.JSONDecodeError:
            return reply.get("data") or "[]"
        if not rules:
            return "no watches registered"
        out = []
        for r in rules:
            src = r.get("cmd") or "(static data)"
            out.append(f"{r.get('id')}: every {r.get('interval_ms')}ms "
                       f"[{src}] -> {r.get('topic')} "
                       f"(enabled={r.get('enabled')})")
        return "\n".join(out)

    @mcp.tool()
    def kb_watch_stop(id: str) -> str:
        """Stop a registered watch without removing it."""
        return _watch_simple("watch_stop", id)

    @mcp.tool()
    def kb_watch_start(id: str) -> str:
        """Resume a stopped watch."""
        return _watch_simple("watch_start", id)

    @mcp.tool()
    def kb_watch_unregister(id: str) -> str:
        """Stop and remove a registered watch."""
        return _watch_simple("watch_unregister", id)


def _watch_simple(op: str, id: str) -> str:
    try:
        reply = _call({"op": op, "id": id})
    except Exception as e:
        return f"[Error] kb daemon unreachable: {e}"
    if not reply.get("ok"):
        return f"[Error] {op} {id}: {reply.get('error', reply)}"
    return f"{op}: {id} ok"
