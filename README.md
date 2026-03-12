# TermPipe MCP Server

MCP server for Claude Desktop providing surgical file editing, shell execution, AI debugging, and more.

---

## Architecture

```
/home/craig/termpipe-mcp/          ← CANONICAL SOURCE (edit here)
  termpipe_mcp/
    server.py                      ← FastMCP entry point (stdio)
    tools/
      surgical.py                  ← Line-level file editing
      system.py                    ← list_tools, reload_tools, etc.
      files.py                     ← read/write/list
      termf.py                     ← Shell execution
      debug.py                     ← iFlow debug assist
      gemini_debug.py              ← Gemini debug assist
      ... (all tool modules)

~/.termpipe/mcp_server/tools/      ← SYMLINK → termpipe_mcp/tools/
```

**`~/.termpipe/mcp_server/tools/` is a symlink** to `termpipe_mcp/tools/`.  
Edit files in either location — they are the same files.

---

## How Claude Desktop Runs It

From `~/.config/Claude/claude_desktop_config.json`:

```json
"termpipe": {
  "command": "/home/craig/.local/share/pipx/venvs/termpipe-mcp/bin/python",
  "args": ["-m", "termpipe_mcp.server"],
  "env": { "TERMCP_URL": "http://localhost:8421" }
}
```

The pipx venv is installed in **editable mode** pointing to `/home/craig/termpipe-mcp/`.  
Edits to `.py` files take effect on next restart — **no reinstall needed**.

---

## Applying Changes

### Option A — Restart Claude Desktop
Kills and respawns the stdio server process. Always picks up changes.

### Option B — Hot Reload (no restart)
Ask Claude to call `reload_tools()`. It will:
1. `importlib.reload()` every tool module
2. Clear FastMCP's tool registry
3. Re-register all tools in-place

Useful for mid-session edits. Note: changes to `server.py` itself still require a full restart.

---

## Adding a New Tool

1. Open the relevant module in `termpipe_mcp/tools/` (or create a new one)
2. Add your `@mcp.tool()` function inside `register_tools(mcp):`
3. If new module: import and call `register_tools(mcp)` in `server.py`
4. Call `reload_tools()` or restart Claude Desktop

`list_tools()` is **dynamic** — it introspects the live FastMCP registry, so new tools appear automatically without editing any manifest.

---

## Tool Categories

| Category  | Module          | Description                        |
|-----------|-----------------|------------------------------------|
| SURGICAL  | surgical.py     | Line-level file editing            |
| FILE      | files.py        | Read/write/list/move               |
| TERMF     | termf.py        | Shell command execution            |
| DEBUG     | debug.py        | iFlow AI debug assist              |
| GEMINI    | gemini_debug.py | Gemini AI debug/analyze            |
| PROCESS   | process.py      | Session/process management         |
| IFLOW     | iflow.py        | iFlow AI backend                   |
| SYSTEM    | system.py       | list_tools, reload_tools, config   |
| SEARCH    | search.py       | File content search                |
| APPS      | apps.py         | App launcher                       |
| WBIND     | wbind.py        | Wayland GUI automation             |
| THREAD    | thread.py       | Thread coordination log            |
| WEB_SEARCH| web_search.py   | Web search                         |

---

## Key Surgical Tool Behaviors (v2.3)

- **Line delta feedback**: Every mutating tool (`replace_lines`, `insert_lines`, `delete_lines`, etc.) returns `📊 File: N → M lines (delta: ±X)` so models track shifted line numbers across sequential edits.
- **`smart_replace`**: Operates on full file content — supports multi-line `old_text` spans.
- **`replace_at_line`**: Multi-occurrence lines — replaces first by default, pass `replace_all=True` for all.
- **`list_tools`**: Dynamic — reads live FastMCP registry, never stale.
- **`reload_tools`**: Hot-reload all modules in-place without restarting Claude Desktop.

---

## FastAPI Backend

The FastAPI backend (`termf server` / `termcp server`) runs separately on port 8421.  
The MCP server connects to it via `TERMCP_URL=http://localhost:8421`.  
Check status: `termcp status`
