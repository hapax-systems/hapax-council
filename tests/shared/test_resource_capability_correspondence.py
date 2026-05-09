"""Tests for RC-005 private expected-correspondence dry-run substrate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.resource_capability import HandlingDecision, ReplyTier
from shared.resource_capability_correspondence import (
    CorrespondenceArtifactKind,
    CorrespondenceDryRunDecision,
    ExpectedCorrespondenceClassification,
    ExpectedCorrespondenceDryRunFixtureSet,
    ResourceCapabilityCorrespondenceError,
    load_resource_capability_correspondence_fixtures,
)

FIXTURE_PATH = Path("config/resource-capability-correspondence-fixtures.json")


def _fixture_payload() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _write_fixture(tmp_path: Path, payload: dict) -> Path:
    fixture_path = tmp_path / "resource-capability-correspondence-fixtures.json"
    fixture_path.write_text(json.dumps(payload), encoding="utf-8")
    return fixture_path


def test_correspondence_fixture_loads_and_preserves_consumer_boundary() -> None:
    fixtures = load_resource_capability_correspondence_fixtures()

    assert fixtures.consumer_permission_after == "private_correspondence_dry_run_tests_only"
    packet = fixtures.dry_run_packets[0]
    assert packet.authority_source == (
        "isap:resource-capability-expected-correspondence-dry-run-20260509"
    )
    assert packet.classifications
    assert packet.response_artifacts


def test_correspondence_models_are_strict_and_reject_extra_fields() -> None:
    classification = (
        load_resource_capability_correspondence_fixtures().dry_run_packets[0].classifications[0]
    )
    payload = classification.model_dump(mode="json")
    payload["surprise_send_authority"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ExpectedCorrespondenceClassification.model_validate(payload)


def test_dry_run_artifacts_cannot_authorize_mail_or_external_effects() -> None:
    packet = load_resource_capability_correspondence_fixtures().dry_run_packets[0]
    authority_fields = [
        "outbound_email_authorized",
        "automated_email_send_authorized",
        "gmail_draft_create_authorized",
        "smtp_send_authorized",
        "provider_api_execution_authorized",
        "credential_lookup_authorized",
        "live_mail_mutation_authorized",
        "label_mutation_authorized",
        "thread_mutation_authorized",
        "live_calendar_write_authorized",
        "payment_movement_authorized",
        "public_offer_authorized",
        "public_claim_upgrade_authorized",
        "public_projection_allowed",
        "runtime_feeder_execution_authorized",
        "service_execution_authorized",
        "task_file_write_authorized",
        "coordinator_send_authorized",
        "external_action_authorized",
    ]
    rows = [packet, *packet.classifications, *packet.response_artifacts]

    for row in rows:
        for field in authority_fields:
            assert getattr(row, field) is False

    payload = packet.model_dump(mode="json")
    payload["gmail_draft_create_authorized"] = True
    with pytest.raises(ValidationError, match="Input should be False"):
        ExpectedCorrespondenceDryRunFixtureSet.model_validate(
            {
                "schema_version": 1,
                "fixture_set_id": "bad",
                "consumer_permission_after": "private_correspondence_dry_run_tests_only",
                "dry_run_packets": [payload],
            }
        )


def test_report_only_envelopes_cannot_create_draft_text_or_draft_authority() -> None:
    packet = load_resource_capability_correspondence_fixtures().dry_run_packets[0]
    classification = packet.classifications[0]
    artifact = packet.response_artifacts[0]

    assert classification.reply_tier is ReplyTier.REPORT_ONLY
    assert classification.handling_decision is HandlingDecision.NO_RESPONSE
    assert classification.dry_run_decision is CorrespondenceDryRunDecision.REPORT_ONLY
    assert artifact.artifact_kind is CorrespondenceArtifactKind.REPORT_ONLY_RECORD
    assert artifact.response_body is None
    assert artifact.draft_create_allowed is False
    assert artifact.send_allowed is False

    payload = _fixture_payload()
    bad_artifact = payload["dry_run_packets"][0]["response_artifacts"][0]
    bad_artifact["artifact_kind"] = "unsent_draft"
    bad_artifact["response_body"] = "automated Hapax operations note only."
    bad_artifact["fail_closed_reason"] = None
    with pytest.raises(ValidationError, match="REPORT_ONLY classifications"):
        ExpectedCorrespondenceDryRunFixtureSet.model_validate(payload)


def test_auth_account_label_class_and_confidence_mismatches_fail_closed(tmp_path: Path) -> None:
    payload = _fixture_payload()
    payload["dry_run_packets"][0]["classifications"][0]["source_account"] = "account:other"
    with pytest.raises(ResourceCapabilityCorrespondenceError, match="source account outside"):
        load_resource_capability_correspondence_fixtures(_write_fixture(tmp_path, payload))

    payload = _fixture_payload()
    payload["dry_run_packets"][0]["classifications"][0]["label"] = "unapproved-label"
    with pytest.raises(ResourceCapabilityCorrespondenceError, match="label outside"):
        load_resource_capability_correspondence_fixtures(_write_fixture(tmp_path, payload))

    payload = _fixture_payload()
    payload["dry_run_packets"][0]["classifications"][0]["expected_class"] = "custom_work"
    with pytest.raises(ResourceCapabilityCorrespondenceError, match="message class outside"):
        load_resource_capability_correspondence_fixtures(_write_fixture(tmp_path, payload))

    payload = _fixture_payload()
    payload["dry_run_packets"][0]["classifications"][0]["confidence"] = 0.5
    with pytest.raises(ResourceCapabilityCorrespondenceError, match="confidence below"):
        load_resource_capability_correspondence_fixtures(_write_fixture(tmp_path, payload))


def test_suppression_claim_rate_limit_mail_loop_and_body_quote_checks_are_required() -> None:
    required_true_fields = [
        "suppression_checked",
        "claims_checked",
        "rate_limit_checked",
        "mail_loop_policy_checked",
    ]
    for field in required_true_fields:
        payload = _fixture_payload()
        payload["dry_run_packets"][0]["classifications"][0][field] = False
        with pytest.raises(ValidationError, match="Input should be True"):
            ExpectedCorrespondenceDryRunFixtureSet.model_validate(payload)

    payload = _fixture_payload()
    payload["dry_run_packets"][0]["classifications"][0]["body_quote_allowed"] = True
    with pytest.raises(ValidationError, match="Input should be False"):
        ExpectedCorrespondenceDryRunFixtureSet.model_validate(payload)

    for field in ["suppression_checked", "claims_checked", "rate_limit_checked"]:
        payload = _fixture_payload()
        payload["dry_run_packets"][0]["response_artifacts"][0][field] = False
        with pytest.raises(ValidationError, match="Input should be True"):
            ExpectedCorrespondenceDryRunFixtureSet.model_validate(payload)


def test_text_bearing_artifacts_require_operational_disclosure_and_lint() -> None:
    payload = _fixture_payload()
    artifact = payload["dry_run_packets"][0]["response_artifacts"][0]
    artifact["artifact_kind"] = "hard_refusal_notice"
    artifact["response_body"] = "I feel this should not proceed."
    artifact["disclosure_text"] = "automated Hapax operations dry-run"
    artifact["fail_closed_reason"] = None

    with pytest.raises(ValidationError, match="forbidden text token"):
        ExpectedCorrespondenceDryRunFixtureSet.model_validate(payload)

    payload = _fixture_payload()
    artifact = payload["dry_run_packets"][0]["response_artifacts"][0]
    artifact["artifact_kind"] = "hard_refusal_notice"
    artifact["response_body"] = "This message cannot be processed by this dry-run system."
    artifact["disclosure_text"] = "automated system"
    artifact["fail_closed_reason"] = None

    with pytest.raises(ValidationError, match="automated Hapax operations disclosure"):
        ExpectedCorrespondenceDryRunFixtureSet.model_validate(payload)


def test_correspondence_refs_reject_absolute_paths_and_raw_email_tokens() -> None:
    classification = (
        load_resource_capability_correspondence_fixtures().dry_run_packets[0].classifications[0]
    )

    payload = classification.model_dump(mode="json")
    payload["evidence_refs"] = ["/private/absolute"]
    with pytest.raises(ValidationError, match="repo-relative or symbolic"):
        ExpectedCorrespondenceClassification.model_validate(payload)

    payload = classification.model_dump(mode="json")
    payload["evidence_refs"] = ["sender@example.com"]
    with pytest.raises(ValidationError, match="raw email addresses"):
        ExpectedCorrespondenceClassification.model_validate(payload)


def test_correspondence_fixture_file_contains_no_private_payload_or_public_claim_material() -> None:
    text = FIXTURE_PATH.read_text(encoding="utf-8")

    forbidden_tokens = [
        "/private/operator-home",
        "raw_body",
        "body_plain",
        "body_html",
        "receipt_email",
        "customer_email",
        "sender@example.com",
        "billing_details",
        "card_number",
        "government_id",
        "passport",
        "pass show",
        "GMAIL_TOKEN",
        "GOOGLE_CLIENT_SECRET",
        "partnered with",
        "endorsed by",
        "approved by",
    ]
    for token in forbidden_tokens:
        assert token not in text


def test_correspondence_module_has_no_runtime_provider_or_mail_imports() -> None:
    source = Path("shared/resource_capability_correspondence.py").read_text(encoding="utf-8")

    forbidden_tokens = [
        "googleapiclient",
        "smtplib",
        "imaplib",
        "requests",
        "httpx",
        "os.environ",
        "pass_show",
        "agents.mail_monitor",
        "agents.gmail_sync",
        "agents.gcalendar_sync",
        "users.messages.send",
        "users.drafts.create",
        "users.drafts.send",
        "events.insert",
        "events.patch",
        "payment_rails",
        "dispatch_task",
        "cc-claim",
        ".write_text(",
    ]
    for token in forbidden_tokens:
        assert token not in source
