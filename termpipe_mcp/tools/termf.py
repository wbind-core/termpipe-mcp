"""
TermF command execution tools for TermPipe MCP Server.
Complete HSP-integrated terminal automation with event-driven execution.
"""

import subprocess
import shlex
import re
import time
import asyncio
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from pathlib import Path

from termpipe_mcp.helpers import api_post
from termpipe_mcp.tools.process import process_manager

import live_exec as _live_exec


@dataclass
class TerminalSession:
    """Represents an active terminal session with bus topics."""
    session_id: str
    terminal_type: str
    pid: int
    start_time: float
    last_command: str = ""
    last_output: str = ""


class TerminalOrchestrator:
    """
    Event-driven terminal automation using cond's native subscription system.
    
    This replaces polling loops with cond's built-in --sub-window blocking waits.
    """
    
    def __init__(self):
        self._cond = "/home/craig/.local/bin/cond"
        self._kb = "/home/craig/.local/bin/kb"
        self._active_sessions: Dict[str, TerminalSession] = {}
        
    def _strip_ansi(self, text: str) -> str:
        """Remove ANSI escape codes from terminal output."""
        return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
    
    def _kb_get(self, topic: str, timeout_ms: int = 1000) -> str:
        """Get latest message from kb bus topic."""
        try:
            result = subprocess.run(
                [self._kb, "get", topic, "--timeout", str(timeout_ms), "--data-only"],
                capture_output=True, text=True, timeout=timeout_ms/1000 + 0.5
            )
            return self._strip_ansi(result.stdout.strip())
        except Exception:
            return ""
    
    def launch_terminal(self, terminal: str = "kitty", workspace_dir: Optional[str] = None) -> bool:
        """
        Launch a terminal emulator using cond.
        
        Args:
            terminal: Terminal emulator (kitty, wezterm, gnome-terminal)
            workspace_dir: Optional working directory to launch in
            
        Returns:
            True if launched successfully
        """
        launch_cmd = f"{self._cond} --launch {terminal}"
        if workspace_dir:
            # Kitty supports --directory flag
            if terminal == "kitty":
                launch_cmd = f"{self._cond} --launch {terminal} --directory {shlex.quote(workspace_dir)}"
            elif terminal == "wezterm":
                launch_cmd = f"{self._cond} --launch {terminal} start --cwd {shlex.quote(workspace_dir)}"
        
        result = subprocess.run(launch_cmd, shell=True, capture_output=True)
        return result.returncode == 0
    
    def wait_for_terminal_focus(self, terminal: str, timeout_ms: int = 5000) -> bool:
        """
        Block until terminal window is focused using cond's --sub-window.
        
        This is the key event-driven improvement over polling.
        """
        try:
            # cond --sub-window blocks until a window focus event occurs
            # --match filters to our terminal
            wait_cmd = f"{self._cond} --sub-window --match {terminal} --timeout {timeout_ms}"
            result = subprocess.run(wait_cmd, shell=True, capture=True, timeout=timeout_ms/1000 + 1)
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False
    
    def send_command(self, command: str, pre_pause_ms: int = 300) -> bool:
        """
        Send a command to the focused terminal using cond.
        
        Args:
            command: Shell command to execute
            pre_pause_ms: Pause before typing (ms)
            
        Returns:
            True if sent successfully
        """
        # Clear any existing prompt cruft first
        subprocess.run([self._cond, "--key", "ctrl+c"], capture_output=True, check=False)
        time.sleep(0.05)
        
        # Build injection sequence using pipe syntax
        inject = (
            f"{self._cond} --type {shlex.quote(command)}"
            f",,--pause {pre_pause_ms}"
            f",,--key enter"
        )
        result = subprocess.run(inject, shell=True, capture_output=True)
        return result.returncode == 0
    
    def get_command_output(self, timeout_ms: int = 5000) -> str:
        """
        Retrieve command output from kb bus topics.
        
        Reads both terminal.commands (echoed command) and terminal.output
        """
        cmd_echo = self._kb_get("terminal.commands", timeout_ms)
        term_out = self._kb_get("terminal.output", timeout_ms)
        
        parts = []
        if cmd_echo:
            parts.append(f"$ {cmd_echo}")
        if term_out:
            parts.append(term_out)
        
        return "\n".join(parts) if parts else "[No output on bus]"
    
    def execute_live(self, command: str, terminal: str = "kitty", 
                     timeout_ms: int = 30000, workspace_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Complete live terminal execution with event-driven flow.
        
        This is the main entry point for HSP terminal automation.
        
        Args:
            command: Shell command to execute
            terminal: Terminal emulator to use
            timeout_ms: Maximum time to wait for completion
            workspace_dir: Optional working directory
            
        Returns:
            Dict with success, output, duration, and session metadata
        """
        start_time = time.time()
        session_id = f"term_{int(start_time * 1000)}"
        
        try:
            # Step 1: Launch terminal (--launch focuses existing instance or creates new one)
            if not self.launch_terminal(terminal, workspace_dir):
                return {
                    "success": False,
                    "error": f"Failed to launch {terminal}",
                    "output": "",
                    "duration": time.time() - start_time,
                    "session_id": session_id
                }
            time.sleep(0.2)  # Brief pause for window focus
            
            # Step 2: Event-driven wait for terminal focus
            if not self.wait_for_terminal_focus(terminal, 5000):
                return {
                    "success": False,
                    "error": f"{terminal} window not focused within 5 seconds",
                    "output": "",
                    "duration": time.time() - start_time,
                    "session_id": session_id
                }
            
            # Step 3: Send the command
            if not self.send_command(command):
                return {
                    "success": False,
                    "error": "Failed to send command to terminal",
                    "output": "",
                    "duration": time.time() - start_time,
                    "session_id": session_id
                }
            
            # Step 4: Wait for command to start producing output
            time.sleep(0.5)
            
            # Step 5: Collect output (non-blocking, returns whatever is available)
            output = self.get_command_output(min(timeout_ms, 5000))
            
            # Record session
            self._active_sessions[session_id] = TerminalSession(
                session_id=session_id,
                terminal_type=terminal,
                pid=0,  # Would need to track actual PID
                start_time=start_time,
                last_command=command,
                last_output=output
            )
            
            return {
                "success": True,
                "error": None,
                "output": output,
                "duration": time.time() - start_time,
                "session_id": session_id,
                "command": command,
                "terminal": terminal
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "output": "",
                "duration": time.time() - start_time,
                "session_id": session_id
            }
    
    def get_session_output(self, session_id: str) -> Optional[str]:
        """Get latest output for a session."""
        session = self._active_sessions.get(session_id)
        if not session:
            return None
        
        output = self._kb_get("terminal.output", 2000)
        session.last_output = output
        return output
    
    def list_sessions(self) -> List[Dict[str, Any]]:
        """List all active terminal sessions."""
        return [
            {
                "session_id": s.session_id,
                "terminal": s.terminal_type,
                "last_command": s.last_command[:50] + "..." if len(s.last_command) > 50 else s.last_command,
                "start_time": s.start_time,
                "age_seconds": time.time() - s.start_time
            }
            for s in self._active_sessions.values()
        ]


# Global orchestrator instance
_terminator = None

def get_terminator() -> TerminalOrchestrator:
    """Get or create the global terminal orchestrator."""
    global _terminator
    if _terminator is None:
        _terminator = TerminalOrchestrator()
    return _terminator


def register_tools(mcp):
    """Register TermF tools with the MCP server."""
    
    @mcp.tool()
    def termf_exec(command: str, timeout_ms: Optional[int] = None, run_in_bg: bool = False) -> str:
        """
        Execute a shell command via TermPipe (existing method, preserved).
        
        Args:
            command: Shell command to execute
            timeout_ms: Optional timeout in milliseconds
            run_in_bg: Run in background and return PID
        """
        if command.strip().startswith("sudo ") and "sudo -S" not in command:
            command = f"echo 'bon' | sudo -S {command.strip()[5:]}"
            
        timeout = timeout_ms / 1000.0 if timeout_ms else 120.0

        if run_in_bg:
            try:
                proc = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE,
                    start_new_session=True
                )
                process_manager.add(proc.pid, proc, command)
                return f"🚀 Started process {proc.pid} in background\n💡 Use list_sessions() to check status"
            except Exception as e:
                return f"[Error starting background process: {str(e)}]"

        result = api_post("/exec", {
            "command": "exec",
            "args": [],
            "raw_command": command,
            "timeout": int(timeout)
        }, timeout=timeout + 5)
        
        exit_code = result.get("exit_code", 0)
        duration = result.get("duration", 0.0)
        output = result.get("output", "") or ""
        error_output = result.get("error", "") or ""
        
        status = "Success" if result.get("success") else "Failed"
        response = f"Status: {status} (Exit Code: {exit_code})\\n"
        response += f"Duration: {duration:.4f}s\\n"
        response += f"Command: {command}\\n"
        
        if output.strip():
            response += f"Output:\\n{output}\\n"
        else:
            response += "Output: [No stdout]\\n"

        if error_output.strip():
            response += f"Error:\\n{error_output}\\n"

        if result.get("success"):
            return response
        else:
            try:
                from termpipe_mcp.tools.debug import analyze_and_suggest_fix
                help_command = command.split(' ')[0] + ' --help'
                help_result = subprocess.run(help_command, shell=True, capture_output=True, text=True, timeout=5)
                help_output = help_result.stdout + help_result.stderr
                
                suggestion = analyze_and_suggest_fix(command, error_output or "Non-zero exit code", help_output)
                return f"{response}\\n[AI Suggestion]:{suggestion}"
            except Exception as e:
                return f"{response}\\n[Debug assist failed]: {e}"

    @mcp.tool()
    def termf_live_exec(command: str, app_name: str = "Ghostty", timeout_ms: Optional[int] = None) -> str:
        """
        Inject a command into a live GUI terminal (Ghostty by default) via the
        canonical live_exec pipeline: apps (focus-or-launch) -> kb copy ->
        cond --text-type "$(kb paste)" -> kb wait terminal.output -> kb copy history.

        Blocks until the command's output has been captured off the kb bus, then
        returns that output directly as this tool's result.

        Args:
            command:    Shell command to inject into the terminal
            app_name:   App to focus-or-launch via `apps` (default: Ghostty)
            timeout_ms: Optional max wait for output on the kb bus (default: no timeout)

        Returns:
            Captured command output from the kb bus (blocking)
        """
        try:
            output = _live_exec.send_command(
                command,
                app_name=app_name,
                wait_timeout_ms=timeout_ms,
            )
        except Exception as e:
            return f"❌ termf_live_exec failed: {str(e)}"

        if not output:
            return f"⚠️ Injected into {app_name} but no output captured on kb bus:\n$ {command}"

        return f"$ {command}\n\n{output}"

#     @mcp.tool()
#     def termf_live_continue(session_id: str, command: str) -> str:
#         """
#         Execute another command in an existing terminal session.
#         
#         Args:
#             session_id: Session ID from termf_live_exec
#             command: Next command to execute
#         
#         Returns:
#             Command output
#         """
#         terminator = get_terminator()
#         session = terminator._active_sessions.get(session_id)
#         
#         if not session:
#             return f"❌ Session {session_id} not found. Use termf_list_sessions() to see active sessions."
#         
#         # Focus the terminal
#         focus_cmd = f"{terminator._cond} --launch {session.terminal_type}"
#         subprocess.run(focus_cmd, shell=True, capture_output=True)
#         time.sleep(0.1)
#         
#         # Send command
#         if not terminator.send_command(command):
#             return f"❌ Failed to send command to session {session_id}"
#         
#         time.sleep(0.3)
#         output = terminator.get_command_output(5000)
#         
#         session.last_command = command
#         session.last_output = output
#         
#         return f"""📋 Command output for session {session_id}
# $ {command}
# 
# {output if output else '[No output produced]'}"""
# 
#     @mcp.tool()
#     def termf_live_output(session_id: Optional[str] = None) -> str:
#         """
#         Retrieve latest output from a terminal session.
#         
#         Args:
#             session_id: Optional session ID. If omitted, returns most recent output.
#         
#         Returns:
#             Latest terminal output
#         """
#         terminator = get_terminator()
#         
#         if session_id:
#             output = terminator.get_session_output(session_id)
#             if output is None:
#                 return f"❌ Session {session_id} not found"
#             return output if output else "[No output available]"
#         
#         # Return most recent output from kb bus
#         return terminator._kb_get("terminal.output", 2000) or "[No output on bus]"
# 
#     @mcp.tool()
#     def termf_list_sessions() -> str:
#         """List all active terminal sessions."""
#         terminator = get_terminator()
#         sessions = terminator.list_sessions()
#         
#         if not sessions:
#             return "No active terminal sessions."
#         
#         result = "📱 Active Terminal Sessions:\n\n"
#         for s in sessions:
#             result += f"  🔹 {s['session_id']}\n"
#             result += f"     Terminal: {s['terminal']}\n"
#             result += f"     Last command: {s['last_command']}\n"
#             result += f"     Age: {s['age_seconds']:.0f}s\n\n"
#         
#         result += "💡 Use termf_live_continue('<session_id>', 'command') to run more commands"
#         return result
# 
    @mcp.tool()
    def termf_nlp(instruction: str) -> str:
        """
        Execute NLP command via TermPipe. Translates natural language to CLI.
        
        Args:
            instruction: Natural language instruction
        """
        result = api_post("/nlp", {"query": instruction})
        
        if result.get("success"):
            output = result.get("output", "")
            metadata = result.get("metadata", {})
            
            if metadata.get("command_executed"):
                output = f"🎯 Command: {metadata['command_executed']}\n\n{output}"
            
            suggestions = result.get("suggestions", [])
            if suggestions:
                output += "\n\n💡 Suggestions:\n" + "\n".join(f"   • {s}" for s in suggestions[:3])
            
            return output or "[No output]"
        else:
            return f"[Error: {result.get('error', 'Unknown error')}]"

    @mcp.tool()
    def termf_nlp_alias(description: str) -> str:
        """
        Generate and install a shell alias/function from natural language.
        
        Args:
            description: What the alias should do
        """
        gen_result = api_post("/alias/generate", {"description": description})
        
        if not gen_result.get("success"):
            return f"[Error generating: {gen_result.get('error', 'Unknown error')}]"
        
        code = gen_result.get("code", "")
        
        save_result = api_post("/alias/save", {"code": code})
        
        if save_result.get("success"):
            return f"✅ Function generated and saved!\n\n{code}\n\n💡 Run 'source ~/.bashrc_functions' to use"
        else:
            return f"Generated but failed to save:\n\n{code}\n\n[Error: {save_result.get('error')}]"

#     @mcp.tool()
#     def termf_hsp_pipeline(command: str, task_description: str, 
#                            terminal: str = "kitty", max_loops: int = 3) -> str:
#         """
#         Run command through HSP micro-pipeline for automatic error correction.
#         
#         This implements the full 1-2-3-4 HSP pattern:
#         1. Execute command in terminal
#         2. Analyze output for errors
#         3. Suggest and apply fixes
#         4. Re-execute and verify
#         5. Loop until success or max_loops
#         
#         Args:
#             command: Initial command to try
#             task_description: What the command is supposed to do (for error context)
#             terminal: Terminal emulator to use
#             max_loops: Maximum repair attempts
#         
#         Returns:
#             Success/failure with full execution history
#         """
#         terminator = get_terminator()
#         history = []
#         current_command = command
#         
#         for loop in range(max_loops):
#             # Execute the command
#             result = terminator.execute_live(current_command, terminal, 60000)
#             history.append({
#                 "loop": loop + 1,
#                 "command": current_command,
#                 "output": result["output"],
#                 "success": result["success"]
#             })
#             
#             if result["success"] and not result["error"]:
#                 # Parse output to check for implicit failures (error messages, non-zero exit indicators)
#                 output_lower = result["output"].lower()
#                 has_error_indicators = any(
#                     indicator in output_lower 
#                     for indicator in ["error:", "failed:", "exception:", "traceback", "command not found"]
#                 )
#                 
#                 if not has_error_indicators:
#                     return f"""✅ HSP Pipeline succeeded after {loop + 1} loop(s)
# 
# Final command: {current_command}
# 
# Execution history:
# {chr(10).join(f"  Loop {h['loop']}: {h['command'][:60]}{'...' if len(h['command']) > 60 else ''} → {'✅' if h['success'] else '❌'}" for h in history)}
# 
# Full output:
# {result['output']}"""
#             
#             # If we failed or have error indicators, attempt repair
#             if loop < max_loops - 1:
#                 # Use analyst to diagnose and suggest fix
#                 analyst_prompt = f"""
# Task: {task_description}
# Command attempted: {current_command}
# Output/Error: {result['output'][:2000]}
# 
# Analyze the error and suggest a corrected command.
# Return ONLY the corrected shell command, no explanation.
# """
#                 # This would call an LLM for analysis - simplified for now
#                 # In production, this would use HSP's analyst model
#                 suggested_fix = result["output"][:500]  # Placeholder
#                 current_command = f"{current_command} 2>&1 | tee /tmp/fix.log"  # Placeholder
#             
#         return f"""⚠️ HSP Pipeline exhausted after {max_loops} loops
# 
# Last attempt: {current_command}
# Output: {history[-1]['output'][:1000] if history[-1]['output'] else '[No output]'}
# 
# Consider manual intervention or termf_live_exec for interactive debugging."""