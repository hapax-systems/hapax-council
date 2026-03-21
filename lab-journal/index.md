---
title: "Hapax Research Lab Journal"
subtitle: "Open research on conversational grounding in voice AI systems"
---

## What This Is

An open lab journal documenting research on whether **context anchoring**
— injecting a turn-by-turn conversation thread into the LLM system
prompt — produces measurable grounding improvements in voice AI
conversation.

This research is conducted on a single-operator voice AI system
([Hapax Council](https://github.com/ryanklee/hapax-council)) using
Bayesian single-case experimental design (SCED).

## Current Status

**Cycle 1 (pilot)**: Complete. 17 baseline + 20 intervention sessions.
BF=3.66 (inconclusive on word overlap metric). Qualitative grounding
effects observed but not captured by primary metric. Redesigning as
Cycle 2 with corrected methodology.

**Cycle 2**: In preparation. New metrics (embedding-based semantic
coherence), corrected pre-registration (OSF), Kruschke's BEST analysis.

## Counter-Position

The industry converges on profile-gated retrieval for conversational
continuity (ChatGPT Memory, Gemini Personal Intelligence). We argue
this is the wrong architecture — see [Position](../agents/hapax_voice/proofs/POSITION.md).

## Documents

- [Position Paper](../agents/hapax_voice/proofs/POSITION.md) — Context anchoring vs profile retrieval
- [Observability Framework](../agents/hapax_voice/proofs/OBSERVABILITY.md) — Three-class scoring (G/R/F)
- [Cycle 1 Pilot Report](../agents/hapax_voice/proofs/CYCLE-1-PILOT-REPORT.md) — Methods, results, limitations
- [Baseline Analysis](../agents/hapax_voice/proofs/BASELINE-ANALYSIS.md) — 17 sessions, 8 patterns
- [Claim 6: Bayesian Tool Selection](../agents/hapax_voice/proofs/claim-6-bayesian-tools/RESEARCH.md) — Future direction
- [Running Observations](observations.md) — Timestamped notes

## Data

All session data (JSON) is in the
[proofs directory](https://github.com/ryanklee/hapax-council/tree/main/agents/hapax_voice/proofs).

## License

Text: CC-BY-4.0. Data: CC0.
