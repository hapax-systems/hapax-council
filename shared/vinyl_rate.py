"""Vinyl playback rate signal reader.

The operator plays records on a Korg Handytrax-PLAY. The deck's RPM
selector is discrete — playing a 45 RPM record on the 33⅓ setting
produces a non-standard playback rate of 0.741× (not the literal 0.5×
that the pre-2026-04-18 code assumed). A live-tuned pitch knob adds
±10% around the selected preset.

**Authority:** ``/dev/shm/hapax-compositor/vinyl-playback-rate.txt``
contains a single float. ``1.0`` = no rate distortion (standard
playback). ``< 1.0`` = slowed playback. Values outside ``[0.25, 2.0]``
are clamped to defend downstream ffmpeg filters.

**Legacy shim:** the pre-2026-04-18 flag
``/dev/shm/hapax-compositor/vinyl-mode.txt`` carried a boolean "true"
/ "false". On read, "true" maps to ``0.741`` (45-on-33 preset),
"false" maps to ``1.0``. The boolean file is deprecated; new writers
should prefer the float file. Both readers live here so there is one
source of truth for rate-aware consumers (album-identifier, BPM
tracker, reactivity compensation).

Operator invariant (CVS #3 / 2026-04-18): scripts that assumed a
hardcoded 2× speedup (e.g. ``scripts/album-identifier.py`` using
``asetrate=88200,aresample=44100``) must be ported to
``rate_to_restore_factor()`` so the restoration is correct for any
playback preset.
"""

from __future__ import annotations

from pathlib import Path

_SNAPSHOT_DIR = Path("/dev/shm/hapax-compositor")
_RATE_FILE = _SNAPSHOT_DIR / "vinyl-playback-rate.txt"
_LEGACY_BOOL_FILE = _SNAPSHOT_DIR / "vinyl-mode.txt"

# The 45-RPM-on-33⅓ preset that the pre-existing boolean flag meant.
# Operator-confirmable; a configured override will land in a follow-up.
_LEGACY_TRUE_RATE = 0.741
_LEGACY_FALSE_RATE = 1.0

_MIN_RATE = 0.25
_MAX_RATE = 2.0


def read_vinyl_playback_rate() -> float:
    """Return the current vinyl playback rate.

    1.0 = no distortion. Values outside [0.25, 2.0] are clamped.
    Missing / unreadable files default to 1.0.

    Reads the float file first; falls back to the legacy boolean file
    if the float file is absent. This dual-read keeps existing writers
    (the /studio/vinyl-mode/toggle endpoint still writes the bool file)
    working while the float path rolls out.
    """
    rate = _read_float_file()
    if rate is None:
        rate = _read_legacy_bool_file()
    if rate is None:
        return 1.0
    return max(_MIN_RATE, min(_MAX_RATE, rate))


def _read_float_file() -> float | None:
    try:
        if _RATE_FILE.exists():
            raw = _RATE_FILE.read_text().strip()
            return float(raw)
    except (OSError, ValueError):
        return None
    return None


def _read_legacy_bool_file() -> float | None:
    try:
        if _LEGACY_BOOL_FILE.exists():
            raw = _LEGACY_BOOL_FILE.read_text().strip().lower()
            if raw == "true":
                return _LEGACY_TRUE_RATE
            if raw == "false":
                return _LEGACY_FALSE_RATE
    except OSError:
        return None
    return None


def rate_to_restore_factor(rate: float) -> float:
    """Restoration factor that reverses the effect of playback at ``rate``.

    If the record is playing at ``rate`` (e.g. 0.741× for 45-on-33),
    multiplying the captured audio's sample rate by ``1/rate`` restores
    nominal pitch and tempo. Return 1.0 for rate 1.0 (identity).
    """
    if rate <= 0:
        return 1.0
    return 1.0 / rate


def compensate_bpm(observed_bpm: float, rate: float | None = None) -> float:
    """Convert observed-at-playback-rate BPM to nominal BPM.

    At rate 0.741×, a 120 BPM track is observed as 89 BPM. Multiply
    by ``1/rate`` to recover the nominal tempo so that downstream
    consumers (director music framing, MIDI/reactivity) see the track
    as its authors intended.
    """
    if rate is None:
        rate = read_vinyl_playback_rate()
    if rate <= 0:
        return observed_bpm
    return observed_bpm / rate


__all__ = [
    "compensate_bpm",
    "rate_to_restore_factor",
    "read_vinyl_playback_rate",
]
