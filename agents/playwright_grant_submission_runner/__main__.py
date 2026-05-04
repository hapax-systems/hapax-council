"""CLI entry: ``python -m agents.playwright_grant_submission_runner --target nlnet --dry-run``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

from agents.playwright_grant_submission_runner.package import (
    DEFAULT_PACKAGE_VAULT_PATH,
    load_universal_package,
)
from agents.playwright_grant_submission_runner.recipes import (
    BATCH_Q2_2026,
    default_recipes,
)
from agents.playwright_grant_submission_runner.runner import (
    GrantSubmissionRunner,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agents.playwright_grant_submission_runner",
        description="Universal grant-submission runner — fills portal forms from the operator's universal package.",
    )
    parser.add_argument(
        "--target",
        help="Single recipe name (e.g., 'nlnet', 'manifund'). Mutually exclusive with --batch.",
    )
    parser.add_argument(
        "--batch",
        choices=("q2-2026",),
        help="Batch name — runs all recipes in the batch sequentially.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fill forms + capture preview, but do NOT click submit. Default for safety.",
    )
    parser.add_argument(
        "--package",
        type=Path,
        default=DEFAULT_PACKAGE_VAULT_PATH,
        help=f"Path to the universal grant package markdown (default: {DEFAULT_PACKAGE_VAULT_PATH}).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List registered recipes (full + schema-only) and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = _build_parser()
    args = parser.parse_args(argv)
    recipes = default_recipes()

    if args.list:
        for name, recipe in sorted(recipes.items()):
            tag = "stub" if recipe.schema_only else "live"
            print(f"  {tag:5s}  {name:30s}  {recipe.portal_url}")
        return 0

    if not args.target and not args.batch:
        parser.error("supply --target <recipe> or --batch <name>")
    if args.target and args.batch:
        parser.error("--target and --batch are mutually exclusive")

    try:
        package = load_universal_package(args.package)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: package validation failed: {exc}", file=sys.stderr)
        return 2

    runner = GrantSubmissionRunner(recipes, package=package)

    if args.target:
        outcome = runner.run_target(args.target, dry_run=args.dry_run)
        print(json.dumps(asdict(outcome), default=str, indent=2))
        return 0 if outcome.status.value not in ("portal_error", "auth_error") else 1

    targets = list(BATCH_Q2_2026) if args.batch == "q2-2026" else []
    outcomes = runner.run_batch(targets, dry_run=args.dry_run)
    print(json.dumps([asdict(o) for o in outcomes], default=str, indent=2))
    if any(o.status.value in ("portal_error", "auth_error") for o in outcomes):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
