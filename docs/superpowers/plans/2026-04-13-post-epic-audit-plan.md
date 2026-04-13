# Post-Epic Audit — Execution Plan

**Status:** plan
**Date:** 2026-04-13
**Design:** [2026-04-13-post-epic-audit-design.md](../specs/2026-04-13-post-epic-audit-design.md)
**Branch:** `feat/post-epic-layout-fix` (shared with A1 pending follow-ups)

## Phase layout

Five execution phases following the design's five dimensions, plus two bookend phases:

0. **A1 layout fix** (DONE — PR #749, landed in this plan's parent branch)
1. **Completion verification** (read-only, fast)
2. **Correctness + invariants** (read-only, moderate)
3. **Robustness + leaks** (live run, expensive — includes ALPHA-FINDING-1)
4. **Edge cases** (read + light testing)
5. **Dead code + missed opportunities** (read + delete / file tickets)
6. **Retirement + handoff** (write handoff, close relay slot)

One PR per phase unless a phase produces zero change, in which case the phase lands as part of Phase 6's retirement doc.

## Phase 0 — A1 layout fix (DONE)

- [x] Register `StreamOverlayCairoSource` in `cairo_sources/__init__.py`
- [x] Update `config/compositor-layouts/default.json` with four-quadrant operator defaults
- [x] Mirror in `_FALLBACK_LAYOUT`
- [x] Update tests (`test_default_layout_loading.py`, `test_compositor_wiring.py`)
- [x] Push branch `feat/post-epic-layout-fix`
- [x] Open PR #749
- [ ] Wait for CI green, merge

## Phase 1 — Completion verification

**Goal:** independently verify all 15 completion-epic ACs against shipped code.

### Tasks

1. Extract the 11 parent ACs + 4 Phase-8 ACs from `2026-04-13-reverie-source-registry-completion-plan.md`.
2. For each AC, grep/read the implementing symbols on `main`.
3. Classify each as `complete`, `stub`, or `missing`.
4. Write `docs/superpowers/audits/2026-04-13-post-epic-phase-1-completion.md` with the table and one row per AC.
5. File a tracking issue (or add to the plan's "follow-ups" section) for every `stub` and `missing`.

### Known in-advance findings

- **AC-4 (headless reverie render loop)** — `headless.rs::Renderer` is a stub. This will mark `stub`.
- **AC-7 (preset inputs)** — schema + resolver shipped but not wired into the compiler's main entrypoint. This will mark `complete-but-unwired`, which counts as `stub` for audit purposes.

### Exit criteria

- Phase 1 report committed.
- Every non-complete AC has a next-step ticket/issue.
- Decision: do we open Phase 4b here in the audit, or punt it to a separate epic?

## Phase 2 — Correctness + invariants

**Goal:** verify seven invariants listed in the design doc.

### Tasks

For each invariant, produce a small read-through or targeted test:

1. **LayoutState lock discipline** — read every `layout_state.` call site under `agents/studio_compositor/` and `hapax-logos/src-tauri/`. Confirm none escape the lock.
2. **SourceRegistry idempotency** — verify `test_idempotent_when_called_twice` also checks that no new `CairoSourceRunner` thread was spawned on the second call (it currently only checks identity of the registry object). Extend the test.
3. **FreshnessGauge monotonicity** — write a property test that `mark_published()` then `age_seconds()` is always ≥ 0; `mark_failed()` then `mark_published()` resets the clock.
4. **CairoSourceRunner backpressure** — read `_push_buffer_to_appsrc` and verify it handles `Gst.FlowReturn.FLUSHING` by dropping, not retrying.
5. **Layout parity** — verify `test_fallback_layout_parses_to_same_shape_as_default_json` covers the new stream_overlay assignment. Already confirmed by A1's test updates — mark checked.
6. **Default layout path via symlink** — run `ln -s` on the repo and invoke the test from the symlinked path; confirm `.resolve()` unwraps it.
7. **PresetInput pad name collisions** — write a unit test for `resolve_preset_inputs` asserting two inputs with the same `as_` raises `PresetLoadError`.

### Exit criteria

- All seven items ticked.
- Each extended/new test committed.
- Any violation filed as its own fix PR.

## Phase 3 — Robustness + resource leaks

**Goal:** confirm or refute ALPHA-FINDING-1 (50MB/min RSS growth), plus robustness checks.

### 3a — ALPHA-FINDING-1 investigation

1. Start the compositor on main with the merged A1 layout.
2. Capture `ps -o rss`, `pmap`, and GStreamer's `GST_DEBUG=GST_TRACER:7` with `meminfo` + `refcount` for 10 minutes.
3. Parallel: pull `DynamicPipeline::pool_metrics()` every 30s via a one-shot UDS client (write a quick probe script — reverie side).
4. Diff allocator high-water marks by category (Python heap, GStreamer buffers, GL textures, Cairo surfaces).
5. File a finding doc at `docs/superpowers/audits/2026-04-13-alpha-finding-1-memory-leak.md` with:
   - Observed growth rate
   - Primary allocator
   - Root cause (if found)
   - Fix PR or next diagnostic step

### 3b — Failure mode coverage

For each failure mode in the design doc's Phase 3 list, write either a targeted test or a one-paragraph rationale in the finding doc:

1. `CairoSourceRunner` render exception — compositor survives and retries?
2. Missing `params` key — construction error caught and source skipped?
3. Cairo class constructor raises — same?
4. `external_rgba` shm path missing — logs and skips?
5. Command server double-bind on the same UDS path — fails loud?
6. `LayoutAutoSaver` flood — debounce holds, no race with watcher?

### Exit criteria

- Leak root cause documented.
- Every failure mode either test-covered or explicitly marked as "system-accepted failure" in the finding doc.
- If a fix is feasible in this session, it ships as a PR; otherwise a retirement-handoff entry explains the state.

## Phase 4 — Edge cases

**Goal:** close the edge-case list from the design.

### Tasks

1. Write `tests/studio_compositor/test_edge_cases.py` covering:
   - Layout with zero sources
   - Layout with an assignment referencing an undeclared source
   - Overlapping surfaces (identical `z_order`)
   - `shm_path` shorter than `natural_w × natural_h × 4`
   - Unicode in `class_name`
2. Default layout path from `/tmp` — run a manual check, pin with a test if feasible.
3. Preset inputs with reserved `as_` names — extend Phase 2 item 7's test.

### Exit criteria

- All edge cases either tested or documented-as-excluded with a one-line comment at the relevant site.

## Phase 5 — Dead code + missed opportunities

**Goal:** prune and document.

### Tasks

1. Audit dead-code candidates:
   - `headless.rs::new_for_tests` — delete or write a test that uses it.
   - `fx_chain._pip_draw` legacy branch — delete if unreachable.
   - `CairoSourceRunner.get_current_surface` alias — grep call sites; delete if unused.
   - Unwired command server commands — grep UI/CLI/MCP for each.
2. For each missed opportunity:
   - **Phase 4b** — the real headless wgpu render loop. If we're not shipping it here, file a ticket with the design sketch (GpuContext::new_headless, owned wgpu::Texture, staging buffer, shm write, systemd env flip).
   - **Preset inputs wiring** — ticket for wiring `resolve_preset_inputs` into the compositor boot path.
   - **Compositor budget freshness gauge** — ticket for gauging `publish_costs`.
   - **Pool metrics IPC** — ticket for exporting `DynamicPipeline::pool_metrics()` over UDS.
3. Delete or ticket each item.

### Exit criteria

- Dead code removed on a PR, or a one-line comment saying why it stays.
- Every missed opportunity has a tracked follow-up.

## Phase 6 — Retirement + handoff

**Goal:** close the audit and hand the remaining backlog off.

### Tasks

1. Write `docs/superpowers/handoff/2026-04-13-alpha-post-epic-audit-retirement.md` summarizing:
   - PRs shipped (Phases 0–5)
   - Findings closed
   - Findings still open (and their next-step tickets)
   - Phase 4b status
2. Update `.cache/hapax/relay/alpha.yaml` with post-audit state.
3. Close the audit in `MEMORY.md` if appropriate.

### Exit criteria

- Handoff written.
- Relay updated.
- Every audit finding has a known home (PR merged, ticket filed, or explicit excluded note).

## Execution rules

- **Serial phases.** Don't start Phase 2 until Phase 1 report is committed. Don't start Phase 3 until Phase 2's extended tests are green.
- **One PR per phase minimum.** Phases that produce zero changes land as part of Phase 6.
- **Hook discipline.** Work continues in `feat/post-epic-layout-fix` until A1 merges, then each phase gets its own branch following the no-stale-branches rule.
- **Phase 3 requires main worktree.** Don't try to profile the compositor from the feature branch — `rebuild-service.sh` will refuse. Wait for A1 merge, then profile from main.
- **Each phase writes its report before closing.** The reports live under `docs/superpowers/audits/` and become the audit's durable record.
