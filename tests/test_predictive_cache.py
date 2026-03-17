"""Tests for predictive pre-computation cache (WS5)."""

from __future__ import annotations

import time

from agents.predictive_cache import CachedScenario, PredictiveCache
from agents.protention_engine import ProtentionSnapshot, TransitionPrediction
from agents.visual_layer_state import AmbientParams


def _prediction(
    dimension: str = "flow",
    value: str = "flow_ending",
    probability: float = 0.6,
    expected_in_s: float = 120.0,
) -> TransitionPrediction:
    return TransitionPrediction(
        dimension=dimension,
        predicted_value=value,
        probability=probability,
        expected_in_s=expected_in_s,
        basis="test",
    )


def _snapshot(*preds: TransitionPrediction) -> ProtentionSnapshot:
    return ProtentionSnapshot(
        predictions=list(preds),
        timestamp=time.monotonic(),
        observation_count=10,
    )


class TestCachedScenario:
    def test_not_expired_when_fresh(self):
        s = CachedScenario(
            prediction=_prediction(),
            ambient_params=AmbientParams(),
            display_state_hint="ambient",
            created_at=time.monotonic(),
            ttl_s=30.0,
        )
        assert not s.expired

    def test_expired_after_ttl(self):
        s = CachedScenario(
            prediction=_prediction(),
            ambient_params=AmbientParams(),
            display_state_hint="ambient",
            created_at=time.monotonic() - 60.0,
            ttl_s=30.0,
        )
        assert s.expired


class TestPrecompute:
    def test_empty_protention_no_scenarios(self):
        cache = PredictiveCache()
        cache.precompute(
            protention=_snapshot(),
            current_flow=0.5,
            current_audio=0.0,
        )
        assert cache.cached_count == 0

    def test_low_probability_filtered(self):
        cache = PredictiveCache()
        cache.precompute(
            protention=_snapshot(_prediction(probability=0.2)),
            current_flow=0.5,
            current_audio=0.0,
        )
        assert cache.cached_count == 0

    def test_flow_ending_precomputed(self):
        cache = PredictiveCache()
        cache.precompute(
            protention=_snapshot(_prediction("flow", "flow_ending", 0.6)),
            current_flow=0.7,
            current_audio=0.0,
        )
        assert cache.cached_count == 1

    def test_flow_continuing_precomputed(self):
        cache = PredictiveCache()
        cache.precompute(
            protention=_snapshot(_prediction("flow", "flow_continuing", 0.7)),
            current_flow=0.7,
            current_audio=0.0,
        )
        assert cache.cached_count == 1

    def test_activity_precomputed(self):
        cache = PredictiveCache()
        cache.precompute(
            protention=_snapshot(_prediction("activity", "browsing", 0.5)),
            current_flow=0.3,
            current_audio=0.0,
        )
        assert cache.cached_count == 1

    def test_multiple_predictions(self):
        cache = PredictiveCache()
        cache.precompute(
            protention=_snapshot(
                _prediction("flow", "flow_ending", 0.6),
                _prediction("activity", "browsing", 0.5),
            ),
            current_flow=0.7,
            current_audio=0.0,
        )
        assert cache.cached_count == 2

    def test_replaces_previous_cache(self):
        cache = PredictiveCache()
        cache.precompute(
            protention=_snapshot(_prediction("flow", "flow_ending", 0.6)),
            current_flow=0.7,
            current_audio=0.0,
        )
        assert cache.cached_count == 1

        # New precompute replaces
        cache.precompute(
            protention=_snapshot(_prediction("activity", "browsing", 0.5)),
            current_flow=0.3,
            current_audio=0.0,
        )
        assert cache.cached_count == 1  # replaced, not accumulated


class TestMatch:
    def test_no_cache_no_match(self):
        cache = PredictiveCache()
        assert cache.match(flow_score=0.1, activity="browsing") is None

    def test_flow_ending_matches(self):
        cache = PredictiveCache()
        cache.precompute(
            protention=_snapshot(_prediction("flow", "flow_ending", 0.6)),
            current_flow=0.7,
            current_audio=0.0,
        )
        # Flow ended (score dropped below 0.6)
        hit = cache.match(flow_score=0.2, activity="browsing")
        assert hit is not None
        assert hit.prediction.predicted_value == "flow_ending"

    def test_flow_ending_no_match_when_still_flowing(self):
        cache = PredictiveCache()
        cache.precompute(
            protention=_snapshot(_prediction("flow", "flow_ending", 0.6)),
            current_flow=0.7,
            current_audio=0.0,
        )
        hit = cache.match(flow_score=0.8, activity="coding")
        assert hit is None

    def test_flow_continuing_matches(self):
        cache = PredictiveCache()
        cache.precompute(
            protention=_snapshot(_prediction("flow", "flow_continuing", 0.7)),
            current_flow=0.7,
            current_audio=0.0,
        )
        hit = cache.match(flow_score=0.7, activity="coding")
        assert hit is not None

    def test_activity_matches(self):
        cache = PredictiveCache()
        cache.precompute(
            protention=_snapshot(_prediction("activity", "browsing", 0.5)),
            current_flow=0.3,
            current_audio=0.0,
        )
        hit = cache.match(flow_score=0.2, activity="browsing")
        assert hit is not None

    def test_activity_no_match_wrong_activity(self):
        cache = PredictiveCache()
        cache.precompute(
            protention=_snapshot(_prediction("activity", "browsing", 0.5)),
            current_flow=0.3,
            current_audio=0.0,
        )
        hit = cache.match(flow_score=0.2, activity="coding")
        assert hit is None

    def test_expired_scenarios_pruned(self):
        cache = PredictiveCache()
        now = time.monotonic()
        cache.precompute(
            protention=_snapshot(_prediction("flow", "flow_ending", 0.6, expected_in_s=1.0)),
            current_flow=0.7,
            current_audio=0.0,
            now=now - 10.0,  # created 10s ago, TTL = 1.5s (1.0 * 1.5)
        )
        hit = cache.match(flow_score=0.1, activity="browsing")
        assert hit is None  # expired
        assert cache.cached_count == 0

    def test_hit_rate_tracking(self):
        cache = PredictiveCache()
        cache.precompute(
            protention=_snapshot(_prediction("flow", "flow_ending", 0.6)),
            current_flow=0.7,
            current_audio=0.0,
        )
        cache.match(flow_score=0.1, activity="")  # hit
        cache.match(flow_score=0.8, activity="coding")  # miss (flow still active, cache empty)
        assert cache._hits == 1
        assert cache._misses == 1
        assert cache.hit_rate == 0.5


class TestAmbientParamsSimulation:
    def test_flow_ending_produces_different_params(self):
        cache = PredictiveCache()
        cache.precompute(
            protention=_snapshot(_prediction("flow", "flow_ending", 0.6)),
            current_flow=0.8,
            current_audio=0.0,
        )
        assert cache.cached_count == 1
        scenario = cache._scenarios[0]
        # Flow ending → low flow → less dampened speed
        assert scenario.ambient_params.speed > 0

    def test_stimmung_affects_precomputed_params(self):
        cache = PredictiveCache()
        # Nominal
        cache.precompute(
            protention=_snapshot(_prediction("flow", "flow_ending", 0.6)),
            current_flow=0.7,
            current_audio=0.0,
            stimmung_stance="nominal",
        )
        nominal_warmth = cache._scenarios[0].ambient_params.color_warmth

        # Degraded
        cache.precompute(
            protention=_snapshot(_prediction("flow", "flow_ending", 0.6)),
            current_flow=0.7,
            current_audio=0.0,
            stimmung_stance="degraded",
        )
        degraded_warmth = cache._scenarios[0].ambient_params.color_warmth

        assert degraded_warmth > nominal_warmth
