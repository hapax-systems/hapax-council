"""Runtime wiring for revocation cascade (DD-8, DD-23, DD-26).

Connects RevocationPropagator to the carrier registry from the reactive
engine, so consent revocations cascade into carrier fact purges at runtime.

The propagator is a module-level singleton, lazily initialized with the
carrier registry from logos.engine.reactive_rules and a ConsentRegistry
loaded from the axioms/contracts/ directory.
"""

from __future__ import annotations

import logging

from .consent import ConsentRegistry, load_contracts
from .revocation import RevocationPropagator

_log = logging.getLogger(__name__)

_propagator: RevocationPropagator | None = None


def get_revocation_propagator(
    *,
    consent_registry: ConsentRegistry | None = None,
) -> RevocationPropagator:
    """Get or create the module-level RevocationPropagator.

    On first call, loads consent contracts and wires the carrier registry
    from reactive_rules. Subsequent calls return the same instance.
    """
    global _propagator  # noqa: PLW0603
    if _propagator is not None:
        return _propagator

    # Load consent contracts
    cr = consent_registry or load_contracts()
    prop = RevocationPropagator(cr)

    # Wire carrier registry from reactive engine
    try:
        from logos.engine.reactive_rules import get_carrier_registry

        carrier = get_carrier_registry()
        prop.register_carrier_registry(carrier)
        _log.info("Revocation propagator wired to carrier registry")
    except Exception:
        _log.warning("Could not wire carrier registry to revocation propagator", exc_info=True)

    _propagator = prop
    return prop


def set_revocation_propagator(propagator: RevocationPropagator | None) -> None:
    """Inject a RevocationPropagator for testing or reset."""
    global _propagator  # noqa: PLW0603
    _propagator = propagator
