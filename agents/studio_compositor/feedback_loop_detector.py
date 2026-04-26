"""Per-channel L-12 feedback-loop detector with smooth auto-mute.

Long-term safety net for the architectural class of bug that motivated
PR #1471 (capture binding narrowed 14→4): broadcast → L-12 → broadcast
must remain structurally impossible. Even after the immediate fix,
future PipeWire reconnect events, manual operator routing changes, or
the analogous ``hapax-s4-loopback.conf`` pattern can re-introduce a
digital feedback loop. This module is the runtime guard that
continuously watches the existing 14-channel parec capture, detects
narrow-band oscillation, and smooth-mutes the broadcast master with
ease/sine envelopes (never hard cuts — ``feedback_no_blinking_homage_wards``
applies to audio too).

Architectural axioms:

* ``feedback_l12_equals_livestream_invariant`` (inverse direction) —
  broadcast must NEVER loop back into L-12. The detector materializes
  the inverse half of the invariant as a runtime guard.
* ``broadcast_no_loopback`` (this PR's domain axiom) — the explicit
  inverse, weight ~75. Registered separately in ``axioms/registry.yaml``.
* ``feedback_no_blinking_homage_wards`` — every transition is a smooth
  envelope; there is no binary ``pactl set-sink-mute`` anywhere in this
  module.
* ``feedback_show_dont_tell_director`` — detector emits structured
  state + refusal log; it does NOT cause a director ward to narrate
  "feedback detected". Visual surfacing is a downstream concern.
* ``feedback_features_on_by_default`` — detector runs by default. There
  is no "validation mode" gate; if false-positives appear, tighten the
  thresholds — never gate the protection.

Detection algorithm (per research / cc-task spec):

* Rolling 250 ms window per channel (12 000 samples at 48 kHz).
* Peak amplitude + RMS over the window; a 10 s exponentially-weighted
  baseline RMS adapts to drift.
* 2048-point FFT with Hann window on the most recent window;
  peak-bin magnitude / total spectral RMS > 6 dB is the narrow-band
  oscillation signature.
* Trigger if peak > baseline + 12 dB AND spectral peak/RMS > 6 dB AND
  both sustained for two consecutive 250 ms windows (≥ 500 ms total).
* Per-channel 30 s cooldown after a trigger to avoid re-firing on the
  channel's own envelope tail.

The class itself does not own the ``parec`` subprocess or the
auto-mute side-effect. Both are dependency-injected so unit tests can
feed synthetic numpy arrays and assert on structured trigger events
without touching live audio. The systemd-side daemon wires the
subprocess + the volume-modulation hook; that wiring lives in a
follow-up commit.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np

LOG = logging.getLogger("feedback-loop-detector")

# ── Constants ──────────────────────────────────────────────────────────────

# Capture parameters — match the existing hapax-l12-evilpet-capture.
DEFAULT_SAMPLE_RATE_HZ = 48_000
DEFAULT_CHANNELS = 14
"""L-12 USB capture exposes 14 channels (strips 1–12 + MASTER 13/14)."""

# Window + analysis parameters (research §Detection algorithm).
DEFAULT_WINDOW_MS = 250
DEFAULT_FFT_SIZE = 2048
"""≈ 42 ms at 48 kHz. Good enough resolution to separate narrow-band
oscillation peaks from broadband musical content."""

DEFAULT_BASELINE_TAU_S = 10.0
"""Time constant for the exponentially-weighted baseline RMS."""

# Trigger thresholds (research §Trigger condition). Field-tuned post-deploy.
DEFAULT_PEAK_OVER_BASELINE_DB = 12.0
DEFAULT_SPECTRAL_RATIO_DB = 12.0
"""Spectral peak/RMS ratio threshold. Bumped from 6 → 12 dB after field
deploy: sustained vocal notes, MPC sample loops, synth tails routinely
hit 20–26 dB, well above the 6 dB design threshold but below feedback-
whistle territory (typically 25+ dB on a single bin). 12 dB filters
mid-content while keeping feedback whistle margin."""
DEFAULT_SUSTAIN_WINDOWS = 4
"""Both conditions must hold across four consecutive 250 ms windows
(≥ 1 s sustained). Bumped from 2 → 4: real digital feedback whistles
persist until something corrects them (operator action, auto-mute);
musical content rarely sustains a single peak frequency for 1+ s."""

DEFAULT_COOLDOWN_S = 30.0
"""Per-channel re-arm timeout after a trigger fires."""

DEFAULT_MIN_FREQUENCY_HZ = 200.0
"""Spectral-peak frequency floor.

Field-tuning post-deploy: low-frequency content (HVAC at ~70 Hz, room
modes at 40-150 Hz, contact-mic table rumble at 0-50 Hz) routinely
exhibits high single-bin spectral concentration and trips the 6 dB
peak-to-RMS test. Real digital feedback whistles concentrate at the
loop's resonant frequency, which sits above 200 Hz for typical
analog↔digital paths (low-end-trimmed by loudnorm + AUX-send bus).
Skip FFT bins below this frequency when picking the peak; the
peak/RMS-of-spectrum is still computed across the full band so
broadband content above the floor stays discriminating."""

# Numerical safety: clamp baseline RMS at this floor so a long stretch
# of digital silence doesn't make the +12 dB threshold trivially
# exceeded by ordinary noise floor on the next non-silent sample.
_BASELINE_FLOOR_RMS = 1e-6


# ── Data classes ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TriggerEvent:
    """One feedback-loop trigger.

    Emitted when the detector observes the trigger condition on a
    channel for ``DEFAULT_SUSTAIN_WINDOWS`` consecutive windows. The
    event carries enough metadata that a downstream consumer (auto-mute
    side-effect, awareness state writer, refusal log writer, ntfy
    sender) can record the incident without re-deriving it.
    """

    channel_index: int
    """Zero-based channel index in the parec capture (0..N-1)."""

    timestamp: datetime
    """UTC ISO-8601 of the second sustaining window (when trigger fired)."""

    peak_amplitude: float
    """Linear peak amplitude in the trigger window. Range [0, 1]."""

    rms: float
    """Linear RMS in the trigger window."""

    baseline_rms: float
    """Per-channel baseline RMS at trigger time."""

    spectral_ratio_db: float
    """Peak-bin magnitude / total spectral RMS, in dB."""

    dominant_frequency_hz: float
    """Frequency of the FFT peak bin that triggered."""


@dataclass
class _ChannelState:
    """Per-channel rolling state.

    ``baseline_rms`` is None until enough windows have been observed
    for the EWMA to be meaningful — the trigger is gated until then so
    a cold-start does not auto-mute.
    """

    baseline_rms: float | None = None
    sustained_count: int = 0
    cooldown_until_ts: float = 0.0
    """Unix epoch seconds; trigger suppressed while ``time.time() < cooldown_until_ts``."""


@dataclass
class FeedbackLoopDetector:
    """Per-channel narrow-band oscillation detector.

    Designed for dependency-injection: feed buffers via :meth:`process_buffer`
    and read structured ``TriggerEvent`` objects out. The systemd-side
    daemon owns the ``parec`` subprocess and the auto-mute side-effect.

    All numerical state is kept in plain Python; numpy is used only for
    FFT / RMS within a single buffer (no cross-buffer numpy state).
    """

    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ
    channels: int = DEFAULT_CHANNELS
    window_ms: int = DEFAULT_WINDOW_MS
    fft_size: int = DEFAULT_FFT_SIZE
    baseline_tau_s: float = DEFAULT_BASELINE_TAU_S
    peak_over_baseline_db: float = DEFAULT_PEAK_OVER_BASELINE_DB
    spectral_ratio_db: float = DEFAULT_SPECTRAL_RATIO_DB
    sustain_windows: int = DEFAULT_SUSTAIN_WINDOWS
    cooldown_s: float = DEFAULT_COOLDOWN_S
    min_frequency_hz: float = DEFAULT_MIN_FREQUENCY_HZ
    """Skip FFT bins below this frequency when picking the spectral peak."""
    watch_channels: tuple[int, ...] | None = None
    """If set, only analyze these channel indices (0-based). ``None`` analyzes
    all channels. Production daemon scopes to broadcast-path channels per the
    L-12 narrowing in PR #1471 — feedback on a channel that does not reach
    broadcast is irrelevant to the broadcast_no_loopback invariant."""

    _states: list[_ChannelState] = field(default_factory=list, init=False)
    _hann_window: np.ndarray = field(init=False)
    _watch_set: frozenset[int] = field(init=False)

    def __post_init__(self) -> None:
        self._states = [_ChannelState() for _ in range(self.channels)]
        # Pre-compute the Hann window once. FFT input is the most-recent
        # ``fft_size`` samples of the analysis window.
        self._hann_window = np.hanning(self.fft_size).astype(np.float32)
        if self.watch_channels is None:
            self._watch_set = frozenset(range(self.channels))
        else:
            self._watch_set = frozenset(self.watch_channels)

    # ── public API ─────────────────────────────────────────────────────────

    def window_size_samples(self) -> int:
        """Number of samples in one analysis window at the configured rate."""
        return int(self.sample_rate_hz * self.window_ms / 1000)

    def process_buffer(
        self,
        buffer: np.ndarray,
        *,
        now: datetime | None = None,
        epoch_now: float | None = None,
    ) -> list[TriggerEvent]:
        """Analyse one buffer of shape ``(window_samples, channels)``.

        ``buffer`` MUST be float32-normalized [-1, 1]. The systemd-side
        wrapper converts s32 parec output to this form. Returns the
        list of trigger events produced this call (usually empty).

        ``now`` and ``epoch_now`` are split because the per-channel
        cooldown needs a monotonic-ish epoch float (compares to
        ``cooldown_until_ts``) while ``TriggerEvent.timestamp`` is the
        wall-clock UTC datetime. Tests pass both for determinism; live
        callers can leave both as None and the method computes them.
        """
        now = now or datetime.now(UTC)
        epoch_now = epoch_now if epoch_now is not None else now.timestamp()

        if buffer.ndim != 2:
            raise ValueError(f"buffer must be 2-D (samples, channels); got shape {buffer.shape}")
        n_samples, n_channels = buffer.shape
        if n_channels != self.channels:
            raise ValueError(
                f"channel count mismatch: buffer has {n_channels}, detector configured for {self.channels}"
            )
        if n_samples < self.fft_size:
            # Not enough samples for an FFT window. Skip — the daemon
            # accumulates and re-feeds; an under-fill means the live
            # source dropped.
            LOG.debug("process_buffer: under-fill %d < %d samples", n_samples, self.fft_size)
            return []

        events: list[TriggerEvent] = []
        for ch in range(self.channels):
            if ch not in self._watch_set:
                continue
            channel_data = buffer[:, ch].astype(np.float32, copy=False)
            event = self._analyse_channel(ch, channel_data, now=now, epoch_now=epoch_now)
            if event is not None:
                events.append(event)
        return events

    # ── internals ──────────────────────────────────────────────────────────

    def _analyse_channel(
        self,
        ch: int,
        samples: np.ndarray,
        *,
        now: datetime,
        epoch_now: float,
    ) -> TriggerEvent | None:
        state = self._states[ch]

        peak = float(np.max(np.abs(samples)))
        rms = float(np.sqrt(np.mean(samples * samples)))

        # Baseline EWMA. The α derivation: for a per-window update rate
        # of (1000 / window_ms) Hz, a continuous tau_s seconds maps to
        # alpha = 1 - exp(-window_s / tau_s).
        window_s = self.window_ms / 1000.0
        alpha = 1.0 - math.exp(-window_s / self.baseline_tau_s) if self.baseline_tau_s > 0 else 1.0
        if state.baseline_rms is None:
            # Seed with first observation; gate the trigger on the next
            # window so the EWMA has a chance to converge. Still returns
            # None this call.
            state.baseline_rms = max(_BASELINE_FLOOR_RMS, rms)
            state.sustained_count = 0
            return None
        new_baseline = (1.0 - alpha) * state.baseline_rms + alpha * rms
        state.baseline_rms = max(_BASELINE_FLOOR_RMS, new_baseline)

        # Cooldown gate: even if the channel triggers, suppress the
        # event entirely. We still update the baseline above so the
        # cooldown doesn't bias the EWMA.
        if epoch_now < state.cooldown_until_ts:
            state.sustained_count = 0
            return None

        # Trigger condition 1: peak > baseline + threshold (in dB).
        peak_over_baseline_db = 20.0 * math.log10(
            max(peak, _BASELINE_FLOOR_RMS) / state.baseline_rms
        )
        if peak_over_baseline_db < self.peak_over_baseline_db:
            state.sustained_count = 0
            return None

        # Trigger condition 2: narrow-band spectral concentration.
        ratio_db, dominant_hz = self._spectral_peak_ratio_db(samples)
        if ratio_db < self.spectral_ratio_db:
            state.sustained_count = 0
            return None

        # Both conditions met this window. Increment sustain counter.
        state.sustained_count += 1
        if state.sustained_count < self.sustain_windows:
            return None

        # SUSTAINED triggered. Arm cooldown + reset counter + emit.
        state.cooldown_until_ts = epoch_now + self.cooldown_s
        state.sustained_count = 0
        return TriggerEvent(
            channel_index=ch,
            timestamp=now,
            peak_amplitude=peak,
            rms=rms,
            baseline_rms=state.baseline_rms,
            spectral_ratio_db=ratio_db,
            dominant_frequency_hz=dominant_hz,
        )

    def _spectral_peak_ratio_db(self, samples: np.ndarray) -> tuple[float, float]:
        """Compute the peak-bin / total-spectral-RMS ratio in dB.

        Uses the most recent ``fft_size`` samples. Returns ``(ratio_db,
        dominant_frequency_hz)``. A pure sine concentrates virtually
        all spectral energy in one bin → very high ratio. Broadband
        music spreads energy → low ratio.
        """
        tail = samples[-self.fft_size :]
        windowed = tail * self._hann_window
        spectrum = np.abs(np.fft.rfft(windowed))
        # rfft bin spacing = sample_rate / fft_size.
        bin_hz = self.sample_rate_hz / self.fft_size
        # Skip bins below ``min_frequency_hz`` when picking the peak — low-freq
        # room noise (HVAC, contact-mic rumble) routinely concentrates spectral
        # energy and false-positives the ratio test. Total RMS is still computed
        # across the full band so the ratio remains a meaningful contrast.
        min_bin = int(math.ceil(self.min_frequency_hz / bin_hz)) if bin_hz > 0 else 0
        min_bin = min(max(min_bin, 0), len(spectrum) - 1)
        if min_bin >= len(spectrum):
            return -math.inf, 0.0
        search_spectrum = spectrum.copy()
        search_spectrum[:min_bin] = 0.0
        peak_idx = int(np.argmax(search_spectrum))
        peak_mag = float(search_spectrum[peak_idx])
        total_rms = float(np.sqrt(np.mean(spectrum * spectrum)))
        if total_rms <= 0.0 or peak_mag <= 0.0:
            return -math.inf, 0.0
        ratio_db = 20.0 * math.log10(peak_mag / total_rms)
        return ratio_db, peak_idx * bin_hz


# ── outer-loop side-effect plumbing (lightweight; full daemon in PR2 of this task) ──


def emit_trigger_side_effects(
    event: TriggerEvent,
    *,
    auto_mute: Callable[[TriggerEvent], None] | None = None,
    awareness_writer: Callable[[TriggerEvent], None] | None = None,
    refusal_logger: Callable[[TriggerEvent], None] | None = None,
    notifier: Callable[..., Any] | None = None,
    counter_inc: Callable[[TriggerEvent], None] | None = None,
) -> None:
    """Fan out the four documented side-effects for a trigger.

    All callables are optional; missing dependencies degrade gracefully
    so the safety-critical auto-mute path still fires even if the
    awareness state file or refusal-log directory is unavailable. The
    systemd daemon (follow-up commit) wires the production callables;
    tests pass stubs for assertion.
    """
    if auto_mute is not None:
        try:
            auto_mute(event)
        except Exception:
            LOG.exception("feedback-loop auto-mute side-effect failed")
    if awareness_writer is not None:
        try:
            awareness_writer(event)
        except Exception:
            LOG.exception("feedback-loop awareness-state write failed")
    if refusal_logger is not None:
        try:
            refusal_logger(event)
        except Exception:
            LOG.exception("feedback-loop refusal-log write failed")
    if counter_inc is not None:
        try:
            counter_inc(event)
        except Exception:
            LOG.debug("feedback-loop prometheus counter inc failed", exc_info=True)
    if notifier is not None:
        try:
            notifier(
                title=f"Feedback loop auto-muted (CH {event.channel_index + 1}, {event.dominant_frequency_hz:.0f} Hz)",
                message=(
                    f"L-12 channel {event.channel_index + 1} sustained "
                    f"{event.dominant_frequency_hz:.1f} Hz oscillation "
                    f"(spectral peak/RMS {event.spectral_ratio_db:.1f} dB); "
                    f"auto-muted broadcast master."
                ),
                priority="high",
                tags=["mute", "warning"],
            )
        except Exception:
            LOG.debug("feedback-loop ntfy send failed", exc_info=True)


__all__ = [
    "FeedbackLoopDetector",
    "TriggerEvent",
    "emit_trigger_side_effects",
    "DEFAULT_CHANNELS",
    "DEFAULT_SAMPLE_RATE_HZ",
    "DEFAULT_WINDOW_MS",
    "DEFAULT_FFT_SIZE",
    "DEFAULT_COOLDOWN_S",
    "DEFAULT_MIN_FREQUENCY_HZ",
]
