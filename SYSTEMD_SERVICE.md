# Systemd Service Auto-Start Feature

## Overview

TermPipe MCP now includes **automatic systemd service setup** that makes the FastAPI server start automatically on boot.

## What Was Added

### New Script: `systemd-setup.sh`

**Purpose:** Creates and enables a systemd user service for TermPipe MCP FastAPI server

**Size:** 2.8 KB (110 lines)

**Features:**
- ✅ Creates service file at `~/.config/systemd/user/termpipe-mcp.service`
- ✅ Enables service to start on login/boot
- ✅ Configures automatic restart on failure
- ✅ Uses journal logging for easy debugging
- ✅ Interactive - asks before overwriting existing service
- ✅ Optionally starts service immediately
- ✅ Shows status and useful commands after setup

### Updated Master Installer

The `install.sh` script now includes an optional systemd setup step after client configuration.

**Flow:**
1. User configures MCP clients (Claude Desktop, iFlow CLI, Gemini CLI)
2. Script asks: "Enable auto-start? (Y/n)"
3. If yes: Calls `systemd-setup.sh` automatically
4. If no: Shows how to enable later

## Systemd Service Configuration

### Service File Location
```
~/.config/systemd/user/termpipe-mcp.service
```

### Service File Contents
```ini
[Unit]
Description=TermPipe MCP FastAPI Server
Documentation=https://github.com/termpipe/termpipe-mcp
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/home/USERNAME/.local/bin/termcp server
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

### Key Features
- **Type=simple** - Standard service type
- **Restart=always** - Auto-restart on crashes
- **RestartSec=5** - Wait 5 seconds before restart
- **After/Wants=network-online.target** - Start after network is ready
- **StandardOutput/Error=journal** - Log to systemd journal

## Usage

### Automatic Setup (Recommended)
```bash
cd /path/to/termpipe-mcp
./install.sh
# Select clients to configure
# Answer "Y" when asked about systemd service
```

### Manual Setup
```bash
./systemd-setup.sh
```

### Verify Service is Running
```bash
systemctl --user status termpipe-mcp
```

Expected output:
```
● termpipe-mcp.service - TermPipe MCP FastAPI Server
     Loaded: loaded (~/.config/systemd/user/termpipe-mcp.service; enabled)
     Active: active (running) since ...
```

## Systemd Commands

### Essential Commands
```bash
# Check status
systemctl --user status termpipe-mcp

# Start service
systemctl --user start termpipe-mcp

# Stop service
systemctl --user stop termpipe-mcp

# Restart service
systemctl --user restart termpipe-mcp

# Enable auto-start (if not already enabled)
systemctl --user enable termpipe-mcp

# Disable auto-start
systemctl --user disable termpipe-mcp

# View logs (follow mode)
journalctl --user -u termpipe-mcp -f

# View last 50 log lines
journalctl --user -u termpipe-mcp -n 50
```

## Benefits

### For Users
- **Zero manual intervention** - Server starts automatically
- **Boot resilience** - Starts after network is ready
- **Crash recovery** - Auto-restarts on failure
- **Easy debugging** - Logs available via journalctl
- **One-time setup** - Configure once, works forever

### For System Administrators
- **Standard systemd management** - Uses familiar tools
- **User-level service** - No root/sudo required
- **Resource control** - Can add limits if needed
- **Monitoring ready** - Standard systemd monitoring tools work

## How It Works

### Service Lifecycle

1. **On Boot/Login:**
   - systemd waits for network to be ready
   - Starts `termcp server` command
   - Server begins listening on port 8421

2. **During Operation:**
   - Service runs continuously
   - Logs output to systemd journal
   - Monitored by systemd

3. **On Failure:**
   - systemd detects process exit
   - Waits 5 seconds (RestartSec)
   - Automatically restarts service
   - Continues indefinitely

4. **On Shutdown:**
   - systemd sends SIGTERM to process
   - Server shuts down gracefully
   - Service stops

### Logging

All output is sent to systemd journal:
```bash
# View real-time logs
journalctl --user -u termpipe-mcp -f

# View logs since boot
journalctl --user -u termpipe-mcp -b

# View logs for specific time range
journalctl --user -u termpipe-mcp --since "1 hour ago"
```

## Troubleshooting

### Service won't start
```bash
# Check status for error messages
systemctl --user status termpipe-mcp

# View full logs
journalctl --user -u termpipe-mcp -n 100
```

Common issues:
- **termcp not found:** Verify pipx installation
- **Permission denied:** Check file permissions
- **Port already in use:** Another process using port 8421

### Disable and remove service
```bash
# Stop service
systemctl --user stop termpipe-mcp

# Disable auto-start
systemctl --user disable termpipe-mcp

# Remove service file
rm ~/.config/systemd/user/termpipe-mcp.service

# Reload systemd
systemctl --user daemon-reload
```

## Advanced Configuration

### Add Resource Limits

Edit the service file and uncomment/add:
```ini
[Service]
# Limit memory usage
MemoryMax=512M

# Limit CPU usage to 50%
CPUQuota=50%
```

Then reload:
```bash
systemctl --user daemon-reload
systemctl --user restart termpipe-mcp
```

### Change Restart Policy

```ini
[Service]
# Don't restart on success, always restart on failure
Restart=on-failure

# Maximum restart attempts
StartLimitBurst=5
StartLimitIntervalSec=10
```

## Integration with Master Installer

The master installer integrates systemd setup seamlessly:

```bash
$ ./install.sh

[... client configuration ...]

════════════════════════════════════════════════════════════
🚀 Auto-Start on Boot (Optional)
════════════════════════════════════════════════════════════

Would you like to setup TermPipe MCP as a systemd service?
This will make the FastAPI server start automatically on boot.

Enable auto-start? (Y/n): y

🔧 Setting up TermPipe MCP systemd service...

📝 Creating systemd service file...
   ✅ Service file created at ~/.config/systemd/user/termpipe-mcp.service

🔄 Reloading systemd daemon...
   ✅ Daemon reloaded

🚀 Enabling TermPipe MCP service...
   ✅ Service enabled (will start on boot)

Start the service now? (Y/n): y
   ✅ Service started

📊 Service Status:
● termpipe-mcp.service - TermPipe MCP FastAPI Server
     Loaded: loaded
     Active: active (running)
```

## Files Modified

1. **NEW:** `systemd-setup.sh` (111 lines)
   - Standalone systemd service installer
   - Interactive with confirmations
   - Shows status after setup

2. **UPDATED:** `install.sh` (120 lines)
   - Removed embedded systemd function
   - Calls `systemd-setup.sh` when user opts in
   - Cleaner architecture

3. **UPDATED:** `AUTOMATED_INSTALL.md`
   - Added systemd service documentation
   - Included useful commands
   - Explained auto-start feature

4. **UPDATED:** `README.md`
   - Mentioned auto-start feature in installer description

## Success Criteria

✅ Systemd service script created and executable
✅ Service file template with best practices
✅ Automatic restart on failure
✅ Journal logging enabled
✅ Interactive setup with confirmations
✅ Integrated into master installer
✅ Documentation updated
✅ User-level service (no sudo required)
✅ Network dependency configured
✅ Helpful command reference provided

## Impact

**Before:** Users had to manually start `termcp server` every time

**After:** Server starts automatically on boot/login

This eliminates the most common friction point in daily use! 🎉

## Production Ready

The systemd service feature is:
- ✅ Complete and tested
- ✅ Following systemd best practices
- ✅ User-level (no root required)
- ✅ Documented
- ✅ Integrated into master installer
- ✅ Ready for immediate use

**Users can now have a completely hands-off TermPipe MCP experience!**
