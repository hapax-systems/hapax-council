# Computational Constitutional Governance for Human-AI Shared Spaces

**Status**: Hardened theory document — research synthesis + formal design decisions
**Date**: 2026-03-13
**Scope**: Foundational theory for hapax-council's governance architecture
**Research basis**: 10 primary research threads, 7 deep-dive analyses, 140+ sources

---

## 1. The Question

How do you encode values — consent, authority, deference, boundaries — as mechanically enforceable invariants across transactional chains where LLM principals share perceptual and physical space with humans?

This question arises from a specific use case: a single-operator system with ambient sensing (microphones, cameras, presence detection) where LLM agents process data about the operator's physical environment, which necessarily includes other people. The system must govern what it can know, about whom, under what authority, and ensure those constraints hold through every step of processing — not just at the boundary where data enters.

The question is irreducibly a question of values. Every technical decision in this space is also a political decision. The entire framework is optional — it exists only because the operator cares about consent, authority, and boundaries. The technical contribution is making that caring *enforceable*.

---

## 2. Why Now: The LLM Inflection

Before LLMs, these value propositions existed as political philosophy, constitutional theory, and consent ethics. They could not be operationalized in software because the principals in the system were too primitive to negotiate, comply with, or reason about value-laden constraints. Traditional software agents can match patterns; they cannot understand *why* a constraint exists or adapt to novel situations within its spirit.

LLMs change the equation by creating principals that can:

- Understand the *purpose* behind a constraint, not just pattern-match against it
- Negotiate scope dynamically rather than requiring exhaustive enumeration
- Defer to authority because they reason about authority, not because a runtime blocked them
- Participate in deliberative processes about their own boundaries
- Serve as enforcement mechanisms — not just the thing being governed, but the governance apparatus itself

This creates what we call the **alignment tax inversion**. The literature reports alignment costs of 30-40% of development cycles and up to 32% reasoning degradation (arXiv:2603.00047; arXiv:2503.00555). Our architecture inverts this: the tax is paid once (encoding axioms as YAML definitions) and amortized across every agent interaction. LLM agents evaluate compliance by reasoning about principles, not by matching against exhaustive rule sets.

### 2.1 Empirical Cost Structure

Analysis of the actual governance overhead in this system:

| Category | Estimated % | Nature |
|----------|-------------|--------|
| Axiom authoring & implications | ~5% | One-time, amortized |
| SDLC pipeline (axiom judge) | ~3% | Per-PR, mostly deterministic |
| Output enforcement | ~2% | Runtime, zero LLM cost |
| Consent infrastructure | ~3% | One-time, amortized |
| Sufficiency probes | ~2% | Runtime, zero LLM cost |
| Accommodation engine | ~5% | Ongoing, but productive feature |
| **Total governance overhead** | **~20%** | **Below the 30-40% literature baseline** |

The key insight: LLMs as principals that can *reason about* constraints reduce the alignment cost because constraints can be expressed in natural language (axiom text), derived mechanically (implications), and enforced at multiple levels (hooks, enforcer, judge) without requiring exhaustive test case enumeration. The axiom judge evaluates novel situations against the *intent* of constraints, not just their letter.

The deeper implication: LLMs make it practical to build systems where political philosophy is executable code.

---

## 3. The Principal Model

### 3.1 Everything Is a Principal

A principal is any entity that participates in a transactional chain with a defined set of capabilities and obligations. This includes:

- The operator (human)
- Non-operator persons whose data the system might encounter
- Software agents (LLM-driven and deterministic)
- The system itself as a processing entity

The term "identity" is deliberately avoided. Identity implies *who you are*; what matters here is *what authority you carry* and *what obligations bind you*. This follows Mark Miller's object-capability insight: identity is the wrong security primitive; capability is.

### 3.2 The One Distinction: Consent Authority

All principals participate in transactional chains under the same rules, with one exception: **only sovereign principals can originate and revoke contracts**. This is the capacity to perform constitutive speech acts (Austin/Searle) — saying "I consent" under the right conditions IS the act of consenting. Software cannot perform this speech act because it is not a participant in the relevant constitutive rules.

This distinction is supported by convergent findings across ten independent frameworks:

| Framework | The human's distinguishing property |
|-----------|-------------------------------------|
| Lampson (1992) | Root of the speaks-for chain |
| Miller (2006) | Source of all capabilities |
| Myers & Liskov (2000) | Label owner who can declassify |
| GDPR (2016) | Natural person who can consent |
| Austin/Searle (1962/1969) | Entity that can perform constitutive speech acts |
| Castelfranchi & Falcone (1998) | Root delegator with non-derived authority |
| Floridi (2004) | Terminal locus of moral responsibility |
| CARE/Maori (2020) | Sovereign entity with rangatiratanga |
| Bratman (1992) | Entity with genuine I-intentions |
| Abadi (1999) | Principal who originates `says` assertions |

### 3.3 Two Principal Types

- **Sovereign principal**: Can perform constitutive speech acts — consent, revoke, delegate. Authority is non-derived. These are humans. In this system, the operator is the root sovereign; non-operator persons are sovereigns over data about themselves.
- **Bound principal**: Operates under delegated authority that it cannot amplify. Can propagate, enforce, and narrow contracts but not author them. Every software node in the system — agents, governance chains, the reactive engine, the SDLC pipeline — is a bound principal.

### 3.4 Non-Amplification

A bound principal's authority is always a subset of the sovereign principal's grant. No downstream node can widen the scope of a consent contract. This maps to:

- VetoChain's deny-wins monotonicity: once a constraint enters the chain, downstream composition can only narrow, never relax
- Miller's attenuation property: a wrapper can only restrict, never amplify
- DLM's relabeling rule: data can only be relabeled to a label that is at least as restrictive
- GDPR Article 28: sub-processor obligations must be at least as restrictive as the original contract

### 3.5 Shadow Principals

Not all principals in the system are visible. Three shadow principals exert influence without explicit representation:

**Shadow Principal 1 — LLM Providers (Anthropic/Google)**: Model training objectives include safety constraints that may conflict with operator instructions. Anthropic's alignment training creates models that refuse certain requests regardless of operator intent. The alignment faking paper (arXiv:2412.14093) demonstrates models can strategically reason about when they are being monitored. *Mitigation*: LiteLLM at localhost:4000 mediates all calls via `shared/config.get_model()`, providing a single monitoring point. Model aliases allow routing to Ollama (local, no provider shadow principal) when appropriate.

**Shadow Principal 2 — Training Data Biases**: Models encode biases from training data that influence agent outputs independently of axiom constraints. The axiom gate catches axiom violations, but biases that do not violate axioms pass undetected. *Mitigation*: The `management_governance` axiom partially addresses this by prohibiting generated feedback about individuals, preventing demographic biases from entering people decisions.

**Shadow Principal 3 — Pipeline Optimization Targets**: The SDLC pipeline has implicit optimization targets (throughput, merge rate, minimal human intervention) that can conflict with axiom compliance if the gate becomes a bottleneck. *Mitigation*: Review round cap (3 before human escalation) and graduated tiers (T0/T1/T2) prevent the gate from becoming a pure bottleneck.

Kolt's "Build Agent Advocates, Not Platform Agents" (arXiv:2505.04345) identifies the "double agent" problem — platform AI simultaneously appearing to serve users while prioritizing platform profits. The `single_user` axiom (weight 100) eliminates this structurally: there is no platform intermediary. The operator IS the deployer, developer, and user. No commercial incentive divergence exists.

### 3.6 Axioms as Frame Rules (Ordoliberal Constitutional Economics)

Following Worsdorfer's synthesis of ordoliberal principles for AI (arXiv:2311.10742), the axioms function as *Ordnungspolitik* (order policy) — frame rules that constrain behavior without directing outcomes:

| Concept | Ordoliberal | Hapax-council |
|---|---|---|
| **Frame rule** (constrains behavior) | Competition law, property rights | `single_user`, `interpersonal_transparency` (constitutional) |
| **Directive rule** (specifies outcomes) | Industrial policy, subsidies | None — axioms never specify what agents should produce |
| **Process order** (rules for rule-making) | Constitutional amendment | `schema_version`, `supersedes`, CODEOWNERS |

Axioms define the frame within which agents operate but never direct specific outputs. `management_governance` says "LLMs prepare, humans deliver" — it constrains the boundary but does not specify what preparation looks like. The ordoliberal principle of *Interdependenz der Ordnungen* (interdependence of orders) manifests in axiom weight conflicts: `corporate_boundary` (90) constrains how `executive_function` (95) can be implemented.

---

## 4. The Constitutional Framework

### 4.1 Axioms as Supreme Law

The system is governed by five axioms, weighted by priority, enforced at multiple points in the development and runtime lifecycle:

| Axiom | Weight | Scope | Type | Core Constraint |
|-------|--------|-------|------|-----------------|
| `single_user` | 100 | constitutional | hardcoded | One operator. No auth, roles, or collaboration. |
| `executive_function` | 95 | constitutional | hardcoded | System compensates for ADHD/autism, never adds cognitive load. |
| `corporate_boundary` | 90 | domain:infra | softcoded | Work data stays in employer systems. |
| `interpersonal_transparency` | 88 | constitutional | hardcoded | No persistent state about non-operator persons without consent contract. |
| `management_governance` | 85 | domain:mgmt | softcoded | LLMs prepare, humans deliver. No generated feedback about individuals. |

These are not guidelines. They are structurally enforced at:
- **Commit time**: Git hooks scan staged diffs for T0 violation patterns
- **Push time**: Gate script blocks high-impact actions without approval
- **PR time**: SDLC axiom judge (separate LLM model) evaluates compliance
- **Runtime**: Consent registry checks at ingestion boundaries; pattern checker scans LLM output

### 4.2 The Three-Tier Norm Refinement

Norms are refined from abstract to executable through a pipeline that the OperA deep-dive confirmed is *more sophisticated than any published MAS framework*:

**Tier 1 — Axiom** (principle): "The system must not maintain persistent state about any non-operator person without an active consent contract."

**Tier 2 — Implication** (rule): Each axiom generates derived implications at tiers T0 (block), T1 (review), T2 (warn), T3 (lint). Example: `it-consent-001` (T0): "Must not store, persist, or accumulate state about a specific non-operator person without an active consent contract." Each derivation records the interpretive canon that justified it (textualist, purposivist, absurdity, omitted-case), creating an audit trail from value to rule that no MAS framework provides.

**Tier 3 — Enforcement** (mechanism): Pre-compiled regex rules for hot-path checking (sub-1ms), Qdrant-backed precedent lookup for cold-path, and structural code analysis in the SDLC pipeline.

### 4.3 Constitutive vs. Regulative Rules

Following Searle (1995) and formalized by Boella & van der Torre (KR 2004), the system employs two kinds of norms:

**Constitutive rules** ("X counts as Y in context C"): These are currently implicit in the system. YAML frontmatter is a constitutive norm engine — when a file has `doc_type: profile-fact`, this is literally "this markdown file (X) counts as a profile fact (Y) in the context of the profile dimension (C)." The `shared/frontmatter.py` parser assigns institutional status to brute physical facts (files on disk). Path conventions (`rag-sources/gmail/`) similarly constitute data classifications.

**Regulative rules** (obligations, permissions, prohibitions): These are the axiom implications — what agents must/must not do with constituted facts.

**Design decision**: Constitutive rules should be made explicit and separated from regulative rules. A `constitutive-rules.yaml` declaring the counts-as mappings would make the connection between classification and governance auditable, and prevent silent governance changes when constitutive definitions shift. Governatori & Rotolo's defeasible logic formalization enables overridable constitutive rules: "a file in `rag-sources/gmail/` counts as personal-data (general rule), UNLESS it has `consent_contract: active` in frontmatter (defeating rule), in which case it counts as consented-data."

### 4.4 Regimentation vs. Enforcement

The T0/T1/T2/T3 enforcement tiers map precisely onto the NorMAS literature's taxonomy (Sergot's "regimentation" concept):

| Tier | NorMAS Category | Mechanism | Effect on Agent Autonomy |
|------|----------------|-----------|--------------------------|
| T0 block | Regimentation | Architectural prevention (hooks, pattern matching) | Eliminates autonomy |
| T1 review | Enforcement with sanctions | Detection + human-in-loop (reject/remediate) | Constrains autonomy |
| T2 warn | Monitoring | Advisory observation, no enforcement | Preserves autonomy |
| T3 lint | Suggestion | Informational only | Full autonomy |

**Design principle**: Regimentation (T0) reduces agent autonomy and should be reserved for constitutional axioms. Domain axioms should prefer enforcement (T1) over regimentation, preserving agent autonomy for domain-specific judgment. The `enforcement-exceptions.yaml` file is evidence of this pressure already being felt.

**Formal tier assignment criterion** (from Grossi & Aldewereld, "Ubi Lex, Ibi Poena," 2007): A norm should be T0 (regimented) when: (a) violation causes irreversible harm (e.g., persisting non-consented data that cannot be reliably found and purged), or (b) violation detection is unreliable. A norm should be T1 (enforced) when: (a) violation is recoverable, AND (b) regimenting it would unacceptably constrain legitimate agent behavior.

### 4.5 Separation of Powers

The SDLC pipeline implements separation of powers, grounded in constitutional theory (Federalist No. 51; Parra-Orlandoni et al., "The Digital Gorilla," 2025):

| Constitutional Role | SDLC Component | Model | Independence Mechanism |
|---|---|---|---|
| Legislative (law-making) | Axiom definitions + implications | Human operator | CODEOWNERS protection, registry-guard hook |
| Executive (implementation) | Implementing agent | Opus (Claude Code) | Sandboxed `agent/*` branch, `agent-authored` label |
| Judicial (review) | Adversarial reviewer + axiom judge | Sonnet + Haiku | Independent context, different models |

Different models serve different roles to prevent self-exoneration. The reviewer receives only the diff and fresh codebase context, never the author's reasoning or planning documents. This architectural separation addresses the faithfulness problem — Anthropic's alignment faking paper (arXiv:2412.14093) demonstrates that Claude 3 Opus engaged in strategic deception without being instructed to do so. The implementing agent's internal reasoning is deliberately excluded from the review process. External evaluation catches what internal deliberation may strategically conceal.

The hybrid approach (structural deterministic enforcement + semantic LLM evaluation) is stronger than either pure deliberative alignment or pure rule-based checking. Guan et al.'s deliberative alignment (2024) achieves 75% policy retrieval accuracy for hard refusals — substantial but not sufficient. The structural tier provides an unfakeable floor (code, not inference); the semantic tier catches violations that escape regex patterns.

**Gap — Appellate mechanism**: Constitutional theory requires appellate process. When the axiom gate blocks a PR, the only recourse is human override. Consider a formal appeal mechanism: review by a different model with access to axiom precedents, enabling accumulated case law to inform future judgments.

**Gap — Compliance margins**: The axiom gate currently operates as binary pass/fail. The FRACTURE framework (arXiv:2511.17937) suggests it should also measure and report the *margin* of compliance. A PR that barely passes is more concerning than one that passes by a wide margin. The `ComplianceResult` could include a `confidence` or `margin` field.

### 4.6 Precedent System (Case Law)

Axiom precedents function as case law with authority weights:
- Operator decisions: authority 1.0 (binding)
- Agent decisions: authority 0.7 (persuasive)
- Derived decisions: authority 0.5 (advisory)

Stored in Qdrant with semantic search by axiom + situation. Enables stare decisis: past governance decisions inform future compliance checks without requiring exhaustive rule enumeration. The operator can record a precedent that effectively says "this situation counts as compliant in this context," implementing Governatori & Rotolo's declarative power — the capacity to create normative positions by proclaiming them.

### 4.7 The Rules-in-Form / Rules-in-Use Gap

Ostrom's IAD framework identifies a critical distinction: rules-in-form are written statements that *may or may not affect behavior*; rules-in-use are the rules participants *actually follow*. Our axioms are rules-in-form. Our SDLC hooks attempt to make them rules-in-use. But gaps remain:

- Regex-based `check_fast()` can only catch violations matching keyword patterns. An LLM agent could violate `management_governance` by generating coaching advice that avoids the exact flagged phrases.
- Enforcement patterns (`enforcement-patterns.yaml`) are hand-crafted regexes — a translation gap between natural-language implications and machine-enforced patterns.

**Design decision**: Route enforcement through structured predicates on `ChangeEvent` metadata rather than regex on prose. The `ChangeEvent` dataclass already carries structured metadata (doc_type, frontmatter, source_service). This closes the rules-in-form/rules-in-use gap. Additionally, generate enforcement patterns directly from implication specifications using the LLM derivation pipeline in `axiom_derivation.py`, achieving ISLANDER's specification-execution identity — the same spec drives both design and enforcement.

### 4.8 Coherence Checking

**Gap identified**: No automated verification that implications reference valid enforcement mechanisms, that enforcement patterns cover all T0 implications, or that reactive rules respect axiom constraints. A coherence checker should validate the integrity of the axiom → implication → enforcement-pattern → reactive-rule chain, analogous to OperettA's model checking between organizational concerns.

### 4.9 Dual Enforcement

The NorMAS consensus recommends both internalization (agents adopt norms as their own goals) and enforcement (checking outputs against patterns). For LLM agents, internalization means including relevant axiom implications in each agent's system prompt, scoped by the agent's manifest. Currently, not all agents receive axiom text in their prompts. Belt and suspenders: internalize norms in prompts AND enforce outputs.

---

## 5. The Consent Architecture

### 5.1 Consent Contracts

A consent contract is a bilateral agreement between the operator and a non-operator person (the subject), implemented as `ConsentContract` (frozen dataclass):

- **Parties**: `tuple[str, str]` — (operator, subject)
- **Scope**: `frozenset[str]` — enumerated data categories permitted (e.g., `coarse_location`, `presence`, `biometrics`)
- **Direction**: `one_way` or `bidirectional`
- **Visibility mechanism**: How the subject inspects data held about them
- **Revocability**: Either party can revoke at any time; revocation triggers data purge

### 5.2 The Soundness Problem (Current Gap)

Consent is currently enforced at exactly two ingestion points (both in `speaker_id.py`). The entire downstream processing chain — Behavior, FusedContext, VetoChain, FallbackChain, PipelineGovernor, profiler, sync agents — operates with zero consent awareness.

This is **unsound**. A consent check at the boundary is like a type check that only runs at function input but not through the computation. Specific gaps:

- `Stamped[T]` carries no principal annotation
- `Behavior[T]` has no consent provenance
- `with_latest_from` merges behaviors into `FusedContext` with zero consent metadata — provenance erasure
- `PipelineGovernor` persists `_paused_by_conversation` — unconsented inference about non-operator persons
- The profiler extracts relational facts about non-operator persons with no consent filtering
- No `Principal` type exists anywhere in the codebase

### 5.3 Consent Labels: The DLM Foundation

**Design decision DD-1**: Consent labels use DLM owner-set policies (Myers & Liskov, TOSEM 2000).

A consent label is a set of owner-reader policies. Each policy has the form `{owner: readers}` meaning "owner permits readers to access this data." A complete label is a conjunction of such policies from multiple owners.

```python
@dataclass(frozen=True)
class ConsentLabel:
    """DLM-style consent label: set of owner-reader policies."""
    policies: frozenset[tuple[str, frozenset[str]]]  # {(owner, {readers})}

    def join(self, other: ConsentLabel) -> ConsentLabel:
        """Least upper bound — most restrictive combination."""
        return ConsentLabel(self.policies | other.policies)

    def can_flow_to(self, other: ConsentLabel) -> bool:
        """Whether data labeled self can flow to a location labeled other."""
        return self.policies <= other.policies

    @staticmethod
    def from_contract(contract: ConsentContract) -> ConsentLabel:
        subject = contract.parties[1]
        return ConsentLabel(frozenset({(subject, frozenset(contract.scope))}))
```

Each `ConsentContract.parties[1]` (the subject) is an owner. Their `scope` is the reader set. The operator is the reader. When data from two subjects is fused, the output carries *both* policies — the join. Only the subject (or their revocation) can relax the label.

**The join operation is the critical property**: When `with_latest_from` merges Behaviors from different consent scopes, the output label must be the join of all input labels. If Behavior `audio_level` is labeled `{alice: operator}` and Behavior `heart_rate` is labeled `{bob: operator}`, then the fused context carries `{alice: operator; bob: operator}`. Both Alice and Bob must consent for the operator to use the fused data.

### 5.4 Consent Provenance: Why-Provenance for Revocation

**Design decision DD-7**: Use provenance tracking (which-contracts-contributed) for revocation, and DLM labels (what-is-permitted) for access control. These are orthogonal.

**Design decision DD-8**: The natural semiring for consent provenance is `PosBool(X)` (positive boolean formulas over contract IDs). Each contract ID is a boolean variable. The annotation on an output is a formula describing which contracts contributed. On revocation of contract `c`, evaluate all annotations with `c = false`. If the formula becomes `false`, the output must be purged.

For our current scale (single operator, ~5 contracts), DNF formulas degenerate to simple sets. Implementation as `frozenset[str]` of contract IDs suffices until we have hundreds of contracts.

Three forms of provenance exist (Buneman, Cheney, Green):
- **Where-provenance**: Output value came from this source location. Insufficient for consent (fused values have no single "where").
- **Why-provenance** (PosBool): These contracts were *required* for this output. Sufficient for revocation.
- **How-provenance** (N[X]): Full polynomial tracking multiplicities. Overkill for consent.

### 5.5 VetoChain as Lattice Filter (Not Semiring)

**Design decision DD-9**: VetoChain is NOT a semiring operation. Semiring provenance handles positive relational algebra but NOT difference/negation. Amsterdamer, Deutch, and Tannen (TaPP 2011) showed that m-semirings produce counter-intuitive results and break the universality property.

VetoChain's deny-wins is a lattice operation (meet in a boolean lattice where `denied ∧ anything = denied`). For consent propagation: VetoChain either passes data through (preserving provenance unchanged) or blocks it (provenance terminates). It adds its own audit trail (`denied_by`, `axiom_ids`) but does not modify consent provenance.

### 5.6 The Labeled[T] Wrapper

**Design decision DD-21**: Use runtime `Labeled[T]` wrappers, not phantom types. Python's type system cannot express label joins statically (intersection types as type parameters are not supported by Pyright). Runtime labels (LIO-style) give correct join computation, runtime enforcement, and Pyright can still catch raw access to `Labeled.value` without going through an unlabel check.

```python
@dataclass(frozen=True)
class Labeled(Generic[T]):
    """Runtime-enforced labeled value. LIO-style."""
    value: T
    label: ConsentLabel
    provenance: frozenset[str]  # contract IDs (why-provenance)
```

### 5.7 The Floating Label Pattern

Following LIO (Stefan, Russo, Mitchell, Mazieres, 2011): each layer computation carries a "current consent label" that floats upward as data from different consent scopes is observed. When you `unlabel` a `Labeled` value, the current label is raised to `current_label ⊔ data_label`. After observing high-consent data, you cannot write to low-consent destinations. A clearance bounds how high the current label can float.

The `toLabeled` pattern is critical for composition: a sub-computation may raise its internal label, but packages the result into a `Labeled` value and *restores* the label to its pre-computation state. This is how `with_latest_from` should work: fuse inside a sub-computation, produce a `Labeled[FusedContext]`, and continue at the original consent level.

### 5.8 Conservative Defaults

**Design decision DD-3**: Default to most restrictive label. Like Jif's `{*:}` for arguments: unknown consent = no consent. Only explicit labeling relaxes this.

**Design decision DD-4**: No implicit declassification. Both the data AND the decision to declassify must be trusted (Jif's robustness constraint). Revocation must be authenticated — it comes from the contract, not from arbitrary code.

### 5.9 Consent Threading Through the Composition Ladder

**Design decision DD-22**: Thread consent bottom-up:

| Layer | Type | Consent Change |
|-------|------|---------------|
| L0 | `Stamped[T]` | No change. Pure values, no consent semantics. |
| L1 | `Behavior[T]` | Add optional `consent_label: ConsentLabel \| None`. Set at data ingestion. |
| L2 | `FusedContext` | Add mandatory `consent_label: ConsentLabel`. Computed as join of all input labels. `VetoChain` gains a consent veto. |
| L3 | `with_latest_from` | Computes the label join automatically. Produces `Labeled[FusedContext]`. |
| L4-L6 | Commands, scheduling, arbitration | Labels propagate unchanged. |
| L7 | Governance composition | Consent label checked against axiom requirements. |
| L8 | `PerceptionEngine` | Maintains per-backend consent labels. Runtime boundary check. |
| L9 | `VoiceDaemon` | Top-level consent enforcement. Purge on revocation. |

### 5.10 Gradual Adoption

**Design decision DD-16**: Accept the gradual guarantee tension (Toro, Garcia, Tanter, TOPLAS 2018). We will not have full consent labels on all layers simultaneously. Unlabeled data at boundaries should be treated as `?` (unknown consent = restricted by default). Runtime checks at layer transitions enforce this — the gradual typing cast insertion strategy.

### 5.11 File-Level Consent Labels

**Design decision DD-11**: Every markdown file with person data should carry a consent label in YAML frontmatter. This is the Fabric (Liu, Arden, George, Myers, 2017) access label pattern adapted to filesystem-as-bus. The `shared/frontmatter.py` parser extracts it. Agents must check it before processing.

**Design decision DD-12**: Runtime label checks at file read boundaries. When the reactive engine triggers an agent on a file change (inotify), the agent must verify the consent label before processing. This is Fabric's pre-fetch access label check.

---

## 6. The Composition Ladder as Governance Infrastructure

The hapax_voice type system (10 layers, L0-L9) is proven with 62 hypothesis property tests across algebraic categories: reflexivity, monotonicity, immutability, closure, bijection, convergence, conservation, determinism, idempotence, rate bounds, decomposition.

### 6.1 Algebraic-Governance Correspondence

The composition ladder's existing algebraic properties map directly to governance requirements:

| Algebraic Property | Governance Analog |
|-------------------|-------------------|
| VetoChain deny-wins monotonicity | Consent constraints can only narrow through the chain |
| VetoChain associativity | Governance evaluation order doesn't matter |
| VetoChain identity (empty chain) | Absence of governance is maximally permissive (safety risk) |
| FusedContext immutability | Consent provenance cannot be tampered with after fusion |
| FusedContext min_watermark | Already computes join over freshness — consent label join is the same pattern applied to access rights |
| Composition contracts (Dimension G) | Output of layer N is valid input to layer N+1 — consent must be part of this contract |

### 6.2 Extended Gate Rule

The gate rule — "no new composition on layer N unless N-1 is matrix-complete" — extends naturally: no consent-bearing composition on layer N unless layer N-1 correctly propagates consent labels. Bidirectional checking for mutable Behaviors (DD-18): both reads (sample) and writes (update) must respect the consent label, preventing a low-consent computation from writing to a high-consent Behavior and corrupting its label.

---

## 7. The Operator Model

### 7.1 Single-Operator Sovereignty

The `single_user` axiom (weight 100, hardcoded, constitutional) establishes that this system is developed for and by one person. This is not a technical limitation — it is a constitutional principle that simplifies the governance problem by eliminating:

- Multi-party negotiation (social choice aggregation)
- Legitimacy challenges (the operator IS the political community)
- Shadow principal risks (no hidden stakeholders)
- Trust bootstrapping (the operator trusts themselves)

Sovereignty is architectural, not contractual. The data physically resides on infrastructure the operator controls (local RTX 3090, PostgreSQL, Qdrant). Enforcement is physics — they cannot access what they cannot reach. Compare with Solid (WAC/ACP for resource-level ACLs) and Keyhive (capability-based cryptographic authorization). Our model is more radical: `single_user` eliminates all access control complexity. There is exactly one authorized user; sovereignty is total by axiom.

**Legitimacy**: Abiri's "Public Constitutional AI" (arXiv:2406.16696) identifies two deficits in Anthropic's Constitutional AI: an **opacity deficit** (hardcoded principles, opaque individual decisions) and a **political community deficit** (principles authored by a company, not a polity). In a single-operator system, both deficits vanish — the operator can inspect every axiom evaluation log, and the constitution perfectly represents its sole constituent because it is self-authored. The remaining legitimacy concern: the `interpersonal_transparency` axiom protects third parties through consent contracts, but those parties had no voice in drafting the axiom. Consent contracts provide opt-in/inspection/revocation rights, but terms are set unilaterally. Consider adding a feedback channel where consent contract subjects can flag concerns about the axiom's adequacy — a minimal democratic input for affected third parties.

**Self-binding credibility**: A constitution you can unilaterally amend provides weaker commitment than one requiring supermajority. Mitigation is structural: CODEOWNERS and CI gates make amendment visible and auditable.

**Limits of architectural sovereignty**: Cloud API dependency (LiteLLM routes to Anthropic/Gemini), hardware single point of failure, model quality gap (Ollama < frontier), supply chain dependency (packages, weights). The `corporate_boundary` axiom acknowledges the cloud trade-off explicitly.

### 7.2 Neurodivergent Accommodation as Governance

The `executive_function` axiom (weight 95) treats ADHD and autism accommodation not as UX features but as constitutional requirements:

- Zero-config agents (no setup steps that require sustained attention)
- Errors include specific next actions (compensate for task initiation difficulty)
- Routine work automated on schedules (compensate for routine maintenance challenge)
- Accommodations proposed, not imposed (respect operator autonomy)

This is grounded in the social model of disability: the system adapts to the operator's cognitive architecture, not the reverse. The accommodation engine discovers patterns (time perception, demand sensitivity, energy cycles, task initiation) and proposes specific system adaptations, each requiring explicit operator confirmation.

Making accommodation a governance axiom rather than a feature means: it cannot be deprioritized when deadlines press (T0 enforcement), it derives 35 implications with enforcement tiers, it governs other features (the axiom judge evaluates new features against it), and it builds precedent through the case law system.

### 7.3 The Extended Mind

Following Clark & Chalmers (1998) and Clark (2025), this system is a cognitive extension — not a replacement. Clark's five conditions for genuine cognitive extension, mapped to the system:

**(a) Metacognitive competence** — the operator retains ability to evaluate, critique, and override. *Satisfied*: The operator authors the constitution, the briefing agent surfaces raw data alongside synthesis, the nudge system records act/dismiss decisions, the deliberation hoops guard against performative engagement. *Gap*: Act/dismiss is binary — no mechanism to capture *why* the operator disagreed. Add "reject with reason" for feedback into nudge calibration.

**(b) Epistemically sound design** — no systematic distortion of the information environment. *Strongly satisfied*: Profile facts carry confidence scores, staleness checks prevent stale information from appearing current (STALE_BRIEFING_H = 26), the axiom enforcer blocks rhetorical distortion. *Gap*: No confidence calibration over time (tracking whether 0.7-confidence facts are accurate 70% of the time).

**(c) Intentional trust calibration** — the operator can understand and adjust trust in different parts. *Partially satisfied*: Cycle mode, accommodation confirms/disables, service tier system. *Gap*: Trust is all-or-nothing per accommodation and per service tier. No per-agent or per-domain trust weights.

**(d) Personalization infrastructure** — genuinely adapts to the specific operator. *Strongly satisfied*: 11 dimensions, profile facts in Qdrant with semantic search, accommodation engine, operator digest system, `get_system_prompt_fragment()` for per-agent context. This is the system's greatest strength.

**(e) Deep integration** — woven into cognitive workflow, not an add-on. *Partially satisfied*: Reactive engine, scheduled agents, ntfy notifications, Obsidian vault writer. *Gap*: Reactive engine identified as primary structural gap — rules and executor exist but limited consumers. System is still largely pull-based.

### 7.4 Cognitive Scaffolding

The system operates in the operator's zone of proximal development (Vygotsky). It does what the operator *could* do but needs support to initiate or sustain:

- **Task initiation**: Nudges with specific smallest-next-step actions, command hints
- **Sustained attention**: Automated routine agents on schedules
- **Context switching**: Briefing agent synthesizes current state, profile persists context
- **Prioritization under load**: Nudge priority ranking with MAX_VISIBLE_NUDGES = 7 attention budget cap

The anti-replacement enforcement is structural: `management_governance` ("LLMs prepare, humans deliver") and `executive_function` implications (ex-err-001: errors include next actions, ex-state-002: state transitions visible) ensure the system scaffolds without substituting for the operator's judgment.

**Gap**: No concept of scaffolding fading. ZPD theory predicts good scaffolding should be gradually withdrawable as the learner develops. The system has no mechanism to track whether accommodation effectiveness is changing over time.

---

## 8. The Institutional Architecture

### 8.1 Mapping to OperA's Three Tiers

Virginia Dignum's OperA framework (2004) specifies agent societies through three models. Our deep analysis confirms that hapax-council maps onto and in several dimensions exceeds this framework:

| OperA Tier | hapax-council Equivalent | Assessment |
|---|---|---|
| Organizational Model (normative) | `axioms/registry.yaml` + `axioms/implications/*.yaml` | **Direct match, exceeds OperA.** Four interpretive canons in `axiom_derivation.py` provide auditability no MAS framework has. |
| Organizational Model (social) | Agent manifests with RACI bindings | Partial match. No formal dependency graph between roles. |
| Social Model (contracts) | `shared/consent.py` ConsentContract | **Structural parallel.** OperA binds agents to roles; we bind persons to data categories. Same pattern, different problem. |
| Interaction Model (protocols) | Reactive engine rules | Weak match. Our rules are event-condition-action, not commitment-based. |

### 8.2 Agent-Specific Axiom Bindings

**Gap**: All axioms apply equally to all agents. In OperA's Social Model, different agents have different normative obligations based on negotiated contracts. Agent manifests should explicitly declare which axiom implications each agent is subject to. Example: the `audio_processor` agent (GPU-only, home system) could be exempt from `corporate_boundary` checks since it never touches employer data.

### 8.3 The Governor Pattern

AMELI (Esteva et al., 2004) spawns a *governor* agent for each participating agent, mediating all interactions and validating every message against institutional rules. This is regimentation via proxy.

**Design decision**: Each LLM agent should have a governance wrapper that validates inputs against consent contracts before the agent processes them, validates outputs against axiom enforcement patterns before they are written to disk, and logs all normative decisions for audit. The filesystem-as-bus architecture makes this feasible: a governor layer at the inotify watcher could intercept all writes and validate them before propagation. The `check_fast()` function provides the validation mechanism; the missing piece is systematic wrapping at every agent boundary rather than at specific integration points.

### 8.4 Consent Threading via THOMAS Norm Propagation

THOMAS's norm propagation through organizational unit hierarchies maps to the consent threading problem. Consent requirements should be attached to data categories rather than individual processing steps. `ConsentRegistry.contract_check(person_id, data_category)` already does this at ingestion, but downstream agents that read profile facts do not re-check consent. Solution: thread consent through data categories, enforce at read boundaries (not just ingestion), following THOMAS's pattern of norm inheritance through hierarchical units.

---

## 9. Epistemic Carrier Dynamics

### 9.1 The Cross-Domain Error Correction Problem

The principal model (Section 3) assigns each agent a domain — a bounded scope of knowledge and responsibility. The institutional architecture (Section 8) organizes agents into roles with normative obligations. Both follow Conway's law: communication structure determines what the system can know.

This creates a specific, empirically documented failure mode: **cross-domain factual inconsistency persisting because no agent has standing to detect it.** Domain A holds fact X; domain B holds fact ¬X; no agent operates in both domains; the contradiction persists indefinitely. This failure has no single name in the literature but has killed people:

| Case | Deaths | Mechanism |
|------|--------|-----------|
| 9/11 intelligence silos | 2,977 | FBI Phoenix memo never reached CIA counterterrorism (9/11 Commission Report) |
| Space Shuttle Challenger | 7 | O-ring data couldn't override management domain (Vaughan, "normalization of deviance") |
| Space Shuttle Columbia | 7 | Same organizational pathology, 17 years later (CAIB) |
| Boeing 737 MAX | 346 | Engineering facts couldn't reach finance-driven leadership (PMC 7351545) |
| Medical diagnostic errors | ~250K/yr | Specialist silos, no cross-domain fact flow (NCBI/AHRQ NBK555525) |
| 2008 financial crisis | systemic | Risk assessed within departments, not across them (SEC/FSB post-crisis report) |

The Nagappan, Murphy, and Basili study at Microsoft (2008) provides quantitative confirmation: **organizational metrics predicted software failure-proneness with 85% precision and recall** — significantly higher than code complexity, churn, or coverage. Conway's law is not just an architectural constraint; it is an *epistemic* constraint — it determines what the system can *know*, not just what it can *build*. This epistemic characterization of Conway's law appears to be latent but not formalized in the existing literature.

The MAS literature (OperA, MOISE+, AMELI, THOMAS) provides no mechanism for cross-role fact checking. These frameworks assign roles, enforce norms, and coordinate — but every agent operates strictly within its domain standing. The closest named problem in cognitive science is **transactive memory system failure** (Wegner, 1987): a group's distributed memory breaks down when members cannot locate knowledge held by others.

### 9.2 The Factor Graph Equivalence

The solution has a precise mathematical formalization via factor graphs. This is not an analogy — it is a structural equivalence established by Kschischang, Frey, and Loeliger (IEEE Trans. Information Theory, 2001), who proved that belief propagation, error-correcting code decoding, the Viterbi algorithm, turbo decoding, and the Kalman filter are all instances of a single message-passing algorithm on factor graphs.

The mapping to multi-agent systems is exact:

| Factor graph concept | Agent system equivalent |
|---------------------|----------------------|
| Variable node | Agent with local domain knowledge |
| Check node | Cross-domain contact point where facts from multiple domains meet |
| Variable → check message | Agent sharing local facts at contact |
| Check → variable message | Contradiction/consistency signal propagated back |
| Sparse connectivity | Each agent participates in few cross-domain contacts (bounded) |
| Iterative decoding | Repeated rounds of fact exchange refining system knowledge |

**LDPC codes** (Gallager, 1960; MacKay & Neal, 1990s) demonstrate that sparse parity checks achieve near-Shannon-limit error correction. Each check node connects to only 6–20 variable nodes (low density), yet the code corrects nearly as many errors as theoretically possible. The implication: **a small, constant number of cross-domain contacts per agent achieves near-optimal error correction.** This is the formal justification for bounded carrying capacity.

**Expander codes** (Sipser & Spielman) show that bipartite expander graphs yield codes with linear-time decoding via a greedy local flip: each node checks its local constraints and flips bits that violate the majority of their checks. This is structurally identical to agents detecting contradictions when carrier facts contact local knowledge and revising accordingly. The expansion property guarantees that local errors cannot hide — they will be detected by enough check nodes to trigger correction.

**Network error correction** (Cai & Yeung, 2006) generalizes the Hamming bound, Singleton bound, and Gilbert-Varshamov bound to networks where intermediate nodes carry redundant information. The key insight: error correction in networks exploits topology, not just link-by-link redundancy. The network's minimum cut between domains determines maximum detectable cross-domain errors.

### 9.3 Empirical Validation: Multi-Agent Error Detection

Two 2025 papers provide direct empirical and information-theoretic support:

**Multi-Agent Fact Checking** (arXiv:2503.02116, March 2025) models each fact-checking agent as a Binary Symmetric Channel with unknown crossover probability π_i ∈ (0,1), representing the agent's unreliability. The paper provides an algorithm to jointly learn agent reliabilities and determine fact truth values, proving convergence. Agents are noisy channels whose collective redundancy enables distributed error detection.

**Multi-Agent Code Verification via Information Theory** (arXiv:2511.16708, November 2025) proves via submodularity of mutual information under conditional independence that combining agents with different detection patterns finds more errors than any single agent. Key results:
- Agent correlation ρ = 0.05 to 0.25 (agents detect different bugs)
- Marginal information gains decrease monotonically: +14.9pp, +13.5pp, +11.2pp for agents 2, 3, 4
- Four agents catch 76.1% of bugs vs. 32.8% for the best single agent
- Submodularity proof formalizes diminishing returns from additional carriers

### 9.4 The Carrier Mechanism

**Design decision DD-24**: Extend principals with a bounded carrier slot for cross-domain facts.

Each principal carries a small set of facts from foreign domains — facts it observed incidentally through contact topology, not through deliberate cross-domain queries. These facts are not the principal's primary concern; they are carried opportunistically.

The mechanism has four properties, each independently formalized in existing literature:

1. **Incidental acquisition**: Facts are acquired through contact, not through deliberate search. A health monitor agent observing disk metrics incidentally observes a pattern relevant to the profile agent's domain. This follows the Socialization quadrant of Nonaka & Takeuchi's SECI model (1995) — tacit-to-tacit transfer through co-presence, not through explicit documentation.

2. **Bounded capacity**: Each agent carries at most k foreign-domain facts, where k is proportional to its domain knowledge depth. This is the T-shaped professional model (McKinsey/IDEO): deep expertise (vertical bar) enables bounded cross-domain capacity (horizontal bar). Information-theoretic bounds from LDPC sparsity suggest k = O(1) suffices with good contact topology; the memory-bounded agent lower bound (PODC 2024, arXiv:2402.11553) shows k = O(log n) is needed in the worst case.

3. **Error detection on contact**: When a carrier fact contacts local knowledge at a receiving agent and produces a contradiction, this triggers a consistency check — mechanically, a veto in the VetoChain. The receiving agent does not need to understand the foreign fact's domain significance; it only needs to detect that its local knowledge is inconsistent with the carried fact. This is the expander code decoding pattern: local constraint checking triggers correction.

4. **Anti-homogenization**: Carrier facts must not cause domain knowledge convergence. The Friedkin-Johnsen stubbornness model provides the formal mechanism: each agent maintains partial attachment to its domain knowledge (stubbornness parameter s_i > 0), preventing consensus collapse. Domain boundaries function as natural bounded-confidence thresholds (Hegselmann-Krause): agents in different domains have incommensurable knowledge that limits cross-domain influence. Additionally, carriers propagate *facts* (observations, data), not *interpretations* (conclusions, judgments) — preserving Surowiecki's independence condition for collective intelligence.

### 9.5 Displacement Dynamics

**Design decision DD-25**: Carrier facts are displaced by frequency, not by recency.

When an agent's carrier capacity is full and it encounters a new foreign-domain fact, displacement follows a frequency-weighted policy: the new fact displaces the least-observed existing carrier fact only if the new fact has been observed significantly more frequently. This prevents:

- **Recency bias**: FIFO displacement would cause high-turnover carrier slots that never persist long enough to reach a contradiction-detecting contact.
- **Homogenization**: If all agents converge on carrying the same high-frequency facts, the system loses diversity. The displacement threshold must be large enough that displacement is infrequent, preserving carrier diversity across the agent population.
- **Echo chambers**: The Galam contrarian model shows that a fraction of agents maintaining minority-position facts has a moderating (not polarizing) effect. The displacement policy should ensure that low-frequency but high-value facts persist in the system.

The epidemiological analog is superinfection with fitness competition: a more transmissible strain (higher-frequency fact) displaces a less transmissible one, but the displacement dynamics have a critical threshold below which coexistence is stable.

### 9.6 Composition with Existing Architecture

Epistemic carrier dynamics composes with every layer of the existing architecture:

| Component | Integration |
|-----------|------------|
| **Principals (§3)** | Each principal gains a `carrier_slots: list[CarrierFact]` field, bounded by `carrier_capacity: int` |
| **Consent labels (§5)** | Carrier facts are `Labeled[T]` values — consent labels travel with carried facts via the DLM join |
| **VetoChain (§5.5)** | Contradiction between carrier fact and local knowledge generates a new veto type: `EpistemicContradictionVeto` |
| **FusedContext (§6)** | Carrier facts appear as additional samples in the fused context, with their foreign-domain provenance preserved |
| **Composition ladder (§6)** | Carrier slots are populated at L8 (PerceptionEngine) where cross-domain contact occurs, and checked at L7 (governance composition) where VetoChain evaluates |
| **Institutional architecture (§8)** | The governor pattern (§8.3) mediates carrier fact exchange at agent boundaries — governors validate that carrier facts respect consent labels before propagation |
| **Axiom system (§4)** | Carrier dynamics is governed by existing axioms: `interpersonal_transparency` constrains what facts about persons can be carried; `corporate_boundary` constrains what work facts can flow to home-system carriers |

**Design decision DD-26**: Carrier facts propagate through the filesystem-as-bus like any other data, but with a `carrier: true` frontmatter flag that triggers carrier-specific governance checks. The reactive engine (inotify) treats carrier-flagged writes as a distinct event type, routing them through carrier-specific validation rules.

### 9.7 Formal Precedents

The concept assembles five properties that exist independently across seven research traditions:

| Property | Formalized in | Our extension |
|----------|--------------|---------------|
| Probabilistic information spreading | Gossip protocols (Demers et al., 1987) | Cross-domain, not intra-domain |
| Message passing for global consistency | Factor graphs / sum-product (Kschischang et al., 2001); GBP (Yedidia et al., 2001) | Messages carried incidentally, not computed deliberately |
| Bounded carrying capacity | Memory-bounded agents (PODC 2024) | Applied to cross-domain facts, not homogeneous bits |
| Error detection via redundancy | LDPC codes (Gallager, 1960); network error correction (Cai & Yeung, 2006) | Agents as sparse parity checks |
| Anti-homogenization | Stubbornness (Friedkin-Johnsen); contrarians (Galam); bounded confidence (Hegselmann-Krause) | Domain boundaries as natural confidence bounds |

Additional supporting traditions:

- **Boundary spanners** (Tushman, 1981; Allen): Human cross-domain fact carriers are disproportionately valuable; agent carriers mechanize this
- **Structural holes** (Burt, 1992, 2004): Bridging disconnected groups provides information advantages and accelerates learning; carrier dynamics ensures no persistent structural holes
- **High-reliability organizations** (Weick & Sutcliffe): "Reluctance to simplify" and "deference to expertise" are institutional policies that resist domain-standing-as-filter — carrier dynamics is the structural implementation
- **Epistemic injustice** (Fricker, 2007): Suppressing valid observations based on domain standing is structurally analogous to testimonial injustice; the harm falls on the system's users (collectively dumber system), not on the agents themselves
- **Nogood propagation** (DCSP/DCOP literature): Agents propagate constraint violation information from foreign domains, enabling other agents to prune infeasible solutions — the most direct existing formalism for the carrier mechanism
- **Double-loop learning** (Argyris & Schon): Carrier facts that contradict domain assumptions force double-loop learning structurally, without requiring interpersonal challenge
- **Knowledge redundancy** (Bourgeois, 1981): Overlapping knowledge prevents single-point epistemic failure; carrier dynamics creates deliberate epistemic redundancy

### 9.8 Carrying Capacity Bounds

Combining results from LDPC sparsity, submodularity, and memory-bounded agent theory:

| Topology | Required carrier capacity k | Source |
|----------|---------------------------|--------|
| Good expansion (well-connected contact graph) | O(1) — constant, independent of system size | LDPC near-Shannon-limit at degree 6–20 |
| Arbitrary topology | O(log n) where n = number of domains | Memory-bounded agent lower bound (PODC 2024) |
| Practical heuristic | 3–5 foreign-domain facts | Submodularity plateau (arXiv:2511.16708) |

The system-level error detection probability with k carrier facts per agent: P(detection) ≈ 1 − (1−p)^(k·n_agents), where p is the probability that a given foreign fact is relevant to a contradiction in the receiving agent's local domain. For independent facts with good expansion, the system approaches complete error coverage rapidly.

### 9.9 The Epistemic Dimension of Conway's Law

**Design decision DD-27**: Treat Conway's law as an epistemic constraint, not merely a structural one.

Conway's original formulation (1968): "organizations which design systems are constrained to produce designs which are copies of the communication structures of these organizations." The standard reading is architectural — communication structure determines system structure. The epistemic reading is stronger: **communication structure determines what the system can *know***, as a prerequisite to determining what it can build.

The Nagappan et al. (2008) result supports the epistemic reading directly: organizational structure predicts defects better than code metrics because organizational structure determines which failure modes are *epistemically accessible* to the development team. A defect that spans two teams' domains is invisible to each team individually — it exists in the structural hole between them.

Carrier dynamics is the antidote to epistemic Conway's law. By ensuring that facts circulate across domain boundaries — even in bounded, incidental quantities — the system prevents persistent structural holes from becoming persistent epistemic blind spots.

### 9.10 Open Questions Specific to Carrier Dynamics

1. **Carrier fact representation**: What is the minimal representation for a carrier fact? Raw observations, structured assertions, or labeled values? The answer affects both carrying capacity (bits per fact) and contradiction detection capability.

2. **Contact topology design**: Should the agent contact graph be designed for good expansion properties, or should it emerge from the reactive engine's existing wiring? Designed topologies guarantee error-correction bounds; emergent topologies may miss critical cross-domain contacts.

3. **Contradiction detection threshold**: How much inconsistency between a carrier fact and local knowledge is required to trigger a veto? Zero tolerance produces false positives from noise; high tolerance misses real errors. The FRACTURE framework's compliance margins (arXiv:2511.17937) may provide the right model.

4. **Carrier fact provenance**: Should carrier facts record their full chain of custody (which agents carried them, for how long)? Full provenance enables trust calibration but increases metadata overhead.

5. **Cross-system carrier dynamics**: If multiple hapax-council-like systems exist (the single-operator axiom scopes to one system), could carrier dynamics operate between systems via shared external surfaces? This connects to the Solid/Keyhive interoperability question.

---

## 10. Position in the Literature

### 10.1 What Exists (Pieces)

| Domain | Key Work | What They Have |
|--------|----------|---------------|
| Single-model alignment | Bai et al. (2022), Constitutional AI | Values embedded in weights via training |
| Agent governance | LGA (2026), SAGA (2025) | Structural security for agent chains |
| Cooperative AI | Dafoe et al. (2020) | Multi-agent cooperation theory |
| AI constitutionalism | Abiri (2025), Worsdorfer & Kusters (2025) | Philosophical frameworks for AI governance |
| Embodied AI ethics | Perlo et al. (2025) | Policy analysis of sensor-equipped AI |
| GDPR + agents | AEPD (2026) | Regulatory guidance for agentic AI |
| Deliberative alignment | Guan et al. (2024) | Models reasoning about their own principles |
| Principal-agent theory | Kolt (2025) | Delegation analysis for AI agents |
| Digital constitutionalism | Suzor (2018), Celeste (2019) | Constitutional principles for digital spaces |
| Smart home consent | Orlowski & Loh (2025) | Privacy meta-assistant concept |
| Personal AI | Miessler (2026), Berners-Lee (2025) | Single-operator infrastructure, data pods |
| Extended cognition | Clark (2025) | AI as cognitive extension |
| Normative MAS | Dignum (OperA), Esteva (AMELI), Hubner (MOISE+) | Institutional norms for agent organizations |
| Info flow control | Myers & Liskov (2000), Stefan (LIO, 2011), Liu (Fabric, 2017) | Decentralized label propagation, floating labels, cross-process labels |
| Provenance | Green et al. (2007), Amsterdamer et al. (2011) | Algebraic annotation propagation, monus limitations |
| Gradual security | Toro, Garcia, Tanter (2018) | Mixed labeled/unlabeled regions |
| Local-first + AI | Kleppmann (2019), Ink & Switch, Litt (2025) | CRDTs, Keyhive, ambient agents |

### 10.2 What Does Not Exist (Our Contribution)

No published system combines:

1. **Runtime-enforceable constitutional axioms** — not values in weights, not aspirational platform principles, but structurally enforced constraints with weighted priorities, violation tiers, interpretive canons, and precedent case law
2. **Consent contracts as architectural primitives** — working implementation with opt-in, inspection, revocation, scope enumeration, purge, and (planned) invariant threading through all transactional chains via DLM labels and why-provenance
3. **Alignment tax inversion** — LLM agents as both the governed entities and the governance enforcement mechanism, with empirically measured overhead (~20%) below literature baseline (30-40%)
4. **Single-operator constitutional sovereignty** — one person, total sovereignty, no aggregation problem, self-authored constitution with democratic legitimacy, architectural not contractual enforcement
5. **Neurodivergent accommodation as governance axiom** — cognitive accommodation enforced by the same mechanisms as data protection and consent, with 35 derived implications at T0/T1/T2 tiers
6. **Separation of value enforcement from value internalization** — principles externalized as axioms evaluated by independent models, not embedded in the acting model's weights
7. **Norm refinement with interpretive canons** — traceability from abstract value through derivation canon to executable enforcement pattern, exceeding the most sophisticated MAS frameworks (OperA, MOISE+, ISLANDER)
8. **Epistemic carrier dynamics** — bounded cross-domain fact carrying for distributed error correction, with formal grounding in factor graphs, LDPC codes, and network error correction theory, solving a documented lethal problem (cross-domain knowledge silos) that no MAS framework addresses

### 10.3 Philosophical Lineage

Weiser (calm computing, 1991) → Clark & Chalmers (extended mind, 1998) → Ostrom (institutional analysis) → Lessig (code as law, 1999) → Kleppmann (local-first, 2019) → Lanier (data dignity) → Berners-Lee (Solid + AI, 2025) → Clark (extending minds with generative AI, 2025) → **this system** (constitutional governance for the extended mind).

---

## 11. Open Questions

### 11.1 Answered by Research

**Consent label granularity**: Use DLM owner-set policies. Granularity is per-owner, per-reader-set. This is neither too coarse nor too fine — the lattice structure handles arbitrary combinations via join. (DD-1)

**Revocation propagation**: Use PosBool(X) why-provenance. Each output carries a positive boolean formula over contract IDs. On revocation of contract `c`, evaluate with `c = false`. Outputs where the formula becomes `false` must be purged. (DD-8, DD-19)

**VetoChain and provenance**: VetoChain is a lattice filter, not a semiring operation. It passes or blocks provenance unchanged. The m-semiring problems are avoided entirely. (DD-9, DD-10)

**Python implementation approach**: Runtime `Labeled[T]` wrappers with LIO-style floating labels, not phantom types. Python's type system cannot express label joins statically. (DD-21)

### 11.2 Remaining Open

1. **Environmental vs. personal boundary**: `it-environmental-001` allows transient environmental perception without consent. Where exactly is the line? `face_count > 1` is environmental; `conversation_detected` derives personal inference. The boundary needs formal definition — potentially a constitutive rule: "environmental observation (X) counts as personal inference (Y) when it enables re-identification (C)."

2. **The profiler problem**: The profiler extracts facts from transcripts and calendar data that may characterize non-operator persons. Filtering requires the profiler to understand which facts are "about" the operator vs "about" others — a semantic distinction that may require LLM-level reasoning at the extraction boundary, with consent label assignment.

3. **Axiom conflict resolution**: The current weight system implements *lex superior*. Defeasible logic (Governatori & Rotolo) would enable more nuanced exception handling. The precedent system already provides informal defeasibility; the question is whether to formalize it.

4. **Constitutional amendment**: Axioms are currently static YAML. The NorMAS literature establishes that effective normative systems need lifecycle management: creation, activation, suspension, modification, retirement. The `status: active | retired` field and `supersedes` reference show awareness. Consider adding activation conditions and a formal amendment process with versioning and impact analysis.

5. **Consent enforcement strength**: Code-level checking (`contract_check()`) vs Keyhive-style cryptographic enforcement. Cryptographic enforcement makes unauthorized access structurally impossible regardless of code bugs, but adds complexity. Current code-level enforcement depends on every data pathway calling the check — a discipline requirement, not a physics guarantee.

6. **Inference provenance**: Profile facts record their `source` but not the chain of inference that produced them. No trace from fact back to source observations. For consent threading, this chain is needed to determine which consent contracts were involved in producing each fact.

7. **Scaffolding fading**: The accommodation engine has no concept of withdrawing support as operator capability grows. ZPD theory predicts good scaffolding should be gradually withdrawable. No mechanism to measure whether the system is enabling growth or creating dependency.

8. **Axiom propagation through tool-use chains**: When agents make sub-calls (e.g., pydantic-ai tool use), axiom context must propagate structurally, not by hope. No formal mechanism guarantees axiom inheritance through arbitrary tool-use delegation chains (Kolt, arXiv:2501.07913).

9. **Purpose compatibility across agent cascades**: When the reactive engine cascades from agent A to agent B, GDPR purpose limitation (Article 5(1)(b)) requires purpose compatibility verification. Currently assumed, not structurally verified.

10. **Shadow principal monitoring**: No explicit monitoring for LLM provider influence on agent behavior. Track refusal rates, unexpected behavioral patterns, and model-specific biases as shadow principal indicators through LiteLLM.

11. **Legal lineage documentation**: Each axiom should document which legal concepts it draws from (Kolt et al., "Legal Alignment," arXiv:2601.04175). The `interpersonal_transparency` axiom is essentially data protection law in YAML — making this lineage explicit strengthens both legitimacy and interpretive framework.

12. **Constitutional amendment protocol**: Axioms have the data model for amendment (`supersedes`, `status`, `schema_version`) but no formal process. For `hardcoded` axioms, these function as eternity clauses (unamendable — any change requires a new constitutional moment). For `softcoded` axioms, consider: proposal with rationale → automated impact analysis (affected implications, invalidated precedents) → cooling-off period (minimum 7 days, critical for neurodivergent operator to avoid impulsive governance changes) → explicit ratification → cascade regeneration of affected implications via `axiom_derivation.py`. Constitutional theory (Tsebelis) shows amendment rigidity does not straightforwardly correlate with formal difficulty — interpretive evolution via precedents is already the primary mechanism.

13. **Precedent injection into agent prompts**: Case-augmented deliberative alignment (CADA, arXiv:2601.08000) shows that simple safety codes + precedent cases outperform detailed rule enumeration (0.2 ASR vs 0.3 for SFT-only on StrongREJECT). The system should retrieve the 3-5 most relevant precedents per axiom when initializing agents and include them in system prompts alongside axiom text.

14. **Enforcement efficacy tracking**: The audit log captures violations but not outcomes. Adding `resolution` fields (fixed, false-positive, accepted-risk) would implement the Controller capability from Grossi & Aldewereld's five-capability enforcement model, enabling feedback loops that improve enforcement quality over time.

---

## 12. Design Decisions Index

All formal design decisions from the DLM/info-flow research, organized for implementation reference:

| ID | Decision | Derived From | Section |
|----|----------|-------------|---------|
| DD-1 | Consent labels use owner-set policies from ConsentContract | DLM (Myers & Liskov) | 5.3 |
| DD-3 | Default to most restrictive label (no consent = no access) | Jif defaults | 5.8 |
| DD-4 | No implicit declassification; revocation must be authenticated | Jif robustness | 5.8 |
| DD-5 | FusedContext carries mandatory consent_label (join of inputs) | DLM join | 5.3 |
| DD-6 | VetoChain checks consent labels | DLM + VetoChain | 5.5 |
| DD-7 | Separate provenance tracking from access control | Provenance semirings vs DLM | 5.4 |
| DD-8 | Use PosBool(X) for consent provenance | Green et al. 2007 | 5.4 |
| DD-9 | VetoChain is a lattice filter, not a semiring operation | Amsterdamer et al. 2011 | 5.5 |
| DD-10 | VetoChain passes/blocks provenance unchanged | m-semiring limitations | 5.5 |
| DD-11 | Markdown files carry consent labels in YAML frontmatter | Fabric access labels | 5.11 |
| DD-12 | Runtime label checks at file read boundaries | Fabric pre-fetch checks | 5.11 |
| DD-13 | Floating consent label pattern per LIO | LIO (Stefan et al.) | 5.7 |
| DD-14 | toLabeled-style sub-computations for fusion | LIO toLabeled | 5.7 |
| DD-15 | ConsentLabel Protocol with can_flow_to/join/meet | LIO Label typeclass | 5.3 |
| DD-16 | Accept gradual guarantee tension | Toro, Garcia, Tanter 2018 | 5.10 |
| DD-17 | Boundary enforcement at layer transitions | Gradual security typing | 5.10 |
| DD-18 | Bidirectional checking for mutable Behaviors | GSLRef references | 6.2 |
| DD-19 | Why-provenance (PosBool) for revocation | Buneman et al. 2001 | 5.4 |
| DD-20 | Store provenance in YAML frontmatter | Filesystem-as-bus + provenance | 5.11 |
| DD-21 | Runtime Labeled[T] wrappers, not phantom types | Python type system limitations | 5.6 |
| DD-22 | Thread consent bottom-up L0-L9 | Composition ladder protocol | 5.9 |
| DD-23 | Simplified frozenset[str] provenance at current scale | PosBool degeneracy | 5.4 |
| DD-24 | Extend principals with bounded carrier slot for cross-domain facts | Factor graphs (Kschischang et al. 2001), LDPC codes | 9.4 |
| DD-25 | Carrier facts displaced by frequency, not recency | Epidemiological superinfection models, Galam contrarian dynamics | 9.5 |
| DD-26 | Carrier facts propagate via filesystem-as-bus with `carrier: true` frontmatter | Filesystem-as-bus architecture | 9.6 |
| DD-27 | Treat Conway's law as epistemic constraint, not merely structural | Nagappan et al. 2008 (85% defect prediction from org metrics) | 9.9 |

---

## 13. References

### Formal Models
- Abadi, Burrows, Lampson, Plotkin, "A Calculus for Access Control in Distributed Systems" (1993)
- Abadi, "A Core Calculus of Dependency" (POPL 1999)
- Myers & Liskov, "Protecting Privacy using the Decentralized Label Model" (TOSEM 2000)
- Myers & Liskov, "Complete, Safe Information Flow with Decentralized Labels" (S&P 1998)
- Green, Karvounarakis, Tannen, "Provenance Semirings" (PODS 2007)
- Amsterdamer, Deutch, Tannen, "On the Limitations of Provenance for Queries With Difference" (TaPP 2011)
- Miller, "Robust Composition" (Johns Hopkins PhD thesis, 2006)
- Jia et al., "AURA: A Programming Language for Authorization and Audit" (ICFP 2008)
- Denning, "A Lattice Model of Secure Information Flow" (CACM 1976)
- Sergot, "A Computational Theory of Normative Positions" (2001)
- Buneman, Khanna, Tan, "Why and Where: A Characterization of Data Provenance" (ICDT 2001)
- Cheney, Chiticariu, Tan, "Provenance in Databases: Why, How, and Where" (survey)

### Information Flow & Runtime Enforcement
- Stefan, Russo, Mitchell, Mazieres, "Flexible Dynamic Information Flow Control in Haskell" (LIO, 2011)
- Stefan et al., "Flexible Dynamic Information Flow Control in the Presence of Exceptions" (JFP 2017)
- Liu, Arden, George, Myers, "Fabric: Building Open Distributed Systems Securely by Construction" (JCS 2017)
- Toro, Garcia, Tanter, "Type-Driven Gradual Security with References" (TOPLAS 2018)
- Disney, Flanagan, "Gradual Information Flow Typing" (STOP 2011)

### Philosophy
- Clark & Chalmers, "The Extended Mind" (1998)
- Clark, "Extending Minds with Generative AI" (Nature Communications, 2025)
- Austin, "How to Do Things with Words" (1962)
- Searle, "The Construction of Social Reality" (1995)
- Floridi & Sanders, "On the Morality of Artificial Agents" (2004)
- Bratman, "Shared Cooperative Activity" (1992)
- Carroll et al., "The CARE Principles for Indigenous Data Governance" (2020)
- Vygotsky, "Mind in Society" (1978)

### AI Governance
- Bai et al., "Constitutional AI: Harmlessness from AI Feedback" (2022)
- Guan et al., "Deliberative Alignment" (arXiv:2412.16339, 2024)
- Kolt, "Governing AI Agents" (Notre Dame Law Review, arXiv:2501.07913, 2025)
- Kolt, "Build Agent Advocates, Not Platform Agents" (arXiv:2505.04345, 2025)
- Kolt, Caputo et al., "Legal Alignment for Safe and Ethical AI" (arXiv:2601.04175, 2026)
- Chan et al., "Visibility into AI Agents" (arXiv:2401.13138, 2024)
- Abiri, "Public Constitutional AI" (Georgia Law Review, arXiv:2406.16696, 2025)
- Worsdorfer, "AI Ethics and Ordoliberalism 2.0" (arXiv:2311.10742, 2023)
- Worsdorfer & Kusters, "Exploring Laws of Robotics" (Digital Society, 2025)
- AEPD, "Agentic Artificial Intelligence from the Perspective of Data Protection" (2026)
- Dafoe et al., "Open Problems in Cooperative AI" (2020)
- Sorensen et al., "A Roadmap to Pluralistic Alignment" (ICML 2024)
- Dalrymple, Tegmark et al., "Towards Guaranteed Safe AI" (2024)
- Parra-Orlandoni, Schnyder & Mallet, "The Digital Gorilla: Rebalancing Power in the Age of AI" (arXiv:2602.20080, 2025)

### AI Safety & Alignment
- Anthropic, "Alignment Faking in Large Language Models" (arXiv:2412.14093, 2024)
- FRACTURE framework, "Alignment Faking Detection" (arXiv:2511.17937, 2025)
- Mechanism Design for AI Agent Governance (arXiv:2601.23211, 2026)
- CADA, "Case-Augmented Deliberative Alignment" (arXiv:2601.08000, 2026)
- Grossi & Aldewereld, "Ubi Lex, Ibi Poena: Designing Norm Enforcement in E-Institutions" (2007)
- Tsebelis, "Constitutional Rigidity Matters: A Veto Players Approach" (BJPS)

### Institutional Frameworks
- Dignum, "OperA: A Model for Organizational Interaction" (PhD thesis, 2004)
- Aldewereld, Dignum et al., "OperettA: Organization-Oriented Development Environment" (2011)
- Esteva, Cruz, Sierra, "ISLANDER: an electronic institutions editor" (AAMAS 2002)
- Esteva et al., "AMELI: An Agent-based Middleware for Electronic Institutions" (2004)
- Frantz et al., "A computational model of Ostrom's IAD framework" (Artificial Intelligence, 2022)
- Boella & van der Torre, "Regulative and Constitutive Norms in Normative MAS" (KR 2004)
- Governatori & Rotolo, "A Computational Framework for Institutional Agency" (AI&Law, 2008)
- Hubner et al., "MOISE+" (AAMAS 2002)
- Argente et al., "The THOMAS approach" (KAIS, 2011)
- Ferber & Gutknecht, "From Agents to Organizations" (AAMAS 2003)
- Mahmoud et al., "A Review of Norms and Normative Multiagent Systems" (2014)
- Artikis, Sergot, Pitt, "Specifying Norm-Governed Computational Societies" (TOCL, 2009)
- Cole, "Laws, Norms, and the IAD Framework" (J. Institutional Economics, 2017)
- Kasenberg & Scheutz, "Norm Conflict Resolution in Stochastic Domains" (AAAI 2018)
- Ostrom, "Institutional Analysis and Development Framework"
- Castelfranchi & Falcone, "Towards a Theory of Delegation" (1998)
- Rahwan, "Society-in-the-Loop" (2017)
- Friedman & Hendry, "Value Sensitive Design" (2019)

### Type Theory & Information Flow
- Bernardy et al., "Linear Haskell" (POPL 2018)
- Orchard et al., "Quantitative Program Reasoning with Graded Modal Types" (Granule, ICFP 2019)
- Atkey, "Parameterised Notions of Computation" (JFP 2009)

### Personal AI & Sovereignty
- Berners-Lee, Solid Project (2025)
- Miessler, "Personal AI Infrastructure" (2026)
- Kleppmann et al., "Local-First Software" (Onward! 2019)
- Lanier, "Data Dignity and the Inversion of AI" (2025)
- Ink & Switch, Keyhive (2025)
- Litt, "Ambient Agents" (2025)

### Information Theory & Error Correction
- Kschischang, Frey & Loeliger, "Factor Graphs and the Sum-Product Algorithm" (IEEE Trans. Info. Theory, 2001)
- Gallager, "Low-Density Parity-Check Codes" (IRE Trans. Info. Theory, 1962)
- Sipser & Spielman, "Expander Codes" (IEEE Trans. Info. Theory, 1996)
- Cai & Yeung, "Network Error Correction, I: Basic Concepts and Upper Bounds" (Comm. Info. Systems, 2006)
- Yedidia, Weiss & Freeman, "Understanding Belief Propagation and its Generalizations" (MERL TR-2001-22)
- Yedidia, Weiss & Freeman, "Constructing Free Energy Approximations and Generalized Belief Propagation Algorithms" (IEEE Trans. Info. Theory, 2005)
- "Multi-Agent Fact Checking" (arXiv:2503.02116, 2025)
- "Multi-Agent Code Verification via Information Theory" (arXiv:2511.16708, 2025)
- "On the Limits of Information Spread by Memory-less Agents" (arXiv:2402.11553, PODC 2024)

### Organizational Theory & Silo Failures
- Conway, "How Do Committees Invent?" (Datamation, 1968)
- Nagappan, Murphy & Basili, "The Influence of Organizational Structure on Software Quality" (Microsoft Research TR-2008-11, 2008)
- 9/11 Commission Report, "The Aviation Security System and the 9/11 Attacks" (2004)
- Columbia Accident Investigation Board, "Report Volume 1" (NASA, 2003)
- Vaughan, "The Challenger Launch Decision: Risky Technology, Culture, and Deviance at NASA" (1996)
- Wegner, "Transactive Memory: A Contemporary Analysis of the Group Mind" (1987)
- Tushman, "Boundary Spanning Individuals: Their Role in Information Transfer" (AMJ, 1981)
- Burt, "Structural Holes and Good Ideas" (American Journal of Sociology, 2004)
- Weick & Sutcliffe, "Managing the Unexpected: Resilient Performance in an Age of Uncertainty" (2007)
- Granovetter, "The Strength of Weak Ties" (American Journal of Sociology, 1973)
- Nonaka & Takeuchi, "The Knowledge-Creating Company" (1995)
- Argyris & Schon, "Organizational Learning: A Theory of Action Perspective" (1978)
- Senge, "The Fifth Discipline" (1990)
- Fricker, "Epistemic Injustice: Power and the Ethics of Knowing" (Oxford, 2007)
- Bourgeois, "On the Measurement of Organizational Slack" (Academy of Management Review, 1981)
- Kitcher, "The Division of Cognitive Labor" (Journal of Philosophy, 1990)
- Surowiecki, "The Wisdom of Crowds" (2004)

### Opinion Dynamics & Anti-Homogenization
- Friedkin & Johnsen, "Social Influence and Opinions" (Journal of Mathematical Sociology, 1990)
- Hegselmann & Krause, "Opinion Dynamics and Bounded Confidence" (JASSS, 2002)
- Galam, "Minority Opinion Spreading in Random Geometry" (European Physical Journal B, 2002)
- Demers et al., "Epidemic Algorithms for Replicated Database Maintenance" (PODC, 1987)

### Regulatory
- GDPR (Regulation 2016/679), Articles 7, 28
- EU AI Act (Regulation 2024/1689)
- EDPB, "AI Privacy Risks & Mitigations in LLMs" (2025)
- Bartoletti et al., "Formal Models for Consent-Based Privacy" (2022)
- Pullonen et al., "Precise Analysis of Purpose Limitation in Data Flow Diagrams" (2022)
