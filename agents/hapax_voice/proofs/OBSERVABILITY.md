# Observability Framework: Measuring Against the Counter-Position

## The Problem

We need to measure our system's behavior in a way that:
1. Tracks whether context anchoring is working (our claims)
2. Detects when we accidentally exhibit profile-retrieval patterns (our failures)
3. Compares against the industry approach WITHOUT building it

The key insight: **certain metrics are structurally impossible for
profile-retrieval systems to score well on**, while others are easy.
By measuring the right things, we can infer the counter-position's
performance from the structure of the metric itself.

## Three Score Classes

### Class G: Grounding-Native Metrics

These metrics measure phenomena that **only exist in grounding-based
systems**. Profile-retrieval systems score zero or undefined because
they don't track the underlying process. If WE score zero, we've
regressed to profile-retrieval behavior.

| Score | What It Measures | Profile-Retrieval Baseline | Langfuse Name |
|-------|-----------------|---------------------------|---------------|
| **Acceptance tracking** | Did the operator accept, clarify, reject, or ignore? | Undefined — not measured | `acceptance_type` |
| **Frustration detection** | Is grounding breaking down? | Undefined — not measured | `frustration_score`, `frustration_rolling_avg` |
| **Grounding depth** | How many turns before back-references appear? | Undefined — no thread | `grounding_depth` (eval_grounding) |
| **Thread coverage** | How much of the response connects to the conversation thread? | 0.0 — no thread exists | `context_anchor_success` |

**How to read these against the counter-position**: profile-retrieval
has NO acceptance tracking, NO frustration detection, NO thread. These
metrics are structurally zero for the industry approach. Any positive
value from our system demonstrates capability the counter-position
lacks entirely.

**Langfuse implementation**: these are already pushed per-turn. Add
session-level aggregates via `eval_grounding.py`.

### Class R: Retrieval-Native Metrics

These metrics measure things that **profile-retrieval does well**.
We should score AT LEAST as well. If we score worse, the grounding
approach has a real cost that needs addressing.

| Score | What It Measures | Profile-Retrieval Strength | Langfuse Name |
|-------|-----------------|---------------------------|---------------|
| **Preference recall** | Can the system apply known preferences? | High — that's what the profile is for | (sentinel_retrieval as proxy) |
| **Cross-session recall** | Does the system remember prior sessions? | High — profile persists indefinitely | manual probe score |
| **Factual consistency** | Are references to prior content accurate? | Moderate — depends on extraction quality | `reference_accuracy` |
| **Response relevance** | Is the response on-topic? | High — retrieval selects relevant facts | LLM-as-judge in eval_grounding |

**How to read these against the counter-position**: these are the
industry's home turf. If our thread-based approach matches or exceeds
profile-retrieval on THEIR metrics while also providing Class G metrics
they can't, that's the argument.

**Important nuance**: `sentinel_retrieval` is our proxy for preference
recall. In baseline (sentinel OFF), it should be 0 — that's correct.
In intervention, it tests whether injected facts survive prompt
rebuilds. This is analogous to "does the profile lookup work?" but
measured via a mechanistic probe rather than a database query.

### Class F: Failure Mode Detectors

These metrics fire when our system **accidentally exhibits
profile-retrieval behavior** — the five failure modes from POSITION.md.
Any nonzero value is a regression signal.

| Score | Failure Mode | What Triggers It | Langfuse Name |
|-------|-------------|-----------------|---------------|
| **Fact extraction detected** | #1 Extracting facts into separate store | System creates persistent user facts outside the thread | `fm_fact_extraction` |
| **Trigger gating detected** | #2 Gating personalization behind triggers | System checks for trigger phrases before using context | `fm_trigger_gating` |
| **Retrieval query detected** | #3 Treating turns as retrieval queries | System ranks/filters memory by relevance instead of recency | `fm_retrieval_query` |
| **Memory separation detected** | #4 Separating memory from conversation | Memory agent operates independently of conversation flow | `fm_memory_separation` |
| **Retrieval success metric** | #5 Measuring by retrieval accuracy | Evaluation optimizes for "right fact retrieved" over grounding | `fm_retrieval_metric` |

**These are not currently instrumented.** Implementation plan below.

## Langfuse Score Architecture

### Per-Turn Scores (already implemented)

Pushed on every `voice.utterance` trace:

```
context_anchor_success   float 0-1   Class G   thread word overlap
reference_accuracy       float 0-1   Class R   LCS back-reference check
acceptance_type          float 0-1   Class G   ACCEPT/CLARIFY/IGNORE/REJECT
frustration_score        int   0+    Class G   per-turn signal count
frustration_rolling_avg  float 0+    Class G   5-turn rolling average
activation_score         float 0-1   Class G   salience router activation
sentinel_retrieval       float 0-1   Class R   probe question accuracy
total_latency_ms         float ms    infra     end-to-end turn latency
consent_latency_ok       bool        infra     consent threshold pass
```

### Session-Level Scores (via eval_grounding.py)

Pushed as `grounding_eval` event per session:

```
acceptance_rate          float 0-1   Class G   proportion of ACCEPT responses
reference_accuracy       float 0-1   Class R   proportion of correct references
grounding_depth          int   -1+   Class G   turn of first back-reference
judge_summary            str         Class R   LLM-as-judge narrative
```

### Experiment-Level Scores (via experiment_runner.py)

Written to `proofs/claim-N/analysis/` as JSON:

```
bayes_factor             float       per-claim BF against pre-registered prior
decision                 str         continue/stop_h1/stop_h0/stop_max
rope                     dict        posterior mass inside/outside ROPE
success_rate             float 0-1   proportion of sessions meeting threshold
```

## New Scores to Add

### Session-Level Grounding Trajectory (Class G)

Profile-retrieval is stateless per turn — it can't improve within a
session because each turn is an independent lookup. Grounding SHOULD
improve because the thread accumulates context. Measuring the
trajectory within a session is a structural differentiator.

```
anchor_trajectory        float       slope of context_anchor_success across turns
                                     positive = grounding improving (expected)
                                     zero/negative = stateless behavior (failure)

acceptance_trajectory    float       slope of acceptance_type across turns
                                     positive = operator increasingly accepting
                                     flat = no grounding effect

frustration_trajectory   float       slope of frustration_rolling_avg across turns
                                     negative = frustration decreasing (expected)
                                     positive = grounding failing
```

**Why this works against the counter-position**: profile-retrieval
has FLAT trajectories by construction — turn 7 doesn't benefit from
turns 1-6 unless a new fact was extracted. Any positive anchor
trajectory or negative frustration trajectory is evidence of grounding
that profile-retrieval cannot produce.

### Turn-Pair Coherence (Class G)

Measure whether consecutive turns demonstrate mutual understanding,
not just individual quality.

```
acceptance_after_anchor  float 0-1   P(ACCEPT at turn N+1 | high anchor at turn N)
                                     high = anchoring predicts acceptance
                                     (grounding is working)

frustration_after_miss   float 0+    P(frustration at N+1 | low anchor at N)
                                     high = missed anchoring predicts frustration
                                     (grounding failure is detectable)
```

**Why this works**: profile-retrieval has no mechanism connecting
"quality of turn N" to "operator response at turn N+1" because it
doesn't model the sequential grounding process. These conditional
probabilities are structurally undefined for stateless systems.

### Failure Mode Detectors (Class F)

These require code-level instrumentation, not just scoring:

**FM1 — Fact Extraction**: monitor `_persist_session_digest()`. If the
digest ever stores individual facts rather than thread summaries,
flag it. Currently stores `thread` (list of turn summaries) and
`topic_words` (frequency-extracted) — both are conversation-level,
not fact-level. Score: 0 if thread-based, 1 if fact-based.

**FM2 — Trigger Gating**: monitor `process_utterance()`. If any code
path checks for trigger phrases before deciding whether to use the
conversation thread, flag it. Currently the thread is always injected
(when `stable_frame` flag is on). Score: 0 if always-on, 1 if gated.

**FM3 — Retrieval Query**: monitor `_load_recent_memory()`. Currently
uses timestamp-ordered scroll (recency), not semantic search. If it
ever switches to relevance-ranked retrieval, flag it. Score: 0 if
recency-ordered, 1 if relevance-ranked.

**FM4 — Memory Separation**: architectural check. If any new agent or
subsystem starts operating on memory independently of the conversation
pipeline (extracting, organizing, re-indexing user facts), flag it.
Score: 0 if memory lives inside conversation flow, 1 if external.

**FM5 — Retrieval Metric**: monitor evaluation code. If
`experiment_runner.py` or `eval_grounding.py` ever adds "did we
retrieve the right fact?" as a primary metric, flag it. Score: 0
if grounding-based metrics primary, 1 if retrieval-based.

## Dashboard Layout

### Langfuse Custom Dashboard: "Grounding vs Retrieval"

**Row 1: Grounding Health (Class G)**
- `context_anchor_success` trend over time (line chart)
- `acceptance_type` distribution per session (stacked bar)
- `frustration_rolling_avg` trend (line chart, inverted — down is good)

**Row 2: Retrieval Parity (Class R)**
- `reference_accuracy` trend (should stay high)
- `sentinel_retrieval` per-probe results (when available)
- `grounding_depth` per session (scatter — earlier is better)

**Row 3: Structural Differentiators**
- `anchor_trajectory` per session (histogram — should be positive)
- `acceptance_after_anchor` conditional probability (should be high)
- `frustration_after_miss` conditional probability (should be high —
  meaning our frustration detector catches grounding failures)

**Row 4: Failure Mode Watchdog (Class F)**
- All five FM scores as boolean indicators
- Any nonzero value = red alert

## The Comparison Logic

Without building a profile-retrieval system, we can compare by arguing:

1. **Class G metrics are structurally zero for profile-retrieval.**
   Any positive score from our system is capability they lack.
   We report these as "grounding-exclusive capability."

2. **Class R metrics are the industry's home turf.**
   We report these as "parity" — we should match or exceed. If we
   score lower, we name the cost explicitly and decide whether the
   Class G gains justify it.

3. **Trajectory metrics are the smoking gun.**
   Profile-retrieval produces flat trajectories (each turn is
   independent). Context anchoring produces improving trajectories
   (each turn builds on the last). The slope IS the comparison.

4. **Failure mode detectors are our integrity check.**
   If FM scores go nonzero, we're drifting toward the thing we're
   arguing against. The comparison becomes moot if we ARE the
   counter-position.

## Implementation Priority

1. **Trajectory scores** — add to `eval_grounding.py` as session-level
   scores. Linear regression on per-turn `context_anchor_success` and
   `frustration_score` within each session. Push to Langfuse as
   session-level scores.

2. **Turn-pair coherence** — add to `eval_grounding.py`. Compute
   conditional probabilities from per-turn scores within sessions.

3. **FM detectors** — add as assertions/checks in the relevant code
   paths. Push as boolean scores on session traces. Initially just
   log warnings; promote to Langfuse scores once baseline is stable.

4. **Dashboard** — build in Langfuse after enough data accumulates.
   Need ~20 sessions minimum for trajectory statistics to be meaningful.
