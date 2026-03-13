# hapax_voice — Perception, Governance, and Actuation for Voice

An always-on voice interaction daemon that fuses signals arriving at vastly different rates — MIDI clock ticks at sub-millisecond precision, audio energy at 50ms, emotion classification at 1–2 seconds, workspace analysis at 10–15 seconds — into governance decisions that control physical actuators (audio playback, OBS camera direction, TTS synthesis) without losing data or correctness.

The system is organized around three type-theoretic layers — **Perceptives**, **Detectives**, and **Directives** — that decompose the perception→decision→action pipeline into composable, auditable primitives. The layering is not a convenience abstraction. It is the mechanism by which constitutional axioms are enforced at the type level, governance decisions carry full provenance, and the gap between describing an action and executing it becomes the site where safety constraints live.

## The Multi-Cadence Problem

Voice interaction systems face a temporal fusion problem that most architectures solve by either (a) downsampling everything to the slowest rate, losing precision, or (b) running everything at the fastest rate, wasting computation and introducing false coupling between independent signals. Neither is acceptable when beat-aligned audio playback requires sub-50ms precision while workspace analysis involves a 12-second LLM call.

The solution draws from three research traditions:

**Functional reactive programming** (Yampa, Reflex, RxPY). The `Behavior[T]`/`Event[T]` duality separates continuously-available state (a cell that always has a current reading) from discrete occurrences (a MIDI tick, a wake word detection). The `with_latest_from` combinator — borrowed directly from Rx — enables fast events to sample slow behaviors at their current values without blocking or polling. When a MIDI clock tick fires at <1ms precision, it samples emotion (which may be 2 seconds old) at whatever value it currently holds. The watermark on each `Behavior` tracks how old that value is, and the `FreshnessGuard` downstream can reject decisions made on data that's too stale.

**DSP audio synthesis** (modular synthesis, control voltage). Suppression fields use attack/release envelopes — the same temporal smoothing used in audio compressors — to ramp governance thresholds up and down without discontinuities. A conversation detected by VAD doesn't instantly slam the MC governance chain to zero; it smoothly raises the energy threshold over the attack time, and releases it over a longer decay. This prevents the system from oscillating between states when signals are noisy.

**Distributed systems** (watermarks, monotonic clocks, exactly-once delivery). Every `Behavior` enforces a monotonic watermark — updates with regressing timestamps are rejected. Every `Command` carries the minimum watermark of the perception data that informed it, enabling downstream systems to reason about how fresh the decision was. The `FusedContext` computed by `with_latest_from` records the stalest signal in `min_watermark`, giving the `FreshnessGuard` a single number to check. This is the same pattern used in stream processing systems (Flink, Dataflow) adapted for a single-machine, in-process runtime.

## Type System

### Layer 1: Perceptives — Signal Abstractions

Perceptives represent the raw material of perception: values that change over time.

**`Behavior[T]`** (`primitives.py`) — A continuously-available value with a monotonic watermark. `sample()` never fails; it always returns a `Stamped[T]` containing the current value and its timestamp. `update(value, timestamp)` advances the value forward; it raises `ValueError` if the timestamp regresses. This is the core abstraction for slow-changing state: emotion arousal, workspace context, stream health, operator presence. The monotonicity invariant means that downstream consumers can trust that a sampled value was produced at or after the reported time.

**`Event[T]`** (`primitives.py`) — A discrete occurrence with pub/sub semantics. `emit(timestamp, value)` fires all subscribers; exceptions in one subscriber do not prevent delivery to others. Late subscribers receive no history — events are ephemeral. This models MIDI clock ticks, wake word detections, governance chain outputs, and actuation completions.

**`Stamped[T]`** (`primitives.py`) — An immutable snapshot: a value frozen at a moment in time. This is the common currency between Behaviors and Events. When `with_latest_from` samples a Behavior, it gets a `Stamped`. When a FusedContext records its samples, each is a `Stamped`. Immutability prevents TOCTOU (time-of-check-to-time-of-use) bugs between governance evaluation and actuation.

### Layer 2: Detectives — Governance Composition

Detectives evaluate whether a proposed action should proceed. They compose into pipelines where safety constraints are structurally guaranteed.

**`VetoChain[C]`** (`governance.py`) — A set of `Veto` predicates evaluated over a context `C`. The chain is **deny-wins**: any single veto denial blocks the action. Evaluation is **exhaustive** — all vetoes run regardless of earlier denials, producing a complete `VetoResult` for audit. Chains compose via `|` (concatenation). The critical property: **adding a veto to a chain can only make the system more restrictive, never less**. This monotonicity means governance changes are safe by construction — you cannot accidentally widen permissions by adding a constraint.

Each `Veto` optionally tags the axiom it enforces (e.g., `axiom="executive_function"`), linking runtime governance decisions back to constitutional principles.

**`FallbackChain[C, T]`** (`governance.py`) — A priority-ordered sequence of `Candidate` entries, each with a predicate and an action. `select(context)` returns the first candidate whose predicate passes. The chain always has a default (the last entry), ensuring graceful degradation — the system always has something to do. Candidates can carry nested `VetoChain` instances for fine-grained gating. Chains compose via `|`, with the left chain's default taking precedence.

**`FreshnessGuard`** (`governance.py`) — Rejects decisions made on stale perception data. Each `FreshnessRequirement` specifies a behavior name and a maximum staleness in seconds. `check(context, now)` evaluates all watermarks against thresholds and returns a `FreshnessResult` with violation details. The fail-safe default is `fresh_enough=False` — if freshness cannot be determined, the decision is rejected. This prevents the system from acting on perception data that no longer reflects reality.

**`FusedContext`** (`governance.py`) — The output of `with_latest_from`: a trigger event fused with current Behavior samples. Carries `trigger_time`, `trigger_value`, a read-only `samples` dict of `Stamped` values, and `min_watermark` (the stalest signal). This is the universal input to governance chains — it contains everything a VetoChain or FallbackChain needs to make a decision.

### The Combinator

**`with_latest_from(trigger: Event, behaviors: dict[str, Behavior]) → Event[FusedContext]`** (`combinator.py`)

The single combinator that bridges Perceptives to Detectives. When the trigger event fires, it samples all behaviors at their current values and emits a `FusedContext`. This is how MIDI-rate decisions incorporate second-scale perception: the MIDI tick is the trigger, the behaviors are emotion, energy, timeline mapping, and suppression state. The combinator computes `min_watermark` as the stalest signal, which flows into the `FreshnessGuard`.

The naming follows Rx convention. The semantics are: "when this event happens, what does the world look like right now?"

### Layer 3: Directives — Action Descriptions with Provenance

Directives are not actions — they are descriptions of actions that carry the full governance trail of how they were selected. The gap between describing an action and executing it is where governance lives.

**`Command`** (`commands.py`) — An immutable data object recording: what action was selected (`action`, `params`), what governance evaluation produced it (`governance_result: VetoResult`, `selected_by`), which trigger caused it (`trigger_time`, `trigger_source`), and the minimum watermark of the perception data that informed it (`min_watermark`). A denied Command carries its `VetoResult` as provenance. An Executor can inspect it. The system never constructs a Command without a governance trail.

**`Schedule`** (`commands.py`) — A Command bound to a specific time in a specific domain. `domain="beat"` means the target time is a beat number; `domain="wall"` means wall-clock. `wall_time` is the resolved wall-clock time (via `TimelineMapping`), and `tolerance_ms` specifies how late execution can be before the schedule is discarded. This bridges Detective output (a governance decision at the conceptual level) to Directive execution (a physical actuator at a precise time).

### Actuation

**`Executor`** (`executor.py`, Protocol) — The interface for physical actuators. Each Executor declares a `name`, a `frozenset` of action strings it `handles`, an `available()` check, and an `execute(command)` method. The Protocol mirrors `PerceptionBackend` — availability-gated registration, clean shutdown, pluggable implementation.

**`ExecutorRegistry`** (`executor.py`) — Routes Commands to the correct Executor by action name. On successful dispatch, emits an `ActuationEvent` on a shared `Event[ActuationEvent]` stream, recording action, chain, wall time, target time, and latency. This event feeds back into perception Behaviors, closing the loop.

**`ScheduleQueue`** (`executor.py`) — A priority queue ordered by `wall_time`. `drain(now)` returns all schedules whose time has arrived, discards those past their tolerance window, and leaves future schedules in place. This enables beat-precise actuation: the MC governance chain emits Schedules at beat positions, and the actuation loop drains them at the right wall-clock moment.

## Governance Chains

### MC Governance — Beat-Aligned Audio Actuation

The MC (backup microphone) governance chain controls audio sample playback for music production — vocal throws, ad-libs, and silence — synchronized to MIDI transport.

```
Event[MidiTick] → with_latest_from(behaviors) → Event[FusedContext]
  → FreshnessGuard.check(energy: 200ms, emotion: 3s, timeline: 500ms)
  → VetoChain: pipeline_active ∧ speech_clear ∧ energy_sufficient ∧ spacing_respected ∧ transport_active
  → FallbackChain: vocal_throw | ad_lib | silence (default)
  → Schedule(domain="beat", target_time=next_beat)
```

**Veto predicates** (module-level for testability): `speech_clear` gates on VAD confidence (don't fire over someone talking), `energy_sufficient` checks RMS against an effective threshold modulated by `SuppressionField` (conversation suppression raises the bar), `spacing_respected` enforces cooldown between firings (4s default), `transport_active` requires MIDI transport to be PLAYING.

**Source**: `mc_governance.py`

### OBS Governance — Camera Direction

The OBS governance chain selects livestream camera scenes (wide ambient, gear closeup, face cam, rapid cut, hold) and transitions (cut, dissolve, fade) based on audio energy, stream health, and MC feedback.

```
Event[PerceptionTick] → with_latest_from(behaviors) → Event[FusedContext]
  → FreshnessGuard.check(energy: 3s, emotion: 5s, stream_health: 10s)
  → VetoChain: pipeline_active ∧ dwell_time_respected ∧ stream_health_sufficient ∧ encoding_capacity ∧ transport_active
  → FallbackChain: rapid_cut | face_cam (mc_bias) | face_cam | gear_closeup | wide_ambient (default)
  → Command(action=scene, params={transition: select_transition(energy)})
```

Cross-chain feedback: if `last_mc_fire` (a feedback Behavior) indicates the MC chain fired within 2 seconds, the OBS chain biases toward `face_cam` via a boosted candidate — the camera should be on the performer when audio just fired.

**Source**: `obs_governance.py`

### Pipeline Governor — Perception-Level Directive

The `PipelineGovernor` (`governor.py`) operates at a higher level than MC or OBS, determining whether the voice pipeline should be active at all. It evaluates `EnvironmentState` (the fused perception snapshot) and returns a directive: `"process"` (pipeline runs normally), `"pause"` (frame gate drops audio), or `"withdraw"` (session should close).

Internally uses VetoChain + FallbackChain with axiom compliance checking: workspace context (from slow-tick LLM analysis) is matched against `management_governance` T0 implications to prevent the system from processing audio in contexts where it might generate feedback or coaching language about individuals. Wake word detection overrides both chains (supremacy flag with 3-tick grace period).

## Cross-Chain Coordination

### Suppression Fields

`SuppressionField` (`suppression.py`) implements smooth-ramping threshold modulation using attack/release envelopes. When a conversation is detected, the field's target is set high; `tick(now)` advances the current value toward the target using the attack rate (fast ramp up) or release rate (slow ramp down).

The `effective_threshold` function adjusts a base threshold by suppression level: `threshold_eff = base + suppression * (1.0 - base)`. At suppression=0 the threshold is unchanged; at suppression=1.0 it reaches 1.0 (impossible to satisfy), fully suppressing the governed chain. This provides graceful degradation rather than binary on/off switching.

### Resource Arbiter

`ResourceArbiter` (`arbiter.py`) resolves contention when multiple governance chains claim the same physical resource (e.g., both MC and OBS want audio output). Claims carry static priorities configured in `resource_config.py`. `drain_winners(now)` selects one winner per resource (highest priority, FIFO tie-breaking), garbage-collects expired holds, and removes one-shot claims after winning.

### Feedback Loop

`wire_feedback_behaviors()` (`feedback.py`) subscribes to the `ExecutorRegistry`'s `actuation_event` stream and maintains four Behaviors: `last_mc_fire` (wall time of last MC actuation), `mc_fire_count` (running count), `last_obs_switch` (last OBS scene change), and `last_tts_end` (last TTS completion). These Behaviors are included in the fused context of governance chains, enabling feedback-driven decisions: MC's `spacing_respected` veto reads `last_mc_fire` for cooldown, OBS's `_mc_fired_recently` reads it for camera bias.

This closes the reactive loop: perception → governance → actuation → feedback → perception.

## Perception Infrastructure

### PerceptionEngine

`PerceptionEngine` (`perception.py`) produces `EnvironmentState` snapshots by fusing registered backends. It runs at two cadences: a fast tick (2.5s) that polls FAST and EVENT-tier backends (VAD, face detection, window state), and a slow enrichment tick (12s) that polls SLOW-tier backends (workspace analysis via LLM, circadian alignment).

`EnvironmentState` is a frozen dataclass carrying: audio signals (speech detected, VAD confidence), visual signals (face count, operator present, presence score), desktop topology (active window, workspace), voice session state, and an interruptibility score computed from VAD, activity mode, physiological load, circadian alignment, and system health.

### Perception Backends

Each backend implements the `PerceptionBackend` protocol: declares a `name`, `provides` (behavior names), `tier` (FAST/SLOW/EVENT), and `contribute(behaviors)` method. Eight backends in `backends/`:

| Backend | Tier | Signals | Source |
|---------|------|---------|--------|
| `PipeWireBackend` | FAST | Audio energy (RMS, peak), emotion (arousal, valence) | PipeWire audio graph |
| `HyprlandBackend` | EVENT | Active window, workspace, window count | Hyprland IPC socket |
| `WatchBackend` | SLOW | Heart rate, HRV, stress estimate | Wearable API |
| `HealthBackend` | FAST | CPU, RAM, temperature, GPU utilization | `/proc`, `nvidia-smi` |
| `CircadianBackend` | SLOW | Circadian phase, alignment score | Time-of-day model |
| `MidiClockBackend` | FAST | MIDI tick events, transport state, tempo | ALSA MIDI |
| `StreamHealthBackend` | SLOW | Bitrate, encoding lag, dropped frames | OBS WebSocket |

### CadenceGroup

`CadenceGroup` (`cadence.py`) groups backends that share a polling interval. Each group has its own `tick_event: Event[float]` emitted after each poll cycle. This enables per-cadence combinator wiring: `with_latest_from(group.tick_event, behaviors)` triggers governance evaluation at the group's natural rate rather than at a fixed global rate. Different governance chains wire to different cadence groups based on their temporal requirements.

### Multi-Source Wiring

`WiringConfig` (`wiring.py`) maps physical sources (identified by `source_id` like `"monitor_mix"` or `"mic_input"`) to backend instances and cadence groups. `GovernanceBinding` maps bare governance behavior names (like `audio_energy_rms`) to source-qualified names (like `audio_energy_rms:monitor_mix`), allowing governance chains to be written against abstract signal names while the wiring layer resolves them to specific physical sources. `build_behavior_alias()` constructs the alias dict. Aggregation functions (`aggregate_max`, `aggregate_mean`, `aggregate_any`) derive synthetic behaviors from multiple sources.

## Musical Semantics

**`TimelineMapping`** (`timeline.py`) — A bijective affine map between wall-clock time and beat time. Given a reference point (time, beat) and a tempo (BPM), `beat_at_time(t)` and `time_at_beat(b)` are pure arithmetic with no I/O. Transport state (PLAYING/STOPPED) freezes the mapping. This enables the MC governance chain to emit Schedules in beat-domain time and the actuation loop to resolve them to wall-clock for precise playback.

**`MusicalPosition`** (`musical_position.py`) — Hierarchical decomposition of a global beat number into bar, beat-in-bar, phrase, bar-in-phrase, section, and phrase-in-section (assuming 4/4 time, 4-bar phrases, 4-phrase sections). This enables musically-aware governance: fire on downbeats, avoid mid-phrase interruptions, respect section boundaries.

## Consent and Speaker Identity

`SpeakerIdentifier` (`speaker_id.py`) performs speaker identification via embedding cosine similarity — not for authentication (single-user axiom), but for routing (operator vs. guest vs. uncertain). The `identify_audio()` and `enroll()` methods accept optional `person_id` and `consent_registry` parameters. For non-operator persons, the `ConsentRegistry` must have an active contract covering the `"biometric"` data category before embeddings are processed or persisted. Without a contract, identification returns `uncertain` and enrollment raises `ValueError`.

This enforces the `interpersonal_transparency` axiom (weight 88) at the perception boundary — before embeddings are extracted, before state is persisted, before any downstream processing occurs.

## Daemon Lifecycle

`VoiceDaemon` (`__main__.py`, ~1000 lines) orchestrates all subsystems:

**Initialization**: Creates SessionManager, PresenceDetector, ContextGate, NotificationQueue, HotkeyServer (Unix socket), WakeWordDetector (Porcupine or OpenWakeWord), AudioInputStream, TTSManager, ChimePlayer, WorkspaceMonitor, PerceptionEngine, PipelineGovernor, FrameGate, ConsentRegistry, and ResourceArbiter. Registers perception backends (availability-gated — missing hardware degrades gracefully). Wires feedback behaviors and governance chains.

**Async loops** (concurrent via `asyncio.gather`):
- `_audio_loop()` — distributes 30ms audio frames to wake word detector (exact chunk sizes), VAD (512 samples), and Gemini Live session
- `_perception_loop()` — fast tick (2.5s): poll backends, compute EnvironmentState, evaluate PipelineGovernor, apply directive to FrameGate
- `_actuation_loop()` — drain ScheduleQueue at beat precision, route through ResourceArbiter, dispatch via ExecutorRegistry
- `_wake_word_processor()` — awaits wake word detection, atomically starts session and pipeline
- `_proactive_delivery_loop()` — checks notification queue when operator is present and interruptible

**Pipeline backends**: `"local"` (Pipecat: STT → LLM → TTS with LocalAudioTransport) or `"gemini"` (Gemini Live speech-to-speech session).

## Package Structure

```
agents/hapax_voice/
├── primitives.py           Behavior[T], Event[T], Stamped[T]
├── governance.py           VetoChain, FallbackChain, FreshnessGuard, FusedContext
├── combinator.py           with_latest_from combinator
├── commands.py             Command, Schedule (immutable directives)
├── executor.py             Executor protocol, ExecutorRegistry, ScheduleQueue
├── perception.py           PerceptionBackend protocol, PerceptionEngine, EnvironmentState
├── wiring.py               WiringConfig, GovernanceBinding, multi-source aliases
├── cadence.py              CadenceGroup (multi-rate polling)
├── mc_governance.py        MC chain composition (beat-aligned audio)
├── obs_governance.py       OBS chain composition (camera direction)
├── governor.py             PipelineGovernor (process/pause/withdraw)
├── suppression.py          SuppressionField (attack/release envelope)
├── arbiter.py              ResourceArbiter (priority-based contention)
├── resource_config.py      RESOURCE_MAP, DEFAULT_PRIORITIES
├── feedback.py             wire_feedback_behaviors (actuation → perception)
├── chain_state.py          GovernanceChainState, ConversationState, cross-role Behaviors
├── speaker_id.py           SpeakerIdentifier (consent-gated biometric)
├── timeline.py             TimelineMapping (wall-clock ↔ beat bijection)
├── musical_position.py     MusicalPosition (hierarchical beat decomposition)
├── actuation_event.py      ActuationEvent (immutable actuation record)
├── __main__.py             VoiceDaemon (daemon wiring and lifecycle)
├── backends/
│   ├── pipewire.py         PipeWire audio energy + emotion
│   ├── hyprland.py         Hyprland window/workspace (IPC)
│   ├── watch.py            Wearable health signals
│   ├── health.py           System health (CPU, RAM, GPU, temp)
│   ├── circadian.py        Circadian rhythm alignment
│   ├── midi_clock.py       MIDI clock ticks + transport state
│   └── stream_health.py    OBS stream health (bitrate, lag, drops)
└── ... (63 .py files total)
```
