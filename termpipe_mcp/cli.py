"""
CLI entry point for TermPipe MCP.
"""

import sys
import argparse
from pathlib import Path


def setup_command():
    """Interactive setup wizard"""
    from termpipe_mcp.config import config
    
    print("🚀 TermPipe MCP Setup")
    print("=" * 50)
    print()
    
    current_config = config.load()
    
    print("Configure your iFlow API credentials:")
    print("(Get a free API key at: https://iflow.cn)")
    print()
    
    api_key = input(f"API Key [{current_config.get('api_key', '')}]: ").strip()
    if api_key:
        config.set("api_key", api_key)
    
    api_base = input(f"API Base [{current_config.get('api_base', '')}]: ").strip()
    if api_base:
        config.set("api_base", api_base)
    
    print()
    print("✅ Configuration saved!")
    print(f"   Config file: {config.config_file}")
    print()
    print("Next steps:")
    print("1. Start the FastAPI server: termcp server")
    print("2. Configure Claude Desktop with MCP server settings (see README)")
    print()


def server_command():
    """Start the FastAPI server"""
    import uvicorn
    from termpipe_mcp.config import config
    
    host = config.get("server_host", "127.0.0.1")
    port = config.get("server_port", 8421)
    
    print(f"🚀 Starting TermPipe FastAPI server on {host}:{port}")
    print(f"   API docs: http://{host}:{port}/docs")
    print(f"   Health check: http://{host}:{port}/health")
    print()
    print("Press Ctrl+C to stop")
    print()
    
    try:
        uvicorn.run(
            "termpipe_mcp.fastapi_server:app",
            host=host,
            port=port,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n👋 Server stopped")
        sys.exit(0)


def status_command():
    """Check server status"""
    import httpx
    from termpipe_mcp.helpers import TERMCP_URL
    
    print("🔍 Checking TermPipe MCP status...")
    print()
    
    try:
        response = httpx.get(f"{TERMCP_URL}/health", timeout=5.0)
        if response.status_code == 200:
            data = response.json()
            print("✅ FastAPI Server: Running")
            print(f"   URL: {TERMCP_URL}")
            print(f"   Status: {data.get('status', 'unknown')}")
            print(f"   Uptime: {data.get('uptime', 0):.1f}s")
            print()
            return 0
        else:
            print(f"❌ FastAPI Server returned HTTP {response.status_code}")
            print()
            return 1
    except httpx.ConnectError:
        print("❌ FastAPI Server: Not running")
        print(f"   Expected at: {TERMCP_URL}")
        print()
        print("Start it with: termcp server")
        print()
        return 1
    except Exception as e:
        print(f"❌ Error checking status: {e}")
        print()
        return 1


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        prog="termcp",
        description="TermPipe MCP Server - FastAPI backend for MCP clients (Claude Desktop, iFlow CLI, Gemini CLI, etc.)"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Setup command
    subparsers.add_parser("setup", help="Configure API credentials")
    
    # Server command
    subparsers.add_parser("server", help="Start the FastAPI server")
    
    # Status command
    subparsers.add_parser("status", help="Check server status")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    if args.command == "setup":
        setup_command()
    elif args.command == "server":
        server_command()
    elif args.command == "status":
        sys.exit(status_command())
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
