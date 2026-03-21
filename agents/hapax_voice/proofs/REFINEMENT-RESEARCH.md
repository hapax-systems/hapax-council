# Refinement Research Synthesis: What We Now Know

**Date:** 2026-03-21
**Source:** 8 independent deep research agents
**Purpose:** Everything needed to properly refine the model before testing

---

## The Design That Emerges

Eight research streams converge on a coherent refined model. Each refinement is justified by specific research, has a concrete implementation path, and addresses a specific gap in the current system relative to Clark/Traum's grounding theory.

---

## 1. Thread Entry Redesign

**Problem:** `split(",")[0].split(".")[0][:60]` destroys conceptual pacts (Brennan & Clark 1996), loses acceptance signals, treats all turns as equivalent.

**Research basis:**
- Metzing & Brennan (2003): pact violations are maximally costly with a single known partner (our case)
- Mohapatra et al. (2024, LREC-COLING): grounding acts annotation validates content+state tracking
- He et al. (2024, arXiv 2411.10541): semi-structured formats (pipe delimiters) get most of JSON's benefit without token overhead
- C-DIC (OpenReview 2025): compression should be revisable, not write-once

**Design: Tiered hybrid format, 10 entries, ~125 tokens**

Recent tier (last 3, ~20 tokens each):
```
T8 "what about that beat we were working on" | tempo-sync explained | ACCEPT
```

Middle tier (4-7 back, ~10 tokens each):
```
T5 "that beat" timing | tempo-sync | OK
```

Oldest tier (8-10 back, ~8 tokens each):
```
T2 beat-timing | sync | OK
```

Repair entries:
```
T7 "no the aux send" | REPAIR:which-send | ?
```

**Key properties:**
- Operator's words quoted verbatim in recent entries (pact preservation)
- REPAIR prefix makes ungrounded DUs visible
- Abbreviated acceptance (ACCEPT→OK, REJECT→NO, CLARIFY→?, IGNORE→-)
- Header: `## Conversation Thread (most recent last)`

---

## 2. Acceptance-to-Action Loop (Closing the Grounding Cycle)

**Problem:** Acceptance is classified (ACCEPT/CLARIFY/REJECT/IGNORE) but never actuates behavior change. The system responds identically regardless of grounding state.

**Research basis:**
- RavenClaw (CMU, Bohus & Rudnicky 2003-2009): deployed concept-level grounding with ACCEPT/IMPL_CONF/EXPL_CONF strategy selection
- AutoTutor (Graesser et al. 2004): pump→hint→prompt→assertion escalation based on understanding state
- ITSPOKE: misunderstandings vs misconceptions require different repair strategies
- Bohus empirical finding: "move on" strategy (mark ungrounded, advance) beats persistent re-asking

**Design: DU-level grounding ledger + strategy injection**

Per system utterance, create a Discourse Unit with state:
```
PENDING → GROUNDED     (on ACCEPT or relevant next contribution)
PENDING → REPAIR-1     (on first CLARIFY → rephrase)
REPAIR-1 → REPAIR-2    (on second CLARIFY → elaborate with example)
REPAIR-2 → ABANDONED   (max repairs → move on)
PENDING → CONTESTED    (on REJECT → present reasoning, don't retract)
PENDING → UNGROUNDED   (on IGNORE → don't build on it)
```

Inject grounding state into each LLM call as structured context. Cap repair at 2-3 attempts per DU. Never auto-retract on REJECT. Smooth signals with EWMA to prevent oscillation.

**Critical:** "Relevant next contribution" is the strongest ACCEPT signal — the operator builds on what you said without saying "yes." Use turn_pair_coherence between operator's new utterance and system's prior DU as detection mechanism.

---

## 3. Grounding State Tracking

**Problem:** No per-DU state tracking. Thread is just strings with no grounding metadata.

**Research basis:**
- Traum (1994): Recursive transition network with states S/1/2/3/4/F/D and 7 grounding acts
- Roque & Traum (2008): 4 degrees of grounding (high/medium/low/ambiguous)
- Paek & Horvitz (2000): Probabilistic grounding as Bayesian inference with decision-theoretic criterion
- RavenClaw: concept-level confidence tracking with dynamic thresholds

**Design: Start Tier 1 (acceptance-as-proxy), build toward Tier 2 (grounding register)**

**Tier 1** (immediate): Add `grounding_state` field to thread entries. Update from next turn's acceptance classification. Zero new machinery.

**Tier 2** (target): Grounding register alongside thread:
```python
{du_id: 1, turn: 3, state: "grounded", confidence: 0.85, evidence: "relevant_next_turn"}
```

Confidence mapping (Roque & Traum evidence hierarchy):
- Continued attention → 0.3
- Relevant next contribution → 0.7
- Explicit acknowledgment ("okay") → 0.5
- Demonstration (operator uses the content) → 0.85
- Repeat back → 0.95

**What this enables:**
- Don't build on ungrounded DUs
- Prioritize repair over new content when grounding is low
- Only persist GROUNDED content to cross-session memory
- Stimmung integration (low grounding → tension/disconnection)

---

## 4. Effort Modulation

**Problem:** System operates at constant effort regardless of grounding state. Clark's Principle of Least Collaborative Effort requires dynamic calibration.

**Research basis:**
- Clark & Wilkes-Gibbs (1986): 86% efficiency gain through collaborative effort reduction
- Shaikh et al. (2024, NAACL): RLHF specifically reduces grounding acts — LLMs are anti-Clark
- YapBench (2026): LLMs over-explain simple tasks, under-explain complex (inverted from Clark)
- Janarthanam & Lemon (2014): RL-based adaptive generation improved task success
- AutoTutor: 0.5-0.6 SD improvement with adaptive effort

**Design: Grounding Quality Index (GQI) → 3 discrete effort levels**

```
GQI = 0.50 * rolling_acceptance_ewma
    + 0.25 * coherence_trend_normalized
    + 0.15 * (1 - consecutive_negative / 3)
    + 0.10 * user_engagement_signal
```

| Level | GQI | Words | Checks | Explicitness |
|-------|-----|-------|--------|-------------|
| EFFICIENT | >0.75 | 22-25 | Never | Elliptical |
| BASELINE | 0.45-0.75 | 30-35 | Rare | Standard |
| ELABORATIVE | <0.45 | 40-48 | Every 2-3 turns | Examples, explicit |

Hysteresis: escalation immediate, de-escalation damped one level per turn.

**Verdict:** Required for gestalt. But acceptance-actuation IS the minimum viable form. GQI is the refined version.

---

## 5. Request-Acknowledge and Other Traum Acts

**Problem:** System implements only 2 of 7 grounding acts (initiate, continue).

**Research basis:**
- Mohapatra et al. (2024): Request-Acknowledge is 0.01% of human utterances — the RAREST act
- AutoTutor: "Do you understand?" is unreliable — good students say "no" more than poor ones
- Shaikh et al. (2025): LLMs are 3x less likely to clarify than humans
- Healey et al. (2018): Repairs occur every ~25 words — they're normal, not exceptional

**Design: Priority-ordered Traum act additions**

1. **REPAIR** (self-correction): "Actually wait — you meant the other one, right?" Highest impact, most natural. Trigger: low reference_accuracy or contradiction detected.

2. **REQUEST-REPAIR** ("Sorry, I missed that"): Already partially exists. Make explicit with canned fallback.

3. **REQUEST-ACKNOWLEDGE**: Deploy with strict governor. Max 1 per 7 turns, max 2 per session. Never on simple content. Form: trailing discourse markers ("yeah?") or implicit via application ("so which should we start with?"). NOT "does that make sense?"

4. **CANCEL**: Edge case. "Scratch that — the tool says something different."

**Governor prevents over-deployment:** 5 trigger conditions (ALL must hold) + 5 anti-conditions (ANY blocks).

---

## 6. Conceptual Pact Preservation

**Problem:** First-clause extraction destroys operator's referring expressions.

**Research basis:**
- Brennan & Clark (1996): Pacts are partner-specific, form in 2-3 references
- Metzing & Brennan (2003): Breaking pacts causes delayed comprehension, wrong-referent fixation
- Shi et al. (2023, EMNLP): System should entrain to operator, not vice versa
- Kumar & Dusek (2024, NAACL): Entrainment-specific training improves naturalness

**Design: Verbatim operator utterance preservation**

Replace `_extract_substance()` → `split(",")[0].split(".")[0][:60]` with: store post-greeting-stripped operator utterance up to ~100 chars. Voice utterances are 10-30 words — already compressed. Token cost delta: ~150 tokens for 15 turns (negligible).

**The thread IS the pact memory.** The LLM will entrain to whatever words it sees in the thread. If the thread preserves the operator's words, the model naturally maintains pacts via in-context priming (Pickering & Garrod's alignment mechanism).

---

## 7. Thread-Memory Integration (Episodic Buffer)

**Problem:** Thread and cross-session memory are parallel channels with no structural relationship.

**Research basis:**
- Baddeley (2000): Episodic buffer binds working memory and long-term memory
- Tulving & Thomson (1973): Encoding specificity — retrieval context must match encoding context
- Park et al. (2023): recency × relevance × importance scoring
- SeCom (ICLR 2025): Segment-level memory outperforms session-level

**Design: Keep separate stores, add episodic buffer as integration layer**

```
CROSS-SESSION MEMORY (Qdrant)     THREAD (in-process)
        |                              |
        v                              v
    ┌────────────────────────────────────┐
    │        EPISODIC BUFFER             │
    │  - Seeds thread (2-3 entries)      │
    │  - Ages out seeded entries         │
    │  - Re-queries on cue detection     │
    │  - Extracts pacts for persistence  │
    └────────────────────────────────────┘
                    |
                    v
            SYSTEM PROMPT
```

Seeded entries use `[PRIOR]` epoch markers. Age out: compress at 6 entries, drop at 11.

---

## 8. Retrieval Strategy

**Problem:** Recency-only retrieval misses relevant older sessions.

**Research basis:**
- SeCom (ICLR 2025): Segment-level > session-level memory
- Park et al. (2023): recency × relevance × importance
- Tulving: encoding specificity
- Berntsen (2009): Human memory is cue-driven, not periodic

**Design: Grounding-aware hybrid retrieval**

Scoring: `0.3*recency + 0.35*relevance + 0.2*importance + 0.15*grounding_urgency`

Where grounding_urgency: unresolved=1.0, corrected=0.5, acknowledged=0.2.

Session start: retrieve unresolved DUs first (open loops). Then top-3 by hybrid score with cosine threshold > 0.4.

Mid-session: cue-driven (topic overlap detection). Async Qdrant query (~20-50ms), inject next turn. Zero added latency.

**Store per segment:** content embedding + grounding_state + importance + superseded_by chain.

**Empty is better than irrelevant.** Relevance threshold gates injection.

---

## Implementation Priority

Based on impact, feasibility, and gestalt dependency:

| Priority | Refinement | Impact | Cost | Gestalt Role |
|----------|-----------|--------|------|-------------|
| 1 | Thread entry redesign (verbatim + acceptance + tiers) | HIGH | LOW | Pact preservation, grounding visibility |
| 2 | Acceptance-to-action loop (DU ledger + strategy) | HIGH | MEDIUM | Closes the grounding cycle |
| 3 | Grounding state tracking (Tier 1: acceptance-as-proxy) | HIGH | LOW | Don't build on ungrounded content |
| 4 | Effort modulation (GQI → dynamic word limit) | HIGH | LOW | Least collaborative effort principle |
| 5 | Conceptual pact preservation (verbatim operator words) | HIGH | VERY LOW | Already in #1 |
| 6 | Thread-memory integration (episodic buffer) | MEDIUM | MEDIUM | Cross-session grounding continuity |
| 7 | Retrieval strategy (hybrid + cue-driven) | MEDIUM | MEDIUM | Relevant context surfacing |
| 8 | Traum act additions (repair, request-repair) | MEDIUM | LOW | Completes the grounding act repertoire |

Items 1-5 should be implemented BEFORE Cycle 2 testing. They are the minimum viable gestalt.
Items 6-8 are important but can be added incrementally.

---

## What This Model IS and ISN'T

**IS:** A context anchoring system with grounding awareness — tracks whether mutual understanding was established, adapts effort based on evidence, preserves conceptual pacts, and doesn't build on ungrounded content.

**ISN'T:** Full Clark-compliant grounding — still fundamentally unidirectional (system injects, operator cannot inspect), still lacks mutual monitoring during TTS, still no true installment-based delivery.

**The honest claim:** "We implement presentation + acceptance detection + evidence-driven effort modulation + pact preservation within the constraints of an LLM voice system. This is more grounding machinery than any other conversational AI system has attempted. Whether it produces a measurable gestalt effect is the empirical question."
