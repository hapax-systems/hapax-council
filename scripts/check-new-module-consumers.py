#!/usr/bin/env python3
"""CI check enforcing at least one non-test consumer per newly added module."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import subprocess
import sys
from pathlib import Path

SOURCE_PATHS = ("agents", "logos", "shared", "scripts")
DEFAULT_ALLOWLIST_PATH = Path("config/new-module-allowlist.json")


def is_module_file(path: Path) -> bool:
    """Check if the given path matches the project's module glob patterns."""
    if path.suffix != ".py":
        return False
    parts = path.parts
    if not parts:
        return False
    if "tests" in parts:
        return False
    if path.name.startswith("test_"):
        return False
    return parts[0] in SOURCE_PATHS


def get_module_name(path: Path) -> str:
    """Get the fully-qualified Python module name for a file path."""
    return ".".join(path.with_suffix("").parts)


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a shell command and return the process result."""
    return subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def git_diff_added_files(args: argparse.Namespace) -> list[Path]:
    """Get the list of newly added files from git diff."""
    command = ["git", "diff", "--name-only", "--diff-filter=A"]
    if args.staged:
        command.append("--cached")
    elif args.diff_range:
        command.extend(args.diff_range.split())
    elif args.base_ref:
        command.append(f"{args.base_ref}...HEAD")
    else:
        # Default fallback: compare against HEAD~1
        command.append("HEAD~1")

    result = run_command(command)
    if result.returncode != 0:
        # If HEAD~1 fails, fallback to HEAD or empty
        command = ["git", "diff", "--name-only", "--diff-filter=A", "HEAD"]
        result = run_command(command)
        if result.returncode != 0:
            print(f"Git diff failed: {result.stdout}", file=sys.stderr)
            return []

    added_paths = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line:
            added_paths.append(Path(line))
    return added_paths


def get_all_project_modules() -> list[Path]:
    """Get all non-test python source files in the project."""
    modules = []
    for source_dir in SOURCE_PATHS:
        path = Path(source_dir)
        if not path.exists():
            continue
        for py_file in path.glob("**/*.py"):
            if is_module_file(py_file):
                modules.append(py_file)
    return modules


def load_allowlist(allowlist_path: Path) -> set[str]:
    """Load the entrypoint allowlist from a JSON file."""
    if not allowlist_path.exists():
        return set()
    try:
        with open(allowlist_path, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return set(data)
    except Exception as e:
        print(f"Warning: Failed to parse allowlist {allowlist_path}: {e}", file=sys.stderr)
    return set()


def is_allowlisted(path: Path, module_name: str, allowlist: set[str]) -> bool:
    """Check if a module or its path is matched by the allowlist."""
    path_str = str(path)
    for pattern in allowlist:
        if (
            fnmatch.fnmatch(module_name, pattern)
            or fnmatch.fnmatch(path_str, pattern)
            or fnmatch.fnmatch(path.name, pattern)
        ):
            return True
    return False


def get_imported_modules(file_path: Path, module_name: str) -> set[str]:
    """Parse a python file using AST and find all imported modules."""
    imports = set()
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
    except Exception:
        return imports

    package_parts = module_name.split(".")[:-1]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                if node.level - 1 > len(package_parts):
                    continue
                base_parts = (
                    package_parts if node.level == 1 else package_parts[: -(node.level - 1)]
                )
                if node.module:
                    base_parts = base_parts + node.module.split(".")
                import_base = ".".join(base_parts)
            else:
                import_base = node.module or ""

            if import_base:
                imports.add(import_base)
                for alias in node.names:
                    imports.add(f"{import_base}.{alias.name}")
            else:
                for alias in node.names:
                    imports.add(alias.name)
    return imports


def count_consumers(
    target_module_name: str, all_source_files: list[Path], target_file_path: Path
) -> int:
    """Count how many other source files import the target module."""
    count = 0
    for file_path in all_source_files:
        if file_path == target_file_path:
            continue
        file_module_name = get_module_name(file_path)
        imported = get_imported_modules(file_path, file_module_name)
        for imp in imported:
            if imp == target_module_name or imp.startswith(target_module_name + "."):
                count += 1
                break
    return count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--staged",
        action="store_true",
        help="check only modules newly added to the staged diff",
    )
    scope.add_argument(
        "--base-ref",
        help="check only modules newly added since merge-base with this ref or SHA",
    )
    scope.add_argument(
        "--diff-range",
        help="check only modules newly added in an explicit git diff range",
    )
    scope.add_argument(
        "--all",
        action="store_true",
        help="check all modules in the codebase for consumers",
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=DEFAULT_ALLOWLIST_PATH,
        help="JSON file containing the library entrypoint allowlist",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # 1. Gather files to check
    if args.all:
        modules_to_check = get_all_project_modules()
    else:
        added_files = git_diff_added_files(args)
        modules_to_check = [f for f in added_files if is_module_file(f)]

    if not modules_to_check:
        print("No new module files to check.")
        return 0

    # 2. Load allowlist
    allowlist = load_allowlist(args.allowlist)

    # 3. Gather all potential consumer files in the project
    all_source_files = get_all_project_modules()

    # 4. Perform check
    failed_modules = []
    for module_path in modules_to_check:
        module_name = get_module_name(module_path)

        # Check if allowlisted
        if is_allowlisted(module_path, module_name, allowlist):
            print(
                f"Module {module_name} is allowlisted as an entry point. Skipping consumer check."
            )
            continue

        consumer_count = count_consumers(module_name, all_source_files, module_path)
        print(f"Checking module: {module_path} ({module_name}) -> Consumers: {consumer_count}")

        if consumer_count == 0:
            failed_modules.append((module_path, module_name))

    if failed_modules:
        print("\n[ERROR] The following newly added module files have zero non-test consumers:")
        for path, name in failed_modules:
            print(f"  - {path} (module: {name})")
        print("\nTo satisfy this check:")
        print("1. Add a real consumer import in a non-test source file.")
        print(f"2. Or add the module name or path to the allowlist in {args.allowlist}")
        return 1

    print("\nAll new module consumer checks passed successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
