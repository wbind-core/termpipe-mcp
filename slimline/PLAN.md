# Slimline MCP Server — Implementation Plan

## Architecture

Thin Python MCP server wrapping three layers:
1. **File operations** — direct Python stdlib (read, write, edit, search)
2. **Desktop automation** — cond/wput/kb subprocess calls
3. **Shell execution** — subprocess.run

No AT-SPI, no Rust binaries, no FastAPI backend, no telemetry middleware.
One server, one namespace, ~15 tools, optimized for 4b-9b models.

## Tool Inventory (15 tools)

### File Operations (7 tools)
| Tool | Source | Telemetry Rank | Calls |
|------|--------|----------------|-------|
| `read_file` | core.py ✅ | #4 | 1,234 |
| `write_file` | core.py ✅ | #7 | 292 |
| `read_lines` | STUB → new | #2 | 2,365 |
| `search_file_content` | STUB → new | #5 | 674 |
| `list_directory` | STUB → new | #6 | 582 |
| `smart_replace` | surgical.py ✅ | #3 | 1,643 |
| `patch_line` | surgical.py ✅ | #10 | 165 |

### Desktop Automation (6 tools — all wrap cond/wput/kb)
| Tool | Wraps | Purpose |
|------|-------|---------|
| `screenshot` | `cond --sc` | Capture screen to file, return path |
| `click` | `wput click` | Click at x,y coordinates |
| `type_text` | `wput type` | Type string into active window |
| `press_key` | `wput key` | Send key combo (ctrl+c, super+space, etc.) |
| `list_windows` | `wput list` | List open windows with app_id/title |
| `focus_window` | `wput focus` | Activate window by name/id |

### Shell & Undo (2 tools)
| Tool | Source | Notes |
|------|--------|-------|
| `termf_exec` | exec_.py ✅ | Shell command execution |
| `undo` | surgical.py ✅ | In-memory edit rollback |

## Implementation Steps

### Phase 1: Fill the 4 stubs (file operations)

**stub_tool_1 → `read_lines`**
- Read specific line ranges from a file
- Args: path, start_line (0-based), end_line (exclusive)
- Returns: lines with line numbers
- Source: Python stdlib, ~20 lines

**stub_tool_2 → `search_file_content`**
- Grep-like content search across files
- Args: path (file or directory), pattern (regex), include (glob filter)
- Returns: matching lines with file paths and line numbers
- Source: subprocess calls `rg` (ripgrep) or falls back to `grep -rn`

**stub_tool_3 → `list_directory`**
- List files and directories in a path
- Args: path
- Returns: entries with / suffix for directories
- Source: Python stdlib, ~15 lines

**stub_tool_4 → `glob_files`**
- Find files matching glob patterns
- Args: pattern (e.g. "*.py", "src/**/*.ts"), path (optional root)
- Returns: matching file paths
- Source: Python pathlib.glob or subprocess `find`

### Phase 2: Add desktop automation module

**New file: `tools/desktop.py`**

Wrap cond/wput/kb as MCP tools. Each tool:
1. Accepts MCP-typed parameters
2. Calls cond/wput/kb via subprocess.run
3. Parses JSON output (--format json)
4. Returns formatted string for the model

Tools:
- `screenshot(path?)` → `cond --sc [path] --format json`
- `click(x, y, button?)` → `wput click <button>` after `wput move <x> <y>`
- `type_text(text)` → `wput type "<text>"`
- `press_key(key_combo)` → `wput key <combo>`
- `list_windows()` → `wput list --format json`
- `focus_window(target)` → `wput focus "<target>"`

### Phase 3: Cleanup

- Remove `stubs.py` (replaced by real implementations)
- Update `__init__.py` to register new modules
- Update `server.py` tool count in print statement
- Remove workspace_gate, reviewer, telemetry dependencies from imports

## Files to Modify

```
slimline/
├── server.py              (no changes needed)
├── tools/
│   ├── __init__.py        (add desktop module)
│   ├── core.py            (no changes)
│   ├── exec_.py           (no changes)
│   ├── surgical.py        (no changes)
│   ├── stubs.py           (DELETE — replaced by real impls)
│   ├── read_lines.py      (NEW — from stub_tool_1)
│   ├── search.py          (NEW — from stub_tool_2)
│   ├── listdir.py         (NEW — from stub_tool_3)
│   ├── glob.py            (NEW — from stub_tool_4)
│   └── desktop.py         (NEW — cond/wput/kb wrapper)
```

## Dependencies

- Python stdlib only for file operations
- `rg` (ripgrep) preferred for search, `grep -rn` fallback
- `cond`, `wput`, `kb` on $PATH for desktop automation
- `mcp` (fastmcp) — already a dependency

## Token Budget Impact

Current full TermPipe: 87 tools, ~2000 tokens for tool registration
Slimline target: 15 tools, ~400 tokens for tool registration
Savings: ~80% reduction in tool-definition overhead
