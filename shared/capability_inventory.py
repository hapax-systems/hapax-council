"""The read-only capability inventory + validation report (the read-model).

Projects the capability-harness descriptors, validates each against its shape's required facts, and reports
the freshness state. This is the read-model that makes escaped/boutique capabilities visible (taxonomy First
Implementation Sequence step 3). READ-ONLY: it mutates nothing. The dash-named ``scripts/hapax-capability-
inventory`` is a thin entry wrapper around :func:`main` here.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from shared.agentic_trust_boundary import is_agentic_trust_supply_evidence_reference
from shared.capability_harness_descriptor import (
    CapabilityHarnessDescriptor,
    validate_descriptor,
)
from shared.capability_harness_seed import SEED_CAPABILITY_DESCRIPTORS
from shared.capability_inventory_contract import (
    CapabilityInventoryBaselineRecord,
    CapabilityInventoryBaselineV2,
    InventoryDisposition,
    wrap_supply_descriptor_fingerprint,
)

# full_inventory_delta is imported lazily inside main(--delta) to avoid pulling
# all adapter modules at import time for users who only want the seed inventory.

__all__ = ["inventory_report", "project_inventory"]

_BASELINE_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "capability-inventory-baseline.json"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _load_inventory_baseline(
    path: Path = _BASELINE_PATH,
) -> dict[str, CapabilityInventoryBaselineRecord]:
    """Load tagged v2 baseline records, upgrading v1 supply hashes explicitly.

    A v1 baseline can match its admitted-supply rows, but it cannot silently bless
    omitted shapes: those appear NEW until the baseline is intentionally regenerated.
    """

    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("capability inventory baseline must be a JSON object")
    if "schema_version" in payload:
        if payload["schema_version"] != 2 or type(payload["schema_version"]) is not int:
            raise ValueError(
                f"unsupported capability inventory baseline schema_version: "
                f"{payload['schema_version']!r}"
            )
        return CapabilityInventoryBaselineV2.model_validate(payload).records

    if set(payload) != {"count", "fingerprints"}:
        raise ValueError(
            "legacy capability inventory baseline must contain exactly count and fingerprints"
        )
    count = payload["count"]
    if type(count) is not int or count < 0:
        raise ValueError(
            "legacy capability inventory baseline count must be a non-negative integer"
        )
    fingerprints = payload["fingerprints"]
    if not isinstance(fingerprints, dict):
        raise ValueError("legacy capability inventory baseline fingerprints must be an object")
    if count != len(fingerprints):
        raise ValueError("legacy capability inventory baseline count does not match fingerprints")
    for capability_id, fingerprint in fingerprints.items():
        if type(capability_id) is not str or not capability_id.strip():
            raise ValueError("legacy capability inventory IDs must be non-empty strings")
        if type(fingerprint) is not str or _SHA256_RE.fullmatch(fingerprint) is None:
            raise ValueError(
                f"legacy capability inventory fingerprint for {capability_id!r} "
                "must be a lowercase SHA-256 digest"
            )
        if is_agentic_trust_supply_evidence_reference(capability_id):
            raise ValueError(
                "legacy capability inventory cannot classify the agentic-trust evaluator; "
                "migrate it explicitly to evidence_only_non_supply schema v2"
            )
    return {
        capability_id: CapabilityInventoryBaselineRecord(
            inventory_disposition=InventoryDisposition.ADMITTED_SUPPLY,
            fingerprint=wrap_supply_descriptor_fingerprint(fingerprint),
        )
        for capability_id, fingerprint in fingerprints.items()
    }


def _rows(descriptors: Sequence[CapabilityHarnessDescriptor]) -> list[dict[str, object]]:
    """Build the per-descriptor rows (capability_id, shape, freshness, gaps)."""
    rows: list[dict[str, object]] = []
    for desc in descriptors:
        gaps = validate_descriptor(desc)
        rows.append(
            {
                "capability_id": desc.capability_id,
                "shape": desc.shape.value,
                "domain": desc.domain.value,
                "freshness_state": desc.freshness_state.value,
                "authority_ceiling": desc.authority_ceiling.value,
                "gaps": gaps,
            }
        )
    return rows


def inventory_report(descriptors: Sequence[CapabilityHarnessDescriptor]) -> dict[str, object]:
    """The structured inventory report (the read-model output)."""
    rows = _rows(descriptors)
    with_gaps = [r for r in rows if r["gaps"]]
    freshness_counts: dict[str, int] = {}
    shape_counts: dict[str, int] = {}
    for row in rows:
        fstate = str(row["freshness_state"])
        shape = str(row["shape"])
        freshness_counts[fstate] = freshness_counts.get(fstate, 0) + 1
        shape_counts[shape] = shape_counts.get(shape, 0) + 1
    return {
        "total": len(rows),
        "with_validation_gaps": len(with_gaps),
        "freshness_counts": freshness_counts,
        "shape_counts": shape_counts,
        "rows": rows,
    }


def project_inventory(
    descriptors: Sequence[CapabilityHarnessDescriptor] = SEED_CAPABILITY_DESCRIPTORS,
    *,
    gaps_only: bool = False,
) -> list[dict[str, object]]:
    """Project the inventory rows (optionally only those with validation gaps)."""
    rows = _rows(descriptors)
    return [r for r in rows if r["gaps"]] if gaps_only else rows


def _render_human(descriptors: Sequence[CapabilityHarnessDescriptor]) -> str:
    report = inventory_report(descriptors)
    lines = [
        f"Capability inventory ({report['total']} descriptors):",
        "",
        f"  {'shape':<26} {'capability_id':<42} {'fresh':<8} gaps",
        f"  {'-' * 26} {'-' * 42} {'-' * 8} ----",
    ]
    for row in report["rows"]:
        gaps = ", ".join(str(g) for g in row["gaps"]) if row["gaps"] else "-"
        lines.append(
            f"  {str(row['shape']):<26} {str(row['capability_id']):<42} "
            f"{str(row['freshness_state']):<8} {gaps}"
        )
    lines.append("")
    lines.append(
        f"TOTAL: {report['total']} descriptors, "
        f"{report['with_validation_gaps']} with validation gaps, "
        f"{report['freshness_counts'].get('dark', 0)} DARK (freshness unmeasured)."
    )
    if report["with_validation_gaps"]:
        lines.append("DESCRIPTORS WITH GAPS (shape-required facts missing):")
        for row in report["rows"]:
            if row["gaps"]:
                lines.append(
                    f"  {row['capability_id']} ({row['shape']}): {', '.join(str(g) for g in row['gaps'])}"
                )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """The inventory CLI entry (human report by default; --json / --gaps-only)."""
    parser = argparse.ArgumentParser(
        prog="hapax-capability-inventory",
        description="Read-only capability inventory + validation (the read-model).",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit the structured report as JSON (machine-readable)"
    )
    parser.add_argument(
        "--gaps-only", action="store_true", help="only list descriptors with shape-validation gaps"
    )
    parser.add_argument(
        "--delta",
        action="store_true",
        help="run the tagged capability inventory delta over supply and non-supply planes",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=_BASELINE_PATH,
        help="fingerprint baseline to compare against when --delta is set",
    )
    args = parser.parse_args(argv)

    if args.delta:
        from shared.capability_inventory_aggregator import full_capability_inventory_delta

        try:
            registered = _load_inventory_baseline(args.baseline)
        except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
            print(f"capability_inventory_baseline_invalid: {exc}")
            print("NEXT: repair or regenerate the tagged v2 capability inventory baseline.")
            return 2
        snapshot, delta = full_capability_inventory_delta(registered)
        admitted_supply = snapshot.admitted_supply_descriptors()
        invalid = {
            descriptor.capability_id: validate_descriptor(descriptor)
            for descriptor in admitted_supply
            if validate_descriptor(descriptor)
        }
        if invalid:
            print("capability_inventory_validation_gaps:")
            for capability_id, gaps in sorted(invalid.items()):
                print(f"  {capability_id}: {', '.join(gaps)}")
            print("NEXT: fill the missing descriptor facts before regenerating the baseline.")
            return 1
        print(
            f"capability_inventory_delta: {len(delta.new_capability_ids)} new, "
            f"{len(delta.changed_capability_ids)} changed, "
            f"{len(delta.missing_capability_ids)} missing "
            f"(of {len(snapshot.records)} observed; inventory_schema=2)"
        )
        for cid, kind in delta.kinds():
            print(f"  {kind.value}: {cid}")
        if not delta.is_empty:
            print(
                "NEXT: repair the descriptor source or regenerate "
                "config/capability-inventory-baseline.json after an intentional tagged inventory change."
            )
        return 1 if not delta.is_empty else 0

    descriptors = SEED_CAPABILITY_DESCRIPTORS
    if args.gaps_only:
        for row in project_inventory(descriptors, gaps_only=True):
            print(
                f"{row['capability_id']} ({row['shape']}): {', '.join(str(g) for g in row['gaps'])}"
            )
        return 0
    if args.json:
        print(json.dumps(inventory_report(descriptors), indent=2, sort_keys=True))
        return 0
    print(_render_human(descriptors))
    return 0
