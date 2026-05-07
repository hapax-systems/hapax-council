"""Stimmung → MoodArousalEngine signal adapter.

Phase 6b-i adapter for the mood-arousal claim engine. Mood-arousal
signals are sourced from heterogeneous backends (per
``DEFAULT_SIGNAL_WEIGHTS`` in ``mood_arousal_engine.py``):

- ``ambient_audio_rms_high``: room mic RMS above operator's recent quantile
  (``backends/ambient_audio.py`` provides RMS; quantile threshold needs
  a session-baseline reference)
- ``contact_mic_onset_rate_high``: Cortado MKIII onset rate above quantile
  (``backends/contact_mic.py`` provides onset rate; positive-only)
- ``midi_clock_bpm_high``: OXI One MIDI clock pulse rate above tempo cutoff
  (``backends/midi_clock.py`` provides BPM)
- ``hr_bpm_above_baseline``: Pixel Watch HR above session baseline
  (``backends/health.py`` provides HR; bidirectional)

This adapter exposes a ``mood_arousal_observation`` builder that takes
any ``_StimmungArousalSource`` (anything implementing the four
high/baseline accessors) and returns a single-tick observation dict for
``MoodArousalEngine.contribute()``.

The adapter contract is fully wired; the live ``LogosStimmungBridge``
returns ``bool | None`` per accessor. ``None`` means the source is
missing, stale, or still warming a rolling baseline. Per the
``ClaimEngine.tick`` contract, ``None`` means skip-this-signal-for-this-tick.

Reference doc: ``docs/superpowers/research/2026-04-23-bayesian-claims-research.md``
§Phase 6b + the MoodArousalEngine module docstring.
"""

from __future__ import annotations

from typing import Protocol


class _StimmungArousalSource(Protocol):
    """Anything exposing the four mood-arousal signal accessors.

    The bridge in ``logos/api/app.py`` (``LogosStimmungBridge``) matches
    this protocol; tests use a stub object with the same shape.
    Returning ``None`` signals "source unavailable for this tick" — the
    Bayesian engine then skips the signal (no contribution rather than
    negative evidence; positional ``None`` semantics documented in
    ``shared/claim.py::ClaimEngine.tick``).
    """

    def ambient_audio_rms_high(self) -> bool | None: ...
    def contact_mic_onset_rate_high(self) -> bool | None: ...
    def midi_clock_bpm_high(self) -> bool | None: ...
    def hr_bpm_above_baseline(self) -> bool | None: ...


def mood_arousal_observation(
    source: _StimmungArousalSource,
) -> dict[str, bool | None]:
    """Build a single-tick observation dict for MoodArousalEngine.

    Returns the four-key dict matching ``DEFAULT_SIGNAL_WEIGHTS`` in
    ``agents/hapax_daimonion/mood_arousal_engine.py`` and the LR
    derivations in ``shared/lr_registry.yaml::mood_arousal_high_signals``.

    Designed for callers like::

        from agents.hapax_daimonion.mood_arousal_engine import MoodArousalEngine
        from agents.hapax_daimonion.backends.mood_arousal_observation import (
            mood_arousal_observation,
        )

        engine = MoodArousalEngine()
        engine.contribute(mood_arousal_observation(stimmung_bridge))
    """
    return {
        "ambient_audio_rms_high": source.ambient_audio_rms_high(),
        "contact_mic_onset_rate_high": source.contact_mic_onset_rate_high(),
        "midi_clock_bpm_high": source.midi_clock_bpm_high(),
        "hr_bpm_above_baseline": source.hr_bpm_above_baseline(),
    }


__all__ = ["mood_arousal_observation"]
