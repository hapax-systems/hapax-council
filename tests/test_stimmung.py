"""Tests for SystemStimmung — pure logic data model + collector."""

from __future__ import annotations

import time

from shared.stimmung import (
    _STALE_THRESHOLD_S,
    DimensionReading,
    Stance,
    StimmungCollector,
    SystemStimmung,
)


class TestDimensionReading:
    def test_defaults(self):
        r = DimensionReading()
        assert r.value == 0.0
        assert r.trend == "stable"
        assert r.freshness_s == 0.0

    def test_frozen(self):
        r = DimensionReading(value=0.5, trend="rising", freshness_s=10.0)
        assert r.value == 0.5


class TestSystemStimmung:
    def test_default_stance(self):
        s = SystemStimmung()
        assert s.overall_stance == Stance.NOMINAL

    def test_format_for_prompt(self):
        s = SystemStimmung(
            health=DimensionReading(value=0.1, trend="stable", freshness_s=5.0),
            resource_pressure=DimensionReading(value=0.5, trend="rising", freshness_s=3.0),
            overall_stance=Stance.CAUTIOUS,
        )
        text = s.format_for_prompt()
        assert "cautious" in text
        assert "health: 0.10" in text
        assert "resource_pressure: 0.50 (rising)" in text

    def test_format_for_prompt_stale(self):
        s = SystemStimmung(
            health=DimensionReading(value=0.1, freshness_s=200.0),
        )
        text = s.format_for_prompt()
        assert "stale" in text

    def test_modulation_factor_nominal(self):
        s = SystemStimmung(health=DimensionReading(value=0.1))
        assert s.modulation_factor("health") == 1.0

    def test_modulation_factor_cautious(self):
        s = SystemStimmung(health=DimensionReading(value=0.4))
        assert s.modulation_factor("health") == 0.7

    def test_modulation_factor_degraded(self):
        s = SystemStimmung(health=DimensionReading(value=0.7))
        assert s.modulation_factor("health") == 0.5

    def test_modulation_factor_critical(self):
        s = SystemStimmung(health=DimensionReading(value=0.9))
        assert s.modulation_factor("health") == 0.3

    def test_non_nominal_dimensions(self):
        s = SystemStimmung(
            health=DimensionReading(value=0.1, freshness_s=5.0),
            resource_pressure=DimensionReading(value=0.5, freshness_s=3.0),
            error_rate=DimensionReading(value=0.8, freshness_s=2.0),
        )
        non_nom = s.non_nominal_dimensions
        assert "health" not in non_nom
        assert "resource_pressure" in non_nom
        assert "error_rate" in non_nom

    def test_non_nominal_excludes_stale(self):
        s = SystemStimmung(
            error_rate=DimensionReading(value=0.9, freshness_s=200.0),
        )
        assert "error_rate" not in s.non_nominal_dimensions


class TestStimmungCollector:
    def test_empty_snapshot_is_nominal(self):
        c = StimmungCollector()
        s = c.snapshot(now=100.0)
        assert s.overall_stance == Stance.NOMINAL

    def test_healthy_system(self):
        c = StimmungCollector()
        c.update_health(healthy=10, total=10)
        c.update_gpu(used_mb=3000, total_mb=24000)
        s = c.snapshot()
        assert s.overall_stance == Stance.NOMINAL
        assert s.health.value == 0.0
        assert s.resource_pressure.value < 0.3

    def test_degraded_health(self):
        c = StimmungCollector()
        c.update_health(healthy=3, total=10)
        s = c.snapshot()
        assert s.health.value == 0.7
        assert s.overall_stance in (Stance.DEGRADED, Stance.CRITICAL)

    def test_critical_gpu(self):
        c = StimmungCollector()
        c.update_gpu(used_mb=22000, total_mb=24000)
        s = c.snapshot()
        assert s.resource_pressure.value > 0.85
        assert s.overall_stance == Stance.CRITICAL

    def test_engine_errors(self):
        c = StimmungCollector()
        c.update_engine(events_processed=100, actions_executed=50, errors=40, uptime_s=300)
        s = c.snapshot()
        assert s.error_rate.value == 0.8

    def test_perception_stale(self):
        c = StimmungCollector()
        c.update_perception(freshness_s=60.0)
        s = c.snapshot()
        assert s.perception_confidence.value == 1.0  # capped at 1.0

    def test_perception_fresh(self):
        c = StimmungCollector()
        c.update_perception(freshness_s=2.0, confidence=0.9)
        s = c.snapshot()
        assert s.perception_confidence.value < 0.2

    def test_langfuse_cost(self):
        c = StimmungCollector()
        c.update_langfuse(daily_cost=3.0, error_count=0, total_traces=100)
        s = c.snapshot()
        assert s.llm_cost_pressure.value == 0.6

    def test_trend_rising(self):
        c = StimmungCollector()
        c.update_gpu(used_mb=5000, total_mb=24000)
        c.update_gpu(used_mb=10000, total_mb=24000)
        c.update_gpu(used_mb=15000, total_mb=24000)
        s = c.snapshot()
        assert s.resource_pressure.trend == "rising"

    def test_trend_falling(self):
        c = StimmungCollector()
        c.update_gpu(used_mb=20000, total_mb=24000)
        c.update_gpu(used_mb=15000, total_mb=24000)
        c.update_gpu(used_mb=10000, total_mb=24000)
        s = c.snapshot()
        assert s.resource_pressure.trend == "falling"

    def test_trend_stable(self):
        c = StimmungCollector()
        c.update_gpu(used_mb=10000, total_mb=24000)
        c.update_gpu(used_mb=12000, total_mb=24000)
        c.update_gpu(used_mb=11000, total_mb=24000)
        s = c.snapshot()
        assert s.resource_pressure.trend == "stable"

    def test_stance_thresholds(self):
        c = StimmungCollector()
        # All nominal
        c.update_health(healthy=10, total=10)
        assert c.snapshot().overall_stance == Stance.NOMINAL

        # Cautious (0.3 ≤ worst < 0.6)
        c.update_health(healthy=6, total=10)
        assert c.snapshot().overall_stance == Stance.CAUTIOUS

        # Degraded (0.6 ≤ worst < 0.85)
        c.update_health(healthy=3, total=10)
        assert c.snapshot().overall_stance == Stance.DEGRADED

        # Critical (worst ≥ 0.85)
        c.update_health(healthy=1, total=10)
        assert c.snapshot().overall_stance == Stance.CRITICAL

    def test_stale_dimensions_excluded_from_stance(self):
        """Stale dimensions shouldn't drive stance to critical."""
        c = StimmungCollector()
        c.update_health(healthy=1, total=10)
        # Snapshot far in the future — health becomes stale
        s = c.snapshot(now=time.monotonic() + _STALE_THRESHOLD_S + 10)
        assert s.overall_stance == Stance.NOMINAL

    def test_zero_total_ignored(self):
        c = StimmungCollector()
        c.update_health(healthy=0, total=0)
        c.update_gpu(used_mb=100, total_mb=0)
        s = c.snapshot(now=100.0)
        assert s.overall_stance == Stance.NOMINAL
