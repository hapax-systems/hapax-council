"""Tests for safe determination exchange packets."""

from __future__ import annotations

import pytest

from shared.evidence_ledger import (
    DeterminationExchangePacket,
    determination_exchange_packet_to_external_evidence,
    synthetic_inbound_observation_packet,
    synthetic_outbound_determination_packet,
    validate_determination_exchange_packet,
)


def test_synthetic_outbound_packet_is_public_safe_and_valid() -> None:
    packet = synthetic_outbound_determination_packet()

    result = validate_determination_exchange_packet(packet)

    assert result.allowed
    assert packet.public_safe
    assert packet.synthetic_example
    assert packet.authority_level == "informational"
    assert packet.allowed_actions
    assert packet.prohibited_actions


def test_synthetic_inbound_packet_imports_only_as_external_evidence() -> None:
    packet = synthetic_inbound_observation_packet()

    result = validate_determination_exchange_packet(packet)
    evidence = determination_exchange_packet_to_external_evidence(packet)

    assert result.allowed
    assert result.import_as == "external_evidence"
    assert evidence.kind == "external_determination"
    assert evidence.privacy_class == "redacted_cross_boundary"
    assert evidence.public_safe
    assert evidence.derived_from == [packet.packet_id]


def test_missing_reviewer_field_rejects_packet() -> None:
    raw = synthetic_outbound_determination_packet().model_dump()
    raw.pop("reviewer")

    result = validate_determination_exchange_packet(raw)

    assert not result.allowed
    assert any(blocker.startswith("schema_error:reviewer:") for blocker in result.blockers)


@pytest.mark.parametrize(
    ("field_name", "blocker"),
    [
        ("contains_raw_source", "raw_source_present"),
        ("contains_raw_logs", "raw_logs_present"),
        ("contains_secrets", "secrets_present"),
        ("contains_employer_confidential_data", "employer_confidential_data_present"),
        ("contains_private_runtime_state", "private_runtime_state_present"),
        ("contains_personal_data", "personal_data_present"),
    ],
)
def test_redaction_flags_reject_packet(field_name: str, blocker: str) -> None:
    packet = synthetic_outbound_determination_packet().model_copy(update={field_name: True})

    result = validate_determination_exchange_packet(packet)

    assert not result.allowed
    assert blocker in result.blockers


def test_packet_requires_allowed_and_prohibited_actions() -> None:
    packet = synthetic_outbound_determination_packet().model_copy(
        update={"allowed_actions": [], "prohibited_actions": []}
    )

    result = validate_determination_exchange_packet(packet)

    assert not result.allowed
    assert "missing_allowed_actions" in result.blockers
    assert "missing_prohibited_actions" in result.blockers


def test_alliant_origin_packet_must_import_as_external_evidence() -> None:
    packet = synthetic_inbound_observation_packet().model_copy(
        update={
            "import_as": "none",
            "authority_level": "planning_authority",
            "allowed_actions": ["inform_generic_public_tooling"],
        }
    )

    result = validate_determination_exchange_packet(packet)

    assert not result.allowed
    assert "alliant_origin_must_import_as_external_evidence" in result.blockers
    assert "alliant_origin_must_be_informational" in result.blockers
    assert "alliant_origin_missing_external_evidence_action" in result.blockers


@pytest.mark.parametrize(
    ("field_name", "blocker"),
    [
        ("shares_api", "live_bridge_shared_api"),
        ("shares_database", "live_bridge_shared_database"),
        ("shares_token", "live_bridge_shared_token"),
        ("unattended_sync", "live_bridge_unattended_sync"),
        ("live_bridge", "live_bridge_enabled"),
    ],
)
def test_live_bridge_flags_reject_packet(field_name: str, blocker: str) -> None:
    packet = synthetic_outbound_determination_packet().model_copy(update={field_name: True})

    result = validate_determination_exchange_packet(packet)

    assert not result.allowed
    assert blocker in result.blockers


@pytest.mark.parametrize(
    "text",
    [
        "token=abc123",
        "PRIVATE_SENTINEL_DO_NOT_PUBLISH_X",
        "-----BEGIN PRIVATE KEY-----",
        "Ticket ABC-123 for Customer XYZ",
    ],
)
def test_sensitive_text_rejects_packet(text: str) -> None:
    packet = synthetic_outbound_determination_packet().model_copy(
        update={"evidence_summaries": [text]}
    )

    result = validate_determination_exchange_packet(packet)

    assert not result.allowed
    assert any(blocker.startswith("sensitive_text:") for blocker in result.blockers)


def test_external_evidence_conversion_refuses_non_alliant_packet() -> None:
    packet = synthetic_outbound_determination_packet()

    with pytest.raises(ValueError, match="only Alliant-origin inbound packets"):
        determination_exchange_packet_to_external_evidence(packet)


def test_external_system_cannot_grant_implementation_authority() -> None:
    packet = DeterminationExchangePacket(
        packet_id="DXP-BAD-AUTHORITY",
        packet_type="observation",
        from_system="external_enterprise",
        to_system="hapax",
        reviewer="operator",
        reviewed_at="2026-06-11T00:00:00Z",
        review_verdict="approved",
        purpose="Bad authority example.",
        authority_case="CASE-HAPAX-LEGIBILITY-IMPLEMENTATION-20260611",
        authority_level="implementation_authority",
        import_as="implementation_authority",
        allowed_actions=["implement"],
        prohibited_actions=["publish_without_review"],
        public_safe=True,
        synthetic_example=True,
        summary="External system attempts to grant implementation authority.",
    )

    result = validate_determination_exchange_packet(packet)

    assert not result.allowed
    assert "external_system_cannot_grant_implementation_authority" in result.blockers


@pytest.mark.parametrize(
    ("leak", "code"),
    [
        ("reach me at devops@example.org about it", "email_address"),
        ("located at 41.8781, -87.6298 per record", "gps_coordinate"),
        ("see vault:/30-areas/private-x/notes.md for detail", "private_path"),
        ("artifact at /store/llm-data/private/x.py here", "private_path"),
    ],
)
def test_cross_boundary_pii_in_packet_text_rejects(leak: str, code: str) -> None:
    packet = synthetic_outbound_determination_packet().model_copy(update={"summary": leak})

    result = validate_determination_exchange_packet(packet)

    assert not result.allowed
    assert f"cross_boundary_pii:{code}" in result.blockers


def test_operator_legal_name_detected_when_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Jane Q. Operator")
    packet = synthetic_outbound_determination_packet().model_copy(
        update={"summary": "prepared by Jane Q. Operator for pilot review"}
    )

    result = validate_determination_exchange_packet(packet)

    assert not result.allowed
    assert "cross_boundary_pii:operator_legal_name" in result.blockers
