# Effect Graph Vestigial Feature Removal — Boundary Map & Audit

**Date:** 2026-05-21
**Author:** epsilon
**Task:** 202605181733-effect-graph-dead-phase0-research-audit
**Parent request:** REQ-202605181733-effect-graph-dead-feature-removal
**Companion:** `docs/research/2026-04-14-effect-graph-dead-feature-inventory.md` (original inventory)

## Summary

All 7 vestigial features identified in the 2026-04-14 inventory have been fully removed or simplified. The removal was accomplished across 7 commits (PRs #818, #823, #824, #825, #827, #828, #835). Total net deletion: **1,062 lines** (exceeds the ~800-line estimate by 33%).

**Verdict: no remaining dead code to remove. Phase 1 implementation work is complete.**

## Removal Boundary Map

### DR-1: LayerPalette

| Field | Value |
|-------|-------|
| Status | **REMOVED** — safe, no live references |
| Original locations | `agents/effect_graph/types.py`, `agents/effect_graph/runtime.py`, 29 preset JSON files |
| Removal commits | `eb23767b3` (PR #824), `16a7b4b84` (PR #835) |
| Lines removed | 194 net |
| Residual references | None |

LayerPalette type, runtime `_layer_palettes` dict, and `layer_palettes` keys in all 29 preset JSON files were deleted. No downstream consumer existed — 0/28 presets declared layer palettes.

### DR-2: TemporalSlotState

| Field | Value |
|-------|-------|
| Status | **REMOVED** — safe, no live references |
| Original location | `agents/effect_graph/temporal_slot.py` (62 lines), `tests/test_temporal_slot.py` (42 lines) |
| Removal commit | `4c90154ff` (PR #818) |
| Lines removed | 104 net |
| Residual references | None |

Entire file deleted. Zero imports existed at time of removal — glfeedback Rust plugin owns ping-pong buffer management.

### DR-3: temporal_buffers declaration

| Field | Value |
|-------|-------|
| Status | **REMOVED** — safe, no live references |
| Original locations | 60+ shader node JSON manifests, `agents/effect_graph/registry.py`, `agents/effect_graph/compiler.py`, `agents/effect_graph/types.py` |
| Removal commit | `25bdcd2eb` (PR #827) |
| Lines removed | 11 net |
| Residual references | None |

Schema field stripped from all shader JSON files. Passthrough code in registry, compiler, and types removed. glfeedback Rust plugin allocates 1 buffer per slot regardless of declared value — the field was never consumed at runtime.

### DR-4: find_slot_for_node prefix-matching

| Field | Value |
|-------|-------|
| Status | **SIMPLIFIED** — dead path removed, function retained (live) |
| Original location | `agents/effect_graph/pipeline.py:222-237` |
| Removal commit | `73f2f33e2` (PR #823) |
| Lines removed | 7 net (shared with DR-5) |
| Residual references | Docstring at `pipeline.py:455` notes prior existence (informational only) |

The `pN_` prefix-stripping second pass was removed. `find_slot_for_node()` now performs exact match only. The function itself remains live — it is used by `update_node_uniforms()`, `get_graph_state()`, and other pipeline methods.

Note: `registry.py:30` and `wgsl_compiler.py:192` reference "prefix matching" in docstrings, but these describe the **live** content-slot SHM-path family routing feature (slot_family), not the dead preset chain composition prefix matching.

### DR-5: merge_default_modulations "pick LAST matching"

| Field | Value |
|-------|-------|
| Status | **SIMPLIFIED** — dead path removed, function retained (live) |
| Original location | `agents/studio_compositor/effects.py:125-161` |
| Removal commit | `73f2f33e2` (PR #823) |
| Lines removed | 7 net (shared with DR-4) |
| Residual references | Docstring at `effects.py:179` notes prior existence (informational only) |

The `dict[str, list[str]]` type_to_ids + `matching_ids[-1]` selection was replaced with a flat `dict[str, str]` direct lookup. `merge_default_modulations()` remains live at `effects.py:166` — it merges `_default_modulations.json` into preset graphs. The function is called from `effects.py:110`.

### DR-6: needs_dedicated_fbo

| Field | Value |
|-------|-------|
| Status | **REMOVED** — safe, no live references |
| Original locations | `agents/effect_graph/compiler.py:77,291`, `agents/effect_graph/types.py:ExecutionStep` |
| Removal commit | `5b62b984e` (PR #825) |
| Lines removed | 44 net |
| Residual references | None |

Field deleted from `ExecutionStep` dataclass and its computation (fanout count > 1) removed from compiler. No consumer existed — the field was computed but never read.

### DR-7: PresetInput / resolve_preset_inputs

| Field | Value |
|-------|-------|
| Status | **REMOVED** — safe, no live references |
| Original locations | `agents/effect_graph/types.py`, `agents/effect_graph/compiler.py`, `agents/studio_compositor/effects.py`, `agents/studio_compositor/fx_chain.py` (90-line appsrc branch), `tests/effect_graph/test_preset_inputs.py` (234 lines), `tests/studio_compositor/test_appsrc_pads.py` (225 lines), `tests/studio_compositor/test_edge_cases.py` (51 lines) |
| Removal commit | `e8fccb913` (PR #828) |
| Lines removed | 717 net |
| Residual references | None |

Largest single removal. The entire source-registry → preset → glvideomixer appsrc pad pipeline was dead end-to-end. 0/28 presets declared `inputs`. Combined with layout-declared cairo sources never starting, the whole `build_source_appsrc_branches` infrastructure was unreachable.

## Line-Count Summary

| DR # | Feature | Lines Removed (net) | Status |
|------|---------|-------------------:|--------|
| DR-1 | LayerPalette | 194 | Removed |
| DR-2 | TemporalSlotState | 104 | Removed |
| DR-3 | temporal_buffers | 11 | Removed |
| DR-4 | prefix-matching | 7 | Simplified |
| DR-5 | merge_default "pick LAST" | 7 | Simplified |
| DR-6 | needs_dedicated_fbo | 44 | Removed |
| DR-7 | PresetInput / resolve_preset_inputs | 717 | Removed |
| | **Total** | **1,062** | |

Acceptance criterion: ≥ 700 lines removed (within 15% of ~800). Actual: 1,062 lines — **criterion met**.

## Blocking References

**None.** All 7 features are fully removed or simplified. No live code references to dead types or dead code paths remain. Two historical docstring comments (`pipeline.py:455`, `effects.py:179`) reference prior existence for context but do not constitute blocking references.

## Root Cause

All 7 features trace to a single unshipped architectural pattern: **preset chain composition** (`pN_` prefixed multi-instance nodes, per-layer palette grading, main-layer source-registry binding, multi-buffer temporal accumulation). This pattern was designed and partially implemented but never adopted in the preset library (0/88 current presets use any chain composition feature).

## Recommendation

Phase 1 implementation plan (task `202605181733-effect-graph-dead-phase1-impl-plan`) and downstream removal tasks (phase 2/3) should be closed as already-complete. The removal work was accomplished in PRs #818, #823, #824, #825, #827, #828, #835 prior to this audit.
