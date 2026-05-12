"""Labeled[T]: LIO-style runtime wrapper for consent-tracked values.

Labeled wraps any value with its ConsentLabel and why-provenance
(contract IDs that justify its existence). Provides functor map
that preserves label and provenance.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from agentgov.consent_label import ConsentLabel
from agentgov.provenance import ProvenanceExpr


@dataclass(frozen=True)
class Labeled[T]:
    """Immutable value tagged with consent label and provenance."""

    value: T
    label: ConsentLabel
    provenance: frozenset[str] = frozenset()
    provenance_expr: ProvenanceExpr | None = None

    def with_expr(self, expr: ProvenanceExpr) -> Labeled[T]:
        """Return a copy with structured provenance expression."""
        return Labeled(
            value=self.value,
            label=self.label,
            provenance=expr.to_flat(),
            provenance_expr=expr,
        )

    def effective_expr(self) -> ProvenanceExpr:
        """Get the effective provenance expression."""
        if self.provenance_expr is not None:
            return self.provenance_expr
        return ProvenanceExpr.from_contracts(self.provenance)

    def evaluate_provenance(self, active_contracts: frozenset[str]) -> bool:
        """Evaluate provenance against active contracts using semiring algebra."""
        return self.effective_expr().evaluate(active_contracts)

    def map[U](self, f: Callable[[T], U]) -> Labeled[U]:
        """Functor map: apply f to value, preserving label and provenance."""
        return Labeled(
            value=f(self.value),
            label=self.label,
            provenance=self.provenance,
            provenance_expr=self.provenance_expr,
        )

    def join_with[U](self, other: Labeled[U]) -> tuple[ConsentLabel, frozenset[str]]:
        """Compute joined metadata for combining two labeled values."""
        return (self.label.join(other.label), self.provenance | other.provenance)

    def join_with_expr[U](self, other: Labeled[U]) -> tuple[ConsentLabel, ProvenanceExpr]:
        """Compute joined metadata using semiring algebra."""
        joined_label = self.label.join(other.label)
        joined_prov = self.effective_expr().tensor(other.effective_expr())
        return (joined_label, joined_prov)

    def can_flow_to(self, target_label: ConsentLabel) -> bool:
        """Check if this labeled value may flow to a target context."""
        return self.label.can_flow_to(target_label)

    def relabel(self, new_label: ConsentLabel) -> Labeled[T]:
        """Relabel to a more restrictive label. Raises if flow is not permitted."""
        if not self.label.can_flow_to(new_label):
            raise ValueError("Cannot relabel: flow not permitted to target label")
        return Labeled(
            value=self.value,
            label=new_label,
            provenance=self.provenance,
            provenance_expr=self.provenance_expr,
        )

    def unlabel(self) -> T:
        """Extract the raw value. Caller is responsible for label obligations."""
        return self.value
