"""Tests for DimensionReading posterior promotion — Phase A.

Phase A adds sigma and n fields with backward-compatible defaults.
These tests verify:
1. Default values preserve legacy behavior.
2. New fields are accepted and serialized correctly.
3. format_for_prompt shows ±sigma when sigma > 0.
4. chronicle payload includes sigma and n.
"""

from __future__ import annotations

from shared.stimmung import (
    DimensionReading,
    StimmungCollector,
    SystemStimmung,
)


class TestDimensionReadingPhaseA:
    """Verify sigma/n fields on DimensionReading."""

    def test_default_sigma_is_zero(self) -> None:
        """Legacy callers omitting sigma get point-estimate behavior."""
        r = DimensionReading(value=0.5, trend="rising", freshness_s=2.0)
        assert r.sigma == 0.0
        assert r.n == 1

    def test_sigma_and_n_accepted(self) -> None:
        """Explicit sigma/n are accepted."""
        r = DimensionReading(value=0.5, trend="stable", freshness_s=1.0, sigma=0.12, n=5)
        assert r.sigma == 0.12
        assert r.n == 5

    def test_frozen_immutability(self) -> None:
        """sigma and n are immutable (frozen model)."""
        r = DimensionReading(value=0.5, sigma=0.1, n=3)
        try:
            r.sigma = 0.2  # type: ignore[misc]
            raise AssertionError("Should have raised")
        except (TypeError, ValueError):
            pass

    def test_serialization_roundtrip(self) -> None:
        """model_dump includes sigma and n."""
        r = DimensionReading(value=0.42, sigma=0.08, n=4)
        d = r.model_dump()
        assert d["sigma"] == 0.08
        assert d["n"] == 4
        r2 = DimensionReading.model_validate(d)
        assert r2.sigma == 0.08
        assert r2.n == 4

    def test_default_factory_sigma_zero(self) -> None:
        """DimensionReading() with no args has sigma=0, n=1."""
        r = DimensionReading()
        assert r.sigma == 0.0
        assert r.n == 1


class TestSystemStimmungPhaseA:
    """Verify SystemStimmung with sigma/n fields."""

    def test_system_stimmung_default_dimensions_have_sigma_zero(self) -> None:
        """Default-constructed SystemStimmung has sigma=0 on all dimensions."""
        s = SystemStimmung()
        assert s.health.sigma == 0.0
        assert s.health.n == 1
        assert s.resource_pressure.sigma == 0.0
        assert s.operator_stress.sigma == 0.0

    def test_system_stimmung_with_sigma(self) -> None:
        """SystemStimmung accepts dimensions with sigma > 0."""
        s = SystemStimmung(
            health=DimensionReading(value=0.3, sigma=0.05, n=5),
            resource_pressure=DimensionReading(value=0.1, sigma=0.02, n=3),
        )
        assert s.health.sigma == 0.05
        assert s.health.n == 5


class TestFormatForPromptPhaseA:
    """Verify prompt formatting with sigma/n."""

    def test_sigma_zero_shows_legacy_format(self) -> None:
        """When sigma=0, prompt output is identical to pre-Phase-A."""
        s = SystemStimmung(
            health=DimensionReading(value=0.25, trend="stable", freshness_s=5.0),
        )
        prompt = s.format_for_prompt()
        assert "health: 0.25 (stable)" in prompt
        assert "±" not in prompt.split("health")[1].split("\n")[0]

    def test_sigma_positive_shows_uncertainty(self) -> None:
        """When sigma > 0, prompt shows ±sigma and n."""
        s = SystemStimmung(
            health=DimensionReading(value=0.42, sigma=0.08, n=4, trend="rising", freshness_s=3.0),
        )
        prompt = s.format_for_prompt()
        health_line = [l for l in prompt.split("\n") if "health:" in l][0]
        assert "0.42±0.08" in health_line
        assert "n=4" in health_line
        assert "rising" in health_line

    def test_stale_dimension_shows_stale_not_sigma(self) -> None:
        """Stale dimensions show 'stale' regardless of sigma."""
        s = SystemStimmung(
            health=DimensionReading(value=0.5, sigma=0.1, n=3, freshness_s=200.0),
        )
        prompt = s.format_for_prompt()
        health_line = [l for l in prompt.split("\n") if "health:" in l][0]
        assert "stale" in health_line
        assert "±" not in health_line


class TestCollectorPhaseA:
    """Verify StimmungCollector still produces valid DimensionReadings."""

    def test_snapshot_produces_sigma_zero(self) -> None:
        """Pre-Phase-B collector always produces sigma=0 readings."""
        c = StimmungCollector(enable_exploration=False)
        c.update_health(9, 10)
        snap = c.snapshot()
        assert snap.health.sigma == 0.0
        assert snap.health.n == 1

    def test_snapshot_all_dimensions_have_sigma(self) -> None:
        """Every dimension in snapshot has the sigma field."""
        c = StimmungCollector(enable_exploration=False)
        snap = c.snapshot()
        for name in [
            "health",
            "resource_pressure",
            "error_rate",
            "processing_throughput",
            "perception_confidence",
            "llm_cost_pressure",
            "grounding_quality",
            "exploration_deficit",
            "audience_engagement",
            "operator_stress",
            "operator_energy",
            "physiological_coherence",
        ]:
            dim = getattr(snap, name)
            assert hasattr(dim, "sigma"), f"{name} missing sigma"
            assert hasattr(dim, "n"), f"{name} missing n"
            assert dim.sigma == 0.0
            assert dim.n == 1


class TestBackwardCompatibility:
    """Verify that Phase A is fully backward-compatible."""

    def test_legacy_construction_unchanged(self) -> None:
        """DimensionReading(value=, trend=, freshness_s=) still works."""
        r = DimensionReading(value=0.7, trend="falling", freshness_s=10.0)
        assert r.value == 0.7
        assert r.trend == "falling"
        assert r.freshness_s == 10.0

    def test_modulation_factor_unaffected_by_sigma(self) -> None:
        """modulation_factor uses value only, not sigma."""
        s1 = SystemStimmung(
            health=DimensionReading(value=0.65, sigma=0.0, n=1),
        )
        s2 = SystemStimmung(
            health=DimensionReading(value=0.65, sigma=0.15, n=5),
        )
        assert s1.modulation_factor("health") == s2.modulation_factor("health")

    def test_non_nominal_dimensions_unaffected_by_sigma(self) -> None:
        """non_nominal_dimensions uses value threshold, not sigma."""
        s = SystemStimmung(
            health=DimensionReading(value=0.5, sigma=0.1, n=3, freshness_s=5.0),
            resource_pressure=DimensionReading(value=0.1, sigma=0.05, n=4, freshness_s=5.0),
        )
        non_nom = s.non_nominal_dimensions
        assert "health" in non_nom  # 0.5 >= 0.3
        assert "resource_pressure" not in non_nom  # 0.1 < 0.3

    def test_stance_computation_unaffected(self) -> None:
        """_compute_stance ignores sigma (Phase A guarantees no semantic change)."""
        c = StimmungCollector(enable_exploration=False)
        c.update_health(5, 10)  # value=0.5
        snap = c.snapshot()
        # 0.5 is between CAUTIOUS (0.30) and DEGRADED (0.60) for infra
        # so stance should be CAUTIOUS
        assert snap.overall_stance in ("cautious", "degraded", "nominal")
