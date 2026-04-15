# Qdrant collection notes

**Purpose:** per-collection data-quality observations and state notes for every Qdrant collection listed in `shared/qdrant_schema.py::EXPECTED_COLLECTIONS`. Lives outside the schema module so the comments are searchable + operator-readable without grepping source.

**Scope:** documentation only. For schema (dimensions + distance), see `shared/qdrant_schema.py`. For canonical operator decisions affecting authority (who writes, filesystem-vs-Qdrant source-of-truth), see `research/protocols/profile-source-authority.md`.

## `profile-facts`

Canonical source: **`profiles/*.yaml` on disk** (filesystem-authoritative per `profile-source-authority.md`). Qdrant collection is a derived semantic index. Observed drift over time as the sync agent propagation lags or misses YAML deletes. Reconciliation is operator-triggered via `rebuild-profile-facts.py` (if that script exists; else via the sync agent restart).

## `documents`

Populated from `rag-sources/` ingestion. The RAG pipeline re-embeds the source tree on a systemd timer (`rag-ingest.timer`). Point count scales with `rag-sources/` content; typical steady-state is hundreds of thousands of points. No known drift issues.

## `axiom-precedents`

**Observation:** sparse state. 17 points observed at close-out (Q024 #85, Q026 Phase 4 Finding 4). Axioms are rare by design (3 constitutional + 2 domain per `axioms/registry.yaml`), and the writer embeds each axiom's implication + precedent cases — the low point count matches the sparse nature of the constitutional layer, not a data-loss bug. This is an **expected** sparse state, documented here so future audits don't re-raise the observation as a finding.

## `operator-episodes`

Populated by the episode writer (`agents/_episode_*` or similar — verify at query time). Captures discrete operator interaction episodes. No known drift.

## `studio-moments`

Populated by the studio compositor's moment extractor. Captures timestamped compositor state snapshots tied to reaction events.

## `operator-corrections`

Populated by the correction writer when the operator provides feedback on profile facts or agent outputs. Sparse by nature — the operator only corrects when something is wrong.

## `affordances`

Populated by the affordance pipeline's Gibson-verb descriptions. Every capability registered via `@affordance` gets one point. Semantic retrieval over this collection drives the unified semantic recruitment pipeline (see council `CLAUDE.md` § Unified Semantic Recruitment).

## `stream-reactions`

Populated by the stream reaction writer in the compositor director loop (`agents/studio_compositor/director_loop.py` ~line 906). Every reaction the director loop produces gets a point with payload fields including `reaction`, `stimmung_snapshot`, `trace_id`, and — per LRR Phase 1 item 2 — `condition_id`. This is the primary research data surface; LRR Phase 1 item 9 backfills ~2178 existing points with `cond-phase-a-baseline-qwen-001`.

## `hapax-apperceptions`

Populated by the apperception writer (`agents/_apperception.py` or similar). Captures higher-order structural similarities Hapax observes across its own perception + behavior streams. Present in production but previously missing from `EXPECTED_COLLECTIONS` (Q026 Phase 4 Finding 1, fixed in LRR Phase 1 item 10a).

## `operator-patterns`

**Observation:** currently empty. The writer is de-scheduled (Q024 #83, Q026 Phase 4 Finding 2). LRR Phase 1 item 10b opens the decision to re-schedule or retire. Default: re-schedule if a writer is identifiable; retire if not. Until a decision lands, the collection is present in `EXPECTED_COLLECTIONS` (so `verify_collections` doesn't flag it as missing) but empty.

## Cross-references

- Schema: `shared/qdrant_schema.py::EXPECTED_COLLECTIONS`
- Authority decision: `research/protocols/profile-source-authority.md`
- LRR Phase 1 item 10 (Qdrant schema drift fixes): `docs/superpowers/specs/2026-04-15-lrr-phase-1-research-registry-design.md` §3.10
- Council CLAUDE.md § Qdrant (overview + collection enumeration)
