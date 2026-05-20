"""Tests for visual lane outcome witness fixtures."""

from __future__ import annotations

from shared.affordance_outcome_adapter import (
    AffordanceOutcomeUpdateKind,
    decide_affordance_outcome_update,
)
from shared.capability_outcome import (
    CapabilityOutcomeEnvelope,
    load_capability_outcome_fixtures,
)


def _outcome(outcome_id: str) -> CapabilityOutcomeEnvelope:
    return load_capability_outcome_fixtures().require_outcome(outcome_id)


def test_reverie_lane_witnessed_success_updates_learning() -> None:
    outcome = _outcome("coe:visual.reverie-lane:witnessed-success")
    assert outcome.outcome_status.value == "success"
    assert outcome.manifestation_status.value == "witness_verified"
    assert len(outcome.witness_refs) == 2
    assert outcome.verified_success.capability is True
    assert outcome.verified_success.public is False
    decision = decide_affordance_outcome_update(outcome)
    assert decision.kind is AffordanceOutcomeUpdateKind.SUCCESS
    assert decision.should_update is True


def test_compositor_overlay_witnessed_success_updates_learning() -> None:
    outcome = _outcome("coe:visual.compositor-overlay:witnessed-success")
    assert outcome.outcome_status.value == "success"
    assert outcome.manifestation_status.value == "witness_verified"
    assert len(outcome.witness_refs) == 2
    assert outcome.verified_success.capability is True
    decision = decide_affordance_outcome_update(outcome)
    assert decision.kind is AffordanceOutcomeUpdateKind.SUCCESS


def test_stale_frame_witness_does_not_update_success() -> None:
    outcome = _outcome("coe:visual.frame:stale-witness")
    assert outcome.outcome_status.value == "stale"
    assert outcome.freshness.state.value == "stale"
    assert outcome.freshness.observed_age_s > outcome.freshness.ttl_s
    assert outcome.verified_success.capability is False
    decision = decide_affordance_outcome_update(outcome)
    assert decision.kind is AffordanceOutcomeUpdateKind.NO_UPDATE
    assert decision.should_update is False


def test_missing_frame_witness_does_not_update_success() -> None:
    outcome = _outcome("coe:visual.frame:missing-witness")
    assert outcome.outcome_status.value == "missing"
    assert len(outcome.witness_refs) == 0
    assert outcome.verified_success.capability is False
    decision = decide_affordance_outcome_update(outcome)
    assert decision.kind is AffordanceOutcomeUpdateKind.NO_UPDATE
    assert decision.should_update is False


def test_wrong_lane_failure_updates_negative_learning() -> None:
    outcome = _outcome("coe:visual.compositor-lane:wrong-lane-failure")
    assert outcome.outcome_status.value == "failure"
    assert outcome.manifestation_status.value == "witness_failed"
    assert "camera-mismatch" in outcome.witness_refs[0]
    assert outcome.verified_success.capability is False
    decision = decide_affordance_outcome_update(outcome)
    assert decision.kind is AffordanceOutcomeUpdateKind.FAILURE
    assert decision.success is False


def test_renderability_and_public_egress_are_distinct() -> None:
    reverie = _outcome("coe:visual.reverie-lane:witnessed-success")
    assert reverie.verified_success.capability is True
    assert reverie.verified_success.public is False
    assert reverie.public_event_status.value == "not_public"
    assert reverie.authority_ceiling.value == "internal_only"


def test_all_visual_fixtures_have_witness_refs_or_explicit_missing() -> None:
    fixtures = load_capability_outcome_fixtures()
    visual = [o for o in fixtures.outcomes if "visual" in o.outcome_id]
    assert len(visual) >= 6
    for o in visual:
        if o.outcome_status.value in ("success", "failure"):
            assert len(o.witness_refs) > 0, f"{o.outcome_id} success/failure must have witness_refs"
        elif o.outcome_status.value == "missing":
            assert len(o.witness_refs) == 0, (
                f"{o.outcome_id} missing should have empty witness_refs"
            )
