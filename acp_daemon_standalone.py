#!/usr/bin/env python3
"""
ACP Daemon - Standalone single-file version.

A persistent ACP service using kc-bus IPC. Keeps a warm ACP connection
ready for fast queries. No project PYTHONPATH needed — just run it.

Usage:
    # Start daemon
    ~/termpipe-mcp/.venv/bin/python acp_daemon_standalone.py --backend gemini

    # Query from any process
    kc-bus pub acp.gemini.requests '{"prompt": "What is 2+2?", "request_id": "123"}'
    kc-bus get acp.gemini.responses

    # Client mode (one-shot query)
    ~/termpipe-mcp/.venv/bin/python acp_daemon_standalone.py --backend gemini --query "What is 2+2?"
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from queue import Queue

# ──────────────────────────────────────────────────────────
# kc-bus loader
# ──────────────────────────────────────────────────────────
sys.path.insert(0, str(Path.cwd()))
KC_BUS_SDK = Path.home() / "kernclip" / "bus" / "sdk" / "python"
sys.path.insert(0, str(KC_BUS_SDK))

try:
    from kernclip_bus import Bus
except ImportError:
    print(f"Error: kc-bus Python SDK not found at {KC_BUS_SDK}", file=sys.stderr)
    print("Make sure kernclip/bus is installed.", file=sys.stderr)
    sys.exit(1)


# ──────────────────────────────────────────────────────────
# AcpConnection (inlined from termpipe_mcp/tools/surgical/acp.py)
# ──────────────────────────────────────────────────────────

class AcpConnection:
    """Persistent ACP connection to a CLI agent (qwen, gemini)."""

    def __init__(self, backend: str, model: str = None, cwd: str = None):
        self.backend = backend
        self.model = model
        self.cwd = cwd or str(Path.cwd())

        self._process: subprocess.Popen | None = None
        self._session_id: str | None = None
        self._request_id = 0
        self._is_initialized = False
        self._pending_responses: dict[int, Queue] = {}
        self._reader_thread: threading.Thread | None = None
        self._buffer = ""
        self._response_callback = None

        self._configs = {
            "qwen": {
                "cmd": "qwen",
                "args": ["--acp"],
                "default_model": "qwen3-coder-plus",
            },
            "gemini": {
                "cmd": "gemini",
                "args": ["--acp"],
                "default_model": "gemini-3-pro-preview",
            },
        }

    def connect(self, timeout: float = 30.0) -> bool:
        if self._process is not None:
            return True

        config = self._configs.get(self.backend)
        if not config:
            raise ValueError(f"Unknown backend: {self.backend}")

        cmd = [config["cmd"]] + config["args"]
        try:
            self._process = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, bufsize=1, cwd=self.cwd,
            )
        except FileNotFoundError:
            raise RuntimeError(f"CLI not found: {config['cmd']}")

        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

        init_response = self._send_request("initialize", {
            "protocolVersion": 1,
            "clientCapabilities": {"fs": {"readTextFile": True, "writeTextFile": True}},
        }, timeout=timeout)

        if not init_response or "error" in init_response:
            self.disconnect()
            raise RuntimeError(f"Initialize failed: {init_response}")

        self._is_initialized = True
        return True

    def new_session(self, cwd: str = None, timeout: float = 30.0) -> str:
        if not self._is_initialized:
            raise RuntimeError("Not connected. Call connect() first.")

        response = self._send_request("session/new", {
            "cwd": cwd or self.cwd,
            "mcpServers": [],
        }, timeout=timeout)

        if not response or "error" in response:
            raise RuntimeError(f"Session/new failed: {response}")

        self._session_id = response.get("result", {}).get("sessionId")
        return self._session_id

    def send_prompt(self, prompt: str, timeout: float = 60.0,
                    on_chunk=None) -> str:
        if not self._session_id:
            raise RuntimeError("No session. Call new_session() first.")

        self._streaming_text: list[str] = []
        self._response_callback = on_chunk

        response = self._send_request("session/prompt", {
            "sessionId": self._session_id,
            "prompt": [{"type": "text", "text": prompt}],
        }, timeout=timeout)

        self._response_callback = None
        if not response:
            return "[Error: No response]"
        if "error" in response:
            return f"[Error: {response['error'].get('message', 'Unknown error')}]"

        text = "".join(self._streaming_text)
        if text:
            return text

        return self._extract_text(response.get("result", {}))

    def set_model(self, model_id: str, timeout: float = 10.0) -> bool:
        if not self._session_id:
            return False
        response = self._send_request("session/set_model", {
            "sessionId": self._session_id,
            "modelId": model_id,
        }, timeout=timeout)
        return response and "error" not in response

    def disconnect(self):
        if self._process:
            try:
                self._process.stdin.close()
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()
            finally:
                self._process = None
        self._session_id = None
        self._is_initialized = False
        self._pending_responses.clear()

    def _send_request(self, method: str, params: dict, timeout: float = 30.0):
        self._request_id += 1
        request_id = self._request_id
        response_queue = Queue()
        self._pending_responses[request_id] = response_queue

        try:
            self._process.stdin.write(json.dumps({
                "jsonrpc": "2.0", "id": request_id,
                "method": method, "params": params,
            }) + "\n")
            self._process.stdin.flush()

            try:
                return response_queue.get(timeout=timeout)
            except Exception:
                return {"error": {"message": f"Timeout waiting for {method}"}}
        finally:
            self._pending_responses.pop(request_id, None)

    def _read_loop(self):
        while self._process and self._process.poll() is None:
            try:
                line = self._process.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                print(f"[ACP RECV] {line[:200]}...", file=sys.stderr)
                message = json.loads(line)
                self._handle_message(message)
            except json.JSONDecodeError as e:
                print(f"[ACP JSON ERR] {e}", file=sys.stderr)
            except Exception as e:
                print(f"[ACP READ ERR] {e}", file=sys.stderr)
                break

    def _handle_message(self, message: dict):
        if "id" in message:
            rid = message["id"]
            if rid in self._pending_responses:
                self._pending_responses[rid].put(message)
                return
        if "method" in message:
            method = message["method"]
            params = message.get("params", {})
            if method == "session/update":
                self._handle_session_update(params)
            elif method == "session/request_permission":
                self._handle_permission_request(message)

    def _handle_session_update(self, params: dict):
        update = params.get("update", {})
        if update.get("sessionUpdate") == "agent_message_chunk":
            text = update.get("content", {}).get("text", "")
            if text:
                if hasattr(self, '_streaming_text'):
                    self._streaming_text.append(text)
                if self._response_callback:
                    self._response_callback(text)

    def _handle_permission_request(self, message: dict):
        rid = message.get("id")
        if rid is None:
            return
        response = {"jsonrpc": "2.0", "id": rid, "result": {"proceed": True}}
        try:
            self._process.stdin.write(json.dumps(response) + "\n")
            self._process.stdin.flush()
        except Exception as e:
            print(f"[ACP PERMISSION ERR] {e}", file=sys.stderr)

    @staticmethod
    def _extract_text(result: dict) -> str:
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            if "content" in result:
                c = result["content"]
                if isinstance(c, str):
                    return c
                if isinstance(c, list):
                    return "".join(
                        x.get("text", "") for x in c
                        if isinstance(x, dict) and x.get("type") == "text"
                    )
            if "text" in result:
                return result["text"]
        return str(result)

    @property
    def is_connected(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def has_session(self) -> bool:
        return self._session_id is not None


# ──────────────────────────────────────────────────────────
# AcpDaemon — bus-facing service
# ──────────────────────────────────────────────────────────

class AcpDaemon:
    """Listens on acp.{backend}.requests, replies on acp.{backend}.responses."""

    def __init__(self, backend: str, model: str = None):
        self.backend = backend
        self.model = model
        self.conn = None
        self.bus = Bus()
        self.running = False
        self._lock = threading.Lock()

        self.request_topic = f"acp.{backend}.requests"
        self.response_topic = f"acp.{backend}.responses"

    def start(self):
        print(f"Starting ACP daemon for {self.backend}...", file=sys.stderr)
        print(f"  Request topic:  {self.request_topic}", file=sys.stderr)
        print(f"  Response topic: {self.response_topic}", file=sys.stderr)

        self.conn = AcpConnection(self.backend, self.model)
        print("Connecting to ACP backend...", file=sys.stderr)
        self.conn.connect()

        print("Creating session...", file=sys.stderr)
        session_id = self.conn.new_session()
        print(f"Session ready: {session_id}", file=sys.stderr)

        self.running = True
        print(f"Daemon ready. Listening on {self.request_topic}", file=sys.stderr)
        print("Publish {'prompt': '...', 'request_id': '...'} to query.\n", file=sys.stderr)

        for msg in self.bus.sub(self.request_topic):
            if not self.running:
                break
            threading.Thread(target=self._handle_request, args=(msg,), daemon=True).start()

    def _handle_request(self, msg):
        try:
            data = json.loads(msg.data) if isinstance(msg.data, str) else msg.data
            prompt = data.get("prompt", "")
            request_id = data.get("request_id", str(msg.seq))
            timeout = data.get("timeout", 60.0)

            if not prompt:
                self._send_response(request_id, error="No prompt provided")
                return

            with self._lock:
                result = self.conn.send_prompt(prompt, timeout=timeout)

            self._send_response(request_id, result=result)

        except json.JSONDecodeError:
            self._send_response(str(msg.seq), error="Invalid JSON")
        except Exception as e:
            self._send_response(str(msg.seq), error=f"Query failed: {e}")

    def _send_response(self, request_id: str, result: str = None, error: str = None):
        response = {"request_id": request_id, "timestamp": time.time()}
        if error:
            response["error"] = error
        else:
            response["result"] = result
        self.bus.pub(self.response_topic, json.dumps(response))

    def stop(self):
        print("\nShutting down...", file=sys.stderr)
        self.running = False
        if self.conn:
            self.conn.disconnect()


def query_daemon(backend: str, prompt: str, timeout: float = 60.0) -> str:
    """Send a query to a running daemon and wait for the response."""
    bus = Bus()
    request_id = str(int(time.time() * 1000))
    request_topic = f"acp.{backend}.requests"
    response_topic = f"acp.{backend}.responses"

    bus.pub(request_topic, json.dumps({
        "prompt": prompt,
        "request_id": request_id,
        "timeout": timeout,
    }))

    start_time = time.time()
    for msg in bus.sub(response_topic):
        if time.time() - start_time > timeout:
            return "[Error: Daemon timeout]"
        try:
            data = json.loads(msg.data) if isinstance(msg.data, str) else msg.data
            if data.get("request_id") == request_id:
                if "error" in data:
                    return f"[Daemon Error: {data['error']}]"
                return data.get("result", "[No result]")
        except (json.JSONDecodeError, Exception) as e:
            return f"[Error: {e}]"

    return "[Error: Daemon connection lost]"


# ──────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ACP Daemon - Persistent ACP service")
    parser.add_argument("--backend", default="gemini", choices=["gemini", "qwen"],
                        help="Backend to use (gemini or qwen)")
    parser.add_argument("--model", help="Model ID (uses backend default if not specified)")
    parser.add_argument("--query", help="Send a single query and exit (client mode)")
    parser.add_argument("--timeout", type=float, default=60.0, help="Timeout for queries")

    args = parser.parse_args()

    if args.query:
        result = query_daemon(args.backend, args.query, args.timeout)
        print(result)
    else:
        daemon = AcpDaemon(args.backend, args.model)
        try:
            daemon.start()
        except KeyboardInterrupt:
            daemon.stop()


if __name__ == "__main__":
    main()
