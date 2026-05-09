"""Tests for RC-006 private calendar-obligation dry-run substrate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.resource_capability_calendar import (
    CalendarDryRunExtraction,
    CalendarDryRunFixtureSet,
    ProposedEventArtifact,
    ResourceCapabilityCalendarError,
    load_resource_capability_calendar_fixtures,
)

FIXTURE_PATH = Path("config/resource-capability-calendar-fixtures.json")


def _fixture_payload() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _write_fixture(tmp_path: Path, payload: dict) -> Path:
    fixture_path = tmp_path / "resource-capability-calendar-fixtures.json"
    fixture_path.write_text(json.dumps(payload), encoding="utf-8")
    return fixture_path


def test_calendar_fixture_loads_and_preserves_consumer_boundary() -> None:
    fixtures = load_resource_capability_calendar_fixtures()

    assert fixtures.consumer_permission_after == "private_calendar_dry_run_tests_only"
    packet = fixtures.dry_run_packets[0]
    assert packet.authority_source == (
        "isap:resource-capability-calendar-obligation-dry-run-20260509"
    )
    assert packet.extractions
    assert packet.proposed_events


def test_calendar_models_are_strict_and_reject_extra_fields() -> None:
    extraction = load_resource_capability_calendar_fixtures().dry_run_packets[0].extractions[0]
    payload = extraction.model_dump(mode="json")
    payload["surprise_calendar_write_authority"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CalendarDryRunExtraction.model_validate(payload)


def test_fixture_rows_validate_against_existing_obligation_and_envelope() -> None:
    fixtures = load_resource_capability_calendar_fixtures()
    packet = fixtures.dry_run_packets[0]
    for extraction in packet.extractions:
        assert extraction.obligation_ref.startswith("calendar-obligation:")
        assert extraction.envelope_ref.startswith("calendar-write:")
        assert len(extraction.source_signal_refs) >= 1


def test_every_extraction_cites_obligation_envelope_and_source_signal() -> None:
    fixtures = load_resource_capability_calendar_fixtures()
    packet = fixtures.dry_run_packets[0]
    for extraction in packet.extractions:
        assert extraction.obligation_ref
        assert extraction.envelope_ref
        assert extraction.source_signal_refs
        assert extraction.evidence_refs


def test_auto_create_authority_level_fails_closed() -> None:
    payload = _fixture_payload()
    payload["dry_run_packets"][0]["extractions"][0]["authority_level"] = "auto_create"
    with pytest.raises(ValidationError, match="Input should be 'draft_for_review' or 'escalate'"):
        CalendarDryRunFixtureSet.model_validate(payload)


def test_calendar_scope_other_than_private_internal_fails_closed() -> None:
    payload = _fixture_payload()
    payload["dry_run_packets"][0]["extractions"][0]["calendar_scope"] = "shared"
    with pytest.raises(ValidationError, match="literal_error"):
        CalendarDryRunFixtureSet.model_validate(payload)


def test_attendee_notification_conference_policies_not_blocked_none_fail_closed() -> None:
    for field in ["attendee_policy", "notification_policy", "conference_data_policy"]:
        payload = _fixture_payload()
        payload["dry_run_packets"][0]["extractions"][0][field] = "allowed"
        with pytest.raises(ValidationError, match="Input should be 'blocked_none'"):
            CalendarDryRunFixtureSet.model_validate(payload)

        payload = _fixture_payload()
        payload["dry_run_packets"][0]["proposed_events"][0][field] = "allowed"
        with pytest.raises(ValidationError, match="Input should be 'blocked_none'"):
            CalendarDryRunFixtureSet.model_validate(payload)


def test_availability_promise_true_fails_closed() -> None:
    payload = _fixture_payload()
    payload["dry_run_packets"][0]["extractions"][0]["availability_promise"] = True
    with pytest.raises(ValidationError, match="Input should be False"):
        CalendarDryRunFixtureSet.model_validate(payload)

    payload = _fixture_payload()
    payload["dry_run_packets"][0]["proposed_events"][0]["availability_promise"] = True
    with pytest.raises(ValidationError, match="Input should be False"):
        CalendarDryRunFixtureSet.model_validate(payload)


def test_confidence_below_envelope_minimum_fails_closed(tmp_path: Path) -> None:
    payload = _fixture_payload()
    payload["dry_run_packets"][0]["extractions"][0]["confidence"] = 0.5
    with pytest.raises(ResourceCapabilityCalendarError, match="confidence.*below envelope minimum"):
        load_resource_capability_calendar_fixtures(_write_fixture(tmp_path, payload))


def test_missing_or_empty_timezone_fails_closed() -> None:
    payload = _fixture_payload()
    payload["dry_run_packets"][0]["extractions"][0]["timezone"] = ""
    with pytest.raises(ValidationError, match="at least 1 character"):
        CalendarDryRunFixtureSet.model_validate(payload)

    payload = _fixture_payload()
    payload["dry_run_packets"][0]["proposed_events"][0]["timezone"] = ""
    with pytest.raises(ValidationError, match="at least 1 character"):
        CalendarDryRunFixtureSet.model_validate(payload)


def test_live_calendar_id_or_event_id_fails_closed() -> None:
    payload = _fixture_payload()
    payload["dry_run_packets"][0]["proposed_events"][0]["calendar_id"] = "primary"
    with pytest.raises(ValidationError, match="Input should be None"):
        CalendarDryRunFixtureSet.model_validate(payload)

    payload = _fixture_payload()
    payload["dry_run_packets"][0]["proposed_events"][0]["event_id"] = "abc123xyz"
    with pytest.raises(ValidationError, match="Input should be None"):
        CalendarDryRunFixtureSet.model_validate(payload)


def test_proposed_events_cannot_authorize_any_live_effects() -> None:
    packet = load_resource_capability_calendar_fixtures().dry_run_packets[0]
    authority_fields = [
        "google_calendar_api_authorized",
        "calendar_events_insert_authorized",
        "calendar_events_patch_authorized",
        "calendar_events_delete_authorized",
        "calendar_send_updates_authorized",
        "calendar_attendee_authorized",
        "calendar_conference_data_authorized",
        "calendar_notification_authorized",
        "calendar_availability_promise_authorized",
        "outbound_email_authorized",
        "automated_email_send_authorized",
        "gmail_draft_create_authorized",
        "smtp_send_authorized",
        "live_mail_mutation_authorized",
        "live_calendar_write_authorized",
        "payment_movement_authorized",
        "public_offer_authorized",
        "public_claim_upgrade_authorized",
        "provider_api_execution_authorized",
        "provider_credentials_authorized",
        "runtime_authorized",
        "service_execution_authorized",
        "external_action_authorized",
        "task_file_write_authorized",
        "dispatch_authorized",
    ]
    rows = [packet, *packet.extractions, *packet.proposed_events]

    for row in rows:
        for field in authority_fields:
            assert getattr(row, field) is False


def test_proposed_events_cannot_set_send_updates_other_than_none() -> None:
    payload = _fixture_payload()
    payload["dry_run_packets"][0]["proposed_events"][0]["send_updates"] = "all"
    with pytest.raises(ValidationError, match="Input should be 'none'"):
        CalendarDryRunFixtureSet.model_validate(payload)


def test_fixture_file_contains_no_pii_or_forbidden_material() -> None:
    text = FIXTURE_PATH.read_text(encoding="utf-8")

    forbidden_tokens = [
        "/home/",
        "~/.config",
        "raw_body",
        "body_plain",
        "body_html",
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
        "events.insert",
        "events.patch",
        "events.delete",
    ]
    for token in forbidden_tokens:
        assert token not in text


def test_calendar_module_has_no_forbidden_imports() -> None:
    source = Path("shared/resource_capability_calendar.py").read_text(encoding="utf-8")

    forbidden_tokens = [
        "googleapiclient",
        "google.oauth2",
        "agents.gcalendar_sync",
        "agents.mail_monitor",
        "agents.gmail_sync",
        "smtplib",
        "imaplib",
        "httpx",
        "requests",
        "os.environ",
        "pass_show",
        "events.insert",
        "events.patch",
        "events.delete",
        "events.list",
        "events.get",
        "users.messages.send",
        "users.drafts.create",
        "users.drafts.send",
        "payment_rails",
        "dispatch_task",
        "cc-claim",
        ".write_text(",
    ]
    for token in forbidden_tokens:
        assert token not in source


def test_unknown_obligation_ref_fails_closed(tmp_path: Path) -> None:
    payload = _fixture_payload()
    payload["dry_run_packets"][0]["extractions"][0]["obligation_ref"] = (
        "calendar-obligation:nonexistent"
    )
    payload["dry_run_packets"][0]["proposed_events"][0]["obligation_ref"] = (
        "calendar-obligation:nonexistent"
    )
    with pytest.raises(ResourceCapabilityCalendarError, match="unknown obligation"):
        load_resource_capability_calendar_fixtures(_write_fixture(tmp_path, payload))


def test_unknown_envelope_ref_fails_closed(tmp_path: Path) -> None:
    payload = _fixture_payload()
    payload["dry_run_packets"][0]["extractions"][0]["envelope_ref"] = "calendar-write:nonexistent"
    payload["dry_run_packets"][0]["proposed_events"][0]["envelope_ref"] = (
        "calendar-write:nonexistent"
    )
    with pytest.raises(ResourceCapabilityCalendarError, match="unknown envelope"):
        load_resource_capability_calendar_fixtures(_write_fixture(tmp_path, payload))


def test_unknown_source_signal_ref_fails_closed(tmp_path: Path) -> None:
    payload = _fixture_payload()
    payload["dry_run_packets"][0]["extractions"][0]["source_signal_refs"] = ["nonexistent:ref"]
    with pytest.raises(ResourceCapabilityCalendarError, match="source signal ref.*not found"):
        load_resource_capability_calendar_fixtures(_write_fixture(tmp_path, payload))


def test_refs_reject_absolute_paths_and_raw_email_addresses() -> None:
    extraction = load_resource_capability_calendar_fixtures().dry_run_packets[0].extractions[0]

    payload = extraction.model_dump(mode="json")
    payload["evidence_refs"] = ["/private/absolute"]
    with pytest.raises(ValidationError, match="repo-relative or symbolic"):
        CalendarDryRunExtraction.model_validate(payload)

    payload = extraction.model_dump(mode="json")
    payload["evidence_refs"] = ["sender@example.com"]
    with pytest.raises(ValidationError, match="raw email addresses"):
        CalendarDryRunExtraction.model_validate(payload)


def test_extraction_without_matching_proposed_event_fails() -> None:
    payload = _fixture_payload()
    payload["dry_run_packets"][0]["proposed_events"] = [
        payload["dry_run_packets"][0]["proposed_events"][0]
    ]
    with pytest.raises(ValidationError, match="extractions require proposed event artifacts"):
        CalendarDryRunFixtureSet.model_validate(payload)


def test_proposed_event_obligation_ref_mismatch_fails() -> None:
    payload = _fixture_payload()
    payload["dry_run_packets"][0]["proposed_events"][0]["obligation_ref"] = (
        "calendar-obligation:other"
    )
    with pytest.raises(ValidationError, match="obligation_ref mismatch"):
        CalendarDryRunFixtureSet.model_validate(payload)


def test_four_source_signal_kinds_are_covered() -> None:
    fixtures = load_resource_capability_calendar_fixtures()
    packet = fixtures.dry_run_packets[0]
    kinds = {e.source_kind.value for e in packet.extractions}
    assert "resource_expiry" in kinds
    assert "correspondence_followup" in kinds
    assert "autonomy_debt_recurrence" in kinds
    assert "semantic_transaction_waiting_state" in kinds


def test_whitespace_only_timezone_fails_closed() -> None:
    extraction = load_resource_capability_calendar_fixtures().dry_run_packets[0].extractions[0]
    payload = extraction.model_dump(mode="json")
    payload["timezone"] = "   "
    with pytest.raises(ValidationError, match="timezone must not be empty"):
        CalendarDryRunExtraction.model_validate(payload)


def test_escalation_artifacts_require_operator_review() -> None:
    artifact = load_resource_capability_calendar_fixtures().dry_run_packets[0].proposed_events[1]
    assert artifact.authority_level.value == "escalate"
    assert artifact.operator_review_required is True

    payload = artifact.model_dump(mode="json")
    payload["operator_review_required"] = False
    with pytest.raises(ValidationError, match="escalation artifacts require operator review"):
        ProposedEventArtifact.model_validate(payload)
