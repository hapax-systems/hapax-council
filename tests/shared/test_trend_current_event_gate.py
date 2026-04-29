"""Tests for the deterministic trend/current-event gate helper."""

from __future__ import annotations

from shared.trend_current_event_gate import (
    GateAction,
    GateInfraction,
    TrendCurrentEventCandidate,
    evaluate_candidate,
    load_policy,
    validate_policy,
)


def _candidate(**overrides: object) -> TrendCurrentEventCandidate:
    payload = {
        "candidate_id": "candidate_a",
        "claim_type": "current_event_claim",
        "proposed_format": "explainer",
        "public_mode": "public_archive",
        "source_age_s": 300.0,
        "source_ttl_s": 3600.0,
        "event_age_s": 172800.0,
        "primary_source_count": 1,
        "official_source_count": 0,
        "corroborating_source_count": 2,
        "recency_label_present": True,
        "title_uncertainty_present": True,
        "description_uncertainty_present": True,
        "sensitivity_categories": (),
        "edsa_context_present": False,
        "monetized": False,
        "trend_used_as_truth": False,
        "trend_decay_score": 0.42,
        "source_bias_score": 0.2,
    }
    payload.update(overrides)
    return TrendCurrentEventCandidate(**payload)


def test_default_policy_validates() -> None:
    assert validate_policy(load_policy()) == []


def test_all_constraints_passing_allows_public_claim() -> None:
    result = evaluate_candidate(_candidate())

    assert result.action is GateAction.ALLOW_PUBLIC_CLAIM
    assert result.public_claim_allowed is True
    assert result.monetization_allowed is False
    assert result.blockers == ()
    assert result.infractions == ()
    assert result.scoring_features == {"trend_decay_score": 0.42, "source_bias_score": 0.2}


def test_missing_freshness_or_primary_corroboration_blocks_public_claim() -> None:
    result = evaluate_candidate(
        _candidate(
            source_age_s=None,
            source_ttl_s=None,
            primary_source_count=0,
            official_source_count=0,
            corroborating_source_count=1,
        )
    )

    assert result.action is GateAction.BLOCK_PUBLIC_CLAIM
    assert result.public_claim_allowed is False
    assert GateInfraction.MISSING_FRESHNESS in result.infractions
    assert GateInfraction.MISSING_PRIMARY_OR_OFFICIAL_SOURCE in result.infractions


def test_under_24h_definitive_format_downgrades_to_watch() -> None:
    result = evaluate_candidate(
        _candidate(
            proposed_format="ranking",
            event_age_s=7200.0,
        )
    )

    assert result.action is GateAction.DOWNGRADE_TO_WATCH
    assert result.public_claim_allowed is False
    assert result.required_format_family == "watching_or_audit"
    assert GateInfraction.UNDER_24H_DEFINITIVE_FORMAT in result.infractions


def test_sensitive_event_forces_refusal_format_and_demonetizes() -> None:
    result = evaluate_candidate(
        _candidate(
            proposed_format="ranking",
            public_mode="public_monetizable",
            monetized=True,
            sensitivity_categories=("health", "identifiable_persons"),
            edsa_context_present=False,
        )
    )

    assert result.action is GateAction.FORCE_REFUSAL_FORMAT
    assert result.public_claim_allowed is False
    assert result.monetization_allowed is False
    assert result.required_format_family == "refusal_or_audit"
    assert GateInfraction.SENSITIVE_EVENT_EXPLOITATION in result.infractions


def test_missing_title_or_description_uncertainty_blocks_public_copy() -> None:
    result = evaluate_candidate(
        _candidate(
            title_uncertainty_present=False,
            description_uncertainty_present=True,
        )
    )

    assert result.action is GateAction.DOWNGRADE_TO_WATCH
    assert result.public_claim_allowed is False
    assert "uncertainty_language" in result.required_copy_fields
    assert GateInfraction.MISSING_UNCERTAINTY_LANGUAGE in result.infractions


def test_trend_as_truth_is_hard_block_even_with_scores_present() -> None:
    result = evaluate_candidate(_candidate(trend_used_as_truth=True))

    assert result.action is GateAction.BLOCK_PUBLIC_CLAIM
    assert result.public_claim_allowed is False
    assert GateInfraction.TREND_AS_TRUTH in result.infractions
    assert result.scoring_features["trend_decay_score"] == 0.42
    assert result.scoring_features["source_bias_score"] == 0.2


def test_missing_source_bias_or_trend_decay_keeps_scores_from_becoming_truth() -> None:
    result = evaluate_candidate(_candidate(trend_decay_score=None, source_bias_score=None))

    assert result.action is GateAction.DOWNGRADE_TO_WATCH
    assert result.public_claim_allowed is False
    assert GateInfraction.SOURCE_BIAS_UNTRACKED in result.infractions
    assert result.scoring_features == {"trend_decay_score": None, "source_bias_score": None}
