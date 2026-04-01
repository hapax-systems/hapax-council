# SCM Control Law Specifications: All 14 S1 Components

**Date:** 2026-03-31
**Status:** Design specification — ready for implementation
**Depends on:** [SCM Spec](stigmergic-cognitive-mesh.md), [Concrete Formalizations](2026-03-31-scm-concrete-formalizations.md), [ControlSignal Extension Plan](../superpowers/plans/2026-03-31-scm-control-signal-extension.md)

---

## Abstract

This document specifies concrete control laws for all 14 S1 components of the stigmergic cognitive mesh. Each control law follows the PCT (Powers, 1973) template: controlled variable, reference signal, error signal, corrective action, and recovery condition. The specification draws on four frameworks (PCT, MAPE-K, Kubernetes reconciliation, chaos engineering steady-state hypothesis) to produce implementable, safe control laws with hysteresis to prevent oscillation.

---

## 1. Framework Synthesis

### 1.1 Applicable Frameworks

Four frameworks inform the control law design. None provides a complete template alone; the specification below synthesizes elements from each.

**Perceptual Control Theory (Powers, 1973).** The foundational model. Each component controls a *perception*, not an output. The control law compares a reference signal (desired perception) to the actual perception, computes error, and adjusts output to reduce error. PCT provides the structural template but does not address software-specific concerns (cascading failures, resource exhaustion, service dependencies).

PCT has been applied to robotics, organizational behavior, and psychology, but not to distributed software systems operating as cognitive infrastructure. The SCM application is novel: each process controls a perceptual variable *about its own functioning*, not about an external physical variable. The closest precedent is Contracts-Based Control Integration into Software Systems (Springer, 2019), which applies control-theoretic contracts to software components but uses classical control (PID), not perceptual control.

**IBM MAPE-K (Kephart & Chess, 2003).** Autonomic computing reference model: Monitor-Analyze-Plan-Execute over shared Knowledge. MAPE-K provides the *adaptation loop structure*: monitor a managed element, analyze symptoms, plan corrective actions, execute adaptations. The SCM already has the Monitor phase (ControlSignal publishing) and the Knowledge base (/dev/shm traces). What is missing is the Analyze-Plan-Execute cycle within each component — reading its own error signal and acting on it.

MAPE-K's key contribution to our design: **the separation of monitoring from action**. A component should not react to a single error reading. It should accumulate evidence (Analyze), determine whether the situation warrants intervention (Plan), and only then act (Execute). This maps directly to hysteresis counters.

**Kubernetes Reconciliation Loop.** The pattern: declare desired state, observe actual state, compute delta, take minimal action to converge, repeat forever. Kubernetes adds two critical ideas absent from PCT:

1. **Graceful degradation.** When the desired state cannot be achieved, operate in the best achievable state rather than oscillating between attempts and failures.
2. **Convergence over correctness.** The system does not need to reach the exact desired state on every cycle — it needs to *converge toward* it. Small deltas are acceptable; large sustained deltas trigger action.

**Chaos Engineering Steady-State Hypothesis (Rosenthal et al., 2017).** Define steady state as a measurable output indicating normal behavior. Hypothesize that steady state will continue under perturbation. If the hypothesis is disproved, improve resilience. The key contribution: **every control law needs a falsifiable steady-state definition** — not just "is the component healthy?" but "what specific measurable property must hold?"

### 1.2 Unified Control Law Template

Every control law below follows this structure:

```
COMPONENT: {name}
CONTROLLED VARIABLE: What the component perceives about its own functioning
REFERENCE SIGNAL: The desired value of that perception (steady-state hypothesis)
ERROR SIGNAL: |reference - perception|
ERROR THRESHOLD: The error magnitude that triggers corrective action
HYSTERESIS:
  - Degrade after N consecutive ticks with error > threshold
  - Recover after M consecutive ticks with error < threshold
  - N < M (degrade fast, recover slow — asymmetric for stability)
CORRECTIVE ACTIONS:
  - Level 1: Mild intervention (adjust parameters within normal operating range)
  - Level 2: Moderate intervention (reduce capability to preserve core function)
  - Level 3: Severe intervention (shed load, enter minimal mode)
ESCALATION: What happens if Level 3 does not resolve the error
SAFETY CONSTRAINTS: What the control law must NOT do (cascade prevention)
```

### 1.3 Design Principles

1. **Degrade fast, recover slow.** Asymmetric hysteresis prevents oscillation. Degradation requires fewer consecutive error ticks than recovery requires consecutive ok ticks. Ratio: 3:5 for most components.

2. **No cascading failures.** A control law must never cause a downstream component to fail. Corrective actions are always *reductions* (slower cadence, fewer features, simpler processing), never *increases* that could overwhelm dependent systems.

3. **Monotonic degradation levels.** Each component has at most 3 degradation levels (nominal → degraded → minimal). Transitions are monotonic within a hysteresis window — no jumping from nominal to minimal or minimal to nominal without passing through degraded.

4. **Stimmung alignment.** Component-level control laws operate independently of stimmung modulation. They are *additive*: if stimmung says "slow down" and the component's own control law says "slow down," the effects compound. This is intentional — stimmung is a system-wide coordination signal; component control laws are local self-regulation.

5. **Observable.** Every control law action is logged and reflected in the component's health.json. External observers (health monitor, Langfuse, API) can see what action each component has taken and why.

---

## 2. Control Law Specifications

### 2.1 IR Perception

```
COMPONENT: ir_perception
CONTROLLED VARIABLE: Freshness ratio — fraction of Pi fleet reporting within staleness window
REFERENCE SIGNAL: 1.0 (all 3 Pis reporting fresh data every ≤10s)
ERROR SIGNAL: 1.0 - (fresh_pis / expected_pis)
ERROR THRESHOLD: 0.34 (i.e., fewer than 2 of 3 Pis reporting)
```

**Hysteresis:** Degrade after 3 consecutive ticks (~9s) with <2 Pis. Recover after 5 consecutive ticks with >=2 Pis.

**Corrective Actions:**

| Level | Condition | Action |
|-------|-----------|--------|
| 1 — Partial coverage | 2/3 Pis reporting | Widen staleness window from 10s to 15s for missing Pi. Log which Pi is missing. Continue fusion with available data. Weight available Pis higher for signals normally sourced from missing role. |
| 2 — Single source | 1/3 Pis reporting | Disable role-based priority (cannot prefer desk for gaze if desk is offline). Report all gaze/posture signals as `"unknown"` rather than using single-Pi data for face-dependent signals. Reduce ir_person_detected confidence by 0.3 (single camera cannot triangulate). |
| 3 — No sources | 0/3 Pis reporting | Set all 14 IR signals to defaults (person_detected=False, all numeric=0.0, all string="unknown"). Publish perception=0.0 to health. Do NOT fabricate phantom presence data. |

**Escalation:** If Level 3 persists for >60s, emit an impingement (type=INFRASTRUCTURE, strength=0.5, content="IR fleet offline") to alert DMN. The impingement surfaces in stimmung via perception_confidence dimension.

**Safety Constraints:**
- Never generate positive presence signals when no Pi data is available.
- Never retry HTTP connections to Pis (IR perception is a passive reader of state files written by the API; the Pis push to the API independently).
- Level 2/3 actions must be idempotent — calling them repeatedly must not accumulate side effects.

---

### 2.2 Contact Mic

```
COMPONENT: contact_mic
CONTROLLED VARIABLE: Audio stream health — whether the capture buffer contains valid PCM data
REFERENCE SIGNAL: 1.0 (buffer has data, RMS is computable, no clipping)
ERROR SIGNAL: Quality score derived from three conditions:
  - buffer_empty: perception = 0.0
  - clipping (>5% of samples at ±32767): perception = 0.5
  - noise_floor_high (RMS > 0.8 sustained): perception = 0.5
  - normal: perception = 1.0
ERROR THRESHOLD: perception < 0.75
```

**Hysteresis:** Degrade after 5 consecutive frames (~160ms) with error. Recover after 10 consecutive frames (~320ms) with no error. Audio is continuous and high-frequency, so hysteresis counts are in frames, not ticks.

**Corrective Actions:**

| Level | Condition | Action |
|-------|-----------|--------|
| 1 — Quality degradation | Clipping or high noise floor | Increase onset threshold by 1.5x (reduce false onset detection). Log quality metrics. Continue all DSP but mark outputs as low-confidence by setting a `quality_confidence` field in contributed signals. |
| 2 — Buffer starvation | Empty buffer for >500ms | Stop publishing onset/gesture signals (they would be fabricated). Continue publishing RMS=0.0 and activity="idle". Attempt to reopen PipeWire stream once (single retry, not a loop). |
| 3 — Device loss | Buffer empty for >5s after retry | Set all contact mic signals to defaults (energy=0.0, activity="idle", gesture="none"). Stop the capture thread to prevent CPU waste on a dead device. Set a `device_lost` flag. |

**Escalation:** If Level 3 persists for >60s, emit impingement. Device recovery requires manual intervention (PipeWire restart, cable check) or automatic PipeWire reconnect event. When the daemon receives SIGUSR1, it re-probes the device.

**Safety Constraints:**
- Never generate onset/gesture events from an empty or clipping buffer.
- The single PipeWire reopen attempt in Level 2 must have a 2s timeout — no blocking the perception tick.
- Contact mic is a FAST tier backend. All corrective actions must complete in <5ms to avoid blocking the perception loop.

---

### 2.3 Voice Daemon (Perception Orchestrator)

```
COMPONENT: voice_daemon
CONTROLLED VARIABLE: Backend freshness — fraction of FAST-tier backends with watermark < 30s
REFERENCE SIGNAL: 1.0 (all backends fresh)
ERROR SIGNAL: 1.0 - (fresh_backends / total_backends)
ERROR THRESHOLD: 0.3 (i.e., more than 30% of backends stale)
```

**Hysteresis:** Degrade after 3 consecutive ticks (~4.5s at 1.5s tick). Recover after 5 consecutive ticks.

**Corrective Actions:**

| Level | Condition | Action |
|-------|-----------|--------|
| 1 — Partial staleness | 70-90% backends fresh | Log which backends are stale. Continue normal operation. Increase perception tick logging to DEBUG for stale backends (diagnostic aid). |
| 2 — Significant staleness | 40-70% backends fresh | Reduce governor evaluation frequency to every 2nd tick (conserve CPU for remaining backends). Mark stale backend signals as `"unknown"` in perception state rather than using last-known values. Stop publishing stale signals to /dev/shm — downstream readers should see absence, not stale data. |
| 3 — Severe staleness | <40% backends fresh | Enter degraded perception mode: only IR presence and contact mic (the two hardware backends) are evaluated. All LLM-dependent backends are suspended. Governor switches to simple presence-only logic (process if present, withdraw if absent). Voice pipeline continues independently. |

**Escalation:** If Level 3 persists for >120s, the voice daemon's own health.json error will propagate to stimmung via the health dimension. The voice daemon does NOT self-restart — systemd handles process-level recovery.

**Safety Constraints:**
- Never kill or restart individual backends. Backend lifecycle is managed by the perception engine, not by the control law.
- Level 3 must not disable the voice pipeline (ASR/TTS). Voice interaction must continue even when perception is degraded.
- Control law actions must not modify the perception engine's backend registry — only which backends are *evaluated* on each tick.

---

### 2.4 DMN Pulse

```
COMPONENT: dmn
CONTROLLED VARIABLE: Observation production — whether Ollama inference produces a non-empty observation
REFERENCE SIGNAL: 1.0 (observation produced on every sensory tick)
ERROR SIGNAL: 0.0 if observation produced, 1.0 if Ollama failed or circuit breaker open
ERROR THRESHOLD: 0.5 (any failure)
```

**Hysteresis:** The circuit breaker already provides hysteresis (5 failures → open, 30s cooldown → half-open probe). The control law layers additional behavioral adaptation on top.

**Corrective Actions:**

| Level | Condition | Action |
|-------|-----------|--------|
| 1 — Transient failure | 1-2 consecutive Ollama failures | Log failure. Continue at normal tick rate. Buffer the raw sensor prompt as the observation (already implemented: `self._buffer.add_observation(prompt[:100], ...)`). |
| 2 — Circuit breaker open | 5+ failures, breaker open | Already implemented: requests are blocked for 30s cooldown. Additional action: **switch to cached-only mode**. DMN continues ticking and reading sensors, but instead of calling Ollama, it generates observations from sensor deltas alone (deterministic string formatting, no LLM). This maintains the observation stream for imagination and apperception. Emit degradation impingement (already implemented). |
| 3 — Sustained outage | Circuit breaker re-opens after half-open probe fails (2+ cycles) | Extend cooldown from 30s to 120s (reduce probe frequency to avoid hammering a struggling Ollama). Continue cached-only observations. Reduce evaluative tick rate by 4x (evaluative ticks are more expensive and less useful without fresh observations). |

**Escalation:** If Level 3 persists for >10 minutes, emit a high-strength impingement (INFRASTRUCTURE, strength=0.8, "Ollama sustained outage"). This will reach stimmung and trigger system-wide degradation. The DMN does NOT attempt to restart Ollama — that is systemd's responsibility.

**Recovery:** When the circuit breaker half-open probe succeeds:
- If in Level 2: immediately resume Ollama inference (breaker closure handles this).
- If in Level 3: restore normal cooldown (30s) but keep evaluative tick rate reduced for 3 more successful ticks (recovery hysteresis).

**Safety Constraints:**
- Never restart Ollama or any external process.
- Cached-only observations must be clearly marked (prefix with `[cached]` or equivalent) so downstream consumers can distinguish them from LLM-generated observations.
- DMN must never stop ticking entirely. Even in Level 3, the sensor read + delta detection loop continues — the observation stream is a dependency for imagination and apperception.

---

### 2.5 Imagination Daemon (EXISTING — Document PoC)

```
COMPONENT: imagination
CONTROLLED VARIABLE: Fragment production — whether a tick produces an ImaginationFragment
REFERENCE SIGNAL: 1.0 (fragment produced when observations and snapshot are fresh)
ERROR SIGNAL: 1.0 if observations or snapshot are stale/missing, 0.0 if tick succeeds
ERROR THRESHOLD: 0.5 (any failure)
```

**Hysteresis:** Degrade after 3 consecutive errors. Recover after 3 consecutive successes. (Symmetric — the existing PoC uses 3:3. Consider changing to 3:5 for consistency with other components.)

**Corrective Actions (IMPLEMENTED):**

| Level | Condition | Action |
|-------|-----------|--------|
| 1 — Stale inputs | Observations or snapshot stale | Skip tick, publish perception=0.0, sleep for current cadence interval. No cadence change. |
| 2 — Sustained staleness | 3+ consecutive errors | Double the base cadence interval (`_base_s *= 2.0`). Log warning. Continue attempting ticks at the slower rate. |
| Stimmung overlay | stance=degraded | Cadence interval *= 2.0 (compounds with Level 2 if active). |
| Stimmung overlay | stance=critical | Cadence interval = 60s (effectively pause). |

**Recovery (IMPLEMENTED):** 3 consecutive successful ticks → restore base cadence (`_base_s /= 2.0`).

**Escalation:** No explicit escalation beyond Level 2 + stimmung overlay. If both the control law doubling and stimmung degraded overlay are active, the effective cadence is 4x normal — sufficient to prevent resource waste.

**Safety Constraints:**
- The cadence doubling is capped: base_s cannot exceed 120s (2 minutes) regardless of how many doublings occur. (NOT YET IMPLEMENTED — should be added.)
- Imagination must never generate fragments from stale observations. The staleness check in `observations_are_fresh()` is the primary safety gate.

**Recommended Changes to PoC:**
1. Change recovery hysteresis from 3 to 5 (asymmetric, consistent with other components).
2. Add a floor on base_s: `max(self._imagination.cadence._base_s, 5.0)` after halving (prevent sub-second cadence from acceleration + recovery interaction).
3. Add a ceiling on base_s: `min(self._imagination.cadence._base_s, 120.0)` after doubling.

---

### 2.6 Content Resolver

```
COMPONENT: content_resolver
CONTROLLED VARIABLE: Resolution success — whether slow content references resolve without error
REFERENCE SIGNAL: 1.0 (resolution succeeds)
ERROR SIGNAL: 0.0 on success, 1.0 on failure
ERROR THRESHOLD: 0.5 (any failure)
```

**Hysteresis:** Per-fragment: 5 failures → skip for 60s (ALREADY IMPLEMENTED). System-level: degrade after 3 consecutive fragment failures across *different* fragments. Recover after 5 consecutive successes.

**Corrective Actions:**

| Level | Condition | Action |
|-------|-----------|--------|
| 1 — Single fragment failure | Resolution fails for one fragment | Retry up to MAX_FAILURES_PER_FRAGMENT (5) times. Log each failure with fragment ID and error type. Continue processing other fragments normally. (ALREADY IMPLEMENTED.) |
| 2 — Repeated failures | 3+ different fragments fail consecutively | **Disable slow content types.** Only resolve `text` references (cheap, local). Skip `qdrant_query` and `url` references (network-dependent, likely the failure source). Log which content types are disabled. Reduce poll interval from 0.5s to 2.0s (conserve resources). |
| 3 — Systemic failure | 5+ consecutive failures across all types including text | Stop attempting resolution. Publish perception=0.0. Enter passthrough mode: new fragments are written to the active slots directory with `resolved: false` flag so the visual pipeline knows to use placeholder content. |

**Escalation:** Level 3 does not escalate further. The content resolver is a non-critical enhancement — imagination and reverie can operate without resolved content (they fall back to procedural visuals). No impingement needed.

**Recovery from Level 2:** 5 consecutive text-only successes → re-enable qdrant_query. 5 more successes → re-enable url. Staged recovery prevents re-enabling a failing content type immediately.

**Safety Constraints:**
- Never retry the same fragment more than MAX_FAILURES_PER_FRAGMENT times. The skip_until mechanism is the circuit breaker.
- Never block the poll loop waiting for a slow resolution. All resolution must be bounded by a timeout (current: inherited from resolve_references_staged).
- Content resolver must never modify imagination fragments — it reads current.json as immutable input and writes resolved content to a separate directory.

---

### 2.7 Stimmung (Meta-Control)

```
COMPONENT: stimmung
CONTROLLED VARIABLE: Dimension freshness — fraction of 10 dimensions with freshness_s < 120s
REFERENCE SIGNAL: 1.0 (all dimensions have fresh readings)
ERROR SIGNAL: 1.0 - (fresh_dimensions / total_dimensions)
ERROR THRESHOLD: 0.3 (i.e., 3+ of 10 dimensions stale)
```

Stimmung is unique: it IS the coordination signal for other components. Its own control law is therefore *meta-control* — it governs the quality of the coordination signal itself.

**Hysteresis:** ALREADY IMPLEMENTED for stance transitions (RECOVERY_THRESHOLD = 3 consecutive nominal readings to recover from degraded). The dimension freshness control law adds a *separate* hysteresis for stimmung's own health: degrade after 2 consecutive snapshots with >3 stale dimensions. Recover after 4 consecutive snapshots with <=3 stale dimensions.

**Corrective Actions:**

| Level | Condition | Action |
|-------|-----------|--------|
| 1 — Partial staleness | 3-5 of 10 dimensions stale | Mark stale dimensions explicitly in the stimmung snapshot (already done via `freshness_s`). Exclude stale dimensions from stance computation (ALREADY IMPLEMENTED — `_STALE_THRESHOLD_S = 120.0`). Emit a `perception_confidence` dimension reading of 0.5 to reflect reduced self-assessment quality. |
| 2 — Majority stale | 6+ of 10 dimensions stale | **Report stance as "degraded" regardless of fresh dimension values.** Rationale: if most dimensions are stale, the system cannot reliably self-assess. A "nominal" stance computed from 4 dimensions is unreliable. Add a `_stale_override` flag to the snapshot so downstream consumers know the stance is forced. |
| 3 — All stale | 10/10 dimensions stale (no fresh data at all) | **Report stance as "critical" with a `no_data` flag.** This is the stimmung equivalent of "I don't know how I'm doing." All downstream consumers that read stimmung will see critical and reduce their activity, which is the correct conservative response when self-assessment is impossible. |

**Escalation:** Level 3 triggers an ntfy notification to the operator ("Stimmung has no fresh data — system self-assessment offline"). This is the only control law that directly notifies the operator, because stimmung failure means all other control laws that depend on stimmung modulation are operating blind.

**Safety Constraints:**
- Stimmung must never stop publishing snapshots. Even in Level 3, it publishes a snapshot with stance=critical and the no_data flag. Silent stimmung failure is worse than noisy stimmung failure — downstream readers would use the last-known stance indefinitely.
- The forced stance in Level 2/3 must NOT affect the hysteresis counter for normal stance transitions. When fresh data returns, the normal stance computation resumes from where it left off.
- Stimmung must never attempt to refresh its own dimensions (it does not control the data sources — health monitor, GPU watchdog, etc. do).

---

### 2.8 Temporal Bands

```
COMPONENT: temporal_bands
CONTROLLED VARIABLE: Ring buffer occupancy — whether the perception ring has current data
REFERENCE SIGNAL: 1.0 (ring.current() returns a non-None snapshot)
ERROR SIGNAL: 0.0 if ring has data, 1.0 if ring is empty
ERROR THRESHOLD: 0.5 (empty ring)
```

**Hysteresis:** Degrade after 5 consecutive format() calls with empty ring (~5s at 1s caller cadence). Recover after 3 calls with non-empty ring (faster recovery because temporal bands are stateless — no warm-up needed).

**Corrective Actions:**

| Level | Condition | Action |
|-------|-----------|--------|
| 1 — Empty ring | ring.current() returns None | Return empty TemporalBands() (ALREADY IMPLEMENTED). Publish perception=0.0. This is a correct response — temporal bands should not fabricate history. |
| 2 — Sustained empty ring | 5+ consecutive empty calls | **Stop computing protention and surprise.** These computations are wasted when there is no perception data to project from. Return a minimal TemporalBands with only a `_ring_empty: true` flag. Log at WARNING level once (not every tick). |
| 3 — N/A | Temporal bands do not have a Level 3. | They are a pure-logic formatter with no state to protect and no resources to conserve beyond CPU. Level 2 already minimizes CPU usage. |

**Escalation:** None needed. An empty perception ring is a symptom of voice daemon or perception engine failure, not a temporal bands failure. The upstream component's control law handles the root cause.

**Safety Constraints:**
- Never generate synthetic retention entries to fill an empty ring. The temporal bands must reflect actual perception history, even if that history is empty.
- Never cache old ring data across calls. Each format() call reads the ring's current state fresh.
- The computational savings from Level 2 (skipping protention/surprise) are modest (~2ms per call) but compound across high-frequency callers.

---

### 2.9 Apperception

```
COMPONENT: apperception
CONTROLLED VARIABLE: Self-model coherence — mean confidence across discovered dimensions
REFERENCE SIGNAL: Dynamic, range [0.15, 0.95] (coherence floor prevents shame spiral, ceiling prevents narcissistic inflation)
ERROR SIGNAL: |target_coherence - actual_coherence| where target is 0.55 (midpoint)
ERROR THRESHOLD: coherence < 0.25 (approaching floor) OR coherence > 0.85 (approaching ceiling)
```

**Hysteresis:** The rumination breaker (ALREADY IMPLEMENTED) provides hysteresis for negative cascades: 5 consecutive negative valence observations on the same dimension → gate that dimension for 600s. The control law adds a *complementary* hysteresis for positive inflation: 5 consecutive affirming observations on the same dimension → reduce learning rate by 0.5x for that dimension.

**Corrective Actions:**

| Level | Condition | Action |
|-------|-----------|--------|
| 1 — Low coherence drift | coherence in [0.20, 0.25] | Increase stochastic resonance noise (step 2 of cascade) from base level to 1.5x. This introduces exploratory noise that can break negative feedback loops by occasionally generating unexpected positive observations. |
| 2 — Near-floor coherence | coherence in [0.15, 0.20] | **Activate rumination breaker globally** (not per-dimension). Reduce cascade trigger sensitivity: require 2 events of same source within 30s instead of 1. This slows the rate at which new negative observations can accumulate. Log at WARNING. |
| 3 — Near-ceiling coherence | coherence > 0.85 | **Increase problematizing weight by 1.5x.** The dampening rule (magnitude > 0.7 reduces step size) prevents runaway inflation, but near the ceiling, additional resistance is needed. Temporarily increase the problematizing step multiplier so negative evidence has more effect. |

**Escalation:** Coherence at exactly 0.15 (the floor) for >10 minutes is a pathological state — the shame spiral guard is actively preventing collapse but cannot restore healthy functioning. Emit impingement (type=COGNITIVE, strength=0.6, "apperception coherence at floor"). This is informational — no automated recovery exists for a collapsed self-model.

**Safety Constraints:**
- Never modify the coherence floor (0.15) or ceiling (0.95) at runtime. These are constitutional constants (shame spiral prevention + narcissistic inflation prevention).
- Never reset dimensions or clear history. The self-model is accumulated evidence — destroying it is not recovery, it is amnesia.
- The rumination breaker's 600s gate is a safety mechanism, not a bug. Do not shorten it under any control law action.
- Apperception operates on *derived* events (prediction errors, corrections, pattern shifts). Its control law must never modify the source event stream — only how apperception *processes* events.

---

### 2.10 Reactive Engine

```
COMPONENT: reactive_engine
CONTROLLED VARIABLE: Rule execution health — fraction of rule executions completing without error or timeout
REFERENCE SIGNAL: 1.0 (all rules execute successfully)
ERROR SIGNAL: errors / total_executions (trailing window of 20 executions)
ERROR THRESHOLD: 0.15 (i.e., >3 failures in last 20 executions)
```

**Hysteresis:** Degrade after 2 consecutive evaluation cycles with error rate > 0.15. Recover after 5 consecutive cycles with error rate < 0.10 (note: recovery threshold is stricter than degradation threshold — this prevents edge-case oscillation at exactly 0.15).

**Corrective Actions:**

| Level | Condition | Action |
|-------|-----------|--------|
| 1 — Elevated error rate | 0.15-0.30 error rate | Log failing rules with their error details. Increase action_timeout_s from 120s to 60s for Phase 2 (cloud LLM) rules (fail faster to free semaphore slots). Continue all phases. |
| 2 — High error rate | >0.30 error rate | **Disable Phase 2 (cloud LLM) rules entirely.** These are the most failure-prone (network-dependent, expensive, slow) and the least critical (they enhance but don't maintain core functionality). Phase 0 (deterministic) and Phase 1 (local LLM) rules continue. Log which Phase 2 rules are disabled. |
| 3 — Critical error rate | >0.50 error rate, or Phase 0 rules failing | **Disable Phase 1 (GPU/local LLM) rules.** Only Phase 0 (deterministic) rules execute. This preserves the filesystem-as-bus cascade (file writes triggering downstream file writes) while shedding all LLM inference. |

**Escalation:** If Phase 0 rules themselves fail (which would indicate filesystem or Python runtime issues, not LLM issues), the reactive engine publishes perception=0.0 and logs at CRITICAL. It does NOT stop the inotify watcher — rule matching continues, only execution is affected. systemd restart is the escalation path.

**Recovery from Level 2:** 5 consecutive clean cycles → re-enable Phase 2 rules one at a time (ordered by priority). Each re-enabled rule must succeed 3 times before the next is re-enabled. This staged recovery prevents a burst of re-enabled cloud LLM calls from immediately overwhelming a recovering API.

**Safety Constraints:**
- Never disable Phase 0 rules (deterministic cascades are the backbone of the filesystem-as-bus architecture).
- Never increase concurrency limits (gpu_concurrency, cloud_concurrency) as a corrective action. The semaphore bounds exist for resource protection.
- Rule disablement must be per-phase, not per-rule. Individual rule disablement would require maintaining a blocklist and risks leaving gaps in the cascade graph.

---

### 2.11 Studio Compositor

```
COMPONENT: compositor
CONTROLLED VARIABLE: Camera availability — fraction of configured cameras producing frames
REFERENCE SIGNAL: 1.0 (all configured cameras active)
ERROR SIGNAL: 1.0 - (active_cameras / configured_cameras)
ERROR THRESHOLD: 0.34 (i.e., at least one camera offline in a 3-camera setup)
```

**Hysteresis:** Degrade after 2 consecutive status checks with a camera offline (~4s at 2s GStreamer bus check). Recover after 10 consecutive checks with camera online (~20s — cameras need time to stabilize after reconnection).

**Corrective Actions:**

| Level | Condition | Action |
|-------|-----------|--------|
| 1 — Single camera loss | 2/3 cameras active | **Reduce layout to 2-camera composition.** The compositor already has `_mark_camera_offline(role)` (PARTIALLY IMPLEMENTED in lifecycle.py). Additional: adjust videomixer sink pads to center the remaining 2 cameras. Log which camera role is offline. Continue recording and HLS on available cameras. |
| 2 — Multiple camera loss | 1/3 cameras active | **Switch to single-camera fullscreen mode.** Remove the tiling layout entirely. Output the single remaining camera at full resolution to v4l2loopback. Disable any overlay effects that depend on multi-camera input (e.g., PiP, cross-fade transitions). |
| 3 — No cameras | 0/3 cameras active | **Output a static test pattern** (solid color frame, not black — black is indistinguishable from a dead pipeline). Write status "no_cameras" to the status file. Continue running the pipeline so cameras can be hot-plugged. Do NOT output to HLS (serving a test pattern wastes bandwidth). |

**Escalation:** If Level 3 persists for >5 minutes, emit ntfy notification ("All cameras offline"). The compositor does not attempt to restart cameras — USB device lifecycle is outside its control.

**Recovery:** Camera reconnection triggers GStreamer pad events. The compositor's bus message handler (`_on_bus_message`) detects the new pad and re-adds the camera. Recovery hysteresis (10 checks) ensures the camera is stable before restoring the full layout.

**Safety Constraints:**
- Never attempt USB device reset or v4l2 ioctl commands from the compositor process. Device management is an OS-level concern.
- Pipeline set_state(NULL) and rebuild is a last resort, not a corrective action. It causes a visible glitch on the output and potential frame loss in recordings.
- Layout changes must be smooth (videomixer property transitions, not abrupt pad disconnection).
- The compositor must never stop writing to v4l2loopback — downstream consumers (OBS, HLS) expect a continuous stream even if it is a test pattern.

---

### 2.12 Reverie (Visual Expression)

```
COMPONENT: reverie
CONTROLLED VARIABLE: Tick health — whether the governance tick completes without exception
REFERENCE SIGNAL: 1.0 (tick completes successfully)
ERROR SIGNAL: 0.0 on success, 1.0 on exception
ERROR THRESHOLD: 0.5 (any tick failure)
```

**Hysteresis:** Degrade after 3 consecutive tick failures. Recover after 5 consecutive successes.

**Corrective Actions:**

| Level | Condition | Action |
|-------|-----------|--------|
| 1 — Transient tick failure | 1-2 consecutive failures | Log exception (ALREADY IMPLEMENTED). Publish perception=0.0 (ALREADY IMPLEMENTED). Continue at normal 1s tick interval. The wgpu pipeline operates independently — a Python tick failure does not stop frame rendering. |
| 2 — Sustained failure | 3+ consecutive failures | **Freeze visual chain state.** Stop writing new uniforms.json to /dev/shm. The Rust DynamicPipeline will continue rendering with the last-known uniforms, producing a static but visually coherent output. Disable impingement consumption (impingements arriving during degraded state are dropped, not queued — prevents burst on recovery). |
| 3 — Prolonged failure | 10+ consecutive failures (~10s) | **Write a "fallback" uniforms.json** with minimal safe values: intensity=0.3, tension=0.0, depth=0.5, coherence=1.0, all other dimensions=0.0. This produces a subtle, ambient visual that is clearly "alive" but not distracting. Disable satellite recruitment. Reduce tick interval to 5s (conserve CPU). |

**Escalation:** If Level 3 persists for >60s, emit impingement (type=VISUAL, strength=0.4, "Reverie mixer degraded"). Reverie failure is cosmetic, not functional — the system continues to operate fully without visual expression.

**Recovery from Level 2/3:** Resume normal tick interval. Re-enable impingement consumption. Do NOT replay dropped impingements — start fresh from current state. Resume writing uniforms.json. The visual chain will smoothly transition from frozen/fallback values to live values due to the decay_rate mechanism.

**Safety Constraints:**
- Never kill or restart the hapax-imagination Rust process from the Python mixer. The Rust process has its own lifecycle management.
- Fallback uniforms must be *gentle* values (low intensity, high coherence) — not zeros, which could produce a black frame, and not maximal values, which could produce a seizure-inducing strobe.
- Never queue impingements during degraded mode. A burst of queued impingements on recovery would cause a visual spike.

---

### 2.13 Voice Pipeline (ASR→LLM→TTS)

```
COMPONENT: voice_pipeline
CONTROLLED VARIABLE: ASR availability — whether the conversation pipeline exists and is active
REFERENCE SIGNAL: 1.0 (ASR model loaded, pipeline accepting audio)
ERROR SIGNAL: 0.0 if ASR available, 1.0 if not
ERROR THRESHOLD: 0.5
```

**Hysteresis:** Degrade after 3 consecutive perception ticks with ASR unavailable (~4.5s). Recover after 5 consecutive ticks with ASR available.

**Corrective Actions:**

| Level | Condition | Action |
|-------|-----------|--------|
| 1 — ASR temporarily unavailable | Pipeline exists but `is_active` returns False | Continue monitoring. The pipeline may be in a transient state (model loading, reconnecting). Do not interfere with the pipeline's own recovery logic. Publish perception=0.0. |
| 2 — Pipeline absent | `_conversation_pipeline is None` for 3+ ticks | **Increase silence detection threshold** in the voice daemon's frame gate. When ASR is unavailable, audio frames are accumulating without being processed. By raising the energy threshold for "speech detected," we prevent the frame buffer from growing unboundedly. Log at WARNING. |
| 3 — Sustained absence | Pipeline absent for >30s | **Enter listen-only mode.** The voice daemon continues perception (all backends run normally) but does not attempt to start new conversations. The operator can still trigger conversation via explicit command (tap gesture, keyboard shortcut). This prevents the voice daemon from repeatedly trying to initialize a failing ASR model. |

**Escalation:** If Level 3 persists for >5 minutes, emit impingement (INFRASTRUCTURE, strength=0.5, "Voice pipeline offline"). The voice daemon does not attempt to restart the ASR model — that would require GPU memory management beyond its scope.

**Recovery:** When a new conversation pipeline is created (via session start), immediately restore normal frame gate thresholds and exit listen-only mode.

**Safety Constraints:**
- Never attempt to load or unload ASR models. Model lifecycle is managed by the session layer, not by the perception loop.
- Listen-only mode must still process all perception backends — the operator's presence, activity, and stimmung signals are needed even without voice interaction.
- Frame buffer growth must be bounded regardless of control law state. If the buffer exceeds 10s of audio, older frames are dropped (not queued).

---

### 2.14 Consent Engine

```
COMPONENT: consent_engine
CONTROLLED VARIABLE: Contract registry integrity — whether contracts are loaded and not stale
REFERENCE SIGNAL: 1.0 (contracts loaded, registry not stale, not fail-closed)
ERROR SIGNAL: Composite:
  - fail_closed=True: perception = 0.0
  - is_stale()=True: perception = 0.3
  - loaded and fresh: perception = 1.0
ERROR THRESHOLD: perception < 0.5 (fail-closed state)
```

**Hysteresis:** Degrade immediately (no hysteresis on degradation — consent is a safety system). Recover after 3 consecutive checks with contracts loaded and fresh.

**Corrective Actions:**

| Level | Condition | Action |
|-------|-----------|--------|
| 1 — Stale registry | `is_stale()` returns True (>300s since load) | **Attempt single reload** from `axioms/contracts/` directory. If reload succeeds, update `_loaded_at` and continue. If reload fails, remain stale but do NOT go fail-closed (stale contracts are better than no contracts). Log at WARNING with time since last load. |
| 2 — Fail-closed | `fail_closed=True` (load failed entirely) | **This is already the correct behavior.** Fail-closed means all consent checks return False (deny). This is the most conservative possible response. Additional action: emit ntfy notification to operator ("Consent engine fail-closed — all person-data operations blocked"). The operator needs to know because fail-closed blocks legitimate data flows. |
| 3 — Contract file corruption | Reload attempt raises YAML parse errors | **Preserve the last-known-good registry in memory.** Do not replace a working registry with corrupted data. Log the parse error with the specific file path. Emit ntfy notification with the error details so the operator can fix the YAML. Set a `_corruption_detected` flag in health.json. |

**Escalation:** Consent engine failure is a governance issue, not a performance issue. If fail-closed persists for >10 minutes, emit a high-priority ntfy notification (priority=high). The operator must intervene — there is no automated resolution for missing consent contracts.

**Safety Constraints:**
- **NEVER go fail-open.** Under no circumstance should the control law bypass consent checks. The consent engine's fail-closed behavior is not a bug to be "fixed" by a control law — it is the constitutionally mandated response to uncertainty.
- Reload attempts must be rate-limited (at most once per 60s) to prevent filesystem thrashing on corrupted contract files.
- The control law must never modify contract files. Contracts are authored by the operator and versioned in git.
- The `_corruption_detected` flag must be cleared only when a successful reload occurs, not after a timeout.

---

## 3. Cross-Component Interaction Analysis

### 3.1 Cascade Prevention

The control laws are designed to prevent cascading failures through three mechanisms:

1. **No upward amplification.** A component's corrective action never increases load on upstream components. All actions are *reductions* (slower cadence, fewer features, shed load).

2. **Stale data → absence, not propagation.** When a component degrades, it stops publishing or publishes defaults — it does not publish stale data that could be misinterpreted as fresh by downstream readers.

3. **Independent hysteresis.** Each component maintains its own hysteresis counters. There is no "system-wide degradation counter" that could synchronize all components into simultaneous state changes (which would be a thundering herd).

### 3.2 Dependency-Ordered Recovery

When multiple components are degraded, recovery should follow the dependency order:

```
Tier 0 (recover first):  Stimmung, Consent Engine
Tier 1 (recover second): IR Perception, Contact Mic
Tier 2 (recover third):  Voice Daemon, DMN Pulse
Tier 3 (recover last):   Imagination, Content Resolver, Temporal Bands, Apperception
Tier 4 (cosmetic):       Reverie, Studio Compositor, Reactive Engine (Phase 2), Voice Pipeline
```

This ordering is not enforced mechanically — each component recovers independently. But the asymmetric hysteresis (fast degrade, slow recover) naturally produces this ordering because upstream components (which fail first when things go wrong) also recover first (they have no upstream dependencies to wait for).

### 3.3 Stimmung Interaction Matrix

| Component Control Law | Stimmung Interaction |
|-----------------------|---------------------|
| IR Perception | None — IR is a data source for stimmung, not a consumer |
| Contact Mic | None — hardware backend, operates at physical cadence |
| Voice Daemon | Reads stance for governor modulation (existing), independent of control law |
| DMN Pulse | Reads stance for rate modulation (EXISTING). Control law and stimmung effects compound multiplicatively |
| Imagination | Reads stance for cadence modulation (EXISTING). Control law and stimmung effects compound |
| Content Resolver | None — operates on imagination output, not system-wide state |
| Stimmung | Self-referential — own control law affects the signal other components read |
| Temporal Bands | None — pure formatter, no behavioral modulation |
| Apperception | Reads stance for stochastic resonance level (existing) |
| Reactive Engine | Uses stimmung indirectly via Phase 2 rules that may read stance |
| Compositor | None — GStreamer pipeline operates at hardware cadence |
| Reverie | Reads stance for visual chain modulation (existing) |
| Voice Pipeline | None — ASR availability is independent of system mood |
| Consent Engine | None — governance operates independently of mood |

---

## 4. Implementation Priority

| Priority | Components | Rationale |
|----------|-----------|-----------|
| **P0 — Already done** | Imagination (PoC), Stimmung hysteresis | Proof-of-concept validates the pattern |
| **P1 — Safety critical** | Consent Engine, Stimmung meta-control | Governance and coordination signal quality |
| **P2 — Core perception** | DMN Pulse, Voice Daemon, IR Perception | Core cognitive loop components |
| **P3 — Enhancement** | Contact Mic, Reactive Engine, Apperception | Improves resilience but system functions without |
| **P4 — Cosmetic** | Reverie, Compositor, Voice Pipeline, Content Resolver, Temporal Bands | Nice to have; failures are visible but not functional |

**Estimated implementation effort:** Each control law is 30-60 lines of Python (hysteresis counter + level checks + corrective action dispatch). Total: ~600-800 lines across 14 files, plus ~400 lines of tests. Approximately 3-4 days of implementation work.

---

## 5. Testing Strategy

Each control law requires three categories of tests:

1. **Unit test: hysteresis transitions.** Verify that the component degrades after N errors and recovers after M successes. Verify that N < M (asymmetric). Verify that a single good reading in a degradation window does not reset the counter.

2. **Unit test: corrective action safety.** Verify that each corrective action is idempotent (applying it twice produces the same state as applying it once). Verify that corrective actions do not modify state outside the component's boundary.

3. **Integration test: cascade prevention.** Simulate upstream component failure. Verify that the downstream component degrades gracefully without amplifying the failure. Key scenarios:
   - Ollama crash → DMN degrades → Imagination degrades → Reverie freezes (correct cascade)
   - All Pis offline → IR perception defaults → Voice daemon partial staleness (correct)
   - Stimmung all-stale → stance=critical → DMN slows → Imagination pauses (correct, controlled)

---

## 6. Framework Assessment

### 6.1 PCT (Powers, 1973)

**Applicability: HIGH.** PCT provides the correct structural template. Each component controls a perception, not an output. The reference signal is what the component *expects to perceive about its own functioning*. The error signal drives corrective action. The key PCT insight — organisms control perceptions, not behavior — maps precisely to our design: components control their *perceived health*, and behavior change is the means, not the goal.

**Limitation:** PCT assumes continuous control with smooth gain functions. Our system is discrete (tick-based) with threshold-triggered actions. We use hysteresis instead of smooth gain to prevent oscillation in a discrete system.

**Template contribution:** Controlled variable, reference signal, error signal structure.

### 6.2 MAPE-K (Kephart & Chess, 2003)

**Applicability: MEDIUM.** The Monitor-Analyze-Plan-Execute structure maps well to our tick cycle. Monitor = compute ControlSignal. Analyze = check hysteresis counters. Plan = select corrective action level. Execute = apply the action. The shared Knowledge base = /dev/shm traces.

**Limitation:** MAPE-K assumes a centralized autonomic manager per managed element. Our components are self-managing — there is no separate "autonomic manager" process. The control law is embedded in the component itself.

**Template contribution:** Separation of monitoring from action (hysteresis as the Analyze phase).

### 6.3 Kubernetes Reconciliation

**Applicability: MEDIUM.** The reconciliation pattern (desired state → observe actual → converge) is structurally identical to PCT. Kubernetes adds graceful degradation as a first-class concept, which PCT does not address. The Kubernetes insight that controllers should "continue operating as best they can during partial failures" directly informed our Level 2 actions.

**Limitation:** Kubernetes assumes a declarative desired state that can be fully specified. Our "desired state" (all components healthy) is an aspiration, not a specification — the system routinely operates with partial health.

**Template contribution:** Graceful degradation levels, staged recovery.

### 6.4 Chaos Engineering

**Applicability: LOW for control law design, HIGH for validation.** Chaos engineering does not specify control laws — it specifies *how to test* them. The steady-state hypothesis ("this measurable property will hold under perturbation") maps directly to our ControlSignal reference values. Chaos experiments would inject the failures that each control law is designed to handle.

**Template contribution:** Steady-state hypothesis as the definition of "reference signal."

---

## References

- Powers, W.T. (1973). *Behavior: The Control of Perception.* Aldine.
- Kephart, J.O. & Chess, D.M. (2003). "The Vision of Autonomic Computing." IEEE Computer, 36(1).
- Garlan, D., Cheng, S.-W., Huang, A.-C., Schmerl, B. & Steenkiste, P. (2004). "Rainbow: Architecture-Based Self-Adaptation with Reusable Infrastructure." IEEE Computer, 37(10).
- Rosenthal, C., Jones, N., Basiri, A. & Hochstein, L. (2017). *Chaos Engineering.* O'Reilly.
- Marken, R.S. & Mansell, W. (2013). "Perceptual Control as a Unifying Concept in Social Psychology." Review of General Psychology.
- Kubernetes Documentation. "Controllers." https://kubernetes.io/docs/concepts/architecture/controller/

Sources:
- [IBM MAPE-K Reference Model](https://www.researchgate.net/figure/BMs-MAPE-K-reference-model-for-autonomic-control-loops_fig1_358421575)
- [Perceptual Control Theory - Wikipedia](https://en.wikipedia.org/wiki/Perceptual_control_theory)
- [Control at the Heart of Life: A Philosophical Review of PCT](https://www.sciencedirect.com/science/article/pii/S2352154625000452)
- [Rainbow: Architecture-Based Self-Adaptation](https://ieeexplore.ieee.org/document/1301377)
- [Principles of Chaos Engineering](https://principlesofchaos.org/)
- [Google Cloud Chaos Engineering Framework](https://www.infoq.com/news/2025/11/google-chaos-engineering/)
- [Kubernetes Self-Healing Reconciliation Loop](https://dev.to/adipolak/kubernetes-self-healing-reconciliation-loop-4aj5)
- [MAPE-K for Adaptive Workflow Management](https://link.springer.com/article/10.1007/s10844-022-00766-w)
- [Contracts-Based Control Integration into Software Systems](https://link.springer.com/chapter/10.1007/978-3-319-74183-3_9)
- [Self-Healing - CNCF Glossary](https://glossary.cncf.io/self-healing/)
