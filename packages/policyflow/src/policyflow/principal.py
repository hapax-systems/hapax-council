"""Principal type: sovereign and bound actors in consent governance.

Principals are the actors in the consent system — humans (sovereign)
originate and revoke consent, software agents (bound) operate under
delegated authority only.

Key invariant: non-amplification. A bound principal's authority is
always a subset of its delegator's grant.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class PrincipalKind(enum.Enum):
    SOVEREIGN = "sovereign"
    BOUND = "bound"


@dataclass(frozen=True)
class Principal:
    """Immutable actor in the consent governance system.

    Sovereign principals (humans) can originate and revoke contracts.
    Bound principals (software) operate under delegated authority only.
    """

    id: str
    kind: PrincipalKind
    delegated_by: str | None = None
    authority: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.kind is PrincipalKind.SOVEREIGN and self.delegated_by is not None:
            raise ValueError("Sovereign principals cannot have a delegator")
        if self.kind is PrincipalKind.BOUND and self.delegated_by is None:
            raise ValueError("Bound principals must have a delegator")

    @property
    def is_sovereign(self) -> bool:
        return self.kind is PrincipalKind.SOVEREIGN

    def can_delegate(self, scope: frozenset[str]) -> bool:
        """Check if this principal can delegate the given scope."""
        if self.is_sovereign:
            return True
        return scope <= self.authority

    def delegate(self, child_id: str, scope: frozenset[str]) -> Principal:
        """Create a bound child principal with the given scope.

        Raises ValueError if scope exceeds this principal's authority
        (non-amplification invariant).
        """
        if not self.is_sovereign:
            excess = scope - self.authority
            if excess:
                raise ValueError(
                    f"Non-amplification violation: {sorted(excess)} "
                    f"not in delegator authority {sorted(self.authority)}"
                )
        return Principal(
            id=child_id,
            kind=PrincipalKind.BOUND,
            delegated_by=self.id,
            authority=scope,
        )
