#!/usr/bin/env python3
"""LLM import graph analyzer.

Builds a transitive import graph for Python source files and calculates token
costs. Used to measure LLM context overhead and guide codebase restructuring.

Usage::

    uv run python scripts/llm_import_graph.py
    uv run python scripts/llm_import_graph.py --module agents.drift_detector
    uv run python scripts/llm_import_graph.py --json
    uv run python scripts/llm_import_graph.py --baseline
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOKENS_PER_LINE_PY = 10
INTERNAL_PREFIXES = ("shared.", "agents.", "logos.")
DEFAULT_SOURCE_DIRS = ["agents", "shared", "logos", "scripts"]
DEFAULT_BASELINE_OUTPUT = PROJECT_ROOT / "profiles" / "token-baseline.json"


@dataclass
class ImportInfo:
    """A single import statement extracted from a Python file."""

    module: str
    names: list[str]  # empty list for bare `import module`
    line: int
    is_internal: bool


@dataclass
class ModuleInfo:
    """Metadata for a single Python module including its import graph."""

    path: str
    loc: int
    token_cost: int
    imports: list[ImportInfo] = field(default_factory=list)
    transitive_deps: list[str] = field(default_factory=list)
    transitive_token_cost: int = 0


def extract_imports(source: str, filepath: str) -> list[ImportInfo]:
    """Extract all import statements from Python source.

    Args:
        source: Python source code string.
        filepath: Relative path to the file (used for context only).

    Returns:
        List of ImportInfo objects for all imports found.
    """
    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError:
        return []

    result: list[ImportInfo] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
            names = [alias.name for alias in node.names] if node.names else []
            is_internal = module.startswith(INTERNAL_PREFIXES)
            result.append(
                ImportInfo(
                    module=module,
                    names=names,
                    line=node.lineno,
                    is_internal=is_internal,
                )
            )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                is_internal = module.startswith(INTERNAL_PREFIXES)
                result.append(
                    ImportInfo(
                        module=module,
                        names=[],
                        line=node.lineno,
                        is_internal=is_internal,
                    )
                )

    # Sort by line number to match source order
    result.sort(key=lambda i: i.line)
    return result


def module_to_path(module_name: str) -> Path | None:
    """Convert a dotted module name to a file path relative to project root.

    Tries both package directory (__init__.py) and module file.

    Args:
        module_name: Dotted module name like "agents.drift_detector".

    Returns:
        Absolute path if found, None otherwise.
    """
    parts = module_name.split(".")
    # Try as a module file first
    as_file = PROJECT_ROOT / Path(*parts).with_suffix(".py")
    if as_file.exists():
        return as_file
    # Try as a package
    as_package = PROJECT_ROOT / Path(*parts) / "__init__.py"
    if as_package.exists():
        return as_package
    return None


def count_lines(filepath: Path) -> int:
    """Count non-empty, non-comment lines in a Python file.

    Args:
        filepath: Absolute path to a Python file.

    Returns:
        Count of substantive lines.
    """
    try:
        source = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0

    count = 0
    for line in source.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            count += 1
    return count


def _file_to_module_name(filepath: Path) -> str:
    """Convert an absolute file path to a dotted module name."""
    rel = filepath.relative_to(PROJECT_ROOT)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    elif parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    return ".".join(parts)


def build_graph(source_dirs: list[str] | None = None) -> dict[str, ModuleInfo]:
    """Build a full import graph with transitive resolution.

    Args:
        source_dirs: List of source directory names relative to project root.
                     Defaults to DEFAULT_SOURCE_DIRS.

    Returns:
        Dict mapping module name → ModuleInfo.
    """
    if source_dirs is None:
        source_dirs = DEFAULT_SOURCE_DIRS

    modules: dict[str, ModuleInfo] = {}

    # Walk all source dirs and parse each .py file
    for dir_name in source_dirs:
        src_dir = PROJECT_ROOT / dir_name
        if not src_dir.exists():
            continue
        for py_file in sorted(src_dir.rglob("*.py")):
            try:
                source = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            module_name = _file_to_module_name(py_file)
            imports = extract_imports(source, str(py_file.relative_to(PROJECT_ROOT)))
            loc = count_lines(py_file)
            token_cost = loc * TOKENS_PER_LINE_PY

            modules[module_name] = ModuleInfo(
                path=str(py_file.relative_to(PROJECT_ROOT)),
                loc=loc,
                token_cost=token_cost,
                imports=imports,
                transitive_deps=[],
                transitive_token_cost=0,
            )

    # Resolve transitive dependencies
    for module_name in modules:
        deps = _resolve_transitive(module_name, modules, set())
        deps.discard(module_name)  # A module is not its own dependency
        modules[module_name].transitive_deps = sorted(deps)
        transitive_cost = modules[module_name].token_cost + sum(
            modules[dep].token_cost for dep in deps if dep in modules
        )
        modules[module_name].transitive_token_cost = transitive_cost

    return modules


def _resolve_transitive(
    module_name: str,
    modules: dict[str, ModuleInfo],
    visited: set[str],
) -> set[str]:
    """Recursively resolve all transitive internal dependencies.

    Args:
        module_name: Starting module.
        modules: Full module registry built so far.
        visited: Set of already-visited modules (cycle guard).

    Returns:
        Set of all transitive dependency module names (excluding self).
    """
    if module_name in visited:
        return set()
    visited = visited | {module_name}

    module = modules.get(module_name)
    if module is None:
        return set()

    direct_internal = {
        imp.module for imp in module.imports if imp.is_internal and imp.module in modules
    }

    all_deps: set[str] = set()
    for dep in direct_internal:
        all_deps.add(dep)
        all_deps |= _resolve_transitive(dep, modules, visited)

    return all_deps


def format_report(
    modules: dict[str, ModuleInfo],
    module_filter: str | None = None,
) -> str:
    """Format a human-readable report of modules and their token costs.

    Args:
        modules: Module graph from build_graph().
        module_filter: If set, filter to modules whose name starts with this prefix.

    Returns:
        Formatted report string.
    """
    if module_filter:
        filtered = {k: v for k, v in modules.items() if k.startswith(module_filter)}
    else:
        # Default: agents only
        filtered = {k: v for k, v in modules.items() if k.startswith("agents.")}

    if not filtered:
        return f"No modules found matching filter: {module_filter!r}\n"

    lines = ["LLM Import Graph — Token Cost Report", "=" * 60, ""]

    # Sort by transitive token cost descending
    sorted_mods = sorted(filtered.items(), key=lambda kv: kv[1].transitive_token_cost, reverse=True)

    for name, info in sorted_mods:
        lines.append(f"{name}")
        lines.append(f"  path:               {info.path}")
        lines.append(f"  loc:                {info.loc}")
        lines.append(f"  self token cost:    {info.token_cost}")
        lines.append(f"  transitive cost:    {info.transitive_token_cost}")
        lines.append(f"  transitive deps:    {len(info.transitive_deps)}")
        if info.transitive_deps:
            top_deps = info.transitive_deps[:5]
            lines.append(f"  top deps:           {', '.join(top_deps)}")
        lines.append("")

    total_self = sum(v.token_cost for v in filtered.values())
    total_trans = sum(v.transitive_token_cost for v in filtered.values())
    lines.append("-" * 60)
    lines.append(f"Modules shown:        {len(filtered)}")
    lines.append(f"Total self cost:      {total_self}")
    lines.append(f"Total transitive:     {total_trans}")

    return "\n".join(lines) + "\n"


def _modules_to_dict(modules: dict[str, ModuleInfo]) -> dict[str, dict]:
    """Convert module graph to JSON-serializable dict."""
    return {
        name: {
            "path": info.path,
            "loc": info.loc,
            "token_cost": info.token_cost,
            "transitive_deps": info.transitive_deps,
            "transitive_token_cost": info.transitive_token_cost,
        }
        for name, info in sorted(modules.items())
    }


def save_baseline(modules: dict[str, ModuleInfo], output: Path) -> None:
    """Save a JSON baseline of module token costs.

    Args:
        modules: Module graph from build_graph().
        output: Output file path.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    data = _modules_to_dict(modules)
    output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Baseline saved to {output} ({len(data)} modules)")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Analyze LLM token costs for Python imports.")
    parser.add_argument(
        "--module",
        metavar="MODULE",
        help="Show report for a single module (e.g. agents.drift_detector)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output full graph as JSON to stdout",
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help=f"Save JSON baseline to {DEFAULT_BASELINE_OUTPUT}",
    )
    args = parser.parse_args()

    print("Building import graph...", flush=True)
    modules = build_graph()
    print(f"  {len(modules)} modules indexed", flush=True)

    if args.baseline:
        save_baseline(modules, DEFAULT_BASELINE_OUTPUT)
        return

    if args.json:
        print(json.dumps(_modules_to_dict(modules), indent=2))
        return

    module_filter = args.module
    print(format_report(modules, module_filter))


if __name__ == "__main__":
    main()
