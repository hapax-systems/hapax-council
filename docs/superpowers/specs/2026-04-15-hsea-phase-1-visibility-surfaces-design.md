# HSEA Phase 1 — Visibility Surfaces — Design Spec

**Date:** 2026-04-15
**Author:** delta (pre-staging extraction from HSEA epic spec per the LRR-epic extraction pattern)
**Status:** DRAFT pre-staging — awaiting operator sign-off + cross-epic dependency resolution before Phase 1 open
**Epic reference:** `docs/superpowers/specs/2026-04-14-hsea-epic-design.md` §5 Phase 1 (drops #60/#61)
**Plan reference:** `docs/superpowers/plans/2026-04-15-hsea-phase-1-visibility-surfaces-plan.md` (companion TDD checkbox plan)
**Branch target:** `feat/hsea-phase-1-visibility-surfaces`
**Cross-epic authority:** `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md` (drop #62) — §3 ownership table and §5 unified phase sequence take precedence over any conflicting claim in this spec
**Unified phase mapping:** **UP-4 Visibility Surfaces** (drop #62 §5): depends on UP-1 (LRR research registry), UP-2 (HSEA foundation primitives), UP-3 (LRR archive instrument); 2-3 sessions, ~1200 LOC

---

## 1. Phase goal

Ship the 5 Cairo overlay sources that make all subsequent HSEA work visible on the livestream. Phase 1 is the first visibility layer: every downstream HSEA phase writes at least one piece of state that becomes content through a Phase 1 surface.

**What this phase is:** HUD telemetry overlay, research state broadcaster, glass-box prompt renderer, live orchestration strip, governance queue overlay. Plus the `hsea_spawn_heartbeat()` helper needed by the orchestration strip (since `shared/telemetry.py::hapax_span` has no post-emit hook per Phase 0 deliverable 0.1 discovery).

**What this phase is NOT:** this phase does not ship director-loop activities (Phase 2), does not extend the compositor's zone allocation registry (LRR Phase 2 / UP-3 owns `config/compositor-zones.yaml`), does not ship any new governance primitives (Phase 0), and does not ship any non-Cairo surface (no HTML, no logos, no Hyprland widget). Phase 1 is strictly GStreamer/Cairo overlay sources that read state and render it.

---

## 2. Dependencies + preconditions

**Cross-epic (from drop #62 §5 + §3):**

1. **LRR UP-0 (verification) closed.** Standard HSEA phase precondition.
2. **LRR UP-1 (research registry) closed.** Deliverables 1.1 and 1.2 both read LRR-owned artifacts:
   - `scripts/research-registry.py` CLI + `/dev/shm/hapax-compositor/research-marker.json` + `~/hapax-state/research-registry/cond-*/condition.yaml` + `~/hapax-state/research-integrity/heartbeat.json`. Per drop #62 §3 ownership table rows 2/3/5: LRR Phase 1 is the only writer of these paths; HSEA Phase 1 reads via atomic-read pattern.
3. **LRR UP-3 (archive instrument) closed.** Phase 1 uses LRR Phase 2's `SourceRegistry`/`OutputRouter` registration pattern to register new Cairo sources per drop #62 §3 row 14. Zone registration goes through `config/compositor-zones.yaml` (LRR Phase 2 item 10 mandates layout-declared `video_out` migration and ships the zones registry). If LRR Phase 2 has not shipped `SourceRegistry`, Phase 1 cannot register its overlays cleanly.
4. **HSEA UP-2 (foundation primitives) closed.** Phase 1 consumes Phase 0 deliverables directly:
   - **0.1 `shared/prom_query.py`**: deliverable 1.1 HUD uses `WatchedQueryPool` at 2 Hz.
   - **0.2 `shared/governance_queue.py`**: deliverable 1.5 governance queue overlay reads `GovernanceQueue.pending()` + `oldest_pending_age_s()` + `most_recent()`.
   - Phase 0 `hsea-state.yaml` must exist with `phase_statuses[0].status: closed` before Phase 1 opens.

**Intra-epic:** Phase 0 closed. No other HSEA phase prerequisite.

**Infrastructure:**

1. `agents/studio_compositor/cairo_source.py::CairoSource` + `CairoSourceRunner` (existing, Phase 1 registers 5 new subclasses).
2. `agents/studio_compositor/overlay_zones.py::ZONES` (existing zone registry; Phase 1 may add new zones or use existing).
3. Design-language CSS custom properties (existing; `--color-*` tokens per `docs/logos-design-language.md`). Phase 1 MUST NOT use hardcoded hex.
4. `shared/frontmatter.py` (existing; consumed by deliverable 1.2 for reading condition.yaml).
5. `agents/studio_compositor/sierpinski_renderer.py` (existing; deliverable 1.2 adds a new "research card" slot).
6. `_build_unified_prompt()` in `agents/hapax_daimonion/prompt_builder.py` or similar (existing; deliverable 1.3 reads its output).

---

## 3. Deliverables

### 3.1 HUD Cairo overlay (D1)

**Scope:**
- New `HudSource(CairoSource)` in `agents/studio_compositor/hud_source.py`
- Renders compositor telemetry at 2 Hz in a top-left, low-opacity zone
- Metrics displayed:
  - Compositor uptime (`compositor_uptime_seconds` via prom_query)
  - FD count bar (`compositor_fd_count` gauge from FDL-1 observability additions)
  - Cameras healthy/total (`compositor_cameras_healthy_total` / `compositor_cameras_total`)
  - Per-role frame age (4 cameras × `compositor_frame_age_seconds{role=X}`)
  - GPU utilization + VRAM used (`nvidia_gpu_utilization` + `nvidia_vram_used_mib` from central Prometheus)
  - LLM p95 latency (`hapax_llm_p95_ms` from central Prometheus)
  - Voice latency (`hapax_voice_latency_ms`)
  - Chat authors in last window (`hapax_chat_authors_5m`)
  - Current condition_id (read from `research-marker.json`, NOT from prom_query — faster and more authoritative)
- **Color-coded via design-language CSS custom properties** — no hardcoded hex. Layer color semantics: green = nominal, yellow = degraded, red = failing. Colors come from the CSS custom property system documented in `docs/logos-design-language.md` §3.
- **Consumer of shared Prometheus poller (Phase 0 0.1):** registers ~10 `WatchedQuery`s at the 2 Hz tier, one per metric. Pool worker drives the refresh; HudSource's render callback just reads the cached values the pool writes into a shared `dict[str, InstantResult]`.
- **Render safety:** Cairo callback runs on the GStreamer streaming thread and MUST NOT block. Reads from the prom_query cache are pure dict lookups. If a metric is stale (> 5s since last update), HUD displays "--" for that field, not the stale value.
- **Target file:** `agents/studio_compositor/hud_source.py`
- **Tests:** `tests/studio_compositor/test_hud_source.py` with fixture-based metric injection (no real compositor required)

**Size:** ~250 LOC implementation + ~120 LOC tests ≈ 370 LOC total, ~0.5 day serial work

### 3.2 Research state broadcaster (C1)

**Scope:**
- New `ResearchStateSource(CairoSource)` in `agents/studio_compositor/research_state_source.py`
- Persistent Cairo overlay in the top-right zone; refreshes at 1 Hz
- Renders:
  - Active `condition_id` (from `/dev/shm/hapax-compositor/research-marker.json`, atomic-read; if stale >30s, show "condition unknown — check registry")
  - Current LRR phase (from `hsea-state.yaml` or `lrr-state.yaml` via the Phase 0 session-context pattern — read-only)
  - Scores today vs target (parsed from `~/hapax-state/research-registry/cond-<id>/scores-today.jsonl`)
  - Time since last session (parsed from `~/hapax-state/research-integrity/heartbeat.json`)
  - Attribution integrity tier (from `heartbeat.json::attribution_tier`)
  - Next scheduled session (from `~/hapax-state/research-registry/cond-<id>/schedule.yaml` if present)
- **Sierpinski card slot:** every 5 minutes, the research state broadcaster also renders a condensed "research card" into the Sierpinski triangle slot system via `agents/studio_compositor/sierpinski_renderer.py::render_text_card()`. The card shows only the condition_id + score progress bar (design-language tokens). Separate cadence from the Cairo overlay.
- **Data source ownership:** per drop #62 §3 rows 2/3/5, all research-registry paths are LRR Phase 1 scope. HSEA Phase 1 reads via atomic-read-with-stale-detection; never writes.
- **Color semantics:** research card color maps to condition phase (A/B/C) using design-language tokens. Overlay opacity reflects staleness (1.0 fresh → 0.3 stale).
- **Target file:** `agents/studio_compositor/research_state_source.py`
- **Tests:** `tests/studio_compositor/test_research_state_source.py` with fixture research-marker + condition.yaml + heartbeat files

**Size:** ~200 LOC implementation + ~100 LOC tests ≈ 300 LOC total, ~0.5 day serial work

### 3.3 Glass-box prompt rendering (F1)

**Scope:**
- New `PromptGlassSource(CairoSource)` in `agents/studio_compositor/prompt_glass_source.py`
- Dedicated `prompt-glass` Cairo zone (left-middle or wherever the zone registry places it)
- Renders the current unified prompt as produced by `_build_unified_prompt()`:
  - Truncates to the active section (persona header, last-8 reactions window, extreme-dimension callouts)
  - Shows which of the last-8 reactions are in context (highlight vs dim)
  - Shows which of the 9 canonical dimensions are currently extreme (color-coded per design-language)
  - Shows current `condition_id` as a header band
- **Refresh cadence:** per-tick (8 seconds, matching the daimonion cognitive tick). No narration.
- **Foundation for F-series:** per the HSEA epic, layers F2–F7 (reflexive self-modeling) are unfalsifiable without 1.3 — they narrate the prompt, so the prompt must be legible on stream. 1.3 is the substrate that makes F2–F7 verifiable. Phase 1 does NOT ship F2–F7 — those are HSEA Phase 10 per drop #62 §5.
- **Reading surface:** `PromptGlassSource` does NOT call `_build_unified_prompt()` directly; that function is called by the daimonion on the cognitive-loop thread. Instead, the daimonion writes its most recent built prompt (+ metadata about last-8 reactions, extreme dimensions, condition_id) to a shared memory snapshot file at each tick; the PromptGlassSource reads that file atomically. This preserves render-thread safety.
- **Daimonion writer:** add `_write_prompt_glass_snapshot()` in `agents/hapax_daimonion/prompt_builder.py` (or wherever `_build_unified_prompt()` lives) that writes the snapshot JSON after every `_build_unified_prompt()` call. ~30 LOC addition.
- **Target files:**
  - `agents/studio_compositor/prompt_glass_source.py` (~150 LOC overlay)
  - `agents/hapax_daimonion/prompt_builder.py` (~30 LOC snapshot writer extension — verify exact file name at open time)
  - `tests/studio_compositor/test_prompt_glass_source.py` (~80 LOC)

**Size:** ~260 LOC total, ~0.5 day serial work

### 3.4 Live orchestration strip (G3)

**Scope:**
- New `OrchestrationStripSource(CairoSource)` in `agents/studio_compositor/orchestration_strip_source.py`
- Reads a JSONL ledger of currently-active sub-agents at `/dev/shm/hapax-orchestration/active.jsonl`, one line per agent
- Per-line schema: `{id, label, started_at, status, latency_estimate, parent_spawn_id, model_tier}`
- Renders horizontal swimlanes in the lower content zone: one row per active agent, showing id/label + elapsed time bar + status icon
- Refresh: 2 Hz via `WatchedQueryPool`-style polling (or simpler `threading.Timer`; the pool is primarily for Prometheus queries, not JSONL reads)
- **Writer side — `hsea_spawn_heartbeat()` helper:** `shared/telemetry.py::hapax_span` currently has no post-emit hook (discovered as a Phase 0 workaround note). Phase 1 introduces `shared/hsea_orchestration.py::hsea_spawn_heartbeat(spawn_id, label, status, latency_estimate)` that any sub-agent can call to append/update its entry in the active.jsonl ledger. The helper manages:
  - Append on first call
  - Update (rewrite-in-place via `atomic_write_json`-style on subsequent calls, OR append a second line with the same id that the reader deduplicates — append is simpler)
  - Terminal transition on status=done/failed: marks the entry as terminal; OrchestrationStripSource filters terminal entries after 30 seconds
  - Reap: a companion systemd timer `hapax-orchestration-reap.timer` rotates stale entries to `/dev/shm/hapax-orchestration/reaped.jsonl` (or deletes)
- **Target files:**
  - `agents/studio_compositor/orchestration_strip_source.py` (~200 LOC overlay)
  - `shared/hsea_orchestration.py` (~80 LOC heartbeat helper)
  - `systemd/user/hapax-orchestration-reap.timer` + `.service` (config)
  - `tests/studio_compositor/test_orchestration_strip_source.py` (~100 LOC)
  - `tests/shared/test_hsea_orchestration.py` (~80 LOC)

**Size:** ~460 LOC total, ~0.5-1 day serial work

### 3.5 Governance queue overlay

**Scope:**
- New `GovernanceQueueSource(CairoSource)` in `agents/studio_compositor/governance_queue_source.py`
- **Phase 0 descope carry-over:** the original HSEA epic spec Phase 0 deliverable 0.2 listed a governance queue Cairo overlay inline with the queue module; drop #62 §7 resource budget row 2 re-listed it as a Phase 1 surface. This spec resolves the duplication by declaring Phase 0 ships the queue primitive only and Phase 1 ships the overlay. The HSEA Phase 0 spec + plan are edited alongside this spec to remove the Cairo overlay from deliverable 0.2 scope.
- Renders governance queue state as a persistent pill in the bottom-center zone
- Display: "N proposals awaiting review · oldest X" (e.g., "2 proposals awaiting review · oldest 3h 14m")
- Color transitions via design-language tokens:
  - Green = queue empty (0 pending)
  - Yellow = oldest pending > 24h
  - Red = oldest pending > 72h
- Refresh: 1 Hz via `WatchedQueryPool` pseudo-query (or `threading.Timer`; same implementer choice as orchestration strip)
- **Command-registry integration:** the pill is clickable in the Logos app via command-registry action `governance.queue.open`, which opens the Obsidian inbox at `~/Documents/Personal/00-inbox/`. The command-registry wiring is a ~20 LOC addition to `hapax-logos/src/lib/commands/governance.ts`; the Cairo overlay itself is non-interactive (the click target lives in the Logos shell, not in the compositor render path).
- **Reading:** consumes `shared/governance_queue.py::GovernanceQueue` from HSEA Phase 0 deliverable 0.2. Specifically: `pending()` + `oldest_pending_age_s()` + `most_recent()` methods.
- **Target files:**
  - `agents/studio_compositor/governance_queue_source.py` (~150 LOC overlay source)
  - `hapax-logos/src/lib/commands/governance.ts` (~20 LOC command wiring)
  - `tests/studio_compositor/test_governance_queue_source.py` (~80 LOC)

**Size:** ~250 LOC total, ~0.3 day serial work

---

## 4. Phase-specific decisions since epic authored

Drop #62 fold-in (2026-04-14) + operator batch ratification (2026-04-15T05:35Z) + this extraction (2026-04-15) introduce the following corrections relative to the original HSEA epic spec §5 Phase 1:

1. **Governance queue Cairo overlay ownership is Phase 1, not Phase 0.** The original HSEA epic spec listed the Cairo overlay in BOTH Phase 0 deliverable 0.2 (as part of the queue module) AND Phase 1 deliverable 1.5 (as a separate surface). This spec resolves the duplication: Phase 0 ships the primitive (module + inotify watcher + reap); Phase 1 ships the surface. The HSEA Phase 0 spec + plan are edited in the same commit as this spec to reflect the descope.

2. **Spawn budget Cairo overlay stays in Phase 0 deliverable 0.3.** Unlike the governance queue overlay, the spawn budget overlay was not duplicated in the original HSEA epic spec's Phase 1. This extraction does NOT move it. Rationale: (a) the original intent is respected; (b) spawn budget overlay is tightly coupled to the ledger's aggregation methods and benefits from ledger co-location; (c) Phase 1 does not have a spawn budget surface slot without introducing a 1.6 which is scope creep. If the operator prefers the "Phase 0 = primitives only, Phase 1 = all visibility surfaces" split for consistency, a follow-up extraction can create 1.6 Spawn Budget Overlay and descope 0.3's overlay. This spec does NOT make that move; it leaves the spawn budget overlay in 0.3.

3. **Deliverable 1.3 splits into two files:** the original epic spec described 1.3 as a single surface. This extraction splits the work across two files (`prompt_glass_source.py` for the overlay + a ~30-LOC extension to the daimonion's prompt-builder module for writing the snapshot JSON). The split is mechanical, not a scope change, and preserves render-thread safety (the daimonion thread writes, the compositor thread reads).

4. **Deliverable 1.4 introduces `shared/hsea_orchestration.py`** as a new top-level module for the `hsea_spawn_heartbeat()` helper. The HSEA epic spec mentioned the helper inline ("since `hapax_span` has no post-emit hook") but did not assign it a target file. This extraction declares the target.

5. **All drop #62 §10 open questions are closed** as of 2026-04-15T05:35Z. No Phase 1 deliverable is gated on a pending operator decision. Phase 1's opening preconditions are entirely upstream-epic (UP-0/UP-1/UP-2/UP-3 closed) + infrastructure (FDL-1 deployed + compositor running).

6. **LRR Phase 8 vs HSEA Phase 1 surface distinction (drop #62 §3 row 20):** LRR Phase 8 ships `objective-overlay`, Logos studio view tile, terminal capture tile, PR/CI status overlay — these are NOT the same as HSEA Phase 1's 5 surfaces. The naming is kept distinct to prevent re-implementation drift. Phase 1 does not ship any LRR Phase 8 surface.

7. **Zone registry (`config/compositor-zones.yaml`) is LRR Phase 2 / UP-3 scope.** Phase 1 ADDS entries to the zone registry (each of the 5 new surfaces needs a zone), but does NOT ship the registry file itself. If LRR Phase 2 has not yet shipped the registry, Phase 1 blocks on UP-3 close per precondition 3.

---

## 5. Exit criteria

Phase 1 closes when ALL of the following are verified:

1. All 5 Cairo sources rendering in the production compositor:
   - [ ] `HudSource` registered via `SourceRegistry`, visible in top-left zone
   - [ ] `ResearchStateSource` registered, visible in top-right zone, Sierpinski card slot updating every 5 min
   - [ ] `PromptGlassSource` registered, visible in prompt-glass zone, updating per daimonion tick
   - [ ] `OrchestrationStripSource` registered, visible in lower content zone, renders at least one stub agent during smoke test
   - [ ] `GovernanceQueueSource` registered, visible as persistent pill, reflects Phase 0 queue state

2. Operator verification: operator runs the compositor and visually confirms each of the 5 surfaces. Screenshot evidence attached to the handoff doc.

3. Zone allocation updated in `config/compositor-zones.yaml` (LRR Phase 2-owned file) with the 5 new zones. Each zone declaration references the Phase 1 spec by name.

4. `hsea_spawn_heartbeat()` helper ships with regression tests covering: first-call append, update-in-place, terminal transition, reap after 30s terminal, concurrent writer safety.

5. `hsea-state.yaml::phase_statuses[1].status == closed` written at phase close; `research-stream-state.yaml::unified_sequence[UP-4].status == closed` if the shared index has landed.

6. **Golden-image regression tests** for each Cairo source (if existing compositor test harness supports). If the existing harness does not support rendered-output capture, ship tests that validate the Cairo draw call sequence without pixel comparison. Do NOT block phase close on a test harness upgrade — that is scope creep.

7. **Smoke test 1 (HUD):** all ~10 HUD metrics show live values when the compositor is running under normal conditions. FD bar bars visible. Color coding transitions correctly when a metric is forced into degraded/failing state (inject via a test-only Prometheus proxy).

8. **Smoke test 2 (Research state):** research-marker.json update propagates to the research state broadcaster within 1 second. Sierpinski card updates visible on the next 5-minute tick.

9. **Smoke test 3 (Prompt glass):** daimonion writes a snapshot JSON; the overlay updates within 1 tick (8s). Verify with a stub daimonion that does not require full cognitive loop.

10. **Smoke test 4 (Orchestration strip):** stub agent calls `hsea_spawn_heartbeat()` three times (append → update → terminal). Strip renders one swimlane, updates, and removes the swimlane 30s after terminal.

11. **Smoke test 5 (Governance queue overlay):** append a test entry to Phase 0 governance queue; overlay pill updates within 1 refresh cycle (1 Hz). Color transitions triggered by injecting an artificial 25h-old pending entry (yellow) and a 73h-old pending entry (red).

12. **Handoff doc written** at `docs/superpowers/handoff/2026-04-15-hsea-phase-1-complete.md` (use today's date at actual closing) with screenshots of all 5 surfaces.

---

## 6. Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LRR Phase 2 (UP-3) `SourceRegistry` not ready when Phase 1 opens | MEDIUM | Blocks Phase 1 opening entirely (no registration mechanism) | Phase 1 onboarding MUST verify UP-3 closed; otherwise phase blocks |
| Cairo render thread blocking on slow disk reads | MEDIUM | Frame-age spikes, stream judder | All reads are atomic-read from `/dev/shm` (tmpfs); no disk I/O on render path. `shared/frontmatter.py` caching for condition.yaml reads. |
| Design-language token integration — hardcoded hex leaks through | LOW | Violates logos-design-language.md §3 authority | Pre-commit hook `axiom-commit-scan.sh` or similar enforces; CI catches. If no hook exists, add one in Phase 1 deliverable 1.1 PR. |
| HUD metric cardinality explodes Prometheus scrape budget | MEDIUM | Per-condition slicing (drop #62 §3 row 13) has a budget; adding ~10 HUD-specific queries could collide | Budget owner is LRR Phase 10; Phase 1 registers at 2 Hz only; if budget pressure arises, Phase 1 drops to 1 Hz + batching. |
| `_build_unified_prompt()` snapshot write races with daimonion's next tick | LOW | Overlay sees an inconsistent snapshot | `atomic_write_json`-style write via temp+rename; render thread reads atomically. |
| Orchestration strip active ledger grows unbounded if reap timer fails | MEDIUM | `/dev/shm` exhaustion over time | Reap timer every 1 minute + size guard in `hsea_spawn_heartbeat` (>1MB triggers emergency truncation + ntfy) |
| Governance queue Cairo overlay descoped from Phase 0 late — breaks Phase 0 spec/plan | HIGH | Phase 0 spec/plan just committed on 2026-04-15 | Same-commit amendment of Phase 0 spec/plan alongside this spec (applied in the same delta research commit) |
| Sierpinski card slot contention with existing content | MEDIUM | Research card + existing album cover / overlay zones may compete for the same slot | Phase 1 1.2 declares a NEW card slot in `sierpinski_renderer.py`; does not repurpose existing |
| FDL-1 not deployed when Phase 1 tests run | MEDIUM | HUD `compositor_fd_count` gauge unavailable | HUD gracefully shows "--" for missing metrics; test fixtures inject synthetic values |

---

## 7. Open questions

All drop #62 §10 open questions are resolved as of 2026-04-15T05:35Z. Phase 1 has no remaining operator-pending decisions.

Phase-1-specific design questions (operator or Phase 1 opener can decide at open time; not blocking):

1. **Spawn budget Cairo overlay relocation to Phase 1 1.6.** This extraction leaves the spawn budget overlay in Phase 0 deliverable 0.3 per §4 decision 2. If the operator prefers pure "Phase 0 = primitives / Phase 1 = visibility" consistency, a follow-up decision can create 1.6 Spawn Budget Overlay and descope 0.3's overlay component. Recommendation: leave as-is; the coupling to the ledger is real and the cost of a 1.6 addition is not worth the aesthetic consistency.

2. **OrchestrationStrip polling cadence.** Epic spec suggests 2 Hz. This extraction preserves that. If the operator observes distracting strip movement at 2 Hz on stream, drop to 1 Hz.

3. **Glass-box prompt zone sizing.** The epic spec does not pin a zone size. Phase 1 opener decides based on the current compositor layout; default recommendation is ~30% width, lower-middle vertical.

4. **HUD telemetry inclusion list.** This spec lists ~10 metrics; the opener may decide to start with a smaller set (5-6) and expand after user feedback. The `WatchedQueryPool` registration pattern makes adding/removing queries cheap.

---

## 8. Companion plan doc

TDD checkbox task breakdown at `docs/superpowers/plans/2026-04-15-hsea-phase-1-visibility-surfaces-plan.md`.

Execution order inside Phase 1 (serial, single-session-per-deliverable model):

1. **1.1 HUD** — ships first because the `WatchedQueryPool` consumer pattern is exercised by this deliverable and becomes the reference for 1.5
2. **1.5 Governance queue overlay** — ships second because it is the simplest surface and validates the Phase 0 0.2 descope amendment lands cleanly
3. **1.2 Research state broadcaster** — ships third; depends on LRR UP-1 research-marker atomic-read pattern being exercised
4. **1.4 Live orchestration strip + `hsea_spawn_heartbeat()` helper** — ships fourth; introduces the first new `shared/` module from Phase 1
5. **1.3 Glass-box prompt rendering** — ships last; requires the daimonion writer extension which is the only edit outside the compositor + shared tree

Each deliverable is a separate PR (or a single multi-commit PR with reviewer pass per deliverable). Phase 1 closes when all 5 are merged, all 5 smoke tests pass, and operator visually confirms each surface.

---

## 9. End

This is the standalone per-phase design spec for HSEA Phase 1. It extracts the Phase 1 section of the HSEA epic spec (drop #60, §5) and incorporates:

- Drop #62 fold-in corrections (§3 ownership table + §5 unified phase sequence + §7 resource budget row 2)
- Operator batch ratification 2026-04-15T05:35Z (all 10 §10 questions closed)
- Resolution of the pre-existing HSEA epic spec inconsistency on the governance queue Cairo overlay (Phase 0 0.2 + Phase 1 1.5 duplication)

This spec is pre-staging. It does not open Phase 1. Phase 1 opens only when:

- LRR UP-0 + UP-1 + UP-3 are closed
- HSEA UP-2 (Phase 0) is closed and all 6 deliverables merged
- FDL-1 is deployed to a running compositor
- A session claims the phase via `hsea-state.yaml::phase_statuses[1].status: open`

Pre-staging authored by delta per the request "research and evaluate the best use of your time to push the work along" (second iteration, same request as the Phase 0 extraction).

— delta, 2026-04-15
