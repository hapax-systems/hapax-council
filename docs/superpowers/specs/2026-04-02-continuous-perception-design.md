# Continuous Perception During System Speech

**Date:** 2026-04-02
**Status:** Design approved, pending implementation plan
**Depends on:** CPAL spec (2026-04-01), grounding ledger (Batch 2), energy classifier (new)

## 1. Problem

The conversation buffer goes completely deaf during system output. Three hard gates in `conversation_buffer.py` drop all operator audio:

1. `feed_audio()`: `if self._speaking: return` — drops all frames during TTS
2. `update_vad()`: `if self._speaking: return` — ignores all VAD during TTS
3. `feed_audio()`/`update_vad()`: `if self.in_cooldown: return` — drops frames after TTS

This violates the CPAL spec's commitment (§7.4): "There is no phase that excludes another." Operator speech during system output — backchannels, grounding signals, floor claims — is silently discarded. The operator must repeat themselves or wait for system silence.

Pre-roll is always captured (line 155), but speech detection and utterance emission are completely dark during system output.

## 2. Constraints

### Engineering Reality

No production voice system achieves continuous perception with AEC alone. speexdsp provides ~30dB echo attenuation; the residual (-30 to -40 dBFS) triggers Silero VAD reliably. Removing all gates without secondary classification creates an echo loop, not continuous perception.

Production systems (LiveKit, Pipecat, GPT-4o, Gemini Live) all use layered approaches: AEC for echo reduction, secondary classifiers for residual echo discrimination, adaptive VAD thresholds during playback.

### Model Commitments

- Operator speech is never dropped (feedback: `feedback_never_drop_speech.md`)
- Perception never stops (CPAL spec §7.4)
- Operator backchannels during system speech are grounding signals (CPAL spec §8.1)
- Operator always wins the floor — Hapax yields at tier boundaries (CPAL spec §4.3)
- This is not traditional barge-in — operator speech during system speech is continuous perceptual data, not an interruption event

## 3. Architecture: Three-Layer Echo Discrimination

```
PipeWire mic source
    |
    +---> PipeWire webrtc AEC module (Layer 1)
    |     (reference = speaker output sink monitor, handled by PipeWire)
    |
    v
AEC-cleaned frames arrive at audio_loop()
    |
    +---> Energy-ratio classifier (Layer 2)
    |     Compares mic RMS against TTS energy ring buffer.
    |     During system speech: high correlation = residual echo -> suppress.
    |     Low correlation with high energy = real operator speech -> pass.
    |
    +---> Silero VAD with adaptive thresholds (Layer 3)
    |     System speaking: threshold 0.8, require 200ms sustained.
    |     System silent: threshold 0.5, require 90ms (current).
    |
    v
Speech classification
    |
    +-- If system silent: normal utterance path (unchanged)
    |
    +-- If system speaking:
        +-- Run speculative STT on detected speech (primary)
        |   +-- Phatic/backchannel ("yeah", "mm-hm", "okay", "right")
        |   |   -> Feed to grounding ledger as acceptance signal
        |   |   -> Do NOT interrupt production
        |   |
        |   +-- Substantive content
        |   |   -> Yield at next tier boundary
        |   |   -> Queue utterance for T3 processing
        |   |
        |   +-- STT timeout or ambiguous (fallback to duration-based)
        |       +-- < 1s: treat as backchannel
        |       +-- >= 1s: treat as floor claim -> yield
        |
        +-- Below classifier threshold: residual echo -> discard
```

### Layer 1: PipeWire webrtc AEC

Replace application-level speexdsp `EchoCanceller` with PipeWire's `libspa-aec-webrtc` module. Advantages:

- Includes nonlinear processing (NLP) stage that speexdsp lacks — critical for suppressing residual echo from speaker distortion and room reverb
- Runs at the audio server level before our process sees frames (cleaner separation of concerns)
- Reference signal handled automatically via sink monitor (no application-level `feed_reference()`)
- Ships with PipeWire, no additional dependencies

Configuration: `~/.config/pipewire/pipewire.conf.d/echo-cancel.conf`. Source: Blue Yeti mic. Sink: monitor of playback output. Verify ERLE >= 30dB.

### Layer 2: Energy-Ratio Classifier

New component `energy_classifier.py` (~80 lines).

During TTS synthesis, record RMS energy of each PCM chunk into a ring buffer (`TtsEnergyTracker`). During system speech, compare incoming mic frame RMS against the TTS energy envelope:

- High correlation between mic and TTS energy = residual echo (the mic is tracking what the speaker is playing)
- Low correlation with high mic energy = real operator speech (mic energy not explained by playback)
- Low energy overall = silence

Per-frame classification, stateless, computationally trivial (one RMS + one correlation per frame).

The TTS energy ring buffer replaces all `feed_reference()` calls — instead of feeding raw PCM to an echo canceller, we record the energy envelope for classification.

### Layer 3: Adaptive VAD

Silero VAD runs on every frame (no `_speaking` gate). Thresholds adapt based on system state:

| State | Confidence Threshold | Sustained Detection |
|-------|---------------------|-------------------|
| System silent | 0.5 (current default) | 90ms / 3 frames (current) |
| System speaking | 0.8 | 200ms / 7 frames |
| Post-TTS (first 500ms) | 0.7 | 150ms / 5 frames |

The higher threshold during system speech accounts for residual echo that passes through both PipeWire AEC and the energy classifier. The sustained detection requirement filters intermittent residual echo (which tends to be choppy) from real operator speech (which is continuous).

## 4. Speech During Production: Classification

When VAD detects speech during system output (passing both energy classifier and adaptive threshold), it must be classified before acting on it.

### Primary: Speculative STT

Run Whisper on the detected speech segment. Classify the transcript:

**Backchannel tokens** (phatic set): "yeah", "mm-hm", "mm", "right", "okay", "ok", "uh-huh", "sure", "got it", "I see", "go on"
- Feed to grounding ledger as acceptance evidence for current DU
- Update GQI (EWMA acceptance component)
- Apply small positive CPAL gain delta (operator is engaged)
- Do NOT interrupt production

**Substantive content** (anything not in phatic set):
- Yield production at next tier boundary (`production.yield_to_operator()`)
- Queue utterance bytes for normal T3 processing after production stops
- Call `set_speaking(False)` to exit system speech state

### Fallback: Duration-Based

When STT can't classify in time (GPU contention with Kokoro TTS, or STT latency exceeds useful window):

- Speech duration < 1s: treat as backchannel
- Speech duration >= 1s: treat as floor claim, yield

Duration is a reliable first-order signal — backchannels are short by nature (typically 200-500ms).

## 5. Components Changed

### Removed

- `echo_canceller.py` — entire file. PipeWire webrtc AEC replaces it.
- All `feed_reference()` calls (6 sites: runner.py:380, conversation_pipeline.py:697, 1241, 1362, 1721, production_stream.py via callback)
- `_speaking` gate in `conversation_buffer.feed_audio()` (line 158-159)
- `_speaking` gate in `conversation_buffer.update_vad()` (line 178-179)
- `in_cooldown` gate in `conversation_buffer.feed_audio()` (line 161-162)
- `in_cooldown` property and all cooldown machinery (`POST_TTS_COOLDOWN_S`, `_dynamic_cooldown_s`, `_speaking_ended_at` cooldown calculation)
- `echo_canceller` parameter from `ConversationPipeline.__init__`
- `echo_canceller.process()` call in `run_loops.py` audio loop (line 46-47)
- `EchoCanceller` initialization in `pipeline_start.py`

### New: `energy_classifier.py` (~80 lines)

```python
class TtsEnergyTracker:
    """Ring buffer of TTS output RMS energy for echo classification."""
    def record(self, pcm: bytes) -> None: ...  # called at each TTS write
    def is_active(self) -> bool: ...  # True when system has spoken recently
    def expected_energy(self) -> float: ...  # current expected echo energy level

class EnergyClassifier:
    """Per-frame classification: speech vs residual echo vs silence."""
    def __init__(self, tracker: TtsEnergyTracker): ...
    def classify(self, mic_frame: bytes, system_speaking: bool) -> str: ...
    # Returns: "speech" | "echo" | "silent"
```

### New: `speech_classifier.py` (~60 lines)

```python
class DuringProductionClassifier:
    """Classify operator speech detected during system output."""
    def __init__(self, stt, phatic_tokens: set[str]): ...
    async def classify(self, speech_frames: list[bytes]) -> ClassifyResult: ...
    # Returns: BackchannelSignal | FloorClaim

@dataclass
class BackchannelSignal:
    transcript: str
    confidence: float

@dataclass  
class FloorClaim:
    utterance_bytes: bytes
    transcript: str
```

### Modified: `conversation_buffer.py`

- `feed_audio()`: always accumulates to speech_frames when speech_active. No `_speaking` or `in_cooldown` gates.
- `update_vad()`: always processes VAD probability. Receives `system_speaking: bool` parameter to select adaptive threshold. No `_speaking` gate.
- `set_speaking()`: tracks state for adaptive threshold selection only. No longer gates audio.
- Remove: `in_cooldown` property, `_dynamic_cooldown_s`, `POST_TTS_COOLDOWN_S`, `_speaking_ended_at` cooldown logic.

### Modified: `run_loops.py`

- Remove `echo_canceller.process()` from audio loop
- Add `energy_classifier.classify(frame, system_speaking)` inline
- Pass classification result to conversation buffer (skip `feed_audio` only for "echo" frames)

### Modified: `cpal/runner.py`

- `_tick()` utterance dispatch (line 212): remove `buffer.is_speaking` from drain condition. During production, route detected speech to `DuringProductionClassifier`.
- Barge-in (line 261): replaced by `FloorClaim` from speech classifier
- New: feed `BackchannelSignal` to grounding ledger when detected during production
- T1 echo cooldown (1s) remains — T1 presynthesized audio could still self-loop without PipeWire AEC seeing it as "system output" (it goes through `audio_output.write`, which IS the monitored sink, so PipeWire AEC should handle it — verify empirically)

### Modified: `conversation_pipeline.py`

- Remove all `echo_canceller` references and `feed_reference()` calls
- Replace with `TtsEnergyTracker.record(pcm)` at each TTS write point
- Remove `echo_canceller` parameter from `__init__`
- `_is_echo()` transcript-level detection remains as safety net

### Modified: `pipeline_start.py`

- Remove `EchoCanceller` initialization
- Add `TtsEnergyTracker`, `EnergyClassifier`, `DuringProductionClassifier` initialization
- Wire into CPAL runner and conversation pipeline

### Config: PipeWire webrtc AEC

New file: `~/.config/pipewire/pipewire.conf.d/echo-cancel.conf`

```
context.modules = [
    {
        name = libpipewire-module-echo-cancel
        args = {
            capture.props = {
                node.name = "echo_cancel_capture"
            }
            source.props = {
                node.name = "echo_cancel_source"
            }
            playback.props = {
                node.name = "echo_cancel_playback"
            }
            sink.props = {
                node.name = "echo_cancel_sink"
            }
            aec.method = webrtc
        }
    }
]
```

Daemon's `audio_input.py` already targets `echo_cancel_capture` by default.

## 6. Grounding Integration

When `BackchannelSignal` is detected during system speech:
- Grounding ledger receives acceptance evidence for the current DU
- GQI updates (EWMA acceptance component)
- No interruption to production stream
- CPAL gain gets small positive delta (+0.02, source="operator_backchannel")

When `FloorClaim` is detected:
- Production stream yields at current tier boundary (`production.yield_to_operator()`)
- Utterance queued for normal T3 processing after production stops
- `set_speaking(False)` called to exit system speech state
- CPAL gain gets moderate positive delta (+0.1, source="floor_claim")

## 7. What This Preserves

- Pre-roll always captured (unchanged, line 155)
- Echo detection at transcript level (`_is_echo()`) remains as safety net
- Speaker identification remains
- Effort calibration drives response length (unchanged)
- T1 echo cooldown (1s) remains for presynthesized audio
- Consent gating remains
- Session lifecycle unchanged (gain-based, not event-based)

## 8. Verification Plan

1. **PipeWire AEC ERLE measurement**: play known signal, measure attenuation. Target >= 30dB.
2. **Energy classifier accuracy**: during system speech, speak and verify classification as "speech" not "echo". Verify silence correctly classified.
3. **Backchannel detection**: say "mm-hm" during system speech, verify grounding ledger receives acceptance, production not interrupted.
4. **Floor claim detection**: speak a sentence during system speech, verify production yields and utterance queued.
5. **No echo loop**: system speaks, verify no false utterance detection from residual echo.
6. **Transcript-level safety net**: verify `_is_echo()` still catches any leaked echo transcripts.

## 9. Risks

- **PipeWire webrtc AEC may underperform** in the studio environment (multiple speakers, reflective surfaces). Mitigation: energy classifier + adaptive VAD provide defense in depth.
- **Speculative STT during TTS contends for GPU** (Whisper + Kokoro). Mitigation: duration-based fallback. Monitor VRAM.
- **Phatic token set too narrow/broad**. Mitigation: start conservative, expand based on grounding ledger data.
- **T1 presynthesized audio may not route through PipeWire AEC correctly** if the audio output path bypasses the echo-cancel sink. Verify empirically; keep T1 echo cooldown as backup.
