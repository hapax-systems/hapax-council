"""Consent contract management — extends agentgov.consent with hapax-specific behavior.

Re-exports ConsentContract and ConsentRegistry from agentgov, then adds:
- REGISTERED_CHILD_PRINCIPALS
- is_child_principal()
- Health signal integration (control_signal, notify)
- Repo-relative contracts directory default
"""

from __future__ import annotations

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

REGISTERED_CHILD_PRINCIPALS: frozenset[str] = frozenset({"simon", "agatha"})


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
    "check_consent_state_freshness",
    "is_child_principal",
    "load_contracts",
    "parse_contract",
]
