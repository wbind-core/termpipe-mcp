import subprocess
import re
from typing import Optional

def kb_pub(topic: str, data: str):
    try:
        subprocess.run(["kb", "pub", topic, data], capture_output=True, check=False)
    except Exception:
        pass

def kb_get(topic: str) -> Optional[str]:
    try:
        res = subprocess.run(["kb", "get", topic, "--data-only"], capture_output=True, text=True, check=False)
        if res.returncode == 0:
            val = res.stdout.strip().strip('"')
            val = re.sub(r'\x1b\[[0-9;]*m', '', val).strip()
            if not val or val == "(empty)":
                return None
            return val
    except Exception:
        pass
    return None
