# Qdrant Live Collections State Check

**Queue:** #186
**Depends on:** #118 Qdrant schema audit
**Author:** alpha
**Date:** 2026-04-15 (snapshot 2026-04-16T00:12Z UTC)
**Method:** live query against `http://localhost:6333` + comparison to `shared/qdrant_schema.py` `EXPECTED_COLLECTIONS` map.

---

## §0. TL;DR

**All 10 canonical collections exist, match, and are healthy.**

- Set equivalence: live 10 == canonical 10 (no missing, no extra).
- Vector dimension: every collection is 768d Cosine, matching `EXPECTED_EMBED_DIMENSIONS`.
- HTTP status: every collection reports `status: green`.
- One historical finding still visible: `operator-patterns` has 0 points (Queue 026 Phase 4 Finding 2 — writer is de-scheduled). This is a documented dead collection, not new drift.

No immediate action required. No drift, no PR needed.

---

## §1. Live vs canonical set diff

| Collection | Live | Canonical (shared/qdrant_schema.py) |
|---|---|---|
| affordances | ✓ | ✓ |
| axiom-precedents | ✓ | ✓ |
| documents | ✓ | ✓ |
| hapax-apperceptions | ✓ | ✓ |
| operator-corrections | ✓ | ✓ |
| operator-episodes | ✓ | ✓ |
| operator-patterns | ✓ (empty) | ✓ |
| profile-facts | ✓ | ✓ |
| stream-reactions | ✓ | ✓ |
| studio-moments | ✓ | ✓ |

**Count:** 10 live == 10 canonical. **No collections missing from either side.**

---

## §2. Per-collection configuration

All collections queried via `GET /collections/{name}` on `http://localhost:6333` at snapshot time.

| Collection | Points | Vector dim | Distance | Status | Purpose |
|---|---:|---:|---|---|---|
| affordances | 172 | 768 | Cosine | green | Unified Semantic Recruitment gate — Gibson-verb capability descriptions |
| axiom-precedents | 17 | 768 | Cosine | green | Past-operator-decision embeddings for axiom precedents |
| documents | **181 853** | 768 | Cosine | green | RAG document chunks — Obsidian vault + external sources |
| hapax-apperceptions | 184 | 768 | Cosine | green | Higher-order perception aggregates (`agents/_apperception.py` writer) |
| operator-corrections | 307 | 768 | Cosine | green | Explicit operator corrections for learning feedback |
| operator-episodes | 1 712 | 768 | Cosine | green | Session episodes for operator memory |
| operator-patterns | **0** | 768 | Cosine | green | **Empty — writer de-scheduled** (Q026 Phase 4 Finding 2) |
| profile-facts | 929 | 768 | Cosine | green | 11-dimension operator profile facts |
| stream-reactions | 2 758 | 768 | Cosine | green | LRR Phase 2 reaction log + research condition tagging |
| studio-moments | 1 965 | 768 | Cosine | green | Studio compositor moment tagging |

**Total points:** 189,797 across all 10 collections.

**Embedding dimension consistency:** 768 across all 10, matching `EXPECTED_EMBED_DIMENSIONS = 768` and `nomic-embed-cpu`'s output dimension. No dimension drift.

**Distance metric consistency:** every collection uses Cosine distance. No metric drift.

---

## §3. Observations

### §3.1. `operator-patterns` remains at 0 points (not new)

This is **not a new finding** — it's documented in the comment block at `shared/qdrant_schema.py:24-33`:

> `operator-patterns` is currently empty — the writer is de-scheduled; that is Q026 Phase 4 Finding 2 and is inherited as a separate work item in the alpha close-out handoff.

The collection exists (schema correct) but the write path at `agents/_pattern_consolidation.py` is not running on any timer or daemon. The collection will remain at 0 until the writer is re-scheduled.

**This audit is not the place to fix that** — the fix belongs to whatever sprint picks up the Q026 Phase 4 Finding 2 work item. Flagging here only for visibility.

### §3.2. `documents` is the largest collection by far

181,853 points vs the next-largest `stream-reactions` at 2,758. This matches expectations: `documents` is the batch RAG ingest of the Obsidian vault + external sources, ingested via `agents/obsidian_sync.py` and related batch jobs. The 100× scale difference is structurally correct.

### §3.3. `stream-reactions` point count

2,758 points in `stream-reactions`. Queue #164 (PR #915, Phase 1 Qdrant integration check) reported the same point count with a finding that 55 of those (2%) have `condition_id: null` due to the post-reboot SHM marker hydration gap. The writer path correctness was confirmed in that audit; the gap is a pre-writer condition-resolution issue, not a Qdrant-side defect.

This audit does not re-verify the null-condition count (out of scope — queue #164 is the canonical source). Flagging for continuity.

### §3.4. `axiom-precedents` has 17 points

These are embeddings of past-operator-decision text used by the axiom runtime for precedent lookup. The new `sp-hsea-mg-001.yaml` shipped via PR #911 (queue #166) does NOT appear to have been embedded into this collection yet — 17 is a pre-#911 count. There is no writer that automatically embeds new `axioms/precedents/*.yaml` files into Qdrant; the embedding would need to be triggered manually via the `populate-axiom-precedents` script or equivalent.

**Not a defect** — the YAML precedents file is the source of truth for axiom runtime, and the embedding is just for similarity lookup. But it's a minor follow-up candidate: add an auto-embed hook for new precedent files, or a periodic `rag-ingest-axiom-precedents.timer` that scans the directory.

### §3.5. `affordances` at 172 entries

The Unified Semantic Recruitment pipeline depends on this collection. 172 registered capability affordances is consistent with the ~150+ surface area documented in the council CLAUDE.md (perception + expression + recall + action + communication + regulation × instances).

---

## §4. Comparison to #118 audit baseline

Queue #118 was the prior Qdrant schema audit. I do not have the exact point counts from that audit recorded here, but the canonical 10-collection set was the same — the schema drift Q026 Phase 4 Finding 1 had already been resolved at that time.

**This audit's delta vs #118:** no structural change. Point counts will have grown (particularly `documents` via ongoing obsidian_sync, `stream-reactions` via LRR Phase 2 writers, `operator-episodes` via session usage), but the schema is stable.

---

## §5. Recommendations

### §5.1. No blockers

No immediate action required. Schema is clean, all collections healthy, no dimension or distance drift.

### §5.2. Follow-up candidates (not shipped in this queue scope)

| Priority | Item | Size |
|---|---|---|
| LOW | Revive `operator-patterns` writer OR remove the collection from the canonical schema (pick one; don't leave a zero-point collection indefinitely) | dev session — out of scope for audits |
| LOW | Add auto-embed hook for new `axioms/precedents/*.yaml` files so `axiom-precedents` stays in sync with the YAML source of truth | ~20 LOC shell script + systemd timer |
| LOW | Periodic point-count snapshot into Prometheus for each collection (complements LRR Phase 10 §3.2 Grafana work) | ~40 LOC metrics exporter |

None of these are blocking; all are cleanup + observability hardening candidates.

---

## §6. Cross-references

- `shared/qdrant_schema.py` — canonical `EXPECTED_COLLECTIONS` map (10 entries)
- Queue #118 — prior Qdrant schema audit (dependency)
- Queue #164 PR #915 — Phase 1 Qdrant integration check (the 55 null-condition finding)
- Queue #166 PR #911 — shipped `axioms/precedents/sp-hsea-mg-001.yaml` (relates to §3.4)
- Queue #186 — this item

---

## §7. Verdict

Live Qdrant state matches canonical schema exactly. 10 collections, all 768d Cosine, all green. Total points 189,797 across the stack. One historical dead collection (`operator-patterns`) is documented and tracked elsewhere. No drift. No PR needed.

Queue #186 closes as a clean-bill-of-health verification.

— alpha, queue #186
