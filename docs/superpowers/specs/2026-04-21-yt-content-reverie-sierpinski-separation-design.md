# YouTube Content — Reverie/Sierpinski Slot-Family Separation

**Date:** 2026-04-21
**Status:** Design, operator-directed ("make sure we are not trodding on Reverie's original purpose and that Hapax has a way to front YT vids being shown")
**Governing anchors:** `CLAUDE.md § Unified Semantic Recruitment` (Reverie is substrate, not recruitable); `CLAUDE.md § Studio Compositor` (Sierpinski is the canonical YT-frame ward); HOMAGE Phase 12 (task #124 — "Reverie retains its purpose despite being a ward").

---

## 1. Problem

YouTube video frames currently render into Reverie's `content_layer` shader pass, overlaid on the generative substrate. That violates Reverie's substrate-only contract and usurps space that should belong to Sierpinski (the HOMAGE ward spec'd to feature YouTube frames in a triangular composition).

**Root cause (from 2026-04-21 audit):** `content_slot_0..3` are globally untagged texture bindings in the wgpu render graph. Both `content_layer.wgsl` (Reverie substrate) and `sierpinski_content.wgsl` declare `requires_content_slots: true` at `@group(1) @binding(2..5)`. The Rust `ContentSourceManager` populates those bindings from every `/dev/shm/hapax-imagination/sources/*/` path indiscriminately — so any shader requesting content slots gets all active sources, regardless of semantic fit.

**Secondary issue:** `sierpinski_content` is not registered in `presets/reverie_vocabulary.json` nor in `agents/reverie/_satellites.py`. The shader file exists, the node manifest exists, but there's no recruitment path. Sierpinski never runs. YT frames therefore render only through Reverie, which is the very violation the operator flagged.

**Tertiary issue:** No affordance exists for "front this YT video." The `sierpinski_loader` tags frames with `["youtube", "sierpinski"]` but the tag is informational only — it does not gate which shaders consume the source.

---

## 2. Design

### 2.1 Principle — slot-family separation

Split the global content-slot pool into named families. Each shader declares the family its content bindings belong to. Rust populates per-family pools from separate SHM prefixes.

**Families for v1:**
- `narrative` — substrate content for Reverie: text, recalled knowledge, imagination fragments. SHM prefix: `/dev/shm/hapax-imagination/sources/narrative-content-*/`.
- `youtube_pip` — featured YT video frames for Sierpinski and future YT-capable wards. SHM prefix: `/dev/shm/hapax-imagination/sources/yt-slot-*/`.

Future families (camera-pip, album-art, etc.) can be added with the same pattern.

### 2.2 Schema additions

**`agents/effect_graph/registry.py`** — add `slot_family: str = "narrative"` to the pass metadata (default is backward-compatible; existing plans without the field continue to bind narrative content).

**Node manifests:**
- `agents/shaders/nodes/content_layer.json` — add `"slot_family": "narrative"` explicitly (no behavior change; makes the contract visible).
- `agents/shaders/nodes/sierpinski_content.json` — add `"slot_family": "youtube_pip"`.

**`content_layer.wgsl`** — prepend a comment documenting its substrate contract: narrative/memory/imagination only; YT frames are routed to Sierpinski via the media slot family.

### 2.3 Rust runtime changes

**`hapax-logos/crates/hapax-visual/src/content_sources.rs`** — `ContentSourceManager` gains a `get_for_family(family: &str) -> Vec<&ContentSource>` method that filters sources by SHM-path prefix. Existing `list()` stays for backward compatibility and is used only for tests.

**`hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs`** (around lines 1690–1710) — when binding a pass's content slots, read `pass.slot_family` (default `"narrative"`) and pull textures via `get_for_family(family)` instead of the global pool.

Safety guard: if a pass requests a slot but the family is empty, bind a 1×1 transparent placeholder texture and log a WARNING once per pass per startup. Do NOT fall back to a different family — that re-introduces the bug.

### 2.4 Sierpinski recruitment activation

Independent of the slot-family fix, Sierpinski itself must run. That requires:

- Register `sat_sierpinski_content` as a recruitable satellite in `agents/reverie/_satellites.py` (follow the existing `sat_*` pattern — Gibson-verb affordance description, recruitment gates).
- Add a satellite entry (not a core-vocabulary entry) to `presets/reverie_vocabulary.json` so the mixer can recruit it. **Satellite prefix mandatory** per `CLAUDE.md § Reverie Vocabulary Integrity`: any dynamic Sierpinski node is `sat_sierpinski_content`, never `content: sierpinski_content`.

Without this step, PR-1/PR-2 cleanly separate the slot pools but Sierpinski still never renders.

### 2.5 Hapax-authored fronting mechanism

A future Phase 2 (out of scope for the immediate fix but spec'd here for continuity):

**Register a capability:**
```yaml
affordance_name: content.yt.feature
gibson_verb: "to elevate a YouTube video thumbnail to attention-peak presence at a scene cut-point"
domain: expression
OperationalProperties:
  medium: visual
  consent_required: false
```

**Impingement family `yt.feature`** with per-impingement `slot_id` field. Director emits when scene cutpoint aligns with an active YT slot. Recruitment fires `ContentCapabilityRouter.activate_youtube(slot_id, level)` which writes `/dev/shm/hapax-compositor/featured-yt-slot` — Sierpinski reads and elevates the active slot's opacity/animation.

This makes YT fronting a first-class affordance on par with ward.position, camera.hero, etc. Out of scope for the slot-family fix; tracked separately.

---

## 3. Scope

**In scope (Phase 1 — the fix):**
- Slot-family schema + runtime split
- Reverie's `content_layer` becomes narrative-only in contract + documentation
- Sierpinski's recruitment wiring so it actually runs when the affordance pipeline picks it

**Out of scope:**
- Hapax-authored YT featuring affordance (Phase 2, §2.5)
- New YT-dedicated HOMAGE ward beyond Sierpinski (possible future work; not needed for the fix)
- Camera-PiP separation into its own family (can be added later following the same pattern)
- Reverie content_layer becoming a recruitable capability (explicitly NOT recruitable per substrate contract)

---

## 4. Acceptance

- [ ] YouTube frames no longer composite into Reverie's output (visual regression: diff frames of the vocabulary graph with and without active YT slots — should be identical).
- [ ] Sierpinski renders YT frames in its triangular composition when recruited.
- [ ] `content_layer.wgsl` has a comment documenting its substrate contract.
- [ ] Existing plans without `slot_family` continue to parse and bind narrative-family content (backward compat).
- [ ] Safety guard: an empty family binds transparent placeholder + WARNING log (not a fallback to a different family).

---

## 5. References

- Audit source: 2026-04-21 `Explore` agent output (session `a3ab7c93df8e3753a`).
- `agents/studio_compositor/sierpinski_loader.py:162-198` — current YT frame injection, tagged but non-gating.
- `agents/shaders/nodes/content_layer.wgsl:23-29, 168-174` — `@group(1) @binding(2..5)` content-slot declarations, `sample_and_blend_slot` calls.
- `agents/shaders/nodes/sierpinski_content.wgsl:71-125` — complete Sierpinski shader, unused.
- `agents/shaders/nodes/sierpinski_content.json` — node manifest exists, declares `requires_content_slots: true`.
- `hapax-logos/crates/hapax-visual/src/content_sources.rs:104-150` — `ContentSourceManager` global source pool.
- `hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs:1128-1129, 1695-1710` — binding site where family-aware filtering goes.
- `presets/reverie_vocabulary.json` — currently no sierpinski_content satellite entry.
- `agents/reverie/_satellites.py` — currently no `sat_sierpinski_content` recruitment path.
- Memory: `project_reverie.md`, `project_splattribution` (related — SPLATTRIBUTION for attribution text is orthogonal to frame routing).
