"""
slimline.tools

Tool package for the slimline MCP server. server.py discovers every
module here and calls its register_tools(mcp) function. Add new modules
to this list as they're implemented.
"""

from . import core
from . import surgical

__all__ = ["core", "surgical"]
