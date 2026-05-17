---
case_id: CASE-VOICE-PIPELINE-REPAIR-20260517
version: 0
stage: S5_AUTHORIZATION_PACKET
status: implementation_authorized
created_utc: 2026-05-17T05:00:00Z
originator: alpha
methodology: hapax-sdlc
risk_tier: T2_MODERATE
source_mutation_authorized: true
docs_mutation_authorized: true
vault_mutation_authorized: true
implementation_authorized: true
release_authorized: false
public_current: false
axiom_mutation_authorized: false
plan_accepted: true
plan_grants_implementation_authority: true
axiom_compliance_checked: true
axiom_compliance_result: "All 5 axioms satisfied (single_user, executive_function, corporate_boundary, interpersonal_transparency, management_governance)"
consent_contract_required: false
source_mutation_scope: "agents/hapax_daimonion/, shared/information_density.py, shared/config.py, agents/deliberative_council/, agents/streamdeck_adapter/, config/streamdeck.yaml, config/pipewire/, systemd/units/"
implementation_scope: "Voice pipeline end-to-end: audio input → VAD → STT → conversation pipeline → TTS → destination routing → PipeWire → broadcast. Plus TTS engine swap and S-4 voice modulation chain."
---

# CASE-VOICE-PIPELINE-REPAIR-20260517

## Purpose

Complete repair of the Hapax voice conversation pipeline. The system currently cannot hold a conversation with the operator despite all hardware being connected and services running. Multiple compounding failures prevent speech detection, response generation, and audio output.

## Governing Principles

- executive_function (95): Zero-config, errors include next actions
- single_user (100): No auth/roles/collaboration complexity
- no_expert_system_rules: All behavioral changes through feedback, tools, capabilities — never hardcoded rules

## Risk Assessment

T2_MODERATE — Multi-file changes across daimonion, shared modules, PipeWire config, and systemd units. All changes are reversible. No governance spec modifications. No axiom changes.

## Research Evidence (S1 Complete)

7 research/audit agents produced findings across 4 diagnostic areas + 2 voice design areas:

### Root Causes Identified

1. **Daemon crash-loop**: `planner.plan()` blocks asyncio event loop with synchronous `urllib.request.urlopen()` (300s timeout). Freezes perception, VAD, audio, everything. Systemd kills after 30s SIGTERM timeout.

2. **Broadcast routing paradox**: `resolve_playback_decision(None)` blocks broadcast for conversational responses because they have no impingement. Stream mode public → classify returns LIVESTREAM → but resolve requires per-utterance `broadcast_intent` that conversational responses never carry.

3. **Stream Deck routing disconnect**: Key 5 writes to `~/.cache/hapax/stream-mode` but `_stream_mode_is_public()` reads from `/dev/shm/hapax-compositor/stream-mode-intent.json`. Two separate systems.

4. **Audio health gate**: `audio_safe_for_broadcast.safe == false` due to stale witness data, loudness out of band, ducker readback errors.

5. **TTS quality**: Kokoro 82M on CPU is flat/monotone. Chatterbox Turbo (350M, GPU, 75ms TTFB) is the replacement.

6. **Voice identity**: Non-anthropomorphic voice through Chatterbox → S-4 granular/filter/color/space processing chain. Voice cloning reference = processed Kokoro output (formant-shifted, pitch-quantized). S-4 VOICE-SELF-MOD scene designed.

### Agent Evidence Artifacts

- Daemon lifecycle audit (crash causes, dependency chain, asyncio starvation proof)
- Conversation pipeline end-to-end trace (12 steps, every gate mapped)
- TTS output chain audit (Kokoro→Chatterbox swap plan, VRAM budget, PipeWire routing)
- Presence engine audit (pending completion)
- Non-anthropomorphic voice design (reference audio strategy, exaggeration settings, emotion tag reframing)
- S-4 modulation chain engineering (VOICE-SELF-MOD scene, CC automation, intelligibility thresholds, PipeWire fallback)

## Plan (S2)

### Track A: Daemon Stability (P0)
- A1: Run `planner.plan()` in `asyncio.run_in_executor()` — eliminate event loop blocking
- A2: Reduce TabbyAPI timeout from 300s to 30s for programme planner path
- A3: Cache TabbyAPI unavailability for >30s to prevent rapid retry

### Track B: Broadcast Routing (P0)
- B1: When stream mode is public AND impingement is None (conversational response), skip broadcast_intent gate in `resolve_playback_decision()`
- B2: Unify stream mode state — `_stream_mode_is_public()` reads from canonical `shared.stream_mode` instead of SHM file
- B3: Wire Stream Deck key 4 (`studio.stream_mode.toggle`) handler in `logos_control_dispatch.py`
- B4: Refresh audio_safe_for_broadcast state (clear stale witness, fix loudness/ducker readback)

### Track C: TTS Swap — Kokoro → Chatterbox Turbo (P0)
- C1: Install `chatterbox-tts`, add to pyproject.toml
- C2: Create reference voice (Kokoro → formant shift +2-4 semitones → pitch quantize → bandpass → save as profiles/voice-sample.wav)
- C3: Replace TTSManager in tts.py with ChatterboxTurboBackend (exaggeration 0.35, cfg_weight 0.4, GPU 0)
- C4: Update tts_server.py UDS wire format if needed

### Track D: S-4 Voice Modulation Chain (P1)
- D1: Add VOICE-SELF-MOD scene to s4_scenes.py (Mosaic 35%, Ring 40%, Deform 30%)
- D2: Wire S-4 MIDI CC automation from information density + stimmung
- D3: Create PipeWire filter-chain fallback (hapax-voice-s4-emulation.conf)
- D4: Wire S-4 audio input path (hardware + PipeWire loopback)

### Track E: Audio Input (P0)
- E1: Permanent Rode Wireless Pro priority in audio_input.py DEFAULT_SOURCE_PRIORITY (not env var hack)
- E2: Commit and merge audio_input.py HAPAX_AUDIO_INPUT_TARGET env override

## Success Criteria

1. Operator speaks into Rode → Hapax detects speech within 2s
2. Hapax responds with Chatterbox Turbo voice through broadcast chain (MPC USB 3/4)
3. Stream Deck key 4/5 toggles private/public routing instantly
4. Daemon runs stable for 1+ hour without crash/freeze
5. S-4 modulation chain produces intelligible non-human voice (>0.85 intelligibility)
