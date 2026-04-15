# HSEA Phase 1 — Visibility Surfaces — Plan

**Date:** 2026-04-15
**Author:** delta (pre-staging extraction from HSEA epic plan per the LRR-epic extraction pattern)
**Status:** DRAFT pre-staging — awaiting operator sign-off + cross-epic dependency resolution before Phase 1 open
**Spec reference:** `docs/superpowers/specs/2026-04-15-hsea-phase-1-visibility-surfaces-design.md`
**Epic reference:** `docs/superpowers/plans/2026-04-14-hsea-epic-plan.md`
**Branch target:** `feat/hsea-phase-1-visibility-surfaces`
**Cross-epic authority:** `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md` (drop #62) — §3 ownership + §5 unified sequence
**Unified phase mapping:** UP-4 Visibility Surfaces (depends on UP-1/UP-2/UP-3)

---

## 0. Preconditions (MUST verify before task 1.1)

- [ ] **LRR UP-0 closed.** Check `~/.cache/hapax/relay/lrr-state.yaml::phase_statuses[0].status == closed`.
- [ ] **LRR UP-1 (research registry) closed.** Check `~/.cache/hapax/relay/lrr-state.yaml::phase_statuses[1].status == closed`. Verify `scripts/research-registry.py` CLI exists, `/dev/shm/hapax-compositor/research-marker.json` is being written, and `~/hapax-state/research-registry/cond-*/condition.yaml` exists for at least one condition.
- [ ] **LRR UP-3 (archive instrument) closed.** Check `~/.cache/hapax/relay/lrr-state.yaml::phase_statuses[2].status == closed` (or UP-3 equivalent). Verify `SourceRegistry`/`OutputRouter` registration mechanism in `agents/studio_compositor/` is live, and `config/compositor-zones.yaml` exists.
- [ ] **HSEA UP-2 (Phase 0) closed.** Check `~/.cache/hapax/relay/hsea-state.yaml::phase_statuses[0].status == closed`. Verify all 6 Phase 0 deliverables merged:
  - [ ] `shared/prom_query.py` + `WatchedQueryPool` singleton accessible via `get_pool()`
  - [ ] `shared/governance_queue.py::GovernanceQueue` + `pending()` + `oldest_pending_age_s()` + `most_recent()` methods work
  - [ ] `shared/spawn_budget.py` exists (Phase 1 does not consume directly but its absence signals Phase 0 was not closed properly)
  - [ ] `scripts/promote-*.sh` exist and pass tests
  - [ ] `axioms/precedents/hsea/management-governance-drafting-as-content.yaml.draft` exists
  - [ ] `~/.cache/hapax/relay/hsea-state.yaml` + `research-stream-state.yaml` exist
- [ ] **FDL-1 deployed to a running compositor.** Verify:
  - [ ] `systemctl --user is-active studio-compositor` returns `active`
  - [ ] `curl -s 127.0.0.1:9482/metrics | grep compositor_uptime_seconds` returns a numeric value
  - [ ] `curl -s 127.0.0.1:9482/metrics | grep compositor_fd_count` returns a numeric value (FDL-1 observability addition; if absent, HUD will show "--" for fd count)
- [ ] **Drop #62 §10 ratifications in place.** All 10 questions closed as of 2026-04-15T05:35Z; no pending decisions block Phase 1.
- [ ] **Session claims the phase.** Write `~/.cache/hapax/relay/hsea-state.yaml::phase_statuses[1].status: open` + `current_phase: 1` + `current_phase_owner: <session>` + `current_phase_branch: feat/hsea-phase-1-visibility-surfaces` + `current_phase_opened_at: <now>`. Update `research-stream-state.yaml::unified_sequence[UP-4].status: open` + `owner: <session>`.

---

## 1. Deliverable 1.1 — HUD Cairo overlay (D1)

Executed FIRST because the `WatchedQueryPool` consumer pattern exercised here becomes the reference for 1.5.

### 1.1 Test scaffolding (TDD: tests first)

- [ ] Create `tests/studio_compositor/test_hud_source.py` with failing tests:
  - [ ] `test_render_happy_path` — fixture injects all ~10 metric values via a mock `WatchedQueryPool`; assert HudSource render callback produces Cairo draw ops (via a Cairo mock or counting `ctx.move_to/show_text` calls); verify at least 10 draw calls
  - [ ] `test_render_degraded_metric` — inject one metric with `InstantResult(ok=False)`; assert that field renders "--" and the overall status color flips to yellow
  - [ ] `test_render_stale_metric` — inject a metric whose `InstantResult.timestamp` is > 5 seconds ago; assert field renders "--"
  - [ ] `test_render_all_failing` — inject all metrics as `ok=False`; assert status color is red
  - [ ] `test_watched_query_registration` — verify HudSource's `__init__` registers ~10 queries against the shared pool at the 2 Hz tier; assert pool receives the correct query strings
  - [ ] `test_no_hardcoded_hex` — static assertion that the source file contains no `#[0-9a-fA-F]{6}` hex literals; colors must come from design-language tokens
  - [ ] `test_condition_id_from_marker` — verify condition_id is read from a fake research-marker.json fixture, not from prom_query (performance assertion)
  - [ ] `test_cairo_callback_safety` — mock Cairo context raises on any blocking I/O call during render; assert the HudSource render callback never blocks (reads from pool cache only)
- [ ] Run tests: all fail with `ModuleNotFoundError: agents.studio_compositor.hud_source`

### 1.2 Implementation

- [ ] Create `agents/studio_compositor/hud_source.py`:
  - [ ] Import `shared.prom_query.get_pool()` + `WatchedQuery` + design-language color tokens (from whatever module provides them in the compositor tree)
  - [ ] `class HudSource(CairoSource)`:
    - [ ] `__init__(zone: str = "top-left", refresh_tier: RefreshTier = 2.0)` — registers ~10 WatchedQueries with the shared pool; caches results in `self._cache: dict[str, InstantResult]`
    - [ ] `_on_metric_value(metric_name: str, result: InstantResult)` — callback stored per-query; updates cache
    - [ ] `render(ctx: cairo.Context, width: int, height: int) -> None` — reads from cache, lays out fields in a grid, uses design-language color tokens, never blocks
    - [ ] Stale detection: metric with `time.time() - result.timestamp > 5.0` renders "--"
  - [ ] Color helper: `_status_color(value: float | None, thresholds: tuple[float, float]) -> str` returns CSS variable name, NOT a hex literal
- [ ] Run tests: all pass

### 1.3 Zone registration

- [ ] Edit `config/compositor-zones.yaml` (LRR Phase 2 owned file): add `hud_top_left` zone entry with position + size + declared owner = `HudSource`
- [ ] If `overlay_zones.py::ZONES` needs a new entry, add it there too
- [ ] Register `HudSource` with `SourceRegistry` at compositor startup (edit whatever bootstrap code currently wires up existing Cairo sources)

### 1.4 Commit 1.1

- [ ] `uv run ruff check agents/studio_compositor/hud_source.py tests/studio_compositor/test_hud_source.py`
- [ ] `uv run ruff format` same files
- [ ] `uv run pyright agents/studio_compositor/hud_source.py`
- [ ] `git add agents/studio_compositor/hud_source.py tests/studio_compositor/test_hud_source.py config/compositor-zones.yaml`
- [ ] `git commit -m "feat(hsea-phase-1): 1.1 HUD Cairo overlay source + WatchedQueryPool consumer"`
- [ ] Update `hsea-state.yaml::phase_statuses[1].deliverables[1.1].status: completed`
- [ ] Push + open PR (separate per-deliverable) or accumulate on the phase branch
- [ ] **Restart compositor + visually confirm HUD renders** — do not proceed to 1.5 until the HUD is visible on the screen

---

## 2. Deliverable 1.5 — Governance queue overlay

Executed SECOND because it is the simplest surface and validates the Phase 0 0.2 descope amendment lands cleanly (Phase 0 spec + plan were edited in the same commit as this spec to remove the Cairo overlay from 0.2).

### 2.1 Phase 0 0.2 descope verification

- [ ] Verify that the HSEA Phase 0 spec at `docs/superpowers/specs/2026-04-15-hsea-phase-0-foundation-primitives-design.md` no longer lists the Cairo overlay in deliverable 0.2 scope (should be amended as part of this delta commit)
- [ ] Verify that the Phase 0 plan at `docs/superpowers/plans/2026-04-15-hsea-phase-0-foundation-primitives-plan.md` no longer has a Cairo overlay task under deliverable 0.2
- [ ] Verify `shared/governance_queue.py` (shipped by Phase 0 0.2) exports `GovernanceQueue` with `pending() -> list`, `oldest_pending_age_s() -> float | None`, `most_recent() -> GovernanceEntry | None` methods

### 2.2 Test scaffolding

- [ ] Create `tests/studio_compositor/test_governance_queue_source.py`:
  - [ ] `test_empty_queue_green_pill` — fixture returns 0 pending; assert pill renders with green design-language token
  - [ ] `test_recent_pending_green_pill` — fixture returns 2 pending, oldest 3 hours; assert green
  - [ ] `test_24h_yellow` — fixture returns 1 pending, oldest 25 hours; assert yellow
  - [ ] `test_72h_red` — fixture returns 1 pending, oldest 73 hours; assert red
  - [ ] `test_pill_text_format` — verify "N proposals awaiting review · oldest X" text where X is formatted as "Nh Nm" or "N days"
  - [ ] `test_most_recent_rendered` — verify `most_recent()` entry's title appears in the pill's secondary line (or tooltip in Logos)
  - [ ] `test_refresh_cadence_1hz` — mock timer; assert source re-reads queue state once per second
  - [ ] `test_no_hardcoded_hex`
- [ ] Run tests: fail (module missing)

### 2.3 Implementation

- [ ] Create `agents/studio_compositor/governance_queue_source.py`:
  - [ ] `class GovernanceQueueSource(CairoSource)`:
    - [ ] `__init__(zone: str = "bottom-center")` — constructs `GovernanceQueue` instance pointing at `~/hapax-state/governance-queue.jsonl`
    - [ ] `_refresh()` — reads `pending()` + `oldest_pending_age_s()` + `most_recent()`; cached in `self._state`
    - [ ] `render(ctx, w, h)` — renders pill using design-language tokens
    - [ ] 1 Hz refresh via `threading.Timer` (or the pool if the implementer prefers consistency)
  - [ ] Color helper maps `oldest_pending_age_s` to CSS variable: `< 86400 → green`, `< 259200 → yellow`, `else → red`

### 2.4 Command-registry wiring

- [ ] Edit `hapax-logos/src/lib/commands/governance.ts` (or create if it does not exist):
  - [ ] Register command `governance.queue.open` that opens `~/Documents/Personal/00-inbox/` via the existing file-opener command
- [ ] Verify command registers in `window.__logos` command list at runtime

### 2.5 Commit 1.5

- [ ] Lint + format + pyright
- [ ] `git add agents/studio_compositor/governance_queue_source.py tests/studio_compositor/test_governance_queue_source.py hapax-logos/src/lib/commands/governance.ts`
- [ ] `git commit -m "feat(hsea-phase-1): 1.5 governance queue overlay + command-registry wiring"`
- [ ] Update `hsea-state.yaml::phase_statuses[1].deliverables[1.5].status: completed`
- [ ] Restart compositor + verify pill renders; appends test governance queue entry + confirms pill updates

---

## 3. Deliverable 1.2 — Research state broadcaster (C1)

Executed THIRD because it depends on LRR UP-1 research-marker atomic-read pattern being exercised.

### 3.1 Test scaffolding

- [ ] Create `tests/studio_compositor/test_research_state_source.py`:
  - [ ] `test_render_happy_path` — fixture research-marker.json + condition.yaml + heartbeat.json + scores-today.jsonl + schedule.yaml; assert all 6 fields rendered
  - [ ] `test_stale_marker_shows_unknown` — marker mtime > 30s ago; assert "condition unknown — check registry" rendered
  - [ ] `test_missing_schedule_ok` — schedule.yaml absent; assert render still succeeds (schedule field shows "unscheduled")
  - [ ] `test_attribution_tier_color` — heartbeat.json has `attribution_tier: "direct"`; assert green. `"derived"` → yellow. `"orphaned"` → red.
  - [ ] `test_sierpinski_card_cadence` — mock Sierpinski renderer; assert `render_text_card()` called once per 5 minutes, not more often
  - [ ] `test_opacity_reflects_staleness` — marker 0s old → opacity 1.0. 15s old → ~0.65. 30s old → 0.3.
  - [ ] `test_no_hardcoded_hex`
- [ ] Run tests: fail

### 3.2 Implementation

- [ ] Create `agents/studio_compositor/research_state_source.py`:
  - [ ] `class ResearchStateSource(CairoSource)`:
    - [ ] `__init__(zone: str = "top-right", refresh_hz: float = 1.0)`
    - [ ] `_read_research_marker()` — atomic-read `/dev/shm/hapax-compositor/research-marker.json`, returns dict or None on failure
    - [ ] `_read_condition_yaml(condition_id)` — uses `shared/frontmatter.py` to parse `~/hapax-state/research-registry/cond-<id>/condition.yaml`
    - [ ] `_read_heartbeat()` — atomic-read `~/hapax-state/research-integrity/heartbeat.json`
    - [ ] `_read_scores_today(condition_id)` — tail-read `~/hapax-state/research-registry/cond-<id>/scores-today.jsonl`
    - [ ] `_read_schedule(condition_id)` — optional read of `schedule.yaml`
    - [ ] `render(ctx, w, h)` — composes the 6 fields into a vertically stacked layout
    - [ ] `_render_sierpinski_card()` — called every 5 min by internal timer; invokes `sierpinski_renderer.render_text_card()` with condition_id + score progress bar
- [ ] Run tests: all pass

### 3.3 Sierpinski renderer integration

- [ ] Verify `agents/studio_compositor/sierpinski_renderer.py::render_text_card()` exists; if absent, add a thin wrapper that renders a text card into a specified Sierpinski slot
- [ ] Declare a new Sierpinski slot for "research card" in whatever slot registry the renderer uses; do NOT repurpose existing slots

### 3.4 Commit 1.2

- [ ] Lint + format + pyright
- [ ] `git add agents/studio_compositor/research_state_source.py tests/studio_compositor/test_research_state_source.py`
- [ ] `git commit -m "feat(hsea-phase-1): 1.2 research state broadcaster + Sierpinski card slot"`
- [ ] Update `hsea-state.yaml::phase_statuses[1].deliverables[1.2].status: completed`
- [ ] Restart compositor + verify overlay + verify Sierpinski card appears on next 5-min tick

---

## 4. Deliverable 1.4 — Live orchestration strip + `hsea_spawn_heartbeat()` helper

Executed FOURTH because it introduces the first new `shared/` module from Phase 1 and requires both the overlay source + the writer helper.

### 4.1 `shared/hsea_orchestration.py` — heartbeat helper

- [ ] Create `tests/shared/test_hsea_orchestration.py`:
  - [ ] `test_first_call_appends` — call `hsea_spawn_heartbeat("abc", "test-spawn", "running", 2.5)`; assert one line in `/tmp/active.jsonl` fixture
  - [ ] `test_update_in_place` — two calls with same id, different status; assert reader sees final status only (dedup logic)
  - [ ] `test_terminal_transition` — status=done; assert entry marked terminal with timestamp
  - [ ] `test_reap_after_30s_terminal` — manually advance time 31s; assert entry filtered out by reader
  - [ ] `test_concurrent_writers_safe` — two threads calling heartbeat simultaneously; assert no interleaved lines (use `fcntl.flock` like governance queue does)
  - [ ] `test_size_guard_ntfy` — inject a 2MB active.jsonl; assert heartbeat truncates + calls `shared.notify.send_notification`
- [ ] Create `shared/hsea_orchestration.py`:
  - [ ] `@dataclass class OrchestrationEntry(id, label, started_at, status, latency_estimate, parent_spawn_id, model_tier, is_terminal, terminal_at)`
  - [ ] `def hsea_spawn_heartbeat(id, label, status, latency_estimate, parent_spawn_id=None, model_tier=None) -> None`
  - [ ] `def read_active_entries() -> list[OrchestrationEntry]` — reads the ledger, applies 30s terminal filter, returns non-terminal + recently-terminal entries
  - [ ] `fcntl.flock(LOCK_EX)` + `O_APPEND` for writes (same pattern as governance queue)
  - [ ] Size guard: if ledger > 1 MB, truncate to last 100 lines + ntfy
- [ ] Run tests: pass

### 4.2 `OrchestrationStripSource` — overlay

- [ ] Create `tests/studio_compositor/test_orchestration_strip_source.py`:
  - [ ] `test_render_empty` — no active entries; strip renders placeholder text "no active spawns"
  - [ ] `test_render_one_swimlane` — one active entry; one swimlane row rendered
  - [ ] `test_render_three_swimlanes` — 3 entries; 3 rows; elapsed time bars proportional to `started_at`
  - [ ] `test_status_icon_mapping` — `running` → spinner icon, `done` → check icon, `failed` → x icon
  - [ ] `test_filter_terminal_after_30s` — entry with `is_terminal: True, terminal_at: now-31s`; not rendered
  - [ ] `test_refresh_2hz` — mock timer; assert re-read cadence
- [ ] Create `agents/studio_compositor/orchestration_strip_source.py`:
  - [ ] `class OrchestrationStripSource(CairoSource)`:
    - [ ] `__init__(zone: str = "lower-content")`
    - [ ] `_refresh()` calls `shared.hsea_orchestration.read_active_entries()`
    - [ ] `render()` draws horizontal swimlanes; each lane = one entry; width proportional to elapsed time
- [ ] Run tests: pass

### 4.3 Reap timer systemd unit

- [ ] Create `systemd/user/hapax-orchestration-reap.service`:
  - [ ] `Type=oneshot`
  - [ ] `ExecStart=uv run python -c "from shared.hsea_orchestration import reap_stale; reap_stale()"`
- [ ] Create `systemd/user/hapax-orchestration-reap.timer`:
  - [ ] `OnBootSec=1min`
  - [ ] `OnUnitActiveSec=1min`
- [ ] Add `reap_stale()` function to `shared/hsea_orchestration.py` — rewrites the ledger keeping only non-terminal or recent-terminal entries

### 4.4 Commit 1.4

- [ ] Lint + format + pyright
- [ ] `git add shared/hsea_orchestration.py tests/shared/test_hsea_orchestration.py agents/studio_compositor/orchestration_strip_source.py tests/studio_compositor/test_orchestration_strip_source.py systemd/user/hapax-orchestration-reap.{timer,service}`
- [ ] `git commit -m "feat(hsea-phase-1): 1.4 orchestration strip + hsea_spawn_heartbeat helper + reap timer"`
- [ ] Update `hsea-state.yaml::phase_statuses[1].deliverables[1.4].status: completed`
- [ ] `systemctl --user daemon-reload && systemctl --user enable --now hapax-orchestration-reap.timer`
- [ ] Restart compositor + run the smoke test (stub spawn heartbeats 3 times); verify strip renders, updates, removes

---

## 5. Deliverable 1.3 — Glass-box prompt rendering (F1)

Executed LAST because it requires the daimonion writer extension, which is the only edit outside the compositor + shared tree.

### 5.1 Daimonion snapshot writer extension

- [ ] Locate `_build_unified_prompt()` in the daimonion tree — likely `agents/hapax_daimonion/prompt_builder.py` or `agents/hapax_daimonion/persona.py`. Verify exact file at open time.
- [ ] Add `_write_prompt_glass_snapshot(prompt_text, last_8_reactions, extreme_dims, condition_id)`:
  - [ ] Writes JSON to `/dev/shm/hapax-compositor/prompt-glass.json` via `shared.atomic_io.atomic_write_json`
  - [ ] Schema: `{built_at, prompt_text, active_section, last_8_reactions: [{id, in_context}], extreme_dims: [{name, value}], condition_id}`
- [ ] Call `_write_prompt_glass_snapshot()` at the end of `_build_unified_prompt()` (after all section assembly is done)
- [ ] Tests: `tests/hapax_daimonion/test_prompt_glass_snapshot.py`
  - [ ] `test_snapshot_written_after_build` — call `_build_unified_prompt()`; assert file exists + parseable JSON
  - [ ] `test_atomic_write_no_partial` — simulate interrupted write; verify no partial JSON visible

### 5.2 `PromptGlassSource` — overlay

- [ ] Create `tests/studio_compositor/test_prompt_glass_source.py`:
  - [ ] `test_render_happy_path` — fixture prompt-glass.json; assert all fields rendered
  - [ ] `test_truncation` — prompt_text > 2000 chars; assert truncated to active_section
  - [ ] `test_in_context_highlighting` — reactions where `in_context: true` visibly distinct from `in_context: false`
  - [ ] `test_extreme_dim_color_coding` — each of the 9 dimensions maps to a specific CSS color var when extreme
  - [ ] `test_refresh_per_tick` — mock daimonion tick at 8s; assert PromptGlassSource re-reads snapshot at that cadence
- [ ] Create `agents/studio_compositor/prompt_glass_source.py`:
  - [ ] `class PromptGlassSource(CairoSource)`:
    - [ ] `__init__(zone: str = "left-middle")`
    - [ ] `_read_snapshot()` — atomic-read `/dev/shm/hapax-compositor/prompt-glass.json`
    - [ ] `render()` — lays out persona header + reactions window + extreme dims + condition_id band
    - [ ] 8s refresh (or simply re-read every render call since Cairo is triggered by the compositor pipeline at its own cadence)

### 5.3 Commit 1.3

- [ ] Lint + format + pyright
- [ ] `git add agents/hapax_daimonion/prompt_builder.py agents/studio_compositor/prompt_glass_source.py tests/hapax_daimonion/test_prompt_glass_snapshot.py tests/studio_compositor/test_prompt_glass_source.py`
- [ ] `git commit -m "feat(hsea-phase-1): 1.3 glass-box prompt rendering + daimonion snapshot writer"`
- [ ] Update `hsea-state.yaml::phase_statuses[1].deliverables[1.3].status: completed`
- [ ] Restart daimonion + compositor; verify overlay updates per 8s tick

---

## 6. Phase 1 close

All 5 deliverables complete. Final steps:

### 6.1 Smoke tests

- [ ] **HUD smoke test:** compositor running, all ~10 metrics show live values. FD count bar visible. Force degraded state on one metric (e.g., kill Prometheus for 10s) and verify color flips to yellow.
- [ ] **Research state smoke test:** update research-marker.json with a new condition_id; verify the overlay updates within 1 second. Wait 5 minutes; verify Sierpinski card renders.
- [ ] **Prompt glass smoke test:** daimonion writes a snapshot; overlay updates within the next 8s tick. Verify last-8 reactions + extreme dims render.
- [ ] **Orchestration strip smoke test:** stub agent calls `hsea_spawn_heartbeat("test", "smoke", "running", 1.0)` three times over 10 seconds, each with different status (running → running → done). Verify strip renders, updates, and removes after 30s terminal.
- [ ] **Governance queue overlay smoke test:** append a test entry to `~/hapax-state/governance-queue.jsonl` via `GovernanceQueue.append(...)`; verify pill updates within 1 second. Inject a 25h-old pending entry; verify pill flips to yellow. Inject a 73h-old pending entry; verify pill flips to red.

### 6.2 Handoff doc

- [ ] Write `docs/superpowers/handoff/2026-04-15-hsea-phase-1-complete.md`:
  - [ ] Summary of what shipped (5 deliverables)
  - [ ] Links to PRs/commits for each deliverable
  - [ ] Screenshot evidence for each of the 5 surfaces (captured via compositor + screenshot tool; attach to the handoff via `docs/superpowers/handoff/images/` or equivalent)
  - [ ] Known issues / deferred items
  - [ ] Next phase (Phase 2 — Core Director Activities) preconditions

### 6.3 State file close-out

- [ ] Edit `~/.cache/hapax/relay/hsea-state.yaml`:
  - [ ] `phase_statuses[1].status: closed`
  - [ ] `phase_statuses[1].closed_at: <now>`
  - [ ] `phase_statuses[1].handoff_path: docs/superpowers/handoff/2026-04-15-hsea-phase-1-complete.md`
  - [ ] `phase_statuses[1].deliverables[*].status: completed` (all 5)
  - [ ] `last_completed_phase: 1`
  - [ ] `last_completed_at: <now>`
  - [ ] `current_phase: null` (or 2 if Phase 2 is about to open)
  - [ ] `overall_health: green`
- [ ] Request operator update to `~/.cache/hapax/relay/research-stream-state.yaml::unified_sequence[UP-4]`:
  - [ ] `status: closed`
  - [ ] `owner: null`
  - [ ] `last_updated_at: <now>`
  - [ ] (Per Q8 ratification, the shared index is operator-only-edits-after-initial, so this edit goes through a governance-queue request if Phase 0 0.2 has landed, or via direct operator edit)

### 6.4 Final verification

- [ ] `git log --oneline` shows 5 `feat(hsea-phase-1): …` commits
- [ ] All 5 overlays visually confirmed by operator (screenshots in handoff)
- [ ] All 5 smoke tests pass in a single session
- [ ] Fresh shell shows `HSEA: Phase 1 · status=closed` in session-context
- [ ] Inflection written to peer sessions announcing Phase 1 closure + Phase 2 open readiness

---

## 7. Cross-epic coordination (canonical references)

This plan defers to drop #62 §3 (ownership) + §5 (unified sequence) + §7 (resource budget row 2) for all cross-epic questions. Specifically:

- **LRR owns research-registry paths** (Phase 1 reads only): condition.yaml, research-marker.json, heartbeat.json, scores-today.jsonl, schedule.yaml.
- **LRR owns SourceRegistry + compositor-zones.yaml** (Phase 2 / UP-3). HSEA Phase 1 registers its 5 sources using this mechanism.
- **HSEA owns new surface code** (Phase 1). LRR Phase 8's separate surfaces (objective-overlay, studio view tile, terminal capture, PR/CI status) are distinct and kept distinct by naming.
- **HSEA Phase 4 Cluster I full rescoping (Q3 ratification)** does not affect Phase 1; the HUD and other surfaces are independent of the rescoped drafters.
- **Governance queue Cairo overlay descope from Phase 0 0.2** is part of this spec's same-commit amendment of the Phase 0 docs.

---

## 8. End

This is the standalone per-phase plan for HSEA Phase 1. It is pre-staging — the plan is not executed until the phase opens per the preconditions in §0. The companion spec lives at `docs/superpowers/specs/2026-04-15-hsea-phase-1-visibility-surfaces-design.md`.

Pre-staging authored by delta.

— delta, 2026-04-15
