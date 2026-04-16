"""Consent contract management for interpersonal_transparency axiom.

Provides contract loading, validation, and enforcement at data ingestion
boundaries. Any PerceptionBackend or data pathway handling non-operator
person data must call contract_check() before persisting state.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from shared.control_signal import ControlSignal, publish_health

log = logging.getLogger(__name__)

_CONTRACTS_DIR = Path(__file__).parent.parent.parent / "axioms" / "contracts"


class ConsentContractLoadError(Exception):
    """Raised by ``ConsentRegistry.load(..., strict=True)`` when a contract
    YAML file fails to parse. LRR Phase 6 §11 fail-loud validation."""


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
    _fail_closed: bool = field(default=False)
    _loaded_at: float = field(default=0.0)

    @property
    def fail_closed(self) -> bool:
        return self._fail_closed

    def is_stale(self, stale_threshold_s: float = 300.0) -> bool:
        """Check if the registry was loaded too long ago to trust.

        Returns False if load() was never called (registry may have been
        populated programmatically via create_contract).
        """
        if self._loaded_at == 0.0:
            return False  # Never loaded from disk — staleness doesn't apply
        return time.time() - self._loaded_at > stale_threshold_s

    def load(self, contracts_dir: Path | None = None, *, strict: bool = False) -> int:
        """Load all contract files from the contracts directory.

        Args:
            contracts_dir: Path to scan. Defaults to repo ``axioms/contracts/``.
            strict: LRR Phase 6 §11 — when True, raise
                ``ConsentContractLoadError`` on any malformed YAML or
                construction failure instead of logging and skipping.
                Tests, CI, and startup should use ``strict=True`` to
                prevent silent contract loss. Default ``False`` preserves
                the existing fail-soft behavior for runtime reload paths.

        Returns:
            The number of active contracts loaded.

        Raises:
            ConsentContractLoadError: When ``strict=True`` and any contract
                file fails to parse. Error message includes the file path.
        """
        directory = contracts_dir or _CONTRACTS_DIR
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
                except Exception as exc:
                    if strict:
                        raise ConsentContractLoadError(
                            f"Failed to load contract from {path}: {exc}"
                        ) from exc
                    log.exception("Failed to load contract from %s", path)

            self._fail_closed = False
            self._loaded_at = time.time()
            publish_health(ControlSignal(component="consent_engine", reference=1.0, perception=1.0))
            # Control law: successful load
            self._cl_errors = 0
            self._cl_ok = getattr(self, "_cl_ok", 0) + 1
            if self._cl_ok >= 5 and getattr(self, "_cl_degraded", False):
                self._cl_degraded = False
                log.info("Control law [consent_engine]: recovered")
            return count
        except ConsentContractLoadError:
            # Strict-mode validation failure — propagate outward.
            # Do not set fail_closed: caller wants to see the error.
            raise
        except Exception:
            log.exception("Failed to load contracts from %s", directory)
            self._fail_closed = True
            publish_health(ControlSignal(component="consent_engine", reference=1.0, perception=0.0))
            # Control law: fail_closed → emit ntfy notification
            self._cl_errors = getattr(self, "_cl_errors", 0) + 1
            self._cl_ok = 0
            self._cl_degraded = getattr(self, "_cl_degraded", False)
            if self._cl_errors >= 3 and not self._cl_degraded:
                self._cl_degraded = True
                try:
                    from shared.notify import send_notification

                    send_notification(
                        "Consent Engine Degraded",
                        "Contract loading failed 3 times — fail-closed active",
                        priority="high",
                        tags=["warning"],
                    )
                except Exception:
                    pass  # notification is best-effort
                log.warning("Control law [consent_engine]: degrading — fail_closed, ntfy sent")
            return 0

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
        """LRR Phase 6 §7 — revoke a single consent contract by ID.

        Synchronous revocation: marks the in-memory contract revoked AND
        moves the YAML to ``<contracts_dir>/revoked/<YYYY-MM-DD>-<id>.yaml``
        so downstream readers that re-scan the dir see the contract as
        revoked immediately (no 60s cache wait).

        Returns the wall-clock seconds the full in-process revocation took.
        The §7 drill asserts this is ≤ 5.0 s end-to-end (including the
        filesystem operation).

        Raises ``KeyError`` if the contract_id is not registered. Caller
        is responsible for ConsentGatedWriter / Reader cache invalidation
        at their layer; ``_fail_closed`` is NOT set because a single-
        contract revoke does not mean the registry itself is broken.
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

        # Move the YAML file to revoked/ so a fresh load() also sees it revoked.
        # Missing source file is not fatal — the in-memory state already carries
        # the revocation.
        directory = contracts_dir or _CONTRACTS_DIR
        src = directory / f"{contract_id}.yaml"
        if src.exists():
            revoked_dir = directory / "revoked"
            revoked_dir.mkdir(parents=True, exist_ok=True)
            stamp = now_iso[:10]  # YYYY-MM-DD
            dst = revoked_dir / f"{stamp}-{contract_id}.yaml"
            # Avoid collision on multiple same-day revocations
            n = 2
            while dst.exists():
                dst = revoked_dir / f"{stamp}-{contract_id}-{n}.yaml"
                n += 1
            src.rename(dst)
            log.info("Revoked contract %s — moved YAML to %s", contract_id, dst)
        else:
            log.warning(
                "Revoked contract %s in-memory only (source YAML %s missing)",
                contract_id,
                src,
            )

        elapsed = time.monotonic() - t0
        return elapsed

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


def check_consent_state_freshness(path: Path, *, stale_threshold_s: float = 300.0) -> bool:
    """Check if a consent state file on disk is fresh enough to trust.

    Returns False (fail-closed) if the file is missing, unreadable, or older
    than stale_threshold_s seconds.
    """
    try:
        mtime = path.stat().st_mtime
        return (time.time() - mtime) < stale_threshold_s
    except OSError:
        return False
