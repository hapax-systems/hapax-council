# Package Assessment: Conversational Continuity Components

**Date:** 2026-03-20 (updated 2026-03-21 with deep research findings)
**Audited by:** 12 independent research agents + synthesis
**Question:** Does this package hang together?
**Companion:** See `THEORETICAL-FOUNDATIONS.md` for complete literature review

## Executive Summary

**Yes, with caveats.** The 4-component package (thread, message drop, cross-session memory, sentinel) forms a theoretically coherent gestalt with strong structural symmetry across cognitive science, database systems, and communication theory. All 4 components are built and functional. However, the package implements *context anchoring*, not *grounding* per Clark — a distinction the EPISTEMIC-AUDIT already acknowledges. Two components have scope limitations that should be addressed before Cycle 2.

## Component Status

| Component | Built | Tested | Experiment-Gated | Theoretical Role |
|-----------|-------|--------|-------------------|-----------------|
| Thread (stable_frame) | 100% | Yes | Yes | Within-session context provision |
| Message Drop | 100% | Yes | Yes | Within-session context maintenance |
| Cross-Session Memory | 100% | Yes | Yes | Cross-session context provision |
| Sentinel Fact | 75% | Partially | Yes | Cross-session context verification |

### Thread (stable_frame) — FULLY BUILT

**What it does:** Accumulates first-clause summaries per turn (`"{user_clause} → {resp_clause}"`), max 15 entries (~225 tokens). Injected into STABLE band of system prompt. Survives prompt rebuilds.

**What it captures:** User utterance substance, assistant response opening, turn sequence.

**What it misses:**
- Acceptance signals (ACCEPT/CLARIFY/REJECT scored by evaluator but never fed back into thread)
- Emotional tone / affect
- Topic metadata (computed only for session digest, not injected during turns)
- Semantic depth beyond first clause
- Temporal anchoring (no timestamps on entries)

**Assessment:** Implements one-third of Clark's grounding cycle (presentation). Does not capture acceptance or evidence of understanding *within the thread itself*. The evaluator scores these metrics separately but they remain observational, not actuated. This is the defining gap: the thread tells the model what was discussed, but not whether understanding was established.

**Scale concern:** 15 entries puts entries 4-12 in the "Lost in the Middle" attention dead zone. Research consensus recommends 7-10 entries for reliable recall. First-clause extraction is syntax-dependent (splits on comma/period), not semantic.

### Message Drop — FULLY BUILT

**What it does:** When `len(messages) > 12`, keeps system message + last 5 user exchanges. Thread compensates for dropped content.

**Assessment:** Sound engineering, but may be solving a problem that doesn't exist. Baseline sessions average 5-8 turns (trigger at turn 6+). Reference accuracy is 0.956 across all sessions — no evidence of context rot in current session lengths. The thread compensation theory is correct in principle but untested empirically because sessions rarely get long enough to trigger meaningful drops.

**Verdict:** Keep as-is. Low risk, low cost. Will become important if sessions grow longer, which is a reasonable expectation as the system improves.

### Cross-Session Memory — FULLY BUILT

**What it does:** At session end, persists thread + metadata to Qdrant (`operator-episodes` collection). At session start, scrolls for 3 most recent voice sessions, injects as `## Recent Conversations` block (~100 tokens).

**Critical finding:** Thread and memory are *parallel channels, not integrated*. Memory is injected once at session start. Thread grows per-turn. Memory never seeds the thread. They occupy adjacent positions in the system prompt but have no structural relationship.

**Retrieval mechanism:** Recency-only (scroll by timestamp, not semantic search). This means the 3 most recent sessions load regardless of topical relevance. A conversation about studio cameras from a week ago is invisible when the user starts talking about cameras today.

**Assessment:** Solves *session label continuity* ("we talked about X last time") but not *grounding continuity* ("I understand why X matters and how our prior discovery applies here"). The EPISTEMIC-AUDIT calls this honestly: "May produce anchoring without producing grounding."

### Sentinel Fact — 75% BUILT

**What it does:** Injects a random 2-digit number into the system prompt (`"The operator's favorite number this session is {N}"`). After each response, checks if the model produced that number. Scores 1.0/0.0/None to Langfuse.

**What's missing:** Proactive probe scheduling. The operator must naturally ask "what's my favorite number?" — the system has no mechanism to prompt this at scheduled turns (2, 5, 10+) as the hypothesis specifies.

**Deeper concern:** The sentinel tests *retrieval*, not *grounding*. A model can score 1.0 on sentinel retrieval (follows injected instruction perfectly) while scoring 0.0 on actual conversational grounding (doesn't track operator context, makes contradictory references). The sentinel is a measurement instrument, not a grounding component. It tells you the prompt is intact, not that understanding was established.

**False positive risk:** 2-digit numbers appear naturally in responses (counts, timestamps, status codes). No distinction between "your favorite number is 42" and "I have 42 tabs open."

## Structural Analysis

### The 2x2 Matrix

The 4 components map to a clean decomposition:

|  | Within-Session | Cross-Session |
|---|---|---|
| **Context Provision** | Thread | Memory |
| **Context Maintenance** | Drop | Sentinel |

No cell is empty. No cell is duplicated. Each component has high cohesion (does one thing) and moderate coupling (interact through shared state, not internal dependencies).

### Formal Composition

Components are state transformations on `S = (M, T, K, V)`:

- `C_thread`: Append turn summary to T
- `C_drop`: Prune M to fit window
- `C_memory`: Query Qdrant, inject facts into K
- `C_sentinel`: Verify injected fact in output, update V

**Non-commutative ordering matters:**
- Thread before Drop (summarize before pruning, or you lose content)
- Thread before Memory (thread enriches the retrieval query)
- Sentinel last (verify the assembled context)

Recommended composition: `C_sentinel ∘ C_drop ∘ C_memory ∘ C_thread`

### Multiple Structural Analogies

| Component | Cognitive (Baddeley) | Database | Communication (Shannon) |
|-----------|---------------------|----------|------------------------|
| Thread | Episodic Buffer | Write-Ahead Log | Channel State |
| Drop | Attentional Filtering | Log Compaction / GC | Bandwidth Limit |
| Memory | Long-Term Retrieval | Indexed Snapshot Query | Shared Codebook |
| Sentinel | Metacognitive Monitoring | Checksum / Integrity | Error Detection Code |

Three independent domains arrive at the same 4-function decomposition: **any system maintaining shared state over time under bounded resources needs accumulate, prune, recall, verify.**

## Does the Package Hang Together?

### Functionally: YES

Each component addresses a distinct concern. Thread provides within-session continuity. Drop prevents context overflow. Memory bridges sessions. Sentinel verifies integrity. Removing any one creates a specific gap:

- Without Thread: no accumulated narrative. Each turn is independent within session.
- Without Drop: long sessions overflow context window.
- Without Memory: every session starts cold.
- Without Sentinel: no way to detect silent context corruption.

### Theoretically: PARTIALLY

The package implements *context anchoring* — unidirectional injection of context at privileged positions. Clark's *grounding* requires bidirectional mutual understanding with uptake signals and repair cycles. The package provides the infrastructure on which grounding could be built, but is not itself a grounding mechanism.

**What's missing from Clark:**
1. **Acceptance-to-action loop** — Acceptance is classified but not actuated. If the operator says "huh?" (CLARIFY), the system should increase elaboration. Currently it doesn't.
2. **Repair mechanisms** — No barge-in repair. No contradiction correction. No retraction.
3. **Least collaborative effort** — System always operates at same effort level. No modulation based on grounding success. (Salience router is disabled for experiment — correct methodologically, but leaves this gap in production.)
4. **Mutual monitoring** — During TTS, the system is presenting without monitoring. Grounding blackout.

### Formally: YES

Components compose as a transformation monoid with well-defined non-commutative ordering. Each transformation is predictable (deterministic or quasi-deterministic). The composition is associative. Stochasticity enters only through the LLM's use of assembled context, not through assembly itself.

### As a Gestalt: YES, with the right framing

The full package produces an emergent property no subset provides: **bounded, verified, cross-session conversational continuity.** Any 3-component subset has a specific gap:

- Thread + Memory + Drop without Sentinel: no failure detection
- Thread + Memory + Sentinel without Drop: long session overflow
- Thread + Drop + Sentinel without Memory: no cross-session continuity
- Memory + Drop + Sentinel without Thread: no within-session narrative (this is profile-retrieval with guardrails)

## Pairwise Interaction Predictions

| Pair | Interaction | Testable Prediction |
|------|-------------|-------------------|
| Thread + Memory | **Synergistic** | Memory seeds early-turn context → thread summaries richer from turn 1. First-turn anchor > 0.5 (vs 0.5 neutral baseline). |
| Thread + Drop | **Complementary** | Thread preserves meaning that Drop removes. Reference accuracy maintained even in long sessions (>10 turns). |
| Memory + Drop | **Weakly synergistic** | Memory provides stable anchors surviving Drop's pruning. |
| Memory + Sentinel | **Independent** | No interaction expected. |
| Thread + Sentinel | **Weakly synergistic** | Better thread → more reliable sentinel verification (model attends to full STABLE band). |
| Drop + Sentinel | **Diagnostic** | If sentinel fails after Drop, indicates too-aggressive pruning. |

## Recommendations for Cycle 2

### Do Before Cycle 2

1. **Reduce thread cap from 15 to 10.** Entries 4-12 at 15 sit in the attention dead zone. Variable-length entries: recent 3 at ~20 tokens, older entries at ~10 tokens (keyword-only). Total budget: ~130 tokens (down from ~225).

2. **Decide sentinel's role.** Two options:
   - **Keep as measurement instrument** (current): Accept it tests retrieval, not grounding. Rename claim to "system prompt integrity verification." Don't include in the "grounding package" — treat as cross-cutting diagnostic.
   - **Upgrade to natural fact probe**: Replace 2-digit number with operator-provided facts emerging from conversation ("I'm working on the timing fix"). More ecologically valid, better theoretical alignment. Higher implementation cost.

3. **Document the anchoring/grounding distinction explicitly in pre-registration.** The package provides *context anchoring*. Grounding is the hypothesis — does anchoring lead to grounding? Don't claim the package *is* grounding.

### Consider for Cycle 2

4. **Add semantic retrieval to cross-session memory.** Currently recency-only. Hybrid: 2 by recency + 1 by semantic similarity to current conversation. Small change, significant improvement.

5. **Thread seeding from memory.** At session start, prepend loaded memory summaries to `_conversation_thread` with epoch markers: `[PRIOR SESSION]: ...`. This integrates the parallel channels.

### Defer Past Cycle 2

6. **Acceptance-to-action loop** (5th component candidate). Feed acceptance classification back into next turn's context assembly. This is the bridge from anchoring to grounding.

7. **Barge-in repair** (already documented in BARGE-IN-REPAIR.md). Required for Clark-compliant grounding but correctly deferred.

8. **Effort modulation** (salience router re-integration). Held constant for experiment. Production deployment needs this.

## SCED Methodology: Package vs Component Testing

Kazdin (2011, *Single-Case Research Designs*, Oxford) defines three sequential strategies:

1. **Treatment Package Strategy** — demonstrate the full package works (A-B-A reversal). "The logical first step."
2. **Dismantling Strategy** — remove components one at a time to identify active ingredients. Only after package effect is established.
3. **Parametric Strategy** — optimize parameters of active components.

Ward-Horner & Sturmey (2010, JABA 43(4)) formalize dropout vs add-in designs: present full package, systematically remove one component. When removal degrades performance, the removed component is *necessary*. Their review of 30 component analyses found most studies identify necessary components but fail to evaluate sufficiency.

**Our A-B-A reversal testing the full package is standard practice per this literature.**

### Clark & Brennan Alignment

| Component | Predicted by Clark & Brennan (1991)? | Role |
|-----------|--------------------------------------|------|
| Thread | **Yes, core.** Maps directly to common ground updating "increment by increment" (Clark 1996, Ch. 4) |
| Message Drop | **Yes, supporting.** Enables "reviewability" constraint that Clark identifies as critical for grounding |
| Cross-Session Memory | **Partially.** Restores personal common ground (prior shared experience). Grounding theory focuses on within-conversation processes; this is about initial state, not process |
| Sentinel | **No.** Test instrumentation, not a conversational mechanism. Nothing in Clark predicts this |

### Construct Validity Concern

Per Ward-Horner & Sturmey's logic: the sentinel should be treated as a **dependent measure** (does the system maintain prompt integrity?) rather than a component of the intervention package. Including it as a "component" inflates the package with a non-therapeutic element, threatening construct validity (Kazdin 2011).

**Recommendation:** The package under test should be framed as 3 components (thread + drop + memory) with sentinel as a cross-cutting diagnostic instrument. This preserves construct validity and clarifies what the independent variable actually is.

### Necessity/Sufficiency Matrix

| | Necessary | Not Necessary |
|---|-----------|---------------|
| **Sufficient** | Core standalone (package unnecessary) | Redundant alternative |
| **Not Sufficient** | Essential package member | Dead weight |

A coherent package has components that are all necessary but individually not sufficient. The dismantling phase (Cycle 3+) would populate this matrix empirically.

### Sources

- Kazdin (2011), *Single-Case Research Designs*, 2nd ed., Oxford
- Ward-Horner & Sturmey (2010), JABA 43(4), 685-704
- Collins et al. (2005), Multiphase Optimization Strategy (MOST)
- Clark & Brennan (1991), "Grounding in Communication"
- Hains (1989), JABA 22, "Interaction Effects in Multielement Designs"

## Package Verdict

| Question | Answer |
|----------|--------|
| Does it hang together? | **Yes** — structurally, formally, and functionally coherent |
| Is it correctly partitioned? | **Yes** — 2×2 matrix with no gaps or redundancies |
| Is it sufficient for grounding? | **No** — it provides anchoring infrastructure. Grounding requires closing the acceptance loop |
| Is it overstuffed? | **Slightly** — sentinel is a measurement instrument, not a treatment component. Reframe as 3+1 (3 treatment + 1 diagnostic) |
| Is it the right thing to test? | **Yes** — test the architecture first, add interaction quality mechanisms second |
| Should we test as package or individually? | **Package first** (Kazdin 2011). Dismantle in Cycle 3+ only if package effect is established |
| Is sentinel a grounding component or a measurement instrument? | **Measurement instrument.** Treat as dependent measure, not independent variable |

## Critical Methodological Findings (from deep research)

### A-B-A May Be Inappropriate for Grounding

Barlow, Nock & Hersen (2009): reversal designs are not warranted when the intervention entails learning. Grounding creates persistent knowledge structures — once common ground is established, removing the mechanism doesn't erase the knowledge. The operator learns how the system communicates; expectations shaped by B phase persist into A'.

**Options**:
1. A-B-A-B (3 phase-change demonstrations, ends on treatment)
2. Multiple baseline across behaviors (stagger metrics)
3. Acknowledge carryover explicitly; analyze A' as "residual of learning"
4. Pre-specify what "reversal" means operationally

**Decision needed before Cycle 2 launch.**

### We Are Underpowered

At expected d=0.3-0.6, 20 sessions/phase gives only 40-50% probability of reaching BF>10. Most likely outcome is moderate/inconclusive evidence (3 < BF < 10). Pre-commit to extending if inconclusive.

### Autocorrelation Inflates Our Statistics

Turns within sessions are not independent. Typical SCED autocorrelation r=0.20 (Shadish et al. 2013). Effective N drops by factor (1+r)/(1-r). Cycle 1's BF=3.66 may be 2.0-2.5 after correction.

**Mitigation**: BEST on session means (aggregation removes within-session correlation).

### Beta-Binomial Is Wrong for Continuous Data

Must use Kruschke's BEST (t-distributed likelihood, posterior HDI + ROPE) instead of beta-binomial with binarization. This is a model specification fix, not a preference.

### Traum Mapping Gap

We implement 2 of 7 computational grounding acts (initiate, continue). We classify the operator's acts but perform none of the 5 responsive acts (acknowledge, repair, request-repair, request-acknowledge, cancel). This is the honest scope of our system.

## Token Budget Summary

| Component | Current | Recommended | Change |
|-----------|---------|-------------|--------|
| Thread | ~225 tokens (15 × 15) | ~130 tokens (10 variable) | -42% |
| Message history | ~500-1000 (5 exchanges) | ~500-1000 (keep) | — |
| Cross-session memory | ~100 (3 episodes) | ~120 (2 recency + 1 semantic) | +20% |
| Sentinel | ~30 | ~30 (keep) | — |
| **Total fixed grounding** | **~355** | **~280** | **-21%** |
