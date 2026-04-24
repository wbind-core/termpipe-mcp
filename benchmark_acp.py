#!/usr/bin/env python3
"""Benchmark ACP performance: Cold start vs Warm daemon."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from termpipe_mcp.tools.surgical.acp import AcpConnection
from acp_daemon import query_daemon

def test_cold_start():
    """Test cold start performance."""
    print("Testing cold start (new connection each time)...")
    
    # First query (includes connection + session overhead)
    start = time.time()
    conn = AcpConnection("gemini")
    conn.connect()
    session_id = conn.new_session()
    result1 = conn.send_prompt("What is 2+2?")
    time1 = time.time() - start
    conn.disconnect()
    
    # Second query (cold start again)
    start = time.time()
    conn = AcpConnection("gemini")
    conn.connect()
    session_id = conn.new_session()
    result2 = conn.send_prompt("What is 3+3?")
    time2 = time.time() - start
    conn.disconnect()
    
    print(f"  Query 1: {time1:.2f}s (connection + session + prompt)")
    print(f"  Query 2: {time2:.2f}s (connection + session + prompt)")
    print(f"  Average: {(time1 + time2) / 2:.2f}s")
    print(f"  Results: {result1}, {result2}")
    
    return (time1 + time2) / 2

def test_warm_daemon():
    """Test warm daemon performance."""
    print("\nTesting warm daemon (pre-initialized session)...")
    
    # First query (daemon already running)
    start = time.time()
    result1 = query_daemon("gemini", "What is 2+2?")
    time1 = time.time() - start
    
    # Second query (reuse same session)
    start = time.time()
    result2 = query_daemon("gemini", "What is 3+3?")
    time2 = time.time() - start
    
    # Third query
    start = time.time()
    result3 = query_daemon("gemini", "What is 4+4?")
    time3 = time.time() - start
    
    print(f"  Query 1: {time1:.2f}s (prompt only)")
    print(f"  Query 2: {time2:.2f}s (prompt only)")
    print(f"  Query 3: {time3:.2f}s (prompt only)")
    print(f"  Average: {(time1 + time2 + time3) / 3:.2f}s")
    print(f"  Results: {result1}, {result2}, {result3}")
    
    return (time1 + time2 + time3) / 3

def main():
    print("=" * 60)
    print("ACP Performance Benchmark")
    print("=" * 60)
    
    cold_avg = test_cold_start()
    warm_avg = test_warm_daemon()
    
    print("\n" + "=" * 60)
    print("Summary:")
    print(f"  Cold start average: {cold_avg:.2f}s")
    print(f"  Warm daemon average: {warm_avg:.2f}s")
    print(f"  Speed improvement: {cold_avg / warm_avg:.1f}x faster")
    print("=" * 60)

if __name__ == "__main__":
    main()