"""Source code annotation insertion for inline suppression.

Inserts ai-guardian:allow (inline) or ai-guardian:begin-allow/end-allow (block)
annotations into source files. Uses Python AST for multi-line string detection.
"""

import ast
import logging
import os
from pathlib import Path
from typing import Dict, Optional, Tuple

from ai_guardian.annotations import INLINE_MARKER, BLOCK_BEGIN_MARKER, BLOCK_END_MARKER

logger = logging.getLogger(__name__)

COMMENT_PREFIXES: Dict[str, str] = {
    ".py": "#",
    ".pyw": "#",
    ".pyi": "#",
    ".rb": "#",
    ".rake": "#",
    ".sh": "#",
    ".bash": "#",
    ".zsh": "#",
    ".yml": "#",
    ".yaml": "#",
    ".toml": "#",
    ".cfg": "#",
    ".ini": "#",
    ".conf": "#",
    ".txt": "#",
    ".md": "#",
    ".rst": "#",
    ".env": "#",
    ".properties": "#",
    ".gitignore": "#",
    ".dockerignore": "#",
    ".editorconfig": "#",
    ".r": "#",
    ".R": "#",
    ".pl": "#",
    ".pm": "#",
    ".ps1": "#",
    ".psm1": "#",
    ".tf": "#",
    ".tfvars": "#",
    ".js": "//",
    ".mjs": "//",
    ".cjs": "//",
    ".ts": "//",
    ".tsx": "//",
    ".jsx": "//",
    ".go": "//",
    ".rs": "//",
    ".java": "//",
    ".kt": "//",
    ".kts": "//",
    ".scala": "//",
    ".groovy": "//",
    ".c": "//",
    ".cpp": "//",
    ".cc": "//",
    ".cxx": "//",
    ".h": "//",
    ".hpp": "//",
    ".cs": "//",
    ".swift": "//",
    ".dart": "//",
    ".v": "//",
    ".proto": "//",
    ".zig": "//",
    ".sql": "--",
    ".lua": "--",
    ".hs": "--",
    ".elm": "--",
    ".erl": "%",
    ".ex": "#",
    ".exs": "#",
    ".clj": ";;",
    ".cljs": ";;",
    ".cljc": ";;",
    ".lisp": ";;",
    ".el": ";;",
    ".vim": '"',
    ".bat": "REM",
    ".cmd": "REM",
}


def get_comment_prefix(file_path: str) -> Optional[str]:
    """Return the comment prefix for a file based on extension. None if unsupported."""
    ext = Path(file_path).suffix.lower()
    return COMMENT_PREFIXES.get(ext)


def find_enclosing_multiline_string(
    file_path: str, line_number: int
) -> Optional[Tuple[int, int]]:
    """Find if line_number is inside a multi-line string (Python only).

    Uses AST to detect triple-quoted strings, docstrings, f-strings.

    Args:
        file_path: Path to Python file.
        line_number: 1-based line number to check.

    Returns:
        (start_line, end_line) 1-based if inside multi-line string, None otherwise.
    """
    if not file_path.endswith((".py", ".pyw", ".pyi")):
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if (
                hasattr(node, "end_lineno")
                and node.end_lineno is not None
                and node.end_lineno > node.lineno
            ):
                if node.lineno <= line_number <= node.end_lineno:
                    return (node.lineno, node.end_lineno)
        elif isinstance(node, ast.JoinedStr):
            if (
                hasattr(node, "end_lineno")
                and node.end_lineno is not None
                and node.end_lineno > node.lineno
            ):
                if node.lineno <= line_number <= node.end_lineno:
                    return (node.lineno, node.end_lineno)

    return None


def _get_indentation(line: str) -> str:
    """Extract leading whitespace from a line."""
    return line[: len(line) - len(line.lstrip())]


def prepare_annotation(
    file_path: str, line_number: int
) -> Optional[Tuple[str, int, str]]:
    """Prepare source content with annotation inserted.

    Decides inline vs block based on AST analysis (Python only).

    Args:
        file_path: Absolute path to source file.
        line_number: 1-based line number of violation.

    Returns:
        (modified_content, highlight_start_line, annotation_type) or None if unsupported.
        annotation_type is "inline" or "block".
        highlight_start_line is 1-based.
    """
    prefix = get_comment_prefix(file_path)
    if prefix is None:
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return None

    lines = content.splitlines(keepends=True)
    if line_number < 1 or line_number > len(lines):
        return None

    multiline = find_enclosing_multiline_string(file_path, line_number)

    if multiline is not None:
        start_line, end_line = multiline
        indent = _get_indentation(lines[start_line - 1])
        begin_comment = f"{indent}{prefix} {BLOCK_BEGIN_MARKER}\n"
        end_comment = f"{indent}{prefix} {BLOCK_END_MARKER}\n"

        new_lines = list(lines)
        new_lines.insert(start_line - 1, begin_comment)
        new_lines.insert(end_line + 1, end_comment)

        modified = "".join(new_lines)
        return (modified, start_line, "block")
    else:
        idx = line_number - 1
        line = lines[idx]
        stripped = line.rstrip("\n\r")
        marker = f"  {prefix} {INLINE_MARKER}"
        lines[idx] = stripped + marker + "\n"

        modified = "".join(lines)
        return (modified, line_number, "inline")


def generate_source_preview(
    file_path: str, line_number: int, context_lines: int = 5
) -> Optional[Tuple[str, str, int, int, str]]:
    """Generate before/after preview snippets for the source editor.

    Args:
        file_path: Absolute path to source file.
        line_number: 1-based line number of violation.
        context_lines: Number of lines of context around the change.

    Returns:
        (original_snippet, annotated_snippet, preview_start_line, highlight_line, annotation_type)
        or None if unsupported. Lines are 1-based.
    """
    result = prepare_annotation(file_path, line_number)
    if result is None:
        return None

    modified_content, highlight_line, annotation_type = result

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            original_content = f.read()
    except (OSError, UnicodeDecodeError):
        return None

    orig_lines = original_content.splitlines()
    mod_lines = modified_content.splitlines()

    if annotation_type == "block":
        start = max(0, highlight_line - 1 - context_lines)
        end = min(len(mod_lines), highlight_line + context_lines + 2)
    else:
        start = max(0, highlight_line - 1 - context_lines)
        end = min(len(mod_lines), highlight_line + context_lines)

    orig_start = max(0, line_number - 1 - context_lines)
    orig_end = min(len(orig_lines), line_number + context_lines)

    orig_snippet_lines = []
    for i in range(orig_start, orig_end):
        orig_snippet_lines.append(f"{i + 1:4d} | {orig_lines[i]}")

    mod_snippet_lines = []
    for i in range(start, end):
        mod_snippet_lines.append(f"{i + 1:4d} | {mod_lines[i]}")

    return (
        "\n".join(orig_snippet_lines),
        "\n".join(mod_snippet_lines),
        start + 1,
        highlight_line,
        annotation_type,
    )


def write_annotated_source(file_path: str, content: str) -> bool:
    """Write modified source content to file atomically.

    Uses temp file + rename for atomicity.
    """
    try:
        dir_path = os.path.dirname(file_path)
        import tempfile

        fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, file_path)
            return True
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass  # intentionally silent — best-effort operation
            raise
    except Exception as e:
        logger.warning("Failed to write annotated source: %s", e)
        return False
