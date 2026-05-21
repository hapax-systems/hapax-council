#!/usr/bin/env python3
"""CI gate: detect Python modules with zero importers outside tests/.

Scans all .py files under shared/, agents/, logos/, scripts/ and checks
whether each module is imported by at least one file outside tests/.
Modules with zero non-test importers are flagged as orphans.

Exit 0 if no orphans found, exit 1 with a list of orphans otherwise.

Usage:
    uv run python scripts/ci_orphan_module_check.py
"""

from __future__ import annotations

import ast
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SOURCE_DIRS = ["shared", "agents", "logos"]

EXCLUDE_PATTERNS = [
    "__pycache__",
    ".venv",
    "node_modules",
    "_retired",
    "packages/",
]

EXEMPT_MODULES: set[str] = {
    "__init__",
    "__main__",
    "conftest",
}

EXEMPT_PATHS: set[str] = set()


def _is_excluded(path: Path) -> bool:
    s = str(path)
    return any(p in s for p in EXCLUDE_PATTERNS)


def _module_name(path: Path) -> str:
    rel = path.relative_to(REPO_ROOT)
    parts = list(rel.with_suffix("").parts)
    return ".".join(parts)


def _collect_source_modules() -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for src_dir in SOURCE_DIRS:
        root = REPO_ROOT / src_dir
        if not root.is_dir():
            continue
        for py_file in root.rglob("*.py"):
            if _is_excluded(py_file):
                continue
            if py_file.stem in EXEMPT_MODULES:
                continue
            mod = _module_name(py_file)
            modules[mod] = py_file
    return modules


def _extract_imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_bytes(), filename=str(path))
    except SyntaxError:
        return set()

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    return imports


def _collect_all_imports(exclude_tests: bool = True) -> set[str]:
    all_imports: set[str] = set()
    for py_file in REPO_ROOT.rglob("*.py"):
        if _is_excluded(py_file):
            continue
        if exclude_tests and "tests" in py_file.parts:
            continue
        all_imports.update(_extract_imports(py_file))
    return all_imports


def _is_imported(module_name: str, all_imports: set[str]) -> bool:
    parts = module_name.split(".")
    for i in range(len(parts), 0, -1):
        prefix = ".".join(parts[:i])
        if prefix in all_imports:
            return True
    return False


def main() -> int:
    start = time.monotonic()

    if (REPO_ROOT / "scripts" / "ci_orphan_module_exempt.txt").exists():
        for line in (
            (REPO_ROOT / "scripts" / "ci_orphan_module_exempt.txt").read_text().splitlines()
        ):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                EXEMPT_PATHS.add(stripped)

    source_modules = _collect_source_modules()
    non_test_imports = _collect_all_imports(exclude_tests=True)

    orphans: list[str] = []
    for mod_name, mod_path in sorted(source_modules.items()):
        rel = str(mod_path.relative_to(REPO_ROOT))
        if rel in EXEMPT_PATHS:
            continue
        if not _is_imported(mod_name, non_test_imports):
            orphans.append(f"  {rel} ({mod_name})")

    elapsed = time.monotonic() - start

    if orphans:
        print(f"FAIL: {len(orphans)} orphan module(s) with zero non-test importers:")
        for o in orphans:
            print(o)
        print("\nTo exempt a module, add its relative path to scripts/ci_orphan_module_exempt.txt")
        print(f"Scan completed in {elapsed:.1f}s")
        return 1

    print(f"All {len(source_modules)} source modules have non-test importers. ({elapsed:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
