# Phase Transition: Baseline (A) → Intervention (B)

**Date:** 2026-03-19
**Decision by:** Operator + beta session analysis

## Baseline Summary

20 sessions, 115 scored turns, all components OFF. Code frozen throughout
(with one mechanical parameter change: word cutoff 25→35 at session 11,
density-driven word limits landed by alpha at session 17).

Key baseline characteristics:
- Mean context_anchor_success: 0.317 (low, no thread to anchor to)
- Mean acceptance_type: 0.420 (52% IGNORE — neutral/generic responses)
- Mean reference_accuracy: 0.956 (high — factual recall strong)
- Anchor trajectory: -0.241 (grounding declines within sessions)
- Frustration: 0.09 (rare, all mechanical — pipeline, not grounding)

→ Full analysis in `BASELINE-ANALYSIS.md`

## Deferred Research Items — Evaluated

### Tool calls (TOOL-CALLS.md) — Decision: (1a) NOT blocking

Baseline showed no information starvation. Frustration was mechanical
(audio drops, truncation), never "I need data and can't get it."
Tools stay disabled for Phase B. Orthogonal to claims 1-4. Confound
noted for claim 5 (activation-response correlation).

### Barge-in repair (BARGE-IN-REPAIR.md) — Decision: (1a) NOT blocking

Frustration 0.09 across 115 turns. Operator adapted to turn-taking
pattern. System goes deaf during TTS but this is consistent across
baseline and Phase B — not a confound. Improvement deferred to
post-experiment.

### Density-driven word limits (alpha Tier 1) — Already active

Alpha wired `_density_word_limit()` during baseline testing. Reads
`display_density` from visual layer state. Independent of experiment
components — mechanical parameter, not experiment variable. Active
for both baseline (sessions 17-20) and Phase B.

## Pre-Phase-B Actions

### Required

1. **Environment cleanup** — fix health monitor crash, clear stale
   drift alerts, restart langfuse-sync. Removes noise that was
   constant in baseline but shouldn't carry into Phase B.

2. **Flip experiment config** — stable_frame=true only. One variable
   at a time. Claims 2-4 remain OFF.

3. **Restart daemon** — pick up new config + clean environment.

### NOT done (code freeze continues)

- No tool re-enablement
- No barge-in repair
- No new features
- No parameter tuning beyond what alpha already landed

## Phase B Protocol

**Experiment config:**
```json
{
  "name": "continuity-v1",
  "condition": "B",
  "phase": "intervention",
  "components": {
    "stable_frame": true,
    "message_drop": false,
    "cross_session": false,
    "sentinel": false
  }
}
```

**What changes:** The conversation thread (`_conversation_thread`) is
injected into the system prompt via `_update_system_context()` at
line 388 of `conversation_pipeline.py`:
```python
if self._conversation_thread and self._experiment_flags.get("stable_frame", True):
    thread_text = "\n".join(f"- {entry}" for entry in self._conversation_thread)
    updated += f"\n\n## Conversation So Far\n{thread_text}"
```

**What stays the same:** Everything else. Same model (Opus), same
token limits, same word cutoff, same tools disabled, same scoring,
same Langfuse instrumentation.

**Collection target:** 20 sessions (matching baseline count), or
until sequential stopping rule fires (BF > 10).

**Sequential stopping:** Run `experiment_runner.py` after every 5
sessions. If BF > 10 for claim 1, stop collection — decisive evidence.
If BF > 10 against (< 0.1), also stop — decisive null.

**Success criteria (from pre-registration):**
- Primary: context_anchor_success increases by ≥0.15 over baseline
  (baseline mean: 0.317, target: ≥0.467)
- Secondary: acceptance rate increases (baseline: 23% ACCEPT)
- Trajectory: anchor trajectory becomes positive (baseline: -0.241)

## Why Claim 1 First

The conversation thread is the foundational mechanism. Everything else
builds on it:
- Claim 2 (message drop) tests a compression strategy FOR the thread
- Claim 3 (cross-session) tests thread persistence across sessions
- Claim 4 (sentinel) tests fact survival within the thread
- Claim 5 (salience correlation) tests activation's relationship to
  thread-grounded responses

If the thread doesn't improve grounding, the other claims are moot.

## Phase A' (Reversal) — After Phase B

Flip stable_frame back to false. Collect 10 sessions. If grounding
returns to baseline levels, the effect is attributable to the thread
and not to practice effects, operator adaptation, or environmental
changes.
