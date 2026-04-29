"""Typed CapabilityOutcomeEnvelope fixtures.

This module pins the outcome vocabulary used between capability execution,
world witnesses, public-event adapters, and future affordance-learning
adapters. It is a contract surface only; it does not replace or mutate the
existing AffordancePipeline.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
CAPABILITY_OUTCOME_FIXTURES = REPO_ROOT / "config" / "capability-outcome-fixtures.json"

REQUIRED_OUTCOME_STATUSES = frozenset(
    {
        "success",
        "failure",
        "neutral_defer",
        "blocked",
        "refused",
        "stale",
        "missing",
        "inferred",
        "public_event_accepted",
    }
)

REQUIRED_NO_UPDATE_CASES = frozenset(
    {
        "selected_only",
        "commanded_only",
        "inferred",
        "stale",
        "missing",
    }
)

OUTCOME_ENVELOPE_REQUIRED_FIELDS = (
    "schema_version",
    "outcome_id",
    "created_at",
    "capability_id",
    "capability_name",
    "attempt_kind",
    "selection_ref",
    "selection_state",
    "command_ref",
    "route_ref",
    "substrate_refs",
    "programme_refs",
    "director_move_ref",
    "evidence_envelope_refs",
    "witness_refs",
    "expected_effect",
    "outcome_status",
    "execution_status",
    "manifestation_status",
    "claim_status",
    "public_event_status",
    "learning_update",
    "claim_posterior_update",
    "blocked_reasons",
    "refusal_or_correction_refs",
    "health_refs",
    "privacy_state",
    "rights_state",
    "freshness",
    "authority_ceiling",
    "witness_policy",
    "verified_success",
    "public_claim_evidence",
    "operator_visible_summary",
    "fixture_case",
)


class CapabilityOutcomeError(ValueError):
    """Raised when capability outcome fixtures cannot be loaded safely."""


class AttemptKind(StrEnum):
    OBSERVE = "observe"
    EXPRESS = "express"
    ACT = "act"
    ROUTE = "route"
    RECALL = "recall"
    COMMUNICATE = "communicate"
    REGULATE = "regulate"


class SelectionState(StrEnum):
    CANDIDATE_SCORED = "candidate_scored"
    SELECTED = "selected"
    SUPPRESSED = "suppressed"
    THRESHOLD_MISS = "threshold_miss"
    CONSENT_VETO = "consent_veto"
    MONETIZATION_VETO = "monetization_veto"
    NOT_SELECTED = "not_selected"


class OutcomeStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    NEUTRAL_DEFER = "neutral_defer"
    BLOCKED = "blocked"
    REFUSED = "refused"
    STALE = "stale"
    MISSING = "missing"
    INFERRED = "inferred"
    PUBLIC_EVENT_ACCEPTED = "public_event_accepted"


class ExecutionStatus(StrEnum):
    NOT_ATTEMPTED = "not_attempted"
    ACCEPTED = "accepted"
    APPLIED = "applied"
    QUEUED = "queued"
    WRITE_FAILED = "write_failed"
    TOOL_ERROR = "tool_error"
    TIMEOUT = "timeout"
    BLOCKED_BY_POLICY = "blocked_by_policy"
    DRY_RUN = "dry_run"
    UNKNOWN = "unknown"


class ManifestationStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    NOT_OBSERVED = "not_observed"
    OBSERVED_WITHOUT_WITNESS = "observed_without_witness"
    WITNESS_VERIFIED = "witness_verified"
    WITNESS_FAILED = "witness_failed"
    WITNESS_STALE = "witness_stale"
    WITNESS_UNAVAILABLE = "witness_unavailable"
    INFERRED_ONLY = "inferred_only"


class ClaimStatus(StrEnum):
    NOT_CLAIM_BEARING = "not_claim_bearing"
    PRIVATE_DRAFT = "private_draft"
    GATE_PASS = "gate_pass"
    GATE_FAIL = "gate_fail"
    DRY_RUN = "dry_run"
    REFUSAL = "refusal"
    CORRECTION_REQUIRED = "correction_required"
    POSTERIOR_UPDATED = "posterior_updated"
    POSTERIOR_NOT_ALLOWED = "posterior_not_allowed"


class PublicEventStatus(StrEnum):
    NOT_PUBLIC = "not_public"
    ELIGIBLE = "eligible"
    ACCEPTED = "accepted"
    HELD = "held"
    ARCHIVE_ONLY = "archive_only"
    DRY_RUN = "dry_run"
    BLOCKED = "blocked"
    PUBLISHED = "published"
    FAILED = "failed"


class LearningPolicy(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    NEUTRAL = "neutral"
    DEFER = "defer"


class LearningTarget(StrEnum):
    AFFORDANCE_ACTIVATION = "affordance_activation"
    CONTEXT_ASSOCIATION = "context_association"
    SURFACE_HEALTH = "surface_health"
    OPPORTUNITY_MODEL = "opportunity_model"
    NONE = "none"


class AuthorityCeiling(StrEnum):
    NO_CLAIM = "no_claim"
    INTERNAL_ONLY = "internal_only"
    SPECULATIVE = "speculative"
    EVIDENCE_BOUND = "evidence_bound"
    POSTERIOR_BOUND = "posterior_bound"
    PUBLIC_GATE_REQUIRED = "public_gate_required"


class PrivacyState(StrEnum):
    PUBLIC_SAFE = "public_safe"
    PRIVATE_ONLY = "private_only"
    DRY_RUN = "dry_run"
    ARCHIVE_ONLY = "archive_only"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class RightsState(StrEnum):
    PUBLIC_CLEAR = "public_clear"
    PRIVATE_ONLY = "private_only"
    AGGREGATE_ONLY = "aggregate_only"
    BLOCKED = "blocked"
    MISSING = "missing"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class FreshnessState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class WitnessPolicy(StrEnum):
    WITNESSED = "witnessed"
    INFERRED = "inferred"
    SELECTED_ONLY = "selected_only"
    COMMANDED_ONLY = "commanded_only"
    MISSING = "missing"
    STALE = "stale"
    PUBLIC_EVENT_ADAPTER = "public_event_adapter"
    FIXTURE_ONLY = "fixture_only"


class FixtureCase(StrEnum):
    WITNESSED_SUCCESS = "witnessed_success"
    WITNESSED_FAILURE = "witnessed_failure"
    NEUTRAL_DEFER = "neutral_defer"
    BLOCKED = "blocked"
    REFUSED = "refused"
    STALE = "stale"
    MISSING = "missing"
    INFERRED = "inferred"
    PUBLIC_EVENT_ACCEPTED = "public_event_accepted"
    SELECTED_ONLY = "selected_only"
    COMMANDED_ONLY = "commanded_only"


class ExpectedEffect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effect_id: str
    description: str
    witness_class: str
    public_claim_bearing: bool
    action_bearing: bool


class Freshness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: FreshnessState
    ttl_s: int | None = Field(default=None, ge=0)
    observed_age_s: int | None = Field(default=None, ge=0)
    source_ref: str | None = None
    checked_at: str

    @model_validator(mode="after")
    def _fresh_sources_need_age_and_ttl(self) -> Self:
        if self.state is FreshnessState.FRESH:
            if self.ttl_s is None or self.observed_age_s is None or self.source_ref is None:
                raise ValueError("fresh outcome requires ttl_s, observed_age_s, and source_ref")
            if self.observed_age_s > self.ttl_s:
                raise ValueError("fresh outcome observed_age_s cannot exceed ttl_s")
        return self


class LearningUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy: LearningPolicy
    allowed: bool
    target: LearningTarget
    reason: str
    required_witness_refs: list[str] = Field(default_factory=list)
    missing_witness_refs: list[str] = Field(default_factory=list)
    thompson_delta: float | None = None
    context_association_delta: float | None = None

    @model_validator(mode="after")
    def _no_target_when_update_not_allowed(self) -> Self:
        if not self.allowed and self.target is not LearningTarget.NONE:
            raise ValueError("disallowed learning updates must target none")
        if (
            self.allowed
            and self.policy is LearningPolicy.SUCCESS
            and not self.required_witness_refs
        ):
            raise ValueError("success learning requires required_witness_refs")
        return self


class ClaimPosteriorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool
    claim_ids: list[str] = Field(default_factory=list)
    evidence_envelope_refs: list[str] = Field(default_factory=list)
    gate_refs: list[str] = Field(default_factory=list)
    claim_engine_refs: list[str] = Field(default_factory=list)
    reason: str

    @model_validator(mode="after")
    def _allowed_claim_updates_need_evidence_and_gate(self) -> Self:
        if self.allowed and (
            not self.claim_ids or not self.evidence_envelope_refs or not self.gate_refs
        ):
            raise ValueError(
                "claim posterior updates require claim_ids, evidence_envelope_refs, and gate_refs"
            )
        return self


class VerifiedSuccess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: bool
    action: bool
    public: bool
    claim_posterior: bool


class PublicClaimEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: bool
    present: bool
    evidence_envelope_refs: list[str] = Field(default_factory=list)
    public_event_refs: list[str] = Field(default_factory=list)
    gate_refs: list[str] = Field(default_factory=list)
    note: str

    @model_validator(mode="after")
    def _present_public_claims_need_evidence_event_and_gate(self) -> Self:
        if self.present and (
            not self.evidence_envelope_refs or not self.public_event_refs or not self.gate_refs
        ):
            raise ValueError(
                "public claim evidence requires evidence_envelope_refs, public_event_refs, "
                "and gate_refs"
            )
        if self.required and not self.present:
            raise ValueError("required public claim evidence must be present")
        return self


class CapabilityOutcomeEnvelope(BaseModel):
    """Runtime-shaped capability outcome contract envelope."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    outcome_id: str
    created_at: str
    capability_id: str
    capability_name: str
    attempt_kind: AttemptKind
    selection_ref: str
    selection_state: SelectionState
    command_ref: str | None = None
    route_ref: str | None = None
    substrate_refs: list[str] = Field(default_factory=list)
    programme_refs: list[str] = Field(default_factory=list)
    director_move_ref: str | None = None
    evidence_envelope_refs: list[str] = Field(default_factory=list)
    witness_refs: list[str] = Field(default_factory=list)
    expected_effect: ExpectedEffect
    outcome_status: OutcomeStatus
    execution_status: ExecutionStatus
    manifestation_status: ManifestationStatus
    claim_status: ClaimStatus
    public_event_status: PublicEventStatus
    learning_update: LearningUpdate
    claim_posterior_update: ClaimPosteriorUpdate
    blocked_reasons: list[str] = Field(default_factory=list)
    refusal_or_correction_refs: list[str] = Field(default_factory=list)
    health_refs: list[str] = Field(default_factory=list)
    privacy_state: PrivacyState
    rights_state: RightsState
    freshness: Freshness
    authority_ceiling: AuthorityCeiling
    witness_policy: WitnessPolicy
    verified_success: VerifiedSuccess
    public_claim_evidence: PublicClaimEvidence
    operator_visible_summary: str
    fixture_case: FixtureCase

    @model_validator(mode="after")
    def _validate_outcome_learning_and_claims(self) -> Self:
        blockers = self.success_blockers()
        if self.validates_success() and blockers:
            raise ValueError(
                f"{self.outcome_id} validates success but blockers remain: " + ", ".join(blockers)
            )
        if self.fixture_case.value in REQUIRED_NO_UPDATE_CASES:
            if self.learning_update.allowed:
                raise ValueError(f"{self.outcome_id} no-update fixture cannot allow learning")
            if any(
                (
                    self.verified_success.capability,
                    self.verified_success.action,
                    self.verified_success.public,
                    self.verified_success.claim_posterior,
                )
            ):
                raise ValueError(f"{self.outcome_id} no-update fixture cannot verify success")
        if self.learning_update.allowed and self.learning_update.policy is LearningPolicy.SUCCESS:
            if not self.validates_success():
                raise ValueError(f"{self.outcome_id} success learning requires validated success")
            if not self.verified_success.capability:
                raise ValueError(f"{self.outcome_id} success learning requires capability success")
        if self.verified_success.action and not self._has_action_witness():
            raise ValueError(f"{self.outcome_id} verified action success requires action witness")
        if self.verified_success.public and not self._has_public_witness():
            raise ValueError(f"{self.outcome_id} verified public success requires public witness")
        if self.claim_posterior_update.allowed:
            if not self.public_claim_evidence.present:
                raise ValueError(
                    f"{self.outcome_id} claim posterior update requires public claim evidence"
                )
            if self.claim_status not in {
                ClaimStatus.GATE_PASS,
                ClaimStatus.POSTERIOR_UPDATED,
            }:
                raise ValueError(
                    f"{self.outcome_id} claim posterior update requires passing claim status"
                )
        if self.outcome_status is OutcomeStatus.BLOCKED and not self.blocked_reasons:
            raise ValueError(f"{self.outcome_id} blocked outcome requires blocked_reasons")
        if self.outcome_status is OutcomeStatus.REFUSED and not self.refusal_or_correction_refs:
            raise ValueError(
                f"{self.outcome_id} refused outcome requires refusal_or_correction_refs"
            )
        if self.outcome_status is OutcomeStatus.STALE:
            if self.freshness.state is not FreshnessState.STALE:
                raise ValueError(f"{self.outcome_id} stale outcome requires stale freshness")
            if self.manifestation_status is not ManifestationStatus.WITNESS_STALE:
                raise ValueError(f"{self.outcome_id} stale outcome requires stale witness")
        if self.outcome_status is OutcomeStatus.MISSING:
            if self.freshness.state is not FreshnessState.MISSING:
                raise ValueError(f"{self.outcome_id} missing outcome requires missing freshness")
            if self.manifestation_status is not ManifestationStatus.WITNESS_UNAVAILABLE:
                raise ValueError(f"{self.outcome_id} missing outcome requires unavailable witness")
        if self.outcome_status is OutcomeStatus.INFERRED:
            if self.witness_policy is not WitnessPolicy.INFERRED:
                raise ValueError(f"{self.outcome_id} inferred outcome requires inferred witness")
            if self.manifestation_status is not ManifestationStatus.INFERRED_ONLY:
                raise ValueError(
                    f"{self.outcome_id} inferred outcome requires inferred manifestation"
                )
        return self

    def success_blockers(self) -> list[str]:
        """Return reasons this outcome cannot validate capability success."""

        blockers: list[str] = []
        if self.fixture_case.value in REQUIRED_NO_UPDATE_CASES:
            blockers.append(f"fixture_case:{self.fixture_case.value}")
        if self.selection_state is not SelectionState.SELECTED:
            blockers.append(f"selection_state:{self.selection_state.value}")
        if self.execution_status not in {ExecutionStatus.ACCEPTED, ExecutionStatus.APPLIED}:
            blockers.append(f"execution_status:{self.execution_status.value}")
        if self.manifestation_status is not ManifestationStatus.WITNESS_VERIFIED:
            blockers.append(f"manifestation_status:{self.manifestation_status.value}")
        if self.freshness.state is not FreshnessState.FRESH:
            blockers.append(f"freshness:{self.freshness.state.value}")
        if self.witness_policy not in {
            WitnessPolicy.WITNESSED,
            WitnessPolicy.PUBLIC_EVENT_ADAPTER,
        }:
            blockers.append(f"witness_policy:{self.witness_policy.value}")
        if not self.witness_refs:
            blockers.append("witness_refs:missing")
        if self.blocked_reasons and self.outcome_status is not OutcomeStatus.REFUSED:
            blockers.append("blocked_reasons")
        return blockers

    def validates_success(self) -> bool:
        """Return true when the envelope can validate capability-level success."""

        return (
            self.outcome_status
            in {
                OutcomeStatus.SUCCESS,
                OutcomeStatus.PUBLIC_EVENT_ACCEPTED,
                OutcomeStatus.REFUSED,
            }
            and self.verified_success.capability
            and not self.success_blockers()
        )

    def allows_verified_public_or_action_success_update(self) -> bool:
        """Return true if public or action success can be updated from this envelope."""

        return (
            self.validates_success()
            and (self.verified_success.public or self.verified_success.action)
            and self.learning_update.allowed
            and self.learning_update.policy is LearningPolicy.SUCCESS
        )

    def allows_claim_posterior_update(self) -> bool:
        """Return true only when claim evidence and gate refs permit posterior update."""

        return self.claim_posterior_update.allowed and self.public_claim_evidence.present

    def _has_action_witness(self) -> bool:
        return (
            self.expected_effect.action_bearing
            and self.manifestation_status is ManifestationStatus.WITNESS_VERIFIED
            and bool(self.witness_refs)
        )

    def _has_public_witness(self) -> bool:
        return (
            self.public_event_status in {PublicEventStatus.ACCEPTED, PublicEventStatus.PUBLISHED}
            and self.public_claim_evidence.present
            and bool(self.public_claim_evidence.public_event_refs)
            and bool(self.public_claim_evidence.gate_refs)
        )


class OutcomeStatusFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: OutcomeStatus
    success_learning_allowed_without_witness: Literal[False] = False
    verified_public_success_without_claim_evidence: Literal[False] = False
    meaning: str
    failure_reason: str


class OutcomeSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_outcomes: int = Field(ge=0)
    by_status: dict[str, int]
    success_validated_count: int = Field(ge=0)
    learning_update_allowed_count: int = Field(ge=0)
    claim_posterior_update_allowed_count: int = Field(ge=0)
    public_success_update_allowed_count: int = Field(ge=0)


class CapabilityOutcomeFixtureSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    fixture_set_id: str
    schema_ref: Literal["schemas/capability-outcome-envelope.schema.json"]
    generated_from: list[str] = Field(min_length=1)
    declared_at: str
    producer: str
    outcome_statuses: list[OutcomeStatus] = Field(min_length=1)
    no_update_fixture_cases: list[FixtureCase] = Field(min_length=1)
    outcome_envelope_required_fields: list[str] = Field(min_length=1)
    status_fixtures: list[OutcomeStatusFixture] = Field(min_length=1)
    outcomes: list[CapabilityOutcomeEnvelope] = Field(min_length=1)
    summary: OutcomeSummary
    fail_closed_policy: dict[str, bool]

    @model_validator(mode="after")
    def _validate_contract_coverage(self) -> Self:
        status_values = {status.value for status in self.outcome_statuses}
        missing_statuses = REQUIRED_OUTCOME_STATUSES - status_values
        if missing_statuses:
            raise ValueError(
                "missing capability outcome statuses: " + ", ".join(sorted(missing_statuses))
            )

        fixture_statuses = {fixture.status.value for fixture in self.status_fixtures}
        missing_fixture_statuses = REQUIRED_OUTCOME_STATUSES - fixture_statuses
        if missing_fixture_statuses:
            raise ValueError(
                "missing capability outcome status fixtures: "
                + ", ".join(sorted(missing_fixture_statuses))
            )

        no_update_cases = {case.value for case in self.no_update_fixture_cases}
        missing_no_update_cases = REQUIRED_NO_UPDATE_CASES - no_update_cases
        if missing_no_update_cases:
            raise ValueError(
                "no_update_fixture_cases missing: " + ", ".join(sorted(missing_no_update_cases))
            )

        if set(self.outcome_envelope_required_fields) != set(OUTCOME_ENVELOPE_REQUIRED_FIELDS):
            raise ValueError("outcome_envelope_required_fields does not match typed contract")

        outcomes_by_status = {outcome.outcome_status.value for outcome in self.outcomes}
        missing_outcome_statuses = REQUIRED_OUTCOME_STATUSES - outcomes_by_status
        if missing_outcome_statuses:
            raise ValueError(
                "outcomes do not cover statuses: " + ", ".join(sorted(missing_outcome_statuses))
            )

        outcomes_by_case = {outcome.fixture_case.value for outcome in self.outcomes}
        missing_outcome_cases = REQUIRED_NO_UPDATE_CASES - outcomes_by_case
        if missing_outcome_cases:
            raise ValueError(
                "outcomes do not cover no-update cases: " + ", ".join(sorted(missing_outcome_cases))
            )

        expected_summary = OutcomeSummary(
            total_outcomes=len(self.outcomes),
            by_status={
                status.value: [outcome.outcome_status for outcome in self.outcomes].count(status)
                for status in sorted({outcome.outcome_status for outcome in self.outcomes})
            },
            success_validated_count=sum(outcome.validates_success() for outcome in self.outcomes),
            learning_update_allowed_count=sum(
                outcome.learning_update.allowed for outcome in self.outcomes
            ),
            claim_posterior_update_allowed_count=sum(
                outcome.allows_claim_posterior_update() for outcome in self.outcomes
            ),
            public_success_update_allowed_count=sum(
                outcome.allows_verified_public_or_action_success_update()
                for outcome in self.outcomes
            ),
        )
        if self.summary != expected_summary:
            raise ValueError("capability outcome summary does not match outcomes")

        if self.fail_closed_policy != {
            "selected_only_allows_success": False,
            "commanded_only_allows_success": False,
            "inferred_context_updates_success": False,
            "stale_witness_updates_success": False,
            "missing_witness_updates_success": False,
            "public_claim_without_evidence_updates_posterior": False,
            "capability_success_updates_claim_posterior_by_itself": False,
            "legacy_public_event_without_gate_counts_as_public_success": False,
        }:
            raise ValueError("fail_closed_policy must pin all outcome no-false-grounding gates")
        return self

    def outcomes_by_id(self) -> dict[str, CapabilityOutcomeEnvelope]:
        """Return fixture outcomes keyed by outcome id."""

        return {outcome.outcome_id: outcome for outcome in self.outcomes}

    def require_outcome(self, outcome_id: str) -> CapabilityOutcomeEnvelope:
        """Return a capability outcome or raise a fail-closed lookup error."""

        outcome = self.outcomes_by_id().get(outcome_id)
        if outcome is None:
            raise KeyError(f"unknown capability outcome fixture: {outcome_id}")
        return outcome

    def rows_for_fixture_case(self, fixture_case: FixtureCase) -> list[CapabilityOutcomeEnvelope]:
        """Return fixture rows for a no-update or success fixture case."""

        return [outcome for outcome in self.outcomes if outcome.fixture_case is fixture_case]


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CapabilityOutcomeError(f"{path} did not contain a JSON object")
    return payload


def load_capability_outcome_fixtures(
    path: Path = CAPABILITY_OUTCOME_FIXTURES,
) -> CapabilityOutcomeFixtureSet:
    """Load capability outcome fixtures, failing closed on malformed data."""

    try:
        return CapabilityOutcomeFixtureSet.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise CapabilityOutcomeError(
            f"invalid capability outcome fixtures at {path}: {exc}"
        ) from exc


__all__ = [
    "CAPABILITY_OUTCOME_FIXTURES",
    "OUTCOME_ENVELOPE_REQUIRED_FIELDS",
    "REQUIRED_NO_UPDATE_CASES",
    "REQUIRED_OUTCOME_STATUSES",
    "AttemptKind",
    "CapabilityOutcomeEnvelope",
    "CapabilityOutcomeError",
    "CapabilityOutcomeFixtureSet",
    "ExecutionStatus",
    "FixtureCase",
    "LearningPolicy",
    "ManifestationStatus",
    "OutcomeStatus",
    "PublicEventStatus",
    "SelectionState",
    "WitnessPolicy",
    "load_capability_outcome_fixtures",
]
