"""
GitHub CLI wrapper for TermPipe Slimline — hank edition.

Five dead-simple tools over `gh`. Trimmed hard; the long tail lives behind gh_api.

  gh_search(kind, query, limit)  — search repos | issues | prs | code
  gh_repo(action, ...)            — list | view | clone | sync | create
  gh_issue(action, ...)           — list | view | create | comment | close | reopen
  gh_pr(action, ...)              — list | view | diff | checks | create | merge | comment | close
  gh_api(path, method, data)      — raw authenticated API escape hatch

Hank-edition conventions:
- Outputs read like native tool results: compact, one item per line.
  The tool shells to `gh` locally on the box, so there are no SSH
  banners or connection artifacts — outputs are built from `gh --json`
  and formatted here.
- Local project sync target: /home/craig/Hank/tmp (GH_TMP).
- Trimmed as unnecessary / redundant / duplicative: commits search (use
  code), gist, browse (opens a browser — not model work), workflow / run /
  cache (CI), secret / variable / ssh-key / gpg-key (setup-time),
  codespace, copilot, extension, discussion, project, skill, agent-task,
  attestation, ruleset, label, org, alias, config, completion (setup/niche),
  repo archive / edit / rename / fork / delete / deploy-key / autolink
  (rare or dangerous), issue develop / edit / lock / pin / transfer
  (niche), pr checkout / co (local git work), pr review / ready / revert /
  update-branch (comment covers discussion, merge covers landing).
  Everything trimmed stays reachable via gh_api.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Shell-out core — gh runs locally on the box, outputs stay clean
# ---------------------------------------------------------------------------

GH_TMP = Path("/home/craig/Hank/tmp")


def _gh_bin() -> str:
    return shutil.which("gh") or "/usr/bin/gh"


def _git_bin() -> str:
    return shutil.which("git") or "/usr/bin/git"


def _run(args: List[str], timeout: int = 60,
         input_data: Optional[str] = None,
         prog: Optional[str] = None) -> Tuple[int, str, str]:
    """Run a local binary. Returns (returncode, stdout, stderr)."""
    cmd = [prog or _gh_bin()] + args
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, input=input_data)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    except Exception as e:  # binary missing etc.
        return 1, "", str(e)


def _err(tool: str, stderr: str) -> str:
    msg = " ".join((stderr or "unknown error").strip().splitlines()[:3])
    return f"[{tool}] error: {msg[:500]}"


def _clip(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + "…"


def _jload(out: str):
    try:
        return json.loads(out) if out.strip() else []
    except Exception:
        return None


def _repo_name(full: str) -> str:
    return (full or "").split("/")[-1]


# ---------------------------------------------------------------------------
# gh_search
# ---------------------------------------------------------------------------

_SEARCH = {
    "repo": ("repos", "fullName,description,stargazersCount,url,language"),
    "issue": ("issues", "number,title,state,url,repository"),
    "pr": ("prs", "number,title,state,url,repository"),
    "code": ("code", "path,repository,url"),
}


def _search_repo_name(it) -> str:
    return ((it.get("repository") or {}).get("nameWithOwner", "")
            or (it.get("owner") or {}).get("login", ""))


def do_search(kind: str, query: str, limit: int = 10) -> str:
    kind = (kind or "").lower()
    if kind not in _SEARCH:
        return f"[gh_search] kind must be one of: {', '.join(_SEARCH)}"
    if not query.strip():
        return "[gh_search] query required"
    sub, fields = _SEARCH[kind]
    limit = max(1, min(50, limit))
    rc, out, err = _run(["search", sub, query, "--json", fields,
                         "--limit", str(limit)])
    if rc != 0:
        return _err("gh_search", err)
    items = _jload(out)
    if items is None:
        return f"[gh_search] could not parse output:\n{_clip(out, 1000)}"
    if not items:
        return f"[gh_search] no {kind} results for '{query}'"
    lines = [f"[gh_search] {kind} results for '{query}' ({len(items)}):"]
    for it in items:
        if kind == "repo":
            desc = _clip((it.get("description") or "").replace("\n", " "), 100)
            lang = it.get("language") or "?"
            lines.append(f"• {it.get('fullName')} "
                         f"★{it.get('stargazersCount', 0)} [{lang}] — {desc}")
            lines.append(f"  {it.get('url')}")
        elif kind == "code":
            lines.append(f"• {_search_repo_name(it)} : {it.get('path')}")
            lines.append(f"  {it.get('url')}")
        else:
            lines.append(f"• {_search_repo_name(it)}"
                         f"#{it.get('number')} [{it.get('state')}] "
                         f"{it.get('title')}")
            lines.append(f"  {it.get('url')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# gh_repo
# ---------------------------------------------------------------------------

def _sync_repos(limit: int = 50) -> str:
    limit = max(1, min(100, limit))
    rc, out, err = _run(["repo", "list", "--json", "nameWithOwner",
                         "--limit", str(limit)])
    if rc != 0:
        return _err("gh_repo", err)
    items = _jload(out) or []
    GH_TMP.mkdir(parents=True, exist_ok=True)
    cloned, current, updated, failed = [], [], [], []
    for it in items:
        full = it.get("nameWithOwner", "")
        name = _repo_name(full)
        if not name:
            continue
        dest = GH_TMP / name
        try:
            if dest.exists() and (dest / ".git").exists():
                rc2, o2, e2 = _run(["-C", str(dest), "pull", "--ff-only"],
                                   timeout=120, prog=_git_bin())
                if rc2 != 0:
                    failed.append(f"{name} (pull: {_clip(e2.strip(), 120)})")
                elif "Already up to date" in o2:
                    current.append(name)
                else:
                    updated.append(name)
            elif dest.exists():
                failed.append(f"{name} (exists, not a git repo — skipped)")
            else:
                rc2, o2, e2 = _run(["repo", "clone", full, str(dest)],
                                    timeout=300)
                if rc2 != 0:
                    failed.append(f"{name} (clone: {_clip(e2.strip(), 120)})")
                else:
                    cloned.append(name)
        except Exception as e:
            failed.append(f"{name} ({e})")
    lines = [f"[gh_repo] sync → {GH_TMP} "
             f"({len(items)} repos listed):"]
    if cloned:
        lines.append(f"  cloned ({len(cloned)}): {', '.join(cloned)}")
    if updated:
        lines.append(f"  updated ({len(updated)}): {', '.join(updated)}")
    if current:
        lines.append(f"  current ({len(current)}): "
                     f"{', '.join(current[:10])}"
                     f"{' …' if len(current) > 10 else ''}")
    if failed:
        lines.append(f"  failed ({len(failed)}):")
        lines.extend(f"    • {f}" for f in failed)
    if not (cloned or updated or current or failed):
        lines.append("  nothing to do")
    return "\n".join(lines)


def do_repo(action: str, repo: str = "", limit: int = 20,
            private: bool = False, description: str = "") -> str:
    action = (action or "").lower()
    if action == "list":
        limit = max(1, min(100, limit))
        rc, out, err = _run(["repo", "list", "--json",
                             "nameWithOwner,description,isPrivate,url",
                             "--limit", str(limit)])
        if rc != 0:
            return _err("gh_repo", err)
        items = _jload(out) or []
        lines = [f"[gh_repo] repositories ({len(items)}):"]
        for it in items:
            lock = " 🔒" if it.get("isPrivate") else ""
            desc = _clip((it.get("description") or "").replace("\n", " "), 90)
            lines.append(f"• {it.get('nameWithOwner')}{lock} — {desc}")
        return "\n".join(lines)
    if action == "view":
        if not repo.strip():
            return "[gh_repo] view needs repo='OWNER/REPO'"
        rc, out, err = _run(["repo", "view", repo, "--json",
                             "nameWithOwner,description,url,isPrivate,"
                             "isArchived,defaultBranchRef,stargazerCount,"
                             "forkCount,pushedAt"])
        if rc != 0:
            return _err("gh_repo", err)
        it = _jload(out)
        if not isinstance(it, dict):
            return f"[gh_repo] could not parse output:\n{_clip(out, 1000)}"
        branch = (it.get("defaultBranchRef") or {}).get("name", "?")
        flags = "".join([
            " 🔒" if it.get("isPrivate") else "",
            " 📦archived" if it.get("isArchived") else "",
        ])
        return (
            f"[gh_repo] {it.get('nameWithOwner')}{flags}\n"
            f"  {it.get('description') or '(no description)'}\n"
            f"  ★{it.get('stargazerCount', 0)} "
            f"⑂{it.get('forkCount', 0)} "
            f"default branch: {branch} "
            f"pushed: {it.get('pushedAt', '?')[:10]}\n"
            f"  {it.get('url')}"
        )
    if action == "clone":
        if not repo.strip():
            return "[gh_repo] clone needs repo='OWNER/REPO'"
        GH_TMP.mkdir(parents=True, exist_ok=True)
        dest = GH_TMP / _repo_name(repo)
        if dest.exists():
            return f"[gh_repo] already exists: {dest}"
        rc, out, err = _run(["repo", "clone", repo.strip(), str(dest)],
                            timeout=300)
        if rc != 0:
            return _err("gh_repo", err)
        return f"[gh_repo] cloned {repo.strip()} → {dest}"
    if action == "sync":
        return _sync_repos(limit)
    if action == "create":
        name = repo.strip()
        if not name:
            return "[gh_repo] create needs repo='NAME' (new repo name)"
        args = ["repo", "create", name]
        if private:
            args.append("--private")
        else:
            args.append("--public")
        if description:
            args += ["--description", description]
        rc, out, err = _run(args)
        if rc != 0:
            return _err("gh_repo", err)
        return f"[gh_repo] created {name}:\n{_clip(out.strip(), 500)}"
    return "[gh_repo] action must be one of: list | view | clone | sync | create"


# ---------------------------------------------------------------------------
# gh_issue
# ---------------------------------------------------------------------------

def do_issue(action: str, repo: str, number: int = 0, title: str = "",
             body: str = "", comment: str = "", limit: int = 20) -> str:
    action = (action or "").lower()
    if not repo.strip():
        return "[gh_issue] repo='OWNER/REPO' required"
    repo = repo.strip()
    if action == "list":
        limit = max(1, min(100, limit))
        rc, out, err = _run(["issue", "list", "-R", repo, "--json",
                             "number,title,state,author,url",
                             "--limit", str(limit)])
        if rc != 0:
            return _err("gh_issue", err)
        items = _jload(out) or []
        lines = [f"[gh_issue] issues in {repo} ({len(items)}):"]
        for it in items:
            author = (it.get("author") or {}).get("login", "?")
            lines.append(f"• #{it.get('number')} [{it.get('state')}] "
                         f"{it.get('title')} (@{author})")
        return "\n".join(lines)
    if action == "view":
        if not number:
            return "[gh_issue] view needs number=<issue#>"
        rc, out, err = _run(["issue", "view", str(number), "-R", repo,
                             "--json",
                             "number,title,state,author,body,url,labels"])
        if rc != 0:
            return _err("gh_issue", err)
        it = _jload(out)
        if not isinstance(it, dict):
            return f"[gh_issue] could not parse output:\n{_clip(out, 1000)}"
        author = (it.get("author") or {}).get("login", "?")
        labels = ",".join(l.get("name", "") for l in it.get("labels", []))
        return (
            f"[gh_issue] #{it.get('number')} [{it.get('state')}] "
            f"{it.get('title')} (@{author}"
            f"{' #' + labels if labels else ''})\n"
            f"{_clip(it.get('body') or '(no body)', 1500)}\n"
            f"  {it.get('url')}"
        )
    if action == "create":
        if not title.strip():
            return "[gh_issue] create needs title='...'"
        args = ["issue", "create", "-R", repo, "--title", title.strip()]
        if body:
            args += ["--body", body]
        rc, out, err = _run(args)
        if rc != 0:
            return _err("gh_issue", err)
        return f"[gh_issue] created in {repo}:\n{_clip(out.strip(), 500)}"
    if action == "comment":
        if not number:
            return "[gh_issue] comment needs number=<issue#>"
        if not comment.strip():
            return "[gh_issue] comment needs comment='...'"
        rc, out, err = _run(["issue", "comment", str(number), "-R", repo,
                             "--body", comment])
        if rc != 0:
            return _err("gh_issue", err)
        return f"[gh_issue] commented on #{number} in {repo}"
    if action == "close":
        if not number:
            return "[gh_issue] close needs number=<issue#>"
        rc, out, err = _run(["issue", "close", str(number), "-R", repo])
        if rc != 0:
            return _err("gh_issue", err)
        return f"[gh_issue] closed #{number} in {repo}"
    if action == "reopen":
        if not number:
            return "[gh_issue] reopen needs number=<issue#>"
        rc, out, err = _run(["issue", "reopen", str(number), "-R", repo])
        if rc != 0:
            return _err("gh_issue", err)
        return f"[gh_issue] reopened #{number} in {repo}"
    return ("[gh_issue] action must be one of: "
            "list | view | create | comment | close | reopen")


# ---------------------------------------------------------------------------
# gh_pr
# ---------------------------------------------------------------------------

def do_pr(action: str, repo: str, number: int = 0, title: str = "",
          body: str = "", comment: str = "", limit: int = 20,
          method: str = "merge", base: str = "", head: str = "") -> str:
    action = (action or "").lower()
    if not repo.strip():
        return "[gh_pr] repo='OWNER/REPO' required"
    repo = repo.strip()
    if action == "list":
        limit = max(1, min(100, limit))
        rc, out, err = _run(["pr", "list", "-R", repo, "--json",
                             "number,title,state,author,url,isDraft",
                             "--limit", str(limit)])
        if rc != 0:
            return _err("gh_pr", err)
        items = _jload(out) or []
        lines = [f"[gh_pr] pull requests in {repo} ({len(items)}):"]
        for it in items:
            draft = " 📝draft" if it.get("isDraft") else ""
            author = (it.get("author") or {}).get("login", "?")
            lines.append(f"• #{it.get('number')} [{it.get('state')}]"
                         f"{draft} {it.get('title')} (@{author})")
        return "\n".join(lines)
    if action == "view":
        if not number:
            return "[gh_pr] view needs number=<pr#>"
        rc, out, err = _run(["pr", "view", str(number), "-R", repo, "--json",
                             "number,title,state,author,url,baseRefName,"
                             "headRefName,mergeable,additions,deletions,"
                             "isDraft,body"])
        if rc != 0:
            return _err("gh_pr", err)
        it = _jload(out)
        if not isinstance(it, dict):
            return f"[gh_pr] could not parse output:\n{_clip(out, 1000)}"
        author = (it.get("author") or {}).get("login", "?")
        draft = " 📝draft" if it.get("isDraft") else ""
        return (
            f"[gh_pr] #{it.get('number')} [{it.get('state')}]"
            f"{draft} {it.get('title')} (@{author})\n"
            f"  {it.get('headRefName')} → {it.get('baseRefName')} "
            f"(+{it.get('additions', 0)}/-{it.get('deletions', 0)}, "
            f"mergeable: {it.get('mergeable')})\n"
            f"{_clip(it.get('body') or '(no body)', 1200)}\n"
            f"  {it.get('url')}"
        )
    if action == "diff":
        if not number:
            return "[gh_pr] diff needs number=<pr#>"
        rc, out, err = _run(["pr", "diff", str(number), "-R", repo])
        if rc != 0:
            return _err("gh_pr", err)
        return f"[gh_pr] diff #{number} in {repo}:\n{_clip(out, 6000)}"
    if action == "checks":
        if not number:
            return "[gh_pr] checks needs number=<pr#>"
        rc, out, err = _run(["pr", "checks", str(number), "-R", repo])
        if rc != 0:
            return _err("gh_pr", err)
        return f"[gh_pr] checks #{number} in {repo}:\n{_clip(out.strip(), 2000)}"
    if action == "create":
        if not title.strip():
            return "[gh_pr] create needs title='...'"
        args = ["pr", "create", "-R", repo, "--title", title.strip()]
        if body:
            args += ["--body", body]
        if base:
            args += ["--base", base]
        if head:
            args += ["--head", head]
        rc, out, err = _run(args)
        if rc != 0:
            return _err("gh_pr", err)
        return f"[gh_pr] created in {repo}:\n{_clip(out.strip(), 500)}"
    if action == "merge":
        if not number:
            return "[gh_pr] merge needs number=<pr#>"
        method = method.lower()
        flag = {"merge": "--merge", "squash": "--squash",
                "rebase": "--rebase"}.get(method, "--merge")
        rc, out, err = _run(["pr", "merge", str(number), "-R", repo, flag])
        if rc != 0:
            return _err("gh_pr", err)
        return f"[gh_pr] merged #{number} in {repo} ({flag[2:]})"
    if action == "comment":
        if not number:
            return "[gh_pr] comment needs number=<pr#>"
        if not comment.strip():
            return "[gh_pr] comment needs comment='...'"
        rc, out, err = _run(["pr", "comment", str(number), "-R", repo,
                             "--body", comment])
        if rc != 0:
            return _err("gh_pr", err)
        return f"[gh_pr] commented on #{number} in {repo}"
    if action == "close":
        if not number:
            return "[gh_pr] close needs number=<pr#>"
        rc, out, err = _run(["pr", "close", str(number), "-R", repo])
        if rc != 0:
            return _err("gh_pr", err)
        return f"[gh_pr] closed #{number} in {repo}"
    return ("[gh_pr] action must be one of: "
            "list | view | diff | checks | create | merge | comment | close")


# ---------------------------------------------------------------------------
# gh_api — the escape hatch
# ---------------------------------------------------------------------------

def do_api(path: str, method: str = "GET", data: str = "") -> str:
    path = (path or "").strip().lstrip("/")
    if not path:
        return "[gh_api] path required, e.g. path='repos/OWNER/REPO/releases'"
    method = (method or "GET").upper()
    args = ["api", path, "-X", method]
    inp = data.strip() if data and data.strip() else None
    if inp:
        try:
            json.loads(inp)  # validate before sending
        except Exception as e:
            return f"[gh_api] data must be a JSON object string: {e}"
        args += ["--input", "-"]
    rc, out, err = _run(args, timeout=60, input_data=inp)
    if rc != 0:
        return _err("gh_api", err)
    return f"[gh_api] {method} {path}:\n{_clip(out.strip(), 8000)}"


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

def register_tools(mcp: FastMCP):
    @mcp.tool()
    def gh_search(kind: str, query: str, limit: int = 10) -> str:
        """
        Search GitHub — dead simple. One tool for repos, issues, PRs, code.

        Args:
            kind: repo | issue | pr | code.
            query: Search query (GitHub search syntax works).
            limit: Max results (default 10, max 50).
        """
        return do_search(kind, query, limit)

    @mcp.tool()
    def gh_repo(action: str, repo: str = "", limit: int = 20,
                private: bool = False, description: str = "") -> str:
        """
        Repositories: list yours, view one, clone it, sync them all, create.

        Args:
            action: list | view | clone | sync | create.
            repo: OWNER/REPO for view/clone; new repo NAME for create.
            limit: Max repos for list/sync (default 20/50, max 100).
            private: For create — make it private (default public).
            description: For create — repo description.
        sync clones every missing repo into /home/craig/Hank/tmp and
        fast-forward pulls the rest. view/clone take OWNER/REPO.
        """
        return do_repo(action, repo, limit, private, description)

    @mcp.tool()
    def gh_issue(action: str, repo: str, number: int = 0, title: str = "",
                 body: str = "", comment: str = "", limit: int = 20) -> str:
        """
        Issues: list, view, create, comment, close, reopen.

        Args:
            action: list | view | create | comment | close | reopen.
            repo: OWNER/REPO (always required).
            number: Issue number (view/comment/close/reopen).
            title: Issue title (create).
            body: Issue body (create).
            comment: Comment text (comment).
            limit: Max issues for list (default 20, max 100).
        """
        return do_issue(action, repo, number, title, body, comment, limit)

    @mcp.tool()
    def gh_pr(action: str, repo: str, number: int = 0, title: str = "",
              body: str = "", comment: str = "", limit: int = 20,
              method: str = "merge", base: str = "", head: str = "") -> str:
        """
        Pull requests: list, view, diff, checks, create, merge, comment, close.

        Args:
            action: list | view | diff | checks | create | merge | comment | close.
            repo: OWNER/REPO (always required).
            number: PR number (view/diff/checks/merge/comment/close).
            title: PR title (create).
            body: PR body (create).
            comment: Comment text (comment).
            limit: Max PRs for list (default 20, max 100).
            method: merge | squash | rebase (merge action, default merge).
            base: Base branch (create).
            head: Head branch (create).
        """
        return do_pr(action, repo, number, title, body, comment, limit,
                     method, base, head)

    @mcp.tool()
    def gh_api(path: str, method: str = "GET", data: str = "") -> str:
        """
        Raw authenticated GitHub API — the escape hatch. Anything the four
        curated tools don't cover (releases, gists, workflows, etc.) goes
        through here.

        Args:
            path: API path, e.g. 'repos/OWNER/REPO/releases/latest'.
            method: GET | POST | PUT | PATCH | DELETE (default GET).
            data: JSON object string sent as the request body (for
                POST/PUT/PATCH), e.g. '{"name":"v1.0"}'.
        """
        return do_api(path, method, data)
