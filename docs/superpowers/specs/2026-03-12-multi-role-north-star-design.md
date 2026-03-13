# North Star Use Case: Multi-Role Studio Companion

> **Status:** North Star (architectural validation target) — supersedes [Backup MC North Star](2026-03-11-backup-mc-north-star-design.md)
> **Date:** 2026-03-12
> **Builds on:** [Perception Primitives](2026-03-11-perception-primitives-design.md), [Backup MC North Star](2026-03-11-backup-mc-north-star-design.md)
> **Purpose:** This use case exists to stress-test architectural generality. If multi-role composition requires specialized per-role components, the architecture isn't general enough. The goal is to find primitives that make multiple simultaneous roles emerge from composition rather than mode-switching.

## Why the Backup MC North Star Was Too Narrow

The original North Star validated important primitives (Behavior/Event, VetoChain/FallbackChain, TimelineMapping, Combinator, Command/Schedule) but encoded a structural limitation: **single-role operation**. The spec explicitly stated "MC mode and conversation mode mutually exclusive." This drove an architecture where roles mode-switch rather than compose — the opposite of what the operator actually needs.

The operator records hours daily. During those sessions, Hapax must simultaneously be:

- **MC** — vocal throws, ad libs, beat-aligned sample playback
- **Production assistant** — monitoring levels, managing OBS, tracking takes
- **Advisor** — answering questions about gear, technique, mix decisions
- **Conversationalist** — natural dialogue that doesn't interrupt the music
- **Knowledge resource** — recalling session history, gear specs, project context
- **Stream director** — autonomous scene switching, transport management

These roles must be available concurrently. They should compose freely unless mutually exclusive for fundamental physical reasons (e.g., two audio outputs can't occupy the same moment) or suppressed for explicitly sanctioned governance reasons.

The operator's canonical command: *"Hapax, start live recording on YouTube and take care of everything."* This decomposes across every role simultaneously.

## The Use Case

Hapax operates as a multi-role studio companion during live recording sessions. The operator performs DAWless music (OXI One MKII, dual SP-404 MKII, MPC Live III, Elektron Digitakt II + Digitone II) while Hapax runs all roles concurrently:

### Concurrent Role Composition

| Role | Trigger domain | Output resources | Cadence |
|------|---------------|-----------------|---------|
| MC | MIDI clock (beat-precise) | Audio output, operator attention | Sub-50ms |
| Production assistant | Perception tick, MIDI transport | OBS transport, notifications | ~2.5s |
| Stream director | Perception tick, energy arc | OBS scenes, overlays | ~2.5s (min 2 bars between cuts) |
| Conversationalist | Wake word, speech input | Audio output (TTS), operator attention | Event-driven |
| Advisor | Speech input (question detected) | Audio output (TTS), operator attention | Event-driven |
| Knowledge resource | Speech input (query detected) | Audio output (TTS), notifications | Event-driven |

Key observation: roles share **output resources** (audio output, OBS control, operator attention) and **input signals** (energy, emotion, transport state). The architecture must handle both sharing patterns.

### Shared Input: Already Solved

The existing Behavior/Event + Combinator model handles shared inputs correctly. Multiple governance chains wire `withLatestFrom` to the same Behavior pool with different trigger Events. Each chain samples the same emotion reading, the same energy signal, the same transport state — at its own cadence.

### Shared Output: The New Problem

Multiple governance chains can simultaneously want to:
- Play audio (MC sample vs TTS response vs notification chime)
- Switch OBS scenes (stream director vs production assistant)
- Claim operator attention (conversation vs MC hype vs advisory notification)

This requires **resource arbitration** — a pattern the current architecture lacks entirely.

## Capability Requirements

Everything from the Backup MC North Star remains valid (multi-cadence perception, music-time awareness, emotional/energy perception, dual output modality, constraint-based autonomy, external system control, MIDI I/O). The following are **additional** requirements exposed by multi-role composition.

### 1. Graduated Governance Modulation

Binary allow/deny is insufficient for multi-role composition. When the operator starts a conversation mid-performance, MC activity should **dim** (reduced frequency, lower energy threshold, no TTS ad libs) rather than halt entirely. When the conversation ends, MC should **recover** over 2-4 bars rather than snap back.

This implies a continuous suppression signal:

```
Behavior[float]  # 0.0 = fully active, 1.0 = fully suppressed
```

Each role reads suppression Behaviors from other roles. Governance chains use these as continuous modifiers on their VetoChain thresholds, not as binary gates. The suppression signal is itself a Behavior — it has a value at every point in time, it carries a watermark, it can be sampled by any Combinator.

**Suppression vs veto:** A veto blocks a single decision. Suppression modulates a role's overall activity level over time. The MC might still fire a single well-timed throw during conversation (low suppression) but not a rapid sequence (high suppression). This is a different governance primitive from the VetoChain.

### 2. Resource Arbitration

Multiple governance chains can produce Commands targeting the same physical output. The system needs a priority-based claim/release mechanism:

- **Audio output**: Conversation TTS > MC vocal throw > notification chime > ambient. Higher priority preempts or queues.
- **OBS scenes**: Stream director governs scene composition. Production assistant governs transport. Neither should clobber the other — they operate on orthogonal OBS axes (scenes vs recording state).
- **Operator attention**: Conversation holds exclusive attention. Advisory notifications are interruptible. MC operates in the background (doesn't demand attention).

Resource arbitration sits between governance output (Commands/Schedules) and executor dispatch. It is not a governance concern (governance decides what *should* happen within a role) — it is a coordination concern (what *can* happen given competing claims).

### 3. Cross-Role Awareness

Roles must read each other's state without tight coupling:

- MC governance reads conversation state (suppress during speech)
- Stream director reads MC state (cut to face cam during vocal throw)
- Conversation reads transport state (don't interrupt during recording)
- Production assistant reads all roles (holistic monitoring)

The mechanism: each governance chain publishes its current state as a `Behavior`. Other chains sample these Behaviors via their Combinators. No direct coupling — the Behavior pool is the shared medium.

### 4. Compound Goal Decomposition

"Start live recording on YouTube and take care of everything" decomposes into:

1. **Stream director**: Configure OBS scenes, start streaming to YouTube
2. **Production assistant**: Start OBS recording, monitor stream health
3. **MC**: Await MIDI transport start, then begin MC behavior
4. **Conversationalist**: Remain available for dialogue
5. **Knowledge resource**: Load session context

This is a single operator intent that activates multiple roles with inter-role dependencies (streaming must start before MC announces it). The system needs a way to express compound goals that decompose into per-role activations with ordering constraints.

### 5. Actuation as Perception (Feedback Loops)

The current pipeline is feedforward: sense → fuse → decide → act. Multi-role composition requires feedback: actuation events feed back as Behaviors/Events that other governance chains can read.

Examples:
- MC fires a vocal throw → `Event[ActuationEvent]` → stream director samples it → cuts to face cam
- Conversation starts → `Behavior[ConversationState]` → MC reads it → suppression increases
- OBS scene switches → `Event[SceneChange]` → production assistant logs it → adjusts monitoring

The Executor already produces actuation events. These need to be published back into the Behavior/Event pool — closing the loop from feedforward pipeline to reactive system.

### 6. Hierarchical Musical Time

The current flat beat/bar model is insufficient for phrase-level governance. Musical structure is hierarchical:

```
tick < beat < bar < phrase (4-8 bars) < section (16-32 bars)
```

MC governance decisions operate at different levels of this hierarchy:
- **Beat**: sample trigger timing
- **Bar**: TTS hold-and-release points
- **Phrase**: energy arc evolution, throw density ceiling
- **Section**: overall MC character (hype vs laid-back)

TimelineMapping handles beat ↔ wall-clock. The hierarchy above beat is a separate concern: bar = beat / beats_per_bar, phrase = bar / bars_per_phrase. These are pure arithmetic on TimelineMapping output — they don't need new primitives, but governance chains need configurable hierarchical position awareness.

## What This North Star Validates

If the architecture can support all six concurrent roles with graceful interference management, then:

1. **Graduated modulation** proves governance operates on a continuous spectrum, not binary gates
2. **Resource arbitration** proves the Command/Executor boundary supports coordination across chains
3. **Cross-role awareness** proves the Behavior pool is a sufficient medium for inter-chain communication
4. **Compound goals** prove the system can decompose high-level intent into multi-domain activations
5. **Feedback loops** prove the pipeline can close into a reactive loop
6. **Hierarchical time** proves TimelineMapping composes with higher-level musical structure

Each of these either validates an existing primitive's generality or identifies a new primitive that the architecture needs.

## New Primitives Required

The existing 10-primitive type system (Section 1 of [Perception Primitives](2026-03-11-perception-primitives-design.md)) needs extension:

| New primitive | Class | Role |
|--------------|-------|------|
| `SuppressionField` | Perceptive | Continuous modulation signal (0.0–1.0) between roles |
| `ResourceClaim` | Directive | Priority-tagged output claim with preemption semantics |
| `ResourceArbiter` | Detective | Resolves competing claims on shared output resources |
| `CompoundGoal` | Directive | Decomposable intent → per-role activation sequence |

These are detailed in the [Multi-Role Composition Design](2026-03-12-multi-role-composition-design.md).

## The Architectural Question (Revised)

The original question was: "What general-purpose primitives would make the backup MC fall out of composition?"

The answer (Behavior, Event, Watermark, TimelineMapping, Combinator, VetoChain, FallbackChain, FreshnessGuard, Command, Schedule) was validated by implementation. But those primitives assumed a single governance chain operating in isolation.

The revised question is:

**What composition patterns between governance chains — sharing inputs, arbitrating outputs, modulating each other's activity — would make simultaneous multi-role operation fall out naturally rather than requiring per-role orchestration logic?**

The answer should extend the existing primitive type system minimally. If a new primitive can be expressed as composition of existing primitives, it should be. If it cannot, it reveals a genuine gap in the type system.

## Relation to Brooks' Subsumption

The multi-role structure maps to Brooks' subsumption architecture:

```
Layer 0: Production assistant (base competence — always running, monitors everything)
Layer 1: Stream director (subsumes scene decisions from Layer 0)
Layer 2: MC (subsumes audio output from Layers 0-1 during performance)
Layer 3: Conversationalist (suppresses Layer 2 during dialogue, subsumes audio output)
```

Higher layers suppress lower layers via the `SuppressionField` mechanism. Each layer is independently functional — removing the conversationalist leaves MC + production + streaming fully operational. This is Brooks' "layers of competence" property: the system degrades gracefully by shedding higher layers.

The key difference from classical subsumption: suppression is **graduated**, not binary. Layer 3 doesn't hard-inhibit Layer 2 — it dims it. The continuous SuppressionField is the mechanism for this graduated inhibition.
