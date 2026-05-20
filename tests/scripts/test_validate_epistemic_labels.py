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
