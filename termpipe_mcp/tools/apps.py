"""
App launcher tools for TermPipe MCP Server.
"""

import subprocess
from pathlib import Path
from typing import Optional
from termpipe_mcp.helpers import LAUNCH_SCRIPTS_DIR, HOME


def register_tools(mcp):
    """Register app launcher tools with the MCP server."""
    
    @mcp.tool()
    def launch_app(app_name: str) -> str:
        """
        Launch an application via normalized launch script.
        
        Args:
            app_name: App name (e.g., "Firefox", "Claude", "Visual_Studio_Code")
        """
        script_path = LAUNCH_SCRIPTS_DIR / f"launch_{app_name}.sh"
        
        if not script_path.exists():
            for f in LAUNCH_SCRIPTS_DIR.glob("launch_*.sh"):
                if f.stem.lower() == f"launch_{app_name.lower()}":
                    script_path = f
                    break
        
        if not script_path.exists():
            return f"[Error: No launch script found for '{app_name}'. Use list_apps() to see available.]"
        
        try:
            result = subprocess.Popen(
                ["bash", str(script_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            return f"✅ Launched {app_name} (PID: {result.pid})"
        except Exception as e:
            return f"[Error: {str(e)}]"

    @mcp.tool()
    def list_apps(filter_term: Optional[str] = None) -> str:
        """
        List available launch scripts.
        
        Args:
            filter_term: Optional filter (e.g., "firefox", "code")
        """
        if not LAUNCH_SCRIPTS_DIR.exists():
            return "[No launch scripts directory found]"
        
        apps = []
        for f in sorted(LAUNCH_SCRIPTS_DIR.glob("launch_*.sh")):
            name = f.stem.replace("launch_", "")
            if filter_term is None or filter_term.lower() in name.lower():
                apps.append(name)
        
        if not apps:
            return "[No matching apps found]"
        
        total = len(apps)
        shown = apps[:50]
        
        output = f"📱 Available apps ({total} total):\n"
        output += "\n".join(f"  • {app}" for app in shown)
        
        if total > 50:
            output += f"\n  ... and {total - 50} more"
        
        return output
