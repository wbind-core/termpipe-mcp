"""
bootstrap.py — One-time provider detection + settings write.

Called once at server startup from server.py.
  - is_first_run=True  (or missing settings.json): default to OpenRouter
  - is_first_run=False: read saved backend, register directly
  
Provider priority: OpenRouter default
"""
import sys
import shutil
from pathlib import Path
import json

from termpipe_mcp.settings import load_settings, save_settings
from termpipe_mcp.tools.surgical.reviewer import (
    register_reviewer,
)


def _load_api_keys() -> dict:
    """Load API keys — ~/.omniproxy/keys.json first, fallback ~/.termpipe-mcp/keys.json"""
    for p in [Path.home() / ".omniproxy" / "keys.json",
              Path.home() / ".termpipe-mcp" / "keys.json"]:
        if p.exists():
            try:
                data = json.loads(p.read_text())
                if data:
                    return data
            except Exception:
                pass
    return {}


def maybe_bootstrap():
    settings = load_settings()

    if not settings.get("is_first_run", True):
        _register_from_settings(settings)
        return

    backend, model = ("openrouter", None)
    settings["reviewer_backend"] = backend
    settings["reviewer_model"]   = model
    settings["is_first_run"]     = False
    save_settings(settings)
    _register_from_settings(settings)
    print(f"[termpipe] First-run bootstrap complete. Reviewer: {backend}", file=sys.stderr)


def _register_from_settings(settings: dict):
    """Register OpenRouter reviewer from ~/.omniproxy/keys.json."""
    backend = settings.get("reviewer_backend")

    # Migrate any legacy backend to openrouter
    if backend in ("omniproxy", "cliproxy", "iflow", "gemini-cli", "qwen-cli", "groq"):
        settings["reviewer_backend"] = "openrouter"
        settings["reviewer_model"] = None
        from termpipe_mcp.settings import save_settings
        save_settings(settings)

    # reviewer auto-detection runs lazily via _get_reviewer() in reviewer.py

