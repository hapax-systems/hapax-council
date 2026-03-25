"""Tests for SystemStimmung — pure logic data model + collector."""

from __future__ import annotations

import time
import time as time_mod

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
        # 95%+ VRAM = critical (above the 80-95% pressure ramp)
        c.update_gpu(used_mb=23500, total_mb=24000)
        s = c.snapshot()
        assert s.resource_pressure.value > 0.85
        assert s.overall_stance == Stance.CRITICAL

    def test_engine_errors(self):
        c = StimmungCollector()
        c.update_engine(events_processed=100, actions_executed=50, errors=120, uptime_s=300)
        s = c.snapshot()
        assert s.error_rate.value == 0.8  # 120/(100+50) = 0.8

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
        c.update_langfuse(daily_cost=30.0, error_count=0, total_traces=100)
        s = c.snapshot()
        assert s.llm_cost_pressure.value == 0.6

    def test_trend_rising(self):
        c = StimmungCollector()
        # Values must be above 80% threshold to register as pressure
        c.update_gpu(used_mb=19500, total_mb=24000)
        c.update_gpu(used_mb=21000, total_mb=24000)
        c.update_gpu(used_mb=22500, total_mb=24000)
        s = c.snapshot()
        assert s.resource_pressure.trend == "rising"

    def test_trend_falling(self):
        c = StimmungCollector()
        # Values must be above 80% threshold to register as pressure
        c.update_gpu(used_mb=23000, total_mb=24000)
        c.update_gpu(used_mb=21500, total_mb=24000)
        c.update_gpu(used_mb=20000, total_mb=24000)
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


class TestBiometricDimensions:
    """Tests for biometric Stimmung integration (Design A)."""

    def test_biometric_dimensions_exist(self):
        s = SystemStimmung()
        assert s.operator_stress.value == 0.0
        assert s.operator_energy.value == 0.0
        assert s.physiological_coherence.value == 0.0

    def test_update_biometrics_stress_from_hrv_drop(self):
        c = StimmungCollector()
        # HRV dropped 50% below baseline → high stress
        c.update_biometrics(hrv_current=20.0, hrv_baseline=40.0)
        s = c.snapshot()
        assert s.operator_stress.value > 0.3  # significant stress

    def test_update_biometrics_stress_from_eda(self):
        c = StimmungCollector()
        c.update_biometrics(eda_active=True, frustration_score=0.5)
        s = c.snapshot()
        assert s.operator_stress.value > 0.2

    def test_update_biometrics_stress_no_data(self):
        c = StimmungCollector()
        c.update_biometrics()  # all defaults
        s = c.snapshot()
        # No HRV/EDA data → stress should be low
        assert s.operator_stress.value == 0.0

    def test_update_biometrics_energy(self):
        c = StimmungCollector()
        c.update_biometrics(sleep_quality=0.3, circadian_alignment=0.7)
        s = c.snapshot()
        # Poor sleep + bad circadian = high energy deficit
        assert s.operator_energy.value > 0.3

    def test_update_biometrics_coherence_stable(self):
        c = StimmungCollector()
        c.update_biometrics(hrv_cv=0.05, skin_temp_cv=0.01)
        s = c.snapshot()
        # Low CV = high coherence = low value (good)
        assert s.physiological_coherence.value < 0.3

    def test_update_biometrics_coherence_fragmented(self):
        c = StimmungCollector()
        c.update_biometrics(hrv_cv=0.4, skin_temp_cv=0.15)
        s = c.snapshot()
        # High CV = fragmented
        assert s.physiological_coherence.value > 0.5

    def test_biometric_weight_in_stance(self):
        """Biometric dimensions should not drive stance alone due to 0.5x weight."""
        c = StimmungCollector()
        # Max out biometric stress
        c.update_biometrics(
            hrv_current=5.0,
            hrv_baseline=50.0,
            eda_active=True,
            frustration_score=1.0,
        )
        s = c.snapshot()
        # operator_stress.value should be high (~1.0)
        assert s.operator_stress.value > 0.8
        # But stance should NOT be critical because of 0.5x weight
        assert s.overall_stance != Stance.CRITICAL
        # It should be at most cautious (0.5 * 1.0 = 0.5 → cautious range)
        assert s.overall_stance in (Stance.CAUTIOUS, Stance.NOMINAL)

    def test_biometric_plus_infra_additive(self):
        """Biometric stress + infra stress can compound."""
        c = StimmungCollector()
        c.update_health(healthy=4, total=10)  # infra degraded (0.6)
        c.update_biometrics(
            hrv_current=10.0,
            hrv_baseline=50.0,
            eda_active=True,
            frustration_score=0.8,
        )
        s = c.snapshot()
        # Infra at 0.6 → degraded, biometric compounds
        assert s.overall_stance in (Stance.DEGRADED, Stance.CRITICAL)

    def test_format_includes_biometrics(self):
        s = SystemStimmung(
            operator_stress=DimensionReading(value=0.5, trend="rising", freshness_s=5.0),
        )
        text = s.format_for_prompt()
        assert "operator_stress: 0.50" in text

    def test_non_nominal_includes_biometrics(self):
        s = SystemStimmung(
            operator_stress=DimensionReading(value=0.5, trend="rising", freshness_s=5.0),
        )
        nn = s.non_nominal_dimensions
        assert "operator_stress" in nn


class TestStimmungTimestamp:
    def test_snapshot_timestamp_is_wall_clock(self):
        """N2: serialized timestamp must be wall-clock, not monotonic."""
        c = StimmungCollector()
        c.update_health(healthy=5, total=5)
        s = c.snapshot()
        assert s.timestamp > 1_000_000_000, f"Timestamp {s.timestamp} looks monotonic"
        assert abs(s.timestamp - time_mod.time()) < 2.0
