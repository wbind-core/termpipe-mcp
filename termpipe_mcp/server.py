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

# Install tool-call telemetry middleware BEFORE any tools are registered.
from termpipe_mcp.telemetry import install_telemetry_middleware
install_telemetry_middleware(mcp)

# Dynamically import and register all tool modules.
# __init__.py is the single source of truth — add/remove/comment modules there.
import termpipe_mcp.tools as _tools
import inspect

for _name, _mod in inspect.getmembers(_tools, inspect.ismodule):
    if hasattr(_mod, "register_tools"):
        _mod.register_tools(mcp)

import threading as _threading
from termpipe_mcp.telemetry import compress_old_edits as _compress_old_edits
_threading.Thread(target=_compress_old_edits, daemon=True).start()

print("🚀 TermPipe MCP Server initialized", file=sys.stderr)

# Bootstrap provider detection (first-run probe, then load from settings)
from termpipe_mcp.bootstrap import maybe_bootstrap
maybe_bootstrap()

# Run the server
if __name__ == "__main__":
    mcp.run()
