"""
settings.py — Persistent user settings (separate from API-key config).
File: <config_dir>/settings.json
"""
import json
from pathlib import Path
from termpipe_mcp.helpers import get_config_dir

SETTINGS_PATH = get_config_dir() / "settings.json"

DEFAULTS = {
    "is_first_run":      True,
    "reviewer_backend":  None,   # "cliproxy" | "iflow" | "gemini-cli" | None
    "reviewer_model":    None,   # "auto" | "gemini-2.5-flash" | "qwen3-coder-plus" | etc.
    "reviewer_timeout":  8.0,
    "cliproxy_url":      "http://127.0.0.1:7599",
    "iflow_url":         "http://127.0.0.1:8421",
    "gemini_cli_model":  "gemini-2.5-flash",
    "schema_version":    1,
}

def load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return dict(DEFAULTS)
    with open(SETTINGS_PATH) as f:
        data = json.load(f)
    return {**DEFAULTS, **data}   # fill any missing keys with defaults

def save_settings(settings: dict):
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)
    SETTINGS_PATH.chmod(0o600)

def get(key: str):
    return load_settings().get(key, DEFAULTS.get(key))

def set(key: str, value):
    s = load_settings()
    s[key] = value
    save_settings(s)
