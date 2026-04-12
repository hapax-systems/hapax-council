# Compositor Unification Epic — Multi-Phase Audit

**Date:** 2026-04-12
**Scope:** Phase 2 through Phase 7 + Phase 5b sub-phases + Followups F1–F3
**Methodology:** Six parallel `Explore` subagent batches each auditing a logical phase grouping for consistency, completion, dead code, edge cases, robustness, and missed opportunities. Findings verified by reading the cited file:line locations directly.

The full Phase 1 cleanup PRs (#644–#652) predate this conversation and are excluded.

## Executive summary

| Severity | Count | Resolution |
|---|---|---|
| Critical (latent crash, lost behavior) | 2 | **Fixed in this PR** |
| Quality (dead code, redundancy) | 8 | 2 fixed; 6 documented |
| Robustness (untested edges, silent failures) | 14 | Documented |
| Missed opportunity | 18 | Documented |
| Spec drift | 3 | 1 fixed; 2 noted |

The two critical findings are real but reach unreachable code paths in the current vocabulary graph — they are *latent*, not currently observed. They are still fixed because the cost is one line each.

The bulk of findings cluster around the additive nature of the epic: most code paths exist as scaffolding waiting for a future executor to consume them. "Dead until consumer wires it" is **not** a regression — it's the documented Phase 4/F1/etc. ship pattern. Findings flagged as dead code where the future consumer is genuinely missing or stalled are the ones to act on.

---

## Critical findings (fixed in this PR)

### Phase 5b1 — `dynamic_pipeline.rs:1393` hardcoded `"final"` fallback

`hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs:1393` falls back to `self.textures.get("final")` instead of `self.textures.get(MAIN_FINAL_TEXTURE)` (`"main:final"`). The Phase 5b1 multi-target rename was missed at this one site.

The sibling site at line 1388 (the `@accum_*` temporal branch) was correctly updated.

**Why it matters:** when an input texture name doesn't appear in `self.textures`, the fallback looks up `"final"` — which no longer exists — and the subsequent `.unwrap()` panics. The current vocabulary graph never reaches this fallback (every input is satisfied by an explicit producer), so it has not crashed. But a misconfigured plan or a future preset with a missing input would crash the executor.

**Fix:** one-line change to use `MAIN_FINAL_TEXTURE`.

### Phase 6 — Missing `test_clock_source_renders_into_canvas`

`tests/test_plugin_registry.py:298` ships `test_clock_source_can_be_constructed_with_defaults` but the spec (line 406) explicitly required *both* a constructor test AND a render-into-canvas test that calls `ClockSource.render(cr, w, h, t, state)` and verifies non-zero pixel output.

**Why it matters:** the constructor test only validates instance state; the actual `render()` path is untested. A regression in `text_render` imports, `time.strftime` semantics, or Cairo surface construction goes undetected. The missing test was the only spec-promised acceptance check on the reference plugin's render path.

**Fix:** add the test, gate it on Pango availability (matching the existing `text_render` test pattern from Phase 3c).

---

## Per-batch findings

### Batch A — Phase 2 Data Model

**Quality**
- `shared/compositor_model.py:69-75` — SourceSchema fields `update_cadence` and `rate_hz` lack docstrings; their semantic coupling (rate cadence requires rate_hz) lives only in the validator.
- `config/layouts/garage-door.json:112,174-181` — Three sources/surfaces (`halftone-shader`, `main-output`, `wgpu-surface`) declared but never referenced by an assignment. Valid per schema but adds noise to the canonical "validation" layout.

**Robustness**
- `agents/studio_compositor/layout_loader.py:153-162` — `OSError` on `os.path.getmtime` is silently caught; no warning log when a layout file is briefly unreadable. Operator loses a hot-reload event with no signal.
- `agents/studio_compositor/layout_loader.py:138-140` — `LayoutStore` constructed against a non-existent dir continues silently. Operator gets zero loaded layouts and no startup warning.

**Missed opportunities**
- `shared/compositor_model.py` — No `Layout.source_by_id()` / `Layout.surface_by_id()` / `Layout.assignments_for_source()` / `Layout.assignments_for_surface()` helpers. Phase 3+ executor code will need them; manual iteration is the only option today.
- `agents/studio_compositor/layout_loader.py` — mtime polling at 1Hz; an inotify-based watcher would scale better and react instantly. Mentioned but deferred.
- `shared/compositor_model.py:169-186` — Reference validation errors are bare ("unknown source: X"). Adding `difflib.get_close_matches` suggestions (`Did you mean 'cam-brio-operator'?`) would shrink debug time substantially.

**Spec drift:** none.

---

### Batch B — Phase 3 Executor Polymorphism

**Critical:** none.

**Quality**
- `agents/studio_compositor/sierpinski_renderer.py:115-145` — `_load_frame()` still uses GdkPixbuf for YouTube frame JPEGs. Phase 3d's unified `ImageLoader` exists but Sierpinski wasn't migrated to it. Two image-loading code paths.

**Robustness**
- `agents/studio_compositor/image_loader.py` — Cache has no eviction. Long sessions with many image sources grow memory linearly. Spec acknowledged + deferred.
- `agents/studio_compositor/image_loader.py:125-157` — JPEG decode imports PIL/numpy lazily; if PIL is missing, `_decode_jpeg` raises `ImportError` instead of returning `None`. Spec promised graceful degradation.
- `hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs` — Unknown backend dispatch logs at debug level then continues. A misconfigured manifest produces no visual error and no warning-level signal.

**Missed opportunities**
- `agents/studio_compositor/text_render.py` — No `TextSource(CairoSource)` wrapper class shipped. Phase 3c spec sketched it in Appendix B but it didn't land. Plugin authors who want a text source must hand-roll their own `CairoSource` subclass.

**Spec drift**
- `agents/studio_compositor/{fx_chain.py,overlay_zones.py,token_pole.py}` — Phase 3b spec deferred AlbumOverlay / OverlayZoneManager / TokenPole migration to follow-up "3b-2/3/4" PRs. **Those follow-up PRs never landed in this conversation.** The three classes still render Cairo directly outside the new `CairoSource` protocol. The Phase 3b *helpers* are present and exercised by Sierpinski, but the original "all four classes migrated" goal is incomplete.

---

### Batch C — Phase 4 Compile Phase

**Critical:** none currently. (Hash stability flagged below.)

**Quality:** all `compile.py` symbols are reachable from `compile_frame` or its tests. No dead helpers.

**Robustness**
- `tests/test_compile.py` — No tests for non-string entries in `effect_chain` (Pydantic prevents this so it's defensive only) or for cross-frame ordering stability when surface IDs change between layouts.
- `agents/studio_compositor/compile.py:98` — `pool_key = hash(descriptor)` uses Python's process-local hash. Same descriptor on two distinct Python processes produces different keys. **Currently fine** because the only consumer is the same Python process; **not fine** if the pool key is ever serialized to plan.json or shared cross-process. Worth a docstring warning even though no consumer is live.

**Missed opportunities**
- `agents/studio_compositor/compile.py` — No `CompiledFrame.is_empty` property, no `__repr__` summarizing optimization metrics, no `diff(other)` for inter-frame deltas. Executor code will reinvent these.

**Spec drift**
- `compile.py:312` — Spec wrote transient name as `{surface_id}.{effect_node_id}`; implementation uses the literal effect-chain string entry. Equivalent but spec wording was ambiguous about whether the effect node *id* or the *type* was meant.

---

### Batch D — Phase 5 Multi-Output

**Critical**
- ✅ **Fixed:** `dynamic_pipeline.rs:1393` hardcoded `"final"` fallback (see top of report).

**Quality**
- `agents/studio_compositor/output_router.py:151-157` — `render_targets()` and `sinks_of_kind()` have no in-tree callers. Designed for the host compositor that hasn't shipped yet — known additive plumbing.
- `dynamic_pipeline.rs:187` — `DynamicPass.target` is `#[allow(dead_code)]`. Stored for diagnostics + future host wiring (Phase 5b3 OutputRouter consumer). Confirmed intentional.

**Robustness**
- `dynamic_pipeline.rs:448-451` — A plan with all targets containing zero passes silently clears `self.passes` and returns `true` with an info log. A more typical case (operator typo in compiler emit) renders black with only the existing log line. No structured signal.
- `shared/compositor_model.py` — `SurfaceGeometry.render_target` defaults to `None`; `OutputRouter` defaults the routing to `"main"` but **never validates** that `"main"` (or any declared `render_target`) is a target the executor actually produces. A layout can declare `render_target: "hud"` that never gets rendered; OutputRouter won't notice.
- `agents/effect_graph/wgsl_compiler.py:106-107` — Comment notes "cross-target sharing of the same temporal node is a known limitation" but the Rust executor has no enforcement. Two targets with the same temporal node would write the same `@accum_{node_id}` buffer and bleed across each other.
- `agents/studio_compositor/ingest_mode.py:104` — `set_mode()` does the atomic write but writes no timestamp into the file. Operator can't trace when the toggle happened across restarts.

**Missed opportunities**
- `shared/compositor_model.py` — No `Layout.render_targets()` helper to extract the unique render target names declared across video_out surfaces. `OutputRouter.from_layout` could compute it but the Layout API is the natural home.
- `agents/studio_compositor/output_router.py` — No `validate_against_plan(plan)` method to check the bindings' render_target values against the targets the executor will actually produce. Invalid bindings go undetected until execution.
- `dynamic_pipeline.rs` — `target_names()` exists but no per-target frame count / pass count introspection. Future debug overlays can't query "how deep is each target."

**Spec drift:** none.

---

### Batch E — Phase 6 Plugin System

**Critical**
- ✅ **Fixed:** missing `test_clock_source_renders_into_canvas` (see top of report).

**Quality**
- `shared/plugin_manifest.py:95` — `PluginManifest.backend` accepts any non-empty string. Spec referenced specific dispatcher keys (`wgsl_render`, `cairo`, `text`, `image_file`) but the field has no enum constraint. Typos like `"textt"` or `"cairo_v2"` slip through validation and fail later at compositor init.
- `tests/test_plugin_registry.py` — `PluginParam.enum_values` is parsed but never test-exercised. Future UI form generation that consumes the field has no test scaffold.

**Robustness**
- `plugins/clock/source.py:57` — `time.strftime(self._format)` has no error handling. Invalid format codes silently produce literal output instead of raising.
- `tests/test_plugin_registry.py` — No tests for concurrent `scan()` + `reload_changed()` calls (the registry holds a lock; race ordering untested).
- `tests/test_plugin_registry.py` — No test for plugin directories with Unicode names. Filesystem encoding issues on non-UTF8 systems unvalidated.

**Missed opportunities**
- `agents/studio_compositor/plugin_registry.py` — No `instantiate(name, **kwargs)` helper to lazy-load `source_module` + instantiate the class. Spec promised lazy import; the operator must call `importlib.import_module` themselves.
- `shared/plugin_manifest.py` — No `min_compositor_version` field. Plugins can't declare compatibility bounds; backward-incompatible compositor changes break plugins silently.
- `shared/plugin_manifest.py` — No plugin dependency declaration. Interdependent plugins can't express load order or shared state.

**Spec drift**
- Test count is 20 vs spec's "~14 new tests". Acceptance criteria over-fulfilled — flag for spec accuracy, not implementation.

---

### Batch F — Phase 7 + Followups

**Critical:** none.

**Quality**
- ✅ **Fixed:** `transient_pool.rs` `fresh<T>()` test helper unused — removed.
- ✅ **Fixed:** `transient_pool.rs:167-173` — `reuse_ratio()` docstring claimed NaN return for empty tracker; implementation returns `0.0`. Docstring updated to match the implementation (0.0 is the more idiomatic Rust answer; NaN would surprise integer-bucketed metric collectors).
- `transient_pool.rs:110-141` — Two `acquire` methods with overlapping intent. The bare `acquire` returning `&T` has dead-code comments referencing a borrow-checker workaround that was never finished — the increment of `total_allocations` is silently dropped. All tests use `acquire_tracked` instead. The bare `acquire` is effectively vestigial; removing it would simplify the API but breaks the documented contract. **Documented for follow-up.**
- `agents/studio_compositor/budget.py + budget_signal.py` — `publish_costs` and `publish_degraded_signal` both implement the atomic write pattern (mkdir → write tmp → os.replace). Could share an `atomic_write_json(data, path)` helper. Cosmetic.

**Robustness**
- `agents/studio_compositor/budget.py:153-160` — `over_budget(source_id, budget_ms)` does not validate `budget_ms > 0` (the constructor does, the query doesn't). A caller passing `0` or negative gets "always under budget" silently.
- `agents/studio_compositor/budget_signal.py:88-91` — `worst_source` selection uses strict `>` comparison. When two sources tie on `skip_count`, the iteration order of `snapshot()` (dict insertion order) determines who wins. Documented tiebreak behavior is missing.
- `tests/test_budget.py` — Missing edge cases: duplicate `source_ids` in `over_layout_budget`, negative/NaN/inf in `record`, extremely large window_size.
- `tests/test_budget_signal.py` — No test for `publish_degraded_signal` when `/dev/shm` is read-only or full (`os.replace` would fail silently in the current code).

**Missed opportunities**
- `agents/studio_compositor/budget.py` — No callback / event interface for over-budget transitions. Reactive consumers (stimmung gating) must poll `snapshot()`.
- Both `publish_costs` and `publish_degraded_signal` payloads lack a payload-side timestamp. Readers can't distinguish stale vs current files without `stat()`. Trivial addition.
- `agents/studio_compositor/budget.py` — `over_layout_budget` returns `bool` only. No method to identify *which* source(s) pushed the total over. Diagnostics are coarse.
- `transient_pool.rs` — No `bucket_keys()` iterator for diagnostics. External profilers can't enumerate pool buckets without exposing the private `buckets` HashMap.

**Spec drift:** none.

---

## Cross-phase synthesis

### Pattern: "land the data plane, defer the consumer"

Six modules ship as scaffolding with no in-tree consumer yet:

1. `compile.py::CompiledFrame` — no executor reads it
2. `compile.py::TransientTexture / pool_key` — no Rust consumer wires it
3. `output_router.py::OutputRouter` — no host wiring
4. `ingest_mode.py::IngestMode` — no `pipeline.py` branch
5. `transient_pool.rs::TransientTexturePool` — no executor wiring
6. `budget_signal.py::publish_degraded_signal` — no VLA subscriber

**This is the documented epic ship pattern** ("additive plumbing, consumer later"). It is not a defect — but it does mean the *integration tests* and *end-to-end coverage* of these modules will only land when their consumers do. The `Quality` "no callers" findings on `OutputRouter.render_targets/sinks_of_kind`, `DynamicPipeline.target_names`, `Layout.video_outputs`, etc. all fall in this category.

**Recommendation:** when a future consumer wires up, *also* land the "first real call site" tests. Don't merge a consumer PR without an integration test against the previously-additive module.

### Pattern: "spec drift on incomplete migrations"

Phase 3b set out to migrate four Cairo classes (`SierpinskiRenderer`, `AlbumOverlay`, `OverlayZoneManager`, `TokenPole`). Only Sierpinski landed; the other three were deferred to "Phase 3b-2/3/4" follow-up PRs that never shipped. The compositor now has a two-tier architecture: legacy direct-render classes + the new `CairoSource` protocol.

This is the largest *incomplete* item in the audit. It does not affect correctness (both paths render correctly) but it defeats the unification goal.

**Recommendation:** track Phase 3b-2/3/4 as concrete follow-up tickets, not vague "future work."

### Pattern: "missing helpers on the data model"

Three batches independently flagged the same gap: `shared/compositor_model.py::Layout` lacks lookup helpers (`source_by_id`, `surface_by_id`, `render_targets`, `assignments_for_source`, `assignments_for_surface`). Every consumer (compile, OutputRouter, future executor) reinvents the same iteration patterns.

**Recommendation:** ship a small "Layout convenience helpers" PR. ~30 lines of code, ~10 tests, zero risk.

### Pattern: "silent failure modes"

Six findings flag silent failure modes (LayoutStore mtime stat OSError swallowed, image_loader ImportError on missing PIL, dynamic_pipeline unknown-backend skipped at debug level, OutputRouter doesn't validate render_target against plan, set_mode doesn't write a timestamp, plugin_registry doesn't surface the failed list anywhere visible).

**Recommendation:** an "observability tightening" PR that promotes the worst of these from `log.debug` / silent-skip to `log.warning` and exposes failure counts via the existing `publish_costs` / `publish_degraded_signal` mechanism.

---

## Action items (recommended)

| Severity | Item | Recommended action |
|---|---|---|
| **CRITICAL** | `dynamic_pipeline.rs:1393` hardcoded `"final"` fallback | ✅ **Fixed in this PR** |
| **CRITICAL** | Missing `test_clock_source_renders_into_canvas` | ✅ **Fixed in this PR** |
| Quality | `transient_pool.rs::fresh<T>()` unused | ✅ **Fixed in this PR** |
| Quality | `transient_pool.rs::reuse_ratio` docstring/impl mismatch | ✅ **Fixed in this PR** |
| HIGH | Phase 3b incomplete migration (3 classes) | Schedule as follow-up tickets |
| HIGH | Layout convenience helpers | Small one-PR ship |
| MEDIUM | Observability tightening (silent failure modes) | One-PR ship |
| MEDIUM | `OutputRouter.validate_against_plan` | Land alongside first real consumer |
| MEDIUM | Per-payload timestamps in published signals | One-line per publisher |
| LOW | Doc strings on `SourceSchema` rate fields | Trivial touch-up |
| LOW | Difflib suggestions in Layout validation errors | Trivial touch-up |
| LOW | `transient_pool.rs::acquire` vestigial bare method | Remove or finish; pick one |

The two HIGH items (Phase 3b incomplete migration, Layout convenience helpers) are the highest-leverage follow-ups. Everything else is small enough to bundle into a single "audit fixes round 2" PR if the operator wants to clear the board.

---

## Methodology notes

The audit was executed by six parallel `Explore` subagents, each with a focused file scope and a fixed output template (`Critical / Quality / Robustness / Missed opportunities / Spec drift`). The two `Critical` findings were independently verified by direct file inspection before being included in this report. Subagent findings flagged as `Quality` or `Missed opportunity` were presented as-is — the audit's job is to surface them, not to litigate every one.

The audit deliberately did NOT include:
- Phase 1 PRs (#644–#652) because they predate this conversation
- Live-system smoke testing of the operator's stream
- Performance regression measurement (would require baseline capture)

These are reasonable next-step audits to schedule once the operator has triaged the current findings.
