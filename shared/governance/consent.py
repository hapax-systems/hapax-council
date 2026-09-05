"""Consent contract management — extends agentgov.consent with hapax-specific behavior.

Re-exports ConsentContract and ConsentRegistry from agentgov, then adds:
- REGISTERED_CHILD_PRINCIPALS
- is_child_principal()
- Health signal integration (control_signal, notify)
- Repo-relative contracts directory default
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from agentgov.consent import (
    ConsentContract,
    ConsentContractLoadError,
    check_consent_state_freshness,
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

# Digests are migration metadata, retained even after contract revocation.
# Recipe: sha256("principal-alias-v1:" + predecessor).hexdigest()
_PRINCIPAL_ALIASES: dict[str, str] = {
    # The keys are identifier digests, not credentials (push-scan allowlist).
    "31224f3e0ccf3be0ab957b5719877b66723aa6f4ebca89bcb250fabd07450d6d": "principal-a1",  # pragma: allowlist secret
    "0e9b2cd2da8bed8fe7534e0c4a5fb3b82513a6701a66c638b04690f359e3d89a": "principal-c1",  # pragma: allowlist secret
    "a668db127fcfd198a0127ee00ba376f7d39036d48caa9d7fb08c688ff520848d": "principal-c2",  # pragma: allowlist secret
}
_CONTRACT_ALIASES: dict[str, str] = {
    "a30de7d2024abca811da34e3cc25a25da59f0a0ee95b6089ad88130d23c98efd": "contract-principal-a1-2026-04-19",  # pragma: allowlist secret
    "9d754c6983e2fc76a96c80696b072586d6436cd940b48a0fe9dcaf0c149d0a5d": "contract-principal-a1-enroll-2026-04-19",  # pragma: allowlist secret
    "a51ebc899c84427004e7240a013dd0d0fbd9ae0da77a8239f28f9b571fea3b08": "contract-principal-c1",  # pragma: allowlist secret
    "6d49ae5807206af3053f70f6213f479421b62fe3cc7c29a504db3f85230cc7fa": "contract-principal-c2",  # pragma: allowlist secret
}
_REGISTERED_CONTRACT_IDS: frozenset[str] = frozenset(_CONTRACT_ALIASES.values())


def resolve_principal_id(candidate: str) -> str | None:
    """Resolve an opaque principal or a registered predecessor, otherwise None."""
    if candidate in REGISTERED_PRINCIPALS:
        return candidate
    digest = hashlib.sha256(("principal-alias-v1:" + candidate).encode()).hexdigest()
    return _PRINCIPAL_ALIASES.get(digest)


def resolve_contract_id(candidate: str) -> str | None:
    """Resolve an opaque contract or a registered predecessor, otherwise None."""
    if candidate in _REGISTERED_CONTRACT_IDS:
        return candidate
    digest = hashlib.sha256(("principal-alias-v1:" + candidate).encode()).hexdigest()
    return _CONTRACT_ALIASES.get(digest)


class ConsentRegistry(_BaseConsentRegistry):
    """ConsentRegistry with hapax-specific health signals and notifications."""

    def __init__(self, **kwargs: Any) -> None:
        if "_contracts_dir" not in kwargs:
            kwargs["_contracts_dir"] = _CONTRACTS_DIR
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
        except ConsentContractLoadError:
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
