# TermPipe MCP Installation Guide

Complete guide for installing and configuring the TermPipe MCP Server.

## Prerequisites

- Python 3.10 or higher
- `pipx` package manager
- An MCP client (Claude Desktop, iFlow CLI, or other)

## Step 1: Install pipx (if needed)

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
```

Restart your terminal after installation.

## Step 2: Install TermPipe MCP

```bash
cd /path/to/termpipe-mcp
pipx install . --force
```

This installs:
- The `termcp` command-line tool
- The FastAPI backend server
- The MCP server for Claude Desktop
- All tool modules

## Step 3: Configure API Key

Run the interactive setup:

```bash
termcp setup
```

Enter your iFlow API key (get one free at https://iflow.cn).

Or manually create `~/.termpipe-mcp/config.json`:

```json
{
  "api_key": "YOUR_IFLOW_API_KEY",
  "api_base": "https://apis.iflow.cn/v1",
  "default_model": "qwen3-coder-plus",
  "server_port": 8421,
  "server_host": "127.0.0.1"
}
```

## Step 4: Start the FastAPI Server

Open a terminal and run:

```bash
termcp server
```

Leave this running. You should see:

```
🚀 Starting TermPipe FastAPI server on 127.0.0.1:8421
   API docs: http://127.0.0.1:8421/docs
   Health check: http://127.0.0.1:8421/health

Press Ctrl+C to stop
```

Test it's working:

```bash
curl http://localhost:8421/health
```

## Step 5: Configure Claude Desktop

Edit `~/.config/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "termpipe": {
      "command": "YOUR_PIPX_VENV_PATH/bin/python",
      "args": ["-m", "termpipe_mcp.server"],
      "env": {
        "TERMCP_URL": "http://localhost:8421"
      }
    }
  }
}
```

To find your pipx venv path:

```bash
pipx list | grep termpipe-mcp
```

It will show something like:
```
   package termpipe-mcp 2.0.0, installed using Python 3.12.7
   - termcp
```

The full path is typically:
```
/home/YOUR_USERNAME/.local/share/pipx/venvs/termpipe-mcp/bin/python
```

### For iFlow CLI

Edit `~/.iflow/settings.json` and add to the `mcpServers` section:

```json
"termpipe": {
  "description": "TermPipe MCP - Terminal automation, file operations, and AI-powered command execution",
  "command": "/home/YOUR_USERNAME/.local/share/pipx/venvs/termpipe-mcp/bin/python",
  "args": ["-m", "termpipe_mcp.server"],
  "env": {
    "TERMCP_URL": "http://localhost:8421"
  }
}
```

Replace `YOUR_USERNAME` with your actual username.

### For Gemini CLI

Edit `~/.gemini/settings.json` and add to the `mcpServers` section:

```json
"termpipe": {
  "command": "/home/YOUR_USERNAME/.local/share/pipx/venvs/termpipe-mcp/bin/python",
  "args": ["-m", "termpipe_mcp.server"],
  "env": {
    "TERMCP_URL": "http://localhost:8421"
  }
}
```

Replace `YOUR_USERNAME` with your actual username.

## Step 6: Restart Your MCP Client

### For Claude Desktop

1. Quit Claude Desktop completely
2. Start Claude Desktop again
3. The MCP server will automatically connect

### For iFlow CLI

The iFlow CLI will automatically pick up the new configuration on next use.

### For Gemini CLI

The Gemini CLI will automatically pick up the new configuration on next use.

## Verification

### In Claude Desktop

Ask Claude:

> "Can you use termpipe to list the files in my home directory?"

Claude should use the `termf_exec` or similar tool to execute the command.

### In iFlow CLI

The iFlow CLI will have access to all TermPipe tools when connected.

### In Gemini CLI

The Gemini CLI will have access to all TermPipe tools when connected.

## Troubleshooting

### FastAPI server not starting

```bash
# Check if port 8421 is already in use
lsof -i :8421

# Try a different port in config.json
{
  "server_port": 8422
}

# Update Claude Desktop config to match:
"TERMCP_URL": "http://localhost:8422"
```

### MCP server not connecting

1. Check your MCP client logs:
   ```bash
   # For Claude Desktop
   tail -f ~/.config/Claude/logs/mcp*.log
   
   # For iFlow CLI
   # Check iFlow CLI output/logs
   
   # For Gemini CLI
   # Check Gemini CLI output/logs
   ```

2. Verify FastAPI server is running:
   ```bash
   termcp status
   ```

3. Check config file path is correct in your MCP client configuration

### API key errors

```bash
# Verify config exists
cat ~/.termpipe-mcp/config.json

# Re-run setup
termcp setup
```

### Tools not working

Make sure the FastAPI server is running:

```bash
termcp server
```

The MCP server needs this backend to execute commands.

## Updating

To update the installation:

```bash
cd /path/to/termpipe-mcp
git pull  # if using git
pipx install . --force
```

Restart both the FastAPI server and your MCP client (Claude Desktop, iFlow CLI, Gemini CLI, etc.).

## Uninstalling

```bash
# Remove the package
pipx uninstall termpipe-mcp

# Remove configuration (optional)
rm -rf ~/.termpipe-mcp

# Remove from MCP client config
# For Claude Desktop: edit ~/.config/Claude/claude_desktop_config.json
# For iFlow CLI: edit ~/.iflow/settings.json
# For Gemini CLI: edit ~/.gemini/settings.json
```

## Optional: Systemd Service

To have the FastAPI server start automatically, create a systemd service:

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/termpipe-mcp.service << 'EOF'
[Unit]
Description=TermPipe MCP FastAPI Server
After=network.target

[Service]
Type=simple
ExecStart=/home/YOUR_USERNAME/.local/bin/termcp server
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

# Enable and start
systemctl --user daemon-reload
systemctl --user enable termpipe-mcp
systemctl --user start termpipe-mcp

# Check status
systemctl --user status termpipe-mcp
```

## Getting Help

- Check logs: `~/.termpipe-mcp/server.log`
- Server status: `termcp status`
- Test API: `curl http://localhost:8421/health`
- MCP client logs:
  - Claude Desktop: `~/.config/Claude/logs/`
  - iFlow CLI: Check CLI output
  - Gemini CLI: Check CLI output

## Next Steps

Once installed, you can:

- Execute shell commands through Claude
- Use natural language to generate commands
- Manage interactive processes (Python REPLs, etc.)
- Perform surgical file editing
- Search files and directories
- Launch applications
- Get AI-powered debugging help

Enjoy! 🚀
