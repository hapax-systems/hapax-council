#!/usr/bin/env python3
"""Validate epistemic quality Phase 0 label set against acceptance criteria.

Checks:
  1. All manifest records have 4 labels on the 1-5 scale
  2. Each label row has required provenance fields
  3. No model-generated label marked ground truth
  4. No missing labels, invalid scale values, duplicate IDs, stale hashes
  5. Relabel subset frozen with due date >= 7 days after round-one timestamp
  6. Source-required rows have source references

Usage:
    uv run python scripts/validate-epistemic-labels.py
    uv run python scripts/validate-epistemic-labels.py --strict
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

DATASET_DIR = (
    Path.home() / "Documents/Personal/20-projects/hapax-research/datasets/epistemic-quality"
)
MANIFEST = DATASET_DIR / "phase0-golden-dataset-v0-curated.jsonl"
LABELS = DATASET_DIR / "phase0-human-labels-round1-v0.jsonl"
RELABEL_FREEZE = DATASET_DIR / "phase0-relabel-freeze-v0.json"

REQUIRED_AXES = frozenset(
    {
        "claim_evidence_alignment",
        "hedge_calibration",
        "quantifier_precision",
        "source_grounding",
    }
)
VALID_SCALE = frozenset(range(1, 6))
REQUIRED_LABEL_FIELDS = frozenset(
    {
        "id",
        "manifest_hash",
        "source_ref",
        "source_text_hash",
        "label_round",
        "labeler",
        "label_origin",
        "labeled_at",
        "provenance",
        "labels",
    }
)
FORBIDDEN_ORIGINS = frozenset({"model", "llm", "auto", "generated", "claude", "gpt"})
RELABEL_MIN_DELAY_DAYS = 7
EXPECTED_RELABEL_COUNT = 40


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def compute_manifest_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(
    *,
    strict: bool = False,
    manifest_path: Path = MANIFEST,
    labels_path: Path = LABELS,
    freeze_path: Path = RELABEL_FREEZE,
) -> tuple[bool, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not manifest_path.exists():
        errors.append(f"Manifest not found: {manifest_path}")
        return False, errors, warnings

    manifest_records = load_jsonl(manifest_path)
    if len(manifest_records) != 200:
        errors.append(f"Manifest has {len(manifest_records)} records, expected 200")

    manifest_ids = {r["id"] for r in manifest_records}
    manifest_by_id = {r["id"]: r for r in manifest_records}
    current_hash = compute_manifest_hash(manifest_path)

    if not labels_path.exists():
        errors.append(f"Label file not found: {labels_path}")
        return False, errors, warnings

    label_rows = load_jsonl(labels_path)
    seen_ids: set[str] = set()
    earliest_ts: datetime | None = None

    for i, row in enumerate(label_rows):
        row_id = row.get("id", f"<row {i}>")

        missing_fields = REQUIRED_LABEL_FIELDS - set(row.keys())
        if missing_fields:
            errors.append(f"{row_id}: missing fields {sorted(missing_fields)}")

        if row_id in seen_ids:
            errors.append(f"{row_id}: duplicate ID")
        seen_ids.add(row_id)

        if row_id not in manifest_ids:
            errors.append(f"{row_id}: not in manifest")

        if row.get("manifest_hash") != current_hash:
            errors.append(
                f"{row_id}: stale manifest hash "
                f"(got {row.get('manifest_hash', 'missing')[:16]}..., "
                f"expected {current_hash[:16]}...)"
            )

        origin = str(row.get("label_origin", "")).lower()
        if origin in FORBIDDEN_ORIGINS:
            errors.append(f"{row_id}: model-generated label origin={origin}")

        labels = row.get("labels", {})
        if not isinstance(labels, dict):
            errors.append(f"{row_id}: labels is not a dict")
            continue

        missing_axes = REQUIRED_AXES - set(labels.keys())
        if missing_axes:
            errors.append(f"{row_id}: missing axes {sorted(missing_axes)}")

        for axis, value in labels.items():
            if axis not in REQUIRED_AXES:
                warnings.append(f"{row_id}: unexpected axis '{axis}'")
            if value not in VALID_SCALE:
                errors.append(f"{row_id}: {axis}={value} not in 1-5")

        manifest_row = manifest_by_id.get(row_id)
        if manifest_row and manifest_row.get("source_ref"):
            if not row.get("source_ref"):
                errors.append(f"{row_id}: source-required row missing source_ref")

        ts_str = row.get("labeled_at")
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str)
                if earliest_ts is None or ts < earliest_ts:
                    earliest_ts = ts
            except (ValueError, TypeError):
                errors.append(f"{row_id}: invalid labeled_at timestamp")

    unlabeled = manifest_ids - seen_ids
    if unlabeled:
        if strict:
            errors.append(
                f"{len(unlabeled)} manifest records unlabeled: {sorted(unlabeled)[:5]}..."
            )
        else:
            warnings.append(f"{len(unlabeled)} manifest records still unlabeled")

    relabel_ids = {r["id"] for r in manifest_records if r.get("relabel_required")}
    if len(relabel_ids) != EXPECTED_RELABEL_COUNT:
        warnings.append(
            f"Relabel subset has {len(relabel_ids)} records, expected {EXPECTED_RELABEL_COUNT}"
        )

    if freeze_path.exists():
        try:
            freeze = json.loads(freeze_path.read_text())
            freeze_ids = set(freeze.get("relabel_ids", []))
            if freeze_ids != relabel_ids:
                errors.append(
                    f"Relabel freeze IDs mismatch: "
                    f"{len(freeze_ids)} frozen vs {len(relabel_ids)} in manifest"
                )
            due_str = freeze.get("relabel_due_date")
            if due_str and earliest_ts:
                due = datetime.fromisoformat(due_str)
                min_due = earliest_ts + timedelta(days=RELABEL_MIN_DELAY_DAYS)
                if due < min_due:
                    errors.append(
                        f"Relabel due date {due.date()} is < 7 days "
                        f"after earliest label {earliest_ts.date()}"
                    )
        except (json.JSONDecodeError, KeyError) as e:
            errors.append(f"Relabel freeze file invalid: {e}")
    elif strict:
        errors.append("Relabel freeze file not found")
    else:
        warnings.append("Relabel freeze file not yet created")

    return len(errors) == 0, errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 0 labels")
    parser.add_argument("--strict", action="store_true", help="Require all 200 labels + freeze")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    ok, errors, warnings = validate(strict=args.strict)
    label_count = len(load_jsonl(LABELS)) if LABELS.exists() else 0

    if args.json:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "label_count": label_count,
                    "target": 200,
                    "errors": errors,
                    "warnings": warnings,
                },
                indent=2,
            )
        )
    else:
        print("\n=== Epistemic Quality Phase 0 Label Validation ===")
        print(f"Labels: {label_count}/200")
        if warnings:
            print(f"\nWarnings ({len(warnings)}):")
            for w in warnings:
                print(f"  ⚠ {w}")
        if errors:
            print(f"\nErrors ({len(errors)}):")
            for e in errors:
                print(f"  ✗ {e}")
        if ok:
            print(f"\n✓ Validation passed{' (strict)' if args.strict else ''}")
        else:
            print(f"\n✗ Validation failed with {len(errors)} error(s)")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
