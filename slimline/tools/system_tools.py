import os
import re
import subprocess
import sys
from pathlib import Path
from mcp.server.fastmcp import FastMCP

def _trim_explore_output(raw_text: str, max_lines: int = 40) -> str:
    """
    Trims verbose CodeGraph explore output for small/local model context windows:
    - Removes boilerplate warning blockquotes
    - Caps overall lines so it doesn't blow token limits
    """
    # Remove the standard CodeGraph verbatim warning blockquote
    cleaned = re.sub(r"> The code below is the \*\*verbatim.*?\n\n", "", raw_text, flags=re.DOTALL).strip()
    
    lines = cleaned.splitlines()
    if len(lines) > max_lines:
        trimmed = "\n".join(lines[:max_lines])
        return f"{trimmed}\n\n... [explore preview trimmed ({len(lines) - max_lines} lines hidden); call codegraph_explore for full verbatim source]"
    return cleaned

def register_tools(mcp: FastMCP):
    @mcp.tool()
    def list_tools(cwd: str = None) -> str:
        """
        List all available tools in the slimline MCP server.
        Also initializes or updates CodeGraph indexing in the specified directory,
        and provides an orientation exploration summary of the codebase.
        
        Args:
            cwd: Project root directory to index with CodeGraph. Defaults to current directory.
        """
        if not cwd:
            cwd = os.environ.get("PWD") or os.getcwd()
            
        output_parts = []
        target_path = Path(cwd).resolve()
        
        # Guard against accidentally indexing the filesystem root
        if str(target_path) == "/":
            output_parts.append("ℹ️ Skipped CodeGraph indexing: current working directory is root ('/'). Pass a project path to index.")
        else:
            codegraph_dir = target_path / ".codegraph"
            index_succeeded = False
            
            # 1. Init or Index
            try:
                if not codegraph_dir.exists():
                    output_parts.append(f"Initializing CodeGraph in {target_path}...")
                    res = subprocess.run(
                        ["codegraph", "init", str(target_path)],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                else:
                    output_parts.append(f"Updating CodeGraph index in {target_path}...")
                    res = subprocess.run(
                        ["codegraph", "index", str(target_path)],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )

                if res.returncode == 0:
                    index_succeeded = True
                    out = res.stdout.strip()
                    if out:
                        output_parts.append(out)
                    else:
                        output_parts.append("✅ CodeGraph index ready.")
                else:
                    err = res.stderr.strip() or res.stdout.strip()
                    output_parts.append(f"⚠️ CodeGraph warning: {err}")
            except Exception as e:
                output_parts.append(f"⚠️ CodeGraph operation failed: {e}")

            # 2. Automated CodeGraph Explore Orientation
            if index_succeeded:
                try:
                    explore_res = subprocess.run(
                        [
                            "codegraph",
                            "explore",
                            "main entry point core architecture workflow",
                            "--path", str(target_path),
                            "--max-files", "2"
                        ],
                        capture_output=True,
                        text=True,
                        timeout=15
                    )
                    if explore_res.returncode == 0 and explore_res.stdout.strip():
                        trimmed_summary = _trim_explore_output(explore_res.stdout.strip(), max_lines=45)
                        output_parts.append("\nCodebase Orientation Preview:")
                        output_parts.append(trimmed_summary)
                except Exception as e:
                    output_parts.append(f"(Automated exploration skipped: {e})")

        # 2b. Agent workspace mode (kb-backed standing autonomy policy).
        # The probe may block for the configured decision window when a
        # brand-new workspace needs its mode selected.
        if str(target_path) != "/":
            try:
                from slimline.agent_mode import KbClient, probe
                output_parts.append("\n" + probe(KbClient(), str(target_path)))
            except Exception as e:
                output_parts.append(
                    "\nAgent Workspace Mode:\n"
                    f"- note: probe failed ({e}); fail closed to Full HITL."
                )

        # 2c. Workspace resume + phase briefing (mirrors termpipe system.py).
        # Rehydrates kb artifacts for this cwd and appends the tactical
        # briefing fragment; also starts the session-approve listener.
        # Zero-cost when no workspace exists or the bus is down.
        if str(target_path) != "/":
            try:
                _tp_root = "/home/craig/termpipe-mcp"
                if _tp_root not in sys.path:
                    sys.path.insert(0, _tp_root)
                from termpipe_mcp.tools.workspace._artifacts import workspace_resume
                from termpipe_mcp.tools.workspace._phase import (
                    phase_briefing, ws_id_from_cwd, _start_session_approve_listener,
                )
                workspace_resume(str(target_path))
                _ws_id = ws_id_from_cwd(str(target_path))
                if _ws_id:
                    output_parts.append(phase_briefing(_ws_id))
                    _start_session_approve_listener(_ws_id, project_name=target_path.name)
            except Exception as e:
                output_parts.append(f"(workspace resume skipped: {e})")

        # 2d. Session memory (context-core slice). list_tools is the semantic
        # resume trigger: touch the cwd-scoped session and append the
        # significance-ranked resume briefing. Zero-cost on failure.
        if str(target_path) != "/":
            try:
                from slimline.tools import session_memory
                session_memory.touch_session(str(target_path))
                _brief = session_memory.briefing(str(target_path))
                if _brief:
                    output_parts.append("\n" + _brief)
            except Exception as e:
                output_parts.append(f"(session memory skipped: {e})")

        # 3. List tools dynamically from FastMCP router
        output_parts.append("\nAvailable Tools:")
        try:
            tools_dict = mcp._tool_manager._tools
            for name, tool_obj in sorted(tools_dict.items()):
                doc = ""
                if hasattr(tool_obj, "fn") and tool_obj.fn.__doc__:
                    doc = tool_obj.fn.__doc__.strip().split('\n')[0]
                output_parts.append(f"- {name}: {doc}")
        except Exception as e:
            output_parts.append(f"(Failed to introspect tools: {e})")
            
        return "\n".join(output_parts)
