#!/usr/bin/env python3
"""Enqueue the constitutional governance blog post through the publication bus.

Usage:
    uv run python scripts/publish-constitutional-blog-post.py [--dry-run] [--surfaces omg-weblog]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import publish_vault_artifact

DRAFT_PATH = (
    REPO_ROOT
    / "docs"
    / "publication-drafts"
    / "2026-05-11-constitutional-governance-beyond-prompt-engineering.md"
)

DEFAULT_SURFACES = "omg-weblog"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enqueue constitutional governance blog post")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print artifact JSON without writing to the publication inbox",
    )
    parser.add_argument(
        "--surfaces",
        default=DEFAULT_SURFACES,
        help=f"Comma-separated publication-bus surfaces (default: {DEFAULT_SURFACES})",
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=None,
        help="Override $HAPAX_STATE for testing",
    )
    parser.add_argument(
        "--approver",
        default="Oudepode",
        help="Operator referent to record on approval",
    )
    args = parser.parse_args(argv)

    bus_args = [
        str(DRAFT_PATH),
        "--surfaces",
        args.surfaces,
        "--approver",
        args.approver,
    ]
    if args.state_root is not None:
        bus_args.extend(["--state-root", str(args.state_root)])
    if args.dry_run:
        bus_args.append("--dry-run")
    return publish_vault_artifact.main(bus_args)


if __name__ == "__main__":
    raise SystemExit(main())
