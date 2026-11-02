#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Stack Manager - Ollama GGUF Importer + MCP Server Manager
Unified tool for importing GGUF models and managing MCP servers.
"""

import sys
from omgr.config import DEFAULT_MODEL_DIR, OMGR_MCP_JSON
from omgr.utils.kb import kb_get
from omgr.utils.fzf import fzf_select
from omgr.ollama.importer import OllamaImporter
from omgr.mcp.manager import MCPServerManager
from omgr.hf.searcher import HFModelSearcher
from omgr.ollama.chat import OllamaChatSurface

class AIStackWizard:
    def __init__(self):
        self.de = kb_get("de")
        if self.de:
            print(f"\n🖥️  Detected Desktop Environment: {self.de}")
        self.ollama = OllamaImporter()
        self.mcp = MCPServerManager()
        self.searcher = HFModelSearcher()
        self.download_dir = DEFAULT_MODEL_DIR
    
    def run(self):
        while True:
            self._show_menu()
            choice = self._get_choice()
            
            if choice == "1":
                self._import_gguf()
            elif choice == "2":
                self._search_models()
            elif choice == "3":
                self._download_model()
            elif choice == "4":
                self._manage_mcp()
            elif choice == "5":
                self._list_models()
            elif choice == "6":
                self._test_model()
            elif choice == "7":
                self._remove_model()
            elif choice == "8":
                self._export_config()
            elif choice == "9":
                chat_surface = OllamaChatSurface(self.mcp)
                if chat_surface.configure_session():
                    chat_surface.run_chat_loop()
            elif choice == "10":
                self._import_mcp_json()
            elif choice == "q" or choice == "quit":
                print("\n👋 Goodbye!")
                break
            else:
                print("\n❌ Invalid choice. Please try again.")
    
    def _show_menu(self):
        print("\n" + "=" * 60)
        print("🤖 AI STACK MANAGER")
        print("=" * 60)
        print("\n📦 OLLAMA MODELS:")
        print("  1. Import local GGUF model")
        print("  2. 🔍 Search HuggingFace models")
        print("  3. ⬇️  Download model from HuggingFace")
        print("  5. List models")
        print("  6. Test model")
        print("  7. Remove model")
        print("\n🔌 MCP SERVERS:")
        print("  4. Manage MCP servers")
        print(" 10. Import MCP servers from JSON file")
        print("\n💬 CHAT SURFACE:")
        print("  9. Interactive Chat Surface")
        print("\n📋 UTILITIES:")
        print("  8. Export configuration")
        print("\n  q. Quit")
        print("-" * 60)
    
    def _get_choice(self) -> str:
        return input("\nChoice: ").strip().lower()

    def _import_gguf(self):
        print("Import local GGUF model - NotImplemented in this stub")
        
    def _search_models(self):
        print("Search HuggingFace models - NotImplemented in this stub")
        
    def _download_model(self):
        print("Download model from HuggingFace - NotImplemented in this stub")

    def _manage_mcp(self):
        print("Manage MCP servers - NotImplemented in this stub")
        
    def _list_models(self):
        print("List models - NotImplemented in this stub")
        
    def _test_model(self):
        print("Test model - NotImplemented in this stub")
        
    def _remove_model(self):
        print("Remove model - NotImplemented in this stub")
        
    def _export_config(self):
        print("Export configuration - NotImplemented in this stub")

    def _import_mcp_json(self):
        print("\n" + "=" * 60)
        print("🔌 IMPORT MCP JSON CONFIGURATION")
        print("=" * 60)
        
        default_path = str(OMGR_MCP_JSON)
        path = input(f"\nPath to MCP JSON file [{default_path}]: ").strip()
        if not path:
            path = default_path
            
        self.mcp.import_mcp_json(path)

if __name__ == "__main__":
    wizard = AIStackWizard()
    wizard.run()
