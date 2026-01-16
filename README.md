# TermPipe MCP

**System automation tools for AI assistants. Saves you money with surgical file editing.**

## Install

**macOS / Linux:**
```bash
curl -sSL https://raw.githubusercontent.com/wbind-core/termpipe-mcp/master/quick-install.sh | bash
```

**Windows:**
```powershell
iwr -useb https://raw.githubusercontent.com/wbind-core/termpipe-mcp/master/quick-install.ps1 | iex
```

Done. Everything auto-configures. No setup required.

---

## What You Get

**Saves Money:** Surgical editing tools modify single lines instead of rewriting entire files. 90% fewer tokens = lower API costs.

**AI Debugging:** When Claude gets stuck, it calls smarter models (iFlow/Gemini) to get unstuck. No more retry loops burning your context.

**System Access:** Terminal commands, file operations, process management, smart search, app launching - all the tools AI actually needs.

**Zero Config:** One command installs and configures everything. Works with Claude Desktop, Claude Code, iFlow CLI, Gemini CLI.

---

## Example: Why Surgical Editing Matters

**Traditional approach (wastes tokens):**
- Read entire 1000-line file → 1000 tokens
- Modify in context → more tokens  
- Write entire file back → 1000 tokens
- **Total: 2000+ tokens to change one line**

**TermPipe approach (saves money):**
- Change one line → 10 tokens
- **200x token reduction**

This adds up fast. Real savings on real usage.

---

## Troubleshooting

Server won't start? → `lsof -i :8421`  
Tools not appearing? → Restart your MCP client  
Still broken? → [File an issue](https://github.com/wbind-core/termpipe-mcp/issues)

## Contributing

MIT License. PRs welcome.
