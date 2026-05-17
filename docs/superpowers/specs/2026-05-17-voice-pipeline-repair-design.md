# Voice Pipeline Repair — Complete Conversation System

> **Authority Case:** CASE-VOICE-PIPELINE-REPAIR-20260517
> **Risk Tier:** T2_MODERATE
> **Stage:** S2_PLAN_DRAFT (implementation NOT yet authorized)
> **For agentic workers:** Use superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Fix all failures preventing Hapax from holding voice conversations on the livestream. Swap TTS engine. Wire broadcast routing. Design non-anthropomorphic voice through S-4 modulation.

**Architecture:** 5 tracks across daimonion, shared modules, PipeWire config, and systemd units.

---

## Root Causes (7 audit agents, empirical evidence)

### RC-1: Asyncio Event Loop Starvation (daemon crash-loop)
`programme_loop.py:810` → `planner.plan()` → `urllib.request.urlopen(timeout=300)` SYNCHRONOUS in async loop. Freezes perception, VAD, audio. Systemd SIGKILL after 30s.

### RC-2: Presence Engine False-Negative (evdev on Wayland)
`evdev_input.py` reports `keyboard_active=False` because KWin holds exclusive libinput. LR 0.158 drives posterior to 0.136. Logind `input_active=True` is shadowed. Fix: warmup + self-disable, logind fallback. **Agent already applied fix + tests.**

### RC-3: Broadcast Routing Paradox
`conversation_pipeline.py:1682` → `resolve_playback_decision(None)` → `broadcast_intent_missing` → ALL conversational TTS dropped. Stream mode public signals intent at system level but per-utterance gate overrides.

### RC-4: Stream Deck State Disconnect
Key 5 writes `~/.cache/hapax/stream-mode`. `_stream_mode_is_public()` reads `/dev/shm/hapax-compositor/stream-mode-intent.json`. Two systems.

### RC-5: Audio Health Gate
`audio_safe_for_broadcast.safe == false`: loudness, stale witness, ducker readback. Blocks all broadcast.

### RC-6: TTS Quality
Kokoro 82M CPU flat/monotone → Chatterbox Turbo 350M GPU (75ms TTFB, voice cloning, emotion tags as timbral markers).

### RC-7: Voice Identity
Non-anthropomorphic voice via Chatterbox → S-4 chain. Reference = processed Kokoro (formant +2-4 semitones, pitch quantize). VOICE-SELF-MOD scene. Importance → processing reduction.

---

## Tracks

### Track A: Daemon Stability (P0, independent, ~3h)

- [ ] **A1** (2h): Wrap `planner.plan()` in `asyncio.run_in_executor()` in `programme_loop.py`. Eliminate synchronous blocking.
- [ ] **A2** (30min): Reduce TabbyAPI timeout from 300s to 30s in `resident_command_r.py` for programme planner.
- [ ] **A3** (30min): Cache TabbyAPI unavailability for 5min (not 30s) to prevent rapid retry on outage.

### Track B: Broadcast Routing (P0, independent, ~5h)

- [ ] **B1** (2h): In `resolve_playback_decision()`: when stream mode is public AND impingement is None, skip `broadcast_intent` gate. Operator's system-level intent overrides per-utterance gate.
- [ ] **B2** (1h): Unify stream mode reading — `_stream_mode_is_public()` reads from `shared.stream_mode` canonical source, not SHM file.
- [ ] **B3** (1h): Wire `studio.stream_mode.toggle` handler in `logos_control_dispatch.py`. Write BOTH canonical file AND SHM intent.
- [ ] **B4** (1h): Fix audio health: clear stale witness, fix loudness monitoring, resolve ducker readback errors.

### Track C: TTS Swap (P0, depends on A1, ~4h)

- [ ] **C1** (30min): `uv pip install chatterbox-tts`. Add `"chatterbox-tts>=0.1.4"` to pyproject.toml `[audio]` extra.
- [ ] **C2** (1h): Create reference voice: Kokoro → formant shift +2-4 semitones → pitch quantize to chromatic → bandpass 1.5-3kHz → remove breath/silence → save `profiles/voice-sample.wav`.
- [ ] **C3** (2h): Replace TTSManager in `tts.py` with ChatterboxTurboBackend. Exaggeration 0.35, cfg_weight 0.4. GPU 0 (3090). Same output format (PCM int16 24kHz mono bytes).
- [ ] **C4** (30min): Update `tts_server.py` UDS interface if format changes. Verify `pipecat_tts.py` compatibility.

### Track D: S-4 Voice Modulation (P1, depends on C3, ~6h)

- [ ] **D1** (1h): Add VOICE-SELF-MOD scene to `s4_scenes.py`: Mosaic 35% wet (CC69=45), Ring 40% (CC85=50), Deform 30% (CC101=38), Vast small-room.
- [ ] **D2** (2h): Wire MIDI CC automation: information_density → CC69 (granular wet), stimmung.tension → CC79 (resonance), exploration_deficit → CC67 (spray). Max 2 simultaneous, min 1s ramp.
- [ ] **D3** (1h): Create `config/pipewire/hapax-voice-s4-emulation.conf` — PipeWire filter-chain with pitch shift + resonant bandpass + high-cut as S-4 software fallback.
- [ ] **D4** (2h): Wire S-4 hardware audio path: TTS → PipeWire loopback → S-4 USB input → S-4 processing → S-4 output → L-12 CH7/8 → broadcast. Fail-safe dry bypass.

### Track E: Audio Input (P0, independent, ~1h)

- [ ] **E1** (30min): Add `_RODE_WIRELESS_PATTERN` to `DEFAULT_SOURCE_PRIORITY` in `audio_input.py` (ahead of Yeti). Permanent, not env hack.
- [ ] **E2** (30min): Commit the `HAPAX_AUDIO_INPUT_TARGET` env override (already in canonical from tonight's work). Ensure source-activation worktree includes it.

### Track F: Presence Fix (P0, already implemented by audit agent)

- [ ] **F1** (verify): Confirm evdev warmup + self-disable fix in `evdev_input.py`. Verify tests pass. Commit.

---

## Success Criteria

1. Operator speaks into Rode → Hapax detects speech (VAD) within 1s
2. Presence posterior reaches PRESENT within 5s of keyboard/camera activity
3. Hapax responds with Chatterbox Turbo voice through broadcast chain
4. Stream Deck key 4/5 toggles private/public routing, destination channel respects it
5. Daemon runs stable for 1+ hour without crash/freeze
6. S-4 modulation produces intelligible non-human voice (>0.85 intelligibility)
7. Voice identity: processed-Kokoro reference → Chatterbox synthesis → S-4 granular/filter/color/space

## Total: ~19h across 16 tasks, 5 tracks + 1 verification.
