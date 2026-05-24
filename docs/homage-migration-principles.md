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

## 2. The Engine Is a Substrate, Not the Subject

DarkPlaces constraints are real, but they do not replace the existing Screwm
commitments. The migration target is the last non-Quake Screwm composition:
AoA/Sierpinski as central aperture, wards as lived information surfaces,
Reverie drift/effects as the atmosphere, and working-mode palettes as semantic
state. Quake is the new environment in which those commitments must be
expressed; it is not a mandate to make a Quake level in spirit.

- **GL_NEAREST** texture filtering: pixels visible, not interpolated
- **Vertex lighting**: hard shadows, no soft ambient occlusion
- **Fog**: uniform color overlay, not volumetric — use this for depth cue
- **No PBR**: materials are flat-lit with a single diffuse texture
- These constraints shape implementation details. They do not authorize losing
  Screwm's prior composition, theory, density, ward inventory, or drift.

## 3. Split by Temporal vs Spatial

DarkPlaces excels at spatial rendering (geometry, lighting, fog, entities).
GStreamer excels at temporal compositing (frame history, feedback loops, overlays).
Never cross the boundary in the wrong direction.

| Domain | Owner | Examples |
|--------|-------|---------|
| Spatial | DarkPlaces | Tower geometry, AoA entity, lights, fog, camera path |
| Temporal | GStreamer glfeedback | Feedback loops, echo, diff, stutter, slitscan |
| Informational | DarkPlaces first, GStreamer only as legacy bridge | Ward panes, in-world state lights, text/data surfaces while live texture strategies mature |
| Color | Either | Colorgrade possible in both; prefer DarkPlaces for scene-level, GStreamer for output-level |

## 4. Dynamic Content Is the Hardest In-Engine Migration Surface

DarkPlaces cannot reload textures at runtime without engine restart. This is
a confirmed, researched constraint (not an assumption). It is a blocker to
naive texture-based live wards, not a reason to declare wards out of scope.

The required direction is:
- Sourceize static in-engine ward anchors/panes for all legacy wards so the
  spatial Screwm composition is present inside DarkPlaces.
- Use CSQC for engine-native pulse lights and state coupling tied to those
  spatial anchors; any projected text/line overlay must be opt-in diagnostic,
  not the default migration surface.
- Keep GStreamer/Cairo wards only as a legacy or temporary dynamic-content
  bridge while Quake-native dynamic strategies are evaluated.
- Treat any remaining compositor-owned ward as an explicit parity gap with
  evidence, not as the target architecture.

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

## 9. The Camera Is Reviewable Before It Is Expressive

The camera is the viewer's experience of Screwm, so it cannot lurch while the
operator is judging migration parity through OBS. Default runtime must use a
stable review pose that makes AoA, in-engine ward anchors, and drift/effects
legible. Recurrent motion is allowed only after a fixed review baseline is
visually accepted; then it must be slow, cyclic, and never read as accidental
forward jumps.

## 10. Verify Visually, Not Computationally

A mesh that passes validation (correct vertex count, face indices, normals)
can still render as a degenerate sliver. Always screenshot after deploying
a visual change. Type checking and unit tests verify code correctness —
only rendering verifies visual correctness.
