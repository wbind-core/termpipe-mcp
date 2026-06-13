"""
Task and plan helpers — status encoding, id management, status mutation.
"""
import re
import json

from ._db import _db_read_artifact
from ._bus import PLAN_DRAFT

# ---------------------------------------------------------------------------
# Plan status helpers
# ---------------------------------------------------------------------------

def _get_plan_status(ws_id: str) -> str:
    """Read current plan status from DB artifact summary field."""
    row = _db_read_artifact(ws_id, "implementation_plan.md")
    if not row:
        return PLAN_DRAFT
    # status stored as JSON in summary: {"text": "...", "plan_status": "..."}
    try:
        meta = json.loads(row["summary"] or "{}")
        return meta.get("plan_status") or PLAN_DRAFT
    except Exception:
        return PLAN_DRAFT


def _pack_summary(text: str | None, plan_status: str) -> str:
    return json.dumps({"text": text or "", "plan_status": plan_status})


def _unpack_summary(raw: str | None) -> tuple[str, str]:
    """Returns (human_text, plan_status)."""
    if not raw:
        return ("", PLAN_DRAFT)
    try:
        d = json.loads(raw)
        if isinstance(d, dict):
            return (d.get("text", ""), d.get("plan_status", PLAN_DRAFT))
    except Exception:
        pass
    return (raw, PLAN_DRAFT)


# ---------------------------------------------------------------------------
# Core upsert — single entry point for all artifact mutations
# ---------------------------------------------------------------------------


def _next_task_id(content: str) -> int:
    ids = re.findall(r"<!--\s*id:\s*(\d+)\s*-->", content)
    return max((int(i) for i in ids), default=0) + 1


def _set_task_status(content: str, item_id: int, status: str) -> tuple[str, bool]:
    marker = {"done": "[x]", "in_progress": "[/]", "todo": "[ ]"}.get(status, "[ ]")
    pattern = re.compile(
        r"(-\s*)\[[x/ ]\](\s*.+?)(<!--\s*id:\s*" + str(item_id) + r"\s*-->)",
        re.IGNORECASE
    )
    new, count = pattern.subn(
        lambda m: f"{m.group(1)}{marker}{m.group(2)}{m.group(3)}", content
    )
    return new, count > 0


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------
