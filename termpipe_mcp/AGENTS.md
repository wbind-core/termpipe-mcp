# AGENTS.md — TermPipe MCP Bug Report & Fix Guide

## Bug: `reload_tools` fails with `NameError: name 'inspect' is not defined`

### Status
**Fixed in source** — `import inspect` added to module-level imports in
`tools/system.py`. Requires server restart to take effect (see below).

---

## Symptom

Calling `reload_tools` via MCP returns:

```
Error executing tool reload_tools: name 'inspect' is not defined
```

---

## Root Cause

`tools/system.py` uses `inspect` in the `reload_tools()` function body at the
module level (line ~440 before fix):

```python
mods = [m for _, m in inspect.getmembers(tp, inspect.ismodule)]
```

But `inspect` was **never imported at the top of `system.py`**. The only import
of `inspect` in this file was a *local* import inside the `list_tools` function
(line ~384), which is scoped to that function only.

### Why it worked transiently before

`server.py` does `import inspect` at its top level (line 29). Because Python
caches modules in `sys.modules`, if `server.py` happened to be loaded *in the
same interpreter context* before `reload_tools` was called, `inspect` would be
present in `sys.modules` — but **not** in `system.py`'s module namespace.

This created a race condition: whether `reload_tools` succeeded depended on
import ordering at startup. A recent refactor of `server.py` or the module
loading sequence changed that ordering, making the failure consistent.

### The specific gap

There are actually **two** uses of `inspect` in `system.py`:

1. **Line ~384** (inside `list_tools`): has a correct local `import inspect`
2. **Line ~440** (inside `reload_tools`): uses `inspect.getmembers()` and
   `inspect.ismodule` **with no local or module-level import** → crashes

---

## Fix Applied

Added `import inspect` to the module-level imports in `tools/system.py`,
immediately after `import os`:

```python
import os
import inspect      # ← added
import importlib
import sys
...
```

File: `/home/craig/termpipe-mcp/termpipe_mcp/tools/system.py`, line 5.

---

## How to Reproduce (before fix)

1. Remove `import inspect` from the top of `tools/system.py`
2. Ensure `server.py` is NOT importing inspect, or alter load order
3. Start `termcp server`
4. Call `reload_tools` via MCP → `NameError: name 'inspect' is not defined`

---

## Why `reload_tools` Can't Fix Itself

`reload_tools` is designed to hot-reload modules without a server restart.
However, it **cannot un-import a broken module** that was already loaded at
process start. Once `system.py` is imported with the missing `inspect`, the
broken module object lives in memory for the lifetime of that process. Calling
`reload_tools` attempts to execute the very function that crashes, so it cannot
bootstrap itself out of the broken state.

**A full server restart is always required after fixing `system.py`.**

Restart sequence:
```bash
pkill -f "termcp server"
/home/craig/.local/bin/termcp server &
```

---

## Broader Recommendation for MCP Agent Fixing This

When auditing `tools/system.py`, do a **comprehensive import audit** across all
tool modules. The pattern to check:

```bash
grep -rn "inspect\." /home/craig/termpipe-mcp/termpipe_mcp/tools/
```

For every use of `inspect.X` in a function body, verify that either:
- `import inspect` exists at the **module level** (preferred), OR
- `import inspect` exists as a **local import at the top of that specific function**

The local import in `list_tools` (line ~384) is fine as-is. The fix needed was
only in `reload_tools`.

Also worth checking: are there other stdlib modules used in function bodies
across the tool modules that rely on transitive imports via `server.py`? The
same race condition could affect `threading`, `pathlib`, `re`, or others if
`server.py` imports them and the tool modules assume they're available.

---

## Files Relevant to This Bug

| File | Role |
|------|------|
| `tools/system.py` | Contains `reload_tools()` — **the broken function** |
| `server.py` | Imports `inspect` at top level — masked the bug transitively |
| `tools/workspace/tools.py` | Workspace tool registration — unrelated but nearby |

---

*Written: 2026-04-21 — diagnosed and fixed by Claude Sonnet 4.6 during session,
MiniMax requested for comprehensive audit and verification.*
