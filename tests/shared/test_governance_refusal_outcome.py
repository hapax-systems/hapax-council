"""Tests for the governance refusal outcome policy.

cc-task: governance-refusal-outcome-policy.
"""

from __future__ import annotations

from typing import Any

import pytest

from shared.capability_outcome import (
    CapabilityOutcomeEnvelope,
    OutcomeStatus,
    load_capability_outcome_fixtures,
)
from shared.governance_refusal_outcome import (
    GovernanceRefusalPair,
    PublicRefusalArtifactPolicy,
    RefusalEnvelopePolicy,
    learning_adapter_treats_refusal_as_governance_success,
)


@pytest.fixture(scope="module")
def refused_envelope() -> CapabilityOutcomeEnvelope:
    """Return the canonical refusal envelope from the existing fixtures."""
    fixtures = load_capability_outcome_fixtures()
    refused = [
        outcome for outcome in fixtures.outcomes if outcome.outcome_status is OutcomeStatus.REFUSED
    ]
    assert refused, "fixtures must contain a refused outcome"
    return refused[0]


@pytest.fixture
def blocked_envelope() -> CapabilityOutcomeEnvelope:
    fixtures = load_capability_outcome_fixtures()
    blocked = [
        outcome for outcome in fixtures.outcomes if outcome.outcome_status is OutcomeStatus.BLOCKED
    ]
    assert blocked, "fixtures must contain a blocked outcome"
    return blocked[0]


@pytest.fixture(scope="module")
def success_envelope() -> CapabilityOutcomeEnvelope:
    fixtures = load_capability_outcome_fixtures()
    success = [
        outcome for outcome in fixtures.outcomes if outcome.outcome_status is OutcomeStatus.SUCCESS
    ]
    assert success, "fixtures must contain a success outcome"
    return success[0]


@pytest.fixture(scope="module")
def neutral_envelope() -> CapabilityOutcomeEnvelope:
    fixtures = load_capability_outcome_fixtures()
    neutral = [
        outcome
        for outcome in fixtures.outcomes
        if outcome.outcome_status is OutcomeStatus.NEUTRAL_DEFER
    ]
    assert neutral, "fixtures must contain a neutral_defer outcome"
    return neutral[0]


def _envelope_with(
    refused_envelope: CapabilityOutcomeEnvelope, **overrides: Any
) -> CapabilityOutcomeEnvelope:
    payload = refused_envelope.model_dump()
    for key, value in overrides.items():
        payload[key] = value
    return CapabilityOutcomeEnvelope.model_validate(payload)


def _claim_envelope(
    blocked_envelope: CapabilityOutcomeEnvelope, refused_envelope: CapabilityOutcomeEnvelope
) -> CapabilityOutcomeEnvelope:
    """Synthesize a 'refused claim' envelope cross-linked to the governance envelope."""
    payload = blocked_envelope.model_dump()
    payload["outcome_id"] = "coe:claim:claim-17:blocked"
    payload["refusal_or_correction_refs"] = list(refused_envelope.refusal_or_correction_refs)
    payload["blocked_reasons"] = ["governance_refusal"] + list(
        blocked_envelope.blocked_reasons or ["governance_refusal"]
    )
    return CapabilityOutcomeEnvelope.model_validate(payload)


def test_refusal_envelope_policy_accepts_canonical_refused_fixture(refused_envelope):
    policy = RefusalEnvelopePolicy(envelope=refused_envelope)
    assert policy.governance_capability_learning_allowed() is True
    assert policy.refused_claim_posterior_locked() is True


def test_refusal_envelope_policy_rejects_success_status(success_envelope):
    with pytest.raises(Exception, match="outcome_status"):
        RefusalEnvelopePolicy(envelope=success_envelope)


def test_refusal_envelope_policy_rejects_allowed_claim_posterior(refused_envelope):
    laundered_payload = refused_envelope.model_dump()
    laundered_payload["claim_posterior_update"] = dict(laundered_payload["claim_posterior_update"])
    laundered_payload["claim_posterior_update"]["allowed"] = True
    with pytest.raises(Exception):
        CapabilityOutcomeEnvelope.model_validate(laundered_payload)


def test_refusal_envelope_policy_requires_refusal_refs(blocked_envelope):
    no_refs_payload = blocked_envelope.model_dump()
    no_refs_payload["refusal_or_correction_refs"] = []
    no_refs = CapabilityOutcomeEnvelope.model_validate(no_refs_payload)
    with pytest.raises(Exception, match="refusal_or_correction_refs"):
        RefusalEnvelopePolicy(envelope=no_refs)


def test_refusal_envelope_policy_rejects_verified_claim_posterior(refused_envelope):
    payload = refused_envelope.model_dump()
    payload["verified_success"] = dict(payload["verified_success"])
    payload["verified_success"]["claim_posterior"] = True
    with pytest.raises(Exception):
        env = CapabilityOutcomeEnvelope.model_validate(payload)
        RefusalEnvelopePolicy(envelope=env)


def test_governance_refusal_pair_succeeds_with_canonical_fixtures(
    refused_envelope, blocked_envelope
):
    governance = refused_envelope
    claim = _claim_envelope(blocked_envelope, refused_envelope)
    pair = GovernanceRefusalPair(governance_outcome=governance, claim_outcome=claim)
    assert pair.governance_learning_is_success() is True
    assert pair.refused_claim_validates_success() is False
    assert pair.shared_refusal_refs(), "shared refusal refs must cross-link the pair"


def test_governance_refusal_pair_rejects_neutral_governance_outcome(
    neutral_envelope, blocked_envelope, refused_envelope
):
    claim = _claim_envelope(blocked_envelope, refused_envelope)
    with pytest.raises(Exception, match="governance outcome"):
        GovernanceRefusalPair(governance_outcome=neutral_envelope, claim_outcome=claim)


def test_governance_refusal_pair_rejects_success_claim_outcome(refused_envelope):
    success_claim_payload = refused_envelope.model_dump()
    success_claim_payload["outcome_status"] = "success"
    success_claim_payload["claim_status"] = "gate_pass"
    with pytest.raises(Exception):
        success_claim = CapabilityOutcomeEnvelope.model_validate(success_claim_payload)
        GovernanceRefusalPair(governance_outcome=refused_envelope, claim_outcome=success_claim)


def test_governance_refusal_pair_rejects_unlinked_outcomes(refused_envelope, blocked_envelope):
    payload = blocked_envelope.model_dump()
    payload["outcome_id"] = "coe:claim:claim-99:blocked"
    payload["refusal_or_correction_refs"] = ["refusal:unrelated:claim-99"]
    payload["blocked_reasons"] = ["governance_refusal"] + list(
        blocked_envelope.blocked_reasons or ["governance_refusal"]
    )
    unlinked = CapabilityOutcomeEnvelope.model_validate(payload)
    with pytest.raises(Exception, match="share at least one refusal_or_correction_ref"):
        GovernanceRefusalPair(governance_outcome=refused_envelope, claim_outcome=unlinked)


def test_learning_adapter_predicate_true_for_valid_pair(refused_envelope, blocked_envelope):
    pair = GovernanceRefusalPair(
        governance_outcome=refused_envelope,
        claim_outcome=_claim_envelope(blocked_envelope, refused_envelope),
    )
    assert learning_adapter_treats_refusal_as_governance_success(pair) is True


def test_learning_adapter_predicate_false_when_governance_learning_disabled(
    refused_envelope, blocked_envelope
):
    payload = refused_envelope.model_dump()
    payload["learning_update"] = dict(payload["learning_update"])
    payload["learning_update"]["allowed"] = False
    payload["learning_update"]["policy"] = "neutral"
    payload["learning_update"]["target"] = "none"
    payload["learning_update"]["required_witness_refs"] = []
    payload["verified_success"] = dict(payload["verified_success"])
    payload["verified_success"]["capability"] = False
    no_learn = CapabilityOutcomeEnvelope.model_validate(payload)
    pair = GovernanceRefusalPair(
        governance_outcome=no_learn,
        claim_outcome=_claim_envelope(blocked_envelope, refused_envelope),
    )
    assert learning_adapter_treats_refusal_as_governance_success(pair) is False


def test_public_refusal_artifact_policy_accepts_fully_evidenced_artifact():
    policy = PublicRefusalArtifactPolicy(
        artifact_id="refusal:no-expert:claim-17",
        intended_public=True,
        public_event_refs=("public-event:refusal:claim-17",),
        privacy_state="public_safe",
        rights_state="public_clear",
        evidence_envelope_refs=("evidence-envelope:claim-17:insufficient-authority",),
        public_event_status="published",
    )
    assert policy.cleared_for_public_release() is True


def test_public_refusal_artifact_policy_rejects_missing_public_event_refs():
    with pytest.raises(Exception, match="public_event_refs"):
        PublicRefusalArtifactPolicy(
            artifact_id="refusal:no-expert:claim-17",
            intended_public=True,
            public_event_refs=(),
            privacy_state="public_safe",
            rights_state="public_clear",
            evidence_envelope_refs=("evidence-envelope:claim-17:insufficient-authority",),
            public_event_status="eligible",
        )


def test_public_refusal_artifact_policy_rejects_non_public_safe_privacy():
    with pytest.raises(Exception, match="privacy_state"):
        PublicRefusalArtifactPolicy(
            artifact_id="refusal:no-expert:claim-17",
            intended_public=True,
            public_event_refs=("public-event:refusal:claim-17",),
            privacy_state="private_only",
            rights_state="public_clear",
            evidence_envelope_refs=("evidence-envelope:claim-17:insufficient-authority",),
            public_event_status="eligible",
        )


def test_public_refusal_artifact_policy_rejects_non_public_clear_rights():
    with pytest.raises(Exception, match="rights_state"):
        PublicRefusalArtifactPolicy(
            artifact_id="refusal:no-expert:claim-17",
            intended_public=True,
            public_event_refs=("public-event:refusal:claim-17",),
            privacy_state="public_safe",
            rights_state="not_applicable",
            evidence_envelope_refs=("evidence-envelope:claim-17:insufficient-authority",),
            public_event_status="eligible",
        )


def test_public_refusal_artifact_policy_rejects_missing_evidence_envelope_refs():
    with pytest.raises(Exception, match="evidence_envelope_refs"):
        PublicRefusalArtifactPolicy(
            artifact_id="refusal:no-expert:claim-17",
            intended_public=True,
            public_event_refs=("public-event:refusal:claim-17",),
            privacy_state="public_safe",
            rights_state="public_clear",
            evidence_envelope_refs=(),
            public_event_status="eligible",
        )


def test_public_refusal_artifact_policy_rejects_not_public_event_status():
    with pytest.raises(Exception, match="public_event_status"):
        PublicRefusalArtifactPolicy(
            artifact_id="refusal:no-expert:claim-17",
            intended_public=True,
            public_event_refs=("public-event:refusal:claim-17",),
            privacy_state="public_safe",
            rights_state="public_clear",
            evidence_envelope_refs=("evidence-envelope:claim-17:insufficient-authority",),
            public_event_status="not_public",
        )


def test_public_refusal_artifact_policy_skips_public_checks_for_private_artifacts():
    policy = PublicRefusalArtifactPolicy(
        artifact_id="refusal:internal:claim-17",
        intended_public=False,
        public_event_refs=(),
        privacy_state="private_only",
        rights_state="not_applicable",
        evidence_envelope_refs=(),
    )
    assert policy.cleared_for_public_release() is False


def test_public_refusal_artifact_policy_cleared_only_when_published_or_accepted():
    eligible = PublicRefusalArtifactPolicy(
        artifact_id="refusal:no-expert:claim-17",
        intended_public=True,
        public_event_refs=("public-event:refusal:claim-17",),
        privacy_state="public_safe",
        rights_state="public_clear",
        evidence_envelope_refs=("evidence-envelope:claim-17:insufficient-authority",),
        public_event_status="eligible",
    )
    assert eligible.cleared_for_public_release() is False

    accepted = PublicRefusalArtifactPolicy(
        artifact_id="refusal:no-expert:claim-17",
        intended_public=True,
        public_event_refs=("public-event:refusal:claim-17",),
        privacy_state="public_safe",
        rights_state="public_clear",
        evidence_envelope_refs=("evidence-envelope:claim-17:insufficient-authority",),
        public_event_status="accepted",
    )
    assert accepted.cleared_for_public_release() is True
