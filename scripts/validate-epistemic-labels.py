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
import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

DATASET_DIR = (
    Path.home() / "Documents/Personal/20-projects/hapax-research/datasets/epistemic-quality"
)
MANIFEST = DATASET_DIR / "phase0-golden-dataset-v0-curated.jsonl"
LABELS = DATASET_DIR / "phase0-human-labels-round1-v0.jsonl"
RELABEL_LABELS = DATASET_DIR / "phase0-human-labels-relabel-v0.jsonl"
RELABEL_FREEZE = DATASET_DIR / "phase0-relabel-freeze-v0.json"
RELABEL_REPORT_JSON = DATASET_DIR / "phase0-relabel-reliability-report-v0.json"
RELABEL_REPORT_MD = DATASET_DIR / "phase0-relabel-reliability-report-v0.md"

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
KAPPA_THRESHOLD = 0.75


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


def row_manifest_id(row: dict[str, Any]) -> str:
    """Accept both historical `id` rows and current `manifest_id` rows."""
    value = row.get("manifest_id", row.get("id", ""))
    return str(value)


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def cohen_kappa(left: list[int], right: list[int]) -> dict[str, Any]:
    if len(left) != len(right) or not left:
        return {"n": min(len(left), len(right)), "kappa": None, "computable": False}
    categories = range(1, 6)
    n = len(left)
    observed = sum(1 for a, b in zip(left, right, strict=True) if a == b) / n
    expected = sum(
        (left.count(category) / n) * (right.count(category) / n) for category in categories
    )
    if math.isclose(expected, 1.0):
        kappa = 1.0 if math.isclose(observed, 1.0) else 0.0
    else:
        kappa = (observed - expected) / (1.0 - expected)
    return {"n": n, "kappa": kappa, "computable": True}


def _validate_reliability_rows(
    *,
    rows: list[dict[str, Any]],
    manifest_by_id: dict[str, dict[str, Any]],
    manifest_hash: str,
    expected_ids: set[str],
    expected_round: str,
    allow_extra_ids: bool = False,
) -> tuple[list[str], dict[str, dict[str, Any]], dict[str, int]]:
    errors: list[str] = []
    valid_by_id: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    counters = {
        "stale_manifest_hashes": 0,
        "invalid_label_values": 0,
        "missing_expected_rows": 0,
        "unexpected_rows": 0,
    }

    for index, row in enumerate(rows, start=1):
        manifest_id = row_manifest_id(row)
        row_label = manifest_id or f"row {index}"
        row_errors: list[str] = []
        if not manifest_id:
            row_errors.append("missing id or manifest_id")
        elif manifest_id in seen:
            row_errors.append(f"duplicate {expected_round} row")
        seen.add(manifest_id)

        record = manifest_by_id.get(manifest_id)
        if record is None:
            row_errors.append("not in manifest")
        elif manifest_id not in expected_ids and not allow_extra_ids:
            counters["unexpected_rows"] += 1
            row_errors.append(f"not in expected {expected_round} set")

        if row.get("manifest_hash") != manifest_hash:
            counters["stale_manifest_hashes"] += 1
            row_errors.append("stale or missing manifest_hash")

        if record is not None:
            if row.get("source_ref") != record.get("source_ref"):
                row_errors.append("source_ref does not match manifest")
            if row.get("source_text_hash") not in (None, record.get("excerpt_hash")):
                row_errors.append("source_text_hash does not match manifest")

        if row.get("label_round") != expected_round:
            row_errors.append(f"label_round must be {expected_round!r}")
        if not row.get("labeler"):
            row_errors.append("missing labeler")
        if not row.get("provenance"):
            row_errors.append("missing provenance")
        if parse_timestamp(row.get("labeled_at")) is None:
            row_errors.append("labeled_at is missing or invalid")

        origin = str(row.get("label_origin", "")).lower()
        if origin in FORBIDDEN_ORIGINS:
            row_errors.append(f"model-generated label origin={origin}")

        labels = row.get("labels")
        if not isinstance(labels, dict):
            counters["invalid_label_values"] += 1
            row_errors.append("labels is not a dict")
        else:
            if set(labels) != REQUIRED_AXES:
                counters["invalid_label_values"] += 1
                row_errors.append(f"labels must contain exactly {sorted(REQUIRED_AXES)}")
            for axis in REQUIRED_AXES:
                value = labels.get(axis)
                if value not in VALID_SCALE:
                    counters["invalid_label_values"] += 1
                    row_errors.append(f"{axis}={value!r} not in 1-5")

        if row_errors:
            errors.extend(f"{row_label}: {error}" for error in row_errors)
            continue
        if manifest_id in expected_ids:
            valid_by_id[manifest_id] = row

    missing = sorted(expected_ids - set(valid_by_id))
    counters["missing_expected_rows"] = len(missing)
    if missing:
        errors.append(f"missing {expected_round} rows: {', '.join(missing[:10])}")
    return errors, valid_by_id, counters


def compute_relabel_reliability_report(
    *,
    manifest_path: Path = MANIFEST,
    labels_path: Path = LABELS,
    relabel_labels_path: Path = RELABEL_LABELS,
) -> dict[str, Any]:
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not manifest_path.exists():
        return {
            "status": "manifest_missing",
            "passed": False,
            "generated_at": generated_at,
            "errors": [f"Manifest not found: {manifest_path}"],
            "predicates": {"reliability_gate_passed": False},
        }

    records = load_jsonl(manifest_path)
    manifest_hash = compute_manifest_hash(manifest_path)
    manifest_by_id = {str(record["id"]): record for record in records}
    relabel_ids = {
        str(record["id"]) for record in records if record.get("relabel_required") is True
    }
    round1_rows = load_jsonl(labels_path)
    relabel_rows = load_jsonl(relabel_labels_path) if relabel_labels_path.exists() else []

    round1_errors, round1_by_id, round1_counters = _validate_reliability_rows(
        rows=round1_rows,
        manifest_by_id=manifest_by_id,
        manifest_hash=manifest_hash,
        expected_ids=relabel_ids,
        expected_round="round1",
        allow_extra_ids=True,
    )

    relabel_errors: list[str] = []
    relabel_by_id: dict[str, dict[str, Any]] = {}
    relabel_counters = {
        "stale_manifest_hashes": 0,
        "invalid_label_values": 0,
        "missing_expected_rows": len(relabel_ids),
        "unexpected_rows": 0,
    }
    if relabel_labels_path.exists():
        relabel_errors, relabel_by_id, relabel_counters = _validate_reliability_rows(
            rows=relabel_rows,
            manifest_by_id=manifest_by_id,
            manifest_hash=manifest_hash,
            expected_ids=relabel_ids,
            expected_round="relabel",
        )

    timing_errors: list[str] = []
    for manifest_id in sorted(relabel_ids & set(round1_by_id) & set(relabel_by_id)):
        round1_at = parse_timestamp(round1_by_id[manifest_id].get("labeled_at"))
        relabel_at = parse_timestamp(relabel_by_id[manifest_id].get("labeled_at"))
        if round1_at is None or relabel_at is None:
            continue
        if relabel_at < round1_at + timedelta(days=RELABEL_MIN_DELAY_DAYS):
            timing_errors.append(f"{manifest_id}: relabel is less than 7 days after round one")

    matched_ids = sorted(relabel_ids & set(round1_by_id) & set(relabel_by_id))
    kappa_by_axis: dict[str, dict[str, Any]] = {}
    for axis in sorted(REQUIRED_AXES):
        kappa_by_axis[axis] = cohen_kappa(
            [int(round1_by_id[manifest_id]["labels"][axis]) for manifest_id in matched_ids],
            [int(relabel_by_id[manifest_id]["labels"][axis]) for manifest_id in matched_ids],
        )
    overall_left: list[int] = []
    overall_right: list[int] = []
    for manifest_id in matched_ids:
        for axis in sorted(REQUIRED_AXES):
            overall_left.append(int(round1_by_id[manifest_id]["labels"][axis]))
            overall_right.append(int(relabel_by_id[manifest_id]["labels"][axis]))
    overall = cohen_kappa(overall_left, overall_right)

    stale_count = (
        round1_counters["stale_manifest_hashes"] + relabel_counters["stale_manifest_hashes"]
    )
    invalid_count = (
        round1_counters["invalid_label_values"] + relabel_counters["invalid_label_values"]
    )
    relabel_present = relabel_labels_path.exists() and bool(relabel_rows)
    kappa_by_axis_passes = len(kappa_by_axis) == len(REQUIRED_AXES) and all(
        metric["kappa"] is not None and metric["kappa"] >= KAPPA_THRESHOLD
        for metric in kappa_by_axis.values()
    )
    overall_passes = overall["kappa"] is not None and overall["kappa"] >= KAPPA_THRESHOLD

    predicates = {
        "manifest_exists": True,
        "manifest_record_count_is_200": len(records) == 200,
        "relabel_subset_count_is_40": len(relabel_ids) == EXPECTED_RELABEL_COUNT,
        "round1_relabel_subset_complete": len(round1_by_id) == len(relabel_ids),
        "relabel_rows_present": relabel_present,
        "relabel_count_is_40": len(relabel_by_id) == EXPECTED_RELABEL_COUNT,
        "no_stale_manifest_hashes": stale_count == 0,
        "label_values_valid": invalid_count == 0,
        "relabel_delay_ge_7_days": relabel_present and not timing_errors,
        "kappa_by_axis_ge_0_75": kappa_by_axis_passes,
        "overall_kappa_ge_0_75": overall_passes,
        "reliability_gate_passed": False,
    }

    if (
        not predicates["manifest_record_count_is_200"]
        or not predicates["relabel_subset_count_is_40"]
    ):
        status = "invalid_manifest"
    elif stale_count:
        status = "stale_manifest"
    elif invalid_count:
        status = "invalid_label_values"
    elif not relabel_present or len(relabel_by_id) != EXPECTED_RELABEL_COUNT:
        status = "missing_relabels"
    elif timing_errors:
        status = "relabel_too_early"
    elif not predicates["round1_relabel_subset_complete"]:
        status = "missing_round1_labels"
    elif not kappa_by_axis_passes or not overall_passes:
        status = "reliability_failure"
    else:
        status = "reliability_pass"
        predicates["reliability_gate_passed"] = True

    return {
        "status": status,
        "passed": status == "reliability_pass",
        "generated_at": generated_at,
        "manifest": {
            "path": str(manifest_path),
            "sha256": manifest_hash,
            "record_count": len(records),
            "relabel_required_count": len(relabel_ids),
        },
        "labels": {
            "round1_path": str(labels_path),
            "round1_row_count": len(round1_rows),
            "valid_round1_relabel_rows": len(round1_by_id),
            "relabel_path": str(relabel_labels_path),
            "relabel_row_count": len(relabel_rows),
            "valid_relabel_rows": len(relabel_by_id),
        },
        "metrics": {
            "kappa_threshold": KAPPA_THRESHOLD,
            "kappa_by_axis": kappa_by_axis,
            "overall_kappa": overall,
            "matched_relabel_ids": len(matched_ids),
        },
        "errors": {
            "round1": round1_errors,
            "relabel": relabel_errors,
            "timing": timing_errors,
        },
        "predicates": predicates,
        "downstream": {
            "calibrator_contract_baseline_blocked": status != "reliability_pass",
            "epistemic_score_library_extraction_blocked": status != "reliability_pass",
            "validation_gate_run_blocked": status != "reliability_pass",
        },
        "claim_ceiling": (
            "support_non_authoritative; reliability evidence cannot upgrade public claims "
            "or validate scorer outputs by itself"
        ),
    }


def write_relabel_reliability_markdown(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    predicates = report.get("predicates", {})
    metrics = report.get("metrics", {})
    axis_metrics = metrics.get("kappa_by_axis", {})
    predicate_lines = [f"- `{name}`: `{value}`" for name, value in sorted(predicates.items())]
    axis_lines = [
        f"- `{axis}`: n={metric['n']}, kappa={metric['kappa']}, computable={metric['computable']}"
        for axis, metric in sorted(axis_metrics.items())
    ]
    overall = metrics.get("overall_kappa", {})
    path.write_text(
        "\n".join(
            [
                "---",
                'title: "Epistemic Quality Phase 0 Delayed Relabel Reliability Report V0"',
                f"date: {report['generated_at'][:10]}",
                "request: REQ-20260512-epistemic-quality-infrastructure",
                "cc_task: epistemic-quality-phase0-relabel-reliability-gate",
                "authority_level: support_non_authoritative",
                f"status: {report['status']}",
                "---",
                "",
                "# Epistemic Quality Phase 0 Delayed Relabel Reliability Report V0",
                "",
                f"Status: `{report['status']}`",
                f"Passed: `{report['passed']}`",
                "",
                "## Artifacts",
                "",
                f"- Manifest: `{report['manifest']['path']}`",
                f"- Manifest SHA-256: `{report['manifest']['sha256']}`",
                f"- Round-one labels: `{report['labels']['round1_path']}`",
                f"- Relabel labels: `{report['labels']['relabel_path']}`",
                "",
                "## Kappa",
                "",
                f"- Threshold: `{metrics.get('kappa_threshold')}`",
                *axis_lines,
                (
                    "- `overall`: "
                    f"n={overall.get('n')}, kappa={overall.get('kappa')}, "
                    f"computable={overall.get('computable')}"
                ),
                "",
                "## Predicates",
                "",
                *predicate_lines,
                "",
                "## Downstream",
                "",
                *[
                    f"- `{name}`: `{value}`"
                    for name, value in sorted(report.get("downstream", {}).items())
                ],
                "",
                "## Claim Ceiling",
                "",
                report["claim_ceiling"],
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


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
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--labels", type=Path, default=LABELS)
    parser.add_argument("--freeze", type=Path, default=RELABEL_FREEZE)
    parser.add_argument("--strict", action="store_true", help="Require all 200 labels + freeze")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--reliability-report",
        action="store_true",
        help="Emit the delayed relabel reliability gate report instead of label-entry validation",
    )
    parser.add_argument("--relabel-labels", type=Path, default=RELABEL_LABELS)
    parser.add_argument("--report-json", type=Path, default=None)
    parser.add_argument("--report-md", type=Path, default=None)
    args = parser.parse_args()

    if args.reliability_report:
        report = compute_relabel_reliability_report(
            manifest_path=args.manifest,
            labels_path=args.labels,
            relabel_labels_path=args.relabel_labels,
        )
        if args.report_json:
            args.report_json.parent.mkdir(parents=True, exist_ok=True)
            args.report_json.write_text(
                json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
        if args.report_md:
            write_relabel_reliability_markdown(args.report_md, report)
        if args.json or not args.report_json:
            print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True))
        else:
            print(f"wrote reliability JSON report to {args.report_json}")
            if args.report_md:
                print(f"wrote reliability Markdown report to {args.report_md}")
            print(f"status={report['status']}")
        return 0 if report["passed"] else 1

    ok, errors, warnings = validate(
        strict=args.strict,
        manifest_path=args.manifest,
        labels_path=args.labels,
        freeze_path=args.freeze,
    )
    label_count = len(load_jsonl(args.labels)) if args.labels.exists() else 0

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
