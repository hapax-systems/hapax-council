"""Tests for DimensionReading posterior promotion — Phase C.

Posterior-aware stance aggregator tests:
1. Legacy path is bit-identical when HAPAX_STIMMUNG_POSTERIOR_STANCE unset.
2. High-mean/high-sigma does NOT escalate (Bayesian humility).
3. High-mean/low-sigma DOES escalate (confident reading).
4. exceeds_with_confidence() helper.
5. Sigma=0 posterior path is bit-identical to legacy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from shared.stimmung import DimensionReading, Stance, StimmungCollector

if TYPE_CHECKING:
    import pytest


class TestExceedsWithConfidence:
    """DimensionReading.exceeds_with_confidence() tests."""

    def test_sigma_zero_falls_back_to_comparison(self) -> None:
        """With sigma=0, exceeds_with_confidence is just value >= threshold."""
        r = DimensionReading(value=0.5, sigma=0.0)
        assert r.exceeds_with_confidence(0.3) is True
        assert r.exceeds_with_confidence(0.5) is True
        assert r.exceeds_with_confidence(0.6) is False

    def test_high_confidence_with_low_sigma(self) -> None:
        """Value well above threshold with low sigma → high probability."""
        r = DimensionReading(value=0.7, sigma=0.05, n=5)
        # P(0.7 > 0.3 | sigma=0.05) is essentially 1.0
        assert r.exceeds_with_confidence(0.3, confidence=0.95) is True

    def test_low_confidence_with_high_sigma(self) -> None:
        """Value near threshold with high sigma → lower probability."""
        r = DimensionReading(value=0.35, sigma=0.3, n=3)
        # P(0.35 > 0.3 | sigma=0.3) ≈ 0.57 — below 0.7 confidence
        assert r.exceeds_with_confidence(0.3, confidence=0.7) is False

    def test_value_below_threshold_never_exceeds(self) -> None:
        """Value well below threshold should not exceed even with moderate sigma."""
        r = DimensionReading(value=0.1, sigma=0.05, n=5)
        assert r.exceeds_with_confidence(0.6, confidence=0.7) is False

    def test_value_well_above_threshold_always_exceeds(self) -> None:
        """Value well above threshold exceeds even with high confidence requirement."""
        r = DimensionReading(value=0.9, sigma=0.05, n=5)
        assert r.exceeds_with_confidence(0.3, confidence=0.99) is True


class TestPosteriorStance:
    """_compute_stance_posterior tests."""

    def test_sigma_zero_identical_to_legacy(self) -> None:
        """With all sigma=0, posterior stance should match legacy exactly."""
        dims_low = {
            "health": DimensionReading(value=0.2, sigma=0.0, freshness_s=5.0),
            "resource_pressure": DimensionReading(value=0.1, sigma=0.0, freshness_s=5.0),
        }
        legacy = StimmungCollector._compute_stance(dims_low)
        posterior = StimmungCollector._compute_stance_posterior(dims_low)
        assert legacy == posterior

    def test_sigma_zero_high_value_identical(self) -> None:
        """High-value sigma=0 should produce same stance in both paths."""
        dims_high = {
            "health": DimensionReading(value=0.9, sigma=0.0, freshness_s=5.0),
        }
        legacy = StimmungCollector._compute_stance(dims_high)
        posterior = StimmungCollector._compute_stance_posterior(dims_high)
        assert legacy == posterior

    def test_high_mean_high_sigma_no_escalation(self) -> None:
        """Bayesian humility: high mean + high sigma should NOT escalate to CRITICAL.

        A single noisy spike to 0.9 with sigma=0.3 should not trigger CRITICAL
        because the probability of truly exceeding 0.85 is not confident enough.
        """
        dims = {
            "health": DimensionReading(value=0.86, sigma=0.3, n=2, freshness_s=5.0),
        }
        posterior = StimmungCollector._compute_stance_posterior(dims)
        # With sigma=0.3, P(0.86 > 0.85 | sigma=0.3) ≈ 0.51 — below CRITICAL conf=0.95
        assert posterior != Stance.CRITICAL

    def test_high_mean_low_sigma_does_escalate(self) -> None:
        """Confident high reading should escalate normally."""
        dims = {
            "health": DimensionReading(value=0.9, sigma=0.01, n=5, freshness_s=5.0),
        }
        posterior = StimmungCollector._compute_stance_posterior(dims)
        # With sigma=0.01, P(0.9 > 0.85 | sigma=0.01) ≈ 1.0 → CRITICAL
        assert posterior == Stance.CRITICAL

    def test_moderate_value_high_sigma_stays_nominal(self) -> None:
        """A moderate reading with high uncertainty should stay NOMINAL."""
        dims = {
            "health": DimensionReading(value=0.35, sigma=0.2, n=3, freshness_s=5.0),
        }
        posterior = StimmungCollector._compute_stance_posterior(dims)
        # P(0.35 > 0.30 | sigma=0.2) ≈ 0.60 — below CAUTIOUS conf=0.7
        assert posterior == Stance.NOMINAL

    def test_moderate_value_low_sigma_escalates_to_cautious(self) -> None:
        """A moderate reading with low uncertainty should escalate."""
        dims = {
            "health": DimensionReading(value=0.35, sigma=0.01, n=5, freshness_s=5.0),
        }
        posterior = StimmungCollector._compute_stance_posterior(dims)
        assert posterior == Stance.CAUTIOUS

    def test_seeking_still_fires_with_posterior(self) -> None:
        """SEEKING should still fire from exploration_deficit in posterior mode."""
        dims = {
            "health": DimensionReading(value=0.1, sigma=0.0, freshness_s=5.0),
            "exploration_deficit": DimensionReading(value=0.5, sigma=0.0, freshness_s=5.0),
        }
        posterior = StimmungCollector._compute_stance_posterior(dims)
        assert posterior == Stance.SEEKING


class TestFlagGating:
    """Verify the HAPAX_STIMMUNG_POSTERIOR_STANCE env var gating."""

    def test_flag_unset_uses_legacy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without the flag, legacy stance is used."""
        monkeypatch.delenv("HAPAX_STIMMUNG_POSTERIOR_STANCE", raising=False)
        c = StimmungCollector(enable_exploration=False)
        # Record a noisy spike
        c._record("health", 0.86)
        c._record("health", 0.86)
        snap = c.snapshot()
        # Legacy: 0.86 >= 0.85 → CRITICAL
        assert snap.overall_stance == Stance.CRITICAL

    def test_flag_set_uses_posterior(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With the flag set, posterior stance is used."""
        monkeypatch.setenv("HAPAX_STIMMUNG_POSTERIOR_STANCE", "1")
        c = StimmungCollector(enable_exploration=False)
        # Record a noisy spike with high sigma
        c._record("health", 0.4)
        c._record("health", 0.86)
        snap = c.snapshot()
        # Posterior with sigma > 0: P(0.86 > 0.85) at this sigma level
        # won't reach CRITICAL confidence of 0.95
        assert snap.overall_stance != Stance.CRITICAL

    def test_flag_zero_uses_legacy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Flag=0 should use legacy path."""
        monkeypatch.setenv("HAPAX_STIMMUNG_POSTERIOR_STANCE", "0")
        c = StimmungCollector(enable_exploration=False)
        c._record("health", 0.86)
        c._record("health", 0.86)
        snap = c.snapshot()
        assert snap.overall_stance == Stance.CRITICAL


class TestPosteriorBiometricCognitive:
    """Verify posterior stance handles biometric/cognitive weights correctly."""

    def test_biometric_weight_applied_to_sigma(self) -> None:
        """Biometric sigma should be scaled by 0.5 weight."""
        dims = {
            "operator_stress": DimensionReading(value=0.8, sigma=0.1, n=5, freshness_s=5.0),
        }
        posterior = StimmungCollector._compute_stance_posterior(dims)
        # effective_value = 0.8 * 0.5 = 0.4, effective_sigma = 0.1 * 0.5 = 0.05
        # Biometric thresholds: (0.15, 0.40, 1.01)
        # P(0.4 >= 0.4 | sigma=0.05) = 0.5 — below DEGRADED conf=0.85
        # P(0.4 >= 0.15 | sigma=0.05) ≈ 1.0 → CAUTIOUS
        assert posterior == Stance.CAUTIOUS

    def test_cognitive_weight_applied(self) -> None:
        """Cognitive sigma should be scaled by 0.3 weight."""
        dims = {
            "grounding_quality": DimensionReading(value=0.6, sigma=0.05, n=5, freshness_s=5.0),
        }
        posterior = StimmungCollector._compute_stance_posterior(dims)
        # effective_value = 0.6 * 0.3 = 0.18, effective_sigma = 0.05 * 0.3 = 0.015
        # Cognitive thresholds: (0.15, 1.01, 1.01)
        # P(0.18 >= 0.15 | sigma=0.015) ≈ 0.98 → CAUTIOUS
        assert posterior == Stance.CAUTIOUS
