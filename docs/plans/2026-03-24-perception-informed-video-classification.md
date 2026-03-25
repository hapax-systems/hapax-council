# Perception-Informed Video Segment Classification

**Date**: 2026-03-24
**Status**: Design
**Scope**: video_processor, temporal_scales, visual_layer_aggregator, cache-cleanup

## Problem

The video processor classifies 5-minute MKV segments using OpenCV haar cascades
on extracted keyframes. This produces classifications that are 76% false-positive
driven: 6,913 of 9,101 segments classified as "conversation" because haar
cascades detect faces on posters, monitors, equipment, and reflections. The
"production_session" category has never fired. 401 GB/day is uploaded to gdrive
— functionally a no-filter archive.

Meanwhile, the perception system runs YOLO11n, MediaPipe, cross-modal activity
inference, Bayesian operator presence, and flow state computation every 2.5
seconds. These signals are orders of magnitude more accurate than haar cascades
but are not available to the deferred video processor because they are ephemeral
(50-second ring buffer, 30-minute in-memory minute summaries).

## Design

Two changes. One persists the temporal bridge. The other consumes it.

### Change 1: Perception Minute Log

Persist MinuteSummary objects to a JSONL file as they are emitted by the
existing MinuteBuffer in temporal_scales.py.

**Integration point**: visual_layer_aggregator.py calls
`self._multi_scale.tick(data)` on each perception tick (~2.5s). The internal
MinuteBuffer emits a MinuteSummary every 60 seconds. Currently,
MultiScaleAggregator.tick() swallows the return value. Change it to return
the MinuteSummary, then persist in the aggregator.

**File**: `~/.cache/hapax-voice/perception-minutes.jsonl`

**Enriched MinuteSummary**: Add 4 fields to MinuteSummary (all with defaults,
backward-compatible with frozen model):

| Field | Source key in snapshot | Extraction |
|-------|----------------------|------------|
| operator_present | presence_state | any("PRESENT") in minute |
| person_count_max | person_count | max across minute |
| consent_phase | consent_phase | mode across minute |
| stress_elevated | stress_elevated | any(True) in minute |

**Size**: ~220 bytes/line x 1440 lines/day x 7 days = ~2.2 MB. Rotated by
cache-cleanup.sh.

### Change 2: Perception-Informed Classifier

Replace `_classify_segment()` haar cascade pipeline with
`_classify_from_perception()` that reads perception-minutes.jsonl for the
segment's 5-minute time window.

**Current pipeline** (~60s CPU per segment):
```
ffprobe → ffmpeg 5 keyframes → cv2 haar x3 per frame → frame diff → SSIM → score
```

**New pipeline** (~0.1s per segment):
```
parse filename timestamp → read JSONL [T, T+300s] → aggregate 5 minutes → score
```

**Scoring model** (same 5 categories, perception-derived):

```
person_count_max > 1 AND consent == "consent_granted"
    → conversation (0.8)

operator_present AND activity == "producing" AND flow_peak > 0.5
    → production_session (1.0)

operator_present AND activity in (coding, meeting, producing) AND flow_mean > 0.3
    → active_work (0.6)

operator_present AND present_ratio > 0.3
    → idle_occupied (0.3)

else
    → empty_room (0.0)

Bonuses: activity_changed +0.1, voice_active +0.1
```

**Sidecar compatibility**: motion_score mapped from audio_energy_mean, ssim
mapped from 1.0 - audio_energy_mean. AV correlator boost rules match on
category strings, not numeric fields.

**Fallback**: If no perception minutes exist for a segment's window (daemon
down), fall back to existing haar cascade pipeline.

**Segment discovery fix**: _find_unprocessed_segments currently iterates
CAMERA_ROLES (6 cameras) but the filesystem has 9 camera directories. Change
to scan VIDEO_DIR subdirectories directly.

### File changes

| File | Change |
|------|--------|
| agents/temporal_scales.py | Add 4 fields to MinuteSummary; _close_minute() extracts them |
| agents/temporal_scales.py | MultiScaleAggregator.tick() returns MinuteSummary or None |
| agents/visual_layer_aggregator.py | Persist returned MinuteSummary to JSONL |
| agents/video_processor.py | Add perception-based classification pipeline |
| agents/video_processor.py | _classify_segment_dispatch() with fallback |
| agents/video_processor.py | Fix segment discovery to scan VIDEO_DIR |
| scripts/cache-cleanup.sh | Add 7-day rotation for perception-minutes.jsonl |
| tests/test_temporal_scales.py | Update tests for new MinuteSummary fields |

### What does NOT change

- Sidecar format, AV correlator, retention script, upload mechanism
- Video processor CLI (--process, --stats, --reprocess)
- ProcessedSegmentInfo model and state file
- Consent enforcement (compositor valves)
- Studio moments Qdrant collection

### Expected outcomes

| Metric | Current | Expected |
|--------|---------|----------|
| Upload rate | 76% | 15-25% |
| gdrive volume | ~401 GB/day | ~80-100 GB/day |
| CPU per segment | ~60s | ~0.1s |
| production_session detections | 0/9101 | Matches actual producing time |
| Throughput | ~60 seg/hr | 200+ (fewer uploads) |

### Risks

1. **Perception daemon downtime**: Haar cascade fallback covers gaps.
2. **MinuteSummary field additions**: All have defaults; frozen model is
   backward-compatible.
3. **JSONL growth**: 2.2 MB/week, rotated. Negligible.
