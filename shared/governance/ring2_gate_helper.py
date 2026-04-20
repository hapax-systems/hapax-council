"""Ring 2 gate helper — one-call wrapper for production call-sites.

Phase 3 §call-site convenience for ``#202``. Wraps the three-step
pre-emit safety pipeline (surface resolution, classifier construction,
gate assess) into a single ``ring2_assess()`` call so production
modules (AffordancePipeline, TTSManager, future caption renderers)
don't duplicate boilerplate.

Design notes:

- **Surface resolution** maps ``OperationalProperties.medium`` (the
  four-value enum declared at capability-registration time) to a
  ``SurfaceKind``. The mapping is STRICTEST-FIRST: ambiguous mediums
  resolve to the more-risk-bearing surface, so borderline content
  still gets classified when there's doubt.
- **Classifier lifetime** is module-level singleton — one
  ``Ring2Classifier`` per process. Tests can inject via the
  ``classifier=`` kwarg.
- **Pre-render gate.** Called BEFORE the capability produces its
  rendered payload. The `rendered_payload` argument is whatever
  candidate-payload metadata is available (capability name, reason
  text, provenance). A post-render gate at TTS/caption emit time
  is a separate follow-up (plan §Phase 3 call-site insertion; this
  helper prepares the surface kind + classifier reference).

Callers:

- ``shared.affordance_pipeline.AffordancePipeline.select()`` (pre-
  render; uses metadata as payload proxy)
- Future: ``agents.hapax_daimonion.tts.TTSManager`` (post-text gate
  on synthesized string)
- Future: production_stream T2/T3 text paths
- Future: caption emit pipeline

Reference:
    - docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md §3
    - shared/governance/monetization_safety.py — the underlying
      ``MonetizationRiskGate.assess()`` that this helper invokes
    - shared/governance/ring2_classifier.py — the classifier impl
"""

from __future__ import annotations

import logging
from typing import Any, Final

from shared.governance.monetization_safety import (
    GATE,
    RiskAssessment,
    SurfaceKind,
)

log = logging.getLogger(__name__)


# Medium (OperationalProperties.medium) → SurfaceKind mapping. Chosen
# conservatively: ambiguous cases resolve to the surface with the
# highest Content-ID / demonetization risk floor so borderline content
# doesn't sneak past.
_MEDIUM_TO_SURFACE: Final[dict[str, SurfaceKind]] = {
    "auditory": SurfaceKind.TTS,
    "visual": SurfaceKind.WARD,
    "textual": SurfaceKind.OVERLAY,
    "notification": SurfaceKind.NOTIFICATION,
}

# Module-level classifier singleton. Built lazily on first use so
# importing this module doesn't spin up a pydantic-ai Agent.
_classifier_instance: Any = None


def resolve_surface(medium: str | None) -> SurfaceKind | None:
    """Map an ``OperationalProperties.medium`` value to a ``SurfaceKind``.

    Returns ``None`` when the medium is missing or unrecognized — the
    caller interprets that as "no Ring 2" (caller skips classification
    and relies on Ring 1 only).
    """
    if not medium:
        return None
    return _MEDIUM_TO_SURFACE.get(medium)


def default_classifier() -> Any:
    """Lazy-construct the module-level classifier singleton.

    Deferred import of ``Ring2Classifier`` keeps this module's import
    graph light — callers that set ``classifier=`` on every call never
    pay the pydantic-ai cost.
    """
    global _classifier_instance
    if _classifier_instance is None:
        from shared.governance.ring2_classifier import Ring2Classifier

        _classifier_instance = Ring2Classifier()
    return _classifier_instance


def reset_default_classifier() -> None:
    """Drop the cached classifier — used by tests + after daimonion restart."""
    global _classifier_instance
    _classifier_instance = None


def ring2_assess(
    candidate: Any,
    programme: Any = None,
    *,
    medium: str | None = None,
    surface: SurfaceKind | None = None,
    rendered_payload: Any = None,
    classifier: Any = None,
) -> RiskAssessment:
    """One-call Ring-1 + Ring-2 risk assessment on a capability candidate.

    Most callers need only ``candidate`` + ``programme`` + ``medium``.
    The helper:

    1. Resolves ``medium`` → ``SurfaceKind`` via ``_MEDIUM_TO_SURFACE``.
       Explicit ``surface`` kwarg overrides the mapping.
    2. Constructs a default classifier if none provided.
    3. Calls ``MonetizationRiskGate.assess()`` with Ring 2 kwargs.
    4. Returns the resulting ``RiskAssessment``.

    When ``medium`` and ``surface`` are both ``None``, the helper
    degrades to Ring-1-only (no LLM call) — equivalent to calling
    ``GATE.assess(candidate, programme)``.

    ``rendered_payload`` defaults to ``None`` — the pipeline caller
    passes what metadata it has (capability_name, risk_reason, medium)
    since rendered output isn't available pre-render. Post-render
    callers pass the actual emitted string / URL.
    """
    eff_surface = surface if surface is not None else resolve_surface(medium)
    eff_classifier = (
        classifier
        if classifier is not None
        else (default_classifier() if eff_surface is not None else None)
    )
    return GATE.assess(
        candidate,
        programme,
        ring2_classifier=eff_classifier,
        surface=eff_surface,
        rendered_payload=rendered_payload,
    )


__all__ = [
    "default_classifier",
    "reset_default_classifier",
    "resolve_surface",
    "ring2_assess",
]
