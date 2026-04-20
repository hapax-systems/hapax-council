"""MonetizationRiskGate — zero-red-flag content invariant (task #165, Phase 1).

Gates candidate capabilities against YouTube monetization risk BEFORE the
affordance pipeline scores them. Sits adjacent to the consent gate in
``shared.affordance_pipeline.AffordancePipeline.select``.

Risk levels (matched on ``OperationalProperties.monetization_risk``):

- **high**: unconditionally blocked on every surface
- **medium**: blocked unless the active ``Programme`` opts the capability
  in via ``Programme.constraints.monetization_opt_ins`` (that wiring
  ships in plan Phase 5; Phase 1 accepts a ``programme`` argument and
  defaults medium to blocked when ``programme is None``)
- **low** / **none**: pass through the filter unchanged

The filter is pure (no side effects, no network, no state). All
monetization-risk metadata is declared on the capability record at
registration time. Runtime pre-render classification (Ring 2 in the
research doc) is deferred to plan Phase 3.

References:
    - docs/research/2026-04-19-demonetization-safety-design.md §1, §4
    - docs/superpowers/plans/2026-04-20-demonetization-safety-plan.md §2
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Protocol

from shared.affordance import MonetizationRisk

# Re-exports for Phase-1 call sites.
__all__ = [
    "MonetizationRisk",
    "MonetizationRiskGate",
    "RiskAssessment",
    "SurfaceKind",
]


class SurfaceKind(StrEnum):
    """Where the rendered output would land if emitted.

    Phase 1 records the surface kind on each filter decision for later
    auditing; Phase 6 wires it into the egress JSONL. Phase 3 uses it to
    pick the classifier prompt.
    """

    TTS = "tts"
    CAPTIONS = "captions"
    CHRONICLE = "chronicle"
    OVERLAY = "overlay"
    WARD = "ward"
    NOTIFICATION = "notification"
    LOG = "log"


@dataclass(frozen=True)
class RiskAssessment:
    """Immutable result of a classification or catalog-lookup decision.

    Used by both the pre-flight capability filter (Ring 1) and the
    pre-render classifier (Ring 2, Phase 3) so both rings emit the same
    shape for downstream audit + quiet-frame logic.
    """

    allowed: bool
    risk: MonetizationRisk
    reason: str
    surface: SurfaceKind | None = None


class _CandidateLike(Protocol):
    """Structural type for AffordancePipeline SelectionCandidates.

    Accepts any object exposing ``capability_name`` and ``payload`` — keeps
    the gate independent of affordance_pipeline's import graph.
    """

    capability_name: str
    payload: dict[str, Any]


class _ProgrammeLike(Protocol):
    """Structural type for the Programme that opts-in medium capabilities.

    Phase 1 only reads ``monetization_opt_ins``. The concrete Programme
    model from ``shared.programme`` does not yet have this field (it
    lands in plan Phase 5 — intentionally so); for now the gate treats
    missing programmes and missing opt-ins identically.
    """

    @property
    def monetization_opt_ins(self) -> set[str]: ...


class MonetizationRiskGate:
    """Pure filter — blocks high-risk always, gates medium-risk on programme.

    No I/O, no caching, no logging in the hot path. A separate audit hook
    (Phase 6) will subscribe to the filter's return value without touching
    the filter itself.
    """

    def assess(
        self,
        candidate: _CandidateLike,
        programme: _ProgrammeLike | None = None,
    ) -> RiskAssessment:
        """Return a RiskAssessment without mutating state.

        Called from the pipeline's filter step and also available as a
        standalone helper for ad-hoc audits (plan Phases 6, 10).
        """
        risk: MonetizationRisk = candidate.payload.get("monetization_risk", "none")
        reason = candidate.payload.get("risk_reason") or ""
        name = candidate.capability_name

        if risk == "high":
            return RiskAssessment(
                allowed=False,
                risk=risk,
                reason=f"{name}: high-risk capability blocked unconditionally ({reason})".strip(
                    " ()"
                ),
            )
        if risk == "medium":
            opted_in = False
            if programme is not None:
                opt_ins = getattr(programme, "monetization_opt_ins", None)
                if opt_ins is not None and name in opt_ins:
                    opted_in = True
            if not opted_in:
                return RiskAssessment(
                    allowed=False,
                    risk=risk,
                    reason=f"{name}: medium-risk capability requires programme opt-in".rstrip(),
                )
            return RiskAssessment(
                allowed=True,
                risk=risk,
                reason=f"{name}: medium-risk capability opted in by active programme",
            )
        return RiskAssessment(
            allowed=True,
            risk=risk,
            reason=f"{name}: {risk}-risk capability — passed",
        )

    def candidate_filter(
        self,
        candidates: list[_CandidateLike],
        programme: _ProgrammeLike | None = None,
    ) -> list[_CandidateLike]:
        """Return only the candidates that pass the monetization gate."""
        return [c for c in candidates if self.assess(c, programme).allowed]


# Phase 1 ships a module-level singleton — the gate is stateless, so a
# single instance costs nothing and prevents accidental drift if callers
# were to construct multiple gates with divergent futures.
GATE = MonetizationRiskGate()


def candidate_filter(
    candidates: list[_CandidateLike],
    programme: _ProgrammeLike | None = None,
) -> list[_CandidateLike]:
    """Module-level convenience for the shared singleton."""
    return GATE.candidate_filter(candidates, programme)


def assess(
    candidate: _CandidateLike,
    programme: _ProgrammeLike | None = None,
) -> RiskAssessment:
    """Module-level convenience for the shared singleton."""
    return GATE.assess(candidate, programme)


# Deliberately unused import — kept only so ``Literal`` remains available
# for Phase 3 RiskAssessment refinements when the classifier lands.
_ = Literal
