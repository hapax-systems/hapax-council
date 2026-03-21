# Refinement Decision: Build the Model Right Before Testing

**Date:** 2026-03-21
**Trigger:** Operator challenge — "Why would we start with a model we know is unrefined if we are looking for gestalt effects that depend on gestalt properties that don't come from nothing?"

## The Realization

We did exhaustive research (12 agents, 80+ citations) to understand what our model SHOULD be. We identified exact gaps. Then we defaulted to "test what we have and see." This is backwards. Gestalt effects emerge from properly composed, properly interacting components. Testing an incomplete system for emergence is testing whether a chord resolves by playing two of four notes.

## What the Research Says Must Be Refined

### 1. Thread Must Capture Acceptance Signals

**Current:** `user_clause → resp_clause` (presentation only — 1/3 of Clark's cycle)
**Required:** `user_clause → resp_clause [ACCEPT|CLARIFY|REJECT|IGNORE]` (presentation + acceptance — 2/3)

The acceptance classification already exists in `grounding_evaluator.py:classify_acceptance()`. It scores to Langfuse. But it never feeds back into the thread. The thread records WHAT was discussed but not WHETHER understanding was established. This is the defining gap.

### 2. Thread Must Preserve Operator Terminology (Conceptual Pacts)

**Current:** First-clause extraction via `split(",")[0].split(".")[0][:60]` — syntax-dependent, destroys operator's chosen words.
**Required:** Preserve the operator's actual referring expressions. When the operator says "that beat," the thread should keep "that beat."

Brennan & Clark (1996): Breaking conceptual pacts incurs processing cost. The thread should be the mechanism that maintains pacts.

### 3. Acceptance Must Actuate (Close the Loop)

**Current:** Acceptance is classified but discarded. System behavior is identical regardless of ACCEPT, CLARIFY, REJECT, or IGNORE.
**Required:** If CLARIFY → elaborate. If ACCEPT → advance. If REJECT → retract/correct. If IGNORE → note as ungrounded.

This is the bridge from anchoring to grounding. Without it, the system presents but never adapts based on evidence of understanding.

### 4. Cross-Session Memory Must Seed the Thread

**Current:** Thread and memory are parallel channels. Memory injected once at session start as text block. Thread grows independently from empty.
**Required:** Prior session summaries prepended to thread with epoch markers. Memory becomes part of the active conversational record.

### 5. Thread Cap 15 → 10 (Variable Length)

**Current:** 15 uniform entries (~15 tokens each, ~225 tokens total).
**Required:** 10 entries, variable length. Recent 3 at ~20 tokens (detailed), older entries at ~10 tokens (keyword-only). ~130 tokens total.

Lost in the Middle (Liu et al. 2024): entries 4-12 at 15 are in the attention dead zone.

### 6. At Minimum One More Traum Act

**Current:** 2 of 7 (initiate, continue).
**Required:** At minimum request-acknowledge ("does that make sense?"). Cheapest to add, closes the grounding loop, directly addresses Shaikh et al.'s finding that LLMs are 3x less likely to initiate clarification.

## The Principle

**These phenomena are substrate-independent.** Grounding theory doesn't care whether the substrate is two humans, a human and a computer, or a human and an LLM with a context window. The mechanisms are the mechanisms. If Clark says grounding requires presentation + acceptance + evidence of understanding, then our system needs all three — not as aspirational future work, but as preconditions for the gestalt to emerge.

We should not test a system we know is incomplete for effects that require completeness.

## Next Step

Research everything needed to properly refine each gap. Independent deep research per concern. Then implement, THEN test.
