"""Grant attestation operating-system contract.

This module composes the institutional-fit registry, opportunity scout, and
application-obligation refusal gate into one deterministic lifecycle read model:
scout -> fit check -> evidence packet -> draft -> operator attestation boundary
-> submit/refuse -> outcome.

The contract is intentionally private/support-facing. It prepares application
state and evidence references, but it cannot grant public release,
monetization, institutional-public claims, or fake affiliation authority.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.application_obligation_refusal import (
    OperatorAction,
    RefusalReason,
    evaluate_application_obligation,
)
from shared.grant_opportunity_scout import (
    GrantOpportunityFixtureSet,
    GrantOpportunityRecord,
    evaluate_grant_opportunity,
    load_grant_opportunity_fixtures,
)
from shared.institutional_fit_source_registry import (
    InstitutionalFitSourceRegistry,
    RefusalTrigger,
    SourceRow,
    default_registry,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRANT_OS_FIXTURE_PATH = (
    REPO_ROOT / "config" / "grant-attestation-operating-system-fixtures.json"
)

type GrantOperatingLifecycleState = Literal[
    "discovered",
    "eligible",
    "refused",
    "drafted",
    "ready_for_attestation",
    "submitted",
    "won",
    "lost",
    "disbursed",
    "follow_up",
]
type AttestationState = Literal["not_required", "required_pending_operator", "attested"]
type DeadlineStatus = Literal["no_deadline", "future", "due_soon", "due_now", "past_due"]

LIFECYCLE_SEQUENCE: tuple[GrantOperatingLifecycleState, ...] = (
    "discovered",
    "eligible",
    "refused",
    "drafted",
    "ready_for_attestation",
    "submitted",
    "won",
    "lost",
    "disbursed",
    "follow_up",
)
OUTCOME_STATES: frozenset[GrantOperatingLifecycleState] = frozenset(
    {"submitted", "won", "lost", "disbursed", "follow_up"}
)


class GrantOperatingSystemModel(BaseModel):
    """Frozen base for grant operating-system models."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class FundingEvidenceIntake(GrantOperatingSystemModel):
    """Evidence inputs consumed by the grant operating-system draft layer."""

    reusable_evidence_packet_refs: tuple[str, ...] = Field(min_length=1)
    demo_kit_refs: tuple[str, ...] = Field(min_length=1)
    n1_methodology_refs: tuple[str, ...] = Field(min_length=1)
    public_event_proof_refs: tuple[str, ...] = Field(min_length=1)
    scout_evidence_packet_refs: tuple[str, ...] = Field(min_length=1)
    privacy_labeled: Literal[True] = True
    provenance_labeled: Literal[True] = True
    public_release_allowed: Literal[False] = False
    monetization_allowed: Literal[False] = False
    institutional_public_claim_allowed: Literal[False] = False

    def all_refs(self) -> tuple[str, ...]:
        """All evidence refs available to the draft packet."""

        return _dedupe_sorted(
            (
                *self.reusable_evidence_packet_refs,
                *self.demo_kit_refs,
                *self.n1_methodology_refs,
                *self.public_event_proof_refs,
                *self.scout_evidence_packet_refs,
            )
        )


class GrantOperatingFixture(GrantOperatingSystemModel):
    """Fixture row used to materialize a grant operating-system record."""

    fixture_id: str = Field(pattern=r"^[a-z0-9_]+$")
    opportunity_fixture_id: str = Field(pattern=r"^[a-z0-9_]+$")
    source_row_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    lifecycle_state: GrantOperatingLifecycleState
    evidence_intake: FundingEvidenceIntake
    draft_packet_ref: str | None = None
    operator_attestation_ref: str | None = None
    submitted_at: datetime | None = None
    follow_up_due_at: date | None = None
    outcome_evidence_refs: tuple[str, ...] = ()
    posterior_update_refs: tuple[str, ...] = ()
    stakeholder_report_refs: tuple[str, ...] = ()
    expected_lifecycle_state: GrantOperatingLifecycleState
    expected_refusal_reasons: tuple[RefusalReason, ...] = ()
    expected_operator_actions: tuple[OperatorAction, ...] = ()


class GrantOperatingFixtureSet(GrantOperatingSystemModel):
    """Canonical fixture packet for the operating-system contract."""

    schema_version: Literal[1]
    fixture_set_id: Literal["grant_attestation_operating_system"]
    source_refs: tuple[str, ...] = Field(min_length=1)
    fixtures: tuple[GrantOperatingFixture, ...] = Field(min_length=5)


class GrantOperatingRecord(GrantOperatingSystemModel):
    """One materialized grant/fellowship/residency operating-system row."""

    record_id: str = Field(pattern=r"^grant-os:[a-z0-9_]+$")
    source_row_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    source_row: SourceRow
    opportunity: GrantOpportunityRecord
    lifecycle_state: GrantOperatingLifecycleState
    evidence_intake: FundingEvidenceIntake
    draft_packet_ref: str | None = None
    operator_attestation_ref: str | None = None
    submitted_at: datetime | None = None
    follow_up_due_at: date | None = None
    outcome_evidence_refs: tuple[str, ...] = ()
    posterior_update_refs: tuple[str, ...] = ()
    stakeholder_report_refs: tuple[str, ...] = ()
    requires_operator_opportunity_chasing: Literal[False] = False
    public_release_allowed: Literal[False] = False
    monetization_allowed: Literal[False] = False
    institutional_public_claim_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _validate_lifecycle_guards(self) -> Self:
        if self.source_row.id != self.source_row_id:
            raise ValueError("source_row_id must match source_row.id")
        if (
            self.lifecycle_state
            in {
                "drafted",
                "ready_for_attestation",
                "submitted",
                "won",
                "lost",
                "disbursed",
                "follow_up",
            }
            and self.draft_packet_ref is None
        ):
            raise ValueError("drafted and later lifecycle states require draft_packet_ref")
        if self.lifecycle_state == "ready_for_attestation":
            if not self.opportunity.attestation.required:
                raise ValueError("ready_for_attestation requires a required attestation boundary")
            if self.operator_attestation_ref is not None:
                raise ValueError("ready_for_attestation must wait for the operator act")
        if (
            self.lifecycle_state in OUTCOME_STATES
            and self.opportunity.attestation.required
            and self.operator_attestation_ref is None
        ):
            raise ValueError("submitted/outcome states require operator_attestation_ref")
        if self.lifecycle_state in OUTCOME_STATES and not self.outcome_evidence_refs:
            raise ValueError("submitted/outcome states require outcome_evidence_refs")
        if self.lifecycle_state in OUTCOME_STATES and not self.posterior_update_refs:
            raise ValueError("submitted/outcome states require posterior_update_refs")
        if self.lifecycle_state in OUTCOME_STATES and not self.stakeholder_report_refs:
            raise ValueError("submitted/outcome states require stakeholder_report_refs")
        if self.lifecycle_state == "follow_up" and self.follow_up_due_at is None:
            raise ValueError("follow_up state requires follow_up_due_at")
        return self

    def attestation_state(self) -> AttestationState:
        """Current operator-attestation boundary state."""

        if not self.opportunity.attestation.required:
            return "not_required"
        if self.operator_attestation_ref is not None:
            return "attested"
        return "required_pending_operator"

    def deadline_status(self, *, today: date | None = None) -> DeadlineStatus:
        """Deadline state without creating an operator-chasing obligation."""

        if self.opportunity.deadline is None:
            return "no_deadline"
        today = today or datetime.now(tz=UTC).date()
        deadline = date.fromisoformat(self.opportunity.deadline)
        if deadline < today:
            return "past_due"
        if deadline == today:
            return "due_now"
        if deadline <= today + timedelta(days=14):
            return "due_soon"
        return "future"

    def follow_up_required(self, *, today: date | None = None) -> bool:
        """True when the record is in follow-up or the follow-up date has arrived."""

        if self.lifecycle_state == "follow_up":
            return True
        if self.follow_up_due_at is None:
            return False
        today = today or datetime.now(tz=UTC).date()
        return self.follow_up_due_at <= today


class GrantOperatingDecision(GrantOperatingSystemModel):
    """Evaluated read-model row for downstream grant/outcome consumers."""

    record_id: str
    lifecycle_state: GrantOperatingLifecycleState
    attestation_state: AttestationState
    submission_allowed: bool
    refusal_reasons: tuple[RefusalReason, ...]
    operator_actions: tuple[OperatorAction, ...]
    deadline_status: DeadlineStatus
    follow_up_required: bool
    evidence_refs: tuple[str, ...]
    outcome_evidence_refs: tuple[str, ...]
    posterior_update_refs: tuple[str, ...]
    stakeholder_report_refs: tuple[str, ...]
    operator_opportunity_chasing_required: Literal[False] = False
    public_release_allowed: Literal[False] = False
    monetization_allowed: Literal[False] = False
    institutional_public_claim_allowed: Literal[False] = False
    operator_visible_reason: str


def _dedupe_sorted[T: str](values: Iterable[T]) -> tuple[T, ...]:
    return tuple(sorted(set(values)))


def _source_refusal_reasons(
    source_row: SourceRow,
    *,
    active_refusal_triggers: Iterable[RefusalTrigger],
) -> tuple[RefusalReason, ...]:
    active = frozenset(active_refusal_triggers)
    if not (active & set(source_row.refusal_triggers)):
        return ()
    if "requires_institutional_affiliation" in source_row.refusal_triggers:
        return ("fake_affiliation",)
    return ("unknown_obligation",)


def evaluate_grant_operating_record(
    record: GrantOperatingRecord,
    *,
    today: date | None = None,
    active_refusal_triggers: Iterable[RefusalTrigger] = (),
) -> GrantOperatingDecision:
    """Evaluate one operating-system row against all feeder gates."""

    application_decision = evaluate_application_obligation(
        record.opportunity.application_opportunity()
    )
    scout_decision = evaluate_grant_opportunity(record.opportunity)
    source_refusal_reasons = _source_refusal_reasons(
        record.source_row,
        active_refusal_triggers=active_refusal_triggers,
    )
    refusal_reasons = _dedupe_sorted(
        (
            *application_decision.refusal_reasons,
            *scout_decision.refusal_reasons,
            *source_refusal_reasons,
        )
    )
    source_refused = bool(source_refusal_reasons)
    refused = (
        application_decision.decision == "refused"
        or scout_decision.queue_state == "refused"
        or source_refused
    )
    lifecycle_state: GrantOperatingLifecycleState = "refused" if refused else record.lifecycle_state
    attestation_state = record.attestation_state()
    submission_allowed = not refused and (
        not record.opportunity.attestation.required or attestation_state == "attested"
    )

    if refused:
        reason = "opportunity refused by obligation, scout, or source-fit policy"
    elif lifecycle_state == "ready_for_attestation":
        reason = "draft is ready; submission waits on one explicit operator attestation act"
    elif lifecycle_state in OUTCOME_STATES:
        reason = f"opportunity lifecycle is {lifecycle_state}; outcome evidence is stored"
    else:
        reason = f"opportunity lifecycle is {lifecycle_state}"

    return GrantOperatingDecision(
        record_id=record.record_id,
        lifecycle_state=lifecycle_state,
        attestation_state=attestation_state,
        submission_allowed=submission_allowed,
        refusal_reasons=refusal_reasons,
        operator_actions=_dedupe_sorted(
            (*application_decision.operator_actions, *scout_decision.operator_actions)
        ),
        deadline_status=record.deadline_status(today=today),
        follow_up_required=record.follow_up_required(today=today),
        evidence_refs=record.evidence_intake.all_refs(),
        outcome_evidence_refs=record.outcome_evidence_refs,
        posterior_update_refs=record.posterior_update_refs,
        stakeholder_report_refs=record.stakeholder_report_refs,
        operator_visible_reason=reason,
    )


def load_grant_operating_fixtures(
    path: Path = DEFAULT_GRANT_OS_FIXTURE_PATH,
) -> GrantOperatingFixtureSet:
    """Load and validate the canonical grant operating-system fixture packet."""

    return GrantOperatingFixtureSet.model_validate(json.loads(path.read_text(encoding="utf-8")))


def materialize_grant_operating_record(
    fixture: GrantOperatingFixture,
    *,
    opportunity_fixtures: GrantOpportunityFixtureSet | None = None,
    registry: InstitutionalFitSourceRegistry | None = None,
) -> GrantOperatingRecord:
    """Compose a fixture row with the scout fixtures and institutional registry."""

    opportunity_fixture_set = opportunity_fixtures or load_grant_opportunity_fixtures()
    source_registry = registry or default_registry()
    opportunity_by_fixture_id = {
        opportunity_fixture.fixture_id: opportunity_fixture.opportunity
        for opportunity_fixture in opportunity_fixture_set.fixtures
    }
    source_by_id = source_registry.by_id()

    try:
        opportunity = opportunity_by_fixture_id[fixture.opportunity_fixture_id]
    except KeyError as exc:
        raise ValueError(f"unknown opportunity fixture: {fixture.opportunity_fixture_id}") from exc

    try:
        source_row = source_by_id[fixture.source_row_id]
    except KeyError as exc:
        raise ValueError(f"unknown source row: {fixture.source_row_id}") from exc

    return GrantOperatingRecord(
        record_id=f"grant-os:{fixture.fixture_id}",
        source_row_id=fixture.source_row_id,
        source_row=source_row,
        opportunity=opportunity,
        lifecycle_state=fixture.lifecycle_state,
        evidence_intake=fixture.evidence_intake,
        draft_packet_ref=fixture.draft_packet_ref,
        operator_attestation_ref=fixture.operator_attestation_ref,
        submitted_at=fixture.submitted_at,
        follow_up_due_at=fixture.follow_up_due_at,
        outcome_evidence_refs=fixture.outcome_evidence_refs,
        posterior_update_refs=fixture.posterior_update_refs,
        stakeholder_report_refs=fixture.stakeholder_report_refs,
    )


__all__ = [
    "DEFAULT_GRANT_OS_FIXTURE_PATH",
    "LIFECYCLE_SEQUENCE",
    "FundingEvidenceIntake",
    "GrantOperatingDecision",
    "GrantOperatingFixture",
    "GrantOperatingFixtureSet",
    "GrantOperatingRecord",
    "evaluate_grant_operating_record",
    "load_grant_operating_fixtures",
    "materialize_grant_operating_record",
]
