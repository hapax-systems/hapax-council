"""Tests for EvalReceiptV1 schema."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from shared.eval_receipt import ContaminationStatus, EvalReceiptV1, FreshnessStatus


def _valid_kwargs() -> dict:
    return {
        "run_id": "run-001",
        "authority_case": "CASE-TEST-001",
        "task_ref": "task-001",
        "normalized_score": 0.85,
        "contamination_status": ContaminationStatus.CLEAN,
        "freshness_status": FreshnessStatus.FRESH,
        "claim_ceilings": ["ceiling-1"],
        "what_this_does_not_prove": ["limitation-1"],
    }


def test_valid_receipt_round_trips_json() -> None:
    receipt = EvalReceiptV1(**_valid_kwargs())
    dumped = receipt.model_dump_json()
    restored = EvalReceiptV1.model_validate_json(dumped)
    assert restored == receipt
    assert restored.schema_version == "EvalReceiptV1"


def test_schema_version_pinned() -> None:
    receipt = EvalReceiptV1(**_valid_kwargs())
    assert receipt.schema_version == "EvalReceiptV1"
    payload = json.loads(receipt.model_dump_json())
    assert payload["schema_version"] == "EvalReceiptV1"


def test_replayable_requires_artifact_refs() -> None:
    kwargs = _valid_kwargs()
    kwargs["replayable"] = True
    kwargs["raw_artifact_refs"] = []
    kwargs.update(
        {
            "model_id_hash": "h1",
            "route_hash": "h2",
            "config_hash": "h3",
            "prompt_hash": "h4",
            "scorer_hash": "h5",
            "dataset_hash": "h6",
        }
    )
    with pytest.raises(ValidationError, match="raw_artifact_refs"):
        EvalReceiptV1(**kwargs)


def test_replayable_requires_all_hashes() -> None:
    kwargs = _valid_kwargs()
    kwargs["replayable"] = True
    kwargs["raw_artifact_refs"] = ["artifact-1"]
    kwargs["model_id_hash"] = "h1"
    with pytest.raises(ValidationError, match="missing"):
        EvalReceiptV1(**kwargs)


def test_replayable_with_all_fields_succeeds() -> None:
    kwargs = _valid_kwargs()
    kwargs["replayable"] = True
    kwargs["raw_artifact_refs"] = ["artifact-1"]
    kwargs.update(
        {
            "model_id_hash": "h1",
            "route_hash": "h2",
            "config_hash": "h3",
            "prompt_hash": "h4",
            "scorer_hash": "h5",
            "dataset_hash": "h6",
        }
    )
    receipt = EvalReceiptV1(**kwargs)
    assert receipt.replayable is True


def test_claim_ceilings_required_nonempty() -> None:
    kwargs = _valid_kwargs()
    kwargs["claim_ceilings"] = []
    with pytest.raises(ValidationError):
        EvalReceiptV1(**kwargs)


def test_what_this_does_not_prove_required_nonempty() -> None:
    kwargs = _valid_kwargs()
    kwargs["what_this_does_not_prove"] = []
    with pytest.raises(ValidationError):
        EvalReceiptV1(**kwargs)


def test_contamination_status_accepts_unknown() -> None:
    kwargs = _valid_kwargs()
    kwargs["contamination_status"] = "unknown"
    receipt = EvalReceiptV1(**kwargs)
    assert receipt.contamination_status == ContaminationStatus.UNKNOWN


def test_freshness_status_accepts_unknown() -> None:
    kwargs = _valid_kwargs()
    kwargs["freshness_status"] = "unknown"
    receipt = EvalReceiptV1(**kwargs)
    assert receipt.freshness_status == FreshnessStatus.UNKNOWN


def test_normalized_score_bounds() -> None:
    kwargs = _valid_kwargs()
    kwargs["normalized_score"] = 1.5
    with pytest.raises(ValidationError):
        EvalReceiptV1(**kwargs)
    kwargs["normalized_score"] = -0.1
    with pytest.raises(ValidationError):
        EvalReceiptV1(**kwargs)


def test_non_replayable_allows_missing_hashes() -> None:
    kwargs = _valid_kwargs()
    kwargs["replayable"] = False
    receipt = EvalReceiptV1(**kwargs)
    assert receipt.model_id_hash is None
    assert receipt.replayable is False


def test_round_trip_with_resource_observations() -> None:
    kwargs = _valid_kwargs()
    kwargs["resource_observations"] = {
        "gpu_vram_mb": 8192,
        "inference_time_s": 12.5,
        "tokens_generated": 1024,
    }
    receipt = EvalReceiptV1(**kwargs)
    restored = EvalReceiptV1.model_validate_json(receipt.model_dump_json())
    assert restored.resource_observations == kwargs["resource_observations"]
