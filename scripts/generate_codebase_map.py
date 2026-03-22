#!/usr/bin/env python3
"""Generate a static codebase map for offline context in CI.

Walks Python source directories and extracts module docstrings, class names,
and function signatures using the ``ast`` module. Output is a JSON file
consumable by the planning and review agents when Qdrant is unavailable.

Usage::

    uv run python scripts/generate_codebase_map.py
    uv run python scripts/generate_codebase_map.py --output codebase-map.json
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRS = ["agents", "shared", "logos", "scripts"]
DEFAULT_OUTPUT = PROJECT_ROOT / "codebase-map.json"


def _extract_file_info(filepath: Path) -> dict | None:
    """Extract metadata from a single Python file."""
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError):
        return None

    rel_path = str(filepath.relative_to(PROJECT_ROOT))

    docstring = ast.get_docstring(tree) or ""
    classes = []
    functions = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            args = []
            for arg in node.args.args:
                ann = ""
                if arg.annotation:
                    ann = f": {ast.unparse(arg.annotation)}"
                args.append(f"{arg.arg}{ann}")
            ret = ""
            if node.returns:
                ret = f" -> {ast.unparse(node.returns)}"
            functions.append(f"{node.name}({', '.join(args)}){ret}")

    return {
        "path": rel_path,
        "docstring": docstring[:200],
        "classes": classes,
        "functions": functions,
    }


def generate_map(output_path: Path = DEFAULT_OUTPUT) -> dict:
    """Generate codebase map and write to JSON."""
    files = []
    for src_dir in SOURCE_DIRS:
        dir_path = PROJECT_ROOT / src_dir
        if not dir_path.is_dir():
            continue
        for py_file in sorted(dir_path.rglob("*.py")):
            if py_file.name.startswith("__"):
                continue
            info = _extract_file_info(py_file)
            if info:
                files.append(info)

    result = {"generated_at": str(Path), "file_count": len(files), "files": files}
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate codebase map")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    result = generate_map(args.output)
    print(f"Generated codebase map: {len(result['files'])} files -> {args.output}")


if __name__ == "__main__":
    main()
