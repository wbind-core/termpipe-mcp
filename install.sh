#!/bin/bash
# TermPipe MCP Master Installation Script
# Configure TermPipe MCP for one or more MCP clients

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "╔════════════════════════════════════════════════════════════╗"
echo "║         TermPipe MCP - Client Installation Tool           ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "This script will configure TermPipe MCP for your MCP client(s)."
echo ""
echo "Available clients:"
echo "  1) Claude Desktop"
echo "  2) iFlow CLI"
echo "  3) Gemini CLI"
echo "  4) All of the above"
echo "  5) Cancel"
echo ""

read -p "Select option (1-5): " choice

case $choice in
    1)
        echo ""
        bash "$SCRIPT_DIR/claude-desktop-install.sh"
        ;;
    2)
        echo ""
        bash "$SCRIPT_DIR/iflow-install.sh"
        ;;
    3)
        echo ""
        bash "$SCRIPT_DIR/gemini-install.sh"
        ;;
    4)
        echo ""
        echo "Installing for all clients..."
        echo ""
        echo "═══════════════════════════════════════════════════════════"
        echo "1/3: Claude Desktop"
        echo "═══════════════════════════════════════════════════════════"
        bash "$SCRIPT_DIR/claude-desktop-install.sh"
        
        echo ""
        echo "═══════════════════════════════════════════════════════════"
        echo "2/3: iFlow CLI"
        echo "═══════════════════════════════════════════════════════════"
        bash "$SCRIPT_DIR/iflow-install.sh"
        
        echo ""
        echo "═══════════════════════════════════════════════════════════"
        echo "3/3: Gemini CLI"
        echo "═══════════════════════════════════════════════════════════"
        bash "$SCRIPT_DIR/gemini-install.sh"
        
        echo ""
        echo "✅ All clients configured!"
        ;;
    5)
        echo "Installation cancelled."
        exit 0
        ;;
    *)
        echo "Invalid option. Exiting."
        exit 1
        ;;
esac

# Offer to setup systemd service
echo ""
echo "════════════════════════════════════════════════════════════"
echo "🚀 Auto-Start Setup"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "Would you like to setup the FastAPI server as a systemd service?"
echo "This will make it start automatically when you log in."
echo ""
read -p "Setup systemd service? (Y/n): " -n 1 -r
echo
echo

if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
    bash "$SCRIPT_DIR/systemd-setup.sh"
else
    echo "Skipping systemd service setup."
    echo ""
    echo "You can set it up later by running:"
    echo "   ./systemd-setup.sh"
fi

echo ""
echo "════════════════════════════════════════════════════════════"
echo "✅ TermPipe MCP installation complete!"
echo "════════════════════════════════════════════════════════════"
echo ""

if systemctl --user is-active --quiet termpipe-mcp 2>/dev/null; then
    echo "✅ FastAPI server is running as a systemd service"
    echo ""
else
    echo "📋 Quick Start:"
    echo ""
    echo "1. Start the FastAPI backend:"
    echo "   $ termcp server"
    echo ""
    echo "2. (Optional) Check server status:"
    echo "   $ termcp status"
    echo ""
fi

echo "3. Use your configured MCP client(s)"
echo ""
echo "📚 Documentation:"
echo "   • README.md - Overview and features"
echo "   • INSTALL.md - Complete installation guide"
echo "   • VERIFICATION.md - Testing and troubleshooting"
echo ""
