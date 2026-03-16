# Studio Ingestion Pipeline — Formal Design Document

**Date:** 2026-03-14
**Status:** Design complete, pending implementation planning
**Scope:** 24/7 audio+video capture, multi-dimensional classification, prompt-searchable sample library, behavioral observability, autonomous storage lifecycle
**Depends on:** Value arbiter design (2026-03-14), ingestion expansion plan (2026-03-13)

---

## 1. Problem Statement

The operator runs an experimental hip hop production studio with cameras and a Blue Yeti microphone. All observation data is potential production material: samples, freestyles, visual content, lyrics, ideas. The system must:

1. Capture 24/7 audio and video from all sources
2. Immediately discard obvious nothing (silence, static)
3. Deeply classify everything that survives across multiple concerns
4. Make all audio retrievable by natural language prompt
5. Provide behavioral/emotive observability (flow state, energy, mood)
6. Autonomously manage storage lifecycle (value arbiter)
7. Never interfere with the existing perception layer (voice daemon)
8. Comply with all constitutional axioms including interpersonal_transparency

### Design Constraints

- **Knowledge is permanent, storage is finite.** RAG documents, transcriptions, classifications, and embeddings persist forever. Only raw media files are subject to trimming.
- **Perception is king.** Ingestion never locks, blocks, or degrades the voice daemon's perception pipeline.
- **Single operator.** No multi-user features. Guest detection triggers consent-aware behavior.
- **Filesystem-as-bus.** All state in markdown + YAML frontmatter, git-versioned, human-readable.

---

## 2. Classifier Stack

### 2.1 Always-On (~650MB VRAM)

| # | Model | Purpose | Hardware | Latency |
|---|---|---|---|---|
| 1 | RMS energy gate | Discard silence before any model loads | CPU, DSP | <1ms |
| 2 | Silero VAD v5 | Voice/silence gate | CPU, 2MB | <1ms/30ms |
| 3 | CLAP `laion/larger_clap_music_and_speech` | Audio embedding (512-dim) + zero-shot classification | GPU, ~600MB | ~50ms/10s |
| 4 | Essentia | Exact BPM, key, spectral centroid, onset strength, loudness LUFS | CPU | ~30ms |
| 5 | MediaPipe BlazeFace | Face detection + landmarks (shared with voice daemon) | CPU | <5ms/frame |
| 6 | HSEmotion (ONNX) | Facial emotion from face crop | CPU, ~50MB | ~20ms/frame |
| 7 | Olaf | Audio fingerprinting for replay detection | CPU, 250KB | negligible |

### 2.2 Conditional (~900MB peak)

| # | Model | Trigger | Purpose | VRAM |
|---|---|---|---|---|
| 8 | emotion2vec+ base | Speech detected | 9-class emotion + valence/arousal | ~180MB |
| 9 | distil-whisper-small.en | Speech >3s (real-time) | Real-time transcription | ~330MB |
| 10 | beat_this | Music detected | SOTA beat/downbeat tracking | GPU |

### 2.3 On-Demand

| # | Model | Trigger | Purpose | VRAM |
|---|---|---|---|---|
| 11 | Demucs v4 TRT | High-value moment | Stem separation (~40s for 15min) | ~1GB |
| 12 | faster-whisper large-v3-turbo | Batch processing | Detailed transcription (existing) | ~1.5GB |
| 13 | SongFormer | Music structure analysis | Verse/chorus/bridge detection | ~200MB |
| 14 | DOSE | One-shot extraction | Clean kick/snare/hat from mixed audio | TBD |

### 2.4 Deferred

| Model | Reason | Trigger to Add |
|---|---|---|
| HuBERT base + vocal type head | Needs ~400 labeled examples | Bootstrap from operator recordings |
| MuQ-MuLan | Marginal gain over CLAP | CLAP retrieval proves insufficient |
| Qwen3-Omni-30B-A3B | Deep multimodal analysis | Add via tabbyAPI when needed |

### 2.5 Decision Tree

```
RAW AUDIO+VIDEO (continuous)
|
+-- [Gate 0: RMS Energy] -- threshold (zero-cost DSP)
|   '-- Below threshold -> discard, log timestamp
|
+-- [Gate 1: Silero VAD] -- voice activity (CPU, <1ms)
|   +-- Speech detected -> Speech Pipeline
|   '-- No speech -> Audio-Only Pipeline
|
+-- [Gate 2: CLAP] -- embedding + classification (GPU, ~600MB)
|   +-- 512-dim embedding -> Qdrant studio_moments
|   +-- Music detected -> Music Pipeline
|   '-- Other -> tag metadata only
|
+-- [Gate 3: Olaf] -- fingerprint against rolling buffer
|   '-- Replay detected -> boost sample-worthiness
|
+-- [Gate 4: Consent] -- speaker count + calendar cross-ref
|   +-- Multi-speaker + work hours + calendar match -> suppress/bridge
|   '-- Otherwise -> proceed
|
'-- [Gate 5: Video] -- MediaPipe (CPU)
    +-- Face detected -> HSEmotion
    '-- Pose -> activity/engagement heuristics

SPEECH PIPELINE:
  +-- emotion2vec+ base -> emotion labels
  +-- distil-whisper-small.en -> transcription
  '-- Consent check (it-consent-001) before storage

MUSIC PIPELINE:
  +-- Essentia -> BPM, key, spectral (CPU)
  +-- beat_this -> beat grid + downbeats (GPU)
  '-- IF high-value:
      +-- Demucs v4 TRT -> stems
      +-- DOSE -> one-shots
      '-- SongFormer -> structure
```

---

## 3. Classification Dimensions

### 3.1 Audio Classification (per segment)

| Dimension | Source | Output |
|---|---|---|
| Category | CLAP zero-shot + existing heuristics | sample-session, vocal-note, conversation, listening-log |
| Instruments | CLAP zero-shot + existing INSTRUMENT_MAP | drums, bass, keys, synth, guitar, horns, strings, vocals, percussion |
| BPM | Essentia RhythmExtractor2013 | Float (e.g., 92.3) |
| Key | Essentia KeyExtractor | Note + scale (e.g., Cm) |
| Energy | Essentia loudness (LUFS) | Float dB |
| Spectral centroid | Essentia | Float Hz |
| Onset strength | Essentia | Float 0-1 |
| Beat grid | beat_this | Timestamps of beats + downbeats |
| Speech emotion | emotion2vec+ | 9-class + valence/arousal |
| Vocal type | Heuristic (future: HuBERT) | freestyle, conversation, singing, humming |
| Replay count | Olaf fingerprinting | Integer |
| Structure | SongFormer (on-demand) | verse, chorus, bridge, intro, outro |
| Stems available | Demucs (on-demand) | Boolean |

### 3.2 Visual Classification (per frame sample)

| Dimension | Source | Output |
|---|---|---|
| Face present | MediaPipe BlazeFace | Boolean |
| Face count | MediaPipe BlazeFace | Integer |
| Facial emotion | HSEmotion | 7-class + valence/arousal |
| Body pose | MediaPipe Pose (future) | Engagement heuristics |
| Activity | Pose rules (future) | sitting, standing, playing, typing |

### 3.3 Behavioral / Flow State

| Signal | Source | Weight |
|---|---|---|
| HRV (SDNN) | Pixel Watch via Health Connect (WatchBackend) | High |
| Heart rate | Pixel Watch via Health Connect (WatchBackend) | Medium |
| Facial emotion | HSEmotion | Medium |
| Pose stability | MediaPipe (future) | Medium |
| Sustained activity | Session timer | High |
| Replay detection | Olaf | Low |

**State machine:** idle -> warming-up -> active -> flow -> winding-down. 5-minute hysteresis.

### 3.4 Sample-Worthiness Score

Composite signal, no single model:

| Signal | Source | Description |
|---|---|---|
| Replay count | Olaf | Producer loops/replays = interest |
| Spectral novelty | Essentia spectral flux | High flux = something changed |
| Transient quality | Essentia onset + spectral flatness | Sharp transients = one-shot candidates |
| CLAP distance | CLAP cosine from context | Outlier segments = interesting |
| Classification richness | CLAP zero-shot | Multi-class > mono-class |
| Beat alignment | beat_this | Clean boundaries = loop candidates |

---

## 4. Qdrant Integration

### 4.1 New Collection: `studio_moments`

```python
collection_name = "studio_moments"
vector_config = VectorParams(size=512, distance=Distance.COSINE)
```

CLAP 512-dim audio embeddings. Separate from existing `documents` (768-dim nomic text).

### 4.2 Payload Schema

```json
{
  "timestamp_start": "2026-03-14T02:30:00",
  "timestamp_end": "2026-03-14T02:30:45",
  "session_id": "session-20260314-0200",
  "category": "sample-session",
  "instruments": ["drums", "bass", "horns"],
  "bpm": 92.5,
  "key": "Cm",
  "energy_lufs": -14.2,
  "spectral_centroid": 2400.0,
  "onset_strength": 0.73,
  "has_speech": true,
  "vocal_type": "freestyle",
  "speech_emotion": "happy",
  "facial_emotion": "neutral",
  "flow_state_score": 0.78,
  "replay_count": 3,
  "sample_worthiness": 0.82,
  "structure_label": "verse",
  "transcript": "...",
  "has_stems": false,
  "source_file": "rec-20260314-023000.flac",
  "rag_doc_ref": "rag-sources/audio/sample-session-rec-20260314-023000-s150.md",
  "duration_s": 45.2
}
```

### 4.3 Dual Indexing

Each classified segment is indexed twice:
1. **`documents`** collection (768-dim nomic text) — the markdown RAG document, via existing `rag-source-landed` reactive rule
2. **`studio_moments`** collection (512-dim CLAP audio) — the raw audio segment, via new `audio-clap-indexed` reactive rule

### 4.4 CLAP Embedding Module

New module `shared/clap.py`:
- Manages CLAP model lifecycle independently of Ollama
- `embed_audio(waveform: torch.Tensor) -> list[float]` returns 512-dim vector
- Respects `VRAMLock` for GPU access
- Text query encoding via `embed_text(query: str) -> list[float]` for search

---

## 5. Hapax Integration

### 5.1 Voice Daemon — PerceptionBackend

The ingestion pipeline registers as a `PerceptionBackend` in the voice daemon's perception engine.

**Protocol compliance:**

```python
class StudioIngestionBackend:
    name = "studio_ingestion"
    provides = frozenset({
        "production_activity",   # bool: music actively playing
        "music_genre",           # str: dominant genre from CLAP
        "flow_state_score",      # float 0-1: composite
        "emotion_valence",       # float: from HSEmotion
        "emotion_arousal",       # float: from HSEmotion
        "audio_energy_rms",      # float: RMS energy
    })
    tier = PerceptionTier.SLOW  # >100ms, polled every ~12s
```

**Constraints:**
- `contribute()` must not block — pre-compute results in background thread, contribute() reads cached values
- Scoped behavior dict — cannot read other backends' behaviors in contribute()
- Must respect VRAMLock for GPU model access
- Background inference thread handles CLAP/HSEmotion, writes to thread-safe cache

**Audio source coexistence:**
- Voice daemon uses `echo_cancel_capture` via PyAudio callback
- Ingestion pipeline uses `pw-record --target` on the raw Yeti source (no echo cancellation)
- PipeWire natively supports multiple readers on the same source
- No conflict — different PipeWire nodes

**Webcam sharing:**
- Run ingestion backend in-process with voice daemon
- Share `WebcamCapturer` instance via constructor injection
- Stagger frame captures using CadenceGroup timing

**Color normalization:**
- Extract `_normalize_color()` from `face_detector.py` to shared utility
- Both FaceDetector and HSEmotion preprocessor import from shared location

### 5.2 Audio Processor Extension

**Strategy: Extend in-place.** The audio_processor already owns the pipeline from FLAC → RAG documents. New models integrate at specific points:

| New Model | Integration Point | What It Adds |
|---|---|---|
| CLAP | After RAG doc write (line ~1157/1195/1209/1263) | 512-dim embedding → Qdrant studio_moments |
| beat_this | Inside listening_log loop (line ~1134) | BPM, beat grid, downbeats to frontmatter |
| DOSE | After onset detection for music segments | One-shot extraction, quality scoring |
| Olaf | Phase 0 reactive rule on rag-sources/audio/ | Fingerprint index, replay detection |
| Consent gate | Before conversation storage (line ~1263) | speaker_count + calendar cross-ref → suppress/bridge |

**CLAP replaces PANNs in the ingestion pipeline** (not in voice daemon — PANNs stays there for CPU-based interrupt gating).

**Raw file archival:** Currently the processor deletes raw FLACs (line 1331). Change to:
- Write archive sidecar with value metadata
- Move raw FLAC to archive directory (not delete)
- Value arbiter manages lifecycle from there

### 5.3 Reactive Engine Rules

Five new rules:

```yaml
# 1. Classify new raw audio
- name: audio-chunk-classify
  phase: 1  # GPU semaphore
  cooldown_s: 0
  trigger: event_type == "created" AND path matches ~/audio-recording/raw/rec-*.flac
  action: Run audio_processor classification pipeline

# 2. Index CLAP embeddings after RAG doc creation
- name: audio-clap-indexed
  phase: 1  # GPU (CLAP model)
  cooldown_s: 0
  trigger: event_type == "created" AND source_service == "ambient-audio"
  action: Compute CLAP embedding, upsert to studio_moments

# 3. Fingerprint index (CPU)
- name: audio-fingerprint-index
  phase: 0  # deterministic
  cooldown_s: 0
  trigger: event_type == "created" AND source_service == "ambient-audio"
  action: Compute Olaf fingerprint, index for replay detection

# 4. Beat analysis for music segments
- name: audio-beat-analysis
  phase: 1  # GPU (beat_this)
  cooldown_s: 0
  trigger: content_type in (listening_log, sample_session)
  action: Run beat_this, write BPM/grid to frontmatter

# 5. Value arbiter (hourly, not event-driven)
# Registered as systemd timer, not reactive rule
```

### 5.4 VRAM Coordination

All GPU models in the ingestion pipeline must acquire `VRAMLock` (`~/.cache/hapax-voice/vram.lock`):
- CLAP inference: acquire → infer → release (batch to minimize lock holds)
- beat_this: acquire → process → release
- Demucs: acquire → separate → release

The lock is binary and non-blocking (`acquire()` returns False if held). On contention:
- Skip current cycle, retry on next tick (PerceptionBackend)
- Queue behind GPU semaphore (reactive engine Phase 1)

Existing VRAM check: audio_processor requires >= 6000MB free (`MIN_VRAM_FREE_MB`). Budget with new models:
- CLAP (~600MB) + existing models (~4GB) = ~4.6GB. Well within 24GB.

---

## 6. Constitutional Compliance

### 6.1 Axiom Bindings

```yaml
axiom_bindings:
  single_user:
    relevance: high
    status: compliant
    implications: [su-privacy-001, su-data-001, su-feature-001]
    notes: >
      Pipeline records operator only. Guest detection triggers consent-aware
      behavior per interpersonal_transparency. No multi-user features.

  executive_function:
    relevance: critical
    status: compliant
    implications:
      - ex-routine-001  # T0: automated, not manual
      - ex-routine-007  # T0: scheduled agents
      - ex-attention-001  # T0: external alerts on failure
      - ex-memory-010  # T2: historical context preserved (RAG docs permanent)
      - ex-cogload-002  # T2: no operator triage required
      - ex-err-001  # T0: errors include next actions
      - ex-feedback-001  # T1: progress via arbiter report
    notes: >
      Fully autonomous pipeline. Value arbiter runs hourly without operator
      involvement. RAG documents and sidecars persist forever, satisfying
      memory obligation. Raw media trimmed only under storage pressure.

  interpersonal_transparency:
    relevance: critical
    status: compliant
    implications:
      - it-consent-001  # T0: no persistent state without consent
      - it-consent-002  # T0: explicit opt-in
      - it-environmental-001  # T2: transient perception OK
      - it-backend-001  # T1: verify consent at ingestion boundary
      - it-inference-001  # T1: inferred state requires consent
    notes: >
      Consent gate at ingestion boundary. Multi-speaker segments checked
      against consent registry before storage. Guest-present segments
      (face_count > 1) flagged. Work call detection via speaker count +
      calendar cross-ref suppresses bridge-zone content.

  management_governance:
    relevance: boundary
    status: compliant-with-gate
    implications:
      - mg-bridge-001  # T1: work/home boundary
      - mg-boundary-001  # T0: no feedback language generation
      - mg-boundary-002  # T0: no 1:1 drafting from recordings
    notes: >
      Work call classifier prevents work PII from entering personal RAG.
      Multi-speaker standalone speech overlapping calendar events suppressed
      or routed to bridge zone. No downstream management agent consumes
      studio recording data.

  corporate_boundary:
    relevance: boundary
    status: compliant
    implications:
      - cb-data-001  # T0: no flow to corporate-synced systems
    notes: >
      All pipeline output stays local. No Obsidian Sync, no corporate
      network boundary crossing.
```

### 6.2 Existing T0 Violation — Immediate Fix Required

**The current audio_processor already violates `it-consent-001` (T0).** Multi-speaker conversation transcripts are written to `~/documents/rag-sources/audio/` with zero consent checking (audio_processor.py line ~1263). Work call transcripts with team member names enter the personal RAG.

**This violation is live today and predates the studio pipeline.** It should be fixed as a
near-term patch to `audio_processor.py` independent of the larger pipeline work.

**Fix:** Insert consent gate between transcription and storage for `conversation`-category segments:
1. Check `speaker_count > 1`
2. Cross-reference timestamp with calendar events (gcalendar_sync)
3. If overlap with calendar event → suppress storage entirely
4. If no calendar overlap → check consent registry for known non-operator speakers
5. No consent contract → suppress or anonymize

### 6.3 Guest Detection Behavior

When `face_count > 1` (MediaPipe BlazeFace):
- Audio segments containing non-operator speech flagged `guest_present: true` in sidecar
- Per `it-environmental-001` (T2): transient perception OK, no consent needed for detection itself
- Per `it-consent-001` (T0): persistent state (transcriptions, RAG docs) containing identifiable non-operator content requires consent contract
- Without consent contract: store audio/video segment metadata only (timestamp, duration, classification), suppress transcription content
- **Raw data buffered** during curtailment (not discarded) so consent can retroactively unlock processing

### 6.4 Consent Facilitation Principle

Any curtailment of system functionality due to absent consent must be paired with
proactive, frictionless consent facilitation:

1. **Proactive solicitation**: When guest detected, system surfaces consent opportunity
   immediately (operator notification with shareable link/QR code for guest's device)
2. **Frictionless grant**: Single-tap or voice confirmation. Minimal information required.
3. **Frictionless refusal**: Equally easy as granting. No penalty, no repeated asks within
   the same session. Curtailment continues silently.
4. **Frictionless revocation**: Change of mind at any time, any number of times, with
   immediate effect. No cooling-off period, no "are you sure" friction.
5. **Symmetry**: The UX cost of "yes" and "no" must be identical. No dark patterns,
   no defaults that favor consent over refusal.
6. **Retroactive processing**: If consent is granted after curtailment began, buffered raw
   data from the curtailed window is processed normally (if still in buffer). If buffer
   has aged out, only future data is processed.

**Proposed implication `it-access-001` (T0):** "When the system curtails functionality due
to absent consent, it must simultaneously offer the opportunity to grant consent. The
mechanism for granting, refusing, and revoking consent must be equally accessible, require
minimal effort, and be available at any time. No asymmetry between the cost of consent and
refusal."

### 6.5 Constitution Amendment Required

`su-privacy-001` in hapax-constitution needs scoping:

**Current:** "Privacy controls, data anonymization, and consent mechanisms are unnecessary since the user is also the developer."

**Proposed:** "Privacy controls, data anonymization, and consent mechanisms **for the operator** are unnecessary since the user is also the developer. **Non-operator persons are governed by the interpersonal_transparency axiom.**"

The `interpersonal_transparency` axiom should be upstreamed from hapax-council to hapax-constitution. It already exists in council (weight 88, 9 implications, consent.py, constitutive-rules.yaml). The constitution is the spec; the council diverged.

### 6.6 Value Arbiter Sufficiency Floor

Per constitutional analysis (purposivist reading of `ex-memory-010`):

1. **RAG documents never deleted** — the hard floor
2. **Sidecars persist after raw deletion** — metadata survives
3. **7-day minimum retention** before trim eligibility (except emergency >95%)
4. **RAG retrieval immunity** — segments whose docs have been retrieved get minimum value floor

Two new sufficiency probes:
- `probe-memory-002`: Verify RAG docs exist for trimmed segments
- `probe-memory-003`: Verify sidecars survive deletion

---

## 7. Video Capture (New)

### 7.1 Architecture

Video capture does not exist yet. Design:

- One `ffmpeg` process per camera, writing segmented MKV/MP4 files
- Segment duration: 5 minutes (shorter than audio's 15 min due to file size)
- Resolution: configurable per camera role
  - Operator-facing (BRIO): 1080p (production footage potential)
  - Hardware/workspace (C920): 720p (observational, lower storage)
  - IR cameras: 720p grayscale
- Format: H.264 MJPEG → MKV container
- Output: `~/video-recording/raw/cap-{timestamp}-{cam}.mkv`

### 7.2 Integration with Perception Layer

- Video capture runs as a separate systemd service per camera
- Frame sampling for classification: every 30-60s via PerceptionBackend
- Uses existing `WebcamCapturer` in-process for classification frames
- Raw recording is independent of perception — ffmpeg writes continuously

### 7.3 Storage Estimates

| Config | Per Camera/Day | 4 Cameras | 7 Cameras |
|---|---|---|---|
| 1080p H.264 CRF23 | ~25 GB | ~100 GB | ~175 GB |
| 720p H.264 CRF23 | ~12 GB | ~48 GB | ~84 GB |
| Mixed (1 1080p + 6 720p) | — | — | ~97 GB |

With 786GB free on NVMe + 331GB on /data + 5TB gdrive, storage is manageable with aggressive arbiter trimming.

---

## 8. Filesystem Layout

```
~/audio-recording/
  raw/                              # Active recording (15-min FLAC segments)
  archive/                          # Sidecars + raw files post-classification
    rec-20260314-143200.md          # Sidecar (persists after trim)
    rec-20260314-143200.flac        # Raw (deleted when trimmed)

~/video-recording/
  raw/                              # Active recording (5-min MKV segments)
  archive/                          # Sidecars + raw files
    cap-20260314-143200-cam1.md
    cap-20260314-143200-cam1.mkv

~/documents/rag-sources/
  audio/                            # RAG docs (never deleted)
  video/                            # RAG docs (never deleted)

profiles/
  storage-arbiter-report.md         # Arbiter output

~/olaf-db/                          # Olaf fingerprint database
```

### 8.1 Archive Sidecar Schema

```yaml
---
source: ambient-audio
source_service: ambient-audio
captured: 2026-03-14T14:32:00
duration_s: 900
category: sample-session
classifications:
  instruments: [drums, bass, horns]
  speech_emotion: happy
  facial_emotion: neutral
  vocal_type: freestyle
bpm: 92.5
key: Cm
energy_lufs: -14.2
spectral_centroid: 2400.0
onset_strength: 0.73
beat_grid: [0.0, 0.645, 1.290, ...]  # beat timestamps
replay_count: 3
sample_worthiness: 0.82
flow_state_score: 0.78
guest_present: false
consent_checked: true
transcription_ref: rag-sources/audio/sample-session-rec-20260314-143200-s0.md
qdrant_point_id: "abc123"
raw_path: ~/audio-recording/archive/rec-20260314-143200.flac
value_score: 0.72
value_last_evaluated: 2026-03-14T18:00:00
value_signals:
  classification_richness: 0.8
  rag_reference_count: 3
  temporal_neighbors: 2
  uniqueness: 0.6
  recency_weight: 1.0
disposition: active
---
```

---

## 9. Compute Budget

### 9.1 VRAM (RTX 3090, 24GB)

| Tier | Models | VRAM |
|---|---|---|
| Always-on | CLAP + HSEmotion | ~650MB |
| Conditional | emotion2vec+ + distil-whisper + beat_this | ~900MB |
| Peak concurrent | Tier 1 + 2 | ~1.5GB |
| On-demand (Demucs) | + Demucs v4 TRT | ~2.5GB |
| Ollama (nomic-embed) | Existing | ~1.4GB |
| **Total peak** | | **~3.9GB** |

21GB headroom remaining.

### 9.2 Processing Time (15-min audio segment)

| Stage | Time | Hardware |
|---|---|---|
| RMS + VAD gate | <1s | CPU |
| CLAP embedding (90 chunks) | ~4.5s | GPU |
| Essentia features | ~2s | CPU |
| Olaf fingerprinting | <1s | CPU |
| emotion2vec+ (speech) | ~10s | GPU |
| distil-whisper (speech) | ~15s | GPU |
| beat_this (music) | ~5s | GPU |
| **Total** | **~38s** | |

24x real-time headroom. Comfortable for 24/7.

---

## 10. Officium Coordination

Officium is management-only domain. **No integration with ingestion pipeline.**

- `management_safety` axiom blocks behavioral/emotional data from management flows
- `mg-selfreport-001` (T1) blocks LLM-inferred behavioral assessments in management profiler
- Separate Qdrant (6433), LiteLLM (4100), no shared data stores

Only coordination: **Ollama GPU contention.** Pipeline systemd services should set `CPUQuota=` and coordinate GPU access via VRAMLock to avoid starving officium's embedding calls.

---

## 11. Open Questions

1. **Video capture service design**: Continuous ffmpeg per camera vs periodic snapshot service? Continuous generates more data but captures everything; periodic is cheaper but may miss moments.

2. **Olaf database lifecycle**: Rolling window (last N hours) or persistent? Persistent
   enables cross-session replay detection but grows. **Consent implication:** If persistent,
   Olaf fingerprints become carrier facts with provenance implications. A guest's vocal
   fingerprint persisting indefinitely without consent violates `it-consent-001` (T0). The
   carrier registry and revocation cascade must be wired to Olaf DB purge — when a consent
   contract is revoked, all fingerprints from guest-present segments must be purged from the
   Olaf DB. The `constitutive-rules.yaml` should include an `cr-source-olaf` entry linking
   fingerprint persistence to `it-consent-001` and `it-consent-002`.

3. **HuBERT vocal type classifier**: When to start collecting labeled training data? The operator could label segments during normal workflow via a simple CLI tool.

4. **Camera resolution per role**: Exact resolution assignments need operator input based on production footage quality requirements.

5. **Bridge zone storage location**: Where do suppressed work-call segments go? `32-bridge/audio/`? Or discard entirely?

---

## 12. References

### Models
- [CLAP (LAION)](https://github.com/LAION-AI/CLAP) | [larger_clap_music_and_speech](https://huggingface.co/laion/larger_clap_music_and_speech)
- [Silero VAD v5](https://github.com/snakers4/silero-vad)
- [Essentia](https://essentia.upf.edu/)
- [emotion2vec+](https://github.com/ddlBoJack/emotion2vec) | [HF](https://huggingface.co/emotion2vec/emotion2vec_plus_large)
- [distil-whisper](https://github.com/huggingface/distil-whisper)
- [beat_this](https://github.com/CPJKU/beat_this) (ISMIR 2024)
- [Demucs v4 TRT](https://huggingface.co/MansfieldPlumbing/Demucs_v4_TRT)
- [SongFormer](https://huggingface.co/ASLP-lab/SongFormer) | [GitHub](https://github.com/ASLP-lab/SongFormer/)
- [DOSE](https://github.com/HSUNEH/DOSE) (ICASSP 2025)
- [Olaf](https://github.com/JorenSix/Olaf)
- [HSEmotion](https://github.com/sb-ai-lab/EmotiEffLib) | [ONNX](https://github.com/av-savchenko/hsemotion-onnx)

### Research
- [Hip-hop sample identification](https://arxiv.org/abs/2502.06364)
- [GNN sample identification](https://arxiv.org/abs/2506.14684)
- [Flow state physiology (Nature 2025)](https://www.nature.com/articles/s41598-025-95647-x)
- [Vocal type classification (voice2mode)](https://arxiv.org/html/2602.13928)
- [Beat tracking comparison (Frontiers 2025)](https://www.frontiersin.org/journals/computer-science/articles/10.3389/fcomp.2025.1595939/full)

### Hapax Source Files
- Voice daemon: `agents/hapax_voice/perception.py`, `ambient_classifier.py`, `vram.py`
- Audio processor: `agents/audio_processor.py`
- Reactive engine: `cockpit/engine/reactive_rules.py`, `executor.py`, `rules.py`
- Consent: `shared/consent.py`, `axioms/constitutive-rules.yaml`
- Config: `shared/config.py` (Qdrant, embeddings)
- Constitution: `axioms/registry.yaml`, `axioms/implications/`
