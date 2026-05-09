"""Private calendar-obligation dry-run contracts.

This module validates dry-run calendar-obligation extractions and proposed-event
artifacts over local resource-capability and expected-correspondence fixtures.
It does not import Google Calendar API clients, read live calendars, create
events, send notifications, add attendees, promise availability, read
credentials, send email, move money, or start services.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.resource_capability import (
    AutonomyDebtEvent,
    CalendarObligation,
    CalendarScope,
    CalendarWriteEnvelope,
    ResourceOpportunity,
    ResourceReceipt,
    SemanticTransactionTrace,
    load_resource_capability_fixtures,
)
from shared.resource_capability_correspondence import (
    ExpectedCorrespondenceClassification,
    load_resource_capability_correspondence_fixtures,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RESOURCE_CAPABILITY_CALENDAR_FIXTURES = (
    REPO_ROOT / "config" / "resource-capability-calendar-fixtures.json"
)

LIVE_CALENDAR_ID_PREFIXES = frozenset({"primary", "group.calendar.google.com"})
FIXTURE_REF_PREFIXES = frozenset({"calendar-obligation:", "calendar-write:", "fixture:", "null"})


class ResourceCapabilityCalendarError(ValueError):
    """Raised when calendar dry-run fixtures cannot be loaded safely."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CalendarObligationSourceKind(StrEnum):
    RESOURCE_EXPIRY = "resource_expiry"
    CORRESPONDENCE_FOLLOWUP = "correspondence_followup"
    AUTONOMY_DEBT_RECURRENCE = "autonomy_debt_recurrence"
    SEMANTIC_TRANSACTION_WAITING_STATE = "semantic_transaction_waiting_state"


class CalendarDryRunAuthorityLevel(StrEnum):
    DRAFT_FOR_REVIEW = "draft_for_review"
    ESCALATE = "escalate"


class CalendarAuthorityBlock(StrictModel):
    """All live calendar/mail/provider/payment effects are forbidden."""

    google_calendar_api_authorized: Literal[False] = False
    calendar_events_insert_authorized: Literal[False] = False
    calendar_events_patch_authorized: Literal[False] = False
    calendar_events_delete_authorized: Literal[False] = False
    calendar_send_updates_authorized: Literal[False] = False
    calendar_attendee_authorized: Literal[False] = False
    calendar_conference_data_authorized: Literal[False] = False
    calendar_notification_authorized: Literal[False] = False
    calendar_availability_promise_authorized: Literal[False] = False
    outbound_email_authorized: Literal[False] = False
    automated_email_send_authorized: Literal[False] = False
    gmail_draft_create_authorized: Literal[False] = False
    smtp_send_authorized: Literal[False] = False
    live_mail_mutation_authorized: Literal[False] = False
    live_calendar_write_authorized: Literal[False] = False
    payment_movement_authorized: Literal[False] = False
    public_offer_authorized: Literal[False] = False
    public_claim_upgrade_authorized: Literal[False] = False
    provider_api_execution_authorized: Literal[False] = False
    provider_credentials_authorized: Literal[False] = False
    runtime_authorized: Literal[False] = False
    service_execution_authorized: Literal[False] = False
    external_action_authorized: Literal[False] = False
    task_file_write_authorized: Literal[False] = False
    dispatch_authorized: Literal[False] = False


class CalendarDryRunExtraction(CalendarAuthorityBlock):
    """Private dry-run extraction of a calendar-obligation candidate."""

    extraction_id: str
    obligation_ref: str
    envelope_ref: str
    source_signal_refs: list[str] = Field(min_length=1)
    source_kind: CalendarObligationSourceKind
    source_account: str
    obligation_class: str
    date_time: str
    timezone: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    authority_level: CalendarDryRunAuthorityLevel
    calendar_scope: Literal[CalendarScope.PRIVATE_INTERNAL] = CalendarScope.PRIVATE_INTERNAL
    attendee_policy: Literal["blocked_none"] = "blocked_none"
    notification_policy: Literal["blocked_none"] = "blocked_none"
    conference_data_policy: Literal["blocked_none"] = "blocked_none"
    availability_promise: Literal[False] = False
    idempotency_key: str
    evidence_refs: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _extraction_stays_private_and_safe(self) -> Self:
        _reject_private_or_identity_refs(
            [
                self.obligation_ref,
                self.envelope_ref,
                *self.source_signal_refs,
                *self.evidence_refs,
            ],
            "calendar dry-run extraction",
        )
        if not self.timezone.strip():
            raise ValueError("timezone must not be empty or whitespace")
        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty")
        return self


class ProposedEventArtifact(CalendarAuthorityBlock):
    """Private proposed-event artifact; never creates a live calendar event."""

    artifact_id: str
    from_extraction_id: str
    obligation_ref: str
    envelope_ref: str
    proposed_summary: str
    proposed_start: str
    proposed_end: str | None = None
    timezone: str = Field(min_length=1)
    calendar_scope: Literal[CalendarScope.PRIVATE_INTERNAL] = CalendarScope.PRIVATE_INTERNAL
    attendee_policy: Literal["blocked_none"] = "blocked_none"
    notification_policy: Literal["blocked_none"] = "blocked_none"
    conference_data_policy: Literal["blocked_none"] = "blocked_none"
    availability_promise: Literal[False] = False
    authority_level: CalendarDryRunAuthorityLevel
    idempotency_key: str
    calendar_id: None = None
    event_id: None = None
    send_updates: Literal["none"] = "none"
    operator_review_required: bool = True
    fail_closed_reason: str | None = None
    evidence_refs: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _artifact_cannot_create_live_event(self) -> Self:
        _reject_private_or_identity_refs(
            [
                self.from_extraction_id,
                self.obligation_ref,
                self.envelope_ref,
                *self.evidence_refs,
            ],
            "proposed event artifact",
        )
        if self.calendar_id is not None:
            raise ValueError("proposed event artifact cannot set live calendar_id")
        if self.event_id is not None:
            raise ValueError("proposed event artifact cannot set live event_id")
        if not self.timezone.strip():
            raise ValueError("timezone must not be empty or whitespace")
        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty")
        if self.authority_level is CalendarDryRunAuthorityLevel.ESCALATE:
            if self.operator_review_required is not True:
                raise ValueError("escalation artifacts require operator review")
        return self


class CalendarDryRunPacket(CalendarAuthorityBlock):
    """Complete private dry-run packet for calendar obligations."""

    schema_version: Literal[1] = 1
    packet_id: str
    evaluated_at: str
    authority_source: Literal["isap:resource-capability-calendar-obligation-dry-run-20260509"]
    generated_from: list[str] = Field(min_length=1)
    source_fixture_refs: list[str] = Field(min_length=1)
    privacy_scope: Literal["private"] = "private"
    consumer_permission_after: Literal["private_calendar_dry_run_tests_only"]
    extractions: list[CalendarDryRunExtraction] = Field(min_length=1)
    proposed_events: list[ProposedEventArtifact] = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _packet_contract(self) -> Self:
        generated = set(self.generated_from)
        required_generated = {
            "shared/resource_capability.py",
            "config/resource-capability-fixtures.json",
        }
        if not required_generated.issubset(generated):
            missing = required_generated - generated
            raise ValueError(f"calendar packet missing generated_from refs: {sorted(missing)}")

        _reject_private_or_identity_refs(
            [*self.generated_from, *self.source_fixture_refs, *self.evidence_refs],
            "calendar dry-run packet",
        )

        extraction_ids = [e.extraction_id for e in self.extractions]
        if len(extraction_ids) != len(set(extraction_ids)):
            raise ValueError("extraction_id values must be unique")

        extraction_by_id = {e.extraction_id: e for e in self.extractions}
        artifact_extraction_ids = {a.from_extraction_id for a in self.proposed_events}
        missing_artifacts = set(extraction_by_id) - artifact_extraction_ids
        if missing_artifacts:
            raise ValueError(
                f"extractions require proposed event artifacts: {sorted(missing_artifacts)}"
            )

        for artifact in self.proposed_events:
            extraction = extraction_by_id.get(artifact.from_extraction_id)
            if extraction is None:
                raise ValueError(f"{artifact.artifact_id} references unknown extraction")
            if artifact.obligation_ref != extraction.obligation_ref:
                raise ValueError(f"{artifact.artifact_id} obligation_ref mismatch")
            if artifact.envelope_ref != extraction.envelope_ref:
                raise ValueError(f"{artifact.artifact_id} envelope_ref mismatch")
            if artifact.authority_level != extraction.authority_level:
                raise ValueError(f"{artifact.artifact_id} authority_level mismatch")
            if artifact.idempotency_key != extraction.idempotency_key:
                raise ValueError(f"{artifact.artifact_id} idempotency_key mismatch")
        return self


class CalendarDryRunFixtureSet(StrictModel):
    """Private fixture set for RC-006 calendar-obligation dry runs."""

    schema_version: Literal[1] = 1
    fixture_set_id: str
    consumer_permission_after: Literal["private_calendar_dry_run_tests_only"]
    dry_run_packets: list[CalendarDryRunPacket] = Field(min_length=1)

    @model_validator(mode="after")
    def _fixture_set_stays_private(self) -> Self:
        for packet in self.dry_run_packets:
            if packet.google_calendar_api_authorized:
                raise ValueError("dry-run packets cannot authorize Google Calendar API")
            if packet.live_calendar_write_authorized:
                raise ValueError("dry-run packets cannot authorize live calendar writes")
            if packet.external_action_authorized:
                raise ValueError("dry-run packets cannot authorize external actions")
            if packet.payment_movement_authorized:
                raise ValueError("dry-run packets cannot authorize payment movement")
            if packet.outbound_email_authorized:
                raise ValueError("dry-run packets cannot authorize outbound email")
        return self


def _reject_private_or_identity_refs(refs: list[str], label: str) -> None:
    for ref in refs:
        if ref is None:
            continue
        if ref.startswith(("/", "~")):
            raise ValueError(f"{label} refs must stay repo-relative or symbolic")
        if "@" in ref:
            raise ValueError(f"{label} refs must not contain raw email addresses")


def _is_live_calendar_ref(value: str | None) -> bool:
    if value is None:
        return False
    for prefix in LIVE_CALENDAR_ID_PREFIXES:
        if prefix in value:
            return True
    if value and not any(value.startswith(p) for p in FIXTURE_REF_PREFIXES):
        if "." in value or value.startswith("c") and len(value) > 20:
            return True
    return False


def _validate_against_local_sources(fixtures: CalendarDryRunFixtureSet) -> None:
    resource_fixtures = load_resource_capability_fixtures()

    obligations: dict[str, CalendarObligation] = {
        o.obligation_id: o for o in resource_fixtures.calendar_obligations
    }
    envelopes: dict[str, CalendarWriteEnvelope] = {
        e.envelope_id: e for e in resource_fixtures.calendar_write_envelopes
    }
    opportunities: dict[str, ResourceOpportunity] = {
        o.opportunity_id: o for o in resource_fixtures.opportunities
    }
    receipts: dict[str, ResourceReceipt] = {r.receipt_id: r for r in resource_fixtures.receipts}
    debt_events: dict[str, AutonomyDebtEvent] = {
        e.event_id: e for e in resource_fixtures.autonomy_debt_events
    }
    traces: dict[str, SemanticTransactionTrace] = {
        t.trace_id: t for t in resource_fixtures.semantic_transaction_traces
    }

    correspondence_classifications: dict[str, ExpectedCorrespondenceClassification] = {}
    try:
        corr_fixtures = load_resource_capability_correspondence_fixtures()
        for packet in corr_fixtures.dry_run_packets:
            for c in packet.classifications:
                correspondence_classifications[c.classification_id] = c
    except Exception:
        pass

    for packet in fixtures.dry_run_packets:
        for extraction in packet.extractions:
            obligation = obligations.get(extraction.obligation_ref)
            if obligation is None:
                raise ResourceCapabilityCalendarError(
                    f"{extraction.extraction_id} references unknown obligation"
                )

            envelope = envelopes.get(extraction.envelope_ref)
            if envelope is None:
                raise ResourceCapabilityCalendarError(
                    f"{extraction.extraction_id} references unknown envelope"
                )

            if extraction.confidence < envelope.source_confidence_minimum:
                raise ResourceCapabilityCalendarError(
                    f"{extraction.extraction_id} confidence {extraction.confidence} "
                    f"below envelope minimum {envelope.source_confidence_minimum}"
                )

            if obligation.calendar_id is not None and _is_live_calendar_ref(obligation.calendar_id):
                raise ResourceCapabilityCalendarError(
                    f"{extraction.extraction_id} obligation has live calendar_id"
                )
            if obligation.event_id is not None and _is_live_calendar_ref(obligation.event_id):
                raise ResourceCapabilityCalendarError(
                    f"{extraction.extraction_id} obligation has live event_id"
                )

            _validate_source_signal_refs(
                extraction,
                opportunities,
                receipts,
                debt_events,
                traces,
                correspondence_classifications,
            )

        for artifact in packet.proposed_events:
            if artifact.calendar_id is not None:
                raise ResourceCapabilityCalendarError(
                    f"{artifact.artifact_id} cannot set live calendar_id"
                )
            if artifact.event_id is not None:
                raise ResourceCapabilityCalendarError(
                    f"{artifact.artifact_id} cannot set live event_id"
                )


def _validate_source_signal_refs(
    extraction: CalendarDryRunExtraction,
    opportunities: dict[str, ResourceOpportunity],
    receipts: dict[str, ResourceReceipt],
    debt_events: dict[str, AutonomyDebtEvent],
    traces: dict[str, SemanticTransactionTrace],
    correspondence_classifications: dict[str, ExpectedCorrespondenceClassification],
) -> None:
    all_sources = (
        set(opportunities)
        | set(receipts)
        | set(debt_events)
        | set(traces)
        | set(correspondence_classifications)
    )
    for ref in extraction.source_signal_refs:
        if ref not in all_sources:
            raise ResourceCapabilityCalendarError(
                f"{extraction.extraction_id} source signal ref {ref} not found in any local fixture"
            )


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ResourceCapabilityCalendarError(f"{path} did not contain a JSON object")
    return payload


def load_resource_capability_calendar_fixtures(
    path: Path = RESOURCE_CAPABILITY_CALENDAR_FIXTURES,
) -> CalendarDryRunFixtureSet:
    """Load RC-006 calendar dry-run fixtures, failing closed on malformed data."""

    try:
        fixtures = CalendarDryRunFixtureSet.model_validate(_load_json_object(path))
        _validate_against_local_sources(fixtures)
        return fixtures
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ResourceCapabilityCalendarError(
            f"invalid resource capability calendar fixtures at {path}: {exc}"
        ) from exc


_PYDANTIC_DYNAMIC_ENTRYPOINTS = (
    CalendarDryRunExtraction._extraction_stays_private_and_safe,
    ProposedEventArtifact._artifact_cannot_create_live_event,
    CalendarDryRunPacket._packet_contract,
    CalendarDryRunFixtureSet._fixture_set_stays_private,
)


__all__ = [
    "RESOURCE_CAPABILITY_CALENDAR_FIXTURES",
    "CalendarAuthorityBlock",
    "CalendarDryRunAuthorityLevel",
    "CalendarDryRunExtraction",
    "CalendarDryRunFixtureSet",
    "CalendarDryRunPacket",
    "CalendarObligationSourceKind",
    "ProposedEventArtifact",
    "ResourceCapabilityCalendarError",
    "load_resource_capability_calendar_fixtures",
]
