"""agentgov — Computational constitutional governance for AI agent systems.

Pure governance logic with algebraic guarantees:
- ConsentLabel: join-semilattice (associative, commutative, idempotent)
- Labeled[T]: functor (identity, composition)
- Principal: non-amplification (bound <= delegator authority)
- Governor: consistent with can_flow_to
- ProvenanceExpr: PosBool(X) semiring
- VetoChain: deny-wins composition
- Says: DCC-style principal attribution monad
"""

from agentgov.agent_governor import create_agent_governor
from agentgov.carrier import CarrierFact, CarrierRegistry, DisplacementResult
from agentgov.consent import ConsentContract, ConsentRegistry, load_contracts
from agentgov.consent_label import ConsentLabel
from agentgov.governor import (
    GovernorDenial,
    GovernorPolicy,
    GovernorResult,
    GovernorWrapper,
    consent_input_policy,
    consent_output_policy,
)
from agentgov.labeled import Labeled
from agentgov.primitives import (
    Candidate,
    FallbackChain,
    GatedResult,
    Selected,
    Veto,
    VetoChain,
    VetoResult,
)
from agentgov.principal import Principal, PrincipalKind
from agentgov.provenance import ProvenanceExpr
from agentgov.revocation import (
    PurgeResult,
    RevocationPropagator,
    RevocationReport,
    check_provenance,
)
from agentgov.says import Says

__version__ = "0.2.0"

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
    "DisplacementResult",
    # Governor
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
    # Compositional primitives
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
