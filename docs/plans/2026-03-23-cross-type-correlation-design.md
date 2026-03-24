# Cross-Type Correlation: Design Document

**Date:** 2026-03-23
**Scope:** Wire cross-type (AV ↔ non-AV) correlation at four actionable integration points

---

## 1. Fixes Selected (4 of 7 opportunities, ordered by feasibility)

### Fix A: Serialize Local LLM Activity to Perception State + Re-enable Disagreement Tracking

**Current state:** LocalLLMBackend emits `llm_activity`, `llm_flow_hint`, `llm_confidence` via the perception engine behavior dict. These are accessible via `_bval()` in the perception state writer but never serialized to JSON. `_check_model_disagreement()` in workspace_monitor was turned into a no-op because these fields were absent.

**Fix:** Add 3 fields to perception state dict. Re-enable `_check_model_disagreement()` to route activity disagreements as synthetic corrections.

**Files:**
- `agents/hapax_voice/_perception_state_writer.py` — add 3 fields to state dict
- `agents/hapax_voice/workspace_monitor.py` — re-enable disagreement method, route to correction store

### Fix B: Enrich Episode Summary Text with Biometrics

**Current state:** `Episode.summary_text` (used for embedding) includes only activity, flow, voice_turns. Heart rates and audio energy are downsampled and stored in episode payload but excluded from the embedding text and from the pattern consolidation LLM context.

**Fix:** Add biometric context to `summary_text` property. Add biometric fields to the consolidation LLM episode formatting.

**Files:**
- `shared/episodic_memory.py` — enrich `summary_text` property (line 71-83)
- `shared/pattern_consolidation.py` — add biometric fields to episode context formatting (line 149-183)

### Fix C: Enrich Pattern Consolidation Prompt for Biometric-AV Patterns

**Current state:** The `_EXTRACT_PROMPT` asks for if-then patterns about activity and flow but never mentions biometrics. Heart rate, stress, sleep quality are available in episodes but the LLM is never asked to look for biometric-activity correlations.

**Fix:** Add explicit instruction to the pattern extraction prompt to look for biometric-AV correlations.

**File:**
- `shared/pattern_consolidation.py` — extend `_EXTRACT_PROMPT` (lines 189-212)

### Fix D: Enrich AV Correlator Summary with Unused Sidecar Fields

**Current state:** `_build_summary_text()` includes audio classification, speech/music duration, per-camera categories, joint score, and transcript. But `speaker_count` (audio) and `scene_change`/`max_people` (video) are parsed and ignored.

**Fix:** Add unused but informative sidecar fields to the summary text for richer embeddings.

**File:**
- `agents/av_correlator.py` — extend `_build_summary_text()` (lines 600-621)

---

## 2. Scope Exclusions

- Episode context annotation from non-AV documents (Opp 1) — requires cross-collection temporal join, too complex for this batch
- AV-weighted profile confidence (Opp 2) — requires sync agent redesign
- Cognitive load stimmung dimension (Opp 3) — requires new stimmung dimension, needs separate design
