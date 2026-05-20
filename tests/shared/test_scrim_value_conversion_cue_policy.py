from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.scrim_value_conversion_cue_policy import (
    POLICY_ROWS,
    REQUIRED_CUE_FAMILIES,
    ScrimValueConversionCueInput,
    project_scrim_value_conversion_cue,
)


def _cue_input(**overrides: object) -> ScrimValueConversionCueInput:
    payload = {
        "cue_id": "cue-001",
        "run_id": "run-001",
        "cue_family": "artifact",
        "target_family_id": "artifact_edition_release",
        "requested_state": "public-archive",
        "readiness_state": "public-archive",
        "format_id": "claim_audit",
        "source_class": "generated_asset",
        "rights_class": "owned",
        "public_private_mode": "public_archive",
        "conversion_refs": ("conversion:candidate:artifact-001",),
        "readiness_evidence_refs": ("readiness:ledger:artifact-001",),
        "source_event_refs": ("programme-boundary:artifact-candidate",),
        "revenue_metric_refs": ("revenue:format:claim_audit:artifact",),
        "operator_labor_policy": "no_recurring_operator_labor",
        "supporter_programming_policy": "no_supporter_control",
    }
    payload.update(overrides)
    return ScrimValueConversionCueInput.model_validate(payload)


def test_policy_defines_required_value_conversion_cue_families() -> None:
    assert {row.cue_family for row in POLICY_ROWS} == REQUIRED_CUE_FAMILIES

    target_families = {
        target_family for row in POLICY_ROWS for target_family in row.allowed_target_families
    }
    assert {
        "youtube_vod_packaging",
        "replay_demo",
        "artifact_edition_release",
        "support_prompt",
        "grants_fellowships",
    } <= target_families


def test_every_conversion_cue_requires_conversion_and_readiness_evidence_refs() -> None:
    with pytest.raises(ValidationError):
        _cue_input(conversion_refs=())

    with pytest.raises(ValidationError):
        _cue_input(readiness_evidence_refs=())


@pytest.mark.parametrize(
    ("cue_family", "target_family_id", "readiness_state", "public_private_mode"),
    [
        ("archive", "youtube_vod_packaging", "public-archive", "public_archive"),
        ("replay", "replay_demo", "public-archive", "public_archive"),
        ("artifact", "artifact_edition_release", "public-archive", "public_archive"),
        ("support", "support_prompt", "public-live", "public_live"),
        ("grant", "grants_fellowships", "private-evidence", "private"),
        ("monetization", "support_prompt", "public-monetizable", "monetized"),
    ],
)
def test_ready_conversion_cues_are_visible_but_not_truth_or_confidence_cues(
    cue_family: str,
    target_family_id: str,
    readiness_state: str,
    public_private_mode: str,
) -> None:
    projection = project_scrim_value_conversion_cue(
        _cue_input(
            cue_family=cue_family,
            target_family_id=target_family_id,
            requested_state=readiness_state,
            readiness_state=readiness_state,
            public_private_mode=public_private_mode,
        )
    )

    assert projection.posture == "conversion_ready"
    assert projection.is_ready is True
    assert projection.visibility_treatment == "conversion_cue_visible"
    assert projection.truth_signal_refs == ()
    assert projection.no_grant_policy.conversion_cue_grants_truth is False
    assert projection.no_grant_policy.conversion_cue_grants_claim_confidence is False
    assert projection.no_grant_policy.conversion_cue_grants_freshness is False
    assert projection.no_grant_policy.conversion_cue_grants_public_live_status is False
    assert projection.no_grant_policy.conversion_cue_grants_monetization_status is False

    lowered = projection.cue_language.lower()
    assert "truth" not in lowered
    assert "claim confidence" not in lowered
    assert "freshness" not in lowered
    assert "public-live" not in lowered


def test_high_revenue_potential_cannot_override_rights_or_monetization_blockers() -> None:
    blocked = _cue_input(
        cue_family="monetization",
        target_family_id="support_prompt",
        requested_state="public-monetizable",
        readiness_state="blocked",
        public_private_mode="monetized",
        rights_class="forbidden",
        missing_gate_dimensions=("rights", "monetization"),
        blocked_reasons=("rights_blocked", "monetization_not_ready"),
        revenue_potential_score=1.0,
    )
    low_value = blocked.model_copy(update={"revenue_potential_score": 0.0})

    high_projection = project_scrim_value_conversion_cue(blocked)
    low_projection = project_scrim_value_conversion_cue(low_value)

    assert high_projection.posture == "monetization_held"
    assert high_projection.is_held is True
    assert high_projection.visibility_treatment == "monetization_held_visible"
    assert high_projection.blocker_dimensions == low_projection.blocker_dimensions
    assert high_projection.blocked_reasons == low_projection.blocked_reasons
    assert high_projection.truth_signal_refs == ()
    assert high_projection.no_grant_policy.revenue_potential_can_upgrade_readiness is False
    assert high_projection.revenue_metric_export.revenue_potential_score == 1.0
    assert high_projection.revenue_metric_export.updates_truth_posteriors is False


def test_public_safe_artifact_cue_requires_no_labor_or_supporter_control() -> None:
    ready = project_scrim_value_conversion_cue(_cue_input())

    assert ready.posture == "conversion_ready"
    assert ready.cue_family == "artifact"
    assert ready.rights_class == "owned"
    assert ready.source_class == "generated_asset"
    assert ready.public_private_mode == "public_archive"

    labor_held = project_scrim_value_conversion_cue(
        _cue_input(operator_labor_policy="operator_recurring_labor_required")
    )
    supporter_held = project_scrim_value_conversion_cue(
        _cue_input(supporter_programming_policy="supporter_controlled_programming")
    )

    assert labor_held.posture == "conversion_held"
    assert "no_hidden_operator_labor" in labor_held.blocker_dimensions
    assert "operator_labor_policy:operator_recurring_labor_required" in labor_held.blocked_reasons

    assert supporter_held.posture == "conversion_held"
    assert "supporter_controlled_programming" in supporter_held.blocked_reasons
    assert supporter_held.no_grant_policy.supporter_controls_programming is False


def test_format_aware_revenue_metrics_are_non_truth_signal_context() -> None:
    projection = project_scrim_value_conversion_cue(
        _cue_input(
            format_id="review",
            source_class="owned_source",
            revenue_metric_refs=("revenue:format:review:artifact",),
            revenue_potential_score=0.72,
        )
    )

    assert projection.revenue_metric_export.format_id == "review"
    assert projection.revenue_metric_export.format_family == "review_comparison"
    assert projection.revenue_metric_export.source_class == "owned_source"
    assert projection.revenue_metric_export.metric_refs == ("revenue:format:review:artifact",)
    assert projection.revenue_metric_export.updates_truth_posteriors is False
    assert "revenue:format:review:artifact" in projection.non_truth_signal_refs
    assert "revenue:format:review:artifact" not in projection.truth_signal_refs


def test_incompatible_target_family_fails_closed() -> None:
    with pytest.raises(ValidationError, match="not valid"):
        _cue_input(cue_family="grant", target_family_id="support_prompt")
