"""Private expected-correspondence dry-run contracts.

This module validates dry-run classifications and response artifacts over local
resource-capability fixtures. It does not import mail runtimes, read live
mailboxes, create drafts, send email, mutate labels, call providers, read
credentials, write calendars, publish claims, start services, or move money.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.resource_capability import (
    AuthenticationState,
    EmailAutonomyEvent,
    ExpectedCorrespondenceEnvelope,
    ExpectedMailCandidate,
    HandlingDecision,
    PublicClaimCeiling,
    ReplyTier,
    load_resource_capability_fixtures,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RESOURCE_CAPABILITY_CORRESPONDENCE_FIXTURES = (
    REPO_ROOT / "config" / "resource-capability-correspondence-fixtures.json"
)

TEXT_BEARING_ARTIFACT_KINDS = frozenset({"unsent_draft", "hard_refusal_notice"})
DISCLOSURE_TOKENS = frozenset({"automated", "hapax", "operations"})
FORBIDDEN_TEXT_TOKENS = frozenset(
    {
        "i feel",
        "i understand how you feel",
        "i personally",
        "human reviewed",
        "legal advice",
        "tax advice",
        "we can schedule",
        "i promise",
        "partnered with",
        "endorsed by",
        "approved by",
    }
)


class ResourceCapabilityCorrespondenceError(ValueError):
    """Raised when correspondence dry-run fixtures cannot be loaded safely."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CorrespondenceArtifactKind(StrEnum):
    UNSENT_DRAFT = "unsent_draft"
    SUPPRESSED_REPLY = "suppressed_reply"
    HARD_REFUSAL_NOTICE = "hard_refusal_notice"
    REPORT_ONLY_RECORD = "report_only_record"


class CorrespondenceDryRunDecision(StrEnum):
    REPORT_ONLY = "report_only"
    SUPPRESS_REPLY = "suppress_reply"
    DRAFT_FOR_OPERATOR_REVIEW = "draft_for_operator_review"
    HARD_REFUSAL = "hard_refusal"


class CorrespondenceAuthorityBlock(StrictModel):
    """All live mail/account/provider effects are forbidden in this dry run."""

    outbound_email_authorized: Literal[False] = False
    automated_email_send_authorized: Literal[False] = False
    gmail_draft_create_authorized: Literal[False] = False
    smtp_send_authorized: Literal[False] = False
    provider_api_execution_authorized: Literal[False] = False
    credential_lookup_authorized: Literal[False] = False
    live_mail_mutation_authorized: Literal[False] = False
    label_mutation_authorized: Literal[False] = False
    thread_mutation_authorized: Literal[False] = False
    live_calendar_write_authorized: Literal[False] = False
    payment_movement_authorized: Literal[False] = False
    public_offer_authorized: Literal[False] = False
    public_claim_upgrade_authorized: Literal[False] = False
    public_projection_allowed: Literal[False] = False
    runtime_feeder_execution_authorized: Literal[False] = False
    service_execution_authorized: Literal[False] = False
    task_file_write_authorized: Literal[False] = False
    coordinator_send_authorized: Literal[False] = False
    external_action_authorized: Literal[False] = False


class ExpectedCorrespondenceClassification(CorrespondenceAuthorityBlock):
    """Private classification of one expected mail candidate."""

    classification_id: str
    envelope_ref: str
    candidate_ref: str
    email_autonomy_event_ref: str
    source_account: str
    original_recipient_alias: str
    label: str
    expected_class: str
    authentication_state: AuthenticationState
    confidence: float = Field(ge=0, le=1)
    reply_tier: ReplyTier
    handling_decision: HandlingDecision
    dry_run_decision: CorrespondenceDryRunDecision
    commercial_class: str
    disclosure_required: Literal[True] = True
    suppression_checked: Literal[True] = True
    claims_checked: Literal[True] = True
    rate_limit_checked: Literal[True] = True
    mail_loop_policy_checked: Literal[True] = True
    body_quote_allowed: Literal[False] = False
    evidence_refs: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _classification_is_private_and_coherent(self) -> Self:
        _reject_private_or_identity_refs(
            [
                self.envelope_ref,
                self.candidate_ref,
                self.email_autonomy_event_ref,
                self.source_account,
                self.original_recipient_alias,
                self.label,
                *self.evidence_refs,
            ],
            "expected correspondence classification",
        )
        if self.reply_tier is ReplyTier.REPORT_ONLY:
            if self.dry_run_decision is not CorrespondenceDryRunDecision.REPORT_ONLY:
                raise ValueError("REPORT_ONLY envelopes require report_only dry-run decision")
            if self.handling_decision is not HandlingDecision.NO_RESPONSE:
                raise ValueError("REPORT_ONLY envelopes require no_response handling")
        if self.authentication_state is AuthenticationState.FAILED:
            if self.dry_run_decision not in {
                CorrespondenceDryRunDecision.SUPPRESS_REPLY,
                CorrespondenceDryRunDecision.HARD_REFUSAL,
            }:
                raise ValueError("failed authentication cannot proceed to response drafting")
        return self


class DryRunResponseArtifact(CorrespondenceAuthorityBlock):
    """Private response artifact; it never creates a live Gmail/SMTP draft."""

    artifact_id: str
    artifact_kind: CorrespondenceArtifactKind
    from_classification_id: str
    envelope_ref: str
    message_ref: str
    template_id: str | None = None
    response_body: str | None = None
    disclosure_text: str
    auto_submitted_policy: str
    list_reply_policy: str
    body_quote_included: Literal[False] = False
    claims_checked: Literal[True] = True
    suppression_checked: Literal[True] = True
    rate_limit_checked: Literal[True] = True
    send_allowed: Literal[False] = False
    draft_create_allowed: Literal[False] = False
    operator_review_required: bool
    fail_closed_reason: str | None = None
    evidence_refs: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _artifact_cannot_be_live_mail(self) -> Self:
        _reject_private_or_identity_refs(
            [
                self.from_classification_id,
                self.envelope_ref,
                self.message_ref,
                *self.evidence_refs,
            ],
            "dry-run response artifact",
        )

        text_bearing = self.artifact_kind.value in TEXT_BEARING_ARTIFACT_KINDS
        if text_bearing:
            if not self.response_body:
                raise ValueError("text-bearing response artifacts require response_body")
            _validate_response_text(self.response_body, self.disclosure_text)
        else:
            if self.response_body is not None:
                raise ValueError("suppressed/report-only artifacts cannot carry response_body")

        if self.artifact_kind is CorrespondenceArtifactKind.REPORT_ONLY_RECORD:
            if self.template_id is not None:
                raise ValueError("report-only artifacts cannot select templates")
            if self.operator_review_required:
                raise ValueError("report-only artifacts cannot imply operator review")
            if not self.fail_closed_reason:
                raise ValueError("report-only artifacts require fail-closed reason")
        return self


class ExpectedCorrespondenceDryRunPacket(CorrespondenceAuthorityBlock):
    """Complete private dry-run packet for expected correspondence."""

    schema_version: Literal[1] = 1
    packet_id: str
    evaluated_at: str
    authority_source: Literal["isap:resource-capability-expected-correspondence-dry-run-20260509"]
    generated_from: list[str] = Field(min_length=1)
    source_fixture_refs: list[str] = Field(min_length=1)
    privacy_scope: Literal["private"] = "private"
    consumer_permission_after: Literal["private_correspondence_dry_run_tests_only"]
    classifications: list[ExpectedCorrespondenceClassification] = Field(min_length=1)
    response_artifacts: list[DryRunResponseArtifact] = Field(min_length=1)
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
            raise ValueError(
                f"correspondence packet missing generated_from refs: {sorted(missing)}"
            )

        _reject_private_or_identity_refs(
            [*self.generated_from, *self.source_fixture_refs, *self.evidence_refs],
            "expected correspondence packet",
        )

        classification_ids = [row.classification_id for row in self.classifications]
        if len(classification_ids) != len(set(classification_ids)):
            raise ValueError("classification_id values must be unique")

        classification_by_id = {row.classification_id: row for row in self.classifications}
        artifact_classification_ids = {
            artifact.from_classification_id for artifact in self.response_artifacts
        }
        missing_artifacts = set(classification_by_id) - artifact_classification_ids
        if missing_artifacts:
            raise ValueError(
                f"classifications require response artifacts: {sorted(missing_artifacts)}"
            )

        for artifact in self.response_artifacts:
            classification = classification_by_id[artifact.from_classification_id]
            if artifact.envelope_ref != classification.envelope_ref:
                raise ValueError(f"{artifact.artifact_id} envelope mismatch")
            if classification.reply_tier is ReplyTier.REPORT_ONLY:
                if artifact.artifact_kind is not CorrespondenceArtifactKind.REPORT_ONLY_RECORD:
                    raise ValueError(
                        "REPORT_ONLY classifications can only produce report-only records"
                    )
                if artifact.response_body is not None:
                    raise ValueError("REPORT_ONLY classifications cannot produce response text")
        return self


class ExpectedCorrespondenceDryRunFixtureSet(StrictModel):
    """Private fixture set for RC-005 expected-correspondence dry runs."""

    schema_version: Literal[1] = 1
    fixture_set_id: str
    consumer_permission_after: Literal["private_correspondence_dry_run_tests_only"]
    dry_run_packets: list[ExpectedCorrespondenceDryRunPacket] = Field(min_length=1)

    @model_validator(mode="after")
    def _fixture_set_stays_private(self) -> Self:
        if any(packet.outbound_email_authorized for packet in self.dry_run_packets):
            raise ValueError("dry-run packets cannot authorize outbound email")
        if any(packet.gmail_draft_create_authorized for packet in self.dry_run_packets):
            raise ValueError("dry-run packets cannot authorize Gmail drafts")
        if any(packet.provider_api_execution_authorized for packet in self.dry_run_packets):
            raise ValueError("dry-run packets cannot authorize provider execution")
        return self


def _reject_private_or_identity_refs(refs: list[str], label: str) -> None:
    if any(ref.startswith(("/", "~")) for ref in refs):
        raise ValueError(f"{label} refs must stay repo-relative or symbolic")
    if any("@" in ref for ref in refs):
        raise ValueError(f"{label} refs must not contain raw email addresses")


def _validate_response_text(response_body: str, disclosure_text: str) -> None:
    lowered_body = response_body.lower()
    lowered_disclosure = disclosure_text.lower()
    if not DISCLOSURE_TOKENS.issubset(set(lowered_disclosure.replace(";", " ").split())):
        raise ValueError("response artifacts require automated Hapax operations disclosure")
    for token in FORBIDDEN_TEXT_TOKENS:
        if token in lowered_body:
            raise ValueError(f"response artifact contains forbidden text token: {token}")


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ResourceCapabilityCorrespondenceError(f"{path} did not contain a JSON object")
    return payload


def _validate_against_local_sources(fixtures: ExpectedCorrespondenceDryRunFixtureSet) -> None:
    resource_fixtures = load_resource_capability_fixtures()
    envelopes: dict[str, ExpectedCorrespondenceEnvelope] = {
        envelope.envelope_id: envelope
        for envelope in resource_fixtures.expected_correspondence_envelopes
    }
    candidates: dict[str, ExpectedMailCandidate] = {
        candidate.message_id_hash: candidate
        for candidate in resource_fixtures.expected_mail_candidates
    }
    events: dict[str, EmailAutonomyEvent] = {
        event.event_id: event for event in resource_fixtures.email_autonomy_events
    }

    for packet in fixtures.dry_run_packets:
        classifications_by_id = {
            classification.classification_id: classification
            for classification in packet.classifications
        }
        for classification in packet.classifications:
            envelope = envelopes.get(classification.envelope_ref)
            candidate = candidates.get(classification.candidate_ref)
            event = events.get(classification.email_autonomy_event_ref)
            if envelope is None:
                raise ResourceCapabilityCorrespondenceError(
                    f"{classification.classification_id} references unknown envelope"
                )
            if candidate is None:
                raise ResourceCapabilityCorrespondenceError(
                    f"{classification.classification_id} references unknown candidate"
                )
            if event is None:
                raise ResourceCapabilityCorrespondenceError(
                    f"{classification.classification_id} references unknown email event"
                )
            _validate_classification_sources(classification, envelope, candidate, event)

        for artifact in packet.response_artifacts:
            classification = classifications_by_id[artifact.from_classification_id]
            envelope = envelopes[classification.envelope_ref]
            if envelope.reply_tier is ReplyTier.REPORT_ONLY:
                if artifact.artifact_kind is not CorrespondenceArtifactKind.REPORT_ONLY_RECORD:
                    raise ResourceCapabilityCorrespondenceError(
                        f"{artifact.artifact_id} violates REPORT_ONLY envelope"
                    )
            if (
                artifact.template_id is not None
                and artifact.template_id not in envelope.allowed_templates
            ):
                raise ResourceCapabilityCorrespondenceError(
                    f"{artifact.artifact_id} uses template outside envelope"
                )


def _validate_classification_sources(
    classification: ExpectedCorrespondenceClassification,
    envelope: ExpectedCorrespondenceEnvelope,
    candidate: ExpectedMailCandidate,
    event: EmailAutonomyEvent,
) -> None:
    if classification.source_account not in envelope.allowed_accounts:
        raise ResourceCapabilityCorrespondenceError(
            f"{classification.classification_id} source account outside envelope"
        )
    if classification.label not in envelope.allowed_aliases_or_labels:
        raise ResourceCapabilityCorrespondenceError(
            f"{classification.classification_id} label outside envelope"
        )
    if classification.expected_class not in envelope.message_classes:
        raise ResourceCapabilityCorrespondenceError(
            f"{classification.classification_id} message class outside envelope"
        )
    if classification.confidence < envelope.auth_confidence_minimum:
        raise ResourceCapabilityCorrespondenceError(
            f"{classification.classification_id} confidence below envelope minimum"
        )
    if envelope.public_claim_ceiling is not PublicClaimCeiling.NONE:
        raise ResourceCapabilityCorrespondenceError(
            f"{classification.classification_id} envelope cannot raise public claim ceiling"
        )
    if classification.reply_tier is not envelope.reply_tier:
        raise ResourceCapabilityCorrespondenceError(
            f"{classification.classification_id} reply tier mismatch"
        )
    if candidate.source_account != classification.source_account:
        raise ResourceCapabilityCorrespondenceError(
            f"{classification.classification_id} candidate source account mismatch"
        )
    if candidate.original_recipient != classification.original_recipient_alias:
        raise ResourceCapabilityCorrespondenceError(
            f"{classification.classification_id} candidate recipient mismatch"
        )
    if candidate.label != classification.label:
        raise ResourceCapabilityCorrespondenceError(
            f"{classification.classification_id} candidate label mismatch"
        )
    if candidate.expected_class != classification.expected_class:
        raise ResourceCapabilityCorrespondenceError(
            f"{classification.classification_id} candidate class mismatch"
        )
    if event.message_ref != candidate.message_id_hash:
        raise ResourceCapabilityCorrespondenceError(
            f"{classification.classification_id} event message mismatch"
        )
    if event.response_sent:
        raise ResourceCapabilityCorrespondenceError(
            f"{classification.classification_id} source event cannot have sent response"
        )


def load_resource_capability_correspondence_fixtures(
    path: Path = RESOURCE_CAPABILITY_CORRESPONDENCE_FIXTURES,
) -> ExpectedCorrespondenceDryRunFixtureSet:
    """Load RC-005 correspondence fixtures, failing closed on malformed data."""

    try:
        fixtures = ExpectedCorrespondenceDryRunFixtureSet.model_validate(_load_json_object(path))
        _validate_against_local_sources(fixtures)
        return fixtures
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ResourceCapabilityCorrespondenceError(
            f"invalid resource capability correspondence fixtures at {path}: {exc}"
        ) from exc


_PYDANTIC_DYNAMIC_ENTRYPOINTS = (
    ExpectedCorrespondenceClassification._classification_is_private_and_coherent,
    DryRunResponseArtifact._artifact_cannot_be_live_mail,
    ExpectedCorrespondenceDryRunPacket._packet_contract,
    ExpectedCorrespondenceDryRunFixtureSet._fixture_set_stays_private,
)


__all__ = [
    "RESOURCE_CAPABILITY_CORRESPONDENCE_FIXTURES",
    "CorrespondenceArtifactKind",
    "CorrespondenceDryRunDecision",
    "DryRunResponseArtifact",
    "ExpectedCorrespondenceClassification",
    "ExpectedCorrespondenceDryRunFixtureSet",
    "ExpectedCorrespondenceDryRunPacket",
    "ResourceCapabilityCorrespondenceError",
    "load_resource_capability_correspondence_fixtures",
]
