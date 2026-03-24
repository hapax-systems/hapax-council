"""Tests for TrendEngine — EMA, Z-score, CUSUM, trend classification."""

from __future__ import annotations

import unittest

from agents.fortress.schema import FastFortressState
from agents.fortress.trends import TRACKED_VARIABLES, TrendEngine, VariableTracker


def _state(
    *,
    tick: int = 1000,
    food: int = 200,
    drink: int = 100,
    population: int = 50,
    idle: int = 5,
    stress: int = 5000,
    threats: int = 0,
    jobs: int = 10,
) -> FastFortressState:
    return FastFortressState(
        timestamp=0.0,
        game_tick=tick,
        year=1,
        season=0,
        month=0,
        day=0,
        fortress_name="Test",
        paused=False,
        population=population,
        food_count=food,
        drink_count=drink,
        active_threats=threats,
        job_queue_length=jobs,
        idle_dwarf_count=idle,
        most_stressed_value=stress,
    )


class TestVariableTracker(unittest.TestCase):
    def test_single_push_sets_mean(self) -> None:
        t = VariableTracker()
        t.push(100.0, 1000)
        assert t.n == 1
        assert t.ewma_mean == 100.0
        assert t.ewma_var == 0.0

    def test_ema_rate_computed(self) -> None:
        t = VariableTracker()
        t.push(100.0, 1000)
        t.push(110.0, 1010)
        # rate = (110 - 100) / 10 = 1.0, n=1 so ema = alpha*1.0 + (1-alpha)*0 = 0.2
        assert abs(t.ema_rate - 0.2) < 0.01

    def test_ema_rate_smooths(self) -> None:
        t = VariableTracker()
        t.push(100.0, 1000)
        t.push(110.0, 1010)  # raw=1.0, ema=0.2*1.0+0.8*0.0=0.2
        t.push(110.0, 1020)  # raw=0.0, ema=0.2*0.0+0.8*0.2=0.16
        assert abs(t.ema_rate - 0.16) < 0.01

    def test_z_score_zero_variance(self) -> None:
        t = VariableTracker()
        t.push(100.0, 1000)
        assert t.z_score(100.0) == 0.0

    def test_z_score_nonzero(self) -> None:
        t = VariableTracker()
        for i in range(10):
            t.push(100.0 + i * 10, 1000 + i * 10)
        z = t.z_score(200.0)
        # Should be nonzero since we have variance
        assert z != 0.0

    def test_cusum_no_shift(self) -> None:
        t = VariableTracker()
        result = t.cusum_check(10.0, 10.0)
        assert result is None

    def test_cusum_shift_up(self) -> None:
        t = VariableTracker()
        result = None
        for _ in range(20):
            result = t.cusum_check(12.0, 10.0, threshold=5.0, drift=0.5)
            if result is not None:
                break
        assert result == "shift_up"

    def test_cusum_shift_down(self) -> None:
        t = VariableTracker()
        result = None
        for _ in range(20):
            result = t.cusum_check(8.0, 10.0, threshold=5.0, drift=0.5)
            if result is not None:
                break
        assert result == "shift_down"

    def test_deque_maxlen(self) -> None:
        t = VariableTracker()
        for i in range(50):
            t.push(float(i), i * 10)
        assert len(t.values) == 30
        assert t.n == 50


class TestTrendEngine(unittest.TestCase):
    def test_all_tracked_variables_initialized(self) -> None:
        engine = TrendEngine()
        assert set(engine._trackers.keys()) == set(TRACKED_VARIABLES)

    def test_unknown_trend_with_few_samples(self) -> None:
        engine = TrendEngine()
        engine.push(_state(tick=1000, food=200))
        assert engine.trend("food_count") == "unknown"

    def test_stable_trend(self) -> None:
        engine = TrendEngine()
        for i in range(5):
            engine.push(_state(tick=1000 + i * 100, food=200))
        assert engine.trend("food_count") == "stable"

    def test_rising_trend(self) -> None:
        engine = TrendEngine()
        for i in range(10):
            engine.push(_state(tick=1000 + i * 120, food=200 + i * 50))
        trend = engine.trend("food_count")
        assert trend == "rising"

    def test_declining_trend(self) -> None:
        engine = TrendEngine()
        for i in range(10):
            engine.push(_state(tick=1000 + i * 120, food=500 - i * 20))
        trend = engine.trend("food_count")
        assert trend in ("declining", "crashing")

    def test_crashing_trend(self) -> None:
        engine = TrendEngine()
        for i in range(10):
            engine.push(_state(tick=1000 + i * 120, food=1000 - i * 100))
        trend = engine.trend("food_count")
        assert trend == "crashing"

    def test_no_anomalies_with_stable_data(self) -> None:
        engine = TrendEngine()
        for i in range(10):
            engine.push(_state(tick=1000 + i * 100, food=200))
        assert engine.anomalies() == []

    def test_anomaly_z_score_grows_with_deviation(self) -> None:
        """Verify z-score increases with deviation from EWMA mean.

        With alpha=0.2 EWMA, a single-sample spike produces z ≈ 2.236
        (mathematical ceiling of sqrt((1-alpha)/alpha)). We verify the
        mechanism produces a significant z-score on large deviations
        by calling z_score() without pushing the outlier value.
        """
        tracker = VariableTracker()
        # Baseline with slight natural variance so ewma_var > 0
        for i in range(15):
            tracker.push(5.0 + (i % 3), 1000 + i * 100)
        # Compute z-score for hypothetical extreme without pushing it
        z = tracker.z_score(5000.0)
        assert abs(z) > 50, f"Expected large z but got {z}"

    def test_projection_when_declining(self) -> None:
        engine = TrendEngine()
        for i in range(5):
            engine.push(_state(tick=1000 + i * 120, food=500 - i * 50))
        projections = engine.projections()
        assert any("food_count" in p for p in projections)

    def test_no_projection_when_rising(self) -> None:
        engine = TrendEngine()
        for i in range(5):
            engine.push(_state(tick=1000 + i * 120, food=200 + i * 50))
        projections = engine.projections()
        food_projections = [p for p in projections if "food_count" in p]
        assert len(food_projections) == 0

    def test_trends_summary_returns_all_variables(self) -> None:
        engine = TrendEngine()
        for i in range(5):
            engine.push(_state(tick=1000 + i * 100))
        summary = engine.trends_summary()
        assert set(summary.keys()) == set(TRACKED_VARIABLES)


if __name__ == "__main__":
    unittest.main()
