"""Consent contract management for interpersonal_transparency axiom.

Provides contract loading, validation, and enforcement at data ingestion
boundaries. Any PerceptionBackend or data pathway handling non-operator
person data must call contract_check() before persisting state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

_CONTRACTS_DIR = Path(__file__).parent.parent.parent / "axioms" / "contracts"

# Registered child principals — ONLY these children may have consent contracts.
# All other children are categorically excluded from system participation.
# Guardian-granted consent: operator is legal guardian.
REGISTERED_CHILD_PRINCIPALS: frozenset[str] = frozenset({"simon", "agatha"})


@dataclass(frozen=True)
class ConsentContract:
    """A bilateral consent agreement between operator and subject.

    Immutable once loaded. Revocation creates a new record, it does not
    mutate the existing contract.
    """

    id: str
    parties: tuple[str, str]  # (operator, subject)
    scope: frozenset[str]  # permitted data categories
    direction: str = "one_way"  # "one_way" | "bidirectional"
    visibility_mechanism: str = "on_request"
    created_at: str = ""
    revoked_at: str | None = None
    principal_class: str = ""  # "child" for minors (guardian-mediated consent)
    guardian: str | None = None  # guardian principal ID (e.g., "operator")

    @property
    def active(self) -> bool:
        return self.revoked_at is None


@dataclass
class ConsentRegistry:
    """Runtime registry of consent contracts.

    Loaded from axioms/contracts/*.yaml on startup.
    Provides contract_check() for ingestion boundary enforcement.
    """

    _contracts: dict[str, ConsentContract] = field(default_factory=dict)

    def load(self, contracts_dir: Path | None = None) -> int:
        """Load all contract files from the contracts directory.

        Returns the number of active contracts loaded.
        """
        directory = contracts_dir or _CONTRACTS_DIR
        if not directory.exists():
            log.info("No contracts directory at %s", directory)
            return 0

        count = 0
        for path in sorted(directory.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text())
                if data is None:
                    continue
                contract = _parse_contract(data)
                self._contracts[contract.id] = contract
                if contract.active:
                    count += 1
                    log.info(
                        "Loaded contract %s: %s ↔ %s (scope: %s)",
                        contract.id,
                        contract.parties[0],
                        contract.parties[1],
                        ", ".join(sorted(contract.scope)),
                    )
            except Exception:
                log.exception("Failed to load contract from %s", path)

        return count

    def get(self, contract_id: str) -> ConsentContract | None:
        """Return a contract by ID, or None."""
        return self._contracts.get(contract_id)

    def __iter__(self):
        """Iterate over all contracts."""
        return iter(self._contracts.values())

    def contract_check(self, person_id: str, data_category: str) -> bool:
        """Check whether an active contract permits this data flow.

        Returns True if an active contract exists for the given person
        with the given data category in scope. Returns False otherwise.

        This is the enforcement boundary — call at ingestion, not downstream.
        """
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

    def purge_subject(self, person_id: str) -> list[str]:
        """Mark all contracts for a person as revoked.

        Returns list of revoked contract IDs. Does NOT purge data —
        callers must handle data purge based on the returned IDs.
        The contract record is retained for audit (per it-audit-001).
        """
        revoked: list[str] = []
        for contract_id, contract in self._contracts.items():
            if contract.active and person_id in contract.parties:
                # Create revoked copy (ConsentContract is frozen)
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
        """Create and activate a new consent contract at runtime.

        Writes the contract to axioms/contracts/ as YAML (filesystem-as-bus)
        and registers it in the in-memory registry. Returns the new contract.

        The contract is immediately active — no confirmation step needed
        because the operator or guest already confirmed via the facilitation UI.
        """
        import yaml

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

        # Persist to filesystem (the canonical store)
        directory = contracts_dir or _CONTRACTS_DIR
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

        # Register in memory
        self._contracts[cid] = contract
        return contract

    @property
    def active_contracts(self) -> list[ConsentContract]:
        return [c for c in self._contracts.values() if c.active]


def _parse_contract(data: dict[str, Any]) -> ConsentContract:
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


def is_child_principal(person_id: str, registry: ConsentRegistry | None = None) -> bool:
    """Check if a person is a registered child principal.

    Checks both the hardcoded REGISTERED_CHILD_PRINCIPALS set and the
    principal_class field on active contracts.
    """
    if person_id in REGISTERED_CHILD_PRINCIPALS:
        return True
    if registry is not None:
        contract = registry.get_contract_for(person_id)
        if contract is not None and contract.principal_class == "child":
            return True
    return False


def load_contracts(contracts_dir: Path | None = None) -> ConsentRegistry:
    """Convenience function: create and load a ConsentRegistry."""
    registry = ConsentRegistry()
    registry.load(contracts_dir)
    return registry
