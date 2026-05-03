"""Tests for shared.audio_ducker_rms_config (cc-task audio-audit-C-rms-window Phase 0)."""

from __future__ import annotations

import pytest

from shared.audio_ducker_rms_config import (
    HAPAX_DUCKER_ONSET_DETECTION_LATENCY_MS,
    RMS_WINDOW_MS_LEGACY,
    RMS_WINDOW_MS_TARGET,
    expected_rms_samples,
)


@pytest.fixture(autouse=True)
def _reset_histogram():
    HAPAX_DUCKER_ONSET_DETECTION_LATENCY_MS.clear()
    yield
    HAPAX_DUCKER_ONSET_DETECTION_LATENCY_MS.clear()


def _observation_count(rms_window_ms: int) -> int:
    samples = HAPAX_DUCKER_ONSET_DETECTION_LATENCY_MS.labels(
        rms_window_ms=str(rms_window_ms)
    ).collect()
    if not samples:
        return 0
    for s in samples[0].samples:
        if s.name.endswith("_count"):
            return int(s.value)
    return 0


class TestPinnedConstants:
    def test_legacy_value_pinned(self) -> None:
        """Pin the value being replaced. A future PR that changes
        __main__.py:112 should also update this constant — the diff
        will surface that fact."""
        assert RMS_WINDOW_MS_LEGACY == 50

    def test_target_value_matches_audit(self) -> None:
        """Audit acceptance: drop from 50 to 20 ms."""
        assert RMS_WINDOW_MS_TARGET == 20

    def test_target_is_strictly_smaller_than_legacy(self) -> None:
        """A future regression that flipped target above legacy would silently
        defeat the audit's "react faster" intent."""
        assert RMS_WINDOW_MS_TARGET < RMS_WINDOW_MS_LEGACY

    def test_target_above_minimum_safe(self) -> None:
        """20 ms is the audit-requested minimum. Going below 10 ms starts
        amplifying transient noise (mouse clicks register as onsets) without
        further latency gain since the ducker tick is itself 50 ms."""
        assert RMS_WINDOW_MS_TARGET >= 10


class TestExpectedRmsSamples:
    def test_legacy_matches_main_formula(self) -> None:
        """At 48 kHz, 50 ms = 2400 samples. This must match the inline
        derivation in __main__.py:113."""
        assert expected_rms_samples(RMS_WINDOW_MS_LEGACY, 48000) == 2400

    def test_target_at_48k_is_960_samples(self) -> None:
        assert expected_rms_samples(RMS_WINDOW_MS_TARGET, 48000) == 960

    def test_default_sample_rate_is_48k(self) -> None:
        """48 kHz is the canonical Studio 24c rate; pin the default."""
        assert expected_rms_samples(20) == expected_rms_samples(20, 48000)

    def test_zero_window_rejected(self) -> None:
        with pytest.raises(ValueError, match="window_ms must be positive"):
            expected_rms_samples(0)

    def test_negative_window_rejected(self) -> None:
        with pytest.raises(ValueError, match="window_ms must be positive"):
            expected_rms_samples(-20)

    def test_zero_sample_rate_rejected(self) -> None:
        with pytest.raises(ValueError, match="sample_rate_hz must be positive"):
            expected_rms_samples(20, 0)


class TestOnsetDetectionLatencyHistogram:
    def test_observation_increments_count(self) -> None:
        HAPAX_DUCKER_ONSET_DETECTION_LATENCY_MS.labels(
            rms_window_ms=str(RMS_WINDOW_MS_TARGET)
        ).observe(15.0)
        assert _observation_count(RMS_WINDOW_MS_TARGET) == 1

    def test_legacy_and_target_are_distinct_time_series(self) -> None:
        """Phase 1 A/B comparison plots both labels as separate Grafana
        lines — must NOT collapse into a single counter."""
        HAPAX_DUCKER_ONSET_DETECTION_LATENCY_MS.labels(
            rms_window_ms=str(RMS_WINDOW_MS_LEGACY)
        ).observe(45.0)
        HAPAX_DUCKER_ONSET_DETECTION_LATENCY_MS.labels(
            rms_window_ms=str(RMS_WINDOW_MS_TARGET)
        ).observe(15.0)
        assert _observation_count(RMS_WINDOW_MS_LEGACY) == 1
        assert _observation_count(RMS_WINDOW_MS_TARGET) == 1

    def test_repeated_observations_accumulate(self) -> None:
        for _ in range(10):
            HAPAX_DUCKER_ONSET_DETECTION_LATENCY_MS.labels(
                rms_window_ms=str(RMS_WINDOW_MS_TARGET)
            ).observe(20.0)
        assert _observation_count(RMS_WINDOW_MS_TARGET) == 10
