# Comparative Evaluation: Prior Art vs Existing Patterns

**Date:** 2026-03-11
**Context:** Phase c) of the research plan. Independent comparison of the prior art survey findings against the inside-out codebase analysis. Goal: identify which general-purpose primitives to build, which the code already has, and where the gaps are.

---

## 1. Alignment Matrix

| Prior Art Primitive | Existing Code Equivalent | Gap |
|---------------------|-------------------------|-----|
| **SignalSlot** (Behavior/Event duality) | PerceptionEngine's retained slow fields + VAD events | No explicit type distinction. No `Continuous[T]` vs `Discrete[T]`. Signals are ad-hoc fields, not typed containers. |
| **WithLatestFrom** (multi-cadence fusion) | PerceptionEngine.tick() carrying forward slow fields | Implicit — the "sample slow state when fast tick fires" behavior exists but is hardwired. Not composable. |
| **TimelineMapping** (bidirectional time) | Nothing. All time is `monotonic()`. | Complete gap. No music time, no audio time, no domain-specific time references. |
| **FreshnessWatermark** (staleness tracking) | Nothing explicit. PresenceDetector has face decay (30s). | Staleness exists for exactly one signal. No general freshness on EnvironmentState fields. |
| **CommandObject** (serializable actuation) | Nothing. Directives are bare strings. | Complete gap. No actuation commands as objects. No audit trail of actuation decisions. |
| **GovernanceVeto** (deny-wins composition) | ContextGate's layer chain | Exists but hardcoded. No dynamic rule addition. No provenance. No axiom linkage. |
| **SuppressionWithTimeout** | FrameGate suppression + Governor debounce timers | Partial. Suppression exists (FrameGate) and timeouts exist (governor's resume delay), but they're separate mechanisms, not a unified primitive. |
| **RetainedPubSub** (retained-value pub/sub) | PerceptionEngine._subscribers + carried slow fields | Very partial. Subscribers exist but only push full snapshots. No per-signal retention. No late-joiner semantics. |

---

## 2. What the Code Already Has (and Should Keep)

### Strong matches — the code independently arrived at patterns the survey validates:

1. **Frozen snapshots = Capture-commit (Ableton Link).** EnvironmentState as frozen dataclass is the same pattern as Link's `captureSessionState()`. The code got this right.

2. **Governor = Pure evaluator (behavior tree tick).** The governor's `evaluate(state) → directive` is structurally identical to a behavior tree tick that returns Success/Failure/Running. The three directives (process/pause/withdraw) map to Running/Failure/terminal. The code got this right.

3. **ContextGate = Cedar deny-wins.** The layered gate with fail-closed defaults is exactly Cedar's policy model. Any deny kills the evaluation. The code got this right.

4. **Audio fan-out = DSP multi-rate.** The audio loop's per-consumer buffering with different chunk sizes is a hand-rolled version of SuperCollider's multi-rate UGen graph, where audio-rate data feeds into control-rate consumers at their native block size. The code got this right in substance, even though it's not abstracted.

5. **Wake word supremacy = Subsumption override.** The wake word overriding all governor state is Brooks' suppression mechanism: a higher-priority behavior (user intent) suppresses all lower-priority behaviors (conversation pause, activity mode pause) immediately. The code got this right.

6. **Debounce = Watermark precursor.** Governor's conversation debounce and HyprlandEventListener's pending-confirmation are both doing freshness/stability assessment on signals before acting. This is a simplified form of watermark-based "wait for signal stability before committing."

---

## 3. What's Missing (Prioritized Gaps)

### 3.1 Critical for the North Star Use Case

**TimelineMapping — no music time at all.**

The entire system operates in monotonic wall-clock time. For the backup MC use case, the system needs to understand beat position, bar boundaries, tempo, and phase. None of this exists. This is the single largest gap.

The prior art gives us clear models: Ableton Link's `(beat, time, tempo)` triple, TidalCycles' rational-time query model, MIDI clock's PPQN-based timeline. The implementation needs at least a bidirectional mapping between wall-clock time and beat time, plus the ability to query "what beat are we at now?" and "when does beat N occur in wall-clock time?"

**FreshnessWatermark — no staleness tracking.**

Consumers have no way to know how stale perception data is. The governor makes decisions based on EnvironmentState fields without knowing whether the activity mode was classified 1 second ago or 11 seconds ago. For time-sensitive actuation (triggering a sample on a specific beat), staleness matters — a 10-second-old emotion reading might not reflect the current moment.

The fix is lightweight: add a `last_updated: float` timestamp per signal (or per signal group) to EnvironmentState, and let consumers check freshness before acting.

**CommandObject — no actuation abstraction.**

Directives are bare strings ("process"/"pause"/"withdraw") with no metadata. For the north star use case, actuation needs to be: "play sample X at beat 4.3 with velocity 0.8, triggered by energy peak in the last 50ms." This requires commands as objects with timing, parameters, provenance (which signal triggered this), and a governance check result.

### 3.2 Important for Generality

**SignalSlot — no typed signal containers.**

Adding a new signal to the perception layer currently requires: modifying PerceptionEngine's `tick()`, adding fields to EnvironmentState, wiring the source in VoiceDaemon's constructor, and potentially updating Governor's evaluation rules. This is too much coupling for a system that should handle diverse signal types.

A typed `SignalSource[T]` abstraction would let new signals be registered without touching PerceptionEngine. The engine would iterate over registered sources, sample each one, and compose the snapshot.

**Composable rule evaluation.**

Governor's rules are a hardcoded if/elif chain. ContextGate's layers are a hardcoded method sequence. Neither is composable. For the north star use case, governance needs to handle: axiom enforcement (T0 blocks), activity mode constraints, timing constraints (don't trigger during a rest), energy constraints (match intensity), and user overrides (wake word). These should be composable rules with explicit priority, not a monolithic function.

### 3.3 Nice to Have

**RetainedPubSub — per-signal retained pub/sub.**

Currently, PerceptionEngine notifies subscribers with the full EnvironmentState snapshot. A retained pub/sub where each signal topic retains its latest value would let consumers subscribe to only the signals they care about and always get the current value on subscription (no waiting for the next tick).

**TemporalBuffer — queryable signal history.**

PresenceDetector's sliding window is the only temporal buffer. A general `TemporalBuffer[T]` would enable "what was the energy level 2 beats ago?" queries for the north star use case.

---

## 4. Cross-Cutting Insight: The Hot/Cold Pattern

The most powerful insight from the survey that the code *almost* has is Pure Data's **hot/cold inlet pattern**:

- **Cold update:** A signal updates its value silently (retained). No downstream computation fires.
- **Hot update:** A signal fires and triggers computation using the current values of all cold signals.

The existing code does this implicitly:
- PerceptionEngine's slow fields update silently (cold)
- The fast tick fires and reads all fields (hot)
- Desktop state updates via callback (cold — it updates `_desktop_*` fields but doesn't trigger a tick)

Making this explicit would be the single most impactful refactoring. Instead of "fast tick + slow tick," the system becomes: "N cold signal sources that update at their own rates, plus M hot triggers that sample all cold sources when they fire."

For the north star use case:
- **Cold:** emotion reading (1-2s), activity mode (12s), ambient class (12s), face detection (8s), desktop state (event-driven)
- **Hot:** MIDI clock tick (sub-ms), audio energy threshold crossing (50ms), manual trigger (event)

When a hot trigger fires, it samples all cold signals, produces a fused context, runs governance checks, and potentially emits an actuation command. This is `withLatestFrom` from ReactiveX, hot/cold from Pure Data, and Behavior/Event from FRP — all the same pattern.

---

## 5. Recommended Path Forward

### Step 1: Make existing implicit patterns explicit (low risk, high clarity)

1. Add `freshness: dict[str, float]` to EnvironmentState tracking per-field-group last-update timestamps
2. Extract Governor's rules into a composable `Rule` list with explicit priority
3. Abstract ContextGate's layers into a `VetoChain` that can be inspected and extended

### Step 2: Introduce the core missing primitives (medium risk, enables north star)

4. `TimelineMapping`: bidirectional wall-clock ↔ beat-time conversion, driven by MIDI clock or manual BPM
5. `SignalSource[T]`: typed signal containers with retained value + freshness + subscription
6. `CommandObject`: actuation commands as data objects with timing, parameters, provenance

### Step 3: Refactor perception around hot/cold (higher risk, architectural shift)

7. Reclassify all signals as hot or cold
8. Replace dual-cadence ticking with hot-trigger-driven snapshot generation
9. PerceptionEngine becomes a `withLatestFrom` combinator: "when any hot signal fires, sample all cold signals and produce a snapshot"

Steps 1-2 are additive — they don't break existing behavior. Step 3 is a refactor that changes the fundamental evaluation model. All three steps move toward the north star use case without building any specialized music/MC components.

---

## 6. What NOT to Build

1. **Don't build a music-specific perception engine.** The primitives (TimelineMapping, hot/cold, CommandObject) should handle music time as one of many time domains, not the primary one.

2. **Don't build a sample playback system.** That's an actuation target, not a perception primitive. Build CommandObject first; sample playback is just one handler for music-time-stamped commands.

3. **Don't build an emotion-to-music mapper.** The north star use case needs emotional perception → actuation decisions, but the mapping should emerge from composing general primitives (energy signal crosses threshold → hot trigger → sample cold emotion state → governance check → command object), not from a specialized "emotion-to-music" module.

4. **Don't build a distributed system.** This runs on one machine. ZeroMQ, MQTT brokers, and distributed consensus are overkill. In-process retained pub/sub with typed signals is sufficient.

---

## Sources

- [Prior Art Survey](./2026-03-11-prior-art-survey.md) — Phase a)
- [Inside-Out Analysis](./2026-03-11-inside-out-analysis.md) — Phase b)
- [Backup MC North Star Spec](../specs/2026-03-11-backup-mc-north-star-design.md) — Use case context
