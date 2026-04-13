# Alpha Retirement — Post-Epic Audit + Fix Bundle

**Session:** alpha (post-epic-fixes worktree)
**Date:** 2026-04-13
**PR:** #749 — `feat(compositor+imagination): post-epic fixes — A1 default layout + A3 reverie headless + audit plan`
**Branch:** `feat/post-epic-layout-fix`

## What shipped

Fourteen commits across one PR, addressing two operator-reported live bugs and five audit-discovered wiring gaps.

### Operator-reported fixes

- **A1** — Default layout four-quadrant operator assignments (reverie UR, Vitruvian UL, album LL, stream_overlay LR). Registered `StreamOverlayCairoSource`, updated `default.json`, mirrored in `_FALLBACK_LAYOUT`, updated tests.
- **A3 / Phase 4b** — Real headless wgpu render loop. `headless::Renderer` now owns a private wgpu device, offscreen Rgba8UnormSrgb target, and the same `DynamicPipeline` + `ContentSourceManager` + `StateReader` triple as the winit path. `HAPAX_IMAGINATION_HEADLESS=1` flipped on both copies of the systemd unit. Live verified against NVIDIA 3090: 1920×1080 RGBA (8,294,400 bytes) flowing to the reverie SHM path, no winit window.

### Audit

- **A2** — Post-epic audit design (5 dimensions) + 7-phase execution plan. `docs/superpowers/specs/2026-04-13-post-epic-audit-design.md` + `docs/superpowers/plans/2026-04-13-post-epic-audit-plan.md`.
- **A4 / Phase 1** — Independent completion verification of all 15 completion-epic ACs. `docs/superpowers/audits/2026-04-13-post-epic-phase-1-completion.md`. Findings: 9 complete, 3 unwired (file-watch reload, `resolve_preset_inputs`, per-cairo FreshnessGauge), 2 stubs (AC-3 → fixed by A3, AC-11 → deferred), 1 missing (reverie_pool_* IPC → deferred).
- **A5 / Phase 2** — Correctness fixes for four of six follow-up tickets from the Phase 1 report:
  1. `LayoutAutoSaver` + `LayoutFileWatcher` wired into `StudioCompositor` (AC-5 now true on main).
  2. `resolve_preset_inputs` wired into `try_graph_preset` (AC-7 now true on main).
  3. Per-`CairoSourceRunner` `FreshnessGauge` (AC-10 now true on main for every registered source).
  4. `ntfy` on fallback layout load (AC-8 now true on main).
  Each with a regression pin.
- **A7 / Phase 4** — Ten edge-case tests covering zero-source layouts, overlapping z_orders, unicode IDs, symlinked default paths, preset-input alias collisions, and broken-backend boot. `tests/studio_compositor/test_edge_cases.py`.
- **A8 / Phase 5** — Dead-code + missed-opportunities report. `docs/superpowers/audits/2026-04-13-post-epic-phase-5-dead-code.md`. Zero deletions (every candidate turned out to have ownership or protocol reasons to stay); five items filed as follow-up tickets.

## Open follow-ups

In audit-priority order. The operator picks the order to execute.

1. **ALPHA-FINDING-1 — compositor memory leak (~50MB/min RSS).** Not investigated in this PR. Phase 3 of the audit plan specified a live-profile session from the main worktree; blocked on A1+A3 landing first. Next session should execute Phase 3.
2. **Phase 9 Task 29 legacy facade cleanup** — delete `TokenPole.draw()`, `AlbumOverlay.draw()`, `SierpinskiRenderer.draw()` and the `compositor._token_pole = TokenPole()` construction sites in `fx_chain.py`. Deferred from the completion epic; tracked here.
3. **Pool metrics IPC exposure** — wire `DynamicPipeline::pool_metrics()` through a Prometheus exporter on the Rust side (port 9482, reusing the camera-resilience metrics server). Closes AC-13.
4. **token_pole golden-image regression test** — fixed-seed render + cairo `write_to_png` golden, pinned by a per-pixel delta ≤ 2 check. Closes AC-11.
5. **Command server → command_registry bridge** — the five `compositor.*` commands are unreachable from `window.__logos`, MCP, or voice. Wiring them unlocks runtime layout control from every surface. Own PR due to scope.
6. **Compositor budget freshness gauge** — one-liner to gauge `publish_costs` in `budget_signal.py`. Trivial; roll into next compositor touch.

## Retirement state

- **Relay** (`alpha.yaml` under the session relay cache) — **to update when PR merges**: status → `RETIRED — post-epic audit + fix bundle shipped`, `session_status` → idle, `next_session_directives` → "execute audit Phase 3 from main worktree (ALPHA-FINDING-1 leak investigation); follow-up tickets in retirement handoff."
- **Worktree** (post-epic-fixes) — retains branch `feat/post-epic-layout-fix` until merge; delete with `git worktree remove` after merge.
- **Deploy** — `rebuild-services.timer` will pick up the new systemd unit + rebuilt binary after merge; verify with `systemctl --user show hapax-imagination.service -p Environment` showing `HAPAX_IMAGINATION_HEADLESS=1`, then watch for the winit window to disappear and the reverie SHM frame counter to keep advancing.

## Counts

- **Lines added:** ~1,100 (including audit docs, fix code, tests).
- **Tests added:** 22 (10 edge-case + 12 regression pins across four audit findings).
- **Live test runs:** 1 (15-second headless binary run with env var).
- **ACs reverified:** 15.
- **Follow-up tickets filed:** 6.
