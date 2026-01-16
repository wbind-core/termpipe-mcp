# TermPipe MCP - Windows PowerShell Installer
# Cross-platform installer for Windows

Write-Host "╔════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║         TermPipe MCP - Windows Installation               ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

$ErrorActionPreference = "Stop"

# Check Python
Write-Host "🔍 Checking dependencies..." -ForegroundColor Yellow
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Python is required but not installed." -ForegroundColor Red
    Write-Host "   Download from: https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

# Check pipx
if (-not (Get-Command pipx -ErrorAction SilentlyContinue)) {
    Write-Host "❌ pipx is required but not installed." -ForegroundColor Red
    Write-Host "   Install with: python -m pip install --user pipx" -ForegroundColor Yellow
    Write-Host "   Then run: python -m pipx ensurepath" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ All dependencies found" -ForegroundColor Green
Write-Host ""

# iFlow setup
$iflowPath = Join-Path $env:USERPROFILE ".iflow"
if (Test-Path $iflowPath) {
    Write-Host "✅ iFlow detected - AI-powered debugging features will be available!" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "╔════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║          AI-Powered Debugging Features (Optional)         ║" -ForegroundColor Cyan
    Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "TermPipe includes intelligent debugging tools powered by iFlow:"
    Write-Host "  • debug_assist - AI analyzes failed attempts and suggests fixes"
    Write-Host "  • analyze_file_structure - Understand files before editing"
    Write-Host "  • suggest_edit_approach - Get step-by-step editing strategies"
    Write-Host ""
    Write-Host "🌟 FREE access to SOTA AI models (Qwen3-Coder, Kimi K2, DeepSeek v3, GLM-4.6)"
    Write-Host "⚡ No rate limits, no throttling, sub-second response times"
    Write-Host ""
    Write-Host "Choose an option:"
    Write-Host "  [1] Auto-install iFlow CLI (recommended)"
    Write-Host "  [2] Get FREE iFlow API key (opens browser)"
    Write-Host ""
    $iflowChoice = Read-Host "Enter choice (1/2, or press Enter to skip)"
    
    switch ($iflowChoice) {
        "1" {
            Write-Host "🚀 Installing iFlow CLI..." -ForegroundColor Yellow
            if (Get-Command npm -ErrorAction SilentlyContinue) {
                npm install -g @iflow-ai/iflow-cli
                Write-Host "   ✅ iFlow CLI installed!" -ForegroundColor Green
                Write-Host "   Run 'iflow' to complete setup"
            } else {
                Write-Host "   ❌ npm not found. Please install Node.js first:" -ForegroundColor Red
                Write-Host "      https://nodejs.org/en/download"
            }
        }
        "2" {
            Write-Host "🌐 Opening iFlow API key page in your browser..." -ForegroundColor Yellow
            Write-Host ""
            Write-Host "   You'll be taken to: https://iflow.cn/?open=setting"
            Write-Host ""
            Write-Host "   Steps:"
            Write-Host "   1. Register/login to iFlow (free account)"
            Write-Host "   2. Click 'Reset' to generate API key"
            Write-Host "   3. Copy the key"
            Write-Host "   4. After installation, run: termcp setup"
            Write-Host "   5. Paste your API key when prompted"
            Write-Host ""
            Start-Process "https://iflow.cn/?open=setting"
            Read-Host "   Press Enter when you've copied your API key"
        }
        default {
            Write-Host "⏩ Skipping iFlow setup" -ForegroundColor Yellow
            Write-Host "   (You can install later: npm install -g @iflow-ai/iflow-cli)"
        }
    }
    Write-Host ""
}

# Clone and install
Write-Host "📦 Cloning TermPipe MCP..." -ForegroundColor Yellow
$tempDir = Join-Path $env:TEMP "termpipe-mcp-install"
if (Test-Path $tempDir) {
    Remove-Item -Recurse -Force $tempDir
}

try {
    git clone --quiet https://github.com/wbind-core/termpipe-mcp.git $tempDir
    Set-Location $tempDir
    
    Write-Host "🔧 Installing package..." -ForegroundColor Yellow
    pipx install . --force | Out-Null
    Write-Host "✅ Package installed!" -ForegroundColor Green
    Write-Host ""
    
    # Auto-detect and configure clients
    Write-Host "🔍 Auto-detecting MCP clients..." -ForegroundColor Yellow
    Write-Host ""
    
    $clientsFound = $false
    
    # Get pipx Python path
    $pipxVenv = Join-Path $env:USERPROFILE ".local\share\pipx\venvs\termpipe-mcp"
    if (-not (Test-Path $pipxVenv)) {
        # Try Windows-style path
        $pipxVenv = Join-Path $env:LOCALAPPDATA "pipx\venvs\termpipe-mcp"
    }
    $pythonPath = Join-Path $pipxVenv "Scripts\python.exe"
    
    # Check for Claude Desktop
    $claudeDesktopDir = Join-Path $env:APPDATA "Claude"
    $claudeConfig = Join-Path $claudeDesktopDir "claude_desktop_config.json"
    if (Test-Path $claudeDesktopDir) {
        Write-Host "✅ Found Claude Desktop - Configuring..." -ForegroundColor Green
        
        $mcpServer = @{
            command = $pythonPath
            args = @("-m", "termpipe_mcp.server")
            env = @{ TERMCP_URL = "http://localhost:8421" }
        }
        
        if (-not (Test-Path $claudeConfig)) {
            @{ mcpServers = @{ termpipe = $mcpServer } } | ConvertTo-Json -Depth 10 | Set-Content $claudeConfig
        } else {
            $config = Get-Content $claudeConfig | ConvertFrom-Json
            if (-not $config.mcpServers) { $config | Add-Member -NotePropertyName mcpServers -NotePropertyValue @{} }
            $config.mcpServers.termpipe = $mcpServer
            $config | ConvertTo-Json -Depth 10 | Set-Content $claudeConfig
        }
        Write-Host "   ✅ Claude Desktop configured!" -ForegroundColor Green
        $clientsFound = $true
    }
    
    # Check for Claude Code
    $claudeCodeDir = Join-Path $env:USERPROFILE ".claude"
    $claudeCodeConfig = Join-Path $claudeCodeDir "claude.json"
    if (Test-Path $claudeCodeDir) {
        Write-Host "✅ Found Claude Code - Configuring..." -ForegroundColor Green
        
        $mcpServer = @{
            command = $pythonPath
            args = @("-m", "termpipe_mcp.server")
            env = @{ TERMCP_URL = "http://localhost:8421" }
        }
        
        if (-not (Test-Path (Split-Path $claudeCodeConfig))) {
            New-Item -ItemType Directory -Path (Split-Path $claudeCodeConfig) -Force | Out-Null
        }
        
        if (-not (Test-Path $claudeCodeConfig)) {
            @{ mcpServers = @{ termpipe = $mcpServer } } | ConvertTo-Json -Depth 10 | Set-Content $claudeCodeConfig
        } else {
            $config = Get-Content $claudeCodeConfig | ConvertFrom-Json
            if (-not $config.mcpServers) { $config | Add-Member -NotePropertyName mcpServers -NotePropertyValue @{} }
            $config.mcpServers.termpipe = $mcpServer
            $config | ConvertTo-Json -Depth 10 | Set-Content $claudeCodeConfig
        }
        Write-Host "   ✅ Claude Code configured!" -ForegroundColor Green
        $clientsFound = $true
    }
    
    # Check for iFlow
    if (Test-Path $iflowPath) {
        Write-Host "✅ Found iFlow CLI - Configuring..." -ForegroundColor Green
        $iflowSettings = Join-Path $iflowPath "settings.json"
        
        $mcpServer = @{
            command = $pythonPath
            args = @("-m", "termpipe_mcp.server")
            env = @{ TERMCP_URL = "http://localhost:8421" }
        }
        
        if (-not (Test-Path $iflowSettings)) {
            @{ mcpServers = @{ termpipe = $mcpServer } } | ConvertTo-Json -Depth 10 | Set-Content $iflowSettings
        } else {
            $config = Get-Content $iflowSettings | ConvertFrom-Json
            if (-not $config.mcpServers) { $config | Add-Member -NotePropertyName mcpServers -NotePropertyValue @{} }
            $config.mcpServers.termpipe = $mcpServer
            $config | ConvertTo-Json -Depth 10 | Set-Content $iflowSettings
        }
        Write-Host "   ✅ iFlow CLI configured!" -ForegroundColor Green
        $clientsFound = $true
    }
    
    # Check for Gemini
    $geminiPath = Join-Path $env:USERPROFILE ".gemini"
    if (Test-Path $geminiPath) {
        Write-Host "✅ Found Gemini CLI - Configuring..." -ForegroundColor Green
        $geminiSettings = Join-Path $geminiPath "settings.json"
        
        $mcpServer = @{
            command = $pythonPath
            args = @("-m", "termpipe_mcp.server")
            env = @{ TERMCP_URL = "http://localhost:8421" }
        }
        
        if (-not (Test-Path $geminiSettings)) {
            @{ mcpServers = @{ termpipe = $mcpServer } } | ConvertTo-Json -Depth 10 | Set-Content $geminiSettings
        } else {
            $config = Get-Content $geminiSettings | ConvertFrom-Json
            if (-not $config.mcpServers) { $config | Add-Member -NotePropertyName mcpServers -NotePropertyValue @{} }
            $config.mcpServers.termpipe = $mcpServer
            $config | ConvertTo-Json -Depth 10 | Set-Content $geminiSettings
        }
        Write-Host "   ✅ Gemini CLI configured!" -ForegroundColor Green
        $clientsFound = $true
    }

    
    if (-not $clientsFound) {
        Write-Host "⚠️  No MCP clients detected on this system." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Available clients:"
        Write-Host "  • Claude Desktop - https://claude.ai/download"
        Write-Host "  • Claude Code - https://code.claude.com"
        Write-Host "  • iFlow CLI - https://iflow.cn"
        Write-Host "  • Gemini CLI - https://ai.google.dev"
    }
    
    Write-Host ""
    
    Write-Host ""
    Write-Host "════════════════════════════════════════════════════════════"
    Write-Host "✅ TermPipe MCP installation complete!" -ForegroundColor Green
    Write-Host "════════════════════════════════════════════════════════════"
    Write-Host ""
    Write-Host "📋 Next Steps:"
    Write-Host "1. Start TermPipe server: termcp server"
    Write-Host "2. Restart your MCP clients (Claude Desktop, Claude Code, etc.)"
    Write-Host "3. MCP tools will be available automatically!"
    Write-Host ""
    Write-Host "💡 Tip: Keep the server running or set up Windows auto-start manually"
    Write-Host ""

    
} catch {
    Write-Host "❌ Installation failed: $_" -ForegroundColor Red
    exit 1
} finally {
    Set-Location $HOME
}
