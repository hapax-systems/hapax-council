"""Vendored governance primitives for effect graph.

Copied from shared/governance/primitives.py — pure data structures
with no external dependencies.
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
    """Result of gating a value through a VetoChain."""

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
    """Order-independent deny-wins constraint composition."""

    __slots__ = ("_vetoes",)

    def __init__(self, vetoes: list[Veto[C]] | None = None) -> None:
        self._vetoes: list[Veto[C]] = list(vetoes) if vetoes else []

    @property
    def vetoes(self) -> list[Veto[C]]:
        return list(self._vetoes)

    def add(self, veto: Veto[C]) -> None:
        self._vetoes.append(veto)

    def evaluate(self, context: C) -> VetoResult:
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
        veto_result = self.evaluate(context)
        return GatedResult(
            veto_result=veto_result,
            value=value if veto_result.allowed else None,
        )

    def __or__(self, other: VetoChain[C]) -> VetoChain[C]:
        return VetoChain(self._vetoes + other._vetoes)


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
    veto_chain: VetoChain[C] | None = None


class FallbackChain[C, T]:
    """Priority-ordered action selection. First eligible candidate wins."""

    __slots__ = ("_candidates", "_default")

    def __init__(self, candidates: list[Candidate[C, T]], default: T) -> None:
        self._candidates = list(candidates)
        self._default = default

    @property
    def candidates(self) -> list[Candidate[C, T]]:
        return list(self._candidates)

    def select(self, context: C) -> Selected[T]:
        for c in self._candidates:
            if c.predicate(context):
                return Selected(action=c.action, selected_by=c.name)
        return Selected(action=self._default, selected_by="default")

    def __or__(self, other: FallbackChain[C, T]) -> FallbackChain[C, T]:
        return FallbackChain(self._candidates + other._candidates, self._default)
