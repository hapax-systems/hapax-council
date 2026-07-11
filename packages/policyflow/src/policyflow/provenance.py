"""Provenance semirings: algebraic why-provenance tracking.

A provenance semiring tracks WHY data exists — which consent contracts
justify each datum. The algebra supports:
- tensor (and): data derived from combining two sources needs BOTH
- plus (or): data available from alternative sources needs EITHER
- Evaluation: given active contracts, compute whether data survives

Reference: Green et al., "Provenance Semirings" (PODS 2007).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class ProvenanceOp(enum.Enum):
    """Binary operations in the provenance semiring."""

    TENSOR = "tensor"
    PLUS = "plus"


@dataclass(frozen=True)
class ProvenanceExpr:
    """A provenance expression in the PosBool(X) semiring.

    Leaf: a single contract ID.
    Branch: binary operation (tensor or plus) over two sub-expressions.
    """

    contract_id: str | None = None
    op: ProvenanceOp | None = None
    left: ProvenanceExpr | None = None
    right: ProvenanceExpr | None = None
    _is_zero: bool = False
    _is_one: bool = False

    @staticmethod
    def leaf(contract_id: str) -> ProvenanceExpr:
        """A single contract as provenance."""
        return ProvenanceExpr(contract_id=contract_id)

    @staticmethod
    def zero() -> ProvenanceExpr:
        """Additive identity: no provenance (data doesn't exist)."""
        return ProvenanceExpr(_is_zero=True)

    @staticmethod
    def one() -> ProvenanceExpr:
        """Multiplicative identity: unconditional (public data)."""
        return ProvenanceExpr(_is_one=True)

    @staticmethod
    def from_contracts(contract_ids: frozenset[str]) -> ProvenanceExpr:
        """Build a tensor (all-required) expression from a set of contract IDs."""
        if not contract_ids:
            return ProvenanceExpr.one()
        ids = sorted(contract_ids)
        result = ProvenanceExpr.leaf(ids[0])
        for cid in ids[1:]:
            result = result.tensor(ProvenanceExpr.leaf(cid))
        return result

    def tensor(self, other: ProvenanceExpr) -> ProvenanceExpr:
        """Both required (conjunction)."""
        if self._is_one:
            return other
        if other._is_one:
            return self
        if self._is_zero or other._is_zero:
            return ProvenanceExpr.zero()
        return ProvenanceExpr(op=ProvenanceOp.TENSOR, left=self, right=other)

    def plus(self, other: ProvenanceExpr) -> ProvenanceExpr:
        """Either sufficient (disjunction)."""
        if self._is_zero:
            return other
        if other._is_zero:
            return self
        if self == other:
            return self
        return ProvenanceExpr(op=ProvenanceOp.PLUS, left=self, right=other)

    def evaluate(self, active_contracts: frozenset[str]) -> bool:
        """Evaluate provenance against active contracts."""
        if self._is_zero:
            return False
        if self._is_one:
            return True
        if self.contract_id is not None:
            return self.contract_id in active_contracts
        if self.op is ProvenanceOp.TENSOR:
            assert self.left is not None and self.right is not None
            return self.left.evaluate(active_contracts) and self.right.evaluate(active_contracts)
        if self.op is ProvenanceOp.PLUS:
            assert self.left is not None and self.right is not None
            return self.left.evaluate(active_contracts) or self.right.evaluate(active_contracts)
        return False

    def contract_ids(self) -> frozenset[str]:
        """Extract all contract IDs mentioned in this expression."""
        if self._is_zero or self._is_one:
            return frozenset()
        if self.contract_id is not None:
            return frozenset({self.contract_id})
        ids: set[str] = set()
        if self.left is not None:
            ids |= self.left.contract_ids()
        if self.right is not None:
            ids |= self.right.contract_ids()
        return frozenset(ids)

    def to_flat(self) -> frozenset[str]:
        """Downgrade to flat frozenset[str] for backwards compatibility."""
        return self.contract_ids()

    @property
    def is_trivial(self) -> bool:
        """True if this is Zero, One, or a single leaf."""
        return self._is_zero or self._is_one or self.contract_id is not None

    def __repr__(self) -> str:
        if self._is_zero:
            return "Zero"
        if self._is_one:
            return "One"
        if self.contract_id is not None:
            return self.contract_id
        if self.op is ProvenanceOp.TENSOR:
            return f"({self.left!r} ⊗ {self.right!r})"
        if self.op is ProvenanceOp.PLUS:
            return f"({self.left!r} ⊕ {self.right!r})"
        return "?"
