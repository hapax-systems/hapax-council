# Impingement-Native Voice Architecture

**Date:** 2026-05-23
**Status:** Draft
**Supersedes:** ConversationPipeline sidecar pattern (conversation_pipeline.py)
**Spec dependencies:** 2026-03-25-impingement-activation-cascade, 2026-04-02-unified-semantic-recruitment-design

## Problem

Operator speech bypasses the impingement/affordance system entirely. The ConversationPipeline is a hardwired sidecar: audio → VAD → STT → LLM → TTS, with no force competition against exploration or narration. The conative impingement spec (2026-03-25) defines operator utterances as "external signals triggering perception-level impingements" but the code violates this.

Consequences:
- Exploration and narration play over operator speech with no force comparison
- The speaking gate suppresses VAD for 8-35 seconds during exploration surfacing
- Conversation is not in the affordance vocabulary — it cannot be recruited
- The ResourceArbiter (conversation:100 > narration:20 > exploration:15) is not wired into audio
- Audio classification does not generate impingement force

## Design Principles

1. **All behavior through impingement force.** No special-cased sidecars. Operator speech competes on the same field as exploration and narration — it wins because it's the strongest signal.
2. **Audio classification is the dominant impingement source.** Human speech in the room is the most significant audio event. Full ambient sound understanding is the target.
3. **Force wins, not locks.** The async mutex is replaced by priority-aware resource arbitration. Higher-force impingements preempt lower-force in-flight speech.
4. **Speaking gate during playback only.** VAD suppression covers TTS playback duration, never LLM inference or composition.

## Architecture

Three components replace the ConversationPipeline monolith:

### 1. AudioPerceptionBackend

Perception backend registered in the daimonion perception engine. Replaces ConversationBuffer as the primary audio ingestion point.

**Inputs:** Raw PCM from pw-cat (ReSpeaker XVF3800 or Yeti, existing audio_input.py).

**Processing pipeline:**
- VAD (Silero, existing) → speech probability per 30ms frame
- Adaptive speech-end detection (existing ConversationBuffer logic) → complete utterance segmentation
- Speaker identification (pyannote embedding, existing) → operator/guest/unknown posterior
- Speculative STT (Parakeet TDT, existing) → transcription of complete utterances
- Audio scene classification (Phase 1: speech/not-speech; Phase 2: YAMNet semantic events; Phase 3: temporal compound events)
- Echo cancellation (existing AEC, perception filter not gate)

**Outputs:** Impingements written to `/dev/shm/hapax-dmn/impingements.jsonl`.

**Impingement schema — operator speech:**
```yaml
source: "audio.operator_speech"
type: PATTERN_MATCH
strength: vad_confidence * speaker_operator_posterior  # typically 0.85-1.0
content:
  transcript: "what the operator said"
  audio_event: "directed_speech"
  speaker: "operator"
  energy_db: -12.3
  duration_s: 2.4
  utterance_bytes_ref: "/dev/shm/hapax-daimonion/utterance-{timestamp}.pcm"
```

**Impingement schema — audio scene events:**
```yaml
source: "audio.scene"
type: STATISTICAL_DEVIATION
strength: contextual  # music onset ~0.3, silence after speech ~0.4, impact ~0.5
content:
  audio_event: "music_onset" | "silence_onset" | "impact" | "multiple_speakers"
  confidence: 0.85
```

**Strength calibration:** Operator-directed speech at normal conversational volume produces strength 0.85-1.0. This exceeds all exploration impingement strengths (typically 0.2-0.6) and narrative drive posterior (typically 0.12-0.40). Only safety-critical interrupt tokens (operator_distress, population_critical) match or exceed.

**Key invariant:** AudioPerceptionBackend NEVER stops listening. There is no speaking gate at the perception layer. Echo cancellation filters TTS bleed-through; it does not suppress perception.

### 2. ConversationalResponse Capability

Registered affordance in the Qdrant `affordances` collection.

```yaml
name: "conversational_response"
domain: "communication"
description: "Respond to operator speech with contextually appropriate conversational reply using grounded language model"
activation_cost: 0.3
consent_required: false
```

**Recruitment:** When an `audio.operator_speech` impingement wins recruitment (it will, given strength ~1.0), the AffordancePipeline activates this capability.

**Execution:**
1. Extract transcript from impingement content
2. Build conversation context: history (shared store, not instance state), phenomenal state, grounding envelope, temporal bands
3. Call Command-R via LiteLLM (`openai/local-fast`, api_key from env, 10s timeout)
4. Produce text intent
5. Emit speech-production impingement carrying the response text, destination decision, and conversation metadata

**Conversation history:** Moves from ConversationPipeline instance state to a shared conversation store (`/dev/shm/hapax-daimonion/conversation-history.jsonl`). Capability is stateless — recruited fresh each time, reads history from store.

**What moves here from ConversationPipeline:**
- `process_utterance()` LLM call logic
- `_update_system_context()` context building
- Grounding ledger integration
- Tool recruitment gate
- Sentinel fact injection
- Bayesian envelope rendering

**What does NOT move here:**
- TTS synthesis (→ SpeechProduction)
- Audio output management (→ SpeechProduction)
- Speaking gate management (→ SpeechProduction)
- `generate_spontaneous_speech()` (remains in exploration surfacing, uses SpeechProduction)

### 3. Unified SpeechProduction

Single output path for ALL hapax speech. Registered affordance.

```yaml
name: "speech_production"
domain: "expression"
description: "Synthesize text to speech via Chatterbox TTS and play to resolved audio destination"
activation_cost: 0.4
consent_required: false
```

**Replaces three current paths:**
- `_speak_sentence()` in ConversationPipeline
- Autonomous narrative TTS in CPAL runner (lines 1105-1250)
- `prepared_playback_loop` sentence-level TTS in run_loops_aux

**Execution:**
1. Receive text + source metadata (conversation, narration, exploration)
2. Resolve destination via `resolve_playback_decision()` (existing)
3. Claim `audio_output` resource via ResourceArbiter with source priority
4. Synthesize via Chatterbox TTS (existing TTSManager)
5. Set speaking gate (`set_speaking(True)`)
6. Play via pw-cat to resolved target (existing pw_audio_output)
7. Release speaking gate (`set_speaking(False)`)
8. Record playback witness (existing voice_output_witness)

**Speaking gate invariant:** The gate is held ONLY during steps 5-7 (actual audio playback). Steps 1-4 (text processing, TTS synthesis) do NOT suppress VAD.

**Preemption:** If a higher-priority ResourceArbiter claim arrives during playback, the in-flight pw-cat process is killed, the gate drops, and the new claim proceeds.

### 4. CPAL Runner Changes

**Removed:**
- Step 4 utterance processing path (`_process_utterance`, `_queued_utterance`)
- `_processing_utterance` flag
- `_speech_lock` async mutex
- Speaking gate management in exploration surfacing
- All `set_speaking()` calls in the runner

**Modified:**
- `process_impingement()` handles ALL impingements uniformly, including `audio.operator_speech`
- ResourceArbiter wired in: every speech-producing impingement claims `audio_output` before synthesis
- Priority from resource_config.py enforced

**Interruption flow:**
1. Exploration impingement wins recruitment, claims `audio_output` at priority 15
2. SpeechProduction begins TTS + playback
3. Operator speaks → AudioPerceptionBackend emits `audio.operator_speech` (strength ~1.0)
4. Impingement enters CPAL runner via `process_impingement()`
5. ConversationalResponse capability recruited
6. Claims `audio_output` at priority 100 → ResourceArbiter preempts exploration
7. In-flight exploration pw-cat killed, speaking gate released
8. Conversation response synthesized and played

### 5. Audio Scene Classification (Progressive Phases)

**Phase 1 (this spec):** Speech detection + speaker ID + speculative STT → impingement emission. Existing capabilities rewired as AudioPerceptionBackend. Binary speech/not-speech.

**Phase 2:** Semantic event classification via lightweight ONNX model (YAMNet or AudioSet-derived). Music, impacts, environmental sounds, multiple speakers. Each event emits impingement with contextual strength. Runs on CPU.

**Phase 3:** Full ambient sound understanding with temporal context. Compound events: "music stopped 30s ago and nobody has spoken." Multimodal fusion with vision and contact mic. Deep audio scene analysis — door opening, phone ringing, genre shifts.

## Migration Path

ConversationPipeline is ~2400 lines. Dissolution is phased:

1. **AudioPerceptionBackend:** Extract ConversationBuffer + VAD + STT into perception backend. Wire impingement output. ConversationPipeline recruited via temporary impingement bridge.
2. **SpeechProduction capability:** Extract `_speak_sentence()`, unify with autonomous narrative TTS. All speech routes through single capability.
3. **ConversationalResponse capability:** Extract `process_utterance()` LLM logic. Move conversation history to shared store. Register as affordance.
4. **CPAL runner cleanup:** Remove utterance processing path, speech lock, processing flag. Wire ResourceArbiter into audio claims.
5. **ConversationPipeline deletion:** Once all logic extracted and tests pass, delete the file.

Each phase is independently deployable and testable. Phase 1 alone fixes the immediate problem (operator speech generates impingement force).

## Testing

- Existing CPAL runner tests updated for unified impingement path
- New: operator speech impingement preempts exploration impingement
- New: ResourceArbiter priority enforcement on audio_output
- New: AudioPerceptionBackend emits correctly-shaped impingements
- New: speaking gate held only during playback, not during LLM inference
- Integration: speak during exploration → exploration interrupted → conversation response plays

## Files Affected

**New files:**
- `agents/hapax_daimonion/audio_perception.py` — AudioPerceptionBackend
- `agents/hapax_daimonion/capabilities/conversational_response.py`
- `agents/hapax_daimonion/capabilities/speech_production.py`

**Modified files:**
- `agents/hapax_daimonion/cpal/runner.py` — remove utterance path, wire ResourceArbiter
- `agents/hapax_daimonion/run_inner.py` — register AudioPerceptionBackend
- `agents/hapax_daimonion/arbiter.py` — add preemption support for audio_output

**Deleted files (after full migration):**
- `agents/hapax_daimonion/conversation_pipeline.py`
- `agents/hapax_daimonion/conversation_buffer.py` (logic moves to audio_perception.py)
