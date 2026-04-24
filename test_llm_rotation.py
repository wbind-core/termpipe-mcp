#!/usr/bin/env python3
"""Test script for LLM round-robin rotation."""

import sys
import time

# Add project to path
sys.path.insert(0, "/home/craig/termpipe-mcp")

from termpipe_mcp.tools.surgical.helpers import llm_query, get_llm_stats


def test_rotation(num_calls: int = 5, timeout: int = 20):
    """Test round-robin rotation across all providers."""
    print(f"Making {num_calls} LLM calls with round-robin rotation...\n")
    
    results = []
    start = time.time()
    
    for i in range(num_calls):
        call_start = time.time()
        result = llm_query(f"Say just the word 'call{i+1}'", timeout=timeout)
        call_duration = time.time() - call_start
        
        results.append({
            "call": i + 1,
            "result": result.strip()[:30],
            "duration": call_duration
        })
        print(f"Call {i+1}: {result.strip()[:40]}... ({call_duration:.1f}s)")
    
    total_duration = time.time() - start
    stats = get_llm_stats()
    
    print(f"\n{'='*50}")
    print(f"Total time: {total_duration:.1f}s")
    print(f"Average per call: {total_duration/num_calls:.1f}s")
    print(f"\nLLM Stats:")
    print(f"  Total calls: {stats['total_calls']}")
    print(f"  Rotation index: {stats['rotation_index']}")
    print(f"  Providers: {stats['providers']}")
    

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test LLM round-robin rotation")
    parser.add_argument("-n", "--num-calls", type=int, default=5, help="Number of calls")
    parser.add_argument("-t", "--timeout", type=int, default=20, help="Timeout per call")
    args = parser.parse_args()
    
    test_rotation(args.num_calls, args.timeout)
