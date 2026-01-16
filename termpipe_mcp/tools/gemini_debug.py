"""
Debug assistance tools - Gemini-powered debugging helper.
Uses Google's Gemini CLI for a different model perspective.
"""

import subprocess
from typing import Optional
from pathlib import Path


def _gemini_query(prompt: str, timeout: int = 60) -> str:
    """Query Gemini CLI with a prompt."""
    try:
        result = subprocess.run(
            ["gemini", "-o", "text", prompt],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            return f"[Gemini error: {result.stderr.strip()}]"
            
    except subprocess.TimeoutExpired:
        return f"[Gemini timeout after {timeout}s]"
    except FileNotFoundError:
        return "[Gemini CLI not installed. Install with: npm install -g @anthropic/gemini-cli]"
    except Exception as e:
        return f"[Gemini error: {e}]"


def register_tools(mcp):
    """Register Gemini-powered debug tools with the MCP server."""
    
    @mcp.tool()
    def gemini_debug(
        problem: str,
        file_path: Optional[str] = None,
        line_range: Optional[tuple[int, int]] = None,
        include_history: bool = True
    ) -> str:
        """
        Gemini-powered debugging assistant - get a different AI's perspective.
        
        Uses Google's Gemini model via CLI when you want a second opinion
        or different approach than what you've been trying.
        
        Args:
            problem: Describe what you're trying to do and what's going wrong
            file_path: Optional file to include as context
            line_range: Optional (start, end) line range to focus on
            include_history: Include recent tool call history (default: True)
        """
        from termpipe_mcp.tools.system import _tool_call_history
        
        # Build context
        context_parts = []
        
        # Add recent tool history
        if include_history and _tool_call_history:
            recent = _tool_call_history[-5:]
            history_str = "Recent tool calls:\n"
            for call in recent:
                result_preview = call.get('result_preview', '')[:150]
                history_str += f"  - {call['tool']}({call['args']})\n"
                if 'Error' in result_preview or 'error' in result_preview:
                    history_str += f"    Result: {result_preview}\n"
            context_parts.append(history_str)
        
        # Add file context
        if file_path:
            try:
                p = Path(file_path).expanduser()
                if p.exists():
                    lines = p.read_text().split('\n')
                    total_lines = len(lines)
                    
                    if line_range:
                        start, end = line_range
                        start = max(0, start)
                        end = min(total_lines, end)
                        selected = lines[start:end]
                        file_context = f"File: {file_path} (lines {start}-{end} of {total_lines}):\n"
                        for i, line in enumerate(selected, start):
                            file_context += f"{i}: {line}\n"
                    else:
                        # Truncate for large files
                        if total_lines > 50:
                            file_context = f"File: {file_path} ({total_lines} lines, showing first 25 + last 25):\n"
                            for i, line in enumerate(lines[:25]):
                                file_context += f"{i}: {line}\n"
                            file_context += f"... ({total_lines - 50} lines omitted) ...\n"
                            for i, line in enumerate(lines[-25:], total_lines - 25):
                                file_context += f"{i}: {line}\n"
                        else:
                            file_context = f"File: {file_path} ({total_lines} lines):\n"
                            for i, line in enumerate(lines):
                                file_context += f"{i}: {line}\n"
                    
                    context_parts.append(file_context)
            except Exception as e:
                context_parts.append(f"[Could not read file: {e}]")
        
        context_str = '\n'.join(context_parts) if context_parts else "No additional context."
        
        prompt = f"""You are a debugging assistant. An AI (Claude) is stuck on a task and needs help.

PROBLEM: {problem}

CONTEXT:
{context_str}

Analyze and provide:
1. ROOT CAUSE: What's actually wrong (be specific)
2. FIX: The exact solution - give concrete code/commands with line numbers
3. PREVENTION: One sentence on avoiding this

Be concise. Give exact line numbers and exact text."""

        result = _gemini_query(prompt, timeout=45)
        
        return f"""🔮 Gemini Debug Analysis

{result}

---
💡 Different perspective from Gemini model"""

    @mcp.tool()
    def gemini_analyze(path: str) -> str:
        """
        Gemini-powered file analysis - understand a file before editing.
        
        Args:
            path: File path to analyze
        """
        try:
            p = Path(path).expanduser()
            if not p.exists():
                return f"[Error: File not found: {path}]"
            
            content = p.read_text()
            lines = content.split('\n')
            
            # Truncate for prompt
            preview = '\n'.join(f"{i}: {line}" for i, line in enumerate(lines[:80]))
            if len(lines) > 80:
                preview += f"\n... ({len(lines) - 80} more lines)"
            
            prompt = f"""Analyze this file structure:

File: {path} ({len(lines)} lines, {len(content)} bytes)

{preview}

Provide:
1. PURPOSE: What this file does (one sentence)
2. STRUCTURE: Key sections with line numbers
3. EDIT TIPS: What to watch out for when modifying"""

            result = _gemini_query(prompt, timeout=30)
            
            return f"""📊 Gemini File Analysis: {path}

{result}"""
            
        except Exception as e:
            return f"[Error: {e}]"

    @mcp.tool()
    def gemini_suggest(file_path: str, goal: str) -> str:
        """
        Gemini suggests how to edit a file - get edit strategy from Gemini.
        
        Args:
            file_path: File you want to edit
            goal: What you're trying to accomplish
        """
        try:
            p = Path(file_path).expanduser()
            if not p.exists():
                return f"[Error: File not found: {file_path}]"
            
            content = p.read_text()
            lines = content.split('\n')
            
            preview = '\n'.join(f"{i}: {line}" for i, line in enumerate(lines[:60]))
            if len(lines) > 60:
                preview += f"\n... ({len(lines) - 60} more lines)"
            
            prompt = f"""Suggest edits for this file.

AVAILABLE TOOLS:
- find_in_file(path, pattern) - find text, returns line numbers
- replace_at_line(path, line_num, old_text, new_text) - replace on one line
- replace_lines(path, start, end, content) - replace line range
- insert_lines(path, line_num, content) - insert before line
- delete_lines(path, start, end) - delete range

FILE ({len(lines)} lines):
{preview}

GOAL: {goal}

Give exact tool calls with actual line numbers from the file. Be specific."""

            result = _gemini_query(prompt, timeout=30)
            
            return f"""📝 Gemini Edit Strategy

Goal: {goal}

{result}"""
            
        except Exception as e:
            return f"[Error: {e}]"
