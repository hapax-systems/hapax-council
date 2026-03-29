"""CapabilityHealthVeto: compose capability health into VetoChain.

Provides a Veto predicate that checks whether a required capability is
healthy before allowing an action. Proves that check_fast (hot-path
enforcement from Batch 4) can be used as a VetoChain predicate.
"""

from __future__ import annotations

from agents.hapax_daimonion.governance import Veto
from shared.capabilities.protocols import HealthStatus
from shared.capabilities.registry import CapabilityRegistry


def capability_health_veto(
    capability_type: str,
    registry: CapabilityRegistry,
    *,
    axiom: str | None = None,
    description: str = "",
) -> Veto:
    """Create a Veto that denies when a capability is unhealthy.

    The predicate checks the registry's health for the given capability type.
    The context parameter is ignored (the veto checks external state).

    Args:
        capability_type: The capability type to check health for.
        registry: The capability registry to query.
        axiom: Optional axiom ID for audit trail.
        description: Human-readable description.
    """

    def _predicate(_context: object) -> bool:
        adapter = registry.get(capability_type)
        if adapter is None:
            return False  # no adapter registered → deny
        try:
            status: HealthStatus = adapter.health()  # type: ignore[union-attr]
            return status.healthy
        except Exception:
            return False

    return Veto(
        name=f"capability_health:{capability_type}",
        predicate=_predicate,
        axiom=axiom,
        description=description or f"Requires healthy {capability_type} capability",
    )


def compliance_veto(
    rules: list,
    *,
    axiom: str | None = None,
    description: str = "",
) -> Veto:
    """Create a Veto that denies when check_fast finds violations.

    Proves that check_fast can be used as a VetoChain predicate (hot-path
    enforcement in the governance layer).

    The context is expected to be a string (situation description).

    Args:
        rules: Pre-compiled ComplianceRules from axiom_enforcement.compile_rules().
        axiom: Optional axiom ID.
        description: Human-readable description.
    """
    from shared.axiom_enforcement import check_fast

    def _predicate(context: object) -> bool:
        situation = str(context)
        result = check_fast(situation, rules=rules)
        return result.compliant

    return Veto(
        name="compliance_fast_check",
        predicate=_predicate,
        axiom=axiom,
        description=description or "Fast compliance check against T0 rules",
    )
