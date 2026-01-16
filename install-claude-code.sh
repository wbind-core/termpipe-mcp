#!/bin/bash
#!/bin/bash
# TermPipe MCP - Claude Code Installation Script (Cross-Platform)

set -e

USERNAME=$(whoami)

# Use environment variable if available, otherwise default to Linux path
CLAUDE_DIR="${CLAUDE_CODE_DIR:-$HOME/.claude}"
CLAUDE_CODE_CONFIG="$CLAUDE_DIR/claude.json"
CLAUDE_MD="$CLAUDE_DIR/CLAUDE.md"

# Cross-platform Python path (no hardcoded /home/)
PYTHON_PATH="$HOME/.local/share/pipx/venvs/termpipe-mcp/bin/python"
TERMCP_MARKER="# TermPipe MCP Documentation"

echo "════════════════════════════════════════════════════════════"
echo "TermPipe MCP - Claude Code Configuration"
echo "════════════════════════════════════════════════════════════"
echo ""

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo "❌ Error: jq is required but not installed"
    echo "   Install with: sudo apt install jq"
    exit 1
fi

# Verify pipx installation
if [ ! -f "$PYTHON_PATH" ]; then
    echo "❌ Error: TermPipe MCP not found at $PYTHON_PATH"
    echo "   Run: pipx install /path/to/termpipe-mcp"
    exit 1
fi

# Create ~/.claude directory if it doesn't exist
mkdir -p "$(dirname "$CLAUDE_CODE_CONFIG")"
mkdir -p "$(dirname "$CLAUDE_MD")"

# Check if TermPipe is already configured
if [ -f "$CLAUDE_CODE_CONFIG" ] && jq -e '.mcpServers.termpipe' "$CLAUDE_CODE_CONFIG" > /dev/null 2>&1; then
    echo "⚠️  TermPipe MCP is already configured in Claude Code"
    read -p "   Overwrite existing configuration? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "   Skipping Claude Code configuration"
        exit 0
    fi
fi

# Configure MCP server in ~/.claude.json
echo "📝 Configuring MCP server..."

if [ ! -f "$CLAUDE_CODE_CONFIG" ]; then
    # Create new config file
    cat > "$CLAUDE_CODE_CONFIG" << EOF
{
  "mcpServers": {
    "termpipe": {
      "command": "$PYTHON_PATH",
      "args": ["-m", "termpipe_mcp.server"],
      "env": {
        "TERMCP_URL": "http://localhost:8421"
      }
    }
  }
}
EOF
else
    # Merge with existing config using jq
    jq --arg python_path "$PYTHON_PATH" '.mcpServers.termpipe = {
      "command": $python_path,
      "args": ["-m", "termpipe_mcp.server"],
      "env": {
        "TERMCP_URL": "http://localhost:8421"
      }
    }' "$CLAUDE_CODE_CONFIG" > "$CLAUDE_CODE_CONFIG.tmp"
    mv "$CLAUDE_CODE_CONFIG.tmp" "$CLAUDE_CODE_CONFIG"
fi

echo "   ✅ MCP server configured in $CLAUDE_CODE_CONFIG"

# Add documentation to CLAUDE.md
echo ""
echo "📚 Adding TermPipe documentation to CLAUDE.md..."

# Check if documentation already exists
if [ -f "$CLAUDE_MD" ] && grep -q "$TERMCP_MARKER" "$CLAUDE_MD"; then
    echo "   ⚠️  TermPipe documentation already exists in CLAUDE.md"
    read -p "   Overwrite existing documentation? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "   Skipping CLAUDE.md update"
    else
        # Remove old documentation
        sed -i "/^$TERMCP_MARKER/,/^# End TermPipe MCP Documentation/d" "$CLAUDE_MD"
    fi
fi

# Append documentation (only if we didn't skip)
if [ ! -f "$CLAUDE_MD" ] || ! grep -q "$TERMCP_MARKER" "$CLAUDE_MD"; then
    cat >> "$CLAUDE_MD" << 'EOFMD'

# TermPipe MCP Documentation

## Available TermPipe Tools

TermPipe MCP provides intelligent system automation with token-efficient operations.

### Command Execution
- **termf_exec** - Execute shell commands
- **termf_nlp** - Natural language to command translation

### File Operations (Surgical - Token-Efficient)
- **read_file** - Read with pagination (offset, length)
- **write_file** - Write/overwrite
- **append_file** - Append content
- **read_lines** - Read specific line range
- **insert_lines** - Insert at line number
- **replace_lines** - Replace line range
- **replace_at_line** - **MOST SURGICAL** - change text on one specific line
- **smart_replace** - Intelligent find/replace with diff preview
- **delete_lines** - Delete line range
- **find_in_file** - Search with line numbers and context
- **read_multiple_files** - Read multiple files at once
- **list_directory** - List directory contents (recursive with depth)
- **glob_files** - Find files by glob pattern
- **search_file_content** - Grep-style content search
- **get_file_info** - Get file metadata
- **move_file** - Move or rename files
- **create_directory** - Create directories

### Process Management
- **start_process** - Start interactive REPLs (Python, Node.js, etc.)
- **interact_with_process** - Send input to running process
- **read_process_output** - Read output with pagination
- **list_sessions** - Show active processes
- **force_terminate** - Kill process by PID
- **list_processes** - Show all running processes

### Search (Stream-Based)
- **start_search** - Begin file/content search
- **get_more_search_results** - Paginate through results
- **stop_search** - Stop active search
- **list_searches** - Show active searches

### AI Debugging
- **debug_assist** - iFlow-powered debugging help
- **gemini_debug** - Gemini-powered debugging help
- **analyze_file_structure** - AI analysis of file structure
- **suggest_edit_approach** - AI suggests best editing approach

### App Launching & GUI
- **launch_app** - Launch from 900+ app database
- **list_apps** - Show available apps
- **wbind_action** - GUI automation actions
- **wbind_launch_and_focus** - Launch and focus apps

### System & Coordination
- **thread_log** - Log to coordination thread
- **thread_read** - Read coordination messages
- **system_info** - Get system information
- **get_config** - View TermPipe configuration
- **get_recent_tool_calls** - See tool call history
- **list_tools** - List available tools by category

## Critical Usage Rules

### MANDATORY: Debug Assist Workflow
**On ANY failed edit attempt, you MUST call debug_assist or gemini_debug BEFORE retrying manually.**
**ZERO EXCEPTIONS!**

Example workflow:
```
1. Attempt file edit → fails
2. IMMEDIATELY call: debug_assist("Edit failed with error X", "/path/file.py")
3. Review AI suggestions
4. Retry with improved approach
```

### Token-Efficient Editing Priority
**Always use the most surgical tool possible:**

1. **replace_at_line** - For single-line changes (most efficient)
2. **smart_replace** - For find/replace operations
3. **replace_lines** - For multi-line range replacement
4. **read_lines + write_file** - Only when bulk changes needed

**Example - Change one value:**
```
❌ BAD (wastes tokens):
   content = read_file("config.py")  # Read entire 1000-line file
   modified = modify_content(content)
   write_file("config.py", modified)  # Write entire file

✅ GOOD (token-efficient):
   replace_at_line("config.py", 42, "DEBUG = False", "DEBUG = True")
```

### Process Management for Data Analysis
**Use interactive REPLs instead of one-off commands:**

```python
# Start Python REPL
start_process("python3 -i")

# Load data
interact_with_process(pid, "import pandas as pd")
interact_with_process(pid, "df = pd.read_csv('data.csv')")

# Analyze (session persists)
interact_with_process(pid, "print(df.describe())")
interact_with_process(pid, "df.groupby('column').sum()")
```

### Smart Search Patterns
```python
# Search for files by name
start_search("/project", "*.py", searchType="files")

# Search for content across codebase  
start_search("/project", "authentication", searchType="content")

# Paginate results
get_more_search_results(session_id, 0, 50)
```

## Best Practices

1. **Prefer surgical tools** - Save tokens, save money
2. **Use debug_assist liberally** - When stuck or errors occur
3. **Keep REPL sessions alive** - For iterative data analysis
4. **Paginate large results** - Don't load everything at once
5. **Use start_search for exploration** - Stream-based, can stop early

## Server Requirements

TermPipe MCP requires the FastAPI backend to be running:
```bash
termcp server  # Start in terminal, keep running
```

Or enable systemd auto-start:
```bash
systemctl --user status termpipe-mcp
```

# End TermPipe MCP Documentation
EOFMD
    echo "   ✅ Documentation added to $CLAUDE_MD"
fi

echo ""
echo "════════════════════════════════════════════════════════════"
echo "✅ Claude Code configuration complete!"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "📋 Next Steps:"
echo ""
echo "1. Restart Claude Code (if currently running)"
echo "2. Start TermPipe server: termcp server"
echo "3. Claude Code will now have access to TermPipe tools!"
echo ""
echo "💡 Note: The CLAUDE.md memory file educates Claude Code about"
echo "   TermPipe tools automatically in every session."
echo ""
