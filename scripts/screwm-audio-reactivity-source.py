#!/usr/bin/env python3
"""Screwm-native audio-reactivity producer (R2).

Re-homes the audio -> visual reactivity that studio-compositor used to drive.
The DSP (``CompositorAudioCapture``) and the publish bus
(``shared.audio_reactivity.UnifiedReactivityBus``) already exist; the GStreamer
studio-compositor was only the per-frame *driver*, and it is gated off in
screwm mode -- so ``/dev/shm/hapax-compositor/unified-reactivity.json`` stopped
being written and audio reactivity died at the engine boundary.

This daemon re-drives the bus WITHOUT the compositor:
- captures ``mixer_master`` via ``pw-cat`` (READ-ONLY tap; no routing change,
  audio invariants untouched),
- adapts the DSP signal dict to the unified ``AudioSignals`` shape,
- ticks the bus at 60 Hz, which publishes ``unified-reactivity.json``.

The reverie/effect-drift pipeline and the information-density daemon read that
file, so this restores live audio coupling to the screwm surface.
"""

from __future__ import annotations

import importlib.util
import os
import signal
import sys
import time
from pathlib import Path
from types import FrameType

os.environ.setdefault("HAPAX_UNIFIED_REACTIVITY_ACTIVE", "1")

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Load CompositorAudioCapture standalone. audio_capture.py is self-contained
# (numpy + subprocess only); we deliberately bypass the agents.studio_compositor
# package __init__, which eagerly imports the full GStreamer StudioCompositor
# stack that is gated off in screwm mode.
_AC_PATH = _ROOT / "agents" / "studio_compositor" / "audio_capture.py"
_spec = importlib.util.spec_from_file_location("_screwm_audio_capture", _AC_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover - import guard
    raise RuntimeError(f"cannot load audio_capture from {_AC_PATH}")
_ac = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ac)
CompositorAudioCapture = _ac.CompositorAudioCapture

from shared.audio_reactivity import AudioSignals, get_bus  # noqa: E402

PUBLISH_HZ = 60.0
PERIOD_S = 1.0 / PUBLISH_HZ
ACTIVITY_FLOOR_RMS = 0.01


class MixerMasterSource:
    """Adapt ``CompositorAudioCapture``'s signal dict to ``AudioReactivitySource``.

    The daemon calls :meth:`refresh` exactly once per bus tick so the capture's
    peak-hold/decay (inside ``get_signals``) runs once per tick; the bus's
    ``is_active()`` + ``get_signals()`` then both read the cached snapshot
    (no double-poll, so transient pulses are not decayed twice).
    """

    def __init__(self, capture: object, name: str = "mixer") -> None:
        self._capture = capture
        self._name = name
        self._snap: dict[str, float] = {}

    def refresh(self) -> None:
        self._snap = self._capture.get_signals()

    @property
    def name(self) -> str:
        return self._name

    def get_signals(self) -> AudioSignals:
        s = self._snap
        onset = max(
            s.get("onset_kick", 0.0),
            s.get("onset_snare", 0.0),
            s.get("onset_hat", 0.0),
            s.get("beat_pulse", 0.0),
        )
        return AudioSignals(
            rms=s.get("mixer_energy", 0.0),
            onset=onset,
            centroid=s.get("spectral_centroid", 0.0),
            zcr=s.get("zero_crossing_rate", 0.0),
            bpm_estimate=0.0,
            energy_delta=0.0,
            bass_band=s.get("mixer_bass", 0.0),
            mid_band=s.get("mixer_mid", 0.0),
            treble_band=s.get("mixer_high", 0.0),
        )

    def is_active(self) -> bool:
        return self._snap.get("mixer_energy", 0.0) > ACTIVITY_FLOOR_RMS


def main() -> int:
    target = os.environ.get("HAPAX_SCREWM_AUDIO_TARGET", "mixer_master")
    capture = CompositorAudioCapture(target=target)
    capture.start()
    source = MixerMasterSource(capture)
    bus = get_bus()
    bus.register(source)

    running = True

    def _stop(_signum: int, _frame: FrameType | None) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    next_tick = time.monotonic()
    try:
        while running:
            source.refresh()
            bus.tick(publish=True)
            next_tick += PERIOD_S
            delay = next_tick - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_tick = time.monotonic()
    finally:
        capture.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
