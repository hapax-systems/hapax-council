"""Tests for shared.audio_duck_compose (cc-task audio-audit-C Phase 0).

Pin the composition rule (sum-of-dB), the clamp behaviour, the amplitude
conversion, and the single-source-matches-old-behaviour acceptance criterion.
"""

from __future__ import annotations

import math

import pytest

from shared.audio_duck_compose import (
    MAX_TOTAL_ATTEN_DB,
    amplitude_from_db,
    compose_attenuations,
)


class TestComposeAttenuationsBaseline:
    def test_default_max_is_documented_value(self) -> None:
        assert MAX_TOTAL_ATTEN_DB == -24.0

    def test_no_sources_returns_zero(self) -> None:
        assert compose_attenuations([]) == 0.0

    def test_single_zero_source_returns_zero(self) -> None:
        assert compose_attenuations([0.0]) == 0.0

    def test_single_source_matches_legacy_behavior(self) -> None:
        """Audit acceptance: single-source must match the old max() behavior.

        With only one source, max(srcs) == sum(srcs) for the negative-only
        domain we restrict to.
        """
        assert compose_attenuations([-6.0]) == -6.0
        assert compose_attenuations([-12.0]) == -12.0


class TestSumOfDb:
    def test_two_sources_compose_additively(self) -> None:
        # Phase 1 requirement: 6 dB + 6 dB = 12 dB total, NOT 6 dB.
        assert compose_attenuations([-6.0, -6.0]) == -12.0

    def test_three_sources_compose_additively(self) -> None:
        assert compose_attenuations([-3.0, -4.0, -5.0]) == -12.0

    def test_zero_sources_in_mix_dont_contribute(self) -> None:
        assert compose_attenuations([-6.0, 0.0, -3.0]) == -9.0

    def test_positive_sources_are_clamped_to_zero(self) -> None:
        """Boost requests don't make sense for a ducker; clamp to 0."""
        assert compose_attenuations([+3.0, -6.0]) == -6.0
        assert compose_attenuations([+10.0]) == 0.0


class TestClampBehavior:
    def test_three_sources_still_clamps_to_max(self) -> None:
        # Audit acceptance: three-source composition still clamps.
        # 12 + 12 + 12 = 36 dB total; clamped to -24 dB default.
        result = compose_attenuations([-12.0, -12.0, -12.0])
        assert result == MAX_TOTAL_ATTEN_DB

    def test_clamps_at_default_max_db(self) -> None:
        # 30 dB request, clamped to -24 dB.
        assert compose_attenuations([-30.0]) == MAX_TOTAL_ATTEN_DB

    def test_custom_max_db_honored(self) -> None:
        assert compose_attenuations([-30.0], max_db=-12.0) == -12.0

    def test_just_below_clamp_passes_through(self) -> None:
        assert compose_attenuations([-23.9]) == pytest.approx(-23.9)

    def test_at_clamp_boundary_returns_clamp(self) -> None:
        assert compose_attenuations([-24.0]) == MAX_TOTAL_ATTEN_DB

    def test_positive_max_db_rejected(self) -> None:
        """A positive max_db would mean "amplify on duck" — disallowed."""
        with pytest.raises(ValueError, match="max_db must be"):
            compose_attenuations([-6.0], max_db=3.0)


class TestAmplitudeFromDb:
    def test_zero_db_is_unity(self) -> None:
        assert amplitude_from_db(0.0) == 1.0

    def test_negative_20_db_is_one_tenth(self) -> None:
        assert amplitude_from_db(-20.0) == pytest.approx(0.1)

    def test_negative_6_db_is_half_amplitude_ish(self) -> None:
        # -6 dB ≈ 0.501 (half power = -3 dB; half amplitude = -6 dB).
        assert amplitude_from_db(-6.0) == pytest.approx(0.5012, rel=1e-3)

    def test_negative_inf_is_zero(self) -> None:
        assert amplitude_from_db(-math.inf) == 0.0

    def test_positive_db_treated_as_unity(self) -> None:
        """Positive input is nonsensical for a ducker amplitude write;
        clamp to unity rather than emit > 1.0 amplitudes."""
        assert amplitude_from_db(+6.0) == 1.0
        assert amplitude_from_db(+0.0001) == 1.0


class TestComposeIntegration:
    """End-to-end: dB composition then amplitude conversion."""

    def test_two_sources_compose_then_amplitude(self) -> None:
        composed_db = compose_attenuations([-6.0, -6.0])
        amp = amplitude_from_db(composed_db)
        # -12 dB ≈ 0.251 amplitude.
        assert composed_db == -12.0
        assert amp == pytest.approx(0.2512, rel=1e-3)

    def test_no_sources_is_unity_amplitude(self) -> None:
        assert amplitude_from_db(compose_attenuations([])) == 1.0

    def test_runaway_request_clamps_amplitude(self) -> None:
        """5 sources @ -10 dB each = -50 dB requested but clamped to -24 dB."""
        composed = compose_attenuations([-10.0] * 5)
        assert composed == MAX_TOTAL_ATTEN_DB
        # -24 dB ≈ 0.063 amplitude.
        assert amplitude_from_db(composed) == pytest.approx(0.0631, rel=1e-3)
