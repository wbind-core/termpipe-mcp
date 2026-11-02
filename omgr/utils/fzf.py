import sys
import subprocess
from typing import List, Optional

def fzf_select(
    items: List[str],
    prompt: str = "Select: ",
    preview: Optional[str] = None,
    multi: bool = False,
    height: str = "40%",
    layout: str = "reverse",
    border: bool = True
) -> Optional[List[str]]:
    if not items:
        return None

    cmd = ["fzf"]
    cmd.extend(["--prompt", prompt])
    cmd.extend(["--height", height])
    cmd.extend(["--layout", layout])
    if multi:
        cmd.append("--multi")
    if preview:
        cmd.extend(["--preview", preview])
    if border:
        cmd.append("--border")
    cmd.extend([
        "--color=fg:white,fg+:green,bg+:black,hl:cyan,hl+:cyan,info:yellow,pointer:green,marker:cyan,spinner:blue"
    ])
    cmd.append("--bind=tab:down,shift-tab:up")

    try:
        result = subprocess.run(cmd, input="\n".join(items), capture_output=True, text=True, check=False)
        if result.returncode == 0:
            selected = [x.strip() for x in result.stdout.strip().split("\n") if x.strip()]
            return selected if selected else None
        return None
    except FileNotFoundError:
        print("\n❌ fzf not found. Please install it:", file=sys.stderr)
        sys.exit(1)

def fzf_confirm(prompt: str = "Confirm? ", default: bool = True) -> bool:
    items = ["✅ Yes", "❌ No"]
    selected = fzf_select(items, prompt=prompt, height="10%")
    if selected:
        return selected[0].startswith("✅")
    return default
