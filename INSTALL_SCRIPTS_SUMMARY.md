# Installation Scripts - Summary

## Overview

Created **4 automated installation scripts** that make TermPipe MCP setup effortless and educate AI assistants about available tools.

## Scripts Created

### 1. `install.sh` (Master Script)
**Purpose:** Interactive installer with menu
**Size:** 3.8 KB
**Features:**
- Choose which client(s) to configure
- Can install for all clients at once
- Calls individual scripts as needed

**Usage:**
```bash
./install.sh
# Shows menu with options 1-5
```

### 2. `iflow-install.sh`
**Purpose:** Configure iFlow CLI
**Size:** 6.6 KB
**What it does:**
- ✅ Updates `~/.iflow/settings.json` with TermPipe MCP config
- ✅ Appends tool documentation to `~/.iflow/IFLOW.md`
- ✅ Educates iFlow about all TermPipe tools
- ✅ Safe: Won't overwrite without confirmation

**Result:** iFlow CLI knows about TermPipe tools in every session

### 3. `gemini-install.sh`
**Purpose:** Configure Gemini CLI
**Size:** 6.5 KB
**What it does:**
- ✅ Updates `~/.gemini/settings.json` with TermPipe MCP config
- ✅ Appends tool documentation to `~/.gemini/GEMINI.md`
- ✅ Educates Gemini about all TermPipe tools
- ✅ Safe: Won't overwrite without confirmation

**Result:** Gemini CLI knows about TermPipe tools in every session

### 4. `claude-desktop-install.sh`
**Purpose:** Configure Claude Desktop
**Size:** 2.8 KB
**What it does:**
- ✅ Updates `~/.config/Claude/claude_desktop_config.json`
- ✅ Uses dynamic username detection
- ✅ Safe: Won't overwrite without confirmation

**Result:** Claude Desktop has access to TermPipe tools (memories via GUI)

## What Gets Added to Memory Files

For iFlow and Gemini CLI, extensive documentation is appended to their memory files including:

### Tool Categories
1. **Command Execution** - termf_exec, termf_nlp
2. **Process Management** - start_process, interact_with_process, REPLs
3. **File Operations** - read_file, write_file, surgical editing
4. **Search** - start_search (file/content), streaming results
5. **App Launching** - 900+ Linux app database
6. **AI Debugging** - debug_assist, gemini_debug

### Critical Instructions
- **MANDATORY:** Call debug_assist/gemini_debug on ANY failed edit
- Use TermPipe for all local file operations
- Use process tools for data analysis (not browser tools)
- Prefer surgical editing over full rewrites

### Example Workflows
- Python REPL data analysis
- Surgical file editing
- Smart search operations

## Technical Implementation

### Safety Features
- **JSON-safe merging** via `jq` (not string replacement)
- **Idempotent** (can run multiple times safely)
- **Verification checks** (pipx installation, paths)
- **Interactive confirmation** for overwrites
- **Preserves existing configs**

### Dynamic Configuration
- Detects actual username (not hardcoded)
- Finds pipx venv path automatically
- Creates directories if missing
- Handles missing files gracefully

## Usage Examples

### Install for All Clients
```bash
cd /home/craig/termpipe-mcp
./install.sh
# Select option 4
```

### Install for Specific Client
```bash
# iFlow only
./iflow-install.sh

# Gemini only
./gemini-install.sh

# Claude Desktop only
./claude-desktop-install.sh
```

### Verify Installation
```bash
# Check iFlow config
cat ~/.iflow/settings.json | jq '.mcpServers.termpipe'

# Check iFlow memory file
grep -A 5 "TermPipe MCP Tools" ~/.iflow/IFLOW.md

# Check Gemini config
cat ~/.gemini/settings.json | jq '.mcpServers.termpipe'

# Check Claude Desktop config
cat ~/.config/Claude/claude_desktop_config.json | jq '.mcpServers.termpipe'
```

## Benefits

### For Users
- **1-command setup** instead of manual JSON editing
- **No mistakes** in JSON formatting
- **Safe** - won't break existing configurations
- **Fast** - takes seconds to run

### For AI Assistants
- **Pre-educated** about TermPipe capabilities
- **Knows best practices** from day one
- **Understands mandatory workflows** (debug_assist on failures)
- **Eliminates repetitive explanations** in every session

## Example Installation Session

```bash
$ cd /home/craig/termpipe-mcp
$ ./install.sh

╔════════════════════════════════════════════════════════════╗
║         TermPipe MCP - Client Installation Tool           ║
╚════════════════════════════════════════════════════════════╝

This script will configure TermPipe MCP for your MCP client(s).

Available clients:
  1) Claude Desktop
  2) iFlow CLI
  3) Gemini CLI
  4) All of the above
  5) Cancel

Select option (1-5): 2

🚀 Installing TermPipe MCP for iFlow CLI...

📝 Updating iFlow settings.json...
   ✅ Configuration updated

📚 Adding TermPipe documentation to IFLOW.md...
   ✅ Documentation added to /home/craig/.iflow/IFLOW.md

✅ Installation complete!

Next steps:
1. Start the FastAPI server: termcp server
2. Restart iFlow CLI or start a new session
3. iFlow will automatically have access to TermPipe tools
```

## Documentation Created

- **AUTOMATED_INSTALL.md** - Comprehensive guide (233 lines)
- **README.md** - Updated with automated installation section
- This summary document

## Files in Package

```
termpipe-mcp/
├── install.sh                  # Master interactive installer
├── iflow-install.sh            # iFlow CLI configuration
├── gemini-install.sh           # Gemini CLI configuration
├── claude-desktop-install.sh   # Claude Desktop configuration
├── AUTOMATED_INSTALL.md        # Complete documentation
└── README.md                   # Updated with quick start
```

## Success Criteria

✅ All 4 scripts created and executable
✅ Safe JSON merging with jq
✅ Comprehensive tool documentation added to memory files
✅ Interactive master script with menu
✅ Idempotent (can run multiple times)
✅ Dynamic path detection
✅ Verification checks
✅ Full documentation created
✅ README updated

## Impact

**Before:** Users had to manually:
1. Edit JSON files carefully
2. Find the correct pipx path
3. Explain TermPipe tools to AI in every session
4. Remember which tools exist
5. Risk JSON syntax errors

**After:** Users just run:
```bash
./install.sh
```

And AI assistants are **pre-educated** about TermPipe! 🎉
