#!/usr/bin/env python3
"""Test script for Groq latency."""

import sys
import time

sys.path.insert(0, "/home/craig/termpipe-mcp")

from termpipe_mcp.tools.surgical.helpers import llm_query


def test_groq(num_calls: int = 5, timeout: int = 30):
    """Test Groq latency only."""
    print(f"Testing Groq only ({num_calls} calls)...\n")
    
    results = []
    start = time.time()
    
    for i in range(num_calls):
        call_start = time.time()
        result = llm_query(f"Say just the word 'call{i+1}'", model="openai/gpt-oss-20b", timeout=timeout, rotate=False)
        call_duration = time.time() - call_start
        
        results.append(call_duration)
        print(f"Call {i+1}: {result.strip()[:30]}... ({call_duration:.1f}s)")
    
    total = time.time() - start
    
    print(f"\n{'='*40}")
    print(f"Total: {total:.1f}s")
    print(f"Avg: {sum(results)/len(results):.1f}s")
    print(f"Min: {min(results):.1f}s")
    print(f"Max: {max(results):.1f}s")


if __name__ == "__main__":
    test_groq()
