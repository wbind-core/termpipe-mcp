#!/bin/bash
# Gemini CLI TermPipe MCP Installation Script
# Automatically configures TermPipe MCP server for Gemini CLI

set -e

echo "🚀 Installing TermPipe MCP for Gemini CLI..."
echo ""

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo "❌ Error: 'jq' is required but not installed."
    echo "   Install it with: sudo apt install jq"
    exit 1
fi

# Get actual username
USERNAME=$(whoami)
GEMINI_DIR="$HOME/.gemini"
SETTINGS_FILE="$GEMINI_DIR/settings.json"
GEMINI_MD="$GEMINI_DIR/GEMINI.md"
PIPX_PYTHON="/home/$USERNAME/.local/share/pipx/venvs/termpipe-mcp/bin/python"

# Verify pipx installation
if [ ! -f "$PIPX_PYTHON" ]; then
    echo "❌ Error: TermPipe MCP not found at $PIPX_PYTHON"
    echo "   Run: pipx install /path/to/termpipe-mcp first"
    exit 1
fi

# Create Gemini directory if it doesn't exist
mkdir -p "$GEMINI_DIR"

# Initialize settings.json if it doesn't exist
if [ ! -f "$SETTINGS_FILE" ]; then
    echo "{}" > "$SETTINGS_FILE"
fi

# Check if termpipe is already configured
if jq -e '.mcpServers.termpipe' "$SETTINGS_FILE" > /dev/null 2>&1; then
    echo "⚠️  TermPipe MCP already configured in Gemini CLI"
    read -p "   Overwrite? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "   Skipping configuration update"
        SKIP_CONFIG=true
    fi
fi

# Add/update TermPipe MCP configuration
if [ "$SKIP_CONFIG" != "true" ]; then
    echo "📝 Updating Gemini settings.json..."
    
    # Create temporary file with updated config
    jq --arg python_path "$PIPX_PYTHON" '
        .mcpServers.termpipe = {
            "command": $python_path,
            "args": ["-m", "termpipe_mcp.server"],
            "env": {
                "TERMCP_URL": "http://localhost:8421"
            }
        }
    ' "$SETTINGS_FILE" > "$SETTINGS_FILE.tmp"
    
    mv "$SETTINGS_FILE.tmp" "$SETTINGS_FILE"
    echo "   ✅ Configuration updated"
fi

# Add TermPipe documentation to GEMINI.md
echo ""
echo "📚 Adding TermPipe documentation to GEMINI.md..."

# Check if already documented
if [ -f "$GEMINI_MD" ] && grep -q "TermPipe MCP Tools" "$GEMINI_MD" 2>/dev/null; then
    echo "   ⚠️  TermPipe documentation already exists in GEMINI.md"
    read -p "   Append updated docs? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "   Skipping documentation update"
        SKIP_DOCS=true
    fi
fi

if [ "$SKIP_DOCS" != "true" ]; then
    cat >> "$GEMINI_MD" << 'EOF'

---

## TermPipe MCP Tools

You have access to the TermPipe MCP server, which provides powerful terminal automation and file operation capabilities.

### Core Capabilities

**Command Execution:**
- `termf_exec(command, timeout_ms)` - Execute shell commands
- `termf_nlp(instruction)` - Convert natural language to commands
  - Example: "find all python files modified today"

**Process Management:**
- `start_process(command)` - Start interactive REPLs (Python, Node, etc.)
- `interact_with_process(pid, input)` - Send input to running process
- `read_process_output(pid)` - Read process output
- `list_sessions()` - Show active sessions
- `force_terminate(pid)` - Kill a process

**File Operations:**
- `read_file(path, offset, length)` - Read files with pagination
- `write_file(path, content)` - Write/overwrite files
- `append_file(path, content)` - Append to files
- `list_directory(path)` - List directory contents
- `glob_files(pattern, path)` - Find files by pattern
- `search_file_content(path, pattern)` - Search within files
- `get_file_info(path)` - Get file metadata
- `move_file(source, destination)` - Move/rename files

**Surgical File Editing:**
- `read_lines(path, start_line, end_line)` - Read specific lines
- `insert_lines(path, line_number, content)` - Insert at line
- `replace_lines(path, start_line, end_line, content)` - Replace lines
- `replace_at_line(path, line_number, old_text, new_text)` - Most surgical tool
- `smart_replace(path, old_text, new_text)` - Intelligent find/replace with diff
- `delete_lines(path, start_line, end_line)` - Delete line range
- `find_in_file(path, pattern, context)` - Find with line numbers

**Search:**
- `start_search(path, pattern, searchType)` - Stream-based search
  - searchType: "files" (by name) or "content" (inside files)
- `get_more_search_results(sessionId, offset, length)` - Paginate results
- `stop_search(sessionId)` - Stop active search

**App Launching:**
- `launch_app(app_name)` - Launch apps from 900+ app database
- `list_apps(filter_term)` - Search available apps

**AI Debugging:**
- `debug_assist(problem, file_path)` - iFlow-powered debugging help
- `gemini_debug(problem, file_path)` - Gemini-powered debugging help

**System:**
- `get_config()` - Get TermPipe configuration
- `system_info()` - Get system information
- `list_tools(category)` - List available tools

### Important Notes

**MANDATORY: On ANY failed edit attempt, you MUST call `debug_assist` or `gemini_debug` BEFORE your next attempt. Do not retry manually first. ZERO EXCEPTIONS!**

**Best Practices:**
- Always use TermPipe for local file operations and command execution
- Use `start_process` + `interact_with_process` for data analysis (Python REPLs)
- Prefer surgical editing tools over full file rewrites
- Use `smart_replace` for intelligent edits with automatic diff preview
- For complex research needing 20+ tool calls, suggest the Research feature

**File Analysis Priority:**
1. ALWAYS FIRST: Use TermPipe process tools for local data analysis
2. ALTERNATIVE: Use command-line tools (cut, awk, grep)
3. NEVER: Use browser-based tools for local file access (they WILL FAIL)

**Example Workflows:**

```python
# Data analysis with Python REPL
start_process("python3 -i")
interact_with_process(pid, "import pandas as pd")
interact_with_process(pid, "df = pd.read_csv('/path/file.csv')")
interact_with_process(pid, "print(df.describe())")
```

```bash
# Surgical file editing
read_lines("config.py", 50, 60)  # Check context
replace_at_line("config.py", 55, "DEBUG = False", "DEBUG = True")
```

```bash
# Smart search
start_search("/home/user", "authentication", searchType="content")
get_more_search_results(session_id, 0, 50)
```

EOF
    echo "   ✅ Documentation added to $GEMINI_MD"
fi

echo ""
echo "✅ Installation complete!"
echo ""
echo "Next steps:"
echo "1. Start the FastAPI server: termcp server"
echo "2. Restart Gemini CLI or start a new session"
echo "3. Gemini will automatically have access to TermPipe tools"
echo ""
echo "Test it by asking Gemini:"
echo '   "Use termpipe to list files in my home directory"'
echo ""
