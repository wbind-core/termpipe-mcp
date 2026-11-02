import subprocess
from typing import Optional
from mcp.server.fastmcp import FastMCP

try:
    from . import guard
except ImportError:  # direct module load outside the package
    from slimline.tools import guard


# Craig's ~/.local/bin is not on the non-interactive PATH that `kb exec`
# uses, so his canonical binaries (kb, kc, wput, cond, pwm, ...) would not
# resolve without absolute paths. Prepend it for every command — this matches
# the PATH ordering of his interactive shells. The guard screens the original
# command string before wrapping, so gating is unaffected.
_USER_BIN = "/home/craig/.local/bin"


def _with_user_bin(command: str) -> str:
    return f'export PATH="{_USER_BIN}:$PATH"; {command}'


def register_tools(mcp: FastMCP):
    @mcp.tool()
    def termf_exec(command: str, timeout_ms: Optional[int] = None,
                   override_id: Optional[str] = None) -> str:
        """
        Execute a shell command via TermPipe (synchronous only).

        Craig's ~/.local/bin is prepended to PATH automatically, so his
        canonical binaries (kb, kc, wput, cond, pwm, ...) resolve without
        absolute paths.

        Dangerous commands (rm and peers — see tools/guard.py) are gated:
        they block on a kb notification approval from Craig (Approve Once /
        Reject Once, 120s window, fail closed). A denial returns a
        [Guard: ...] message and the command is never run — do not retry
        it or work around the gate; surface it to Craig instead.

        When Craig is away from his desk, use the chat-routed override:
        file request_override with the denial's request id and a reason,
        ask him in chat for `approve <id>` / `deny <id>`, record his reply
        with resolve_override, then re-invoke with the IDENTICAL command and
        override_id set. The guard verifies the exact command match and a
        recorded chat approval, consumes it one-shot, and runs the command.

        Args:
            command: Shell command to execute
            timeout_ms: Optional timeout in milliseconds (not natively supported by kb exec yet, but provided for compat)
            override_id: Optional override id from a chat-approved request_override (exact-command match required)
        """
        denial = guard.gate(command, override_id=override_id)

        if denial is not None:
            return denial
        try:
            res = subprocess.run(["kb", "exec", _with_user_bin(command)], capture_output=True, text=True, check=True)
            return res.stdout
        except subprocess.CalledProcessError as e:
            return f"[Command Failed] Exit code: {e.returncode}\nStdout: {e.stdout}\nStderr: {e.stderr}"
        except Exception as e:
            return f"[Execution Error]: {e}"
