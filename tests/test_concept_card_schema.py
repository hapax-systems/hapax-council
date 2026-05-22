"""Unit tests for HapaxConceptCard schema and validation model."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from shared.concept_card import (
    ClaimCeiling,
    HapaxConceptCard,
    PrivacyClass,
    RedactionPolicy,
    SourceQuality,
)

NOW = datetime(2026, 5, 21, 12, 0, 0, tzinfo=UTC)


def _concept_card(**overrides) -> HapaxConceptCard:
    defaults = {
        "concept_id": "concept-conceptual-wall",
        "concept_name": "Conceptual Wall",
        "description": "The threshold of understanding where the sheer volume of novel terminology prevents legibility.",
        "formation_provenance": [
            "research/2026-05-21-evidence-card-prior-art.md",
            "spec/concept-card.md",
        ],
        "claim_scope": "Explaining explanation-layer legible metadata structures.",
        "claim_ceiling": ClaimCeiling.PUBLICATION_WITNESS,
        "evidence_refs": ["tests/test_concept_card_schema.py"],
        "limitations": ["Requires active backfilling and manual audit."],
        "what_this_does_not_prove": "Does not prove that any specific claim is true; only documents conceptual boundaries.",
        "related_terms": ["evidence-explorer", "public-safe-evidence-card"],
        "privacy_class": PrivacyClass.INTERNAL,
        "redaction_policy": RedactionPolicy.NONE,
        "public_allowlist_approved": False,
        "source_quality": SourceQuality.HIGH,
        "license_provenance": "MIT/Hapax-Proprietary",
        "freshness_timestamp": NOW,
    }
    defaults.update(overrides)
    return HapaxConceptCard(**defaults)


def test_concept_card_instantiation() -> None:
    card = _concept_card()
    assert card.concept_id == "concept-conceptual-wall"
    assert card.concept_name == "Conceptual Wall"
    assert card.claim_ceiling == ClaimCeiling.PUBLICATION_WITNESS
    assert card.privacy_class == PrivacyClass.INTERNAL
    assert card.public_allowlist_approved is False
    assert card.source_quality == SourceQuality.HIGH
    assert card.freshness_timestamp == NOW


def test_concept_card_round_trip() -> None:
    card = _concept_card()
    dumped = card.model_dump(mode="json")
    restored = HapaxConceptCard.model_validate(dumped)
    assert restored == card


def test_json_serializable_enums() -> None:
    card = _concept_card()
    dumped = card.model_dump(mode="json")
    assert dumped["privacy_class"] == "internal"
    assert dumped["claim_ceiling"] == "publication_witness"
    assert dumped["redaction_policy"] == "none"
    assert dumped["source_quality"] == "high"


def test_missing_mandatory_claim_ceiling_raises_validation_error() -> None:
    with pytest.raises(ValidationError) as exc_info:
        HapaxConceptCard(
            concept_id="concept-1",
            concept_name="Concept One",
            description="Testing missing fields",
            claim_scope="Unit test scope",
            # missing claim_ceiling
            what_this_does_not_prove="Missing ceiling test",
            license_provenance="MIT",
        )
    assert "claim_ceiling" in str(exc_info.value)


def test_missing_mandatory_what_this_does_not_prove_raises_validation_error() -> None:
    with pytest.raises(ValidationError) as exc_info:
        HapaxConceptCard(
            concept_id="concept-1",
            concept_name="Concept One",
            description="Testing missing fields",
            claim_scope="Unit test scope",
            claim_ceiling=ClaimCeiling.NO_CLAIM,
            # missing what_this_does_not_prove
            license_provenance="MIT",
        )
    assert "what_this_does_not_prove" in str(exc_info.value)


def test_missing_other_mandatory_fields_raises_validation_error() -> None:
    mandatory_fields = [
        "concept_id",
        "concept_name",
        "description",
        "claim_scope",
        "license_provenance",
    ]
    for field in mandatory_fields:
        args = {
            "concept_id": "concept-1",
            "concept_name": "Concept One",
            "description": "Testing missing fields",
            "claim_scope": "Unit test scope",
            "claim_ceiling": ClaimCeiling.NO_CLAIM,
            "what_this_does_not_prove": "Testing missing fields",
            "license_provenance": "MIT",
        }
        del args[field]
        with pytest.raises(ValidationError) as exc_info:
            HapaxConceptCard(**args)
        assert field in str(exc_info.value)


def test_privacy_class_enum_variants() -> None:
    # Verify at least PUBLIC, INTERNAL, and REDACTED variants are present
    assert PrivacyClass.PUBLIC == "public"
    assert PrivacyClass.INTERNAL == "internal"
    assert PrivacyClass.REDACTED == "redacted"
    assert PrivacyClass.OPERATOR_ONLY == "operator_only"
    assert PrivacyClass.CONSENT_GATED == "consent_gated"

    # Test instantiation with each required variant
    for variant in [PrivacyClass.PUBLIC, PrivacyClass.INTERNAL, PrivacyClass.REDACTED]:
        card = _concept_card(privacy_class=variant)
        assert card.privacy_class == variant


def test_public_allowlist_approved_default_is_false() -> None:
    card = HapaxConceptCard(
        concept_id="concept-1",
        concept_name="Concept One",
        description="Testing default allowlist",
        claim_scope="Unit test scope",
        claim_ceiling=ClaimCeiling.NO_CLAIM,
        what_this_does_not_prove="Testing defaults",
        license_provenance="MIT",
    )
    assert card.public_allowlist_approved is False


def test_json_schema_export_is_valid() -> None:
    schema = HapaxConceptCard.model_json_schema()
    assert schema["type"] == "object"
    assert "concept_id" in schema["properties"]
    assert "claim_ceiling" in schema["properties"]
    assert "what_this_does_not_prove" in schema["properties"]
    assert "privacy_class" in schema["properties"]
    assert "public_allowlist_approved" in schema["properties"]
