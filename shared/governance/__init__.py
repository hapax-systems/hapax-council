"""Governance package — thin wrapper re-exporting from the agentgov package.

The algebraic governance core (consent labels, principals, provenance,
governors, carriers, revocation, VetoChain, Says) lives in the standalone
``agentgov`` package (packages/agentgov/). This module re-exports
everything for backwards compatibility.

Hapax-specific modules (consent_gate, consent_channels, content_risk,
monetization_safety, etc.) remain here as they depend on council internals.
"""

from agentgov import (
    Candidate,
    CarrierFact,
    CarrierRegistry,
    ConsentContract,
    ConsentLabel,
    ConsentRegistry,
    DisplacementResult,
    FallbackChain,
    GatedResult,
    GovernorDenial,
    GovernorPolicy,
    GovernorResult,
    GovernorWrapper,
    Labeled,
    Principal,
    PrincipalKind,
    ProvenanceExpr,
    PurgeResult,
    RevocationPropagator,
    RevocationReport,
    Says,
    Selected,
    Veto,
    VetoChain,
    VetoResult,
    check_provenance,
    consent_input_policy,
    consent_output_policy,
    create_agent_governor,
    load_contracts,
)


def __getattr__(name: str):
    """Lazy imports for hapax-specific modules."""
    if name == "CarrierIntakeResult":
        from shared.governance.carrier_intake import CarrierIntakeResult

        return CarrierIntakeResult
    if name == "intake_carrier_fact":
        from shared.governance.carrier_intake import intake_carrier_fact

        return intake_carrier_fact
    raise AttributeError(f"module 'shared.governance' has no attribute {name}")


from agentgov.revocation import check_provenance  # noqa: F811

from shared.governance.revocation_wiring import (
    get_revocation_propagator,
    set_revocation_propagator,
)

__all__ = [
    # Principal model
    "Principal",
    "PrincipalKind",
    # Consent
    "ConsentContract",
    "ConsentRegistry",
    "ConsentLabel",
    "load_contracts",
    # Labeled data
    "Labeled",
    # Provenance
    "ProvenanceExpr",
    # Carrier dynamics
    "CarrierFact",
    "CarrierRegistry",
    "CarrierIntakeResult",
    "DisplacementResult",
    "intake_carrier_fact",
    # Governor (AMELI pattern)
    "GovernorWrapper",
    "GovernorPolicy",
    "GovernorResult",
    "GovernorDenial",
    "consent_input_policy",
    "consent_output_policy",
    "create_agent_governor",
    # Revocation cascade
    "RevocationPropagator",
    "RevocationReport",
    "PurgeResult",
    "check_provenance",
    "get_revocation_propagator",
    "set_revocation_propagator",
    # Compositional governance primitives
    "Candidate",
    "FallbackChain",
    "GatedResult",
    "Selected",
    "Veto",
    "VetoChain",
    "VetoResult",
    # Says monad
    "Says",
]
