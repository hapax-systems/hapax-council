"""Adapter from CapabilityOutcomeEnvelope to AffordancePipeline learning.

The AffordancePipeline still owns Thompson and context-association learning.
This module is the gate that decides whether a typed capability outcome may be
collapsed into the pipeline's legacy boolean success/failure primitive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from shared.capability_outcome import (
    REQUIRED_NO_UPDATE_CASES,
    AttemptKind,
    AuthorityCeiling,
    CapabilityOutcomeEnvelope,
    ClaimPosteriorUpdate,
    ClaimStatus,
    ExecutionStatus,
    ExpectedEffect,
    FixtureCase,
    Freshness,
    FreshnessState,
    LearningPolicy,
    LearningTarget,
    LearningUpdate,
    ManifestationStatus,
    OutcomeStatus,
    PrivacyState,
    PublicClaimEvidence,
    PublicEventStatus,
    RightsState,
    SelectionState,
    VerifiedSuccess,
    WitnessPolicy,
)


class AffordanceOutcomeUpdateKind(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    NO_UPDATE = "no_update"


@dataclass(frozen=True)
class AffordanceOutcomeDecision:
    """Explicit adapter result before mutating AffordancePipeline state."""

    outcome_id: str
    capability_name: str
    kind: AffordanceOutcomeUpdateKind
    should_update: bool
    success: bool | None
    reason: str
    learning_policy: str
    learning_target: str
    refused_claim_validated: bool = False
    claim_posterior_update_allowed: bool = False


_NO_SUCCESS_OUTCOME_STATUSES = {
    OutcomeStatus.BLOCKED,
    OutcomeStatus.STALE,
    OutcomeStatus.MISSING,
    OutcomeStatus.INFERRED,
}

_NO_SUCCESS_WITNESS_POLICIES = {
    WitnessPolicy.SELECTED_ONLY,
    WitnessPolicy.COMMANDED_ONLY,
    WitnessPolicy.INFERRED,
    WitnessPolicy.MISSING,
    WitnessPolicy.STALE,
    WitnessPolicy.LEGACY_PUBLIC_EVENT,
    WitnessPolicy.FIXTURE_ONLY,
}


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_.-]+", "-", value.lower()).strip("-")
    return slug or "unknown-tool"


def _no_update(outcome: CapabilityOutcomeEnvelope, reason: str) -> AffordanceOutcomeDecision:
    return AffordanceOutcomeDecision(
        outcome_id=outcome.outcome_id,
        capability_name=outcome.capability_name,
        kind=AffordanceOutcomeUpdateKind.NO_UPDATE,
        should_update=False,
        success=None,
        reason=reason,
        learning_policy=outcome.learning_update.policy.value,
        learning_target=outcome.learning_update.target.value,
        claim_posterior_update_allowed=outcome.allows_claim_posterior_update(),
    )


def _update(
    outcome: CapabilityOutcomeEnvelope,
    *,
    success: bool,
    reason: str,
) -> AffordanceOutcomeDecision:
    return AffordanceOutcomeDecision(
        outcome_id=outcome.outcome_id,
        capability_name=outcome.capability_name,
        kind=(
            AffordanceOutcomeUpdateKind.SUCCESS if success else AffordanceOutcomeUpdateKind.FAILURE
        ),
        should_update=True,
        success=success,
        reason=reason,
        learning_policy=outcome.learning_update.policy.value,
        learning_target=outcome.learning_update.target.value,
        refused_claim_validated=False,
        claim_posterior_update_allowed=outcome.allows_claim_posterior_update(),
    )


def decide_affordance_outcome_update(
    outcome: CapabilityOutcomeEnvelope,
) -> AffordanceOutcomeDecision:
    """Return the AffordancePipeline learning decision for an outcome envelope."""

    if not outcome.learning_update.allowed:
        return _no_update(outcome, "learning_update.allowed is false")
    if outcome.learning_update.target is LearningTarget.NONE:
        return _no_update(outcome, "learning_update.target is none")
    if outcome.learning_update.missing_witness_refs:
        return _no_update(outcome, "learning_update has missing witness refs")

    if outcome.learning_update.policy is LearningPolicy.SUCCESS:
        return _decide_success_update(outcome)
    if outcome.learning_update.policy is LearningPolicy.FAILURE:
        return _decide_failure_update(outcome)

    return _no_update(outcome, f"learning policy {outcome.learning_update.policy.value} is neutral")


def build_tool_recruitment_no_witness_outcome(
    tool_name: str,
    *,
    legacy_success: bool,
    created_at: str | None = None,
) -> CapabilityOutcomeEnvelope:
    """Build a no-update envelope for legacy tool result booleans.

    Conversation tool calls currently know only that a handler returned a
    string without an obvious error. That is command/result evidence, not a
    source-artifact or claim witness, so the adapter must fail closed.
    """

    checked_at = created_at or _utc_now()
    slug = _slug(tool_name)
    missing_ref = f"evidence-envelope:tool.{slug}:source-artifacts"
    if legacy_success:
        outcome_status = OutcomeStatus.NEUTRAL_DEFER
        execution_status = ExecutionStatus.ACCEPTED
        manifestation_status = ManifestationStatus.NOT_OBSERVED
        freshness_state = FreshnessState.UNKNOWN
        witness_policy = WitnessPolicy.COMMANDED_ONLY
        fixture_case = FixtureCase.COMMANDED_ONLY
        blocked_reason = "commanded_only_no_source_artifact_witness"
        reason = "Tool handler returned without an error, but no source/artifact witness exists."
    else:
        outcome_status = OutcomeStatus.MISSING
        execution_status = ExecutionStatus.TOOL_ERROR
        manifestation_status = ManifestationStatus.WITNESS_UNAVAILABLE
        freshness_state = FreshnessState.MISSING
        witness_policy = WitnessPolicy.MISSING
        fixture_case = FixtureCase.MISSING
        blocked_reason = "tool_result_error_no_source_artifact_witness"
        reason = "Tool handler reported an error and no source/artifact witness exists."

    return CapabilityOutcomeEnvelope(
        outcome_id=f"coe:tool.{slug}:legacy-no-witness",
        created_at=checked_at,
        capability_id=f"capability:tool.{slug}",
        capability_name=tool_name,
        attempt_kind=AttemptKind.RECALL,
        selection_ref=f"selection:tool.{slug}:legacy",
        selection_state=SelectionState.SELECTED,
        command_ref=f"command:tool.{slug}:legacy-result",
        route_ref="route:tool-recruitment-gate",
        substrate_refs=["substrate:tool-recruitment-gate"],
        programme_refs=[],
        director_move_ref=None,
        evidence_envelope_refs=[],
        witness_refs=[],
        expected_effect=ExpectedEffect(
            effect_id=f"effect:tool.{slug}:source-artifacts",
            description="The recruited tool produces typed source or artifact evidence.",
            witness_class="tool_source_artifact",
            public_claim_bearing=True,
            action_bearing=False,
        ),
        outcome_status=outcome_status,
        execution_status=execution_status,
        manifestation_status=manifestation_status,
        claim_status=ClaimStatus.POSTERIOR_NOT_ALLOWED,
        public_event_status=PublicEventStatus.NOT_PUBLIC,
        learning_update=LearningUpdate(
            policy=LearningPolicy.DEFER,
            allowed=False,
            target=LearningTarget.NONE,
            reason=reason,
            required_witness_refs=[],
            missing_witness_refs=[missing_ref],
            thompson_delta=None,
            context_association_delta=None,
        ),
        claim_posterior_update=ClaimPosteriorUpdate(
            allowed=False,
            claim_ids=[],
            evidence_envelope_refs=[],
            gate_refs=[],
            claim_engine_refs=[],
            reason="Legacy tool result booleans cannot update claim posterior state.",
        ),
        blocked_reasons=[blocked_reason],
        refusal_or_correction_refs=[],
        health_refs=[],
        privacy_state=PrivacyState.UNKNOWN,
        rights_state=RightsState.UNKNOWN,
        freshness=Freshness(
            state=freshness_state,
            ttl_s=None,
            observed_age_s=None,
            source_ref=None,
            checked_at=checked_at,
        ),
        authority_ceiling=AuthorityCeiling.NO_CLAIM,
        witness_policy=witness_policy,
        verified_success=VerifiedSuccess(
            capability=False,
            action=False,
            public=False,
            claim_posterior=False,
        ),
        public_claim_evidence=PublicClaimEvidence(
            required=False,
            present=False,
            evidence_envelope_refs=[],
            public_event_refs=[],
            gate_refs=[],
            note="No public claim evidence exists for a legacy tool result boolean.",
        ),
        operator_visible_summary=reason,
        fixture_case=fixture_case,
    )


def build_commanded_no_witness_outcome(
    capability_name: str,
    *,
    created_at: str | None = None,
    command_ref: str | None = None,
    route_ref: str | None = None,
    source_ref: str | None = None,
    attempt_kind: AttemptKind = AttemptKind.ACT,
    action_bearing: bool = True,
    public_claim_bearing: bool = False,
    reason: str | None = None,
) -> CapabilityOutcomeEnvelope:
    """Build a no-update envelope for accepted commands without readback.

    File writes, recruitment logs, and handler return values prove command
    acceptance at most. Until an action receipt provides witness/readback refs,
    they must not update positive affordance learning.
    """

    checked_at = created_at or _utc_now()
    slug = _slug(capability_name)
    missing_ref = f"action-receipt:{slug}:readback"
    summary = reason or "Command was accepted, but no applied/readback witness exists."
    return CapabilityOutcomeEnvelope(
        outcome_id=f"coe:{slug}:commanded-no-witness",
        created_at=checked_at,
        capability_id=f"capability:{slug}",
        capability_name=capability_name,
        attempt_kind=attempt_kind,
        selection_ref=f"selection:{slug}:recruited",
        selection_state=SelectionState.SELECTED,
        command_ref=command_ref or f"command:{slug}:accepted",
        route_ref=route_ref,
        substrate_refs=[],
        programme_refs=[],
        director_move_ref=None,
        evidence_envelope_refs=[],
        witness_refs=[],
        expected_effect=ExpectedEffect(
            effect_id=f"effect:{slug}:applied-readback",
            description="The requested action is applied and witnessed by a readback surface.",
            witness_class="action_receipt_readback",
            public_claim_bearing=public_claim_bearing,
            action_bearing=action_bearing,
        ),
        outcome_status=OutcomeStatus.NEUTRAL_DEFER,
        execution_status=ExecutionStatus.ACCEPTED,
        manifestation_status=ManifestationStatus.NOT_OBSERVED,
        claim_status=ClaimStatus.POSTERIOR_NOT_ALLOWED,
        public_event_status=PublicEventStatus.NOT_PUBLIC,
        learning_update=LearningUpdate(
            policy=LearningPolicy.DEFER,
            allowed=False,
            target=LearningTarget.NONE,
            reason=summary,
            required_witness_refs=[],
            missing_witness_refs=[missing_ref],
            thompson_delta=None,
            context_association_delta=None,
        ),
        claim_posterior_update=ClaimPosteriorUpdate(
            allowed=False,
            claim_ids=[],
            evidence_envelope_refs=[],
            gate_refs=[],
            claim_engine_refs=[],
            reason="Command acceptance without readback cannot update claim posterior state.",
        ),
        blocked_reasons=["commanded_only_no_action_readback"],
        refusal_or_correction_refs=[],
        health_refs=[],
        privacy_state=PrivacyState.UNKNOWN,
        rights_state=RightsState.UNKNOWN,
        freshness=Freshness(
            state=FreshnessState.UNKNOWN,
            ttl_s=None,
            observed_age_s=None,
            source_ref=source_ref,
            checked_at=checked_at,
        ),
        authority_ceiling=AuthorityCeiling.NO_CLAIM,
        witness_policy=WitnessPolicy.COMMANDED_ONLY,
        verified_success=VerifiedSuccess(
            capability=False,
            action=False,
            public=False,
            claim_posterior=False,
        ),
        public_claim_evidence=PublicClaimEvidence(
            required=False,
            present=False,
            evidence_envelope_refs=[],
            public_event_refs=[],
            gate_refs=[],
            note="No public claim evidence exists for command acceptance without readback.",
        ),
        operator_visible_summary=summary,
        fixture_case=FixtureCase.COMMANDED_ONLY,
    )


def _decide_success_update(outcome: CapabilityOutcomeEnvelope) -> AffordanceOutcomeDecision:
    if outcome.fixture_case.value in REQUIRED_NO_UPDATE_CASES:
        return _no_update(
            outcome, f"fixture_case:{outcome.fixture_case.value} cannot update success"
        )
    if outcome.outcome_status in _NO_SUCCESS_OUTCOME_STATUSES:
        return _no_update(
            outcome, f"outcome_status:{outcome.outcome_status.value} cannot update success"
        )
    if outcome.witness_policy in _NO_SUCCESS_WITNESS_POLICIES:
        return _no_update(
            outcome, f"witness_policy:{outcome.witness_policy.value} cannot update success"
        )
    if outcome.outcome_status is OutcomeStatus.REFUSED:
        if not outcome.refusal_or_correction_refs:
            return _no_update(outcome, "refusal success requires refusal_or_correction_refs")
        if outcome.claim_posterior_update.allowed or outcome.verified_success.claim_posterior:
            return _no_update(outcome, "refusal success cannot validate the refused claim")
    if not outcome.validates_success():
        blockers = ", ".join(outcome.success_blockers()) or "unknown"
        return _no_update(outcome, f"outcome does not validate capability success: {blockers}")
    if not outcome.learning_update.required_witness_refs:
        return _no_update(outcome, "success update requires required_witness_refs")
    return _update(outcome, success=True, reason=outcome.learning_update.reason)


def _decide_failure_update(outcome: CapabilityOutcomeEnvelope) -> AffordanceOutcomeDecision:
    if outcome.outcome_status is not OutcomeStatus.FAILURE:
        return _no_update(outcome, f"failure policy cannot update {outcome.outcome_status.value}")
    if outcome.manifestation_status is not ManifestationStatus.WITNESS_FAILED:
        return _no_update(outcome, "failure update requires witness_failed manifestation")
    if outcome.freshness.state is not FreshnessState.FRESH:
        return _no_update(outcome, "failure update requires fresh failure witness")
    if not outcome.witness_refs or not outcome.learning_update.required_witness_refs:
        return _no_update(outcome, "failure update requires witness refs")
    return _update(outcome, success=False, reason=outcome.learning_update.reason)


__all__ = [
    "AffordanceOutcomeDecision",
    "AffordanceOutcomeUpdateKind",
    "build_commanded_no_witness_outcome",
    "build_tool_recruitment_no_witness_outcome",
    "decide_affordance_outcome_update",
]
