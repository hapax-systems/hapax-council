# Homage Migration Principles

Working principles for migrating visual elements from hapax-imagination (wgpu/WGSL)
into the DarkPlaces Quake engine. Developed during the Screwm-Quake migration
(2026-05-23). These guide all future aesthetic decisions in the migration.

## 1. Format Constraints Are Physical Laws, Not Suggestions

The Quake MDL format packs vertices as 8-bit integers. This is not a quality
setting — it is a hard physical constraint. Every geometric asset must be
designed WITH this constraint, not despite it.

- **Depth 2 maximum** for recursive fractal geometry (16 sub-elements)
- **Minimum vertex separation**: ~2% of bounding box per axis (5/255 byte values)
- **Test by rendering**, not by counting vertices — quantization artifacts are
  visible, not calculable
- If a shape survives 8-bit quantization and still reads as itself, it belongs
  in the engine. If it doesn't, find a different representation.

## 2. The Engine's Aesthetic IS the Homage

Do not fight DarkPlaces to make it render like wgpu. Quake's rendering
limitations — nearest-neighbor textures, vertex lighting, fog-as-atmosphere,
8-bit geometry — are the aesthetic. They are what makes the Quake homage
authentic rather than a skin.

- **GL_NEAREST** texture filtering: pixels visible, not interpolated
- **Vertex lighting**: hard shadows, no soft ambient occlusion
- **Fog**: uniform color overlay, not volumetric — use this for depth cue
- **No PBR**: materials are flat-lit with a single diffuse texture
- These constraints produce the visual language. Embrace them.

## 3. Split by Temporal vs Spatial

DarkPlaces excels at spatial rendering (geometry, lighting, fog, entities).
GStreamer excels at temporal compositing (frame history, feedback loops, overlays).
Never cross the boundary in the wrong direction.

| Domain | Owner | Examples |
|--------|-------|---------|
| Spatial | DarkPlaces | Tower geometry, AoA entity, lights, fog, camera path |
| Temporal | GStreamer glfeedback | Feedback loops, echo, diff, stutter, slitscan |
| Informational | GStreamer Cairo | Wards, text, data visualization, HUD |
| Color | Either | Colorgrade possible in both; prefer DarkPlaces for scene-level, GStreamer for output-level |

## 4. Content Cannot Be In-Engine

DarkPlaces cannot reload textures at runtime without engine restart. This is
a confirmed, researched constraint (not an assumption). All dynamic content
(wards, video, live data) MUST render in the GStreamer compositor overlay.

Ward rendering stays in Cairo/Pango. The HomagePackage controls ward aesthetics
(palette, typography, grammar) regardless of which engine renders the 3D world.

## 5. Mode Propagation Is Map-Level

Working mode (Gruvbox R&D / Solarized Research) requires different BSP maps
compiled with different light colors and fog presets. This is because:
- Quake light colors are baked at compile time (`.lit` files)
- Fog color can change at runtime via `localcmd("fog ...")`
- Texture sets cannot swap without map reload

The dual-BSP approach (screwm-rnd.bsp / screwm-research.bsp) is the correct
architecture. The brief load screen during map swap is acceptable.

## 6. Cognitive Coupling Through File I/O Bridge

QuakeC's `fopen` is sandboxed to the game directory. External state must be
bridged via a sidecar service that copies `/dev/shm` files into the game's
`data/` directory. This is the architecturally correct approach — it respects
DarkPlaces' sandbox model while enabling live coupling.

Polling cadence: 1 second for energy/voice, 5 seconds for mode changes.
These are soft-real-time requirements, not hard-real-time.

## 7. Normal Tables Matter for Lighting

Quake's 162-entry normal lookup table determines how models interact with
lighting. Using a constant normal index (e.g., always 0) produces flat,
directionless shading that makes 3D geometry look like a cardboard cutout.
Every MDL generator must compute per-vertex normals and look up the closest
table entry.

## 8. Sound Is Spatial, Not Decorative

Each tower level has a distinct sonic identity. Sound emitters are entities
with spatial attenuation. The sound design encodes the cognitive hierarchy
the same way lighting and textures do — it is semantic, not ambient.

## 9. The Camera IS the Viewer

The QuakeC pendulum camera path is the viewer's experience of the tower.
Camera dynamics (speed, look direction, path shape) are first-class
expressive parameters, not technical settings. Stimmung energy modulating
camera period is cognitive coupling, not animation.

## 10. Verify Visually, Not Computationally

A mesh that passes validation (correct vertex count, face indices, normals)
can still render as a degenerate sliver. Always screenshot after deploying
a visual change. Type checking and unit tests verify code correctness —
only rendering verifies visual correctness.
