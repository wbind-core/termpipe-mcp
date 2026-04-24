# Session Handoff - 2026-04-10

## Status: INCOMPLETE - Need to Restart Environment

The AionUi environment has no session saving and times out, losing all context. Writing this handoff to resume.

---

## Task: Migrate TermPipe AI Tools from iFlow to OmniProxy

### Completed

1. ✅ **Binary swap for kernclip-busd** - Fixed "Text file busy" error by killing running processes and systemd service before copying new binaries
2. ✅ **OmniProxy investigation** - Full analysis of omniproxy architecture, configuration, and provider setup
3. ✅ **Workspace initialized** - `/home/craig/omniproxy` workspace with todos and implementation plan

### OmniProxy Status

**Working:**
- Main API: Port 8743 ✅
- Tool Server: Port 8422 ✅  
- Reviewer backend: `omniproxy` ✅
- 400+ models via OpenRouter ✅

**Provider Health (from `/health`):**
- openrouter: ✅ ok
- opencode: ✅ ok
- voice_ai: ✅ ok
- qwen_cli: ❌ unavailable (CLI IS installed but health check fails)
- gemini_cli: ❌ unavailable (CLI IS installed but health check fails)

**CLIs ARE installed:**
- `gemini` at `/home/craig/.npm-global/bin/gemini` (v0.37.1)
- `qwen` at `/home/craig/.local/bin/qwen` (v0.14.2)

**Issue:** Both CLIs hang when called non-interactively. Need to investigate how AionUi handles them.

---

## AionUi Reference

Location: `/home/craig/aion/` (extracted from tar)

Key files for CLI backend handling:
- `/home/craig/aion/src/process/worker/gemini.ts`
- `/home/craig/aion/src/process/worker/aionrs.ts`
- `/home/craig/aion/src/process/extensions/types.ts`

**Action needed:** Study how AionUi invokes gemini-cli and qwen-cli to understand the correct invocation pattern.

---

## Migration Todos (from workspace)

1. ✅ Investigate omniproxy configuration and setup
2. ⏳ Migrate debug.py from iflow_query to omniproxy
3. ⏳ Migrate iflow.py tools to use omniproxy SDK
4. ⏳ Update helpers.py omniproxy_query to use SDK client
5. ⏳ Remove iflow direct API dependencies after migration
6. ⏳ Test all AI-powered features after migration

---

## Key Files to Migrate

### debug.py (4 functions using iflow_query)
Location: `/home/craig/termpipe-mcp/termpipe_mcp/tools/debug.py`

Functions to change:
- `debug_assist()` - line ~50: `from termpipe_mcp.tools.iflow import iflow_query`
- `analyze_file_structure()` - similar import
- `suggest_edit_approach()` - similar import
- `analyze_and_suggest_fix()` - similar import

**Fix:** Change `iflow_query` to `omniproxy_query` from helpers.py

### iflow.py (3 MCP tools)
Location: `/home/craig/termpipe-mcp/termpipe_mcp/tools/iflow.py`

Tools:
- `ifp_send()` - sends to iFlow API directly
- `ifp_model()` - switches model
- `ifp_status()` - status check

**Fix:** Either migrate to omniproxy SDK or deprecate (omniproxy handles routing now)

### helpers.py
Location: `/home/craig/termpipe-mcp/termpipe_mcp/tools/surgical/helpers.py`

Already has `omniproxy_query()` that works correctly. Also has `get_iflow_credentials()` that should be deprecated.

---

## Omniproxy SDK

Location: `/home/craig/omniproxy/sdk/python/omniproxy/__init__.py`

Provides:
- `Client` (sync)
- `AsyncClient` (async)
- `ToolServerClient`
- `run_with_tools()` for agentic loops

---

## Settings Files

**OmniProxy:** `~/.omniproxy/settings.json`
```json
{
  "port": 8743,
  "default_provider": "auto",
  "timeout_seconds": 60
}
```

**TermPipe:** `/home/craig/termpipe-mcp/settings.json`
```json
{
  "reviewer_backend": "omniproxy",
  "reviewer_model": "qwen3-coder-plus",
  "omniproxy_url": "http://127.0.0.1:8743"
}
```

---

## Next Steps on Resume

1. Study AionUi's gemini.ts and qwen handling to understand correct CLI invocation
2. Fix omniproxy's qwen_cli and gemini_cli backend health checks
3. Migrate debug.py (simple import change)
4. Decide on iflow.py tools (migrate or deprecate)
5. Test reviewer still works after changes
6. Remove iflow dependencies

---

## Commands to Resume

```bash
# Check omniproxy health
curl -s http://127.0.0.1:8743/health

# Check tool server
curl -s http://127.0.0.1:8422/tools/list

# Check TermPipe reviewer
# In Python: from termpipe_mcp.tools.system import system_info; system_info()

# Test qwen CLI (figure out correct invocation)
qwen --help
# Need to study AionUi's implementation

# Test gemini CLI (figure out correct invocation)
gemini --help
```

---

## Context

User is building:
- **Vocoder** - Voice-driven coding assistant with pattern detection
- **GTT** - Voice-driven RPA for Wayland  
- **Babel** - Real-time translation with voice cloning (Kirkland pilot)
- **kc-bus** - 10gbps event bus infrastructure
- **OmniProxy** - LLM gateway for all the above

User has Kirkland contract for Babel (Chinese translation focus).

iFlow is shutting down, hence this migration.
