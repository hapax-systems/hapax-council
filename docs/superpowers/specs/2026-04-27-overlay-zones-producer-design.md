# Overlay-Zones Producer: Content Strategy & Architecture

**Date:** 2026-04-27
**Epic:** Livestream Surface Shepherd (`lssh-009`)
**Phase:** Design / Brainstorming Only

## 1. Goal

The `overlay-zones` compositor source currently cycles text rendered via Pango, functioning as a passive reader of `shared.text_repo` or local `.md` folders. This spec proposes the design for the **Overlay-Zones Producer**—the upstream intelligence that autonomously *authors* content for the `text_repo` so the zones display fresh, context-aware information without requiring manual operator intervention.

*Scope Constraint:* This is a design document. No code is implemented in this phase.

## 2. Architectural Seam

The compositor-side `OverlayZoneManager` (in `agents/studio_compositor/overlay_zones.py`) already implements the ideal consumer interface:
- It polls `shared.text_repo` on a configurable cycle (e.g., 15s for the `main` zone, 20s for `research`).
- It falls back to `~/Documents/Personal/30-areas/stream-overlays/` only if the repo is empty.

**The Producer Pattern:**
The new producer will be a standalone daemon (e.g., `agents.overlay_producer.daemon`) that writes directly to `shared.text_repo`. It operates entirely decoupled from the compositor. 
- **Delivery:** It pushes `TextEntry` objects into the JSONL repo.
- **Expiry:** Entries are minted with a TTL (Time-To-Live). The compositor ignores expired entries, providing a natural mechanism for content to "decay" if the producer crashes.

## 3. Brainstormed Content Sources

We propose four initial content pillars. The producer will poll these sources, synthesize short, punchy Pango-compatible markdown, and push to the text repo.

### 3.1. Refusal-as-Data Pipeline
- **Concept:** Periodically surface recent "Refusal Briefs" to the livestream. This reinforces the constitutional boundaries and operational philosophy to the audience.
- **Format:** `[REFUSAL] cold-contact-email-last-resort: Constitutionally incompatible with full-automation directive.`
- **Target Zone:** `main`

### 3.2. Git / Activity Stream
- **Concept:** Trace the operator's active project progression.
- **Implementation Proposal:** Hook into `git_watch` or the local file-watcher to detect commits, branch switches, or PR merges.
- **Format:** `[GIT] Merged PR #1732: docs(refusals) T3-1 draft cold email last-resort refusal brief`
- **Target Zone:** `main`

### 3.3. Objective Tracing
- **Concept:** Translate the current active objective (`~/Documents/Personal/30-areas/hapax-objectives/*.md`) into audience-facing context.
- **Implementation Proposal:** The producer reads the active objective's `activities_that_advance` and `status` fields, summarizing the operator's current focus.
- **Format:** `[OBJECTIVE] Active: Livestream Surface Shepherd (T3-2). Advancing via: brainstorming, design specs.`
- **Target Zone:** `research` (since this zone is already gated by the `study` activity).

### 3.4. Semantic RAG & Contextual Lore
- **Concept:** Pull historical research notes from Qdrant based on the current conversational or task context.
- **Implementation Proposal:** When the Daimonion conversation shifts topics, query Qdrant for top-1 related research snippets.
- **Format:** `[RESEARCH LOG: 2026-04-14] Drop 3: Overlay zones cairo invalid size incident resolved.`
- **Target Zone:** `research`

## 4. Tone and Governance Constraints

The generated content must strictly adhere to Hapax's overarching directives:

- **Show, Don't Tell:** The overlay text must not "narrate" the stream or try to be overly conversational. It should present factual telemetry, raw data, or brief statements. (e.g., Use `[GIT] Commit pushed` instead of `I just pushed a commit!`).
- **Anti-Anthropomorphization:** The text should feel like a system readout or a terminal dump. It must never use "I", "me", or express emotions.
- **Format Limitations:** Max 1-2 sentences. The compositor's Pango engine has a `max_width` of ~1000px and a bold font. Long paragraphs will clip or scroll illegibly.

## 5. Next Steps

1. Select 1-2 pillars (e.g., Git Activity and Objective Tracing) for the Phase 1 implementation.
2. Draft the `OverlayProducer` class that runs on a 1-minute timer, generating and purging `TextEntry` objects in `shared.text_repo`.
3. Wire the producer daemon into the `hapax-supervisor` startup sequence.

## 6. Phase 1 implementation status (2026-05-01)

Per cc-task `overlay-zones-producer-implementation`. Phase 1 ships the
producer framework + the **Git Activity** content pillar (§3.2).

**Shipped entrypoints** (`agents/overlay_producer/`):

- `OverlayProducer` (`producer.py`): orchestrator that holds a list of
  `ContentSource` instances, dedups candidates by id against the
  current repo state, applies a default 5-minute TTL when sources omit
  one, and writes via `TextRepo.add_entry`. Source exceptions are
  caught + counted in `ProducerTickResult.source_failures`; a bad
  source does not block remaining sources or the next tick.
- `ContentSource` Protocol (`producer.py`): structural interface every
  pillar implements as `def collect(self, now: float) -> list[TextEntry]`.
- `GitActivitySource` (`git_activity.py`): shells out to `git log` once
  per `collect`, parses `%H %ct %s` output, emits `[GIT] <hash7>
  <subject>` entries with `context_keys=["main"]`. Subprocess timeout /
  non-zero exit / OSError / missing-PATH / missing-`.git` all degrade
  to an empty list (degraded empty-state).
- `ProducerTickResult` (`producer.py`): typed `(added, skipped_existing,
  source_failures)` tuple so daemon health monitors can act on tick
  outcome counters.
- `agents.overlay_producer.daemon.main`: argparse-backed CLI with
  `--once` (single tick + exit) and the daemon loop. Default 60s
  cadence per spec §5. Run via `uv run python -m agents.overlay_producer`.

**Tests** (`tests/overlay_producer/`):

- `test_producer.py`: construction, no-source / no-candidate / failure
  isolation paths, default TTL vs source-supplied TTL, dedup-by-id
  semantics, zone-context propagation through `select_for_context`.
- `test_git_activity.py`: well-formed and malformed `git log` parsing,
  subprocess error paths, missing-PATH / missing-`.git` short-circuits,
  body truncation invariants, end-to-end `collect` shape.

**Explicit deferrals** (separate slices):

- §3.1 (Refusal-as-Data) — needs the refusal-brief consumer; lands as
  a new `RefusalAnnexSource`.
- §3.3 (Objective Tracing) — depends on a stable schema for vault
  objective notes; lands as a new `ObjectiveSource`.
- §3.4 (Semantic RAG) — Qdrant query path is not yet wired; lands when
  the conversation-context retriever stabilizes.
- systemd `hapax-overlay-producer.service` unit definition — operator
  wires after this module lands; the daemon module is ready to plug in
  via `ExecStart=uv run python -m agents.overlay_producer`.
