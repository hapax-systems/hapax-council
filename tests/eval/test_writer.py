"""Tests for EvalReceiptWriter integration and end-to-end receipt generation."""

from __future__ import annotations

import os
import time

import pytest

from hapax.eval.writer import EvalReceiptWriter, ReceiptWriteError
from shared.eval_receipt import ContaminationStatus, EvalReceiptV1, FreshnessStatus


class MockScorer:
    """Mock scorer to test result extraction from objects."""

    def __init__(self, score: float) -> None:
        self.score = score


def test_writer_produces_valid_receipt(tmp_path) -> None:
    """Integration test: EvalReceiptWriter produces a fully-validated, persistent receipt."""
    ledger_dir = tmp_path / "ledger"
    samples_dir = ledger_dir / "samples"
    samples_dir.mkdir(parents=True)

    # 1. Create mock artifacts on disk with # comment prefixes
    artifacts = {
        "model_id": str(samples_dir / "model.bin"),
        "route": str(samples_dir / "route.json"),
        "config": str(samples_dir / "config.yaml"),
        "prompt": str(samples_dir / "prompt.txt"),
        "scorer": str(samples_dir / "scorer.py"),
        "dataset": str(samples_dir / "dataset.jsonl"),
    }

    for path in artifacts.values():
        with open(path, "w", encoding="utf-8") as f:
            f.write("# mock content\n")

    # 2. Setup metadata
    metadata = {
        "run_id": "test-run-123",
        "authority_case": "CASE-TEST-123",
        "task_ref": "task-test-123",
        "contamination_status": ContaminationStatus.CLEAN,
        "freshness_status": FreshnessStatus.FRESH,
        "claim_ceilings": ["Mock passes all unit tests"],
        "what_this_does_not_prove": ["No guarantees about visual consistency"],
        "replayable": True,
    }

    # 3. Use context manager and scorer
    mock_scorer = MockScorer(0.88)
    with EvalReceiptWriter(ledger_dir=str(ledger_dir)) as writer:
        # Mock some execution time
        time.sleep(0.05)

    # 4. Write receipt to custom path
    output_path = str(samples_dir / "sample_receipt_v1.json")
    receipt = writer.write(mock_scorer, artifacts, metadata, output_path=output_path)

    # 5. Verify the returned receipt object
    assert isinstance(receipt, EvalReceiptV1)
    assert receipt.normalized_score == 0.88
    assert receipt.replayable is True
    assert receipt.run_id == "test-run-123"
    assert receipt.model_id_hash is not None
    assert receipt.model_id_hash.startswith("sha256:")

    # 6. Verify resources are logged
    res_obs = receipt.resource_observations
    assert "wall_time_seconds" in res_obs
    assert res_obs["wall_time_seconds"] > 0
    assert "peak_memory_mb" in res_obs
    assert res_obs["peak_memory_mb"] > 0

    # 7. Verify the written JSON file parses successfully
    assert os.path.exists(output_path)
    with open(output_path, encoding="utf-8") as f:
        data = f.read()

    parsed = EvalReceiptV1.model_validate_json(data)
    assert parsed == receipt


def test_writer_parses_string_score(tmp_path) -> None:
    """Writer must parse float-compatible numeric strings successfully."""
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    model_file = ledger_dir / "model.bin"
    model_file.write_text("# mock\n")
    artifacts = {"model_id": str(model_file)}

    metadata = {
        "run_id": "test-run-str-score",
        "authority_case": "CASE-STR-SCORE",
        "task_ref": "task-str-score",
        "contamination_status": ContaminationStatus.CLEAN,
        "freshness_status": FreshnessStatus.FRESH,
        "claim_ceilings": ["test"],
        "what_this_does_not_prove": ["test"],
    }

    writer = EvalReceiptWriter(ledger_dir=str(ledger_dir))
    receipt = writer.write("0.75", artifacts, metadata)
    assert receipt.normalized_score == 0.75


def test_writer_raises_error_on_missing_artifact(tmp_path) -> None:
    """Writer must raise ReceiptWriteError if any hash cannot be computed (file missing)."""
    ledger_dir = tmp_path / "ledger"
    artifacts = {"model_id": str(tmp_path / "non_existent_file.bin")}

    metadata = {
        "run_id": "test-run-error",
        "authority_case": "CASE-ERROR",
        "task_ref": "task-error",
        "contamination_status": ContaminationStatus.CLEAN,
        "freshness_status": FreshnessStatus.FRESH,
        "claim_ceilings": ["test"],
        "what_this_does_not_prove": ["test"],
    }

    writer = EvalReceiptWriter(ledger_dir=str(ledger_dir))
    with pytest.raises(ReceiptWriteError, match="Failed to compute hash"):
        writer.write(0.5, artifacts, metadata)


def test_writer_raises_error_on_invalid_score(tmp_path) -> None:
    """Writer must raise ReceiptWriteError if normalized_score cannot be extracted or is out of bounds."""
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()

    # Create valid mock file for hashing
    model_file = ledger_dir / "model.bin"
    model_file.write_text("# mock\n")
    artifacts = {"model_id": str(model_file)}

    metadata = {
        "run_id": "test-run-score-error",
        "authority_case": "CASE-SCORE-ERROR",
        "task_ref": "task-score-error",
        "contamination_status": ContaminationStatus.CLEAN,
        "freshness_status": FreshnessStatus.FRESH,
        "claim_ceilings": ["test"],
        "what_this_does_not_prove": ["test"],
    }

    writer = EvalReceiptWriter(ledger_dir=str(ledger_dir))

    # Missing score entirely
    with pytest.raises(ReceiptWriteError, match="Could not extract normalized_score"):
        writer.write(None, artifacts, metadata)

    # Score is not float-compatible (in dict)
    with pytest.raises(ReceiptWriteError, match="normalized_score must be a float"):
        writer.write({"score": "not-a-number"}, artifacts, metadata)

    # Score is out of bounds (Pydantic validation error wrapped in ReceiptWriteError)
    with pytest.raises(ReceiptWriteError, match="validation failed"):
        writer.write(1.5, artifacts, metadata)
