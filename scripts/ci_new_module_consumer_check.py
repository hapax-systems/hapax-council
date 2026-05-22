#!/usr/bin/env python3
import ast
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def extract_imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_bytes(), filename=str(path))
    except Exception:
        return set()
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    return imports


def is_imported(module_name: str, all_imports: set[str]) -> bool:
    parts = module_name.split(".")
    for i in range(len(parts), 0, -1):
        prefix = ".".join(parts[:i])
        if prefix in all_imports:
            return True
    return False


def main():
    base_ref = os.environ.get("GITHUB_BASE_REF")
    if not base_ref:
        print("GITHUB_BASE_REF not set. Assuming no new files.")
        sys.exit(0)

    try:
        output = subprocess.check_output(
            ["git", "diff", "--name-only", "--diff-filter=A", f"origin/{base_ref}", "HEAD"]
        )
        added_files = output.decode().splitlines()
    except subprocess.CalledProcessError as e:
        print(f"Failed to run git diff: {e}")
        sys.exit(1)

    # project's module glob patterns: assume shared/, agents/, logos/ and ends with .py
    module_files = [
        f
        for f in added_files
        if f.endswith(".py") and any(f.startswith(d + "/") for d in ["shared", "agents", "logos"])
    ]

    if not module_files:
        print("No new module files are present in the diff.")
        sys.exit(0)

    # Collect exempt paths
    exempt_paths = set()
    exempt_file = REPO_ROOT / "scripts" / "ci_orphan_module_exempt.txt"
    if exempt_file.exists():
        for line in exempt_file.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                exempt_paths.add(stripped)

    # Collect all imports from non-test source files
    non_test_imports = set()
    exclude_patterns = ["__pycache__", ".venv", "node_modules", "_retired", "packages/"]
    for py_file in REPO_ROOT.rglob("*.py"):
        s = str(py_file)
        if any(p in s for p in exclude_patterns):
            continue
        if "tests" in py_file.parts:
            continue
        non_test_imports.update(extract_imports(py_file))

    failed = False
    for mod_path_str in module_files:
        if mod_path_str in exempt_paths:
            continue

        mod_path = REPO_ROOT / mod_path_str
        if mod_path.stem in {"__init__", "__main__", "conftest"}:
            continue

        rel = mod_path.relative_to(REPO_ROOT)
        parts = list(rel.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        mod_name = ".".join(parts)

        if not is_imported(mod_name, non_test_imports):
            print(f"FAIL: New module {mod_path_str} has 0 non-test consumers.")
            failed = True

    if failed:
        sys.exit(1)

    print("All new modules have at least one non-test consumer.")
    sys.exit(0)


if __name__ == "__main__":
    main()
