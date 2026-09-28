"""Revocation propagation via why-provenance.

When a consent contract is revoked, all data whose provenance includes
that contract must be purged. The RevocationPropagator orchestrates
cascading purge across all registered subsystems.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from copy import copy
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentgov.carrier import CarrierRegistry
from agentgov.consent import (
    ConsentContractLoadError,
    ConsentRegistry,
    IdentityMigrationUnavailable,
    SubjectPurgeIncomplete,
    identity_operation,
    resolve_contract_id,
    resolve_principal_id,
)
from agentgov.labeled import Labeled

log = logging.getLogger(__name__)


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
    retry_revocation_ids: tuple[str, ...] = ()
    prior_purge_results: tuple[PurgeResult, ...] = ()
    audit_failures: tuple[str, ...] = ()

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

    def refresh_contracts(self) -> None:
        """Refresh durable grants at the caller's serialized mutation boundary."""
        registry = self._consent_registry
        directory = registry._contracts_dir
        if directory is None:
            return
        # A failed load must neither discard known grants nor permit a purge
        # against a silently truncated contract set.
        staged = copy(registry)
        staged._contracts = registry._contracts.copy()
        staged._contract_paths = registry._contract_paths.copy()
        try:
            list(directory.iterdir())  # glob alone can hide an unreadable directory.
            staged.load(directory, strict=True)
            if staged._fail_closed:
                raise ConsentContractLoadError("consent_refresh_unavailable")
        except Exception:
            log.warning("consent_refresh_unavailable: inspect contract storage before retrying")
            raise ConsentContractLoadError("consent_refresh_unavailable") from None
        registry._contracts = staged._contracts
        registry._contract_paths = staged._contract_paths
        registry._loaded_at = staged._loaded_at
        registry._fail_closed = staged._fail_closed

    def record_purge_pending(self, report: RevocationReport, audit_path: Path) -> None:
        """Append residue to the installation's existing purge audit, not a retry journal."""
        self._record_purge_state(
            "purge_pending", report.person_id, report.retry_contract_ids, audit_path
        )

    def record_purge_complete(
        self, person_id: str, contract_ids: tuple[str, ...], audit_path: Path
    ) -> None:
        """Resolve only the outstanding contracts that this retry actually completed."""
        self._record_purge_state("purge_complete", person_id, contract_ids, audit_path)

    def _record_purge_state(
        self, event: str, person_id: str, contract_ids: tuple[str, ...], audit_path: Path
    ) -> None:
        with identity_operation(self._consent_registry._identity_binding):
            entry = {
                "ts": datetime.now(UTC).isoformat(),
                "event": event,
                "person_id": resolve_principal_id(person_id),
                "contract_ids": sorted({resolve_contract_id(cid) for cid in contract_ids}),
            }
            try:
                audit_path.parent.mkdir(parents=True, exist_ok=True)
                with audit_path.open("a", encoding="utf-8") as audit:
                    audit.write(json.dumps(entry) + "\n")
                    audit.flush()
                    os.fsync(audit.fileno())
            except OSError:
                log.warning("purge_audit_unwritten: retain current-process retry report")
                raise RuntimeError("purge_audit_unwritten") from None

    def pending_purges(self, audit_path: Path) -> dict[str, tuple[str, ...]]:
        """Read outstanding audit residue without reconstituting or running a retry."""
        with identity_operation(self._consent_registry._identity_binding):
            pending: dict[str, set[str]] = {}
            try:
                with audit_path.open(encoding="utf-8") as audit:
                    for line in audit:
                        entry = json.loads(line)
                        if entry.get("event") not in {"purge_pending", "purge_complete"}:
                            continue  # Existing archive purge audit entries remain untouched.
                        person_id = resolve_principal_id(entry["person_id"])
                        contract_ids = {resolve_contract_id(cid) for cid in entry["contract_ids"]}
                        remaining = pending.setdefault(person_id, set())
                        if entry["event"] == "purge_pending":
                            remaining.update(contract_ids)
                        else:
                            remaining.difference_update(contract_ids)
            except FileNotFoundError:
                return {}
            return {pid: tuple(sorted(ids)) for pid, ids in pending.items() if ids}

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
                    log.warning("purge_handler_failed: %s", exc.reason)
                    results.append(PurgeResult(subsystem, 0, failures=(exc.reason,)))
                except Exception:
                    log.warning("purge_handler_failed: purge_failed")
                    results.append(PurgeResult(subsystem, 0, failures=("purge_failed",)))
        return tuple(results)

    def _revoke_subject(self, person_id: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        try:
            revoked = self._consent_registry.purge_subject(person_id)
        except SubjectPurgeIncomplete as exc:
            return exc.revoked_ids, exc.pending_ids
        return tuple(dict.fromkeys(resolve_contract_id(cid) for cid in revoked)), ()

    def revoke(self, person_id: str) -> RevocationReport:
        """Revoke durably before purging; downstream failure never restores consent."""
        with identity_operation(self._consent_registry._identity_binding):
            person_id = resolve_principal_id(person_id) or person_id
            revoked_ids, outstanding = self._revoke_subject(person_id)
            results = self._purge(revoked_ids)
            purge_pending = revoked_ids if any(r.failures for r in results) else ()
            if outstanding:
                results += (
                    PurgeResult(
                        "contract_persistence", 0, failures=("contract_persistence_failed",)
                    ),
                )
            return RevocationReport(
                contract_id=",".join(revoked_ids),
                person_id=person_id,
                contract_revoked=bool(revoked_ids),
                purge_results=results,
                retry_contract_ids=tuple(dict.fromkeys(purge_pending + outstanding)),
                retry_revocation_ids=outstanding,
            )

    def retry_purge(self, report: RevocationReport) -> RevocationReport:
        """Retry from the retained report after reload; do not reactivate consent."""
        if not report.retry_contract_ids:
            return report
        with identity_operation(self._consent_registry._identity_binding):
            persistence_ids = set(report.retry_revocation_ids)
            for cid in report.retry_contract_ids:
                contract = self._consent_registry.get(cid)
                if contract is not None and contract.active:
                    persistence_ids.add(cid)
            revoked, outstanding = (
                self._revoke_subject(report.person_id) if persistence_ids else ((), ())
            )
            # A pending file may already have disappeared on reload. Its purge
            # obligation remains even when there is no active contract to move.
            full_purge_ids = tuple(sorted((set(revoked) | persistence_ids) - set(outstanding)))
            pending = {
                result.subsystem
                for result in report.purge_results
                if result.failures and result.subsystem != "contract_persistence"
            }
            purge_ids = tuple(
                cid for cid in report.retry_contract_ids if cid not in persistence_ids
            )
            registered = {name for name, _ in self._handlers}
            results = self._purge(purge_ids, pending) + tuple(
                PurgeResult(name, 0, failures=("purge_handler_missing",))
                for name in sorted(pending - registered)
            )
            remaining = purge_ids if any(r.failures for r in results) else ()
            full_results = self._purge(full_purge_ids)
            if any(r.failures for r in full_results):
                remaining += full_purge_ids
            results += full_results
            if outstanding:
                results += (
                    PurgeResult(
                        "contract_persistence", 0, failures=("contract_persistence_failed",)
                    ),
                )
            remaining += outstanding
            contract_ids = list(filter(None, report.contract_id.split(","))) + list(full_purge_ids)
            return replace(
                report,
                contract_id=",".join(dict.fromkeys(contract_ids)),
                contract_revoked=bool(contract_ids),
                purge_results=results,
                prior_purge_results=report.prior_purge_results + report.purge_results,
                retry_contract_ids=tuple(dict.fromkeys(remaining)),
                retry_revocation_ids=outstanding,
            )


def check_provenance(data: Labeled[Any], active_contract_ids: frozenset[str]) -> bool:
    """Check if labeled data's provenance is still valid."""
    return data.evaluate_provenance(active_contract_ids)
