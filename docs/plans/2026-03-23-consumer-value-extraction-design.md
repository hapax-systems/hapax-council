# Consumer Value Extraction: Design Document

**Date:** 2026-03-23
**Scope:** Three highest-impact gaps where ingested data is underutilized by consumers
**Prerequisite:** Ingestion pipeline audit design (2026-03-23-ingestion-pipeline-audit-design.md)

---

## 1. Problem Statement

The system ingests rich, well-structured data but consumers systematically underutilize it. Three structural gaps dominate:

1. **10 sync agent profile-facts JSONL files are orphaned** — written but never loaded by the profiler
2. **WS3 Level 3 patterns are write-only** — `PatternStore.search()` exists but is never called
3. **12 perception state fields are dead** — written every 2.5s, read by nothing

---

## 2. Fix A: Wire Sync Agent Profile Facts into Profiler

### Current State
- 10 sync agents write JSONL to `~/.cache/{service}-sync/{service}-profile-facts.jsonl`
- Schema: `{dimension, key, value, confidence, source, evidence}` — matches `ProfileFact` exactly
- `profiler.py:913-952` `load_structured_facts()` only reads 3 hardcoded JSON files from `profiles/`
- `profiler_sources.py:28-44` declares `BRIDGED_SOURCE_TYPES` for these sync agents — the bridge was designed but never built

### Fix
Add JSONL loading to `load_structured_facts()` after the existing JSON loading block and before the watch facts block. Read each sync agent's JSONL from its cache path.

### Files
- `agents/profiler.py` — add JSONL loading loop in `load_structured_facts()` (after line 941)

---

## 3. Fix B: Wire Pattern Retrieval into Perception Tick

### Current State
- `PatternStore.search(query, dimension, active_only, limit, min_score)` returns `list[PatternMatch]`
- Neither method is called by any production code
- `_tick_experiential()` has 3 steps — step 4 is missing
- `CorrectionStore.search_for_dimension()` provides the precedent pattern

### Fix
1. Add `PatternStore` to WS3 initialization alongside the existing stores
2. Add step 4 in `_tick_experiential()`: consult patterns for current activity/flow/hour
3. Rate-limit to every 60s or on activity transition

### Integration Point
- `visual_layer_aggregator.py:__init__` — add `self._pattern_store`
- `visual_layer_aggregator.py:_init_ws3()` — init PatternStore
- `visual_layer_aggregator.py:_tick_experiential()` — step 4 after line 1093

### Output
Store matching patterns in `self._active_patterns`. Surface in perception data for downstream consumption. Best-effort, non-blocking.

### Files
- `agents/visual_layer_aggregator.py`

---

## 4. Fix C: Remove Dead Perception State Fields

### Dead Fields to Remove (12)
- `turn_phase`, `conversation_temperature`, `predicted_tier` (cognitive pipeline)
- `phone_media_app`, `phone_network_type` (phone awareness)
- `operator_confirmed` (presence)
- `nearest_person_distance`, `detected_action`, `audio_scene`, `room_occupancy`, `pose_summary`, `scene_objects` (vision/audio)

### Workspace Monitor Fix
Remove stale reads of `llm_confidence` and `llm_activity` (never written to JSON file, always default values at runtime).

### Files
- `agents/hapax_voice/_perception_state_writer.py` — remove 12 dead fields
- `agents/hapax_voice/workspace_monitor.py` — remove stale reads

---

## 5. Implementation Batches

### Batch A: Sync Agent Profile Facts Bridge
- `agents/profiler.py`

### Batch B: Pattern Retrieval Wiring
- `agents/visual_layer_aggregator.py`

### Batch C: Dead Field Cleanup
- `agents/hapax_voice/_perception_state_writer.py`
- `agents/hapax_voice/workspace_monitor.py`

---

## 6. Scope Exclusions

- Document metadata fields (need consumer redesign, not wiring)
- Confidence-based filtering (architectural decision needed)
- Episode temporal fields (need consumer design)
- Studio-moments underutilization (need agent prompt redesign)
- Watch orphaned signals (need consumer agents)
- Apperception write-only (needs retrieval consumer design)
