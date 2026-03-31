"""Labeled[T]: LIO-style runtime wrapper for consent-tracked values.

Implements DD-21, DD-23, Theory §5.6. Labeled wraps any value with
its ConsentLabel and why-provenance (contract IDs that justify its
existence). Provides functor map that preserves label and provenance.

Functor laws: map(id) == id, map(f . g) == map(f) . map(g)

Provenance can be either flat (frozenset[str], backwards compat) or
structured (ProvenanceExpr, semiring algebra with tensor/plus).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .consent_label import ConsentLabel
from .provenance import ProvenanceExpr


@dataclass(frozen=True)
class Labeled[T]:
    """Immutable value tagged with consent label and provenance.

    Provenance tracks which contract IDs justify this value's existence.
    On revocation of contract c, any Labeled with c in provenance must
    be purged.

    Two provenance representations coexist:
    - provenance (frozenset[str]): flat set, backwards compatible
    - provenance_expr (ProvenanceExpr): semiring algebra (tensor/plus)

    When provenance_expr is set, it is authoritative. The flat provenance
    field is kept in sync for backwards compatibility.
    """

    value: T
    label: ConsentLabel
    provenance: frozenset[str] = frozenset()
    provenance_expr: ProvenanceExpr | None = None

    def with_expr(self, expr: ProvenanceExpr) -> Labeled[T]:
        """Return a copy with structured provenance expression.

        Syncs the flat provenance field from the expression.
        """
        return Labeled(
            value=self.value,
            label=self.label,
            provenance=expr.to_flat(),
            provenance_expr=expr,
        )

    def effective_expr(self) -> ProvenanceExpr:
        """Get the effective provenance expression.

        Returns provenance_expr if set, otherwise upgrades flat provenance.
        """
        if self.provenance_expr is not None:
            return self.provenance_expr
        return ProvenanceExpr.from_contracts(self.provenance)

    def evaluate_provenance(self, active_contracts: frozenset[str]) -> bool:
        """Evaluate provenance against active contracts using semiring algebra.

        This is the formal replacement for the flat subset check.
        """
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
        """Compute joined metadata for combining two labeled values.

        Returns the joined label and union of provenances. The caller
        decides how to combine the values themselves.
        """
        return (self.label.join(other.label), self.provenance | other.provenance)

    def join_with_expr[U](self, other: Labeled[U]) -> tuple[ConsentLabel, ProvenanceExpr]:
        """Compute joined metadata using semiring algebra.

        Tensor (⊗) of provenances: combined data needs ALL contracts.
        """
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
