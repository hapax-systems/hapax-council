# Studio-Aware Unified Perception Layer — Design Spec

> **Status:** Approved
> **Date:** 2026-03-10
> **Scope:** `agents/hapax_voice/` — perception, governance, and pipeline integration

## Problem

The voice daemon lacks environment awareness during active sessions. Three concrete failures:

1. **Interruption cascade** — background speech (e.g., child talking) triggers Pipecat's VAD → STT → cancels in-flight LLM response → LLM never completes → TTS never speaks
2. **No behavioral constraints** — daemon doesn't know when Ryan is in conversation, recording, or producing; it interrupts regardless
3. **Fragmented sensing** — audio classification, presence detection, workspace analysis, and webcam feeds operate independently with no unified state

## Goal

A unified perception layer that fuses audio and visual signals into a single `EnvironmentState` snapshot every 2-3 seconds, governs the active Pipecat pipeline (process/pause/withdraw), and detects studio conditions (conversation, production, recording) to enforce behavioral constraints.

---

## Section 1: Unified Perception Layer

### EnvironmentState

A frozen dataclass produced every perception tick, representing the fused audio-visual state:

```python
@dataclass(frozen=True)
class EnvironmentState:
    timestamp: float
    # Audio signals (fast tick)
    speech_detected: bool
    speech_volume_db: float
    ambient_class: str          # "silence", "speech", "music", "noise"
    vad_confidence: float       # 0.0-1.0

    # Visual signals (fast tick)
    face_count: int
    operator_present: bool      # face recognized as operator
    gaze_at_camera: bool        # operator looking at camera

    # Enriched signals (slow tick, carried forward)
    activity_mode: str          # coding, production, meeting, conversation, idle, away
    workspace_context: str      # free-text from LLM workspace analysis
    ambient_detailed: str       # PANNs classification label

    # Derived
    conversation_detected: bool  # face_count > 1 AND speech_detected
    directive: str              # "process", "pause", "withdraw" (set by Governor)
```

### PerceptionEngine

Owns the tick loop and produces `EnvironmentState` snapshots:

- **Fast tick (2-3s):** Reads audio VAD, face detection, gaze detection. Cheap signals only — no LLM calls, no heavy classifiers.
- **Slow enrichment (10-15s):** Runs workspace analysis (LLM), PANNs ambient classification, deeper visual analysis. Results carried forward between slow ticks.
- Publishes state to subscribers (Governor, context_gate, session manager).
- All cadences tunable via `VoiceConfig` for cost/latency tradeoffs.

---

## Section 2: Pipeline Governance

### PipelineGovernor

Translates `EnvironmentState` into pipeline directives:

| Condition | Directive | Effect |
|-----------|-----------|--------|
| Operator present, no conversation, not producing | `process` | Pipeline runs normally |
| Conversation detected (face_count > 1 + speech) | `pause` | FrameGate drops audio frames; pipeline frozen |
| Production/recording mode | `pause` | Same as above |
| Operator absent (no face for >60s) | `withdraw` | Session closes gracefully |
| Wake word detected | `process` | Always overrides pause |

### FrameGate

A Pipecat-compatible `FrameProcessor` inserted into the pipeline before STT:

```
transport.input() → FrameGate → STT → user_agg → LLM → TTS → transport.output()
```

- On `process`: passes all frames through
- On `pause`: drops `AudioRawFrame`s, passes control frames (needed for Pipecat lifecycle)
- On `withdraw`: sends end-of-stream frame to trigger graceful shutdown
- Reads directive from Governor (shared reference or callback)

---

## Section 3: Perception Tick Architecture

### Dual-Cadence Design

```
Fast Tick (every 2-3s):
  ├── Read Silero VAD buffer → speech_detected, vad_confidence
  ├── Read face detector → face_count, operator_present
  ├── Read gaze estimator → gaze_at_camera
  └── Fuse into EnvironmentState (carry forward slow signals)

Slow Tick (every 10-15s):
  ├── Run PANNs ambient classifier → ambient_detailed
  ├── Run workspace analysis (LLM) → activity_mode, workspace_context
  └── Update carried-forward fields for next fast tick
```

### Cost Profile

- Fast tick: ~0ms LLM cost, <50ms compute (VAD + face detection are already running)
- Slow tick: ~1 LLM call per 10-15s for workspace analysis, ~200ms for PANNs on CPU
- Tunable: increase slow tick interval to 30-60s to reduce cost; fast tick stays responsive

---

## Section 4: Conversation Mode & Resume Signals

### Conversation Detection

Triggered when `face_count > 1 AND speech_detected` persists for >3s (debounced to avoid false triggers from someone walking past).

Effects:
- Governor issues `pause` directive
- FrameGate drops audio frames — Pipecat's VAD never fires, no interruption cascade
- Session timeout clock pauses (conversation may last minutes)
- Notification delivery suppressed

### Resume Signals (priority order)

1. **Wake word** — always works, immediate resume regardless of environment state
2. **Gaze + environment clear** — operator looks at camera AND face_count == 1 AND no conversation speech for >5s
3. **Environment clear with delay** — face_count returns to 1, no conversation speech for >15s, auto-resume

All thresholds tunable via config. Easy to loosen if too aggressive.

---

## Section 5: Integration Points

### New Files

| File | Responsibility |
|------|---------------|
| `agents/hapax_voice/perception.py` | `EnvironmentState` dataclass + `PerceptionEngine` (tick loops, signal fusion) |
| `agents/hapax_voice/governor.py` | `PipelineGovernor` (state → directive mapping) |
| `agents/hapax_voice/frame_gate.py` | `FrameGate` Pipecat processor (drops/passes frames) |

### Modified Files

| File | Changes |
|------|---------|
| `agents/hapax_voice/__main__.py` | Wire PerceptionEngine + Governor into VoiceDaemon lifecycle |
| `agents/hapax_voice/pipeline.py` | Insert FrameGate before STT in pipeline construction |
| `agents/hapax_voice/config.py` | Add perception config fields (tick intervals, thresholds, gaze params) |
| `agents/hapax_voice/context_gate.py` | Simplify to read from PerceptionEngine instead of running own checks |
| `agents/hapax_voice/session.py` | Add `pause()`/`resume()` for timeout clock management |

### Config Additions

```python
# In VoiceConfig
perception_fast_tick_s: float = 2.5
perception_slow_tick_s: float = 12.0
conversation_debounce_s: float = 3.0
gaze_resume_clear_s: float = 5.0
environment_clear_resume_s: float = 15.0
operator_absent_withdraw_s: float = 60.0
```

---

## Tracked B-Path Items

Items tracked for future implementation (do not lose):

1. **Speaker isolation via voice enrollment** — distinguish operator voice from others without face detection; enables audio-only conversation detection
2. **Richer activity mode taxonomy** — monitoring, recording, active_production as distinct from generic "production"
3. **Proper gaze estimation model** — MediaPipe face mesh for accurate gaze vector; current version uses face bounding box heuristic
4. **Real-time (<1s) perception** — for specific high-value signals that need sub-tick response

## Other Tracked Items

- Pipecat `OpenAILLMContext` → `LLMContext` migration (deprecation warning)
- PipeWire echo cancellation routing (PyAudio can't access virtual nodes)
- TTSSettings NOT_GIVEN fix in `pipecat_tts.py`
- Streaming TTS for lower latency
- Silero VAD threshold tuning
