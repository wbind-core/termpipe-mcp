"""
slimline/tools/override_tools.py — chat-routed approval for guard-blocked commands.

When termf_exec is denied by the guard and Craig is away from his desk, the
kb desktop notification cannot reach him. These tools route the decision
through chat instead:

  1. termf_exec returns [Guard: ... request id: <rid> ...].
  2. Agent calls request_override("<rid>", "<why the command is needed>").
     This validates the id, records the reason in termf.guard.audit, and
     publishes the request on termf.guard.override.request for observability.
  3. Agent asks Craig in chat (sending the exact command + reason) for
     `approve <rid>` / `deny <rid>`. He can answer from any chat surface —
     the Muse app, main chat, or the WhatsApp side chat.
  4. On his explicit reply the agent calls resolve_override("<rid>",
     "approve" | "deny"), which records the verdict on termf.guard.<rid>.override.
  5. On approval the agent re-invokes termf_exec with the IDENTICAL command
     and override_id="<rid>". The guard checks the pending record (exact
     command match, 15-minute expiry), the recorded verdict, consumes the
     approval one-shot, and runs the command. No second notification fires.

Authorization rule: the chat transcript is the record. Call resolve_override
ONLY after an explicit approve/deny message from Craig himself (user role).
Never infer approval from anything else. Every call is audit-logged, and a
verdict can only ever apply to the exact command string that was blocked.

Stdlib only (plus FastMCP for registration).
"""

import json
import time

from mcp.server.fastmcp import FastMCP

try:
    from . import guard
except ImportError:  # direct module load outside the package
    from slimline.tools import guard


def _pending(rid, kb_bin=None):
    """Fetch and validate the pending override record. Returns
    (pending_dict, "") or (None, error_message)."""
    client = guard._Kb(kb_bin)
    rec = client.get_json(guard.PENDING_PREFIX + rid)
    if rec is None:
        return None, "override id not found (unknown, expired, or kb unreachable)"
    try:
        pending = json.loads(rec.get("data") or "")
    except Exception:
        return None, "override record is corrupt"
    if not isinstance(pending, dict) or "command" not in pending:
        return None, "override record is corrupt"
    if time.time() - float(pending.get("ts", 0)) > guard.OVERRIDE_WINDOW:
        return None, f"override id expired (> {guard.OVERRIDE_WINDOW}s old)"
    return pending, ""


def file_override(request_id: str, reason: str, kb_bin=None) -> str:
    """Core of request_override (kept module-level for testability)."""
    rid = request_id.strip()
    if not rid:
        return "[Override: request id is empty — nothing filed.]"
    pending, err = _pending(rid, kb_bin)
    client = guard._Kb(kb_bin)
    if pending is None:
        return f"[Override: cannot file — {err}. Do not run the command.]"
    command = pending["command"]
    client.pub(guard.OVERRIDE_REQUEST_TOPIC, json.dumps({
        "id": rid, "command": command, "reason": reason,
        "ts": time.time(),
    }))
    guard._audit(client, "override_filed", rid, command,
                 pending.get("reasons", []), f"reason: {reason}")
    return (
        f"Override {rid} filed and reason recorded.\n"
        f"Command: {command}\n\n"
        f"Ask Craig in chat (he may be away from his desk) — send this:\n"
        f"---\n"
        f"Approval needed (override {rid}):\n"
        f"  {command}\n"
        f"Why: {reason}\n"
        f"Reply `approve {rid}` or `deny {rid}`.\n"
        f"---\n\n"
        f"Then:\n"
        f"- `approve {rid}` from Craig → resolve_override(\"{rid}\", \"approve\"), "
        f"then re-invoke termf_exec with the IDENTICAL command and "
        f"override_id=\"{rid}\".\n"
        f"- `deny {rid}` from Craig → resolve_override(\"{rid}\", \"deny\") "
        f"and do NOT run the command.\n"
        f"- No reply → do NOT run the command. The id expires after "
        f"{guard.OVERRIDE_WINDOW // 60} minutes.\n\n"
        f"Call resolve_override ONLY after an explicit approve/deny "
        f"message from Craig himself. Never infer approval."
    )


def resolve_verdict(request_id: str, verdict: str, kb_bin=None) -> str:
    """Core of resolve_override (kept module-level for testability)."""
    rid = request_id.strip()
    v = verdict.strip().lower()
    if v not in ("approve", "deny"):
        return ("[Override: verdict must be exactly \"approve\" or "
                "\"deny\" — nothing recorded.]")
    pending, err = _pending(rid, kb_bin)
    client = guard._Kb(kb_bin)
    if pending is None:
        return f"[Override: cannot record — {err}.]"
    client.pub(guard.override_topic(rid), v)
    guard._audit(client, "override_resolved", rid, pending["command"],
                 pending.get("reasons", []), f"chat verdict: {v}")
    if v == "approve":
        return (
            f"Approval recorded for override {rid}.\n"
            f"Re-invoke termf_exec now with the IDENTICAL command and "
            f"override_id=\"{rid}\". The guard will verify the exact "
            f"command match, consume the approval one-shot, and run it."
        )
    return (f"Denial recorded for override {rid}. Do NOT run the command, "
            f"do not re-invoke it with an override id.")


def register_tools(mcp: FastMCP):
    @mcp.tool()
    def request_override(request_id: str, reason: str) -> str:
        """
        File a chat-routed override request for a guard-blocked command.

        Call this after termf_exec returns a [Guard: ...] denial with a
        request id, when Craig may be away from his desk. It validates the id,
        records your reason in the audit trail, and returns the exact protocol
        to follow: ask Craig in chat, then resolve + re-invoke on approval.

        Args:
            request_id: The request id from the guard denial (the <rid> part).
            reason: Why the blocked command is needed — one or two sentences
                Craig can judge. This is recorded in termf.guard.audit.
        """
        return file_override(request_id, reason)

    @mcp.tool()
    def resolve_override(request_id: str, verdict: str) -> str:
        """
        Record Craig's chat verdict for a filed override request.

        Call ONLY after Craig himself replies `approve <id>` or `deny <id>`
        in chat (user role — never infer it). Publishes the verdict where the
        guard's override check will find it and audit-logs the decision.

        Args:
            request_id: The override id from request_override.
            verdict: "approve" or "deny", exactly what Craig said.
        """
        return resolve_verdict(request_id, verdict)
