#!/usr/bin/env python3
"""LLM vendor tool — makes agent packages self-contained.

Given an agent module name, resolves all ``shared.*`` and ``agents.*`` imports,
extracts only the symbols the agent actually uses (via AST analysis), copies
them into the agent's package directory as local modules, and rewrites the
agent's imports from ``from shared.X import Y`` to ``from .X import Y``.

Usage::

    uv run python scripts/llm_vendor.py agents.drift_detector
    uv run python scripts/llm_vendor.py agents.drift_detector --apply
    uv run python scripts/llm_vendor.py --all-agents --apply
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def extract_used_symbols(
    source: str,
    module: str,
    imported_names: list[str],
) -> set[str]:
    """Return the subset of *imported_names* that are actually referenced in *source*.

    Parses the AST and collects all ``Name`` and ``Attribute`` references,
    then intersects with the provided names.  The *module* argument is
    accepted for interface consistency but is not used in the current
    implementation.
    """
    tree = ast.parse(source)
    referenced: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            referenced.add(node.id)
        elif isinstance(node, ast.Attribute):
            referenced.add(node.attr)

    return set(imported_names) & referenced


def rewrite_imports(source: str, module_map: dict[str, str]) -> str:
    """Rewrite ``from shared.X import …`` statements to relative imports.

    *module_map* maps original dotted module names to local names, e.g.
    ``{"shared.config": "config"}``.  Each matching ``from`` import line is
    replaced with ``from .{local_name} import …``.

    Non-matching lines are passed through unchanged.
    """
    lines = source.splitlines(keepends=True)
    result: list[str] = []

    for line in lines:
        replaced = False
        for original, local in module_map.items():
            prefix = f"from {original} import "
            if line.lstrip().startswith(prefix):
                # Preserve leading whitespace
                indent = line[: len(line) - len(line.lstrip())]
                tail = line.lstrip()[len(prefix) :]
                result.append(f"{indent}from .{local} import {tail}")
                replaced = True
                break
        if not replaced:
            result.append(line)

    return "".join(result)


# ---------------------------------------------------------------------------
# Import collection / resolution
# ---------------------------------------------------------------------------


def _collect_shared_imports(filepath: Path) -> dict[str, list[str]]:
    """Collect ``{shared_module: [imported_names]}`` from a Python file."""
    source = filepath.read_text()
    tree = ast.parse(source)
    result: dict[str, list[str]] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("shared.") or node.module.startswith("agents."):
                names = [alias.name for alias in node.names] if node.names else []
                result.setdefault(node.module, []).extend(names)

    return result


def _resolve_shared_file(module: str) -> Path | None:
    """Find the ``.py`` file for a dotted module path relative to PROJECT_ROOT."""
    parts = module.split(".")
    # Try as a direct module file first: shared/config.py
    candidate = PROJECT_ROOT / ("/".join(parts) + ".py")
    if candidate.exists():
        return candidate
    # Try as a package: shared/config/__init__.py
    candidate = PROJECT_ROOT / "/".join(parts) / "__init__.py"
    if candidate.exists():
        return candidate
    return None


def _extract_symbols_from_file(filepath: Path, names: list[str]) -> str:
    """Extract only the requested top-level definitions from a Python file.

    Uses AST to find functions, classes, and assignments matching *names*.
    Falls back to copying the whole file if specific extraction fails.
    """
    source = filepath.read_text()
    tree = ast.parse(source)

    # Collect line ranges for requested symbols
    segments: list[tuple[int, int]] = []  # (start_line, end_line) — 1-indexed
    source_lines = source.splitlines(keepends=True)

    for node in ast.iter_child_nodes(tree):
        name: str | None = None

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in names:
                    name = target.id
                    break
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in names:
                name = node.target.id

        if name and name in names:
            start = node.lineno  # 1-indexed
            end = node.end_lineno or node.lineno
            segments.append((start, end))

    if not segments:
        # Fallback: copy the whole file
        return _strip_shared_imports(source)

    # Sort and collect lines, including any decorator lines above
    segments.sort()
    collected_lines: list[str] = []

    # Collect module-level imports that aren't shared (needed for vendored code)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("shared.") or node.module.startswith("agents."):
                    continue
            start = node.lineno
            end = node.end_lineno or node.lineno
            for i in range(start - 1, end):
                if i < len(source_lines):
                    collected_lines.append(source_lines[i])

    if collected_lines:
        collected_lines.append("\n")

    for start, end in segments:
        # Look for decorators above
        actual_start = start
        for i in range(start - 2, -1, -1):
            stripped = source_lines[i].strip()
            if stripped.startswith("@"):
                actual_start = i + 1  # convert to 1-indexed
            else:
                break

        for i in range(actual_start - 1, end):
            if i < len(source_lines):
                collected_lines.append(source_lines[i])
        collected_lines.append("\n")

    header = '"""Vendored from {filepath.name}."""\nfrom __future__ import annotations\n\n'
    return header.format(filepath=filepath) + "".join(collected_lines)


def _strip_shared_imports(source: str) -> str:
    """Remove ``from shared.*`` and ``import shared.*`` lines from source."""
    lines = source.splitlines(keepends=True)
    result: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("from shared.") or stripped.startswith("import shared."):
            continue
        if stripped.startswith("from agents.") or stripped.startswith("import agents."):
            continue
        result.append(line)
    return "".join(result)


# ---------------------------------------------------------------------------
# Main vendor logic
# ---------------------------------------------------------------------------


def vendor_agent(module_name: str, dry_run: bool = True) -> dict[str, str]:
    """Vendor all shared dependencies for an agent into its package directory.

    Returns ``{relative_path: content}`` for files to create/modify.
    If *dry_run* is False, writes the files to disk.
    """
    parts = module_name.split(".")
    if parts[0] != "agents" or len(parts) < 2:
        raise ValueError(f"Expected agents.<name>, got {module_name}")

    agent_name = parts[1]
    agent_dir = PROJECT_ROOT / "agents" / agent_name

    result: dict[str, str] = {}

    # Determine if it's a single-file agent that needs conversion to package
    single_file = PROJECT_ROOT / "agents" / f"{agent_name}.py"
    is_single_file = single_file.exists() and not agent_dir.exists()

    if is_single_file:
        # Plan conversion: single file → package
        agent_source = single_file.read_text()
        agent_py_path = f"agents/{agent_name}/agent.py"
        init_path = f"agents/{agent_name}/__init__.py"
        result[init_path] = f'"""Agent package for {agent_name}."""\n'
    elif agent_dir.exists():
        # Already a package — find the main agent file(s)
        agent_source = ""
        agent_py_path = None
        # Look for all .py files in the package
        py_files = sorted(agent_dir.glob("*.py"))
        if not py_files:
            raise FileNotFoundError(f"No Python files found in {agent_dir}")
    else:
        raise FileNotFoundError(f"Agent not found: {single_file} or {agent_dir}")

    # Collect imports from all source files
    all_imports: dict[str, list[str]] = {}

    if is_single_file:
        all_imports = _collect_shared_imports(single_file)
        source_files = {agent_py_path: agent_source}
    else:
        source_files = {}
        for py_file in sorted(agent_dir.glob("*.py")):
            rel_path = str(py_file.relative_to(PROJECT_ROOT))
            source_content = py_file.read_text()
            source_files[rel_path] = source_content
            file_imports = _collect_shared_imports(py_file)
            for mod, names in file_imports.items():
                all_imports.setdefault(mod, []).extend(names)

    # For each shared import, resolve and extract needed symbols
    module_map: dict[str, str] = {}
    for shared_mod, imported_names in all_imports.items():
        # Determine local filename
        local_name = shared_mod.split(".")[-1]
        module_map[shared_mod] = local_name

        shared_file = _resolve_shared_file(shared_mod)
        if shared_file is None:
            result[f"agents/{agent_name}/{local_name}.py"] = (
                f"# WARNING: Could not resolve {shared_mod}\n# Manual vendoring required.\n"
            )
            continue

        # Determine which symbols are actually used across all source files
        all_used: set[str] = set()
        for _rel, src in source_files.items():
            used = extract_used_symbols(src, shared_mod, imported_names)
            all_used |= used

        # If nothing is used (e.g., side-effect import), include everything
        if not all_used:
            all_used = set(imported_names)

        vendored_content = _extract_symbols_from_file(shared_file, list(all_used))
        result[f"agents/{agent_name}/{local_name}.py"] = vendored_content

    # Rewrite imports in agent source files
    for rel_path, source_content in source_files.items():
        rewritten = rewrite_imports(source_content, module_map)
        result[rel_path] = rewritten

    # Write files if not dry run
    if not dry_run:
        for rel_path, content in result.items():
            full_path = PROJECT_ROOT / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Vendor shared dependencies into agent packages.",
    )
    parser.add_argument(
        "module",
        nargs="?",
        help="Agent module name (e.g., agents.drift_detector)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write files (default: dry run)",
    )
    parser.add_argument(
        "--all-agents",
        action="store_true",
        help="Vendor all single-file agents",
    )
    args = parser.parse_args()

    if args.all_agents:
        agents_dir = PROJECT_ROOT / "agents"
        modules = []
        for f in sorted(agents_dir.glob("*.py")):
            if f.name.startswith("_"):
                continue
            modules.append(f"agents.{f.stem}")
        # Also include package agents
        for d in sorted(agents_dir.iterdir()):
            if d.is_dir() and not d.name.startswith("_") and (d / "__init__.py").exists():
                modules.append(f"agents.{d.name}")
    elif args.module:
        modules = [args.module]
    else:
        parser.error("Provide a module name or --all-agents")
        return

    dry_run = not args.apply

    for module_name in modules:
        print(f"\n{'=' * 60}")
        print(f"{'[DRY RUN] ' if dry_run else ''}Vendoring: {module_name}")
        print(f"{'=' * 60}")

        try:
            files = vendor_agent(module_name, dry_run=dry_run)
        except (FileNotFoundError, ValueError) as exc:
            print(f"  SKIP: {exc}")
            continue

        for rel_path, content in sorted(files.items()):
            lines = content.count("\n")
            print(f"  {'would create' if dry_run else 'wrote'}: {rel_path} ({lines} lines)")

    if dry_run:
        print("\nDry run complete. Use --apply to write files.")


if __name__ == "__main__":
    main()
