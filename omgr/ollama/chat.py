import sys
import json
import urllib.request
import time
import base64
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from omgr.config import SESSION_DIR
from omgr.mcp.manager import MCPServerManager
from omgr.mcp.client import LightweightMCPClient
from omgr.ollama.importer import OllamaImporter
from omgr.ollama.reviewer import SecondOpinionReviewer
from omgr.utils.kb import kb_pub, kb_get
from omgr.utils.fzf import fzf_select, fzf_confirm

class OllamaChatSurface:
    def __init__(self, mcp_manager: Optional[MCPServerManager] = None):
        self.mcp_mgr = mcp_manager or MCPServerManager()
        self.importer = OllamaImporter()
        self.reviewer = SecondOpinionReviewer(self.mcp_mgr.provider)
        self.endpoint = "http://localhost:11434"
        self.model_name = kb_get("ollama.model") or ""
        self.num_ctx = 8192
        self.temperature = 0.7
        self.system_prompt = "You are a helpful, expert AI assistant."
        self.messages: List[Dict[str, Any]] = []
        self.pending_images: List[str] = []
        self.tools_enabled = True
        
        # MCP Clients
        self.mcp_clients: Dict[str, LightweightMCPClient] = {}
        self.mcp_tools: List[Dict[str, Any]] = []
        self.mcp_tool_map: Dict[str, LightweightMCPClient] = {}
    
    def _start_mcp_clients(self):
        self._stop_mcp_clients()
        enabled = self.mcp_mgr.list_enabled_servers()
        for server in enabled:
            try:
                print(f"🔌 Starting MCP Server '{server.name}'...")
                client = LightweightMCPClient(server.command, server.args, server.env)
                tools = client.start()
                self.mcp_clients[server.name] = client
                
                # Convert MCP tools to Ollama format
                for t in tools:
                    t_name = t.get("name", "")
                    if not t_name: continue
                    self.mcp_tool_map[t_name] = client
                    
                    # Ensure inputSchema is converted to parameters
                    parameters = t.get("inputSchema", {})
                    if "type" not in parameters:
                        parameters["type"] = "object"
                    
                    o_tool = {
                        "type": "function",
                        "function": {
                            "name": t_name,
                            "description": t.get("description", ""),
                            "parameters": parameters
                        }
                    }
                    self.mcp_tools.append(o_tool)
            except Exception as e:
                print(f"⚠️  Failed to start MCP server '{server.name}': {e}", file=sys.stderr)

    def _stop_mcp_clients(self):
        for client in self.mcp_clients.values():
            client.stop()
        self.mcp_clients.clear()
        self.mcp_tools.clear()
        self.mcp_tool_map.clear()
        
    def get_available_tools(self) -> List[Dict[str, Any]]:
        if not self.tools_enabled:
            return []
            
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "exec_shell",
                    "description": "Execute a shell command on the host system and return its output.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "The shell command to run"}
                        },
                        "required": ["command"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "kb_publish",
                    "description": "Publish a key-value message or event to a KernClip Bus (kb) topic.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "topic": {"type": "string", "description": "KernClip Bus topic name (e.g. 'sys.notify')"},
                            "data": {"type": "string", "description": "Message string or JSON payload"}
                        },
                        "required": ["topic", "data"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "kb_query",
                    "description": "Read the latest message value from a KernClip Bus (kb) topic.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "topic": {"type": "string", "description": "KernClip Bus topic name"}
                        },
                        "required": ["topic"]
                    }
                }
            }
        ]
        
        # Inject dynamically discovered MCP tools
        tools.extend(self.mcp_tools)
        return tools

    def execute_tool_call(self, name: str, args: Dict[str, Any]) -> str:
        # Determine if it's a mutating tool
        mutating_keywords = ["write", "edit", "replace", "termf", "delete", "append", "insert"]
        is_mutating = any(kw in name for kw in mutating_keywords)

        if is_mutating:
            print(f"\n🔍 [Second Opinion] Reviewing proposed call to {name}...")
            # Extract last 2 tool interactions from history
            tool_history = []
            for msg in reversed(self.messages):
                if msg.get("role") == "tool":
                    tool_history.insert(0, msg)
                if len(tool_history) >= 2:
                    break
            
            # Extract intent (last assistant message text)
            intent = ""
            for msg in reversed(self.messages):
                if msg.get("role") == "assistant":
                    intent = msg.get("content", "")
                    break

            try:
                final_args = self.reviewer.request_review(name, args, tool_history, intent)
                if final_args != args:
                    print(f"✨ [Second Opinion] GLM modified the arguments!")
                args = final_args
            except Exception as e:
                print(f"⚠️  [Second Opinion Failed: {e}]")

        print(f"\n🛠️  [Executing Tool] {name}({args})")
        kb_pub("ollama.state", "executing_tool")
        
        try:
            # Check native tools first
            if name == "exec_shell":
                import subprocess
                cmd = args.get("command", "")
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                out = res.stdout if res.returncode == 0 else f"Error (code {res.returncode}): {res.stderr}"
                return out.strip() or "(no output)"
            elif name == "kb_publish":
                topic = args.get("topic", "")
                data = args.get("data", "")
                kb_pub(topic, data)
                return f"Published to '{topic}' successfully."
            elif name == "kb_query":
                topic = args.get("topic", "")
                val = kb_get(topic)
                return val if val else "(empty or not found)"
                
            # Fallback to MCP dynamically loaded tools
            elif name in self.mcp_tool_map:
                client = self.mcp_tool_map[name]
                return client.call_tool(name, args)
                
            else:
                return f"Error: Unknown tool '{name}'"
        except Exception as e:
            return f"Tool Execution Error: {e}"

    def select_model(self) -> Optional[str]:
        models = self.importer.ollama_list()
        if not models:
            print("❌ No Ollama models found. Import or pull a model first.")
            return None
        
        selected = fzf_select(models, prompt="Select Model for Chat: ")
        if selected:
            self.model_name = selected[0]
            kb_pub("ollama.model", self.model_name)
            return self.model_name
        return None

    def attach_image(self, file_path: str) -> bool:
        path = Path(file_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            print(f"❌ Image file not found: {file_path}")
            return False
        
        try:
            with open(path, "rb") as img_file:
                b64_str = base64.b64encode(img_file.read()).decode("utf-8")
                self.pending_images.append(b64_str)
                print(f"🖼️  Image attached: {path.name} ({path.stat().st_size / 1024:.1f} KB)")
                return True
        except Exception as e:
            print(f"❌ Failed to read image: {e}")
            return False

    def save_session(self, filename: Optional[str] = None):
        if not self.messages:
            print("⚠️  No chat history to save.")
            return
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        name = filename if filename else f"session_{timestamp}.json"
        if not name.endswith(".json"):
            name += ".json"
            
        save_path = SESSION_DIR / name
        data = {
            "model": self.model_name,
            "num_ctx": self.num_ctx,
            "system_prompt": self.system_prompt,
            "timestamp": timestamp,
            "messages": self.messages
        }
        with open(save_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"💾 Session saved to: {save_path}")

    def load_session(self):
        files = sorted(list(SESSION_DIR.glob("*.json")), reverse=True)
        if not files:
            print("📭 No saved sessions found.")
            return
        
        choices = [f.name for f in files]
        selected = fzf_select(choices, prompt="Select Session to Load: ")
        if not selected:
            return
        
        load_path = SESSION_DIR / selected[0]
        try:
            with open(load_path, "r") as f:
                data = json.load(f)
            self.model_name = data.get("model", self.model_name)
            self.num_ctx = data.get("num_ctx", self.num_ctx)
            self.system_prompt = data.get("system_prompt", self.system_prompt)
            self.messages = data.get("messages", [])
            print(f"✅ Loaded session '{selected[0]}' ({len(self.messages)} messages)")
        except Exception as e:
            print(f"❌ Failed to load session: {e}")

    def run_multi_model_compare(self, prompt: str, target_models: List[str]):
        print(f"\n" + "=" * 60)
        print(f"⚔️  MULTI-MODEL COMPARISON ({len(target_models)} models)")
        print("=" * 60)
        print(f"💬 Prompt: '{prompt}'\n")

        def query_single(model: str) -> Tuple[str, str, float]:
            start_t = time.time()
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "stream": False,
                "options": {"num_ctx": self.num_ctx}
            }
            try:
                req = urllib.request.Request(
                    f"{self.endpoint}/api/chat",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    elapsed = time.time() - start_t
                    content = res_data.get("message", {}).get("content", "(no content)")
                    return model, content, elapsed
            except Exception as e:
                return model, f"Error: {e}", time.time() - start_t

        with ThreadPoolExecutor(max_workers=len(target_models)) as executor:
            futures = [executor.submit(query_single, m) for m in target_models]
            for future in as_completed(futures):
                model, response, elapsed = future.result()
                print(f"────────────────────────────────────────────────────────────")
                print(f"📦 Model: {model}  ({elapsed:.2f}s)")
                print(f"────────────────────────────────────────────────────────────")
                print(response)
                print()

    def configure_session(self):
        print("\n" + "=" * 60)
        print("⚙️  CHAT SESSION CONFIGURATION")
        print("=" * 60)
        
        if not self.model_name:
            if not self.select_model():
                return False
        else:
            print(f"📦 Active Model: {self.model_name}")
            if fzf_confirm(f"Change model (currently '{self.model_name}')? ", default=False):
                self.select_model()
        
        ctx_options = [
            "2048  (2K tokens)",
            "4096  (4K tokens)",
            "8192  (8K tokens - default)",
            "16384 (16K tokens)",
            "32768 (32K tokens)",
            "65536 (64K tokens)",
            "131072 (128K tokens)",
            "Custom..."
        ]
        sel_ctx = fzf_select(ctx_options, prompt=f"Select Context Window Size (current: {self.num_ctx}): ")
        if sel_ctx:
            choice = sel_ctx[0]
            if "Custom" in choice:
                val = input("Enter custom context size: ").strip()
                if val.isdigit():
                    self.num_ctx = int(val)
            else:
                self.num_ctx = int(choice.split()[0])
        
        sys_presets = [
            "You are a helpful, expert AI assistant.",
            "You are an expert pair-programmer and software architect. Write clean, modular, bug-free code.",
            "You are a concise, direct technical assistant. Provide minimal, highly factual responses without fluff.",
            "Custom System Prompt..."
        ]
        sel_sys = fzf_select(sys_presets, prompt="Select System Prompt: ")
        if sel_sys:
            if "Custom" in sel_sys[0]:
                custom_sys = input("\nEnter custom system prompt: ").strip()
                if custom_sys:
                    self.system_prompt = custom_sys
            else:
                self.system_prompt = sel_sys[0]
        
        enabled_servers = self.mcp_mgr.list_enabled_servers()
        print(f"\n🔌 Connected MCP Servers: {len(enabled_servers)}")
        for s in enabled_servers:
            print(f"   • {s.name} ({s.command})")
            
        print(f"\n✅ Session configured: Model={self.model_name} | ctx={self.num_ctx} | temp={self.temperature}")
        return True

    def run_chat_loop(self):
        if not self.model_name:
            models = self.importer.ollama_list()
            if not models:
                print("❌ No models imported.")
                return
            self.model_name = models[0]
        
        if not self.messages:
            self.messages = [{"role": "system", "content": self.system_prompt}]
        
        # Start MCP Servers
        self._start_mcp_clients()
        
        kb_pub("ollama.model", self.model_name)
        kb_pub("ollama.endpoint", self.endpoint)
        kb_pub("ollama.state", "idle")
        
        print("\n" + "=" * 60)
        print("💬 OMGR ADVANCED CHAT SURFACE")
        print("=" * 60)
        print(f"📦 Model: {self.model_name}  |  🧠 Context: {self.num_ctx} tokens")
        print(f"⚙️  System Prompt: '{self.system_prompt[:50]}...'")
        tools = self.get_available_tools()
        print(f"🛠️  Tools Active: {len(tools)} executable functions bound")
        print("-" * 60)
        print("Commands: /image <file>, /compare <m1,m2>, /save, /load, /clear, /ctx, /sys, /exit")
        print("=" * 60 + "\n")
        
        try:
            while True:
                try:
                    user_input = input("💬 You > ").strip()
                except (KeyboardInterrupt, EOFError):
                    print("\n👋 Ending chat session.")
                    break
                
                if not user_input:
                    continue
                
                if user_input.startswith("/"):
                    cmd_parts = user_input.split(maxsplit=1)
                    cmd = cmd_parts[0].lower()
                    arg = cmd_parts[1].strip() if len(cmd_parts) > 1 else ""
                    
                    if cmd in ["/exit", "/quit", "/q"]:
                        print("👋 Ending chat session.")
                        break
                    elif cmd in ["/clear", "/reset"]:
                        self.messages = [{"role": "system", "content": self.system_prompt}]
                        self.pending_images = []
                        print("🧹 Chat history cleared.")
                        continue
                    elif cmd == "/image" or cmd == "/attach":
                        if arg:
                            self.attach_image(arg)
                        else:
                            path_in = input("Enter path to image: ").strip()
                            if path_in:
                                self.attach_image(path_in)
                        continue
                    elif cmd == "/save":
                        self.save_session(arg if arg else None)
                        continue
                    elif cmd == "/load":
                        self.load_session()
                        continue
                    elif cmd == "/compare":
                        if arg:
                            models = [m.strip() for m in arg.split(",") if m.strip()]
                        else:
                            all_m = self.importer.ollama_list()
                            sel = fzf_select(all_m, prompt="Select models to compare: ", multi=True)
                            models = sel if sel else []
                        
                        if models:
                            prompt_in = input("Enter comparison prompt: ").strip()
                            if prompt_in:
                                self.run_multi_model_compare(prompt_in, models)
                        continue
                    elif cmd == "/ctx":
                        if arg.isdigit():
                            self.num_ctx = int(arg)
                            print(f"⚙️ Context window updated to {self.num_ctx} tokens.")
                        else:
                            print(f"Current context size: {self.num_ctx}. Usage: /ctx <number>")
                        continue
                    elif cmd == "/sys":
                        if arg:
                            self.system_prompt = arg
                            self.messages[0] = {"role": "system", "content": self.system_prompt}
                            print(f"⚙️ System prompt updated.")
                        else:
                            print(f"Current system prompt: '{self.system_prompt}'")
                        continue
                    elif cmd == "/model":
                        if arg:
                            self.model_name = arg
                            kb_pub("ollama.model", self.model_name)
                            print(f"📦 Switched to model: {self.model_name}")
                        else:
                            self.select_model()
                        continue
                    elif cmd == "/status":
                        print(f"Model: {self.model_name} | ctx: {self.num_ctx} | Messages: {len(self.messages)} | Images: {len(self.pending_images)}")
                        continue
                    else:
                        print(f"Unknown command '{cmd}'. Available: /image, /compare, /save, /load, /clear, /ctx, /sys, /exit")
                        continue
                
                msg_dict: Dict[str, Any] = {"role": "user", "content": user_input}
                if self.pending_images:
                    msg_dict["images"] = self.pending_images
                    self.pending_images = []
                
                self.messages.append(msg_dict)
                
                kb_pub("ollama.state", "thinking")
                print(f"\n🤖 {self.model_name} > ", end="", flush=True)
                
                payload = {
                    "model": self.model_name,
                    "messages": self.messages,
                    "tools": self.get_available_tools(),
                    "stream": True,
                    "options": {
                        "num_ctx": self.num_ctx,
                        "temperature": self.temperature
                    }
                }
                
                full_response = ""
                tool_calls_to_exec = []
                
                try:
                    req = urllib.request.Request(
                        f"{self.endpoint}/api/chat",
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"}
                    )
                    
                    kb_pub("ollama.state", "responding")
                    with urllib.request.urlopen(req, timeout=120) as resp:
                        for line in resp:
                            if line:
                                data = json.loads(line.decode("utf-8"))
                                msg_obj = data.get("message", {})
                                msg_chunk = msg_obj.get("content", "")
                                
                                if msg_chunk:
                                    print(msg_chunk, end="", flush=True)
                                    full_response += msg_chunk
                                    kb_pub("ollama.chat_stream", msg_chunk)
                                
                                if "tool_calls" in msg_obj and msg_obj["tool_calls"]:
                                    tool_calls_to_exec.extend(msg_obj["tool_calls"])
                                    
                                if data.get("done", False):
                                    break
                    print("\n")
                    
                    self.messages.append({"role": "assistant", "content": full_response})
                    
                    if tool_calls_to_exec:
                        for t_call in tool_calls_to_exec:
                            fn = t_call.get("function", {})
                            fn_name = fn.get("name")
                            fn_args = fn.get("arguments", {})
                            
                            tool_out = self.execute_tool_call(fn_name, fn_args)
                            self.messages.append({
                                "role": "tool",
                                "content": tool_out,
                                "name": fn_name
                            })
                            print(f"🤖 Tool Output > {tool_out[:200]}...\n")
                            
                except Exception as e:
                    print(f"\n❌ Error calling Ollama: {e}\n")
                finally:
                    kb_pub("ollama.state", "idle")
        finally:
            self._stop_mcp_clients()
