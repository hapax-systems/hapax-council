"""Revocation propagation via why-provenance.

When a consent contract is revoked, all data whose provenance includes
that contract must be purged. The RevocationPropagator orchestrates
cascading purge across all registered subsystems.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agentgov.carrier import CarrierRegistry
from agentgov.consent import ConsentRegistry
from agentgov.labeled import Labeled


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


PurgeHandler = Callable[[str], int]


class RevocationPropagator:
    """Orchestrates consent revocation across all data-holding subsystems."""

    __slots__ = ("_consent_registry", "_handlers")

    def __init__(self, consent_registry: ConsentRegistry) -> None:
        self._consent_registry = consent_registry
        self._handlers: list[tuple[str, PurgeHandler]] = []

    def register_carrier_registry(self, registry: CarrierRegistry) -> None:
        self._handlers.append(("carrier_registry", registry.purge_by_provenance))

    def register_handler(self, name: str, handler: PurgeHandler) -> None:
        self._handlers.append((name, handler))

    def revoke(self, person_id: str) -> RevocationReport:
        """Revoke all contracts for a person and cascade purge."""
        revoked_ids = self._consent_registry.purge_subject(person_id)

        if not revoked_ids:
            return RevocationReport(
                contract_id="",
                person_id=person_id,
                contract_revoked=False,
                purge_results=(),
            )

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
    """Check if labeled data's provenance is still valid."""
    return data.evaluate_provenance(active_contract_ids)
