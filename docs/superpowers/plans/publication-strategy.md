# Publication & Implementation Strategy

**Status**: Active strategic plan
**Date**: 2026-03-13
**Scope**: How to shape the theoretical framework and implementation for multi-audience consumption
**Prerequisite**: [Computational Constitutional Governance spec](../specs/2026-03-13-computational-constitutional-governance.md)

---

## 1. What We Have

An 875-line theory document with 27 design decisions, ~140 references across 10+ disciplines, and a running system (26 agents, 2,700+ tests) that partially implements the theory. The theory contains at least 8 novel contributions, several independently publishable.

The project has shifted: **the theory and its exemplary implementation are now the primary deliverable**, not the operational system they describe. The system exists to prove the theory works. The theory exists to contribute to multiple research communities. Both must be shaped for that purpose.

---

## 2. Audience Analysis

### 2.1 Primary Audiences

| Audience | What they care about | What they'd scrutinize | Venue class |
|----------|---------------------|----------------------|-------------|
| **PL/Security** | Consent-as-information-flow; DLM/LIO application to consent; gradual adoption | Formal soundness of label operations; type-safety claims; performance overhead | POPL, PLDI, Oakland, CCS, POST |
| **MAS/Normative MAS** | Epistemic carrier dynamics; norm refinement with interpretive canons; OperA extension | Mathematical rigor of factor graph claims; comparison with existing frameworks; evaluation metrics | AAMAS, IJCAI, AAAI |
| **AI Safety/Alignment** | Alignment tax inversion; separation of enforcement from internalization; externalized values | Empirical measurement methodology; threat model; comparison with Constitutional AI/RLHF | SafeAI workshop, AAAI, NeurIPS |
| **HCI/Ethics** | Neurodivergent accommodation as governance; single-operator sovereignty; extended mind | User study or evaluation; accessibility claims; philosophical coherence | CHI, FAccT, AIES, CSCW |
| **Systems/Infrastructure** | Filesystem-as-bus; reactive engine; composition ladder; working implementation | Performance, scalability, fault tolerance; comparison with alternatives | SOSP, OSDI, EuroSys (stretch) |
| **Organizational theory** | Epistemic Conway's law; cross-domain error correction; documented silo failures | Empirical validation; case study methodology | Organization Science, AMJ, MISQ |

### 2.2 Secondary Audiences

- **Personal AI builders** (Solid community, local-first community, Ink & Switch): Want a governance pattern they can adopt. Need clean APIs and documented integration points.
- **AI governance policymakers**: Want evidence that governance doesn't require 30-40% overhead. Need the alignment tax inversion finding stated clearly with methodology.
- **Open-source developers building similar systems**: Want to fork/adapt the architecture. Need clean code, clear boundaries, and documented design decisions.

---

## 3. Paper Decomposition

The theory document should NOT be submitted as a single paper. It spans too many communities and would be rejected as unfocused at any single venue. Instead, decompose into 3-4 focused papers, each self-contained but cross-referencing.

### Paper A: "Consent as Information Flow: DLM Labels for Human-AI Shared Spaces"

**Core claim**: Consent governance in multi-agent systems with ambient sensing is an information-flow control problem. DLM labels, LIO floating labels, and PosBool why-provenance provide correct consent propagation, revocation, and fusion — stronger guarantees than any existing consent framework.

**Draws from**: Sections 3, 5, 6 of theory document (Principal Model, Consent Architecture, Composition Ladder)

**Novel contributions**:
1. Application of DLM owner-set policies to consent (not confidentiality)
2. LIO floating labels for consent propagation through multi-layer composition
3. PosBool(X) why-provenance for revocation propagation
4. VetoChain as lattice filter (not semiring) for consent governance
5. Gradual security typing for incremental consent adoption

**What the implementation must demonstrate**:
- `ConsentLabel` with correct `join`, `can_flow_to`, `meet` operations
- `Labeled[T]` wrapper with runtime enforcement
- Consent threading through all 10 composition layers (DD-22)
- Revocation propagation via provenance evaluation
- Performance: label operations are O(1) amortized, not a scalability bottleneck

**Target venue**: POST (Principles of Security and Trust), or CSF (Computer Security Foundations), or a PL workshop. Stretch: Oakland S&P.

**Evaluation strategy**: Formal proofs of label properties (join is LUB, non-amplification holds); implementation benchmarks; comparison with existing consent frameworks (GDPR compliance tools, Solid WAC/ACP).

### Paper B: "Epistemic Carrier Dynamics: Cross-Domain Error Correction for Multi-Agent Systems"

**Core claim**: Multi-agent systems suffer from cross-domain factual inconsistency because no agent has standing to detect contradictions across domain boundaries. Bounded incidental fact carrying, formalized via factor graphs and LDPC codes, provides near-optimal error correction with O(1) carrier capacity per agent.

**Draws from**: Section 9 of theory document (Epistemic Carrier Dynamics)

**Novel contributions**:
1. Named identification of the cross-domain error correction problem in MAS
2. Factor graph equivalence for multi-agent error correction
3. LDPC sparsity bounds on carrying capacity
4. Anti-homogenization guarantees via Friedkin-Johnsen stubbornness
5. Epistemic characterization of Conway's law
6. Application of Fricker's epistemic injustice to agent architectures

**What the implementation must demonstrate**:
- Carrier slots on agents with bounded capacity
- Contradiction detection when carrier facts contact local knowledge
- Displacement dynamics (frequency-based)
- Measurable error detection improvement vs. baseline (no carriers)
- Anti-homogenization: domain knowledge diversity preserved

**Target venue**: AAMAS (primary), AAAI, or IJCAI. The factor graph formalization could also target IEEE Trans. Info. Theory if developed with full proofs.

**Evaluation strategy**: Simulation with synthetic multi-agent system (configurable domains, error injection, carrier capacity). Measure: error detection rate vs. carrier capacity, time-to-detection, homogenization index. Compare: no carriers, random gossip, full broadcast, carrier dynamics. Formal: prove carrying capacity bounds via coding theory.

### Paper C: "Constitutional Governance for Personal AI: Alignment Tax Inversion Through Externalized Values"

**Core claim**: Externalizing values as weighted axioms evaluated by independent LLM models produces stronger alignment guarantees than Constitutional AI or RLHF, at lower measured cost (~20% vs 30-40%), with the benefits of auditability, amendability, and separation of powers.

**Draws from**: Sections 2, 4, 7, 8 of theory document (Why Now, Constitutional Framework, Operator Model, Institutional Architecture)

**Novel contributions**:
1. Alignment tax inversion: governance overhead below literature baseline
2. Separation of enforcement from internalization
3. Norm refinement with four interpretive canons
4. Neurodivergent accommodation as constitutional requirement
5. Single-operator sovereignty as simplification (not limitation)
6. Ordoliberal frame rules for AI governance

**What the implementation must demonstrate**:
- Full axiom system with enforcement tiers
- SDLC pipeline with separation of powers (different models for author, reviewer, judge)
- Precedent system with case law accumulation
- Measurable governance overhead
- Accommodation engine with confirmed/disabled accommodations

**Target venue**: FAccT (primary), AIES, or CHI. The alignment tax finding could target a safety workshop.

**Evaluation strategy**: Governance overhead measurement (wall-clock, token cost, developer time). Axiom violation detection rate (precision/recall of enforcement tiers). Comparison with: no governance, Constitutional AI prompt, RLHF. Case study: trace a consent contract through the full system lifecycle.

### Paper D (Optional): "The Composition Ladder: Algebraic Governance Correspondence in Reactive Agent Systems"

**Core claim**: A bottom-up composition discipline with algebraic property testing (192 matrix tests, 62 hypothesis tests) provides mechanical guarantees that governance constraints propagate correctly through multi-layer agent composition.

**Draws from**: Section 6, plus the hypothesis testing work (LAYER_STATUS.yaml)

**This paper is the implementation companion** — it shows how the algebra makes the governance trustworthy.

**Target venue**: ICSE (software engineering), ASE, or ESEC/FSE.

---

## 4. Implementation Priorities

The implementation must serve two masters: the running system AND the publication strategy. Prioritize work that advances both.

### 4.1 Critical Path (Blocks Papers A and C)

These must be implemented for any paper submission:

| Priority | Component | Design Decisions | Blocks |
|----------|-----------|-----------------|--------|
| **P0** | `shared/principals.py` — Principal type (sovereign/bound) | §3.2, §3.3 | Everything downstream |
| **P0** | `shared/consent_label.py` — ConsentLabel with DLM operations | DD-1, DD-15 | Paper A |
| **P0** | `shared/labeled.py` — Labeled[T] wrapper | DD-21 | Paper A |
| **P1** | Consent threading L0-L3 (Stamped, Behavior, FusedContext, with_latest_from) | DD-22 | Paper A |
| **P1** | Consent veto in VetoChain | DD-6 | Paper A |
| **P1** | Floating label pattern in with_latest_from | DD-13, DD-14 | Paper A |
| **P2** | Consent threading L4-L9 | DD-22 | Paper A completeness |
| **P2** | File-level consent labels in frontmatter | DD-11, DD-12, DD-20 | Paper A, Paper C |
| **P2** | Revocation propagation via why-provenance | DD-8, DD-19, DD-23 | Paper A |

### 4.2 Carrier Dynamics (Blocks Paper B)

| Priority | Component | Design Decisions | Notes |
|----------|-----------|-----------------|-------|
| **P1** | Carrier slot on agents | DD-24 | Requires Principal type (P0) |
| **P1** | Contradiction detection (EpistemicContradictionVeto) | DD-24 | Requires VetoChain consent veto |
| **P2** | Displacement dynamics | DD-25 | Frequency tracking |
| **P2** | Carrier-flagged filesystem events | DD-26 | Reactive engine extension |
| **P3** | Simulation harness for evaluation | — | For Paper B evaluation |

### 4.3 Governance Completeness (Blocks Paper C)

| Priority | Component | Notes |
|----------|-----------|-------|
| **P1** | Governor wrappers (AMELI pattern) | §8.3 — per-agent governance validation |
| **P2** | Constitutive rules (counts-as mappings) | §4.3 — make implicit constitutive rules explicit |
| **P2** | Agent-specific axiom bindings in manifests | §8.2 |
| **P2** | Coherence checker (axiom → implication → enforcement chain) | §4.8 |
| **P3** | Compliance margins (FRACTURE) | §4.5 gap |
| **P3** | Precedent injection into agent prompts (CADA) | Open question 13 |

### 4.4 Implementation Discipline

Every implementation step must:
1. **Follow the composition ladder protocol** — bottom-up, matrix-complete before climbing
2. **Include hypothesis property tests** — algebraic properties that prove the governance invariants hold
3. **Trace to design decisions** — every module docstring cites the DD it implements
4. **Be PR'd with theory-implementation mapping** — PR description explains which section of the theory document this implements and what paper it supports

---

## 5. Quality Bar for "Exemplary Implementation"

The implementation is not a prototype or proof-of-concept. It must be the kind of code that makes reviewers say "this is clearly correct" when they read it.

### 5.1 What "Exemplary" Means

- **Type-level correctness**: `ConsentLabel` operations are algebraically proven (hypothesis tests for join associativity, commutativity, idempotence; meet distributivity; can_flow_to transitivity)
- **Composition contracts verified**: Every layer N's output is verified as valid input to layer N+1 (existing pattern in composition ladder)
- **No escape hatches**: No `# type: ignore`, no `cast()`, no `Any` in the consent/principal/label code. If the type system can't express it, redesign until it can.
- **100% branch coverage on consent paths**: Every branch in consent label operations, every error path in revocation propagation
- **Documentation as proof**: Module-level docstrings cite the paper, the design decision, and the algebraic properties the module maintains
- **Performance characterized**: Benchmarks for label operations, join computation, revocation propagation. Not necessarily fast — but measured and reported.

### 5.2 What "Reference Implementation" Means

The code should be readable as a standalone artifact by someone who has read the theory document:
- A PL researcher should be able to read `consent_label.py` and recognize the DLM operations
- A MAS researcher should be able to read `carrier.py` and see the factor graph correspondence
- An AI safety researcher should be able to read the axiom enforcement chain and verify separation of powers

This means: clean module boundaries, minimal dependencies between the governance code and the operational code, and a `shared/governance/` package that could be extracted and used by other projects.

---

## 6. Publication Timeline

### Phase 1: Foundation (Now → 4 weeks)

**Implementation**: P0 items (Principal, ConsentLabel, Labeled[T])
**Writing**: Paper A outline and related work section (most labor-intensive to write because the PL literature comparison must be precise)
**Evaluation prep**: Design the consent threading benchmark suite

### Phase 2: Consent Threading (Weeks 5-8)

**Implementation**: P1 consent items (threading L0-L3, VetoChain consent veto, floating labels)
**Writing**: Paper A first draft; Paper C outline
**Evaluation**: Run consent threading benchmarks; measure label operation costs

### Phase 3: Carrier Dynamics + Governance (Weeks 9-14)

**Implementation**: Carrier slots, contradiction detection, governor wrappers
**Writing**: Paper B first draft; Paper C first draft
**Evaluation**: Build simulation harness for carrier dynamics evaluation

### Phase 4: Polish + Submit (Weeks 15-18)

**Implementation**: P2/P3 items; complete consent threading L4-L9
**Writing**: All papers revised; Paper A submitted to target venue
**Evaluation**: Complete all evaluation runs; generate figures

### Venue Calendar

| Venue | Typical deadline | Paper |
|-------|-----------------|-------|
| AAMAS 2027 | Oct 2026 | Paper B |
| FAccT 2027 | Jan 2027 | Paper C |
| POST 2027 | ~Oct 2026 | Paper A |
| CSF 2027 | ~Feb 2027 | Paper A (backup) |
| CHI 2027 | Sep 2026 | Paper C (stretch, earlier) |
| AAAI 2027 | Aug 2026 | Paper B (stretch, earlier) |

---

## 7. Honesty Requirements

The theory document and papers must be honest about:

### 7.1 What Is Implemented vs. Theorized

The current gap is significant. The theory document describes consent threading through 10 layers; the implementation has consent checks at exactly 2 ingestion points. Every claim must distinguish between "we have built this" and "we have designed this." Papers should present implemented components with evaluation and designed components as future work.

### 7.2 Single-Operator Scope

The single-operator axiom is simultaneously the system's greatest strength (eliminates aggregation, legitimacy, and trust bootstrapping problems) and its greatest limitation (results may not generalize to multi-user systems). Papers must be explicit: "This architecture solves the single-operator case completely. Extension to multi-operator settings requires solving social choice problems we deliberately exclude."

### 7.3 Evaluation Limitations

- No user study (single operator, single system)
- Alignment tax measurement is self-reported, not independently measured
- The system has been running for months but without formal A/B testing against alternatives
- Carrier dynamics evaluation will be simulation, not deployment

Papers must acknowledge these limitations and frame contributions appropriately: "We demonstrate feasibility and provide formal design, not a controlled experiment."

### 7.4 The LLM Dependency

The entire architecture depends on LLMs being capable enough to reason about axioms, evaluate compliance, and participate in deliberative processes. If models regress in capability, the governance guarantees weaken. This is a genuine fragility that must be acknowledged.

---

## 8. Framing Guidance

### 8.1 The One-Sentence Pitch

> "What if consent, authority, and values were type-level invariants — checked, propagated, and enforced with the same rigor as type safety?"

### 8.2 The Elevator Pitch (30 seconds)

"We built a personal AI system with ambient sensing — microphones, cameras, presence detection — that enforces consent, authority, and cognitive accommodation as structural invariants, not aspirational guidelines. Constitutional axioms are weighted, enforced at commit/push/PR/runtime, refined through interpretive canons, and accumulated as case law. The governance overhead is ~20%, below the 30-40% literature reports. The key insight: LLMs can both comply with and enforce governance, inverting the alignment tax."

### 8.3 Per-Audience Lead

**PL/Security**: "We apply the Decentralized Label Model to consent governance in multi-agent systems. Consent labels propagate as lattice joins through a 10-layer reactive composition stack. PosBool why-provenance enables correct revocation. LIO-style floating labels track consent scope through fusion operations."

**MAS**: "We extend OperA's organizational model with two mechanisms no published framework provides: norm refinement with four interpretive canons giving full value-to-enforcement traceability, and epistemic carrier dynamics — bounded cross-domain fact carrying that provides distributed error correction, formalized via factor graphs and LDPC sparsity bounds."

**AI Safety**: "We demonstrate that externalizing values as weighted axioms evaluated by independent models produces ~20% governance overhead — below the 30-40% alignment tax reported in the literature — while providing stronger guarantees: auditability, amendability, separation of powers, and accumulated case law."

**HCI/Ethics**: "We treat neurodivergent accommodation not as a UX feature but as a constitutional requirement, enforced by the same mechanisms as data protection and consent. The system is a cognitive extension (Clark & Chalmers), governed by a self-authored constitution with total sovereignty — the operator authors the laws that bind their own AI agents."

---

## 9. Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| Implementation doesn't match theory | Medium | High — undermines all papers | Strict DD tracing; test each claim |
| Papers rejected as "just an architecture" | Medium | Medium — venues want evaluation | Strong evaluation strategy; formal proofs for Paper A, simulation for Paper B |
| Scope creep in implementation | High | Medium — delays everything | P0/P1/P2/P3 prioritization; resist P3 until papers submitted |
| Single-operator framing seen as toy | Medium | High — dismissal | Frame as deliberate simplification (like studying ideal gases), not limitation |
| Theory document becomes stale | Medium | Low — living document | Update after each implementation milestone |

---

## 10. Immediate Next Steps

1. **Create `shared/governance/` package** — clean module boundary for the reference implementation
2. **Implement `Principal` type** (P0) — sovereign/bound distinction, capability model
3. **Implement `ConsentLabel`** (P0) — DLM operations with hypothesis property tests
4. **Implement `Labeled[T]`** (P0) — runtime wrapper with floating label support
5. **Thread consent through L0-L1** (P1) — Stamped and Behavior gain optional consent labels
6. **Write Paper A outline** — related work section first (identifies gaps in our understanding)
7. **Update theory document** — mark implemented DDs, track implementation-theory correspondence
