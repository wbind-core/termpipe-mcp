"""
Process management tools for TermPipe MCP Server.
"""

import os
import subprocess
from datetime import datetime
from typing import Optional, Dict, Any


class ProcessManager:
    """Track running processes for interactive sessions (REPLs, background jobs)"""
    
    def __init__(self):
        self.processes: Dict[int, Dict[str, Any]] = {}
    
    def add(self, pid: int, proc: subprocess.Popen, command: str):
        self.processes[pid] = {
            "command": command,
            "process": proc,
            "started": datetime.now(),
            "blocked": True
        }
    
    def get(self, pid: int) -> Optional[Dict[str, Any]]:
        return self.processes.get(pid)
    
    def is_blocked(self, pid: int) -> bool:
        proc_info = self.get(pid)
        return proc_info.get("blocked", False) if proc_info else False
    
    def set_blocked(self, pid: int, blocked: bool):
        if pid in self.processes:
            self.processes[pid]["blocked"] = blocked
    
    def remove(self, pid: int):
        if pid in self.processes:
            del self.processes[pid]
    
    def list_all(self) -> list[dict]:
        result = []
        for pid, info in self.processes.items():
            proc = info["process"]
            result.append({
                "pid": pid,
                "command": info["command"],
                "started": info["started"].isoformat(),
                "running": proc.poll() is None,
                "blocked": info.get("blocked", False),
                "return_code": proc.returncode
            })
        return result
    
    def cleanup_finished(self):
        finished = [pid for pid, info in self.processes.items() 
                   if info["process"].poll() is not None]
        for pid in finished:
            self.remove(pid)


# Global instance
process_manager = ProcessManager()


def register_tools(mcp):
    """Register process management tools with the MCP server."""
    
    @mcp.tool()
    def list_sessions() -> str:
        """
        List all active terminal sessions (running processes).
        Shows session status including PID, blocked status, and runtime.
        """
        process_manager.cleanup_finished()
        sessions = process_manager.list_all()
        
        if not sessions:
            return "📭 No active sessions"
        
        output = f"🔵 Active Sessions ({len(sessions)}):\n\n"
        for s in sessions:
            status = "⏸️  Blocked" if s["blocked"] else "▶️  Running"
            output += f"  PID {s['pid']}: {s['command'][:40]}\n"
            output += f"       Status: {status} | Code: {s['return_code']}\n\n"
        
        return output

    @mcp.tool()
    def read_process_output(pid: int) -> str:
        """
        Read output from a running process (REPL/interactive session).
        """
        proc_info = process_manager.get(pid)
        if not proc_info:
            return f"[Error: No session found with PID {pid}]"
        
        proc = proc_info["process"]
        poll_result = proc.poll()
        if poll_result is not None:
            process_manager.remove(pid)
            stdout = proc.stdout.read() if proc.stdout else ""
            return f"✅ Process finished (exit code: {poll_result})\n\n{stdout}"
        
        try:
            import fcntl
            stdout = proc.stdout
            if stdout:
                flags = fcntl.fcntl(stdout.fileno(), fcntl.F_GETFL)
                fcntl.fcntl(stdout.fileno(), fcntl.F_SETFL, flags | os.O_NONBLOCK)
                
                try:
                    output = stdout.read()
                    if output:
                        process_manager.set_blocked(pid, False)
                        return f"📤 Output:\n{output.decode() if isinstance(output, bytes) else output}"
                except BlockingIOError:
                    pass
                
                process_manager.set_blocked(pid, True)
                return f"⏳ Process {pid} is waiting for input (REPL prompt detected)"
            
            return f"⏳ Process {pid} running (no stdout available)"
            
        except Exception as e:
            return f"[Error reading output: {str(e)}]"

    @mcp.tool()
    def interact_with_process(pid: int, input: str) -> str:
        """
        Send input to a running process (REPL, interactive shell, etc).
        """
        proc_info = process_manager.get(pid)
        if not proc_info:
            return f"[Error: No session found with PID {pid}]"
        
        proc = proc_info["process"]
        
        if proc.poll() is not None:
            process_manager.remove(pid)
            return f"[Error: Process {pid} is no longer running]"
        
        try:
            if proc.stdin:
                proc.stdin.write(input)
                if not input.endswith("\n"):
                    proc.stdin.write("\n")
                proc.stdin.flush()
            
            process_manager.set_blocked(pid, True)
            return f"📤 Sent to PID {pid}:\n{input}\n\n💡 Use read_process_output({pid}) to see response"
            
        except BrokenPipeError:
            process_manager.remove(pid)
            return f"[Error: Process {pid} stdin closed]"
        except Exception as e:
            return f"[Error: {str(e)}]"

    @mcp.tool()
    def force_terminate(pid: int) -> str:
        """Force terminate a running process by PID."""
        proc_info = process_manager.get(pid)
        if not proc_info:
            try:
                os.kill(pid, 9)
                return f"✅ Killed process {pid} (was not tracked)"
            except ProcessLookupError:
                return f"[Error: No process found with PID {pid}]"
            except Exception as e:
                return f"[Error: {str(e)}]"
        
        try:
            proc = proc_info["process"]
            proc.kill()
            process_manager.remove(pid)
            return f"✅ Terminated process {pid}"
        except Exception as e:
            return f"[Error: {str(e)}]"

    @mcp.tool()
    def list_processes() -> str:
        """List all running processes (system-wide)."""
        try:
            proc = subprocess.run(
                ["ps", "aux", "--sort=-%mem"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            lines = proc.stdout.strip().split("\n")
            output = "🖥️  System Processes (sorted by memory):\n\n"
            output += "\n".join(lines[:51])
            
            if len(lines) > 51:
                output += f"\n... and {len(lines) - 51} more (use 'ps aux' for full list)"
            
            return output
            
        except Exception as e:
            return f"[Error listing processes: {str(e)}]"
