"""ConsentLabel: DLM join-semilattice for information flow control.

Implements DD-1, DD-3, DD-15, Theory §5.3. A ConsentLabel is an
immutable set of policies (owner, readers) that tracks who may read
data. Labels combine via join (union) — combining data with different
consent requirements produces the most restrictive combination.

Algebraic structure: join-semilattice with bottom.
- Bottom: empty policies (public data, identity for join)
- Join: set union of policies (more policies = more restrictive)
- Partial order: can_flow_to is subset relation on policies
- No meet: declassification requires explicit action (DD-4)
"""

from __future__ import annotations

from dataclasses import dataclass

from .consent import ConsentContract


@dataclass(frozen=True)
class ConsentLabel:
    """Immutable information flow label for consent-governed data.

    Each policy is a (owner, readers) pair: the owner's data may only
    flow to the named readers. Multiple policies combine conjunctively.
    """

    policies: frozenset[tuple[str, frozenset[str]]]

    def join(self, other: ConsentLabel) -> ConsentLabel:
        """Least upper bound: union of policies (most restrictive combination)."""
        return ConsentLabel(self.policies | other.policies)

    def can_flow_to(self, target: ConsentLabel) -> bool:
        """Check if data with this label may flow to a target context.

        Data can flow to a target if the target's policies are a superset
        of (at least as restrictive as) this label's policies.
        """
        return self.policies <= target.policies

    @staticmethod
    def bottom() -> ConsentLabel:
        """Bottom element: no policies, public data. Identity for join."""
        return ConsentLabel(frozenset())

    @staticmethod
    def from_contract(contract: ConsentContract) -> ConsentLabel:
        """Bridge a ConsentContract into a ConsentLabel.

        Revoked contracts produce bottom label (safe default per DD-3):
        revoked consent means data must be purged, not relabeled with
        the old contract's permissions.
        """
        if not contract.active:
            return ConsentLabel.bottom()
        owner = contract.parties[1]  # subject is the data owner
        readers = frozenset(contract.parties)  # both parties can read
        return ConsentLabel(frozenset({(owner, readers)}))

    @staticmethod
    def from_contracts(contracts: list[ConsentContract]) -> ConsentLabel:
        """Join of all contract labels."""
        result = ConsentLabel.bottom()
        for contract in contracts:
            result = result.join(ConsentLabel.from_contract(contract))
        return result
