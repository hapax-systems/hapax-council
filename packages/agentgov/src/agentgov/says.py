"""Says monad: principal-annotated assertions (Abadi DCC formalism).

The Says monad wraps a value with the principal who asserts it. This is
the formal bridge between Principal (who has authority) and Labeled[T]
(what data carries).

    Says(principal, value) means "principal asserts value"

Reference: Abadi, "Access Control in a Core Calculus of Dependency" (DCC).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from agentgov.consent_label import ConsentLabel
from agentgov.labeled import Labeled
from agentgov.principal import Principal


@dataclass(frozen=True)
class Says[T]:
    """Principal-annotated assertion: 'principal says value'."""

    principal: Principal
    value: T

    @staticmethod
    def unit(principal: Principal, value: T) -> Says[T]:
        """Monadic unit: wrap a value with a principal assertion."""
        return Says(principal=principal, value=value)

    def bind[U](self, f: Callable[[T], Says[U]]) -> Says[U]:
        """Monadic bind: compose assertions.

        The result carries the ORIGINAL principal, not the intermediate
        principal from f's result. This preserves accountability.
        """
        inner = f(self.value)
        return Says(principal=self.principal, value=inner.value)

    def map[U](self, f: Callable[[T], U]) -> Says[U]:
        """Functor map: transform the value, preserving principal."""
        return Says(principal=self.principal, value=f(self.value))

    def handoff(self, target: Principal, scope: frozenset[str] | None = None) -> Says[T]:
        """Transfer assertion to another principal (delegation).

        Raises ValueError on non-amplification violation.
        """
        if not self.principal.is_sovereign:
            check_scope = scope or self.principal.authority
            excess = check_scope - self.principal.authority
            if excess:
                raise ValueError(
                    f"Non-amplification: {self.principal.id} cannot hand off "
                    f"scope {sorted(excess)} beyond authority {sorted(self.principal.authority)}"
                )
        return Says(principal=target, value=self.value)

    def speaks_for(self, target: Principal) -> bool:
        """Check if this principal speaks for target."""
        if self.principal.id == target.id:
            return True
        return target.delegated_by == self.principal.id

    def to_labeled(
        self, label: ConsentLabel, provenance: frozenset[str] = frozenset()
    ) -> Labeled[T]:
        """Convert to Labeled[T], attaching consent label and provenance."""
        return Labeled(value=self.value, label=label, provenance=provenance)

    @staticmethod
    def from_labeled(principal: Principal, labeled: Labeled[T]) -> Says[Labeled[T]]:
        """Wrap a Labeled value with principal attribution."""
        return Says(principal=principal, value=labeled)

    @property
    def authority(self) -> frozenset[str]:
        return self.principal.authority

    @property
    def asserter_id(self) -> str:
        return self.principal.id
