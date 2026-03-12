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


def register_tools(mcp):
    _reg_readers(mcp)
    _reg_writers(mcp)
    _reg_replacers(mcp)
    _reg_formatters(mcp)
