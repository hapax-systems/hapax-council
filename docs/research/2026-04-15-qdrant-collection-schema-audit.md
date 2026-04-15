# Qdrant collection schema audit vs canonical schema

**Date:** 2026-04-15
**Author:** alpha (AWB mode, queue/ item #118)
**Scope:** Verify live Qdrant collections match `shared/qdrant_schema.py EXPECTED_COLLECTIONS`. Check vector dim, distance metric, payload schema consistency, orphaned collections. Compare against workspace CLAUDE.md list.
**Register:** scientific, neutral

## 1. Headline

**Live Qdrant matches canonical schema exactly.** 10 collections, all with 768d Cosine vectors, perfect 1:1 mapping with `EXPECTED_COLLECTIONS` in `shared/qdrant_schema.py`.

**One empty collection flagged as inherited work:** `operator-patterns` has 0 points. Per inline comment in `shared/qdrant_schema.py` (lines 31-33), the writer is de-scheduled (Q026 Phase 4 Finding 2). Known drift, tracked elsewhere.

**No orphaned collections. No missing collections. No distance metric drift. No dim drift.**

## 2. Method

```bash
# Canonical schema
cat shared/qdrant_schema.py

# Live collections
curl -s http://localhost:6333/collections

# Per-collection config
for c in <collection_names>; do
  curl -s "http://localhost:6333/collections/$c" | python -c '...'
done

# Sample payloads
curl -X POST "http://localhost:6333/collections/$c/points/scroll" \
     -d '{"limit":1,"with_payload":true}'
```

## 3. Canonical schema (shared/qdrant_schema.py)

```python
EXPECTED_COLLECTIONS: dict[str, dict[str, object]] = {
    "profile-facts":         {"size": 768, "distance": "Cosine"},
    "documents":             {"size": 768, "distance": "Cosine"},
    "axiom-precedents":      {"size": 768, "distance": "Cosine"},
    "operator-episodes":     {"size": 768, "distance": "Cosine"},
    "studio-moments":        {"size": 768, "distance": "Cosine"},
    "operator-corrections":  {"size": 768, "distance": "Cosine"},
    "affordances":           {"size": 768, "distance": "Cosine"},
    "stream-reactions":      {"size": 768, "distance": "Cosine"},
    "hapax-apperceptions":   {"size": 768, "distance": "Cosine"},
    "operator-patterns":     {"size": 768, "distance": "Cosine"},
}
```

All 10 collections use `EXPECTED_EMBED_DIMENSIONS = 768` (nomic-embed-cpu) + `Cosine` distance. Homogeneous by design.

## 4. Live state (2026-04-15T18:34Z)

```
$ curl -s http://localhost:6333/collections
{"result":{"collections":[
  {"name":"operator-corrections"},
  {"name":"stream-reactions"},
  {"name":"documents"},
  {"name":"axiom-precedents"},
  {"name":"profile-facts"},
  {"name":"hapax-apperceptions"},
  {"name":"operator-episodes"},
  {"name":"studio-moments"},
  {"name":"affordances"},
  {"name":"operator-patterns"}
]}}
```

**10 collections live. 10 collections canonical. Perfect match.**

### 4.1 Per-collection config verification

| Collection | size | distance | points | Canonical match |
|---|---|---|---|---|
| profile-facts | 768 | Cosine | 929 | ✓ |
| documents | 768 | Cosine | 181,871 | ✓ |
| axiom-precedents | 768 | Cosine | 17 | ✓ |
| operator-episodes | 768 | Cosine | 1,710 | ✓ |
| studio-moments | 768 | Cosine | 1,965 | ✓ |
| operator-corrections | 768 | Cosine | 307 | ✓ |
| affordances | 768 | Cosine | 172 | ✓ |
| stream-reactions | 768 | Cosine | 2,758 | ✓ |
| hapax-apperceptions | 768 | Cosine | 183 | ✓ |
| **operator-patterns** | 768 | Cosine | **0** | ✓ config, empty data |

**10/10 collections match canonical schema.** Zero dim drift, zero distance metric drift.

**Total points across all collections: 189,912** (181,871 of which are in `documents`).

## 5. Payload schema spot-check

Sample payload keys per collection (first point):

| Collection | Payload keys |
|---|---|
| profile-facts | confidence, dimension, key, profile_version, source, text, value |
| documents | chunk_count, chunk_index, extension, filename, gdrive_folder, ingested_at, source, source_service, text |
| axiom-precedents | authority, axiom_id, created, decision, distinguishing_facts, precedent_id, reasoning, situation, superseded_by, tier |
| operator-episodes | activity, audio_energy, audio_trend, consent_phase, corrections_applied, duration_s, end_ts, flow_scores, flow_state, flow_trend, heart_rates, hour |
| studio-moments | audio_classification, audio_file, audio_score, correlated_at, joint_category, joint_score, music_seconds, speech_seconds, transcript_snippet, video_classifications, video_files, video_motion |
| operator-corrections | activity, applied_count, context, corrected_value, dimension, flow_score, hour, id, last_applied, original_value, timestamp |
| affordances | available, capability_name, consent_required, daemon, description, latency_class, priority_floor, requires_gpu |
| stream-reactions | activity, album, chat_authors, chat_messages, reaction_index, stimmung, text, tokens, ts, ts_str, video_channel, video_title |
| hapax-apperceptions | action, cascade_depth, observation, reflection, source, stimmung_stance, timestamp, trigger_text, valence, valence_target |
| operator-patterns | EMPTY |

**Observations:**
- Payload schemas are **collection-specific** (no unified schema — each collection has its own domain fields)
- Canonical schema at `shared/qdrant_schema.py` **does not encode payload schemas** — only vector config. So there is no "canonical payload" to drift against.
- `canonical schema audit` for payloads would require per-collection Pydantic models, which do not exist in `shared/qdrant_schema.py` today. This is a **gap** (G1 below).

## 6. Workspace CLAUDE.md cross-reference

Workspace CLAUDE.md § Shared Infrastructure states:

> **Qdrant** — Vector DB (10 collections: profile-facts, documents, axiom-precedents, operator-episodes, studio-moments, operator-corrections, affordances, hapax-apperceptions, operator-patterns, stream-reactions)

| Listed in CLAUDE.md | Present in EXPECTED_COLLECTIONS | Present live |
|---|---|---|
| profile-facts | ✓ | ✓ |
| documents | ✓ | ✓ |
| axiom-precedents | ✓ | ✓ |
| operator-episodes | ✓ | ✓ |
| studio-moments | ✓ | ✓ |
| operator-corrections | ✓ | ✓ |
| affordances | ✓ | ✓ |
| hapax-apperceptions | ✓ | ✓ |
| operator-patterns | ✓ | ✓ |
| stream-reactions | ✓ | ✓ |

**10/10 tripled.** Workspace CLAUDE.md list, canonical schema, and live state are all in sync.

## 7. Findings

### 7.1 Drift: zero

No collection exists in one source but not another. No config drift. No dim drift. No distance metric drift. The schema verification infrastructure (`verify_collections` in `shared/qdrant_schema.py`) is actively running and would log warnings if any drift appeared.

### 7.2 Known inherited work — `operator-patterns` empty

`operator-patterns` has 0 points. Per inline comment in `shared/qdrant_schema.py:31-33`:

> `operator-patterns` is currently empty — the writer is de-scheduled; that is Q026 Phase 4 Finding 2 and is inherited as a separate work item in the alpha close-out handoff.

**Not a drift finding** — the collection exists per canonical schema, but the agent writing to it (`agents/_pattern_consolidation.py`) is de-scheduled. Tracked as Q026 P4 F2.

### 7.3 Gap G1 (LOW) — no canonical payload schema

`shared/qdrant_schema.py` only encodes vector config (dim + distance). It does not define payload schemas, so there is no structural check that e.g. `operator-episodes` payloads always have the expected keys (`activity`, `duration_s`, `consent_phase`, etc.).

**Impact:** a writer that drifts (adds/removes/renames fields) will not be caught until a reader fails. Payload corruption via schema drift is currently detected by runtime failures, not by upstream validation.

**Remediation options:**
- (a) Add Pydantic models per collection in `shared/qdrant_schema.py`, use them in all writers
- (b) Add `verify_payloads()` that scroll-samples each collection and checks for a minimum set of required keys
- (c) Keep as-is — collection-specific payload schemas, no centralized enforcement

Alpha recommends (b) as a small, incremental improvement. (a) is a larger refactor; (c) leaves the gap.

### 7.4 Gap G2 (LOW) — `operator-patterns` writer de-scheduled

Separate from G1. The `operator-patterns` collection is in canonical schema but unpopulated because its writer agent is de-scheduled. Either:

- (a) Re-enable the writer (`agents/_pattern_consolidation.py`)
- (b) Remove the collection from canonical schema + delete the live collection
- (c) Keep as inherited Q026 P4 F2 work item (current)

Alpha recommends (c) — this is already tracked, low priority, and the empty collection has negligible cost.

## 8. Positive findings

1. **Exact 10/10 match between canonical, live, and CLAUDE.md docs.** No drift, no orphans, no missing.
2. **`verify_collections()` runs at startup** (called from `log_collection_issues()`) — drift would be logged automatically if it appeared.
3. **Q026 Phase 4 Finding 1 fix holds.** Previously `hapax-apperceptions` + `operator-patterns` were live but not in `EXPECTED_COLLECTIONS`; the schema file now includes them.
4. **`documents` collection is by far the largest** (181,871 points) and matches expected RAG bulk ingestion pattern. No cardinality concerns.
5. **Payload keys are semantically coherent per collection** (e.g., `operator-episodes` has activity+duration+flow scores as expected).

## 9. Recommendations

### 9.1 File as follow-up (low priority)

- **G1 — Add `verify_payloads()` helper.** Small incremental improvement. ~30 LOC Python + 3 tests. Optional.

### 9.2 No action needed

- Schema is consistent across all three sources of truth (canonical file, live state, CLAUDE.md docs).
- Existing `verify_collections()` infrastructure provides ongoing drift detection.

## 10. Closing

Qdrant schema is clean. 10/10 collections match canonical. Zero drift. The only caveat is the empty `operator-patterns` collection, which is already tracked as inherited work. Payload schema validation is a structural gap but is low-impact and can be addressed incrementally via a small `verify_payloads()` helper.

Branch-only commit per queue item #118 acceptance criteria.

## 11. Cross-references

- `shared/qdrant_schema.py` — canonical schema + `verify_collections()`
- `shared/config.py:102` — `EXPECTED_EMBED_DIMENSIONS = 768`
- Workspace CLAUDE.md § "Shared Infrastructure" — Qdrant collection list
- Q026 Phase 4 Finding 1 — previous drift fix (adding hapax-apperceptions + operator-patterns)
- Q026 Phase 4 Finding 2 — operator-patterns writer de-scheduled (inherited work)
- `agents/_apperception.py` — writer for hapax-apperceptions
- `agents/_pattern_consolidation.py` — writer for operator-patterns (de-scheduled)

— alpha, 2026-04-15T18:36Z
