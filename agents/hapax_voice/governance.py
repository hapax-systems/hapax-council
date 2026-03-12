"""Detective primitives: VetoChain, FallbackChain, FreshnessGuard, FusedContext.

Phase 2 of the perception type system. Detectives evaluate state and produce
structured judgments. They consume Perceptives and emit decisions that
Directives can carry to actuators.
"""

from __future__ import annotations

import logging
import types
from collections.abc import Callable
from dataclasses import dataclass, field

from agents.hapax_voice.primitives import Stamped

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FusedContext:
    """Output of a Combinator: trigger event fused with current Behavior values."""

    trigger_time: float
    trigger_value: object
    samples: dict[str, Stamped] = field(default_factory=dict)
    min_watermark: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "samples", types.MappingProxyType(self.samples))

    def get_sample(self, name: str) -> Stamped:
        """Look up a named sample. Raises KeyError if not present."""
        return self.samples[name]


@dataclass(frozen=True)
class VetoResult:
    """Outcome of a VetoChain evaluation."""

    allowed: bool
    denied_by: tuple[str, ...] = ()


@dataclass
class Veto[C]:
    """A single governance constraint. Predicate returns True=allow, False=deny."""

    name: str
    predicate: Callable[[C], bool]
    axiom: str | None = None


class VetoChain[C]:
    """Order-independent deny-wins constraint composition.

    Evaluates all vetoes regardless of individual results (for audit trail).
    Adding a veto can only make the system more restrictive, never less.
    """

    __slots__ = ("_vetoes",)

    def __init__(self, vetoes: list[Veto[C]] | None = None) -> None:
        self._vetoes: list[Veto[C]] = list(vetoes) if vetoes else []

    @property
    def vetoes(self) -> list[Veto[C]]:
        return list(self._vetoes)

    def add(self, veto: Veto[C]) -> None:
        """Append a veto to the chain."""
        self._vetoes.append(veto)

    def evaluate(self, context: C) -> VetoResult:
        """Evaluate all constraints. Any denial blocks the action."""
        denials: list[str] = []
        for veto in self._vetoes:
            if not veto.predicate(context):
                denials.append(veto.name)
        return VetoResult(allowed=len(denials) == 0, denied_by=tuple(denials))


@dataclass(frozen=True)
class Selected[T]:
    """Output of a FallbackChain selection."""

    action: T
    selected_by: str


@dataclass
class Candidate[C, T]:
    """A candidate action with eligibility condition."""

    name: str
    predicate: Callable[[C], bool]
    action: T


class FallbackChain[C, T]:
    """Priority-ordered action selection. First eligible candidate wins.

    Deterministic: same context always selects same action.
    Graceful degradation: default always exists.
    """

    __slots__ = ("_candidates", "_default")

    def __init__(self, candidates: list[Candidate[C, T]], default: T) -> None:
        self._candidates = list(candidates)
        self._default = default

    def select(self, context: C) -> Selected[T]:
        """Select the highest-priority eligible action."""
        for c in self._candidates:
            if c.predicate(context):
                return Selected(action=c.action, selected_by=c.name)
        return Selected(action=self._default, selected_by="default")


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
