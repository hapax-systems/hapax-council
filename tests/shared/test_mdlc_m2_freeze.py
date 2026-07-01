"""Tests for the MonDLC M2 freeze artifact contract."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from shared.capdlc_lifecycle import GateStatus
from shared.mdlc_m2_freeze import (
    M2FreezeRefusal,
    M2FreezeRefusalReason,
    require_m2_freeze_artifact,
    verify_m2_freeze_artifact,
)

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


def test_boolean_freeze_flag_without_artifact_never_counts_as_presence() -> None:
    result = verify_m2_freeze_artifact(
        {"freeze_lock_fired": True, "ruler_hash": HASH},
        ruler_hash_commit=HASH,
    )

    assert result.status is GateStatus.DARK
    assert result.ok is False
    assert result.gate_result.verdict is None
    assert result.refusal_reason is M2FreezeRefusalReason.MISSING_ARTIFACT_ID


def test_missing_ruler_hash_commit_refuses_before_m2_commit() -> None:
    result = verify_m2_freeze_artifact(_artifact(), ruler_hash_commit=None)

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.MISSING_RULER_HASH_COMMIT
    assert result.expected_ruler_hash == HASH
    assert result.next_action == "supply the commit ruler hash from the freeze artifact"


def test_mismatched_ruler_hash_refuses_and_require_raises() -> None:
    result = verify_m2_freeze_artifact(_artifact(), ruler_hash_commit="different")

    assert result.status is GateStatus.DARK
    assert result.refusal_reason is M2FreezeRefusalReason.RULER_HASH_MISMATCH
    assert result.expected_ruler_hash == HASH

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
