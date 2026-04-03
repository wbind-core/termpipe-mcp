"""
termpipe_mcp.tools.workspace — workspace artifact management.

External callers import workspace_resume and register_tools from here.
This subpackage replaces the monolithic workspace.py.
"""

# Cascade sub-module imports so importlib.reload(__init__) pulls fresh versions
from . import _bus, _registry, _db, _files, _task, _artifacts
from . import tools as _tools_mod

# Re-export the external surface — these paths must not change
from ._artifacts import workspace_resume
from .tools import register_tools
