# Audio Grounding ML Upgrade Design

**Date:** 2026-05-19
**Task:** multimodal-grounding-audio-cpu-deploy
**Parent spec:** docs/superpowers/specs/2026-05-08-visual-audio-inspection-standard.md

## Goal

Replace the spectral-analysis audio perception daemon with ML models that provide genuine classification rather than heuristic approximation. Zero VRAM — CPU only.

## Architecture: Sequential Pipeline

Single-threaded sequential pipeline in the existing daemon process. Each tick:

1. **Capture** — 2s window from `hapax-broadcast-normalized` via `parecord` at 48kHz (unchanged)
2. **LAION CLAP** — Zero-shot audio classification. Classifies scene (speech, music, silence, ambient). Produces `scene`, `confidence`, `is_speech`, `music_playing`
3. **Essentia** — Beat tracking, key detection, energy analysis. Produces `bpm`, `key`, `rms_dbfs`
4. **pyannote 3.1** — Speaker diarization. Produces `speaker_id` (embedding-based, not named)
5. **Write** — Atomic JSON write to `/dev/shm/hapax-perception/audio.json` (unchanged path + schema)

Estimated tick time: ~3-4s per cycle on CPU. Adaptive: if a tick exceeds 5s, skip pyannote on the next tick.

## Output Schema (unchanged)

```json
{
  "is_speech": true,
  "speaker_id": "spk_0",
  "music_playing": false,
  "bpm": null,
  "key": null,
  "scene": "speech",
  "confidence": 0.87,
  "rms_dbfs": -18.3,
  "voice_ratio": 0.72,
  "music_ratio": 0.15,
  "updated_at": "2026-05-19T12:00:00Z"
}
```

Backward compatible — all existing consumers (perception_fusion.py, daily_segment_prep.py) continue working without changes.

## Graceful Degradation

Each model loads independently with its own try/except. If a model fails to load:

- **CLAP fails** — fall back to current spectral band analysis for scene/confidence/is_speech/music_playing
- **Essentia fails** — bpm=null, key=null, rms_dbfs from numpy RMS (current behavior)
- **pyannote fails** — speaker_id=null (current behavior)

The daemon never crashes due to a model load failure. Partial ML is better than no ML.

## Model Details

| Model | Size | CPU Time (est.) | Source |
|-------|------|-----------------|--------|
| LAION CLAP (630k-audioset-best) | ~600MB | ~1.5s/2s window | `laion/clap-htsat-unfused` HF |
| Essentia (TempoCNN + KeyNet) | ~50MB | ~0.3s | essentia pip package |
| pyannote 3.1 (segmentation-3.0) | ~200MB | ~1.5s/2s window | `pyannote/segmentation-3.0` HF |

Total memory footprint: ~2-3GB resident. Fits within 4GB MemoryMax.

## Systemd Unit Changes

`systemd/units/hapax-audio-perception.service`:
- `MemoryMax=2G` → `MemoryMax=4G`
- Add `Environment=HF_TOKEN=%h/.config/huggingface/token` (pyannote gated model access)
- `CUDA_VISIBLE_DEVICES=""` remains (CPU-only invariant)
- `CPUQuota=200%` remains

## Dependencies

In `pyproject.toml` under `[project.optional-dependencies]` audio extras:
- `laion-clap>=1.1.6`
- `essentia>=2.1b6.dev1091`
- `pyannote.audio>=3.1`

These pull torch (already a dep) but must not pull CUDA runtime (CPU-only constraint enforced by `CUDA_VISIBLE_DEVICES=""`).

## File Changes

| File | Action |
|------|--------|
| `agents/audio_perception/daemon.py` | Rewrite: ML pipeline replaces spectral analysis |
| `agents/audio_perception/models.py` | New: model loading with graceful fallback |
| `systemd/units/hapax-audio-perception.service` | Edit: MemoryMax, HF_TOKEN |
| `pyproject.toml` | Edit: add ML deps to audio extras |
| `tests/test_audio_perception_models.py` | New: unit tests for model loading + fallback |

## pyannote Consumer Research

pyannote provides speaker embeddings (not named identities). Research deliverable: identify which existing or new consumers can use `speaker_id`:

- **hapax-daimonion voice routing** — distinguish operator from other speakers
- **daily_segment_prep** — segment narration attribution
- **content programme narration** — speaker change detection for programme flow
- **chronicle entries** — attribute speech segments in daily chronicle
- **publication bus** — speaker metadata for published content

This research informs Phase 2 (speaker enrollment + identification) but is out of scope for this task. Deliverable: a research note documenting findings and recommendations.

## Acceptance Criteria

- `/dev/shm/hapax-perception/audio.json` updating at ≥0.25Hz (one tick per 4s max)
- `scene` field populated by CLAP classification (not spectral heuristic)
- `bpm` and `key` populated by Essentia when music is detected
- `speaker_id` populated by pyannote when speech is detected
- Graceful degradation: daemon runs with any subset of models loaded
- Zero GPU usage (`CUDA_VISIBLE_DEVICES=""`)
- `perception_fusion.py` and `daily_segment_prep.py` continue working unchanged
- MemoryMax 4GB not exceeded under steady state
