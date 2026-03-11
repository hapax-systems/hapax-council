# Prior Art Survey: Multi-Cadence Perception-to-Actuation Architectures

**Date:** 2026-03-11
**Context:** Architectural research for a perception layer that handles signals at wildly different cadences (sub-ms MIDI clock, 50ms audio energy, 1-2s visual emotion, 2.5s environment state) and composes them into actuation decisions (sample playback at 20-50ms precision, TTS synthesis, OBS scene control).

**Goal:** Identify general-purpose primitives, not specialized components.

---

## 1. Signal Stream Abstractions

How do existing systems model heterogeneous time-series data at different rates?

### 1.1 FRP (Functional Reactive Programming)

**Core abstraction:** Two primitives — **Behaviors** (continuous, time-varying values) and **Events** (discrete occurrences). A Behavior has a value at every point in time; an Event has values only at specific instants.

**How it handles multi-cadence:**
- Behaviors are conceptually continuous — they don't have a "rate." You sample them when you need a value. This sidesteps the rate problem entirely for continuously-varying state.
- Events are discrete and asynchronous — they fire when they fire, regardless of cadence.
- Composition happens through combinators: `fmap` transforms signals, `merge` combines event streams, `switch` selects between behaviors dynamically.
- Pull-based FRP (Yampa, classic Fran) evaluates on demand. Push-based FRP (Reflex) propagates changes immediately when inputs change. Push-pull hybrids (Reflex's actual implementation) combine both.

**Key implementations:**

- **Yampa** (Haskell): Uses arrowized signal functions (`SF a b`) that transform input signals to output signals. The system is defined as a network of `SF` values composed with arrow combinators (`>>>`, `***`, `&&&`). Time is implicit — the runtime provides `DTime` (delta time) at each step. Yampa is pull-based and discrete, stepping the entire signal network at each tick.

- **Reflex** (Haskell): Push-pull FRP with `Event t a` (discrete occurrences), `Behavior t a` (time-varying values), and `Dynamic t a` (a Behavior that also notifies on change). Composition via `MonadHold` — you can "hold" the latest event value to create a behavior. Used primarily for UI (reflex-dom) but the model is general.

- **ReactiveX / RxPY**: Observable streams with operator chains. Key operators for multi-cadence: `combineLatest` (emit when any source emits, using latest from all), `withLatestFrom` (sample one stream at the rate of another), `throttle`/`debounce` (rate limiting), `window`/`buffer` (batching). Backpressure via `onBackpressureBuffer`, `onBackpressureDrop`, or reactive pull. Hot observables emit regardless of subscribers; cold observables emit per-subscriber.

**Strengths for our context:**
- The Behavior/Event distinction maps directly to our problem: environment state is a Behavior (always has a value), MIDI clock ticks are Events.
- `combineLatest` and `withLatestFrom` are exactly the operators needed to compose signals at different rates — sample slow signals at the rate of fast decisions.
- Declarative composition avoids manual synchronization.

**Weaknesses:**
- Pure FRP (Yampa-style) assumes a single global clock driving the whole network. Our system has multiple independent clocks.
- ReactiveX loses the semantic distinction between Behaviors and Events — everything is an Observable. This means you lose the guarantee that a Behavior always has a value.
- Backpressure models assume slower consumers, but our problem is mixed-rate producers.

**Key insight worth stealing:** The Behavior/Event duality. Model slow-changing state (emotion, environment) as Behaviors that always have a current value, and fast discrete signals (MIDI, audio onsets) as Events. Compose them with `withLatestFrom` semantics: when a fast event fires, sample the current value of all slow behaviors.

### 1.2 Dataflow / DSP

**Core abstraction:** **Signal flow graphs** where nodes are unit generators (UGens) and edges carry signals. Crucially, signals exist at different **rates**.

**How it handles multi-cadence:**

- **Faust** defines four computation domains discovered by the compiler's type system: (1) compilation/specialization time, (2) init time, (3) control rate, and (4) audio rate. The programmer distributes computation to the most appropriate domain — slower-rate is preferred for efficiency. Faust models signals as discrete functions of time (`int -> float`), signal processors as second-order functions, and composition operators (sequential `:`, parallel `,`, split `<:`, merge `:>`, recursive `~`) as third-order functions. The compiler automatically classifies which computations belong at which rate.

- **SuperCollider** has explicit rate markers: `.ar` (audio rate, typically 44100 Hz) and `.kr` (control rate, 1 sample per 64 audio samples = ~689 Hz at 44.1kHz). A SynthDef is a signal flow graph of UGens. Control-rate UGens automatically interpolate when feeding into audio-rate UGens. Each UGen has a single output; multi-output processors return arrays. The server builds and optimizes the graph at SynthDef compile time.

- **Pure Data / Max/MSP**: Dataflow with two distinct connection types — audio-rate (tilde objects, `osc~`, `dac~`) at 44.1kHz in 64-sample blocks, and control-rate (non-tilde objects) triggered by messages. **Hot and cold inlets**: the leftmost inlet is "hot" (triggers computation), other inlets are "cold" (store values without triggering). A `[bang]` message initiates computation. This hot/cold distinction is a primitive for "update state without acting" vs "act now with current state."

**Strengths for our context:**
- The audio-rate / control-rate separation is a proven solution for mixed-cadence signals coexisting in one graph.
- Faust's automatic rate classification by the compiler is elegant — the system figures out where computation belongs.
- Pure Data's hot/cold inlet pattern directly solves the "sample slow state when fast event fires" problem.

**Weaknesses:**
- DSP assumes all signals are ultimately synchronized to a single sample clock. Our system has truly independent clocks (MIDI clock vs wall clock vs frame rate).
- Block processing (64 samples) introduces latency. Faust can go down to 1-sample blocks but at CPU cost.
- These systems are designed for audio, not general perception-to-actuation.

**Key insight worth stealing:** Multi-rate signal graphs with explicit rate annotations, and Pure Data's hot/cold inlet pattern. A "cold" input updates state silently; a "hot" input triggers computation using all current state. This is a minimal, composable primitive for multi-cadence fusion.

### 1.3 ROS (Robot Operating System)

**Core abstraction:** **Topics** (named pub/sub channels with typed messages), **Nodes** (processes), and **Quality of Service (QoS)** policies governing delivery semantics.

**How it handles multi-cadence:**
- Each sensor publishes to its own topic at its own rate. No global clock assumption.
- **QoS policies** include: Reliability (best-effort vs reliable), Durability (volatile vs transient-local for late joiners), History/Depth (how many messages to buffer), Deadline (max time between publications), Lifespan (message expiry), Liveliness (failure detection). QoS follows a "Request vs Offered" compatibility model — connections form only when subscriber requirements don't exceed publisher capabilities.
- **message_filters** provide time synchronization: `TimeSynchronizer` collects messages from multiple topics and delivers them as a bundle when timestamps are close enough. `ApproximateTimeSynchronizer` handles sensors with slightly different timestamps.
- **tf2** maintains a tree of coordinate frame transforms over time, allowing queries like "where was the camera relative to the base 200ms ago?" This is temporal + spatial alignment.
- **robot_localization** (EKF package) fuses sensors at different rates using circular buffers per sensor, linear interpolation for aligned timestamps, and configurable timeouts and smoothing delays.

**Strengths for our context:**
- Designed from the ground up for heterogeneous sensors at mixed rates.
- QoS policies are a clean abstraction for expressing delivery requirements per-channel.
- The temporal transform tree (tf2) is a powerful primitive for "what was the state of X at time T?"

**Weaknesses:**
- Heavy infrastructure (DDS middleware, discovery protocol). Massive overkill for a single-machine system.
- Message serialization overhead irrelevant for in-process communication.
- tf2 is spatial-first, temporal-second. We need temporal-first.

**Key insight worth stealing:** Per-topic QoS policies and the `ApproximateTimeSynchronizer` pattern. Also, tf2's concept of a queryable temporal state tree — "what was the value of signal X at time T?" as a first-class operation.

### 1.4 Stream Processing (Kafka Streams, Flink, Akka Streams)

**Core abstraction:** Unbounded streams of timestamped events, processed through operator graphs with explicit time semantics and backpressure.

**How it handles multi-cadence:**

- **Apache Flink** distinguishes **event time** (embedded in data, when it actually happened) from **processing time** (wall clock when processed). **Watermarks** — special timestamps flowing through the stream — declare "no more events before time T will arrive." Operators use watermarks to know when to finalize windowed computations. This handles out-of-order and late-arriving events. **Windowing** scopes aggregations: tumbling (non-overlapping), sliding (overlapping), session (gap-based). An **allowed lateness** parameter lets operators accept late data within a grace period.

- **Kafka Streams**: Simpler model built on Kafka's log abstraction. KStream (event stream) vs KTable (changelog / materialized state). Joins between streams of different rates use windowed joins with configurable grace periods.

- **Akka Streams**: Implements Reactive Streams with `Source`, `Flow`, `Sink` as typed graph components. Uses windowed, batching backpressure — multiple elements can be in-flight, and new requests batch after multiple elements drain. The `GraphDSL` allows fan-in and fan-out patterns. **Materialization** is the explicit step of allocating resources and starting the computation described by the graph.

**Strengths for our context:**
- Event time vs processing time distinction is exactly right for our system. A MIDI clock tick has an event time (when it was generated by the hardware) that matters more than when we process it.
- Watermarks solve the "how long do I wait for slow signals before deciding?" problem.
- Backpressure prevents fast producers from overwhelming slow consumers.

**Weaknesses:**
- Designed for distributed systems processing millions of events. Our system is single-machine, low-volume but latency-sensitive.
- Windowing assumes aggregation (count, sum). Our "windows" are more like "what's the current state of all signals?"
- Serialization and checkpoint overhead irrelevant for our use case.

**Key insight worth stealing:** The event-time / processing-time distinction and watermarks. Define a per-signal "freshness" watermark: "I last saw a valid emotion reading at time T." This lets the actuation layer know how stale each perception signal is and make decisions accordingly.

---

## 2. Temporal Reference Frames

How do systems handle multiple notions of time?

### 2.1 Ableton Link

**Core abstraction:** A **timeline** represented as a triple `(beat, time, tempo)` that defines a bijection between beat values and system time values. The `SessionState` is a snapshot of this mapping plus transport state (playing/stopped).

**How it handles multiple time notions:**
- **System time** (microseconds from epoch) is the shared reference. Link maintains a mapping from system time to beat time.
- **Tempo** synchronization: any participant can change tempo; the most recent change wins (eventual convergence, no central authority).
- **Beat alignment**: integral beat values on one participant's timeline correspond to integral beat values on all others (though actual beat numbers may differ by integer offsets).
- **Phase synchronization** via **quantum**: a quantum of 4 beats means all participants agree on bar boundaries. Beat 3 on one device could correspond to beat 11 on another, but never beat 12 (which would break 4-beat phase alignment).
- **Capture-commit model**: applications capture a SessionState snapshot, query/modify it, then commit changes. This ensures consistent values during computation.
- **Threading model**: separate capture/commit functions for the audio thread (realtime-safe, non-blocking) vs application thread (may block). Only modify session state from the audio thread.

**Strengths for our context:**
- The timeline triple `(beat, time, tempo)` is a clean abstraction for mapping between different time domains.
- The capture-commit pattern for thread-safe state access is directly applicable.
- Phase/quantum concepts generalize beyond music — "what fraction of the current cycle are we at?" applies to any periodic process.

**Weaknesses:**
- Assumes a single shared tempo. Our signals don't share a tempo — they have independent cadences.
- Peer-to-peer consensus protocol is unnecessary for a single-machine system.

**Key insight worth stealing:** The timeline triple as a bidirectional time mapping, and the capture-commit pattern for thread-safe state snapshots. Define a `TimelineMapping(reference_time, domain_time, rate)` that converts between wall clock and any signal's native time domain.

### 2.2 TidalCycles

**Core abstraction:** A **Pattern** is a function from a time arc (timespan) to a list of events. Type signature: `type Query a = State -> [Event a]`. Patterns are infinite, cyclic, and queried on demand.

**How it handles time:**
- **Rational time**: time is represented as a ratio of two integers (`Rational` = `Integer/Integer`). Three one-thirds exactly equal one whole — no floating-point drift. This is critical for musical time where divisions must be exact.
- **Cycles**: the fundamental time unit. One cycle = one repetition of the pattern. Cycles are abstract — their wall-clock duration is set externally.
- **Arcs**: queries specify a start and end time (both rational). The pattern function returns all events that intersect that arc.
- **Event structure**: each event has two arcs — the "whole" (the full duration of the part it belongs to) and the "part" (the portion actually present). When whole == part, the event is complete. When part is smaller, the event has been subdivided.
- **Nature**: patterns are either `Analog` (continuous, like a sine wave) or `Digital` (discrete events like drum hits).
- **ControlPattern**: uses `ControlMap` (string-keyed dictionaries) for synthesizer parameters.

**Strengths for our context:**
- The query model is powerful: don't push events, let consumers pull what they need for their current time window. This naturally handles mixed rates — each consumer queries at its own cadence.
- Rational time eliminates drift for periodic signals.
- The Analog/Digital nature distinction maps to Behavior/Event from FRP.

**Weaknesses:**
- Designed for deterministic pattern generation, not real-time perception. Patterns are pure functions — they don't react to external input.
- The cycle-based model assumes periodicity. Our signals are aperiodic.

**Key insight worth stealing:** Patterns as queryable functions of time, and rational time for drift-free periodic processes. Instead of pushing MIDI clock ticks, model the MIDI clock as a queryable timeline: "what beat are we at for time T?" with exact rational arithmetic.

### 2.3 Sonic Pi

**Core abstraction:** **Virtual time** that runs independently of wall-clock time, with explicit synchronization primitives (`cue`/`sync`) between threads.

**How it handles time:**
- **The problem**: using `sleep` for timing is unreliable because execution time varies, audio synthesis messages are asynchronous, and errors compound across multiple threads.
- **The solution**: each thread maintains a virtual time counter. `sleep 1` advances virtual time by 1 second but the actual `play` command is scheduled at the virtual time, not when the code executes. The runtime schedules audio events ahead of time using the virtual timestamps.
- **`cue`/`sync`**: `cue :name` broadcasts a named event from one thread. `sync :name` in another thread blocks until the cue arrives, then **inherits the cue thread's virtual time** and continues. This means synchronized threads share a time reference without drift.
- **`time_warp`**: temporarily shifts virtual time, allowing events to be scheduled in the past or future relative to the current virtual time.

**Strengths for our context:**
- Virtual time decoupled from wall clock solves the "schedule ahead" problem for audio output that needs precise timing.
- The cue/sync model where synchronized threads inherit time references is elegant for multi-cadence coordination.

**Weaknesses:**
- Virtual time is linear and monotonic. Doesn't handle tempo changes or non-uniform time domains.
- Designed for generative music, not reactive perception.

**Key insight worth stealing:** Virtual time with ahead-of-time scheduling. For actuation that needs precise timing (sample playback), schedule events using a virtual time that maps to the audio system's future, not the current wall clock. The cue/sync "inherit the sender's time" pattern is a clean primitive for time-domain handoff between components.

### 2.4 Game Engine Timestep Decoupling

**Core abstraction:** The **accumulator pattern** — separate fixed-timestep simulation from variable-rate rendering via an accumulator that tracks unconsumed time.

**How it handles multiple time rates:**

The canonical formulation (Glenn Fiedler, "Fix Your Timestep!"):

```
accumulator += frameTime
while accumulator >= dt:
    previousState = currentState
    integrate(currentState, t, dt)
    accumulator -= dt
alpha = accumulator / dt
renderState = lerp(previousState, currentState, alpha)
```

- **Fixed timestep** (`dt`): physics simulation runs at a constant rate (e.g., 60 Hz) regardless of frame rate. This ensures determinism and stability.
- **Variable rendering**: the render loop runs as fast as possible. The accumulator tracks how much simulation time hasn't been consumed yet.
- **Interpolation**: the leftover accumulator time becomes an alpha value for linear interpolation between the previous and current physics states. This eliminates temporal aliasing (stuttering).
- **Spiral of death prevention**: cap the maximum frame time to prevent physics from falling behind when rendering is slow.

**Implementations:**
- **Unity**: `FixedUpdate()` (physics, fixed dt of 0.02s default) vs `Update()` (rendering, variable dt). Multiple `FixedUpdate` calls may execute per `Update` frame.
- **Godot**: `_physics_process(delta)` (fixed at 60 Hz default) vs `_process(delta)` (variable). Physics interpolation can be enabled to smooth display between physics steps.
- **Unreal**: Semi-fixed timestep with substepping — subdivides large frame times into smaller physics steps.

**Strengths for our context:**
- The accumulator pattern is a general solution for running two systems at different rates on the same machine.
- Interpolation between states is directly applicable — when actuation needs a value between two perception samples, interpolate.
- The "spiral of death" concept applies: if perception processing falls behind, cap it rather than trying to catch up.

**Weaknesses:**
- Assumes exactly two rates (physics + render). We have N rates.
- The accumulator model is synchronous — it assumes both systems are driven by the same main loop.

**Key insight worth stealing:** The accumulator pattern generalized to N rates. Each signal source has its own accumulator. The actuation layer consumes accumulated state, interpolating between samples when needed. Cap processing to prevent cascade failures when any signal falls behind.

### 2.5 MIDI Clock

**Core abstraction:** A stream of single-byte timing messages at 24 pulses per quarter note (PPQN), plus transport messages (Start, Stop, Continue, Song Position Pointer).

**How it handles time:**
- 24 PPQN divides the quarter note into 24 equal parts. At 120 BPM, that's 48 ticks/second (~20.8ms per tick). At 180 BPM, 72 ticks/second (~13.9ms per tick).
- The resolution supports triplets (24 / 3 = 8) and swing (alternating tick counts).
- **Transport messages**: Start resets to beat 1, Continue resumes from current position, Stop halts playback. The clock keeps ticking even when stopped so receivers stay ready.
- **Song Position Pointer (SPP)**: 14-bit value (0-16383) indicating position in 16th notes from song start. Allows jumping to arbitrary positions.
- **Real-time priority**: MIDI clock bytes can interrupt other MIDI messages mid-transmission to ensure timing accuracy.

**Strengths for our context:**
- The "clock keeps ticking when stopped" pattern is useful — perception should keep running even when actuation is paused.
- SPP allows random access into the timeline — useful for "what beat are we at?"

**Weaknesses:**
- 24 PPQN is coarse for sub-millisecond precision. Modern hardware often uses higher internal resolutions.
- Master-slave model (one clock source) doesn't match our multi-source architecture.
- No notion of varying tempo within a stream — tempo changes are implicit in tick spacing.

**Key insight worth stealing:** The separation of clock (continuous timing) from transport (start/stop/continue/locate). Our system needs both: a timing reference that always runs, and transport control that governs when actuation responds to perception.

### 2.6 PTP (IEEE 1588)

**Core abstraction:** Hierarchical master-slave clock synchronization achieving sub-microsecond (potentially sub-nanosecond) precision across a network.

**How it handles time:**
- A **grandmaster clock** is elected via the Best Master Clock Algorithm (BMCA). All other clocks synchronize to it.
- **Sync messages**: the master periodically sends timestamps. Slaves measure message delay and compute clock offset.
- **Boundary clocks** relay timing across network segments, re-stamping at each hop.
- PTP operates at Layer 2 (Ethernet) or Layer 3 (UDP), with hardware timestamping for maximum precision.

**Relevance to our context:**
- For a single-machine system, PTP itself is unnecessary. However, the concept of a single elected time reference that all other subsystems synchronize to is directly applicable.
- Hardware timestamping at the NIC level demonstrates that timing precision matters at the infrastructure level, not just the application level.

**Key insight worth stealing:** Elect a single reference clock for the system. All signal timestamps are expressed relative to this reference. The reference should be the highest-precision clock available (e.g., the audio interface's sample clock).

---

## 3. Governance / Constraint Composition

How do systems generalize decision-making under constraints?

### 3.1 Rule Engines (Drools, CLIPS, OPS5)

**Core abstraction:** **Production rules** — condition-action pairs evaluated against a **working memory** of facts. When conditions match, actions fire. The Rete algorithm efficiently indexes rules and facts to avoid re-evaluating everything on each change.

**How it handles decision composition:**
- **Forward chaining**: facts are asserted into working memory, triggering rules whose conditions match. Fired rules may assert new facts, triggering more rules.
- **Conflict resolution**: when multiple rules match simultaneously, a strategy selects which fires first. Drools uses **salience** (numeric priority, default 0), then recency (most recently activated first), then specificity.
- **Working memory**: the shared state that rules pattern-match against. Facts are inserted, modified, or retracted. `FactHandle` is the token for interacting with an inserted fact.
- **Rete network**: compiles rule conditions into a discrimination network. Alpha nodes test individual conditions; beta nodes test joins across facts. This avoids re-testing all rules when one fact changes.

**Strengths for our context:**
- The "assert facts, let rules react" model maps well to perception signals becoming facts and governance rules constraining actuation.
- Salience provides simple priority ordering — higher-priority axioms (T0) get higher salience.
- The Rete algorithm is efficient for many rules over changing facts.

**Weaknesses:**
- Rule engines are designed for business logic, not real-time control. Rete has unpredictable latency.
- Conflict resolution strategies are global, not composable.
- Forward chaining can cascade unpredictably — hard to reason about timing.

**Key insight worth stealing:** The working memory as a shared perception state that governance rules pattern-match against. Instead of rules directly calling actuators, rules modify the working memory (setting constraints, permissions, vetoes) and a separate actuation layer reads the constrained state.

### 3.2 Behavior Trees

**Core abstraction:** A tree of nodes that is **ticked** at a regular interval. Each node returns `Success`, `Failure`, or `Running`. Internal nodes compose child behaviors.

**Node types:**
- **Sequence** (AND): ticks children left-to-right, succeeds if all succeed, fails on first failure.
- **Selector/Fallback** (OR): ticks children left-to-right, succeeds on first success, fails if all fail.
- **Decorator**: wraps a single child, modifying its result (invert, repeat, timeout, etc.).
- **Leaf nodes**: conditions (check state) and actions (do something).

**How it handles decision composition:**
- Trees are ticked from the root each cycle. This means priority is implicit in tree structure — leftmost children of a Selector are tried first.
- **Running** status allows long-running actions across multiple ticks without blocking the tree.
- Subtrees are modular and reusable — you can compose complex behaviors from simple ones.
- **Blackboard** (shared state): nodes read/write a shared data structure, allowing communication without coupling.

**Strengths for our context:**
- The tick model maps to our actuation cycle. Each tick = one decision opportunity.
- Selector nodes naturally express fallback behavior: "try the preferred action, fall back to safe default."
- Running status handles actions that span multiple perception cycles (TTS synthesis).
- Modularity — add new behaviors without restructuring existing ones.

**Weaknesses:**
- Trees are evaluated top-down each tick, which can be wasteful for parts of the tree that haven't changed.
- No native concept of time or cadence — ticks are assumed uniform.
- Blackboard is unstructured — any node can write anything, making it hard to reason about data flow.

**Key insight worth stealing:** The tick-based evaluation with three-valued return (Success/Failure/Running) and the Selector node as a priority-ordered fallback. For actuation: tick the governance tree each cycle. Higher-priority constraints (axiom violations) are leftmost in a Selector and pre-empt lower-priority actions.

### 3.3 Subsumption Architecture (Brooks)

**Core abstraction:** **Layered reactive control** where each layer is a complete behavior implemented as a network of **augmented finite state machines (AFSMs)**. Higher layers can **suppress** (override outputs of) or **inhibit** (block inputs to) lower layers.

**How it handles governance:**
- Layers are numbered from 0 (lowest, most reactive) upward. Layer 0 might be "avoid obstacles," layer 1 "wander," layer 2 "explore."
- Each layer runs independently and continuously in parallel. There is no central coordinator.
- **Suppression**: a higher layer's output replaces a lower layer's output for a fixed time duration. If the higher layer stops asserting, the lower layer's output resumes.
- **Inhibition**: a higher layer blocks a lower layer's input for a fixed duration.
- Key property: removing higher layers leaves a fully functional system at the lower level. Each layer adds competence without depending on layers above it.

**Strengths for our context:**
- The "layers as independent competence levels" model maps to governance tiers. Base layer: always-safe defaults. Upper layers: contextually-appropriate refinements.
- Suppression with timeout is a clean primitive: "override this for N ms, then revert to default." This handles transient governance decisions without permanent state changes.
- No central coordinator — each layer is autonomous. This is resilient to partial failures.

**Weaknesses:**
- Designed for simple reactive robots, not complex decision-making.
- No deliberation or planning — purely reactive.
- Suppression/inhibition are binary (on/off), not graduated.

**Key insight worth stealing:** Suppression with timeout as a governance primitive. A higher-priority constraint can suppress a lower-priority behavior for a bounded duration, after which the system reverts to the lower-priority default. This prevents governance decisions from becoming permanent accidentally.

### 3.4 Blackboard Architecture

**Core abstraction:** Three components — a **blackboard** (shared structured workspace), **knowledge sources** (independent specialist modules), and a **control component** (selects which knowledge source to run next).

**How it handles decision composition:**
- The blackboard contains partial solutions organized into **levels of analysis** (hierarchical). Objects at each level have attribute-value pairs.
- Knowledge sources monitor the blackboard and declare interest in specific patterns. When their preconditions match, they become candidates for execution.
- The control component selects among ready knowledge sources using a strategy (priority, focus of attention, opportunity cost).
- Knowledge sources are independent — they don't know about each other. They only interact through the blackboard.
- Incremental refinement: each knowledge source contributes a partial solution, building toward a complete answer over multiple cycles.

**Strengths for our context:**
- The perception layer IS a blackboard: multiple knowledge sources (MIDI parser, audio analyzer, emotion detector, environment scanner) each contribute partial state to a shared workspace.
- Levels of analysis map to levels of abstraction: raw signals -> features -> interpretations -> decisions.
- Control component can implement governance by selecting which knowledge sources run and in what order.

**Weaknesses:**
- The control component is a bottleneck and hard to design well.
- No built-in notion of time or freshness — stale data on the blackboard looks the same as fresh data.
- Can be inefficient — knowledge sources may repeatedly check conditions that haven't changed.

**Key insight worth stealing:** The blackboard as a structured, hierarchical shared workspace with levels of analysis. Perception signals write to lower levels, intermediate processing writes to middle levels, governance constraints write to upper levels. Actuation reads from the top level. Each entry is timestamped for freshness.

### 3.5 Constraint Satisfaction (CSP/SAT)

**Core abstraction:** Variables with domains, connected by constraints. A solution assigns values to all variables such that all constraints are satisfied.

**How constraints compose:**
- Constraints are conjunctive by default — all must be satisfied simultaneously.
- **Arc consistency** (AC-3 algorithm): for each pair of constrained variables, prune domain values that have no valid partner. This propagates constraints without full search.
- Solvers use backtracking search with constraint propagation, variable ordering heuristics (most-constrained-first), and value ordering heuristics (least-constraining-first).

**Strengths for our context:**
- Governance axioms ARE constraints: "don't trigger sample playback during TTS output" is a constraint between actuation variables.
- Constraint propagation can efficiently determine which actions are compatible before committing.

**Weaknesses:**
- CSP solving is batch-oriented — you define the problem and solve it. Not designed for continuous, real-time constraint evaluation.
- NP-hard in general. Our constraints are simple enough that we don't need a general solver.

**Key insight worth stealing:** Arc consistency as a lightweight pre-filter. Before actuation, propagate known constraints to eliminate invalid combinations without full search. "If TTS is active, remove sample-playback from the available actions" is arc consistency.

### 3.6 Policy Composition (OPA/Cedar)

**Core abstraction:** Policies as declarative rules evaluated against a request context, producing allow/deny decisions.

**How policies compose:**
- **OPA (Open Policy Agent)**: policies in Rego (Datalog derivative). Multiple rules can contribute to a decision. Virtual documents aggregate sub-decisions. Rules are evaluated against a JSON input document. Policies compose by reference — one policy can refer to another's output.
- **Cedar**: each policy is evaluated independently against the request. Default deny. Any explicit deny overrides any allow. This is a simple but powerful composition model: deny wins.

**Strengths for our context:**
- Cedar's "deny wins" model maps directly to governance axioms as vetoes. Any axiom violation vetoes the actuation.
- OPA's virtual documents could aggregate perception state into a decision context.
- Declarative — policies don't specify execution order.

**Weaknesses:**
- Designed for authorization (binary allow/deny), not graduated actuation decisions.
- No temporal dimension — policies are evaluated at a point in time, not over a window.

**Key insight worth stealing:** Cedar's "explicit deny overrides any allow" composition model. Governance axioms are deny rules. If any axiom says "no," the actuation is vetoed regardless of how many other signals say "yes." This is simple, safe, and composable.

---

## 4. Actuation Interfaces

How do systems generalize "do something in the world"?

### 4.1 Actor Model (Erlang, Akka)

**Core abstraction:** **Actors** — lightweight concurrent entities that communicate exclusively via asynchronous message passing. Each actor has a mailbox, processes one message at a time, and can create child actors.

**Communication patterns:**
- **Fire-and-forget** (`tell` / `cast`): send a message and move on. No response expected.
- **Request-response** (`ask` / `call`): send a message and await a reply, with a timeout.
- **Supervision**: each actor supervises its children. When a child fails, the parent's supervision strategy decides: restart, stop, escalate, or resume. This creates a hierarchy of fault tolerance.

**Erlang/Elixir specifics:** GenServer provides `call` (synchronous request-response with timeout), `cast` (async fire-and-forget), and `info` (handling arbitrary messages). Process isolation means one actor's crash doesn't affect others.

**Akka specifics:** Typed actors with `ActorRef[MessageType]` ensure type-safe messaging. `Behaviors` define how an actor responds to messages and can change behavior over time (`Behaviors.same`, `Behaviors.stopped`, or a new behavior function).

**Strengths for our context:**
- Each actuator (MIDI output, TTS engine, OBS controller) is naturally an actor with its own mailbox and processing rate.
- Fire-and-forget is appropriate for "play sample" commands; request-response for "is TTS currently speaking?"
- Supervision handles actuator failures gracefully — restart the OBS controller without affecting MIDI output.

**Weaknesses:**
- Pure message passing adds latency (mailbox queuing) that may matter for sub-millisecond MIDI timing.
- No built-in concept of message priority — all messages queue equally.
- Actors are opaque — you can't inspect their state without asking them.

**Key insight worth stealing:** The supervision hierarchy for actuator fault tolerance, and the `tell`/`ask` distinction for actuation commands. "Play this sample" is a `tell` (fire-and-forget with timing); "what's your current state?" is an `ask` (request-response for status).

### 4.2 Command Pattern

**Core abstraction:** Encapsulate an action request as an object with an `execute()` method. The command carries all information needed to perform the action.

**Key capabilities:**
- **Queuing**: commands are data, so they can be enqueued, persisted, or retried.
- **Undo/Redo**: each command implements `undo()` with the minimal state needed to reverse the action. A command history with a "current" pointer enables multi-level undo.
- **Decoupling**: the invoker (who decides to act) doesn't know the receiver (who performs the action). Commands mediate between them.
- **Replay**: recording and replaying command sequences reproduces behavior without storing full state.

**Game programming application (Nystrom):** Commands decouple input from action, enabling configurable button mapping. The same command infrastructure drives player input, AI decisions, and demo replay. Commands accept the actor as a parameter: `execute(actor)`, making them reusable across different targets.

**Strengths for our context:**
- Actuation commands as objects enables logging, replay, and debugging. "What commands were issued in the last 5 seconds?" is a simple query.
- Undo is relevant for state-modifying actuations (OBS scene changes).
- Queuing with priority handles the case where multiple perception signals trigger conflicting actuations.

**Weaknesses:**
- One command per action can lead to class explosion.
- Undo requires careful state management — some actions (playing a sound) aren't truly reversible.

**Key insight worth stealing:** Commands as serializable, queueable, loggable action objects. Every actuation is a command object with a timestamp, priority, source signal, and execute method. This creates an audit trail and enables governance review.

### 4.3 Effect Systems (Algebraic Effects)

**Core abstraction:** Side effects are represented as **values** (effect descriptions) that are interpreted by **handlers**. Code `perform`s an effect; a handler catches it and can `resume` execution with a value.

**How it works:**
- Unlike exceptions, algebraic effects are **resumable**. When code performs an effect, the handler receives the continuation and can decide when/how to resume it.
- **Composability**: handlers can nest, with different handlers at different stack depths managing different effects. Code performing effects is agnostic to how they're handled.
- **Function coloring solved**: intermediate functions don't need to be marked async/effectful. The handler decides execution strategy, not the performing code.
- **Implementations**: Koka (first-class effects in the type system), OCaml 5.0+ (untyped effect handlers), Haskell (via libraries like `polysemy`, `effectful`, using GADTs and free monads).

**Haskell's approach:** "Evaluate your program to build an abstract syntax tree of side effects, then the runtime executes the tree by interpreting it." This two-phase model (describe effects, then interpret) is the key insight.

**Strengths for our context:**
- "Describe effects, then interpret" cleanly separates actuation decisions from actuation execution. The governance layer can inspect, modify, or veto effect descriptions before they execute.
- Handlers at different levels can add governance wrapping: a base handler sends MIDI, a governance handler wraps it with timing constraints.
- Effect composition without function coloring means perception processors don't need to know about actuation mechanics.

**Weaknesses:**
- Algebraic effects are a PL-theory concept with limited practical implementations. Python doesn't have them natively.
- The overhead of building and interpreting effect trees may matter for sub-millisecond timing.
- Steep learning curve.

**Key insight worth stealing:** The two-phase model: describe effects as data, then interpret them. Actuation decisions are effect descriptions (data objects) that pass through a governance interpreter before reaching the actual actuator. This is essentially the Command pattern elevated to a first-class language feature, but the principle applies regardless of language support.

### 4.4 ROS Actions/Services

**Core abstraction:** Three communication patterns with typed interfaces:
- **Topics** (pub/sub): fire-and-forget, many-to-many.
- **Services** (request/response): synchronous, one-to-one.
- **Actions** (goal/feedback/result): long-running operations with progress feedback and cancellation.

**Actions in detail:** A client sends a goal. The server accepts/rejects it, then sends periodic feedback updates. The client can cancel. When complete, the server sends a result. This models operations like "navigate to position X" that take time and can report progress.

**Strengths for our context:**
- The Action pattern (goal + feedback + result + cancel) maps to long-running actuations like TTS synthesis. Send a "speak this text" goal, receive progress feedback, get a result when done, cancel if interrupted.
- Typed interfaces enforce contracts between perception and actuation.

**Key insight worth stealing:** The three-tier communication model: fire-and-forget for fast actuation (MIDI), request-response for state queries, and goal-feedback-result for long-running operations (TTS, scene transitions).

### 4.5 MIDI Output

**Core abstraction:** A stream of timestamped messages on channels, with real-time priority messages that can interrupt.

**Relevant patterns:**
- **Running status**: after a status byte, subsequent messages on the same channel/type can omit the status byte, reducing bandwidth.
- **Active sensing**: optional heartbeat (every 300ms max) to detect disconnection.
- **Real-time messages** (clock, start, stop, continue) have priority over other messages — they can be inserted between bytes of a longer message.
- **Jitter**: MIDI hardware has ~1ms resolution. Software sequencers pre-schedule events ahead of time to hit precise timing.

**Key insight worth stealing:** Pre-scheduling with jitter compensation. Don't wait until the exact moment to send an actuation command — schedule it ahead of time and let the output layer handle precise timing. This is the same principle as Sonic Pi's virtual time.

---

## 5. Event Routing / Subscription

How do systems route events between heterogeneous producers and consumers?

### 5.1 Pub/Sub Systems

**MQTT:**
- Broker-mediated pub/sub with hierarchical topic names (e.g., `sensors/temperature/room1`).
- Three QoS levels: 0 (at most once), 1 (at least once), 2 (exactly once).
- **Retained messages**: the broker stores the last message on each topic, delivering it immediately to new subscribers. This means subscribers always get the current state, even if they join late.
- **Last Will and Testament (LWT)**: a message automatically published if a client disconnects unexpectedly.
- Lightweight protocol designed for constrained devices and unreliable networks.

**ZeroMQ:**
- **Brokerless** — "zero broker." Peers connect directly.
- Multiple socket patterns: PUB/SUB, REQ/REP, PUSH/PULL, DEALER/ROUTER, RADIO/DISH.
- PUB/SUB uses topic prefix matching (publisher includes topic in first message frame).
- Supports TCP, IPC (Unix sockets), inproc (in-process), PGM (multicast).
- **No persistence, no delivery guarantees** by default. You build reliability on top.
- Very low latency due to zero-copy message passing and no broker hop.

**Redis Streams:**
- Append-only log with auto-generated IDs (timestamp + sequence number).
- `XADD` appends entries; `XREAD` reads from a position; `XREADGROUP` distributes entries across a consumer group.
- **Consumer groups**: each message delivered to exactly one consumer in the group. Pending Entries List (PEL) tracks unacknowledged messages.
- Messages persist until explicitly trimmed — natural event store.
- Each entry has field-value pairs — structured data, not just bytes.

**Strengths for our context:**
- MQTT's retained messages solve the "late joiner" problem — a new consumer immediately gets the latest state of each signal.
- ZeroMQ's inproc transport gives near-zero-latency in-process pub/sub — ideal for single-machine, multi-cadence routing.
- Redis Streams' auto-timestamped append-only log is a natural fit for event sourcing perception data.

**Weaknesses:**
- MQTT's broker is a single point of failure and adds latency.
- ZeroMQ requires careful socket management and doesn't handle backpressure natively.
- Redis Streams adds a network hop even for local communication.

**Key insight worth stealing:** ZeroMQ's inproc transport for zero-copy in-process pub/sub, and MQTT's retained messages for "always know the latest value" semantics. Combine: an in-process pub/sub where each topic retains the latest value, so any consumer can get current state without waiting for the next publication.

### 5.2 Event Sourcing / CQRS

**Core abstraction:** All state changes are recorded as an **append-only log of events**. Current state is derived by replaying the log. CQRS separates the write model (event log) from the read model (materialized views optimized for queries).

**How it handles event routing:**
- **Event store**: the single source of truth. Events are immutable and ordered.
- **Projections/Materialized views**: event handlers consume the log and build query-optimized read models. Multiple views can be built from the same events for different access patterns.
- **Eventual consistency**: read models lag behind the event store. For real-time systems, this lag must be bounded.
- **Replay**: you can rebuild any read model by replaying the event log from the beginning.

**Strengths for our context:**
- Perception events as an append-only log enables debugging, replay, and auditing. "What did the system perceive in the last 10 seconds?" is a simple log query.
- Multiple materialized views: one view for governance (latest state of all constraints), one for actuation (next action to take), one for monitoring (dashboard).
- Temporal queries are natural: the log IS the time-series.

**Weaknesses:**
- Eventual consistency is a problem for real-time actuation. The materialized view must be updated synchronously or near-synchronously.
- Log growth requires pruning/compaction for long-running systems.
- Complexity of managing multiple projections.

**Key insight worth stealing:** The separation of event capture (append-only log) from state derivation (materialized views). Perception signals are appended to a log. Each consumer (governance, actuation, monitoring) maintains its own materialized view optimized for its access pattern. The log is the shared truth; views are derived and disposable.

### 5.3 Observable Pattern (ReactiveX, Signals/Slots)

**Core abstraction:** An **Observable** emits items over time. **Observers** subscribe and receive items via `onNext`, `onError`, and `onCompleted` callbacks.

**Key combining operators:**
- `merge`: interleave emissions from multiple Observables.
- `combineLatest`: when any Observable emits, combine with latest from all others.
- `zip`: pair emissions 1:1 from multiple Observables (waits for all).
- `withLatestFrom`: when the primary Observable emits, sample the latest from secondaries.
- `switch`: subscribe to the most recent inner Observable, unsubscribing from previous.

**Hot vs Cold:**
- **Cold**: starts emitting only on subscribe; each subscriber gets the full sequence.
- **Hot**: emits regardless of subscribers; late joiners miss earlier items.
- **Connectable**: hot Observable that doesn't start until `connect()` is called.

**Signals/Slots (Qt):** Compile-time type-safe connections. A signal emission calls all connected slots. Connections can be direct (same thread, synchronous), queued (cross-thread, via event loop), or auto (runtime selection).

**Strengths for our context:**
- `combineLatest` and `withLatestFrom` are the exact operators for multi-cadence fusion.
- Hot Observables model continuous perception signals; Cold model on-demand queries.
- Operator chains are declarative and composable.

**Weaknesses:**
- Observable chains can become hard to debug (long operator chains, backpressure issues).
- No built-in governance — any operator can transform or filter signals.
- Cold/Hot distinction is easy to get wrong, leading to subtle bugs.

**Key insight worth stealing:** `withLatestFrom` as the canonical multi-cadence fusion operator. When the fast signal (MIDI clock) emits, sample the latest value from all slow signals (emotion, environment) and produce a fused decision context.

### 5.4 CSP (Communicating Sequential Processes)

**Core abstraction:** Independent sequential processes communicate by sending/receiving values on **channels**. Channels are typed, first-class values that can be passed around.

**How it handles routing:**
- **Unbuffered channels** (rendezvous): sender blocks until receiver is ready and vice versa. This provides natural synchronization.
- **Buffered channels**: sender can push up to N items without blocking. After that, sender blocks.
- **Select/alt**: wait on multiple channels simultaneously, proceeding with whichever is ready first. This is the multiplexing primitive.
- **Go channels**: built into the language. Select statement with default case for non-blocking.
- **Clojure core.async**: `go` blocks (lightweight coroutines) + channels. `alt!`/`alts!` for select. Go blocks are converted to state machines internally — no OS threads consumed.

**Strengths for our context:**
- Select/alt is a natural primitive for "wait for the next event from any signal source."
- Buffered channels provide natural backpressure without explicit flow control.
- Channels as values can be passed to dynamically configure routing.

**Weaknesses:**
- CSP is process-oriented, not data-flow-oriented. You think in terms of "processes that communicate" rather than "streams that transform."
- Select doesn't support priority — all channels are equally weighted. (Some implementations add priority select as an extension.)
- Channel-based designs can deadlock if processes form circular dependencies.

**Key insight worth stealing:** The `select` statement as a multi-source event multiplexer, and buffered channels as a natural backpressure mechanism. A central perception multiplexer selects across all signal channels, processing whichever is ready first, with buffer sizes tuned per-signal to absorb cadence differences.

---

## Synthesis: Cross-Cutting Patterns

Several patterns recur across domains:

### Pattern 1: Continuous State vs Discrete Events
FRP (Behavior/Event), TidalCycles (Analog/Digital), DSP (control-rate/audio-rate), Pure Data (cold/hot inlets) all distinguish between continuously-available state and discrete occurrences. This is the foundational abstraction for multi-cadence systems.

### Pattern 2: Sample-on-Demand Fusion
`withLatestFrom` (ReactiveX), hot/cold inlets (Pure Data), `combineLatest` (ReactiveX), behaviors sampled at event time (FRP) all solve the same problem: when a fast event arrives, combine it with the current value of slow-changing state. This is the key multi-cadence composition primitive.

### Pattern 3: Describe-Then-Interpret
Algebraic effects (perform/handle), Command pattern (create/execute), event sourcing (record/project), Faust (build graph/compile) all separate the description of an action from its execution. This creates a governance interception point.

### Pattern 4: Accumulator / Watermark for Freshness
Game engine accumulators, Flink watermarks, ROS message timeouts all track "how current is this information?" as a first-class concern. For multi-cadence systems, each signal needs a freshness indicator.

### Pattern 5: Priority with Fallback
Behavior tree selectors, subsumption suppression, Cedar deny-wins, rule engine salience all implement "try the highest-priority option, fall back to lower priorities." This is the governance composition model.

### Pattern 6: Clock Separation
MIDI clock vs transport, Sonic Pi virtual time vs wall clock, game engine physics time vs render time, Flink event time vs processing time all maintain multiple time references. The system needs at least two clocks: a reference clock for coordination and per-signal domain clocks for native timing.

---

## Recommended Primitives for Our System

Based on this survey, the following general-purpose primitives emerge:

1. **SignalSlot**: A typed value container that is either `Continuous` (always has a current value, with timestamp) or `Discrete` (emits events). This is the Behavior/Event distinction from FRP, implemented as a concrete data structure.

2. **WithLatestFrom combinator**: When a discrete signal fires, sample all continuous signals and produce a fused context. This is the multi-cadence fusion operator.

3. **TimelineMapping**: A bidirectional mapping `(reference_time, domain_time, rate)` for converting between wall clock and any signal's native time domain. Stolen from Ableton Link's timeline triple.

4. **FreshnessWatermark**: Per-signal staleness tracking. Each signal carries a watermark indicating "last valid reading at time T." Actuation can check freshness before using stale perception data.

5. **CommandObject**: Every actuation is a serializable command with timestamp, priority, source signal, and execute method. Commands pass through governance before execution. Stolen from Command pattern + algebraic effects' describe-then-interpret.

6. **GovernanceVeto**: Cedar-style deny-wins composition. Governance axioms are evaluated as constraints. Any deny overrides all allows. Constraints are checked against the fused perception context before command execution.

7. **SuppressionWithTimeout**: Subsumption-style override where a higher-priority behavior can suppress a lower-priority one for a bounded duration, reverting automatically. Prevents permanent accidental state changes.

8. **RetainedPubSub**: In-process pub/sub where each topic retains the latest value (MQTT retained semantics) with ZeroMQ inproc-style zero-copy transport. Late joiners immediately get current state.

---

## Sources

### Signal Stream Abstractions
- [FRP Wikipedia](https://en.wikipedia.org/wiki/Functional_reactive_programming)
- [Yampa on GitHub](https://github.com/ivanperez-keera/Yampa)
- [FRP on HaskellWiki](https://wiki.haskell.org/Functional_Reactive_Programming)
- [ReactiveX Observable](https://reactivex.io/documentation/observable.html)
- [ReactiveX Operators](https://reactivex.io/documentation/operators.html)
- [RxJava Backpressure](https://github.com/ReactiveX/RxJava/wiki/Backpressure)
- [Faust Programming Language](https://faust.grame.fr/)
- [Audio Signal Processing in Faust (Stanford CCRMA)](https://ccrma.stanford.edu/~jos/aspf/)
- [Faust Optimizing Documentation](https://faustdoc.grame.fr/manual/optimizing/)
- [SuperCollider UGen Documentation](https://doc.sccode.org/Classes/UGen.html)
- [SuperCollider SynthDef Documentation](https://doc.sccode.org/Classes/SynthDef.html)
- [Pure Data Wikipedia](https://en.wikipedia.org/wiki/Pure_Data)
- [ROS2 QoS Settings](https://docs.ros.org/en/rolling/Concepts/Intermediate/About-Quality-of-Service-Settings.html)
- [ROS2 tf2 MessageFilter](https://docs.ros2.org/foxy/api/tf2_ros/classtf2__ros_1_1MessageFilter.html)
- [Apache Flink Timely Stream Processing](https://nightlies.apache.org/flink/flink-docs-release-2.1/docs/concepts/time/)
- [Akka Streams Basics](https://doc.akka.io/docs/akka/current/stream/stream-flows-and-basics.html)

### Temporal Reference Frames
- [Ableton Link Documentation](https://ableton.github.io/link/)
- [Ableton Link on GitHub](https://github.com/Ableton/link)
- [Ableton Link MIDI.org Article](https://midi.org/ableton-link-a-technology-for-synchronization-that-expands-on-midi-timing)
- [TidalCycles: What is a Pattern?](https://tidalcycles.org/docs/innards/what_is_a_pattern/)
- [TidalCycles Time Reference](https://tidalcycles.org/docs/reference/time/)
- [Sonic Pi Temporal Semantics (Aaron & Orchard, FARM 2014)](https://www.doc.ic.ac.uk/~dorchard/publ/farm14-sonicpi.pdf)
- [Sonic Pi Thread Synchronisation](https://github.com/sonic-pi-net/sonic-pi/blob/dev/etc/doc/tutorial/05.7-Thread-Synchronisation.md)
- [Fix Your Timestep! (Gaffer on Games)](https://gafferongames.com/post/fix_your_timestep/)
- [Unity Fixed Timestep Documentation](https://docs.unity3d.com/6000.3/Documentation/Manual/physics-optimization-cpu-frequency.html)
- [Godot _process vs _physics_process](https://forum.godotengine.org/t/delta-time-in-physics-process-vs-process/11360)
- [MIDI Beat Clock Wikipedia](https://en.wikipedia.org/wiki/MIDI_beat_clock)
- [Precision Time Protocol Wikipedia](https://en.wikipedia.org/wiki/Precision_Time_Protocol)

### Governance / Constraint Composition
- [Drools Rule Engine Documentation](https://docs.drools.org/8.38.0.Final/drools-docs/docs-website/drools/rule-engine/index.html)
- [Rete Algorithm Wikipedia](https://en.wikipedia.org/wiki/Rete_algorithm)
- [Forward Chaining Wikipedia](https://en.wikipedia.org/wiki/Forward_chaining)
- [Behavior Trees in Robotics and AI (Survey)](https://arxiv.org/pdf/2005.05842)
- [Behavior Trees Wikipedia](https://en.wikipedia.org/wiki/Behavior_tree_(artificial_intelligence,_robotics_and_control))
- [Introduction to Behavior Trees (Robohub)](https://robohub.org/introduction-to-behavior-trees/)
- [Brooks' Subsumption Architecture (MIT AIM-864)](https://people.csail.mit.edu/brooks/papers/AIM-864.pdf)
- [Subsumption Architecture Wikipedia](https://en.wikipedia.org/wiki/Subsumption_architecture)
- [Blackboard System Wikipedia](https://en.wikipedia.org/wiki/Blackboard_system)
- [Blackboard Design Pattern Wikipedia](https://en.wikipedia.org/wiki/Blackboard_(design_pattern))
- [H. Penny Nii, Blackboard Systems (Stanford 1986)](http://i.stanford.edu/pub/cstr/reports/cs/tr/86/1123/CS-TR-86-1123.pdf)
- [CSP Wikipedia](https://en.wikipedia.org/wiki/Constraint_satisfaction_problem)
- [OPA Philosophy](https://www.openpolicyagent.org/docs/philosophy)
- [Cedar Language Paper (arXiv)](https://arxiv.org/pdf/2403.04651)

### Actuation Interfaces
- [Akka Actors Introduction](https://doc.akka.io/libraries/akka-core/current/typed/actors-intro.html)
- [Erlang/Elixir Actor Model (Underjord)](https://underjord.io/unpacking-elixir-the-actor-model.html)
- [Command Pattern (Game Programming Patterns)](https://gameprogrammingpatterns.com/command.html)
- [Command Pattern (Refactoring Guru)](https://refactoring.guru/design-patterns/command)
- [Algebraic Effects for the Rest of Us (Dan Abramov)](https://overreacted.io/algebraic-effects-for-the-rest-of-us/)
- [Algebraic Effects in Haskell](https://www.haskellforall.com/2015/03/algebraic-side-effects.html)
- [OCaml 5 Effects](https://www.janestreet.com/tech-talks/effective-programming/)
- [ROS2 Actions/Services Architecture](https://www.roboticsunveiled.com/ros2-ipc-dds-topics-services-actions-interfaces/)

### Event Routing / Subscription
- [MQTT vs ZeroMQ (HiveMQ)](https://www.hivemq.com/blog/mqtt-vs-zeromq-for-iot/)
- [ZeroMQ Socket Patterns Guide](https://zguide.zeromq.org/docs/chapter2/)
- [Redis Streams Documentation](https://redis.io/docs/latest/develop/data-types/streams/)
- [Event Sourcing Pattern (Microsoft Azure)](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing)
- [Event Sourcing + CQRS (Confluent)](https://www.confluent.io/blog/event-sourcing-cqrs-stream-processing-apache-kafka-whats-connection/)
- [CSP Wikipedia](https://en.wikipedia.org/wiki/Communicating_sequential_processes)
- [Clojure core.async Channels](https://clojure.org/news/2013/06/28/clojure-clore-async-channels)
- [core.async Rationale](https://clojure.github.io/core.async/rationale.html)
