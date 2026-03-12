# Inside-Out Analysis: General Patterns Implicit in the Existing Perception Layer

**Date:** 2026-03-11
**Context:** Phase b) of the research plan. Analyze existing hapax_voice code to extract implicit general-purpose patterns, independently of the prior art survey.

**Method:** Read the full implementation, name the patterns the code already uses, assess their generality, and identify where specialization has crept in that could be abstracted.

---

## 1. Patterns Already Present

### 1.1 Dual-Cadence State Fusion (PerceptionEngine)

**What the code does:** PerceptionEngine maintains two update cadences — a fast tick (2.5s) that reads audio/visual sensors and a slow tick (~12s) that runs LLM workspace analysis and PANNs classification. The slow tick's results are "carried forward" into subsequent fast ticks until the next slow update arrives.

**The implicit general pattern:** A signal combiner that fuses sources at different native rates into a single snapshot, where slower signals are treated as "current until superseded." This is a concrete instance of the **retained-value** pattern: each signal has a latest value that persists until replaced.

**Generality assessment:** Medium. The pattern is general but the implementation is tightly coupled to the specific signal set (VAD, face, desktop, ambient). The carry-forward mechanism is implicit (stored in `_slow_*` fields) rather than explicit as a composable abstraction. Adding a new signal at a third cadence would require modifying PerceptionEngine internals.

**What's missing:** No explicit freshness tracking. The carried-forward slow fields have no timestamp — consumers can't distinguish a 1-second-old LLM analysis from a 11-second-old one. The fast tick doesn't know *how stale* the slow data is.

### 1.2 Immutable State Snapshots (EnvironmentState)

**What the code does:** EnvironmentState is a frozen dataclass. Each perception tick creates a new instance. Consumers receive a snapshot that won't mutate under them.

**The implicit general pattern:** **Capture-commit semantics.** Perception "captures" the current state of all signals into an immutable snapshot. Consumers operate on this snapshot without worrying about concurrent mutations. This is the same pattern as Ableton Link's `captureSessionState()` and game engine state interpolation.

**Generality assessment:** High. Frozen dataclass snapshots are a clean, general abstraction. The issue is that EnvironmentState is a *monolithic* snapshot — all 15+ fields are bundled together. A consumer that only needs VAD + face still receives the full state.

**What's missing:** No partial subscription. No way to say "give me a snapshot of just audio signals." The monolith works because there's exactly one consumer (the governor), but it won't compose if there are multiple consumers with different needs.

### 1.3 Pure State Machine Evaluation (PipelineGovernor)

**What the code does:** Governor takes an EnvironmentState and returns a directive string ("process"/"pause"/"withdraw"). It maintains minimal state (debounce timers, absence tracking) but the evaluation is essentially a pure function of the current state plus a small amount of temporal context.

**The implicit general pattern:** **State → Decision evaluator with debounce.** The governor is a function `(State, History) → Directive` where History is just timing information for debounce and absence tracking. It doesn't own any signals or actuators.

**Generality assessment:** High. The separation of "evaluate state" from "apply directive" is clean. The governor doesn't know about FrameGate, sessions, or pipelines — the daemon mediates. However, the evaluation rules are hardcoded in a priority chain, not composable. Adding a new rule (e.g., "pause during high ambient noise") requires editing the `evaluate()` method.

**What's missing:** Rule composition. The priority order is implicit in code ordering. There's no way to add/remove/reorder rules without modifying the governor. No concept of rule provenance (which axiom does this rule enforce?).

### 1.4 Frame-Level Gating (FrameGate)

**What the code does:** FrameGate sits in the Pipecat pipeline and silently drops audio frames when the directive is "pause." Control frames always pass through.

**The implicit general pattern:** **Typed suppression.** A filter node in a processing pipeline that selectively suppresses certain message types based on an external control signal, while allowing control/lifecycle messages to pass. This is a concrete instance of subsumption's "suppression" mechanism, scoped to a specific message type.

**Generality assessment:** Medium-high. The pattern of "gate data frames but pass control frames" is general and reusable. The implementation is tightly coupled to Pipecat's frame type hierarchy (`AudioRawFrame` specifically). The control signal (directive string) is simple and clean.

**What's missing:** No timeout/automatic revert. Unlike subsumption's suppression-with-timeout, FrameGate stays in whatever state it's told indefinitely. The timeout behavior exists in the governor (conversation resume delay), but the gate itself is stateless — it has no concept of "revert to default after N seconds."

### 1.5 Layered Fail-Closed Gating (ContextGate)

**What the code does:** ContextGate checks a sequence of conditions (session active → activity mode → volume → MIDI → ambient). Each check can block. Any failure in a subprocess check defaults to "block." The first blocking condition short-circuits.

**The implicit general pattern:** **Priority-ordered deny-wins gate chain.** A sequence of boolean checks evaluated in priority order, where any "deny" terminates evaluation. Subprocess failures are treated as denies. This is Cedar's "explicit deny overrides any allow" policy, implemented as a sequential check chain.

**Generality assessment:** High. The pattern is very general — any system with layered veto conditions uses this. The ContextGate implementation is clean: each layer is a method returning `(bool, str)`, the chain is explicit. Adding a new layer is straightforward (add a method, add it to the chain).

**What's missing:** No per-layer provenance or logging. When the gate blocks, you get a reason string, but there's no structured record of which layers were checked and passed before the blocking layer. No concept of "soft deny" vs "hard deny" (all are equal).

### 1.6 Sliding-Window Scoring with Decay (PresenceDetector)

**What the code does:** PresenceDetector accumulates VAD events in a sliding time window and combines them with face detection (which decays after 30s) to produce a presence score.

**The implicit general pattern:** **Temporal evidence accumulation with signal decay.** Multiple evidence sources contribute to a confidence assessment, where evidence expires over time. This is a simplified version of a temporal Bayesian filter (like a Kalman filter reduced to threshold counting).

**Generality assessment:** Medium. The pattern is general (any system needs "how confident are we based on recent evidence?") but the implementation is specialized to exactly two signals (VAD events and face detection) with hardcoded thresholds. The decay mechanism is different for each signal type (sliding window for VAD, timestamp decay for face), which is realistic but not abstracted.

**What's missing:** No general "evidence source" abstraction. Adding a third signal (e.g., keyboard activity, MIDI input) would require modifying the scoring logic. No calibration mechanism — thresholds are set at initialization and never updated.

### 1.7 Concurrent Loop Orchestration (VoiceDaemon)

**What the code does:** The daemon runs multiple async loops at different cadences (audio at real-time, perception at 2.5s, proactive delivery at 30s, main loop at 1s) and coordinates them through shared references to subsystem instances.

**The implicit general pattern:** **Multi-cadence async task graph with shared-state coordination.** Independent loops run at their own rates and communicate by reading/writing shared objects. No explicit message passing — coordination is through method calls and property reads on shared instances.

**Generality assessment:** Low-medium. The pattern is common but the implementation is ad hoc. Loop cadences are hardcoded. Inter-loop coordination is implicit (loop A writes to object X, loop B reads from object X). There's no explicit dependency graph or startup ordering beyond "spawn tasks and go." Adding a new loop requires understanding all the implicit dependencies.

**What's missing:** Explicit dependency declaration. No way to see the data flow between loops without reading all the code. No lifecycle management beyond task cancellation. No backpressure — if the perception loop falls behind, it just skips ticks.

### 1.8 Event-Driven Desktop Integration (HyprlandEventListener)

**What the code does:** Listens to Hyprland's Unix socket for window events and fires callbacks. Uses debounce with "pending-confirmation" to handle rapid alt-tab without losing events.

**The implicit general pattern:** **External event source adapter with debounce.** An adapter that converts an external event stream (Hyprland IPC) into the system's internal representation (desktop state fields on PerceptionEngine), with debounce to smooth high-frequency event bursts.

**Generality assessment:** Medium-high. The adapter pattern is very general. The debounce-with-confirmation technique is reusable. But the wiring is done by the daemon through closure callbacks, which is fragile.

### 1.9 Audio Frame Buffering and Distribution (Audio Loop)

**What the code does:** The audio loop receives 30ms frames and distributes them to multiple consumers (wake word detector, VAD, Gemini) that each expect different frame sizes. It maintains per-consumer buffers and dispatches complete chunks.

**The implicit general pattern:** **Fan-out with per-consumer buffering.** A single source produces data at one rate/chunk-size, and multiple consumers need it at different sizes. The distributor buffers per-consumer and dispatches when each buffer is full.

**Generality assessment:** Medium. The buffer accumulation pattern is general, but it's implemented inline in the audio loop with hardcoded consumer-specific chunk sizes. Adding a new consumer requires modifying the loop body.

---

## 2. Implicit Architectural Decisions

### 2.1 Pull vs Push

The system is primarily **pull-based** for state and **push-based** for events:
- **Pull:** Governor pulls state from PerceptionEngine. ContextGate pulls volume/MIDI state from subprocesses. Main loop pulls latest analysis from WorkspaceMonitor.
- **Push:** HyprlandEventListener pushes desktop events via callbacks. Wake word detector pushes activation via callback. Audio frames are pushed to the audio loop via async queue.

This hybrid is not an explicit design choice — it emerged from convenience. The pull paths introduce latency (governor only sees state when it next ticks). The push paths are immediate but create coupling.

### 2.2 Single Consumer Assumption

EnvironmentState has exactly one consumer: PipelineGovernor. ContextGate doesn't consume EnvironmentState directly — it receives it via `set_environment_state()` but mostly runs its own subprocess checks. This single-consumer design means there's no fan-out, no subscription mechanism, no conflict resolution between multiple consumers wanting different things.

### 2.3 No Explicit Time Domain

Everything uses `time.monotonic()` — wall-clock relative monotonic time. There's no concept of "music time," "audio time," or any domain-specific time reference. All timing is in absolute seconds. This works for a 2.5s perception tick but would not work for music-time-aligned decisions.

### 2.4 Governance is Structural, Not Declared

Governance rules are embedded in code structure:
- Governor's `evaluate()` method has priority baked into `if/elif/else` ordering
- ContextGate's layer chain has priority baked into method call order
- There's no governance policy file, no rule declarations, no way to audit "what rules does the system enforce?"

### 2.5 No Event Log as Decision Input

EventLog records what happened (perception transitions, session events) but is never read back as input. It's write-only from the system's perspective. There's no "what happened in the last N seconds?" query that feeds into decision-making. History is only maintained in PresenceDetector's sliding window and Governor's debounce timers.

---

## 3. Generalization Opportunities

### 3.1 SignalSource Abstraction

**Current state:** Each signal (VAD, face, desktop, ambient, activity mode) is accessed differently — some via method calls on shared objects, some via subprocess execution, some via async queues, some via callback wiring.

**General pattern:** A `SignalSource[T]` that provides:
- `latest: T | None` — current value (retained)
- `freshness: float` — seconds since last update
- `subscribe(callback)` — push notification on update
- `cadence: float` — expected update interval

This would let PerceptionEngine treat all signals uniformly, make freshness explicit, and allow new signals to be added without modifying the engine.

### 3.2 Composable Gate / Veto Chain

**Current state:** ContextGate has a hardcoded layer chain. Governor has hardcoded priority rules.

**General pattern:** A `VetoChain` where each veto is a `(condition: State → bool, priority: int, reason: str)` tuple. The chain evaluates all conditions in priority order and returns the first veto or "allow." Vetoes can be added/removed dynamically. Each veto carries provenance (which axiom/rule it enforces).

### 3.3 Snapshot Projection

**Current state:** EnvironmentState is monolithic — all fields bundled together.

**General pattern:** A `StateProjection` that selects a subset of fields from the full state. Consumers declare which fields they need; the engine provides projected snapshots. This is the CQRS "materialized view" concept applied to perception state.

### 3.4 Cadence-Aware Loop Registry

**Current state:** The daemon manually spawns async tasks and hardcodes sleep intervals.

**General pattern:** A `LoopRegistry` where each loop declares its cadence, dependencies, and a tick function. The registry manages startup ordering, cadence enforcement, and lifecycle. Loops can declare "I need the output of loop X" to express data dependencies.

### 3.5 Temporal State Buffer

**Current state:** PresenceDetector's sliding window is the only temporal buffer. Governor has debounce timers. EventLog records history but can't be queried programmatically.

**General pattern:** A `TemporalBuffer[T]` that stores timestamped values and supports queries: `at(t)` (value at time), `since(t)` (all values since), `window(duration)` (sliding window), `freshness()` (seconds since last update). This subsumes the sliding window, debounce state, and could replace EventLog for decision-relevant history.

---

## 4. What the Code Already Gets Right

1. **Frozen snapshots** — EnvironmentState as immutable dataclass is a correct and general pattern. Don't break this.

2. **Governance separation** — Governor doesn't own signals or actuators. The daemon mediates. This clean separation should be preserved and strengthened.

3. **Fail-closed gating** — ContextGate defaults to "block" on errors. This is the right safety posture for any governance gate.

4. **Debounce as first-class concern** — Governor and HyprlandEventListener both implement debounce explicitly. The system acknowledges that real-world signals are noisy and need smoothing.

5. **Audio frame distribution** — The per-consumer buffering in the audio loop correctly handles the frame-size mismatch problem without forcing all consumers to the same chunk size.

6. **Wake word supremacy** — Wake word overrides all governor state. This is a correct implementation of "user intent always wins" — a governance primitive worth preserving.

---

## 5. Summary: Extracted Primitives

From the existing code, these general primitives are implicit and could be made explicit:

| Primitive | Where It Lives Now | Current Limitation |
|-----------|-------------------|-------------------|
| **RetainedValue** | PerceptionEngine's slow field carry-forward | No freshness tracking |
| **ImmutableSnapshot** | EnvironmentState frozen dataclass | Monolithic, no projection |
| **StateEvaluator** | Governor.evaluate() | Hardcoded rule priority, not composable |
| **TypedSuppression** | FrameGate | No timeout, Pipecat-coupled |
| **DenyWinsChain** | ContextGate layer checks | Hardcoded layers, no provenance |
| **TemporalAccumulator** | PresenceDetector sliding window | Single-purpose, not reusable |
| **FanOutBuffer** | Audio loop per-consumer buffers | Inline implementation, not abstracted |
| **EventAdapter** | HyprlandEventListener | Callback wiring, fragile |
| **DebounceGuard** | Governor conversation debounce | Embedded in evaluator, not reusable |
