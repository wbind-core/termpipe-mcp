import subprocess
from mcp.server.fastmcp import FastMCP
from slimline.session import resolve_session_cwd


def register_tools(mcp: FastMCP):
    @mcp.tool()
    def codegraph_explore(query: str, project_path: str = None) -> str:
        """
        Explore the codebase using CodeGraph. Returns verbatim source code for relevant symbols.

        Args:
            query: Symbol names, file names, or a natural-language question.
            project_path: Optional absolute path to the project root. Defaults to the
                cwd published by the most recent list_tools call (resolved from the
                kb bus, topic termpipe.session<id>.cwd).
        """
        try:
            path = project_path
            if not path:
                # Resolve the active session cwd published by list_tools.
                # kb/import failure degrades to the old behavior (server cwd).
                try:
                    from slimline.agent_mode import KbClient
                    path = resolve_session_cwd(KbClient())
                except Exception:
                    path = None

            cmd = ["codegraph", "explore", query]
            if path:
                cmd.extend(["--path", path])

            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return res.stdout
        except subprocess.CalledProcessError as e:
            return f"[CodeGraph Error] Exit {e.returncode}\n{e.stderr}\n{e.stdout}"
        except Exception as e:
            return f"[Error] Failed to execute codegraph: {e}"
