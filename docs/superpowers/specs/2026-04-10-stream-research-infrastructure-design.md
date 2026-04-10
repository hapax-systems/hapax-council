# Stream Research Infrastructure — Legomena Live as Grounding Research Vehicle

**Date:** 2026-04-10
**Status:** Draft
**Scope:** Measurement, persistence, and data infrastructure for the 24/7 livestream

---

## Problem

The voice grounding experiment had N=0 data after 12 days (Langfuse telemetry gap). The livestream produces hundreds of observations per hour. The stream is the more tractable research vehicle. It needs measurement infrastructure.

## What Needs to Ship Tonight

### 1. JSONL Structured Logging

Parallel to the Obsidian markdown log. Every reaction gets a structured JSON record:

```jsonl
{"ts":"2026-04-10T17:05:23Z","activity":"react","video":"Steve Jobs 1981","text":"...","tokens":47,"album":"Unobtainium by Tofu","coherence":0.687,"chat_authors":0,"stimmung":"nominal"}
```

File: `~/Documents/Personal/30-areas/legomena-live/reactor-log.jsonl`

### 2. Qdrant `stream-reactions` Collection

768-dim nomic-embed vectors. Every reaction persisted with full metadata. On startup, load last 20 reactions so Hapax never loses memory.

Schema: timestamp, activity, text, video_title, album_info, stimmung_stance, chat_state, embedding.

### 3. Langfuse Per-Reaction Scoring

Tag every LLM call with `hapax_score()`:
- `reaction_coherence`: embedding similarity of reaction to (video_title + album + chat)
- `reaction_tokens`: output length
- `reaction_activity`: which activity was chosen

Environment tag: `stream-experiment` (segregated from voice experiment)

### 4. Startup Memory Loading

On compositor restart, load last 20 reactions from Qdrant into `_reaction_history`. Hapax never starts cold.

### 5. Monthly Log Rotation

Obsidian markdown log rotates per month: `reactor-log-2026-04.md`. JSONL rotates similarly.

## What Doesn't Ship Tonight

- Pre-registration (needs careful drafting, not rushed)
- SCED phase protocol (Phase A baseline collection starts after infra is verified)
- Experiment freeze manifest expansion (after pre-reg is filed)
- Vision subsampling cost optimization (not urgent at ~$0.88/day)
