# SCM Remaining Gaps: Research Synthesis

**Date:** 2026-03-31
**Status:** Active research
**Depends on:** [Stigmergic Cognitive Mesh](stigmergic-cognitive-mesh.md)

---

## Abstract

Three remaining gaps in the SCM formalization require new mathematical frameworks: observer-system circularity (Property 6), emergent state formalization (Property 3), and IFC label enforcement through the processing pipeline. This document synthesizes exhaustive research across second-order cybernetics, sheaf theory, domain theory, traced monoidal categories, information geometry, and information flow control to identify the specific formalisms that address each gap. Implementation recommendations follow.

---

## 1. Observer-System Circularity

### The Problem

Property 6 asserts that the operator is both the system's environment and a component of the system. The SCM spec defines this as constitutive but never formalizes it — all analysis proceeds as if the operator were external.

### Recommended Formalization: Three Layers

**Layer 1 — Structural: Traced Monoidal Categories** (Joyal, Street & Verity, 1996)

The SCM's 14 processes and the operator are morphisms in a symmetric monoidal category. The monoidal product models concurrent trace deposition. The trace operator `Tr: C(A ⊗ U, B ⊗ U) → C(A, B)` closes the operator-system feedback loop by internalizing the operator's behavioral responses as a feedback wire `U`. The resulting morphism `Tr(system_with_operator)` is the autonomous system — the operator is no longer external but structurally integrated.

The Int construction generates the free compact closure, providing "negative types" where the operator's behavior is formally dual to the system's output. Neither the operator nor the system is privileged as "external."

This provides: compositional reasoning about the coupled system, formal semantics for feedback, and the structural guarantee that the operator and system are treated symmetrically.

**Layer 2 — Dynamical: Coupled PCT + Eigenforms** (Powers, 1973; Kauffman, 2005)

The circularity is two interlocking control hierarchies:

```
System loop:   p_sys = f(operator_behavior), e_sys = r_sys - p_sys, output = g(e_sys)
Operator loop: p_op  = h(system_output),     e_op  = r_op  - p_op,  behavior = k(e_op)
```

Stable coupled states are eigenforms (Kauffman, 2005; Kauffman, 2023): fixed points `x*` of the recursive transformation `T(x) = operator_responds_to(system_produces(x))` where `T(x*) = x*`. The eigenform is the stable pattern of interaction — not a static state but a stable behavior (eigenBEHAVIOR).

The DEUTS criterion (Kirchhoff & Kiverstein, 2019) distinguishes constitutive coupling from incidental coupling: the coupling qualifies as constitutive when dynamical entanglement has a unique temporal signature destroyed by severing. This is testable for the SCM: disable the visual surface and observe whether the operator's behavioral patterns change in kind (constitutive) or merely in degree (incidental).

**Layer 3 — Informational: Channel Theory + Non-Well-Founded Sets** (Barwise & Seligman, 1997; Aczel, 1988)

Barwise-Seligman channel theory models information flow through `/dev/shm` as an information channel. The operator and processes are peripheral classifications; the trace space is the core classification. Constraints model what information is available at each node.

Aczel's Anti-Foundation Axiom handles the circular definitions: the operator's situation includes the system, and the system's definition includes the operator. These are non-well-founded sets — mathematically well-defined entities that contain themselves.

**Validation: Game-Theoretic Co-Adaptation** (Madduri & Orsborn, 2026)

A computational framework for co-adaptive neural interfaces models user-decoder mutual adaptation as a dynamic game. The SCM's operator-system circularity maps directly: each party adapts strategy while the other adapts simultaneously. Provides stability analysis (Nash equilibria), convergence guarantees, and design criteria for adaptation rates.

### What This Does NOT Solve

The operator's generative model cannot be fully specified — it is a human mind. The constitutive claim (the system IS part of the operator's cognition, not just a tool) requires philosophical argument beyond what formalism can prove. Formalism can demonstrate structural consistency with constitution, not prove it.

### Key References

- Joyal, A., Street, R. & Verity, D. (1996). "Traced monoidal categories." Math. Proc. Cambridge Phil. Soc., 119(3).
- Kauffman, L.H. (2023). "Autopoiesis and Eigenform." Computation, 11(12), 247.
- Kauffman, L.H. (2005). "EigenForm." Kybernetes, 34(1/2).
- Powers, W.T. (1973). Behavior: The Control of Perception. Aldine.
- Kirchhoff, M. & Kiverstein, J. (2019). Extended Consciousness and Predictive Processing. Routledge.
- Barwise, J. & Seligman, J. (1997). Information Flow: The Logic of Distributed Systems. Cambridge University Press.
- Aczel, P. (1988). Non-Well-Founded Sets. CSLI Lecture Notes.
- Madduri, M.M. & Orsborn, A.L. (2026). "Computational framework to predict and shape human-machine interactions in closed-loop, co-adaptive neural interfaces." Nature Machine Intelligence, 8, 372-387.
- Letelier, J.C. et al. (2023). "Reformalizing the notion of autonomy as closure through category theory." arXiv:2305.15279.
- Varela, F.J. (1979/2024). Principles of Biological Autonomy. MIT Press (annotated edition).

---

## 2. Emergent State Formalization

### The Problem

Property 3 defines emergent perceptual state as "the superposition of all traces" but provides no formalization of what superposition means operationally, how it differs from reading all files, or how to reason about its properties.

### Recommended Formalization: Sheaves + Domains

**Primary: Cellular Sheaves** (Robinson, 2017; Ledent et al., 2025)

The emergent state is a **presheaf** on the reading-dependency graph. Each node (process) has a stalk (the type of data it observes). Restriction maps encode how a reader's observation relates to a writer's output, including cadence mismatch and fusion transforms. A presheaf becomes a **sheaf** when local observations are consistent — they glue into a unique global section.

The critical payoff: **sheaf cohomology provides computable measures of consistency.**

- **H^0** = space of global sections = consistent global states. If H^0 is nontrivial, the mesh has at least one self-consistent configuration.
- **H^1** = obstructions to gluing = algebraic measure of where and how local observations fail to cohere. High H^1 means the mesh's processes disagree about the state of the world.
- **Consistency radius** (Robinson): a scalar measure of how far from consistent the current observations are.

Recent results make this immediately actionable:
- Ledent et al. (2025, arXiv:2503.02556): task solvability in distributed systems equals existence of global sections of a "task sheaf"
- Asynchronous sheaf diffusion (2025, arXiv:2510.00270): proves convergence under bounded delays — directly applicable to cadence-heterogeneous mesh
- Schmid (2025, arXiv:2504.17700): applied sheaf theory for multi-agent AI systems prospectus

Computational tools: pysheaf, AlgebraicJulia, discrete Morse theory algorithms. For a 14-node system, cohomology computation is matrix algebra — tractable.

**Secondary: Scott Domains** (Abramsky & Jung, 1994)

The approximation of ideal state from partial observations is formalized by domain theory. Define a partial order on trace configurations: A ≤ B iff A carries less information. This forms a bounded lattice:

- **Bottom**: empty observation
- **Top**: all traces at most recent values (idealized global state)
- **Compact elements**: finite trace snapshots
- **Ideal elements**: limits of directed sets of compacts (the emergent state)

Scott's information systems provide an alternative: tokens = individual trace key-value pairs, consistency relation = which sets can coexist, entailment = which tokens imply others. Elements of the domain = consistent, deductively closed sets of tokens = possible global states.

The CRDT connection: state-based CRDTs require merge to form a join-semilattice (commutative, associative, idempotent) — guaranteeing strong eventual consistency regardless of delivery order. The SCM's atomic JSON writes are essentially last-writer-wins CRDTs.

**Diagnostic: Persistent Homology** (Edelsbrunner & Harer, 2010)

Topological invariants detect structural phase transitions. Build simplicial complex from trace-reading dependencies. Betti numbers (β₀ = connected components, β₁ = cycles, β₂ = voids) are structural invariants. Persistence barcodes reveal which features are robust. For a 14-node system, computation is exact using GUDHI or Ripser.

### The Unified Answer

"Superposition of all traces" means: the emergent state is a presheaf on the reading-dependency category. It is well-defined when the presheaf is a sheaf (local observations are consistent). Consistency is measured by sheaf cohomology. Approximation from partial observations follows domain theory. Two emergent states are "the same" when they are bisimilar (process algebra). The structural shape over time is captured by persistent homology.

### Key References

- Robinson, M. (2017). "Sheaves are the canonical data structure for sensor integration." Information Fusion, 36.
- Ledent, J. et al. (2025). "A Sheaf-Theoretic Characterization of Tasks in Distributed Systems." arXiv:2503.02556.
- arXiv:2510.00270 (2025). "Asynchronous Nonlinear Sheaf Diffusion for Multi-Agent Coordination."
- Schmid, U. (2025). "Applied Sheaf Theory for Multi-agent AI Systems: A Prospectus." arXiv:2504.17700.
- Abramsky, S. & Jung, A. (1994). "Domain Theory." Handbook of Logic in Computer Science, Vol. 3.
- Shapiro, M. et al. (2011). "Conflict-free Replicated Data Types." SSS 2011.
- Edelsbrunner, H. & Harer, J. (2010). Computational Topology. AMS.
- Goguen, J.A. (1992). "Sheaf semantics for concurrent interacting objects." Math. Structures in CS.

---

## 3. IFC Label Enforcement

### The Problem

ConsentLabel algebra is algebraically complete (join-semilattice proven by Hypothesis). Labeled[T] and Behavior[T] float labels correctly in-memory. But JSON serialization strips labels. Every `/dev/shm` reader sees unlabeled data. Current enforcement uses boundary checking (contract_check), not flow tracking.

### Research Findings

**Full flow tracking is not justified.** Rajani et al. (POPL'20) prove coarse-grained and fine-grained IFC are equally expressive. For a single-operator system with no adversarial execution, boundary enforcement provides equivalent security guarantees to full flow tracking.

**The serialization gap is the real problem.** Labels survive in-memory (Behavior.consent_label floats correctly in the daimonion process) but die at JSON serialization boundaries. The fix is not more sophisticated IFC — it's making labels survive serialization.

**xattr on /dev/shm is infeasible.** tmpfs does not support `user.*` extended attributes. The `trusted.*` namespace requires CAP_SYS_ADMIN.

### Recommended Approach: Embedded Labels + Boundary Gates (~5 days)

1. **Embed `_consent` in JSON payloads.** When writing to `/dev/shm`, include the consent label as a `_consent` field in the JSON:
```json
{
  "stimmung": {"stance": "nominal"},
  "_consent": {"policies": [], "provenance": []},
  "published_at": 1711865000
}
```

2. **Reconstruct labels on read.** When reading from `/dev/shm`, parse `_consent` and reconstruct the ConsentLabel. If `_consent` is absent, treat as bottom (public data).

3. **Enforce at output boundaries.** The 5 output boundaries (API responses, LLM prompts, Qdrant upserts, notifications, visual surface) already have or can trivially add ConsentGatedWriter/Reader checks. Interior processes propagate labels but are not gated.

4. **LLM taint propagation.** When labeled data enters an LLM prompt, the response carries the join of all input labels. Microsoft's FIDES paper (2025) validates this approach for AI agent pipelines.

This preserves the existing consent algebra while making it operational across process boundaries. The boundary enforcement provides equivalent security to full flow tracking for the single-operator use case.

### What Remains Novel

The consent-as-DLM-label approach (repurposing Myers-Liskov Decentralized Label Model for interpersonal consent governance) appears to have no prior art. The provenance semiring applied to consent revocation (Green et al., PODS'07) is also not in the literature. These remain potential publication contributions.

### Key References

- Rajani, V. et al. (2020). "From Fine- to Coarse-Grained Dynamic Information Flow Control and Back." POPL.
- Zeldovich, N. et al. (2006). "Making information flow explicit in HiStar." OSDI.
- Krohn, M. et al. (2007). "Information Flow Control for Standard OS Abstractions." SOSP (Flume).
- Stefan, D. et al. (2011). "Flexible Dynamic Information Flow Control in Haskell." Haskell Symposium.
- Microsoft FIDES (2025). Dynamic taint tracking for AI agent pipelines.
- Green, T.J. et al. (2007). "Provenance Semirings." PODS.

---

## 4. Implementation Priorities

| Gap | Framework | Effort | Impact |
|-----|-----------|--------|--------|
| IFC label enforcement | Embedded JSON labels + boundary gates | ~5 days | Makes dormant consent algebra operational |
| Emergent state | Sheaf cohomology consistency metric | ~2 weeks | First computable mesh health metric |
| Observer-system circularity | Coupled PCT + eigenform analysis | ~3 weeks | Formal foundation for the entire project's thesis |
| ControlSignal extension | Extend pattern to 12 more backends | ~3 days | Completes mesh health coverage |
| AIF tightening | Editorial revision of §3.1 | ~2 hours | Clarifies spec without code changes |

The IFC label enforcement is the highest-priority implementation because it makes existing proven algebra operational. The emergent state formalization (sheaves) is the highest-priority research because it provides the first genuine analytical tool beyond uptime monitoring. The circularity formalization is the deepest research but the least urgent for the running system.
