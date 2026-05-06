"""Adapters that expose existing broadcast-capture DSP pipelines as ``AudioReactivitySource``.

Each adapter is a thin wrapper. No DSP changes — the underlying capture
class continues to run at its configured rate; the adapter just reshapes
its output into the unified ``AudioSignals`` dataclass and publishes it
through the bus.

Adapters:

- ``CompositorAudioCaptureSource`` — wraps ``CompositorAudioCapture``
  (FR / mixer_master, ``mixer_master`` → room mic / external mixer bus).
  Signal name prefix: ``mixer``.
- ``ContactMicSource`` — wraps ``ContactMicBackend`` output via its
  ``desk_energy`` / ``desk_onset_rate`` behaviors (FL / contact_mic).
  Signal name prefix: ``desk``.
- ``PipeWireLineInSource`` — generic adapter for Inputs 3-8 when a
  ``MelFFTReactivitySource``-style DSP becomes available. For now,
  provides a zero-signal fallback so the bus contract still holds.

The compositor startup path calls :func:`register_default_sources` once
after ``CompositorAudioCapture`` is constructed. When the
``HAPAX_UNIFIED_REACTIVITY_ACTIVE`` flag is OFF, registration is still
performed (so the bus observability surface is live) but consumers fall
back to direct-AudioCapture paths — see :mod:`shared.audio_reactivity`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from shared.audio_reactivity import (
    ACTIVITY_FLOOR_RMS,
    AudioSignals,
    UnifiedReactivityBus,
    get_bus,
)

if TYPE_CHECKING:
    from agents.studio_compositor.audio_capture import CompositorAudioCapture

log = logging.getLogger(__name__)


# ── Mixer master (FR / mixer_master) ─────────────────────────────────────────


class CompositorAudioCaptureSource:
    """Adapts ``CompositorAudioCapture.get_signals()`` to ``AudioSignals``.

    The compositor capture already snapshots transient values before
    applying decay (CVS #148, ``audio_capture.py::get_signals`` docstring),
    so this adapter does not need to re-order anything — it just reshapes
    the dict-of-floats into the unified dataclass.
    """

    def __init__(self, capture: CompositorAudioCapture, *, name: str = "mixer") -> None:
        self._capture = capture
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def get_signals(self) -> AudioSignals:
        raw = self._capture.get_signals()
        # Composite treble is the mean of (brilliance, air) mel bands
        # because ``mixer_high`` maps to 2-8 kHz while ``mel_air`` maps to
        # 8-16 kHz; averaging catches hi-hats + cymbals symmetrically.
        treble = max(
            float(raw.get("mixer_high", 0.0)),
            float(raw.get("mel_brilliance", 0.0)),
            float(raw.get("mel_air", 0.0)),
        )
        onset = max(
            float(raw.get("onset_kick", 0.0)),
            float(raw.get("onset_snare", 0.0)),
            float(raw.get("onset_hat", 0.0)),
            float(raw.get("beat_pulse", 0.0)),
        )
        return AudioSignals(
            rms=float(raw.get("mixer_energy", 0.0)),
            onset=onset,
            centroid=float(raw.get("spectral_centroid", 0.0)),
            zcr=float(raw.get("zero_crossing_rate", 0.0)),
            # CompositorAudioCapture doesn't emit a BPM estimate directly;
            # consumers that need BPM read it from ``beat_tracker`` state.
            bpm_estimate=0.0,
            # energy_delta is derived by consumers from prev/current rms;
            # we leave it at 0 here to avoid double-buffering the delta.
            energy_delta=0.0,
            bass_band=float(raw.get("mixer_bass", 0.0)),
            mid_band=float(raw.get("mixer_mid", 0.0)),
            treble_band=treble,
        )

    def is_active(self) -> bool:
        raw = self._capture.get_signals()
        return float(raw.get("mixer_energy", 0.0)) > ACTIVITY_FLOOR_RMS


# ── Contact mic (FL / contact_mic) ──────────────────────────────────────────


class ContactMicSource:
    """Adapts Cortado contact-mic state into ``AudioSignals``.

    The ``ContactMicBackend`` in ``agents/hapax_daimonion/backends/contact_mic.py``
    owns the DSP and publishes ``desk_energy`` + ``desk_onset_rate`` into
    a shared state object. This adapter accepts a callable that returns
    the current ``(energy, onset_rate, centroid_norm)`` tuple so it can
    be driven from either the daimonion process (in-process) or the
    compositor process (reading ``/dev/shm/hapax-contact-mic/state.json``).

    When no reader is provided or the reader raises, the adapter returns
    the zero signal (dormant).
    """

    def __init__(
        self,
        reader: Any | None = None,
        *,
        name: str = "desk",
    ) -> None:
        self._reader = reader
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def get_signals(self) -> AudioSignals:
        if self._reader is None:
            return AudioSignals.zero()
        try:
            state = self._reader()
        except Exception:
            log.debug("contact-mic reader raised", exc_info=True)
            return AudioSignals.zero()
        if not state:
            return AudioSignals.zero()
        energy = float(state.get("desk_energy", 0.0))
        onset_rate = float(state.get("desk_onset_rate", 0.0))
        centroid_norm = float(state.get("desk_centroid", 0.0))
        # Contact mic is broadband-hit — classify the onset as mid-band
        # impact for blending purposes. Inputs are pre-normalized by the
        # contact-mic backend's rolling AGC.
        return AudioSignals(
            rms=energy,
            onset=min(1.0, onset_rate),
            centroid=centroid_norm,
            zcr=0.0,
            bpm_estimate=0.0,
            energy_delta=0.0,
            bass_band=0.0,
            mid_band=energy,
            treble_band=0.0,
        )

    def is_active(self) -> bool:
        sig = self.get_signals()
        return sig.rms > ACTIVITY_FLOOR_RMS


# ── Generic PipeWire line-in (capture inputs 3-8) ───────────────────────────────


class PipeWireLineInSource:
    """Placeholder for auto-discovered capture line inputs (3-8).

    The full auto-discovery path lives in the #149 Phase C plan
    (``pw-dump`` enumeration + generated loopback config). Until that
    ships, this class exists so the Protocol contract is satisfied for
    any additional sources operators manually register; it returns zero
    signals by default and accepts an optional ``signal_provider``
    callable for test fixtures.
    """

    def __init__(
        self,
        name: str,
        *,
        signal_provider: Any | None = None,
    ) -> None:
        self._name = name
        self._provider = signal_provider

    @property
    def name(self) -> str:
        return self._name

    def get_signals(self) -> AudioSignals:
        if self._provider is None:
            return AudioSignals.zero()
        try:
            signals = self._provider()
        except Exception:
            log.debug("pipewire-linein provider raised", exc_info=True)
            return AudioSignals.zero()
        if isinstance(signals, AudioSignals):
            return signals
        if isinstance(signals, dict):
            return AudioSignals.from_dict(signals)
        return AudioSignals.zero()

    def is_active(self) -> bool:
        return self.get_signals().rms > ACTIVITY_FLOOR_RMS


# ── Composition root helper ─────────────────────────────────────────────────


def register_default_sources(
    capture: CompositorAudioCapture | None,
    *,
    contact_mic_reader: Any | None = None,
    bus: UnifiedReactivityBus | None = None,
) -> UnifiedReactivityBus:
    """Register the default set of sources on the bus.

    Called once from the compositor composition root after
    ``CompositorAudioCapture`` is constructed. Missing arguments register
    a zero-signal adapter so the contract is honored even in degraded
    launches (no mic, headless tests, etc.).
    """
    target_bus = bus or get_bus()
    if capture is not None:
        target_bus.register(CompositorAudioCaptureSource(capture, name="mixer"))
    target_bus.register(ContactMicSource(contact_mic_reader, name="desk"))
    return target_bus
