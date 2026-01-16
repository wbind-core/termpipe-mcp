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



## Quick Start

**One command. All platforms.**

```bash
curl -sSL https://raw.githubusercontent.com/wbind-core/termpipe-mcp/master/quick-install.sh | bash
```

**What it does:**
1. Detects your OS (Linux, macOS, Windows/Git Bash)
2. Offers optional iFlow setup for AI debugging features
3. Installs TermPipe MCP via pipx
4. Auto-detects and configures all installed MCP clients
5. Sets up auto-start (systemd on Linux, launchd on macOS)

**Supported Platforms:**
- ✅ **Linux** - Ubuntu 20.04+, Debian 10+, Fedora, Arch
- ✅ **macOS** - 10.15+ (Catalina and newer)  
- ✅ **Windows** - Via Git Bash or WSL

**Supported Clients (auto-configured):**
- Claude Desktop
- Claude Code  
- iFlow CLI
- Gemini CLI

## Installation

### One-Line Install (Recommended)

```bash
curl -sSL https://raw.githubusercontent.com/wbind-core/termpipe-mcp/master/quick-install.sh | bash
```

### Manual Install

```bash
git clone https://github.com/wbind-core/termpipe-mcp.git
cd termpipe-mcp
pipx install .
./install.sh
```

Both methods:
- **Auto-detect** which MCP clients you have installed
- **Auto-configure** all detected clients (Claude Desktop, Claude Code, iFlow, Gemini)
- Educate AI assistants via memory files (Claude Code, iFlow, Gemini)
- Optionally set up systemd service for auto-start
- Verify everything works

**No manual JSON editing required!**


### Even More Manual

```bash
git clone https://github.com/wbind-core/termpipe-mcp.git
cd termpipe-mcp
pipx install .
termcp setup  # Configure iFlow API key
termcp server # Start backend (keep running)
```

Then manually edit your MCP client config (see [INSTALL.md](INSTALL.md)).


## Configuration

### AI Features Configuration

**iFlow API (Auto-Detected)**

iFlow credentials are automatically detected from any of:
1. `~/.termpipe-mcp/config.json` (TermPipe config)
2. `~/.iflow/settings.json` (iFlow CLI settings)  
3. `~/.iflow/oauth_creds.json` (iFlow OAuth - most common)

If you already have iFlow CLI installed and configured, **no additional setup needed**!

To manually configure:
```bash
termcp setup  # Prompts for API key
```

Free tier available at: https://iflow.cn

**Gemini CLI (Command-Line Based)**

Gemini tools work by calling the Gemini CLI in non-interactive mode: `gemini -o text "prompt"`

Requirements:
- Gemini CLI installed and configured
- Active Google account with AI Studio access

Install: https://ai.google.dev

No additional TermPipe configuration needed—just have Gemini CLI working.



### MCP Client Setup

Installation scripts handle this automatically, but manual configs are documented in:
- [Claude Desktop setup](INSTALL.md#for-claude-desktop)
- [iFlow CLI setup](INSTALL.md#for-iflow-cli)
- [Gemini CLI setup](INSTALL.md#for-gemini-cli)

## Usage Examples

### Surgical File Editing (Token-Efficient)

```python
# Read specific lines only
read_lines("config.py", 50, 60)

# Change one value - no full file rewrite
replace_at_line("settings.json", 15, '"debug": false', '"debug": true')

# Smart replace with automatic conflict detection
smart_replace("app.py", "old_api_call()", "new_api_call()")

# Insert without reading entire file
insert_lines("data.csv", 100, "new,row,data")
```

### Process Management

```python
# Start Python REPL for data analysis
pid = start_process("python3 -i")

# Interactive data analysis
interact_with_process(pid, "import pandas as pd")
interact_with_process(pid, "df = pd.read_csv('/data/large_file.csv')")
interact_with_process(pid, "print(df.groupby('category').sum())")

# Keep session alive between requests
read_process_output(pid)
```

### Command Execution

```python
# Direct command execution
termf_exec("find /tmp -name '*.log' -mtime -1")

# Natural language to command
termf_nlp("show me disk usage for the home directory")
```

### Smart Search

```python
# Search for files by name
start_search("/home/user", "*.py", searchType="files")

# Search for content across codebase
start_search("/project", "TODO|FIXME", searchType="content")

# Paginate through results
get_more_search_results(session_id, 0, 50)
get_more_search_results(session_id, 50, 50)
```

## Architecture

```
┌──────────────────┐
│  MCP Clients     │
│  - Claude Desktop│
│  - iFlow CLI     │
│  - Gemini CLI    │
└────────┬─────────┘
         │ MCP Protocol
         ▼
┌─────────────────────┐     HTTP          ┌──────────────────┐
│ termpipe-mcp        │ ◄───────────────► │ FastAPI Server   │
│ MCP Server          │  localhost:8421   │ (termcp server)  │
│ (12 tool modules)   │                   │                  │
└─────────────────────┘                   └──────────────────┘
```

**Two-component design:**
1. **MCP Server** - Auto-started by MCP clients, provides tool interface
2. **FastAPI Backend** - Runs on port 8421, handles command execution

**Port 8421** is used to avoid conflicts with the original TermPipe (port 8420).

## Tool Categories

### File Operations
- `read_file` - Read with pagination
- `write_file` - Write/overwrite
- `append_file` - Append content
- `read_lines` - Read specific line range
- `insert_lines` - Insert at line number
- `replace_lines` - Replace line range
- `replace_at_line` - **Most surgical** - change text on one line
- `smart_replace` - Intelligent find/replace with diff
- `delete_lines` - Delete line range
- `find_in_file` - Search with line numbers

### Process Management
- `start_process` - Start interactive sessions
- `interact_with_process` - Send input to REPL
- `read_process_output` - Read with pagination
- `list_sessions` - Show active sessions
- `force_terminate` - Kill process

### Command & Search
- `termf_exec` - Execute shell commands
- `termf_nlp` - Natural language to command
- `start_search` - Stream-based file/content search
- `get_more_search_results` - Paginate results
- `stop_search` - Stop active search

### AI & System
- `debug_assist` - iFlow-powered debugging
- `gemini_debug` - Gemini-powered debugging
- `launch_app` - Launch from 900+ app database
- `list_tools` - Show available tools
- `get_config` - View configuration
- `system_info` - System details

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
