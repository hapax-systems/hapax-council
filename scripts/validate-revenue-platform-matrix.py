#!/usr/bin/env python3
"""Validate the revenue platform W-9/payout rollout matrix.

Checks completeness, required fields, and rollout progress.

Usage:
    uv run python scripts/validate-revenue-platform-matrix.py
    uv run python scripts/validate-revenue-platform-matrix.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

MATRIX_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "revenue-platform-w9-payout-matrix.yaml"
)

REQUIRED_PLATFORM_FIELDS = {
    "id",
    "name",
    "category",
    "w9_required",
    "payout_setup_required",
    "status",
    "operator_steps",
    "source_links",
}
VALID_STATUSES = {
    "not_started",
    "in_progress",
    "submitted",
    "verified",
    "blocked",
    "not_applicable",
}
MIN_PLATFORMS = 8


def validate(matrix_path: Path = MATRIX_PATH) -> tuple[bool, list[str], list[str], dict]:
    errors: list[str] = []
    warnings: list[str] = []

    if not matrix_path.exists():
        errors.append(f"Matrix file not found: {matrix_path}")
        return False, errors, warnings, {}

    data = yaml.safe_load(matrix_path.read_text())
    platforms = data.get("platforms", [])

    if len(platforms) < MIN_PLATFORMS:
        errors.append(f"Only {len(platforms)} platforms, need >= {MIN_PLATFORMS}")

    completed = 0
    blocked = 0

    for p in platforms:
        pid = p.get("id", "unknown")
        missing = REQUIRED_PLATFORM_FIELDS - set(p.keys())
        if missing:
            errors.append(f"{pid}: missing fields {sorted(missing)}")

        status = p.get("status", "")
        if status not in VALID_STATUSES:
            errors.append(f"{pid}: invalid status '{status}'")

        if status == "blocked" and not p.get("blocker"):
            errors.append(f"{pid}: status=blocked but no blocker recorded")

        if status in ("submitted", "verified"):
            if not p.get("evidence_path"):
                warnings.append(f"{pid}: {status} but no evidence_path")
            completed += 1

        if status == "blocked":
            blocked += 1

        if not p.get("source_links"):
            warnings.append(f"{pid}: no source links")

        if not p.get("operator_steps"):
            errors.append(f"{pid}: no operator_steps defined")

    stats = {
        "total": len(platforms),
        "completed": completed,
        "blocked": blocked,
        "not_started": sum(1 for p in platforms if p.get("status") == "not_started"),
    }

    return len(errors) == 0, errors, warnings, stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate revenue platform matrix")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    ok, errors, warnings, stats = validate()

    if args.json:
        print(
            json.dumps({"ok": ok, "stats": stats, "errors": errors, "warnings": warnings}, indent=2)
        )
    else:
        print("\n=== Revenue Platform W-9/Payout Matrix ===")
        print(
            f"Platforms: {stats['total']} ({stats['completed']} done, {stats['blocked']} blocked, {stats['not_started']} pending)"
        )
        if warnings:
            for w in warnings:
                print(f"  ⚠ {w}")
        if errors:
            for e in errors:
                print(f"  ✗ {e}")
        print(f"\n{'✓ Valid' if ok else '✗ Invalid'}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
