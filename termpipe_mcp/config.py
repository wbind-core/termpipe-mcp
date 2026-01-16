"""
Configuration management for TermPipe MCP Server.
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any


class Config:
    """Manages TermPipe MCP configuration"""
    
    def __init__(self):
        self.config_dir = Path.home() / ".termpipe-mcp"
        self.config_file = self.config_dir / "config.json"
        self.log_file = self.config_dir / "server.log"
        self._config: Optional[Dict[str, Any]] = None
    
    def ensure_dir(self):
        """Ensure configuration directory exists"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.chmod(0o700)
    
    def load(self) -> Dict[str, Any]:
        """Load configuration from file"""
        if self._config is not None:
            return self._config
        
        self.ensure_dir()
        
        if not self.config_file.exists():
            # Create default config
            default = {
                "api_key": "",
                "api_base": "https://apis.iflow.cn/v1",
                "default_model": "qwen3-coder-plus",
                "server_port": 8421,
                "server_host": "127.0.0.1"
            }
            self.save(default)
            return default
        
        try:
            with open(self.config_file) as f:
                self._config = json.load(f)
            return self._config
        except Exception as e:
            raise RuntimeError(f"Failed to load config: {e}")
    
    def save(self, config: Dict[str, Any]):
        """Save configuration to file"""
        self.ensure_dir()
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=2)
        self.config_file.chmod(0o600)
        self._config = config
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value"""
        config = self.load()
        return config.get(key, default)
    
    def set(self, key: str, value: Any):
        """Set configuration value"""
        config = self.load()
        config[key] = value
        self.save(config)
    
    def get_iflow_credentials(self) -> tuple[str, str]:
        """Get iFlow API credentials"""
        api_key = self.get("api_key")
        api_base = self.get("api_base", "https://apis.iflow.cn/v1")
        
        if not api_key:
            # Try fallback to main iFlow settings
            iflow_settings = Path.home() / ".iflow" / "settings.json"
            if iflow_settings.exists():
                try:
                    with open(iflow_settings) as f:
                        settings = json.load(f)
                    api_key = settings.get("apiKey", "")
                    api_base = settings.get("baseUrl", api_base)
                except Exception:
                    pass
        
        if not api_key:
            raise ValueError(
                "No API key configured. Run 'termcp setup' or set api_key in "
                f"{self.config_file}"
            )
        
        return api_key, api_base


# Global config instance
config = Config()
