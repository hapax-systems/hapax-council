"""Canonical test fixtures for all EvalReceiptV1 card validity states.

Covers: valid receipt, missing hash/artifact rejection, contaminated/stale
parsing, overclaiming rejection, and unknown status acceptance.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.eval_receipt import ContaminationStatus, EvalReceiptV1, FreshnessStatus


def _base_kwargs() -> dict:
    """Minimal valid kwargs for a non-replayable EvalReceiptV1."""
    return {
        "run_id": "run-fixture-001",
        "authority_case": "CASE-FIXTURE-001",
        "task_ref": "task-fixture-001",
        "normalized_score": 0.92,
        "contamination_status": ContaminationStatus.CLEAN,
        "freshness_status": FreshnessStatus.FRESH,
        "claim_ceilings": ["Model passes benchmark X at ≥90%"],
        "what_this_does_not_prove": ["Generalisation beyond benchmark X"],
    }


_ALL_HASHES = {
    "model_id_hash": "sha256:aaa",
    "route_hash": "sha256:bbb",
    "config_hash": "sha256:ccc",
    "prompt_hash": "sha256:ddd",
    "scorer_hash": "sha256:eee",
    "dataset_hash": "sha256:fff",
}


def _replayable_kwargs() -> dict:
    """Kwargs for a fully-populated replayable receipt."""
    kw = _base_kwargs()
    kw["replayable"] = True
    kw["raw_artifact_refs"] = ["s3://bucket/artifact-001.jsonl"]
    kw.update(_ALL_HASHES)
    kw["resource_observations"] = {
        "gpu_vram_mb": 24576,
        "inference_time_s": 45.2,
    }
    return kw


# ── 1. Valid receipt ─────────────────────────────────────────────────────


def test_valid_receipt() -> None:
    """Fully-populated receipt with all hashes, replayable=True, no errors."""
    receipt = EvalReceiptV1(**_replayable_kwargs())
    assert receipt.schema_version == "EvalReceiptV1"
    assert receipt.replayable is True
    assert receipt.normalized_score == 0.92
    assert receipt.contamination_status == ContaminationStatus.CLEAN
    assert receipt.freshness_status == FreshnessStatus.FRESH
    assert len(receipt.claim_ceilings) >= 1
    assert len(receipt.what_this_does_not_prove) >= 1
    # Round-trip sanity
    restored = EvalReceiptV1.model_validate_json(receipt.model_dump_json())
    assert restored == receipt


# ── 2. Missing hash → rejected when replayable ──────────────────────────


def test_missing_hash_rejected() -> None:
    """Any hash field set to None with replayable=True must raise."""
    kw = _replayable_kwargs()
    kw["model_id_hash"] = None  # knock out one hash
    with pytest.raises(ValidationError, match="missing"):
        EvalReceiptV1(**kw)


# ── 3. Missing artifact refs → rejected when replayable ─────────────────


def test_missing_artifact_rejected() -> None:
    """Empty raw_artifact_refs with replayable=True must raise."""
    kw = _replayable_kwargs()
    kw["raw_artifact_refs"] = []
    with pytest.raises(ValidationError, match="raw_artifact_refs"):
        EvalReceiptV1(**kw)


# ── 4. Contaminated receipt parses ───────────────────────────────────────


def test_contaminated_receipt_parses() -> None:
    """contamination_status='contaminated' is schema-valid (policy layer flags)."""
    kw = _base_kwargs()
    kw["contamination_status"] = ContaminationStatus.CONTAMINATED
    receipt = EvalReceiptV1(**kw)
    assert receipt.contamination_status == ContaminationStatus.CONTAMINATED
    # Schema says valid; policy decides whether to act on it
    assert receipt.schema_version == "EvalReceiptV1"


# ── 5. Stale receipt parses ──────────────────────────────────────────────


def test_stale_receipt_parses() -> None:
    """freshness_status='stale' is schema-valid."""
    kw = _base_kwargs()
    kw["freshness_status"] = FreshnessStatus.STALE
    receipt = EvalReceiptV1(**kw)
    assert receipt.freshness_status == FreshnessStatus.STALE
    assert receipt.schema_version == "EvalReceiptV1"


# ── 6. Overclaiming rejected ────────────────────────────────────────────


def test_overclaiming_rejected() -> None:
    """Empty claim_ceilings must raise ValidationError (min_length=1)."""
    kw = _base_kwargs()
    kw["claim_ceilings"] = []
    with pytest.raises(ValidationError):
        EvalReceiptV1(**kw)


# ── 7. Unknown statuses accepted ────────────────────────────────────────


def test_unknown_statuses_accepted() -> None:
    """Both contamination and freshness set to 'unknown' must parse without error."""
    kw = _base_kwargs()
    kw["contamination_status"] = ContaminationStatus.UNKNOWN
    kw["freshness_status"] = FreshnessStatus.UNKNOWN
    receipt = EvalReceiptV1(**kw)
    assert receipt.contamination_status == ContaminationStatus.UNKNOWN
    assert receipt.freshness_status == FreshnessStatus.UNKNOWN


# ── 8. Implicit: all 7 above + this structural sanity check = 8 tests ───


def test_non_replayable_allows_missing_hashes() -> None:
    """Non-replayable receipt with all hash fields None is valid."""
    kw = _base_kwargs()
    kw["replayable"] = False
    receipt = EvalReceiptV1(**kw)
    assert receipt.replayable is False
    assert receipt.model_id_hash is None
    assert receipt.route_hash is None
    assert receipt.config_hash is None
    assert receipt.prompt_hash is None
    assert receipt.scorer_hash is None
    assert receipt.dataset_hash is None
