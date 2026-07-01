# Content-driven, fit-to-purpose homage wards

- **Date:** 2026-06-21
- **Status:** design approved (operator), pending implementation plan
- **Scope:** the Screwm/CNS homage-ward geometry + rendering (`generate-screwm-map.py`, the media-mount contracts, `media_pane_brush` chrome, the ward-atlas cell layout). One implementation plan.

## Problem

Every homage ward currently renders as a **placard**: a uniform `HOMAGE_TILE_W×HOMAGE_TILE_H = 960×540` (16:9) BSP tile (`ward_pane_dimensions()` returns the constant for all wards; `_apply_homage_wall_layout` splays uniform tiles), with the non-content faces textured `MEDIA_RECEIVER_EDGE_TEX = "scroom"` — visible geometric substrate. Content shapes vary widely (camera 16:9, ticker 84:11, waveform 4:1, IR 1:1, atlas 2:1), so forcing every ward into one 16:9 tile letterboxes/crops the content and exposes the `scroom` chrome — the ward reads as a frame around content, not as the content.

## Goal (operator directive, 2026-06-21)

1. No ward looks like a placard by default — **content is shown, not geometric substrate.**
2. Content is **projected at a size and shape appropriate to the content itself.**
3. The **ward's own shape and size are fit to purpose**, derived from the content and the ward's purpose.

## Design

### 1. Sizing/shaping model (per ward)

Each ward derives its geometry from two inputs:

- **Shape** = the content's `source_aspect` (from the media-mount). The truth-bearing face *is* that aspect, so content fills it with no letterbox or pad. Aspect is authoritative; the ward is never forced to 16:9.
- **Size** = the tier's target visual angle, **bounded by what the content can show legibly**:
  - `tier_angle` = the tier's target visual angle (table below).
  - `legibility_max_angle = native_content_px / minimum_media_px_per_degree` — above this the content is stretched below the framework's px/degree floor (blurry).
  - `inspection_min_angle = minimum_inspection_visual_angle_deg` — below this it is unreadable.
  - `ward_angle = clamp(tier_angle, inspection_min_angle, legibility_max_angle)`
  - `W = 2 · review_distance · tan(ward_angle / 2)`; `H = W / source_aspect`
  - Low-resolution content (e.g. the 340 px IR feeds) is naturally capped small by `legibility_max`; high-resolution content (cameras, atlas, OARB) can fill its tier. This is "fit to content" made quantitative — the content's own resolution bounds its legible size.

The framework JSON (`config/screwm-spatiotemporal-framework.json`) already carries the angular targets — `target_hero_media_visual_angle_deg_max`, `target_primary_media_visual_angle_deg`, `minimum_inspection_visual_angle_deg`, `minimum_media_px_per_degree`. Tiers map onto these; SECONDARY/AMBIENT angle values are added if absent. The flat-mount validator already enforces `physical_width == computed visual-angle width` + the px/degree floor, so the build gate keeps every mount honest.

### 2. Purpose tiers (operator-approved; per-ward assignment adjustable)

| Tier | Target visual angle | Wards |
|---|---|---|
| Hero | ~50° (`target_hero_media_visual_angle_deg_max`) | OARB (`aoa-media-sphere`) — the object of mutual attention |
| Primary | ~24° (`target_primary_media_visual_angle_deg`) | the 6 cameras (`brio-*`, `c920-*`); the atlas-instrument panel (`ward-atlas`); the speech-waveform (`speech-waveform`, a wide 4:1 band) |
| Secondary | ~15° (`minimum_inspection_visual_angle_deg`) | reverie (`reverie-field`); the 3 IR wards (`brio-*-ir-ward`, 1:1 squares) |
| Ambient | ~10° band (legibility-of-text-driven height; full content width) | the 3 tickers (`*-ticker`, 84:11 thin bands) |

The AoA tetrix lattice (`aoa-fractal-face-atlas`) is the central 3-D structure, not a flat content ward, and is out of this model's scope (it is governed by its own translucency/occlusion contract).

### 3. No-placard rendering

`media_pane_brush` paints the live texture on the single front face and `MEDIA_RECEIVER_EDGE_TEX` on the other five. Change the receiver edge from `scroom` to the existing **`NO_DRAW_SHELL_TEX`** (already used for `level_ledge_tex` no-draw shells) so the non-content faces are invisible. Combined with aspect-matched faces (content fills, no letterbox), the ward *is* the content — zero substrate, border, or chrome.

### 4. Atlas internals (content-shaped cells)

The 36 instrument wards must share one atlas texture (`ward-atlas`, slot 8) because the live-texture engine is hard-capped at `SLOT_COUNT=17` (all 17 slots used). Within that constraint:
- The atlas **panel** is sized to its 2:1 content via the model above (Primary tier).
- Inside the atlas renderer (`quake-live-ward-atlas-source.py` / the Rust `screwm_ward_atlas`), cells are laid out **by content/purpose** — varied cell sizes/aspects packed into the atlas, replacing the uniform 4×9 grid. Each instrument reads fit-to-purpose within the shared panel. (This is the largest sub-change and may be staged after the wall-ward geometry.)

### 5. Wall layout (varied-size packing)

Replace the uniform-tile splay in `_apply_homage_wall_layout` with a **per-wall bin-packer** that places the now-varied-size/aspect wards non-overlapping, each facing inward, preserving the operator's wall assignment (camera bank on the front wall; instruments/tickers/reverie/IR distributed across the other three). Rows pack by height; the packer guarantees no overlap and reports any ward that does not fit (fail loud, never silently clip).

### 6. Validation / testing

- `generate-screwm-map.py` + the spatiotemporal validator must pass (the flat-mount `physical_width == computed visual-angle width` + px/degree-floor checks become the sizing gate).
- A no-overlap assertion over the packed ward rectangles per wall.
- Witness frame-grab from `/dev/video52` after the v4l2 renderer reload, confirming: no `scroom` substrate visible; each ward shows content at its own aspect; the tier hierarchy reads.

## Files to change

- `scripts/generate-screwm-map.py` — the sizing model (`ward_pane_dimensions` → aspect+tier+legibility), the per-wall packer (`_apply_homage_wall_layout`), the no-draw edge (`MEDIA_RECEIVER_EDGE_TEX` use in `media_pane_brush`), a per-ward tier table.
- `config/screwm-quake-media-mounts.json` — each mount's `physical_width` (and any flat-receiver fields) recomputed for its tier+aspect so the validator passes; a `tier` field per mount.
- `config/screwm-spatiotemporal-framework.json` — add SECONDARY/AMBIENT visual-angle targets if not present.
- `scripts/quake-live-ward-atlas-source.py` (and/or the Rust atlas renderer) — content-shaped cell layout (staged sub-change).
- `assets/quake/scripts/hapax_live_media.shader` — only if `NO_DRAW_SHELL_TEX` needs a stanza.

## Risks / constraints

- **17-slot live-texture cap** — instruments stay atlas-shared; no per-instrument wall wards without an engine rebuild (out of scope).
- **Validator coupling** — every mount's declared `physical_width` must equal its computed visual-angle width for its tier or the map build fails (this is the intended gate, but each mount must be updated in lockstep with the model).
- **Live-renderer restart** — deploy requires a `hapax-darkplaces-v4l2` restart (a brief `/dev/video52` blip); gated on a clean validated build.
- **Atlas-renderer change** is the heaviest piece and may be deferred to a second phase so the wall-ward geometry/no-placard ships first.
- **Review distance varies** (the roji-walk camera moves); use the framework's vantage basis (as the existing validator does), not a single hardcoded distance.

## Out of scope

- The AoA tetrix lattice geometry/translucency (its own contract).
- Per-instrument live-texture slots (blocked by the 17-slot cap).
- The director/ticker content pipeline (separate; tickers here get correct geometry, not new content).
