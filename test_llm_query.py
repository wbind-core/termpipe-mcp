#!/usr/bin/env python3
"""Test llm_query with ACP integration."""

import sys
sys.path.insert(0, "/home/craig/termpipe-mcp")

from termpipe_mcp.tools.surgical.helpers import llm_query
import time

print("Testing llm_query with ACP integration...\n")

print("Test 1: qwen via ACP")
start = time.time()
result = llm_query("What is 2+2? Answer with just the number.", model="qwen3-coder-plus", timeout=30)
print(f"Result: {result}")
print(f"Time: {time.time() - start:.2f}s\n")

print("Test 2: qwen via ACP (should reuse session)")
start = time.time()
result = llm_query("What is 3+3? Answer with just the number.", model="qwen3-coder-plus", timeout=30)
print(f"Result: {result}")
print(f"Time: {time.time() - start:.2f}s\n")

print("Test 3: groq (for comparison)")
start = time.time()
result = llm_query("What is 4+4? Answer with just the number.", timeout=30)
print(f"Result: {result}")
print(f"Time: {time.time() - start:.2f}s")

# Close ACP connections
from termpipe_mcp.tools.surgical.acp import close_all_connections
close_all_connections()
print("\nDone!")
