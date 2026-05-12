# Changelog

## 0.2.0 (2026-05-11)

### Added

- **Governance hooks** (`agentgov.hooks`): 5 production-tested checks extracted from hapax-council:
  - `scan_pii` — SSN, email, phone, card number detection
  - `scan_single_user_violations` — multi-user/auth scaffolding patterns
  - `scan_attribution_entities` — product-company misattributions
  - `scan_provenance_references` — ungrounded system capability claims
  - `scan_management_boundary` — LLM-generated management feedback
  - `validate_all()` — run any subset of hooks, returns list of `HookResult`
- `py.typed` marker (PEP 561)

### Changed

- URLs point to standalone `hapax-systems/agentgov` repository
- PyPI and license badges in README
- README notes production origin (extracted from hapax-council, governing 200+ agents)

## 0.1.0 (2026-04-28)

### Added

- `ConsentLabel` — DLM join-semilattice (associative, commutative, idempotent)
- `Labeled[T]` — LIO-style functor with consent label + provenance
- `Principal` — sovereign/bound delegation with non-amplification
- `ProvenanceExpr` — PosBool(X) semiring (tensor + plus)
- `VetoChain` — deny-wins compositional constraint evaluation
- `Says` — DCC-style principal attribution monad
- `GovernorWrapper` — per-agent input/output policy enforcement
- `ConsentRegistry` + `RevocationPropagator` — cascading consent revocation
- `CarrierRegistry` — carrier dynamics with displacement
- `create_agent_governor()` — factory from axiom bindings
- Hypothesis property tests for all algebraic guarantees
