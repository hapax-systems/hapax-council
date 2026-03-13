# Multi-Role Composition — Design Spec

> **Status:** Proposed
> **Date:** 2026-03-12
> **Scope:** Extensions to the perception primitive type system for concurrent multi-role governance
> **Builds on:** [Perception Primitives](2026-03-11-perception-primitives-design.md), [Multi-Role North Star](2026-03-12-multi-role-north-star-design.md)

## Problem

The 10-primitive type system (Behavior, Event, Watermark, TimelineMapping, Combinator, VetoChain, FallbackChain, FreshnessGuard, Command, Schedule) handles a single governance chain operating in isolation. The multi-role North Star requires multiple governance chains running concurrently, sharing inputs, arbitrating outputs, and modulating each other's activity levels.

Five structural gaps exist:

1. **No graduated modulation.** VetoChain is binary (allow/deny). Multi-role requires continuous suppression.
2. **No resource arbitration.** Multiple chains can produce Commands for the same physical output with no coordination.
3. **No cross-role awareness.** Chains are isolated — no mechanism to read another chain's state.
4. **No compound goals.** No way to express a single intent that decomposes across roles.
5. **No feedback loops.** The pipeline is feedforward — actuation events don't feed back as perception.

This spec addresses each gap, extending the type system minimally. Each new primitive is justified by showing it cannot be expressed as composition of existing primitives.

---

## Section 1: SuppressionField — Graduated Cross-Role Modulation

### 1.1 Why VetoChain Is Insufficient

VetoChain implements deny-wins: any veto blocks the action entirely. For multi-role composition, the requirement is not "block MC during conversation" but "dim MC during conversation." A vocal throw that would fire at energy threshold 0.3 should require energy threshold 0.6 when conversation is active — harder to trigger, not impossible.

This cannot be expressed as a VetoChain predicate because:
- A veto is `FusedContext → bool`. It either blocks or doesn't.
- Graduated modulation requires `FusedContext → float` — a continuous value that modifies downstream thresholds.
- The modification is not a single decision but an ongoing state: suppression persists as long as the suppressing condition holds.

### 1.2 Definition

A `SuppressionField` is a `Behavior[float]` in the range [0.0, 1.0] where 0.0 = fully active and 1.0 = fully suppressed. It is published by one governance chain and read by others.

```python
@dataclass
class SuppressionField:
    """Continuous modulation signal between governance chains.

    Not a new type — this is a Behavior[float] with:
    - Defined range [0.0, 1.0] via clamping at update()
    - Defined semantics (0.0 = active, 1.0 = suppressed)
    - Smoothing to prevent step discontinuities
    """
    _behavior: Behavior[float]        # underlying signal
    _attack_s: float = 0.5            # seconds to reach full suppression
    _release_s: float = 2.0           # seconds to return to full activity
    _target: float = 0.0             # target suppression level

    def set_target(self, level: float, now: float) -> None:
        """Set target suppression. Actual value ramps via attack/release."""
        self._target = max(0.0, min(1.0, level))

    def tick(self, now: float) -> None:
        """Advance smoothing. Called from perception loop."""
        current = self._behavior.sample().value
        if current < self._target:
            # Attacking (suppressing): ramp up
            rate = 1.0 / self._attack_s
        else:
            # Releasing (recovering): ramp down
            rate = 1.0 / self._release_s
        delta = (self._target - current) * min(1.0, rate * dt)
        self._behavior.update(current + delta, now)

    @property
    def behavior(self) -> Behavior[float]:
        """Expose as Behavior for Combinator sampling."""
        return self._behavior
```

**Key properties:**

1. **It is a Behavior.** SuppressionField wraps `Behavior[float]`. It participates in the existing Combinator/sampling infrastructure with no special-casing. Any governance chain can sample it via `withLatestFrom`.

2. **Smoothing is inherent.** The attack/release envelope prevents step transitions. When conversation starts, MC suppression ramps up over 0.5s. When conversation ends, MC suppression ramps down over 2.0s (~4 bars at 120 BPM). The musical feel is preserved — no jarring cuts.

3. **Clamped range.** Values are always [0.0, 1.0]. Governance chains use it as a threshold modifier: `effective_threshold = base_threshold + suppression * (1.0 - base_threshold)`. At suppression 0.0, threshold is base. At suppression 1.0, threshold is 1.0 (never triggers).

### 1.3 Usage in Governance

Governance chains read suppression via their Combinator:

```python
mc_fused = with_latest_from(
    midi_tick_event,
    energy_rms,
    emotion_valence,
    arc_phase,
    conversation_suppression.behavior,   # ← cross-role modulation
    transport_state,
)
```

The VetoChain predicates then use the suppression value:

```python
def energy_sufficient(ctx: FusedContext) -> bool:
    suppression = ctx.get_sample("conversation_suppression").value
    base_threshold = 0.3
    effective = base_threshold + suppression * (1.0 - base_threshold)
    return ctx.get_sample("energy_rms").value >= effective
```

This preserves all VetoChain algebraic properties (commutativity, associativity, monotonic safety). The suppression field doesn't change the VetoChain structure — it changes the *inputs* to veto predicates. The deny-wins semilattice is intact.

### 1.4 Suppression Topology

Each role publishes a SuppressionField that other roles read:

```
Conversationalist → publishes → conversation_suppression
    → read by: MC (dims throws), Stream Director (holds scene)

MC → publishes → mc_activity
    → read by: Stream Director (face cam on throw), Conversationalist (pause TTS during sample)

Production Assistant → publishes → monitoring_alert
    → read by: MC (pause during alerts), Stream Director (switch to status overlay)
```

These are ordinary Behaviors in the shared pool. No special wiring infrastructure — the existing `WiringConfig` mechanism registers them like any other Behavior.

---

## Section 2: ResourceArbiter — Output Coordination

### 2.1 Why ExecutorRegistry Is Insufficient

`ExecutorRegistry.dispatch(command)` routes by action name. If two governance chains both produce `Command(action="tts_announce")`, both are dispatched to the same executor. The executor has no information about priority, preemption, or queueing — it just plays audio.

This produces audible collisions: an MC vocal throw and a conversational TTS response overlap. The executor can't resolve this because it has no cross-chain context.

### 2.2 Definition

A `ResourceArbiter` sits between governance output and executor dispatch. It manages named resources with priority-based access.

```python
@dataclass(frozen=True)
class ResourceClaim:
    """A governance chain's claim on a shared output resource."""
    resource: str               # "audio_output", "obs_scene", "operator_attention"
    chain: str                  # claiming governance chain name
    priority: int               # higher = more important
    command: Command            # the command to execute if claim wins
    hold_until: float | None    # wall-clock time to hold claim (None = one-shot)

class ResourceArbiter:
    """Resolves competing claims on shared output resources.

    Semantics:
    - Higher priority preempts lower priority
    - Equal priority: first claim wins (FIFO)
    - Held claims block lower-priority claims until released
    - One-shot claims (hold_until=None) are released after execution
    """
    _claims: dict[str, list[ResourceClaim]]   # resource → active claims, sorted by priority

    def claim(self, rc: ResourceClaim) -> bool:
        """Submit a claim. Returns True if claim is currently winning."""
        ...

    def release(self, resource: str, chain: str) -> None:
        """Release a chain's claim on a resource."""
        ...

    def resolve(self, resource: str) -> ResourceClaim | None:
        """Return the winning claim for a resource, or None if unclaimed."""
        ...

    def drain_winners(self) -> list[ResourceClaim]:
        """Return all winning claims across all resources. Called by actuation loop."""
        ...
```

**Key properties:**

1. **Priority is static per chain.** Priority is set at wiring time, not per-command. The conversationalist always has priority 100 on `audio_output`; MC always has priority 50. This prevents priority inversion — a chain can't promote a command to jump the queue.

2. **Hold semantics.** Conversation holds `audio_output` and `operator_attention` while speaking. MC one-shot claims release immediately after the sample plays. This prevents MC from firing during conversational TTS.

3. **Resource independence.** Arbitration is per-resource. A chain can win `audio_output` and lose `obs_scene` simultaneously. Resources are orthogonal — no cross-resource coupling in the arbiter.

4. **Transparent to governance.** Governance chains produce Commands as before. The arbiter is between governance and execution. Governance doesn't know about contention — it decides what *should* happen. The arbiter decides what *can* happen given competing claims.

### 2.3 Resource Definitions

| Resource | Claimants | Priority order (high → low) |
|----------|-----------|---------------------------|
| `audio_output` | Conversationalist (100), Advisor (90), MC (50), Notification (30) |
| `obs_scene` | Production Assistant (80, transport only), Stream Director (60) |
| `operator_attention` | Conversationalist (100), Advisory (70), MC (20, background) |

### 2.4 Integration with ScheduleQueue

The ResourceArbiter replaces direct `ExecutorRegistry.dispatch()` calls. The actuation loop becomes:

```python
async def _actuation_loop(self) -> None:
    while self._running:
        now = time.monotonic()
        # Drain ready schedules into claims
        for schedule in self.schedule_queue.drain(now):
            resource = self._resource_for(schedule.command.action)
            chain = schedule.command.trigger_source
            self.arbiter.claim(ResourceClaim(
                resource=resource,
                chain=chain,
                priority=self._priority_for(chain, resource),
                command=schedule.command,
            ))
        # Resolve and dispatch winners
        for winner in self.arbiter.drain_winners():
            self.executor_registry.dispatch(winner.command)
        await asyncio.sleep(0.010)
```

---

## Section 3: Cross-Role Awareness via Behavior Publication

### 3.1 Why No New Primitive Is Needed

Cross-role awareness — where MC governance reads conversation state, or the stream director reads MC state — does not require a new primitive. The existing `Behavior[T]` is the mechanism.

Each governance chain, after evaluating its VetoChain/FallbackChain, publishes its current state as a Behavior:

```python
class GovernanceChainState(Enum):
    IDLE = "idle"
    ACTIVE = "active"
    SUPPRESSED = "suppressed"
    FIRING = "firing"

# MC governance publishes:
mc_state: Behavior[GovernanceChainState]

# Conversationalist publishes:
conversation_state: Behavior[ConversationState]  # idle, listening, speaking, processing

# Stream director publishes:
current_scene: Behavior[str]                     # current OBS scene name
```

Other chains sample these via their Combinators. No special wiring — they're Behaviors in the shared pool.

### 3.2 What This Enables

```
MC fires vocal throw
  → MC publishes mc_state = FIRING
  → Stream Director's Combinator samples mc_state on next perception tick
  → Stream Director's FallbackChain: mc_state == FIRING → face_cam (high priority candidate)
  → Stream Director produces Command(action="switch_scene", params={"scene": "face_cam"})
```

The latency is the stream director's trigger cadence (~2.5s perception tick). This is acceptable — scene switches should trail MC activity, not lead it.

### 3.3 Avoiding Circular Dependencies

Cross-role Behavior reads create potential circular dependencies: A reads B's state, B reads A's state. This is safe because:

1. **Behaviors are sampled, not subscribed.** Reading a Behavior doesn't trigger computation in the publishing chain. It returns the last-written value.
2. **Chains evaluate on different trigger Events.** MC fires on MIDI clock; stream director fires on perception tick. They don't trigger each other.
3. **Staleness is explicit.** If chain A reads chain B's state that was updated before B read A's state, the watermark reflects the staleness. FreshnessGuard can reject stale cross-role readings.

The only dangerous pattern would be two chains using the same trigger Event and both reading each other's published state — creating an evaluation order dependency. This is avoided by: each role uses its own trigger domain (MIDI clock, perception tick, wake word, etc.).

---

## Section 4: Compound Goals

### 4.1 The Problem

"Start live recording on YouTube and take care of everything" is a single operator intent that requires activations across multiple roles with ordering constraints:

1. Stream director configures OBS scenes → must complete before step 2
2. Production assistant starts streaming + recording → must complete before step 3
3. MC announces "we're live" (TTS) → depends on streaming being active
4. All roles enter their active state → can be parallel

This is not a governance concern (governance decides what to do within a role). It's an orchestration concern — coordinating activations across roles.

### 4.2 Design Decision: Imperative, Not Declarative

A CompoundGoal could be modeled as a declarative dependency graph. But the current system's complexity budget doesn't justify a goal planner. The simpler approach:

**Compound goals are async methods on the daemon that call role activations in sequence.**

```python
async def goal_start_live_session(self) -> None:
    """Compound goal: start live recording on YouTube."""
    # Step 1: Configure OBS
    await self.stream_director.configure_for_live()

    # Step 2: Start streaming + recording
    await self.production_assistant.start_streaming()
    await self.production_assistant.start_recording()

    # Step 3: Announce
    self.tts_governance.announce("We're live.")

    # Step 4: Activate all roles
    self.mc_governance.set_active(True)
    self.stream_director.set_active(True)
```

This is deliberately not a new primitive. It's an async method that sequences existing operations. The complexity of goal decomposition is in the code, not in a type system — which is appropriate for a system with a single operator and a small number of compound goals.

### 4.3 When This Becomes Insufficient

If the number of compound goals grows beyond ~10, or if goals need dynamic decomposition (e.g., different activation sequences based on context), a proper CompoundGoal type with dependency graph resolution would be warranted. Tracked as B-path item.

---

## Section 5: Actuation as Perception (Feedback Loops)

### 5.1 Closing the Loop

The current pipeline is feedforward:

```
Perception → Fusion → Governance → Scheduling → Actuation
```

Multi-role requires feedback: actuation events feed back as inputs:

```
Perception → Fusion → Governance → Scheduling → Actuation
     ↑                                              │
     └──────────────────────────────────────────────┘
```

### 5.2 Mechanism

The Executor protocol's `execute()` method fires an `Event[ActuationEvent]` after successful execution:

```python
@dataclass(frozen=True)
class ActuationEvent:
    """Record of a completed actuation."""
    action: str
    chain: str              # which governance chain produced this
    wall_time: float        # when it actually executed
    target_time: float      # when it was scheduled to execute
    latency_ms: float       # target_time - wall_time
    params: dict[str, Any]  # from the Command

class ExecutorRegistry:
    actuation_event: Event[ActuationEvent]   # published after each dispatch

    def dispatch(self, command: Command) -> bool:
        # ... existing dispatch logic ...
        if success:
            self.actuation_event.emit(now, ActuationEvent(
                action=command.action,
                chain=command.trigger_source,
                wall_time=now,
                target_time=command.trigger_time,
                latency_ms=(now - command.trigger_time) * 1000,
                params=command.params,
            ))
```

### 5.3 Derived Behaviors from Actuation Events

Actuation Events are converted to Behaviors via simple accumulators:

```python
# "When did MC last fire?" — Behavior updated on MC actuation events
last_mc_fire: Behavior[float] = Behavior(0.0)

def on_mc_actuation(timestamp: float, event: ActuationEvent) -> None:
    if event.chain == "mc":
        last_mc_fire.update(timestamp, timestamp)

actuation_event.subscribe(on_mc_actuation)
```

These derived Behaviors join the shared pool and are sampled by any governance chain's Combinator.

### 5.4 Stability

Feedback loops risk oscillation: MC fires → stream director switches scene → scene change triggers MC → repeat. Stability is ensured by:

1. **Different trigger domains.** MC triggers on MIDI clock; stream director triggers on perception tick. They don't directly trigger each other.
2. **Minimum spacing constraints.** MC's VetoChain includes a spacing veto (minimum 2 beats between throws). Scene switching has a dwell time veto (minimum 2 bars between cuts). These act as dampers.
3. **SuppressionField smoothing.** Attack/release envelopes prevent rapid oscillation in suppression levels.
4. **FreshnessGuard.** Cross-role readings that are too stale are rejected, breaking potential feedback cycles.

---

## Section 6: Hierarchical Musical Time

### 6.1 Extension, Not New Primitive

Hierarchical position (beat, bar, phrase, section) is derived from TimelineMapping via pure arithmetic:

```python
@dataclass(frozen=True)
class MusicalPosition:
    """Hierarchical position derived from beat position."""
    beat: float
    bar: int
    beat_in_bar: float
    phrase: int              # bar // bars_per_phrase
    bar_in_phrase: int       # bar % bars_per_phrase
    section: int             # phrase // phrases_per_section
    phrase_in_section: int   # phrase % phrases_per_section

def musical_position(
    beat: float,
    beats_per_bar: int = 4,
    bars_per_phrase: int = 4,
    phrases_per_section: int = 4,
) -> MusicalPosition:
    bar = int(beat // beats_per_bar)
    return MusicalPosition(
        beat=beat,
        bar=bar,
        beat_in_bar=beat % beats_per_bar,
        phrase=bar // bars_per_phrase,
        bar_in_phrase=bar % bars_per_phrase,
        section=(bar // bars_per_phrase) // phrases_per_section,
        phrase_in_section=(bar // bars_per_phrase) % phrases_per_section,
    )
```

This is a `Behavior[MusicalPosition]` updated whenever `TimelineMapping` updates. Governance chains sample it like any other Behavior.

### 6.2 Governance at Different Levels

```python
# Beat-level: sample trigger timing
def beat_aligned(ctx: FusedContext) -> bool:
    pos = ctx.get_sample("musical_position").value
    return pos.beat_in_bar % 1.0 < 0.1  # within 10% of beat

# Phrase-level: throw density ceiling
def phrase_density_ok(ctx: FusedContext) -> bool:
    pos = ctx.get_sample("musical_position").value
    throws_this_phrase = count_throws_in_phrase(pos.phrase)
    return throws_this_phrase < MAX_THROWS_PER_PHRASE

# Section-level: MC character
def section_character(ctx: FusedContext) -> str:
    pos = ctx.get_sample("musical_position").value
    if pos.section % 2 == 0:
        return "hype"       # even sections are hype
    return "laid_back"      # odd sections are chill
```

---

## Section 7: Summary of Extensions

### New primitives

| Primitive | Class | Justification |
|-----------|-------|---------------|
| `SuppressionField` | Perceptive (wraps Behavior[float]) | Graduated modulation cannot be expressed as VetoChain predicates — requires continuous state with smoothing |
| `ResourceClaim` | Directive | Commands alone lack priority and hold semantics needed for multi-chain output coordination |
| `ResourceArbiter` | Detective | ExecutorRegistry routes by action name, not by competing chain priority — arbiter adds the priority resolution layer |

### Patterns (not primitives)

| Pattern | Mechanism |
|---------|-----------|
| Cross-role awareness | Governance chains publish state as Behaviors in the shared pool |
| Compound goals | Async methods sequencing existing role activations |
| Feedback loops | Executor publishes `Event[ActuationEvent]` → accumulated into derived Behaviors |
| Hierarchical time | `MusicalPosition` derived from `TimelineMapping` via arithmetic |

### Unchanged primitives

The existing 10 primitives (Behavior, Event, Watermark, TimelineMapping, Combinator, VetoChain, FallbackChain, FreshnessGuard, Command, Schedule) are unchanged. The extensions add 3 new types and 4 patterns that compose with the existing type system.

---

## Section 8: Implementation Sequencing

### Phase 1: SuppressionField + Cross-Role Publication
- Implement `SuppressionField` (wraps `Behavior[float]` with smoothing)
- Add governance chain state publication (each chain publishes its state as a Behavior)
- Wire conversation_suppression → MC governance Combinator
- **Validates:** graduated modulation, cross-role awareness

### Phase 2: ResourceArbiter
- Implement `ResourceClaim`, `ResourceArbiter`
- Insert arbiter between ScheduleQueue drain and ExecutorRegistry dispatch
- Define resource priorities per chain
- **Validates:** output coordination, priority preemption

### Phase 3: Feedback Loops
- Add `Event[ActuationEvent]` to ExecutorRegistry
- Implement actuation → Behavior accumulators
- Wire derived Behaviors into stream director's Combinator
- **Validates:** closed-loop perception, stability

### Phase 4: Hierarchical Time + Compound Goals
- Implement `MusicalPosition` derivation
- Add phrase/section-level governance predicates
- Implement compound goal methods on daemon
- **Validates:** hierarchical governance, multi-role orchestration

---

## Section 9: B-Path Items

1. **Dynamic role loading.** Currently roles are hardcoded in daemon startup. A plugin system for roles would enable post-deployment extension. Deferred — 6 roles is manageable statically.

2. **Suppression negotiation.** Currently suppression is unilateral (conversation suppresses MC). Negotiated suppression (MC can request "one more throw" during conversation wind-down) would require bidirectional suppression fields. Deferred — unilateral is sufficient for the current role set.

3. **Resource preemption notification.** When a higher-priority claim preempts a lower-priority one, the preempted chain could be notified. Deferred — currently chains don't need to react to preemption.

4. **Declarative compound goals.** If the number of compound goals grows beyond ~10, a dependency-graph-based goal decomposition system would reduce boilerplate. Deferred — async method sequencing is sufficient.

5. **Cross-role FreshnessGuard tuning.** Different cross-role readings may need different staleness tolerances. Currently all cross-role Behaviors share the default freshness threshold. Per-pair tuning would be needed if latency requirements differ significantly between cross-role pairs.

6. **TemporalBuffer for feedback.** `Behavior[T]` retains only the latest value. If feedback consumers need historical actuation data ("how many throws in the last 4 bars?"), a `TemporalBuffer[T]` (queryable ring buffer with time-range queries) would be needed. Currently, simple counters suffice.

---

## Sources

### Formal Foundations (additional to Perception Primitives spec)

- Brooks, R. (1986). [A Robust Layered Control System for a Mobile Robot](https://people.csail.mit.edu/brooks/papers/AIM-864.pdf). MIT AI Memo 864. — Subsumption architecture, layered competence, suppression/inhibition between layers
- Arkin, R. (1998). *Behavior-Based Robotics*. MIT Press. — Motor schema arbitration, cooperative vs competitive output fusion, graduated behavioral suppression
- Maes, P. (1989). [How to Do the Right Thing](https://www.media.mit.edu/publications/how-to-do-the-right-thing/). Connection Science 1(3). — Spreading activation networks for action selection with competing goals
- Bryson, J. (2001). Intelligence by Design: Principles of Modularity and Coordination for Engineering Complex Adaptive Agents. PhD Thesis, MIT. — POSH reactive plans, priority-based action selection across behavioral modules
