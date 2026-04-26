"""Validate audit-PR-<N>.yaml against the tier-aware schema.

P-1 of the absence-class-bug-prevention-and-remediation epic. Schema:
audits/SCHEMA.md. Templates: audits/template-tier-{0,1,2}.yaml.

Usage:
    python scripts/validate-audit-yaml.py audits/audit-PR-1234.yaml
    python scripts/validate-audit-yaml.py --tier 0 audits/audit-PR-1234.yaml

Exit codes:
    0 — schema valid (or absent for tier 0/1, which is allowed)
    1 — schema invalid OR tier-2 PR missing required fields
    2 — usage error
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

TIER1_FIELDS = ("tests_run", "lint_passed")

TIER2_FIELDS = (
    "data_flow_traced",
    "production_path_verified",
    "peer_module_glob_match",
    "new_function_call_sites",
)


def _validate(data: dict[str, Any], *, tier: int) -> list[str]:
    errors: list[str] = []
    declared_tier = data.get("tier")
    if declared_tier is not None and declared_tier != tier:
        errors.append(
            f"tier mismatch: file declares tier {declared_tier!r}, caller passed --tier {tier}"
        )
    if not isinstance(data.get("pr_number"), int):
        errors.append("pr_number missing or not an int")

    if tier >= 1:
        for f in TIER1_FIELDS:
            if not isinstance(data.get(f), bool):
                errors.append(f"{f} missing or not a bool")

    if tier >= 2:
        for f in TIER2_FIELDS[:3]:
            if not isinstance(data.get(f), bool):
                errors.append(f"{f} missing or not a bool")
        sites = data.get("new_function_call_sites")
        if not isinstance(sites, list):
            errors.append("new_function_call_sites missing or not a list")
        # If a substrate-truth field is False, require a `note:` companion
        for f in TIER2_FIELDS[:3]:
            if data.get(f) is False:
                note = data.get(f"{f}_note")
                if not isinstance(note, str) or not note.strip():
                    errors.append(f"{f} is false but {f}_note is missing or empty")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate audit-yaml schema")
    parser.add_argument("path", type=Path, help="path to audit-PR-<N>.yaml")
    parser.add_argument(
        "--tier",
        type=int,
        choices=(0, 1, 2),
        default=None,
        help="override tier (default: read from yaml)",
    )
    args = parser.parse_args(argv)

    if not args.path.exists():
        # Missing yaml is allowed for tier 0/1 PRs (the explicit-attestation
        # policy is tier-2 only).
        if args.tier is None or args.tier <= 1:
            print(f"ok: {args.path} not present; tier-0/1 default applies")
            return 0
        print(f"ERROR: tier-{args.tier} PR requires {args.path}", file=sys.stderr)
        return 1

    data = yaml.safe_load(args.path.read_text())
    if not isinstance(data, dict):
        print(f"ERROR: {args.path} did not parse as a yaml mapping", file=sys.stderr)
        return 1

    tier = args.tier if args.tier is not None else data.get("tier", 0)
    if not isinstance(tier, int) or tier not in (0, 1, 2):
        print(f"ERROR: tier {tier!r} not in (0, 1, 2)", file=sys.stderr)
        return 1

    errors = _validate(data, tier=tier)
    if errors:
        print(f"INVALID {args.path} (tier {tier}):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"ok: {args.path} valid (tier {tier})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
