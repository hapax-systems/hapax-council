# Ambient Audio Pipeline — Design

**Goal:** Continuous 24/7 audio capture from Blue Yeti, with intelligent segmentation, classification, diarization, transcription, and RAG ingestion — all feeding into the Hapax system.

**Constraint:** Must not interfere with concurrent mic usage (LLM voice interface, calls, etc.). PipeWire's PulseAudio compat layer allows multiple consumers of the same source simultaneously — the recorder uses `-f pulse`, never `-f alsa`, so no exclusive device locking.

---

## Components

4 independent pieces, each a separate systemd concern:

1. **`audio-recorder.service`** — always-on ffmpeg recording, 15-min FLAC chunks
2. **`audio_processor` agent** — Python, runs on timer. VAD → classification → diarization → transcription → RAG output
3. **`audio-archiver.timer`** — rclone move of raw files >48h to Google Drive
4. **Ingest integration** — `rag-sources/audio/` auto-tagged, profiler bridge

---

## 1. Recording

**Tool:** ffmpeg with segment muxer via PulseAudio compat input (PipeWire provides this).

```bash
ffmpeg -nostdin -f pulse \
  -i alsa_input.usb-Blue_Microphones_Yeti_Stereo_Microphone_REV8-00.analog-stereo \
  -ac 1 -f segment -segment_time 900 -strftime 1 -c:a flac \
  ~/audio-recording/raw/rec-%Y%m%d-%H%M%S.flac
```

- Mono FLAC, 48kHz, 16-bit
- 15-minute auto-rotated files with timestamp filenames
- ~2-2.5 GB/day
- PipeWire allows multiple consumers — voice chat, LLM voice, etc. all work in parallel

**Reliability:** systemd user service with `Restart=always`, `RestartSec=10`. USB disconnect → ffmpeg dies → systemd restarts → reconnects (PipeWire recreates the source with the same name based on USB vendor/product ID).

**Yeti config:** Cardioid mode (physical switch), gain ~0.7 via `wpctl set-volume <node-id> 0.7`.

---

## 2. Processing Pipeline

**Agent:** `audio_processor.py` in `~/projects/ai-agents/`. No LLM — all local ML models.

### Pipeline Stages

```
raw FLAC (15 min, 48kHz mono)
  → resample to 16kHz (torchaudio)
  → Silero VAD → non-silence regions (~15s/hr, CPU)
  → PANNs CNN14 frame-level SED → classify each frame across 527 AudioSet classes (~30-60s/hr, <1GB VRAM)
  → merge adjacent same-type frames into segments
  → discard noise-only segments (HVAC, keyboard, static, silence)
  → pyannote community-1 diarization on speech segments → speaker labels (~1-3 min/hr, 2-4GB VRAM)
  → faster-whisper large-v3-turbo int8 on speech segments → transcript (~2 min/hr, 3.5GB VRAM)
  → write RAG output + save processed segments
```

### VRAM Budget (RTX 3090, 24GB)

| Model | VRAM | Stage |
|-------|------|-------|
| Silero VAD | 0 (CPU) | Segmentation |
| PANNs CNN14 | <1GB | Classification |
| pyannote community-1 | 2-4GB | Diarization |
| faster-whisper large-v3-turbo int8 | 3.5GB | Transcription |
| **Total peak** | **~8GB** | Sequential, not concurrent |

**VRAM coexistence:** Check `nvidia-smi` before GPU stages. If Ollama has a large model loaded (>16GB), defer processing to next timer cycle. Ollama auto-unloads after 5 min idle.

### Processing Speed

1 hour of raw audio processes in ~5-7 minutes on RTX 3090. With 15-min chunks arriving every 15 min, the pipeline easily keeps up (processes a chunk in ~1-2 min).

### Noise Filtering

PANNs AudioSet classes to discard (configurable blocklist):
- Air conditioning, Mechanical fan, White noise
- Computer keyboard, Typing, Mouse click
- Static, Hum, Buzz
- Silence (already filtered by VAD)

Keep: Speech, Music, Singing, Musical instrument, Conversation, Laughter, Clapping, Door, Telephone.

### State Tracking

`~/.cache/audio-processor/state.json` — maps raw filenames to processing status (pending, processing, done, error). Incremental: only processes files not yet in state. CLI: `--process`, `--stats`, `--reprocess FILE`.

---

## 3. RAG Output

Output to `~/documents/rag-sources/audio/`.

### Speech Segments (full transcript + speaker labels)

```yaml
---
source_service: ambient-audio
content_type: audio_transcript
timestamp: 2026-03-08T14:30:00
duration_seconds: 45
speakers: [SPEAKER_00, SPEAKER_01]
speaker_count: 2
audio_source: rec-20260308-143000.flac
segment_start: "00:05:30"
segment_end: "00:06:15"
classification: speech
confidence: 0.94
---

# Audio Transcript — 2026-03-08 14:30 (45s, 2 speakers)

## SPEAKER_00 (00:05:30)
Let's look at the profiler output...

## SPEAKER_01 (00:05:42)
The dimension weights seem off...
```

### Non-Speech Events (metadata only, no transcript)

```yaml
---
source_service: ambient-audio
content_type: audio_event
timestamp: 2026-03-08T15:00:00
duration_seconds: 180
audio_source: rec-20260308-150000.flac
segment_start: "00:02:10"
segment_end: "00:05:10"
classification: music
sub_classifications: [singing, acoustic_guitar]
confidence: 0.87
energy_db: -18.4
---

# Audio Event — 2026-03-08 15:00 (3m 0s)

Type: music (singing, acoustic guitar)
Energy: -18.4 dB average
```

Rich queryable metadata without hallucinated text for non-speech content.

---

## 4. Profiler Facts

Dimension: `activity`
- `audio_daily_summary`: hours of speech, music, silence per day
- `audio_conversation_patterns`: frequency and duration of multi-speaker segments
- `audio_music_activity`: singing/instrument detection patterns

---

## 5. Storage + Archival

### Local Layout

```
~/audio-recording/
  raw/              # 15-min FLAC chunks (48h local retention)
  processed/        # Extracted segments of interest (30 days)

~/.cache/audio-processor/
  state.json        # Processing state
  audio-profile-facts.jsonl  # Profiler bridge output
  changes.jsonl     # Behavioral logging

~/documents/rag-sources/audio/
  transcript-20260308-143000-s0530.md
  event-20260308-150000-s0210.md
```

### Google Drive Archival

```
Google Drive: audio-archive/raw/2026/03/08/
```

`rclone move` with `--min-age 48h`, `--checksum`, `--drive-chunk-size 64M`. Verifies checksums before deleting local copies. Daily at 03:00.

**Cost:** ~120 GB/month raw. Google One 2TB ($10/month) covers 16+ months.

---

## 6. Integration Points

### Ingest

Add to `_SERVICE_PATH_PATTERNS` in `ingest.py`:
```python
"rag-sources/audio": "ambient-audio",
```

### Profiler

Add to `BRIDGED_SOURCE_TYPES` and `SOURCE_TYPE_CHUNK_CAPS`:
```python
"ambient-audio": 100,  # Cap: audio generates many small segments
```

### Briefing

"Audio Activity" section — hours of speech/music/silence in lookback window, notable multi-speaker conversations.

---

## 7. Timer Summary

| Timer/Service | Schedule | Purpose |
|---------------|----------|---------|
| `audio-recorder.service` | Always on | ffmpeg continuous capture |
| `audio-processor.timer` | Every 30 min | Process new raw chunks |
| `audio-archiver.timer` | Daily 03:00 | rclone move raw >48h to Drive |

---

## 8. Dependencies

New Python packages for ai-agents:
- `faster-whisper` — Whisper CTranslate2 inference
- `silero-vad` — Voice activity detection (or `torch.hub` load)
- `pyannote.audio` — Speaker diarization (requires HuggingFace token)
- `panns_inference` — Audio event classification
- `torchaudio` — Audio I/O and resampling

System:
- `rclone` — not yet installed, needed for Drive archival
- `ffmpeg` — already installed

---

## 9. Deferred / Not In Scope

- Speaker identification (mapping SPEAKER_00 → "the operator") — requires reference embeddings, can be added later
- Real-time processing (streaming) — batch is simpler and sufficient
- Audio quality enhancement (noise reduction) — not needed for transcription accuracy
- Music fingerprinting (Shazam-like) — interesting but low priority
