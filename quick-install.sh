#!/bin/bash
# TermPipe MCP One-Command Installer
# Usage: curl -sSL https://raw.githubusercontent.com/wbind-core/termpipe-mcp/master/quick-install.sh | bash

set -e

echo "╔════════════════════════════════════════════════════════════╗"
echo "║         TermPipe MCP - One-Command Installation           ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Check dependencies
if ! command -v pipx &> /dev/null; then
    echo "❌ Error: pipx is required but not installed."
    echo "   Install it with: sudo apt install pipx && pipx ensurepath"
    exit 1
fi

if ! command -v jq &> /dev/null; then
    echo "❌ Error: jq is required but not installed."
    echo "   Install it with: sudo apt install jq"
    exit 1
fi

if ! command -v git &> /dev/null; then
    echo "❌ Error: git is required but not installed."
    echo "   Install it with: sudo apt install git"
    exit 1
fi

# Create temp directory
TEMP_DIR=$(mktemp -d)
cd "$TEMP_DIR"

echo "📦 Cloning TermPipe MCP..."
git clone --quiet https://github.com/wbind-core/termpipe-mcp.git
cd termpipe-mcp

echo "🔧 Installing package..."
pipx install . --force > /dev/null 2>&1

echo "✅ Package installed!"
echo ""

# Run the interactive installer
exec ./install.sh
