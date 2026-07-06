"""Consent contract management for information flow governance.

Provides contract loading, validation, and enforcement at data ingestion
boundaries. Any data pathway handling person data must call
contract_check() before persisting state.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)


class ConsentContractLoadError(Exception):
    """Raised when a contract YAML file fails to parse in strict mode."""


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

    _contracts: dict[str, ConsentContract] = field(default_factory=dict)
    _fail_closed: bool = field(default=False)
    _loaded_at: float = field(default=0.0)
    _contracts_dir: Path | None = field(default=None)

    @property
    def fail_closed(self) -> bool:
        return self._fail_closed

    def is_stale(self, stale_threshold_s: float = 300.0) -> bool:
        """Check if the registry was loaded too long ago to trust."""
        if self._loaded_at == 0.0:
            return False
        return time.time() - self._loaded_at > stale_threshold_s

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

            count = 0
            for path in sorted(directory.glob("*.yaml")):
                try:
                    data = yaml.safe_load(path.read_text())
                    if data is None:
                        continue
                    contract = parse_contract(data)
                    self._contracts[contract.id] = contract
                    if contract.active:
                        count += 1
                        log.info(
                            "Loaded contract %s: %s <-> %s (scope: %s)",
                            contract.id,
                            contract.parties[0],
                            contract.parties[1],
                            ", ".join(sorted(contract.scope)),
                        )
                except Exception as exc:
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

    def get(self, contract_id: str) -> ConsentContract | None:
        return self._contracts.get(contract_id)

    def __iter__(self):
        return iter(self._contracts.values())

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
            if person_id in contract.parties and data_category in contract.scope:
                return True
        return False

    def get_contract_for(self, person_id: str) -> ConsentContract | None:
        """Return the active contract for a person, if any."""
        for contract in self._contracts.values():
            if contract.active and person_id in contract.parties:
                return contract
        return None

    def subject_data_categories(self, person_id: str) -> frozenset[str]:
        """Return all permitted data categories for a person."""
        categories: set[str] = set()
        for contract in self._contracts.values():
            if contract.active and person_id in contract.parties:
                categories |= contract.scope
        return frozenset(categories)

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
        contract = self._contracts.get(contract_id)
        if contract is None:
            raise KeyError(f"Contract {contract_id} not registered")

        now_iso = datetime.now().isoformat()
        revoked_contract = ConsentContract(
            id=contract.id,
            parties=contract.parties,
            scope=contract.scope,
            direction=contract.direction,
            visibility_mechanism=contract.visibility_mechanism,
            created_at=contract.created_at,
            revoked_at=now_iso,
            principal_class=contract.principal_class,
            guardian=contract.guardian,
        )
        self._contracts[contract_id] = revoked_contract

        directory = contracts_dir or self._contracts_dir
        if directory is not None:
            src = directory / f"{contract_id}.yaml"
            if src.exists():
                revoked_dir = directory / "revoked"
                revoked_dir.mkdir(parents=True, exist_ok=True)
                stamp = now_iso[:10]
                dst = revoked_dir / f"{stamp}-{contract_id}.yaml"
                n = 2
                while dst.exists():
                    dst = revoked_dir / f"{stamp}-{contract_id}-{n}.yaml"
                    n += 1
                src.rename(dst)
                log.info("Revoked contract %s — moved YAML to %s", contract_id, dst)

        elapsed = time.monotonic() - t0
        return elapsed

    def purge_subject(self, person_id: str) -> list[str]:
        """Mark all contracts for a person as revoked. Returns revoked IDs."""
        revoked: list[str] = []
        for contract_id, contract in self._contracts.items():
            if contract.active and person_id in contract.parties:
                revoked_contract = ConsentContract(
                    id=contract.id,
                    parties=contract.parties,
                    scope=contract.scope,
                    direction=contract.direction,
                    visibility_mechanism=contract.visibility_mechanism,
                    created_at=contract.created_at,
                    revoked_at=datetime.now().isoformat(),
                    principal_class=contract.principal_class,
                    guardian=contract.guardian,
                )
                self._contracts[contract_id] = revoked_contract
                revoked.append(contract_id)
                log.info("Revoked contract %s for %s", contract_id, person_id)
        return revoked

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
            log.info("Created consent contract %s for %s at %s", cid, person_id, contract_path)

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
