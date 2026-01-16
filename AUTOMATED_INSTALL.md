# Automated Client Installation Scripts

TermPipe MCP includes automated installation scripts that configure your MCP clients and educate them about TermPipe tools.

## Quick Start

```bash
cd /path/to/termpipe-mcp
./install.sh
```

This interactive script lets you choose which client(s) to configure and optionally enables auto-start on boot via systemd.

## Individual Scripts

### Master Installer

```bash
./install.sh
```

**What it does:**
1. ✅ Interactive menu to select client(s) to configure
2. ✅ Calls individual client installation scripts
3. ✅ Offers to setup systemd service for auto-start on boot
4. ✅ Verifies installation and provides next steps

### Systemd Service Setup

```bash
./systemd-setup.sh
```

**What it does:**
1. ✅ Creates systemd user service at `~/.config/systemd/user/termpipe-mcp.service`
2. ✅ Enables service to start automatically on login
3. ✅ Optionally starts the service immediately
4. ✅ Shows service status and useful commands

**Result:** FastAPI server auto-starts on boot - no manual intervention needed!

## Individual Scripts

### iFlow CLI Installation

```bash
./iflow-install.sh
```

**What it does:**
1. ✅ Adds TermPipe MCP config to `~/.iflow/settings.json`
2. ✅ Appends comprehensive TermPipe documentation to `~/.iflow/IFLOW.md`
3. ✅ Detects existing configuration (won't overwrite without confirmation)
4. ✅ Uses actual username and verifies pipx installation path

**Result:** iFlow CLI will know about TermPipe tools in every session.

### Gemini CLI Installation

```bash
./gemini-install.sh
```

**What it does:**
1. ✅ Adds TermPipe MCP config to `~/.gemini/settings.json`
2. ✅ Appends comprehensive TermPipe documentation to `~/.gemini/GEMINI.md`
3. ✅ Detects existing configuration (won't overwrite without confirmation)
4. ✅ Uses actual username and verifies pipx installation path

**Result:** Gemini CLI will know about TermPipe tools in every session.

### Claude Desktop Installation

```bash
./claude-desktop-install.sh
```

**What it does:**
1. ✅ Adds TermPipe MCP config to `~/.config/Claude/claude_desktop_config.json`
2. ✅ Detects existing configuration (won't overwrite without confirmation)
3. ✅ Uses actual username and verifies pipx installation path

**Result:** Claude Desktop will have access to TermPipe tools (memories managed via GUI).

## Systemd Service (Auto-Start on Boot)

### Automatic Setup (via master installer)

The master `./install.sh` script will prompt you to setup systemd after client configuration.

### Manual Setup

```bash
./systemd-setup.sh
```

**What it creates:**
- Service file: `~/.config/systemd/user/termpipe-mcp.service`
- Auto-start on login/boot
- Automatic restart on failure
- Journal logging for debugging

**Useful systemd commands:**
```bash
# Check status
systemctl --user status termpipe-mcp

# View logs
journalctl --user -u termpipe-mcp -f

# Restart service
systemctl --user restart termpipe-mcp

# Stop service
systemctl --user stop termpipe-mcp

# Disable auto-start
systemctl --user disable termpipe-mcp
```

**Result:** TermPipe MCP FastAPI server runs automatically on every boot!

## Requirements

All scripts require:
- `jq` - JSON processor
  ```bash
  sudo apt install jq  # Ubuntu/Debian
  ```
- TermPipe MCP already installed via pipx
  ```bash
  pipx install /path/to/termpipe-mcp
  ```

## What Gets Added to IFLOW.md / GEMINI.md

The scripts add comprehensive documentation including:

### Core Capabilities Listed
- Command execution (termf_exec, termf_nlp)
- Process management (interactive REPLs)
- File operations (read, write, surgical editing)
- Search (file/content search)
- App launching (900+ Linux apps)
- AI debugging (debug_assist, gemini_debug)

### Best Practices
- MANDATORY: Call debug_assist/gemini_debug on ANY failed edit
- Use TermPipe for all local file operations
- Use start_process for data analysis with Python REPLs
- Prefer surgical editing over full file rewrites

### Example Workflows
```python
# Data analysis
start_process("python3 -i")
interact_with_process(pid, "import pandas as pd")
interact_with_process(pid, "df = pd.read_csv('file.csv')")
```

```bash
# Surgical editing
read_lines("config.py", 50, 60)
replace_at_line("config.py", 55, "old", "new")
```

## Configuration Format

### iFlow CLI Config Added

```json
{
  "mcpServers": {
    "termpipe": {
      "description": "TermPipe MCP - Terminal automation...",
      "command": "/home/USERNAME/.local/share/pipx/venvs/termpipe-mcp/bin/python",
      "args": ["-m", "termpipe_mcp.server"],
      "env": {
        "TERMCP_URL": "http://localhost:8421"
      }
    }
  }
}
```

### Gemini CLI Config Added

```json
{
  "mcpServers": {
    "termpipe": {
      "command": "/home/USERNAME/.local/share/pipx/venvs/termpipe-mcp/bin/python",
      "args": ["-m", "termpipe_mcp.server"],
      "env": {
        "TERMCP_URL": "http://localhost:8421"
      }
    }
  }
}
```

### Claude Desktop Config Added

```json
{
  "mcpServers": {
    "termpipe": {
      "command": "/home/USERNAME/.local/share/pipx/venvs/termpipe-mcp/bin/python",
      "args": ["-m", "termpipe_mcp.server"],
      "env": {
        "TERMCP_URL": "http://localhost:8421"
      }
    }
  }
}
```

## Safety Features

All scripts are **idempotent** and **safe**:

✅ **Won't overwrite existing configs without confirmation**
- Detects existing TermPipe configuration
- Prompts before overwriting

✅ **JSON-safe merging**
- Uses `jq` for proper JSON manipulation
- Preserves existing MCP servers and settings

✅ **Verification checks**
- Verifies pipx installation before proceeding
- Uses actual username (not hardcoded paths)
- Creates directories if they don't exist

✅ **No destructive operations**
- Only adds/updates, never deletes
- Appends to .md files (doesn't overwrite)

## Manual Alternative

If you prefer to configure manually, see:
- `INSTALL.md` - Step-by-step manual instructions
- Individual config examples in `README.md`

## Troubleshooting

### "jq not found"
```bash
sudo apt install jq
```

### "TermPipe MCP not found"
```bash
# Install first
pipx install /path/to/termpipe-mcp

# Verify installation
which termcp
```

### "Settings file not found"
Scripts will create the necessary directories and files automatically.

### Want to update documentation only
Just run the script again and say "No" when asked to overwrite config, then "Yes" for documentation.

## Post-Installation

After running any install script:

1. **Start the FastAPI server:**
   ```bash
   termcp server
   ```

2. **Restart your MCP client:**
   - Claude Desktop: Quit and relaunch
   - iFlow CLI: Start a new session
   - Gemini CLI: Start a new session

3. **Test:**
   Ask your client: "Use termpipe to list files in my home directory"

## Benefits of Automated Installation

### For Users
- ⚡ One command setup
- 📝 No manual JSON editing
- 🛡️ Safe (won't break existing configs)
- ✅ Verified installation paths

### For AI Assistants
- 📚 Educated about TermPipe from day one
- 🎯 Knows which tools to use when
- 🔧 Understands best practices
- ⚠️ Knows mandatory debugging workflow

This eliminates the need for users to manually explain TermPipe capabilities in every session!
