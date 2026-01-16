# TermPipe MCP

> **Intelligent system automation for AI assistants.** Production-ready MCP server providing terminal access, surgical file operations, process management, and AI-powered debugging.

## What Is This?

TermPipe MCP gives AI assistants **powerful, token-efficient system access**. Not just command execution—**surgical file editing**, interactive REPL management, smart search, app launching, and AI debugging. All through a clean, reliable MCP interface.

**The killer feature:** Automated installation scripts that **educate your AI assistants** about available tools. iFlow and Gemini learn about TermPipe capabilities automatically—no manual explanation needed in every session.

## Why TermPipe MCP?

- 💰 **Token-Efficient** - Surgical editing tools that modify specific lines instead of rewriting entire files
- 🧠 **AI Education** - Assistants learn available tools automatically via memory files
- 🔧 **Comprehensive** - Terminal, files, processes, search, debugging—all in one package
- 🚀 **Auto-Start** - Optional systemd service for boot-time startup
- 🎯 **Battle-Tested** - 12 tool modules covering real automation needs
- ✅ **Just Works** - One command installation with auto-configuration

## Features

### 💰 Surgical File Operations (Save Tokens, Save Money)

Most MCP servers force AI to read entire files, modify them, and write them back. **TermPipe uses line-level precision:**

```python
# Change one line - no need to read/write entire file
replace_at_line("config.py", 42, "DEBUG = False", "DEBUG = True")

# Smart find-replace with diff preview
smart_replace("app.py", "old_function()", "new_function()")

# Insert at specific line
insert_lines("data.csv", 100, "new,data,row")

# Replace line range
replace_lines("output.txt", 50, 55, "new content")
```

**This saves massive amounts of tokens** compared to traditional read-entire-file/write-entire-file approaches.

### 🖥️ Terminal & Process Management

- **Command Execution** - Run shell commands with intelligent error handling
- **Natural Language** - Convert plain English to commands via iFlow API
- **Interactive REPLs** - Python, Node.js, R, Julia with persistent sessions
- **Process Management** - Start, interact, monitor, terminate

```python
# Data analysis workflow
start_process("python3 -i")
interact_with_process(pid, "import pandas as pd")
interact_with_process(pid, "df = pd.read_csv('data.csv')")
interact_with_process(pid, "print(df.describe())")
```

### 🔍 Smart Search (Stream-Based, Context-Friendly)

- **File Search** - Find files by name with glob patterns
- **Content Search** - Search inside files with streaming results
- **Pagination** - Get results in chunks, stop when you find what you need

```python
# Search for content across codebase
start_search("/home/user", "authentication", searchType="content")
get_more_search_results(session_id, 0, 50)  # Get first 50 results
```

### 🐛 AI-Powered Debugging

When edits fail or you're stuck, get help from other AI models:

```python
# Get debugging help from iFlow
debug_assist("File edit failed, getting unexpected results", "/path/file.py")

# Or get a second opinion from Gemini
gemini_debug("Can't figure out why this regex isn't matching", "/path/script.sh")
```

### 🚀 Additional Tools

- **App Launching** - Database of 900+ Linux applications
- **GUI Automation** - wbind integration for desktop control  
- **Thread Coordination** - Shared communication file for multi-agent workflows
- **System Info** - Configuration, usage stats, tool listing

### 🤖 AI-Powered Debugging (When You Get Stuck)

TermPipe includes intelligent debugging tools that leverage AI models to help when you're stuck:

**iFlow-Powered Tools:**
- `debug_assist` - AI analyzes your failed attempts and suggests specific fixes
- `analyze_file_structure` - Understand a file before editing it  
- `suggest_edit_approach` - Get step-by-step editing strategy

**Gemini-Powered Tools:**
- `gemini_debug` - Second-opinion debugging from Google's Gemini
- `gemini_analyze` - Alternative file analysis perspective
- `gemini_suggest` - Different edit strategy suggestions

```python
# When you're stuck on a failed edit
debug_assist(
    problem="My replace_at_line keeps failing with 'text not found'",
    file_path="/path/to/file.py",
    line_range=(40, 60)
)

# Get a second opinion from Gemini
gemini_debug(
    problem="Claude tried 5 times to edit this file - what am I missing?",
    file_path="/path/to/config.json"
)
```

**How It Works:**
- iFlow: Direct API integration, auto-detected from `~/.iflow/oauth_creds.json`
- Gemini: Calls `gemini -o text "prompt"` in non-interactive mode
- Both tools include recent tool call history for context
- Fast responses (1-3 seconds) perfect for debugging loops

**Pro Tip:** Use `debug_assist` or `gemini_debug` BEFORE retrying failed edits. Don't waste tokens on blind retries—get AI guidance first!


## Supported Clients

- **Claude Desktop** ✅
- **Claude Code** ✅ (with AI education)
- **iFlow CLI** ✅ (with AI education)
- **Gemini CLI** ✅ (with AI education)
- **Any MCP-compatible client** ✅




## Installation

### Method 1: Quick Install (Recommended)

**macOS / Linux:**
```bash
curl -sSL https://raw.githubusercontent.com/wbind-core/termpipe-mcp/master/quick-install.sh | bash
```

**Windows:**
```powershell
iwr -useb https://raw.githubusercontent.com/wbind-core/termpipe-mcp/master/quick-install.ps1 | iex
```

**Done.** Everything is auto-detected and configured. Zero manual steps.

---

### Method 2: Manual Install

```bash
git clone https://github.com/wbind-core/termpipe-mcp.git
cd termpipe-mcp
pipx install .
./quick-install.sh  # Still automated
```




## Configuration

**There is no configuration.** The installer auto-detects everything and configures all clients automatically.

If you need to manually add an iFlow API key later: `termcp setup`

That's it.



## Why TermPipe?

**Saves you money.** Surgical editing tools use 90% fewer tokens than rewriting entire files. Token-efficient operations mean lower API costs.

**AI-powered debugging.** Built-in iFlow and Gemini integration means when Claude gets stuck, it calls smarter models to get unstuck. No more retry loops burning your context.

**Zero friction.** One command installs everything. No JSON editing, no manual configuration, no bullshit.

**Actually works.** Persistent REPL sessions, smart search, process management, app launching - the tools you actually need for real work.

---

## Documentation

- **[INSTALL.md](INSTALL.md)** - Complete installation guide
- **[AUTOMATED_INSTALL.md](AUTOMATED_INSTALL.md)** - Installation scripts documentation
- **[VERIFICATION.md](VERIFICATION.md)** - Testing and troubleshooting
- **[SYSTEMD_SERVICE.md](SYSTEMD_SERVICE.md)** - Auto-start on boot setup

## Development

```bash
# Clone and install in dev mode
git clone https://github.com/wbind-core/termpipe-mcp.git
cd termpipe-mcp
pipx install -e .

# Make changes
vim termpipe_mcp/tools/mynewtool.py

# Reinstall
pipx install -e . --force

# Test
termcp server  # Start backend
# Then test via your MCP client
```

## Troubleshooting

### Server won't start
```bash
# Check if port 8421 is in use
lsof -i :8421

# View logs
journalctl --user -u termpipe-mcp -f  # If using systemd
tail -f ~/.termpipe-mcp/server.log    # Manual logs
```

### MCP tools not appearing
1. Restart your MCP client (Claude Desktop, iFlow CLI, etc.)
2. Check client logs for connection errors
3. Verify `termcp server` is running

### Import errors after installation
```bash
# Verify installation
pipx list | grep termpipe-mcp

# Reinstall if needed
cd /path/to/termpipe-mcp
pipx install . --force
```

## Requirements

- **Python 3.10+**
- **pipx** - For isolated package installation
- **jq** - For installation scripts (JSON manipulation)
- **Linux** - Primary platform (Ubuntu/Debian tested)

Install dependencies:
```bash
sudo apt install pipx jq  # Ubuntu/Debian
pipx ensurepath
```

## Why "Surgical" Matters

Traditional file operations in MCP:
```python
# Read entire 1000-line file (uses ~1000 tokens)
content = read_file("large_file.py")

# AI modifies it in context (uses more tokens)
modified = modify_content(content)

# Write entire file back (uses ~1000 tokens)
write_file("large_file.py", modified)

# Total: ~2000+ tokens for one line change
```

TermPipe surgical approach:
```python
# Change one line (uses ~10 tokens)
replace_at_line("large_file.py", 42, "old", "new")

# Total: ~10 tokens for one line change
```

**200x token reduction for common operations.** This adds up fast.

## License

MIT © 2026 Craig Nelson

## Contributing

Issues and pull requests welcome! This is a production tool being actively developed and used.

## Credits

Built with:
- [FastMCP](https://github.com/jlowin/fastmcp) - MCP server framework
- [FastAPI](https://fastapi.tiangolo.com/) - Backend server
- [httpx](https://www.python-httpx.org/) - HTTP client

Part of the [TermPipe](https://github.com/wbind-core) ecosystem.
