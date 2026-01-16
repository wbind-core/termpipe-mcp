"""
WBind GUI automation tools for TermPipe MCP Server.
"""

import subprocess
from pathlib import Path
from termpipe_mcp.helpers import HOME


def register_tools(mcp):
    """Register WBind tools with the MCP server."""
    
    @mcp.tool()
    def wbind_action(actions: str) -> str:
        """
        Execute WBind GUI automation actions.
        
        Actions are comma-separated. Examples:
        - "mouseto 0.5 0.5,, click left" - Move to center, click
        - "key ctrl+c" - Copy
        - "type Hello World" - Type text
        
        Args:
            actions: Comma-separated WBind actions
        """
        try:
            result = subprocess.run(
                [str(HOME / ".local" / "bin" / "wbind"), actions],
                capture_output=True,
                text=True,
                timeout=30
            )
            return result.stdout or result.stderr or "[Done]"
        except FileNotFoundError:
            return "[Error: wbind not installed at ~/.local/bin/wbind]"
        except Exception as e:
            return f"[Error: {str(e)}]"

    @mcp.tool()
    def wbind_launch_and_focus(app_name: str, maximize: bool = True, fullscreen: bool = False) -> str:
        """
        Launch an app and bring it to a known state.
        
        Args:
            app_name: App name (e.g., "Firefox", "Claude")
            maximize: Whether to maximize the window
            fullscreen: Whether to make fullscreen with F11
        """
        try:
            LAUNCH_SCRIPTS_DIR = HOME / ".termpipe" / "installed_apps_launch_scripts"
            
            # Launch via script
            script_path = LAUNCH_SCRIPTS_DIR / f"launch_{app_name}.sh"
            if not script_path.exists():
                for f in LAUNCH_SCRIPTS_DIR.glob("launch_*.sh"):
                    if f.stem.lower() == f"launch_{app_name.lower()}":
                        script_path = f
                        break
            
            if not script_path.exists():
                return f"[Error: No launch script for '{app_name}']"
            
            subprocess.Popen(
                ["bash", str(script_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            
            import time
            time.sleep(1.5)
            
            actions = []
            if maximize:
                actions.append("key super+up")
            if fullscreen:
                actions.append("key F11")
            
            if actions:
                subprocess.run(
                    [str(HOME / ".local" / "bin" / "wbind"), ",, ".join(actions)],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
            
            status = f"Launched {app_name}"
            if maximize:
                status += " (maximized)"
            if fullscreen:
                status += " (fullscreen)"
            
            return status
            
        except Exception as e:
            return f"[Error: {str(e)}]"
