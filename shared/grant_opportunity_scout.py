"""Grant/fellowship opportunity scout and attestation queue contract."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.application_obligation_refusal import (
    ApplicationDecision,
    ApplicationObligation,
    ApplicationOpportunity,
    AutomationFit,
    Disposition,
    OperatorAction,
    RefusalReason,
    evaluate_application_obligation,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRANT_FIXTURE_PATH = REPO_ROOT / "config" / "grant-opportunity-scout-fixtures.json"

type OpportunityKind = Literal[
    "grant",
    "fellowship",
    "compute_credit",
    "residency",
    "institutional_support",
]
type ScoutCadence = Literal["daily", "weekly", "monthly", "deadline_window"]
type ScoutAutomationMode = Literal[
    "api", "rss", "site_watch", "mailbox_parser", "operator_seeded_once"
]
type QueueLifecycleState = Literal[
    "discovered",
    "private_evidence",
    "operator_attestation_required",
    "submitted",
    "refused",
    "won",
    "lost",
    "disbursed",
    "follow_up_due",
]
type QueueDecisionState = Literal[
    "private_evidence",
    "operator_attestation_required",
    "submitted",
    "refused",
    "won",
    "lost",
    "disbursed",
    "follow_up_due",
]

TERMINAL_OR_EXTERNAL_STATES: frozenset[QueueLifecycleState] = frozenset(
    {"submitted", "won", "lost", "disbursed", "follow_up_due"}
)


class GrantScoutModel(BaseModel):
    """Frozen base for grant scout models."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class OpportunitySource(GrantScoutModel):
    """Machine-checkable source scanned by the opportunity scout."""

    source_id: str = Field(pattern=r"^[a-z0-9_.-]+$")
    name: str = Field(min_length=1)
    url: str = Field(min_length=1)
    cadence: ScoutCadence
    automation_mode: ScoutAutomationMode
    requires_manual_opportunity_chasing: Literal[False] = False
    source_refs: tuple[str, ...] = Field(min_length=1)


class AttachmentRequirement(GrantScoutModel):
    """Required packet attachment for an opportunity."""

    attachment_id: str = Field(pattern=r"^[a-z0-9_.-]+$")
    description: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    operator_attestation_required: bool = False


class OperatorAttestationRequirement(GrantScoutModel):
    """Legal attestation boundary for grant/fellowship work."""

    required: bool
    explicit_operator_act_only: Literal[True] = True
    operator_action: OperatorAction = "none"
    attestation_ref: str | None = None
    operator_visible_reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _operator_action_matches_requiredness(self) -> Self:
        if self.required and self.operator_action != "explicit_legal_attestation":
            raise ValueError("required attestation must use explicit_legal_attestation")
        if not self.required and self.operator_action == "explicit_legal_attestation":
            raise ValueError("explicit legal attestation action requires required=true")
        return self


class PrivateEvidencePacket(GrantScoutModel):
    """Private evidence bundle prepared for an application packet."""

    packet_id: str = Field(pattern=r"^[a-z0-9_.:-]+$")
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    n1_methodology_refs: tuple[str, ...] = Field(default_factory=tuple)
    public_event_refs: tuple[str, ...] = Field(default_factory=tuple)
    research_output_refs: tuple[str, ...] = Field(default_factory=tuple)
    corpus_ledger_refs: tuple[str, ...] = Field(default_factory=tuple)
    prior_application_outcome_refs: tuple[str, ...] = Field(default_factory=tuple)
    privacy_labeled: Literal[True] = True
    provenance_labeled: Literal[True] = True
    public_release_allowed: Literal[False] = False
    monetization_allowed: Literal[False] = False


class GrantOpportunityRecord(GrantScoutModel):
    """One opportunity row in the scout/attestation queue."""

    opportunity_id: str = Field(pattern=r"^[a-z0-9_.-]+$")
    title: str = Field(min_length=1)
    kind: OpportunityKind
    source_id: str = Field(pattern=r"^[a-z0-9_.-]+$")
    source_url: str = Field(min_length=1)
    discovered_at: str
    deadline: str | None = None
    eligibility: str = Field(min_length=1)
    amount_range: str = Field(min_length=1)
    obligations: tuple[ApplicationObligation, ...] = Field(min_length=1)
    required_attachments: tuple[AttachmentRequirement, ...] = Field(min_length=1)
    attestation: OperatorAttestationRequirement
    automation_feasibility: AutomationFit
    requires_fake_affiliation: bool = False
    requires_manual_opportunity_chasing: bool = False
    evidence_packet: PrivateEvidencePacket
    lifecycle_state: QueueLifecycleState = "discovered"
    urgent_fast_path_task_id: Literal["openai-safety-fellowship-fast-packet"] | None = None
    target_family: Literal["grants_fellowships"] = "grants_fellowships"
    readiness_state_ceiling: Literal["private-evidence"] = "private-evidence"
    public_release_allowed: Literal[False] = False
    monetization_allowed: Literal[False] = False
    institutional_public_claim_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _validate_private_evidence_contract(self) -> Self:
        if self.urgent_fast_path_task_id and self.opportunity_id != self.urgent_fast_path_task_id:
            raise ValueError("urgent fast path task id must match the opportunity id")
        if self.attestation.required and not any(
            obligation.class_id == "legal_attestation" for obligation in self.obligations
        ):
            raise ValueError("required legal attestation needs a legal_attestation obligation")
        return self

    def application_opportunity(self) -> ApplicationOpportunity:
        """Convert this queue row into the shared obligation-refusal gate input."""

        return ApplicationOpportunity(
            opportunity_id=self.opportunity_id,
            title=self.title,
            obligations=self.obligations,
            requires_fake_affiliation=self.requires_fake_affiliation,
            requires_manual_opportunity_chasing=self.requires_manual_opportunity_chasing,
        )


class GrantOpportunityDecision(GrantScoutModel):
    """Machine-readable decision emitted by the queue."""

    opportunity_id: str
    queue_state: QueueDecisionState
    application_decision: Disposition
    refusal_reasons: tuple[RefusalReason, ...]
    operator_actions: tuple[OperatorAction, ...]
    evidence_packet_refs: tuple[str, ...]
    private_evidence_allowed: Literal[True] = True
    public_release_allowed: Literal[False] = False
    monetization_allowed: Literal[False] = False
    institutional_public_claim_allowed: Literal[False] = False
    handled_by_fast_path_task: bool = False
    operator_visible_reason: str


class GrantOpportunityFixture(GrantScoutModel):
    """Fixture row with an expected queue decision."""

    fixture_id: str = Field(pattern=r"^[a-z0-9_]+$")
    opportunity: GrantOpportunityRecord
    expected_queue_state: QueueDecisionState
    expected_refusal_reasons: tuple[RefusalReason, ...] = ()
    expected_operator_actions: tuple[OperatorAction, ...] = ()
    expected_fast_path: bool = False


class GrantOpportunityFixtureSet(GrantScoutModel):
    """Fixture packet for the scout/attestation queue."""

    schema_version: Literal[1]
    fixture_set_id: Literal["grant_opportunity_scout_attestation_queue"]
    schema_ref: Literal["schemas/grant-opportunity-scout.schema.json"]
    source_refs: tuple[str, ...] = Field(min_length=1)
    scout_sources: tuple[OpportunitySource, ...] = Field(min_length=1)
    fixtures: tuple[GrantOpportunityFixture, ...] = Field(min_length=6)

    @model_validator(mode="after")
    def _validate_source_coverage(self) -> Self:
        source_ids = {source.source_id for source in self.scout_sources}
        for fixture in self.fixtures:
            if fixture.opportunity.source_id not in source_ids:
                raise ValueError(f"fixture source not declared: {fixture.opportunity.source_id}")
        return self


def _dedupe_sorted[T: str](values: Iterable[T]) -> tuple[T, ...]:
    return tuple(sorted(set(values)))


def evaluate_grant_opportunity(opportunity: GrantOpportunityRecord) -> GrantOpportunityDecision:
    """Evaluate one opportunity row against obligation and attestation policy."""

    application_decision: ApplicationDecision = evaluate_application_obligation(
        opportunity.application_opportunity()
    )
    if application_decision.decision == "refused":
        queue_state: QueueDecisionState = "refused"
        reason = application_decision.operator_visible_reason
    elif opportunity.lifecycle_state in TERMINAL_OR_EXTERNAL_STATES:
        queue_state = opportunity.lifecycle_state
        reason = f"opportunity lifecycle is already {opportunity.lifecycle_state}"
    elif (
        opportunity.attestation.required
        or "explicit_legal_attestation" in application_decision.operator_actions
    ):
        queue_state = "operator_attestation_required"
        reason = "private evidence packet is prepared; explicit operator attestation is required"
    else:
        queue_state = "private_evidence"
        reason = "private evidence packet is prepared without recurring operator labor"

    return GrantOpportunityDecision(
        opportunity_id=opportunity.opportunity_id,
        queue_state=queue_state,
        application_decision=application_decision.decision,
        refusal_reasons=application_decision.refusal_reasons,
        operator_actions=_dedupe_sorted(application_decision.operator_actions),
        evidence_packet_refs=(opportunity.evidence_packet.packet_id,),
        handled_by_fast_path_task=opportunity.urgent_fast_path_task_id is not None,
        operator_visible_reason=reason,
    )


def load_grant_opportunity_fixtures(
    path: Path = DEFAULT_GRANT_FIXTURE_PATH,
) -> GrantOpportunityFixtureSet:
    """Load and validate the canonical grant opportunity queue fixtures."""

    return GrantOpportunityFixtureSet.model_validate(json.loads(path.read_text(encoding="utf-8")))


__all__ = [
    "DEFAULT_GRANT_FIXTURE_PATH",
    "AttachmentRequirement",
    "GrantOpportunityDecision",
    "GrantOpportunityFixture",
    "GrantOpportunityFixtureSet",
    "GrantOpportunityRecord",
    "OperatorAttestationRequirement",
    "OpportunitySource",
    "PrivateEvidencePacket",
    "evaluate_grant_opportunity",
    "load_grant_opportunity_fixtures",
]
