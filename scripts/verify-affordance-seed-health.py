"""Verify Qdrant `affordances` collection payloads carry the governance fields.

Drift detection for the 2026-05-02 dispatch-dropout pattern (cc-task
`preset-bias-similarity-recruit-trace`): stale payloads that pre-date
the addition of ``monetization_risk`` / ``public_capable`` / ``content_risk``
to ``OperationalProperties`` cause the AffordancePipeline's monetization
gate to drop every fx.family.* candidate at ``monetization_filter_empty``
because ``_public_or_monetizable()`` fails closed on the missing field
(medium='visual' triggers the public-fallback branch).

Operator runs after adding/changing entries in
``shared/compositional_affordances.py`` to confirm the seeder kept the
indexed payloads in sync. Prints a per-capability JSON map of:

    {capability_name: missing_required_fields_or_empty_list}

Exits 0 when every capability has the required field set, non-zero with
the per-capability gap report otherwise. The companion fix is always
``scripts/seed-compositional-affordances.py`` — that's the operational
path that updates Qdrant in-place.

Usage:
    uv run scripts/verify-affordance-seed-health.py
    uv run scripts/verify-affordance-seed-health.py --prefix fx.family.
    uv run scripts/verify-affordance-seed-health.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


REQUIRED_FIELDS = (
    "monetization_risk",
    "public_capable",
    "content_risk",
)


def fetch_payloads(prefix: str | None) -> tuple[list[dict], str | None]:
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import FieldCondition, Filter, MatchText
    except ImportError as exc:
        return [], f"qdrant_client not installed: {exc}"

    try:
        from shared.affordance_pipeline import COLLECTION_NAME
        from shared.config import get_qdrant
    except Exception as exc:
        return [], f"affordance_pipeline import failed: {exc}"

    try:
        client = get_qdrant() if prefix is None else QdrantClient(url="http://localhost:6333")
        flt = (
            Filter(must=[FieldCondition(key="capability_name", match=MatchText(text=prefix))])
            if prefix
            else None
        )
        points, _ = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=flt,
            limit=500,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as exc:
        return [], f"qdrant query failed: {exc}"
    return [pt.payload for pt in points], None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--prefix",
        default=None,
        help="filter to capabilities whose name contains this prefix (e.g. 'fx.family.')",
    )
    p.add_argument("--json", action="store_true", help="emit machine-parseable JSON only")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    payloads, err = fetch_payloads(args.prefix)
    if err:
        report = {"status": "skipped", "reason": err}
        print(json.dumps(report))
        return 0

    gaps: dict[str, list[str]] = {}
    for payload in payloads:
        name = payload.get("capability_name", "<unknown>")
        missing = [f for f in REQUIRED_FIELDS if payload.get(f) is None]
        if missing:
            gaps[name] = missing

    report = {
        "status": "drift" if gaps else "healthy",
        "checked": len(payloads),
        "drifted": len(gaps),
        "required_fields": list(REQUIRED_FIELDS),
        "gaps": gaps,
        "remediation": ("uv run scripts/seed-compositional-affordances.py" if gaps else "(none)"),
    }

    if args.json:
        print(json.dumps(report, indent=2 if not gaps else None))
    else:
        print(f"status: {report['status']}")
        print(f"checked: {report['checked']} payloads")
        if gaps:
            print(f"drifted: {report['drifted']} capabilities missing fields")
            for name, missing in sorted(gaps.items()):
                print(f"  {name}: missing {missing}")
            print(f"remediation: {report['remediation']}")
        else:
            print("all required governance fields populated; no drift detected")

    return 0 if not gaps else 2


if __name__ == "__main__":
    sys.exit(main())
