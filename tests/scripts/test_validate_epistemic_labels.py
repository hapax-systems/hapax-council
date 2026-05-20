"""Tests for validate-epistemic-labels.py — Phase 0 label validation harness."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "validate-epistemic-labels.py"
_spec = importlib.util.spec_from_file_location("validate_epistemic_labels", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["validate_epistemic_labels"] = _mod
_spec.loader.exec_module(_mod)
load_jsonl = _mod.load_jsonl
validate = _mod.validate
compute_relabel_reliability_report = _mod.compute_relabel_reliability_report
write_relabel_reliability_markdown = _mod.write_relabel_reliability_markdown


def _manifest_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_manifest(tmp_path: Path, n: int = 200, relabel_count: int = 40) -> Path:
    path = tmp_path / "manifest.jsonl"
    rows = []
    for i in range(n):
        rows.append(
            json.dumps(
                {
                    "id": f"eqi-v0-{i:03d}",
                    "excerpt": f"Excerpt {i}",
                    "excerpt_hash": hashlib.sha256(f"Excerpt {i}".encode()).hexdigest(),
                    "source_ref": f"vault:source-{i}",
                    "label_status": "unlabeled",
                    "labels": {},
                    "relabel_required": i < relabel_count,
                    "domain_partition": "technical",
                    "tier": "A",
                }
            )
        )
    path.write_text("\n".join(rows) + "\n")
    return path


def _make_label(
    record_id: str,
    manifest_hash: str,
    *,
    source_ref: str = "vault:source",
    origin: str = "operator",
    labels: dict | None = None,
    ts: str | None = None,
) -> dict:
    return {
        "id": record_id,
        "manifest_hash": manifest_hash,
        "source_ref": source_ref,
        "source_text_hash": hashlib.sha256(b"text").hexdigest(),
        "label_round": "round1",
        "labeler": "operator",
        "label_origin": origin,
        "labeled_at": ts or datetime.now(UTC).isoformat(),
        "provenance": "operator_label_entry",
        "labels": labels
        or {
            "claim_evidence_alignment": 3,
            "hedge_calibration": 4,
            "quantifier_precision": 4,
            "source_grounding": 5,
        },
    }


def _write_labels(path: Path, labels: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in labels) + "\n")


def _relabel_rows(
    *,
    manifest_hash: str,
    count: int = 40,
    round_name: str = "round1",
    ts: datetime | None = None,
    label_value: int = 3,
    source_prefix: str = "vault:source",
) -> list[dict]:
    label_time = ts or datetime.now(UTC)
    rows = [
        _make_label(
            f"eqi-v0-{i:03d}",
            manifest_hash,
            source_ref=f"{source_prefix}-{i}",
            labels={
                "claim_evidence_alignment": label_value,
                "hedge_calibration": label_value,
                "quantifier_precision": label_value,
                "source_grounding": label_value,
            },
            ts=label_time.isoformat(),
        )
        | {"label_round": round_name}
        for i in range(count)
    ]
    for i, row in enumerate(rows):
        row["source_text_hash"] = hashlib.sha256(f"Excerpt {i}".encode()).hexdigest()
    return rows


class TestValidLabel:
    def test_full_200_labels_pass(self, tmp_path):
        manifest = _make_manifest(tmp_path)
        mhash = _manifest_hash(manifest)
        labels_path = tmp_path / "labels.jsonl"
        rows = [
            _make_label(f"eqi-v0-{i:03d}", mhash, source_ref=f"vault:source-{i}")
            for i in range(200)
        ]
        _write_labels(labels_path, rows)

        ok, errors, warnings = validate(
            manifest_path=manifest,
            labels_path=labels_path,
            freeze_path=tmp_path / "freeze.json",
        )
        assert ok, errors

    def test_partial_labels_pass_non_strict(self, tmp_path):
        manifest = _make_manifest(tmp_path)
        mhash = _manifest_hash(manifest)
        labels_path = tmp_path / "labels.jsonl"
        rows = [
            _make_label(f"eqi-v0-{i:03d}", mhash, source_ref=f"vault:source-{i}") for i in range(10)
        ]
        _write_labels(labels_path, rows)

        ok, errors, warnings = validate(
            manifest_path=manifest,
            labels_path=labels_path,
            freeze_path=tmp_path / "freeze.json",
        )
        assert ok
        assert any("190 manifest records still unlabeled" in w for w in warnings)

    def test_partial_labels_fail_strict(self, tmp_path):
        manifest = _make_manifest(tmp_path)
        mhash = _manifest_hash(manifest)
        labels_path = tmp_path / "labels.jsonl"
        rows = [
            _make_label(f"eqi-v0-{i:03d}", mhash, source_ref=f"vault:source-{i}") for i in range(10)
        ]
        _write_labels(labels_path, rows)

        ok, errors, _ = validate(
            strict=True,
            manifest_path=manifest,
            labels_path=labels_path,
            freeze_path=tmp_path / "freeze.json",
        )
        assert not ok
        assert any("unlabeled" in e for e in errors)


class TestInvalidLabels:
    def test_duplicate_id_fails(self, tmp_path):
        manifest = _make_manifest(tmp_path)
        mhash = _manifest_hash(manifest)
        labels_path = tmp_path / "labels.jsonl"
        rows = [
            _make_label("eqi-v0-000", mhash, source_ref="vault:source-0"),
            _make_label("eqi-v0-000", mhash, source_ref="vault:source-0"),
        ]
        _write_labels(labels_path, rows)

        ok, errors, _ = validate(
            manifest_path=manifest,
            labels_path=labels_path,
            freeze_path=tmp_path / "freeze.json",
        )
        assert not ok
        assert any("duplicate" in e.lower() for e in errors)

    def test_invalid_scale_value_fails(self, tmp_path):
        manifest = _make_manifest(tmp_path)
        mhash = _manifest_hash(manifest)
        labels_path = tmp_path / "labels.jsonl"
        bad = _make_label("eqi-v0-000", mhash, source_ref="vault:source-0")
        bad["labels"]["claim_evidence_alignment"] = 7
        _write_labels(labels_path, [bad])

        ok, errors, _ = validate(
            manifest_path=manifest,
            labels_path=labels_path,
            freeze_path=tmp_path / "freeze.json",
        )
        assert not ok
        assert any("not in 1-5" in e for e in errors)

    def test_missing_axis_fails(self, tmp_path):
        manifest = _make_manifest(tmp_path)
        mhash = _manifest_hash(manifest)
        labels_path = tmp_path / "labels.jsonl"
        row = _make_label("eqi-v0-000", mhash, source_ref="vault:source-0")
        del row["labels"]["hedge_calibration"]
        _write_labels(labels_path, [row])

        ok, errors, _ = validate(
            manifest_path=manifest,
            labels_path=labels_path,
            freeze_path=tmp_path / "freeze.json",
        )
        assert not ok
        assert any("missing axes" in e for e in errors)

    def test_model_origin_fails(self, tmp_path):
        manifest = _make_manifest(tmp_path)
        mhash = _manifest_hash(manifest)
        labels_path = tmp_path / "labels.jsonl"
        row = _make_label("eqi-v0-000", mhash, source_ref="vault:source-0", origin="claude")
        _write_labels(labels_path, [row])

        ok, errors, _ = validate(
            manifest_path=manifest,
            labels_path=labels_path,
            freeze_path=tmp_path / "freeze.json",
        )
        assert not ok
        assert any("model-generated" in e for e in errors)

    def test_stale_hash_fails(self, tmp_path):
        manifest = _make_manifest(tmp_path)
        labels_path = tmp_path / "labels.jsonl"
        row = _make_label("eqi-v0-000", "stale_hash_abc", source_ref="vault:source-0")
        _write_labels(labels_path, [row])

        ok, errors, _ = validate(
            manifest_path=manifest,
            labels_path=labels_path,
            freeze_path=tmp_path / "freeze.json",
        )
        assert not ok
        assert any("stale manifest hash" in e for e in errors)

    def test_missing_source_ref_fails(self, tmp_path):
        manifest = _make_manifest(tmp_path)
        mhash = _manifest_hash(manifest)
        labels_path = tmp_path / "labels.jsonl"
        row = _make_label("eqi-v0-000", mhash, source_ref="")
        _write_labels(labels_path, [row])

        ok, errors, _ = validate(
            manifest_path=manifest,
            labels_path=labels_path,
            freeze_path=tmp_path / "freeze.json",
        )
        assert not ok
        assert any("source-required" in e for e in errors)


class TestRelabelFreeze:
    def test_valid_freeze_passes(self, tmp_path):
        manifest = _make_manifest(tmp_path)
        mhash = _manifest_hash(manifest)
        labels_path = tmp_path / "labels.jsonl"
        ts = datetime.now(UTC)
        rows = [
            _make_label(
                f"eqi-v0-{i:03d}",
                mhash,
                source_ref=f"vault:source-{i}",
                ts=ts.isoformat(),
            )
            for i in range(200)
        ]
        _write_labels(labels_path, rows)

        freeze_path = tmp_path / "freeze.json"
        freeze_path.write_text(
            json.dumps(
                {
                    "relabel_ids": [f"eqi-v0-{i:03d}" for i in range(40)],
                    "relabel_due_date": (ts + timedelta(days=8)).isoformat(),
                    "frozen_at": ts.isoformat(),
                }
            )
        )

        ok, errors, _ = validate(
            manifest_path=manifest,
            labels_path=labels_path,
            freeze_path=freeze_path,
        )
        assert ok, errors

    def test_due_date_too_soon_fails(self, tmp_path):
        manifest = _make_manifest(tmp_path)
        mhash = _manifest_hash(manifest)
        labels_path = tmp_path / "labels.jsonl"
        ts = datetime.now(UTC)
        rows = [
            _make_label(
                f"eqi-v0-{i:03d}",
                mhash,
                source_ref=f"vault:source-{i}",
                ts=ts.isoformat(),
            )
            for i in range(200)
        ]
        _write_labels(labels_path, rows)

        freeze_path = tmp_path / "freeze.json"
        freeze_path.write_text(
            json.dumps(
                {
                    "relabel_ids": [f"eqi-v0-{i:03d}" for i in range(40)],
                    "relabel_due_date": (ts + timedelta(days=3)).isoformat(),
                    "frozen_at": ts.isoformat(),
                }
            )
        )

        ok, errors, _ = validate(
            manifest_path=manifest,
            labels_path=labels_path,
            freeze_path=freeze_path,
        )
        assert not ok
        assert any("< 7 days" in e for e in errors)

    def test_mismatched_ids_fails(self, tmp_path):
        manifest = _make_manifest(tmp_path)
        mhash = _manifest_hash(manifest)
        labels_path = tmp_path / "labels.jsonl"
        rows = [
            _make_label(f"eqi-v0-{i:03d}", mhash, source_ref=f"vault:source-{i}")
            for i in range(200)
        ]
        _write_labels(labels_path, rows)

        freeze_path = tmp_path / "freeze.json"
        freeze_path.write_text(
            json.dumps(
                {
                    "relabel_ids": ["eqi-v0-000", "eqi-v0-001"],
                    "relabel_due_date": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
                }
            )
        )

        ok, errors, _ = validate(
            manifest_path=manifest,
            labels_path=labels_path,
            freeze_path=freeze_path,
        )
        assert not ok
        assert any("mismatch" in e.lower() for e in errors)


class TestRelabelReliabilityReport:
    def test_missing_relabels_report_is_fail_closed(self, tmp_path: Path) -> None:
        manifest = _make_manifest(tmp_path)
        manifest_hash = _manifest_hash(manifest)
        labels_path = tmp_path / "round1.jsonl"
        _write_labels(labels_path, _relabel_rows(manifest_hash=manifest_hash))

        report = compute_relabel_reliability_report(
            manifest_path=manifest,
            labels_path=labels_path,
            relabel_labels_path=tmp_path / "missing-relabels.jsonl",
        )

        assert report["status"] == "missing_relabels"
        assert report["passed"] is False
        assert report["predicates"]["relabel_rows_present"] is False
        assert report["predicates"]["reliability_gate_passed"] is False

    def test_stale_manifest_status_is_distinct(self, tmp_path: Path) -> None:
        manifest = _make_manifest(tmp_path)
        manifest_hash = _manifest_hash(manifest)
        labels_path = tmp_path / "round1.jsonl"
        relabel_path = tmp_path / "relabels.jsonl"
        ts = datetime.now(UTC)
        _write_labels(labels_path, _relabel_rows(manifest_hash=manifest_hash, ts=ts))
        stale_relabels = _relabel_rows(
            manifest_hash="stale-hash",
            round_name="relabel",
            ts=ts + timedelta(days=8),
        )
        _write_labels(relabel_path, stale_relabels)

        report = compute_relabel_reliability_report(
            manifest_path=manifest,
            labels_path=labels_path,
            relabel_labels_path=relabel_path,
        )

        assert report["status"] == "stale_manifest"
        assert report["predicates"]["no_stale_manifest_hashes"] is False

    def test_invalid_label_values_status_is_distinct(self, tmp_path: Path) -> None:
        manifest = _make_manifest(tmp_path)
        manifest_hash = _manifest_hash(manifest)
        labels_path = tmp_path / "round1.jsonl"
        relabel_path = tmp_path / "relabels.jsonl"
        ts = datetime.now(UTC)
        _write_labels(labels_path, _relabel_rows(manifest_hash=manifest_hash, ts=ts))
        relabels = _relabel_rows(
            manifest_hash=manifest_hash,
            round_name="relabel",
            ts=ts + timedelta(days=8),
        )
        relabels[0]["labels"]["source_grounding"] = 9
        _write_labels(relabel_path, relabels)

        report = compute_relabel_reliability_report(
            manifest_path=manifest,
            labels_path=labels_path,
            relabel_labels_path=relabel_path,
        )

        assert report["status"] == "invalid_label_values"
        assert report["predicates"]["label_values_valid"] is False

    def test_reliability_failure_status_is_distinct(self, tmp_path: Path) -> None:
        manifest = _make_manifest(tmp_path)
        manifest_hash = _manifest_hash(manifest)
        labels_path = tmp_path / "round1.jsonl"
        relabel_path = tmp_path / "relabels.jsonl"
        ts = datetime.now(UTC)
        _write_labels(
            labels_path,
            _relabel_rows(manifest_hash=manifest_hash, ts=ts, label_value=1),
        )
        _write_labels(
            relabel_path,
            _relabel_rows(
                manifest_hash=manifest_hash,
                round_name="relabel",
                ts=ts + timedelta(days=8),
                label_value=5,
            ),
        )

        report = compute_relabel_reliability_report(
            manifest_path=manifest,
            labels_path=labels_path,
            relabel_labels_path=relabel_path,
        )

        assert report["status"] == "reliability_failure"
        assert report["predicates"]["kappa_by_axis_ge_0_75"] is False
        assert report["metrics"]["overall_kappa"]["kappa"] < 0.75

    def test_reliability_pass_status_and_markdown(self, tmp_path: Path) -> None:
        manifest = _make_manifest(tmp_path)
        manifest_hash = _manifest_hash(manifest)
        labels_path = tmp_path / "round1.jsonl"
        relabel_path = tmp_path / "relabels.jsonl"
        report_md = tmp_path / "report.md"
        ts = datetime.now(UTC)
        round1 = _relabel_rows(manifest_hash=manifest_hash, ts=ts)
        _write_labels(labels_path, round1)
        relabels = [row | {"label_round": "relabel"} for row in round1]
        for row in relabels:
            row["labeled_at"] = (ts + timedelta(days=8)).isoformat()
        _write_labels(relabel_path, relabels)

        report = compute_relabel_reliability_report(
            manifest_path=manifest,
            labels_path=labels_path,
            relabel_labels_path=relabel_path,
        )
        write_relabel_reliability_markdown(report_md, report)

        assert report["status"] == "reliability_pass"
        assert report["passed"] is True
        assert report["predicates"]["reliability_gate_passed"] is True
        assert "`reliability_gate_passed`: `True`" in report_md.read_text()
