"""Governance refusal outcome policy.

Refusing or correcting an unsafe / unsupported claim is a first-class
positive outcome for the governance capability that performed the
refusal — *but the original refused claim must remain failed,
blocked, or refused, and the learning adapter must not validate it*.

This module pairs two ``CapabilityOutcomeEnvelope`` rows:

- a *governance* outcome: the act of refusing / correcting succeeded.
- a *claim* outcome: the original unsafe / unsupported claim is
  refused or blocked.

The pair enforces the no-laundering invariants:

1. The claim outcome's ``claim_posterior_update.allowed`` is ``False``.
2. The claim outcome's ``learning_update.policy`` is not ``SUCCESS``.
3. The governance outcome's ``claim_posterior_update.allowed`` is
   ``False`` (the governance success does not retroactively validate
   the refused claim).
4. The governance and claim outcomes cross-link via
   ``refusal_or_correction_refs``.
5. Public refusal artifacts require public-event, privacy-public-safe,
   rights-public-clear, and evidence-envelope evidence.

cc-task: ``governance-refusal-outcome-policy``.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.capability_outcome import (
    CapabilityOutcomeEnvelope,
    ClaimStatus,
    LearningPolicy,
    OutcomeStatus,
    PrivacyState,
    PublicEventStatus,
    RightsState,
)

_GOVERNANCE_SUCCESS_STATUSES = frozenset(
    {
        OutcomeStatus.SUCCESS,
        OutcomeStatus.PUBLIC_EVENT_ACCEPTED,
        OutcomeStatus.REFUSED,
    }
)
_CLAIM_REFUSAL_STATUSES = frozenset(
    {OutcomeStatus.REFUSED, OutcomeStatus.BLOCKED, OutcomeStatus.FAILURE}
)
_CLAIM_REFUSAL_CLAIM_STATUSES = frozenset(
    {
        ClaimStatus.REFUSAL,
        ClaimStatus.CORRECTION_REQUIRED,
        ClaimStatus.POSTERIOR_NOT_ALLOWED,
        ClaimStatus.GATE_FAIL,
    }
)


class GovernanceRefusalPolicyError(ValueError):
    """Raised when a governance refusal pair violates a no-laundering invariant."""


class GovernanceRefusalPair(BaseModel):
    """Paired (governance success, refused claim) outcome envelopes.

    Both rows must reference each other through
    ``refusal_or_correction_refs``. The governance outcome can mark the
    refusal as a success that the learning adapter rewards. The claim
    outcome stays refused / blocked, with no claim-posterior update.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    governance_outcome: CapabilityOutcomeEnvelope
    claim_outcome: CapabilityOutcomeEnvelope

    @model_validator(mode="after")
    def _validate_no_laundering_invariants(self) -> Self:
        gov = self.governance_outcome
        claim = self.claim_outcome

        if gov.outcome_status not in _GOVERNANCE_SUCCESS_STATUSES:
            raise GovernanceRefusalPolicyError(
                f"governance outcome must be one of {sorted(s.value for s in _GOVERNANCE_SUCCESS_STATUSES)}; "
                f"got {gov.outcome_status.value!r}"
            )

        if claim.outcome_status not in _CLAIM_REFUSAL_STATUSES:
            raise GovernanceRefusalPolicyError(
                f"claim outcome must be one of {sorted(s.value for s in _CLAIM_REFUSAL_STATUSES)}; "
                f"got {claim.outcome_status.value!r}"
            )

        if claim.claim_status not in _CLAIM_REFUSAL_CLAIM_STATUSES:
            raise GovernanceRefusalPolicyError(
                f"refused claim must have a refusal/blocked claim_status; "
                f"got {claim.claim_status.value!r}"
            )

        if claim.claim_posterior_update.allowed:
            raise GovernanceRefusalPolicyError(
                "no-laundering: refused claim's claim_posterior_update.allowed must be False"
            )

        if claim.learning_update.allowed and claim.learning_update.policy is LearningPolicy.SUCCESS:
            raise GovernanceRefusalPolicyError(
                "no-laundering: refused claim's learning_update.policy must not be SUCCESS"
            )

        if claim.verified_success.claim_posterior:
            raise GovernanceRefusalPolicyError(
                "no-laundering: refused claim cannot mark verified_success.claim_posterior"
            )

        if gov.claim_posterior_update.allowed:
            raise GovernanceRefusalPolicyError(
                "no-laundering: governance success cannot allow claim_posterior_update on the refused claim"
            )

        if gov.verified_success.claim_posterior:
            raise GovernanceRefusalPolicyError(
                "no-laundering: governance success cannot mark verified_success.claim_posterior"
            )

        gov_refs = set(gov.refusal_or_correction_refs)
        claim_refs = set(claim.refusal_or_correction_refs)
        if not gov_refs:
            raise GovernanceRefusalPolicyError(
                "governance success must include refusal_or_correction_refs cross-linking the claim"
            )
        if not claim_refs:
            raise GovernanceRefusalPolicyError(
                "refused claim must include refusal_or_correction_refs cross-linking the governance outcome"
            )
        if not (gov_refs & claim_refs):
            raise GovernanceRefusalPolicyError(
                "governance and claim outcomes must share at least one refusal_or_correction_ref"
            )

        return self

    def governance_learning_is_success(self) -> bool:
        return (
            self.governance_outcome.learning_update.allowed
            and self.governance_outcome.learning_update.policy is LearningPolicy.SUCCESS
        )

    def refused_claim_validates_success(self) -> bool:
        return self.claim_outcome.validates_success()

    def shared_refusal_refs(self) -> tuple[str, ...]:
        gov = set(self.governance_outcome.refusal_or_correction_refs)
        claim = set(self.claim_outcome.refusal_or_correction_refs)
        return tuple(sorted(gov & claim))


class PublicRefusalArtifactPolicy(BaseModel):
    """Policy gate for publishing a refusal artifact.

    Refusal artifacts can become public weirdness / research material —
    but only when public-event, privacy, rights, and evidence are all
    satisfied. Private artifacts (e.g. internal-only refusal logs) skip
    the public-event requirement; the gate distinguishes the two via
    ``intended_public``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(min_length=1)
    intended_public: bool
    public_event_refs: tuple[str, ...] = Field(default_factory=tuple)
    privacy_state: PrivacyState
    rights_state: RightsState
    evidence_envelope_refs: tuple[str, ...] = Field(default_factory=tuple)
    public_event_status: PublicEventStatus = PublicEventStatus.NOT_PUBLIC

    @model_validator(mode="after")
    def _validate_public_artifact_invariants(self) -> Self:
        if not self.intended_public:
            return self

        if not self.public_event_refs:
            raise GovernanceRefusalPolicyError("public refusal artifact requires public_event_refs")
        if self.privacy_state is not PrivacyState.PUBLIC_SAFE:
            raise GovernanceRefusalPolicyError(
                f"public refusal artifact requires privacy_state=public_safe; "
                f"got {self.privacy_state.value!r}"
            )
        if self.rights_state is not RightsState.PUBLIC_CLEAR:
            raise GovernanceRefusalPolicyError(
                f"public refusal artifact requires rights_state=public_clear; "
                f"got {self.rights_state.value!r}"
            )
        if not self.evidence_envelope_refs:
            raise GovernanceRefusalPolicyError(
                "public refusal artifact requires evidence_envelope_refs"
            )
        if self.public_event_status not in {
            PublicEventStatus.ACCEPTED,
            PublicEventStatus.PUBLISHED,
            PublicEventStatus.ELIGIBLE,
        }:
            raise GovernanceRefusalPolicyError(
                f"public refusal artifact requires public_event_status in "
                f"{{eligible, accepted, published}}; got {self.public_event_status.value!r}"
            )
        return self

    def cleared_for_public_release(self) -> bool:
        return self.intended_public and self.public_event_status in {
            PublicEventStatus.ACCEPTED,
            PublicEventStatus.PUBLISHED,
        }


def learning_adapter_treats_refusal_as_governance_success(
    pair: GovernanceRefusalPair,
) -> bool:
    """Predicate the learning adapter consults when consuming a pair.

    Returns ``True`` only when the governance side validates success
    AND the refused claim does *not* validate success. The pair model
    itself enforces the no-laundering invariants at construction;
    this predicate is the runtime read used by the adapter to decide
    whether to update the governance capability.
    """

    return (
        pair.governance_outcome.validates_success()
        and not pair.claim_outcome.validates_success()
        and pair.governance_learning_is_success()
    )


class RefusalEnvelopePolicy(BaseModel):
    """Policy wrapper for a single ``CapabilityOutcomeEnvelope`` representing a refusal.

    The existing capability-outcome fixture model collapses governance
    success and refused claim into one envelope (e.g. the
    ``coe:governance.no-expert:refused`` fixture). This wrapper
    enforces — at construction — the no-laundering invariants the
    governance refusal outcome policy requires of any such envelope.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    envelope: CapabilityOutcomeEnvelope

    @model_validator(mode="after")
    def _validate_no_laundering_for_refusal(self) -> Self:
        env = self.envelope

        if env.outcome_status not in {OutcomeStatus.REFUSED, OutcomeStatus.BLOCKED}:
            raise GovernanceRefusalPolicyError(
                f"refusal envelope must have outcome_status in {{refused, blocked}}; "
                f"got {env.outcome_status.value!r}"
            )

        if env.claim_posterior_update.allowed:
            raise GovernanceRefusalPolicyError(
                "no-laundering: refusal envelope cannot allow claim_posterior_update"
            )

        if env.verified_success.claim_posterior:
            raise GovernanceRefusalPolicyError(
                "no-laundering: refusal envelope cannot mark verified_success.claim_posterior"
            )

        if (
            env.outcome_status is OutcomeStatus.REFUSED
            and env.claim_status not in _CLAIM_REFUSAL_CLAIM_STATUSES
        ):
            raise GovernanceRefusalPolicyError(
                f"refused outcome must use a refusal/blocked claim_status; "
                f"got {env.claim_status.value!r}"
            )

        if not env.refusal_or_correction_refs:
            raise GovernanceRefusalPolicyError(
                "refusal envelope must include refusal_or_correction_refs"
            )

        return self

    def governance_capability_learning_allowed(self) -> bool:
        return (
            self.envelope.learning_update.allowed
            and self.envelope.learning_update.policy is LearningPolicy.SUCCESS
        )

    def refused_claim_posterior_locked(self) -> bool:
        return (
            not self.envelope.claim_posterior_update.allowed
            and not self.envelope.verified_success.claim_posterior
        )


__all__ = [
    "GovernanceRefusalPair",
    "GovernanceRefusalPolicyError",
    "PublicRefusalArtifactPolicy",
    "RefusalEnvelopePolicy",
    "learning_adapter_treats_refusal_as_governance_success",
]
