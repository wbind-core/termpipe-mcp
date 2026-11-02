import json
import subprocess
import threading
import uuid
import sys
from typing import Dict, Any, List

class LightweightMCPClient:
    """A lightweight JSON-RPC over stdio client for MCP servers."""
    def __init__(self, command: str, args: List[str], env: Dict[str, str] = None):
        self.command = command
        self.args = args
        self.env = env
        self.process = None
        self._request_id = 0
        self._callbacks = {}
        self._running = False
        self.tools = []

    def start(self):
        import os
        env = os.environ.copy()
        if self.env:
            env.update(self.env)
            
        self.process = subprocess.Popen(
            [self.command] + self.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1
        )
        self._running = True
        
        self.reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self.reader_thread.start()
        
        # Initialize sequence
        init_res = self.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "omgr-client", "version": "1.0.0"}
        })
        
        self.send_notification("notifications/initialized", {})
        
        # Fetch tools
        tools_res = self.send_request("tools/list", {})
        if tools_res and "tools" in tools_res:
            self.tools = tools_res["tools"]
            
        return self.tools

    def _read_loop(self):
        while self._running and self.process and self.process.poll() is None:
            line = self.process.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
                if "id" in msg and msg["id"] in self._callbacks:
                    self._callbacks[msg["id"]] = msg
            except:
                pass

    def send_request(self, method: str, params: Dict) -> Any:
        self._request_id += 1
        req_id = self._request_id
        req = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params
        }
        self._callbacks[req_id] = None
        self.process.stdin.write(json.dumps(req) + "\n")
        self.process.stdin.flush()
        
        import time
        timeout = 10
        start = time.time()
        while self._callbacks[req_id] is None and (time.time() - start) < timeout:
            time.sleep(0.01)
            
        res = self._callbacks.pop(req_id, None)
        if res and "result" in res:
            return res["result"]
        return None

    def send_notification(self, method: str, params: Dict):
        req = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        self.process.stdin.write(json.dumps(req) + "\n")
        self.process.stdin.flush()

    def call_tool(self, name: str, arguments: Dict) -> str:
        res = self.send_request("tools/call", {
            "name": name,
            "arguments": arguments
        })
        if res and "content" in res and res["content"]:
            return res["content"][0].get("text", str(res))
        if res and "isError" in res and res["isError"]:
            return f"Error: {res}"
        return str(res)

    def stop(self):
        self._running = False
        if self.process:
            self.process.terminate()
            self.process.wait()
