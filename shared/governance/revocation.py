"""Revocation propagation via why-provenance (DD-8, DD-23).

When a consent contract is revoked, all data whose provenance includes
that contract must be purged. This module connects ConsentRegistry
(contract lifecycle) with CarrierRegistry (carrier facts) and any
additional systems holding Labeled[T] data.

At current scale (~5 contracts), PosBool(X) why-provenance degenerates
to simple set membership: if contract_id ∈ provenance, purge the datum.
The RevocationPropagator orchestrates cascading purge across all
registered subsystems.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from shared.governance.carrier import CarrierRegistry
from shared.governance.consent import ConsentRegistry
from shared.governance.labeled import Labeled


@dataclass(frozen=True)
class PurgeResult:
    """Result of purging a single subsystem."""

    subsystem: str
    items_purged: int
    details: str = ""


@dataclass(frozen=True)
class RevocationReport:
    """Complete report of a revocation cascade."""

    contract_id: str
    person_id: str
    contract_revoked: bool
    purge_results: tuple[PurgeResult, ...]

    @property
    def total_purged(self) -> int:
        return sum(r.items_purged for r in self.purge_results)


# Type for pluggable purge handlers: (contract_id) -> items_purged
PurgeHandler = Callable[[str], int]


class RevocationPropagator:
    """Orchestrates consent revocation across all data-holding subsystems.

    Subsystems register purge handlers. On revocation, the propagator:
    1. Revokes the contract in ConsentRegistry
    2. Calls each registered handler with the contract ID
    3. Returns a complete RevocationReport

    This is the DD-8 cascade: provenance annotation enables targeted purge
    without scanning all data. Each subsystem knows how to purge its own
    data by provenance (e.g., CarrierRegistry.purge_by_provenance).
    """

    __slots__ = ("_consent_registry", "_handlers")

    def __init__(self, consent_registry: ConsentRegistry) -> None:
        self._consent_registry = consent_registry
        self._handlers: list[tuple[str, PurgeHandler]] = []

    def register_carrier_registry(self, registry: CarrierRegistry) -> None:
        """Register a CarrierRegistry for provenance-based purging."""
        self._handlers.append(("carrier_registry", registry.purge_by_provenance))

    def register_handler(self, name: str, handler: PurgeHandler) -> None:
        """Register a custom purge handler for a subsystem."""
        self._handlers.append((name, handler))

    def revoke(self, person_id: str) -> RevocationReport:
        """Revoke all contracts for a person and cascade purge.

        Returns a RevocationReport detailing what was revoked and purged.
        """
        # Step 1: Revoke contracts
        revoked_ids = self._consent_registry.purge_subject(person_id)

        if not revoked_ids:
            return RevocationReport(
                contract_id="",
                person_id=person_id,
                contract_revoked=False,
                purge_results=(),
            )

        # Step 2: Cascade purge for each revoked contract
        all_results: list[PurgeResult] = []
        for contract_id in revoked_ids:
            for subsystem_name, handler in self._handlers:
                purged = handler(contract_id)
                if purged > 0:
                    all_results.append(
                        PurgeResult(
                            subsystem=subsystem_name,
                            items_purged=purged,
                            details=f"contract={contract_id}",
                        )
                    )

        return RevocationReport(
            contract_id=",".join(revoked_ids),
            person_id=person_id,
            contract_revoked=True,
            purge_results=tuple(all_results),
        )


def check_provenance(data: Labeled[Any], active_contract_ids: frozenset[str]) -> bool:
    """Check if labeled data's provenance is still valid.

    Uses semiring evaluation when structured provenance is available,
    falls back to flat subset check for backwards compatibility.

    Returns True if the data's provenance is satisfied given active contracts.
    Returns True if provenance is empty (public data, no contract dependency).
    Returns False if any required contract has been revoked.

    This is the DD-8 evaluation: PosBool(X) semiring with revoked contracts
    evaluated to false.
    """
    # Use semiring evaluation (handles both structured and flat provenance)
    return data.evaluate_provenance(active_contract_ids)
