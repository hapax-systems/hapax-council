# North Star Use Case: Backup MC + Livestream Director

> **Status:** North Star (architectural validation target)
> **Date:** 2026-03-11 (expanded 2026-03-12)
> **Purpose:** This use case is deliberately ambitious. It exists to stress-test architectural generality. If the perception layer requires specialized components to support this, the architecture isn't general enough. The goal is to find elegant, non-specialized primitives that render this problem less complex through composition.

## The Use Case

Hapax serves as backup MC and livestream director during live studio recording sessions. The operator records DAWless music (OXI One MKII, dual SP-404 MKII, MPC Live III, Elektron Digitakt II + Digitone II) while simultaneously streaming to an audience. Hapax:

- Delivers **vocal throws and ad libs** with on-point timing (~20-50ms precision for samples, beat-aligned for TTS)
- Responds in **real-time to emotional cues** from fused audio-visual perception
- Operates in **music time** (beat/bar/phrase aware), not wall-clock time
- **Directs the livestream** — scene switching, transitions, overlays, camera selection, all driven by the same perception signals that drive MC behavior
- **Monitors stream health** — bitrate, dropped frames, chat activity — as additional perception signals
- Maintains **manual override** at every layer (dedicated MIDI triggers from performance gear)

The MC and livestream director roles are two actuation domains consuming the same perception signals through different governance chains. This is the architectural validation: if the primitives are right, adding a second actuation domain should be composition, not new infrastructure.

Genre context: boom bap, lo-fi hip-hop, experimental (JPEGMAFIA / JJ DOOM aesthetic). 85-100 BPM typical range.

## Capability Requirements

This use case implies the system must have:

### 1. Multi-Cadence Perception
- **Sub-50ms** — audio energy (RMS, spectral, onset density) for beat-level responsiveness
- **~100ms** — trigger eligibility decisions synchronized to musical grid
- **~1-2s** — visual emotion (body language, arousal/valence from webcam, IR preferred for studio lighting)
- **~2.5s** — environment state (existing perception engine cadence)
- **~bar cadence** — energy arc phase (building/peak/sustain/dropping/silence)

The system must support concurrent signal streams at different cadences without coupling them.

### 2. Music-Time Awareness
- MIDI clock reception (24 ppqn from OXI One via ALSA/snd-virmidi)
- Bar.beat.tick position tracking with configurable time signature
- Transport state (start/stop/continue)
- Audio BPM estimation fallback when no MIDI clock present
- Musical position subscriptions ("call me on beat 4 of every 4th bar")

### 3. Emotional/Energy Perception
- **Audio energy analysis** — RMS level, spectral centroid, onset density, delta RMS (rate of change), smoothed energy curve (0.0–1.0)
- **Energy arc detection** — building/peak/sustain/dropping/silence derived from delta trends over multi-bar windows
- **Visual operator state** — arousal (low→high energy), valence (negative→positive), motion magnitude (stillness vs movement). Continuous dimensions, not fixed taxonomy. IR camera as preferred source for lighting-independent tracking.
- **Mood as continuous vector** — not a fixed enum. Open-ended for future articulation.

### 4. Dual Output Modality
- **Sample bank** — pre-loaded PCM samples (44.1kHz 16-bit WAV, SP-404 compatible) organized by function (throw/ad lib/hype/fill) and energy tag. Direct PipeWire output for minimal latency.
- **TTS synthesis** — Kokoro for contextual ad libs. Longer latency acceptable (~500ms-1s) because output is held and released at next musically appropriate position.

### 5. Constraint-Based Autonomy
Same pattern as axiom governance — rules set boundaries, autonomy operates within them:
- No throws when speech detected (don't talk over conversation)
- No throws when operator disengaged
- Minimum spacing between throws (configurable, default 2 beats)
- Maximum throws per phrase (configurable ceiling)
- Energy matching (high-energy samples only above energy threshold)
- Manual trigger overrides all constraints except speech detection
- MC mode and conversation mode mutually exclusive

### 6. Livestream Direction (OBS via obs-websocket)

The operator performs; Hapax directs the broadcast. OBS is not a sidecar — it's a co-equal actuation domain alongside MC throws.

**Transport coupling:**
- Recording start/stop tied to MIDI transport (existing)
- Stream start/stop as separate Command — operator may record without streaming or vice versa

**Scene composition and switching:**
- Multiple camera angles (overhead gear view, face cam, wide room, detail cam on hands)
- Scene selection driven by energy arc phase: silence → wide/ambient, building → gear closeup, peak → face cam or rapid cuts, sustain → alternating, dropping → wide pullback
- Transition style mapped to energy: hard cuts at high energy, dissolves/fades at low energy
- Minimum dwell time per scene (configurable, default 2 bars). Same spacing primitive as MC throw cooldown — this is a governance constraint, not a scene-switching primitive.
- Scene switching at perception cadence (~2.5s), not beat precision. Beat-aligned cuts only during peak energy (optional, operator-configurable).

**Overlays and lower thirds:**
- Song/session title overlay on stream start
- BPM display (from TimelineMapping, already a Behavior)
- Energy arc visualization (optional, from existing perception)
- "Now playing" gear identification (from operator state or manual preset)
- Overlays as Behaviors — current overlay state sampled by the OBS actuation layer

**Stream health as perception:**
- OBS stats (bitrate, dropped frames, encoding lag, stream uptime) polled as a SLOW-cadence backend
- Provides: `stream_bitrate`, `stream_dropped_frames`, `stream_encoding_lag`
- Degraded stream health → veto scene transitions that increase encoding cost (e.g., rapid cuts → dissolves, overlays reduced)
- Stream failure → operator notification via existing ntfy channel

**Chat integration (future, not MVP):**
- Chat messages as an Event stream at message cadence
- Chat sentiment as a SLOW-cadence Behavior (aggregated over window)
- Chat hype detection could feed into MC throw intensity — audience energy as a perception signal
- Explicit opt-in only. Constitutional: single_user axiom means chat never drives governance, only provides advisory signal.

**Manual override:**
- Dedicated MIDI CC for scene forcing (same pattern as MC manual trigger)
- Scene lock: hold CC to prevent autonomous switching
- All autonomous decisions yield to manual input

### 7. MIDI I/O
- Inbound: clock, transport, manual trigger notes/CCs from performance gear
- Configurable CC/note → action mappings
- ALSA backend via snd-virmidi virtual ports
- Future: outbound MIDI for triggering external gear samples or parameter automation

## Brainstormed Design (Reference)

The following design emerged from collaborative brainstorming. It is preserved as a reference for what a direct implementation might look like — but the actual implementation goal is to find general-purpose primitives that make this design emerge from composition.

### Dual-Domain Architecture

**Music-time domain** (beat-precise):
- `MidiRouter` — ALSA MIDI listener, dispatches clock/triggers to subscribers
- `MusicClock` — bar.beat.tick position, BPM, transport from MIDI clock. Audio BPM fallback.
- `TriggerScheduler` + `SampleBank` — pre-loaded samples fired at beat-aligned positions via dedicated PipeWire sink. TTS ad libs synthesized by Kokoro, held and released at next musically appropriate position.

**Perception domain** (feel/context):
- `EnergyAnalyzer` — 50ms windows on monitor audio: RMS, spectral centroid, onset density, arc phase
- `EmotionClassifier` — webcam (IR preferred) body language: arousal/valence/motion at ~1-2s via MediaPipe
- `PerformanceGovernor` — fuses energy, clock, EnvironmentState, visual emotion, manual triggers into PerformanceState. Decides throw eligibility, intensity, TTS moments, scene hints.
- Existing `PerceptionEngine` + `PipelineGovernor` unchanged — composes with, not competes with

**Livestream direction:**
- `OBSDirector` — consumes the same perception Behaviors as MC governance through a separate governance chain. Scene selection from arc phase + energy. Transition style from energy level. Overlay state from operator state + stream metadata. Transport coupling to MIDI start/stop + independent stream control.
- `StreamHealthBackend` — SLOW-cadence backend polling OBS stats. Provides `stream_bitrate`, `stream_dropped_frames`, `stream_encoding_lag` as Behaviors. Degradation triggers governance constraints on scene complexity.

**Audio output:**
- Sample triggers → dedicated PipeWire sink (bypasses Pipecat)
- TTS ad libs → Kokoro → queued for beat-aligned playback
- Conversation TTS → existing Pipecat pipeline (unchanged)

### Two Governance Chains, One Perception Layer

The MC and livestream director share perception but have independent governance:

```
                    ┌─── MC Governance ──────────────────────┐
                    │ trigger → with_latest_from → Freshness │
Perception ────────►│ → VetoChain → FallbackChain → Schedule │──► Audio Actuation
(shared Behaviors)  └───────────────────────────────────────┘
        │
        │           ┌─── OBS Governance ─────────────────────┐
        │           │ tick → with_latest_from → Freshness    │
        └──────────►│ → VetoChain → FallbackChain → Command  │──► OBS Actuation
                    └───────────────────────────────────────┘
```

Both chains consume the same Behaviors (energy, emotion, timeline, operator state). Both use VetoChain for constraint enforcement and FallbackChain for decision selection. The difference is:
- MC governance produces Schedules (beat-aligned future actions)
- OBS governance produces Commands (immediate actuation at perception cadence)
- MC vetoes are about speech, spacing, energy thresholds
- OBS vetoes are about dwell time, stream health, encoding capacity

This is the validation: if the primitives are general, the second chain is wiring, not new infrastructure.

### Integration Pattern
- MC mode activates on MIDI Start or manual trigger
- Stream mode independent of MC mode (can stream without MC, MC without streaming, or both)
- When inactive, all new components idle (zero resource cost)
- MC mode and conversation mode mutually exclusive at governor level
- All new components under `agents/hapax_voice/`

## The Architectural Question

The brainstormed design describes **two actuation domains** (MC + livestream) consuming a **shared perception layer** through **independent governance chains**. If we need domain-specific primitives to support either one, the architecture isn't general enough. The real question is:

**What general-purpose primitives in perception, timing, actuation, and governance would make both use cases — and others we haven't imagined — fall out of composition rather than bespoke implementation?**

Candidate abstractions to investigate:
- **Signal streams** — a unified model for heterogeneous time-series data at different cadences (audio energy at 50ms, visual emotion at 1s, MIDI clock at 1ms, OBS stats at 5s). What's the right abstraction?
- **Temporal reference frames** — wall-clock time vs music time vs perception time. Can these be unified or do they need explicit bridging?
- **Governance as constraint composition** — MC governance and OBS governance follow the same pattern (fuse signals → apply constraints → emit decisions) with different predicates and thresholds. VetoChain, FallbackChain, FreshnessGuard are already domain-agnostic. Is that sufficient?
- **Actuation interfaces** — sample playback, TTS, OBS scene commands, OBS overlay updates, MIDI output are all "do something in the world." What's the general model? Schedule (beat-aligned future) vs Command (immediate) covers the timing axis. What about fire-and-forget vs confirmed?
- **Subscription/callback patterns** — MusicClock subscribers, PerceptionEngine subscribers, MIDI dispatch, OBS event callbacks all use callback patterns. Is there a unified event bus or is that over-abstraction?

### Validation Criteria

The architecture passes validation when:
1. Adding a new actuation domain (e.g., lighting control, MIDI parameter automation) requires only new governance predicates and actuation adapters — no new primitives
2. The same Behavior can be consumed by multiple governance chains without coordination
3. Stream health degrades a governance chain's aggressiveness through the same constraint mechanism (VetoChain) used for MC spacing and speech detection
4. Manual override works identically across domains (MIDI CC → veto bypass → Command/Schedule)

### Progress

This analysis has been partially implemented:
- **Perceptives** (Behavior, Event, Stamped, TimelineMapping, CadenceGroup) — implemented
- **Detectives** (with_latest_from, VetoChain, FallbackChain, FreshnessGuard) — implemented
- **Directives** (Command, Schedule) — implemented
- **MC governance composition** — implemented with systematic trinary testing matrices
- **OBS governance composition** — not yet implemented (next validation target)
- **Stream health backend** — not yet implemented
- **OBS actuation adapter** — not yet implemented
