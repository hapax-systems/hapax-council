"""Compositional governance primitives for all Hapax subsystems.

VetoChain: deny-wins constraint composition (order-independent).
FallbackChain: priority-ordered action selection.

Extracted from agents/hapax_daimonion/governance.py for cross-system use.
Phase 3 of capability parity (queue #019).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)


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
