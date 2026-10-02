"""
TermPipe MCP Slimline Server
=================================
A lightweight MCP server.
Uses kb IPC for execution and undo state.
"""

import sys
import inspect
from pathlib import Path

# Add parent directory for imports so `slimline` package resolves
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.fastmcp import FastMCP
import slimline.tools as _tools
from slimline.tools import files_tools, edit_tools, exec_tools, system_tools, codegraph_tools, speak_tools, override_tools, workspace_tools

# Initialize MCP server
mcp = FastMCP("termpipe-slimline")

# Dynamically import and register all tool modules from slimline.tools
modules = [files_tools, edit_tools, exec_tools, system_tools, codegraph_tools, speak_tools, override_tools, workspace_tools]

for _mod in modules:
    if hasattr(_mod, "register_tools"):
        _mod.register_tools(mcp)

print("🚀 TermPipe MCP Slimline Server initialized", file=sys.stderr)

# Run the server
if __name__ == "__main__":
    mcp.run()
