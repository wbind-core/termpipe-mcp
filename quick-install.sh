#!/bin/bash
# TermPipe MCP Universal Installer
# Works on: Linux, macOS, Windows (Git Bash/WSL)
# Usage: curl -sSL https://raw.githubusercontent.com/wbind-core/termpipe-mcp/master/quick-install.sh | bash

set -e

echo "╔════════════════════════════════════════════════════════════╗"
echo "║         TermPipe MCP - Universal Installation             ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Detect operating system
detect_os() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        echo "linux"
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        echo "macos"
    elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
        echo "windows"
    elif [[ -n "$WSL_DISTRO_NAME" ]]; then
        echo "wsl"
    else
        # Fallback detection
        case "$(uname -s)" in
            Linux*)     echo "linux";;
            Darwin*)    echo "macos";;
            CYGWIN*|MINGW*|MSYS*) echo "windows";;
            *)          echo "unknown";;
        esac
    fi
}

OS=$(detect_os)

echo "🖥️  Detected OS: $OS"
echo ""

if [[ "$OS" == "unknown" ]]; then
    echo "❌ Could not detect operating system"
    echo "   Supported: Linux, macOS, Windows (Git Bash/WSL)"
    exit 1
fi

# ═══════════════════════════════════════════════════════════
# iFlow Setup (Recommended for AI-Powered Features)
# ═══════════════════════════════════════════════════════════

# Check if iFlow is already configured
if [ -d "$HOME/.iflow" ] || [ -f "$HOME/.iflow/settings.json" ] || [ -f "$HOME/.iflow/oauth_creds.json" ]; then
    echo ""
    echo "✅ iFlow detected - AI-powered debugging features will be available!"
    echo ""
else
    # iFlow not found - offer installation
    echo ""
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║          AI-Powered Debugging Features (Optional)         ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo ""
    echo "TermPipe includes intelligent debugging tools powered by iFlow:"
    echo "  • debug_assist - AI analyzes failed attempts and suggests fixes"
    echo "  • analyze_file_structure - Understand files before editing"
    echo "  • suggest_edit_approach - Get step-by-step editing strategies"
    echo ""
    echo "🌟 FREE access to SOTA AI models (Qwen3-Coder, Kimi K2, DeepSeek v3, GLM-4.6)"
    echo "⚡ No rate limits, no throttling, sub-second response times"
    echo ""
    echo "Choose an option:"
    echo "  [1] Auto-install iFlow CLI (recommended)"
    echo "  [2] Get FREE iFlow API key (opens browser)"
    echo ""
    read -p "Enter choice (1/2, or press Enter to skip): " -n 1 -r IFLOW_CHOICE
    echo
    echo

    case "$IFLOW_CHOICE" in
        1)
            echo "🚀 Installing iFlow CLI..."
            if [[ "$OS" == "windows" ]]; then
                echo "   Windows detected - using npm installation"
                if ! command -v npm &> /dev/null; then
                    echo "   ❌ npm not found. Please install Node.js first:"
                    echo "      https://nodejs.org/en/download"
                    echo ""
                    echo "   After installing Node.js, run:"
                    echo "      npm install -g @iflow-ai/iflow-cli"
                else
                    npm install -g @iflow-ai/iflow-cli
                    echo "   ✅ iFlow CLI installed!"
                    echo "   Run 'iflow' to complete setup"
                fi
            else
                # Linux/macOS one-command installer
                bash -c "$(curl -fsSL https://cloud.iflow.cn/iflow-cli/install.sh)"
                echo "   ✅ iFlow CLI installed!"
            fi
            echo ""
            ;;
        2)
            echo "🌐 Opening iFlow API key page in your browser..."
            echo ""
            echo "   You'll be taken to: https://iflow.cn/?open=setting"
            echo ""
            echo "   Steps:"
            echo "   1. Register/login to iFlow (free account)"
            echo "   2. Click 'Reset' to generate API key"
            echo "   3. Copy the key"
            echo "   4. After installation, run: termcp setup"
            echo "   5. Paste your API key when prompted"
            echo ""
            
            # Open browser based on OS
            case "$OS" in
                linux|wsl)
                    if command -v xdg-open &> /dev/null; then
                        xdg-open "https://iflow.cn/?open=setting" 2>/dev/null || true
                    elif command -v wslview &> /dev/null; then
                        wslview "https://iflow.cn/?open=setting" 2>/dev/null || true
                    fi
                    ;;
                macos)
                    open "https://iflow.cn/?open=setting" 2>/dev/null || true
                    ;;
                windows)
                    start "https://iflow.cn/?open=setting" 2>/dev/null || true
                    ;;
            esac
            
            echo "   Press Enter when you've copied your API key..."
            read
            echo ""
            ;;
        *)
            echo "⏩ Skipping iFlow setup"
            echo "   (You can install later: npm install -g @iflow-ai/iflow-cli)"
            echo ""
            ;;
    esac
fi



# Check dependencies
echo "🔍 Checking dependencies..."

if ! command -v pipx &> /dev/null; then
    echo "❌ Error: pipx is required but not installed."
    echo ""
    case "$OS" in
        linux|wsl)
            echo "   Install with: sudo apt install pipx && pipx ensurepath"
            ;;
        macos)
            echo "   Install with: brew install pipx && pipx ensurepath"
            ;;
        windows)
            echo "   Install with: python -m pip install --user pipx"
            echo "   Then run: python -m pipx ensurepath"
            ;;
    esac
    exit 1
fi

if ! command -v jq &> /dev/null; then
    echo "❌ Error: jq is required but not installed."
    echo ""
    case "$OS" in
        linux|wsl)
            echo "   Install with: sudo apt install jq"
            ;;
        macos)
            echo "   Install with: brew install jq"
            ;;
        windows)
            echo "   Install with: Download from https://stedolan.github.io/jq/download/"
            ;;
    esac
    exit 1
fi

if ! command -v git &> /dev/null; then
    echo "❌ Error: git is required but not installed."
    echo ""
    case "$OS" in
        linux|wsl)
            echo "   Install with: sudo apt install git"
            ;;
        macos)
            echo "   Install with: brew install git"
            ;;
        windows)
            echo "   Install from: https://git-scm.com/download/win"
            ;;
    esac
    exit 1
fi

echo "✅ All dependencies found"
echo ""

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

# Set platform-specific paths
case "$OS" in
    linux|wsl)
        CLAUDE_DESKTOP_DIR="$HOME/.config/Claude"
        CLAUDE_CODE_DIR="$HOME/.claude"
        ;;
    macos)
        CLAUDE_DESKTOP_DIR="$HOME/Library/Application Support/Claude"
        CLAUDE_CODE_DIR="$HOME/.claude"
        ;;
    windows)
        # Git Bash translates paths
        CLAUDE_DESKTOP_DIR="$APPDATA/Claude"
        CLAUDE_CODE_DIR="$HOME/.claude"
        ;;
esac

export CLAUDE_DESKTOP_DIR
export CLAUDE_CODE_DIR
export OS_TYPE="$OS"

# Auto-detect and configure MCP clients
echo "🔍 Auto-detecting MCP clients..."
echo ""

CLIENTS_FOUND=false

# Check for Claude Desktop
if [ -d "$CLAUDE_DESKTOP_DIR" ]; then
    echo "✅ Found Claude Desktop"
    bash ./install-claude-desktop.sh
    CLIENTS_FOUND=true
    echo ""
fi

# Check for Claude Code
if [ -d "$CLAUDE_CODE_DIR" ] || [ -f "$CLAUDE_CODE_DIR/claude.json" ]; then
    echo "✅ Found Claude Code"
    bash ./install-claude-code.sh
    CLIENTS_FOUND=true
    echo ""
fi

# Check for iFlow CLI
if [ -d "$HOME/.iflow" ]; then
    echo "✅ Found iFlow CLI"
    bash ./install-iflow.sh
    CLIENTS_FOUND=true
    echo ""
fi

# Check for Gemini CLI
if [ -d "$HOME/.gemini" ]; then
    echo "✅ Found Gemini CLI"
    bash ./install-gemini.sh
    CLIENTS_FOUND=true
    echo ""
fi

if [ "$CLIENTS_FOUND" = false ]; then
    echo "⚠️  No MCP clients detected on this system."
    echo ""
    echo "Available clients:"
    echo "  • Claude Desktop - https://claude.ai/download"
    echo "  • Claude Code - https://code.claude.com"
    echo "  • iFlow CLI - https://iflow.cn"
    echo "  • Gemini CLI - https://ai.google.dev"
    echo ""
    echo "Install a client and run this installer again."
    exit 0
fi

echo "📚 AI-Powered Features:"
echo ""
echo "   TermPipe includes smart debugging tools that leverage AI models:"
echo ""
echo "   🤖 iFlow (debug_assist, analyze_file_structure, suggest_edit_approach)"
echo "      • Automatically detected from: ~/.iflow/oauth_creds.json"
echo "      • Uses FREE frontier models: Qwen3, DeepSeek, Kimi-K2, GLM-4.6"
echo "      • Sub-second response times via direct API"
echo ""
echo "   🔮 Gemini (gemini_debug, gemini_analyze, gemini_suggest)"
echo "      • Calls: gemini -o text \"prompt\" (non-interactive mode)"
echo "      • Requires Gemini CLI: https://ai.google.dev"
echo "      • Provides second-opinion debugging perspective"
echo ""
echo "   💡 Pro Tip: Use debug_assist or gemini_debug when you get stuck!"
echo "      The AI assistants can analyze your situation and suggest fixes."
echo ""

# Offer systemd/launchd setup (skip on Windows)
if [[ "$OS" != "windows" ]]; then
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
        if [[ "$OS" == "macos" ]]; then
            bash ./install-launchd.sh
        else
            bash ./install-systemd.sh
        fi
    else
        echo "Skipping auto-start setup."
        echo ""
        echo "💡 You can enable it later by running:"
        if [[ "$OS" == "macos" ]]; then
            echo "   cd $TEMP_DIR/termpipe-mcp && ./install-launchd.sh"
        else
            echo "   cd $TEMP_DIR/termpipe-mcp && ./install-systemd.sh"
        fi
    fi
fi

echo ""
echo "════════════════════════════════════════════════════════════"
echo "✅ TermPipe MCP installation complete!"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "🎉 Your AI assistant(s) now have intelligent system access!"
echo ""
