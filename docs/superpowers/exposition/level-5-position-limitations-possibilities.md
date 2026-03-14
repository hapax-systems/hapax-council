# Level 5: Position, Limitations, and Possibilities

## Where This Sits in the Research Landscape

The work crosses at least six research communities. Each sees a different facet:

### Programming Languages / Security

**What they see**: DLM labels applied to consent governance. LIO floating labels for consent propagation through multi-layer composition. Gradual security typing for incremental adoption. PosBool why-provenance for revocation.

**What they'd scrutinize**: Formal soundness of label operations. Does `can_flow_to` actually prevent leaks? Does the gradual boundary enforcement introduce unsoundness? Performance overhead of runtime label tracking.

**What the system has to show them**: The hypothesis proofs of lattice properties. The functor laws on Labeled[T]. The flow-direction consistency between governors and the label lattice. The fact that label operations are O(1) (set union/subset checks on small policy sets).

**How it extends their work**: DLM was designed for confidentiality — who can read classified data. Applying it to consent — who has permitted processing of their data — is a novel domain. The key difference: in confidentiality, labels protect *secrets*; in consent, labels protect *persons*. The algebra is the same, but the semantics shift from "who can see this" to "whose autonomy is at stake."

### Multi-Agent Systems / Normative MAS

**What they see**: An OperA-class organizational model with norm refinement that exceeds published frameworks. Interpretive canons providing traceability from value to enforcement. Carrier dynamics as a novel coordination mechanism.

**What they'd scrutinize**: Mathematical rigor of the factor graph claims. Is the LDPC analogy a genuine structural equivalence or a suggestive metaphor? Comparison with gossip protocols, which already provide information spreading. Evaluation methodology for carrier dynamics effectiveness.

**What the system has to show them**: The implementation of constitutive vs. regulative rules (which no MAS framework separates cleanly). The coherence checker (analogous to OperettA's model checking). The four interpretive canons in implication derivation (which no framework provides). And for carrier dynamics: simulation results showing error detection rates vs. carrier capacity.

**Honest gap**: The simulation harness for carrier dynamics doesn't exist yet. The types are proven, but the empirical evaluation is future work. The paper would need to present this as "formal design + bounds from information theory," not "measured system."

### AI Safety / Alignment

**What they see**: Alignment tax inversion — governance at ~20% overhead vs. 30-40% in the literature. Separation of enforcement from internalization. Values externalized as inspectable YAML, not embedded in model weights.

**What they'd scrutinize**: Is the 20% figure real? How is it measured? Does it account for the same cost categories as the 30-40% baseline? What's the threat model? Can an adversarial agent circumvent the governance?

**What the system has to show them**: The separation of powers (different models for author, reviewer, judge). The structural defense against alignment faking (excluding implementer's reasoning from review). The comparison with Constitutional AI: Anthropic embeds values in weights via training; this system externalizes values and evaluates them independently. Both approaches have the same goal but different failure modes.

**The honest comparison**: Constitutional AI (Bai et al., 2022) scales to billions of users but has opacity problems — you can't inspect why a specific decision was made. This system has total transparency but scales to exactly one operator. These are complementary, not competing. The single-operator system demonstrates feasibility of a governance architecture; Constitutional AI demonstrates scalability of a training approach.

### HCI / Ethics

**What they see**: Neurodivergent accommodation as a constitutional requirement, not a UX feature. Single-operator sovereignty. Extended mind governance. Consent contracts for third parties in ambient sensing environments.

**What they'd scrutinize**: No user study. Self-reported outcomes. The consent model is unilateral — the operator sets terms. Third parties can opt in or out but can't negotiate terms.

**What the system has to show them**: The accommodation engine with confirmed/disabled accommodations (the operator has agency over their own support). The extended mind mapping to Clark & Chalmers' five conditions. The consent contract structure (bilateral, inspectable, revocable, scope-enumerated).

**The ethical tension**: This system protects third parties through consent contracts, but those parties had no voice in drafting the `interpersonal_transparency` axiom. The operator unilaterally decided what "transparency" means. Consent contracts provide opt-in/inspection/revocation, but terms are set by one party. This is a legitimate critique. The mitigation is structural: the axiom exists at all (most personal AI systems have no such constraint), and it's enforced more rigorously than anything in the commercial ecosystem.

---

## The Three Papers and What Each Must Prove

### Paper A: "Consent as Information Flow"

**Core claim**: Consent governance in multi-agent systems with ambient sensing is an information-flow control problem. DLM labels + LIO floating labels + PosBool why-provenance provide correct consent propagation, revocation, and fusion.

**What makes it novel**: No one has applied IFC to consent governance. The existing consent literature is either legal (GDPR compliance tools) or access-control (Solid WAC/ACP). IFC gives you something neither provides: **invariant propagation through computation**, not just boundary checking.

**What it needs**: Formal proofs of label properties (done). Consent threading through composition layers (L1-L7 done, L8-L9 pending). Performance benchmarks. Comparison with Solid WAC/ACP and GDPR compliance tools.

**Target venues**: POST (Principles of Security and Trust), CSF (Computer Security Foundations).

### Paper B: "Epistemic Carrier Dynamics"

**Core claim**: Multi-agent systems suffer from cross-domain factual inconsistency that no existing framework addresses. Bounded incidental fact carrying, formalized via factor graphs and LDPC codes, provides near-optimal error correction with O(1) carrier capacity per agent.

**What makes it novel**: The named problem (cross-domain epistemic blindness), the factor graph formalization, the LDPC sparsity bounds, and the anti-homogenization guarantees.

**What it needs**: Simulation harness (not built yet). Empirical comparison: no carriers vs. random gossip vs. full broadcast vs. carrier dynamics. Measure error detection rate, time-to-detection, homogenization index.

**Target venues**: AAMAS (primary), AAAI, IJCAI.

### Paper C: "Constitutional Governance for Personal AI"

**Core claim**: Externalizing values as weighted axioms evaluated by independent LLM models produces stronger alignment guarantees than Constitutional AI or RLHF, at lower cost, with auditability, amendability, and separation of powers.

**What makes it novel**: Alignment tax inversion. Norm refinement with interpretive canons. Neurodivergent accommodation as governance. Single-operator sovereignty as simplification.

**What it needs**: Governance overhead measurement (wall-clock, token cost). Axiom violation detection rate. Case study tracing consent through the full lifecycle. Honest limitations section.

**Target venues**: FAccT (primary), AIES, CHI.

---

## What This Proves (Significant)

Via hypothesis testing (universally quantified property tests over randomly generated inputs):

- ConsentLabel forms a correct join-semilattice (10 algebraic properties)
- Non-amplification holds through delegation chains (3 principal properties)
- Labeled[T] is a correct functor (5 composition properties)
- Governor decisions are consistent with the label lattice
- Carrier registry never exceeds capacity; displacement respects thresholds
- Revocation propagation is correct: `provenance ⊆ active_contracts iff valid`

---

## What This Doesn't Prove (Significant)

- End-to-end consent propagation through all 10 composition layers (L1-L7 done, L8-L9 pending)
- Carrier dynamics actually detect cross-domain errors in practice (needs simulation harness)
- Alignment tax is actually ~20% (self-reported, not independently measured)
- The system generalizes beyond single-operator (it deliberately doesn't claim to)
- No user study (n=1)
- No A/B testing against alternatives
- Code-level enforcement, not cryptographic — discipline requirement, not physics guarantee

The honest framing for papers: "We demonstrate feasibility and provide formal design, not a controlled experiment."

---

## What Possibilities This Opens

### For the personal AI ecosystem

No one building personal AI has governance. Solid has access control. Keyhive has cryptographic authorization. But neither has constitutional governance — weighted axioms, enforced implications, case law, separation of powers. If the governance types were extracted into a standalone package, other personal AI projects could adopt the governance layer without rebuilding it.

### For multi-agent system design

Carrier dynamics could apply to any multi-agent system with domain specialization. Microservice architectures, multi-team software organizations, distributed sensor networks — anywhere Conway's law creates epistemic blind spots.

### For AI governance policy

The alignment tax inversion finding challenges the assumption that alignment is inherently expensive. If replicated, this could influence policy discussions about the cost of governance requirements.

### For the extended mind thesis

This is a concrete implementation of governed cognitive extension — the first (to our knowledge) that treats the governance of the cognitive extension as a constitutional matter with formal enforcement.

---

## What Might Be Problematic

1. **Single-operator scope**: Results may not generalize. Multi-operator settings require social choice theory, which this system deliberately excludes.

2. **LLM dependency**: If models regress, governance guarantees weaken. The structural layers (regex, hooks) still work, but nuanced judgment disappears.

3. **Self-authored constitution**: A constitution you can unilaterally amend provides weaker commitment than one requiring supermajority. Mitigated by CODEOWNERS and CI gates, but the operator could override those.

4. **Unilateral consent terms**: Third parties can opt in or out but can't negotiate the axiom's terms. The operator decides what "transparency" means.

5. **Code-level enforcement**: Consent depends on every data pathway calling the right check. No cryptographic guarantee.
