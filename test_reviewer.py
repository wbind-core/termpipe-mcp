#!/usr/bin/env python3
"""Test the reviewer backend."""

import sys
sys.path.insert(0, "/home/craig/termpipe-mcp")

from termpipe_mcp.bootstrap import maybe_bootstrap
from termpipe_mcp.tools.surgical.reviewer import _get_reviewer

maybe_bootstrap()
reviewer = _get_reviewer()

print(f"Reviewer: {reviewer}")
if reviewer:
    result = reviewer("Is 2+2=4? Reply APPROVED.", 20.0)
    print(f"Result: {result}")
