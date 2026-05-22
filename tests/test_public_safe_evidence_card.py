"""Tests for PublicSafeEvidenceCard schema and publication gate checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from shared.capability_evidence_card import PrivacyClass
from shared.public_safe_evidence_card import (
    ClaimCeiling,
    GateVerdict,
    PublicSafeEvidenceCard,
    RedactionPolicy,
    SourceQuality,
)

NOW = datetime(2026, 5, 21, 12, 0, 0, tzinfo=UTC)


def _card(**overrides) -> PublicSafeEvidenceCard:
    defaults = {
        "evidence_id": "pub-ev-001",
        "source_card_id": "test-card-001",
        "public_claim": "Publicly safe evidence for voice switching.",
        "evidence_refs": ["tests/shared/test_voice_register.py"],
        "source_quality": SourceQuality.HIGH,
        "license_provenance": "MIT, derived from research spec v1",
        "redaction_policy": RedactionPolicy.NAMES,
        "redacted_fields": ["operator_name"],
        "public_allowlist_approved": True,
        "privacy_class": PrivacyClass.PUBLIC,
        "freshness_deadline": NOW + timedelta(hours=24),
        "limitations": ["Only tests enum values, not runtime switching"],
        "what_this_does_not_prove": ["Does not prove hardware compatibility"],
        "claim_ceiling": ClaimCeiling.PUBLICATION_WITNESS,
        "methodology_ref": "spec-ref-001",
    }
    defaults.update(overrides)
    return PublicSafeEvidenceCard(**defaults)


def test_round_trip() -> None:
    card = _card()
    dumped = card.model_dump(mode="json")
    restored = PublicSafeEvidenceCard.model_validate(dumped)
    assert restored == card


def test_json_serializable_enums() -> None:
    card = _card()
    dumped = card.model_dump(mode="json")
    assert dumped["source_quality"] == "high"
    assert dumped["redaction_policy"] == "names"
    assert dumped["claim_ceiling"] == "publication_witness"


def test_missing_source_quality_causes_validation_error() -> None:
    data = _card().model_dump()
    data.pop("source_quality")
    with pytest.raises(ValidationError) as exc_info:
        PublicSafeEvidenceCard.model_validate(data)
    assert "source_quality" in str(exc_info.value)


def test_missing_license_provenance_causes_validation_error() -> None:
    data = _card().model_dump()
    data.pop("license_provenance")
    with pytest.raises(ValidationError) as exc_info:
        PublicSafeEvidenceCard.model_validate(data)
    assert "license_provenance" in str(exc_info.value)


def test_missing_what_this_does_not_prove_causes_validation_error() -> None:
    data = _card().model_dump()
    data.pop("what_this_does_not_prove")
    with pytest.raises(ValidationError) as exc_info:
        PublicSafeEvidenceCard.model_validate(data)
    assert "what_this_does_not_prove" in str(exc_info.value)


def test_public_allowlist_approved_false_causes_gate_rejection() -> None:
    card = _card(public_allowlist_approved=False)
    verdict = card.passes_gate(now=NOW)
    assert isinstance(verdict, GateVerdict)
    assert verdict.approved is False
    assert "public_allowlist_approved" in verdict.reason


def test_gate_check_stale_freshness() -> None:
    card = _card(freshness_deadline=NOW - timedelta(hours=1))
    verdict = card.passes_gate(now=NOW)
    assert isinstance(verdict, GateVerdict)
    assert verdict.approved is False
    assert "freshness" in verdict.reason


def test_gate_check_fresh_success() -> None:
    card = _card(freshness_deadline=NOW + timedelta(hours=1))
    verdict = card.passes_gate(now=NOW)
    assert isinstance(verdict, GateVerdict)
    assert verdict.approved is True
    assert verdict.reason is None


def test_empty_evidence_refs_causes_validation_error() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _card(evidence_refs=[])
    assert "evidence_refs" in str(exc_info.value)
