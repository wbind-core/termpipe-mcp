"""
Git tools for TermPipe MCP Server.

Provides model-friendly access to git history, diffs, status, and blame
without requiring termf_exec. All tools operate on an explicit repo path
so they work correctly across multi-repo environments.
"""

import subprocess
from pathlib import Path
from typing import Optional


def _git(args: list[str], cwd: str) -> tuple[str, str, int]:
    """Run a git command. Returns (stdout, stderr, returncode)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(Path(cwd).expanduser().resolve()),
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.stdout, result.stderr, result.returncode
    except FileNotFoundError:
        return "", "git not found in PATH", 1
    except subprocess.TimeoutExpired:
        return "", "git command timed out after 15s", 1
    except Exception as e:
        return "", str(e), 1


def register_tools(mcp):

    @mcp.tool()
    def git_log(
        cwd: str,
        n: int = 20,
        branch: Optional[str] = None,
        path: Optional[str] = None,
        oneline: bool = False,
    ) -> str:
        """
        Show git commit history for a repository.

        Returns the last N commits with hash, author, date, and message.
        Optionally filter by branch or file path.

        Use this instead of termf_exec when you need to inspect commit
        history, understand recent changes, or find when something was
        introduced.

        Args:
            cwd:     Absolute path to the git repository root.
            n:       Number of commits to show (default: 20).
            branch:  Branch or ref to show history for (default: current branch).
            path:    If given, show only commits that touched this file/dir.
            oneline: If True, compact one-line-per-commit format.
        """
        fmt = "%h  %ad  %an  %s" if not oneline else "%h %s"
        args = ["log", f"-{n}", f"--format={fmt}", "--date=short"]
        if branch:
            args.append(branch)
        if path:
            args += ["--", path]

        stdout, stderr, rc = _git(args, cwd)
        if rc != 0:
            return f"[git_log error] {stderr.strip()}"
        if not stdout.strip():
            return "No commits found."

        header = f"git log -{n}"
        if branch:
            header += f" {branch}"
        if path:
            header += f" -- {path}"
        return f"📋 {header}\n{'=' * 60}\n{stdout.rstrip()}"

    @mcp.tool()
    def git_diff(
        cwd: str,
        ref: Optional[str] = None,
        ref2: Optional[str] = None,
        path: Optional[str] = None,
        staged: bool = False,
        stat_only: bool = False,
    ) -> str:
        """
        Show git diff — working tree, staged changes, or between commits/branches.

        Decision guide:
          • Unstaged working-tree changes  → git_diff(cwd)
          • Staged (index) changes         → git_diff(cwd, staged=True)
          • Since a specific commit/tag    → git_diff(cwd, ref="abc1234")
          • Between two commits/branches   → git_diff(cwd, ref="main", ref2="feature/x")
          • Just the changed file list     → git_diff(cwd, stat_only=True)
          • Diff of one file               → git_diff(cwd, path="src/foo.py")

        Output is truncated at 8000 chars. Use path= to narrow scope if needed.

        Args:
            cwd:       Absolute path to the git repository root.
            ref:       Base commit, tag, or branch.
            ref2:      Second ref for ref-to-ref comparison.
            path:      Limit diff to this file or directory.
            staged:    If True, show staged (--cached) diff.
            stat_only: If True, show --stat summary only.
        """
        args = ["diff"]
        if stat_only:
            args.append("--stat")
        if staged:
            args.append("--cached")
        if ref and ref2:
            args += [ref, ref2]
        elif ref:
            args.append(ref)
        if path:
            args += ["--", path]

        stdout, stderr, rc = _git(args, cwd)
        if rc != 0:
            return f"[git_diff error] {stderr.strip()}"
        if not stdout.strip():
            return "✅ No differences found."

        output = stdout
        LIMIT = 8000
        if len(output) > LIMIT:
            output = output[:LIMIT] + f"\n\n... [truncated — {len(stdout) - LIMIT} more chars. Use path= to narrow scope.]"

        label_parts = ["git diff"]
        if staged: label_parts.append("--cached")
        if ref: label_parts.append(ref)
        if ref2: label_parts.append(ref2)
        if path: label_parts += ["--", path]
        return f"🔀 {' '.join(label_parts)}\n{'=' * 60}\n{output.rstrip()}"

    @mcp.tool()
    def git_status(cwd: str) -> str:
        """
        Show working tree status — modified, staged, untracked files.

        Quick overview of what's changed since the last commit. Faster
        and more readable than git_diff for a high-level picture.

        Args:
            cwd: Absolute path to the git repository root.
        """
        stdout, stderr, rc = _git(["status", "--short", "--branch"], cwd)
        if rc != 0:
            return f"[git_status error] {stderr.strip()}"
        return f"📊 git status\n{'=' * 60}\n{stdout.rstrip()}" if stdout.strip() else "✅ Working tree clean."

    @mcp.tool()
    def git_show(
        cwd: str,
        ref: str,
        path: Optional[str] = None,
        stat_only: bool = False,
    ) -> str:
        """
        Show the full diff and metadata for a specific commit.

        Use this after git_log to drill into what a particular commit changed.

        Args:
            cwd:       Absolute path to the git repository root.
            ref:       Commit hash, tag, or ref (e.g. "abc1234", "HEAD~2").
            path:      Limit output to this file.
            stat_only: Show --stat summary only, no line-level diff.
        """
        args = ["show", "--format=fuller"]
        if stat_only:
            args.append("--stat")
        args.append(ref)
        if path:
            args += ["--", path]

        stdout, stderr, rc = _git(args, cwd)
        if rc != 0:
            return f"[git_show error] {stderr.strip()}"

        output = stdout
        LIMIT = 8000
        if len(output) > LIMIT:
            output = output[:LIMIT] + f"\n\n... [truncated — use path= to narrow scope.]"
        return f"🔍 git show {ref}\n{'=' * 60}\n{output.rstrip()}"

    @mcp.tool()
    def git_blame(
        cwd: str,
        path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> str:
        """
        Show who last modified each line of a file (git blame).

        Useful for understanding why a line exists, who introduced a bug,
        or what commit to reference for context.

        Args:
            cwd:        Absolute path to the git repository root.
            path:       File path relative to repo root.
            start_line: First line to show (1-based, optional).
            end_line:   Last line to show (1-based, optional).
        """
        args = ["blame", "--date=short", "-w"]
        if start_line and end_line:
            args += [f"-L{start_line},{end_line}"]
        elif start_line:
            args += [f"-L{start_line},{start_line + 40}"]
        args.append(path)

        stdout, stderr, rc = _git(args, cwd)
        if rc != 0:
            return f"[git_blame error] {stderr.strip()}"
        return f"👤 git blame {path}\n{'=' * 60}\n{stdout.rstrip()}"
