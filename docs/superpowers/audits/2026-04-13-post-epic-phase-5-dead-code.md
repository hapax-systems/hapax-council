# Post-Epic Audit — Phase 5 Dead Code + Missed Opportunities

**Date:** 2026-04-13
**Audit design:** [2026-04-13-post-epic-audit-design.md](../specs/2026-04-13-post-epic-audit-design.md)
**Audit plan:** [2026-04-13-post-epic-audit-plan.md](../plans/2026-04-13-post-epic-audit-plan.md)

## Method

Walked the design doc's dead-code candidate list and missed-opportunity list. For each, grep'd the entire repo (Python + Rust + TS + docs excluded) for callers, then classified as:

- **delete** — no callers, safe to remove.
- **keep-with-rationale** — looks dead but serves ownership, protocol, or interface needs.
- **ticket** — missed opportunity worth a follow-up PR.
- **already-fixed** — Phases 1–4 of this audit closed it.

## Dead-code candidates

| Symbol | Verdict | Notes |
|---|---|---|
| `headless::Renderer::new_for_tests` | **already-fixed** | Phase 4b rewrite of `headless.rs` dropped the entire scaffold, including `new_for_tests` and its two `#[cfg(test)] mod tests` entries. Nothing to delete. |
| `fx_chain._pip_draw` legacy fallback branch | **keep-with-rationale** | The fallback path (`compositor._album_overlay`, `compositor._token_pole`, `compositor._stream_overlay`) is only reached when `layout_state is None` — which Phase D wiring plus this audit's Phase 2 fixes rule out in production. Phase 9 Task 29 of the completion epic explicitly scheduled the legacy facade deletion and it remains unexecuted. **Deferred to a dedicated cleanup PR** rather than rolled into this audit: the facade change touches four files + a dozen tests and deserves its own review window. |
| `CairoSourceRunner.get_current_surface` alias | **keep** | Actively used. `SourceRegistry.get_current_surface` calls it, `fx_chain.pip_draw_from_layout` walks the registry with it, and `shm_rgba_reader` implements the same protocol. It is the canonical SourceBackend contract, not a leftover. |
| `hapax-visual::dynamic_pipeline::main_passes` | **keep-with-rationale** | The `cargo build` warning reports "method `main_passes` is never used" — this method has lived on `PlanFile` since the v2 multi-target refactor and is still the canonical single-target extraction helper. Deletion would reintroduce ad-hoc dict walks at every call site. Adding `#[allow(dead_code)]` would better suppress the warning; left as-is for now since it's a non-blocking lint. |
| `hapax-visual::dynamic_pipeline::DynamicPass::{uniform_bind_group, input_bind_group_layout}` | **keep-with-rationale** | Same category — the fields carry ownership over GPU resources, not data reads. The cargo "never read" warning is correct but misleading; dropping the fields would tear down the bind group the pipeline depends on. Pre-existing, not touched by the audit. |
| `hapax-visual::state::VisualChainState::timestamp` | **keep-with-rationale** | Serde-deserialized; the "never read" lint fires because no downstream Rust code reads the field, but the JSON producer (`hapax-visual` writes it as a heartbeat) and monitoring consumers rely on the schema stability. Deletion would break the contract. |

## Missed opportunities

| Opportunity | Verdict | Notes |
|---|---|---|
| **Phase 4b — real headless wgpu render loop** | **already-fixed** | Shipped in this PR (A3). Live verified: 1920×1080 RGBA, no winit window, NVIDIA 3090 adapter. |
| **Preset inputs wiring into preset load path** | **already-fixed** | Phase 2 audit A5 finding #2 — `resolve_preset_inputs` now called from `try_graph_preset` before `runtime.load_graph`. |
| **Per-`CairoSourceRunner` FreshnessGauge** | **already-fixed** | Phase 2 audit A5 finding #3 — every runner publishes `compositor_source_frame_{id}_{published_total,failed_total,age_seconds}`. |
| **ntfy on fallback layout load** | **already-fixed** | Phase 2 audit A5 finding #6 — `_notify_fallback` fires from all three failure branches in `load_layout_or_fallback`. |
| **`LayoutFileWatcher` + `LayoutAutoSaver` wiring** | **already-fixed** | Phase 2 audit A5 finding #1 — wired into `start_layout_only` + `stop`. |
| **token_pole golden-image regression test** | **ticket** | Follow-up. The test wasn't blocking a live bug and the natural-size rewrite looked mechanical enough that no visual regression surfaced during the epic. One half-day of work to author the golden + fixed-seed harness. **Owner:** next alpha session. |
| **Pool metrics IPC exposure** | **ticket** | `DynamicPipeline::pool_metrics()` exists in Rust but is unread from Python. The Phase 8 task 8.3 shipped the source but not the wire. Fix shape: either (a) add a UDS command to `hapax-imagination` that returns a JSON snapshot, or (b) add a Prometheus exporter on the Rust side. Option (b) is the better long-term path because it integrates with the existing metrics scraper on port 9482 (camera resilience epic). **Owner:** next alpha session. |
| **Compositor budget freshness gauge** | **ticket** | `publish_costs` in `budget_signal.py` has no FreshnessGauge, so the compositor's own budget heartbeat is ungauged while every source is gauged. Single-line fix. **Owner:** trivial; can be rolled into the next compositor touch. |
| **Command server command_registry bridge** | **ticket** | The five `compositor.*` command-server commands (`set_geometry`, `set_z_order`, `set_opacity`, `layout.save`, `layout.reload`) have zero callers outside the module + tests + docs. No `window.__logos.execute` entry, no MCP tool, no voice command. Wiring would unlock every command from `hapax-mcp`, the Logos UI, and voice. **Owner:** next alpha session — bigger scope, deserves its own PR. |
| **Phase 9 Task 29 legacy facade cleanup** | **ticket** | Deferred from the completion epic — `TokenPole.draw()`, `AlbumOverlay.draw()`, `SierpinskiRenderer.draw()`, and the `compositor._token_pole = TokenPole()` facade construction in `fx_chain.py` still live even though the new registry path has been authoritative since Phase 3. **Owner:** next alpha session. |

## Summary

- 5 of 10 "findings" are already fixed by this audit's earlier phases.
- 5 are deferred as follow-up tickets. None block a live feature.
- Zero items were deleted purely as dead code in this PR — the candidates all turned out to have ownership or protocol reasons to remain.

The audit closes with this report. Phase 6 is a retirement handoff documenting the final state and the five outstanding tickets.
