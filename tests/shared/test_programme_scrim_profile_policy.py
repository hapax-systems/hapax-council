"""Runtime tests for programme scrim profile policy selection."""

from __future__ import annotations

import pytest

from shared.programme_scrim_profile_policy import (
    ProfileSelectionContext,
    ProgrammeScrimProfilePolicyError,
    load_policy,
    select_profile_prior,
)

REQUIRED_TARGETS = {
    "tier_list",
    "ranking",
    "bracket",
    "react_commentary",
    "watch_along",
    "review",
    "explainer",
    "rundown",
    "what_is_this",
    "refusal_breakdown",
    "evidence_audit",
    "failure_autopsy",
    "listening",
    "hothouse",
    "ritual_boundary",
}


def test_load_policy_exposes_all_required_targets() -> None:
    policy = load_policy()

    assert {target.target_id for target in policy.targets} == REQUIRED_TARGETS
    assert policy.soft_prior_only.scheduler_hint_only is True
    assert policy.soft_prior_only.policy_can_override_wcs_blockers is False


def test_clean_context_returns_soft_prior_not_public_claim_authority() -> None:
    result = select_profile_prior("evidence_audit", ProfileSelectionContext())

    assert result.selected_profile_id == "clarity_peak"
    assert result.selected_permeability_mode == "semipermeable_membrane"
    assert result.focus_region_kinds == (
        "source_metadata",
        "criteria_table",
        "correction_boundary",
    )
    assert result.fallback_mode == "none"
    assert result.blocked_reasons == ()
    assert result.unavailable_profile_reasons == ()
    assert result.scheduler_hint_only is True
    assert result.soft_prior_only is True
    assert result.wcs_decision_required is True
    assert result.director_decision_required is True
    assert result.public_claim_allowed is False


@pytest.mark.parametrize(
    ("context", "expected_reason"),
    [
        (ProfileSelectionContext(evidence_status="missing"), "missing_evidence_ref"),
        (ProfileSelectionContext(evidence_status="stale"), "source_stale"),
        (ProfileSelectionContext(grounding_gate_state="missing"), "missing_grounding_gate"),
        (ProfileSelectionContext(grounding_gate_state="fail"), "grounding_gate_failed"),
        (ProfileSelectionContext(health_state="blocked"), "world_surface_blocked"),
        (ProfileSelectionContext(health_state="missing"), "health_failed"),
        (ProfileSelectionContext(rights_state="blocked"), "rights_blocked"),
        (ProfileSelectionContext(privacy_state="blocked"), "privacy_blocked"),
        (ProfileSelectionContext(public_event_state="missing"), "public_event_missing"),
        (
            ProfileSelectionContext(
                public_private_mode="public_monetizable",
                monetization_state="blocked",
            ),
            "monetization_blocked",
        ),
        (
            ProfileSelectionContext(
                public_private_mode="public_monetizable",
                monetization_state="unknown",
            ),
            "monetization_readiness_missing",
        ),
        (ProfileSelectionContext(conversion_state="held"), "conversion_held"),
    ],
)
def test_wcs_blockers_make_profiles_unavailable(context, expected_reason: str) -> None:
    result = select_profile_prior("tier_list", context)

    assert result.selected_profile_id is None
    assert result.selected_permeability_mode is None
    assert result.fallback_mode == "neutral_hold"
    assert expected_reason in result.blocked_reasons
    assert result.unavailable_profile_reasons
    assert all(expected_reason in reason for reason in result.unavailable_profile_reasons)
    assert result.candidate_profile_ids == ("clarity_peak",)
    assert result.public_claim_allowed is False


def test_no_target_can_bypass_wcs_blockers_with_persuasive_profile() -> None:
    policy = load_policy()
    blocked = ProfileSelectionContext(
        evidence_status="fresh",
        health_state="healthy",
        explicit_blocked_reasons=("world_surface_blocked",),
    )

    for target in policy.targets:
        result = select_profile_prior(target.target_id, blocked, policy=policy)
        assert result.selected_profile_id is None, target.target_id
        assert "world_surface_blocked" in result.blocked_reasons
        assert result.unavailable_profile_reasons
        assert result.fallback_mode == "neutral_hold"


def test_unavailable_reasons_are_structured_for_scheduler_and_runner() -> None:
    result = select_profile_prior(
        "ritual_boundary",
        ProfileSelectionContext(
            conversion_state="held",
            public_event_state="held",
        ),
    )

    assert result.blocked_reasons == ("public_event_missing", "conversion_held")
    assert result.selected_profile_id is None
    assert result.candidate_profile_ids == ("ritual_open",)
    assert result.unavailable_profile_reasons == (
        "ritual_boundary:ritual_open:unavailable:public_event_missing",
        "ritual_boundary:ritual_open:unavailable:conversion_held",
    )


def test_oq02_legibility_and_anti_visualizer_constraints_survive_runtime_load() -> None:
    policy = load_policy()

    for target in policy.targets:
        for prior in target.profile_priors:
            constraints = prior.legibility_constraints
            assert constraints.oq02_minimum_translucency >= 0.54
            assert constraints.oq02_label_required is True
            assert constraints.anti_visualizer_required is True
            assert constraints.audio_reactive_visualizer_allowed is False
            assert constraints.preserve_operator_foreground is True
            assert prior.motion_rate <= constraints.max_motion_rate


def test_unknown_target_fails_explicitly() -> None:
    with pytest.raises(KeyError):
        select_profile_prior("unknown_format")


def test_malformed_policy_fails_closed(tmp_path) -> None:
    path = tmp_path / "bad-policy.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(ProgrammeScrimProfilePolicyError):
        load_policy(path)
