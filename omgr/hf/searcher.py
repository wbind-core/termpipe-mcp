import sys
import json
import re
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional, List, Dict
from omgr.config import HFModel, MODEL_CACHE_DIR, HUGGINGFACE_API

class HFModelSearcher:
    def __init__(self):
        self.cache_dir = MODEL_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_file = self.cache_dir / "search_cache.json"
        self._cache: Dict = {}
        self._load_cache()
    
    def _load_cache(self):
        if self._cache_file.exists():
            try:
                with open(self._cache_file, "r") as f:
                    self._cache = json.load(f)
            except:
                self._cache = {}
    
    def _save_cache(self):
        with open(self._cache_file, "w") as f:
            json.dump(self._cache, f, indent=2)
    
    def _api_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        url = f"{HUGGINGFACE_API}/{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "omgr/1.0"})
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as e:
            print(f"⚠️  API request failed: {e}", file=sys.stderr)
            return None
    
    def search_models(self, query: str, limit: int = 50, use_cache: bool = True) -> List[HFModel]:
        cache_key = f"search_{query}_{limit}"
        if use_cache and cache_key in self._cache:
            cached = self._cache[cache_key]
            return [HFModel(**m) for m in cached]
        
        print(f"🔍 Searching for '{query}' on HuggingFace...")
        results = []
        params = {
            "search": f"{query}",
            "limit": limit,
            "sort": "downloads",
            "direction": -1,
        }
        
        data = self._api_request("models", params)
        if not data or not isinstance(data, list):
            return []
        
        for model in data:
            hf_model = HFModel(
                id=model["id"],
                author=model.get("author", model["id"].split("/")[0]),
                name=model["id"].split("/")[-1],
                downloads=model.get("downloads", 0),
                likes=model.get("likes", 0),
                tags=model.get("tags", []),
                description=model.get("description", "")[:200] if model.get("description") else "",
            )
            results.append(hf_model)
        
        if use_cache:
            self._cache[cache_key] = [m.__dict__ for m in results]
            self._save_cache()
        
        return results
    
    def get_model_files(self, model_id: str) -> List[Dict]:
        cache_key = f"files_{model_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        data = self._api_request(f"models/{model_id}")
        if not data:
            return []
        
        siblings = data.get("siblings", [])
        gguf_files = []
        for sibling in siblings:
            name = sibling.get("rfilename", "")
            if name.endswith(".gguf") or ".gguf" in name:
                quant = self._extract_quantization(name)
                size = sibling.get("size", 0)
                gguf_files.append({
                    "filename": name,
                    "size": size,
                    "size_mb": size / (1024 * 1024),
                    "quantization": quant,
                    "is_projector": "mmproj" in name.lower() or "projector" in name.lower()
                })
        
        gguf_files.sort(key=lambda x: x["size"], reverse=True)
        self._cache[cache_key] = gguf_files
        self._save_cache()
        return gguf_files
    
    def _extract_quantization(self, filename: str) -> str:
        patterns = [
            (r"q[0-9]_[0-9]", "Q{}"),
            (r"q[0-9]", "Q{}"),
            (r"_([a-zA-Z0-9]+)\.gguf", "{}"),
            (r"\.([a-zA-Z0-9]+)\.gguf", "{}"),
        ]
        
        for pattern, fmt in patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                return fmt.format(match.group(1).upper())
        return "unknown"
