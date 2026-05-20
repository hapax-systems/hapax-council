"""CLI entry point: ``python -m agents.assertion_extractor --target <path>``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agents.assertion_extractor.code_extractor import extract_from_directory
from agents.assertion_extractor.yaml_extractor import extract_from_config_directory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract assertions from code and config")
    parser.add_argument("--target", type=Path, required=True, help="Root directory to scan")
    parser.add_argument(
        "--config-dir", type=Path, help="Config directory (defaults to target/config)"
    )
    parser.add_argument("--repo-root", type=Path, help="Repository root for relative paths")
    args = parser.parse_args(argv)

    repo_root = args.repo_root or args.target
    code_assertions = extract_from_directory(args.target, repo_root=repo_root)

    config_dir = args.config_dir or (args.target / "config")
    config_assertions = []
    if config_dir.exists():
        config_assertions = extract_from_config_directory(config_dir, repo_root=repo_root)

    total = len(code_assertions) + len(config_assertions)
    by_method: dict[str, int] = {}
    for a in code_assertions + config_assertions:
        method = a.provenance.extraction_method
        by_method[method] = by_method.get(method, 0) + 1

    print(
        f"Extracted {total} assertions ({len(code_assertions)} code, {len(config_assertions)} config)"
    )
    for method, count in sorted(by_method.items()):
        print(f"  {method}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
