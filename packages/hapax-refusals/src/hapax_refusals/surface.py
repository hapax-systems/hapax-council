"""Per-surface posterior floor taxonomy.

Asymmetric per surface brittleness — narration surfaces with higher
self-initiated bar (autonomous narrative, persona, grounding-act)
require higher posterior conviction before an LLM may assert a fact;
director-level commentary, audible to viewers but well-bounded as
running narration, has the lowest floor.

  =====================  =====  ==========================================
  Surface                Floor  Rationale
  =====================  =====  ==========================================
  director               0.60   Audible to viewers; retraction is costly
  spontaneous_speech     0.70   Unprompted emission; self-initiated bar
  autonomous_narrative   0.75   Director-over-director; compounding cost
  voice_persona          0.80   Direct conversation; max-intimacy hallucination
  grounding_act          0.90   T4 Jemeinigkeit requires conviction
  =====================  =====  ==========================================

Spec: §8 of the universal-Bayesian-claim-confidence research note.
The floor monotonically increases left-to-right; downstream callers
can rely on this ordering when picking a default surface.
"""

from __future__ import annotations

from typing import Final, Literal

NarrationSurface = Literal[
    "director",
    "spontaneous_speech",
    "autonomous_narrative",
    "voice_persona",
    "grounding_act",
]


SURFACE_FLOORS: Final[dict[str, float]] = {
    "director": 0.60,
    "spontaneous_speech": 0.70,
    "autonomous_narrative": 0.75,
    "voice_persona": 0.80,
    "grounding_act": 0.90,
}


def floor_for(surface: NarrationSurface) -> float:
    """Return the posterior floor for ``surface``.

    Raises ``ValueError`` for an unknown surface so typo-shaped
    misuse fails loudly rather than silently routing to a default.
    """
    try:
        return SURFACE_FLOORS[surface]
    except KeyError as exc:
        raise ValueError(
            f"unknown surface {surface!r}; valid surfaces: {sorted(SURFACE_FLOORS.keys())}"
        ) from exc


__all__ = [
    "SURFACE_FLOORS",
    "NarrationSurface",
    "floor_for",
]
