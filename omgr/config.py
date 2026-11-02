import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

SESSION_DIR = Path.home() / ".cache" / "omgr" / "sessions"
SESSION_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_MODEL_DIR = Path.home() / "Downloads"
OLLAMA_BIN = "ollama"
MCP_CONFIG_DIR = Path.home() / ".config" / "mcp"
MCP_CONFIG_FILE = MCP_CONFIG_DIR / "servers.json"
HUGGINGFACE_API = "https://huggingface.co/api"
MODEL_CACHE_DIR = Path.home() / ".cache" / "omgr"
OMGR_MCP_JSON = Path.home() / ".config" / "omgr" / "omgr_mcp.json"

@dataclass
class ProviderConfig:
    name: str = "tiyuvta"
    base_url: str = ""
    api_key: str = ""
    default_model: str = "zai/glm-5.3-flash"

@dataclass
class HFModel:
    id: str
    author: str
    name: str
    downloads: int
    likes: int
    tags: List[str]
    description: str = ""
    gguf_files: List[Dict] = field(default_factory=list)
    quantizations: List[str] = field(default_factory=list)
    
    @property
    def full_name(self) -> str:
        return f"{self.author}/{self.name}"
    
    @property
    def display_name(self) -> str:
        return f"{self.author}/{self.name} ({self.downloads:,} downloads, {self.likes} ❤️)"

@dataclass
class MCPServer:
    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    description: str = ""
    enabled: bool = True
    protocol: str = "stdio"

    def to_dict(self) -> Dict:
        result = {
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "enabled": self.enabled,
            "protocol": self.protocol
        }
        if self.description:
            result["description"] = self.description
        return result

    def to_mcp_config(self) -> Dict:
        result = {
            "command": self.command,
            "args": self.args
        }
        if self.env:
            result["env"] = self.env
        return result

@dataclass
class MCPServerGroup:
    name: str
    servers: List[MCPServer] = field(default_factory=list)
    description: str = ""

@dataclass
class OllamaModel:
    name: str
    gguf_path: Path
    modelfile_path: Optional[Path] = None
    projector_path: Optional[Path] = None
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    family: str = "unknown"
    imported: bool = False
    source_url: str = ""
