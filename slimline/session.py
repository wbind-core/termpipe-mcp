"""slimline/session.py \u2014 session-cwd tracking on the kb bus.

list_tools() publishes the workspace it indexed under a fresh 5-char session
id; codegraph_explore() (and any other cwd-aware tool) resolves it back.
The bus is the shared session state because the slimline server is spawned
fresh for every MCP connection, so nothing in-process survives between calls.

Topics:
  termpipe.session.active    -> current 5-char session id
  termpipe.session<id>.cwd   -> absolute project cwd for that session
"""

import secrets
import string

ACTIVE_TOPIC = "termpipe.session.active"


def new_session_id() -> str:
    """Random 5-char session id: lowercase alnum."""
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(5))


def cwd_topic(session_id: str) -> str:
    return f"termpipe.session{session_id}.cwd"


def publish_session_cwd(kb, cwd: str) -> str:
    """Publish cwd under a fresh session id and point .active at it.

    Returns the session id. Raises on kb failure \u2014 callers decide whether
    to degrade.
    """
    sid = new_session_id()
    kb.pub(cwd_topic(sid), cwd)
    kb.pub(ACTIVE_TOPIC, sid)
    return sid


def resolve_session_cwd(kb):
    """Return the cwd published by the most recent list_tools call.

    None when the bus is down, no session was ever published, or the stored
    value is empty. Never raises.
    """
    try:
        sid = (kb.get(ACTIVE_TOPIC) or "").strip()
        if not sid or sid == "(empty)":
            return None
        cwd = (kb.get(cwd_topic(sid)) or "").strip()
        if not cwd or cwd == "(empty)":
            return None
        return cwd
    except Exception:
        return None
