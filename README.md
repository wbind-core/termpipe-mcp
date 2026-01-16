# TermPipe MCP

> **Terminal automation that just works.** Production-ready MCP server for Claude Desktop, iFlow CLI, and Gemini CLI.

## What Is This?

TermPipe MCP gives AI assistants **direct, intelligent access to your terminal**. Execute commands, manage files, run REPLs, launch apps, and get AI-powered debugging assistance—all through a clean, reliable MCP interface.

**The killer feature:** Automated installation scripts that **educate your AI assistants** about available tools. iFlow and Gemini learn about TermPipe capabilities automatically—no manual explanation needed in every session.

## Why TermPipe MCP?

- ✅ **Just Works** - One command installation with auto-configuration
- 🧠 **AI Education** - Assistants learn available tools automatically  
- 🚀 **Auto-Start** - Optional systemd service for boot-time startup
- 🔧 **Battle-Tested** - 12 tool modules covering common automation needs
- 🎯 **Zero Config Conflicts** - Runs on port 8421, isolated from other tools
- 📝 **Comprehensive** - File ops, process management, search, debugging

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/wbind-core/termpipe-mcp.git
cd termpipe-mcp

# 2. Install
pipx install .

# 3. Run automated installer (configures your AI client + optional auto-start)
./install.sh

# That's it! Your AI assistant now has terminal access.
```

## Features

### 🔥 Core Capabilities

- **Command Execution** - Run shell commands with intelligent error handling
- **Natural Language** - Convert plain English to commands via iFlow API
- **Process Management** - Interactive REPLs (Python, Node.js, etc.) with persistent sessions
- **File Operations** - Read, write, surgical line-level editing
- **Smart Search** - Stream-based file and content search
- **App Launching** - Database of 900+ Linux applications
- **GUI Automation** - wbind integration for desktop control
- **AI Debugging** - iFlow and Gemini-powered debugging assistance

### 🎯 What Makes It Special

**Automated AI Education:** Installation scripts append comprehensive tool documentation to `~/.iflow/IFLOW.md` and `~/.gemini/GEMINI.md`. Your AI assistants know about TermPipe capabilities from day one—no repetitive explanations needed.

**Systemd Auto-Start:** Optional systemd service means the FastAPI backend starts on boot. Set it up once, never think about it again.

**Surgical Editing:** Line-level file editing tools that minimize token usage and prevent overwriting entire files unnecessarily.

## Supported Clients

- **Claude Desktop** ✅
- **iFlow CLI** ✅ (with AI education)
- **Gemini CLI** ✅ (with AI education)
- **Any MCP-compatible client** ✅

## Installation

### Method 1: Automated (Recommended)

```bash
git clone https://github.com/wbind-core/termpipe-mcp.git
cd termpipe-mcp
pipx install .
./install.sh
```

The installer:
- Configures your MCP client(s) automatically
- Educates AI assistants via memory files (iFlow/Gemini)
- Optionally sets up systemd service for auto-start
- Verifies everything works

### Method 2: Manual

```bash
git clone https://github.com/wbind-core/termpipe-mcp.git
cd termpipe-mcp
pipx install .
termcp setup  # Configure iFlow API key
termcp server # Start backend (keep running)
```

Then manually edit your MCP client config (see [INSTALL.md](INSTALL.md)).

## Configuration

### Get an iFlow API Key

Free tier available at: https://iflow.cn

The installer will prompt you for this, or run:
```bash
termcp setup
```

### MCP Client Setup

Installation scripts handle this automatically, but manual configs are documented in:
- [Claude Desktop setup](INSTALL.md#for-claude-desktop)
- [iFlow CLI setup](INSTALL.md#for-iflow-cli)
- [Gemini CLI setup](INSTALL.md#for-gemini-cli)

## Usage

After installation, your AI assistant has access to these tools:

```python
# Command execution
termf_exec("ls -lah /tmp")
termf_nlp("find all python files modified today")

# Process management (for data analysis, REPLs)
start_process("python3 -i")
interact_with_process(pid, "import pandas as pd")
interact_with_process(pid, "df = pd.read_csv('data.csv')")

# File operations
read_file("/path/to/file.txt", offset=100, length=50)
write_file("/path/to/file.txt", "new content")

# Surgical editing (minimal changes)
replace_at_line("/path/file.py", 42, "old_value = 1", "old_value = 2")
smart_replace("/path/file.py", "DEBUG = False", "DEBUG = True")

# Search
start_search("/home/user", "TODO", searchType="content")
get_more_search_results(session_id, offset=0, length=50)

# Debugging
debug_assist("File edit failed, getting unexpected results", "/path/file.py")
```

See [AUTOMATED_INSTALL.md](AUTOMATED_INSTALL.md) for tool documentation that gets added to AI memory files.

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
