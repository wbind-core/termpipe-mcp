# TermPipe MCP Server

Standalone MCP server that provides MCP clients (Claude Desktop, iFlow CLI, etc.) with powerful terminal automation, file operations, and intelligent command execution.

## Features

- **Command Execution**: Run shell commands with intelligent error handling
- **Natural Language Processing**: Convert plain English to terminal commands
- **Process Management**: Interactive REPLs (Python, Node, etc.) with persistent sessions
- **File Operations**: Read, write, search, and surgical editing
- **App Launching**: Database of 900+ Linux applications
- **GUI Automation**: wbind integration for desktop control
- **AI Debugging**: iFlow and Gemini-powered debugging assistance

## Architecture

This package is completely self-contained and consists of two components:

1. **FastAPI Server** (`termcp server`) - Lightweight backend for command execution and NLP (port 8421)
2. **MCP Server** (auto-started by MCP clients) - Tool interface for any MCP client

**Note:** TermPipe MCP uses port 8421 to avoid conflict with the main TermPipe server (port 8420).

**Supported MCP Clients:**
- Claude Desktop
- iFlow CLI
- Gemini CLI
- Any other MCP-compatible client

## Installation

### Automated Installation (Recommended)

The easiest way to get started:

```bash
# 1. Install the package
pipx install /path/to/termpipe-mcp

# 2. Run the automated installer
cd /path/to/termpipe-mcp
./install.sh
```

The installer will:
- Configure your MCP client(s) automatically
- Add TermPipe documentation to iFlow/Gemini memory files
- Optionally setup systemd service for auto-start on boot
- Verify your installation

See [AUTOMATED_INSTALL.md](AUTOMATED_INSTALL.md) for details.

### Manual Installation

```bash
# Install the package
pipx install /path/to/termpipe-mcp

# Start the FastAPI backend (in a terminal)
termcp server

# Your MCP client will auto-connect to the MCP server
```

See [INSTALL.md](INSTALL.md) for detailed manual setup instructions.

## Configuration

### For Claude Desktop

Add to `~/.config/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "termpipe": {
      "command": "/home/YOUR_USERNAME/.local/share/pipx/venvs/termpipe-mcp/bin/python",
      "args": ["-m", "termpipe_mcp.server"],
      "env": {
        "TERMCP_URL": "http://localhost:8421"
      }
    }
  }
}
```

### For iFlow CLI

Add to `~/.iflow/settings.json`:

```json
{
  "mcpServers": {
    "termpipe": {
      "description": "TermPipe MCP - Terminal automation, file operations, and AI-powered command execution",
      "command": "/home/YOUR_USERNAME/.local/share/pipx/venvs/termpipe-mcp/bin/python",
      "args": ["-m", "termpipe_mcp.server"],
      "env": {
        "TERMCP_URL": "http://localhost:8421"
      }
    }
  }
}
```

### For Gemini CLI

Add to `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "termpipe": {
      "command": "/home/YOUR_USERNAME/.local/share/pipx/venvs/termpipe-mcp/bin/python",
      "args": ["-m", "termpipe_mcp.server"],
      "env": {
        "TERMCP_URL": "http://localhost:8421"
      }
    }
  }
}
```

### API Configuration (Required)

```json
{
  "api_key": "YOUR_IFLOW_API_KEY",
  "api_base": "https://apis.iflow.cn/v1",
  "default_model": "qwen3-coder-plus"
}
```

Get a free iFlow API key at: https://iflow.cn

## Usage

### Start the Backend

```bash
# Start the FastAPI server (required)
termcp server
```

Leave this running in a terminal. It provides the execution backend.

### Use in MCP Clients

Once both servers are running, your MCP client (Claude Desktop, iFlow CLI, Gemini CLI, etc.) has access to all TermPipe tools:

- File operations: `read_file`, `write_file`, `edit_block`
- Process management: `start_process`, `interact_with_process`
- Command execution: `termf_exec`, `termf_nlp`
- Search: `start_search`, `get_more_search_results`
- Debugging: `debug_assist`, `gemini_debug`

## Development

```bash
# Install in development mode
cd termpipe-mcp
pipx install -e . --force

# Run tests
pytest

# Format code
black termpipe_mcp/
```

## Troubleshooting

### FastAPI server not connecting

```bash
# Check if server is running
curl http://localhost:8421/health

# Start manually
termcp server

# Check logs
tail -f ~/.termpipe-mcp/server.log
```

### MCP tools not working

1. Ensure FastAPI server is running (`termcp server`)
2. Check Claude Desktop logs
3. Verify config.json has valid API key

## License

MIT © 2026 Craig Nelson
