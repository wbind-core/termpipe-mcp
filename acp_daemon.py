#!/usr/bin/env python3
"""
ACP Daemon - Persistent ACP service using kc-bus IPC.

Keeps a warm ACP connection ready for fast queries via kc-bus topics.

Architecture:
  - Daemon subscribes to: acp.{backend}.requests
  - Clients publish:      {"prompt": "...", "request_id": "..."}
  - Daemon publishes to:  acp.{backend}.responses
  - Responses:            {"request_id": "...", "result": "..."}

Usage:
    # Start daemon
    python acp_daemon.py --backend gemini
    
    # Query from any process
    kc-bus pub acp.gemini.requests '{"prompt": "What is 2+2?", "request_id": "123"}'
    kc-bus get acp.gemini.responses  # or subscribe for streaming
"""

import argparse
import json
import sys
import threading
import time
from pathlib import Path
from queue import Queue

# Add termpipe-mcp to path
sys.path.insert(0, str(Path(__file__).parent))

from termpipe_mcp.tools.surgical.acp import AcpConnection

# Import kc-bus SDK
KC_BUS_SDK = Path.home() / "kernclip" / "bus" / "sdk" / "python"
sys.path.insert(0, str(KC_BUS_SDK))

try:
    from kernclip_bus import Bus
except ImportError:
    print(f"Error: kc-bus Python SDK not found at {KC_BUS_SDK}", file=sys.stderr)
    print("Make sure kernclip/bus is installed.", file=sys.stderr)
    sys.exit(1)


class AcpDaemon:
    def __init__(self, backend: str, model: str = None):
        self.backend = backend
        self.model = model
        self.conn = None
        self.bus = Bus()
        self.running = False
        self._lock = threading.Lock()
        
        # Topic names
        self.request_topic = f"acp.{backend}.requests"
        self.response_topic = f"acp.{backend}.responses"
        
    def start(self):
        """Initialize ACP connection and start listening for requests."""
        print(f"Starting ACP daemon for {self.backend}...", file=sys.stderr)
        print(f"  Request topic:  {self.request_topic}", file=sys.stderr)
        print(f"  Response topic: {self.response_topic}", file=sys.stderr)
        
        # Connect to ACP backend
        self.conn = AcpConnection(self.backend, self.model)
        print("Connecting to ACP backend...", file=sys.stderr)
        self.conn.connect()
        
        # Create session
        print("Creating session...", file=sys.stderr)
        session_id = self.conn.new_session(mode="autoEdit")
        print(f"Session ready: {session_id}", file=sys.stderr)
        
        # Start listening for requests
        self.running = True
        print(f"Daemon ready. Listening on {self.request_topic}", file=sys.stderr)
        print("Publish {'prompt': '...', 'request_id': '...'} to query.\n", file=sys.stderr)
        
        # Subscribe to requests
        for msg in self.bus.sub(self.request_topic):
            if not self.running:
                break
            
            # Handle each request in a thread
            threading.Thread(target=self._handle_request, args=(msg,), daemon=True).start()
    
    def _handle_request(self, msg):
        """Process a single request."""
        try:
            data = json.loads(msg.data) if isinstance(msg.data, str) else msg.data
            prompt = data.get("prompt", "")
            request_id = data.get("request_id", str(msg.seq))
            timeout = data.get("timeout", 60.0)
            
            if not prompt:
                self._send_response(request_id, error="No prompt provided")
                return
            
            # Process prompt through ACP (thread-safe)
            with self._lock:
                result = self.conn.send_prompt(prompt, timeout=timeout)
            
            # Send response
            self._send_response(request_id, result=result)
            
        except json.JSONDecodeError:
            self._send_response(str(msg.seq), error="Invalid JSON")
        except Exception as e:
            self._send_response(str(msg.seq), error=f"Query failed: {e}")
    
    def _send_response(self, request_id: str, result: str = None, error: str = None):
        """Publish response to response topic."""
        response = {
            "request_id": request_id,
            "timestamp": time.time()
        }
        
        if error:
            response["error"] = error
        else:
            response["result"] = result
        
        self.bus.pub(self.response_topic, json.dumps(response))
    
    def stop(self):
        """Graceful shutdown."""
        print("\nShutting down...", file=sys.stderr)
        self.running = False
        
        if self.conn:
            self.conn.disconnect()


def query_daemon(backend: str, prompt: str, timeout: float = 60.0) -> str:
    """
    Send a query to a running ACP daemon and wait for response.
    
    Args:
        backend: Backend name (gemini, qwen)
        prompt: The prompt to send
        timeout: Max time to wait for response
    
    Returns:
        Response text or error message
    """
    bus = Bus()
    request_id = str(int(time.time() * 1000))  # Unique ID
    
    request_topic = f"acp.{backend}.requests"
    response_topic = f"acp.{backend}.responses"
    
    # Send request
    request = {
        "prompt": prompt,
        "request_id": request_id,
        "timeout": timeout
    }
    
    bus.pub(request_topic, json.dumps(request))
    
    # Subscribe to responses and wait for our response
    start_time = time.time()
    for msg in bus.sub(response_topic):
        # Check timeout
        if time.time() - start_time > timeout:
            return "[Error: Daemon timeout]"
        
        try:
            data = json.loads(msg.data) if isinstance(msg.data, str) else msg.data
            if data.get("request_id") == request_id:
                if "error" in data:
                    return f"[Daemon Error: {data['error']}]"
                return data.get("result", "[No result]")
            # Not our response, continue listening
        except json.JSONDecodeError:
            continue  # Skip invalid JSON
        except Exception as e:
            return f"[Error: {e}]"
    
    return "[Error: Daemon connection lost]"


def main():
    parser = argparse.ArgumentParser(description="ACP Daemon - Persistent ACP service")
    parser.add_argument("--backend", default="gemini", choices=["gemini", "qwen"],
                       help="Backend to use (gemini or qwen)")
    parser.add_argument("--model", help="Model ID (uses backend default if not specified)")
    parser.add_argument("--query", help="Send a single query and exit (client mode)")
    parser.add_argument("--timeout", type=float, default=60.0, help="Timeout for queries")
    
    args = parser.parse_args()
    
    if args.query:
        # Client mode: send query to daemon
        result = query_daemon(args.backend, args.query, args.timeout)
        print(result)
    else:
        # Server mode: start daemon
        daemon = AcpDaemon(args.backend, args.model)
        try:
            daemon.start()
        except KeyboardInterrupt:
            daemon.stop()


if __name__ == "__main__":
    main()
