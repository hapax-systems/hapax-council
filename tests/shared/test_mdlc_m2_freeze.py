"""Tests for the MonDLC M2 freeze artifact contract."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from shared.capdlc_lifecycle import GateStatus
from shared.mdlc_m2_freeze import (
    M2BudgetEnvelope,
    M2FreezeArtifact,
    M2FreezeRefusal,
    M2FreezeRefusalReason,
    require_m2_freeze_artifact,
    verify_m2_freeze_artifact,
)
from shared.mdlc_measure import MonDLCLadder

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
HASH = "6bcb5cb7dd30967d20e78d79cb0a470b615f324475bc280062ce5c94e9d14f36"


def _artifact(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "artifact_id": "m2-freeze:test-disposition",
        "budget_envelope": {
            "authority_ref": "authority:CASE-SDLC-REFORM-001",
            "currency": "usd",
            "max_notional": 250.0,
            "max_position": 1.0,
            "purpose": "test disposition freeze",
            "venue": "test-venue",
            "instrument": "test-instrument",
        },
        "ladder": {
            "ruler_hash": HASH,
            "min_corroboration_count": 2,
            "freshness_ttl_seconds": 3600,
            "as_of": NOW.isoformat(),
            "positive_threshold": 0.0,
            "negative_threshold": -50.0,
        },
        "ruler_hash": HASH,
        "signer": "operator:hapax",
        "signed_at": NOW.isoformat(),
        "signature_ref": "signature:m2-freeze:test-disposition",
        "evidence_refs": ("req:20260628-mdlc-core",),
    }
    data.update(overrides)
    return data


def test_signed_freeze_artifact_records_envelope_ladder_hash_signer_and_time() -> None:
    result = verify_m2_freeze_artifact(_artifact(), ruler_hash_commit=HASH)

    assert result.status is GateStatus.LIT
    assert result.ok is True
    assert result.gate_result.verdict is True
    assert result.reason == "m2_freeze_artifact_present"
    assert result.refusal_reason is None
    assert result.expected_ruler_hash == HASH
    assert result.ruler_hash_commit == HASH
    assert result.artifact is not None
    assert result.artifact.budget_envelope.currency == "USD"
    assert result.artifact.budget_envelope.max_notional == 250.0
    assert result.artifact.ladder.ruler_hash == HASH
    assert result.artifact.signer == "operator:hapax"
    assert result.artifact.signed_at == NOW
    assert "m2-freeze:m2-freeze:test-disposition" in result.evidence_refs
    assert "signature:m2-freeze:test-disposition" in result.evidence_refs


def test_require_success_returns_freeze_artifact() -> None:
    artifact = require_m2_freeze_artifact(_artifact(), ruler_hash_commit=HASH)

    assert artifact.artifact_id == "m2-freeze:test-disposition"
    assert artifact.ruler_hash == HASH
    assert artifact.ladder.ruler_hash == HASH


def test_missing_freeze_artifact_refuses() -> None:
    result = verify_m2_freeze_artifact(None, ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.MISSING_ARTIFACT


def test_boolean_freeze_flag_without_artifact_never_counts_as_presence() -> None:
    result = verify_m2_freeze_artifact(
        {"freeze_lock_fired": True, "ruler_hash": HASH},
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.DARK
    assert result.ok is False
    assert result.gate_result.verdict is None
    assert result.refusal_reason is M2FreezeRefusalReason.MISSING_ARTIFACT_ID


@pytest.mark.parametrize(
    ("field", "reason"),
    (
        ("artifact_id", M2FreezeRefusalReason.MISSING_ARTIFACT_ID),
        ("ruler_hash", M2FreezeRefusalReason.MISSING_RULER_HASH),
    ),
)
def test_artifact_identity_fields_are_required(field: str, reason: M2FreezeRefusalReason) -> None:
    artifact = _artifact()
    artifact.pop(field)

    result = verify_m2_freeze_artifact(artifact, ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is reason


@pytest.mark.parametrize(
    ("field", "reason"),
    (
        ("budget_envelope", M2FreezeRefusalReason.MISSING_BUDGET_ENVELOPE),
        ("ladder", M2FreezeRefusalReason.MISSING_LADDER),
    ),
)
def test_required_mapping_fields_are_required(field: str, reason: M2FreezeRefusalReason) -> None:
    artifact = _artifact()
    artifact.pop(field)

    result = verify_m2_freeze_artifact(artifact, ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is reason


def test_invalid_budget_envelope_is_not_reported_as_ladder_failure() -> None:
    budget = dict(_artifact()["budget_envelope"])
    budget["max_notional"] = -1.0

    result = verify_m2_freeze_artifact(
        _artifact(budget_envelope=budget),
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.INVALID_BUDGET_ENVELOPE
    assert result.next_action == "repair the budget envelope fields before commit"


def test_invalid_ladder_refuses_with_ladder_reason() -> None:
    ladder = dict(_artifact()["ladder"])
    ladder["min_corroboration_count"] = 0

    result = verify_m2_freeze_artifact(_artifact(ladder=ladder), ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.INVALID_LADDER
    assert result.next_action == "repair the frozen ruler ladder before commit"


@pytest.mark.parametrize(
    "missing_field",
    (
        "min_corroboration_count",
        "freshness_ttl_seconds",
        "positive_threshold",
        "negative_threshold",
    ),
)
def test_freeze_ladder_must_record_canonical_fields(missing_field: str) -> None:
    ladder = dict(_artifact()["ladder"])
    ladder.pop(missing_field)

    result = verify_m2_freeze_artifact(_artifact(ladder=ladder), ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.INVALID_LADDER


def test_freeze_ladder_does_not_accept_measurement_alias_defaults() -> None:
    artifact = _artifact(
        ladder={
            "ruler_hash": HASH,
            "min_N": 2,
            "freshness_ttl_s": 3600,
            "positive_threshold": 0.0,
            "negative_threshold": -50.0,
        }
    )

    result = verify_m2_freeze_artifact(artifact, ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.INVALID_LADDER


def test_invalid_signed_at_refuses_with_timestamp_reason() -> None:
    result = verify_m2_freeze_artifact(
        _artifact(signed_at="not-a-timestamp"),
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.INVALID_SIGNED_AT


def test_invalid_evidence_refs_has_specific_refusal_reason() -> None:
    result = verify_m2_freeze_artifact(
        _artifact(evidence_refs="not-a-sequence"),
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.INVALID_EVIDENCE_REFS


def test_missing_ruler_hash_commit_refuses_before_m2_commit() -> None:
    result = verify_m2_freeze_artifact(_artifact(), ruler_hash_commit=None)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.MISSING_RULER_HASH_COMMIT
    assert result.expected_ruler_hash == HASH
    assert result.next_action == "supply the commit ruler hash from the freeze artifact"


def test_whitespace_ruler_hash_commit_refuses_before_m2_commit() -> None:
    result = verify_m2_freeze_artifact(_artifact(), ruler_hash_commit="  ")

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.MISSING_RULER_HASH_COMMIT
    assert result.expected_ruler_hash == HASH
    assert result.next_action == "supply the commit ruler hash from the freeze artifact"


def test_mismatched_ruler_hash_refuses_and_require_raises() -> None:
    result = verify_m2_freeze_artifact(_artifact(), ruler_hash_commit="different")

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.RULER_HASH_MISMATCH
    assert result.expected_ruler_hash == HASH
    assert "m2-freeze:m2-freeze:test-disposition" in result.gate_result.evidence_refs
    assert "signature:m2-freeze:test-disposition" in result.gate_result.evidence_refs

    with pytest.raises(M2FreezeRefusal) as exc:
        require_m2_freeze_artifact(_artifact(), ruler_hash_commit="different")
    assert exc.value.verification.refusal_reason is M2FreezeRefusalReason.RULER_HASH_MISMATCH


def test_ladder_hash_must_match_artifact_hash() -> None:
    artifact = _artifact(
        ladder={
            "ruler_hash": "ab4a8998e57aef44d6d38d0f3dfc848a690de988f7266a4eba2a224a7c883118",
            "min_corroboration_count": 2,
            "freshness_ttl_seconds": 3600,
            "as_of": NOW.isoformat(),
            "positive_threshold": 0.0,
            "negative_threshold": -50.0,
        }
    )

    result = verify_m2_freeze_artifact(artifact, ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.LADDER_RULER_HASH_MISMATCH


@pytest.mark.parametrize(
    ("field", "reason"),
    (
        ("signer", M2FreezeRefusalReason.MISSING_SIGNER),
        ("signed_at", M2FreezeRefusalReason.MISSING_SIGNED_AT),
        ("signature_ref", M2FreezeRefusalReason.MISSING_SIGNATURE_REF),
    ),
)
def test_signature_fields_are_required(field: str, reason: M2FreezeRefusalReason) -> None:
    artifact = _artifact()
    artifact.pop(field)

    result = verify_m2_freeze_artifact(artifact, ruler_hash_commit=HASH)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is reason


def test_freeze_artifact_requires_typed_budget_envelope_and_ladder() -> None:
    budget = M2BudgetEnvelope(
        authority_ref="authority:CASE-SDLC-REFORM-001",
        currency="USD",
        max_notional=250.0,
        max_position=1.0,
    )
    ladder = MonDLCLadder(
        ruler_hash=HASH,
        min_corroboration_count=2,
        freshness_ttl_seconds=3600,
        as_of=NOW,
        positive_threshold=0.0,
        negative_threshold=-50.0,
    )

    with pytest.raises(TypeError, match="budget_envelope"):
        M2FreezeArtifact(
            artifact_id="m2-freeze:test-disposition",
            budget_envelope=object(),  # type: ignore[arg-type]
            ladder=ladder,
            ruler_hash=HASH,
            signer="operator:hapax",
            signed_at=NOW,
            signature_ref="signature:m2-freeze:test-disposition",
        )

    with pytest.raises(TypeError, match="ladder"):
        M2FreezeArtifact(
            artifact_id="m2-freeze:test-disposition",
            budget_envelope=budget,
            ladder=object(),  # type: ignore[arg-type]
            ruler_hash=HASH,
            signer="operator:hapax",
            signed_at=NOW,
            signature_ref="signature:m2-freeze:test-disposition",
        )
