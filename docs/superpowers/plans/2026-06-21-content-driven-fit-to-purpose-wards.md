# Content-driven, fit-to-purpose homage wards — Implementation Plan

> **For agentic workers:** implement task-by-task; each task ends at the build/validator/witness gate noted. Steps use `- [ ]` tracking.

**Goal:** Replace the uniform 16:9 placard tiles with wards whose shape = their content aspect and whose size = a purpose tier clamped to the content's legibility, with no geometric substrate.

**Architecture:** A per-ward geometry model in `generate-screwm-map.py` (aspect + tier-angle + legibility-cap → world W/H), a varied-size per-wall packer replacing the uniform splay, the receiver edge switched to the no-draw shell, media-mount `physical_width` brought into lockstep so the existing flat-mount validator is the gate, and (phase 2) content-shaped atlas cells.

**Tech Stack:** Python map generator (qbsp/light/vis), Quake `.map` brushes + WAD, JSON mount/framework contracts, the `hapax-darkplaces-v4l2` renderer.

## Global Constraints (verbatim from spec)
- Shape = content `source_aspect`; size never forced to 16:9.
- Size = `clamp(tier_angle, minimum_inspection_visual_angle_deg, legibility_max_angle)`, `legibility_max_angle = native_px / minimum_media_px_per_degree`.
- 17-slot live-texture cap: instruments stay atlas-shared (no per-instrument slots).
- No-overlap is fail-loud; never silently clip a ward.
- Deploy = clean validated build → `hapax-darkplaces-v4l2` restart (gated on the build passing).
- Validator coupling: every mount's `physical_width` must equal its computed visual-angle width or the build fails.

## File Structure
- `scripts/generate-screwm-map.py` — tier table, `ward_geometry()`, `ward_pane_dimensions()` rewrite, `_apply_homage_wall_layout()` packer, `media_pane_brush` edge → no-draw.
- `config/screwm-quake-media-mounts.json` — per-mount `tier` + recomputed `physical_width`.
- `config/screwm-spatiotemporal-framework.json` — SECONDARY/AMBIENT angle targets if absent.
- `scripts/quake-live-ward-atlas-source.py` (phase 2) — content-shaped cell layout.

---

## PHASE 1 — Wall-ward geometry + no-placard (ships independently)

### Task 1: Tier table + per-ward geometry model
**Files:** Modify `scripts/generate-screwm-map.py` (near `ward_pane_dimensions`, ~1781; constants near `HOMAGE_TILE_*` ~475).
**Interfaces — Produces:** `WARD_TIER: dict[str,str]` (ward-id → hero|primary|secondary|ambient); `tier_angle_deg(tier)->float` (reads framework targets); `ward_geometry(aspect:tuple, native_px:int, tier:str)->tuple[int,int]` returning `(W,H)` world units.
- [ ] Add `WARD_TIER` mapping every mount id to a tier per the spec table (OARB hero; cameras/ward-atlas/speech-waveform primary; reverie-field + `*-ir-ward` secondary; `*-ticker` ambient).
- [ ] Add `tier_angle_deg()` pulling `target_hero_media_visual_angle_deg_max` / `target_primary_media_visual_angle_deg` / `minimum_inspection_visual_angle_deg` from `SPATIOTEMPORAL_FRAMEWORK["media_constraints"]`; AMBIENT from a new `target_ambient_media_visual_angle_deg` (Task 5).
- [ ] Add `ward_geometry(aspect, native_px, tier)`: `ang = clamp(tier_angle_deg(tier), min_inspection, native_px/min_px_per_deg)`; `W = round(2*REVIEW_DISTANCE*tan(radians(ang)/2))`; `H = round(W*aspect[1]/aspect[0])`. Use the framework's vantage basis for `REVIEW_DISTANCE`.
- [ ] Rewrite `ward_pane_dimensions(idx)` to look up the mount for `idx`, read its `source_aspect`+`texture_size`+`tier`, return `ward_geometry(...)`.
- **Gate:** import the module; print `ward_geometry` for camera(16:9,1280,primary), ticker(84:11,1344,ambient), IR(1:1,340,secondary), OARB(16:9,2048,hero). Assert: camera H≈9/16·W; ticker very wide & short; IR capped small (legibility_max binds); OARB largest.

### Task 2: Media-mount `physical_width` lockstep + `tier` field
**Files:** Modify `config/screwm-quake-media-mounts.json`.
**Interfaces — Consumes:** Task 1's `ward_geometry`.
- [ ] For each mount, add `"tier"` per `WARD_TIER` and set `physical_width` = `ward_geometry(...)[0]` (so the flat-mount validator's `physical_width == computed visual-angle width` holds). Recompute via a one-off script that imports Task 1's `ward_geometry` and rewrites each mount's `physical_width`, preserving JSON formatting (indent=2).
- **Gate:** `python3 scripts/generate-screwm-map.py --mode rnd` (no `--compile`) exits 0 with NO `flat media mount … physical width` / `below px/degree` failures.

### Task 3: Per-wall varied-size packer
**Files:** Modify `scripts/generate-screwm-map.py::_apply_homage_wall_layout` (~528).
**Interfaces — Consumes:** Task 1 `ward_pane_dimensions`. Produces: same `WARD_GARDEN_LAYOUT`/`SOURCE_ANCHORS` mutation contract (idx → (x,y,z,facing), src["pos"/"facing"/"w"/"h"]).
- [ ] Replace the uniform-grid body with a shelf/bin packer: for each wall (front=cameras, then right/back/left for the rest per current assignment), place each ward's `(W,H)` left-to-right into height-sorted shelves, advancing rows; centre each on its face plane; `facing` per wall. Set each `src["w"]/["h"]` (cameras) and each ward idx's `(x,y,z,facing)` from the packed rect centre.
- [ ] Add `assert` no two packed rects on a wall overlap; raise `SystemExit` naming any ward that does not fit the wall.
- **Gate:** import-run the layout; assert 0 overlaps; print per-wall occupancy; confirm every ward placed.

### Task 4: No-placard receiver edge
**Files:** Modify `scripts/generate-screwm-map.py` (`MEDIA_RECEIVER_EDGE_TEX` use in `media_pane_brush`, ~1275/1401).
- [ ] Change the receiver/pane non-content faces from `MEDIA_RECEIVER_EDGE_TEX` (`scroom`) to `NO_DRAW_SHELL_TEX` so only the content face draws. Keep `MEDIA_RECEIVER_EDGE_TEX` for any non-receiver decorative brushes (raked beds) untouched — scope the change to the media-pane receiver faces only.
- **Gate:** generate the `.map`; grep a sample ward brush shows the content tex on one face and `NO_DRAW_SHELL_TEX` (not `scroom`) on the other five.

### Task 5: Framework AMBIENT angle target
**Files:** Modify `config/screwm-spatiotemporal-framework.json::media_constraints`.
- [ ] Add `target_ambient_media_visual_angle_deg` (band height for legible ticker text, e.g. 10) and `target_secondary_media_visual_angle_deg` (e.g. 15) if not already present; Task 1 reads them.
- **Gate:** `load_spatiotemporal_framework()` returns the keys; the validator still passes.

### Task 6: Build, validate, deploy, witness
- [ ] `python3 scripts/generate-screwm-wad.py` then `python3 scripts/generate-screwm-map.py --mode rnd --compile` — validator passes, qbsp/light/vis OK.
- [ ] Recompile `progs.dat` (fteqcc) only if a `.qc` changed (none expected in phase 1).
- [ ] `cp screwm-rnd.{bsp,lit} screwm.{bsp,lit}`; `scripts/install-darkplaces-screwm-assets.sh`; `systemctl --user restart hapax-darkplaces-v4l2.service`.
- [ ] Witness: `ffmpeg -f v4l2 -i /dev/video52 -frames:v 1` from review + forced wall vantages; confirm no `scroom` substrate, each ward shows content at its own aspect, tier hierarchy reads, no overlap/clip. Re-run `hapax-audio-routing-check` (should be untouched) as a no-regression check.

---

## PHASE 2 — Content-shaped atlas cells (deferrable)

### Task 7: Atlas internal content-shaped layout
**Files:** Modify `scripts/quake-live-ward-atlas-source.py` (the cell layout; the panel stays slot 8, 2:1).
- [ ] Replace the uniform 4×9 cell grid with a packer that sizes each instrument cell by its content/purpose (varied), packed into the 2048×2304 atlas; update the per-cell UV sub-rects the wall ward samples (or the meta the ward reads) so each instrument's wall sub-ward maps to its content-shaped cell.
- **Gate:** atlas `.json` meta lists all 36 cells `rendered` with non-uniform cell rects; no cell overlaps; the wall atlas sub-wards sample the correct cells.

### Task 8: Atlas deploy + verify
- [ ] Restart `hapax-quake-live-ward-atlas.service`; witness the atlas panel shows content-shaped instruments (not a uniform grid); all 36 legible.

---

## Self-review notes
- Spec coverage: shape (T1), size/legibility (T1), tiers (T1/T2), no-placard (T4), atlas cells (T7), packing (T3), validation (T2/T6). All covered.
- Phase 1 is independently shippable (the wall wards become content-shaped + no-placard without the atlas-internal change; the atlas panel still shows the current grid until phase 2).
- Risk: the validator lockstep (T2) must match T1's `ward_geometry` exactly — recompute mounts FROM the same function, never by hand.
