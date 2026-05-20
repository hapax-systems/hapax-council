#!/usr/bin/env python3
"""Report research gaps whose value half-life expires within 90 days."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml

REGISTRY = Path(__file__).resolve().parents[1] / "docs" / "research" / "gap-portfolio-registry.yaml"


def load_registry(path: Path = REGISTRY) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def decay_report(registry: dict, horizon_days: int = 90) -> list[dict]:
    now = datetime.now()
    horizon = now + timedelta(days=horizon_days)
    expiring = []
    for gap in registry.get("gaps", []):
        halflife = gap.get("decay_rate_halflife_days", 365)
        reviewed = gap.get("last_reviewed", "2026-01-01")
        reviewed_dt = datetime.fromisoformat(reviewed)
        expiry = reviewed_dt + timedelta(days=halflife)
        days_remaining = (expiry - now).days
        if expiry <= horizon:
            expiring.append(
                {
                    "gap_id": gap["gap_id"],
                    "title": gap["title"],
                    "disposition": gap["disposition"],
                    "halflife_days": halflife,
                    "days_remaining": days_remaining,
                    "expiry_date": expiry.strftime("%Y-%m-%d"),
                    "uniqueness_score": gap.get("uniqueness_score", 0),
                }
            )
    return sorted(expiring, key=lambda x: x["days_remaining"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Gap decay report")
    parser.add_argument("--horizon", type=int, default=90, help="Days to look ahead")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    registry = load_registry()
    report = decay_report(registry, args.horizon)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"\n=== Gaps expiring within {args.horizon} days ===")
        if not report:
            print("  None — all gaps within horizon.")
        for g in report:
            status = "EXPIRED" if g["days_remaining"] < 0 else f"{g['days_remaining']}d remaining"
            print(f"  {g['gap_id']} [{g['disposition']}] {g['title']}")
            print(
                f"    halflife={g['halflife_days']}d, {status}, uniqueness={g['uniqueness_score']:.2f}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
