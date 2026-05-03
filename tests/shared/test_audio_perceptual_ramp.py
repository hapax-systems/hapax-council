"""Tests for shared.audio_perceptual_ramp (cc-task audio-audit-C Phase 0).

Pin the dB-domain interpolator + amplitude conversion + the 3 canonical
envelope shapes called out in the audit acceptance criteria.
"""

from __future__ import annotations

import math

import pytest

from shared.audio_perceptual_ramp import (
    DUCK_FLOOR_DB,
    amplitude_from_db,
    lerp_db,
    perceptual_ramp_amplitude,
)


class TestLerpDbBasics:
    def test_t_zero_returns_start(self) -> None:
        assert lerp_db(-12.0, 0.0, 0.0) == -12.0
        assert lerp_db(0.0, -12.0, 0.0) == 0.0

    def test_t_one_returns_end(self) -> None:
        assert lerp_db(-12.0, 0.0, 1.0) == 0.0
        assert lerp_db(0.0, -12.0, 1.0) == -12.0

    def test_t_half_returns_midpoint(self) -> None:
        assert lerp_db(-12.0, 0.0, 0.5) == -6.0
        assert lerp_db(0.0, -12.0, 0.5) == -6.0

    def test_t_negative_clamped_to_zero(self) -> None:
        # Pathological: zero-length window can produce t = -inf or NaN.
        assert lerp_db(-12.0, 0.0, -0.5) == -12.0

    def test_t_above_one_clamped_to_one(self) -> None:
        assert lerp_db(-12.0, 0.0, 1.5) == 0.0

    def test_zero_length_envelope_handles_both_endpoints(self) -> None:
        """attack_ms = 0 means we should be at end_db immediately;
        the caller passes t = inf which we clamp to 1.0."""
        assert lerp_db(-12.0, 0.0, math.inf) == 0.0


class TestLerpDbInfHandling:
    def test_negative_inf_start_floored(self) -> None:
        """``start_db == -inf`` (fully ducked) is floored to DUCK_FLOOR_DB
        so the dB-domain math stays finite."""
        result = lerp_db(-math.inf, 0.0, 0.5)
        # Floored start: lerp(DUCK_FLOOR_DB, 0, 0.5) = DUCK_FLOOR_DB / 2.
        assert result == pytest.approx(DUCK_FLOOR_DB / 2.0)

    def test_negative_inf_end_floored(self) -> None:
        result = lerp_db(0.0, -math.inf, 0.5)
        assert result == pytest.approx(DUCK_FLOOR_DB / 2.0)


class TestAmplitudeFromDb:
    def test_zero_db_is_unity(self) -> None:
        assert amplitude_from_db(0.0) == 1.0

    def test_negative_6_db_is_half_amplitude(self) -> None:
        # -6 dB amplitude = 0.5012, a near-half-amplitude reduction.
        assert amplitude_from_db(-6.0) == pytest.approx(0.5012, rel=1e-3)

    def test_negative_20_db_is_one_tenth(self) -> None:
        assert amplitude_from_db(-20.0) == pytest.approx(0.1)

    def test_floor_reaches_zero(self) -> None:
        assert amplitude_from_db(DUCK_FLOOR_DB) == 0.0
        assert amplitude_from_db(DUCK_FLOOR_DB - 5.0) == 0.0

    def test_negative_inf_is_zero(self) -> None:
        assert amplitude_from_db(-math.inf) == 0.0

    def test_positive_db_is_unity_clamp(self) -> None:
        """Write-time amplitude must always be in [0, 1]."""
        assert amplitude_from_db(+6.0) == 1.0
        assert amplitude_from_db(+0.0001) == 1.0


class TestThreeCanonicalEnvelopes:
    """Audit acceptance: cover the 3 envelope shapes called out in the
    cc-task acceptance criteria.

    1. -inf -> 0 dB attack (fully ducked rising to unity)
    2. 0 -> -12 dB attack (unity descending to -12 dB)
    3. -12 -> 0 dB release (-12 dB rising to unity)
    """

    def test_neg_inf_to_zero_attack(self) -> None:
        # t=0 → fully ducked → amplitude 0.
        assert perceptual_ramp_amplitude(-math.inf, 0.0, 0.0) == 0.0
        # t=1 → unity → amplitude 1.0.
        assert perceptual_ramp_amplitude(-math.inf, 0.0, 1.0) == 1.0
        # Midway: lerp gives DUCK_FLOOR_DB/2 = -30 dB → amplitude ~0.0316.
        midway = perceptual_ramp_amplitude(-math.inf, 0.0, 0.5)
        assert midway == pytest.approx(10 ** (DUCK_FLOOR_DB / 40.0), rel=1e-3)

    def test_zero_to_neg_12_db_attack(self) -> None:
        # t=0 → unity.
        assert perceptual_ramp_amplitude(0.0, -12.0, 0.0) == 1.0
        # t=1 → -12 dB → amplitude 10^(-12/20) ≈ 0.2512.
        assert perceptual_ramp_amplitude(0.0, -12.0, 1.0) == pytest.approx(0.2512, rel=1e-3)
        # t=0.5 → -6 dB → amplitude ≈ 0.5012.
        assert perceptual_ramp_amplitude(0.0, -12.0, 0.5) == pytest.approx(0.5012, rel=1e-3)

    def test_neg_12_db_to_zero_release(self) -> None:
        # t=0 → -12 dB → amplitude ≈ 0.2512.
        assert perceptual_ramp_amplitude(-12.0, 0.0, 0.0) == pytest.approx(0.2512, rel=1e-3)
        # t=1 → unity.
        assert perceptual_ramp_amplitude(-12.0, 0.0, 1.0) == 1.0
        # Midway: -6 dB → amplitude ≈ 0.5012.
        assert perceptual_ramp_amplitude(-12.0, 0.0, 0.5) == pytest.approx(0.5012, rel=1e-3)

    def test_release_curve_is_perceptually_uniform(self) -> None:
        """The whole point of dB-domain interpolation: equal t-steps produce
        equal-perceived loudness changes. Pin that the dB delta from t=0 to
        t=0.5 equals the dB delta from t=0.5 to t=1.0 — which would NOT be
        true for linear-amplitude interpolation."""
        amp_0 = perceptual_ramp_amplitude(-12.0, 0.0, 0.0)
        amp_half = perceptual_ramp_amplitude(-12.0, 0.0, 0.5)
        amp_1 = perceptual_ramp_amplitude(-12.0, 0.0, 1.0)

        db_0 = 20 * math.log10(amp_0) if amp_0 > 0 else -math.inf
        db_half = 20 * math.log10(amp_half) if amp_half > 0 else -math.inf
        db_1 = 20 * math.log10(amp_1) if amp_1 > 0 else -math.inf

        # The dB deltas must be equal (perceptual uniformity).
        first_half = db_half - db_0
        second_half = db_1 - db_half
        assert first_half == pytest.approx(second_half, rel=1e-6)


class TestRegressionVsLinearAmplitude:
    """The audit's WSJF rationale: dB-domain feels smooth, linear-amplitude
    feels snapped. Pin the difference quantitatively.

    Linear-amplitude midpoint between 0.2512 (-12 dB) and 1.0 = 0.6256.
    dB-domain midpoint between -12 dB and 0 dB = -6 dB → amplitude 0.5012.

    The dB-domain midpoint is ~20% lower in amplitude than the linear
    midpoint — which is exactly why the linear ramp feels rushed at the
    quiet end.
    """

    def test_db_midpoint_is_quieter_than_linear_midpoint(self) -> None:
        amp_0 = perceptual_ramp_amplitude(-12.0, 0.0, 0.0)
        amp_1 = perceptual_ramp_amplitude(-12.0, 0.0, 1.0)
        amp_db_midpoint = perceptual_ramp_amplitude(-12.0, 0.0, 0.5)
        amp_linear_midpoint = (amp_0 + amp_1) / 2.0

        assert amp_db_midpoint < amp_linear_midpoint
        # Differential should be > 10% — meaningful enough that listeners
        # perceive the change as smoother.
        delta_pct = (amp_linear_midpoint - amp_db_midpoint) / amp_linear_midpoint
        assert delta_pct > 0.10
