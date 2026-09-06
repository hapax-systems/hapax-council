"""Revocation propagation via why-provenance.

When a consent contract is revoked, all data whose provenance includes
that contract must be purged. The RevocationPropagator orchestrates
cascading purge across all registered subsystems.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from agentgov.carrier import CarrierRegistry
from agentgov.consent import (
    ConsentRegistry,
    IdentityMigrationUnavailable,
    identity_operation,
    resolve_contract_id,
    resolve_principal_id,
)
from agentgov.labeled import Labeled


@dataclass(frozen=True)
class PurgeResult:
    """Result of purging a single subsystem."""

    subsystem: str
    items_purged: int
    details: str = ""
    failures: tuple[str, ...] = ()

    purge_complete: bool = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "purge_complete", not self.failures)


@dataclass(frozen=True)
class RevocationReport:
    """Complete report of a revocation cascade."""

    contract_id: str
    person_id: str
    contract_revoked: bool
    purge_results: tuple[PurgeResult, ...]

    retry_contract_ids: tuple[str, ...] = ()
    prior_purge_results: tuple[PurgeResult, ...] = ()

    purge_complete: bool = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "purge_complete",
            (
                self.contract_revoked
                and not self.retry_contract_ids
                and all(r.purge_complete for r in self.purge_results)
            ),
        )

    @property
    def total_purged(self) -> int:
        return sum(r.items_purged for r in self.prior_purge_results + self.purge_results)


PurgeHandler = Callable[[str], int | PurgeResult]


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

    def _purge(
        self,
        contract_ids: tuple[str, ...],
        subsystems: set[str] | None = None,
    ) -> tuple[PurgeResult, ...]:
        results: list[PurgeResult] = []
        for contract_id in contract_ids:
            for subsystem, handler in self._handlers:
                if subsystems is not None and subsystem not in subsystems:
                    continue
                try:
                    outcome = handler(contract_id)
                    if isinstance(outcome, PurgeResult):
                        results.append(replace(outcome, subsystem=subsystem))
                    elif type(outcome) is int and outcome >= 0:
                        if outcome:
                            results.append(PurgeResult(subsystem, outcome))
                    else:
                        results.append(PurgeResult(subsystem, 0, failures=("purge_invalid",)))
                except IdentityMigrationUnavailable as exc:
                    results.append(PurgeResult(subsystem, 0, failures=(exc.reason,)))
                except Exception:
                    results.append(PurgeResult(subsystem, 0, failures=("purge_failed",)))
        return tuple(results)

    def revoke(self, person_id: str) -> RevocationReport:
        """Revoke durably before purging; downstream failure never restores consent."""
        with identity_operation(self._consent_registry._identity_binding):
            person_id = resolve_principal_id(person_id) or person_id
            revoked_ids = tuple(
                dict.fromkeys(
                    resolve_contract_id(cid) or cid
                    for cid in self._consent_registry.purge_subject(person_id)
                )
            )
            results = self._purge(revoked_ids)
            return RevocationReport(
                contract_id=",".join(revoked_ids),
                person_id=person_id,
                contract_revoked=bool(revoked_ids),
                purge_results=results,
                retry_contract_ids=revoked_ids if any(r.failures for r in results) else (),
            )

    def retry_purge(self, report: RevocationReport) -> RevocationReport:
        """Retry from the retained report after reload; do not reactivate consent."""
        if not report.contract_revoked or not report.retry_contract_ids:
            return report
        with identity_operation(self._consent_registry._identity_binding):
            pending = {result.subsystem for result in report.purge_results if result.failures}
            registered = {name for name, _ in self._handlers}
            results = self._purge(report.retry_contract_ids, pending) + tuple(
                PurgeResult(name, 0, failures=("purge_handler_missing",))
                for name in sorted(pending - registered)
            )
            return replace(
                report,
                purge_results=results,
                prior_purge_results=report.prior_purge_results + report.purge_results,
                retry_contract_ids=(
                    report.retry_contract_ids if any(r.failures for r in results) else ()
                ),
            )


def check_provenance(data: Labeled[Any], active_contract_ids: frozenset[str]) -> bool:
    """Check if labeled data's provenance is still valid."""
    return data.evaluate_provenance(active_contract_ids)
