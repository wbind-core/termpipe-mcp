#!/bin/bash
# Claude Desktop TermPipe MCP Installation Script  
# Automatically configures TermPipe MCP server for Claude Desktop

set -e

echo "🚀 Installing TermPipe MCP for Claude Desktop..."
echo ""

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo "❌ Error: 'jq' is required but not installed."
    echo "   Install it with: sudo apt install jq"
    exit 1
fi

# Get configuration from environment or use defaults
CLAUDE_DIR="${CLAUDE_DESKTOP_DIR:-$HOME/.config/Claude}"
CONFIG_FILE="$CLAUDE_DIR/claude_desktop_config.json"
PIPX_PYTHON="$HOME/.local/share/pipx/venvs/termpipe-mcp/bin/python"

# Verify pipx installation
if [ ! -f "$PIPX_PYTHON" ]; then
    echo "❌ Error: TermPipe MCP not found at $PIPX_PYTHON"
    echo "   Run: pipx install /path/to/termpipe-mcp first"
    exit 1
fi

# Create Claude directory if it doesn't exist
mkdir -p "$CLAUDE_DIR"

# Initialize config file if it doesn't exist
if [ ! -f "$CONFIG_FILE" ]; then
    echo "{}" > "$CONFIG_FILE"
fi

# Check if termpipe is already configured
if jq -e '.mcpServers.termpipe' "$CONFIG_FILE" > /dev/null 2>&1; then
    echo "⚠️  TermPipe MCP already configured in Claude Desktop"
    read -p "   Overwrite? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "   Skipping configuration update"
        exit 0
    fi
fi

# Add/update TermPipe MCP configuration
echo "📝 Updating Claude Desktop config..."

# Create temporary file with updated config
jq --arg python_path "$PIPX_PYTHON" '
    .mcpServers.termpipe = {
        "command": $python_path,
        "args": ["-m", "termpipe_mcp.server"],
        "env": {
            "TERMCP_URL": "http://localhost:8421"
        }
    }
' "$CONFIG_FILE" > "$CONFIG_FILE.tmp"

mv "$CONFIG_FILE.tmp" "$CONFIG_FILE"
echo "   ✅ Configuration updated"

echo ""
echo "✅ Installation complete!"
echo ""
echo "Next steps:"
echo "1. Start the FastAPI server: termcp server"
echo "2. Restart Claude Desktop (quit completely and relaunch)"
echo "3. Claude will automatically connect to TermPipe MCP"
echo ""
