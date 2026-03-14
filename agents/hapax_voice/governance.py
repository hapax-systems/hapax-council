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
from collections.abc import Callable
from dataclasses import dataclass, field

from agents.hapax_voice.primitives import Stamped
from shared.consent_label import ConsentLabel

log = logging.getLogger(__name__)


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
class VetoResult:
    """Outcome of a VetoChain evaluation."""

    allowed: bool
    denied_by: tuple[str, ...] = ()
    axiom_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class GatedResult[T]:
    """Result of gating a value through a VetoChain.

    Wraps a value with its VetoResult: if allowed, `value` is the original;
    if denied, `value` is None.
    """

    veto_result: VetoResult
    value: T | None = None


@dataclass
class Veto[C]:
    """A single governance constraint. Predicate returns True=allow, False=deny."""

    name: str
    predicate: Callable[[C], bool]
    axiom: str | None = None
    description: str = ""


class VetoChain[C]:
    """Order-independent deny-wins constraint composition.

    Evaluates all vetoes regardless of individual results (for audit trail).
    Adding a veto can only make the system more restrictive, never less.
    Supports ``|`` composition: ``chain_a | chain_b`` concatenates vetoes.
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
        axiom_ids: list[str] = []
        for veto in self._vetoes:
            if not veto.predicate(context):
                denials.append(veto.name)
                if veto.axiom is not None:
                    axiom_ids.append(veto.axiom)
        return VetoResult(
            allowed=len(denials) == 0,
            denied_by=tuple(denials),
            axiom_ids=tuple(axiom_ids),
        )

    def gate(self, context: C, value: object) -> GatedResult:
        """Evaluate the chain and wrap the value in a GatedResult.

        If allowed, ``result.value`` is the original value.
        If denied, ``result.value`` is None.
        """
        veto_result = self.evaluate(context)
        return GatedResult(
            veto_result=veto_result,
            value=value if veto_result.allowed else None,
        )

    def __or__(self, other: VetoChain[C]) -> VetoChain[C]:
        """Concatenate two VetoChains. Returns a new chain with all vetoes."""
        return VetoChain(self._vetoes + other._vetoes)


@dataclass(frozen=True)
class Selected[T]:
    """Output of a FallbackChain selection."""

    action: T
    selected_by: str


@dataclass
class Candidate[C, T]:
    """A candidate action with eligibility condition.

    Optional `veto_chain` enables nested gating: the candidate's action
    is additionally gated by its own VetoChain before selection.
    """

    name: str
    predicate: Callable[[C], bool]
    action: T
    veto_chain: VetoChain[C] | None = None


class FallbackChain[C, T]:
    """Priority-ordered action selection. First eligible candidate wins.

    Deterministic: same context always selects same action.
    Graceful degradation: default always exists.
    Supports ``|`` composition: ``chain_a | chain_b`` appends ``other``'s
    candidates after ``self``'s (priority order preserved).
    """

    __slots__ = ("_candidates", "_default")

    def __init__(self, candidates: list[Candidate[C, T]], default: T) -> None:
        self._candidates = list(candidates)
        self._default = default

    @property
    def candidates(self) -> list[Candidate[C, T]]:
        return list(self._candidates)

    def select(self, context: C) -> Selected[T]:
        """Select the highest-priority eligible action."""
        for c in self._candidates:
            if c.predicate(context):
                return Selected(action=c.action, selected_by=c.name)
        return Selected(action=self._default, selected_by="default")

    def __or__(self, other: FallbackChain[C, T]) -> FallbackChain[C, T]:
        """Append other's candidates after self's. Self's default wins."""
        return FallbackChain(self._candidates + other._candidates, self._default)


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
