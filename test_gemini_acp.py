#!/usr/bin/env python3
"""Test Gemini ACP speed."""

import sys
sys.path.insert(0, "/home/craig/termpipe-mcp")

from termpipe_mcp.tools.surgical.acp import AcpConnection
import time

print("Testing Gemini ACP...\n")

print("Connecting...")
conn = AcpConnection("gemini", cwd="/home/craig")
start = time.time()
conn.connect()
print(f"Connected in {time.time() - start:.2f}s")

print("Creating session...")
start = time.time()
session_id = conn.new_session()
print(f"Session: {session_id} ({time.time() - start:.2f}s)")

print("\nPrompt 1...")
start = time.time()
result = conn.send_prompt("What is 2+2? Answer with just the number.", timeout=60)
print(f"Result: {result}")
print(f"Time: {time.time() - start:.2f}s")

print("\nPrompt 2...")
start = time.time()
result = conn.send_prompt("What is 3+3? Answer with just the number.", timeout=60)
print(f"Result: {result}")
print(f"Time: {time.time() - start:.2f}s")

conn.disconnect()
print("\nDone!")
