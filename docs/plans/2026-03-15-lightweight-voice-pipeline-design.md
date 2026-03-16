# Lightweight Voice Pipeline Design

**Date:** 2026-03-15
**Status:** Design (not yet implemented)
**Replaces:** Pipecat-based local pipeline (`pipeline.py`, `pipecat_tts.py`, `frame_gate.py`)

---

## 1. Architecture Overview

```
                        ┌──────────────────────────────────────────┐
                        │           VoiceDaemon (existing)          │
                        │                                          │
  AudioInputStream ─────┤──► wake_word consumer  (always)          │
  (PyAudio callback,    │──► VAD/presence consumer (always)        │
   echo_cancel_capture, │──► ConversationBuffer consumer (active)  │
   16kHz mono, 30ms)    │                                          │
                        └──────────┬───────────────────────────────┘
                                   │
                     wake word fires│or hotkey
                                   ▼
                   ┌───────────────────────────────┐
                   │     ConversationPipeline       │
                   │                                │
                   │  State: IDLE → LISTENING →     │
                   │    TRANSCRIBING → THINKING →   │
                   │    SPEAKING → LISTENING → ...  │
                   │                                │
                   │  ┌────────────┐                │
                   │  │ConvBuffer  │ accumulates    │
                   │  │(ring buf)  │ audio during   │
                   │  │            │ speech          │
                   │  └─────┬──────┘                │
                   │        │ VAD end-of-speech      │
                   │        ▼                        │
                   │  ┌────────────┐                │
                   │  │STT (faster │ model stays    │
                   │  │-whisper)   │ loaded in VRAM │
                   │  └─────┬──────┘                │
                   │        │ transcript             │
                   │        ▼                        │
                   │  ┌────────────┐                │
                   │  │LLM (LiteL  │ streaming via  │
                   │  │LM acompl.) │ acompletion()  │
                   │  └─────┬──────┘                │
                   │        │ token stream           │
                   │        ▼                        │
                   │  ┌────────────┐                │
                   │  │Sentence    │ accumulates    │
                   │  │Accumulator │ to boundaries  │
                   │  └─────┬──────┘                │
                   │        │ complete sentences     │
                   │        ▼                        │
                   │  ┌────────────┐                │
                   │  │TTS (Kokoro)│ model stays    │
                   │  │            │ loaded in VRAM │
                   │  └─────┬──────┘                │
                   │        │ PCM audio              │
                   │        ▼                        │
                   │  ┌────────────┐                │
                   │  │AudioOutput │ PyAudio stream │
                   │  │(playback)  │ @DEFAULT_SINK@ │
                   │  └────────────┘                │
                   └───────────────────────────────┘
```

**Key difference from Pipecat:** The microphone is NEVER exclusively owned. All three consumers (wake word, VAD/presence, conversation buffer) receive every frame from `_audio_loop()`. No transport handoff, no stream stop/start, no latency from mic acquisition.

---

## 2. Component-by-Component Design

### 2.1 ConversationBuffer

**What it does:** Third consumer in `_audio_loop()`. Accumulates raw PCM frames during active speech (VAD above threshold) and delivers complete utterances to STT.

**Design:**
- Ring buffer of 30ms frames, max ~30 seconds (1000 frames)
- VAD speech-start: begin accumulating (with 300ms pre-roll for word onsets)
- VAD speech-end (silence > 600ms): emit accumulated audio as complete utterance
- Runs inline in `_audio_loop()` — no extra task, no extra copy for wake word/VAD

**VAD integration:** Reuses the existing Silero VAD from `PresenceDetector.process_audio_frame()`. The presence detector already runs VAD on every 512-sample chunk. We add a parallel speech-state tracker that watches the VAD probability stream:
- `prob > 0.5` for 3+ consecutive chunks → speech start
- `prob < 0.3` for 20+ consecutive chunks (~600ms) → speech end

**Latency contribution:** ~0ms (inline accumulation, no processing)

### 2.2 STT: faster-whisper (Resident)

**Model lifecycle:**
- `WhisperModel` instantiated ONCE at daemon startup
- Stays in VRAM for the entire daemon lifetime
- Reused across all utterances — no load/unload per session
- Called via `loop.run_in_executor()` to avoid blocking the event loop

**Model selection:**
- **Primary: `large-v3` in float16** — ~3 GB VRAM, best accuracy
- **Alternative: `distil-large-v3`** — ~1.5 GB VRAM, 6x faster, within 1% WER
- **Fallback: `large-v3-turbo`** — faster than large-v3, slightly less accurate
- The config already has `local_stt_model` — reuse this field

**Latency estimate for 2 seconds of audio on RTX 3090:**
- `large-v3` float16: ~200-400ms
- `distil-large-v3` float16: ~80-150ms
- `large-v3-turbo`: ~100-200ms

**Memory footprint (resident):**
- `large-v3` float16: ~3 GB VRAM
- `distil-large-v3` float16: ~1.5 GB VRAM
- Kokoro TTS: ~0.5 GB VRAM
- Silero VAD: CPU only, ~50 MB RAM
- **Total resident: ~4-5 GB of 24 GB on RTX 3090** — leaves plenty for Ollama

**Streaming vs batch:** faster-whisper does NOT support true streaming (incremental transcription). It needs the complete utterance. This is acceptable because:
1. The VAD already segments speech into natural utterances
2. A typical utterance (2-5 seconds) transcribes in 100-400ms
3. Incremental STT adds complexity and word-boundary errors

**Interface:**
```python
class ResidentSTT:
    def __init__(self, model: str = "large-v3", device: str = "cuda"):
        self._model = WhisperModel(model, device=device, compute_type="float16")

    async def transcribe(self, audio: bytes, sample_rate: int = 16000) -> str:
        """Transcribe PCM audio bytes. Runs in thread pool."""
        segments, _ = await asyncio.get_event_loop().run_in_executor(
            None, self._model.transcribe, audio_array, ...
        )
        return " ".join(seg.text for seg in segments).strip()
```

### 2.3 LLM: Streaming via LiteLLM

**Why LiteLLM, not pydantic-ai:** For the voice pipeline, we need:
1. Streaming token-by-token to feed TTS with minimal latency
2. Tool/function calling mid-conversation
3. Conversation history management

pydantic-ai supports streaming (`run_stream_events()`) and tool calls, but adds abstraction layers that increase latency. For voice, raw LiteLLM `acompletion()` with `stream=True` gives the most direct control. The 50-100ms saved matters here.

**However:** Tool execution can use pydantic-ai's patterns internally — the voice pipeline just needs the streaming token interface.

**Conversation state:**
```python
messages: list[dict] = [
    {"role": "system", "content": system_prompt()},
]
# Append user/assistant messages each turn
# Maintain until session close (30s silence timeout or explicit)
# Token window management: truncate oldest user/assistant pairs when approaching limit
```

**Tool calling with streaming:** LiteLLM streaming returns `tool_calls` in the delta. Pattern:
1. Stream tokens, accumulate text for TTS
2. If a tool call appears in the stream, pause TTS accumulation
3. Execute the tool (existing handlers from `tools.py`)
4. Inject tool result into messages
5. Make another `acompletion()` call to get the response incorporating the tool result
6. Resume streaming to TTS

**Latency estimate:**
- Time to first token (TTFT): ~500-800ms for Claude Sonnet via LiteLLM
- Complete response for a 20-word answer: ~2-3 seconds total streaming time
- But TTS starts on the FIRST sentence, so perceived latency is lower

### 2.4 Sentence Accumulator

**What it does:** Sits between LLM token stream and TTS. Accumulates tokens into sentence-sized chunks for natural TTS synthesis.

**Boundary detection:**
- Split on: `. `, `? `, `! `, `; `, `: `, `\n`
- Minimum chunk size: 4 words (avoid choppy synthesis of fragments)
- Maximum accumulation time: 2 seconds (flush even without boundary)
- Flush remaining text when stream ends

**Why sentences, not words:** Kokoro produces much better prosody with complete sentences. Single words or fragments sound robotic and choppy. The tradeoff is ~200-500ms extra latency for the first sentence to accumulate, but natural-sounding output.

### 2.5 TTS: Kokoro (Resident)

**Model lifecycle:**
- `KPipeline` instantiated ONCE at daemon startup (already done in `TTSManager.__init__` via lazy load)
- Stays in VRAM for daemon lifetime
- Reused across all utterances

**The existing `TTSManager` works perfectly.** It's already standalone (not Pipecat-dependent). The `synthesize()` method takes text and returns PCM bytes. It already uses Kokoro with lazy loading.

**Sentence streaming pattern:**
- Each sentence from the accumulator is synthesized independently
- Synthesis runs in `loop.run_in_executor()` (GPU compute, ~100-300ms per sentence)
- PCM bytes are queued for playback immediately
- While sentence N plays, sentence N+1 is being synthesized
- This overlap hides synthesis latency after the first sentence

**Latency estimate:**
- First sentence (~8 words): ~100-200ms synthesis time
- Kokoro at 96x realtime on GPU: 1 second of audio synthesized in ~10ms
- A 20-word response (~3 seconds of audio) synthesizes in ~30ms total

### 2.6 Audio Output (Playback)

**Reuse `TTSExecutor._play_pcm()` pattern** but adapted:
- Dedicated PyAudio output stream, kept open during conversation
- PCM chunks queued and played sequentially
- Stream stays open between utterances (no open/close overhead)
- Separate daemon thread for blocking `stream.write()` calls

**Echo cancellation:** The `AudioInputStream` already uses `echo_cancel_capture` as its PipeWire source. PipeWire's WebRTC echo cancellation module creates a virtual source that subtracts the playback signal from the mic input. This means:
1. The mic always hears the room
2. PipeWire removes the TTS output from the mic signal
3. The wake word detector and VAD see "clean" audio
4. No additional echo suppression needed in the pipeline

**Interruption handling:** When the user speaks while TTS is playing:
1. VAD detects speech on the (echo-cancelled) mic input
2. ConversationBuffer starts accumulating
3. Pipeline stops current TTS playback (clear the playback queue)
4. System enters LISTENING state
5. When user stops speaking, the interrupted response is discarded
6. New utterance goes through STT → LLM → TTS as a new turn

---

## 3. State Machine

```
                    wake word / hotkey
    ┌─────┐        ──────────────────►  ┌───────────┐
    │ IDLE │                            │ GREETING  │
    │      │◄─── silence timeout ───────│ (optional)│
    └──────┘      or "goodbye"          └─────┬─────┘
                                              │ greeting plays
                                              ▼
                                        ┌───────────┐
                          ┌────────────►│ LISTENING  │◄────────────┐
                          │             └─────┬──────┘             │
                          │                   │ VAD speech-end     │
                          │                   ▼                    │
                          │             ┌──────────────┐           │
                          │             │ TRANSCRIBING │           │
                          │             └─────┬────────┘           │
                          │                   │ transcript ready   │
                          │                   ▼                    │
                          │             ┌───────────┐              │
                          │             │ THINKING  │              │
                          │             │ (LLM call)│              │
                          │             └─────┬─────┘              │
                          │                   │ first sentence     │
                          │                   ▼                    │
                          │             ┌───────────┐              │
                          └─────────────│ SPEAKING  │──────────────┘
                           user speaks  │ (TTS out) │  TTS complete
                           (interrupt)  └───────────┘
```

**State is a simple enum, not a full state machine library.** Transitions happen in a single async task (`ConversationPipeline.run()`), making them sequential and race-free.

**Session timeout:** The existing `SessionManager.is_timed_out` (30s silence) applies. When LISTENING with no speech for 30s, the pipeline stops and returns to IDLE.

---

## 4. Integration with Existing Daemon

### 4.1 What Changes in `__main__.py`

**`_audio_loop()` gains a third consumer:**
```python
# Existing consumers (unchanged):
#   wake_buf → wake word detector
#   vad_buf → presence detector

# New consumer:
if self._conversation_pipeline is not None and self._conversation_pipeline.is_active:
    self._conversation_pipeline.feed_audio(frame)
```

**`_start_pipeline()` / `_stop_pipeline()` are replaced:**
- No more Pipecat import, no `PipelineRunner`, no `LocalAudioTransport`
- No more stopping `_audio_input` (the mic stays shared)
- Instead: `self._conversation_pipeline = ConversationPipeline(...)` and `await pipeline.start()`

**`_wake_word_processor()` is simplified:**
- No longer needs to stop audio input before starting pipeline
- Just creates a `ConversationPipeline` and starts it

### 4.2 What Stays the Same

- `_audio_loop()` — same structure, one more consumer
- `_perception_loop()` — unchanged, still ticks every 2.5s
- `PresenceDetector` — unchanged, still processes every VAD chunk
- `wake_word` — unchanged, still processes every frame
- `SessionManager` — unchanged, manages session lifecycle
- `ContextGate` — unchanged, gates proactive delivery
- `PipelineGovernor` — unchanged, evaluates environment state
- `ConsentStateTracker` — unchanged, tracks consent phase
- `EventLog` — unchanged, receives events from new pipeline
- `HotkeyServer` — unchanged, triggers sessions
- All perception backends — unchanged

### 4.3 What Gets Deleted

- `pipeline.py` — Pipecat pipeline builder (replaced entirely)
- `pipecat_tts.py` — Pipecat TTS wrapper (Kokoro used directly)
- `frame_gate.py` — Pipecat frame processor (gating moves to ConversationBuffer)
- All Pipecat imports and dependencies

### 4.4 What Gets Refactored

- `tools.py` — Tool schemas change from `FunctionSchema` (Pipecat) to OpenAI-format dicts. Handler signatures change from `params.result_callback()` to returning strings. The actual handler logic (search, calendar, SMS, etc.) stays identical.
- `consent_session.py` — Uses `ConversationPipeline` with consent prompt/tools instead of building a Pipecat pipeline.

---

## 5. Consent Session Integration

The consent session is just a `ConversationPipeline` with different configuration:

```python
consent_pipeline = ConversationPipeline(
    stt=self.resident_stt,        # same STT instance
    tts=self.tts,                 # same TTS instance
    system_prompt=CONSENT_SYSTEM_PROMPT,
    tools=CONSENT_TOOLS,          # only record_decision, request_clarification
    tool_handlers=consent_handlers,
    timeout_s=cfg.consent_session_timeout_s,
    event_log=self.event_log,
)
```

The consent system prompt, tool schemas, and handlers from `consent_session.py` are reused directly. The only change is that they no longer need Pipecat's `register_function()` — they use the pipeline's own tool dispatch.

**Interaction with consent_state:**
- `ConsentStateTracker.needs_notification` → launches consent pipeline
- Consent pipeline runs → tool calls `grant_consent()` / `refuse_consent()`
- Pipeline ends → `_consent_session_active = False`
- No change to the state machine logic

---

## 6. Governor Integration

**The governor is NOT in the conversation loop.** The governor evaluates environment state and produces directives (process/pause/withdraw) for the perception-driven parts of the daemon. During an active conversation:

- Wake word already set `governor.wake_word_active = True` → grace period
- The governor's `pause` directive doesn't gate the conversation (no FrameGate)
- The governor's `withdraw` directive triggers session close, which stops the pipeline

**This is correct behavior:** The operator explicitly invoked the conversation via wake word or hotkey. The governor shouldn't override that mid-conversation. It can still close the session on `withdraw` (operator leaves the room for 60s).

**New: Conversation state as a Behavior:**
```python
# New behavior registered in perception:
conversation_active: Behavior[bool]  # True when pipeline is running
conversation_state: Behavior[str]    # "listening", "thinking", "speaking"
last_utterance: Behavior[str]        # most recent user transcript
```

This lets the perception layer and other consumers (OBS compositor, cockpit API) know the conversation state without coupling to the pipeline.

---

## 7. Latency Budget (End-to-End)

For the "natural conversation" target of ~1-2 seconds:

| Phase | Duration | Cumulative | Notes |
|-------|----------|------------|-------|
| VAD end-of-speech | 600ms | 600ms | Configurable silence threshold |
| STT transcription | 200ms | 800ms | 2s utterance, distil-large-v3 |
| LLM TTFT | 600ms | 1400ms | Claude Sonnet via LiteLLM |
| Sentence accumulation | 300ms | 1700ms | First ~8 words |
| TTS synthesis | 100ms | 1800ms | First sentence, Kokoro GPU |
| Audio output start | 10ms | 1810ms | PyAudio buffer flush |

**~1.8 seconds from end-of-speech to first audio output.** This is within the natural conversation range. A human takes 200-500ms to START responding after hearing a question, then speaks at ~150 words/minute. Our 1.8s is equivalent to a thoughtful pause before answering.

**Optimization levers if needed:**
1. Reduce VAD end-of-speech threshold to 400ms (saves 200ms, risk of cut-offs)
2. Use `distil-large-v3` instead of `large-v3` (saves 100-200ms)
3. Start LLM call with partial transcript (speculative, risky)
4. Use Gemini Flash instead of Claude Sonnet for faster TTFT (saves 200-400ms)

---

## 8. Turn-Taking and Interruption

### End-of-turn detection (simple approach)

**Silero VAD silence duration.** When VAD confidence drops below 0.3 for 600ms continuously, the user has stopped speaking. This is the same approach used by Pipecat's `SileroVADAnalyzer`, LiveKit, and most voice assistants.

**Why not a "Smart Turn" model:** Pipecat's Smart Turn uses an LLM to predict whether the user is done. This adds 200-500ms latency to EVERY turn boundary. The payoff is better handling of mid-sentence pauses ("I want to... um... go to the store"). In practice, the 600ms silence threshold handles 95% of cases. We can add Smart Turn later if needed.

### Interruption handling

When the user speaks while the system is in SPEAKING state:
1. VAD detects speech on echo-cancelled input
2. ConversationBuffer captures the new speech
3. TTS playback is stopped immediately (clear audio queue, close stream)
4. State transitions to LISTENING
5. When user finishes, normal STT → LLM → TTS flow resumes
6. The partial system response that was interrupted is included in conversation history as-is (so the LLM knows it was cut off)

**Implementation:** The ConversationPipeline monitors VAD during SPEAKING state. If speech is detected for 3+ consecutive VAD chunks (~100ms), trigger interruption.

---

## 9. Echo Cancellation

**PipeWire handles this.** The existing setup:

1. `AudioInputStream` opens with `source_name="echo_cancel_capture"`
2. PipeWire's `libpipewire-module-echo-cancel` (WebRTC AEC) creates this virtual source
3. The module knows what's being played on the default sink (iLoud Micros)
4. It subtracts the playback signal from the Yeti mic input
5. The resulting "clean" audio goes to all consumers

**No additional echo suppression needed in the pipeline.** The Yeti hears the TTS output, but by the time frames reach `_audio_loop()`, PipeWire has already removed it. This is why `_set_pipewire_default_source()` sets `echo_cancel_capture` as the default source.

**Verification needed:** During implementation, test that:
- TTS playback doesn't trigger the wake word detector
- TTS playback doesn't register as speech in VAD
- Interruption detection works even while TTS is playing

If PipeWire AEC is insufficient, the fallback is software AEC: during SPEAKING state, suppress the conversation buffer (but not wake word or VAD). This is simple but loses the ability to detect interruptions.

---

## 10. Gemini Live as Alternative Backend

The existing `GeminiLiveSession` (`gemini_live.py`) is a speech-to-speech backend that bypasses local STT/LLM/TTS entirely. Gemini handles everything server-side.

**Current status:** Implemented and wired into `_audio_loop()` (frames forwarded when connected). It works but has limitations:
- No tool calling (Gemini Live doesn't support function calls in audio mode)
- Higher latency (network round-trip to Google)
- No offline capability
- Privacy: all audio sent to Google
- Cost: per-minute pricing

**Recommendation:** Keep Gemini Live as a config option (`backend: "gemini"`) but don't invest further. The local pipeline is better for all hapax use cases because:
1. Tools are essential (calendar, search, SMS, scene analysis)
2. Consent sessions need precise tool calling
3. Privacy matters (axiom: corporate_boundary)
4. Latency is comparable or better with local models

**Possible future use:** Gemini Live as a fallback when the local GPU is busy (e.g., training a model) and tools aren't needed. Not worth building now.

---

## 11. Comparison: Lightweight Pipeline vs Fixing Pipecat

### Problems with Pipecat (current)

1. **Exclusive mic ownership:** `LocalAudioTransport` opens its own PyAudio stream, requiring the daemon to stop `AudioInputStream`. This means wake word detection, VAD, and presence detection all stop during conversation. 3-5 second gap in perception.

2. **Session teardown/rebuild:** Every conversation tears down and rebuilds the entire Pipecat pipeline. STT model reload, transport negotiation, context aggregator setup. ~2-5 seconds of startup overhead.

3. **Framework overhead:** Pipecat is designed for multi-party live calls with WebRTC, RTVI, and media server integration. We use none of this. The frame processing pipeline, context aggregators, and transport abstraction add complexity without value.

4. **Brittleness:** Pipecat's `LocalAudioTransport` has PyAudio conflicts with the daemon's own PyAudio usage. The `PipelineRunner` has its own signal handling that conflicts with the daemon's. The `FrameGate` is a Pipecat `FrameProcessor` that only works inside a Pipecat pipeline.

5. **Tool registration:** Tools use Pipecat's `FunctionSchema` and `register_function()` API. The consent tools use a different signature format. Two incompatible tool schemas for the same tools.

### What fixing Pipecat would require

- Implement shared audio transport (Pipecat doesn't support this)
- Keep models loaded across sessions (Pipecat tears down services)
- Write custom transport that wraps `AudioInputStream` (fighting the framework)
- Maintain two tool schema formats

### What the lightweight pipeline gives us

- **Shared mic always:** No perception gap. Wake word, VAD, presence all continue during conversation.
- **Resident models:** STT and TTS stay loaded. Zero startup latency.
- **Direct control:** Sentence-level TTS streaming, interruption handling, tool dispatch — all under our control, not mediated by a framework.
- **Simpler code:** ~400 lines of Python replacing ~600 lines of Pipecat integration code plus a complex framework dependency.
- **One tool format:** OpenAI-compatible tool schemas everywhere.
- **Composable with type system:** Conversation state as `Behavior[T]`, conversation eligibility as `VetoChain`, events through `EventLog`.

### Risks of removing Pipecat

1. **We own the VAD/turn-taking logic.** Pipecat's `SileroVADAnalyzer` handles this well. We need to reimplement it (but it's simple: silence duration threshold).
2. **We own the streaming orchestration.** The token → sentence → TTS → playback pipeline needs careful async coordination. But we already do similar things (`_audio_loop`, `_perception_loop`).
3. **No community upgrades.** Pipecat improvements (new STT backends, better turn detection) won't automatically benefit us. This is acceptable — we're already using custom TTS and have specific requirements.

---

## 12. Risks and Failure Modes

### VRAM contention
- **Risk:** Whisper + Kokoro + Ollama (local models) compete for RTX 3090's 24 GB
- **Mitigation:** Budget: Whisper large-v3 (3 GB) + Kokoro (0.5 GB) + Ollama qwen3:8b (5 GB) = ~8.5 GB. Plenty of headroom. Monitor with `nvidia-smi` Behavior.
- **Failure mode:** If VRAM is full, `WhisperModel` init fails → fall back to CPU Whisper (slower but functional)

### Audio pipeline stall
- **Risk:** `run_in_executor()` for STT/TTS blocks all executor threads
- **Mitigation:** Use a dedicated `ThreadPoolExecutor(max_workers=2)` for STT/TTS, separate from the default executor used by `asyncio`
- **Failure mode:** If synthesis takes too long (>5s), timeout and skip

### LLM timeout
- **Risk:** LiteLLM proxy or upstream model is slow/unavailable
- **Mitigation:** 10-second timeout on `acompletion()`. If no tokens in 10s, speak "I'm having trouble connecting right now" and stay in LISTENING
- **Failure mode:** Graceful degradation, not crash

### Echo cancellation failure
- **Risk:** PipeWire AEC module crashes or misconfigures → system hears itself
- **Mitigation:** Monitor for "self-hearing" (wake word triggers during SPEAKING state). If detected, suppress conversation buffer during SPEAKING.
- **Failure mode:** System talks to itself in a loop (capped by max turns per session = 20)

### Conversation runaway
- **Risk:** LLM generates excessively long responses
- **Mitigation:** Max response tokens (256), max TTS sentence queue depth (5 sentences), max conversation turns (20)
- **Failure mode:** Response truncated, user can ask for more

### Concurrent pipeline access
- **Risk:** Wake word fires while consent session is running
- **Mitigation:** Existing `_consent_session_active` flag and `session.is_active` check prevent this. Only one pipeline at a time.

---

## 13. Implementation Plan

### Phase 1: Core Pipeline (PR #1)

Build the minimum viable conversation: wake word → listen → transcribe → respond → speak → listen.

1. **`conversation_buffer.py`** — ConversationBuffer class
   - Ring buffer with VAD-gated accumulation
   - Speech start/end detection from VAD probability stream
   - Pre-roll buffer (300ms of audio before speech start)
   - `feed_audio(frame)` and `get_utterance() -> bytes | None`

2. **`resident_stt.py`** — ResidentSTT class
   - faster-whisper model loaded once, kept resident
   - `async transcribe(audio: bytes) -> str`
   - Runs in dedicated thread pool executor

3. **`conversation_pipeline.py`** — ConversationPipeline class
   - State machine: IDLE → LISTENING → TRANSCRIBING → THINKING → SPEAKING
   - Holds conversation history (messages list)
   - LLM streaming via `litellm.acompletion(stream=True)`
   - Sentence accumulator
   - TTS via existing `TTSManager.synthesize()` in executor
   - Audio playback via dedicated PyAudio output stream
   - Interruption detection (VAD during SPEAKING)

4. **Wire into `__main__.py`:**
   - Add ConversationBuffer as third consumer in `_audio_loop()`
   - Replace `_start_local_pipeline()` / `_stop_pipeline()` with ConversationPipeline lifecycle
   - Remove Pipecat imports and references

**Tests:** Unit tests for ConversationBuffer (VAD gating, pre-roll, utterance extraction), ResidentSTT (mock model), ConversationPipeline state machine (mock STT/LLM/TTS).

### Phase 2: Tool Calling (PR #2)

5. **Refactor `tools.py`:**
   - Convert `FunctionSchema` objects to OpenAI-format tool dicts
   - Change handler signatures from `params.result_callback()` to `async def handler(args: dict) -> str`
   - Keep all handler logic identical
   - Remove Pipecat imports

6. **Tool dispatch in ConversationPipeline:**
   - Detect `tool_calls` in LLM streaming response
   - Pause TTS, execute tool, inject result, resume LLM
   - Natural bridges: "Let me check..." spoken before tool execution

7. **Consent session migration:**
   - `consent_session.py` uses ConversationPipeline instead of Pipecat
   - Same CONSENT_SYSTEM_PROMPT and tool schemas (already OpenAI-format)
   - Remove Pipecat pipeline construction code

### Phase 3: Polish (PR #3)

8. **Conversation state as Behaviors:**
   - `conversation_active: Behavior[bool]`
   - `conversation_state: Behavior[str]`
   - `last_utterance: Behavior[str]`
   - Register in perception engine

9. **Interruption refinement:**
   - Test echo cancellation effectiveness during TTS
   - Tune VAD thresholds for interruption detection
   - Add partial response tracking in conversation history

10. **Remove Pipecat dependency:**
    - Delete `pipeline.py`, `pipecat_tts.py`, `frame_gate.py`
    - Remove `pipecat` from `pyproject.toml` dependencies
    - Update `config.py` to remove unused Pipecat-related fields

### Phase 4: Optimization (PR #4, optional)

11. **Speculative sentence start:** Begin synthesizing the first few tokens before the sentence boundary, cancel if the sentence changes direction
12. **VAD threshold tuning:** Experiment with 400ms vs 600ms end-of-speech
13. **Model selection:** A/B test `large-v3` vs `distil-large-v3` for accuracy/latency tradeoff
14. **Pre-warm greeting:** Synthesize and cache the wake-word acknowledgment phrase so it plays instantly

---

## 14. New Files

| File | Purpose |
|------|---------|
| `agents/hapax_voice/conversation_buffer.py` | VAD-gated audio accumulator |
| `agents/hapax_voice/resident_stt.py` | Persistent faster-whisper wrapper |
| `agents/hapax_voice/conversation_pipeline.py` | Main conversation orchestrator |
| `agents/hapax_voice/sentence_accumulator.py` | LLM token → sentence splitter |
| `agents/hapax_voice/audio_output.py` | Dedicated playback stream manager |

## 15. Deleted Files (Phase 3)

| File | Reason |
|------|--------|
| `agents/hapax_voice/pipeline.py` | Replaced by `conversation_pipeline.py` |
| `agents/hapax_voice/pipecat_tts.py` | Kokoro used directly via `tts.py` |
| `agents/hapax_voice/frame_gate.py` | Gating moves to ConversationBuffer |

## 16. Modified Files

| File | Change |
|------|--------|
| `agents/hapax_voice/__main__.py` | Third audio consumer, new pipeline lifecycle |
| `agents/hapax_voice/tools.py` | OpenAI-format schemas, simplified handler signatures |
| `agents/hapax_voice/consent_session.py` | Uses ConversationPipeline |
| `agents/hapax_voice/config.py` | New fields (vad_end_of_speech_ms, max_conversation_turns) |
| `pyproject.toml` | Remove pipecat dependency, ensure faster-whisper + litellm |
