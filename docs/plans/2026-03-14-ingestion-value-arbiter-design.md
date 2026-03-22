# Ingestion Value Arbiter — Autonomous Storage Management

**Date:** 2026-03-14
**Status:** Planned
**Depends on:** Ingestion expansion plan (2026-03-13), audio_processor, ingest agent

---

## Problem

The hapax ingestion pipeline captures 24/7 audio (and soon video) from studio observation.
Raw media accumulates without bound. The existing `audio_processor` deletes raw FLACs after
processing, but the operator wants valuable raw segments archived for production use (samples,
freestyles, visual material). A bounded storage budget requires intelligent, autonomous trimming.

**Design constraint:** Knowledge is permanent, storage is finite. RAG documents, transcriptions,
classifications, and embeddings persist forever. Only raw media files are subject to trimming.

---

## Architecture

### Layer 1: Capture (existing, extended)

Audio capture already exists (`audio-recorder.service` → `pw-record` → FLAC segments).
Video capture is new — one `ffmpeg` process per camera, triggered by systemd timer or
continuous service, writing to `~/video-recording/raw/`.

Each raw segment gets a **markdown sidecar** upon archival, following filesystem-as-bus convention:

```yaml
---
source: ambient-audio           # or ambient-video
source_service: ambient-audio
captured: 2026-03-14T14:32:00
duration_s: 900
camera: cam1                    # video only
classifications: [speech, music-production, keyboard-typing]
transcription_ref: rag-sources/ambient-audio/2026-03-14-1432.md
raw_path: ~/audio-recording/archive/rec-20260314-143200.flac
value_score: 0.0                # initialized, scored by arbiter
value_last_evaluated: null
value_signals: {}
disposition: active             # active | trim-candidate | rescued | confirmed-trim
---
```

### Layer 2: Value Scoring — `agents/storage_arbiter.py` (Tier 3, deterministic)

**Trigger:** Systemd timer, hourly.

Scans all sidecar files in archive directories. For each segment, computes a composite
`value_score` from weighted signals:

| Signal | Weight | Source | Description |
|--------|--------|--------|-------------|
| `classification_richness` | 0.20 | PANNs tags | Multi-class > mono-class. Speech+music >> silence |
| `rag_reference_count` | 0.30 | Qdrant query log | How many RAG queries retrieved this segment's document |
| `temporal_neighbors` | 0.15 | Adjacent sidecars | Valuable segments within ±5min lift neighbors |
| `uniqueness` | 0.15 | Qdrant embeddings | Embedding distance from nearest cluster centroid |
| `recency_weight` | 0.20 | Exponential decay | Half-life configurable (default 30 days) |

**Scoring formula:**

```
value_score = Σ(signal_i × weight_i) × recency_weight
```

After scoring, the arbiter checks storage pressure:

| Pressure Zone | Storage Used | Action |
|---------------|-------------|--------|
| Green | < 70% | No action |
| Advisory | 70–85% | Note in daily summary |
| Trim | 85–95% | Mark bottom 15% as `trim-candidate` |
| Emergency | > 95% | Mark bottom 30%, skip LLM review |

Writes `profiles/storage-arbiter-report.md` with current distribution, trim candidates,
and storage pressure metrics.

### Layer 3: Semantic Review — `agents/value_judge.py` (Tier 2, LLM)

**Trigger:** Reactive engine rule when `storage-arbiter-report.md` is written with trim candidates.

For each `trim-candidate`, the value judge reviews:
- The segment's transcription and classification
- Temporal context (what happened before/after)
- Whether the segment contains production-valuable material the deterministic scorer missed
  (e.g., a 2-second vocal idea buried in 15 minutes tagged as `silence`)

Outputs per candidate:
- `disposition: confirmed-trim` — safe to delete raw file
- `disposition: rescued` — keep, with `value_floor: true` (arbiter won't re-nominate for 90 days)
  and a one-line reason

**Skipped in emergency pressure zone** — deterministic arbiter trims directly.

### Layer 4: Deletion — `agents/storage_reaper.py` (Tier 3, deterministic)

**Trigger:** Reactive engine rule when value judge writes `confirmed-trim` dispositions.

For each confirmed trim:
1. Delete the raw media file
2. Update sidecar: `raw_deleted: true`, `deleted_at: <timestamp>`, remove `raw_path`
3. The RAG document and sidecar persist — knowledge survives storage reclamation
4. Log deletion event to `profiles/sdlc-events.jsonl`

---

## Reactive Engine Rules

Three new rules added to `logos/engine/`:

```yaml
- name: arbiter-report-written
  watch: profiles/storage-arbiter-report.md
  condition: frontmatter.trim_candidates > 0
  action: agents.value_judge
  phase: llm  # semaphore-bounded

- name: value-judge-complete
  watch: "*/archive/*.md"
  condition: frontmatter.disposition == "confirmed-trim"
  action: agents.storage_reaper
  phase: deterministic

- name: raw-segment-archived
  watch: "*/archive/*.md"
  condition: frontmatter.disposition == "active" and frontmatter.value_score == 0.0
  action: agents.storage_arbiter
  phase: deterministic
  debounce: 300  # batch new arrivals, don't run per-segment
```

---

## Decay Curve

Fresh segments start with `recency_weight: 1.0`. The weight decays exponentially:

```
recency_weight = exp(-λ × age_days)
λ = ln(2) / half_life_days
```

Default half-life: 30 days. After 30 days, weight = 0.5. After 90 days, weight = 0.125.

Counteracting forces that prevent decay from dominating:
- **RAG retrievals** — each query hit increments `rag_reference_count`, boosting score
- **Temporal gravity** — valuable neighbors lift adjacent segments
- **Explicit rescue** — value judge can set `value_floor: true`
- **Uniqueness** — rare segments (far from cluster centroid) score higher

Segments that are never retrieved, not unique, have no valuable neighbors, and have
decayed past the half-life naturally sink to the bottom and get trimmed when pressure demands it.

---

## Storage Budget

Configured in `shared/config.py`:

```python
STORAGE_BUDGETS = {
    "ambient-audio": 500 * 1024**3,   # 500 GB
    "ambient-video": 1024 * 1024**3,  # 1 TB
}
```

Adjustable per source. The arbiter computes pressure per source independently —
audio and video have separate trim cycles.

---

## Filesystem Layout

```
~/audio-recording/
  raw/                              # active recording target
  archive/                          # sidecars + raw files
    rec-20260314-143200.md          # sidecar (persists after trim)
    rec-20260314-143200.flac        # raw (deleted when trimmed)

~/video-recording/
  raw/                              # active recording target
  archive/                          # sidecars + raw files
    cap-20260314-143200-cam1.md
    cap-20260314-143200-cam1.mkv

~/documents/rag-sources/
  ambient-audio/                    # RAG docs (never deleted)
  ambient-video/                    # RAG docs (never deleted)

profiles/
  storage-arbiter-report.md         # arbiter output
```

---

## Agent Manifests

### storage_arbiter.yaml

```yaml
name: storage_arbiter
tier: 3
category: maintenance
description: Score archived media segments by value, identify trim candidates under storage pressure
schedule: hourly
inputs:
  - "~/audio-recording/archive/*.md"
  - "~/video-recording/archive/*.md"
outputs:
  - profiles/storage-arbiter-report.md
  - "~/audio-recording/archive/*.md"  # updates value_score
  - "~/video-recording/archive/*.md"
axiom_bindings:
  single_user: compliant  # single operator's data
  executive_function: compliant  # fully autonomous, zero-config
  corporate_boundary: compliant  # all personal data, stays local
  management_governance: not_applicable  # no people data
```

### value_judge.yaml

```yaml
name: value_judge
tier: 2
category: maintenance
description: Semantic review of trim candidates — rescue production-valuable segments
trigger: reactive  # profiles/storage-arbiter-report.md
inputs:
  - profiles/storage-arbiter-report.md
  - "~/audio-recording/archive/*.md"
  - "~/video-recording/archive/*.md"
  - "~/documents/rag-sources/ambient-audio/*.md"
  - "~/documents/rag-sources/ambient-video/*.md"
outputs:
  - "~/audio-recording/archive/*.md"  # updates disposition
  - "~/video-recording/archive/*.md"
model: balanced
axiom_bindings:
  single_user: compliant
  executive_function: compliant
  corporate_boundary: compliant
  management_governance: not_applicable
```

### storage_reaper.yaml

```yaml
name: storage_reaper
tier: 3
category: maintenance
description: Delete raw media files for confirmed-trim segments, preserve sidecars and RAG docs
trigger: reactive  # archive sidecar disposition change
inputs:
  - "~/audio-recording/archive/*.md"
  - "~/video-recording/archive/*.md"
outputs:
  - profiles/sdlc-events.jsonl
  - "~/audio-recording/archive/*.md"  # updates raw_deleted, deleted_at
  - "~/video-recording/archive/*.md"
axiom_bindings:
  single_user: compliant
  executive_function: compliant
  corporate_boundary: compliant
  management_governance: not_applicable
```

---

## Axiom Compliance

| Axiom | Status | Rationale |
|-------|--------|-----------|
| single_user | Compliant | Single operator's environmental data, no multi-user concerns |
| executive_function | Compliant | Fully autonomous — zero operator involvement. Errors in daily summary with next actions. Storage pressure managed without human intervention |
| corporate_boundary | Compliant | All personal data on local storage, never leaves the machine |
| interpersonal_transparency | N/A | No third-party personal data captured (studio observation, not surveillance) |
| management_governance | N/A | No people management data involved |

---

## Implementation Order

1. `storage_arbiter.py` + manifest + timer — deterministic scoring, no LLM dependency
2. Extend `audio_processor.py` to write archive sidecars instead of deleting raw files
3. `storage_reaper.py` + manifest — deterministic deletion
4. `value_judge.py` + manifest — LLM semantic review
5. Reactive engine rules
6. Video capture service + video archive sidecars
7. Integration tests with synthetic archive data

---

## Open Questions

- **Qdrant query log**: Need to instrument RAG query paths to track which documents are retrieved.
  Currently no query logging — `rag_reference_count` signal requires this.
- **Video segment duration**: Audio uses 15-min FLAC segments. Video segments should be shorter
  (5 min?) due to file size. Or event-driven segmentation (scene change detection)?
- **Cross-modal correlation**: Audio and video segments captured at the same time should share
  value fate — if the audio is valuable, the video probably is too. Temporal neighbor signal
  partially handles this, but explicit cross-modal linking may be worth adding.
- **Operator override**: Should the operator be able to pin segments as never-trim? A simple
  `pinned: true` frontmatter field would work, but adds a manual step the design tries to avoid.
