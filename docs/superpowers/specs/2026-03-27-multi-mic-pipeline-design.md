# Multi-Mic Audio Pipeline + Target Speaker Extraction

**Date:** 2026-03-27
**Queue Item:** #013
**Status:** Design approved

## Overview

Three-layer enhancement to the hapax-voice audio pipeline:

1. Replace PyAudio-based noise reference capture with pw-record multi-source capture
2. Add enrollment quality validation and stability metrics
3. Benchmark target speaker extraction (TSE) models for real-time viability

## Layer 1: Multi-Source Noise Reference via pw-record

### Problem

The current `multi_mic.py` uses PyAudio to capture from reference mics. Two issues:

1. **Single source match** — substring matching on PyAudio device names finds only the first C920. Three C920s and one BRIO are available as reference sources.
2. **Default-source conflict** — the contact mic (PipeWire virtual source) uses `pactl set-default-source` to route through PyAudio's default device. This conflicts with the Yeti also needing to be the default source for primary capture.

### Design

Replace `NoiseReference._capture_loop()` internals with `pw-record` subprocesses. Each reference source gets its own subprocess writing raw PCM s16le mono 16kHz to stdout. The existing daemon thread reads from the subprocess pipe and updates the noise estimate via STFT + exponential smoothing, unchanged.

```
pw-record --target <node-name> --format s16 --rate 16000 --channels 1 -
```

**Source discovery:** At startup, enumerate PipeWire sources via `pactl list sources short`. Match each source name against configured patterns. Start one pw-record subprocess per matched source.

**Noise estimate aggregation:** Replace the single `_noise_estimate: np.ndarray` with `_room_estimates: dict[str, np.ndarray]` keyed by source name. Each capture thread updates its own entry. The `subtract()` method averages all room estimates into a single magnitude spectrum before applying spectral subtraction. Structure-borne estimates remain separate (single contact mic).

**Config changes to `VoiceConfig`:**

```python
noise_ref_room_patterns: list[str] = ["HD Pro Webcam C920", "Logitech BRIO"]
noise_ref_structure_patterns: list[str] = ["Contact Microphone"]
```

These replace the hardcoded `"HD Pro Webcam C920"` string in `__main__.py`. The existing `contact_mic_source` field remains for the contact_mic backend but is no longer used for noise reference routing.

**Subprocess lifecycle:** Each pw-record process is managed by the thread that reads it. On subprocess death, the thread logs a warning, waits 2s, and restarts. On `NoiseReference.stop()`, all subprocesses are terminated via SIGTERM.

**Fallback:** If pw-record is not available or a source pattern matches nothing, log a warning and continue without that reference. Same graceful degradation as today.

### Spectral subtraction parameters (unchanged)

| Parameter | Airborne (room mics) | Structure (contact mic) |
|-----------|---------------------|------------------------|
| Alpha (oversubtraction) | 1.5 | 1.0 |
| Beta (spectral floor) | 0.01 | 0.02 |
| FFT size | 512 | 512 |
| Hop size | 256 | 256 |
| Smoothing | 0.7 | 0.7 |

### Hardware sources

| Device | Type | PipeWire pattern | Count |
|--------|------|-----------------|-------|
| Blue Yeti | Primary mic (not a reference) | `Blue_Microphones_Yeti` | 1 |
| Logitech C920 | Airborne reference | `HD Pro Webcam C920` | 3 |
| Logitech BRIO | Airborne reference | `Logitech BRIO` | 1 |
| Cortado MKIII | Structure reference | `Contact Microphone` | 1 |
| PreSonus Studio 24c | Not used | — | 1 |

## Layer 2: Enrollment Quality Validation

### Problem

The current enrollment flow records 10 samples, averages embeddings, and saves. No quality metrics are reported. The current enrollment (Mar 18) has unknown sample count and quality. The 0.60 accept threshold in `speaker_id.py` may produce false negatives at desk distance.

### Design

Add a validation phase to `enrollment.py` after sample collection, before saving:

1. **Pairwise similarity matrix** — cosine similarity between all sample embedding pairs. Report min, max, mean, stddev. Healthy enrollment: mean >0.70, stddev <0.10.

2. **Outlier detection** — any sample with mean pairwise similarity <0.50 is flagged. User is prompted to drop flagged samples and re-average.

3. **Threshold test** — similarity between the final averaged embedding and each individual sample. If any sample falls below 0.60 (the accept threshold), warn that the threshold may produce false negatives at the distances/conditions represented by that sample.

4. **Stability report** — printed to terminal and saved as `~/.local/share/hapax-voice/enrollment_report.json`:

```json
{
  "timestamp": "2026-03-27T17:00:00Z",
  "sample_count": 10,
  "dropped_samples": 1,
  "pairwise_similarity": {
    "min": 0.62,
    "max": 0.89,
    "mean": 0.74,
    "stddev": 0.07
  },
  "threshold_test": {
    "accept_threshold": 0.60,
    "samples_below_threshold": 0,
    "min_similarity_to_average": 0.68
  },
  "embedding_shape": [512]
}
```

**No changes to `speaker_id.py`** — thresholds and identification logic stay as-is. If the report suggests adjustment, that is a manual decision.

**Enrollment CLI remains interactive.** The 10 prompts and recording flow are unchanged. Only the post-collection analysis is new.

## Layer 3: Target Speaker Extraction Benchmark

### Problem

The current pipeline uses spectral subtraction (noise reference) + post-hoc speaker verification (pyannote cosine similarity). This is a two-step process: remove noise, then check who's speaking. TSE could improve this by replacing spectral subtraction with neural source separation, producing a cleaner operator voice signal. The separation is still two-stage internally (blind separate → identify operator channel), but the output quality should exceed spectral subtraction.

### Design

A standalone benchmark script `agents/hapax_voice/tse_benchmark.py` that evaluates TSE viability on the current hardware.

**Architecture note:** No pretrained target-speaker-extraction model exists that takes a speaker embedding as conditioning input and outputs only that speaker's voice. SpeechBrain's separation models are **blind source separation** — they split a mixture into N channels without knowing which channel is which. The practical approach is two-stage: (1) blind-separate with SepFormer/ConvTasNet, (2) identify the operator's channel via ECAPA-TDNN cosine similarity against the enrolled embedding.

**Models evaluated:**
- SpeechBrain `sepformer-wsj02mix` — transformer-based, 2-speaker separation, 8kHz
- Asteroid `ConvTasNet_Libri2Mix_sepclean_16k` — convolutional, 2-speaker, 16kHz (matches our pipeline sample rate)
- SpeechBrain `spkrec-ecapa-voxceleb` — speaker embedding for channel identification (may replace pyannote)

**Sample rate constraint:** WSJ0Mix models are trained at 8kHz. Our pipeline runs at 16kHz. The Asteroid ConvTasNet variant at 16kHz is preferred for this reason. Resampling (16k→8k→16k) is an option for SepFormer but adds latency and quality loss.

**Test inputs:**
- Synthetic: operator voice (from enrollment samples) mixed with recorded C920 room noise at various SNRs
- Real captures from `~/.local/share/hapax-voice/` if available

**Two-stage pipeline benchmark:**

| Stage | Model | Input | Output |
|-------|-------|-------|--------|
| 1. Separate | SepFormer or ConvTasNet | mixed audio | N separated channels |
| 2. Identify | ECAPA-TDNN cosine similarity | each channel + enrolled embedding | operator channel index |

**Measurements per model combo, per device (GPU and CPU):**

| Metric | Target |
|--------|--------|
| Combined latency (30ms frame / 480 samples) | <50ms p95 |
| Combined latency (500ms chunk / 8000 samples) | <500ms p95 |
| VRAM delta (GPU only) | <4GB for all models |
| Output SNR improvement | positive |

Latency measured over 100 runs, reporting p50/p95/p99. "Combined" means separation + channel identification.

**VRAM safety:** Before loading any model on GPU, check `nvidia-smi` for available VRAM. If <4GB free, skip GPU benchmark and note in report. Never OOM existing workloads (Ollama, visual surface, studio compositor).

**Report output:** `~/.local/share/hapax-voice/tse_benchmark_report.json` with per-model-combo, per-device results and a go/no-go recommendation.

**If go:** Create `agents/hapax_voice/target_speaker.py` with:

```python
class TargetSpeakerExtractor:
    def __init__(self, separation_model: str, device: str, enrollment_path: Path) -> None: ...
    def extract(self, frame: bytes) -> bytes: ...
```

Internally runs blind separation then picks the operator channel. Same external interface as `NoiseReference.subtract()` so it slots into the pipeline chain. Lazy model loading, same pattern as `speaker_id.py`.

**If no-go:** The benchmark report is the deliverable. Documents why TSE is not viable and what would change the answer (faster hardware, longer frame windows, model distillation, future availability of true conditioned TSE models).

## Integration

### Pipeline chain

```
Blue Yeti (16kHz, 480 samples/30ms)
  → speexdsp AEC (echo_canceller.py)
  → multi_mic.py spectral subtraction (pw-record, all refs averaged)
  → [IF TSE viable] target_speaker.py extraction
  → audio_preprocess.py (80Hz highpass → noise gate → RMS normalize)
  → VAD (Silero) → STT (Whisper) → LLM → TTS
```

If TSE is viable, spectral subtraction and TSE can coexist (subtraction for broadband, TSE for voice isolation) or TSE can replace subtraction. The benchmark report informs this decision — not determined at design time.

### Files modified

| File | Change |
|------|--------|
| `agents/hapax_voice/multi_mic.py` | Replace PyAudio with pw-record, multi-source averaging |
| `agents/hapax_voice/enrollment.py` | Add validation phase + stability report |
| `agents/hapax_voice/config.py` | Add `noise_ref_room_patterns`, `noise_ref_structure_patterns` |
| `agents/hapax_voice/__main__.py` | Pass new config fields to NoiseReference, wire TSE if viable |

### Files created

| File | Purpose |
|------|---------|
| `agents/hapax_voice/tse_benchmark.py` | Standalone benchmark script |
| `agents/hapax_voice/target_speaker.py` | TSE class (only if benchmark says go) |

### Files unchanged

`speaker_id.py`, `audio_input.py`, `echo_canceller.py`, `audio_preprocess.py`, `cognitive_loop.py`, `backends/contact_mic.py`.

### Testing

- Unit tests for multi-source noise estimate averaging (mock pw-record output)
- Unit tests for enrollment validation math (known embeddings → expected similarity metrics)
- TSE benchmark is run manually, not a CI test

## Acceptance Criteria

1. Noise reference subtraction captures from all available C920s + BRIO via pw-record (measurable SNR improvement vs single-source)
2. Operator voice enrolled with multi-sample embedding; enrollment report shows mean pairwise similarity >0.70
3. TSE latency measured on RTX 3090 (GPU + CPU); go/no-go documented in benchmark report

## Constraints

- **Single operator axiom** — no multi-speaker enrollment, speaker ID is routing only
- **Consent** — biometric processing of non-operator speakers requires ConsentRegistry check (unchanged)
- **GPU budget** — RTX 3090 shared with Ollama, visual surface, compositor; TSE model must coexist
- **Frame budget** — 30ms frames at 16kHz; processing must complete within frame interval
- **PyAudio limitation** — eliminated by switching to pw-record for reference capture; primary mic capture in `audio_input.py` still uses PyAudio (out of scope)
