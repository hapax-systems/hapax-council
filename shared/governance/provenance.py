"""Provenance semirings: algebraic why-provenance tracking.

Implements deferred formalism #2. Upgrades the frozenset[str] provenance
in Labeled[T] to a proper semiring that supports algebraic composition.

A provenance semiring tracks WHY data exists — which consent contracts
justify each datum. The algebra supports:
- ⊗ (tensor/and): data derived from combining two sources needs BOTH
- ⊕ (plus/or): data available from alternative sources needs EITHER
- Evaluation: given a set of revoked contracts, compute whether data survives

At current scale (~5 contracts), PosBool(X) semiring is sufficient:
provenance expressions are boolean combinations of contract IDs.
Evaluation = substitute true/false for each contract and simplify.

Reference: Green et al., "Provenance Semirings" (PODS 2007).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class ProvenanceOp(enum.Enum):
    """Binary operations in the provenance semiring."""

    TENSOR = "tensor"  # ⊗ — both required (conjunction)
    PLUS = "plus"  # ⊕ — either sufficient (disjunction)


@dataclass(frozen=True)
class ProvenanceExpr:
    """A provenance expression in the PosBool(X) semiring.

    Leaf: a single contract ID.
    Branch: binary operation (tensor or plus) over two sub-expressions.

    The semiring laws:
    - ⊕ is commutative, associative, idempotent, identity = Zero
    - ⊗ is commutative, associative, identity = One
    - ⊗ distributes over ⊕
    - Zero annihilates ⊗: Zero ⊗ x = Zero

    At current scale, we don't normalize expressions — we evaluate directly.
    """

    # Discriminated union via optional fields (frozen dataclass)
    contract_id: str | None = None  # Leaf
    op: ProvenanceOp | None = None  # Branch
    left: ProvenanceExpr | None = None
    right: ProvenanceExpr | None = None
    _is_zero: bool = False  # additive identity (no provenance)
    _is_one: bool = False  # multiplicative identity (unconditional)

    # ── Constructors ─────────────────────────────────────────────────

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
        """Build a tensor (all-required) expression from a set of contract IDs.

        This is the upgrade path from frozenset[str] provenance:
        frozenset({a, b, c}) becomes a ⊗ b ⊗ c (all required).
        """
        if not contract_ids:
            return ProvenanceExpr.one()
        ids = sorted(contract_ids)  # deterministic order
        result = ProvenanceExpr.leaf(ids[0])
        for cid in ids[1:]:
            result = result.tensor(ProvenanceExpr.leaf(cid))
        return result

    # ── Semiring operations ──────────────────────────────────────────

    def tensor(self, other: ProvenanceExpr) -> ProvenanceExpr:
        """⊗ (and): data needs BOTH provenances to survive.

        Used when combining data from two consent-governed sources.
        """
        # Identity: One ⊗ x = x
        if self._is_one:
            return other
        if other._is_one:
            return self
        # Annihilation: Zero ⊗ x = Zero
        if self._is_zero or other._is_zero:
            return ProvenanceExpr.zero()
        return ProvenanceExpr(op=ProvenanceOp.TENSOR, left=self, right=other)

    def plus(self, other: ProvenanceExpr) -> ProvenanceExpr:
        """⊕ (or): data survives if EITHER provenance holds.

        Used when data is available from alternative sources.
        """
        # Identity: Zero ⊕ x = x
        if self._is_zero:
            return other
        if other._is_zero:
            return self
        # Idempotence: x ⊕ x = x
        if self == other:
            return self
        return ProvenanceExpr(op=ProvenanceOp.PLUS, left=self, right=other)

    # ── Evaluation ───────────────────────────────────────────────────

    def evaluate(self, active_contracts: frozenset[str]) -> bool:
        """Evaluate provenance against active contracts.

        Substitutes True for active contracts, False for revoked,
        then simplifies the boolean expression.

        Returns True if the data's provenance is satisfied (data survives).
        """
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
        return False  # unreachable

    # ── Introspection ────────────────────────────────────────────────

    def contract_ids(self) -> frozenset[str]:
        """Extract all contract IDs mentioned in this expression.

        Useful for backwards compatibility with frozenset[str] provenance.
        """
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
        """Downgrade to flat frozenset[str] for backwards compatibility.

        Loses structural information (tensor vs plus) but preserves
        the set of contract IDs. Use for interop with legacy code.
        """
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
