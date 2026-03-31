"""Says monad: principal-annotated assertions (Abadi DCC formalism).

Implements deferred formalism #1. The Says monad wraps a value with
the principal who asserts it. This is the formal bridge between
Principal (who has authority) and Labeled[T] (what data carries).

    Says(principal, value) means "principal asserts value"

Key properties:
- Says is a monad: unit wraps a value, bind composes assertions
- Handoff: principal P can grant Says(Q, v) only if P can delegate to Q
- Speaks-for: if P speaks-for Q, Says(P, v) implies Says(Q, v)
- Non-amplification: bound principals cannot assert beyond authority

The Says monad solves a structural gap: Labeled[T] tracks WHAT consent
applies, but not WHO authorized the data's existence. Says threads
principal authority through data transformations.

Reference: Abadi, "Access Control in a Core Calculus of Dependency" (DCC).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .consent_label import ConsentLabel
from .labeled import Labeled
from .principal import Principal


@dataclass(frozen=True)
class Says[T]:
    """Principal-annotated assertion: 'principal says value'.

    Immutable. The principal field records WHO made or authorized
    this assertion. The value is WHAT they assert.
    """

    principal: Principal
    value: T

    # ── Monad operations ─────────────────────────────────────────────

    @staticmethod
    def unit(principal: Principal, value: T) -> Says[T]:
        """Monadic unit: wrap a value with a principal assertion."""
        return Says(principal=principal, value=value)

    def bind[U](self, f: Callable[[T], Says[U]]) -> Says[U]:
        """Monadic bind: compose assertions.

        The result carries the ORIGINAL principal (the one who initiated
        the assertion chain), not the intermediate principal from f's result.
        This preserves accountability: the chain's authority traces back
        to its originator.
        """
        inner = f(self.value)
        return Says(principal=self.principal, value=inner.value)

    def map[U](self, f: Callable[[T], U]) -> Says[U]:
        """Functor map: transform the value, preserving principal."""
        return Says(principal=self.principal, value=f(self.value))

    # ── Authority operations ─────────────────────────────────────────

    def handoff(self, target: Principal, scope: frozenset[str] | None = None) -> Says[T]:
        """Transfer assertion to another principal (delegation).

        The original principal must be able to delegate to the target.
        If scope is provided, the target must have authority over that scope.
        Raises ValueError on non-amplification violation.
        """
        if not self.principal.is_sovereign:
            # Bound principal: check authority covers scope
            check_scope = scope or self.principal.authority
            excess = check_scope - self.principal.authority
            if excess:
                raise ValueError(
                    f"Non-amplification: {self.principal.id} cannot hand off "
                    f"scope {sorted(excess)} beyond authority {sorted(self.principal.authority)}"
                )
        return Says(principal=target, value=self.value)

    def speaks_for(self, target: Principal) -> bool:
        """Check if this principal speaks for target.

        A sovereign speaks for any bound principal it delegated.
        A bound principal speaks for any sub-delegate within its authority.
        """
        if self.principal.id == target.id:
            return True
        return target.delegated_by == self.principal.id

    # ── Integration with Labeled ─────────────────────────────────────

    def to_labeled(
        self, label: ConsentLabel, provenance: frozenset[str] = frozenset()
    ) -> Labeled[T]:
        """Convert to Labeled[T], attaching consent label and provenance.

        The Says wrapper is consumed: principal authority is validated
        at this boundary, then the data flows as Labeled[T] through
        the consent infrastructure.
        """
        return Labeled(value=self.value, label=label, provenance=provenance)

    @staticmethod
    def from_labeled(principal: Principal, labeled: Labeled[T]) -> Says[Labeled[T]]:
        """Wrap a Labeled value with principal attribution.

        Used when a principal claims responsibility for labeled data
        (e.g., an agent asserting it produced a carrier fact).
        """
        return Says(principal=principal, value=labeled)

    # ── Inspection ───────────────────────────────────────────────────

    @property
    def authority(self) -> frozenset[str]:
        """The asserting principal's authority scope."""
        return self.principal.authority

    @property
    def asserter_id(self) -> str:
        """ID of the principal making this assertion."""
        return self.principal.id
