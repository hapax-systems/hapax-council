#!/usr/bin/env python3
"""Run the Phase 0 epistemic quality validation gate.

Orchestrates the full validation pipeline: label validation, relabel
reliability check, scorer correlation, and gate report generation.
Reports exactly whether the Phase 0 hard gate passed or failed.

Usage:
    uv run python scripts/run-epistemic-phase0-gate.py
    uv run python scripts/run-epistemic-phase0-gate.py --json
    uv run python scripts/run-epistemic-phase0-gate.py --check-readiness
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

DATASET_DIR = (
    Path.home() / "Documents/Personal/20-projects/hapax-research/datasets/epistemic-quality"
)
MANIFEST = DATASET_DIR / "phase0-golden-dataset-v0-curated.jsonl"
LABELS = DATASET_DIR / "phase0-human-labels-round1-v0.jsonl"
RELABEL_REPORT = DATASET_DIR / "phase0-relabel-reliability-report-v0.json"
SCORES = DATASET_DIR / "phase0-scorer-outputs-v0.jsonl"
GATE_REPORT_JSON = DATASET_DIR / "phase0-gate-report-v0.json"
GATE_REPORT_MD = DATASET_DIR / "phase0-gate-report-v0.md"

REQUIRED_LABEL_COUNT = 200
REQUIRED_RELABEL_COUNT = 40
REQUIRED_KAPPA = 0.75
REQUIRED_RELABEL_DELAY_DAYS = 7
REQUIRED_AXES = frozenset(
    {
        "claim_evidence_alignment",
        "hedge_calibration",
        "quantifier_precision",
        "source_grounding",
    }
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def check_readiness() -> dict:
    """Check whether all inputs exist for the gate run."""
    checks = {}

    checks["manifest"] = {
        "path": str(MANIFEST),
        "exists": MANIFEST.exists(),
        "hash": _sha256(MANIFEST) if MANIFEST.exists() else None,
        "count": len(_load_jsonl(MANIFEST)) if MANIFEST.exists() else 0,
    }

    labels = _load_jsonl(LABELS)
    checks["labels"] = {
        "path": str(LABELS),
        "exists": LABELS.exists(),
        "hash": _sha256(LABELS) if LABELS.exists() else None,
        "count": len(labels),
        "required": REQUIRED_LABEL_COUNT,
        "ready": len(labels) >= REQUIRED_LABEL_COUNT,
    }

    checks["scores"] = {
        "path": str(SCORES),
        "exists": SCORES.exists(),
        "count": len(_load_jsonl(SCORES)) if SCORES.exists() else 0,
        "ready": SCORES.exists() and len(_load_jsonl(SCORES)) > 0,
    }

    checks["relabel_report"] = {
        "path": str(RELABEL_REPORT),
        "exists": RELABEL_REPORT.exists(),
        "ready": RELABEL_REPORT.exists(),
    }

    all_ready = all(c.get("ready", c.get("exists", False)) for c in checks.values())
    checks["gate_runnable"] = all_ready

    return checks


def run_gate() -> dict:
    """Run the full Phase 0 validation gate. Returns the gate report."""
    readiness = check_readiness()
    if not readiness["gate_runnable"]:
        blockers = [
            k
            for k, v in readiness.items()
            if k != "gate_runnable" and not v.get("ready", v.get("exists", False))
        ]
        return {
            "gate_passed": False,
            "gate_status": "not_runnable",
            "blockers": blockers,
            "readiness": readiness,
            "run_at": datetime.now(UTC).isoformat(),
        }

    from scripts.epistemic_quality_dataset import (
        validate_gate_inputs,
    )

    manifest_records = _load_jsonl(MANIFEST)
    label_rows = _load_jsonl(LABELS)
    score_rows = _load_jsonl(SCORES)
    relabel_data = json.loads(RELABEL_REPORT.read_text()) if RELABEL_REPORT.exists() else None

    report = validate_gate_inputs(
        manifest_records=manifest_records,
        label_rows=label_rows,
        score_rows=score_rows,
        relabel_data=relabel_data,
    )

    report["readiness"] = readiness
    report["run_at"] = datetime.now(UTC).isoformat()
    report["input_hashes"] = {
        "manifest": _sha256(MANIFEST),
        "labels": _sha256(LABELS),
        "scores": _sha256(SCORES) if SCORES.exists() else None,
        "relabel_report": _sha256(RELABEL_REPORT) if RELABEL_REPORT.exists() else None,
    }

    GATE_REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    GATE_REPORT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    _write_markdown_report(report)

    return report


def _write_markdown_report(report: dict) -> None:
    """Write a human-readable gate report."""
    lines = [
        "# Epistemic Quality Phase 0 Gate Report",
        "",
        f"**Run at:** {report.get('run_at', 'unknown')}",
        f"**Gate passed:** {report.get('gate_passed', False)}",
        f"**Gate status:** {report.get('gate_status', 'unknown')}",
        "",
    ]

    if report.get("blockers"):
        lines.append("## Blockers")
        for b in report["blockers"]:
            lines.append(f"- {b}")
        lines.append("")

    readiness = report.get("readiness", {})
    lines.append("## Input Readiness")
    for key, val in readiness.items():
        if key == "gate_runnable":
            continue
        ready = val.get("ready", val.get("exists", False))
        count = val.get("count", "")
        count_str = f" ({count} rows)" if count else ""
        lines.append(f"- **{key}**: {'ready' if ready else 'NOT READY'}{count_str}")
    lines.append("")

    hashes = report.get("input_hashes", {})
    if hashes:
        lines.append("## Input Hashes")
        for key, val in hashes.items():
            lines.append(f"- {key}: `{val[:16]}...`" if val else f"- {key}: missing")
        lines.append("")

    GATE_REPORT_MD.write_text("\n".join(lines))


def validate_gate_inputs(
    *,
    manifest_records: list[dict],
    label_rows: list[dict],
    score_rows: list[dict],
    relabel_data: dict | None,
) -> dict:
    """Validate gate inputs and return structured report.

    Fallback implementation when the full harness import is unavailable.
    """
    errors: list[str] = []
    metrics: dict = {}

    if len(label_rows) < REQUIRED_LABEL_COUNT:
        errors.append(f"Only {len(label_rows)}/{REQUIRED_LABEL_COUNT} labels present")
    metrics["label_count"] = len(label_rows)

    if not score_rows:
        errors.append("No scorer outputs present")
    metrics["score_count"] = len(score_rows)

    if relabel_data:
        kappa = relabel_data.get("overall_kappa", 0)
        metrics["relabel_kappa"] = kappa
        if kappa < REQUIRED_KAPPA:
            errors.append(f"Relabel kappa {kappa:.3f} < {REQUIRED_KAPPA}")
    else:
        errors.append("No relabel reliability report")

    return {
        "gate_passed": len(errors) == 0,
        "gate_status": "passed" if not errors else "failed",
        "errors": errors,
        "metrics": metrics,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 0 epistemic quality gate")
    parser.add_argument("--check-readiness", action="store_true", help="Check input readiness only")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if args.check_readiness:
        readiness = check_readiness()
        if args.json:
            print(json.dumps(readiness, indent=2))
        else:
            print("\n=== Phase 0 Gate Readiness ===")
            for key, val in readiness.items():
                if key == "gate_runnable":
                    continue
                ready = val.get("ready", val.get("exists", False))
                count = val.get("count")
                print(
                    f"  {'✓' if ready else '✗'} {key}: {count or ''} {'ready' if ready else 'NOT READY'}"
                )
            print(f"\n{'✓ Gate runnable' if readiness['gate_runnable'] else '✗ Gate NOT runnable'}")
        return 0 if readiness["gate_runnable"] else 1

    report = run_gate()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"\n=== Phase 0 Gate: {'PASSED' if report.get('gate_passed') else 'FAILED'} ===")
        if report.get("blockers"):
            print(f"Blockers: {', '.join(report['blockers'])}")
        if report.get("errors"):
            for e in report["errors"]:
                print(f"  ✗ {e}")
        print(f"\nReports: {GATE_REPORT_JSON}")

    return 0 if report.get("gate_passed") else 1


if __name__ == "__main__":
    sys.exit(main())
