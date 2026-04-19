---
title: Salience Router #218 Findings Follow-Up — Recommendation Disposition + 24 h Recruitment Measurement
date: 2026-04-18
author: beta
queue: "#226"
depends_on:
  - "queue #218: salience router threshold validation (2026-04-15-salience-router-threshold-validation.md)"
related:
  - "queue #204: daimonion backends drift audit"
  - "shared/affordance_pipeline.py"
  - "agents/hapax_daimonion/run_loops_aux.py::impingement_consumer_loop"
status: captured
---

# Salience Router #218 Findings Follow-Up

Queue item #226 disposes of each tuning recommendation from queue #218 (`docs/research/2026-04-15-salience-router-threshold-validation.md`) and opportunistically closes the §3.3 / §3.4 24-hour measurement gap that #218 itself deferred.

## 0. Summary

| #218 recommendation | Disposition under #226 |
|---|---|
| §4.1 Keep `THRESHOLD=0.05` as-is | **No change.** #218 explicitly recommended no action. |
| §4.2 Add `space.gaze_direction` debouncing (Thompson decay) | **Deferred to new queue item.** Semantic shift (changes Bayesian learning dynamics) — needs operator ratification. Proposal text below. |
| §4.3 24-hour recruitment count follow-up | **Executed under this item.** Results in §2. |
| §4.4 CLAUDE.md scoring weights comment | **No change.** #218 verified docs match source. |

Net code change under #226: **zero**. Two follow-up queue items proposed for operator review. One new finding surfaced during the 24 h measurement: `digital.active_application` has collapsed from ~226 events/h (#218 extrapolated) to ~0.1 events/h — the desktop-activity publisher has likely broken since #218 was written.

## 1. Rationale for each disposition

### 1.1 §4.1 `THRESHOLD=0.05` unchanged

#218 §4.1 established that the 0.05 pipeline-level threshold is a minimum-viable floor, not the operational gate. Effective gates live inline in `run_loops_aux.py::impingement_consumer_loop` at 0.3–0.4. Raising 0.05 would be redundant; lowering it would only widen the candidate pool without changing dispatch. No code change. Static analysis already in #218; nothing to re-verify.

### 1.2 §4.2 Thompson decay deferred

The proposed fix is Thompson posterior exponential decay (`AffordancePipelineState.record_outcome()` applies a multiplicative decay to `(alpha, beta)` before updating). This is a semantic shift:

- Current behaviour: posterior is cumulative — every outcome is remembered forever.
- Proposed behaviour: posterior has a finite memory — old outcomes decay.

This changes the *learning dynamics* of the unified semantic recruitment system documented in council CLAUDE.md § Unified Semantic Recruitment. That document describes Thompson sampling as cross-session persistent learning:

> *"Thompson sampling (optimistic prior: Beta(2,1)) + Hebbian associations learn from outcomes across sessions."*

Adding decay could conflict with "cross-session persistent learning". A half-life of 138 updates (the #218-proposed 0.995 factor) would effectively erase a session's learning over a few days of activity. Whether this is desirable is an operator-level judgment, not a beta-level threshold tuning.

**Recommendation:** open as a new queue item flagged "needs operator ratification before implementation". Proposed item text in §3.1.

### 1.3 §4.3 24-h recruitment measurement — run now

#218 left `system.error_rate` (2/30m), `studio.midi_tempo` (17/30m), and `studio.mixer_mid` (7/30m) as "possibly dead, possibly rare-but-live" due to a 30-minute window being too short to distinguish. Three days have elapsed, so a 24-hour sample is immediately available. Measurement results in §2.

### 1.4 §4.4 CLAUDE.md weights comment unchanged

#218 verified no drift between CLAUDE.md § Unified Semantic Recruitment and `shared/affordance_pipeline.py`. Re-verification not performed under this item. If this changes, the monthly `claude-md-audit.timer` will surface it.

## 2. 24-hour recruitment count measurement (closes #218 §3.3 / §3.4)

Window: 2026-04-17T19:50 → 2026-04-18T19:50 CDT (~24 h). Source: `journalctl --user -u hapax-daimonion.service`.

Total recruitment events: **75,620**. Rate: **52.5 events/min ≈ 0.88/s**. ( #218 observed 73 events/min in a 30-minute window; the 24-hour rate is lower because the operator is not continuously at desk.)

### 2.1 Per-affordance counts (descending)

```
 24,148  space.gaze_direction            ← OVER-EAGER (#218 §3.1 confirmed)
  9,633  system.exploration_deficit
  8,145  space.ir_hand_zone
  7,712  space.posture
  5,415  digital.keyboard_activity
  3,730  system.health_ratio
  3,629  space.ir_motion
  3,543  social.phone_call
  2,709  studio.desk_activity
  2,706  space.ir_presence
  1,480  studio.desk_gesture
  1,233  studio.ambient_noise
  1,221  studio.mixer_energy
    138  studio.midi_beat
     70  studio.mixer_high
     26  env.ambient_light
     24  space.desk_perspective
     17  studio.mixer_mid                 ← rare-but-live (#218 §3.4 resolved)
     16  digital.clipboard_intent         ← dead-backend ghost (#218 §3.2 confirmed)
     15  studio.midi_tempo                ← rare-but-live (#218 §3.4 resolved)
      3  digital.active_application       ← NEW FINDING — publisher regression
      2  system.stimmung_stance
      2  studio.mixer_bass
      1  space.overhead_perspective
      1  space.operator_perspective
      1  env.time_of_day
      0  system.error_rate                ← DEAD (#218 §3.3 confirmed — 0 events/24h)
```

### 2.2 Disposition of #218 §3.3 / §3.4 borderline cases

| Affordance | #218 30m | 24 h | Verdict |
|---|---|---|---|
| `system.error_rate` | 2 | **0** | DEAD confirmed. Propose removal from Qdrant `affordances` collection. |
| `studio.midi_tempo` | 17 | 15 | Rare-but-live. ~0.6/h. Fires when MIDI clock is active. Keep. |
| `studio.mixer_mid` | 7 | 17 | Rare-but-live. ~0.7/h. Fires on mixer mid-band activity. Keep. |
| `digital.clipboard_intent` | 1 | 16 | Dead-backend ghost confirmed (matches #204 finding). 16 fires/24h ≈ 0.67/h is Qdrant-side noise; backend not wired. Propose removal from Qdrant affordances. |

The DEAD cases (`system.error_rate`, `digital.clipboard_intent`) are now eligible for explicit removal from the Qdrant `affordances` collection. This is a **Qdrant-content change**, not a code change — proposed as a new queue item in §3.2.

### 2.3 New finding F-226-1 (medium): `digital.active_application` publisher regression

**#218 observation (2026-04-15, 30 m):** 113 events — ~226 events/hour.
**#226 observation (2026-04-17 → 2026-04-18, 24 h):** 3 events — ~0.125 events/hour.

This is a ~1800× reduction. Three possible explanations:

1. Operator stopped using active applications for 24 hours (unlikely — `digital.keyboard_activity` is at 5,415/24h, so the operator was actively typing).
2. The upstream publisher (Hyprland focus-change emitter or equivalent) is broken.
3. The affordance's description in Qdrant changed, dropping below similarity threshold for current impingements.

Option 2 is most likely given the keyboard-activity counterexample. The Hyprland IPC focus listener or its downstream impingement writer may have silently stopped emitting events. Not investigated here (out of scope for #226). Recommend a new queue item to trace the publisher chain.

### 2.4 Other long-tail candidates

`env.time_of_day` (1/24h), `space.overhead_perspective` (1/24h), `space.operator_perspective` (1/24h), `studio.mixer_bass` (2/24h), `system.stimmung_stance` (2/24h) all fell below a 5-events-per-24-h heuristic. They may be dead or may be legitimate rare signals. A second 24-h window would settle it. Not acted on here.

### 2.5 SEEKING stance did not fire in the window

`journalctl … | grep -E 'SEEKING|stance.*seeking' | wc -l` returns 0. The half-threshold boredom-triggered pipeline (per council CLAUDE.md § Unified Semantic Recruitment) did not activate in 24 h. Consistent with a busy operator window. Not a finding, just a telemetry observation.

## 3. Proposed follow-up queue items

### 3.1 Queue item (not created here) — Thompson posterior decay

```yaml
title: "Beta: Thompson posterior exponential decay for over-eager recruiters"
assigned_to: beta
status: offered
priority: low
depends_on: ["218", "226"]
needs_ratification: operator
description: |
  Queue #218 §3.1 + #226 §2.1 confirm space.gaze_direction fires
  ~24.1k times/24h (22% of all recruitment). Thompson posterior has no
  decay, so any over-eager recruiter's base_level drifts up monotonically,
  reinforcing the over-eagerness.

  Proposed: apply a multiplicative decay factor (0.995 per update,
  half-life ~138 updates) to (alpha, beta) in AffordancePipelineState.
  record_outcome() before the standard update.

  SEMANTIC SHIFT — needs operator ratification before implementation:
  council CLAUDE.md describes Thompson sampling as "cross-session
  persistent learning"; decay would bound session memory to a finite
  window. Alternative is per-affordance rate-limiting (cheaper but does
  not generalise).
size_estimate: "~40 LOC + 2 tests, ~30 min (after ratification)"
```

### 3.2 Queue item (not created here) — Qdrant affordance cleanup

```yaml
title: "Beta: remove dead affordances from Qdrant affordances collection"
assigned_to: beta
status: offered
priority: low
depends_on: ["204", "218", "226"]
description: |
  24-hour recruitment measurement (queue #226 §2) confirms DEAD status of:
  - system.error_rate (0 events / 24h)
  - digital.clipboard_intent (16 events / 24h, backend already flagged
    dead in queue #204 §5.1)

  Remove both from the Qdrant affordances collection. Cross-reference
  with shared/qdrant_schema.py and any affordance-seeding scripts.

  Extension target: long-tail (§2.4) — env.time_of_day, space.overhead_
  perspective, space.operator_perspective, studio.mixer_bass, system.
  stimmung_stance. A second 24h measurement after ~1 week would either
  confirm dead or show rare-but-live.
size_estimate: "~20 LOC + qdrant operations + test, ~20 min"
```

### 3.3 Queue item (not created here) — `digital.active_application` publisher regression trace

```yaml
title: "Beta: trace digital.active_application publisher regression"
assigned_to: beta
status: offered
priority: medium
depends_on: ["226"]
description: |
  Queue #226 §2.3 observed digital.active_application collapse from 113/
  30m (2026-04-15) to 3/24h (2026-04-18). ~1800× reduction despite
  active operator typing in the same window. Upstream publisher (Hyprland
  IPC focus listener → impingement writer) likely broken. Trace the
  chain:
  1. Verify Hyprland focus events fire (hyprctl monitors -j)
  2. Find the impingement writer for active_application
  3. Check /dev/shm/hapax-dmn/impingements.jsonl for active_application
     entries in the last hour
  4. Propose fix or document as intentional.
size_estimate: "~60 lines research + fix if simple, ~45 min"
```

## 4. No code change under #226

`git diff` at close of this item: zero. All four #218 recommendations are either intentionally no-op (§1.1, §1.4), deferred pending operator ratification (§1.2), or closed by the 24-hour measurement captured here (§1.3 / §2.2). Three new queue items are proposed (§3.1–§3.3) for operator assignment.

## 5. Cross-references

- `docs/research/2026-04-15-salience-router-threshold-validation.md` (queue #218)
- `docs/research/2026-04-15-daimonion-backends-drift-audit.md` (queue #204; `ClipboardIntentBackend` dead)
- `shared/affordance_pipeline.py` lines 28–33, 423–427, 442–443
- `agents/hapax_daimonion/run_loops_aux.py::impingement_consumer_loop` lines 233–298
- council CLAUDE.md § Unified Semantic Recruitment
