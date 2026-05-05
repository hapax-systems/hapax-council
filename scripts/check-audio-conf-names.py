#!/usr/bin/env python3
"""CI/pre-commit gate for deployable PipeWire conf file names.

Audit E naming rule: top-level, hand-authored files in
``config/pipewire/*.conf`` must be named ``hapax-*.conf``. Generated
compiler artifacts under ``config/pipewire/generated/`` intentionally
keep their node-id filenames and are out of scope for this gate.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PIPEWIRE_DIR = REPO_ROOT / "config" / "pipewire"
NAME_PATTERN = re.compile(r"^hapax-[A-Za-z0-9][A-Za-z0-9_.-]*\.conf$")


def deployable_confs(pipewire_dir: Path) -> list[Path]:
    """Return top-level deployable PipeWire confs only."""

    if not pipewire_dir.is_dir():
        return []
    return sorted(path for path in pipewire_dir.glob("*.conf") if path.is_file())


def check(pipewire_dir: Path = DEFAULT_PIPEWIRE_DIR) -> tuple[int, str]:
    violations = [
        path.name
        for path in deployable_confs(pipewire_dir)
        if NAME_PATTERN.fullmatch(path.name) is None
    ]
    if not violations:
        return (
            0,
            f"OK - all {len(deployable_confs(pipewire_dir))} deployable PipeWire confs use hapax-* names.",
        )
    lines = [
        "check-audio-conf-names: non-hapax deployable PipeWire conf names detected",
        "",
        "Top-level files under config/pipewire/ must match ^hapax-.*\\.conf$:",
    ]
    lines.extend(f"  - {name}" for name in violations)
    lines.extend(
        [
            "",
            "Fix: rename the file to hapax-*.conf and update references/tests/docs.",
            "Generated files under config/pipewire/generated/ are intentionally not checked.",
        ]
    )
    return 1, "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reject non-hapax top-level PipeWire conf filenames.",
    )
    parser.add_argument(
        "--pipewire-dir",
        type=Path,
        default=DEFAULT_PIPEWIRE_DIR,
        help=f"Path to deployable PipeWire conf dir (default: {DEFAULT_PIPEWIRE_DIR})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    code, message = check(args.pipewire_dir)
    print(message, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
