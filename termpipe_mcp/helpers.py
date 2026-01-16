"""
HTTP client and utility functions for TermPipe MCP.
"""

import os
import json
import httpx
from pathlib import Path
from typing import Dict, Any, Optional, Tuple


# Constants
HOME = Path.home()
TERMPIPE_MCP_DIR = HOME / ".termpipe-mcp"
THREAD_FILE = HOME / "claude-antig" / "thread.md"
CONFIG_FILE = TERMPIPE_MCP_DIR / "config.json"

# Legacy/compatibility constants (for tools that expect them)
TERMPIPE_DIR = HOME / ".termpipe"  # Original termpipe directory
CONFIG_PATH = CONFIG_FILE  # Alias for config file
LAUNCH_SCRIPTS_DIR = TERMPIPE_DIR / "launch_scripts"  # App launch scripts

# FastAPI server URL
TERMCP_URL = os.environ.get("TERMCP_URL", "http://localhost:8421")


def get_iflow_credentials() -> Tuple[str, str]:
    """
    Get iFlow API credentials from config files.
    
    Tries multiple locations in priority order:
    1. ~/.termpipe-mcp/config.json (new location)
    2. ~/.iflow/settings.json (iFlow settings)
    3. ~/.iflow/oauth_creds.json (iFlow OAuth)
    
    Returns:
        Tuple of (api_key, api_base)
        
    Raises:
        FileNotFoundError: If no credentials found in any location
    """
    # Try new TermPipe config first
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
            api_key = config.get('api_key')
            api_base = config.get('api_base', 'https://apis.iflow.cn/v1')
            if api_key:
                return api_key, api_base
        except Exception:
            pass
    
    # Try iFlow settings.json
    iflow_settings = HOME / ".iflow" / "settings.json"
    if iflow_settings.exists():
        try:
            with open(iflow_settings, 'r') as f:
                settings = json.load(f)
            api_key = settings.get('apiKey')
            api_base = settings.get('baseUrl', 'https://apis.iflow.cn/v1')
            if api_key:
                return api_key, api_base
        except Exception:
            pass
    
    # Try iFlow oauth_creds.json
    iflow_oauth = HOME / ".iflow" / "oauth_creds.json"
    if iflow_oauth.exists():
        try:
            with open(iflow_oauth, 'r') as f:
                oauth = json.load(f)
            api_key = oauth.get('apiKey')
            api_base = 'https://apis.iflow.cn/v1'  # Default for OAuth
            if api_key:
                return api_key, api_base
        except Exception:
            pass
    
    # No credentials found anywhere
    raise FileNotFoundError(
        "iFlow API credentials not found.\n\n"
        "Checked:\n"
        f"  • {CONFIG_FILE}\n"
        f"  • {iflow_settings}\n"
        f"  • {iflow_oauth}\n\n"
        "Configure credentials with: termcp setup"
    )



def api_post(endpoint: str, data: dict, timeout: float = 60.0) -> dict:
    """
    Make a POST request to the FastAPI server.
    
    Args:
        endpoint: API endpoint (e.g. "/exec", "/nlp")
        data: Request payload
        timeout: Request timeout in seconds
        
    Returns:
        Response dictionary with success/error status
    """
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(f"{TERMCP_URL}{endpoint}", json=data)
            if response.status_code == 200:
                return response.json()
            else:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {response.text}"
                }
    except httpx.ConnectError:
        return {
            "success": False,
            "error": f"Cannot connect to {TERMCP_URL}. Start the server with: termcp server"
        }
    except httpx.TimeoutException:
        return {
            "success": False,
            "error": f"Request timed out after {timeout}s"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Request failed: {str(e)}"
        }


def api_get(endpoint: str, params: dict = None, timeout: float = 30.0) -> dict:
    """
    Make a GET request to the FastAPI server.
    
    Args:
        endpoint: API endpoint
        params: Query parameters
        timeout: Request timeout in seconds
        
    Returns:
        Response dictionary with success/error status
    """
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(f"{TERMCP_URL}{endpoint}", params=params)
            if response.status_code == 200:
                return response.json()
            else:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {response.text}"
                }
    except httpx.ConnectError:
        return {
            "success": False,
            "error": f"Cannot connect to {TERMCP_URL}. Start the server with: termcp server"
        }
    except httpx.TimeoutException:
        return {
            "success": False,
            "error": f"Request timed out after {timeout}s"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Request failed: {str(e)}"
        }


def format_error(error_msg: str) -> str:
    """Format error message for display"""
    return f"❌ Error: {error_msg}"


def format_success(msg: str) -> str:
    """Format success message for display"""
    return f"✅ {msg}"
