#!/bin/bash
# TermPipe MCP Systemd Service Setup
# Creates and enables systemd user service for auto-start on boot

set -e

echo "🔧 Setting up TermPipe MCP systemd service..."
echo ""

# Get actual username and paths
USERNAME=$(whoami)
SYSTEMD_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SYSTEMD_DIR/termpipe-mcp.service"
TERMCP_BIN="$HOME/.local/bin/termcp"

# Verify termcp is installed
if [ ! -f "$TERMCP_BIN" ]; then
    echo "❌ Error: termcp not found at $TERMCP_BIN"
    echo "   Install TermPipe MCP first: pipx install /path/to/termpipe-mcp"
    exit 1
fi

# Create systemd user directory if it doesn't exist
mkdir -p "$SYSTEMD_DIR"

# Check if service already exists
if [ -f "$SERVICE_FILE" ]; then
    echo "⚠️  TermPipe MCP service already exists"
    read -p "   Overwrite? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "   Skipping service creation"
        exit 0
    fi
fi

# Create the service file
echo "📝 Creating systemd service file..."
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=TermPipe MCP FastAPI Server
Documentation=https://github.com/termpipe/termpipe-mcp
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$TERMCP_BIN server
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

# Resource limits (optional)
# Uncomment if you want to limit resources
# MemoryMax=512M
# CPUQuota=50%

[Install]
WantedBy=default.target
EOF

echo "   ✅ Service file created at $SERVICE_FILE"

# Reload systemd daemon
echo ""
echo "🔄 Reloading systemd daemon..."
systemctl --user daemon-reload
echo "   ✅ Daemon reloaded"

# Enable the service
echo ""
echo "🚀 Enabling TermPipe MCP service..."
systemctl --user enable termpipe-mcp.service
echo "   ✅ Service enabled (will start on boot)"

# Ask if user wants to start now
echo ""
read -p "Start the service now? (Y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    systemctl --user start termpipe-mcp.service
    echo "   ✅ Service started"
    
    # Brief pause to let service start
    sleep 2
    
    # Check status
    echo ""
    echo "📊 Service Status:"
    systemctl --user status termpipe-mcp.service --no-pager -l || true
else
    echo "   Service not started. Start manually with:"
    echo "   systemctl --user start termpipe-mcp.service"
fi

echo ""
echo "✅ Systemd service setup complete!"
echo ""
echo "📋 Useful Commands:"
echo ""
echo "  Status:   systemctl --user status termpipe-mcp"
echo "  Start:    systemctl --user start termpipe-mcp"
echo "  Stop:     systemctl --user stop termpipe-mcp"
echo "  Restart:  systemctl --user restart termpipe-mcp"
echo "  Logs:     journalctl --user -u termpipe-mcp -f"
echo "  Disable:  systemctl --user disable termpipe-mcp"
echo ""
echo "💡 The service will now start automatically when you log in!"
echo ""
