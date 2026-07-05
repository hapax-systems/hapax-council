"""The read-only capability inventory + validation report (the read-model).

Projects the capability-harness descriptors, validates each against its shape's required facts, and reports
the freshness state. This is the read-model that makes escaped/boutique capabilities visible (taxonomy First
Implementation Sequence step 3). READ-ONLY: it mutates nothing. The dash-named ``scripts/hapax-capability-
inventory`` is a thin entry wrapper around :func:`main` here.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from shared.capability_harness_descriptor import (
    CapabilityHarnessDescriptor,
    validate_descriptor,
)
from shared.capability_harness_seed import SEED_CAPABILITY_DESCRIPTORS

# full_inventory_delta is imported lazily inside main(--delta) to avoid pulling
# all adapter modules at import time for users who only want the seed inventory.

__all__ = ["inventory_report", "project_inventory"]

_BASELINE_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "capability-inventory-baseline.json"
)


def _load_registered_baseline(path: Path = _BASELINE_PATH) -> dict[str, str]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    fingerprints = payload.get("fingerprints", {})
    return (
        {str(cid): str(fp) for cid, fp in fingerprints.items()}
        if isinstance(fingerprints, dict)
        else {}
    )


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
        help="run the full capability_surface_delta over ALL 7 vocabularies (the real failing check)",
    )
    args = parser.parse_args(argv)

    if args.delta:
        from shared.capability_inventory_aggregator import full_inventory_delta

        observed, delta = full_inventory_delta(_load_registered_baseline())
        invalid = {
            descriptor.capability_id: validate_descriptor(descriptor)
            for descriptor in observed
            if validate_descriptor(descriptor)
        }
        if invalid:
            print("capability_inventory_validation_gaps:")
            for capability_id, gaps in sorted(invalid.items()):
                print(f"  {capability_id}: {', '.join(gaps)}")
            return 1
        print(
            f"capability_surface_delta: {len(delta.new_capability_ids)} new, "
            f"{len(delta.changed_capability_ids)} changed, "
            f"{len(delta.missing_capability_ids)} missing "
            f"(of {len(observed)} observed)"
        )
        for cid, kind in delta.kinds():
            print(f"  {kind.value}: {cid}")
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
