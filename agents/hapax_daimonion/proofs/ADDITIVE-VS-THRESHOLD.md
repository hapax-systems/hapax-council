# Additive vs Threshold Effects: Research Findings

**Date:** 2026-03-21
**Status:** Research complete. Informs Cycle 2 design.

## The Question

Are the conversational continuity treatment components (thread, message drop,
cross-session memory) additive (each contributes independently)
or threshold-dependent (they must combine to produce the effect)?

## Literature Findings

### Intervention Research (Agent 1)
- Most dismantling studies find weak or null results for individual
  components. Absence of individual effect does NOT mean inert.
- Lewis et al. (2017) identified 5 interaction mechanisms: accumulation,
  amplification, facilitation, cascade, convergence.
- MOST framework (Multiphase Optimization Strategy) uses factorial
  designs specifically to detect interactions.
- Recommended: additive/constructive design, not pure dismantling.

### SCED Multi-Component (Agent 2)
- Two strategies: treatment package (bundle) vs component analysis.
- Hybrid dropout design: ABCDE → BCD → BDE → BCE → CDE confirms
  which components are necessary.
- Package first, dismantle second is the orthodox approach.
- 45-72 sessions for full dropout in a 4-factor design. A 3-treatment
  dismantling design is smaller; sentinel may be probed alongside it as a
  diagnostic, not as a treatment factor.

### Emergence Theory (Agent 3)
- Context anchoring maps to prerequisites for later grounding: presentation
  (thread), session-to-session continuity (memory), and signal preservation
  under bounded context (drop). Sentinel is only a diagnostic for prompt
  integrity.
- Phase transition model: below threshold, no grounding emerges.
- "Each contributing factor is individually insufficient but jointly
  necessary" — Cook's complex systems principle.
- Prediction: qualitative difference with the treatment components together,
  not just quantitative addition.
- JetBrains research: context management techniques are superadditive.

### Pilot Data Analysis (Agent 4)
- Thread alone HAS distinguishable effects: contradiction catching (S11),
  confabulation detection (S7, S12), sustained discussion (S2, S4).
- Cross-session memory is a clearly separable gap: S12 "prevents us
  from remembering we already discovered it."
- Thread fails when: (a) empty (no history), (b) casual topics,
  (c) sessions too short.
- Baseline session 5 showed strong grounding WITHOUT any components —
  architecture itself enables emergent grounding.

## Resolution

The agents disagreed:
- Literature/theory: test package first, dismantle second
- Pilot data: components have separable effects, test individually

Both are right for different questions:
- "Does context anchoring work?" → test the package
- "Which components matter?" → dismantle after package confirmed
- "Do they interact?" → compare package vs sum of individual effects

## Decision

Cycle 2 tests the FULL PACKAGE first (A-B-A'-B' design, 40 sessions).
If the package works, Cycle 3 dismantles. This answers the existential
question before investing in component analysis.

## Open Question

The package components need validation: are they the right components?
Are they correctly scoped? Do they hang together as a coherent gestalt?
This requires further research before Cycle 2 begins.

## References

- Lewis et al. (2017) — 5 interaction mechanisms in complex interventions
- Cook — How Complex Systems Fail (joint necessity principle)
- Clark & Brennan (1991) — grounding prerequisites
- Inoue et al. (2017) — necessary/sufficient conditions for emergence
- Ward-Horner & Sturmey (2010) — component analysis SCED designs
- JetBrains (2025) — superadditive context management techniques

---

*Saved 2026-03-21. Precedes package component research.*
