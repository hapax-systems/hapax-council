"""hapax-refusals — refusal-as-data primitives.

Public surface:

- :class:`ClaimSpec` — minimal claim model (name, posterior, proposition).
- :class:`RefusalGate` — surface-floored R-Tuning post-emission verifier.
- :class:`RefusalResult` — accept/reject + re-roll prompt addendum.
- :func:`refuse_and_reroll` — drop-in wrapper around any LLM call.
- :func:`claim_discipline_score` — Langfuse-bound 0/1 score per check.
- :class:`RefusalEvent` / :class:`RefusalRegistry` — refusal-as-data log.
- :data:`SURFACE_FLOORS` / :data:`NarrationSurface` — surface taxonomy.

The CORE export is :func:`refuse_and_reroll`: a re-roll-on-refuse
pattern that wraps any LLM call with surface-floored claim-discipline.
See its docstring for the canonical usage shape.
"""

from __future__ import annotations

from hapax_refusals.claim import ClaimSpec
from hapax_refusals.gate import (
    LlmCall,
    RefusalGate,
    RefusalResult,
    claim_discipline_score,
    parse_emitted_propositions,
    refuse_and_reroll,
)
from hapax_refusals.registry import (
    REASON_MAX_CHARS,
    RefusalEvent,
    RefusalRegistry,
)
from hapax_refusals.surface import (
    SURFACE_FLOORS,
    NarrationSurface,
    floor_for,
)

__all__ = [
    "REASON_MAX_CHARS",
    "SURFACE_FLOORS",
    "ClaimSpec",
    "LlmCall",
    "NarrationSurface",
    "RefusalEvent",
    "RefusalGate",
    "RefusalRegistry",
    "RefusalResult",
    "claim_discipline_score",
    "floor_for",
    "parse_emitted_propositions",
    "refuse_and_reroll",
]

__version__ = "0.1.0"
