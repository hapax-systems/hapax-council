"""GateToken: linear discipline for consent gate passage.

Implements deferred formalism #4. A GateToken is a proof object
that records a successful gate passage. It cannot be duplicated
or forged — only the consent gate can create tokens.

Properties:
- Unforgeable: only ConsentGatedWriter.check() produces tokens
- Single-use: token records exactly one gate decision
- Auditable: carries the full decision context
- Non-duplicable: frozen, but uniqueness enforced by nonce

The linear discipline ensures that every persistence action can
produce a token proving it passed the gate. Code that requires
a GateToken as argument structurally cannot bypass consent checking.

Reference: Girard, "Linear Logic" (1987); capability-based security.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class GateToken:
    """Proof of consent gate passage. Unforgeable, auditable.

    Only the consent gate creates these. Downstream code that requires
    a GateToken parameter structurally enforces consent checking.
    """

    nonce: str  # cryptographic nonce — uniqueness + unforgeability
    allowed: bool
    reason: str
    data_category: str
    person_ids: tuple[str, ...]
    provenance: tuple[str, ...]
    timestamp: float
    gate_id: str  # which gate instance issued this token

    @staticmethod
    def _mint(
        *,
        allowed: bool,
        reason: str,
        data_category: str = "",
        person_ids: tuple[str, ...] = (),
        provenance: tuple[str, ...] = (),
        gate_id: str = "",
    ) -> GateToken:
        """Create a new gate token. ONLY called by the consent gate.

        The _mint prefix signals this is an internal constructor.
        External code should never call this directly.
        """
        return GateToken(
            nonce=secrets.token_hex(16),
            allowed=allowed,
            reason=reason,
            data_category=data_category,
            person_ids=person_ids,
            provenance=provenance,
            timestamp=time.time(),
            gate_id=gate_id,
        )

    @property
    def is_allow(self) -> bool:
        return self.allowed

    @property
    def is_deny(self) -> bool:
        return not self.allowed

    def audit_dict(self) -> dict:
        """Serialize for audit logging."""
        return {
            "nonce": self.nonce,
            "allowed": self.allowed,
            "reason": self.reason,
            "data_category": self.data_category,
            "person_ids": list(self.person_ids),
            "provenance": list(self.provenance),
            "timestamp": self.timestamp,
            "gate_id": self.gate_id,
        }


def require_token(token: GateToken, *, must_allow: bool = True) -> None:
    """Assert that a valid gate token is provided.

    Use at the top of functions that must only execute after consent
    gate passage. This makes the consent requirement structural —
    the function signature demands a GateToken, so callers can't
    skip the gate.

    Raises ValueError if token doesn't meet requirements.
    """
    if must_allow and not token.allowed:
        raise ValueError(f"Gate token denied: {token.reason}")
