# Hapax Voice — Voice-First Modality Design

**Goal:** Make voice interaction a first-class modality on the workstation — speech in, speech out, interruptions, proactive system-initiated conversations, and ambient presence awareness.

**Architecture:** Persistent daemon (`hapax-voice`) orchestrated by Pipecat with dual backends: Gemini 2.5 Flash Native Audio (primary, quality-first) and local cascaded pipeline (fallback, full tool access). Intent router classifies utterances and selects backend. Presence detection and context gating enable proactive speech. Speaker identification distinguishes the operator from visitors.

**Tech Stack:** Pipecat, Gemini Live API, NVIDIA Parakeet TDT 0.6B (STT), Kokoro 82M (TTS), Piper (lightweight TTS), Silero VAD, OpenWakeWord, pyannote (speaker embedding), PipeWire echo cancellation, systemd user service.

---

## 1. System Architecture Overview

Hapax Voice is a persistent daemon running as a systemd user service with four subsystems:

1. **Voice Conversation Engine** — Pipecat-orchestrated dual-backend voice interaction
2. **Presence Detector** — lightweight real-time occupancy sensing via the always-on mic
3. **Proactive Speech Engine** — system-initiated spoken notifications and conversations
4. **Intent Router** — classifies utterances as conversational vs system-directed, routes to appropriate backend

### Process Model

Single Python process, always running. Shares the Blue Yeti mic with the ambient audio recorder via PipeWire (multiple consumers, no exclusive lock). Audio output through system speakers. PipeWire echo cancellation sits between mic and the voice engine.

### Session Lifecycle

- Daemon starts at login, loads models (VAD, wake word, TTS), establishes no active session
- Wake word ("Hapax") or hotkey opens a **conversation session**
- Session stays open until explicit dismissal ("that's all", "thanks Hapax"), timeout (30s silence), or hotkey toggle
- Between sessions, only wake word detection and presence monitoring are active (minimal resource use)
- Proactive speech can open a session too — presence verified first, then Hapax speaks, response loop is the same as user-initiated

### VRAM Budget

- Idle: ~3-5GB (Kokoro TTS + wake word ONNX on CPU)
- Active Gemini Live session: ~0GB GPU (cloud)
- Active local fallback session: ~8-10GB (Parakeet STT + Kokoro TTS)
- Sequential with ambient audio processor (~8GB peak, runs every 30 min for ~5-7 min)

---

## 2. Voice Conversation Engine

Pipecat pipeline with two switchable backends behind a common audio transport layer.

### Audio I/O

- Input: Blue Yeti via PipeWire (through echo-cancelled virtual source)
- Output: System speakers via PipeWire
- Transport: Pipecat's `LocalAudioTransport` (PyAudio/PortAudio)

### Primary Path — Gemini Live

- Gemini 2.5 Flash Native Audio via WebSocket
- Speech-to-speech: audio in, audio out, no intermediate text
- Native interruption support (Gemini handles turn-taking)
- Latency: ~300-600ms
- Cost: ~$0.15-0.30/hr active conversation
- Limitation: no tool calling, no transcription — pure conversation only
- WebSocket opened at session start, closed at session end

### Fallback Path — Local Cascade

- STT: NVIDIA Parakeet TDT 0.6B v3 (streaming, ~3GB VRAM, 6% WER)
- LLM: Claude via LiteLLM (full tool access — briefings, meeting prep, system status, calendar)
- TTS: Kokoro 82M (streaming, ~2-3GB VRAM, 60-100ms TTFB)
- Interruptions: Silero VAD barge-in detection (cancel current TTS playback on speech detected)
- Latency: ~800-1500ms total (STT ~200ms + LLM ~400-800ms + TTS ~100ms)

### Intent Router

- Runs on every utterance during an active session
- Wake word "Hapax" + system-directed phrase ("what's my briefing", "system status") → local cascade with Claude tools
- Conversational/general utterances → Gemini Live
- Can switch mid-session: chatting on Gemini, then "Hapax, pull up my calendar" routes to local cascade and returns
- Initial implementation: keyword/pattern matching, upgradeable to lightweight classifier

### Hapax Persona

- Named "Hapax" — light persona, warm but functional, concise responses
- Consistent tone across both backends via system prompt
- Cockpit `voice.py` greeting style carries over
- Voice will differ slightly between Kokoro (local) and Gemini (cloud) — persona continuity matters more than acoustic identity

---

## 3. Presence Detection

Audio-based occupancy sensing using the always-on Blue Yeti mic.

### Detection Approach

- Lightweight process running continuously alongside the daemon
- Taps mic stream via PipeWire (separate consumer)
- Silero VAD on 30ms frames (<1ms per chunk, CPU-only)
- Maintains a **presence score**: sliding window over last N minutes tracking human audio activity (speech, movement, keyboard sounds)
- Thresholds: `likely_present` / `uncertain` / `likely_absent`

### Why Audio-Based

- 24/7 mic already exists — no new hardware
- Silero VAD is effectively free on CPU
- Human presence correlates strongly with ambient sound
- Cardioid pattern reduces false positives from adjacent rooms

### Limitations

- Silent presence (reading, thinking) may not register
- Not a certainty engine — a comfort heuristic
- Tuning required during first week of real-world use

### Verification Protocol

When system has proactive content and presence score is `likely_present`:

1. Check **context gate** (see below) — is this a good moment?
2. Play soft attention chime (not speech — non-intrusive)
3. Wait 2-3 seconds for any audio response
4. If audio detected → deliver notification
5. If silence → queue, retry in 10 minutes or fall back to ntfy

When `uncertain` or `likely_absent` → ntfy only.

---

## 4. Context Gate

Determines whether the current moment is appropriate for interruption. Checked before the verification chime.

### Layered Checks (cheapest first)

1. **Active voice session?** (internal state — free) → never interrupt mid-conversation; queue and deliver at session end or during pause
2. **PipeWire output volume above threshold?** (single API call) → loud music/media = not interruptible
3. **Studio processes/MIDI devices active?** (process check + `aconnect -l`) → recording session in progress
4. **PANNs-lite ambient classification** → dominant sound is music or sustained noise = not interruptible

If any gate fails → queue notification, fall back to ntfy for urgent items.

### Priority Levels

- **Urgent** (meeting in 5 min, system alert): retries context gate every 2 minutes, falls back to ntfy sooner
- **Normal** (briefing ready, digest): tries once, queues for next eligible moment or ntfy
- **Low** (informational): only delivers if clearly idle and present

---

## 5. Speaker Identification

Distinguishes the operator from other people in the room.

### Voice Enrollment

- One-time setup: record a few minutes of the operator speaking, extract speaker embedding via pyannote (already in the stack)
- Runtime: compare first few seconds of speech against enrolled embedding (cosine similarity)
- Confidence levels: `ryan` / `uncertain` / `not_ryan`
- Passive — no explicit identification step

### Behavior Adaptation

- **the operator confirmed:** Full access — system queries, briefings, proactive conversations, personal context
- **Unknown / not the operator:** Guest mode — friendly, general conversation only (Gemini Live path), no system information
  - "Hey, I'm Hapax — I can chat, but I'll keep the system stuff for when the operator's back"
- **Explicit signal** ("it's not the operator", "he's not here"): Hapax acknowledges gracefully, queues pending notifications
- **the operator returns:** Re-identified via embedding shift, or explicitly ("hey Hapax, I'm back")

### Proactive Speech + Speaker ID

- Presence detected → context gate passes → chime → someone responds
- If responder's voice doesn't match the operator → "Hey — is the operator around?" → if no → "No problem, I'll catch him later"

### Privacy Note

Not authentication (axiom: single_operator). A courtesy/privacy heuristic preventing system content from being read to visitors. Voice embedding stays local.

---

## 6. Proactive Speech Engine

System-initiated spoken notifications and conversations.

### Event Sources

- **ntfy notifications** — subscribe to ntfy topics, speak eligible ones aloud
- **Timer-driven agents** — briefing, digest, meeting prep trigger voice delivery when ready
- **Calendar events** — upcoming meetings via gcalendar-sync
- **System alerts** — health monitor failures, VRAM warnings, disk space

### Flow

1. Event arrives (ntfy message, timer fires, agent completes)
2. Assign priority level
3. Check presence score
4. Check context gate
5. If both pass → chime → verify → speak
6. If either fails → queue with TTL (urgent: 30 min, normal: 4 hours, low: expires silently)
7. Queued items re-evaluated on next presence/context check cycle

### Interruptibility

- Interrupt at any point via speech (Silero VAD barge-in)
- "Tell me more" → opens full conversation session about that topic
- "Not now" / "later" → acknowledges, re-queues
- "Stop" / silence → drops it

### Notification Formatting

- Raw ntfy messages reformatted to natural speech via fast LLM call (Haiku tier)
- Agent outputs (briefing, digest) already structured — TTS reads summary, offers to go deeper
- First proactive speech of the day: greeting + briefing summary in one natural delivery

---

## 7. Echo Cancellation & Audio Routing

### PipeWire Echo Cancellation

- Module: `libpipewire-module-echo-cancel` with WebRTC AEC backend
- Config: `~/.config/pipewire/pipewire.conf.d/60-echo-cancel.conf`
- Creates virtual echo-cancelled source consumed by Hapax, ambient recorder, and presence detector
- `monitor.mode = true` captures speaker output as AEC reference signal
- Works well at low-to-moderate volumes; context gate blocks proactive speech at high volumes

### Audio Routing Topology

```
Blue Yeti (physical) ──→ PipeWire
                            ├──→ Echo Cancel Module ──→ Virtual Source (echo-cancelled)
                            │                              ├──→ Hapax Voice Engine
                            │                              ├──→ Ambient Audio Recorder
                            │                              └──→ Presence Detector
                            └──→ Raw source (available if needed)

Hapax TTS Output ──→ PipeWire Default Sink ──→ Speakers
                            │
                            └──→ Echo Cancel Module (reference signal)
```

### Audio Ducking

- When Hapax speaks, other audio ducks via PipeWire `module-role-duck`
- Hapax TTS output gets a media role that triggers ducking
- Restores automatically when Hapax stops

### Ambient Recorder Impact

- Switch from raw device to echo-cancelled virtual source
- Prevents Hapax's own speech from appearing in ambient recordings
- Minor config change to `audio-recorder.service` source name

---

## 8. Wake Word & Hotkey Activation

### Wake Word — OpenWakeWord

- CPU-only, ONNX runtime, <10ms per frame
- Runs continuously while daemon is alive
- Custom "Hapax" / "Hey Hapax" model trained via synthetic speech (Piper TTS generates training samples)
- First-week tuning: collect false positive/negative examples from ambient audio, retrain
- Custom Pipecat `FrameProcessor` (no native OpenWakeWord support in Pipecat)

### Hotkey

- `Super+Shift+V` (fits existing LLM hotkey pattern)
- Sends signal to daemon via Unix socket
- Toggles session open/close
- Faster than wake word when already at keyboard

### Session Start

- Wake word or hotkey → soft acknowledgment chime
- Hapax listens for first utterance
- Intent router classifies and routes
- 5s silence → "What's up?" → 10s timeout → close

### Session End

- Explicit: "that's all", "thanks Hapax", "goodbye"
- Hotkey toggle
- Silence timeout: 30s
- On close: soft chime + optional queued notification offer ("Before you go, your daily digest is ready. Want to hear it?")

---

## 9. Tiered TTS

### Tier 1 — Piper (CPU, instant)

- Use: chimes, short confirmations, notification wrappers
- Zero VRAM, <50ms latency
- Not suitable for long-form speech

### Tier 2 — Kokoro 82M (GPU, near-instant)

- Use: primary conversational TTS on local cascade, briefing readouts, proactive speech
- ~2-3GB VRAM, 60-100ms TTFB, streaming
- The "Hapax voice" on the local path

### Tier 3 — Gemini Native Audio (cloud)

- Use: conversational speech on Gemini Live path
- Zero local resources
- Highest quality, most natural

### Voice Consistency

- Kokoro and Gemini will sound different — unavoidable without voice cloning
- Mitigation: pick tonally similar Kokoro voice to Gemini default
- Persona continuity (name, tone, word choice) matters more than acoustic identity

### Chatterbox

- Not a tier — stays in demo pipeline role
- Could be promoted later for custom voice cloning if desired

---

## 10. Observability & Deployment

### Langfuse Integration

- Local cascade LLM calls route through LiteLLM → Langfuse tracing
- Pipecat OpenTelemetry: session lifecycle, utterance count, backend selection, per-utterance latency
- Presence/context gate decisions logged to journal (high-frequency, low LLM-observability value)

### Systemd Deployment

- `hapax-voice.service` — user service, `Type=simple`, `Restart=always`
- `After=pipewire.service pipewire-pulse.service`
- Graceful degradation without network (local fallback only)
- `OnFailure=notify-failure@%n.service`

### VRAM Coordination

- Low VRAM idle (~2-3GB Kokoro)
- Parakeet loads on-demand during local sessions (~3GB additional)
- Lockfile coordination with ambient audio processor — voice daemon writes lock during active local sessions, audio processor checks and waits/skips

### Health Monitoring

- New check group: wake word process alive, PipeWire echo cancel source exists, daemon socket responsive
- Failures → ntfy (voice can't alert about its own failure)

### Configuration

- `~/.config/hapax-voice/config.yaml`
- Tunables: presence window, VAD thresholds, silence timeout, volume threshold, priority TTLs, Gemini model
- Restart service to apply changes (no hot-reload initially)
