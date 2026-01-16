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
    Get iFlow API credentials from config file.
    
    Returns:
        Tuple of (api_key, api_base)
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        KeyError: If required keys are missing
    """
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"Config file not found: {CONFIG_FILE}\n"
            "Run 'termcp setup' to configure iFlow API credentials"
        )
    
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
    
    api_key = config.get('api_key')
    api_base = config.get('api_base', 'https://apis.iflow.cn/v1')
    
    if not api_key:
        raise KeyError(
            "api_key not found in config file\n"
            "Run 'termcp setup' to configure iFlow API credentials"
        )
    
    return api_key, api_base


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
