#!/usr/bin/env python3
"""
TermPipe MCP Server Entry Point
=================================
Main server that registers all tool modules with FastMCP.

This server is launched by MCP clients (Claude Desktop, iFlow CLI, Gemini CLI, etc.)
and provides the tool interface. It communicates with the FastAPI backend
running on port 8421 for command execution and NLP functionality.

Copyright © 2026 Craig Nelson
"""

import sys
from pathlib import Path

# Add parent directory for imports if needed
sys.path.insert(0, str(Path(__file__).parent.parent))

# MCP framework
from mcp.server.fastmcp import FastMCP

# Initialize MCP server
mcp = FastMCP("termpipe")

# Dynamically import and register all tool modules.
# __init__.py is the single source of truth — add/remove/comment modules there.
import termpipe_mcp.tools as _tools
import inspect

for _name, _mod in inspect.getmembers(_tools, inspect.ismodule):
    if hasattr(_mod, "register_tools"):
        _mod.register_tools(mcp)

print("🚀 TermPipe MCP Server initialized", file=sys.stderr)

# Bootstrap provider detection (first-run probe, then load from settings)
from termpipe_mcp.bootstrap import maybe_bootstrap
maybe_bootstrap()

# Run the server
if __name__ == "__main__":
    mcp.run()
