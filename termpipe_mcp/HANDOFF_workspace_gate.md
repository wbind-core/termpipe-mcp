# workspace_gate wiring — handoff doc
_Generated 2026-05-07, termpipe-mcp session #10_

---

## What this is

Wiring the existing `workspace_gate.py` into all write tools in `files.py`,
`surgical/replacers.py`, and `surgical/writers.py`. The gate module and the
underlying `_phase.py` / SQLite DB are already correct and complete —
this is purely a wiring job.

---

## Status at handoff

| File | Status |
|------|--------|
| `tools/surgical/workspace_gate.py` | ✅ Complete — no changes needed |
| `tools/workspace/_phase.py` | ✅ Complete — `check_write_gate()` is the source of truth |
| `tools/files.py` | ✅ **Already wired** — `write_file`, `append_file`, `move_file`, `write_batch` all gate correctly |
| `tools/surgical/replacers.py` | ❌ **Not wired** + structural bug (see below) |
| `tools/surgical/writers.py` | ❌ **Not wired** |
| `tools/workspace/_review.py` | ❌ **NameError bug** — `PLAN_DRAFT` not imported |

---

## Bug 1 — `_review.py` NameError (fix first)

`workspace_await_approval` crashes with `NameError: name 'PLAN_DRAFT' is not defined`.
`PLAN_DRAFT` is defined in `_bus.py` line 39 but not imported in `_review.py` line 18.

**Fix — `_review.py` line 18:**
```python
# Before:
    PLAN_PENDING_APPROVAL, PLAN_APPROVED, PLAN_REJECTED,
# After:
    PLAN_DRAFT, PLAN_PENDING_APPROVAL, PLAN_APPROVED, PLAN_REJECTED,
```

---

## Bug 2 — `replacers.py` structural bug

`undo()` and `history()` tool defs are defined AFTER the `_remove_basic_duplicates`
helper, outside `register_tools()`. They will never be registered with MCP.
Move them inside `register_tools()`.

---

## Wiring pattern (from `files.py` — already correct reference)

```python
from .workspace_gate import workspace_gate, workspace_gate_consume, workspace_gate_checkpoint

@mcp.tool()
def some_write_tool(path: str, ...) -> str:
    block = workspace_gate(path)   # 1. Gate — FIRST, before any work
    if block:
        return block
    try:
        # ... compute new content ...
        atomic_write(path, new_lines)
        record_edit(...)
        workspace_gate_consume(path)          # 2. Consume once-override if active
        cp = workspace_gate_checkpoint(path)  # 3. Checkpoint prompt if threshold hit
        return f"✅ ...{cp}"                  # cp is '' if no checkpoint due
    except Exception as e:
        return f"[Error: {e}]"
```

`workspace_gate(path)` walks UP from `path` to find a registered workspace.
The workspace root is `/home/craig/termpipe-mcp/termpipe_mcp` (registered folder_path
in context-core registry — NOT the repo root `/home/craig/termpipe-mcp`).

---

## `surgical/replacers.py` — exact changes

### 1. Add import (after existing imports, ~line 14)
```python
from .workspace_gate import workspace_gate, workspace_gate_consume, workspace_gate_checkpoint
```

### 2. `smart_replace` — gate at top of function body
First lines of `try` block, before anything else:
```python
block = workspace_gate(path)
if block:
    return block
```
In each write path (unique occurrence branch + expected_line branch),
after `atomic_write(path, new_lines)` and `record_edit(...)`:
```python
workspace_gate_consume(path)
cp = workspace_gate_checkpoint(path)
# change:  return out  →  return f"{out}{cp}"
```

### 3. `remove_duplicates` — same pattern
Gate at top, consume+checkpoint after `atomic_write` + `record_edit`.

### 4. Move `undo` and `history` inside `register_tools()`
Currently defined after `_remove_basic_duplicates` at module level.
Cut and paste both defs inside `register_tools(mcp)` before its closing line.

---

## `surgical/writers.py` — exact changes

### 1. Add import (after existing imports, ~line 12)
```python
from .workspace_gate import workspace_gate, workspace_gate_consume, workspace_gate_checkpoint
```

### 2. All four tools — identical insertion

Applies to: `insert_lines`, `delete_lines`, `overwrite_lines`, `patch_line`

**Top of function body (before `lines = read_file_lines(path)`):**
```python
block = workspace_gate(path)
if block:
    return block
```

**After `atomic_write` + `record_edit`:**
```python
workspace_gate_consume(path)
cp = workspace_gate_checkpoint(path)
```

**Change final return:**
```python
return f"{out}{cp}"
```

### 3. Optional improvement
`pre_commit_gate` fires before `dry_run` check in all four tools — reviewer logic
runs even on dry runs. Move `if dry_run:` before `pre_commit_gate` in each.

---

## Known gate quirk

The workspace gate only fires for paths under `/home/craig/termpipe-mcp/termpipe_mcp`
(the registered folder_path). Files at the repo root (`/home/craig/termpipe-mcp/`)
are outside the registered subtree and pass through ungated. This is by design
(only source files are managed), but worth knowing.

---

## Verification

```bash
cd /home/craig/termpipe-mcp
python -c "from termpipe_mcp.tools.surgical.replacers import register_tools; print('replacers OK')"
python -c "from termpipe_mcp.tools.surgical.writers import register_tools; print('writers OK')"
python -c "from termpipe_mcp.tools.files import register_tools; print('files OK')"
```

Restart MCP server. Confirm a write on a `no_plan` workspace returns ⛔ block message.

---

## File map
```
/home/craig/termpipe-mcp/termpipe_mcp/tools/
  files.py                    ← reference (already wired correctly)
  surgical/
    workspace_gate.py         ← gate module (complete, no changes needed)
    replacers.py              ← needs wiring + undo/history bug fix
    writers.py                ← needs wiring
  workspace/
    _phase.py                 ← check_write_gate() source of truth
    _review.py                ← PLAN_DRAFT import bug on line 18
    _bus.py                   ← PLAN_DRAFT defined here on line 39

Registered workspace root: /home/craig/termpipe-mcp/termpipe_mcp
context-core ws_id:        ws_0d164c9cf525
DB:                        ~/.context-core/workspaces/ws_0d164c9cf525/workspace.db
Task [1] in_progress:      "Wire workspace_gate into replacers.py and writers.py"
```
