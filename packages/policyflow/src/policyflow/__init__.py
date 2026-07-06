"""policyflow — Computational constitutional governance for AI agent systems.

Pure governance logic with algebraic guarantees:
- ConsentLabel: join-semilattice (associative, commutative, idempotent)
- Labeled[T]: functor (identity, composition)
- Principal: non-amplification (bound <= delegator authority)
- Governor: consistent with can_flow_to
- ProvenanceExpr: PosBool(X) semiring
- VetoChain: deny-wins composition
- Says: DCC-style principal attribution monad
"""

from policyflow.agent_governor import create_agent_governor
from policyflow.carrier import CarrierFact, CarrierRegistry, DisplacementResult
from policyflow.consent import ConsentContract, ConsentRegistry, load_contracts
from policyflow.consent_label import ConsentLabel
from policyflow.governor import (
    GovernorDenial,
    GovernorPolicy,
    GovernorResult,
    GovernorWrapper,
    consent_input_policy,
    consent_output_policy,
)
from policyflow.hooks import (
    HookResult,
    scan_attribution_entities,
    scan_management_boundary,
    scan_pii,
    scan_provenance_references,
    scan_single_user_violations,
    validate_all,
)
from policyflow.labeled import Labeled
from policyflow.primitives import (
    Candidate,
    FallbackChain,
    GatedResult,
    Selected,
    Veto,
    VetoChain,
    VetoResult,
)
from policyflow.principal import Principal, PrincipalKind
from policyflow.provenance import ProvenanceExpr
from policyflow.revocation import (
    PurgeResult,
    RevocationPropagator,
    RevocationReport,
    check_provenance,
)
from policyflow.says import Says

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
    # Governance hooks
    "HookResult",
    "scan_pii",
    "scan_single_user_violations",
    "scan_attribution_entities",
    "scan_provenance_references",
    "scan_management_boundary",
    "validate_all",
]
