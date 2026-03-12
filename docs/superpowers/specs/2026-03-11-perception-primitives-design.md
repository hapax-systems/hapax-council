# Perception Primitive Type System — Design Spec

> **Status:** Proposed
> **Date:** 2026-03-11
> **Scope:** `agents/hapax_voice/`, `shared/` — foundational type system for multi-cadence perception-to-actuation
> **Builds on:** [Perception Layer Design](2026-03-10-perception-layer-design.md), [Backup MC North Star](2026-03-11-backup-mc-north-star-design.md), [Prior Art Survey](../research/2026-03-11-prior-art-survey.md), [Inside-Out Analysis](../research/2026-03-11-inside-out-analysis.md), [Comparative Evaluation](../research/2026-03-11-comparative-evaluation.md)

## Problem

The perception layer works for its current single use case (voice daemon pipeline governance) but its abstractions are ad hoc. Adding new signals, new time domains, new consumers, or new actuation targets requires modifying internals throughout the stack. The north star use case (backup MC) requires sub-50ms beat-aligned actuation driven by signals at 5+ different cadences — a regime where ad hoc wiring cannot deliver the required timing properties and where correctness must arise from the structure of the system, not from careful implementation.

The prior art research identified 6 cross-cutting patterns and 8 candidate primitives. The inside-out analysis extracted 9 implicit patterns from existing code. The comparative evaluation found 3 critical gaps and 2 important gaps. This spec formalizes those findings into a coherent primitive type system whose structural properties necessarily produce the required non-functional behaviors.

## Goal

Define a classification system of typed primitives — **Perceptives**, **Detectives**, and **Directives** — whose formal properties guarantee:

- **Timing independence:** A fast signal's response time is never limited by a slow signal's update rate
- **Compositional safety:** Adding governance constraints can only make the system more restrictive, never less
- **Temporal integrity:** Every decision carries provable freshness bounds on the perception data that informed it
- **Scheduling precision:** Beat-aligned actuation resolves to exact wall-clock timestamps via bijective mappings

These are not aspirational properties to be tested for after implementation. They are structural consequences of the type system — if the types are respected, the properties hold by construction.

---

## Section 1: The Three Primitive Classes

Every primitive in the system belongs to exactly one of three classes, distinguished by their role in the perception-to-actuation pipeline and by the formal structures that govern their composition.

### 1.1 Perceptives — "What is the state of the world?"

Perceptives model the world. They are the typed containers for sensory data, temporal references, and environmental state. A Perceptive's value is always well-defined — you can query it at any instant and receive an answer.

There are four Perceptive primitives:

| Primitive | Formal basis | Role |
|-----------|-------------|------|
| `Behavior[T]` | FRP continuous signal (Elliott) | A value that exists at every point in time |
| `Event[T]` | FRP discrete signal (Elliott) | An occurrence at a specific instant |
| `Watermark` | Stream processing completeness (Flink/VLDB) | Monotonic freshness bound on a signal |
| `TimelineMapping` | Affine bijection (Ableton Link) | Bidirectional conversion between time domains |

### 1.2 Detectives — "What does this mean?"

Detectives evaluate state and produce judgments. They consume Perceptives, apply rules, and emit structured decisions. A Detective never directly causes action — it produces a verdict that a Directive can carry to an actuator.

There are four Detective primitives:

| Primitive | Formal basis | Role |
|-----------|-------------|------|
| `Combinator` | `withLatestFrom` (ReactiveX/FRP) | Fuses an Event with current Behavior values |
| `VetoChain` | Deny-wins semilattice (Cedar) | Order-independent safety constraints |
| `FallbackChain` | Priority-ordered selection (behavior trees) | Ordered action preference |
| `FreshnessGuard` | Bounded staleness (watermark comparison) | Rejects decisions based on stale data |

### 1.3 Directives — "What should we do?"

Directives prescribe action. They are data objects that describe an intended effect, carrying the full provenance of the perception data and governance decisions that produced them. A Directive is inert — it does nothing until an interpreter executes it. This gap between description and execution is where governance lives.

There are two Directive primitives:

| Primitive | Formal basis | Role |
|-----------|-------------|------|
| `Command` | Free monad / Command pattern | Serializable, inspectable action description |
| `Schedule` | Pre-scheduled actuation (Sonic Pi virtual time, MIDI sequencer) | Time-domain-stamped command for future execution |

---

## Section 2: Perceptive Primitives

### 2.1 Behavior[T]

**Denotational semantics:** A `Behavior[T]` is a total function from time to values: `Time → T`. It has a value at every point in time. Sampling it never fails, never returns "not yet available," never blocks.

```python
@dataclass
class Behavior(Generic[T]):
    """A continuously-available value with freshness tracking."""
    _value: T
    _watermark: float  # monotonic timestamp of last real measurement

    def sample(self) -> Stamped[T]:
        """Always succeeds. Returns current value and its freshness."""
        return Stamped(value=self._value, watermark=self._watermark)

    def update(self, value: T, timestamp: float) -> None:
        """Update from a signal source. Watermark must advance monotonically."""
        assert timestamp >= self._watermark, "Watermarks must not regress"
        self._value = value
        self._watermark = timestamp
```

**Key type-level properties:**

1. **Totality.** `sample()` always returns a value. No `None`, no `Optional`, no waiting. This eliminates the entire class of "signal not yet initialized" bugs. The constructor requires an initial value — the Behavior exists fully-formed from creation.

2. **Freshness annotation.** Every sampled value carries a `Watermark` — the timestamp of the last real measurement that produced this value. A value carried forward from a slow tick 10 seconds ago is distinguishable from one measured 50ms ago. The watermark is metadata, not the value itself — it doesn't change what the value *is*, only how *current* it is.

3. **Monotonic watermarks.** The watermark can only advance. If a signal source produces a reading at time T, the watermark moves to T and never retreats. This prevents "time going backward" bugs where stale data masquerades as fresh. The monotonicity invariant is enforced at the `update()` boundary.

**What this replaces in the current code:** PerceptionEngine's `_slow_*` fields (carried-forward ambient classification, activity mode, workspace context) and fast-tick readings (VAD, face count, gaze) are all Behaviors. The difference: currently they're untyped fields on a frozen dataclass with no freshness tracking. As Behaviors, each carries its own watermark and each is independently sampleable.

### 2.2 Event[T]

**Denotational semantics:** An `Event[T]` is an ordered sequence of time-value pairs: `[(Time, T)]`. It has values only at specific instants. Between instants, it does not exist. You cannot "sample" an Event — you can only subscribe to be notified when it fires.

```python
@dataclass
class Event(Generic[T]):
    """A discrete occurrence at a specific instant."""
    _subscribers: list[Callable[[float, T], None]]

    def subscribe(self, callback: Callable[[float, T], None]) -> None:
        """Register to be called when this event fires."""
        self._subscribers.append(callback)

    def emit(self, timestamp: float, value: T) -> None:
        """Fire the event. All subscribers are called with the timestamp and value."""
        for sub in self._subscribers:
            sub(timestamp, value)
```

**Key type-level properties:**

1. **Partiality.** An Event has no "current value." Asking "what is the current wake word?" is a type error — you can subscribe to wake word Events, but you can't sample them. This prevents the bug of treating a past Event occurrence as ongoing state.

2. **Instantaneity.** Each occurrence has an exact timestamp. An Event at time T exists at T and nowhere else. This is what makes Events suitable as timing drivers — they fire at precise instants.

3. **No retention by default.** Once an Event fires and subscribers are notified, the occurrence is consumed. Late subscribers don't receive past Events. This is the correct default for triggers (MIDI note-on, wake word) where only the current firing matters.

**What this replaces in the current code:** Wake word activations, Hyprland focus-change callbacks, MIDI clock ticks, transport start/stop — all currently handled via ad hoc callback wiring on the VoiceDaemon. As Events, they have a uniform subscription interface and explicit timestamps.

### 2.3 The Behavior/Event distinction

This is the foundational type decision. It is not a modeling preference — it is a statement about the **temporal nature** of each signal:

| Signal | Type | Rationale |
|--------|------|-----------|
| VAD confidence | `Behavior[float]` | Always has a value (0.0 when silent) |
| Face count | `Behavior[int]` | Always has a value (0 when no faces) |
| Activity mode | `Behavior[ActivityMode]` | Always classifiable (may be stale) |
| Ambient class | `Behavior[str]` | Always classifiable |
| Operator present | `Behavior[bool]` | Always determinable |
| Desktop state | `Behavior[WindowInfo]` | Always has a current window (or None as a valid state) |
| Emotion reading | `Behavior[EmotionVector]` | Continuous dimensions, always sampleable |
| Audio energy | `Behavior[float]` | Continuous, always measurable |
| Energy arc phase | `Behavior[ArcPhase]` | Always in some phase |
| Wake word | `Event[None]` | Happens at an instant, no "current" value |
| MIDI note on | `Event[MidiNote]` | Discrete trigger |
| MIDI clock tick | `Event[int]` | Discrete timing pulse (24 PPQN) |
| Transport start/stop | `Event[TransportState]` | Discrete state change |
| Hyprland focus change | `Event[FocusEvent]` | Discrete window switch |
| Audio onset | `Event[float]` | Discrete energy spike |

The type assignment is determined by nature, not by update frequency. Audio energy updates at 50ms but is a Behavior (it always has a current value). MIDI clock ticks at sub-ms but is an Event (it happens at instants). The distinction is semantic, not temporal.

### 2.4 Watermark

**Formal definition:** A Watermark is a monotonically non-decreasing timestamp bound on a signal, asserting: "all real-world measurements up to this time have been incorporated into the current value."

Watermarks are not a separate primitive in the implementation — they are embedded in Behaviors (as shown in 2.1). But the concept deserves formal treatment because watermark propagation through fusion is where temporal integrity is maintained.

**Propagation rules:**

When multiple Behaviors are fused into a combined result (via a Combinator, Section 3.1), the fused result's watermark is the **minimum** of the input watermarks:

```
watermark(fuse(B₁, B₂, ..., Bₙ)) = min(watermark(B₁), watermark(B₂), ..., watermark(Bₙ))
```

This follows from the definition: the fused result is only as fresh as its stalest input. If the emotion reading is 8s old and the VAD is 50ms old, any decision that used both is at least 8s stale with respect to emotion.

**Perfect vs heuristic watermarks:** In stream processing (Flink), watermarks can be "perfect" (guaranteed complete) or "heuristic" (best-effort). For the perception layer, all watermarks are heuristic — sensor readings arrive when they arrive, and we can't guarantee that a slow classifier won't produce a retroactively better reading. The monotonicity invariant ensures we never claim more freshness than we've earned, but we accept that the true state of the world may have changed between the watermark time and now. This is the fundamental completeness-latency tradeoff: acting on 100ms-stale data gives 100ms latency; waiting for fresh data adds the classifier's processing time.

### 2.5 TimelineMapping

**Formal definition:** A TimelineMapping is a bijective affine transformation between two time domains.

For constant tempo:

```
beat(t) = (t − t_ref) × (tempo / 60)
time(b) = t_ref + b × (60 / tempo)
```

Where `(t_ref, b_ref, tempo)` is the defining triple, following Ableton Link's model. The bijection guarantees: every wall-clock time maps to exactly one beat position, and every beat position maps to exactly one wall-clock time. No ambiguity, no approximation.

```python
@dataclass(frozen=True)
class TimelineMapping:
    """Bijective affine map between wall-clock and beat time."""
    reference_time: float    # wall-clock anchor point
    reference_beat: float    # beat value at anchor point
    tempo: float             # beats per minute
    transport: TransportState  # playing | stopped

    def beat_at_time(self, t: float) -> float:
        """Wall-clock → beat. Bijective when transport is playing."""
        if self.transport == TransportState.STOPPED:
            return self.reference_beat
        return self.reference_beat + (t - self.reference_time) * (self.tempo / 60.0)

    def time_at_beat(self, b: float) -> float:
        """Beat → wall-clock. Inverse of beat_at_time."""
        if self.transport == TransportState.STOPPED:
            return self.reference_time  # beat doesn't advance; time is frozen at ref
        return self.reference_time + (b - self.reference_beat) * (60.0 / self.tempo)
```

**Key type-level properties:**

1. **Bijectivity.** `beat_at_time(time_at_beat(b)) == b` and `time_at_beat(beat_at_time(t)) == t`, within floating-point precision. This is guaranteed by the affine structure — affine maps are always invertible when the slope (tempo) is non-zero.

2. **Composability.** If you have `wall → beat` and `beat → bar` (where bar = beat / beats_per_bar), you get `wall → bar` by composition. Affine maps compose as affine maps: the composition is still an affine map, still bijective, still O(1) to evaluate.

3. **Piecewise extension for tempo changes.** Tempo changes create a piecewise-affine timeline — a sequence of affine segments joined at change points. Each segment is a TimelineMapping. Beat position lookup becomes binary search over segment boundaries: O(log n) for n tempo changes. The bijection holds within each segment and across segments (the join conditions ensure continuity).

4. **Transport separation.** Following MIDI clock's formal separation of clock from transport: when stopped, the beat position is frozen but time still advances. The mapping exists but is degenerate (constant). This is the product type `(AffineMap, TransportState)` — the map is always defined; the transport determines whether it's active.

**As a Behavior:** The TimelineMapping itself is a `Behavior[TimelineMapping]` — it always has a current value (the current tempo/position mapping). MIDI clock ticks are Events that update this Behavior. The consumer asks the Behavior "what beat are we at?" at any instant and gets an exact answer. The Events that drive updates and the Behavior that holds current state are cleanly separated.

---

## Section 3: Detective Primitives

### 3.1 Combinator (withLatestFrom)

**Formal definition:** A Combinator takes a driving Event and one or more Behaviors, and produces an output Event that fires at exactly the driving Event's times, carrying the current values of all Behaviors at that instant.

```
withLatestFrom : Event[A] × Behavior[B₁] × ... × Behavior[Bₙ] → Event[(A, Stamped[B₁], ..., Stamped[Bₙ])]
```

The output carries `Stamped` values — the Behavior values plus their watermarks. This is watermark propagation in action: the fused result knows how stale each input is.

```python
def with_latest_from(
    trigger: Event[A],
    *behaviors: Behavior,
) -> Event[FusedContext]:
    """When trigger fires, sample all behaviors and emit fused context."""
    result = Event[FusedContext]()

    def on_trigger(timestamp: float, value: A):
        samples = [b.sample() for b in behaviors]
        context = FusedContext(
            trigger_time=timestamp,
            trigger_value=value,
            samples=samples,
            min_watermark=min(s.watermark for s in samples),
        )
        result.emit(timestamp, context)

    trigger.subscribe(on_trigger)
    return result
```

**Key type-level properties:**

1. **Timing preservation.** The output Event fires at the trigger Event's times. If MIDI clock fires at t=1000.000ms and t=1020.833ms, the fused output fires at exactly those times. The Behaviors' update rates are irrelevant to the output timing. This is the property that makes beat-aligned response possible even with slow perception signals.

2. **Causality.** Each sample reflects the Behavior's value at or before the trigger time. No future values are used. This is guaranteed by the sampling order: the trigger fires, *then* Behaviors are sampled. In a single-threaded async system, this ordering is inherent in the call sequence.

3. **Rate independence.** Making a Behavior update faster improves the freshness of its sampled values but does not change when the output fires. Making the trigger faster increases output rate but doesn't affect Behavior update scheduling. These are orthogonal concerns by construction.

4. **Watermark propagation.** The `FusedContext` carries `min_watermark` — the staleness of the least-fresh input. Downstream consumers (governance, scheduling) can check this without knowing which Behavior was stale or why.

**What this replaces in the current code:** PerceptionEngine's periodic tick, which samples everything at 2.5s. Instead: MIDI clock is a trigger Event, perception signals are Behaviors. When MIDI ticks, it samples all perception state. The tick rate is the MIDI clock rate (sub-ms at 120 BPM), not the perception rate. The existing 2.5s fast tick becomes one of several possible triggers, not the only one.

### 3.2 VetoChain

**Formal definition:** A VetoChain is a set of constraint predicates whose combination follows the deny-wins semilattice. Each constraint maps a `FusedContext` to `Allow | Deny`. The chain's result is `Allow` if and only if every constraint returns `Allow`.

This follows Cedar's authorization semantics exactly: (1) if any forbid policy evaluates to true, the result is Deny; (2) else if any permit policy evaluates to true, the result is Allow; (3) otherwise, the result is Deny (default deny). For a VetoChain, we simplify: there are only constraints (forbid policies), and the base case is Allow. Any constraint can veto.

```python
@dataclass
class Veto:
    """A single governance constraint."""
    name: str
    axiom: str | None         # which axiom this enforces, if any
    predicate: Callable[[FusedContext], bool]  # True = allow, False = deny

@dataclass
class VetoChain:
    """Order-independent deny-wins constraint composition."""
    vetoes: list[Veto]

    def evaluate(self, context: FusedContext) -> VetoResult:
        """Evaluate all constraints. Any deny blocks the action."""
        denials: list[str] = []
        for veto in self.vetoes:
            if not veto.predicate(context):
                denials.append(veto.name)
        return VetoResult(
            allowed=len(denials) == 0,
            denied_by=denials,
        )
```

**Algebraic properties (from the semilattice structure):**

1. **Commutativity.** `evaluate(v₁, v₂)` produces the same result as `evaluate(v₂, v₁)`. Evaluation order does not affect the outcome. This is guaranteed because each veto is evaluated independently and the combination is logical AND (all must allow). This means you can add, remove, or reorder vetoes without changing safety properties.

2. **Associativity.** Grouping vetoes into sub-chains and combining results is equivalent to evaluating the flat chain. `VetoChain([a, b, c])` is equivalent to combining `VetoChain([a, b])` with `VetoChain([c])`. This enables modular composition — you can define an "axiom veto chain" and a "performance constraint chain" separately and combine them.

3. **Idempotency.** Adding the same veto twice is harmless: `VetoChain([a, a])` is equivalent to `VetoChain([a])`. This makes it safe to register constraints from multiple sources without deduplication logic.

4. **Monotonic safety.** Adding a veto to the chain can only make the system more restrictive, never less. If a context was denied before adding a veto, it's still denied after. If it was allowed, it may now be denied, but never the reverse. This is the critical property for axiom enforcement: adding a new axiom never opens a previously-closed door.

**What this replaces in the current code:** ContextGate's layered method chain and the safety-constraint portions of Governor's if/elif chain. Both are deny-wins in practice but implemented as ordered sequences that imply ordering matters. The VetoChain makes the order-independence explicit and adds provenance (which veto denied, which axiom it enforces).

### 3.3 FallbackChain

**Formal definition:** A FallbackChain is an ordered sequence of candidate actions, each with an eligibility predicate. The chain selects the first eligible candidate, or a default if none qualify.

This is the behavior tree Selector: try children left-to-right, succeed on first success, fail if all fail.

```python
@dataclass
class Candidate(Generic[T]):
    """A candidate action with its eligibility condition."""
    name: str
    predicate: Callable[[FusedContext], bool]
    action: T

@dataclass
class FallbackChain(Generic[T]):
    """Priority-ordered action selection. First eligible wins."""
    candidates: list[Candidate[T]]
    default: T

    def select(self, context: FusedContext) -> Selected[T]:
        """Select the highest-priority eligible action."""
        for candidate in self.candidates:
            if candidate.predicate(context):
                return Selected(action=candidate.action, selected_by=candidate.name)
        return Selected(action=self.default, selected_by="default")
```

**Key type-level properties:**

1. **Determinism.** Given the same context, the same action is always selected. The chain is evaluated top-to-bottom; the first match wins. No ambiguity.

2. **Non-commutativity.** Order matters. Swapping two candidates may change which fires. This is correct — order encodes preference, and preference is inherently ordered.

3. **Graceful degradation.** The default always exists. The chain never fails to produce an action. Even when no candidate qualifies, the system has a safe fallback. This is the "layers of competence" property from Brooks: removing higher-priority candidates leaves a functional system at lower priority.

**What this replaces in the current code:** Governor's action-selection logic (what directive to issue based on current state). Currently mixed into the same if/elif chain as safety constraints. Separating it into a FallbackChain makes the preference ordering explicit and modifiable.

### 3.4 FreshnessGuard

**Formal definition:** A FreshnessGuard is a predicate on watermarks that gates decisions based on temporal quality. It rejects any FusedContext whose signals are too stale for the decision at hand.

```python
@dataclass
class FreshnessRequirement:
    """Minimum freshness required for a specific signal."""
    behavior_name: str
    max_staleness_s: float

@dataclass
class FreshnessGuard:
    """Rejects decisions made on stale perception data."""
    requirements: list[FreshnessRequirement]

    def check(self, context: FusedContext, now: float) -> FreshnessResult:
        """Check all freshness requirements against watermarks."""
        violations: list[str] = []
        for req in self.requirements:
            sample = context.get_sample(req.behavior_name)
            staleness = now - sample.watermark
            if staleness > req.max_staleness_s:
                violations.append(
                    f"{req.behavior_name}: {staleness:.1f}s stale, max {req.max_staleness_s}s"
                )
        return FreshnessResult(fresh_enough=len(violations) == 0, violations=violations)
```

**Key type-level properties:**

1. **Explicit bounds.** Each signal has a stated maximum staleness. "Energy must be < 100ms stale for sample triggers" is a checkable requirement, not an implicit assumption.

2. **Per-signal granularity.** Different signals can have different freshness requirements. The energy reading for beat-aligned triggers needs 100ms freshness. The emotion reading for mood-based sample selection can tolerate 2s. The activity mode for environment gating can tolerate 15s. These are different requirements for different purposes.

3. **Composability with VetoChain.** A FreshnessGuard can be used as a veto: if any freshness requirement is violated, deny the action. This composes with other vetoes via the semilattice structure — a staleness violation is just another denial, evaluated order-independently alongside axiom constraints.

---

## Section 4: Directive Primitives

### 4.1 Command

**Formal definition:** A Command is a serializable, inspectable data object that describes an intended effect. It carries the full provenance of the perception data and governance decisions that produced it. A Command is inert — it does nothing until an interpreter executes it.

This follows the "describe-then-interpret" pattern identified across algebraic effects, the Command pattern, event sourcing, and Faust's computation graph. The effect is separated from its execution by a data boundary.

```python
@dataclass(frozen=True)
class Command:
    """An inspectable, governable action description."""
    action: str                     # what to do ("play_sample", "speak_tts", "switch_scene")
    params: dict[str, Any]          # action-specific parameters
    trigger_time: float             # when the triggering event occurred
    trigger_source: str             # which event triggered this ("midi_clock", "energy_onset")
    min_watermark: float            # stalest perception data used in this decision
    governance_result: VetoResult   # the governance chain's verdict (for audit)
    selected_by: str                # which FallbackChain candidate produced this
```

**Key type-level properties:**

1. **Inspectability.** Every field is readable data. Governance can inspect `action`, `params`, `min_watermark`, `trigger_source` before deciding whether to allow execution. Logging can record the full decision trail. Replay can re-execute the same commands. This is not optional behavior — the command *is data*, so inspection is structurally free.

2. **Provenance.** The command carries `trigger_source` (which Event), `min_watermark` (how fresh the perception data was), `governance_result` (which vetoes passed/failed), and `selected_by` (which selection rule chose this action). Every command is a complete audit record of the decision that produced it.

3. **Structural governance.** A Command cannot reach an actuator without passing through the interpreter stack. If the interpreter includes governance (VetoChain), then ungoverned actuation is structurally impossible — not by convention, but by the architecture. The command must be constructed with a `governance_result`, and the executor checks it.

4. **Immutability.** Commands are frozen dataclasses. Once created, they cannot be modified. This prevents TOCTOU (time-of-check-time-of-use) bugs where a command passes governance then is modified before execution.

### 4.2 Schedule

**Formal definition:** A Schedule is a Command bound to a specific time in a specific time domain. It bridges the gap between "decide what to do" (Detective output) and "do it at the right moment" (actuator input).

```python
@dataclass(frozen=True)
class Schedule:
    """A command bound to a specific time in a specific domain."""
    command: Command
    domain: str                   # "wall", "beat", "audio_sample"
    target_time: float            # the time in the specified domain
    wall_time: float              # resolved wall-clock time (from TimelineMapping)
    tolerance_ms: float           # acceptable jitter window
```

**Key type-level properties:**

1. **Domain-stamped.** The Schedule specifies *which* time domain the target time is in. "Beat 4.0" is different from "wall-clock 1000.0ms," and the Schedule makes this explicit. The `wall_time` field is the resolved wall-clock time computed via TimelineMapping — the bijection guarantees this resolution is unambiguous.

2. **Pre-scheduled.** Following Sonic Pi's virtual time and MIDI sequencer patterns: don't wait until the exact moment to act. Schedule the command ahead of time and let the output layer handle precise timing. This decouples decision latency (how long it takes to decide) from actuation precision (how accurately the effect is timed).

3. **Tolerance-bounded.** The `tolerance_ms` field states the acceptable jitter window. A sample trigger at beat 4.0 with 20ms tolerance must fire within ±20ms of the resolved wall-clock time. A TTS synthesis with 500ms tolerance can be released anywhere within a half-second window. This makes the precision requirement explicit and checkable.

---

## Section 5: Composition Model

### 5.1 The Perception-to-Actuation Pipeline

The three primitive classes compose into a pipeline where each stage has a defined type boundary:

```
Perceptives          Detectives              Directives
───────────          ──────────              ──────────
Behavior[T]  ─┐
Behavior[U]  ─┤     Combinator
Behavior[V]  ─┤    (withLatestFrom)     ┌─→ Command
              │         │               │
Event[A] ─────┘         ▼               │
                   FusedContext          │
                        │               │
                   FreshnessGuard ──────┤
                        │               │
                   VetoChain ───────────┤
                        │               │
                   FallbackChain ───────┘
                        │
                        ▼
                    Schedule
                        │
                   ┌────┴────┐
                   │Actuator │
                   └─────────┘
```

Type boundaries enforce the pipeline structure:

- **Perceptive → Detective:** The Combinator *requires* typed Behaviors and Events as input. You cannot pass a raw float — it must be wrapped in a Behavior with a watermark. The types enforce freshness tracking.
- **Detective → Directive:** The VetoChain produces a VetoResult. The FallbackChain produces a Selected action. These are composed into a Command, which carries both. You cannot construct a Command without a governance result — the types enforce governance.
- **Directive → Actuator:** The Schedule carries a resolved wall-clock time from TimelineMapping. The actuator receives a fully-resolved, governance-checked, freshness-verified, time-domain-stamped instruction. The types enforce completeness.

### 5.2 The Hot/Cold Pattern Made Explicit

The Behavior/Event distinction formalizes the hot/cold pattern identified in the comparative evaluation:

- **Cold signals** are Behaviors. They update at their own rate, silently. No downstream computation fires on update. Emotion readings, activity mode, ambient classification, face detection, desktop state — all update independently and retain their latest value.

- **Hot signals** are Events. They fire and trigger downstream computation via the Combinator. MIDI clock ticks, audio energy onset crossings, wake word activations, manual triggers — all cause immediate fusion and decision-making.

When a hot signal fires, the Combinator samples all relevant cold signals and produces a fused context. This is `withLatestFrom` from ReactiveX, hot/cold from Pure Data, Behavior-sampled-at-Event from Elliott's FRP — the same pattern, formalized as a typed composition.

The current dual-cadence tick (fast 2.5s, slow 12s) maps to: slow-tick outputs are Behaviors updated at ~12s; the fast tick is an Event that fires at ~2.5s and samples them. But crucially, the fast tick is no longer the *only* trigger. MIDI clock can be another Event that triggers fusion at sub-ms cadence — using the same Behaviors, the same Combinator, the same governance, the same command structure.

### 5.3 Multiple Trigger Domains

Different Events can trigger different Combinators with different Behavior sets and different governance chains:

| Trigger Event | Behaviors sampled | Governance | Output |
|--------------|-------------------|------------|--------|
| Perception tick (2.5s) | All environment signals | PipelineGovernor vetoes | Pipeline directive (process/pause/withdraw) |
| MIDI clock (sub-ms) | Energy, emotion, arc phase, activity mode | Performance vetoes + axiom vetoes | Sample trigger / TTS schedule |
| Audio onset (50ms) | Energy level, beat position, emotion | Energy threshold + spacing constraint | Throw eligibility |
| Wake word (instant) | None (override) | None (supremacy) | Immediate resume |
| Manual MIDI trigger | Beat position, energy | Speech-only veto | Direct sample trigger |

Each row is a separate Combinator wiring with its own VetoChain and FallbackChain. They share the same Behavior pool — the same emotion reading, the same energy signal, the same activity mode. They differ in what drives them and what constraints apply.

This is the extensibility the current architecture lacks: adding a new trigger domain doesn't require modifying PerceptionEngine, Governor, or FrameGate. You create a new Event, wire a new Combinator to existing Behaviors, define the relevant governance chain, and connect the output to an actuator. The existing pipelines are unaffected.

---

## Section 6: Formal Guarantees

Each guarantee is a structural consequence of the type system. If the types are respected, the property holds.

### 6.1 Timing Independence

**Claim:** A fast trigger's response time is bounded by the trigger's own latency, not by any Behavior's update rate.

**Proof sketch:** The Combinator fires when the trigger Event fires. It calls `sample()` on each Behavior, which returns immediately (Behaviors are total). The pipeline from trigger to Command involves: one `sample()` per Behavior (O(1) each), one VetoChain evaluation (O(n) for n vetoes, each a predicate call), one FallbackChain selection (O(m) for m candidates), and one Command construction (O(1)). None of these operations wait for a Behavior to update. The response time is the sum of these synchronous operations — bounded by computation, not by signal freshness.

### 6.2 Compositional Safety (Monotonic Restriction)

**Claim:** Adding a veto to a VetoChain can only deny previously-allowed actions, never allow previously-denied actions.

**Proof sketch:** VetoChain computes `allowed = all(v.predicate(ctx) for v in vetoes)`. Adding a veto V' to the set means `allowed' = allowed AND V'.predicate(ctx)`. Since `(P AND Q) → P` is a tautology, `allowed' → allowed`. If it was denied before (`allowed = False`), it's still denied (`allowed' = False` since `False AND anything = False`). If it was allowed before (`allowed = True`), it may now be denied (`True AND False = False`) but never the reverse. QED.

### 6.3 Temporal Integrity

**Claim:** Every Command carries a provable upper bound on the staleness of the perception data that informed it.

**Proof sketch:** Every Behavior `sample()` returns a `Stamped[T]` with a watermark. The Combinator computes `min_watermark = min(sample.watermark for sample in samples)`. The Command stores this `min_watermark`. Since watermarks are monotonically non-decreasing per Behavior (enforced at `update()`), and the minimum of monotonic sequences is itself a valid bound, the Command's `min_watermark` is a provable lower bound on the freshness of all inputs. The staleness at decision time is `now - min_watermark`.

### 6.4 Scheduling Precision

**Claim:** Beat-aligned actuation resolves to an exact wall-clock timestamp.

**Proof sketch:** TimelineMapping is a bijective affine map. `time_at_beat(b)` computes `t_ref + (b - b_ref) × (60 / tempo)`. This is a single multiply-add with a unique result (bijectivity). The Schedule stores both the beat target and the resolved wall-clock time. The actuator uses the wall-clock time for pre-scheduling. The precision is bounded by floating-point arithmetic (~15 significant digits), which at audio sample rate (44.1kHz) gives sub-nanosecond precision — far beyond the ~20ms jitter floor of audio output systems.

---

## Section 7: Migration Path from Current Architecture

### 7.1 Current primitives mapped to new types

| Current code | New primitive | Change required |
|-------------|--------------|-----------------|
| `EnvironmentState` fields | Individual `Behavior[T]` per signal | Decompose monolith into typed signals |
| PerceptionEngine fast tick | One `Event` trigger among many | Tick becomes one trigger, not the sole driver |
| PerceptionEngine slow tick | Background update loop writing to Behaviors | Decoupled from tick cadence |
| PipelineGovernor.evaluate() | VetoChain + FallbackChain | Split safety from preference |
| ContextGate layers | Additional vetoes in VetoChain | Merge into unified governance |
| FrameGate directive string | `Command` with directive action | Typed command replaces bare string |
| Wake word callback | `Event[None]` with supremacy veto override | Uniform event type |
| HyprlandEventListener callback | `Event[FocusEvent]` → Behavior update | Event-driven Behavior update |
| Carried-forward slow fields | Behavior watermarks | Freshness becomes explicit |

### 7.2 Sequencing

**Phase 1 — Introduce types alongside existing code.**

Implement `Behavior[T]`, `Event[T]`, `Stamped[T]`, `Watermark` as library types. Wrap existing signals in Behaviors. Wrap existing callbacks in Events. The existing PerceptionEngine continues to work — it just reads from Behaviors instead of internal fields.

New files:
- `agents/hapax_voice/primitives.py` — Behavior, Event, Stamped, Watermark types
- `agents/hapax_voice/timeline.py` — TimelineMapping

Modified files:
- `agents/hapax_voice/config.py` — freshness threshold config fields
- `agents/hapax_voice/perception.py` — PerceptionEngine wraps signals as Behaviors internally

**Phase 2 — Introduce Detectives.**

Implement Combinator, VetoChain, FallbackChain, FreshnessGuard. Refactor Governor into VetoChain (safety) + FallbackChain (selection). Refactor ContextGate into additional vetoes. The output is still a directive string, but produced by typed governance.

New files:
- `agents/hapax_voice/governance.py` — VetoChain, FallbackChain, FreshnessGuard
- `agents/hapax_voice/combinator.py` — withLatestFrom Combinator

Modified files:
- `agents/hapax_voice/governor.py` — decompose into VetoChain + FallbackChain
- `agents/hapax_voice/context_gate.py` — migrate layers to vetoes

**Phase 3 — Introduce Directives.**

Implement Command and Schedule. Replace bare directive strings with typed Commands. Add TimelineMapping for beat-time resolution. Wire pre-scheduling for beat-aligned actuation.

New files:
- `agents/hapax_voice/commands.py` — Command, Schedule types

Modified files:
- `agents/hapax_voice/frame_gate.py` — accept Command instead of string directive
- `agents/hapax_voice/__main__.py` — wire new Combinator-based evaluation

---

## Section 8: What NOT to Build

1. **No distributed pub/sub.** This runs on one machine. In-process Behavior/Event wiring is sufficient. ZeroMQ, MQTT brokers, and message serialization are unnecessary overhead.

2. **No general-purpose FRP runtime.** The six Perceptive/Detective/Directive primitives are sufficient. A full FRP library (with `switch`, `accum`, dynamic event networks) adds complexity without matching benefit for this use case.

3. **No music-specific primitives.** TimelineMapping handles music time as one of many time domains. Sample banks, beat grids, and groove templates are actuator concerns, not perception primitives.

4. **No event sourcing.** Commands are logged for debugging but the log is not the source of truth. Perception Behaviors are the source of truth. No replay infrastructure, no event store, no projections.

5. **No reactive streams library.** `withLatestFrom` is the only combinator needed. Don't import RxPY or build an operator algebra for operators that won't be used.

---

## Tracked B-Path Items

Items tracked for future consideration (do not lose):

1. **Partial snapshot projection.** Consumers that need only a subset of Behaviors could receive projected views instead of sampling all signals. Deferred because the current consumer count (1-3) doesn't justify the abstraction.

2. **TemporalBuffer[T].** A queryable signal history for "what was the energy level 2 beats ago?" Deferred because no current use case requires historical Behavior queries.

3. **Dynamic veto registration.** VetoChain is currently static (vetoes defined at construction). Dynamic add/remove would support runtime axiom loading. Deferred because axioms are currently static.

4. **RetainedPubSub for late joiners.** Behaviors already solve the late-joiner problem (sample always works). RetainedPubSub would be needed only if Events need late-joiner semantics, which is semantically wrong for most Events (you shouldn't receive a past wake word activation).

5. **Multi-segment TimelineMapping.** Piecewise-affine timeline for tempo changes. The initial implementation assumes constant tempo within a session. Tempo changes create a new TimelineMapping Behavior value.

---

## Sources

### Formal Foundations

- Elliott, C. (2009). [Push-Pull Functional Reactive Programming](http://conal.net/papers/push-pull-frp/). Haskell Symposium. — Denotational semantics of Behavior and Event types
- Emrich, T., et al. (2021). [Watermarks in Stream Processing Systems: Semantics and Comparative Analysis](http://www.vldb.org/pvldb/vol14/p3135-begoli.pdf). PVLDB 14(12). — Formal watermark model, perfect vs heuristic watermarks, completeness-latency tradeoff
- Cutler, J.W., et al. (2024). [Cedar: A New Language for Expressive, Fast, Safe, and Analyzable Authorization](https://arxiv.org/abs/2403.04651). OOPSLA. Lean-verified deny-wins semantics. [Authorization decision algorithm](https://docs.cedarpolicy.com/auth/authorization.html)
- Brooks, R. (1986). [A Robust Layered Control System for a Mobile Robot](https://people.csail.mit.edu/brooks/papers/AIM-864.pdf). MIT AI Memo 864. — Suppression/inhibition, layered competence, subsumption
- [Ableton Link Documentation](https://ableton.github.io/link/). — Timeline triple `(beat, time, tempo)`, capture-commit model, quantum/phase synchronization
- Nystrom, R. [Command Pattern (Game Programming Patterns)](https://gameprogrammingpatterns.com/command.html). — Commands as serializable action objects, undo/replay

### Prior Art (from project research)

- [Prior Art Survey](../research/2026-03-11-prior-art-survey.md) — 5-domain survey, 6 cross-cutting patterns, 8 candidate primitives
- [Inside-Out Analysis](../research/2026-03-11-inside-out-analysis.md) — 9 implicit patterns extracted from existing code
- [Comparative Evaluation](../research/2026-03-11-comparative-evaluation.md) — Gap analysis, hot/cold insight, 3-step path forward
