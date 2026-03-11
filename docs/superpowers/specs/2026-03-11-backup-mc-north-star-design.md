# North Star Use Case: Backup MC

> **Status:** North Star (architectural validation target)
> **Date:** 2026-03-11
> **Purpose:** This use case is deliberately ambitious. It exists to stress-test architectural generality. If the perception layer requires specialized components to support this, the architecture isn't general enough. The goal is to find elegant, non-specialized primitives that render this problem less complex through composition.

## The Use Case

Hapax serves as a backup MC during live studio recording sessions. The operator records DAWless music (OXI One MKII, dual SP-404 MKII, MPC Live III, Elektron Digitakt II + Digitone II) while Hapax:

- Delivers **vocal throws and ad libs** with on-point timing (~20-50ms precision for samples, beat-aligned for TTS)
- Responds in **real-time to emotional cues** from fused audio-visual perception
- Operates in **music time** (beat/bar/phrase aware), not wall-clock time
- Controls **OBS recording** the studio session (transport + autonomous scene direction)
- Maintains **manual override** at every layer (dedicated MIDI triggers from performance gear)

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

### 6. External System Control
- OBS via obs-websocket: transport (start/stop recording tied to MIDI transport), scene direction (mapped from energy arc + operator state), manual override via MIDI CC
- Scene switching at perception cadence (~2.5s), not beat precision. Minimum 2 bars between cuts.

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
- `PerformanceGovernor` — fuses energy, clock, EnvironmentState, visual emotion, manual triggers into PerformanceState. Decides throw eligibility, intensity, TTS moments, OBS hints.
- Existing `PerceptionEngine` + `PipelineGovernor` unchanged — composes with, not competes with

**OBS integration:**
- `OBSDirector` — transport tied to MIDI start/stop, scene direction from arc phase + energy. Manual override via MIDI CC.

**Audio output:**
- Sample triggers → dedicated PipeWire sink (bypasses Pipecat)
- TTS ad libs → Kokoro → queued for beat-aligned playback
- Conversation TTS → existing Pipecat pipeline (unchanged)

### Integration Pattern
- MC mode activates on MIDI Start or manual trigger
- When inactive, all new components idle (zero resource cost)
- MC mode and conversation mode mutually exclusive at governor level
- All new components under `agents/hapax_voice/`

## The Architectural Question

The brainstormed design describes **7 specialized components**. If we build them as described, we've solved one use case. The real question is:

**What general-purpose primitives in perception, timing, actuation, and governance would make this use case — and others we haven't imagined — fall out of composition rather than bespoke implementation?**

Candidate abstractions to investigate:
- **Signal streams** — a unified model for heterogeneous time-series data at different cadences (audio energy at 50ms, visual emotion at 1s, MIDI clock at 1ms). What's the right abstraction?
- **Temporal reference frames** — wall-clock time vs music time vs perception time. Can these be unified or do they need explicit bridging?
- **Governance as constraint composition** — the existing PipelineGovernor and the proposed PerformanceGovernor follow the same pattern (fuse signals → apply constraints → emit decisions). Is there a general governance primitive?
- **Actuation interfaces** — sample playback, TTS, OBS commands, MIDI output are all "do something in the world." What's the general model?
- **Subscription/callback patterns** — MusicClock subscribers, PerceptionEngine subscribers, MIDI dispatch all use callback patterns. Is there a unified event bus or is that over-abstraction?

This analysis must precede implementation. The path forward is research and evaluation, not code.
