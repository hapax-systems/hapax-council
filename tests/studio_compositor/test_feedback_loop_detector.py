"""Tests for the L-12 per-channel feedback-loop detector."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import numpy as np
import pytest

from agents.studio_compositor import feedback_loop_detector as fld

# ── helpers ────────────────────────────────────────────────────────────────


def _silent_buffer(samples: int = 12000, channels: int = 14) -> np.ndarray:
    return np.zeros((samples, channels), dtype=np.float32)


def _white_noise_buffer(
    rng: np.random.Generator,
    samples: int = 12000,
    channels: int = 14,
    amplitude: float = 0.1,
) -> np.ndarray:
    return (rng.standard_normal((samples, channels)) * amplitude).astype(np.float32)


def _sine_buffer(
    sample_rate_hz: int = 48_000,
    frequency_hz: float = 1000.0,
    samples: int = 12000,
    channels: int = 14,
    amplitude: float = 0.5,
    target_channel: int = 5,
) -> np.ndarray:
    """One channel carries a pure sine; all others are silent."""
    t = np.arange(samples, dtype=np.float32) / sample_rate_hz
    sine = (amplitude * np.sin(2 * np.pi * frequency_hz * t)).astype(np.float32)
    buf = np.zeros((samples, channels), dtype=np.float32)
    buf[:, target_channel] = sine
    return buf


def _build(channels: int = 14, **kwargs) -> fld.FeedbackLoopDetector:
    """Build a detector configured for the test rate/channels.

    ``baseline_tau_s`` defaults to the production 10 s — a shorter tau
    causes the EWMA to track a sustaining signal too quickly, breaking
    the sine-trigger contract within 2 windows. Production lengthening
    to 10 s ensures a sustained sine appears as ``peak >> baseline``
    for the few seconds it needs to fire.
    """
    return fld.FeedbackLoopDetector(
        sample_rate_hz=kwargs.pop("sample_rate_hz", 48_000),
        channels=channels,
        window_ms=kwargs.pop("window_ms", 250),
        fft_size=kwargs.pop("fft_size", 2048),
        baseline_tau_s=kwargs.pop("baseline_tau_s", 10.0),
        sustain_windows=kwargs.pop("sustain_windows", 2),
        cooldown_s=kwargs.pop("cooldown_s", 30.0),
        **kwargs,
    )


# ── shape / contract ──────────────────────────────────────────────────────


class TestShapeContract:
    def test_window_size_samples(self) -> None:
        det = _build()
        assert det.window_size_samples() == 12000

    def test_buffer_must_be_2d(self) -> None:
        det = _build()
        with pytest.raises(ValueError, match="2-D"):
            det.process_buffer(np.zeros(12000, dtype=np.float32))

    def test_channel_count_must_match(self) -> None:
        det = _build(channels=4)
        with pytest.raises(ValueError, match="channel count mismatch"):
            det.process_buffer(np.zeros((12000, 14), dtype=np.float32))

    def test_under_fill_returns_empty(self) -> None:
        det = _build()
        # Less than fft_size samples → cannot do FFT, return [] (no crash).
        events = det.process_buffer(np.zeros((1024, 14), dtype=np.float32))
        assert events == []


# ── baseline EWMA ─────────────────────────────────────────────────────────


class TestBaselineEWMA:
    def test_first_buffer_seeds_baseline_returns_no_event(self) -> None:
        """Cold start: baseline is None → first call seeds, returns no events."""
        det = _build()
        rng = np.random.default_rng(42)
        events = det.process_buffer(_white_noise_buffer(rng))
        assert events == []
        # Each channel got a baseline.
        assert all(s.baseline_rms is not None for s in det._states)


# ── trigger conditions ───────────────────────────────────────────────────


class TestTriggerConditions:
    def test_sustained_sine_on_one_channel_triggers(self) -> None:
        """The canonical positive case: a 1 kHz sine on channel 5 sustained
        for 2 windows should produce one TriggerEvent on channel 5.
        """
        det = _build()
        # Window 1 (cold seed; no event)
        ev = det.process_buffer(_silent_buffer())
        assert ev == []
        # Window 2: sine begins. First sustained window — counter=1, no fire.
        sine = _sine_buffer(target_channel=5)
        ev = det.process_buffer(sine)
        assert ev == []
        # Window 3: sustained N=2 — fires.
        ev = det.process_buffer(sine)
        assert len(ev) == 1
        event = ev[0]
        assert event.channel_index == 5
        # Dominant freq should be near 1 kHz (within bin width ≈ 23 Hz).
        assert abs(event.dominant_frequency_hz - 1000.0) < 25
        # Spectral ratio for a pure sine vs Hann FFT is well above 6 dB.
        assert event.spectral_ratio_db > 6

    def test_pure_sine_spectral_ratio_far_above_white_noise(self) -> None:
        """Spectral concentration check: a pure sine concentrates ~all energy
        in one bin (~30 dB ratio); broadband white noise spreads it across
        all bins (~12 dB by chi-square statistics). The detector relies on
        this separation to distinguish feedback whistle from program audio.
        """
        det = _build()
        sine = _sine_buffer(target_channel=5, amplitude=0.5)
        sine_ratio, sine_freq = det._spectral_peak_ratio_db(sine[:, 5])
        rng = np.random.default_rng(42)
        noise_buf = _white_noise_buffer(rng, amplitude=0.5)
        noise_ratios = [det._spectral_peak_ratio_db(noise_buf[:, ch])[0] for ch in range(14)]
        assert sine_ratio > max(noise_ratios) + 5, (
            f"sine ratio ({sine_ratio:.1f} dB) should be ≥5 dB above max noise "
            f"ratio ({max(noise_ratios):.1f} dB) for clean separation"
        )
        assert abs(sine_freq - 1000) < 25, f"dominant freq {sine_freq} Hz should be near 1 kHz"

    def test_isolated_noise_pulse_does_not_sustain(self) -> None:
        """Single noise window then silence: condition 1 fails on silence
        (peak ≈ 0 vs. positive baseline), so the sustain counter resets and
        no trigger fires even if the noise window happened to satisfy both
        conditions in isolation.
        """
        det = _build()
        rng = np.random.default_rng(42)
        det.process_buffer(_silent_buffer())  # seed
        det.process_buffer(_white_noise_buffer(rng, amplitude=0.3))  # may set counter=1
        ev = det.process_buffer(_silent_buffer())  # silence resets counter
        assert ev == []

    def test_brief_sine_burst_does_not_trigger(self) -> None:
        """A single sustaining window is not enough — sustain_windows=2.

        We use silence (not noise) as the reset window because noise can
        statistically pass condition 2 too; silence guarantees condition 1
        fails (peak ≈ 0) and the sustain counter resets.
        """
        det = _build()
        det.process_buffer(_silent_buffer())  # seed
        det.process_buffer(_sine_buffer())  # counter=1, no fire
        ev = det.process_buffer(_silent_buffer())  # peak fails → counter resets
        assert ev == []
        # Second sine after silence — counter back to 1, no fire.
        ev = det.process_buffer(_sine_buffer())
        assert ev == []

    def test_silence_after_seed_does_not_trigger(self) -> None:
        """No signal → both peak and spectral conditions fail → no trigger."""
        det = _build()
        for _ in range(10):
            ev = det.process_buffer(_silent_buffer())
            assert ev == []

    def test_trigger_only_on_loud_channel(self) -> None:
        """Sine on channel 5 must NOT trigger channels 0-4 or 6-13."""
        det = _build()
        det.process_buffer(_silent_buffer())
        det.process_buffer(_sine_buffer(target_channel=5))
        ev = det.process_buffer(_sine_buffer(target_channel=5))
        assert len(ev) == 1
        assert ev[0].channel_index == 5


class TestMinFrequencyFloor:
    def test_low_freq_sine_below_floor_does_not_trigger(self) -> None:
        """Field-tuning regression: 70 Hz contact-mic rumble triggered the
        spectral test on initial deploy. With min_frequency_hz=200 the peak
        bin is forced above 200 Hz; a 70 Hz sine concentrates spectral
        energy below the floor → peak picked from the (silent) spectrum
        above 200 Hz → low ratio → no trigger.
        """
        det = _build(min_frequency_hz=200.0)
        low_sine = _sine_buffer(frequency_hz=70.0, target_channel=5, amplitude=0.5)
        det.process_buffer(_silent_buffer())  # seed
        det.process_buffer(low_sine)  # would have set counter=1 pre-fix
        ev = det.process_buffer(low_sine)
        assert ev == []

    def test_high_freq_sine_above_floor_still_triggers(self) -> None:
        """Real feedback at 1 kHz must still fire — the floor only filters
        below the threshold, not above it.
        """
        det = _build(min_frequency_hz=200.0)
        high_sine = _sine_buffer(frequency_hz=1000.0, target_channel=5, amplitude=0.5)
        det.process_buffer(_silent_buffer())
        det.process_buffer(high_sine)
        ev = det.process_buffer(high_sine)
        assert len(ev) == 1
        assert ev[0].channel_index == 5
        assert ev[0].dominant_frequency_hz > 200.0

    def test_min_frequency_zero_disables_floor(self) -> None:
        """Setting min_frequency_hz=0 reverts to pre-fix behavior."""
        det = _build(min_frequency_hz=0.0)
        low_sine = _sine_buffer(frequency_hz=70.0, target_channel=5, amplitude=0.5)
        det.process_buffer(_silent_buffer())
        det.process_buffer(low_sine)
        ev = det.process_buffer(low_sine)
        assert len(ev) == 1
        assert ev[0].channel_index == 5


class TestWatchChannels:
    def test_unwatched_channel_skipped_entirely(self) -> None:
        """Sine on channel 5; detector configured to watch only [0, 2, 3].
        No analysis on ch 5 → no trigger even with sustained narrow-band.
        """
        det = _build(watch_channels=(0, 2, 3))
        sine = _sine_buffer(target_channel=5, amplitude=0.5)
        det.process_buffer(_silent_buffer())
        det.process_buffer(sine)
        ev = det.process_buffer(sine)
        assert ev == []

    def test_watched_channel_still_triggers(self) -> None:
        det = _build(watch_channels=(0, 2, 3, 4, 5))
        sine = _sine_buffer(target_channel=5, amplitude=0.5)
        det.process_buffer(_silent_buffer())
        det.process_buffer(sine)
        ev = det.process_buffer(sine)
        assert len(ev) == 1
        assert ev[0].channel_index == 5

    def test_watch_channels_none_analyses_all(self) -> None:
        """Default watch_channels=None must analyze every channel."""
        det = _build(watch_channels=None)
        sine = _sine_buffer(target_channel=11, amplitude=0.5)  # outside broadcast set
        det.process_buffer(_silent_buffer())
        det.process_buffer(sine)
        ev = det.process_buffer(sine)
        assert len(ev) == 1
        assert ev[0].channel_index == 11

    def test_baseline_does_not_advance_for_unwatched_channels(self) -> None:
        """Skipping a channel must not seed/update its baseline (state stays
        clean if watch_channels later expands at restart)."""
        det = _build(watch_channels=(0,))
        det.process_buffer(_silent_buffer())
        det.process_buffer(_sine_buffer(target_channel=5))
        # Channel 5 was never analyzed → baseline still None.
        assert det._states[5].baseline_rms is None
        # Channel 0 was analyzed → baseline seeded.
        assert det._states[0].baseline_rms is not None


# ── cooldown ──────────────────────────────────────────────────────────────


class TestCooldown:
    def test_cooldown_suppresses_re_fire(self) -> None:
        """After firing, the same channel cannot fire again until cooldown elapses."""
        det = _build(cooldown_s=30.0)
        sine = _sine_buffer(target_channel=5)
        now0 = datetime(2026, 4, 26, 0, 0, 0, tzinfo=UTC)
        # Seed + sustain + fire.
        det.process_buffer(_silent_buffer(), now=now0, epoch_now=0.0)
        det.process_buffer(sine, now=now0, epoch_now=1.0)
        ev = det.process_buffer(sine, now=now0, epoch_now=2.0)
        assert len(ev) == 1
        # 5 s later (still in cooldown), sustain again → no fire.
        ev2 = det.process_buffer(sine, now=now0, epoch_now=7.0)
        assert ev2 == []
        ev3 = det.process_buffer(sine, now=now0, epoch_now=7.5)
        assert ev3 == []

    def test_cooldown_releases_after_window(self) -> None:
        """40 s after the trigger (past 30 s cooldown), re-fire is possible."""
        det = _build(cooldown_s=30.0)
        sine = _sine_buffer(target_channel=5)
        now0 = datetime(2026, 4, 26, 0, 0, 0, tzinfo=UTC)
        det.process_buffer(_silent_buffer(), now=now0, epoch_now=0.0)
        det.process_buffer(sine, now=now0, epoch_now=1.0)
        det.process_buffer(sine, now=now0, epoch_now=2.0)  # fires
        # 40 s later, sustain another two windows → fires again.
        det.process_buffer(sine, now=now0, epoch_now=42.0)
        ev = det.process_buffer(sine, now=now0, epoch_now=42.5)
        assert len(ev) == 1


# ── side-effect fan-out ──────────────────────────────────────────────────


class TestEmitTriggerSideEffects:
    def _example_event(self) -> fld.TriggerEvent:
        return fld.TriggerEvent(
            channel_index=4,
            timestamp=datetime(2026, 4, 26, 1, 0, 0, tzinfo=UTC),
            peak_amplitude=0.6,
            rms=0.42,
            baseline_rms=0.05,
            spectral_ratio_db=18.5,
            dominant_frequency_hz=1842.7,
        )

    def test_calls_all_provided_side_effects(self) -> None:
        ev = self._example_event()
        auto_mute = MagicMock()
        awareness = MagicMock()
        refusal = MagicMock()
        notifier = MagicMock()
        counter = MagicMock()
        fld.emit_trigger_side_effects(
            ev,
            auto_mute=auto_mute,
            awareness_writer=awareness,
            refusal_logger=refusal,
            notifier=notifier,
            counter_inc=counter,
        )
        auto_mute.assert_called_once_with(ev)
        awareness.assert_called_once_with(ev)
        refusal.assert_called_once_with(ev)
        counter.assert_called_once_with(ev)
        notifier.assert_called_once()
        kwargs = notifier.call_args.kwargs
        assert "Feedback loop" in kwargs["title"]
        assert "1842" in kwargs["title"] or "1843" in kwargs["title"]
        assert kwargs["priority"] == "high"

    def test_missing_side_effects_are_skipped_silently(self) -> None:
        ev = self._example_event()
        # All None — should not raise.
        fld.emit_trigger_side_effects(ev)

    def test_auto_mute_runs_even_if_awareness_fails(self) -> None:
        """Awareness writer is optional; failure must not skip auto-mute."""
        ev = self._example_event()
        auto_mute = MagicMock()

        def angry_awareness(_ev: fld.TriggerEvent) -> None:
            raise RuntimeError("shm full")

        fld.emit_trigger_side_effects(ev, auto_mute=auto_mute, awareness_writer=angry_awareness)
        auto_mute.assert_called_once()

    def test_notifier_failure_does_not_propagate(self) -> None:
        ev = self._example_event()

        def angry_notifier(**kw) -> None:
            raise RuntimeError("ntfy unreachable")

        # Must not raise.
        fld.emit_trigger_side_effects(ev, notifier=angry_notifier)
