"""Regression tests for the audio-capture snapshot-before-decay invariant (CVS #148).

Prior bug: ``CompositorAudioCapture.get_signals()`` applied decay *before*
snapshotting the signal dict, so an onset that fired at wall-clock T and
landed in ``self._onset_kick = 1.0`` was returned to the render tick at
``1.0 * decay_factor`` (approx 0.75), losing a full frame of transient
amplitude. The fix (``audio_capture.py`` docstring, 2026-04-18 research
drop) re-orders the operations so the caller sees the peak of the
most-recent DSP chunk.

These tests pin:

1. **Onset-fresh invariant** - an onset set to 1.0 at T=0 is returned at 1.0
   from the first ``get_signals()`` call at T=0, not at the decayed value.
2. **Decay monotonicity** - successive ``get_signals()`` calls without new
   onsets produce a monotonically decreasing sequence.
3. **No spurious re-triggers** - tight polling does not re-trigger an onset
   from a stale flag.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agents.studio_compositor.audio_capture import CompositorAudioCapture


@pytest.fixture
def capture() -> CompositorAudioCapture:
    """A capture instance that never actually starts pw-cat.

    We manipulate internal DSP state directly and verify the
    ``get_signals()`` surface - no subprocess, no thread. This
    isolates the snapshot-before-decay invariant from the capture loop.
    """
    c = CompositorAudioCapture(target="test_mixer")
    # Do NOT call .start() - we are unit-testing get_signals() only.
    return c


class TestSnapshotBeforeDecay:
    """CVS #148 core invariant: peak amplitude reaches the caller."""

    def test_onset_kick_at_peak_on_first_get_signals(self, capture: CompositorAudioCapture) -> None:
        """After an onset sets _onset_kick = 1.0, the very next get_signals()
        must return 1.0 (not the decayed value)."""
        with capture._lock:
            capture._onset_kick = 1.0
        signals = capture.get_signals()
        assert signals["onset_kick"] == pytest.approx(1.0), (
            "get_signals must snapshot transient BEFORE decay; saw "
            f"{signals['onset_kick']} (expected 1.0, sync gap regression)"
        )

    def test_beat_pulse_peak_reaches_caller(self, capture: CompositorAudioCapture) -> None:
        with capture._lock:
            capture._beat_pulse = 1.0
        signals = capture.get_signals()
        assert signals["beat_pulse"] == pytest.approx(1.0)
        assert signals["mixer_beat"] == pytest.approx(1.0)

    def test_all_transient_pulses_peak_reach_caller(self, capture: CompositorAudioCapture) -> None:
        with capture._lock:
            capture._beat_pulse = 1.0
            capture._onset_kick = 1.0
            capture._onset_snare = 1.0
            capture._onset_hat = 1.0
            capture._sidechain_kick = 1.0
        signals = capture.get_signals()
        assert signals["beat_pulse"] == pytest.approx(1.0)
        assert signals["onset_kick"] == pytest.approx(1.0)
        assert signals["onset_snare"] == pytest.approx(1.0)
        assert signals["onset_hat"] == pytest.approx(1.0)
        assert signals["sidechain_kick"] == pytest.approx(1.0)


class TestDecayMonotonicity:
    """Without a new onset, successive reads must decay monotonically."""

    def test_onset_kick_decays_monotonic(self, capture: CompositorAudioCapture) -> None:
        with capture._lock:
            capture._onset_kick = 1.0
        prev = capture.get_signals()["onset_kick"]
        assert prev == pytest.approx(1.0)
        for _ in range(5):
            cur = capture.get_signals()["onset_kick"]
            assert cur <= prev + 1e-9, "onset_kick must decay monotonically without a new DSP onset"
            prev = cur

    def test_decay_factor_matches_pin(self, capture: CompositorAudioCapture) -> None:
        """Pin the decay factors to detect unintended config drift.

        Values locked in ``audio_capture.py::get_signals``:
        - beat_pulse * 0.7
        - onset_kick * 0.75
        - onset_snare * 0.65
        - onset_hat * 0.55
        - sidechain_kick * 0.92 (non-vinyl)
        """
        with capture._lock:
            capture._beat_pulse = 1.0
            capture._onset_kick = 1.0
            capture._onset_snare = 1.0
            capture._onset_hat = 1.0
            capture._sidechain_kick = 1.0

        # First call returns peak (1.0). Subsequent state reflects decay.
        capture.get_signals()

        # After the first call, internal state has been multiplied by
        # decay factors. We verify the second snapshot exposes the
        # post-decay values.
        signals = capture.get_signals()
        assert signals["beat_pulse"] == pytest.approx(0.7, abs=1e-6)
        assert signals["onset_kick"] == pytest.approx(0.75, abs=1e-6)
        assert signals["onset_snare"] == pytest.approx(0.65, abs=1e-6)
        assert signals["onset_hat"] == pytest.approx(0.55, abs=1e-6)
        assert signals["sidechain_kick"] == pytest.approx(0.92, abs=1e-6)


class TestTightLoopNoRetrigger:
    """Tight polling without new DSP input must not re-trigger an onset."""

    def test_tight_loop_no_spurious_retrigger(self, capture: CompositorAudioCapture) -> None:
        """Call get_signals() in a tight loop; values must not rebound
        from a residual amplitude. A naive decay-then-snapshot bug
        pattern might leave the internal flag at 1.0 between ticks."""
        with capture._lock:
            capture._onset_kick = 1.0
        values = [capture.get_signals()["onset_kick"] for _ in range(10)]
        # First value is peak; rest are strictly decaying
        assert values[0] == pytest.approx(1.0)
        for prev, cur in zip(values[:-1], values[1:], strict=True):
            assert cur < prev or (prev == 0.0 and cur == 0.0), (
                f"onset_kick rebounded mid-decay ({prev} -> {cur})"
            )

    def test_get_signals_does_not_trigger_new_onset(self, capture: CompositorAudioCapture) -> None:
        """Starting from zero, repeated get_signals() must stay at zero.

        This protects against a class of bugs where a 'reset on snapshot'
        path accidentally writes 1.0 into a transient field.
        """
        for _ in range(20):
            signals = capture.get_signals()
            assert signals["onset_kick"] == 0.0
            assert signals["beat_pulse"] == 0.0
            assert signals["onset_snare"] == 0.0
            assert signals["onset_hat"] == 0.0


class TestVinylModeDecay:
    """Vinyl mode changes sidechain decay; pin both branches."""

    def test_vinyl_mode_slower_sidechain(self, capture: CompositorAudioCapture) -> None:
        with patch.object(CompositorAudioCapture, "VINYL_MODE", True):
            with capture._lock:
                capture._sidechain_kick = 1.0
            capture.get_signals()
            signals = capture.get_signals()
            assert signals["sidechain_kick"] == pytest.approx(0.95, abs=1e-6)

    def test_non_vinyl_default_sidechain(self, capture: CompositorAudioCapture) -> None:
        # VINYL_MODE defaults to False in the class
        with capture._lock:
            capture._sidechain_kick = 1.0
        capture.get_signals()
        signals = capture.get_signals()
        assert signals["sidechain_kick"] == pytest.approx(0.92, abs=1e-6)
