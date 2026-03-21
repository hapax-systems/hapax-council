# Voice Grounding Research State

**Last updated:** 2026-03-21
**Update convention:** After any session with research decisions or implementation progress, update this file before ending.

## Position (one paragraph)

We are building the first system that attempts to operationalize Clark & Brennan's (1991) conversational grounding theory in a production voice AI. We position AGAINST the industry convergence on profile-gated retrieval (ChatGPT Memory, Gemini, Mem0). No commercial system implements Clark. Shaikh et al. (ACL 2025) showed all frontier LLMs score 23.23% on grounding tasks (worse than random). RLHF actively suppresses grounding acts (Shaikh NAACL 2024). OpenAI's model spec explicitly instructs models NOT to ask clarifying questions. We are genuinely novel and genuinely alone.

## Current Phase

- **Cycle 1:** COMPLETE (pilot, 37 sessions, BF=3.66 inconclusive, word overlap metric wrong)
- **Cycle 2:** IMPLEMENTATION IN PROGRESS
  - All research complete (28 agents across 4 rounds, 80+ citations)
  - Refined model designed and justified
  - Implementation: **Batches 1-4 COMPLETE** (85 tests passing, not yet committed)
  - Remaining: code freeze, pre-registration update, OSF registration, lab journal backfill
  - Context persistence system built (RESEARCH-STATE.md + memory pointer + CLAUDE.md directive)
  - Operator had a "second thing" to address — not yet stated
- **Cycle 3:** NOT STARTED (contingent on Cycle 2 results; may require fine-tuned model if RLHF anti-pattern binds)

## What Was Built (Batches 1-4)

### Batch 1 — Foundation
- `_EXPERIMENT_PROMPT` in persona.py (~200 tokens, no tools)
- `_EXPERIMENT_STYLE` in conversational_policy.py (~30 tokens, dignity floor + minimal style)
- `ThreadEntry` dataclass: verbatim operator text (preserves conceptual pacts), acceptance signal, grounding state, repair flag, seeded flag
- `_extract_substance()`: no more `split(",")[0].split(".")[0][:60]` — preserves full text, max 100 chars
- `_render_thread()`: tiered compression (recent=full+quotes, middle=referring expression, oldest=keyword)
- Thread cap: 10 entries (down from 15, Lost in the Middle research)
- Phenomenal context: stimmung-only gating for experiment
- Salience: prompt block stripped, router still computes mechanically
- Env context: presence only in experiment mode

### Batch 2 — Grounding Loop
- `grounding_ledger.py` (NEW, ~315 lines):
  - DU state machine: PENDING → GROUNDED/REPAIR-1/REPAIR-2/ABANDONED/CONTESTED/UNGROUNDED
  - Concern-aware repair thresholds (Clark's "sufficient for current purposes"): high concern + low GQI → require ACCEPT (0.9), low concern + high GQI → IGNORE is fine (0.3)
  - GQI computation: 50% EWMA acceptance + 25% trend + 15% consecutive negatives + 10% engagement
  - 2D effort calibration: activation × (1 - gqi_discount) → EFFICIENT/BASELINE/ELABORATIVE with hysteresis
  - Strategy directives injected into VOLATILE band per turn
- Pipeline wired: acceptance feeds ledger with concern_overlap, DU registered per response, directive + effort level injected

### Batch 3 — Memory Integration
- `_load_seed_entries()`: returns list[ThreadEntry] from Qdrant, prioritizes unresolved DUs
- Thread seeding: 2-3 prior session entries with `[PRIOR]` markers
- Age-out: seeded entries compress at 6 current entries, drop at 11
- Persist: unresolved DUs and grounding_state stored in Qdrant payload
- Experiment flags loaded before prompt construction (was after — bug)

### Batch 4 — Observability
- `_score_monologic()`: detects RLHF anti-pattern (monologic=1.0 vs dialogic=0.0)
- `score_directive_compliance()`: did model follow the grounding directive?
- Selective lockdown: grounding directive/effort NOT locked even with volatile_lockdown
- Salience router computes in both phases (activation/concern available mechanically)

## Critical Decisions (with reasoning)

1. **3+1 package**: 3 treatment (thread + drop + memory) + 1 diagnostic (sentinel). WHY: sentinel tests retrieval not grounding; including it as treatment threatens construct validity (Ward-Horner & Sturmey 2010).

2. **Refine BEFORE test**: gestalt effects require properly composed components. WHY: "testing an incomplete system for emergence is playing 2 of 4 notes."

3. **BEST over beta-binomial**: continuous data requires t-distributed likelihood. WHY: beta-binomial wrong for continuous metrics; autocorrelation inflates BF (Shadish et al. 2013 mean r=0.20).

4. **turn_pair_coherence** replaces context_anchor_success. WHY: word overlap penalizes abstraction/paraphrasing; qualitative grounding effects invisible to prior metric.

5. **Always CAPABLE**: intelligence is last thing shed. Salience router becomes effort calibrator, not model selector.

6. **Acceptance must actuate**: classified but not fed back = 1/3 of Clark's cycle. Closing the loop is the bridge from anchoring to grounding.

7. **Conceptual pacts**: preserve operator's verbatim terminology in thread. WHY: Metzing & Brennan 2003 — pact violations maximally costly with single known partner.

8. **Bands = grounding substrate**: STABLE band = discourse record, VOLATILE band = turn-specific directives, stimmung = GQI signal, salience = effort calibrator, concern graph = "sufficient for current purposes."

9. **Every token justified**: system prompt stripped to ~800-1000 tokens for experiment. No tool descriptions, no profile digest, no environmental modulation.

10. **GQI as stimmung dimension**: 10th dimension, unidirectional (no circular dependency). GQI reads conversation signals only, feeds stimmung, stimmung renders in Layer 1.

## Open Questions

- A-B-A vs A-B-A-B design (Barlow: reversal inappropriate for learning interventions)
- Effect size target from Cycle 2 baseline data
- OSF registration timing and format
- RLHF anti-pattern: prompted Opus sufficient or fine-tuning needed? (Cycle 3 decision)
- GitHub Pages still needs enabling for lab journal
- Redis noeviction policy needs persistent config

## Key Documents (read to reconstruct full context)

| Document | Tokens | Content |
|----------|--------|---------|
| `THEORETICAL-FOUNDATIONS.md` | ~8K | Full literature review: Clark, Traum, Brennan, counter-positions, SCED methodology, emergence, LLM architectures |
| `REFINEMENT-RESEARCH.md` | ~5K | 8 research streams → refined model design |
| `PACKAGE-ASSESSMENT.md` | ~4K | Component analysis, 2x2 matrix, structural analogies, SCED methodology |
| `POSITION.md` | ~3K | Counter-positioning vs profile retrieval, 5 failure modes |
| `WHY-NO-ONE-IMPLEMENTED-CLARK.md` | ~3K | 32-year gap analysis: obstacles, misconceptions, historical accidents |
| `CYCLE-2-PREREGISTRATION.md` | ~3K | Experiment design: ABA, BEST, HDI+ROPE, session protocol |
| `CYCLE-1-PILOT-REPORT.md` | ~2K | Methods, results, 6 deviations, limitations |
| `BASELINE-ANALYSIS.md` | ~2K | 17 sessions, 8 patterns |
| `REFINEMENT-DECISION.md` | ~1K | Decision to refine before testing |
| `SYSTEM-CLEANUP-DECISION.md` | ~1K | Strip to research essentials directive |
| Plan: `shimmering-growing-lollipop.md` | ~3K | Implementation batches 1-4 |

## Operator Research Preferences

- "Clean out ALL GUNK. No need for ANYTHING other than what's justified for research."
- Independent research agents per major concern — deep, broad, don't leave anything out
- Substrate independence: phenomena don't care about implementation
- Composable perspectives: decomposable, independently tappable
- Always CAPABLE model — willing to wait if indicated and justified
- Continuous cognitive loop, not request-response state machine
- No stale branches ever — PR completed work immediately
- "If we are talking about a gestalt, let's not be soft idiots about it"
