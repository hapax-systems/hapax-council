"""Tests for content candidate discovery decisions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from shared.content_candidate_discovery import (
    ContentSourceObservation,
    discover_candidates,
    load_policy,
)

NOW = datetime(2026, 4, 29, 4, 40, tzinfo=UTC)


def _observation(**overrides: object) -> ContentSourceObservation:
    payload = {
        "observation_id": "obs_model_route_tierlist",
        "source_class": "local_state",
        "source_id": "local_model_grounding_scout",
        "format_id": "tier_list",
        "subject": "source-acquiring model route candidates",
        "subject_cluster": "model_routing_grounding",
        "retrieved_at": NOW - timedelta(minutes=5),
        "published_at": NOW - timedelta(hours=2),
        "freshness_ttl_s": 3600,
        "public_mode": "public_archive",
        "rights_state": "operator_original",
        "rights_hints": ("operator_original",),
        "substrate_refs": ("research_brief",),
        "evidence_refs": ("local:research_brief",),
        "provenance_refs": ("obsidian:research_brief",),
        "source_priors": {"grounding_yield_prior": 0.7},
        "grounding_question": "Which model-route candidates can Hapax justify from current evidence?",
    }
    payload.update(overrides)
    return ContentSourceObservation(**payload)


def test_local_state_candidate_emits_without_scheduling() -> None:
    decision = discover_candidates([_observation()], now=NOW)[0]

    assert decision.status == "emitted"
    assert decision.scheduler_action == "emit_candidate"
    assert decision.scheduled_show_created is False
    assert decision.opportunity.public_mode == "public_archive"
    assert decision.opportunity.public_selectable is True
    assert decision.opportunity.source_priors == {"grounding_yield_prior": 0.7}
    assert decision.gates["freshness"].state == "pass"
    assert decision.gates["trend_current_event"].state == "not_applicable"


def test_supporter_controlled_or_request_queue_is_hard_blocked() -> None:
    decision = discover_candidates(
        [
            _observation(
                supporter_controlled=True,
                per_person_request=True,
            )
        ],
        now=NOW,
    )[0]

    assert decision.status == "blocked"
    assert decision.scheduler_action == "block"
    assert "supporter_controlled_programming_forbidden" in decision.blocked_reasons
    assert "per_person_request_queue_forbidden" in decision.blocked_reasons
    assert decision.opportunity.public_selectable is False


def test_stale_or_missing_freshness_holds_candidate_for_refresh() -> None:
    decision = discover_candidates(
        [_observation(retrieved_at=NOW - timedelta(hours=3), freshness_ttl_s=600)],
        now=NOW,
    )[0]

    assert decision.status == "held"
    assert decision.scheduler_action == "hold_for_refresh"
    assert "source_refresh_required" in decision.blocked_reasons
    assert decision.gates["freshness"].state == "fail"
    assert decision.opportunity.public_selectable is False


def test_trend_candidate_under_24h_downgrades_to_dry_run() -> None:
    decision = discover_candidates(
        [
            _observation(
                source_class="trend_sources",
                source_id="official_release_rss",
                format_id="ranking",
                public_mode="public_archive",
                rights_state="public_domain",
                current_event_claim=True,
                published_at=NOW - timedelta(hours=3),
                primary_source_count=1,
                corroborating_source_count=2,
                recency_label_present=True,
                title_uncertainty_present=True,
                description_uncertainty_present=True,
                trend_decay_score=0.4,
                source_bias_score=0.2,
            )
        ],
        now=NOW,
    )[0]

    assert decision.status == "emitted"
    assert decision.opportunity.public_mode == "dry_run"
    assert decision.opportunity.public_selectable is False
    assert "under_24h_event_requires_watch_audit_or_refusal" in decision.blocked_reasons
    assert decision.gates["trend_current_event"].state == "fail"


def test_trend_currentness_never_becomes_truth_warrant() -> None:
    decision = discover_candidates(
        [
            _observation(
                source_class="trend_sources",
                source_id="trend_feed",
                current_event_claim=True,
                trend_used_as_truth=True,
                primary_source_count=1,
                corroborating_source_count=2,
                recency_label_present=True,
                title_uncertainty_present=True,
                description_uncertainty_present=True,
                trend_decay_score=0.9,
                source_bias_score=0.1,
            )
        ],
        now=NOW,
    )[0]

    assert decision.status == "held"
    assert decision.scheduler_action == "hold_for_refresh"
    assert "trend_currentness_is_not_truth_warrant" in decision.blocked_reasons
    assert decision.opportunity.public_selectable is False


def test_policy_config_is_enabled_and_conservative() -> None:
    policy = load_policy()

    assert policy.enabled is True
    assert policy.global_policy.single_operator_only is True
    assert policy.global_policy.schedules_programmes_directly is False
    assert policy.global_policy.creates_supporter_request_queue is False
    assert policy.global_policy.trend_as_truth_allowed is False
    assert set(policy.source_class_modes["ambient_aggregate_audience"]) == {"private", "dry_run"}
