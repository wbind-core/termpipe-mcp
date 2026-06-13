# Session Handoff — kb-lms-daemon Integration
**Date:** 2026-05-07
**Workspace:** /home/craig/termpipe-mcp/termpipe_mcp
**Task:** [2] Integrate kb-lms-daemon into termpipe: llama-cpp-python + kernclip-bus inference

---

## What Was Accomplished This Session

### Storage Cleanup
- Deleted gemma-3-4b-it-GGUF and Mistral-7B-Instruct-v0.3-GGUF from ~/.lmstudio/models (freed ~6.3G)
- Moved all LM Studio models to /media/craig/Linux-SSD/models/
- Moved voice_ai project to /media/craig/Linux-SSD/voice_ai/
- Symlinks in place:
  - /home/craig/new-projects/voice_ai -> /media/craig/Linux-SSD/voice_ai
  - ~/.lmstudio/models/lmstudio-community -> /media/craig/Linux-SSD/models/lmstudio-community
  - ~/.lmstudio/models/hugging-quants -> /media/craig/Linux-SSD/models/hugging-quants
- Disk now at ~18G free on / (was 0)

### termpipe Bug Fixed
- tools.py: `_gated()` was passing `cwd` both as positional and in kwargs, causing
  `workspace_task_set_status` to fail with \"multiple values for argument 'cwd'\"
- Fix applied: `kwargs.pop(\"cwd\", None)` + `fn(cwd=cwd, ...)` in `_gated()`
- File is patched and compile-clean — needs a termpipe restart to take effect
- **Verify fix worked:** `workspace_task_set_status(cwd=..., task_id=2, status=\"in_progress\")`

### llama-cpp-python Install
- Background install launched as PID 133403 with CUDA flags:
  `CMAKE_ARGS=\"-DGGML_CUDA=on\" FORCE_CMAKE=1 pip install llama-cpp-python --break-system-packages`
- Log: /home/craig/llama-install.log
- **Status unknown** — verify with:
  `python3 -c \"from llama_cpp import Llama; import llama_cpp; print(llama_cpp.__version__)\"`
- If not installed, script is ready at: ~/install-llama-cuda.sh
- GPU: NVIDIA RTX 3050 6GB Laptop, CUDA 12.4, driver 550.163.01
- Target CUDA arch: sm_86

---

## What Needs To Happen Next

### 1. Verify llama-cpp-python installed with CUDA
```bash
python3 -c \"from llama_cpp import Llama; import llama_cpp; print(llama_cpp.__version__)\"
```
If not: `bash ~/install-llama-cuda.sh` (logs to ~/llama-install.log)

### 2. Restart termpipe + confirm _gated fix
Restart termpipe, then:
```
workspace_task_set_status(cwd=\"/home/craig/termpipe-mcp/termpipe_mcp\", task_id=2, status=\"in_progress\")
```

### 3. Write kb-lms-daemon.py
Path: /home/craig/kb-lms-daemon.py
- Loads: ~/.lmstudio/models/lmstudio-community/Qwen3-1.7B-GGUF/Qwen3-1.7B-Q8_0.gguf
- Via: llama-cpp-python, n_gpu_layers=-1 (full CUDA), n_ctx=4096
- Subscribes: lms.inference.request
- Publishes: lms.inference.response.<request_id>
- Heartbeats: lms.daemon.heartbeat every 10s { status, model, ts }
- Strips Qwen3 <think>...</think> blocks from output
- Graceful SIGINT/SIGTERM shutdown

### 4. Rewrite _lms.py
Path: /home/craig/termpipe-mcp/termpipe_mcp/tools/workspace/_lms.py
- Drop HTTP transport (localhost:1234/v1) entirely
- Replace with kb socket transport matching _bus.py primitives
- Public API unchanged: lms_query(), lms_query_async(), lms_available()
- Add: lms_model() — reads current model name from heartbeat topic
- lms_available() checks lms.daemon.heartbeat freshness (stale > 30s = False)
- lms_query() uses uuid request ID, polls lms.inference.response.<id>
- Poll timeout: 45s (matches previous HTTP timeout)
- Fail silent on all errors (daemon down never breaks workspace tools)

### 5. Write systemd user service
Path: ~/.config/systemd/user/kb-lms.service
- ExecStart: python3 ~/kb-lms-daemon.py
- Restart=on-failure, RestartSec=5
- Enable: `systemctl --user enable --now kb-lms`

---

## Architecture Summary
```
Qwen3-1.7B-Q8_0.gguf (on Linux-SSD)
  ↓ llama-cpp-python (CUDA, RTX 3050)
kb-lms-daemon.py  (systemd user service)
  ↕ kernclip-bus @ /run/user/1000/kernclip-bus.sock (1.2ns/op)
  topics: lms.inference.request / lms.inference.response.<id> / lms.daemon.heartbeat
_lms.py  (termpipe workspace module)
  lms_query() / lms_query_async() / lms_available() / lms_model()
workspace tools (session summarization, plan injection, etc.)
```

No LM Studio GUI. No HTTP server. No OpenAI-compat endpoint.

---

## Key Paths
| Thing | Path |
|---|---|
| Model | /media/craig/Linux-SSD/models/lmstudio-community/Qwen3-1.7B-GGUF/Qwen3-1.7B-Q8_0.gguf |
| Daemon (to write) | ~/kb-lms-daemon.py |
| _lms.py (to rewrite) | ~/termpipe-mcp/termpipe_mcp/tools/workspace/_lms.py |
| Service (to write) | ~/.config/systemd/user/kb-lms.service |
| Install script | ~/install-llama-cuda.sh |
| Install log | ~/llama-install.log |
| Bus socket | /run/user/1000/kernclip-bus.sock |
| tools.py (bug fixed) | ~/termpipe-mcp/termpipe_mcp/tools/workspace/tools.py |
",
  "path": "/home/craig/HANDOFF-kb-lms-daemon.md"
}
Response

⛔ WRITE BLOCKED [phase: approved]
Plan approved. Create or select a task to begin work.
   ➡️  REQUIRED: Call workspace_task_create(cwd=...) or workspace_task_set_status(cwd=..., task_id=..., status='in_progress').

If you have a legitimate reason to bypass this gate, call workspace_override(cwd=..., reason=...) to request human approval via notification.
