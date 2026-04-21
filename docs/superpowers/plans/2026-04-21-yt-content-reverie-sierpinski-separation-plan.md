# YT Content — Reverie/Sierpinski Separation — Implementation Plan

**Filed:** 2026-04-21
**Spec:** `docs/superpowers/specs/2026-04-21-yt-content-reverie-sierpinski-separation-design.md`
**Total estimate:** ~5 hours, 3 PRs (2 in Phase 1, 1 in Phase 2).

---

## Phase 1A — Schema + Python (~2h)

Commit: `feat(effect_graph): add slot_family to PlanPass schema + tag content_layer narrative + sierpinski_content youtube_pip`

- [ ] `agents/effect_graph/registry.py` — add `slot_family: str = "narrative"` field to the pass dataclass / Pydantic model that represents a compiled pass. Default keeps existing plans parsing unchanged.
- [ ] `agents/effect_graph/wgsl_compiler.py` — propagate `slot_family` from the node manifest through `_build_passes_for_target` into the emitted pass descriptor.
- [ ] `agents/shaders/nodes/content_layer.json` — add `"slot_family": "narrative"` (explicit; currently implicit via default).
- [ ] `agents/shaders/nodes/sierpinski_content.json` — add `"slot_family": "youtube_pip"`.
- [ ] `agents/shaders/nodes/content_layer.wgsl` — prepend a comment:
  ```
  // Reverie substrate — narrative, memory, imagination only.
  // YouTube frames are routed to Sierpinski via the youtube_pip family.
  // Do NOT add YT-frame consumption logic here.
  ```
- [ ] `tests/effect_graph/test_slot_family_schema.py` — new. Asserts:
  - Default `slot_family` is `"narrative"` on a pass with no explicit field.
  - `sierpinski_content.json`'s `slot_family` is `"youtube_pip"` after compile.
  - `content_layer.json`'s `slot_family` is `"narrative"` after compile.
  - Plans without the field still compile (backward-compat).

**PR 1** — `feat/slot-family-schema` — Python only.

---

## Phase 1B — Rust runtime (~3h)

Commit: `feat(visual): filter content_slot bindings by slot_family family`

- [ ] `hapax-logos/crates/hapax-visual/src/content_sources.rs`:
  - Add `get_for_family(&self, family: &str) -> Vec<&ContentSource>` — filters by SHM-path prefix: `narrative-content-*` → `narrative`, `yt-slot-*` → `youtube_pip`.
  - Keep `list()` intact for tests + any non-family callers.
- [ ] `hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs` (around lines 1690–1710):
  - Read `pass.slot_family` (deserialized from the plan JSON).
  - In the content-slot binding loop, call `content_sources.get_for_family(family)` instead of pulling from the global pool.
  - If the family is empty, bind a 1×1 transparent placeholder texture (allocate once at startup, reuse). WARN once per (pass_id, family) per startup; include the family name.
- [ ] `hapax-logos/crates/hapax-visual/src/plan.rs` (or wherever pass deserialization lives) — add `slot_family: String` field, default `"narrative"` if missing.
- [ ] `tests/crate_tests/content_family_routing.rs` (or adjacent test file):
  - Pass declaring `slot_family: "narrative"` receives only narrative-content sources.
  - Pass declaring `slot_family: "youtube_pip"` receives only yt-slot sources.
  - Empty family → transparent placeholder, no panic.
  - Missing field (legacy plan) → defaults to narrative.
- [ ] `cargo test` green in the `hapax-visual` crate.
- [ ] Manual verification: live stream shows YT frames in Sierpinski (after Phase 1C) and NOT in Reverie's generative substrate.

**PR 2** — `feat/slot-family-runtime` — Rust changes.

---

## Phase 1C — Sierpinski recruitment activation (~1h)

Commit: `feat(reverie): register sat_sierpinski_content as recruitable satellite`

- [ ] `agents/reverie/_satellites.py` — register `sat_sierpinski_content` following the existing `sat_*` pattern: Gibson-verb affordance description, recruitment gates. Gibson verb candidate: "to tile a YouTube frame inside a Sierpinski triangle composition during scene cut-points".
- [ ] `presets/reverie_vocabulary.json` — add a satellite entry (NOT a core-vocabulary entry) for `sat_sierpinski_content`. Must use the `sat_` prefix per `CLAUDE.md § Reverie Vocabulary Integrity`.
- [ ] `tests/reverie/test_sat_sierpinski_registration.py` — assert the satellite registers + is affordance-pipeline-discoverable + uses the `sat_` prefix.
- [ ] Verify `SatelliteManager.maybe_rebuild()` doesn't re-inject a core-prefix variant (existing invariant, regression-pin).

**PR 3** — `feat/reverie-sat-sierpinski-recruitment`.

---

## Phase 2 (deferred) — Hapax-authored YT featuring affordance

Filed as a follow-on under `content.yt.feature` affordance + `yt.feature` impingement family per spec §2.5. Track as separate cc-task; operator-reviewed after Phase 1 is live and the separation proves clean.

**Estimated scope:** ~300 LOC, new capability registration, director impingement emission at scene cut-points, `ContentCapabilityRouter.activate_youtube(slot_id, level)` dispatch, Sierpinski reading `/dev/shm/hapax-compositor/featured-yt-slot`.

---

## Acceptance criteria (Phase 1 complete)

- [ ] Slot-family schema + Rust routing + Sierpinski recruitment all green locally.
- [ ] Visual regression: render the vocabulary graph with active YT slots — Reverie output identical to the no-YT case (YT frames no longer composite into Reverie).
- [ ] Live stream: YT frame visible in Sierpinski's triangular composition.
- [ ] No panics / no missing-family errors in the compositor journal.
- [ ] CI green (ruff, pyright, cargo test).

---

## LOC estimate

| Phase | Python | Rust | Tests | Total |
|-------|--------|------|-------|-------|
| 1A (schema) | ~40 | 0 | ~40 | ~80 |
| 1B (runtime) | 0 | ~120 | ~80 | ~200 |
| 1C (recruitment) | ~50 | 0 | ~40 | ~90 |
| **Phase 1 total** | **~90** | **~120** | **~160** | **~370** |
| Phase 2 (deferred) | ~250 | ~50 | ~80 | ~380 |
