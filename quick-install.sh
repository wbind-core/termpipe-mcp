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

# Auto-detect MCP clients and configure them
echo "🔍 Auto-detecting MCP clients..."
echo ""

CLIENTS_FOUND=false

# Check for Claude Desktop
if [ -d "$HOME/.config/Claude" ]; then
    echo "✅ Found Claude Desktop"
    bash ./claude-desktop-install.sh
    CLIENTS_FOUND=true
    echo ""
fi

# Check for iFlow CLI
if [ -d "$HOME/.iflow" ]; then
    echo "✅ Found iFlow CLI"
    bash ./iflow-install.sh
    CLIENTS_FOUND=true
    echo ""
fi

# Check for Gemini CLI
if [ -d "$HOME/.gemini" ]; then
    echo "✅ Found Gemini CLI"
    bash ./gemini-install.sh
    CLIENTS_FOUND=true
    echo ""
fi

if [ "$CLIENTS_FOUND" = false ]; then
    echo "⚠️  No MCP clients detected on this system."
    echo ""
    echo "Available clients:"
    echo "  • Claude Desktop - https://claude.ai/download"
    echo "  • iFlow CLI - https://iflow.cn"
    echo "  • Gemini CLI - https://ai.google.dev"
    echo ""
    echo "Install a client and run this installer again."
    exit 0
fi

# Offer systemd service setup
echo "════════════════════════════════════════════════════════════"
echo "🚀 Auto-Start Setup (Optional)"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "Would you like to setup TermPipe MCP to start automatically on boot?"
echo ""
read -p "Enable auto-start? (Y/n): " -n 1 -r
echo
echo

if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
    bash ./systemd-setup.sh
else
    echo "Skipping systemd setup."
    echo ""
    echo "💡 You can enable it later by running:"
    echo "   cd $TEMP_DIR/termpipe-mcp && ./systemd-setup.sh"
fi

echo ""
echo "════════════════════════════════════════════════════════════"
echo "✅ TermPipe MCP installation complete!"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "🎉 Your AI assistant(s) now have intelligent system access!"
echo ""
