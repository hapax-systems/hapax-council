"""Consent contract management — extends agentgov.consent with hapax-specific behavior.

Re-exports ConsentContract and ConsentRegistry from agentgov, then adds:
- REGISTERED_CHILD_PRINCIPALS
- is_child_principal()
- Health signal integration (control_signal, notify)
- Repo-relative contracts directory default
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from agentgov.consent import (
    ConsentContract,
    ConsentContractLoadError,
    IdentityMigrationBinding,
    IdentityMigrationUnavailable,
    check_consent_state_freshness,
    configure_identity_migration,
    custody_read_failure,
    identity_operation,
    parse_contract,
)
from agentgov.consent import (
    ConsentRegistry as _BaseConsentRegistry,
)

from shared.control_signal import ControlSignal, publish_health

log = logging.getLogger(__name__)

_CONTRACTS_DIR = Path(__file__).parent.parent.parent / "axioms" / "contracts"

REGISTERED_CHILD_PRINCIPALS: frozenset[str] = frozenset({"principal-c1", "principal-c2"})
REGISTERED_PRINCIPALS: frozenset[str] = REGISTERED_CHILD_PRINCIPALS | {"principal-a1"}

_ESTATE_BINDING = IdentityMigrationBinding("required", "shared.governance.consent")
_COMPATIBILITY_ENTRY = "consent-identifier-compatibility"


def bind_estate_identity() -> None:
    """Select the estate at a portable application's configuration boundary."""
    configure_identity_migration(_ESTATE_BINDING.mode, _ESTATE_BINDING.provider)


def estate_identity_operation():
    """Establish required custody for an authoritative operation."""
    return identity_operation(_ESTATE_BINDING)


class CompatibilityIntegrityError(ValueError):
    """FileStore returned no readable bytes for an existing compatibility entry."""


def _read_compatibility_document() -> bytes:
    # Import the installed API the same way as the existing FileStore helper.
    api_path = Path(
        os.environ.get("HAPAX_REINS_API", "").strip()
        or (Path.home() / ".local" / "share" / "reins" / "current" / "api")
    )
    sys.path.insert(0, str(api_path))
    try:
        key_capture = importlib.import_module("k0.key_capture")
    except Exception as exc:
        raise custody_read_failure(exc) from None
    finally:
        sys.path.remove(str(api_path))

    try:

        class ReadOnlyFileStore(key_capture.FileStore):
            def _key(self) -> bytes:
                # Never call the initializing accessor, even if the key
                # disappears between opening the store and reading its blob.
                key = (self.root / ".key").read_bytes()
                if len(key) != 32:
                    raise CompatibilityIntegrityError()
                return key

        store = ReadOnlyFileStore()
        raw = store.get(_COMPATIBILITY_ENTRY)
        if raw is None and store.has(_COMPATIBILITY_ENTRY):
            raise CompatibilityIntegrityError()
    except Exception as exc:
        raise custody_read_failure(exc) from None
    if raw is None:
        raise IdentityMigrationUnavailable("compat_missing")
    return raw


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise IdentityMigrationUnavailable("compat_conflict")
        result[key] = value
    return result


@dataclass(frozen=True, repr=False)
class _CorrespondenceSnapshot:
    principals: Mapping[str, str]
    contracts: Mapping[str, str]

    def resolve_principal_id(self, candidate: str) -> str:
        return self.principals.get(candidate, candidate)

    def resolve_contract_id(self, candidate: str) -> str:
        return self.contracts.get(candidate, candidate)

    def predecessor_labels(self, principal_id: str) -> frozenset[str]:
        """Private matching terms for one principal; never export or audit them."""
        canonical = self.resolve_principal_id(principal_id)
        return frozenset(
            label for label, successor in self.principals.items() if successor == canonical
        )

    def mentioned_principal_ids(self, content: str) -> frozenset[str]:
        """Recognize both identity spellings independently of active consent."""
        matching_content = content.lower()
        return frozenset(
            canonical
            for label, canonical in self.principals.items()
            for spelling in (label, canonical)
            if re.search(r"\b" + re.escape(spelling) + r"\b", matching_content, re.IGNORECASE)
        )

    def contains_predecessor(self, text: str) -> bool:
        """Classify diagnostics without exporting private correspondence."""
        return any(
            label in text for section in (self.principals, self.contracts) for label in section
        )


def load_identity_snapshot() -> _CorrespondenceSnapshot:
    """Read and validate the entire private declared inventory for one operation."""
    raw = _read_compatibility_document()
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object)
    except IdentityMigrationUnavailable:
        raise
    except Exception as exc:
        raise IdentityMigrationUnavailable(
            "compat_malformed", cause_class=type(exc).__name__
        ) from None
    if (
        not isinstance(data, dict)
        or set(data) != {"version", "principals", "contracts", "inventory"}
        or type(data["version"]) is not int
        or data["version"] != 1
    ):
        raise IdentityMigrationUnavailable("compat_malformed")
    sections = (data["principals"], data["contracts"])
    inventory = data["inventory"]
    if (
        any(
            not isinstance(section, dict)
            or not section
            or any(
                not isinstance(key, str)
                or not key.strip()
                or not isinstance(value, str)
                or not value.strip()
                for key, value in section.items()
            )
            for section in sections
        )
        or not isinstance(inventory, list)
        or not inventory
        or any(not isinstance(label, str) or not label.strip() for label in inventory)
    ):
        raise IdentityMigrationUnavailable("compat_malformed")
    principals, contracts = sections
    labels = set(principals) | set(contracts)
    if (
        set(principals) & set(contracts)
        or len(set(inventory)) != len(inventory)
        or labels & (set(principals.values()) | set(contracts.values()))
    ):
        raise IdentityMigrationUnavailable("compat_conflict")
    if set(inventory) != labels:
        raise IdentityMigrationUnavailable("compat_incomplete")
    return _CorrespondenceSnapshot(MappingProxyType(principals), MappingProxyType(contracts))


def resolve_principal_id(candidate: str) -> str:
    """Resolve through required custody, including canonical inputs."""
    with estate_identity_operation() as snapshot:
        return snapshot.resolve_principal_id(candidate)


def resolve_contract_id(candidate: str) -> str:
    """Resolve through required custody, including canonical inputs."""
    with estate_identity_operation() as snapshot:
        return snapshot.resolve_contract_id(candidate)


class ConsentRegistry(_BaseConsentRegistry):
    """ConsentRegistry with hapax-specific health signals and notifications."""

    def __init__(self, **kwargs: Any) -> None:
        if "_contracts_dir" not in kwargs:
            kwargs["_contracts_dir"] = _CONTRACTS_DIR
        kwargs["_identity_binding"] = _ESTATE_BINDING
        super().__init__(**kwargs)
        self._cl_errors: int = 0
        self._cl_ok: int = 0
        self._cl_degraded: bool = False

    def load(self, contracts_dir: Path | None = None, *, strict: bool = False) -> int:
        try:
            count = super().load(contracts_dir or _CONTRACTS_DIR, strict=strict)
            if not strict or count > 0:
                publish_health(
                    ControlSignal(component="consent_engine", reference=1.0, perception=1.0)
                )
                self._cl_errors = 0
                self._cl_ok += 1
                if self._cl_ok >= 5 and self._cl_degraded:
                    self._cl_degraded = False
                    log.info("Control law [consent_engine]: recovered")
            return count
        except (ConsentContractLoadError, IdentityMigrationUnavailable):
            raise
        except Exception:
            log.exception("Failed to load contracts")
            publish_health(ControlSignal(component="consent_engine", reference=1.0, perception=0.0))
            self._cl_errors += 1
            self._cl_ok = 0
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
                    pass
                log.warning("Control law [consent_engine]: degrading — fail_closed, ntfy sent")
            return 0


@estate_identity_operation()
def is_child_principal(person_id: str, registry: ConsentRegistry | None = None) -> bool:
    """Check if a person is a registered child principal."""
    person_id = resolve_principal_id(person_id) or person_id
    if person_id in REGISTERED_CHILD_PRINCIPALS:
        return True
    if registry is not None:
        contract = registry.get_contract_for(person_id)
        if contract is not None and contract.principal_class == "child":
            return True
    return False


def load_contracts(contracts_dir: Path | None = None, *, strict: bool = False) -> ConsentRegistry:
    """Create and load a ConsentRegistry with hapax defaults."""
    registry = ConsentRegistry()
    registry.load(contracts_dir, strict=strict)
    return registry


__all__ = [
    "ConsentContract",
    "ConsentContractLoadError",
    "IdentityMigrationUnavailable",
    "bind_estate_identity",
    "estate_identity_operation",
    "ConsentRegistry",
    "REGISTERED_CHILD_PRINCIPALS",
    "REGISTERED_PRINCIPALS",
    "resolve_principal_id",
    "resolve_contract_id",
    "check_consent_state_freshness",
    "is_child_principal",
    "load_contracts",
    "parse_contract",
]
