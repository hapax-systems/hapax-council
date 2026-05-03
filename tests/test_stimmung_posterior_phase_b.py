"""Tests for DimensionReading posterior promotion — Phase B (Welford variance).

Tests verify:
1. Sigma converges across N=5 samples for stationary input.
2. Sigma=0 when n=1 (single sample).
3. Sigma reflects spread when readings oscillate.
4. Sigma resets correctly when window wraps.
5. Property: 0 ≤ sigma ≤ 0.5 and n ∈ {1..5} for any sequence.
"""

from __future__ import annotations

from shared.stimmung import StimmungCollector


class TestWelfordVariance:
    """Verify Welford online variance tracking in StimmungCollector."""

    def test_single_sample_sigma_zero(self) -> None:
        """A single recording should produce sigma=0."""
        c = StimmungCollector(enable_exploration=False)
        c.update_health(5, 10)  # value=0.5
        snap = c.snapshot()
        assert snap.health.sigma == 0.0
        assert snap.health.n == 1

    def test_identical_samples_sigma_zero(self) -> None:
        """Identical readings produce sigma=0 (no variance)."""
        c = StimmungCollector(enable_exploration=False)
        for _ in range(5):
            c.update_health(5, 10)  # always 0.5
        snap = c.snapshot()
        assert snap.health.sigma == 0.0
        assert snap.health.n == 5

    def test_two_different_samples_positive_sigma(self) -> None:
        """Two different readings produce sigma > 0."""
        c = StimmungCollector(enable_exploration=False)
        c.update_health(3, 10)  # value=0.7
        c.update_health(5, 10)  # value=0.5
        snap = c.snapshot()
        assert snap.health.sigma > 0.0
        assert snap.health.n == 2

    def test_oscillating_readings_high_sigma(self) -> None:
        """Oscillating between 0 and 1 should have high sigma."""
        c = StimmungCollector(enable_exploration=False)
        for i in range(5):
            if i % 2 == 0:
                c.update_health(0, 10)  # value=1.0
            else:
                c.update_health(10, 10)  # value=0.0
        snap = c.snapshot()
        # Oscillating 0/1 → sigma should be significant (~0.5)
        assert snap.health.sigma > 0.3
        assert snap.health.n == 5

    def test_converging_readings_decreasing_sigma(self) -> None:
        """Readings converging to a value should show decreasing sigma over time."""
        c = StimmungCollector(enable_exploration=False)
        # Start with spread-out readings
        values = [0.1, 0.3, 0.5, 0.7, 0.9]  # wide spread
        for v in values:
            c.update_gpu(v * 24000, 24000)  # push raw ratio into 0.8+ range
        snap1 = c.snapshot()
        sigma1 = snap1.resource_pressure.sigma

        # Now push 5 identical readings to replace the window
        for _ in range(5):
            c.update_gpu(0.85 * 24000, 24000)
        snap2 = c.snapshot()
        sigma2 = snap2.resource_pressure.sigma

        assert sigma2 < sigma1 or sigma2 == 0.0

    def test_window_wrap_resets_welford(self) -> None:
        """After 5 samples, the 6th should recompute from the 5-sample window."""
        c = StimmungCollector(enable_exploration=False)
        # Fill window with diverse values
        for healthy in [10, 8, 6, 4, 2]:  # values: 0, 0.2, 0.4, 0.6, 0.8
            c.update_health(healthy, 10)

        snap1 = c.snapshot()
        assert snap1.health.n == 5
        assert snap1.health.sigma > 0

        # Add one more — wraps the deque, recomputes Welford
        c.update_health(1, 10)  # value=0.9
        snap2 = c.snapshot()

        assert snap2.health.n == 5  # window is maxlen=5
        assert snap2.health.sigma > 0  # still has variance

    def test_sigma_bounded(self) -> None:
        """Sigma should be bounded — max theoretical sample std for [0,1] with n=2 is ~0.707."""
        c = StimmungCollector(enable_exploration=False)
        import random

        rng = random.Random(42)
        for _ in range(20):
            healthy = rng.randint(0, 10)
            c.update_health(healthy, 10)
            snap = c.snapshot()
            # Max sample std for values in [0,1] is sqrt(0.5) ≈ 0.7071
            assert 0.0 <= snap.health.sigma <= 0.71, f"sigma={snap.health.sigma} out of bounds"
            assert 1 <= snap.health.n <= 5

    def test_n_bounded_by_window_maxlen(self) -> None:
        """n should never exceed the window maxlen (5)."""
        c = StimmungCollector(enable_exploration=False)
        for _ in range(20):
            c.update_health(5, 10)
        snap = c.snapshot()
        assert snap.health.n <= 5

    def test_all_dimensions_track_variance_independently(self) -> None:
        """Each dimension has its own Welford state."""
        c = StimmungCollector(enable_exploration=False)
        # Record different patterns to different dimensions
        c.update_health(5, 10)  # 1 sample → sigma=0
        c.update_health(3, 10)  # 2 samples → sigma > 0
        c.update_gpu(0.5 * 24000, 24000)  # 1 sample → sigma=0

        snap = c.snapshot()
        assert snap.health.n == 2
        assert snap.health.sigma > 0
        assert snap.resource_pressure.sigma == 0.0  # only 1 sample

    def test_welford_accuracy_against_numpy(self) -> None:
        """Welford sigma should match numpy's std for the same window."""
        import numpy as np

        c = StimmungCollector(enable_exploration=False)
        values = [0.1, 0.4, 0.2, 0.8, 0.5]
        for v in values:
            c._record("health", v)

        snap = c.snapshot()
        expected_sigma = float(np.std(values, ddof=1))  # sample std
        assert abs(snap.health.sigma - expected_sigma) < 1e-4, (
            f"Welford sigma {snap.health.sigma} != numpy std {expected_sigma}"
        )

    def test_welford_after_wrap_matches_window(self) -> None:
        """After wrapping, Welford sigma matches the current 5-element window."""
        import numpy as np

        c = StimmungCollector(enable_exploration=False)
        all_values = [0.1, 0.3, 0.5, 0.7, 0.9, 0.2, 0.4]
        for v in all_values:
            c._record("health", v)

        # Window should contain the last 5: [0.5, 0.7, 0.9, 0.2, 0.4]
        snap = c.snapshot()
        window_values = all_values[-5:]
        expected_sigma = float(np.std(window_values, ddof=1))
        assert abs(snap.health.sigma - expected_sigma) < 1e-4
        assert snap.health.n == 5


class TestPhaseAPhaseBIntegration:
    """Verify Phase A + Phase B work together correctly."""

    def test_format_for_prompt_shows_sigma_after_multiple_readings(self) -> None:
        """After multiple readings, prompt should show ±sigma."""
        c = StimmungCollector(enable_exploration=False)
        c.update_health(8, 10)  # value=0.2
        c.update_health(5, 10)  # value=0.5
        c.update_health(3, 10)  # value=0.7
        snap = c.snapshot()

        prompt = snap.format_for_prompt()
        health_line = [l for l in prompt.split("\n") if "health:" in l][0]
        assert "±" in health_line
        assert "n=" in health_line

    def test_format_for_prompt_hides_sigma_with_single_reading(self) -> None:
        """With a single reading, prompt shows legacy format (no ±)."""
        c = StimmungCollector(enable_exploration=False)
        c.update_health(5, 10)
        snap = c.snapshot()

        prompt = snap.format_for_prompt()
        health_line = [l for l in prompt.split("\n") if "health:" in l][0]
        assert "±" not in health_line
