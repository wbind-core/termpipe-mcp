"""
Debug assistance tools - AI-powered debugging helper.
Lightweight multi-agent orchestration for when Claude gets stuck.
"""

from typing import Optional
from pathlib import Path


def register_tools(mcp):
    """Register debug assistance tools with the MCP server."""
    
    @mcp.tool()
    def debug_assist(
        problem: str,
        file_path: Optional[str] = None,
        line_range: Optional[tuple[int, int]] = None,
        include_history: bool = True
    ) -> str:
        """
        AI-powered debugging assistant - call when stuck on a problem.
        
        Uses a fast iFlow model to analyze your situation and provide
        specific, actionable guidance. Like having a pair programmer.
        
        Use cases:
        - Can't figure out why an edit isn't working
        - File has unexpected content/structure  
        - Need help understanding an error
        - Stuck on how to approach a task
        
        Args:
            problem: Describe what you're trying to do and what's going wrong
            file_path: Optional file to include as context
            line_range: Optional (start, end) line range to focus on
            include_history: Include recent tool call history (default: True)
        
        Returns:
            AI analysis with specific fix recommendations
        """
        from termpipe_mcp.tools.iflow import iflow_query
        from termpipe_mcp.tools.system import _tool_call_history
        
        # Build context
        context_parts = []
        
        # Add recent tool history
        if include_history and _tool_call_history:
            recent = _tool_call_history[-5:]
            history_str = "Recent tool calls:\n"
            for call in recent:
                result_preview = call.get('result_preview', '')[:150]
                history_str += f"  • {call['tool']}({call['args']})\n"
                if 'Error' in result_preview or 'error' in result_preview:
                    history_str += f"    → {result_preview}\n"
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
                        file_context = f"File: {file_path} (lines {start}-{end} of {total_lines}):\n```\n"
                        for i, line in enumerate(selected, start):
                            file_context += f"{i:4d} | {line}\n"
                        file_context += "```"
                    else:
                        # Show first/last if file is long
                        if total_lines > 60:
                            file_context = f"File: {file_path} ({total_lines} lines, showing first 30 + last 30):\n```\n"
                            for i, line in enumerate(lines[:30]):
                                file_context += f"{i:4d} | {line}\n"
                            file_context += f"... ({total_lines - 60} lines omitted) ...\n"
                            for i, line in enumerate(lines[-30:], total_lines - 30):
                                file_context += f"{i:4d} | {line}\n"
                            file_context += "```"
                        else:
                            file_context = f"File: {file_path} ({total_lines} lines):\n```\n"
                            for i, line in enumerate(lines):
                                file_context += f"{i:4d} | {line}\n"
                            file_context += "```"
                    
                    context_parts.append(file_context)
            except Exception as e:
                context_parts.append(f"[Could not read file: {e}]")
        
        # Build the prompt
        prompt = f"""You are a debugging assistant helping an AI model (Claude) that's stuck on a task.

PROBLEM:
{problem}

CONTEXT:
{chr(10).join(context_parts) if context_parts else "No additional context provided."}

Analyze this situation and provide:
1. **Root Cause**: What's actually going wrong (be specific)
2. **Fix**: The exact solution (give concrete code/commands)
3. **Prevention**: How to avoid this in future

Be concise and actionable. Give exact line numbers, exact text to use, exact commands to run.
Format your fix so it can be directly used."""

        try:
            result = iflow_query(
                prompt, 
                model="qwen3-coder-plus",  # Fast model for quick debugging
                max_tokens=600,
                temperature=0.2
            )
            
            return f"""🔧 Debug Assistant

{result}

---
💡 Based on analysis of {'recent tool history + ' if include_history else ''}{f'file {file_path}' if file_path else 'provided context'} """
            
        except Exception as e:
            return f"[Debug assist error: {e}]"

    @mcp.tool()
    def analyze_file_structure(path: str) -> str:
        """
        AI-powered analysis of a file's structure and content.
        
        Useful when you need to understand a file before editing it,
        or when the file structure is unexpected.
        
        Args:
            path: File path to analyze
        """
        from termpipe_mcp.tools.iflow import iflow_query
        
        try:
            p = Path(path).expanduser()
            if not p.exists():
                return f"[Error: File not found: {path}]"
            
            content = p.read_text()
            lines = content.split('\n')
            
            # Basic stats
            stats = f"""File: {path}
Lines: {len(lines)}
Size: {len(content)} bytes
Extension: {p.suffix}
"""
            
            # Prepare content preview (first 100 lines max)
            preview = '\n'.join(f"{i:4d} | {line}" for i, line in enumerate(lines[:100]))
            if len(lines) > 100:
                preview += f"\n... ({len(lines) - 100} more lines)"
            
            prompt = f"""Analyze this file and provide a structural overview:

{stats}

Content:
```
{preview}
```

Provide:
1. **Type/Purpose**: What kind of file is this, what does it do
2. **Structure**: Key sections, classes, functions (with line numbers)
3. **Key Points**: Important things to know when editing this file
4. **Gotchas**: Potential pitfalls or tricky parts

Be concise but specific with line numbers."""

            result = iflow_query(
                prompt,
                model="qwen3-coder-plus",
                max_tokens=500,
                temperature=0.1
            )
            
            return f"""📊 File Analysis: {path}

{stats}
{result}"""
            
        except Exception as e:
            return f"[Error analyzing file: {e}]"

    @mcp.tool()
    def suggest_edit_approach(file_path: str, goal: str) -> str:
        """
        AI suggests the best approach for editing a file.
        
        Tell it what you want to accomplish, and it recommends
        which surgical tools to use and in what order.
        
        Args:
            file_path: File you want to edit
            goal: What you're trying to accomplish
        """
        from termpipe_mcp.tools.iflow import iflow_query
        
        try:
            p = Path(file_path).expanduser()
            if not p.exists():
                return f"[Error: File not found: {file_path}]"
            
            content = p.read_text()
            lines = content.split('\n')
            
            # Show structure
            preview = '\n'.join(f"{i:4d} | {line}" for i, line in enumerate(lines[:80]))
            if len(lines) > 80:
                preview += f"\n... ({len(lines) - 80} more lines)"
            
            prompt = f"""I need to edit a file. Suggest the best approach using these surgical tools:

AVAILABLE TOOLS:
- find_in_file(path, pattern) → Find text with line numbers
- read_lines(path, start, end) → Read specific line range
- replace_at_line(path, line_num, old_text, new_text) → Replace text on one line
- replace_lines(path, start, end, new_content) → Replace line range
- insert_lines(path, line_num, content) → Insert before a line
- delete_lines(path, start, end) → Delete line range
- smart_replace(path, old, new) → Find & replace if unique

FILE ({len(lines)} lines):
```
{preview}
```

GOAL: {goal}

Provide:
1. **Strategy**: Which tool(s) to use and why
2. **Steps**: Exact tool calls with arguments (use actual line numbers from the file)
3. **Verification**: How to confirm the edit worked

Be specific - give exact line numbers, exact text to match."""

            result = iflow_query(
                prompt,
                model="qwen3-coder-plus",
                max_tokens=500,
                temperature=0.2
            )
            
            return f"""📝 Edit Strategy for: {file_path}

Goal: {goal}

{result}"""
            
        except Exception as e:
            return f"[Error: {e}]"

def analyze_and_suggest_fix(command: str, error_message: str, help_output: str = "") -> str:
    """
    Analyzes a failed command and suggests a fix using an AI model.
    """
    from termpipe_mcp.tools.iflow import iflow_query

    prompt = f"""A command failed. Analyze the command, error, and help output to suggest a fix.

**Failed Command:**
```
{command}
```

**Error Message:**
```
{error_message}
```

**Command --help Output:**
```
{help_output}
```

**Instructions:**
Based on the error message and the `--help` output, analyze the failed command and provide a corrected command.

**Analysis and Suggestion:**
1.  **Root Cause:** What is the most likely cause of the error?
2.  **Suggested Command:** Provide the corrected command.
3.  **Explanation:** Briefly explain why the original command failed and why the suggested command works.
"""

    try:
        suggestion = iflow_query(
            prompt,
            model="qwen3-coder-plus",
            max_tokens=400,
            temperature=0.1
        )
        return f"\n\n---\n**AI Debugging Assistant:**\n{suggestion}"
    except Exception as e:
        return f"\n\n[Error calling AI assistant: {e}]"