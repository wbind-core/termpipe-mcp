"""
Surgical file editing tools for TermPipe MCP Server.
Enhanced with inline edits, smart diffs, and robust error handling.
"""

from pathlib import Path
from typing import Optional, Tuple
import difflib


def _read_file_lines(path: str) -> list[str]:
    """Helper to read file as list of lines."""
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    content = p.read_text()
    return content.split("\n")


def _write_file_lines(path: str, lines: list[str]) -> None:
    """Helper to write lines back to file."""
    p = Path(path).expanduser()
    p.write_text("\n".join(lines))


def _generate_diff(old_lines: list[str], new_lines: list[str], context: int = 3) -> str:
    """Generate a unified diff between old and new content."""
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile='before', tofile='after',
        lineterm='', n=context
    )
    return '\n'.join(diff)


def _generate_inline_diff(old: str, new: str) -> str:
    """Generate character-level diff for a single line."""
    matcher = difflib.SequenceMatcher(None, old, new)
    result = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == 'equal':
            result.append(old[i1:i2])
        elif op == 'replace':
            result.append(f'{{-{old[i1:i2]}-}}{{+{new[j1:j2]}+}}')
        elif op == 'delete':
            result.append(f'{{-{old[i1:i2]}-}}')
        elif op == 'insert':
            result.append(f'{{+{new[j1:j2]}+}}')
    return ''.join(result)


def _find_similar_lines(lines: list[str], target: str, threshold: float = 0.6) -> list[Tuple[int, str, float]]:
    """Find lines similar to target, returns (line_num, content, similarity)."""
    results = []
    target_lower = target.lower().strip()
    
    for i, line in enumerate(lines):
        line_lower = line.lower().strip()
        if not line_lower:
            continue
        
        # Quick substring check first
        if target_lower in line_lower or line_lower in target_lower:
            results.append((i, line, 0.9))
            continue
            
        # Fuzzy match
        ratio = difflib.SequenceMatcher(None, target_lower, line_lower).ratio()
        if ratio >= threshold:
            results.append((i, line, ratio))
    
    return sorted(results, key=lambda x: -x[2])[:5]



def _ai_analyze_error(error_type: str, context: dict) -> str:
    """Use iFlow to analyze a failed edit and provide precise diagnosis."""
    try:
        from termpipe_mcp.tools.iflow import iflow_query
        
        prompt = f"""You are a code editing error analyst. Analyze this failed edit attempt and explain EXACTLY what went wrong in 2-3 sentences. Be specific about character/whitespace differences.

Error Type: {error_type}

"""
        if error_type == "text_not_found":
            prompt += f"""Searched for:
```
{context.get('searched_for', '')}
```

Line {context.get('line_number', '?')} actually contains:
```
{context.get('actual_line', '')}
```

Character-level diff: {context.get('char_diff', 'N/A')}
"""
        elif error_type == "wrong_line":
            prompt += f"""Expected text on line {context.get('expected_line', '?')}
But found it on lines: {context.get('found_on_lines', [])}

Text searched: {context.get('searched_for', '')[:100]}
"""
        elif error_type == "ambiguous":
            prompt += f"""Text appears {context.get('match_count', 0)} times in file.
Matches on lines: {context.get('match_lines', [])}
Text: {context.get('searched_for', '')[:100]}
"""
        
        prompt += """
Respond in this exact format:
❌ PROBLEM: [one sentence explaining the exact issue]
✅ FIX: [one sentence with the precise correction needed]"""
        
        result = iflow_query(prompt, model="qwen3-coder-plus", max_tokens=150, temperature=0.1)
        return result
        
    except Exception as e:
        return ""




def _ai_analyze_error(error_type: str, context: dict) -> str:
    """Use iFlow to analyze a failed edit and provide precise diagnosis."""
    try:
        from termpipe_mcp.tools.iflow import iflow_query
        
        prompt = f"""You are a code editing error analyst. Analyze this failed edit attempt and explain EXACTLY what went wrong in 2-3 sentences. Be specific about character/whitespace differences.

Error Type: {error_type}

"""
        if error_type == "text_not_found":
            prompt += f"""Searched for:
```
{context.get('searched_for', '')}
```

Line {context.get('line_number', '?')} actually contains:
```
{context.get('actual_line', '')}
```

Character-level diff: {context.get('char_diff', 'N/A')}
"""
        elif error_type == "wrong_line":
            prompt += f"""Expected text on line {context.get('expected_line', '?')}
But found it on lines: {context.get('found_on_lines', [])}

Text searched: {context.get('searched_for', '')[:100]}
"""
        elif error_type == "ambiguous":
            prompt += f"""Text appears {context.get('match_count', 0)} times in file.
Matches on lines: {context.get('match_lines', [])}
Text: {context.get('searched_for', '')[:100]}
"""
        
        prompt += """
Respond in this exact format:
❌ PROBLEM: [one sentence explaining the exact issue]
✅ FIX: [one sentence with the precise correction needed]"""
        
        result = iflow_query(prompt, model="qwen3-coder-plus", max_tokens=150, temperature=0.1)
        return result
        
    except Exception as e:
        return ""



def register_tools(mcp):
    """Register surgical editing tools with the MCP server."""
    
    @mcp.tool()
    def read_lines(path: str, start_line: int, end_line: Optional[int] = None) -> str:
        """
        Read specific line range from a file.
        
        Args:
            path: File path
            start_line: Start line (0-based)
            end_line: End line (exclusive). None = just start_line
        """
        try:
            lines = _read_file_lines(path)
            
            if end_line is None:
                end_line = start_line + 1
            
            if start_line < 0 or start_line >= len(lines):
                return f"[Error: Line {start_line} out of range (file has {len(lines)} lines)]"
            
            selected = lines[start_line:end_line]
            
            output = f"Lines {start_line}-{min(end_line, len(lines))-1} of {path}:\n\n"
            for i, line in enumerate(selected, start_line):
                output += f"{i:4d} | {line}\n"
            
            return output
            
        except FileNotFoundError as e:
            return f"[Error: {str(e)}]"
        except Exception as e:
            return f"[Error: {str(e)}]"

    @mcp.tool()
    def insert_lines(path: str, line_number: int, content: str) -> str:
        """
        Insert lines at a specific line number.
        
        Args:
            path: File path
            line_number: Line to insert BEFORE (0-based)
            content: Content to insert (can be multi-line)
        """
        try:
            lines = _read_file_lines(path)
            new_lines = content.split("\n")
            
            if line_number < 0:
                line_number = 0
            if line_number > len(lines):
                line_number = len(lines)
            
            old_lines = lines.copy()
            lines = lines[:line_number] + new_lines + lines[line_number:]
            _write_file_lines(path, lines)
            
            # Show diff
            diff = _generate_diff(old_lines, lines)
            
            return f"✅ Inserted {len(new_lines)} line(s) at line {line_number}\n\n```diff\n{diff}\n```"
            
        except FileNotFoundError as e:
            return f"[Error: {str(e)}]"
        except Exception as e:
            return f"[Error: {str(e)}]"

    @mcp.tool()
    def replace_lines(path: str, start_line: int, end_line: int, content: str) -> str:
        """
        Replace a range of lines with new content.
        
        Args:
            path: File path
            start_line: Start line (0-based, inclusive)
            end_line: End line (exclusive)
            content: Replacement content
        """
        try:
            lines = _read_file_lines(path)
            new_lines = content.split("\n")
            
            if start_line < 0 or start_line >= len(lines):
                return f"[Error: Start line {start_line} out of range (file has {len(lines)} lines)]"
            if end_line < start_line:
                return f"[Error: End line must be >= start line]"
            
            old_lines = lines.copy()
            old_count = end_line - start_line
            lines = lines[:start_line] + new_lines + lines[end_line:]
            _write_file_lines(path, lines)
            
            # Show diff
            diff = _generate_diff(old_lines, lines)
            
            return f"✅ Replaced lines {start_line}-{end_line-1} ({old_count} → {len(new_lines)} lines)\n\n```diff\n{diff}\n```"
            
        except FileNotFoundError as e:
            return f"[Error: {str(e)}]"
        except Exception as e:
            return f"[Error: {str(e)}]"

    @mcp.tool()
    def replace_at_line(path: str, line_number: int, old_text: str, new_text: str) -> str:
        """
        Replace text within a specific line - MOST SURGICAL TOOL.
        
        Only modifies the exact text on the exact line. Perfect for:
        - Changing a variable value: replace_at_line(f, 50, "x = 1", "x = 2")
        - Fixing a typo: replace_at_line(f, 100, "teh", "the")
        - Updating a string: replace_at_line(f, 25, '"old"', '"new"')
        
        Args:
            path: File path
            line_number: Line number (0-based)
            old_text: Text to find on that line
            new_text: Text to replace it with
        """
        try:
            lines = _read_file_lines(path)
            
            # Validate line number
            if line_number < 0 or line_number >= len(lines):
                return f"""[Error: Line {line_number} out of range]

📊 File has {len(lines)} lines (valid range: 0-{len(lines)-1})

💡 Use find_in_file('{path}', '{old_text}') to locate the correct line."""
            
            line = lines[line_number]
            
            # Check if old_text exists on this line
            if old_text not in line:
                # Build helpful error message
                error = f"""[Error: Text not found on line {line_number}]

📍 Line {line_number} contains:
   {line}

🔍 Searching for:
   {old_text}

"""
                # Show inline diff of what's different
                if line.strip():
                    similar = _find_similar_lines([line], old_text, threshold=0.3)
                    if similar:
                        inline_diff = _generate_inline_diff(old_text, line.strip())
                        error += f"📐 Character diff:\n   {inline_diff}\n\n"
                
                # Search whole file for the text
                matches = []
                for i, l in enumerate(lines):
                    if old_text in l:
                        matches.append((i, l.strip()[:60]))
                
                if matches:
                    error += f"💡 Found '{old_text}' on other lines:\n"
                    for ln, content in matches[:5]:
                        error += f"   Line {ln}: {content}\n"
                    error += f"\n   Try: replace_at_line('{path}', {matches[0][0]}, '{old_text}', '{new_text}')"
                else:
                    # Fuzzy search
                    similar = _find_similar_lines(lines, old_text)
                    if similar:
                        error += f"💡 Similar lines found:\n"
                        for ln, content, score in similar[:3]:
                            error += f"   Line {ln} ({score:.0%} match): {content.strip()[:60]}\n"
                
                # AI analysis
                ai_analysis = _ai_analyze_error("text_not_found", {
                    "searched_for": old_text,
                    "line_number": line_number,
                    "actual_line": line,
                    "char_diff": _generate_inline_diff(old_text, line.strip()) if line.strip() else "N/A"
                })
                if ai_analysis:
                    error += f"\n\n🤖 AI Analysis:\n{ai_analysis}"
                
                return error
            
            # Check for multiple occurrences on same line
            count = line.count(old_text)
            if count > 1:
                return f"""[Warning: Multiple matches on line {line_number}]

📍 Line {line_number}:
   {line}

🔢 '{old_text}' appears {count} times on this line.
   All {count} occurrences will be replaced.

💡 To replace only one, use a more specific pattern that includes surrounding context."""
            
            # Perform the replacement
            old_line = line
            new_line = line.replace(old_text, new_text)
            lines[line_number] = new_line
            _write_file_lines(path, lines)
            
            # Show inline diff
            inline_diff = _generate_inline_diff(old_line, new_line)
            
            return f"""✅ Replaced on line {line_number}

📐 Diff:
   {inline_diff}

Before: {old_line.strip()}
After:  {new_line.strip()}"""
            
        except FileNotFoundError as e:
            return f"[Error: {str(e)}]"
        except Exception as e:
            return f"[Error: {str(e)}]"

    @mcp.tool()
    def smart_replace(path: str, old_text: str, new_text: str, expected_line: Optional[int] = None) -> str:
        """
        Smart find-and-replace with diff preview and detailed error handling.
        
        If old_text is unique in the file, replaces it.
        If ambiguous or not found, shows helpful diagnostics.
        
        Args:
            path: File path
            old_text: Text to find and replace
            new_text: Replacement text
            expected_line: Optional hint for which line (helps disambiguate)
        """
        try:
            lines = _read_file_lines(path)
            content = "\n".join(lines)
            
            # Find all occurrences
            matches = []
            for i, line in enumerate(lines):
                if old_text in line:
                    matches.append((i, line))
            
            # Case 1: Not found
            if not matches:
                error = f"""[Error: Text not found in file]

🔍 Searching for:
   {old_text[:100]}{'...' if len(old_text) > 100 else ''}

"""
                # Fuzzy search for similar content
                similar = _find_similar_lines(lines, old_text)
                if similar:
                    error += "💡 Similar lines found:\n"
                    for ln, line_content, score in similar:
                        error += f"\n   Line {ln} ({score:.0%} match):\n"
                        error += f"   {line_content.strip()[:80]}\n"
                        if score > 0.7:
                            diff = _generate_inline_diff(old_text.strip(), line_content.strip())
                            error += f"   Diff: {diff[:100]}\n"
                else:
                    error += "❌ No similar content found in file.\n"
                    error += f"\n📊 File has {len(lines)} lines.\n"
                    error += "💡 Use find_in_file() to search for keywords."
                
                # AI analysis for not found
                best_match = similar[0] if similar else None
                ai_analysis = _ai_analyze_error("text_not_found", {
                    "searched_for": old_text[:200],
                    "line_number": best_match[0] if best_match else "N/A",
                    "actual_line": best_match[1] if best_match else "No similar lines",
                    "char_diff": _generate_inline_diff(old_text.strip(), best_match[1].strip())[:200] if best_match else "N/A"
                })
                if ai_analysis:
                    error += f"\n\n🤖 AI Analysis:\n{ai_analysis}"
                
                return error
            
            # Case 2: Multiple matches - need disambiguation
            if len(matches) > 1:
                # If expected_line is provided and matches one, use it
                if expected_line is not None:
                    exact = [(ln, l) for ln, l in matches if ln == expected_line]
                    if exact:
                        matches = exact
                    else:
                        return f"""[Error: expected_line {expected_line} doesn't contain the text]

Found '{old_text[:30]}...' on these lines instead:
{chr(10).join(f'   Line {ln}: {l.strip()[:50]}' for ln, l in matches[:5])}

💡 Use one of these line numbers with expected_line parameter."""
                
                if len(matches) > 1:
                    output = f"""[Ambiguous: Found {len(matches)} matches]

'{old_text[:40]}{'...' if len(old_text) > 40 else ''}' appears on multiple lines:

"""
                    for ln, line_content in matches[:10]:
                        output += f"   Line {ln}: {line_content.strip()[:60]}\n"
                    
                    if len(matches) > 10:
                        output += f"   ... and {len(matches) - 10} more\n"
                    
                    output += f"""
💡 Options:
   1. Use expected_line to specify: smart_replace('{path}', ..., expected_line={matches[0][0]})
   2. Use replace_at_line for surgical precision: replace_at_line('{path}', {matches[0][0]}, ...)
   3. Include more context in old_text to make it unique"""
                    
                    # AI analysis for ambiguous
                    ai_analysis = _ai_analyze_error("ambiguous", {
                        "match_count": len(matches),
                        "match_lines": [ln for ln, _ in matches[:10]],
                        "searched_for": old_text[:100]
                    })
                    if ai_analysis:
                        output += f"\n\n🤖 AI Analysis:\n{ai_analysis}"
                    
                    return output
            
            # Case 3: Unique match - perform replacement
            match_line, match_content = matches[0]
            old_lines = lines.copy()
            lines[match_line] = match_content.replace(old_text, new_text)
            _write_file_lines(path, lines)
            
            # Generate diff
            diff = _generate_diff(old_lines, lines)
            
            return f"""✅ Replaced on line {match_line}

```diff
{diff}
```"""
            
        except FileNotFoundError as e:
            return f"[Error: {str(e)}]"
        except Exception as e:
            return f"[Error: {str(e)}]"

    @mcp.tool()
    def delete_lines(path: str, start_line: int, end_line: int) -> str:
        """
        Delete a range of lines.
        
        Args:
            path: File path
            start_line: Start line (0-based, inclusive)
            end_line: End line (exclusive)
        """
        try:
            lines = _read_file_lines(path)
            
            if start_line < 0 or start_line >= len(lines):
                return f"[Error: Start line {start_line} out of range (file has {len(lines)} lines)]"
            
            old_lines = lines.copy()
            deleted_content = lines[start_line:end_line]
            deleted = end_line - start_line
            lines = lines[:start_line] + lines[end_line:]
            _write_file_lines(path, lines)
            
            # Show what was deleted
            output = f"✅ Deleted lines {start_line}-{end_line-1} ({deleted} lines)\n\n"
            output += "🗑️  Deleted content:\n```\n"
            for i, line in enumerate(deleted_content, start_line):
                output += f"{i:4d} | {line}\n"
            output += "```"
            
            return output
            
        except FileNotFoundError as e:
            return f"[Error: {str(e)}]"
        except Exception as e:
            return f"[Error: {str(e)}]"

    @mcp.tool()
    def find_in_file(path: str, pattern: str, max_matches: int = 50, context: int = 0) -> str:
        """
        Find pattern in file with line numbers and optional context.
        
        Args:
            path: File path
            pattern: Text to search for
            max_matches: Maximum matches to return
            context: Lines of context to show around each match
        """
        try:
            lines = _read_file_lines(path)
            matches = []
            
            for i, line in enumerate(lines):
                if pattern.lower() in line.lower():
                    matches.append(i)
                    if len(matches) >= max_matches:
                        break
            
            if not matches:
                # Fuzzy search
                similar = _find_similar_lines(lines, pattern)
                if similar:
                    output = f"No exact matches for '{pattern}'\n\n💡 Similar lines:\n"
                    for ln, content, score in similar:
                        output += f"   Line {ln} ({score:.0%}): {content.strip()[:60]}\n"
                    return output
                return f"No matches found for: {pattern}"
            
            output = f"Found {len(matches)} matches for '{pattern}':\n\n"
            
            for match_line in matches:
                if context > 0:
                    start = max(0, match_line - context)
                    end = min(len(lines), match_line + context + 1)
                    output += f"--- Line {match_line} ---\n"
                    for i in range(start, end):
                        marker = "→ " if i == match_line else "  "
                        output += f"{marker}{i:4d} | {lines[i]}\n"
                    output += "\n"
                else:
                    output += f"Line {match_line}: {lines[match_line].strip()[:80]}\n"
            
            return output
            
        except FileNotFoundError:
            return f"[Error: File not found: {path}]"
        except Exception as e:
            return f"[Error: {str(e)}]"

    @mcp.tool()
    def read_multiple_files(paths: list[str]) -> str:
        """
        Read contents of multiple files at once.
        
        Args:
            paths: List of file paths to read
        """
        results = []
        for path in paths:
            p = Path(path).expanduser()
            try:
                if p.suffix.lower() in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp']:
                    import base64
                    with open(p, 'rb') as f:
                        b64 = base64.b64encode(f.read()).decode()
                        results.append(f"=== {path} ===\n[Image data: {p.suffix} ({len(b64)} bytes)]\n")
                else:
                    content = p.read_text()
                    results.append(f"=== {path} ===\n{content}\n")
            except Exception as e:
                results.append(f"=== {path} ===\n[Error: {str(e)}]\n")
        
        return "\n".join(results)
