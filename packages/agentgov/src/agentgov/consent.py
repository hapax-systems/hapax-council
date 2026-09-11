"""Consent contract management for information flow governance.

Provides contract loading, validation, and enforcement at data ingestion
boundaries. Any data pathway handling person data must call
contract_check() before persisting state.
"""

from __future__ import annotations

import logging
import os
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import datetime
from functools import wraps
from importlib import import_module
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)


class IdentityMigrationUnavailable(RuntimeError):
    """Identity resolution refused; only a public reason token is exposed."""

    def __init__(
        self, reason: str, *, cause_class: str | None = None, missing_module: str | None = None
    ) -> None:
        remedies = {
            "identity_unconfigured": "configure_identity_binding",
            "compat_missing": "restore_compat_custody",
            "compat_unreadable": "restore_compat_custody",
            "compat_malformed": "repair_compat_document",
            "compat_conflict": "reconcile_compat_conflict",
            "compat_incomplete": "complete_compat_inventory",
        }
        self.reason = reason if reason in remedies else "compat_unreadable"
        self.cause_class = (
            cause_class
            if isinstance(cause_class, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", cause_class)
            else None
        )
        self.remedy = remedies[self.reason]
        module = (
            missing_module
            if isinstance(missing_module, str) and re.fullmatch(r"[A-Za-z_][\w.]*", missing_module)
            else "unavailable"
        )
        log.warning(
            "%s: cause_class=%s missing_module=%s remedy=%s",
            self.reason,
            self.cause_class or "unavailable",
            module,
            self.remedy,
        )
        super().__init__(self.reason)


def custody_read_failure(exc: Exception) -> IdentityMigrationUnavailable:
    """Expose cause types and import names, never exception text or paths."""
    module = getattr(exc, "name", None) if isinstance(exc, ImportError) else None
    return IdentityMigrationUnavailable(
        "compat_unreadable", cause_class=type(exc).__name__, missing_module=module
    )


@dataclass(frozen=True)
class IdentityMigrationBinding:
    """Explicit installation selection; required providers supply snapshots."""

    mode: str
    provider: str | None = None


_configured_binding: IdentityMigrationBinding | None = None
_identity_snapshot: ContextVar[tuple[IdentityMigrationBinding, Any] | None] = ContextVar(
    "identity_snapshot", default=None
)


def configure_identity_migration(mode: str, provider: str | None = None) -> None:
    """Select the installation binding at startup instead of using environment configuration."""
    global _configured_binding
    _configured_binding = IdentityMigrationBinding(mode, provider)


def _installation_binding() -> IdentityMigrationBinding:
    return _configured_binding or IdentityMigrationBinding(
        os.environ.get("AGENTGOV_IDENTITY_MIGRATION", ""),
        os.environ.get("AGENTGOV_IDENTITY_PROVIDER"),
    )


@contextmanager
def identity_operation(binding: IdentityMigrationBinding | None = None):
    """Share one validated snapshot across nested calls; discard it on exit.

    A provider exports load_identity_snapshot(); the returned object implements
    resolve_principal_id() and resolve_contract_id(). No provider is imported
    for an explicitly selected non-migrating installation.
    """
    active = _identity_snapshot.get()
    if active is not None and (binding is None or active[0] == binding):
        yield active[1]
        return
    selected = binding or _installation_binding()
    if selected.mode == "none":
        snapshot = None
    elif selected.mode == "required" and selected.provider:
        try:
            provider = import_module(selected.provider)
        except Exception as exc:
            raise IdentityMigrationUnavailable(
                "identity_unconfigured", cause_class=type(exc).__name__
            ) from None
        try:
            snapshot = provider.load_identity_snapshot()
            if not all(
                callable(getattr(snapshot, name, None))
                for name in ("resolve_principal_id", "resolve_contract_id")
            ):
                raise IdentityMigrationUnavailable("compat_malformed")
        except IdentityMigrationUnavailable as exc:
            raise IdentityMigrationUnavailable(exc.reason, cause_class=exc.cause_class) from None
        except Exception as exc:
            raise custody_read_failure(exc) from None
    else:
        raise IdentityMigrationUnavailable("identity_unconfigured")
    token = _identity_snapshot.set((selected, snapshot))
    try:
        yield snapshot
    finally:
        _identity_snapshot.reset(token)


def _registry_operation(function):
    @wraps(function)
    def wrapped(self, *args, **kwargs):
        with identity_operation(self._identity_binding):
            return function(self, *args, **kwargs)

    return wrapped


def _resolve_identifier(candidate: str, kind: str) -> str:
    with identity_operation() as snapshot:
        if snapshot is None:
            return candidate
        try:
            result = getattr(snapshot, f"resolve_{kind}_id")(candidate)
            if result is not None and not isinstance(result, str):
                raise IdentityMigrationUnavailable("compat_malformed")
            return candidate if result is None else result
        except IdentityMigrationUnavailable as exc:
            raise IdentityMigrationUnavailable(exc.reason, cause_class=exc.cause_class) from None
        except Exception as exc:
            raise custody_read_failure(exc) from None


def resolve_principal_id(candidate: str) -> str:
    """Resolve through the explicitly selected installation binding."""
    return _resolve_identifier(candidate, "principal")


def resolve_contract_id(candidate: str) -> str:
    """Resolve through the explicitly selected installation binding."""
    return _resolve_identifier(candidate, "contract")


class ConsentContractLoadError(Exception):
    """Raised when a contract YAML file fails to parse in strict mode."""


class SubjectPurgeIncomplete(RuntimeError):
    """Durable revocations and remaining obligations after a persistence refusal."""

    def __init__(self, revoked_ids: tuple[str, ...], pending_ids: tuple[str, ...]) -> None:
        self.revoked_ids = revoked_ids
        self.pending_ids = pending_ids
        super().__init__("contract_persistence_failed")


def _private_load_error(path: Path, error: Exception) -> bool:
    """Preserve ordinary parse diagnostics while protecting predecessor text."""
    with identity_operation() as snapshot:
        if snapshot is None:
            return False
        if (
            resolve_contract_id(path.stem) != path.stem
            or resolve_principal_id(path.stem) != path.stem
        ):
            return True
        # Providers may classify embedded text (including YAML parser excerpts).
        # Without that capability, required custody keeps diagnostics private.
        contains_predecessor = getattr(snapshot, "contains_predecessor", None)
        if not callable(contains_predecessor):
            return True
        try:
            return bool(contains_predecessor(f"{path}: {error}"))
        except Exception:
            return True


@dataclass(frozen=True)
class ConsentContract:
    """A bilateral consent agreement between operator and subject.

    Immutable once loaded. Revocation creates a new record, it does not
    mutate the existing contract.
    """

    id: str
    parties: tuple[str, str]
    scope: frozenset[str]
    direction: str = "one_way"
    visibility_mechanism: str = "on_request"
    created_at: str = ""
    revoked_at: str | None = None
    principal_class: str = ""
    guardian: str | None = None

    @property
    def active(self) -> bool:
        return self.revoked_at is None


@dataclass
class ConsentRegistry:
    """Runtime registry of consent contracts.

    Loaded from YAML files on disk. Provides contract_check() for
    ingestion boundary enforcement.
    """

    _identity_binding: IdentityMigrationBinding | None = field(default=None, repr=False)
    _contracts: dict[str, ConsentContract] = field(default_factory=dict)
    _fail_closed: bool = field(default=False)
    _loaded_at: float = field(default=0.0)
    _contracts_dir: Path | None = field(default=None)
    _contract_paths: dict[str, Path] = field(default_factory=dict)

    @property
    def fail_closed(self) -> bool:
        return self._fail_closed

    def is_stale(self, stale_threshold_s: float = 300.0) -> bool:
        """Check if the registry was loaded too long ago to trust."""
        if self._loaded_at == 0.0:
            return False
        return time.time() - self._loaded_at > stale_threshold_s

    @_registry_operation
    def load(self, contracts_dir: Path | None = None, *, strict: bool = False) -> int:
        """Load all contract files from the contracts directory.

        Args:
            contracts_dir: Path to scan for YAML contract files.
            strict: When True, raise ConsentContractLoadError on any
                malformed YAML instead of logging and skipping.

        Returns:
            The number of active contracts loaded.
        """
        directory = contracts_dir or self._contracts_dir
        if directory is None:
            log.info("No contracts directory configured")
            self._fail_closed = True
            return 0

        try:
            if not directory.exists():
                log.info("No contracts directory at %s", directory)
                self._fail_closed = True
                return 0

            self._contracts_dir = directory
            self._contracts.clear()
            self._contract_paths.clear()
            count = 0
            for path in sorted(directory.glob("*.yaml")):
                try:
                    data = yaml.safe_load(path.read_text())
                    if data is None:
                        continue
                    contract = parse_contract(data)
                    self._contracts[contract.id] = contract
                    self._contract_paths[contract.id] = path
                    if contract.active:
                        count += 1
                        log.info("consent_contract_loaded")
                except Exception as exc:
                    if _private_load_error(path, exc):
                        if strict:
                            raise ConsentContractLoadError("consent_contract_malformed") from None
                        log.warning("consent_contract_malformed")
                        continue
                    if strict:
                        raise ConsentContractLoadError(
                            f"Failed to load contract from {path}: {exc}"
                        ) from exc
                    log.exception("Failed to load contract from %s", path)

            self._fail_closed = False
            self._loaded_at = time.time()
            return count
        except ConsentContractLoadError:
            raise
        except Exception:
            log.exception("Failed to load contracts from %s", directory)
            self._fail_closed = True
            return 0

    def _matching_contract_keys(self, contract_id: str) -> list[str]:
        canonical = resolve_contract_id(contract_id) or contract_id
        return [key for key in self._contracts if (resolve_contract_id(key) or key) == canonical]

    @_registry_operation
    def get(self, contract_id: str) -> ConsentContract | None:
        keys = self._matching_contract_keys(contract_id)
        return self._contracts[keys[0]] if keys else None

    def __iter__(self):
        return iter(self._contracts.values())

    @_registry_operation
    def contract_check(self, person_id: str, data_category: str) -> bool:
        """Check whether an active contract permits this data flow.

        Returns True if an active contract exists for the given person
        with the given data category in scope. Returns False otherwise.
        """
        if self._fail_closed or self.is_stale():
            return False
        for contract in self._contracts.values():
            if not contract.active:
                continue
            if (resolve_principal_id(person_id) or person_id) in {
                resolve_principal_id(party) or party for party in contract.parties
            } and data_category in contract.scope:
                return True
        return False

    @_registry_operation
    def get_contract_for(self, person_id: str) -> ConsentContract | None:
        """Return the active contract for a person, if any."""
        for contract in self._contracts.values():
            if contract.active and (resolve_principal_id(person_id) or person_id) in {
                resolve_principal_id(party) or party for party in contract.parties
            }:
                return contract
        return None

    @_registry_operation
    def subject_data_categories(self, person_id: str) -> frozenset[str]:
        """Return all permitted data categories for a person."""
        categories: set[str] = set()
        for contract in self._contracts.values():
            if contract.active and (resolve_principal_id(person_id) or person_id) in {
                resolve_principal_id(party) or party for party in contract.parties
            }:
                categories |= contract.scope
        return frozenset(categories)

    @_registry_operation
    def revoke_contract(
        self,
        contract_id: str,
        *,
        contracts_dir: Path | None = None,
    ) -> float:
        """Revoke a single consent contract by ID.

        Returns the wall-clock seconds the revocation took.
        Raises KeyError if the contract_id is not registered.
        """
        t0 = time.monotonic()
        keys = self._matching_contract_keys(contract_id)
        if not keys:
            if (
                resolve_contract_id(contract_id) != contract_id
                or resolve_principal_id(contract_id) != contract_id
            ):
                raise KeyError("consent_contract_unregistered")
            raise KeyError(f"Contract {contract_id} not registered")

        now_iso = datetime.now().isoformat()
        for key in keys:
            if not self._contracts[key].active:
                continue
            src = self._contract_paths.get(key)
            if src is None:
                self._contracts[key] = replace(self._contracts[key], revoked_at=now_iso)
                continue
            if contracts_dir is not None:
                src = contracts_dir / src.name
            if src.exists():
                revoked_dir = src.parent / "revoked"
                revoked_dir.mkdir(parents=True, exist_ok=True)
                stamp = now_iso[:10]
                dst = revoked_dir / f"{stamp}-{src.name}"
                n = 2
                while dst.exists():
                    dst = revoked_dir / f"{stamp}-{src.stem}-{n}.yaml"
                    n += 1
                src.rename(dst)
                log.info("consent_contract_revoked")
            self._contracts[key] = replace(self._contracts[key], revoked_at=now_iso)

        elapsed = time.monotonic() - t0
        return elapsed

    @_registry_operation
    def purge_subject(self, person_id: str) -> list[str]:
        """Mark all contracts for a person as revoked. Returns revoked IDs."""
        revoked: list[str] = []
        candidates = [
            contract_id
            for contract_id, contract in self._contracts.items()
            if contract.active
            and resolve_principal_id(person_id)
            in {resolve_principal_id(party) or party for party in contract.parties}
        ]
        for index, contract_id in enumerate(candidates):
            try:
                self.revoke_contract(contract_id)
            except OSError:
                log.warning(
                    "contract_persistence_failed: remedy=restore_contract_storage_then_retry"
                )
                raise SubjectPurgeIncomplete(
                    tuple(resolve_contract_id(cid) for cid in revoked),
                    tuple(resolve_contract_id(cid) for cid in candidates[index:]),
                ) from None
            revoked.append(contract_id)
            log.info("consent_subject_revoked")
        return revoked

    @_registry_operation
    def create_contract(
        self,
        person_id: str,
        scope: frozenset[str],
        *,
        contract_id: str | None = None,
        direction: str = "one_way",
        visibility_mechanism: str = "on_request",
        contracts_dir: Path | None = None,
    ) -> ConsentContract:
        """Create and activate a new consent contract at runtime."""
        person_id = resolve_principal_id(person_id) or person_id
        now = datetime.now().isoformat()
        cid = contract_id or f"contract-{person_id}-{now[:10]}"

        contract = ConsentContract(
            id=cid,
            parties=("operator", person_id),
            scope=scope,
            direction=direction,
            visibility_mechanism=visibility_mechanism,
            created_at=now,
        )

        directory = contracts_dir or self._contracts_dir
        if directory is not None:
            directory.mkdir(parents=True, exist_ok=True)
            contract_path = directory / f"{cid}.yaml"
            contract_data: dict[str, Any] = {
                "id": contract.id,
                "parties": list(contract.parties),
                "scope": sorted(contract.scope),
                "direction": contract.direction,
                "visibility_mechanism": contract.visibility_mechanism,
                "created_at": contract.created_at,
            }
            if contract.principal_class:
                contract_data["principal_class"] = contract.principal_class
            if contract.guardian:
                contract_data["guardian"] = contract.guardian
            contract_path.write_text(yaml.dump(contract_data, default_flow_style=False))
            self._contract_paths[cid] = contract_path
            log.info("consent_contract_created")

        self._contracts[cid] = contract
        return contract

    @property
    def active_contracts(self) -> list[ConsentContract]:
        return [c for c in self._contracts.values() if c.active]


def parse_contract(data: dict[str, Any]) -> ConsentContract:
    """Parse a contract YAML dict into a ConsentContract."""
    parties = data.get("parties", [])
    if len(parties) != 2:
        raise ValueError(f"Contract must have exactly 2 parties, got {len(parties)}")

    return ConsentContract(
        id=data["id"],
        parties=(parties[0], parties[1]),
        scope=frozenset(data.get("scope", [])),
        direction=data.get("direction", "one_way"),
        visibility_mechanism=data.get("visibility_mechanism", "on_request"),
        created_at=data.get("created_at", ""),
        revoked_at=data.get("revoked_at"),
        principal_class=data.get("principal_class", ""),
        guardian=data.get("guardian"),
    )


def load_contracts(contracts_dir: Path | None = None) -> ConsentRegistry:
    """Convenience function: create and load a ConsentRegistry."""
    registry = ConsentRegistry(_contracts_dir=contracts_dir)
    registry.load(contracts_dir)
    return registry


def check_consent_state_freshness(path: Path, *, stale_threshold_s: float = 300.0) -> bool:
    """Check if a consent state file on disk is fresh enough to trust."""
    try:
        mtime = path.stat().st_mtime
        return (time.time() - mtime) < stale_threshold_s
    except OSError:
        return False
