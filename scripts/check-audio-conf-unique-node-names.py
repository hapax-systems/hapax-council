#!/usr/bin/env python3
"""Reject PipeWire conf sets with duplicate node.name declarations.

PipeWire targets nodes by name. If two loadable conf files declare the same
``node.name``, a restart can bind links to either instance. This checker treats
top-level ``config/pipewire/*.conf`` files and remaining generated artifacts as
one candidate deployable set, while intentionally ignoring archive/golden files.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONF_ROOTS = (
    REPO_ROOT / "config" / "pipewire",
    REPO_ROOT / "config" / "pipewire" / "generated" / "pipewire",
)

NODE_NAME_PATTERN = re.compile(r"\bnode\.name\s*=\s*\"([^\"]+)\"")


def conf_files(root: Path) -> list[Path]:
    """Return loadable conf files directly under ``root``."""

    if not root.is_dir():
        return []
    return sorted(path for path in root.glob("*.conf") if path.is_file())


def declared_node_names(path: Path) -> set[str]:
    """Return unique node.name values declared by a conf file."""

    text = path.read_text(encoding="utf-8", errors="ignore")
    return set(NODE_NAME_PATTERN.findall(text))


def duplicate_node_names(roots: tuple[Path, ...]) -> dict[str, list[Path]]:
    by_node: dict[str, set[Path]] = defaultdict(set)
    for root in roots:
        for path in conf_files(root):
            for node_name in declared_node_names(path):
                by_node[node_name].add(path)
    return {
        node_name: sorted(paths) for node_name, paths in sorted(by_node.items()) if len(paths) > 1
    }


def format_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def check(roots: tuple[Path, ...] = DEFAULT_CONF_ROOTS) -> tuple[int, str]:
    duplicates = duplicate_node_names(roots)
    file_count = sum(len(conf_files(root)) for root in roots)
    if not duplicates:
        return 0, f"OK - {file_count} PipeWire confs declare unique node.name values."

    lines = [
        "check-audio-conf-unique-node-names: duplicate PipeWire node.name declarations",
        "",
        "Each node.name may appear in only one loadable conf file:",
    ]
    for node_name, paths in duplicates.items():
        lines.append(f"  - {node_name}")
        lines.extend(f"      {format_path(path)}" for path in paths)
    lines.extend(
        [
            "",
            "Fix: keep one canonical conf and move duplicate fossils outside any",
            "pipewire.conf.d load path, or rename the node if both nodes are truly",
            "intended to co-exist.",
        ]
    )
    return 1, "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reject duplicate PipeWire node.name declarations across conf files.",
    )
    parser.add_argument(
        "--conf-root",
        type=Path,
        action="append",
        dest="conf_roots",
        help=(
            "Directory containing loadable *.conf files. May be repeated. "
            "Defaults to config/pipewire and config/pipewire/generated/pipewire."
        ),
    )
    parser.add_argument(
        "--deployed-dir",
        type=Path,
        help="Shortcut for checking a deployed pipewire.conf.d directory by itself.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.deployed_dir is not None and args.conf_roots:
        print("--deployed-dir cannot be combined with --conf-root", file=sys.stderr)
        return 2
    roots = (
        (args.deployed_dir,)
        if args.deployed_dir is not None
        else tuple(args.conf_roots or DEFAULT_CONF_ROOTS)
    )
    code, message = check(roots)
    print(message, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
