import subprocess
import re
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
from omgr.config import OllamaModel, OLLAMA_BIN

class OllamaImporter:
    def __init__(self):
        self.models: Dict[str, OllamaModel] = {}
    
    def ollama_list(self) -> List[str]:
        try:
            result = subprocess.run(
                [OLLAMA_BIN, "list"],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                models = []
                for line in lines[1:]:
                    if line.strip():
                        model_name = line.split()[0]
                        models.append(model_name)
                return models
            return []
        except Exception:
            return []
    
    def ollama_create(self, model_name: str, modelfile_path: Path) -> Tuple[bool, str]:
        try:
            cmd = [OLLAMA_BIN, "create", model_name, "-f", str(modelfile_path)]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                return True, result.stdout
            return False, result.stderr
        except Exception as e:
            return False, str(e)
    
    def generate_modelfile(self, model: OllamaModel) -> str:
        lines = []
        lines.append(f"FROM {model.gguf_path}")
        if model.projector_path:
            lines.append(f"PROJECTOR {model.projector_path}")
        if model.system_prompt:
            lines.append(f'SYSTEM """{model.system_prompt}"""')
        if model.temperature is not None:
            lines.append(f"PARAMETER temperature {model.temperature}")
        for key, value in model.parameters.items():
            lines.append(f"PARAMETER {key} {value}")
        return "\n".join(lines)
