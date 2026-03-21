---
title: "Hapax Research Lab Journal"
subtitle: "Open research on conversational grounding in voice AI systems"
---

## What This Is

An open lab journal documenting research on whether **context anchoring**
— injecting a turn-by-turn conversation thread into the LLM system
prompt — produces measurable grounding improvements in voice AI
conversation, as theorized by Clark & Brennan (1991) and computationally
formalized by Traum (1994).

This research is conducted on a single-operator voice AI system
([Hapax Council](https://github.com/ryanklee/hapax-council)) using
Bayesian single-case experimental design (SCED) with sequential stopping.

Published with minimal filtering per
[OpenLabNotebooks.org](https://openlabnotebooks.org/) best practices.
Error corrections are handled via update blocks, never deletion.
Git commit SHAs serve as timestamps.

## Current Status

**Cycle 1 (pilot)**: Complete. 17 baseline + 20 intervention sessions.
BF=3.66 (inconclusive on word overlap metric, possibly inflated by
autocorrelation). Qualitative grounding effects observed. Redesigning as
Cycle 2 with corrected methodology.
[Full report](posts/2026-03-19-cycle1-pilot/).

**Cycle 2**: In preparation. 6 methodology deviations from Cycle 1
[formally disclosed](posts/2026-03-21-deviation-disclosure/). New metrics
(embedding-based semantic coherence), Kruschke's BEST analysis, code freeze
with lockdown mode.

## Research Position

The industry converges on profile-gated retrieval for conversational
continuity (ChatGPT Memory, Gemini Personal Intelligence, Mem0). We argue
this is the wrong architecture for sustained relational interaction.
[Position paper](posts/2026-03-19-position/).

**No commercial system implements Clark & Brennan grounding** (Shaikh et al.,
ACL 2025). We are the first to attempt it. We are also the first to honestly
measure where we fall short — implementing 2 of Traum's 7 computational
grounding acts. [Full theoretical analysis](posts/2026-03-21-theoretical-foundations/).

## Journal Entries

[Browse all entries](posts.md) — categorized as `data`, `theory`,
`methodology`, `decision`, `deviation`, `preregistration`.

### Key Documents

- [Theoretical Foundations](posts/2026-03-21-theoretical-foundations/) — Complete literature review, 80+ citations
- [Package Assessment](posts/2026-03-20-package-assessment/) — 3+1 component analysis
- [Position Paper](posts/2026-03-19-position/) — Context anchoring vs profile retrieval
- [Baseline Analysis](posts/2026-03-19-baseline-analysis/) — 17 sessions, 8 patterns
- [Cycle 1 Pilot Report](posts/2026-03-19-cycle1-pilot/) — Methods, results, limitations
- [Deviation Disclosure](posts/2026-03-21-deviation-disclosure/) — Cycle 1 → 2 changes

## Cadence

| Day | Activity | Entry Type |
|-----|----------|-----------|
| Monday | Data review, run analysis | Data entry |
| Wednesday | Conceptual/theoretical work | Theory memo |
| Friday | Week synthesis, decisions | Decision record |

## Data

All session data (JSON) is in the
[proofs directory](https://github.com/ryanklee/hapax-council/tree/main/agents/hapax_voice/proofs).

## License

Text: CC-BY-4.0. Data: CC0.
