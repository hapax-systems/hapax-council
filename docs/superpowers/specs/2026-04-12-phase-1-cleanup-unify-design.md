# Phase 1: Cleanup & Unify — Design Spec

**Date:** 2026-04-12
**Status:** Approved (self-authored, alpha session)
**Epic:** `docs/superpowers/plans/2026-04-12-compositor-unification-epic.md`
**Phase:** 1 of 7
**Risk:** Low (all changes are self-contained and reversible)
**Depends on:** Research in `docs/superpowers/research/2026-04-12-content-composition-architecture.md` and the Phase 1 detailed inventory in the epic appendices.

---

## Purpose

Reduce the surface area of the compositor codebase before any architectural change. Delete dead code, collapse the two parallel wgpu content backends into one, and generalize the content slot injection mechanism in the effect graph compiler. Every change in this spec is independently reversible and produces no visible behavior change for the operator.

**This phase makes no architectural commitments.** It just removes what would get in the way of future phases.

**Expected LOC reduction:** ~1,400 lines deleted, ~80 lines added. Net: **~1,300 lines removed.**

---

## Scope

Three sub-phases, each a separate PR merging into `epic/compositor-phase-1`:

1. **Phase 1a:** Delete dead code — `visual_layer.py`, `YouTubeOverlay`, `_add_camera_fx_sources`, legacy `_tick_*` and `_call_llm` methods, and the `spawn_confetti`/`_finished` ghost references they contain.
2. **Phase 1b:** Unify wgpu content backends — delete `ContentTextureManager`, `slots.json` manifest protocol, and the `write_slot_manifest` writer. Migrate to `ContentSourceManager` via `inject_jpeg` from the existing source protocol.
3. **Phase 1c:** Generalize content slot opt-in — replace the hardcoded `(content_layer, sierpinski_content)` tuple in `wgsl_compiler.py` with a `requires_content_slots: bool` flag in node manifests.

---

## Phase 1a: Dead code deletion

### Target paths

From the comprehensive codebase audit, the following paths are confirmed dead via grep verification:

**A. `visual_layer.py` — orphaned 6-zone HUD**

- File: `agents/studio_compositor/visual_layer.py`
- Public entry: `render_visual_layer(cr, state, canvas_w, canvas_h)`
- Verification: `overlay.py::on_draw` does not call it. `state.py` reads `compositor._vl_state` but only logs it. The aspirational 5-6 zone model from `docs/superpowers/plans/2026-04-04-overlay-content-system.md` is half-built.
- Size: ~270 lines
- Dependencies: Audit `shared/visual_layer_state.py` — may also be dead after this removal

**B. `YouTubeOverlay` + `PIP_EFFECTS`**

- File: `agents/studio_compositor/fx_chain.py`
- Class: `YouTubeOverlay` (lines 14-258)
- Dict: `PIP_EFFECTS` (lines 403-409) — 5 stylization functions: `_pip_vintage`, `_pip_cold_surveillance`, `_pip_neon`, `_pip_film_print`, `_pip_phosphor`
- Verification: `build_inline_fx_chain()` at line 785 sets `compositor._yt_overlay = None`. The `_pip_draw` callback at line 544 only iterates `compositor._album_overlay` and `compositor._token_pole`, never `_yt_overlay`.
- Size: ~260 lines (class + effects dict)

**C. `_add_camera_fx_sources` disabled stub**

- File: `agents/studio_compositor/pipeline.py` lines 183-230
- Verification: commented documentation at lines 98-102 declares it broken (caps negotiation deadlock). Function defined but never called.
- Size: ~50 lines

**D. Legacy `_call_llm` + `_tick_*` methods in director_loop**

- File: `agents/studio_compositor/director_loop.py`
- Methods: `_call_llm` (lines 966-1065), `_tick_playing` (408-462), `_tick_chat` (588-609), `_tick_vinyl` (612-629), `_tick_study` (632-660)
- Verification: only `_call_activity_llm` is invoked from the active `_loop`. The rest are legacy per the in-file comment "Legacy activity tick methods (kept for reference, not called)". No external callers anywhere in the repo.
- Size: ~350 lines

**E. `spawn_confetti` and `_finished` ghost references**

- File: `agents/studio_compositor/director_loop.py`
- Line 416-417: `s.spawn_confetti(pos[0], pos[1])` — `VideoSlotStub` does not define this method. Would AttributeError if reached.
- Lines 427-428: `slot._finished` — `VideoSlotStub` does not define this attribute. Would AttributeError if reached.
- Both live inside `_tick_playing` (target D above). Removed transitively.

**F. `SpirographReactor` and `ReactorOverlay` audits**

- Grep whole repo for `SpirographReactor` — expect 0 hits (replaced by SierpinskiLoader in PR #644).
- Grep for `ReactorOverlay` — should only be in comments/docstrings, not as an actual type.
- Any hits get deleted or documented as intentional references.

**G. Possible orphans discovered during audit**

- `shared/visual_layer_state.py` (if only used by deleted `visual_layer.py`)
- `PIP_EFFECTS` helper imports in other files
- Any `# TODO` comments referencing deleted functions

### Verification protocol before deletion

For each target path, before deletion:

1. `rg -w <function_name>` to find every reference in Python
2. `rg -w <class_name>` to find every import and instantiation
3. `rg -w <function_name>` in Rust source too (for cross-language accidents)
4. Check configuration files in `config/` for references
5. Check `systemd/units/` for references
6. Check `docs/` for references (these can stay if they document the removal)
7. Check `tests/` — any tests of dead code must also be removed

Only delete if all verifications return "no active references."

### Expected reductions

| Target | File | Lines deleted |
|---|---|---|
| A. visual_layer.py | `agents/studio_compositor/visual_layer.py` | ~270 |
| A. visual_layer state ref | `agents/studio_compositor/state.py` | ~20 |
| B. YouTubeOverlay class | `agents/studio_compositor/fx_chain.py` | ~260 |
| B. `_yt_overlay = None` | `agents/studio_compositor/fx_chain.py` | ~1 |
| C. `_add_camera_fx_sources` | `agents/studio_compositor/pipeline.py` | ~50 |
| D. `_call_llm` + `_tick_*` | `agents/studio_compositor/director_loop.py` | ~350 |
| E. `spawn_confetti` + `_finished` refs | (inside D) | — |
| **Total estimate** | | **~950 lines** |

Plus test files that exercise the deleted code (if any).

### Test strategy

- Run the full test suite before deletion: `uv run pytest tests/ -q -m "not llm" --ignore=tests/hapax_daimonion --ignore=tests/contract --ignore=tests/fortress`. Baseline = X passed, Y skipped.
- Delete the dead code.
- Run the test suite again. Expected: X − (tests for dead code) passed, Y skipped. If any previously-passing test now fails, the "dead" code wasn't actually dead; revert that specific deletion.
- Start the compositor and verify it renders without error. Compare `fx-snapshot.jpg` against a pre-deletion baseline — must be visually identical (though timing may vary).
- Leave the compositor running for 5 minutes. No new errors in logs.

### Acceptance criteria

- [ ] All 7 dead paths deleted or documented as still-needed.
- [ ] Test suite passes.
- [ ] Compositor starts cleanly.
- [ ] `fx-snapshot.jpg` visually identical to pre-deletion baseline.
- [ ] No new warnings or errors in systemd journal.
- [ ] `uv run ruff check .` passes.
- [ ] Any orphaned imports removed via `ruff check --fix`.

### Rollback

Single `git revert` of the PR.

---

## Phase 1b: Unify wgpu content backends

### Current state (from deletion impact research)

The wgpu Reverie pipeline has **two content backends running simultaneously**:

1. **`ContentTextureManager`** (legacy): 4 fixed slots at 1920×1080 Rgba8Unorm allocated eagerly at startup (~32 MB VRAM). Reads `/dev/shm/hapax-imagination/content/active/slots.json`. Uses turbojpeg to decode JPEGs into slot textures. Polled every 500ms. ~282 lines Rust.

2. **`ContentSourceManager`** (unified): 16 dynamic sources with per-source width/height, reads `/dev/shm/hapax-imagination/sources/{id}/{manifest.json, frame.rgba}` scanned every 100ms. TTL-based expiration with auto-cleanup. Accepts arbitrary RGBA bytes from any agent via `content_injector.py`. ~326 lines Rust.

Both terminate in the same GPU binding (`content_slot_0..3`), with runtime precedence logic in `dynamic_pipeline.rs:1124-1130` and `main.rs:215-225` choosing the unified backend whenever any source has opacity > 0.001.

**Writers of `slots.json`:**
- `agents/studio_compositor/sierpinski_loader.py::_update_manifest` — polls YouTube JPEG snapshots, writes manifest with `fragment_id: "sierpinski-yt"` (always constant), `continuation: true` (always).
- `agents/imagination_resolver.py::write_slot_manifest` — called from `resolve_references_staged`. Writes alongside the source protocol (double-write — `write_source_protocol()` is called at the end of the same function).
- `scripts/smoke_test_reverie.py::write_manifest` — test helper.

**Readers of `slots.json`:**
- `hapax-logos/crates/hapax-visual/src/content_textures.rs::ContentTextureManager` — the only reader.

**Dead payload fields:**
- `kind: "camera_frame"` — written by Python, silently dropped by Rust deserializer.
- `material: "void"` — written by Python, silently dropped by Rust deserializer. The real `material` value flows through `uniforms.json` via `signal.material` from the Reverie mixer, not through the slot manifest.

**Fade state machine:**
- `ContentTextureManager` has separate continuation/non-continuation paths with a 500ms "fade-out → gap → fade-in" sequence for fragment_id changes.
- SierpinskiLoader always sets `continuation: true` and hardcoded `fragment_id: "sierpinski-yt"`, so the gap-fade branch is **never exercised** for the YouTube path.
- imagination_resolver.py writes `continuation: false` for fragments, so the gap-fade IS exercised there — but the source protocol path is already written alongside it, and runtime evidence confirms `ContentSourceManager` is already shadowing the legacy path when any source has opacity > 0.001.

### Problem

- Two parallel backends for the same functional role.
- Hardcoded 4-slot fixed-size allocation eats 32 MB VRAM whether content is loaded or not.
- `slots.json` carries dead payload fields (`kind`, `material`) that Rust ignores.
- The "fade-out → gap → fade-in" code path is exercised by one writer (imagination_resolver) but shadowed at runtime by the source protocol. Net effect: unused code running in production.
- SierpinskiLoader copies JPEG files from `/dev/shm/hapax-compositor/` to `/dev/shm/hapax-imagination/content/active/` before each manifest write — pure I/O duplication.

### Migration

**Step 1:** Create new YouTube source loader that writes to the unified source protocol.

Replace `SierpinskiLoader._update_manifest` with direct `inject_jpeg` calls. The rest of the class (VideoSlotStub, DirectorLoop bootstrap, no-op reactor stubs) stays — only the manifest writing path changes.

Before:
```python
# sierpinski_loader.py::_update_manifest (current)
for slot_id in range(3):
    frame_path = YT_FRAME_DIR / f"yt-frame-{slot_id}.jpg"
    if not frame_path.exists():
        continue
    salience = 0.9 if slot_id == self._active_slot else 0.3
    dest = ACTIVE_DIR / f"slot_{slot_id}.jpg"
    shutil.copy2(str(frame_path), str(dest))
    slots.append({"index": slot_id, "path": str(dest), "kind": "camera_frame", "salience": salience})

manifest = {"fragment_id": "sierpinski-yt", "slots": slots, "continuation": True, "material": "void"}
# Write atomic tmp + rename
```

After:
```python
# sierpinski_loader.py::_update_sources (new)
from agents.reverie.content_injector import inject_jpeg, remove_source

for slot_id in range(3):
    frame_path = YT_FRAME_DIR / f"yt-frame-{slot_id}.jpg"
    source_id = f"sierpinski-yt-{slot_id}"
    if not frame_path.exists():
        remove_source(source_id)
        continue
    opacity = 0.9 if slot_id == self._active_slot else 0.3
    inject_jpeg(
        source_id=source_id,
        jpeg_path=str(frame_path),
        opacity=opacity,
        z_order=slot_id,  # active sorts higher after we set _active_slot
        blend_mode="over",
        tags=["youtube", "sierpinski"],
        ttl_ms=5000,  # stale if not refreshed for 5s
    )
```

The 0.4s poll cadence stays. The `_active_slot` tracking stays. The VideoSlotStub protocol and DirectorLoop bootstrap stays.

**Step 2:** Delete `ContentTextureManager` and references.

Files changed:
- `hapax-logos/crates/hapax-visual/src/content_textures.rs` — **DELETE**
- `hapax-logos/crates/hapax-visual/src/lib.rs` — remove `pub mod content_textures;`
- `hapax-logos/src-imagination/src/main.rs`:
  - Remove `use hapax_visual::content_textures::ContentTextureManager;` (line 20)
  - Remove `content_textures: Option<ContentTextureManager>` field (line 41)
  - Remove initialization (`None` in new, then `Some(...)` in late binding at lines 60, 315, 321)
  - Remove per-frame `ct.poll()` + `ct.tick_fades()` (lines 192-195)
  - Remove `legacy_opacities` computation + the if/else that picks between source and legacy (lines 215-224) — always use `source_opacities`
  - Remove `content_textures.as_ref()` argument from `pipeline.render()` call (line 234)
- `hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs`:
  - Remove `use crate::content_textures::ContentTextureManager;` (line 16)
  - Remove `content_textures: Option<&ContentTextureManager>` parameter from `render()` (line 554)
  - Remove same parameter from `create_input_bind_group()` (line 1072)
  - Remove the if/else branch at lines 1124-1130 — simplify to:
    ```rust
    let slot_view = content_sources
        .map(|cs| cs.slot_view(idx))
        .unwrap_or_else(|| self.textures.get("final").map(|t| &t.view).unwrap());
    ```

**Step 3:** Delete `write_slot_manifest()` from `imagination_resolver.py`.

- `agents/imagination_resolver.py`:
  - Remove `write_slot_manifest(fragment, resolved_paths, manifest_path, refs)` function (~45 lines)
  - Remove the call from `resolve_references_staged()` at line 227
  - Remove the staging → active atomic rename dance at lines 218-234 if no other code uses it (verify via grep of `staging`)
  - `MAX_SLOTS = 4` and the `camera_frame` resolution branch at lines 180-183 become dead; remove them
  - `write_source_protocol()` call at line 238 stays — this is the surviving path

- `tests/test_imagination_resolver.py`:
  - Delete `test_write_slot_manifest` (line 194)
  - Delete `test_resolve_references_staged_atomic` (line 214)
  - Delete `test_resolve_references_staged_replaces_previous` (line 227)
  - Delete `test_manifest_camera_frame_uses_source_path` (line 241)
  - Delete `test_manifest_file_ref_uses_source_path` (line 251)
  - Delete `test_manifest_max_four_slots` (line 260)
  - Delete `test_manifest_includes_material_and_continuation` (line 274)

- `scripts/smoke_test_reverie.py`:
  - Rewrite to use the source protocol (`inject_image("smoke-test-{i}", path, opacity=salience, z_order=5)`) OR delete if redundant with `tests/test_content_source_protocol.py`.

### Expected reductions

| File | Lines |
|---|---|
| `content_textures.rs` (DELETE) | ~282 |
| `lib.rs` (mod declaration) | 1 |
| `main.rs` (instantiation + render args) | ~20 |
| `dynamic_pipeline.rs` (precedence + args) | ~30 |
| `sierpinski_loader.py::_update_manifest` | ~40 |
| `imagination_resolver.py::write_slot_manifest` + related | ~95 |
| `test_imagination_resolver.py` (6 tests deleted) | ~100 |
| `smoke_test_reverie.py` (full rewrite or delete) | ~50 |
| **Total estimate** | **~620 lines** |

Plus the ~32 MB of VRAM reclaimed from the eager 4×1080p texture allocation.

### Behavior change analysis

**Expected identical:**
- YouTube frames appear in the same Sierpinski corners (same content flowing through the same GPU bindings)
- Active slot highlighted via higher opacity
- Fade timing (0.4s updates; linear rate 2.0/s fade — already the current visible behavior via source precedence)

**Expected slight change:**
- Imagination fragment transitions lose the "fade-out → gap → fade-in" sequence. Replaced with linear crossfade. Small visual difference at imagination fragment boundaries only. Can be reintroduced in the future if needed.
- VRAM footprint: -32 MB (eager 4×1080p Rgba8Unorm)
- Slot update latency: -5× (100ms scan vs 500ms scan + 400ms write)

**Not changed:**
- All affordance-recruited content paths (cameras, recall, narrative text) — already use `ContentSourceManager`.
- The GPU binding layout for content-bearing shaders — still `content_slot_0..3` at bindings 2-5.
- The shader code (content_layer.wgsl, sierpinski_content.wgsl).
- The `requires_content_slots` detection path in bind group creation (Phase 1c addresses that).
- The SierpinskiLoader's DirectorLoop bootstrap and VideoSlotStub interface.

### Rollback

Single `git revert` of the PR. The legacy files are restored as-is.

### Acceptance criteria

- [ ] `content_textures.rs` deleted.
- [ ] `sierpinski_loader.py` writes to the unified source protocol.
- [ ] `imagination_resolver.py::write_slot_manifest` deleted.
- [ ] `/dev/shm/hapax-imagination/content/active/slots.json` no longer written by any code path.
- [ ] `dynamic_pipeline.rs::render` and `create_input_bind_group` signatures simplified.
- [ ] Tests updated (6 imagination_resolver tests deleted, smoke test ported or deleted).
- [ ] Rust build clean; no orphaned `mod content_textures` declarations.
- [ ] Python tests pass.
- [ ] Live compositor output (fx-snapshot + wgpu surface) matches pre-migration baseline.
- [ ] Systemd journal clean for 5 minutes of runtime.
- [ ] `pw-dump` or equivalent GPU memory check shows ~32 MB reduction on the `hapax-imagination` process.

---

## Phase 1c: Generalize content slot opt-in

### Current state

`wgsl_compiler.py:127-129` has a hardcoded tuple:
```python
if step.node_type in ("content_layer", "sierpinski_content"):
    inputs.extend(f"content_slot_{j}" for j in range(4))
```

This is the "magic" that adds 4 content slot inputs to specific node types so the Rust side knows to use the alternate bind group layout with 4 bare content textures + shared sampler.

`dynamic_pipeline.rs:979-1022` has matching magic that checks for any input starting with `content_slot_` and switches bind group layout.

Adding a new content-aware shader node today requires editing this tuple in the Python compiler. That's a small thing but it's a hardcoded branch that every new content-aware node has to get added to.

### Change

**JSON manifest:**

Add an optional `requires_content_slots: bool` field to `agents/shaders/nodes/*.json`. Defaults to `false`. Set to `true` for `content_layer.json` and `sierpinski_content.json`.

```json
{"node_type": "content_layer", "requires_content_slots": true,
 "inputs": {"in": "frame", ...}, "outputs": {"out": "frame"}, ...}
```

**Python `LoadedShaderDef` in `agents/effect_graph/registry.py`:**

Add `requires_content_slots: bool` field. Populate from JSON during registry load.

**Python `wgsl_compiler.py`:**

Replace the hardcoded tuple with a registry lookup:
```python
node_def = self._registry.get(step.node_type)
if node_def and node_def.requires_content_slots:
    inputs.extend(f"content_slot_{j}" for j in range(4))
```

Also propagate the flag to the plan.json pass entry:
```python
pass_entry["requires_content_slots"] = True
```

**Rust `PlanPass` in `dynamic_pipeline.rs`:**

Add `#[serde(default)] pub requires_content_slots: bool` field. Populated from plan.json during deserialization.

**Rust `dynamic_pipeline.rs` bind group detection:**

Change the detection to prefer the explicit flag, with name-based fallback:
```rust
let needs_content_slots = pass.requires_content_slots
    || pass.inputs.iter().any(|n| n.starts_with("content_slot_"));
```

### Impact

This is the smallest sub-phase in Phase 1 — ~50 lines of change. The behavior is identical: the same two nodes get the same bind group layout. But the extension mechanism is now declarative:

- Adding a new content-aware shader node means one JSON file, not a code edit in `wgsl_compiler.py`.
- The hardcoded tuple goes away.
- Future phases can introduce more content-aware shaders without touching the compiler.

### Acceptance criteria

- [ ] `content_layer.json` and `sierpinski_content.json` have `requires_content_slots: true`.
- [ ] All other node manifests have `requires_content_slots: false` or absent (default).
- [ ] `wgsl_compiler.py` no longer hardcodes node type names for content slot injection.
- [ ] Python `LoadedShaderDef` and Rust `PlanPass` both have the new field.
- [ ] Existing presets compile and render identically.
- [ ] A test that declares a new `fake_content_node` with `requires_content_slots: true` correctly gets 4 `content_slot_*` inputs in its plan entry.

### Rollback

Single `git revert` of the PR. The hardcoded tuple comes back.

---

## Cross-sub-phase concerns

### Branch strategy

```
main
 └── epic/compositor-phase-1
      ├── feat/phase-1a-dead-code      (PR A)
      ├── feat/phase-1b-content-unify  (PR B, depends on A merged)
      └── feat/phase-1c-source-refs    (PR C, depends on A and B merged)
```

PRs A, B, C merge into `epic/compositor-phase-1` as they complete. When all three merge and CI is green, `epic/compositor-phase-1` merges into main as a single "Phase 1 complete" commit via squash merge.

Each PR has its own CI run. Each PR is independently revertable. The epic branch is kept around for 30 days after main merge for emergency rollback.

### Test baselines

Before starting Phase 1, capture:

- `uv run pytest tests/ -q --ignore=tests/hapax_daimonion --ignore=tests/contract --ignore=tests/fortress -m "not llm"` → record pass count
- `wc -l agents/studio_compositor/*.py agents/effect_graph/*.py hapax-logos/crates/hapax-visual/src/*.rs` → LOC baseline
- A fresh `fx-snapshot.jpg` from the running compositor → visual baseline
- `nvidia-smi --query-gpu=memory.used --format=csv,noheader` → GPU memory baseline
- Journal logs for the last hour → error baseline

After each sub-phase PR merge:

- Re-run the same measurements
- Expected: pass count stable or decreased only by the number of tests for deleted code, LOC decreased by the sub-phase's expected reduction, fx-snapshot visually identical, GPU memory stable or decreased, no new errors in journal

### Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Dead code isn't actually dead (hidden call site) | Low | Medium | Comprehensive grep before deletion; test suite; journal check after deploy |
| ContentTextureManager migration changes visual behavior | Low | Low | Current runtime already shadows it via ContentSourceManager; migration just removes the shadowed-out path. Non-continuation fade-gap will be lost but is unused in the YouTube path (sierpinski-yt always sets continuation=true) |
| `requires_content_slots` flag typo in JSON causes silent fallthrough | Low | Low | Add a test that validates every content-aware node has the flag set |
| Accidental deletion of transitive dead code that isn't dead | Medium | Medium | Sub-phase 1a is the riskiest; do thorough audit, test after each deletion |
| Rebase conflicts with concurrent beta work | Low | Low | Beta's current focus (prompt compression) doesn't touch the affected files |

### Success metrics

Phase 1 is successful when:
- **-1,300 lines of code net** in `agents/studio_compositor/`, `agents/effect_graph/`, `agents/imagination_resolver.py`, `hapax-logos/crates/hapax-visual/src/`, and tests.
- **One wgpu content backend** instead of two.
- **-32 MB VRAM** on the `hapax-imagination` process.
- **5× faster slot update cadence** (100ms scan vs 500ms scan).
- **One declarative mechanism** for content slot injection instead of a hardcoded tuple.
- **Zero visual regression** for the YouTube/Sierpinski path.
- **Zero test regressions**.

---

## Not in scope

Phase 1 does not:

- Introduce the Source/Surface/Assignment data model (that's Phase 2)
- Add any new content types (that's Phase 3)
- Implement any new caching or culling (that's Phase 4)
- Touch the GStreamer compositor pipeline structure (that's Phase 5)
- Define a plugin system (that's Phase 6)
- Add budget enforcement (that's Phase 7)

This phase is purely additive cleanup. Every change is either a deletion (with equivalent behavior) or a declarative equivalent of what was previously imperative. Nothing that didn't exist before should exist after, except the `requires_content_slots` field added to two node manifests.

---

## Appendix A: Files touched per sub-phase

**Phase 1a (dead code):**
- `agents/studio_compositor/visual_layer.py` (DELETE)
- `agents/studio_compositor/state.py` (edit — remove `_vl_state` field)
- `agents/studio_compositor/fx_chain.py` (edit — remove YouTubeOverlay + PIP_EFFECTS)
- `agents/studio_compositor/pipeline.py` (edit — remove `_add_camera_fx_sources`)
- `agents/studio_compositor/director_loop.py` (edit — remove `_call_llm`, `_tick_*`, transitive `spawn_confetti` and `_finished` refs)
- Possibly `shared/visual_layer_state.py` (DELETE if orphaned)
- Possibly `tests/test_studio_compositor.py` (edit — remove tests for deleted code)

**Phase 1b (content backend unify):**
- `agents/studio_compositor/sierpinski_loader.py` (edit — replace `_update_manifest` with `inject_jpeg` calls; remove `CONTENT_DIR`/`ACTIVE_DIR`/`MANIFEST_PATH` constants)
- `agents/imagination_resolver.py` (edit — delete `write_slot_manifest`, remove call from `resolve_references_staged`, possibly simplify staging→active dance)
- `agents/reverie/content_injector.py` (verify `inject_jpeg` has required `ttl_ms` param)
- `hapax-logos/crates/hapax-visual/src/content_textures.rs` (DELETE)
- `hapax-logos/crates/hapax-visual/src/lib.rs` (edit — remove mod declaration)
- `hapax-logos/src-imagination/src/main.rs` (edit — remove ContentTextureManager field/init/poll/tick/legacy_opacities)
- `hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs` (edit — simplify precedence, remove args)
- `tests/test_imagination_resolver.py` (edit — delete 6 slot-manifest tests)
- `scripts/smoke_test_reverie.py` (port or delete)

**Phase 1c (content slot opt-in):**
- `agents/shaders/nodes/content_layer.json` (edit — add `requires_content_slots: true`)
- `agents/shaders/nodes/sierpinski_content.json` (edit — add `requires_content_slots: true`)
- `agents/effect_graph/registry.py` (edit — `LoadedShaderDef.requires_content_slots` field)
- `agents/effect_graph/wgsl_compiler.py` (edit — replace hardcoded tuple with registry lookup; propagate to plan)
- `hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs` (edit — PlanPass adds field, bind group selector uses it)
- `tests/effect_graph/test_smoke.py` (edit — add test for generic content slot opt-in)

Total files touched across all three sub-phases: ~20 files.

---

## Appendix B: Commit message template

Each commit follows conventional commits format with a phase-scoped prefix:

```
refactor(phase-1a): delete YouTubeOverlay and PIP_EFFECTS dead paths

YouTubeOverlay was fully defined in fx_chain.py but never invoked.
_pip_draw only renders _album_overlay and _token_pole. The class plus
its 5 PiP effect stylization functions (~260 lines) are unused.

Verified via: rg -w YouTubeOverlay, rg -w PIP_EFFECTS. Only hits are
the class definition itself and the dead `_yt_overlay = None` in
build_inline_fx_chain.

Part of compositor unification epic Phase 1a (dead code cleanup).
Spec: docs/superpowers/specs/2026-04-12-phase-1-cleanup-unify-design.md
Epic: docs/superpowers/plans/2026-04-12-compositor-unification-epic.md
```

PRs into the epic branch use the same convention in titles and descriptions.
