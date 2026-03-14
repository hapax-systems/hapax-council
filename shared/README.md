# shared/ — Consent Algebra and Governance Infrastructure

This directory contains the formal types and enforcement infrastructure that the theory document specifies and the papers evaluate. Each module below maps to a section of the [computational constitutional governance spec](../docs/superpowers/specs/2026-03-13-computational-constitutional-governance.md).

## Theory-to-code map

### Consent algebra (Paper A)

| Concept | Theory § | Source | Proven properties | Tests |
|---------|----------|--------|-------------------|-------|
| Principal (sovereign/bound) | §3.2–3.4 | [`principal.py`](principal.py) | Non-amplification, delegation narrowing, sovereign totality (3 hypothesis) | [`tests/test_principal.py`](../tests/test_principal.py) |
| ConsentLabel (DLM lattice) | §5.3, DD-1, DD-3 | [`consent_label.py`](consent_label.py) | Join commutativity, associativity, idempotence; bottom identity; reflexivity, antisymmetry, transitivity; LUB; monotonicity; bottom flows to all (10 hypothesis) | [`tests/test_consent_label.py`](../tests/test_consent_label.py) |
| Labeled[T] (LIO wrapper) | §5.6, DD-21, DD-23 | [`labeled.py`](labeled.py) | Functor identity, functor composition, join_with commutativity, provenance union, can_flow_to delegation (5 hypothesis) | [`tests/test_labeled.py`](../tests/test_labeled.py) |
| ConsentContract / ConsentRegistry | §3, DD-3 | [`consent.py`](consent.py) | Contract lifecycle, registry gating | [`tests/test_consent.py`](../tests/test_consent.py) |
| GovernorWrapper (AMELI) | §7 | [`governor.py`](governor.py) | Consent consistency with can_flow_to (1 hypothesis) | [`tests/test_governor.py`](../tests/test_governor.py) |
| RevocationPropagator | DD-8, DD-23 | [`revocation.py`](revocation.py) | Provenance subset iff valid (1 hypothesis) | [`tests/test_revocation.py`](../tests/test_revocation.py) |
| Frontmatter IFC boundary | DD-11, DD-12 | [`frontmatter.py`](frontmatter.py) | Label extraction, provenance extraction, labeled_read | [`tests/test_frontmatter_consent.py`](../tests/test_frontmatter_consent.py) |

### Constitutional governance (Paper C)

| Concept | Theory § | Source | Tests |
|---------|----------|--------|-------|
| Axiom, Implication, load/validate | §2, §4 | [`axiom_registry.py`](axiom_registry.py) | [`tests/test_axiom_registry.py`](../tests/test_axiom_registry.py) |
| T0 hot path / cold path enforcement | §4, §7 | [`axiom_enforcement.py`](axiom_enforcement.py) | [`tests/test_axiom_enforcement.py`](../tests/test_axiom_enforcement.py) |
| Precedent store (case law) | §4.4 | [`axiom_precedents.py`](axiom_precedents.py) | [`tests/test_axiom_precedents.py`](../tests/test_axiom_precedents.py) |
| T0 pattern scanning | §4.2 | [`axiom_patterns.py`](axiom_patterns.py) | [`tests/test_axiom_patterns.py`](../tests/test_axiom_patterns.py) |
| Sufficiency probes (positive requirements) | §4.3 | [`sufficiency_probes.py`](sufficiency_probes.py) | [`tests/test_sufficiency_probes.py`](../tests/test_sufficiency_probes.py) |
| Axiom binding completeness | §8.2 | [`axiom_bindings.py`](axiom_bindings.py) | [`tests/test_axiom_bindings.py`](../tests/test_axiom_bindings.py) |
| ConstitutiveRule (Searle/Boella) | §4.1 | [`constitutive.py`](constitutive.py) | [`tests/test_constitutive.py`](../tests/test_constitutive.py) |
| Governance coherence checker | §4 | [`coherence.py`](coherence.py) | [`tests/test_coherence.py`](../tests/test_coherence.py) |

### Carrier dynamics (Paper B)

| Concept | Theory § | Source | Tests |
|---------|----------|--------|-------|
| CarrierFact, displacement dynamics | §9 | [`carrier.py`](carrier.py) | [`tests/test_carrier.py`](../tests/test_carrier.py) |

## Algebraic properties verified

### ConsentLabel — join-semilattice with bottom

The 10 properties that prove ConsentLabel forms a correct join-semilattice:

1. **Join commutativity**: `a ⊔ b == b ⊔ a`
2. **Join associativity**: `(a ⊔ b) ⊔ c == a ⊔ (b ⊔ c)`
3. **Join idempotence**: `a ⊔ a == a`
4. **Bottom is join identity**: `a ⊔ ⊥ == a`
5. **Reflexivity**: `a ⊑ a`
6. **Antisymmetry**: `a ⊑ b ∧ b ⊑ a → a == b`
7. **Transitivity**: `a ⊑ b ∧ b ⊑ c → a ⊑ c`
8. **Join is LUB**: `a ⊑ (a ⊔ b) ∧ b ⊑ (a ⊔ b)`
9. **Monotonicity**: `a ⊑ b → (a ⊔ c) ⊑ (b ⊔ c)`
10. **Bottom flows to all**: `⊥ ⊑ a`

### Labeled[T] — functor laws

1. **Map identity**: `x.map(id) == x`
2. **Map composition**: `x.map(f).map(g) == x.map(g ∘ f)`
3. **Join_with label commutativity**: `a.join_with(b)[0] == b.join_with(a)[0]`
4. **Provenance union**: `a.join_with(b)[1] == a.provenance ∪ b.provenance`
5. **Can_flow_to delegation**: `x.can_flow_to(t) == x.label.can_flow_to(t)`

### Principal — delegation invariants

1. **Non-amplification**: `p.delegate(s).authority ⊆ p.authority`
2. **Delegation chain narrowing**: chain of delegates produces monotonically narrowing authority
3. **Sovereign totality**: `sovereign.can_delegate(any_scope) == True`

All properties are universally quantified via Hypothesis (property-based testing), not example-based. Hypothesis generates random inputs across the type's domain and verifies the property holds for all of them.

## Reading the code as a researcher

**PL/Security researchers** (Paper A): Start with `consent_label.py` — you'll recognize DLM owner-set-of-readers labels. Then `labeled.py` for the LIO-style wrapper. Then `governor.py` for AMELI-pattern boundary enforcement. The test files contain the algebraic proofs.

**MAS researchers** (Papers B, C): Start with `constitutive.py` for Searle/Boella constitutive rules. Then `axiom_registry.py` + `axiom_enforcement.py` for the norm refinement pipeline. Then `carrier.py` for epistemic carrier dynamics.

**AI Safety researchers** (Paper C): Start with `axiom_enforcement.py` (hot/cold path compliance). Then `sufficiency_probes.py` (positive requirement verification — the hard part of governance). Then `axiom_precedents.py` (case law accumulation).

## Module index

Beyond the formal types above, this directory contains:

- **config.py** — Model aliases, LiteLLM/Qdrant clients, embedding, `DATA_DIR`
- **cycle_mode.py** — dev/prod mode switching, threshold adjustment
- **dimensions.py** — 11 profile dimensions (5 trait, 6 behavioral)
- **frontmatter.py** — Canonical frontmatter parser + IFC boundary (labeled_read)
- **agent_registry.py** — AgentManifest (4-layer schema), query by capability/axiom/RACI
- **notify.py** — ntfy + desktop notifications
- **document_registry.py** — Document type classification
- **service_tiers.py** — Infrastructure service dependency tiers
