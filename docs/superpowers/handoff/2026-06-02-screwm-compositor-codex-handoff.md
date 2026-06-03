# 2026-06-02 Screwm/Compositor Codex Handoff

## Read This First

This handoff is for Claude Code picking up the Screwm/compositor work after Codex alpha. The operator explicitly redirected scope back to **compositor/screwm only** and asked for a thorough handoff before Claude continues.

Current state is **not complete**. Runtime and tests are in a much better place, but the latest visual witness still fails the operator's aesthetic requirement: broad colored line/beam geometry remains visible across the room. Do not call the Screwm "fullest expression" baseline met.

Worktree:

- Repo/worktree: `/home/hapax/projects/hapax-council--cx-alpha`
- Branch: `alpha/screwm-r6b-density-drift-coupling`
- HEAD at handoff: `7c428d0e8`
- Active governed task used for this work: `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/active/20260529-screwm-fullest-expression-build.md`
- Timestamp: `2026-06-02T10:28:44-05:00`

## Operator Requirements In Force

The key operator constraints from this session:

- Focus solely on compositor/screwm, not SDLC reform.
- Witness must be multi-POV and duration-sensitive. OBS alone is not enough; stale/frozen OBS was repeatedly observed.
- Drift must apply visibly to all geometry and edges: floors, ceilings, walls, AoA/OARB, wards, negative space, particulates, edges, surfaces.
- No fourth-wall/postprocess effects as release-grade expression.
- Floors, ceilings, and walls should have no color-filled surfaces. They should read as black/void with luminous/dynamic hex/grid lines and sparse stipple only.
- The grid should not read as scaffold or static structure; it should read as slightly effervescent light, synthwave-shifting, reactive to drift.
- Homage wards must not default to placards. Only inherently rectangular entities such as camera frames may remain rectangular. Truth-bearing live textures must not leak to side/end faces.
- AoA/OARB should be larger than earlier baseline, roughly one third of Screwm height, with perfect Sierpinski/tetrix geometry and independently operable facets.
- GPU/offload is load-bearing; CPU-bound video/compositing should be ported or avoided where possible.
- Current operator complaint at handoff: "there is NO lighting and what are these beams everywhere?"

## High-Level Narrative

The work initially focused on recovering a stalled/frozen OBS-visible Screwm pipeline. The actual renderer and media producers had become unreliable because watchdog/process management and source routing were fighting the intended runtime. After recovery, the X11 renderer was live and `/dev/video52` plus the OBS UDP media stream were active.

After that, the focus shifted to the user's aesthetic failure report: the scene looked anemic, under-lit, and full of broad colored beams that behaved like overlays or arbitrary geometry instead of surface/edge-bound drift. I investigated CSQC and the map generator. There were two separate beam sources:

1. CSQC pre-render additive polygon overlay systems (`screwm_draw_media_receiver_drift_fields`, `screwm_draw_hex_alignment_light_grid`, `screwm_draw_geometry_edge_pulses`, `screwm_draw_substrate_drift_pulses`) that draw world-space ribbons before `renderscene()`.
2. Generated BSP brush geometry: floor/ceiling hex line prisms and wall "beam" grid carriers using hot `geometry_signal_mark` WAD textures.

I gated the CSQC overlay systems off by default and dimmed/thinned the generated grid carriers. However, the final X11 witness still shows broad colored lines. The next person must continue lower in the map/material path.

## Runtime Recovery Changes Made

These changes were made earlier in this Codex run to stabilize the live route:

- `scripts/hapax-vram-watchdog`
  - Added allowlist entries so the watchdog does not kill live visual/inference processes under high VRAM:
    - `darkplaces-sdl`
    - `screwm-media-drift`
    - `screwm_media_drift`
    - `screwm-ward-atlas`
    - `screwm_ward_atlas`
    - `ffmpeg`
    - `obs`
    - `ollama`
    - activation-worktree Python paths
  - Added/updated `tests/scripts/test_hapax_vram_watchdog.py`.

- `systemd/units/hapax-screwm-media-drift.service`
  - Changed restart behavior to `Restart=always` so external `TERM`/watchdog termination does not leave final drift outputs stale.

- `systemd/units/hapax-darkplaces-v4l2.service`
  - Set `HAPAX_DARKPLACES_V4L2_DEVICE=/dev/video52`.
  - Set `HAPAX_DARKPLACES_V4L2_ENABLE=1`.

- Runtime deployments performed:
  - Copied `scripts/hapax-vram-watchdog` into activation worktree:
    `/home/hapax/.cache/hapax/source-activation/worktree/scripts/hapax-vram-watchdog`
  - Installed updated systemd units into:
    `/home/hapax/.config/systemd/user/`
  - Patched runtime drop-in:
    `/home/hapax/.config/systemd/user/hapax-darkplaces-v4l2.service.d/zzzzzz-screwm-xvfb-nvidia-visible.conf`
    to use `/dev/video52` and enable V4L2 output.
  - Copied `scripts/darkplaces-v4l2-xvfb.sh` into the activation worktree.
  - Restarted:
    - `hapax-screwm-media-drift.service`
    - `hapax-quake-live-aoa-atlas.service`
    - `hapax-quake-live-ward-atlas.service`
    - all six `hapax-quake-live-camera@*.service`
    - `hapax-darkplaces-bridge.service`
    - `hapax-darkplaces-v4l2.service`
    - `hapax-darkplaces-obs-media-stream.service`

- Rust visual binaries built and installed:
  - Built from `hapax-logos`:
    `cargo build --release -p hapax-visual --bin screwm_media_drift --bin screwm_ward_atlas`
  - Installed to:
    - `~/.local/bin/screwm-media-drift`
    - `~/.local/bin/screwm-ward-atlas`

Current service status at handoff:

```text
hapax-screwm-media-drift.service       active
hapax-quake-live-aoa-atlas.service     active
hapax-quake-live-ward-atlas.service    active
hapax-darkplaces-v4l2.service          active
hapax-darkplaces-obs-media-stream.service active
```

OBS was earlier forced onto the UDP media source:

- Scene: `Scene`
- Source: `DarkPlaces Screwm Media`
- Input: `udp://127.0.0.1:30552?fifo_size=1000000&overrun_nonfatal=1`
- Disabled sources during ensure: `Video Capture Device (V4L2)`, `DarkPlaces Screwm`

Do not rely on OBS as sole witness; the operator repeatedly observed stale/frozen/black OBS output.

## CSQC/Quake Runtime Changes

Files:

- `assets/quake/csqc/wards.qc`
- `assets/quake/config/autoexec.cfg`
- `assets/quake/qc/world.qc`
- `tests/scripts/test_screwm_csqc_wards.py`

Changes:

- Added CSQC gates:
  - `screwm_roaming_surface_pulses_enabled()`
  - `screwm_surface_grid_overlay_enabled()`
- Default config:
  - `set screwm_csqc_surface_grid_overlay 0`
  - `set screwm_csqc_roaming_surface_pulses 0`
  - `set screwm_csqc_theatre_spots 0`
  - `set screwm_csqc_full_expression_field 1`
  - `set screwm_csqc_shadow_budget 1`
  - `r_ambient 8`
  - `r_shadow_realtime_dlightshadows 1`
- `CSQC_UpdateView` now only draws:
  - dynamic lights by default
  - grid overlay only if `screwm_csqc_surface_grid_overlay > 0`
  - roaming pulse fields only if `screwm_csqc_roaming_surface_pulses > 0`
- Reduced CSQC overlay grid width/alpha if manually enabled, but the overlay is off by default.
- Removed `EF_FULLBRIGHT` from AoA/OARB common entity flags:
  - `ent.effects = EF_DOUBLESIDED + EF_DYNAMICMODELLIGHT;`
  - This was necessary because fullbright made AoA/OARB immune to the lighting behavior under review.

Compile commands run:

```bash
cd /home/hapax/projects/hapax-council--cx-alpha/assets/quake/csqc
fteqcc -Tdp

cd /home/hapax/projects/hapax-council--cx-alpha/assets/quake/qc
fteqcc -Tdp
```

Both compiled. Warnings were the existing unused system-field style warnings, no compile failure.

## Map/WAD Beam-Mitigation Changes

Files:

- `scripts/generate-screwm-map.py`
- `scripts/generate-screwm-wad.py`
- `tests/scripts/test_screwm_scene_generation.py`
- Generated assets:
  - `assets/quake/maps/screwm.wad`
  - `assets/quake/maps/screwm-rnd.map`
  - `assets/quake/maps/screwm-rnd.bsp`
  - `assets/quake/maps/screwm-rnd.lit`
  - `assets/quake/maps/screwm-rnd.prt`
  - `assets/quake/maps/screwm-research.*`
  - `assets/quake/maps/screwm.*`

Changes:

- `HEX_GRID_LINE_WIDTH`: `22 -> 6`
- `HEX_GRID_LINE_DEPTH`: `4 -> 2`
- `WALL_GRID_LINE_WIDTH`: `12 -> 4`
- `WALL_GRID_LINE_DEPTH`: `4 -> 2`
- `WALL_STIPPLE_DOT_SIZE`: `11 -> 6`
- Renamed generated comments from `scroom-wall-beam-*` to `scroom-wall-grid-*`.
- Renamed helper from `append_wall_beam_lattice` to `append_wall_grid_and_stipple`.
- Dimmed `geometry_signal_mark` WAD pattern:
  - no longer emits white-hot palette index `245`
  - uses black base with sparse dim/mid/accent marks
  - test now asserts `245 not in mark_set`

Important: this did **not** eliminate all visible beams in the final witness. See "Current Failure" below.

Asset regeneration commands run:

```bash
cd /home/hapax/projects/hapax-council--cx-alpha
python scripts/generate-screwm-wad.py --no-deploy
python scripts/generate-screwm-map.py --mode both --compile
scripts/install-darkplaces-screwm-assets.sh
systemctl --user restart hapax-darkplaces-v4l2.service hapax-darkplaces-obs-media-stream.service
```

Map compile result:

```text
screwm-rnd.map      qbsp OK, light -extra -lit OK, vis -fast OK
screwm-research.map qbsp OK, light -extra -lit OK, vis -fast OK
screwm.map          qbsp OK, light -extra -lit OK, vis -fast OK
```

## Tests/Verification Run

Focused passing suite at handoff:

```bash
uv run pytest \
  tests/scripts/test_screwm_scene_generation.py \
  tests/scripts/test_screwm_csqc_wards.py \
  tests/systemd/test_screwm_darkplaces_units.py \
  tests/scripts/test_hapax_vram_watchdog.py \
  -q
```

Result:

```text
64 passed in 7.61s
```

Earlier focused CSQC result:

```text
28 passed in 3.87s
```

Earlier systemd/watchdog result:

```text
13 passed in 3.74s
```

## Witness Evidence Collected

The most important witness paths:

### Pre-strict-overlay witness

Path:

```text
/tmp/screwm-beam-witness/x11-01.png
/tmp/screwm-beam-witness/x11-02.png
/tmp/screwm-beam-witness/x11-03.png
/tmp/screwm-beam-witness/x11-04.png
```

Hashes were all distinct, proving the X11 renderer was live over time. The image still showed broad colored cross-room beams.

### After CSQC overlay gates, before map/WAD beam mitigation

Path:

```text
/tmp/screwm-overlay-off-witness/x11-01.png
/tmp/screwm-overlay-off-witness/x11-02.png
/tmp/screwm-overlay-off-witness/x11-03.png
/tmp/screwm-overlay-off-witness/x11-04.png
```

Hashes were all distinct. The image still showed broad colored beams, proving the remaining source was not only CSQC pre-render overlay.

### Final handoff witness after map/WAD mitigation

Path:

```text
/tmp/screwm-thin-grid-witness/x11-01.png
/tmp/screwm-thin-grid-witness/x11-02.png
/tmp/screwm-thin-grid-witness/x11-03.png
/tmp/screwm-thin-grid-witness/x11-04.png
```

Hashes:

```text
8d2b39c3edde44814b87c7eb553e0e9405e33da2920dea17186a3b6e47c9c04a  /tmp/screwm-thin-grid-witness/x11-01.png
ed39c6dbdcb56eacd0ae85058d2f8ce086dd2bbd765f27cfaf0adb34357b9e34  /tmp/screwm-thin-grid-witness/x11-02.png
662f59b86d96b7f8078b54745203b52378a48049c3bd421bb3c65dabfb470cfd  /tmp/screwm-thin-grid-witness/x11-03.png
c446f82ec1fcd7c266e15484b881d3816bbea328916d24ff592e50794e6375ea  /tmp/screwm-thin-grid-witness/x11-04.png
```

Interpretation:

- Renderer is live over time.
- Visual is still not acceptable: final frame still contains broad colored line/beam geometry dominating the foreground and crossing the AoA/OARB.
- Do not release or report "fixed" based on this witness.

## Current Failure: Remaining Beams

The latest inspected frame (`/tmp/screwm-thin-grid-witness/x11-04.png`) still shows:

- broad magenta/blue/red/green lines crossing foreground and AoA/OARB
- wall grid and floor lines still reading as thick beams/scaffold rather than subtle effervescent grid
- lighting still aesthetically weak/unclear; dynamic-light route exists but does not yet read as coherent scene lighting

Likely causes to inspect next:

1. `line_prism_brush` textures every face of the prism with the luminous texture. Even with width reduced, the visible side faces of floor/ceiling line prisms become broad ribbons from the camera angle.
2. `box_brush` also textures every face. Wall grid carriers and stipple boxes expose side/end faces that read as physical opaque bars.
3. `geometry_signal_mark` may still be too visible after mipmapping/lightmaps even though palette index `245` is removed.
4. The generated hex lines can still cross the fixed camera very close to the near plane; even thin geometry becomes a dominant foreground beam.
5. Some ward homage accents (`ward-homage-accent ... drift_*`) are still physical brush surfaces and may contribute to bright angular bands on side walls. They are purpose-shaped, but need witness review.

Recommended next move:

- First make `line_prism_brush` and relevant wall grid/stipple brush helpers support per-face texture assignment:
  - intended exposed surface face: `hex_floor`, `hex_ceil`, `hex_wall`, `stipple_*`
  - all side/end/back faces: `skip` or a hidden/black carrier
- For floor/ceiling line prisms, only the top face of floor grid and bottom face of ceiling grid should be luminous; side faces should not be truth-bearing.
- For wall grid boxes, only the wall-facing visible face should be luminous; all extruded depth/side faces should be non-visible.
- If that still fails, temporarily disable the physical floor/ceiling grid lines and keep only stipple, then reintroduce grid via a surface-local shader/CSQC draw path that is strictly clipped to actual geometry.
- Add tests that enforce side/end faces of grid carriers are `skip` and that `scroom-wall-beam-*` never returns.

## Lighting State

Changes made:

- Dynamic-light path remains active.
- `r_shadow_realtime_world 1`
- `r_shadow_realtime_dlight 1`
- `r_shadow_realtime_dlightshadows 1`
- `r_shadow_shadowmapping 1`
- `r_ambient 8`
- AoA/OARB no longer use `EF_FULLBRIGHT`.
- Theatre spots disabled.

Important caveats:

- `assets/quake/scripts/hapax_live_media.shader` still uses `surfaceparm nolightmap` repeatedly. Live media surfaces may not participate in baked lighting as the operator expects.
- AoA has `EF_ADDITIVE` in `world.qc`; that may still fight shadow/lighting legibility.
- CSQC `screwm_shadow_budget_enabled()` currently routes to a reduced dynamic-light set. It calls:
  - `screwm_add_scroom_baseline_lights`
  - `screwm_add_hex_grid_drift_lights`
  - `screwm_add_entry_substrate_drift_lights`
  - `screwm_add_expression_surface_lights`
  - `screwm_add_media_source_signal_lights`
  - `screwm_add_aoa_pane_signal_lights`
  - `screwm_add_shadow_budget_edge_lights`
  - `screwm_add_aoa_drift_lights`
- It does not call the larger diagnostic/full light inventory in shadow-budget mode. That is intentional for performance, but the aesthetic result is still weak.

Recommended next lighting work:

- After beam geometry is fixed, evaluate lighting again from fixed X11 and OBS POVs.
- Consider removing/reducing `EF_ADDITIVE` for AoA or separating the fractal shell from information-surface facets.
- Decide which live media shaders should be fullbright-like vs light-reactive. Current `nolightmap` choices likely explain why live media does not read as scene-lit.
- Add witness ROIs for AoA rim light, OARB shadow/occlusion, floor grid brightness, wall grid brightness, and ward face/side texture leakage.

## AoA/OARB State

Already in this worktree before this handoff:

- AoA source/model has been expanded heavily; `assets/quake/models/aoa.mdl` is now much larger in diff stats.
- Runtime scale target in `assets/quake/qc/defs.qc` is `AOA_MODEL_SCALE = 1.0` and `AOA_SPHERE_MODEL_SCALE = 1.0`.
- Operator corrected size target: AoA/OARB should be about one third of Screwm height, 30% larger than original baseline. The current source/runtime intended `1.0` scale was selected to meet that corrected target.
- AoA live atlas route exists:
  - `/dev/shm/hapax-compositor/quake-live-aoa-atlas.bgra`
  - DarkPlaces live texture slot 14:
    `hapax_live_texture14_name progs/aoa.mdl_0`
- `hapax-quake-live-aoa-atlas.service` is active.

Needs more:

- Fresh witness that every visible AoA facet is independently operable has not been completed.
- OARB perfect fit needs better visual proof after beam/occlusion cleanup.
- User observed occlusion issues between AoA and OARB; this remains open.

## Ward State

The generator no longer emits the old flat placard-style pane for non-rectangular wards by default; many ward surfaces are purpose-shaped via `ward_homage_glyph`.

Remaining risk:

- The final witness still shows camera/source rectangular surfaces on side walls, some with visible dark bars/rectangles. Camera frames may be inherently rectangular, but every non-camera ward should be rechecked.
- Live texture side/end leakage must be tested at the map face level; generated helpers still often use one texture for all faces unless the helper is specialized.
- Operator specifically said wards disappeared after getting rid of placard defaults. Verify every homage ward still has a purposeful visible carrier and not a hidden/missing one.

## OBS/Stream State

Known good:

- `hapax-darkplaces-v4l2.service` active.
- `hapax-darkplaces-obs-media-stream.service` active with NVIDIA NVENC ffmpeg from `:82.0` to UDP port `30552`.
- X11 renderer `:82.0` produces changing frames.

Not proven in final pass:

- OBS WebSocket screenshot after latest patch was not successfully collected.
- A previous Python attempt using `obsws_python.ReqClient.get_source_active(source_name=...)` failed because the installed API expects positional args in this environment.

Recommended OBS witness tactic:

- Use the helper/fallback style in `agents/live_surface_guard/model.py`:
  - try keyword call
  - if `TypeError`, retry positional
- Do not print OBS WebSocket credentials.
- Witness should include:
  - X11 direct capture duration sample
  - OBS source screenshot duration sample
  - producer BGRA raw/final mtime/hash sample
  - `/dev/video52` or OBS media UDP route state if capture is not locked by OBS

## Commands Claude Should Run First

Start by confirming the current state:

```bash
cd /home/hapax/projects/hapax-council--cx-alpha
git status --short
systemctl --user is-active \
  hapax-screwm-media-drift.service \
  hapax-quake-live-aoa-atlas.service \
  hapax-quake-live-ward-atlas.service \
  hapax-darkplaces-v4l2.service \
  hapax-darkplaces-obs-media-stream.service
```

Then inspect the current failure image:

```bash
xdg-open /tmp/screwm-thin-grid-witness/x11-04.png
```

or recapture:

```bash
rm -rf /tmp/screwm-claude-witness
mkdir -p /tmp/screwm-claude-witness
ffmpeg -hide_banner -loglevel error \
  -f x11grab -draw_mouse 0 -video_size 1920x1080 -framerate 1 \
  -i :82.0 -frames:v 4 /tmp/screwm-claude-witness/x11-%02d.png
sha256sum /tmp/screwm-claude-witness/x11-*.png
```

Use focused tests while editing:

```bash
uv run pytest \
  tests/scripts/test_screwm_scene_generation.py \
  tests/scripts/test_screwm_csqc_wards.py \
  tests/systemd/test_screwm_darkplaces_units.py \
  tests/scripts/test_hapax_vram_watchdog.py \
  -q
```

Regenerate/deploy after map or WAD edits:

```bash
python scripts/generate-screwm-wad.py --no-deploy
python scripts/generate-screwm-map.py --mode both --compile
scripts/install-darkplaces-screwm-assets.sh
systemctl --user restart hapax-darkplaces-v4l2.service hapax-darkplaces-obs-media-stream.service
```

Compile QuakeC after CSQC/QC edits:

```bash
(cd assets/quake/csqc && fteqcc -Tdp)
(cd assets/quake/qc && fteqcc -Tdp)
scripts/install-darkplaces-screwm-assets.sh
systemctl --user restart hapax-darkplaces-v4l2.service hapax-darkplaces-obs-media-stream.service
```

## Dirty Worktree Warning

The worktree is very dirty: `git diff --stat` currently reports 84 changed files, including large generated assets. Not all of this was from the final beam pass; some was inherited from earlier/composited work in the lane. Do not revert broad changes. If you need to isolate, inspect targeted diffs instead of resetting.

Notable changed/new areas:

- `assets/quake/*` maps, models, QC, CSQC, configs, GLSL, WAD
- `scripts/generate-screwm-map.py`
- `scripts/generate-screwm-wad.py`
- `scripts/hapax-vram-watchdog`
- `scripts/darkplaces-state-export.py`
- `hapax-logos/crates/hapax-visual/*`
- `systemd/units/*`
- tests under `tests/scripts` and `tests/systemd`
- untracked:
  - `scripts/quake-live-aoa-atlas-source.py`
  - `systemd/units/hapax-quake-live-aoa-atlas.service`
  - `tests/scripts/test_hapax_vram_watchdog.py`
  - `tests/scripts/test_quake_live_aoa_atlas_source.py`

## Suggested Next Patch

Most direct next patch:

1. Add a face-selective brush helper for surface-carrier prisms:
   - floor line: top face uses `hex_floor`, all other faces `skip`
   - ceiling line: bottom face uses `hex_ceil`, all other faces `skip`
   - wall grid: wall-facing face uses `hex_wall`, all other faces `skip`
   - stipple dots: only the outward/intended face uses `stipple_*`
2. Update `tests/scripts/test_screwm_scene_generation.py` to assert:
   - no `scroom-wall-beam-*`
   - grid carriers contain `skip` on non-display planes
   - `drift_*` textures are not used as room-spanning or side-face carriers
3. Regenerate WAD/maps/BSP, deploy, restart.
4. Re-run X11 duration witness.
5. Only after broad lines are gone, evaluate actual lighting and drift intensity.

Do not spend more time tuning dynamic lights while the foreground beam/line geometry is still dominating the frame; it masks the lighting problem and makes witness ambiguous.

