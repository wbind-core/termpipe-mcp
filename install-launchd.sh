#!/bin/bash
# TermPipe MCP - macOS LaunchAgent Setup Script

set -e

echo "════════════════════════════════════════════════════════════"
echo "TermPipe MCP - macOS Auto-Start Setup"
echo "════════════════════════════════════════════════════════════"
echo ""

LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_FILE="$LAUNCH_AGENTS_DIR/com.termpipe.mcp.plist"
PIPX_PYTHON="$HOME/.local/share/pipx/venvs/termpipe-mcp/bin/python"

# Verify pipx installation
if [ ! -f "$PIPX_PYTHON" ]; then
    echo "❌ Error: TermPipe MCP not found at $PIPX_PYTHON"
    echo "   Run: pipx install termpipe-mcp"
    exit 1
fi

# Create LaunchAgents directory if it doesn't exist
mkdir -p "$LAUNCH_AGENTS_DIR"

# Check if service already exists
if [ -f "$PLIST_FILE" ]; then
    echo "⚠️  LaunchAgent already exists"
    read -p "   Overwrite existing service? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "   Skipping LaunchAgent setup"
        exit 0
    fi
    # Unload existing service
    launchctl unload "$PLIST_FILE" 2>/dev/null || true
fi

# Create LaunchAgent plist
echo "📝 Creating LaunchAgent configuration..."
cat > "$PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.termpipe.mcp</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PIPX_PYTHON</string>
        <string>-m</string>
        <string>termpipe_mcp.fastapi_server</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$HOME/.termpipe-mcp/server.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/.termpipe-mcp/server.error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin</string>
    </dict>
</dict>
</plist>
EOF

echo "   ✅ LaunchAgent created at $PLIST_FILE"

# Load the service
echo ""
echo "🚀 Loading LaunchAgent..."
launchctl load "$PLIST_FILE"

# Give it a moment to start
sleep 2

# Check if it's running
if launchctl list | grep -q "com.termpipe.mcp"; then
    echo "   ✅ Service is running!"
else
    echo "   ⚠️  Service loaded but may not be running"
    echo "   Check logs: tail -f $HOME/.termpipe-mcp/server.log"
fi

echo ""
echo "════════════════════════════════════════════════════════════"
echo "✅ macOS Auto-Start setup complete!"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "📋 Service Management Commands:"
echo ""
echo "  Stop:    launchctl unload $PLIST_FILE"
echo "  Start:   launchctl load $PLIST_FILE"
echo "  Restart: launchctl kickstart -k gui/\$(id -u)/com.termpipe.mcp"
echo "  Status:  launchctl list | grep termpipe"
echo "  Logs:    tail -f $HOME/.termpipe-mcp/server.log"
echo ""
echo "💡 The service will now start automatically on login!"
echo ""
