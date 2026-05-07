"""Health/voice → MoodValenceEngine signal adapter.

Phase 6b-ii adapter for the mood-valence claim engine. Mood-valence
signals are sourced from heterogeneous backends (per
``DEFAULT_SIGNAL_WEIGHTS`` in ``mood_valence_engine.py``):

- ``hrv_below_baseline``: Pixel Watch HRV below operator's recent
  baseline (``backends/health.py``; bidirectional)
- ``skin_temp_drop``: Pixel Watch skin temperature drop from baseline
  (``backends/health.py``; positive-only)
- ``sleep_debt_high``: accumulated sleep deficit above tolerance
  threshold (``backends/health.py``; positive-only)
- ``voice_pitch_elevated``: voice pitch elevated above operator's
  session baseline (Kokoro/Whisper-side speech analysis; positive-only)

This adapter exposes a ``mood_valence_observation`` builder that takes
any ``_HealthVoiceValenceSource`` (anything implementing the four
accessors) and returns a single-tick observation dict for
``MoodValenceEngine.contribute()``.

The adapter contract is fully wired; the live ``LogosMoodValenceBridge``
returns ``bool | None`` per accessor. ``None`` means the source is
missing, stale, or still warming a rolling baseline. Per the
``ClaimEngine.tick`` contract, ``None`` means skip-this-signal-for-this-tick.

Reference doc: ``docs/superpowers/research/2026-04-23-bayesian-claims-research.md``
§Phase 6b + the MoodValenceEngine module docstring.
"""

from __future__ import annotations

from typing import Protocol


class _HealthVoiceValenceSource(Protocol):
    """Anything exposing the four mood-valence signal accessors.

    The bridge in ``logos/api/app.py`` (``LogosMoodValenceBridge``)
    matches this protocol; tests use a stub object with the same shape.
    Returning ``None`` signals "source unavailable for this tick" — the
    Bayesian engine then skips the signal (no contribution rather than
    negative evidence; positional ``None`` semantics documented in
    ``shared/claim.py::ClaimEngine.tick``).
    """

    def hrv_below_baseline(self) -> bool | None: ...
    def skin_temp_drop(self) -> bool | None: ...
    def sleep_debt_high(self) -> bool | None: ...
    def voice_pitch_elevated(self) -> bool | None: ...


def mood_valence_observation(
    source: _HealthVoiceValenceSource,
) -> dict[str, bool | None]:
    """Build a single-tick observation dict for MoodValenceEngine.

    Returns the four-key dict matching ``DEFAULT_SIGNAL_WEIGHTS`` in
    ``agents/hapax_daimonion/mood_valence_engine.py`` and the LR
    derivations in ``shared/lr_registry.yaml::mood_valence_negative_signals``.

    Designed for callers like::

        from agents.hapax_daimonion.mood_valence_engine import MoodValenceEngine
        from agents.hapax_daimonion.backends.mood_valence_observation import (
            mood_valence_observation,
        )

        engine = MoodValenceEngine()
        engine.contribute(mood_valence_observation(valence_bridge))
    """
    return {
        "hrv_below_baseline": source.hrv_below_baseline(),
        "skin_temp_drop": source.skin_temp_drop(),
        "sleep_debt_high": source.sleep_debt_high(),
        "voice_pitch_elevated": source.voice_pitch_elevated(),
    }


__all__ = ["mood_valence_observation"]
