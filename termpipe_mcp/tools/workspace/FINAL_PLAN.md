# Workspace Subpackage — Wiring Audit & Handoff Doc
**Date:** 2026-05-07  
**Scope:** `/home/craig/termpipe-mcp/termpipe_mcp/tools/workspace/`  
**Status:** Audit complete — all identified fixes applied ✅

---

## 1. Architecture Overview

The workspace subpackage is a modular replacement for the old monolithic `workspace.py`.  
External callers import only two symbols from `__init__.py`:
- `workspace_resume` (from `_artifacts.py`)
- `register_tools` (from `tools.py`)

### Module Responsibilities

| Module | Responsibility |
|---|---|
| `_bus.py` | Raw kernclip-bus socket I/O, topic constants, artifact type constants, plan status constants |
| `_db.py` | SQLite read/write primitives for per-workspace artifact storage |
| `_registry.py` | Maps `cwd` → `ws_id` via context_core registry DB |
| `_artifacts.py` | `_upsert_artifact()` core write path; `workspace_resume()` for session re-hydration |
| `_phase.py` | Phase state machine (SQLite-backed), write gate enforcement, override management, checkpoint counter |
| `_task.py` | Plan status helpers (`_pack_summary`, `_unpack_summary`, `_get_plan_status`), task ID management, task status mutation |
| `_task_ops.py` | MCP-facing task CRUD (`workspace_task_create`, `workspace_task_update`, `workspace_task_set_status`, `workspace_task_query`) |
| `_plan.py` | MCP-facing plan/doc tools (`workspace_init`, `workspace_plan_update`, `workspace_walkthrough_update`, `workspace_doc_update`) |
| `_review.py` | Review gate tools (`workspace_request_review`, `workspace_await_approval`, `workspace_task_request_review`, `workspace_await_task_approval`, `workspace_override`) |
| `_workspace.py` | Session tools (`workspace_status`, `workspace_list`, `workspace_load`) |
| `tools.py` | `register_tools(mcp)` — thin dispatcher, imports from all above modules, applies `_gated()` write wrapper |
| `__init__.py` | Public surface + cascade re-imports for hot reload |

### Phase State Machine

```
no_plan → plan_draft → pending_approval → approved → task_in_progress ⇄ task_needs_review
```

Write tools are only unlocked in `task_in_progress` or with an active override.  
Override scopes: `once` (consumed after one write op) | `session` (until session_end).

---

## 2. Data Storage Design

**No separate JSON file is needed or recommended.**  
All persistent state lives in two places:

- **Per-workspace SQLite DB** (`~/.context-core/workspaces/<ws_id>.db`)
  - `workspace_phase` table: phase, current_task_id, override state, write_op_count, checkpoint counter
  - Artifact table: versioned content blobs for `task.md`, `implementation_plan.md`, `walkthrough.md`, plus arbitrary docs
  - Plan status: encoded as JSON in the artifact `summary` field (`{"text": "...", "plan_status": "..."}`)

- **kernclip-bus** (ephemeral pub/sub): live broadcast of artifact updates, review requests, approvals/rejections

A JSON file would create a third source of truth competing with both. The SQLite design is correct as-is.

---

## 3. Bugs Found & Fixed

### Fix 1 — `None` plan_status stored in DB ✅ APPLIED

**Location:** `tools.py` → `workspace_plan_update()` + `_task.py` → `_get_plan_status()`  
**Root cause:** Dispatcher default was `status=None`, passing `None` explicitly to
`_pack_summary(summary, None)`, producing `{"text": "", "plan_status": null}` in the DB.
`_get_plan_status()` used `.get("plan_status", PLAN_DRAFT)` which returned `None` (not
`PLAN_DRAFT`) because the key existed with a null value — fallback never triggered.

**Changes applied:**
- `tools.py`: `status: str = None` → `status: str = "draft"`
- `_task.py`: `meta.get("plan_status", PLAN_DRAFT)` → `meta.get("plan_status") or PLAN_DRAFT`

---

### Fix 2 — Write gate `_gated()` defined but never wired ✅ APPLIED

**Location:** `tools.py` → `register_tools()`  
**Root cause:** `_gated()` existed but every `@mcp.tool()` registration called the underlying
`_workspace_*` function directly, bypassing phase enforcement entirely.

**Changes applied** — five write tools now route through `_gated()`:
- `workspace_plan_update`
- `workspace_walkthrough_update`
- `workspace_doc_update`
- `workspace_task_update`
- `workspace_task_set_status`

**Note:** Active workspaces where phase is not `task_in_progress` will now block on write ops.
Run `workspace_status(cwd=...)` on active projects after reloading to verify phase state.

---

### Fix 3 — Double `_db_list_artifacts()` call in `workspace_resume()` ✅ APPLIED

**Location:** `_artifacts.py` → `workspace_resume()`  
**Root cause:** `_db_list_artifacts(ws_id)` was called twice — once to build `init_payload`,
and again in the `for art in _db_list_artifacts(ws_id):` republish loop. The result was
already in scope as `artifacts`. Fired on every `list_tools` invocation.

**Change applied:** Loop changed from `for art in _db_list_artifacts(ws_id):` → `for art in artifacts:`  
One DB open/query/close cycle eliminated per session start.

---

## 4. Implementation Plan — COMPLETED

---

## 5. What Is Correctly Wired

- All 16 workspace tools are registered in `register_tools()` ✅
- `__init__.py` cascade re-imports ensure `reload_tools()` pulls fresh submodule versions ✅
- `phase_briefing()` is called from `list_tools` and renders correctly in tactical briefing ✅
- `workspace_resume()` fires as side-effect of `list_tools` to re-hydrate session state ✅
- `_pack_summary` / `_unpack_summary` round-trip is structurally correct ✅ (null bug fixed)
- Bus pub/sub wiring in `_artifacts.py` → `_bus_pub()` is correct ✅
- Override lifecycle (`once` vs `session`, `consume_once_override`) is correctly implemented ✅
- Checkpoint counter and `CHECKPOINT_PROMPT` injection via `checkpoint_suffix()` is correct ✅
- Write gate `_gated()` now enforced on all five mutating tools ✅ (previously dead code)
- `workspace_resume()` no longer double-queries `_db_list_artifacts()` ✅

---

## 6. Remaining Recommendations

1. **Verify active workspace phase** — run `workspace_status(cwd=...)` on any active workspace
   to confirm phase is not stuck at `no_plan` or `plan_draft` due to historical null writes.
   Those workspaces will now block on write ops until phase is advanced manually.
2. **Optional:** Add a `workspace_status` summary to the tactical briefing block
   (phase + plan_status + active task in one line) for faster model orientation at session start.

---

*Generated by Claude Sonnet 4.6 — session audit 2026-05-07*
