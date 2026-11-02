import json
import sys
from pathlib import Path
from typing import List, Dict
from omgr.config import MCPServer, MCPServerGroup, MCP_CONFIG_DIR, ProviderConfig
from omgr.utils.fzf import fzf_confirm

class MCPServerManager:
    def __init__(self, config_dir: Path = MCP_CONFIG_DIR):
        self.config_dir = config_dir
        self.config_file = config_dir / "servers.json"
        self.servers: Dict[str, MCPServer] = {}
        self.groups: Dict[str, MCPServerGroup] = {}
        self.provider: ProviderConfig = ProviderConfig()
        self._load()
    
    def _load(self):
        if self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    data = json.load(f)
                
                if "servers" in data:
                    for name, cfg in data["servers"].items():
                        server = MCPServer(
                            name=name,
                            command=cfg.get("command", ""),
                            args=cfg.get("args", []),
                            env=cfg.get("env", {}),
                            description=cfg.get("description", ""),
                            enabled=cfg.get("enabled", True),
                            protocol=cfg.get("protocol", "stdio")
                        )
                        self.servers[name] = server
                
                if "groups" in data:
                    for name, cfg in data["groups"].items():
                        group = MCPServerGroup(
                            name=name,
                            description=cfg.get("description", "")
                        )
                        if "servers" in cfg:
                            for server_name in cfg["servers"]:
                                if server_name in self.servers:
                                    group.servers.append(self.servers[server_name])
                        self.groups[name] = group
            except Exception as e:
                print(f"⚠️  Error loading MCP config: {e}", file=sys.stderr)
    
    def _save(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)
        data = {"servers": {}, "groups": {}}
        for name, server in self.servers.items():
            data["servers"][name] = server.to_dict()
        for name, group in self.groups.items():
            data["groups"][name] = {
                "description": group.description,
                "servers": [s.name for s in group.servers]
            }
        with open(self.config_file, "w") as f:
            json.dump(data, f, indent=2)
        self._save_mcp_compatible()
    
    def _save_mcp_compatible(self):
        mcp_file = self.config_dir / "mcp_servers.json"
        mcp_data = {}
        for name, server in self.servers.items():
            if server.enabled:
                mcp_data[name] = server.to_mcp_config()
        with open(mcp_file, "w") as f:
            json.dump({"mcpServers": mcp_data}, f, indent=2)
            
    def import_mcp_json(self, file_path: str) -> bool:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            print(f"❌ File not found: {path}")
            return False
        
        try:
            with open(path, "r") as f:
                data = json.load(f)
            
            # Parse provider if it exists
            provider_data = data.get("provider", {})
            if provider_data and "tiyuvta" in provider_data:
                opts = provider_data["tiyuvta"].get("options", {})
                self.provider.base_url = opts.get("baseURL", "")
                self.provider.api_key = opts.get("apiKey", "")
                print(f"🔑 Loaded TiYuvta provider config.")

            servers_data = data.get("mcpServers", {})
            if not servers_data:
                print("❌ Invalid format: missing 'mcpServers' object.")
                return False
                
            imported = 0
            for name, cfg in servers_data.items():
                if name in self.servers:
                    print(f"⚠️  Skipping '{name}' - already exists.")
                    continue
                
                server = MCPServer(
                    name=name,
                    command=cfg.get("command", ""),
                    args=cfg.get("args", []),
                    env=cfg.get("env", {}),
                    enabled=True
                )
                self.servers[name] = server
                imported += 1
                
            if imported > 0:
                self._save()
                print(f"✅ Successfully imported {imported} MCP servers.")
                return True
            return False
            
        except Exception as e:
            print(f"❌ Failed to parse JSON: {e}")
            return False
    
    def add_server(self, server: MCPServer) -> bool:
        if server.name in self.servers:
            overwrite = fzf_confirm(f"Server '{server.name}' already exists. Overwrite? ")
            if not overwrite:
                return False
        self.servers[server.name] = server
        self._save()
        return True
    
    def remove_server(self, name: str) -> bool:
        if name not in self.servers:
            return False
        confirm = fzf_confirm(f"Remove server '{name}'? ")
        if not confirm:
            return False
        del self.servers[name]
        for group in self.groups.values():
            group.servers = [s for s in group.servers if s.name != name]
        self._save()
        return True
    
    def toggle_server(self, name: str) -> bool:
        if name not in self.servers:
            return False
        self.servers[name].enabled = not self.servers[name].enabled
        self._save()
        return True
    
    def list_servers(self) -> List[MCPServer]:
        return list(self.servers.values())
    
    def list_enabled_servers(self) -> List[MCPServer]:
        return [s for s in self.servers.values() if s.enabled]
