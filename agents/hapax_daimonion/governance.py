"""Detective primitives: VetoChain, FallbackChain, FreshnessGuard, FusedContext.

Phase 2 of the perception type system. Detectives evaluate state and produce
structured judgments. They consume Perceptives and emit decisions that
Directives can carry to actuators.

Consent threading (DD-22):
- FusedContext gains optional consent_label (DD-5). Computed as join of all
  input Behavior labels by with_latest_from (L3). None = untracked.
- consent_veto() factory creates a Veto that checks FusedContext consent
  labels against required policies (DD-6).
"""

from __future__ import annotations

import logging
import types
from dataclasses import dataclass, field

from agents.hapax_daimonion.primitives import Stamped
from shared.governance import (
    Candidate,
    FallbackChain,
    GatedResult,
    Selected,
    Veto,
    VetoChain,
    VetoResult,
)
from shared.governance.consent_label import ConsentLabel

log = logging.getLogger(__name__)

# Re-export shared primitives so existing imports from this module still work.
__all__ = [
    "Candidate",
    "FallbackChain",
    "FusedContext",
    "GatedResult",
    "Selected",
    "Veto",
    "VetoChain",
    "VetoResult",
    "FreshnessRequirement",
    "FreshnessResult",
    "FreshnessGuard",
    "consent_veto",
]


@dataclass(frozen=True)
class FusedContext:
    """Output of a Combinator: trigger event fused with current Behavior values.

    Optional consent_label (DD-5, DD-22) carries the join of all input
    Behavior consent labels. None means consent is untracked for this
    context (gradual adoption, DD-16).
    """

    trigger_time: float
    trigger_value: object
    samples: dict[str, Stamped] = field(default_factory=dict)
    min_watermark: float = 0.0
    consent_label: ConsentLabel | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "samples", types.MappingProxyType(self.samples))

    def get_sample(self, name: str) -> Stamped:
        """Look up a named sample. Raises KeyError if not present."""
        return self.samples[name]


@dataclass(frozen=True)
class FreshnessRequirement:
    """Minimum freshness required for a specific signal."""

    behavior_name: str
    max_staleness_s: float


@dataclass(frozen=True)
class FreshnessResult:
    """Outcome of a FreshnessGuard check."""

    fresh_enough: bool
    violations: tuple[str, ...] = ()


class FreshnessGuard:
    """Rejects decisions made on stale perception data.

    Each requirement specifies a behavior and its maximum acceptable staleness.
    Composable with VetoChain: a staleness violation is just another denial.
    """

    __slots__ = ("_requirements",)

    def __init__(self, requirements: list[FreshnessRequirement] | None = None) -> None:
        self._requirements = list(requirements) if requirements else []

    def check(self, context: FusedContext, now: float) -> FreshnessResult:
        """Check all freshness requirements against watermarks."""
        violations: list[str] = []
        for req in self._requirements:
            try:
                sample = context.get_sample(req.behavior_name)
            except KeyError:
                violations.append(f"{req.behavior_name}: not present in context")
                continue
            staleness = now - sample.watermark
            if staleness > req.max_staleness_s:
                violations.append(
                    f"{req.behavior_name}: {staleness:.1f}s stale, max {req.max_staleness_s}s"
                )
        return FreshnessResult(fresh_enough=len(violations) == 0, violations=tuple(violations))


def consent_veto(
    required_label: ConsentLabel,
    axiom: str = "interpersonal_transparency",
) -> Veto[FusedContext]:
    """Create a Veto that checks FusedContext consent labels (DD-6).

    Denies if the FusedContext's consent label cannot flow to the
    required label. Also denies if consent is untracked (None) —
    per DD-3, no consent = no access at enforcement boundaries.
    """

    def _check_consent(ctx: FusedContext) -> bool:
        if ctx.consent_label is None:
            return False
        return ctx.consent_label.can_flow_to(required_label)

    return Veto(
        name="consent",
        predicate=_check_consent,
        axiom=axiom,
        description=f"Requires consent label that can flow to {required_label}",
    )
