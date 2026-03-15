"""Labeled[T]: LIO-style runtime wrapper for consent-tracked values.

Implements DD-21, DD-23, Theory §5.6. Labeled wraps any value with
its ConsentLabel and why-provenance (contract IDs that justify its
existence). Provides functor map that preserves label and provenance.

Functor laws: map(id) == id, map(f . g) == map(f) . map(g)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from shared.governance.consent_label import ConsentLabel


@dataclass(frozen=True)
class Labeled[T]:
    """Immutable value tagged with consent label and provenance.

    Provenance tracks which contract IDs justify this value's existence.
    On revocation of contract c, any Labeled with c in provenance must
    be purged.
    """

    value: T
    label: ConsentLabel
    provenance: frozenset[str] = frozenset()

    def map[U](self, f: Callable[[T], U]) -> Labeled[U]:
        """Functor map: apply f to value, preserving label and provenance."""
        return Labeled(value=f(self.value), label=self.label, provenance=self.provenance)

    def join_with[U](self, other: Labeled[U]) -> tuple[ConsentLabel, frozenset[str]]:
        """Compute joined metadata for combining two labeled values.

        Returns the joined label and union of provenances. The caller
        decides how to combine the values themselves.
        """
        return (self.label.join(other.label), self.provenance | other.provenance)

    def can_flow_to(self, target_label: ConsentLabel) -> bool:
        """Check if this labeled value may flow to a target context."""
        return self.label.can_flow_to(target_label)

    def relabel(self, new_label: ConsentLabel) -> Labeled[T]:
        """Relabel to a more restrictive label. Raises if flow is not permitted."""
        if not self.label.can_flow_to(new_label):
            raise ValueError("Cannot relabel: flow not permitted to target label")
        return Labeled(value=self.value, label=new_label, provenance=self.provenance)

    def unlabel(self) -> T:
        """Extract the raw value. Caller is responsible for label obligations."""
        return self.value
