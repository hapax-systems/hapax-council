"""Tests for shared/audio_pin_glitch.py — unified-audio Phase 5.

Verifies the Ryzen HDA pin-routing-stale detector. Pure-decision
unit; no pactl required.

Plan: docs/superpowers/plans/2026-04-20-unified-audio-architecture-plan.md
§Phase 5. Memory: reference_ryzen_codec_pin_glitch.
"""

from __future__ import annotations

import math

from shared.audio_pin_glitch import (
    DEFAULT_MIN_SILENCE_S,
    DEFAULT_SILENCE_RMS_DB,
    DIAGNOSTIC_PIN_GLITCH,
    PinGlitchDetector,
    SinkProbe,
    is_silent,
)


class _Clock:
    def __init__(self, t0: float = 1000.0) -> None:
        self.t = t0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


# ── is_silent ─────────────────────────────────────────────────────────


class TestIsSilent:
    def test_below_threshold_silent(self) -> None:
        assert is_silent(-60.0) is True

    def test_above_threshold_not_silent(self) -> None:
        assert is_silent(-30.0) is False

    def test_negative_infinity_silent(self) -> None:
        assert is_silent(float("-inf")) is True

    def test_nan_silent(self) -> None:
        """NaN signals 'no reading' → treat as silent (defensive)."""
        assert is_silent(float("nan")) is True

    def test_custom_threshold(self) -> None:
        assert is_silent(-40.0, threshold=-35.0) is True
        assert is_silent(-30.0, threshold=-35.0) is False


# ── Detector — non-symptomatic states ─────────────────────────────────


class TestNonSymptomaticStates:
    def test_idle_sink_no_diagnostic(self) -> None:
        clock = _Clock()
        det = PinGlitchDetector(now_fn=clock)
        result = det.detect(SinkProbe("IDLE", has_active_input=False, monitor_rms_db=-90.0))
        assert result.diagnostic is None
        assert det.silence_started_at is None

    def test_running_with_no_active_input_no_diagnostic(self) -> None:
        clock = _Clock()
        det = PinGlitchDetector(now_fn=clock)
        result = det.detect(SinkProbe("RUNNING", has_active_input=False, monitor_rms_db=-90.0))
        assert result.diagnostic is None
        assert det.silence_started_at is None

    def test_running_active_input_with_signal_no_diagnostic(self) -> None:
        clock = _Clock()
        det = PinGlitchDetector(now_fn=clock)
        result = det.detect(SinkProbe("RUNNING", has_active_input=True, monitor_rms_db=-12.0))
        assert result.diagnostic is None
        assert det.silence_started_at is None

    def test_suspended_sink_no_diagnostic(self) -> None:
        clock = _Clock()
        det = PinGlitchDetector(now_fn=clock)
        result = det.detect(SinkProbe("SUSPENDED", has_active_input=True, monitor_rms_db=-90.0))
        assert result.diagnostic is None


# ── Detector — symptomatic but below threshold ───────────────────────


class TestSilenceBelowThreshold:
    def test_first_silent_probe_no_diagnostic(self) -> None:
        """First silent observation sets silence_started_at but doesn't
        fire the diagnostic until min_silence_s elapses."""
        clock = _Clock()
        det = PinGlitchDetector(now_fn=clock)
        result = det.detect(SinkProbe("RUNNING", has_active_input=True, monitor_rms_db=-90.0))
        assert result.diagnostic is None
        assert det.silence_started_at == 1000.0
        assert result.elapsed_silent_s == 0.0

    def test_short_silence_under_threshold(self) -> None:
        clock = _Clock()
        det = PinGlitchDetector(now_fn=clock, min_silence_s=5.0)
        det.detect(SinkProbe("RUNNING", has_active_input=True, monitor_rms_db=-90.0))
        clock.advance(2.0)  # 2 s — under 5 s threshold
        result = det.detect(SinkProbe("RUNNING", has_active_input=True, monitor_rms_db=-90.0))
        assert result.diagnostic is None
        assert math.isclose(result.elapsed_silent_s, 2.0, abs_tol=1e-9)


# ── Detector — diagnostic fires ──────────────────────────────────────


class TestDiagnosticFires:
    def test_silence_past_threshold_fires(self) -> None:
        clock = _Clock()
        det = PinGlitchDetector(now_fn=clock, min_silence_s=5.0)
        det.detect(SinkProbe("RUNNING", has_active_input=True, monitor_rms_db=-90.0))
        clock.advance(6.0)
        result = det.detect(SinkProbe("RUNNING", has_active_input=True, monitor_rms_db=-90.0))
        assert result.diagnostic == DIAGNOSTIC_PIN_GLITCH
        assert result.elapsed_silent_s == 6.0

    def test_diagnostic_fires_at_exact_threshold(self) -> None:
        """elapsed >= min_silence_s — boundary inclusive."""
        clock = _Clock()
        det = PinGlitchDetector(now_fn=clock, min_silence_s=5.0)
        det.detect(SinkProbe("RUNNING", has_active_input=True, monitor_rms_db=-90.0))
        clock.advance(5.0)
        result = det.detect(SinkProbe("RUNNING", has_active_input=True, monitor_rms_db=-90.0))
        assert result.diagnostic == DIAGNOSTIC_PIN_GLITCH

    def test_diagnostic_keeps_firing_until_signal_returns(self) -> None:
        """Steady-state silence: diagnostic continues to fire."""
        clock = _Clock()
        det = PinGlitchDetector(now_fn=clock, min_silence_s=5.0)
        det.detect(SinkProbe("RUNNING", has_active_input=True, monitor_rms_db=-90.0))
        for advance in (5.0, 1.0, 1.0):
            clock.advance(advance)
            result = det.detect(SinkProbe("RUNNING", has_active_input=True, monitor_rms_db=-90.0))
        assert result.diagnostic == DIAGNOSTIC_PIN_GLITCH
        assert result.elapsed_silent_s == 7.0


# ── Detector — recovery clears state ─────────────────────────────────


class TestRecovery:
    def test_signal_returns_clears_silence_state(self) -> None:
        clock = _Clock()
        det = PinGlitchDetector(now_fn=clock)
        det.detect(SinkProbe("RUNNING", has_active_input=True, monitor_rms_db=-90.0))
        clock.advance(10.0)
        # Audio returns
        result = det.detect(SinkProbe("RUNNING", has_active_input=True, monitor_rms_db=-12.0))
        assert result.diagnostic is None
        assert det.silence_started_at is None

    def test_input_disappearing_clears_silence_state(self) -> None:
        """No active input → no symptom even if silent."""
        clock = _Clock()
        det = PinGlitchDetector(now_fn=clock)
        det.detect(SinkProbe("RUNNING", has_active_input=True, monitor_rms_db=-90.0))
        clock.advance(10.0)
        result = det.detect(SinkProbe("RUNNING", has_active_input=False, monitor_rms_db=-90.0))
        assert result.diagnostic is None
        assert det.silence_started_at is None

    def test_state_change_to_idle_clears_silence(self) -> None:
        clock = _Clock()
        det = PinGlitchDetector(now_fn=clock)
        det.detect(SinkProbe("RUNNING", has_active_input=True, monitor_rms_db=-90.0))
        clock.advance(10.0)
        result = det.detect(SinkProbe("IDLE", has_active_input=True, monitor_rms_db=-90.0))
        assert result.diagnostic is None
        assert det.silence_started_at is None

    def test_silence_re_starts_after_recovery(self) -> None:
        """After signal returns, a new silence window starts fresh."""
        clock = _Clock()
        det = PinGlitchDetector(now_fn=clock, min_silence_s=5.0)
        det.detect(SinkProbe("RUNNING", has_active_input=True, monitor_rms_db=-90.0))
        clock.advance(10.0)
        det.detect(SinkProbe("RUNNING", has_active_input=True, monitor_rms_db=-12.0))
        clock.advance(2.0)
        det.detect(SinkProbe("RUNNING", has_active_input=True, monitor_rms_db=-90.0))
        clock.advance(2.0)
        result = det.detect(SinkProbe("RUNNING", has_active_input=True, monitor_rms_db=-90.0))
        # 2 s after the new silence start — under threshold
        assert result.diagnostic is None
        assert math.isclose(result.elapsed_silent_s, 2.0, abs_tol=1e-9)


# ── Defaults ──────────────────────────────────────────────────────────


class TestDefaults:
    def test_default_silence_threshold_db(self) -> None:
        """Spec-example threshold."""
        assert DEFAULT_SILENCE_RMS_DB == -50.0

    def test_default_min_silence_s(self) -> None:
        """Plan §line 75: > 5 s elapsed."""
        assert DEFAULT_MIN_SILENCE_S == 5.0

    def test_diagnostic_string_pinned(self) -> None:
        """Operator scripts grep for this exact string — renaming
        breaks the contract."""
        assert DIAGNOSTIC_PIN_GLITCH == "PIN_GLITCH"
