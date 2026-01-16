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

# Import and register all tool modules
from termpipe_mcp.tools import (
    process,
    termf,
    iflow,
    files,
    surgical,
    apps,
    wbind,
    search,
    thread,
    system,
    debug,
    gemini_debug
)

# Register all tools
process.register_tools(mcp)
termf.register_tools(mcp)
iflow.register_tools(mcp)
files.register_tools(mcp)
surgical.register_tools(mcp)
apps.register_tools(mcp)
wbind.register_tools(mcp)
search.register_tools(mcp)
thread.register_tools(mcp)
system.register_tools(mcp)
debug.register_tools(mcp)
gemini_debug.register_tools(mcp)

print("🚀 TermPipe MCP Server initialized", file=sys.stderr)

# Run the server
if __name__ == "__main__":
    mcp.run()
