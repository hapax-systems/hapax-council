"""Tests for the Phase 0 epistemic quality validation gate runner."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run-epistemic-phase0-gate.py"
_spec = importlib.util.spec_from_file_location("run_epistemic_phase0_gate", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["run_epistemic_phase0_gate"] = _mod
_spec.loader.exec_module(_mod)
check_readiness = _mod.check_readiness
validate_gate_inputs = _mod.validate_gate_inputs


def _make_manifest(tmp_path: Path, n: int = 200) -> Path:
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
                }
            )
        )
    path.write_text("\n".join(rows) + "\n")
    return path


def _make_labels(tmp_path: Path, n: int = 200) -> Path:
    path = tmp_path / "labels.jsonl"
    rows = []
    for i in range(n):
        rows.append(
            json.dumps(
                {
                    "id": f"eqi-v0-{i:03d}",
                    "labels": {
                        "claim_evidence_alignment": 3,
                        "hedge_calibration": 4,
                        "quantifier_precision": 4,
                        "source_grounding": 5,
                    },
                    "labeler": "operator",
                    "label_origin": "operator",
                }
            )
        )
    path.write_text("\n".join(rows) + "\n")
    return path


def _make_scores(tmp_path: Path, n: int = 200) -> Path:
    path = tmp_path / "scores.jsonl"
    rows = []
    for i in range(n):
        rows.append(json.dumps({"id": f"eqi-v0-{i:03d}", "score": 0.8}))
    path.write_text("\n".join(rows) + "\n")
    return path


class TestReadiness:
    def test_missing_labels_not_ready(self, tmp_path, monkeypatch):
        manifest = _make_manifest(tmp_path)
        labels = tmp_path / "labels.jsonl"
        labels.write_text("")
        monkeypatch.setattr(_mod, "MANIFEST", manifest)
        monkeypatch.setattr(_mod, "LABELS", labels)
        monkeypatch.setattr(_mod, "SCORES", tmp_path / "scores.jsonl")
        monkeypatch.setattr(_mod, "RELABEL_REPORT", tmp_path / "relabel.json")

        result = check_readiness()
        assert not result["gate_runnable"]
        assert not result["labels"]["ready"]

    def test_all_present_ready(self, tmp_path, monkeypatch):
        manifest = _make_manifest(tmp_path)
        labels = _make_labels(tmp_path)
        scores = _make_scores(tmp_path)
        relabel = tmp_path / "relabel.json"
        relabel.write_text(json.dumps({"overall_kappa": 0.85}))
        monkeypatch.setattr(_mod, "MANIFEST", manifest)
        monkeypatch.setattr(_mod, "LABELS", labels)
        monkeypatch.setattr(_mod, "SCORES", scores)
        monkeypatch.setattr(_mod, "RELABEL_REPORT", relabel)

        result = check_readiness()
        assert result["gate_runnable"]


class TestValidateGateInputs:
    def test_passes_with_complete_inputs(self):
        manifest = [{"id": f"eqi-v0-{i:03d}"} for i in range(200)]
        labels = [{"id": f"eqi-v0-{i:03d}", "labels": {}} for i in range(200)]
        scores = [{"id": f"eqi-v0-{i:03d}", "score": 0.8} for i in range(200)]
        relabel = {"overall_kappa": 0.80}

        report = validate_gate_inputs(
            manifest_records=manifest,
            label_rows=labels,
            score_rows=scores,
            relabel_data=relabel,
        )
        assert report["gate_passed"]
        assert report["gate_status"] == "passed"

    def test_fails_with_insufficient_labels(self):
        report = validate_gate_inputs(
            manifest_records=[{"id": f"eqi-v0-{i:03d}"} for i in range(200)],
            label_rows=[{"id": "eqi-v0-000"}] * 10,
            score_rows=[{"id": "eqi-v0-000"}],
            relabel_data={"overall_kappa": 0.80},
        )
        assert not report["gate_passed"]
        assert any("labels" in e.lower() for e in report["errors"])

    def test_fails_with_low_kappa(self):
        report = validate_gate_inputs(
            manifest_records=[{"id": f"eqi-v0-{i:03d}"} for i in range(200)],
            label_rows=[{"id": f"eqi-v0-{i:03d}"} for i in range(200)],
            score_rows=[{"id": f"eqi-v0-{i:03d}"} for i in range(200)],
            relabel_data={"overall_kappa": 0.50},
        )
        assert not report["gate_passed"]
        assert any("kappa" in e.lower() for e in report["errors"])

    def test_fails_with_no_scores(self):
        report = validate_gate_inputs(
            manifest_records=[{"id": f"eqi-v0-{i:03d}"} for i in range(200)],
            label_rows=[{"id": f"eqi-v0-{i:03d}"} for i in range(200)],
            score_rows=[],
            relabel_data={"overall_kappa": 0.80},
        )
        assert not report["gate_passed"]
        assert any("scorer" in e.lower() for e in report["errors"])

    def test_fails_with_no_relabel(self):
        report = validate_gate_inputs(
            manifest_records=[{"id": f"eqi-v0-{i:03d}"} for i in range(200)],
            label_rows=[{"id": f"eqi-v0-{i:03d}"} for i in range(200)],
            score_rows=[{"id": f"eqi-v0-{i:03d}"} for i in range(200)],
            relabel_data=None,
        )
        assert not report["gate_passed"]
        assert any("relabel" in e.lower() for e in report["errors"])
