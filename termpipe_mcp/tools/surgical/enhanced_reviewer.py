"""
Enhanced reviewer module for TermPipe pre-commit review system.

Adds semantic duplicate detection, cross-file dependency analysis,
and enhanced language support beyond the original implementation.
"""

import ast
import re
import sys
import tempfile
import threading
from pathlib import Path
from typing import Optional, List, Dict, Set, Tuple, Any
import subprocess
import json
import textwrap
import time
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_WALK = 60
MAX_CONTEXT_LINES = 800
SEMANTIC_SIMILARITY_THRESHOLD = 0.85

# Language-specific parsers
LANGUAGE_PARSERS = {
    "py": "ast",
    "js": "acorn",  # Node.js parser
    "ts": "typescript",  # TypeScript compiler
    "go": "go/parser",
    "rs": "syn",  # Rust syntax parser
    "java": "javac",
    "cpp": "clang",
    "c": "clang",
}

# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------


@dataclass
class SemanticBlock:
    """Represents a semantic code block for duplicate detection."""

    text: str
    normalized_text: str
    start_line: int
    end_line: int
    ast_hash: str  # Hash of AST structure
    imports: Set[str]
    exports: Set[str]
    complexity_score: float


@dataclass
class CrossFileDependency:
    """Represents a dependency relationship between files."""

    from_file: str
    to_file: str
    import_type: str  # import, require, use, etc.
    symbols: Set[str]
    line_number: int


@dataclass
class ReviewContext:
    """Enhanced context for reviewer decisions."""

    path: str
    language: str
    edit_region: Tuple[int, int]
    surrounding_context: str
    semantic_blocks: List[SemanticBlock]
    cross_file_deps: List[CrossFileDependency]
    potential_duplicates: List[SemanticBlock]
    import_issues: List[str]
    syntax_valid: bool


# ---------------------------------------------------------------------------
# Semantic Analysis
# ---------------------------------------------------------------------------


def normalize_code_block(code: str, language: str) -> str:
    """
    Normalize code block for semantic comparison.
    Removes comments, whitespace, variable names for structural comparison.
    """
    if language == "py":
        try:
            # Parse AST and regenerate for normalization
            tree = ast.parse(code)
            # Remove docstrings and comments
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if (
                        node.body
                        and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                        and isinstance(node.body[0].value.value, str)
                    ):
                        node.body.pop(0)
            return ast.unparse(tree)
        except:
            # Fallback to regex normalization
            code = re.sub(r"#.*$", "", code, flags=re.MULTILINE)
            code = re.sub(r'""".*?"""', "", code, flags=re.DOTALL)
            code = re.sub(r"'''.*?'''", "", code, flags=re.DOTALL)

    elif language in ["js", "ts"]:
        # Basic JS/TS normalization
        code = re.sub(r"//.*$", "", code, flags=re.MULTILINE)
        code = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)

    # Generic normalization
    code = re.sub(r"\s+", " ", code.strip())
    return code


def compute_ast_hash(code: str, language: str) -> str:
    """Compute structural hash of code ignoring variable names."""
    try:
        if language == "py":
            tree = ast.parse(code)
            # Create structural representation
            struct_repr = []
            for node in ast.walk(tree):
                if isinstance(node, ast.AST):
                    struct_repr.append(f"{type(node).__name__}:{getattr(node, 'lineno', 0)}")
            return str(hash("|".join(struct_repr)))
    except:
        pass
    return str(hash(normalize_code_block(code, language)))


def extract_imports_exports(code: str, language: str) -> Tuple[Set[str], Set[str]]:
    """Extract imports and exports from code."""
    imports = set()
    exports = set()

    if language == "py":
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                # Import statements
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    for alias in node.names:
                        imports.add(f"{module}.{alias.name}" if module else alias.name)
                # Function/class definitions (exports)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    exports.add(node.name)
        except:
            pass

    elif language in ["js", "ts"]:
        # Basic JS/TS import/export detection
        import_matches = re.findall(r'(?:import|require)\s*\(?[\'"]([^\'"]+)[\'"]\)?', code)
        export_matches = re.findall(
            r"(?:export|module\.exports)\s+(?:default\s+)?(?:function|class|const|let|var)?\s*(\w+)",
            code,
        )
        imports.update(import_matches)
        exports.update(export_matches)

    return imports, exports


# ---------------------------------------------------------------------------
# Cross-File Dependency Analysis
# ---------------------------------------------------------------------------


def analyze_cross_file_dependencies(
    project_root: Path, current_file: str
) -> List[CrossFileDependency]:
    """Analyze dependencies between files in the project."""
    deps = []
    current_path = Path(current_file)

    # Find all relevant source files
    source_files = []
    for ext in [".py", ".js", ".ts", ".go", ".rs"]:
        source_files.extend(project_root.rglob(f"*{ext}"))

    # Analyze each file for imports
    for file_path in source_files:
        if file_path == current_path:
            continue

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Extract imports based on file type
            imports, _ = extract_imports_exports(content, file_path.suffix.lstrip("."))

            # Check if any imports reference our current file
            current_module = current_path.stem
            for imp in imports:
                if current_module in imp or current_path.name in imp:
                    deps.append(
                        CrossFileDependency(
                            from_file=str(file_path),
                            to_file=str(current_path),
                            import_type="import",
                            symbols={imp},
                            line_number=1,  # Would need proper line tracking
                        )
                    )
        except Exception:
            continue

    return deps


# ---------------------------------------------------------------------------
# Semantic Duplicate Detection
# ---------------------------------------------------------------------------


def find_semantic_duplicates(
    lines: List[str], current_block: SemanticBlock, language: str
) -> List[SemanticBlock]:
    """Find semantically similar blocks in the codebase."""
    duplicates = []

    # Split into logical blocks (functions, classes, etc.)
    blocks = extract_semantic_blocks("\n".join(lines), language)

    for block in blocks:
        # Skip if it's the same block
        if (
            block.start_line == current_block.start_line
            and block.end_line == current_block.end_line
        ):
            continue

        # Check semantic similarity
        similarity = compute_semantic_similarity(current_block, block)
        if similarity >= SEMANTIC_SIMILARITY_THRESHOLD:
            duplicates.append(block)

    return duplicates


def extract_semantic_blocks(code: str, language: str) -> List[SemanticBlock]:
    """Extract logical code blocks for analysis."""
    blocks = []
    lines = code.split("\n")

    if language == "py":
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    start_line = node.lineno - 1
                    end_line = node.end_lineno or start_line + 1
                    block_code = "\n".join(lines[start_line:end_line])

                    block = SemanticBlock(
                        text=block_code,
                        normalized_text=normalize_code_block(block_code, language),
                        start_line=start_line,
                        end_line=end_line,
                        ast_hash=compute_ast_hash(block_code, language),
                        imports=set(),
                        exports={node.name},
                        complexity_score=compute_complexity(block_code),
                    )
                    blocks.append(block)
        except:
            pass

    # Fallback: line-based blocks
    if not blocks:
        # Create blocks every 10 lines as fallback
        for i in range(0, len(lines), 10):
            block_lines = lines[i : i + 10]
            block_code = "\n".join(block_lines)
            blocks.append(
                SemanticBlock(
                    text=block_code,
                    normalized_text=normalize_code_block(block_code, language),
                    start_line=i,
                    end_line=min(i + 10, len(lines)),
                    ast_hash=compute_ast_hash(block_code, language),
                    imports=set(),
                    exports=set(),
                    complexity_score=compute_complexity(block_code),
                )
            )

    return blocks


def compute_semantic_similarity(block1: SemanticBlock, block2: SemanticBlock) -> float:
    """Compute similarity between two semantic blocks."""
    # AST structure similarity
    if block1.ast_hash == block2.ast_hash:
        return 1.0

    # Text similarity
    text_sim = len(set(block1.normalized_text.split()) & set(block2.normalized_text.split())) / max(
        len(set(block1.normalized_text.split())), len(set(block2.normalized_text.split()))
    )

    # Complexity similarity
    complexity_sim = 1.0 - abs(block1.complexity_score - block2.complexity_score) / max(
        block1.complexity_score, block2.complexity_score, 1
    )

    return (text_sim + complexity_sim) / 2


def compute_complexity(code: str) -> float:
    """Compute rough complexity score for code."""
    # Simple heuristic: count control flow statements
    control_flow = len(re.findall(r"\b(if|else|elif|for|while|try|except|finally|with)\b", code))
    return control_flow + len(code.split("\n")) * 0.1


# ---------------------------------------------------------------------------
# Enhanced Review Functions
# ---------------------------------------------------------------------------


def analyze_import_issues(
    new_text: str, language: str, project_root: Path, current_file: str
) -> List[str]:
    """Analyze import issues in the proposed change."""
    issues = []
    imports, _ = extract_imports_exports(new_text, language)

    for imp in imports:
        # Check if import exists in project
        if not check_import_exists(imp, project_root, language):
            issues.append(f"Import '{imp}' not found in project")

        # Check for circular dependencies
        if check_circular_dependency(imp, current_file, project_root):
            issues.append(f"Potential circular dependency with import '{imp}'")

    return issues


def check_import_exists(import_name: str, project_root: Path, language: str) -> bool:
    """Check if an import exists in the project."""
    # Simplified check - would need proper module resolution
    for ext in [".py", ".js", ".ts", ".go", ".rs"]:
        module_path = project_root / f"{import_name.replace('.', '/')}{ext}"
        if module_path.exists():
            return True
    return False


def check_circular_dependency(import_name: str, current_file: str, project_root: Path) -> bool:
    """Check for potential circular dependencies."""
    # Simple check - would need full dependency graph analysis
    try:
        current_module = Path(current_file).stem
        if import_name in current_module or current_module in import_name:
            return True
    except:
        pass
    return False


def build_enhanced_context(
    path: str, lines: List[str], edit_start: int, edit_end: int, old_text: str, new_text: str
) -> ReviewContext:
    """Build enhanced context with semantic analysis."""
    language = Path(path).suffix.lstrip(".") or "text"
    project_root = Path(path).parent

    # Basic context
    context_block = build_context_block(path, lines, edit_start, edit_end, old_text, new_text)

    # Semantic analysis
    current_block = SemanticBlock(
        text=new_text,
        normalized_text=normalize_code_block(new_text, language),
        start_line=edit_start,
        end_line=edit_end,
        ast_hash=compute_ast_hash(new_text, language),
        imports=set(),
        exports=set(),
        complexity_score=compute_complexity(new_text),
    )

    # Find semantic duplicates
    semantic_blocks = extract_semantic_blocks("\n".join(lines), language)
    potential_duplicates = find_semantic_duplicates(lines, current_block, language)

    # Cross-file dependency analysis
    cross_file_deps = analyze_cross_file_dependencies(project_root, path)

    # Import issue analysis
    import_issues = analyze_import_issues(new_text, language, project_root, path)

    # Syntax validation
    syntax_valid = validate_syntax(new_text, language)

    return ReviewContext(
        path=path,
        language=language,
        edit_region=(edit_start, edit_end),
        surrounding_context=context_block,
        semantic_blocks=semantic_blocks,
        cross_file_deps=cross_file_deps,
        potential_duplicates=potential_duplicates,
        import_issues=import_issues,
        syntax_valid=syntax_valid,
    )


def validate_syntax(code: str, language: str) -> bool:
    """Validate syntax for the given language."""
    try:
        if language == "py":
            ast.parse(code)
            return True
        elif language in ["js", "ts"]:
            # Basic validation - could use proper parser
            return "{" in code and "}" in code
        elif language == "go":
            # Could use go fmt or go vet
            return True
        return True
    except:
        return False


def build_enhanced_prompt(context: ReviewContext, old_text: str = "", new_text: str = "") -> str:
    """Build enhanced prompt with semantic analysis results."""
    base_prompt = f"""
You are a pre-commit code reviewer with write access to the filesystem.

FILE: {context.path}
LANGUAGE: {context.language}

PROPOSED CHANGE:
--- REMOVE ---
{textwrap.indent(old_text, "  ")}
--- INSERT ---
{textwrap.indent(new_text, "  ")}
--- END ---

SEMANTIC ANALYSIS RESULTS:
"""

    # Add semantic analysis results
    if context.potential_duplicates:
        base_prompt += f"⚠️  SEMANTIC DUPLICATES FOUND ({len(context.potential_duplicates)}):\n"
        for dup in context.potential_duplicates[:3]:  # Show first 3
            base_prompt += f"  - Lines {dup.start_line}-{dup.end_line}: {dup.text[:100]}...\n"

    if context.import_issues:
        base_prompt += f"⚠️  IMPORT ISSUES FOUND ({len(context.import_issues)}):\n"
        for issue in context.import_issues:
            base_prompt += f"  - {issue}\n"

    if context.cross_file_deps:
        base_prompt += f"ℹ️  CROSS-FILE DEPENDENCIES ({len(context.cross_file_deps)}):\n"
        for dep in context.cross_file_deps[:3]:
            base_prompt += f"  - {dep.from_file} imports {dep.to_file}\n"

    if not context.syntax_valid:
        base_prompt += "❌ SYNTAX VALIDATION FAILED\n"

    base_prompt += """
YOUR TASK:
Inspect the proposed change for these issues (ranked by severity):
  1. Syntax errors in the inserted block
  2. Semantic duplicates — functionally equivalent code already exists
  3. Import problems — missing imports or circular dependencies
  4. Cross-file consistency — changes that break dependencies
  5. Obvious structural errors

RULES:
  - If you find NO issues → reply with exactly: APPROVED
  - If you find issues → fix them yourself using available tools
  - After fixing, reply with: FIXED: [brief description]
  - Do NOT refactor beyond identified issues
  - Your version is final if you write the file
"""

    return base_prompt


# ---------------------------------------------------------------------------
# Integration with existing TermPipe reviewer
# ---------------------------------------------------------------------------


def enhanced_pre_commit_gate(
    path: str,
    lines_before: List[str],
    edit_start: int,
    edit_end: int,
    old_text: str,
    new_text: str,
    timeout: float = 8.0,
) -> Any:  # Returns ReviewResult
    """
    Enhanced pre-commit review with semantic analysis.

    This function integrates with the existing TermPipe reviewer system
    by providing enhanced context and analysis capabilities.
    """
    # Import the existing ReviewResult to maintain compatibility
    from .reviewer import ReviewResult, _is_reviewing, _get_reviewer, _set_reviewing

    # Single-pass guard
    if _is_reviewing():
        return ReviewResult(approved=True, reviewer_wrote=False, note="")

    reviewer = _get_reviewer()
    if reviewer is None:
        return ReviewResult(approved=True, reviewer_wrote=False, note="[no reviewer configured]")

    # Build enhanced context
    context = build_enhanced_context(path, lines_before, edit_start, edit_end, old_text, new_text)

    # Build enhanced prompt
    prompt = build_enhanced_prompt(context, old_text=old_text, new_text=new_text)

    # Run review with enhanced context
    _set_reviewing(True)
    try:
        response = reviewer(prompt, timeout)
    except Exception as e:
        return ReviewResult(approved=True, reviewer_wrote=False, note=f"[reviewer error: {e}]")
    finally:
        _set_reviewing(False)

    response = response.strip()

    if response.upper() == "APPROVED":
        return ReviewResult(approved=True, reviewer_wrote=False, note="")

    if response.upper().startswith("FIXED:") or response.upper().startswith("FIXED "):
        # Ghost-write verification — same fix as reviewer.py
        try:
            current = Path(path).read_text()
            original = "".join(lines_before)
            if current.strip() == original.strip():
                return ReviewResult(
                    approved=True,
                    reviewer_wrote=False,
                    note="[enhanced reviewer ghost-write detected — file unchanged after FIXED claim, proceeding with original write]",
                )
        except Exception:
            pass
        return ReviewResult(approved=False, reviewer_wrote=True, note=response)

    return ReviewResult(
        approved=True, reviewer_wrote=False, note=f"[unexpected response: {response[:100]}]"
    )


# Keep the original functions for backward compatibility
from .reviewer import pre_commit_gate, ReviewResult, build_context_block, _enclosing_scope_bounds
