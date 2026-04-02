"""
surgical/__init__.py
Exposes register_tools() and register_reviewer() for external customisation.

To swap in a custom review backend before the server starts:

    from termpipe_mcp.tools.surgical import register_reviewer

    def my_fn(prompt: str, timeout: float) -> str:
        return my_model.chat(prompt)

    register_reviewer("my_model", my_fn)
"""

from .readers    import register_tools as _reg_readers
from .writers    import register_tools as _reg_writers
from .replacers  import register_tools as _reg_replacers
from .formatters import register_tools as _reg_formatters


from .reviewer import register_reviewer  # re-export for convenience

# Wire in the enhanced pre-commit gate — replaces the basic reviewer gate.
# enhanced_reviewer adds: semantic duplicate detection, cross-file dep analysis,
# AST hash comparison, multi-language support, and the ghost-write fix.
from .enhanced_reviewer import enhanced_pre_commit_gate as _enhanced_gate
from .reviewer import pre_commit_gate as _basic_gate  # keep as fallback

# Monkey-patch: any tool that calls surgical.reviewer.pre_commit_gate gets the
# enhanced version transparently. No changes needed in writers/replacers.
import termpipe_mcp.tools.surgical.reviewer as _reviewer_mod
_reviewer_mod.pre_commit_gate = _enhanced_gate


def register_tools(mcp):
    _reg_readers(mcp)
    _reg_writers(mcp)
    _reg_replacers(mcp)
    _reg_formatters(mcp)
