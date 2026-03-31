"""Governance package — consent, authority, and values as type-level invariants.

This package implements the core governance primitives described in the
computational constitutional governance specification. It is designed to
be readable as a standalone reference implementation:

- PL researchers: start with consent_label.py (DLM operations)
- MAS researchers: start with carrier.py (factor graph correspondence)
- AI Safety researchers: start with agent_governor.py (separation of powers)

All modules are pure governance logic with no operational dependencies.
The only external dependency is carrier_intake.py which uses
agents._frontmatter for consent label extraction from filesystem files.

Vendored from shared/governance/ during shared/ dissolution (2026-03-30).

Algebraic properties proven via hypothesis:
- ConsentLabel: join-semilattice (associative, commutative, idempotent)
- Labeled[T]: functor (identity, composition)
- Principal: non-amplification (bound ⊆ delegator authority)
- Governor: consistent with can_flow_to (6 properties)
- Consent threading: invariant through 10 composition layers
"""

from .agent_governor import create_agent_governor
from .carrier import CarrierFact, CarrierRegistry, DisplacementResult
from .consent import ConsentContract, ConsentRegistry, load_contracts
from .consent_label import ConsentLabel
from .primitives import (
    Candidate,
    FallbackChain,
    GatedResult,
    Selected,
    Veto,
    VetoChain,
    VetoResult,
)


def __getattr__(name: str):
    """Lazy imports to break circular dependency with shared.frontmatter."""
    if name == "CarrierIntakeResult":
        from .carrier_intake import CarrierIntakeResult

        return CarrierIntakeResult
    if name == "intake_carrier_fact":
        from .carrier_intake import intake_carrier_fact

        return intake_carrier_fact
    raise AttributeError(f"module 'agents._governance' has no attribute {name}")


from .governor import (
    GovernorDenial,
    GovernorPolicy,
    GovernorResult,
    GovernorWrapper,
    consent_input_policy,
    consent_output_policy,
)
from .labeled import Labeled
from .principal import Principal, PrincipalKind
from .revocation import (
    PurgeResult,
    RevocationPropagator,
    RevocationReport,
    check_provenance,
)
from .revocation_wiring import (
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
]
