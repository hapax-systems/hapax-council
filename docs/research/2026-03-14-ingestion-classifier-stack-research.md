# Ingestion Classifier Stack — Research Record

**Date:** 2026-03-14
**Status:** Research complete, pending design document
**Scope:** 24/7 audio+video studio capture, classification, prompt-searchable sample library, behavioral observability

---

## Problem Statement

The operator runs an experimental hip hop production studio with 4 cameras (1 BRIO + 3 C920, expanding to 7) and a Blue Yeti microphone. All observation data is potential production material: samples, freestyles, visual content, lyrics, ideas. The system must:

1. Capture 24/7 audio and video from all sources
2. Immediately discard obvious nothing (silence, static)
3. Deeply classify everything that survives across multiple concerns
4. Make all audio retrievable by natural language prompt
5. Feed an autonomous value-based storage management system (value arbiter)
6. Provide behavioral/emotive observability (flow state, energy, mood)
7. Never interfere with the existing perception layer (voice daemon)

---

## Research Iterations

Three research passes were conducted, each refining the previous.

### Pass 1: Initial Candidate Stack (14+ models)

Identified candidate models across three tiers. Key models: PANNs, CLAP, Essentia, HuBERT, emotion2vec+, Whisper, Demucs, MT3, madmom, MERT, MediaPipe, HSEmotion, VitalLens, SongFormer.

### Pass 2: Consolidation (13 models)

Dropped PANNs (subsumed by CLAP), SpeechBrain (subsumed by emotion2vec+), identified MuQ-MuLan and SongFormer as additions. Proposed tiered architecture.

### Pass 3: Verification + Hapax Fitness (final)

Verified every model claim. Significant corrections and drops. Deep evaluation of hapax ecosystem integration.

---

## Final Verified Stack

### Always-On (~600MB VRAM)

| # | Model | What | Hardware | Latency | Verified |
|---|---|---|---|---|---|
| 1 | RMS energy gate | Discard silence before any model loads | CPU | <1ms | N/A (DSP) |
| 2 | Silero VAD v5 | Voice/silence gate | CPU, 2MB | <1ms/30ms chunk | Yes |
| 3 | CLAP `laion/larger_clap_music_and_speech` | Audio embedding (512-dim) + zero-shot classification. THE core model. | GPU, ~600MB | ~50ms/10s chunk | Yes |
| 4 | Essentia | Exact BPM, key, spectral centroid, onset strength, loudness LUFS, dynamic complexity | CPU, 0 VRAM | ~30ms | Yes |
| 5 | MediaPipe BlazeFace | Face detection + landmarks. Shared with voice daemon. | CPU | <5ms/frame | Yes |
| 6 | HSEmotion (ONNX) | Facial emotion from face crop (7 emotions + valence/arousal) | CPU, ~50MB | ~20ms/frame | Yes |
| 7 | Olaf | Audio fingerprinting for replay detection. Strongest sample-worthiness signal. | CPU, 250KB | Negligible | Yes |

### Conditional (~900MB peak, loaded on detection)

| # | Model | Trigger | What | VRAM |
|---|---|---|---|---|
| 8 | emotion2vec+ base | Speech detected | 9-class emotion + valence/arousal | ~180MB |
| 9 | distil-whisper-small.en | Speech >3s | Real-time transcription (166M params, 6x faster than standard) | ~330MB |
| 10 | beat_this | Music detected | SOTA beat/downbeat tracking (ISMIR 2024, replaces madmom) | PyTorch GPU |

### On-Demand (loaded exclusively)

| # | Model | Trigger | What | VRAM |
|---|---|---|---|---|
| 11 | Demucs v4 TRT | High-value moment | Stem separation. 15-min segment in ~40s on RTX 3090. | ~1GB |
| 12 | faster-whisper large-v3-turbo | Batch transcription | Already exists in audio_processor. int8 CUDA. | ~1.5GB |
| 13 | SongFormer | Music structure analysis | Verse/chorus/bridge/intro detection (Oct 2025 SOTA) | ~200MB |
| 14 | DOSE | One-shot extraction | Extract clean kick/snare/hat from mixed audio (ICASSP 2025) | TBD |

### Future / Deferred

| Model | Why Deferred |
|---|---|
| HuBERT base + custom vocal type head | Needs ~400 labeled examples. Bootstrap from operator recordings over time. |
| MuQ-MuLan | 700M params, 128-dim. Add only if CLAP retrieval proves insufficient for music-specific queries. |
| Qwen3-Omni-30B-A3B | Deep multimodal analysis. Add via tabbyAPI when needed. |

---

## Models Dropped (with reasons)

| Model | Reason |
|---|---|
| PANNs CNN14 (in ingestion) | CLAP subsumes classification + adds text alignment. Keep in voice daemon only (CPU, interrupt gating). |
| SpeechBrain | emotion2vec+ is SOTA for SER, eliminates need. |
| Essentia genre_discogs400 | CLAP zero-shot handles genre adequately. |
| MT3 (music transcription) | Not needed for sample library workflow. DOSE + beat_this cover the useful subset. |
| MERT | MuQ-MuLan was considered but also dropped. CLAP sufficient initially. |
| allin1 | Superseded by SongFormer (2025 SOTA). |
| ImageBind / LanguageBind / ONE-PEACE | Domain-specific models (CLAP + CLIP) beat generalists. Generalists are too large (7-30B). |
| VitalLens 2.0 | Deep learning model is API-only (paid). Dim orange studio lighting hostile to rPPG. Pixel Watch HR/HRV via Health Connect is vastly more reliable. |
| madmom | Superseded by beat_this (same research group, ISMIR 2024, simpler, better accuracy). |
| Breathing rate from MediaPipe Pose | Infeasible at 1 frame/30-60s (needs 5+ fps). Pixel Watch provides respiratory rate. |
| Qwen3-Omni-30B-A3B | Autoregressive LLM wrong for streaming classification. Defer to tabbyAPI. |
| MuQ-MuLan | 700M params, 128-dim embeddings. Marginal benefit over CLAP. Doubles Qdrant complexity. |

---

## CLAP Variant Selection

| Checkpoint | Training Data | Embedding Dim | ESC50 Accuracy |
|---|---|---|---|
| `laion/larger_clap_music` | Music + AudioSet | 512 | 90.14% |
| `laion/larger_clap_music_and_speech` | Music + Speech + AudioSet | 512 | 89.98% |
| `laion/larger_clap_general` | General + music + speech | 512 | — |
| `microsoft/clap-htsat-fused` | Older, different architecture | 512 | — |

**Selected: `laion/larger_clap_music_and_speech`** — explicitly trained on both music and speech modalities, matching the studio's mixed audio environment. No 2025-2026 successor found.

---

## Pipeline Decision Tree

```
RAW AUDIO+VIDEO FEED (continuous)
|
+- [Gate 0: RMS Energy] --- threshold (zero-cost DSP)
|   '- Below threshold -> discard, log timestamp
|
+- [Gate 1: Silero VAD] --- voice activity (CPU, <1ms)
|   +- Speech detected -> route to Speech Pipeline
|   '- No speech -> route to Audio-Only Pipeline
|
+- [Gate 2: CLAP] --- embedding + zero-shot classification (GPU, ~600MB)
|   +- Generates 512-dim embedding -> Qdrant studio_moments
|   +- Cosine similarity to music/instrument centroids
|   |   '- Music detected -> route to Music Pipeline
|   '- Other (ambient, equipment) -> tag & store metadata only
|
+- [Gate 3: Olaf] --- fingerprint against rolling buffer
|   '- Replay detected -> boost sample-worthiness score
|
+- [Gate 4: Video] --- MediaPipe BlazeFace (CPU)
    +- Face detected -> HSEmotion (emotion classification)
    '- Pose landmarks -> activity/engagement heuristics

SPEECH PIPELINE (conditional):
  +- emotion2vec+ base (~180MB) -> emotion labels
  +- distil-whisper-small.en (~330MB) -> transcription
  '- HuBERT + head (future) -> vocal type

MUSIC PIPELINE (conditional):
  +- Essentia -> exact BPM, key, spectral features (CPU)
  +- beat_this -> beat grid + downbeats (GPU)
  '- IF high-value:
      +- Demucs v4 TRT -> stem separation (~1GB)
      +- DOSE -> one-shot extraction
      '- SongFormer -> structure analysis
```

---

## Qdrant Collection Design

### New collection: `studio_moments`

- **Vector:** CLAP 512-dim, cosine distance
- **Separate from:** existing `documents` (768-dim nomic text embeddings)
- **CLAP embeddings generated in-process** (not via Ollama — Ollama doesn't serve CLAP)

**Payload schema:**
```json
{
  "timestamp_start": "2026-03-14T02:30:00",
  "timestamp_end": "2026-03-14T02:30:45",
  "session_id": "session-20260314-0200",
  "category": "sample-session",
  "instruments": ["drums", "bass", "horns"],
  "bpm": 92.5,
  "key": "Cm",
  "energy_db": -12.3,
  "spectral_centroid": 2400.0,
  "loudness_lufs": -14.2,
  "onset_strength": 0.73,
  "has_speech": true,
  "vocal_type": "freestyle",
  "speech_emotion": "happy",
  "facial_emotion": "neutral",
  "flow_state_score": 0.78,
  "replay_count": 3,
  "structure_label": "verse",
  "transcript": "...",
  "has_stems": false,
  "source_file": "rec-20260314-023000.flac",
  "duration_s": 45.2
}
```

---

## Flow State Detection (Revised)

Camera-based rPPG dropped. Flow state computed from composite signals:

| Signal | Source | Weight | Notes |
|---|---|---|---|
| HRV (SDNN) | Pixel Watch via Health Connect | High | U-shaped: low HRV = flow (Nature 2025) |
| Heart rate | Pixel Watch via Health Connect | Medium | Moderate HR indicates flow |
| Facial emotion | HSEmotion | Medium | Neutral-to-positive valence, moderate arousal |
| Pose stability | MediaPipe | Medium | Engaged but not fidgeting |
| Sustained activity | Session timer | High | >15 min uninterrupted task engagement |
| Replay detection | Olaf | Low | Replaying = engaged with material |

**State machine:** idle -> warming-up -> active -> flow -> winding-down. 5-minute hysteresis to prevent noisy transitions.

---

## Sample-Worthiness Scoring

No single model exists. Composite signal:

| Signal | Source | Description |
|---|---|---|
| Replay count | Olaf fingerprinting | Producer loops/replays -> strong interest signal |
| Spectral novelty | Essentia spectral flux | High flux relative to context = something changed |
| Onset transient quality | Essentia onset strength + spectral flatness | Sharp clean transients = one-shot candidates |
| CLAP embedding distance | CLAP cosine distance from recent context | Outlier segments are more "interesting" |
| Classification richness | CLAP zero-shot | Multi-class > mono-class |
| Beat alignment | beat_this | Clean rhythmic boundaries = loop candidates |

---

## Compute Budget

### VRAM (RTX 3090, 24GB)

| Tier | Models | VRAM |
|---|---|---|
| Always-on | CLAP + HSEmotion | ~650MB |
| Conditional (all loaded) | emotion2vec+ + distil-whisper + beat_this | ~900MB |
| Peak concurrent (Tier 1 + 2) | All above | ~1.5GB |
| On-demand (Demucs) | + Demucs v4 TRT | ~2.5GB |
| Ollama (nomic-embed) | Existing | ~1.4GB |
| **Total peak** | | **~3.9GB** |

21GB headroom for Ollama LLM inference, tabbyAPI, etc.

### Processing Time (15-min audio segment)

| Stage | Time | Hardware |
|---|---|---|
| RMS + VAD gate | <1s | CPU |
| CLAP embedding (90 chunks) | ~4.5s | GPU |
| Essentia features | ~2s | CPU |
| Olaf fingerprinting | <1s | CPU |
| emotion2vec+ (speech segments) | ~10s | GPU |
| distil-whisper (speech segments) | ~15s | GPU |
| beat_this (music segments) | ~5s | GPU |
| **Total** | **~38s** | |

**24x real-time headroom.** Comfortable for 24/7 operation.

---

## Hapax Ecosystem Integration — Critical Findings

### 1. Voice Daemon Coexistence

- PANNs stays in voice daemon (CPU, interrupt gating). CLAP runs in ingestion pipeline (GPU, embeddings). No model conflict.
- Ingestion pipeline registers as a `PerceptionBackend` via voice daemon's perception engine.
- Audio sources coexist in PipeWire — multiple readers on same source natively supported.
- **VRAM lock at `~/.cache/hapax-voice/vram.lock` must be respected** for all GPU model loading.
- Voice daemon's `_normalize_color()` (gray-world for orange lighting) shared with HSEmotion preprocessing.

### 2. Audio Processor Extension

- Existing `audio_processor.py` has 4-category classification, 40+ instrument labels, speaker diarization, RAG output. Battle-tested.
- New stack extends it: add CLAP embeddings, beat_this, DOSE, Olaf.
- Replace PANNs with CLAP in ingestion pipeline (not in voice daemon).
- Batch processing (audio_processor) and real-time classification (new pipeline) share model code, run independently.

### 3. Reactive Engine Integration

- GPU semaphore (Phase 1) allows only 1 concurrent action. Heavy GPU work queues behind RAG embedding.
- `QuietWindowScheduler` pattern for batching audio chunks.
- New rules: `audio-chunk-ready` (Phase 1), `studio-moment-detected` (Phase 0), `flow-state-changed` (Phase 0).

### 4. Constitution — Governance Gaps

#### 4a. Guest Recording (No axiom covers this)

`su-privacy-001` (T0) scopes to "the user." Studio guests are not the user. Personal domain heuristic says "Record only what operator explicitly shares" — passive 24/7 capture violates this at domain level. Needs new `interpersonal_transparency` axiom or amendment.

#### 4b. Work Call Bridge Violation

`mg-bridge-001` (T1): Work PII captured in personal domain recording when operator takes work calls in studio. Transcripts could contain team member names, performance discussions. Needs bridge zone classifier.

#### 4c. Value Arbiter vs Memory Obligation

`ex-memory-010` (T2) says "automatically capture and surface relevant historical context." Aggressive deletion conflicts. The arbiter needs a sufficiency floor — minimum retention to serve the memory obligation.

### 5. Officium — No Integration

Management-only domain. Axioms actively block behavioral/emotional data from management flows. Only coordinate on Ollama GPU contention via systemd resource limits.

---

## Key Sources

- [LAION CLAP](https://github.com/LAION-AI/CLAP) — [larger_clap_music_and_speech](https://huggingface.co/laion/larger_clap_music_and_speech)
- [Silero VAD v5](https://github.com/snakers4/silero-vad)
- [Essentia](https://essentia.upf.edu/)
- [emotion2vec+](https://github.com/ddlBoJack/emotion2vec) — [HF](https://huggingface.co/emotion2vec/emotion2vec_plus_large)
- [distil-whisper](https://github.com/huggingface/distil-whisper)
- [beat_this](https://github.com/CPJKU/beat_this) (ISMIR 2024)
- [Demucs v4 TRT](https://huggingface.co/MansfieldPlumbing/Demucs_v4_TRT)
- [SongFormer](https://huggingface.co/ASLP-lab/SongFormer) — [GitHub](https://github.com/ASLP-lab/SongFormer/)
- [DOSE](https://github.com/HSUNEH/DOSE) (ICASSP 2025)
- [Olaf](https://github.com/JorenSix/Olaf) — lightweight acoustic fingerprinting
- [HSEmotion / EmotiEffLib](https://github.com/sb-ai-lab/EmotiEffLib) — [ONNX](https://github.com/av-savchenko/hsemotion-onnx)
- [MuQ-MuLan](https://huggingface.co/OpenMuQ/MuQ-MuLan-large) (deferred)
- [Hip-hop sample identification](https://arxiv.org/abs/2502.06364) — [GNN refinement](https://arxiv.org/abs/2506.14684)
- [Flow state physiology](https://www.nature.com/articles/s41598-025-95647-x) (Nature 2025)
- [voice2mode](https://arxiv.org/html/2602.13928) — vocal type classification feasibility
