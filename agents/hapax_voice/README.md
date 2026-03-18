# hapax_voice — A Perception Type System for Governed Voice Interaction

A 10-layer composition ladder for fusing signals at different temporal rates into governance decisions. Each layer's algebraic properties are proven via a 7-dimension test matrix and Hypothesis property-based tests. 192 matrix tests + 62 hypothesis tests across all layers.

## Proven properties per layer

| Layer | Types | State | Key properties proven |
|-------|-------|-------|----------------------|
| L0 | Stamped[T] | Proven | Equality reflexivity, frozen immutability, hash consistency (5 hypothesis) |
| L1 | Behavior[T], Event[T] | Proven | Watermark monotonicity, regression rejection, subscriber conservation, consent label monotonicity (8+4 hypothesis) |
| L2 | FusedContext, VetoChain, FallbackChain, FreshnessGuard | Proven | VetoChain monotonicity (adding vetoes only restricts), deny-wins totality |
| L3 | with_latest_from | Proven | Fusion preserves watermarks, min_watermark is minimum of all sources |
| L4 | Command, Schedule, VetoResult | Proven | Command immutability, governance trail completeness |
| L5 | SuppressionField, TimelineMapping, MusicalPosition | Proven | Timeline bijectivity, suppression monotonicity |
| L6 | ResourceArbiter, ExecutorRegistry, ScheduleQueue | Proven | Priority determinism, resource exclusivity |
| L7 | compose_mc_governance, compose_obs_governance | Proven | Chain composition preserves monotonicity |
| L8 | PerceptionEngine, PipelineGovernor, FrameGate | Proven | Governor axiom compliance |
| L9 | VoiceDaemon | Proven | End-to-end lifecycle |

**7-dimension test matrix**: A (Construction), B (Invariants), C (Operations), D (Boundaries), E (Error paths), F (Dog Star proofs — forbidden sequences blocked), G (Composition contracts — output of layer N is valid input to layer N+1).

**Gate rule**: No new composition on layer N unless layer N-1 is matrix-complete. Full status in [`LAYER_STATUS.yaml`](LAYER_STATUS.yaml).

## Research traditions

| Tradition | Contribution | Key references |
|-----------|-------------|----------------|
| Functional reactive programming | Behavior/Event duality, with_latest_from combinator | Elliott 2009, Yampa, Reflex, RxPY |
| Stream processing | Watermarks for staleness reasoning, monotonic progress | Flink, Dataflow, VLDB watermark theory |
| DSP / audio synthesis | Suppression envelopes (attack/release), temporal smoothing | Modular synthesis, compressor design |

## Temporal Fusion

An always-on voice daemon receives signals from the world at vastly different rates. A MIDI clock tick arrives every few milliseconds. Audio energy measurements update at 50ms. Voice activity detection settles over hundreds of milliseconds. Emotion classification from body language or vocal tone takes 1–2 seconds. An LLM-powered workspace analysis — "what is the operator doing right now?" — takes 10–15 seconds. All of these signals contribute to a single governance decision: should the system fire a beat-aligned audio sample, switch an OBS camera, or stay quiet?

The solution draws from three research traditions.

**Functional reactive programming** (Elliott 2009, Yampa, Reflex, RxPY) provides the core duality: `Behavior[T]` for values that are always available (like a voltage reading on a meter — there is always a current value), and `Event[T]` for things that happen at specific instants (like a button press or a MIDI tick). The `with_latest_from` combinator bridges them: when a fast event fires, sample all slow behaviors at whatever they currently hold. This is how a MIDI tick at sub-millisecond precision can incorporate an emotion reading that is 2 seconds old. The tick doesn't wait for emotion to update. It reads what's there.

**Stream processing** (Flink, Dataflow, VLDB watermark theory) provides the mechanism for reasoning about staleness. Every `Behavior` carries a monotonic watermark — a timestamp that records when the value was last updated. When `with_latest_from` fuses a trigger event with multiple behaviors, it computes `min_watermark`: the age of the stalest signal in the fused result. A `FreshnessGuard` downstream can then reject decisions made on data that's too old. The MIDI tick sampled emotion at 2 seconds old, which is fine. But if the emotion signal is 30 seconds old because the classifier crashed, the FreshnessGuard catches it. 

**DSP audio synthesis** (modular synthesis, compressor envelopes) provides the temporal smoothing needed for multi-role coordination. When a conversation starts and the MC (backup microphone) governance chain needs to quiet down, the suppression doesn't slam to zero. A `SuppressionField` uses attack/release envelopes — the same mechanism audio compressors use — to smoothly ramp the energy threshold upward. The MC chain doesn't switch off; it gradually becomes harder to trigger. When the conversation ends, the threshold releases slowly back to baseline. This prevents the kind of oscillation that binary mode-switching produces when signals are noisy.

## The Three Layers


### Perceptives: What Is the World Doing?

Perceptives are the raw material of perception. Two types capture the fundamental duality of time-varying state:

**`Behavior[T]`** is a continuously-available value. It always has a current reading. You can sample it at any time and get a `Stamped[T]` — the value plus the timestamp when it was last updated. If you update a Behavior with a timestamp earlier than its current watermark, the update is rejected. Time does not go backward. Consumers can rely on values being produced at or after the reported time. Behaviors model things like emotion arousal, audio energy, stream health, operator presence, circadian alignment — signals that have a meaningful "current value" even between updates.

**`Event[T]`** is a discrete occurrence. It has no current value — it happens at a specific instant and then it's gone. You subscribe to an Event and your callback fires when it emits. Late subscribers receive no history. Events model MIDI clock ticks, wake word detections, governance chain outputs, and actuation completions. The distinction from Behavior is semantic, not just pragmatic: asking "what is the current MIDI tick?" is a category error, while asking "what is the current emotion arousal?" is not.

**`Stamped[T]`** is the common currency: an immutable snapshot of a value frozen at a moment in time. Immutability prevents TOCTOU bugs — between the moment a governance chain evaluates a signal and the moment an executor acts on the decision, the data cannot change underneath.

### Detectives: What Does It Mean?

Detectives evaluate whether a proposed action should proceed. They are governance primitives with specific algebraic properties that make composition safe.

**`VetoChain[C]`** is a set of constraints evaluated over a context `C`. Each constraint (a `Veto`) is a predicate that either allows or denies. The chain is **deny-wins**: any single denial blocks the action. All vetoes evaluate regardless of earlier denials, producing a complete audit trail. Chains compose via `|` (concatenation).

The critical property is monotonicity: **adding a veto to a chain can only make the system more restrictive, never less.** If a chain with vetoes A and B permits an action, the chain with vetoes A, B, and C will permit it only if C also allows it. You cannot accidentally widen permissions by adding a constraint. When you wire a new safety check into an existing governance chain, you don't need to reason about interactions with existing checks — the algebra guarantees that the system can only become more conservative.

Each Veto optionally tags the axiom it enforces, linking runtime governance decisions back to constitutional principles.

**`FallbackChain[C, T]`** is a priority-ordered sequence of candidates, each with a predicate and an action. It returns the first eligible candidate — deterministically, first-eligible-wins. The chain always has a default (the last entry), which means the system always has something to do. This ensures graceful degradation: even when every interesting action is vetoed, the system doesn't crash or hang — it falls back to the default (typically silence or a hold).

**`FreshnessGuard`** rejects decisions made on stale data. Each requirement specifies a behavior name and a maximum staleness in seconds. The fail-safe default is `fresh_enough=False` — if the guard cannot determine freshness, it rejects the decision. This prevents the system from acting on perception data that no longer reflects reality.

### The Combinator

**`with_latest_from(trigger: Event, behaviors: dict[str, Behavior]) → Event[FusedContext]`**

This single function bridges Perceptives to Detectives. When the trigger fires, it samples every behavior at its current value and emits a `FusedContext` — a frozen snapshot containing the trigger event, all sampled values with their watermarks, and the `min_watermark` (the stalest signal). The semantics are: "this thing just happened — what does the world look like right now?"

This is derived from Rx's `withLatestFrom` operator, but the addition of watermarks and `min_watermark` computation is specific to this system. 

### Directives: What Should We Do?

Directives are not actions. They are descriptions of actions that carry the full governance trail of how they were selected. This distinction — between describing an action and performing it — is where governance lives.

**`Command`** is an immutable data object recording: what action was selected, what parameters it requires, what governance evaluation produced it (the complete `VetoResult`), which chain selected it, what trigger caused it, and the minimum watermark of the perception data that informed it. A denied Command still exists — it carries its denial as provenance. An Executor can inspect any Command and see the full chain of reasoning that led to it.

The system never constructs a Command without a governance trail. There is no way to create an action description that skips the Detective layer. 

**`Schedule`** binds a Command to a specific time in a specific domain. `domain="beat"` means the target time is a beat number (resolved to wall-clock via `TimelineMapping`); `domain="wall"` means direct wall-clock targeting. The `tolerance_ms` field specifies how late execution can be before the schedule is discarded — a beat-aligned sample that arrives 200ms late is worse than not firing at all.

### Actuation

**`Executor`** is a protocol for physical actuators. Each declares what action names it handles and whether it's currently available. **`ExecutorRegistry`** routes Commands to the correct Executor. On successful dispatch, it emits an `ActuationEvent` — an immutable record of what happened, when, and how much latency was incurred. This event feeds back into Behaviors, closing the loop.

**`ScheduleQueue`** is a priority queue ordered by wall-clock time. The actuation loop drains it continuously: schedules whose time has arrived are dispatched; those past their tolerance window are discarded; future schedules wait. This is how beat-aligned actuation achieves sub-50ms precision: the MC governance chain emits Schedules at beat positions, and the actuation loop drains them at the right moment.

## The Governance Chains

Two governance chains demonstrate how the primitives compose into domain-specific decision pipelines.

### MC Governance: Beat-Aligned Audio

The MC (backup microphone) chain controls audio sample playback during live music production — vocal throws, ad-libs, and silence — synchronized to MIDI transport. The pipeline:

1. A MIDI clock tick fires (the trigger Event)
2. `with_latest_from` samples energy, emotion, timeline mapping, suppression, and feedback behaviors
3. `FreshnessGuard` rejects the decision if any signal is too stale (energy: 200ms, emotion: 3s, timeline: 500ms)
4. `VetoChain` evaluates: Is the pipeline active? Is nobody talking (VAD below threshold)? Is there enough audio energy (adjusted by suppression)? Has enough time passed since the last throw (4s cooldown)? Is MIDI transport playing?
5. `FallbackChain` selects: vocal throw (high energy + high arousal), ad-lib (moderate energy), or silence (default)
6. The selected action becomes a `Schedule` at the next beat position, resolved from beat-time to wall-clock via `TimelineMapping`

Each veto predicate is a module-level function, independently testable. The entire chain is composed from the same primitives used everywhere else.

### OBS Governance: Camera Direction

The OBS chain selects livestream camera scenes and transitions based on energy, stream health, and feedback from the MC chain. It runs at perception cadence (2.5s) rather than MIDI cadence, because camera cuts don't need beat alignment — they need stream health awareness and dwell-time respect (don't cut too frequently).

A cross-chain feedback mechanism links the two: when the MC chain fires a vocal throw, the feedback behavior `last_mc_fire` updates. The OBS chain reads this and biases toward the face camera — if audio just fired, the viewer should see the performer. This is not a hardcoded coupling; it's a Behavior that one chain writes and another reads through the normal `with_latest_from` sampling.

### Pipeline Governor

Above both chains sits the `PipelineGovernor`, which determines whether the voice pipeline should be active at all. It evaluates the fused `EnvironmentState` and returns a directive: `"process"` (pipeline runs), `"pause"` (audio frames are dropped), or `"withdraw"` (session should close). It uses VetoChain + FallbackChain internally, with axiom compliance checking: workspace context (from slow-tick LLM analysis) is matched against `management_governance` T0 implications to prevent the system from processing audio in contexts where it might encounter management-sensitive content.

## Cross-Chain Coordination

### Suppression Fields

When roles must coexist — conversation and MC, for instance — binary mode-switching is too coarse. `SuppressionField` provides continuous modulation (0.0 to 1.0) using attack/release envelopes borrowed from audio compressor design. The `effective_threshold` function adjusts a base energy threshold by suppression level: at 0 the threshold is unchanged; at 1.0 it reaches 1.0 (impossible to trigger), fully suppressing the chain. Between those extremes, the chain becomes progressively harder to fire.

This is Brooks' subsumption architecture (layered behavioral competence with inhibition) reimplemented as graduated modulation rather than binary suppression. It prevents oscillation when signals are noisy and allows multiple roles to coexist with dynamic priorities.

### Resource Arbiter

When multiple governance chains produce Commands that claim the same physical resource (both MC and OBS want audio output), the `ResourceArbiter` resolves contention. Claims carry static priorities. `drain_winners()` selects one winner per resource per cycle, garbage-collects expired holds, and removes one-shot claims after winning. The arbiter sits between governance output and executor dispatch — the Commands exist (with full governance provenance) regardless of whether they win the resource.

### Feedback Loop


## Perception Infrastructure

### Backends and Cadence

`PerceptionEngine` produces `EnvironmentState` snapshots by fusing registered backends. Each backend implements the `PerceptionBackend` protocol and is assigned to a `CadenceGroup` — a set of backends polled at a shared interval. Different groups run at different rates: audio energy at fast tick (2.5s), workspace analysis at slow tick (12s), Hyprland window state on IPC events.

Each CadenceGroup has its own `tick_event: Event[float]`. Governance chains wire to the tick event of the cadence group that matches their temporal requirements. The MC chain wires to MIDI clock ticks. The OBS chain wires to perception fast ticks. Each chain fires at its required rate, sampling other signals via `with_latest_from`.

Eight backends in `backends/`: PipeWire (audio energy, emotion), Hyprland (window/workspace), watch (heart rate, HRV), health (CPU, RAM, GPU), circadian (rhythm alignment), MIDI clock (ticks, transport, tempo), stream health (OBS bitrate, lag, drops).

### Multi-Source Wiring

`WiringConfig` maps physical sources to backend instances and cadence groups. `GovernanceBinding` resolves bare signal names (like `audio_energy_rms`) to source-qualified names (like `audio_energy_rms:monitor_mix`), allowing governance chains to be written against abstract signals while the wiring layer handles physical routing. Aggregation functions derive synthetic behaviors from multiple sources (`aggregate_max`, `aggregate_mean`, `aggregate_any`).

## Musical Semantics

`TimelineMapping` is a bijective affine map between wall-clock and beat time: given a reference point and a tempo, `beat_at_time(t)` and `time_at_beat(b)` are pure arithmetic. Transport state (PLAYING/STOPPED) freezes the mapping. Bijectivity means every wall-clock instant has exactly one beat position and vice versa — no ambiguity, no rounding. This is adapted from Ableton Link's timeline triple `(beat, time, tempo)`.

`MusicalPosition` decomposes a global beat number into bar, beat-in-bar, phrase, bar-in-phrase, section, and phrase-in-section (assuming 4/4 time, 4-bar phrases, 4-phrase sections). This enables musically-aware governance: fire on downbeats, respect phrase boundaries, avoid mid-section interruptions.

## Consent and Speaker Identity

`SpeakerIdentifier` performs speaker identification via embedding cosine similarity — not for authentication (single-user axiom), but for routing decisions (operator present vs. guest vs. uncertain). For non-operator persons, the `ConsentRegistry` must have an active contract covering the `"biometric"` data category before embeddings are processed. Without a contract, identification returns `uncertain` and enrollment raises `ValueError`. The gate is at the perception boundary — before the embedding is even extracted.

## Daemon Lifecycle

`VoiceDaemon` (`__main__.py`, ~1000 lines) orchestrates all subsystems. Five concurrent async loops handle audio distribution (30ms frames to wake word, VAD, and Gemini Live), perception (fast/slow tick polling), actuation (ScheduleQueue draining), wake word processing, and proactive notification delivery. Backends are registered with availability gating — missing hardware degrades gracefully, never crashes. Pipeline backends support local processing (Pipecat: STT → LLM → TTS) or cloud (Gemini Live speech-to-speech).

## Package Structure

```
agents/hapax_voice/
├── primitives.py           Behavior[T], Event[T], Stamped[T]
├── governance.py           VetoChain, FallbackChain, FreshnessGuard, FusedContext
├── combinator.py           with_latest_from
├── commands.py             Command, Schedule
├── executor.py             Executor, ExecutorRegistry, ScheduleQueue
├── perception.py           PerceptionBackend, PerceptionEngine, EnvironmentState
├── wiring.py               WiringConfig, GovernanceBinding, multi-source aliases
├── cadence.py              CadenceGroup (multi-rate polling)
├── mc_governance.py        MC chain (beat-aligned audio)
├── obs_governance.py       OBS chain (camera direction)
├── governor.py             PipelineGovernor (process/pause/withdraw)
├── suppression.py          SuppressionField (attack/release envelope)
├── arbiter.py              ResourceArbiter (priority-based contention)
├── feedback.py             wire_feedback_behaviors (actuation → perception)
├── chain_state.py          Cross-role state (GovernanceChainState, ConversationState)
├── speaker_id.py           SpeakerIdentifier (consent-gated)
├── timeline.py             TimelineMapping (wall-clock ↔ beat bijection)
├── musical_position.py     MusicalPosition (hierarchical beat decomposition)
├── actuation_event.py      ActuationEvent (immutable actuation record)
├── __main__.py             VoiceDaemon (wiring and lifecycle)
├── backends/               8 perception backends (PipeWire, Hyprland, MIDI, etc.)
└── ... (63 .py files total)
```
