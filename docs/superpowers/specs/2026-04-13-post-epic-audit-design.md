# Post-Epic Audit — Reverie Source Registry Completion

**Status:** design
**Date:** 2026-04-13
**Author:** alpha (post-epic-fixes session)
**Supersedes:** nothing — companion to `2026-04-13-reverie-source-registry-completion-design.md`
**Depends on:** PR #736 (epic umbrella), PRs #737–#748 (Phases 1–9), PR #749 (A1 layout fix)

## Why this audit

The Reverie Source Registry Completion epic landed in 9 phases over a single autonomous session. Phase 9 produced an acceptance-criteria sweep, but that sweep walked the ACs as written — it did not independently re-read the shipped code for *the things the ACs don't say*. The operator flagged two issues during the retirement window that weren't in the epic scope:

1. **Default layout didn't match the operator spec.** Reverie was upper-right, but token_pole, album, and stream_overlay were not assigned to their four-quadrant defaults. A1 (PR #749) fixed this.
2. **Reverie is still spawning outside Logos.** Phase 4a shipped a scaffold-only `headless` module with a stub `Renderer`. The *actual* headless wgpu render path was deferred to Phase 4b and never executed. The systemd unit still launches reverie as a standalone surface.

These slipped because Phase 9's sweep asked "did each AC get a PR?" not "does the shipped code do what the AC *meant*?" This audit closes that gap systematically, then keeps going — covering correctness invariants, robustness under failure, edge cases the tests don't exercise, dead code, and missed opportunities the epic's scope excluded.

## Scope

In scope:

- All code shipped under the completion epic (PRs #736–#748): `compositor.py`, `layout_state.py`, `source_registry.py`, `cairo_source.py`, `fx_chain.py`, `cairo_sources/*`, `token_pole.py`, `album_overlay.py`, `sierpinski_renderer.py`, `stream_overlay.py`, `layout_persistence.py`, `command_server.py`, `effect_graph/types.py`, `effect_graph/compiler.py`, `shared/freshness_gauge.py`, `agents/imagination_loop.py`, `scripts/verify_reverberation_cadence.py`, `hapax-logos/src-imagination/src/headless.rs`.
- Adjacent: `cairo_sources/__init__.py` (registration), `config/compositor-layouts/default.json` (the thing we just fixed), `_FALLBACK_LAYOUT` (same).
- Two pre-existing ALPHA findings parked during the epic: **ALPHA-FINDING-1 compositor memory leak ~50MB/min**, and **ALPHA-FINDING-3 reverie spawning outside logos**.

Out of scope:

- The visual chain GPU bridge (`visual_chain.compute_param_deltas` → `uniforms.json` → `dynamic_pipeline.rs`). This was stable before the epic and untouched by it.
- The compositor unification epic itself (closed 2026-04-12).
- Bayesian presence detection, IR perception, voice FX chain, SDLC pipeline.
- Anything governed by a separate design doc (orientation panel, command registry).

## Audit dimensions

Each dimension gets its own phase with its own criteria. The phases are ordered so cheap/mechanical checks run first and expensive/invasive checks run after the cheap ones have pruned the surface.

### 1. Completion verification

**Question:** does each of the 11 parent acceptance criteria + 4 Phase-8 criteria from `2026-04-13-reverie-source-registry-completion-plan.md` have working code on `main`?

**Method:** For every AC, locate the implementing symbols, read them, and verify the stated behavior. Do NOT trust the Phase 9 sweep — re-walk independently. Any "shipped as stub" findings (like Phase 4a's `Renderer`) are completion failures, not scope deferrals.

**Exit criteria:** a table of AC → symbol → verdict (complete / stub / missing). Every "stub" and "missing" row becomes a follow-up ticket.

### 2. Correctness and invariants

**Question:** given working code, does it uphold the invariants the system depends on?

**Key invariants to check:**

- **LayoutState lock discipline.** Every reader/writer goes through the RLock. No caller stashes a reference to `layout_state._layout` outside the lock scope. The command server's `reload_callback` is the most likely violator.
- **SourceRegistry idempotency.** `start_layout_only()` must be safe to call twice without re-registering sources, re-allocating appsrcs, or leaking `CairoSourceRunner` threads. The unit test covers ID sets but not runner lifecycle.
- **FreshnessGauge metric contract.** `mark_published()` must be monotonic on a single gauge and never decrement `age_seconds()` below zero. No caller should conflate `mark_failed()` with `mark_published()` (regression trap: "I handled the error, therefore the producer is healthy").
- **CairoSourceRunner appsrc cadence.** `_render_one_frame` must not block on GStreamer backpressure; if `gst_appsrc.push_buffer()` returns `GST_FLOW_FLUSHING`, the runner drops the frame rather than wedging.
- **Layout JSON ⇄ fallback parity.** `_FALLBACK_LAYOUT` must be structurally identical to `config/compositor-layouts/default.json`. Already pinned by `test_fallback_layout_parses_to_same_shape_as_default_json` — verify the test hasn't rotted.
- **Default layout path resolution.** `_DEFAULT_LAYOUT_PATH` must be CWD-independent. PR #748 fixed this via `Path(__file__).resolve().parents[2]`. Re-verify on a case where `__file__` resolves through a symlink.
- **PresetInput pad name collisions.** `resolve_preset_inputs` must reject two inputs with the same `as_` value — two nodes cannot claim the same pad name.

**Exit criteria:** a list of verified invariants, a list of violated invariants, and a follow-up ticket for each violation.

### 3. Robustness + resource leaks

**Question:** what happens under partial failure, resource exhaustion, and the ALPHA-FINDING-1 memory leak?

**Subject areas:**

- **ALPHA-FINDING-1: compositor RSS grows ~50MB/min.** The leak existed before the epic and was parked. This phase investigates it. Hypotheses in decreasing likelihood:
  1. `TransientTexturePool` allocations not returning to the pool on surface resize (we re-key on `(w, h, format)` so old bucket entries are abandoned).
  2. Cairo surface cache in `CairoSourceRunner` doubling rather than replacing on render.
  3. `gst_appsrc` buffer queue unbounded (`max-bytes=0` default) if downstream stalls.
  4. GStreamer GL context texture leak — pool metrics show reuse ratio, but GL textures are on a separate allocator.
  5. Python-side `_FALLBACK_LAYOUT` pydantic model copied per `start_layout_only()` call when the file read fails — unlikely to be the hot path but easy to verify.
  6. `FreshnessGauge.mark_published()` holding Prometheus sample objects in a CollectorRegistry that never rotates.
- **Cairo source failure recovery.** A `CairoSourceRunner` that raises on its render thread — does the compositor log, drop the source, and keep rendering? Does the registry re-attempt later?
- **Broken backend at startup.** `test_continues_past_broken_source_backend` covers this for the `class_name` miss. Re-verify for (a) missing `params` key, (b) cairo class constructor raising, (c) shm path for `external_rgba` pointing at a nonexistent file.
- **Command server UDS path collision.** Two compositors on the same socket path — does the second fail loudly or silently clobber?
- **LayoutAutoSaver flood protection.** Pounding `layout_state.set()` in a tight loop — does the debounce hold? Does the `mark_self_write` race with the file watcher?

**Exit criteria:** leak hypothesis refuted or confirmed with a patch, every failure mode producing either a fix or a tracked-defect ticket.

### 4. Edge cases

**Question:** what inputs does the shipped code silently mishandle?

- **Layout with zero sources.** Does `start_layout_only()` boot a compositor with no cairo overlays? Does `pip_draw_from_layout` noop gracefully?
- **Layout with a source referenced by an assignment but not declared in `sources`.** The pydantic model allows this; the compositor must catch it.
- **Layout with overlapping surfaces (same z_order).** Deterministic painter order required.
- **`shm_path` file smaller than `natural_w * natural_h * 4`.** Shorter reads must not produce a torn frame on screen.
- **CLI invocation from a path outside the repo.** Covered by A1's `test_default_layout_path_is_absolute_and_resolvable` — re-verify after `cd /tmp` manual run.
- **Unicode in `class_name` / `name`.** Pydantic accepts it; registry lookups must too.
- **Preset inputs where `as_` shadows a built-in pad name.** `"output"`, `"signal"`, etc.

**Exit criteria:** each case either covered by a test or excluded explicitly with a one-line comment in the relevant module.

### 5. Dead code + missed opportunities

**Question:** what did we ship that nothing calls, and what did we *not* ship that we should have?

**Dead-code candidates:**

- `hapax-logos/src-imagination/src/headless.rs::new_for_tests` — gated on `#[cfg(test)]` but never called by a test.
- `fx_chain.blit_scaled` legacy `_pip_draw` fallback branch — reachable only if `layout_state` is None, which the Phase D wiring tests assert is never the case in production.
- `CairoSourceRunner.get_current_surface()` alias — does anything actually call it? `get_output_surface()` was the original name.
- `command_server` commands with no external caller (difflib did-you-mean was added for 5 commands — confirm all 5 are wired to at least one client).

**Missed opportunities:**

- **Phase 4b — actual headless wgpu render loop.** This is the big one. Phase 4a was a scaffold; the real work (GpuContext::new_headless + owned `wgpu::Texture` + staging buffer readback + SHM write + systemd env flip) never shipped. This is blocking "reverie spawns outside logos."
- **Preset inputs → LayoutState wiring.** Phase 7 shipped the schema and resolver (`resolve_preset_inputs`) but no caller invokes it from compositor boot. Effect graphs built from presets still use hardcoded pad names.
- **Freshness gauge for the compositor budget signal.** We gauged the imagination loop but not `publish_costs` — the compositor's own heartbeat is ungauged.
- **Pool metrics IPC.** `DynamicPipeline::pool_metrics()` exists in Rust but is not exported over UDS to Python, so the operator can't see transient-texture reuse from the command line.

**Exit criteria:** dead code deleted or a comment explaining why it stays; every missed opportunity becomes either a Phase 4b-style sub-epic or a backlog ticket.

## Non-goals

- This audit does not re-plan the epic. The Reverie Source Registry Completion epic is closed. Findings that require new work get new tickets, not rewritten epic ACs.
- This audit does not touch the visual chain GPU bridge, presence engine, or other stable subsystems outside the epic's blast radius.
- This audit does not refactor for style — only for correctness and robustness.

## Risks

- **Scope creep.** Every phase has a clear exit criterion; the audit stops when the criterion is met even if more interesting questions are open. Those go to a follow-up audit.
- **Phase 3 (robustness) requires running the compositor live.** This needs the systemd stack up and GPU access. Executing it on the post-epic-fixes worktree means `scripts/rebuild-service.sh` will refuse to deploy (feature branch); I will profile from the main worktree after landing A1 + the audit plan.
- **Confirmation bias from Phase 9 sweep.** Mitigated by re-reading source independently and ignoring the sweep's verdicts until after Phase 1 produces its own.

## Acceptance criteria

The audit is complete when:

1. Phase 1 table covers all 15 parent ACs with independent verdicts, and every stub/missing row has a follow-up ticket.
2. Every invariant listed in Phase 2 is either verified on `main` or has a patch.
3. ALPHA-FINDING-1 has either a confirmed root cause with a merged fix, or a time-bounded investigation doc with the next diagnostic step.
4. "Reverie spawns outside logos" is fixed (Phase 4b of the epic ships as a follow-up PR) OR a handoff doc explains exactly what's left.
5. Every edge case in Phase 4 is either test-covered or documented-as-excluded.
6. Phase 5 findings each have a decision (delete / keep with reason / ticket).
7. A retirement handoff documents the audit results, any new open findings, and the next session's immediate asks.
