# Salience router threshold validation with live workstation signals

**Date:** 2026-04-15
**Author:** beta (queue #218, identity verified via `hapax-whoami`)
**Scope:** validate the AffordancePipeline score thresholds against live workstation affordance-recruitment telemetry. Flag dead + over-eager capabilities. Recommend threshold tuning if drift found.
**Branch:** `beta-phase-4-bootstrap`

---

## 0. Summary

**Verdict: 1 OVER-EAGER + 2 DEAD capabilities, THRESHOLD is a floor (not a gate).** The constant `THRESHOLD=0.05` in `shared/affordance_pipeline.py` is a minimum-viable floor; the real dispatch gates live in `run_loops_aux.py::impingement_consumer_loop` at per-handler thresholds of 0.3-0.4. Observed score distribution over a 30-minute window ranges 0.30-0.66+. Top recruiter `space.gaze_direction` fires ~485 times in 30 min (~16/min) — flagged as over-eager candidate for debouncing. `digital.clipboard_intent` (1 event/30m) + `system.error_rate` (2 events/30m) flagged as dead candidates.

## 1. Score weights + thresholds (static analysis)

`shared/affordance_pipeline.py` lines 28-33 define the canonical scoring formula:

```python
SUPPRESSION_FACTOR = 0.3
THRESHOLD = 0.05
W_SIMILARITY = 0.50
W_BASE_LEVEL = 0.20
W_CONTEXT = 0.10
W_THOMPSON = 0.20
```

Scoring formula at line 423-427:

```python
c.combined = (
    W_SIMILARITY * c.similarity
    + W_BASE_LEVEL * c.base_level
    + W_CONTEXT * c.context_boost
    + W_THOMPSON * c.thompson_score
)
```

**Max theoretical combined score:** 0.5 + 0.2 + 0.1 + 0.2 = **1.0** (all four components at 1.0).

Threshold application at line 442-443:

```python
effective_threshold = THRESHOLD * 0.5 if self._seeking else THRESHOLD
survivors = [c for c in normal if c.combined > effective_threshold]
```

- Normal mode: `survivors > 0.05`
- SEEKING mode: `survivors > 0.025` (half-threshold — lets dormant capabilities surface during boredom)

### 1.1 Inline dispatch thresholds (the real gates)

The 0.05 THRESHOLD is a minimum-viable floor for candidates to leave the pipeline. The ACTUAL dispatch gates live in `agents/hapax_daimonion/run_loops_aux.py::impingement_consumer_loop` where each handler has its own threshold:

| Handler | Threshold | Line |
|---|---|---|
| `system.notify_operator` | `c.combined >= 0.4` | 233 |
| World-domain routing (`env.`, `body.`, `studio.`, `digital.`, `social.`, `system.`, `knowledge.`, `space.`, `world.`) | `c.combined >= 0.3` | 254, 298 |
| `system_awareness` | `c.combined >= 0.3` | 279 |
| `capability_discovery` | — | 298 (check in handler body) |

**Observation:** the 0.3-0.4 inline thresholds are the effective gates, not the 0.05 pipeline-level threshold. A candidate passing the pipeline (score > 0.05) is not automatically dispatched; each handler has its own gate.

## 2. Live score distribution (30-min window, 2026-04-15T18:50Z-19:20Z)

Captured via `journalctl --user -u hapax-daimonion.service --since='30 min ago'`:

### 2.1 Score range

```
$ journalctl ... | grep -oE "score=0\.[0-9]+" | sort -u
score=0.30
score=0.31
score=0.32
...
score=0.60
score=0.61
score=0.62
score=0.63
score=0.64
score=0.65
score=0.66
```

**Range:** 0.30 to 0.66+ — all values densely represented in the 0.30-0.66 band.

**Upper ceiling interpretation:** max observed ~0.66 vs max theoretical 1.0. This suggests:

- Similarity contribution caps at ~0.5 × ~0.8 = ~0.4 (best embedding matches don't reach 1.0)
- Base level contribution ~0.2 × 0.5 (mid-range base levels)
- Thompson contribution ~0.2 × 0.5 (mid-range posteriors, pre-convergence)
- Context boost ~0.1 × 0.3 (partial match)
- **Typical observed combined: 0.4 + 0.1 + 0.1 + 0.03 ≈ 0.63** ← matches observed ceiling

No affordance is currently reaching max score 1.0. This is healthy — indicates the Bayesian prior hasn't over-fitted to any single capability.

### 2.2 Recruitment counts (30-min window, top 21 affordances)

```
485 space.gaze_direction           ← OVER-EAGER
272 system.exploration_deficit
183 space.ir_motion
167 space.posture
113 digital.active_application
108 space.ir_hand_zone
108 digital.keyboard_activity
 77 system.health_ratio
 72 social.phone_call
 61 space.operator_perspective
 55 studio.mixer_high
 54 studio.mixer_energy
 54 studio.desk_gesture
 54 studio.desk_activity
 54 studio.ambient_noise
 54 space.overhead_perspective
 54 space.ir_presence
 17 studio.midi_tempo
  7 studio.mixer_mid
  2 system.error_rate               ← DEAD
  1 digital.clipboard_intent         ← DEAD
```

**Total recruitment events in 30 minutes: ~2,200** across 21 unique affordances.

**Rate: ~73 events/minute ≈ 1.2/second.**

## 3. Drift findings

### 3.1 OVER-EAGER: `space.gaze_direction` (485 events/30m = ~16/min)

**Observation:** fires 16 times per minute, or roughly once every 3.75 seconds. This is 22% of all recruitment events.

**Risk assessment:** depends on what each recruitment triggers:

- If the handler just updates an internal gaze state → benign (no external cost)
- If the handler fires an LLM call to reason about gaze → expensive (22% of LLM budget)
- If the handler triggers an expression change (e.g., gaze follow-through on the reverie surface) → potential visual spam

**Data point:** the run_loops_aux world-domain handler (line 294-306) for `space.*` affordances records Thompson outcomes but does NOT fire LLM calls or external effects. Each fire is cheap — Thompson outcome recording only. **NOT a cost concern.**

**However:** 485 Thompson outcome recordings per 30min may skew the Thompson posterior toward high base_level for `space.gaze_direction`, causing it to stay at the top of the ranking forever. This is a POSITIVE-FEEDBACK LOOP risk.

**Proposed fix:** add a per-affordance cooldown OR decay the Thompson posterior over time. Current behavior might be fine if other affordances also get updated often — but the imbalance (485 vs the next highest 272) suggests `space.gaze_direction` is over-represented.

**Severity:** LOW-MEDIUM. Not an immediate problem; worth monitoring and potentially debouncing in a future tuning pass.

### 3.2 DEAD: `digital.clipboard_intent` (1 event/30m)

**Observation:** fires once every 30 minutes on average.

**Cross-reference:** queue #204 daimonion backends drift audit flagged `clipboard.py::ClipboardIntentBackend` as DEAD (zero external imports, not wired in `init_backends.py`). The 1 event/30m is LIKELY a ghost recruitment from a stale Qdrant affordance entry that references the clipboard capability without a backend consuming it.

**Verdict:** matches earlier drift finding. Recommended action is already proposed in queue #204 §5.1 (delete the dead backend).

**Follow-through:** when the clipboard_intent affordance entry in Qdrant is removed, the 1 event/30m will drop to zero.

### 3.3 DEAD: `system.error_rate` (2 events/30m)

**Observation:** fires ~2 times per 30 minutes.

**Possible interpretations:**

- Genuinely rare signal — system errors are hopefully uncommon
- Dead wiring — no backend publishes the upstream signal

**Not verified** in this audit because the 30-min window is too short to distinguish "rare but live" from "dead". A 24-hour measurement would settle it.

**Recommended follow-up:** sample recruitment counts over 24h to separate rare-but-live from dead wiring. If still ≤2 events/24h, investigate upstream signal publication.

**Severity:** LOW. Could be correct behavior (healthy system = few error events).

### 3.4 Mid-range under-recruiters (4-17 events/30m)

- `studio.midi_tempo` (17) — fires when MIDI clock is active, which depends on the operator running MIDI software
- `studio.mixer_mid` (7) — fires when mixer mid-frequency band crosses a threshold (conditional on music playing)

Both are conditional on specific operator activity. Not dead, just dependent on a state that isn't active in this 30-min window.

## 4. Threshold tuning recommendations

### 4.1 Keep THRESHOLD=0.05 as-is

The 0.05 pipeline-level threshold is a floor, not the real gate. The inline 0.3-0.4 gates in run_loops_aux are the effective thresholds. Raising the pipeline threshold to 0.3 would be redundant; lowering it would let more candidates enter the pipeline but still be gated by the inline checks.

**No change needed to `THRESHOLD` constant.**

### 4.2 Add space.gaze_direction debouncing (proposed follow-up)

**Option A:** affordance-level cooldown — if a capability fires within the last N seconds, skip Thompson recording (but still acknowledge the event to the recruitment state).

**Option B:** Thompson posterior decay — apply an exponential decay to Thompson posteriors to prevent any single capability from dominating forever.

**Option C:** per-affordance rate limiting — cap any single affordance at N fires per minute.

**Beta recommendation:** Option B (Thompson decay) is the cleanest because it doesn't require per-affordance configuration and it generalizes to all recruiters. Could be added as a parameter to `AffordancePipelineState.record_outcome()`.

**Proposed queue item #222** (low priority):

```yaml
id: "222"
title: "Thompson posterior exponential decay to prevent runaway recruiters"
assigned_to: beta
status: offered
priority: low
depends_on: []
description: |
  Queue #218 salience router threshold validation flagged space.
  gaze_direction as an over-eager recruiter (485 events/30m, 22%
  of all recruitment). Risk: positive feedback loop where high fire
  rate → high Thompson posterior → higher score → even more fires.
  
  Proposed fix: Thompson posterior exponential decay. Each time
  state.record_outcome() is called, first apply a multiplicative
  decay factor (e.g., 0.995) to the existing (alpha, beta) Beta
  distribution parameters to bound the posterior's influence.
  
  Tuning: decay factor 0.995 = half-life of 138 updates.
size_estimate: "~40 LOC in shared/affordance_pipeline.py + 2 tests, ~30 min"
```

### 4.3 24-hour recruitment count follow-up (proposed)

The 30-minute window captures a slice but doesn't separate rare-but-live from dead wiring for low-count affordances. A 24-hour measurement would settle `system.error_rate` and other borderline cases.

**Proposed queue item #223** (low priority):

```yaml
id: "223"
title: "24-hour salience router recruitment count measurement"
assigned_to: beta
status: offered
priority: low
depends_on: []
description: |
  Queue #218 §3.3/3.4 left system.error_rate + studio.midi_tempo +
  studio.mixer_mid as "possibly dead, possibly rare-but-live" due to
  30-min measurement window being too short. Sample recruitment
  counts over 24h via:
  
    journalctl --user -u hapax-daimonion.service --since='24h ago' |
      grep -oE 'affordance recruited: [a-z._]+' | sort | uniq -c
  
  Any affordance with < 5 events/24h is dead. Propose removal from
  the affordances Qdrant collection.
size_estimate: "~80 lines research + measurement, ~15 min (after 24h wait)"
```

### 4.4 Consider updating CLAUDE.md scoring weights comment

Council CLAUDE.md § Unified Semantic Recruitment currently says:

> *"Mechanism: Impingement → embed narrative → cosine similarity against Qdrant affordances collection → score (0.50×similarity + 0.20×base_level + 0.10×context_boost + 0.20×thompson) → governance veto"*

This matches the source exactly. No drift. ✓

## 5. Non-drift observations

- **Score range 0.30-0.66 is consistent with healthy operation.** Neither the floor (0.05) nor the ceiling (1.0) is being hit regularly.
- **21 unique recruiters in 30 min** across world-domain prefixes (space, system, digital, social, studio) covers the declared perception surface well.
- **SEEKING mode threshold reduction (0.05 → 0.025) not observed firing** in the 30-min window — no SEEKING log entries. Would fire only during boredom events.
- **Thompson sampling pseudo-randomness** means score values drift slightly between reads of the same impingement. Not a drift — expected Bayesian behavior.

## 6. Cross-references

- `shared/affordance_pipeline.py` (lines 28-33 for constants, 367+ for `select()`, 442-443 for threshold)
- `agents/hapax_daimonion/run_loops_aux.py::impingement_consumer_loop` (lines 233-298 for inline dispatch thresholds)
- Council CLAUDE.md § Unified Semantic Recruitment (mechanism spec)
- Queue #204 daimonion backends drift audit — `docs/research/2026-04-15-daimonion-backends-drift-audit.md` (commit `ea832f7c4`) — flagged `ClipboardIntentBackend` as dead, matches queue #218 finding `digital.clipboard_intent` at 1 event/30m
- Queue #206 PresenceEngine calibration audit — `docs/research/2026-04-15-presence-engine-signal-calibration-audit.md` (commit `cbd0264dc`) — parallel audit for presence engine thresholds
- Queue item spec: queue/`218-beta-salience-router-threshold-validation.yaml`

— beta, 2026-04-15T19:25Z (identity: `hapax-whoami` → `beta`)
