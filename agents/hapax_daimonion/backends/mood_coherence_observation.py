"""Health-volatility → MoodCoherenceEngine signal adapter.

Phase 6b-iii adapter for the mood-coherence claim engine. Mood-coherence
(low / INCOHERENT-tier) signals are sourced from heterogeneous backends,
mostly Pixel Watch volatility/variance metrics (per
``DEFAULT_SIGNAL_WEIGHTS`` in ``mood_coherence_engine.py``):

- ``hrv_variability_high``: HRV beat-to-beat coefficient-of-variation
  high (``backends/health.py``; bidirectional)
- ``respiration_irregular``: respiration rate variance high
  (``backends/health.py``; positive-only)
- ``movement_jitter_high``: accelerometer micro-movement noise high
  (``backends/health.py``; positive-only)
- ``skin_temp_volatility_high``: skin temperature varying rapidly
  (``backends/health.py``; positive-only)

This adapter exposes a ``mood_coherence_observation`` builder that
takes any ``_HealthVolatilityCoherenceSource`` (anything implementing
the four accessors) and returns a single-tick observation dict for
``MoodCoherenceEngine.contribute()``.

The adapter contract is fully wired; the live ``LogosMoodCoherenceBridge``
returns ``bool | None`` per accessor. ``None`` means the source is
missing, stale, or still warming a rolling baseline. Per the
``ClaimEngine.tick`` contract, ``None`` means skip-this-signal-for-this-tick.

Reference doc: ``docs/superpowers/research/2026-04-23-bayesian-claims-research.md``
§Phase 6b + the MoodCoherenceEngine module docstring.
"""

from __future__ import annotations

from typing import Protocol


class _HealthVolatilityCoherenceSource(Protocol):
    """Anything exposing the four mood-coherence signal accessors.

    The bridge in ``logos/api/app.py`` (``LogosMoodCoherenceBridge``)
    matches this protocol; tests use a stub object with the same shape.
    Returning ``None`` signals "source unavailable for this tick" — the
    Bayesian engine then skips the signal (no contribution rather than
    negative evidence; positional ``None`` semantics documented in
    ``shared/claim.py::ClaimEngine.tick``).
    """

    def hrv_variability_high(self) -> bool | None: ...
    def respiration_irregular(self) -> bool | None: ...
    def movement_jitter_high(self) -> bool | None: ...
    def skin_temp_volatility_high(self) -> bool | None: ...


def mood_coherence_observation(
    source: _HealthVolatilityCoherenceSource,
) -> dict[str, bool | None]:
    """Build a single-tick observation dict for MoodCoherenceEngine.

    Returns the four-key dict matching ``DEFAULT_SIGNAL_WEIGHTS`` in
    ``agents/hapax_daimonion/mood_coherence_engine.py`` and the LR
    derivations in ``shared/lr_registry.yaml::mood_coherence_low_signals``.

    Designed for callers like::

        from agents.hapax_daimonion.mood_coherence_engine import MoodCoherenceEngine
        from agents.hapax_daimonion.backends.mood_coherence_observation import (
            mood_coherence_observation,
        )

        engine = MoodCoherenceEngine()
        engine.contribute(mood_coherence_observation(coherence_bridge))
    """
    return {
        "hrv_variability_high": source.hrv_variability_high(),
        "respiration_irregular": source.respiration_irregular(),
        "movement_jitter_high": source.movement_jitter_high(),
        "skin_temp_volatility_high": source.skin_temp_volatility_high(),
    }


__all__ = ["mood_coherence_observation"]
