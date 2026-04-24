#!/usr/bin/env python3
"""Test ACP connection."""

import sys
sys.path.insert(0, "/home/craig/termpipe-mcp")

from termpipe_mcp.tools.surgical.acp import AcpConnection
import time

print("Creating connection...")
conn = AcpConnection("qwen", cwd="/home/craig")

print("Connecting...")
start = time.time()
conn.connect()
print(f"Connected in {time.time() - start:.2f}s")

print("Creating session...")
start = time.time()
session_id = conn.new_session()
print(f"Session: {session_id} ({time.time() - start:.2f}s)")

print("\nSending prompt 1...")
start = time.time()
result = conn.send_prompt("What is 2+2? Answer briefly.")
print(f"Result: {result}")
print(f"Time: {time.time() - start:.2f}s")

print("\nSending prompt 2...")
start = time.time()
result = conn.send_prompt("What is 3+3? Answer briefly.")
print(f"Result: {result}")
print(f"Time: {time.time() - start:.2f}s")

print("\nDisconnecting...")
conn.disconnect()
print("Done!")
