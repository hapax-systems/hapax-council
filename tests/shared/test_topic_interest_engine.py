from __future__ import annotations

from datetime import UTC, datetime

import pytest

from shared.content_candidate_discovery import discover_candidates
from shared.impingement import ImpingementType, render_impingement_text
from shared.topic_interest_engine import (
    TopicInterestObservation,
    TopicInterestScoreVector,
    decide_topic_interest,
)

NOW = datetime(2026, 6, 11, 19, 55, tzinfo=UTC)


def _signals(**overrides: float) -> TopicInterestScoreVector:
    values = {
        "novelty": 0.78,
        "surprise": 0.72,
        "relevance": 0.82,
        "evidence_density": 0.86,
        "trajectory": 0.65,
        "public_value": 0.66,
        "research_value": 0.84,
        "actionability": 0.78,
        "staleness": 0.0,
        "rights_privacy_risk": 0.05,
        "claim_risk": 0.05,
        "duplicate_pressure": 0.0,
        "operator_cost": 0.10,
    }
    values.update(overrides)
    return TopicInterestScoreVector(**values)


def _observation(**overrides: object) -> TopicInterestObservation:
    values = {
        "observation_id": "obs-research-gap",
        "source_kind": "chronicle_event",
        "source_id": "chronicle:evt-1",
        "subject": "persistent review loop discovered a reusable publication-bus invariant",
        "subject_cluster": "publication_bus_review_invariants",
        "observed_at": NOW,
        "retrieved_at": NOW,
        "freshness_ttl_s": 3600,
        "format_id": "research_note",
        "source_class": "local_state",
        "public_mode": "dry_run",
        "rights_state": "operator_original",
        "evidence_refs": ("chronicle:evt-1", "task:abc"),
        "provenance_refs": ("chronicle:query:1",),
        "substrate_refs": ("vault:task-note",),
        "grounding_question": "What invariant was exposed and what downstream gate should change?",
        "signals": _signals(),
    }
    values.update(overrides)
    return TopicInterestObservation(**values)


def test_under_evidenced_novelty_routes_to_research_more_not_content() -> None:
    obs = _observation(
        observation_id="obs-under-evidenced",
        evidence_refs=(),
        provenance_refs=(),
        freshness_ttl_s=None,
        signals=_signals(evidence_density=0.20, public_value=0.20, actionability=0.62),
    )

    decision = decide_topic_interest(obs, now=NOW)

    assert decision.action == "research_more"
    assert decision.content_observation is None
    assert decision.impingement is not None
    assert decision.impingement.type == ImpingementType.CURIOSITY
    assert decision.impingement.content["metric"] == "topic_interest"
    assert decision.impingement.content["publication_candidate_allowed"] is False
    assert "evidence_refs_missing" in decision.blocked_reasons
    rendered = render_impingement_text(decision.impingement)
    assert "concern: evidence_refs_missing" in rendered


def test_evidence_dense_local_state_emits_impingement_and_content_observation() -> None:
    decision = decide_topic_interest(_observation(), now=NOW)

    assert decision.action == "emit_content_observation"
    assert decision.impingement is not None
    assert decision.content_observation is not None
    assert decision.content_observation.source_priors["topic_interest_score"] == pytest.approx(
        decision.score
    )
    assert decision.impingement.content["publication_candidate_allowed"] is True
    assert decision.impingement.content["programme_impingement_allowed"] is True

    discovery = discover_candidates([decision.content_observation], now=NOW)
    assert discovery[0].status == "emitted"
    assert discovery[0].scheduler_action == "emit_candidate"
    assert discovery[0].opportunity.subject_cluster == "publication_bus_review_invariants"


def test_impingement_text_carries_systemic_routing_fields() -> None:
    decision = decide_topic_interest(_observation(), now=NOW)

    assert decision.impingement is not None
    rendered = render_impingement_text(decision.impingement)

    assert "signal: topic_interest" in rendered
    assert "action tendency: emit_content_observation" in rendered
    assert "evidence refs: chronicle:evt-1, task:abc" in rendered
    assert "claim posture: tie_obs-research-gap" in rendered
    assert "learning policy:" in rendered


def test_rights_privacy_risk_blocks_content_observation() -> None:
    obs = _observation(
        observation_id="obs-uncleared",
        public_mode="public_live",
        rights_state="third_party_uncleared",
        signals=_signals(rights_privacy_risk=0.82, public_value=0.90),
    )

    decision = decide_topic_interest(obs, now=NOW)

    assert decision.action == "research_more"
    assert decision.content_observation is None
    assert decision.impingement is not None
    assert decision.impingement.content["publication_candidate_allowed"] is False
    assert "rights_state_uncleared" in decision.blocked_reasons


def test_current_event_output_is_dry_run_and_not_truth_warrant() -> None:
    obs = _observation(
        observation_id="obs-current-event",
        source_kind="external_reference",
        source_class="trend_sources",
        public_mode="public_live",
        current_event_claim=True,
        trend_current_event=True,
        primary_source_count=2,
        official_source_count=1,
        corroborating_source_count=2,
        recency_label_present=True,
        title_uncertainty_present=True,
        description_uncertainty_present=True,
        signals=_signals(claim_risk=0.18, public_value=0.88),
    )

    decision = decide_topic_interest(obs, now=NOW)

    assert decision.action == "emit_content_observation"
    assert decision.content_observation is not None
    assert decision.content_observation.public_mode == "dry_run"
    assert decision.content_observation.current_event_claim is True
    assert decision.content_observation.source_bias_score is None
    assert "public_mode_downgraded_to_dry_run" in decision.downgrade_reasons


def test_trend_used_as_truth_blocks_content_observation() -> None:
    obs = _observation(
        observation_id="obs-trend-as-truth",
        source_kind="external_reference",
        source_class="trend_sources",
        public_mode="public_live",
        current_event_claim=True,
        trend_current_event=True,
        trend_used_as_truth=True,
        signals=_signals(public_value=0.92, claim_risk=0.10),
    )

    decision = decide_topic_interest(obs, now=NOW)

    assert decision.action == "research_more"
    assert decision.content_observation is None
    assert decision.impingement is not None
    assert decision.impingement.content["publication_candidate_allowed"] is False
    assert "trend_used_as_truth_forbidden" in decision.blocked_reasons


def test_naive_observed_at_is_normalized_before_discovery() -> None:
    obs = _observation(
        observation_id="obs-naive-current-event",
        source_kind="external_reference",
        source_class="trend_sources",
        public_mode="public_live",
        observed_at=datetime(2026, 6, 11, 19, 55),
        retrieved_at=datetime(2026, 6, 11, 19, 55),
        current_event_claim=True,
        trend_current_event=True,
        signals=_signals(claim_risk=0.18, public_value=0.88),
    )

    decision = decide_topic_interest(obs, now=NOW)

    assert decision.content_observation is not None
    assert decision.content_observation.published_at is not None
    assert decision.content_observation.published_at.tzinfo is UTC
    discovery = discover_candidates([decision.content_observation], now=NOW)
    assert discovery[0].observation_id == "tie_obs-naive-current-event"


def test_source_bias_score_maps_only_explicit_bias_measurement() -> None:
    without_bias = decide_topic_interest(_observation(observation_id="obs-no-bias"), now=NOW)
    with_bias = decide_topic_interest(
        _observation(observation_id="obs-with-bias", source_bias_score=0.42),
        now=NOW,
    )

    assert without_bias.content_observation is not None
    assert with_bias.content_observation is not None
    assert without_bias.content_observation.source_bias_score is None
    assert with_bias.content_observation.source_bias_score == 0.42


def test_duplicate_pressure_suppresses_impingement_to_avoid_alert_fatigue() -> None:
    obs = _observation(
        observation_id="obs-duplicate",
        recent_duplicate_count=12,
        signals=_signals(duplicate_pressure=0.95),
    )

    decision = decide_topic_interest(obs, now=NOW)

    assert decision.action == "watch"
    assert decision.impingement is None
    assert decision.content_observation is None
    assert "duplicate_pressure_present" in decision.downgrade_reasons


def test_operator_authority_routes_question_without_content_candidate() -> None:
    obs = _observation(
        observation_id="obs-authority",
        requires_operator_authority=True,
        signals=_signals(novelty=0.98, surprise=0.92, public_value=0.90),
    )

    decision = decide_topic_interest(obs, now=NOW)

    assert decision.action == "operator_question"
    assert decision.content_observation is None
    assert decision.impingement is not None
    assert decision.impingement.content["action_tendency"] == "operator_question"
    assert decision.impingement.content["programme_impingement_allowed"] is False
