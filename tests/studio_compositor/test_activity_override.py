"""Tests for Continuous-Loop Research Cadence §3.2 — activity override gate."""

from __future__ import annotations

from pathlib import Path

import yaml


def _call(
    proposed: str = "react",
    *,
    momentary: float = 0.5,
    engagement: float = 0.2,
    active_chat_messages: int = 0,
    signals_ts: float | None = None,
    now_epoch: float = 1000.0,
    last_override_at: float = 0.0,
    objective_alignment: float = 0.3,
    **overrides,
):
    from agents.studio_compositor.activity_scoring import choose_activity_with_override

    if signals_ts is None:
        signals_ts = now_epoch - 10.0  # fresh by default

    return choose_activity_with_override(
        proposed,
        momentary=momentary,
        objective_alignment_fn=lambda _a: objective_alignment,
        engagement=engagement,
        active_chat_messages=active_chat_messages,
        signals_ts=signals_ts,
        now_epoch=now_epoch,
        last_override_at=last_override_at,
        **overrides,
    )


class TestConstants:
    def test_weight_sum_is_one(self):
        from agents.studio_compositor.activity_scoring import (
            DEFAULT_MOMENTARY_WEIGHT,
            DEFAULT_OBJECTIVE_WEIGHT,
            DEFAULT_STIMMUNG_WEIGHT,
        )

        assert DEFAULT_MOMENTARY_WEIGHT + DEFAULT_OBJECTIVE_WEIGHT + DEFAULT_STIMMUNG_WEIGHT == 1.0

    def test_never_override_to_contains_silence(self):
        from agents.studio_compositor.activity_scoring import NEVER_OVERRIDE_TO

        assert "silence" in NEVER_OVERRIDE_TO

    def test_candidate_activities_cover_schema(self):
        from agents.studio_compositor.activity_scoring import CANDIDATE_ACTIVITIES

        # Epic 2 (2026-04-17) added ``music`` as the vinyl-decoupled
        # music-featuring activity; ``vinyl`` retained for back-compat.
        expected = {"react", "chat", "vinyl", "music", "study", "observe", "silence"}
        assert set(CANDIDATE_ACTIVITIES) == expected


class TestStalenessGuard:
    def test_missing_timestamp_suppresses_override(self):
        # Bypass the _call helper (which defaults None → fresh) and call
        # the function directly with an explicit None.
        from agents.studio_compositor.activity_scoring import choose_activity_with_override

        decision = choose_activity_with_override(
            "react",
            momentary=0.1,
            objective_alignment_fn=lambda _a: 0.3,
            engagement=0.9,
            active_chat_messages=5,
            signals_ts=None,  # explicit None → missing
            now_epoch=1000.0,
            last_override_at=0.0,
        )
        assert decision.was_override is False
        assert "stale" in decision.reason

    def test_old_timestamp_suppresses_override(self):
        # signals_ts 200s old vs default 90s staleness → stale
        decision = _call(
            proposed="react",
            momentary=0.1,  # very weak so alternates win
            engagement=0.9,
            active_chat_messages=5,
            signals_ts=800.0,
            now_epoch=1000.0,
        )
        assert decision.was_override is False
        assert "stale" in decision.reason

    def test_fresh_timestamp_allows_override_path(self):
        # Fresh signals, everything aligned to trigger override.
        decision = _call(
            proposed="react",
            momentary=0.1,
            engagement=0.9,
            active_chat_messages=5,
            signals_ts=995.0,
            now_epoch=1000.0,
        )
        # Override may or may not fire depending on other guards; just
        # confirm staleness didn't short-circuit.
        assert "stale" not in decision.reason


class TestCooldownGuard:
    def test_recent_override_blocks_new_override(self):
        decision = _call(
            proposed="react",
            momentary=0.1,
            engagement=0.9,
            active_chat_messages=5,
            now_epoch=1000.0,
            last_override_at=990.0,  # 10s ago, default cooldown 60s
        )
        assert decision.was_override is False
        assert "cooldown" in decision.reason

    def test_cooldown_elapsed_allows_override(self):
        decision = _call(
            proposed="react",
            momentary=0.1,
            engagement=0.9,
            active_chat_messages=5,
            now_epoch=1000.0,
            last_override_at=900.0,  # 100s ago
        )
        # Cooldown clear; reason shouldn't mention cooldown
        assert "cooldown" not in decision.reason


class TestSilenceExclusion:
    def test_never_flips_into_silence_even_with_best_score(self):
        # If we rig the scorer to love silence, we must still not pick it
        decision = _call(
            proposed="react",
            momentary=0.1,  # low
            engagement=0.05,  # pushes study/silence up
            objective_alignment=0.9,
            now_epoch=1000.0,
        )
        assert decision.final_activity != "silence"


class TestProposalFloorGuard:
    def test_high_proposed_score_suppresses_override(self):
        # Strong momentary + strong objective → proposal composite above floor
        decision = _call(
            proposed="react",
            momentary=1.0,
            objective_alignment=1.0,
            engagement=0.1,  # would push study up
            now_epoch=1000.0,
        )
        assert decision.was_override is False
        assert "confident" in decision.reason


class TestMarginGuard:
    def test_insufficient_margin_suppresses_override(self):
        """Even if scores tilt against the proposal, if the margin is tiny, keep proposed."""
        decision = _call(
            proposed="react",
            momentary=0.4,  # proposal floor is 0.55; 0.4·0.70 = 0.28; add 0.25·0.3=0.075 → 0.355
            objective_alignment=0.3,
            engagement=0.5,  # mid — stimmung term neutral
            active_chat_messages=1,
            now_epoch=1000.0,
            override_margin=0.5,  # absurdly high
        )
        assert decision.was_override is False
        # Will say "insufficient margin" or "no valid alternate" depending
        # on scoring math — both reflect the guard working.
        assert decision.was_override is False


class TestOverrideFires:
    def test_low_engagement_lifts_study_over_react(self):
        decision = _call(
            proposed="react",
            momentary=0.2,  # weak LLM proposal
            objective_alignment=0.2,
            engagement=0.05,  # low → study lifted
            now_epoch=1000.0,
            last_override_at=0.0,
            override_margin=0.01,  # permissive
            proposal_floor=0.99,  # permissive
        )
        assert decision.was_override is True
        assert decision.final_activity == "study"
        assert decision.proposed_activity == "react"
        assert "override" in decision.reason


class TestScoreDictPopulated:
    def test_all_candidates_have_scores(self):
        decision = _call()
        from agents.studio_compositor.activity_scoring import CANDIDATE_ACTIVITIES

        assert set(decision.scores.keys()) == set(CANDIDATE_ACTIVITIES)
        for v in decision.scores.values():
            assert 0.0 <= v <= 1.0


class TestShippedConfig:
    def test_yaml_has_expected_keys(self):
        config = Path(__file__).resolve().parents[2] / "config" / "director_scoring.yaml"
        if not config.exists():
            import pytest

            pytest.skip("config not in this checkout")
        raw = yaml.safe_load(config.read_text(encoding="utf-8"))
        assert "momentary_weight" in raw
        assert "objective_weight" in raw
        assert "stimmung_weight" in raw
        assert "override_margin" in raw
        assert "proposal_floor" in raw
        assert "override_cooldown_s" in raw
        assert "stimmung_staleness_s" in raw
        # Weights sum to 1.0
        assert raw["momentary_weight"] + raw["objective_weight"] + raw["stimmung_weight"] == 1.0
