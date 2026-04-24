"""
TermF command execution tools for TermPipe MCP Server.
"""

import subprocess
from typing import Optional
from termpipe_mcp.helpers import api_post
from termpipe_mcp.tools.process import process_manager


def register_tools(mcp):
    """Register TermF tools with the MCP server."""
    
    @mcp.tool()
    def termf_exec(command: str, timeout_ms: Optional[int] = None, run_in_bg: bool = False) -> str:
        """
        Execute a shell command via TermPipe.
        
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
            "raw_command": command,  # Pass full command string, preserving heredocs
            "timeout": int(timeout)  # Pass timeout to server so it enforces it on the subprocess
        }, timeout=timeout + 5)  # httpx timeout slightly longer than subprocess timeout
        
        exit_code = result.get("exit_code", 0)
        duration = result.get("duration", 0.0)
        output = result.get("output", "") or ""
        error_output = result.get("error", "") or ""
        
        # Format the standardized response
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
                # Get --help output for context
                help_command = command.split(' ')[0] + ' --help'
                help_result = subprocess.run(help_command, shell=True, capture_output=True, text=True, timeout=5)
                help_output = help_result.stdout + help_result.stderr
                
                suggestion = analyze_and_suggest_fix(command, error_output or "Non-zero exit code", help_output)
                return f"{response}\\n[AI Suggestion]:{suggestion}"
            except Exception as e:
                return f"{response}\\n[Debug assist failed]: {e}"


    @mcp.tool()
    def live_exec(command: str, app: str = "hyper", timeout_ms: int = 30000, topic: str = "terminal.output") -> str:
        """
        Executes a command physically in the user's external terminal app and returns the output.
        
        Args:
            command: Shell command to inject (e.g. 'go build ./...')
            app: Terminal application to focus (default "hyper")
            timeout_ms: How long to wait for the command output on the bus, in ms
            topic: The bus topic to listen to (default "terminal.output")
        """
        import subprocess
        import shlex
        import json
        import os
        
        try:
            _kb = "/home/craig/.local/bin/kb"
            _cond = "/home/craig/.local/bin/cond"
            
            # 1. Get current sequence number
            seq_cmd = f"{_kb} get {shlex.quote(topic)} --json | jq -r '.seq // 0'"
            result = subprocess.run(seq_cmd, shell=True, capture_output=True, text=True)
            
            try:
                current_seq = int(result.stdout.strip())
            except ValueError:
                current_seq = 0
                
            # 2. Inject command natively into the GUI shell
            inject_cmd = f"{_cond} --launch {shlex.quote(app)},,--pause 3000,,--type {shlex.quote(command)},,--pause 200,,--key enter"
            subprocess.run(inject_cmd, shell=True, check=True)
            
            # 3. Poll for new output using raw socket command
            uid = os.getuid()
            sock_path = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{uid}") + "/kernclip-bus.sock"
            
            poll_req = json.dumps({
                "op": "poll",
                "topic": topic,
                "after_seq": current_seq,
                "timeout_ms": timeout_ms
            })
            
            poll_cmd = f"echo {shlex.quote(poll_req)} | socat - UNIX-CONNECT:{shlex.quote(sock_path)} | jq -r '.messages[].data // empty'"
            poll_result = subprocess.run(poll_cmd, shell=True, capture_output=True, text=True, timeout=timeout_ms / 1000.0 + 5)
            
            # 4. Return focus to original window context
            subprocess.run(f"{_cond} --focus-last", shell=True)
            
            if poll_result.returncode != 0:
                err_msg = poll_result.stderr.strip() if poll_result.stderr else poll_result.stdout.strip()
                return f"[Error from bus polling: {err_msg}]"
                
            return poll_result.stdout.strip() or "[No output found]"

        except subprocess.TimeoutExpired:
            subprocess.run("/home/craig/.local/bin/cond --focus-last", shell=True)
            return f"[Timeout waiting for {topic} after {timeout_ms}ms]"
        except Exception as e:
            subprocess.run("/home/craig/.local/bin/cond --focus-last", shell=True)
            return f"[Error executing live_exec: {str(e)}]"

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
