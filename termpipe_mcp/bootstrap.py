"""
bootstrap.py — One-time provider detection + settings write.

Called once at server startup from server.py.
  - is_first_run=True  (or missing settings.json): probe 4-tier chain,
    write result to settings.json, set is_first_run=False
  - is_first_run=False: read saved backend, register directly, skip probing
"""
import sys
from termpipe_mcp.settings import load_settings, save_settings
from termpipe_mcp.tools.surgical.reviewer import (
    register_reviewer,
    _register_cliproxy,
    _register_iflow,
    _register_gemini_cli,
)

def maybe_bootstrap():
    settings = load_settings()

    if not settings.get("is_first_run", True):
        # Not first run — register from saved settings and return immediately
        _register_from_settings(settings)
        return

    # First run: probe, save, register
    backend, model = _probe_and_select(settings)
    settings["reviewer_backend"] = backend
    settings["reviewer_model"]   = model
    settings["is_first_run"]     = False
    save_settings(settings)

    if backend:
        _register_from_settings(settings)

    print(f"[termpipe] First-run bootstrap complete. Reviewer: {backend or 'none'}", file=sys.stderr)


def _probe_and_select(settings: dict) -> tuple:
    """Probe all four tiers. Return (backend_name, model_name) for first winner."""
    import httpx, shutil

    cliproxy_url = settings.get("cliproxy_url", "http://127.0.0.1:7599")
    iflow_url    = settings.get("iflow_url",    "http://127.0.0.1:8421")

    def probe(url):
        try:
            return httpx.get(f"{url}/health", timeout=2.0).status_code < 400
        except Exception:
            return False

    if probe(cliproxy_url):
        return "cliproxy", "auto"

    if probe(iflow_url):
        return "iflow", "qwen3-coder-plus"

    if shutil.which("gemini"):
        return "gemini-cli", settings.get("gemini_cli_model", "gemini-2.5-flash")

    return None, None


def _register_from_settings(settings: dict):
    """Register the saved backend with saved model/url config."""
    backend = settings.get("reviewer_backend")
    model   = settings.get("reviewer_model")

    if backend == "cliproxy":
        _register_cliproxy(url=settings.get("cliproxy_url", "http://127.0.0.1:7599"),
                           model=model or "auto")
    elif backend == "iflow":
        _register_iflow(model=model or "qwen3-coder-plus")
    elif backend == "gemini-cli":
        _register_gemini_cli(model=model or "gemini-2.5-flash")
    # None → no reviewer registered, gate passes through silently
