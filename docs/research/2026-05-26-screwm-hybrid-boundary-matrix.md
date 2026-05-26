---
type: support-artifact
artifact_id: ART-20260526-screwm-hybrid-boundary-matrix
parent_task: 20260526-screwm-hybrid-boundary-research
parent_request: REQ-20260526-screwm-quake-hybrid-aggregate
authority_level: support_non_authoritative
created_at: 2026-05-26T01:30:00Z
author: beta
quality_floor: frontier_review_required
review_requirement:
  authoritative_acceptor_profile: alpha-frontier
sources_consulted:
  - docs/superpowers/specs/2026-05-23-screwm-quake-hybrid-isap.md
  - docs/research/2026-05-23-darkplaces-capabilities-audit.md
  - docs/research/2026-05-23-aesthetic-migration-audit.md
  - docs/superpowers/specs/2026-05-10-livestream-render-architecture-shadow-plan.md
  - REQ-20260526-screwm-quake-hybrid-aggregate.md
  - DarkPlaces dpextensions.qc (upstream source)
  - DarkPlaces shader_glsl.h, gl_rmain.c (upstream source)
  - assets/quake/qc/coupling.qc (existing implementation)
  - assets/quake/qc/camera.qc (existing implementation)
---

# DarkPlaces / Compositor Boundary Decision Matrix

Support artifact for CASE-SCREWM-QUAKE-MIGRATION-20260523. Not authoritative —
alpha must validate each recommendation with live witnesses before implementation.

## Governing Principle

The operator directive (REQ-20260526) establishes one rule above all others:
**true hybrid, no fourth wall.** The boundary must be invisible to the viewer.
DarkPlaces and the compositor are not "engine + overlay" — they are a single
rendering system whose internal seam the operator cannot perceive.

This principle resolves every ambiguous boundary case: the requirement goes
wherever it can be made seamless, not wherever it is technically easiest.

---

## 1. Decision Matrix

Each requirement is classified into one of four categories:

- **Native Quake** — DarkPlaces owns this entirely. It is scene-intrinsic: it
  needs world membership, physics, occlusion, lighting, or 3D camera semantics.
- **Hybrid** — Both systems participate. DarkPlaces provides the spatial
  foundation; the compositor enriches, overlays, or temporally extends it.
  Correlation mechanisms are required.
- **Compositor/Drift** — The compositor/drift stack owns this entirely. It needs
  live media, temporal frame history, 2D overlay precision, or capabilities
  DarkPlaces cannot provide without engine modification.
- **Defer** — Cannot be resolved without additional research, engine
  modification, or runtime evidence that does not yet exist.

### 1.1 Scene Geometry and Spatial Rendering

| Requirement | Category | Rationale |
|---|---|---|
| Tower BSP structure (5-level octagonal geometry) | **Native Quake** | World membership. BSP is DarkPlaces' native spatial representation. Grid-aligned (32-unit = 1m). |
| AoA Sierpinski tetrahedron | **Native Quake** | Entity with world membership — needs occlusion by tower walls, lighting interaction, physics-driven rotation. MDL format. |
| Level-boundary collision/zones | **Native Quake** | Trigger entities define zone boundaries. QuakeC `touch()` detects camera position relative to zones. |
| Ramp/stairway traversal paths | **Native Quake** | Quake movement physics. Camera path must respect BSP geometry. |
| Tower interior negative space | **Native Quake** | The "Japanese garden" spatial grammar requires controlled emptiness. Achieved through BSP geometry + fog density, not compositor masking. |
| Room-scoped Homage zones | **Defer** | The request mentions zone-scoped and room-scoped Homage. DarkPlaces can define zones via trigger entities, but the visual consequences (palette shift, transition style) need compositor cooperation. Requires hybrid correlation design. |

### 1.2 Lighting

| Requirement | Category | Rationale |
|---|---|---|
| Per-level semantic colored lights (6 lights) | **Native Quake** | Dynamic lights are DarkPlaces' strength. Per-entity, shadow-casting, cubemap-projected. QuakeC controls intensity/color per-frame. |
| Stimmung-driven light intensity | **Native Quake** | QuakeC reads `/dev/shm` stimmung energy and multiplies light radius/intensity. Already implemented in `coupling.qc` (polling stimmung-energy.txt at 1s interval). |
| Mode-aware light warmth (Gruvbox / Solarized) | **Native Quake** | QuakeC adjusts light color vectors on mode change. `coupling.qc` already polls `data/working-mode.txt` at 5s interval. |
| Flickering/pulsing light animation | **Native Quake** | DarkPlaces has native light styles (string-based flicker patterns) plus QuakeC sinusoidal modulation. |
| Light-as-breathing-animation (design language) | **Hybrid** | Breathing vocabulary (sinusoidal opacity, severity-driven tempo) maps to QuakeC light pulsing for scene-intrinsic breathing. Compositor-rendered ward breathing remains compositor-owned. Both must share tempo source (stimmung energy). |
| Corona / halo effects | **Native Quake** | DarkPlaces has native corona rendering on dynamic lights. |

### 1.3 Fog

| Requirement | Category | Rationale |
|---|---|---|
| Global distance fog | **Native Quake** | Full CSQC `setproperty(VF_FOG_*)` control. Exponential or quadratic. |
| Mode-aware fog color | **Native Quake** | Warm amber (R&D) / cool blue-grey (Research). QuakeC switches on mode poll. |
| Height-gradient fog | **Native Quake** | DarkPlaces supports height fog with texture-driven color gradients. Per-level fog color achievable via height texture. |
| Stimmung-driven fog density | **Native Quake** | `coupling.qc` already adjusts fog density based on energy. |
| Volumetric fog (light scattering) | **Compositor/Drift** | DarkPlaces has no volumetric scattering. Compositor glfeedback can apply volumetric approximation as post-process on DarkPlaces output. |
| Per-entity fog | **Defer** | DarkPlaces fog is global only. Per-level variation achievable via height fog, but true per-entity fog requires engine modification. |

### 1.4 Camera

| Requirement | Category | Rationale |
|---|---|---|
| Pendulum camera path (6 control points, Catmull-Rom) | **Native Quake** | Already implemented in `camera.qc`. Spline interpolation with `setviewprop()` / `VF_ORIGIN` / `VF_ANGLES`. Camera respects BSP occlusion. |
| Stimmung-driven camera period (120-150s) | **Native Quake** | `camera.qc` already reads energy and adjusts interpolation speed. |
| Choreographer-synchronized camera cadence | **Hybrid** | Camera path timing must align with HOMAGE rotation mode (steady/deliberate/rapid/burst). DarkPlaces reads choreographer state; compositor reads same state for ward transitions. Shared clock, independent execution. |
| Camera teleport on burst mode | **Native Quake** | QuakeC snaps camera position without interpolation when choreographer signals burst. |

### 1.5 Particles

| Requirement | Category | Rationale |
|---|---|---|
| Ambient dust motes per level | **Native Quake** | `pt_alphastatic`, slow velocity, long lifetime, BILLBOARD orientation. |
| Energy effects around AoA | **Native Quake** | `pt_entityparticle` orbiting ring + `pt_static` additive billboards + dynamic lights with corona. |
| Level-boundary transition particles | **Native Quake** | Trigger-spawned particle bursts at zone boundaries via `effectinfo.txt`. |
| Stimmung-responsive particle density | **Native Quake** | QuakeC modulates `pointparticles()` count based on energy reading. |
| Volumetric light beams | **Native Quake** | `PARTICLE_HBEAM`/`PARTICLE_VBEAM` with additive blend + corona. Not true volumetric but visually convincing. |
| God rays / light scattering | **Compositor/Drift** | No GPU ray marching in DarkPlaces. Compositor glfeedback applies screen-space god rays if needed. |

### 1.6 Sound

| Requirement | Category | Rationale |
|---|---|---|
| 5 ambient sound zones | **Native Quake** | Entity-based ambient emitters at level boundaries. `SOUNDFLAG_FORCELOOP`. 7 channels per entity. Already defined in `world.qc`. |
| Stimmung-driven volume/pitch modulation | **Native Quake** | QuakeC adjusts entity sound per stimmung state. |
| Mode-aware sonic shift | **Native Quake** | QuakeC crossfades between R&D and Research ambient variants. |
| Audio-reactive visual effects | **Compositor/Drift** | `waveform_render` needs audio buffer bridge. DarkPlaces has no audio analysis API. Compositor owns this. |

### 1.7 Shader Effects

| Requirement | Category | Rationale |
|---|---|---|
| Bloom | **Native Quake** | Built-in multi-pass bloom. `r_bloom` cvars. |
| Chromatic aberration | **Native Quake** | Built-in `USECOLORFRINGE`. |
| Basic color grading (saturation, gamma) | **Native Quake** | `USEGAMMARAMPS` + `USESATURATION`. |
| Edge detection / sharpen | **Native Quake** | Built-in Sobel in default postprocess shader. |
| Film grain, vignette, scanlines | **Hybrid** | Achievable via `USEPOSTPROCESSING` + UserVec uniforms. `coupling.qc` already maps energy/voice state to `r_glsl_postprocess_uservec1` (vignette, chroma, temp, grain) and `uservec2` (scanlines, edge_glow). Constrained to 4 UserVec (16 floats total). |
| Advanced color grading (3D LUT, split-tone) | **Compositor/Drift** | DarkPlaces has 1D gamma ramps only. Compositor glfeedback handles advanced grading. |
| Temporal feedback loops (feedback, echo, diff, stutter, slitscan, pixsort) | **Compositor/Drift** | DarkPlaces has no multi-pass FBO chain. These require frame history accumulation. GStreamer glfeedback (12 slots, configurable to 24) is the only viable path. |
| Reaction diffusion, fluid sim | **Compositor/Drift** | GPU compute simulation. No DarkPlaces equivalent. |
| Sierpinski content/lines | **Compositor/Drift** | Central Hapax visual. Compositor layer by design. |
| HOMAGE coupling (uniforms.custom[4]) | **Hybrid** | DarkPlaces reads coupling values from shared memory, adjusts fog/light/camera. Compositor reads same values, adjusts ward transitions. Bidirectional feedback via `/dev/shm`. |

### 1.8 Wards and Overlays

| Requirement | Category | Rationale |
|---|---|---|
| 35 Cairo ward overlays | **Compositor/Drift** | Cairo/Pango text rendering on GStreamer. DarkPlaces cannot reload textures at runtime (confirmed blocker ISAP section 4.1). |
| Ward transition FSM + choreographer | **Compositor/Drift** | `HomageTransitionalSource` mixin, concurrency rules, netsplit-burst timing. |
| Signal pips, detection overlays | **Compositor/Drift** | Compositor-native 2D overlays. |
| Stimmung stance overlay (tint + pulse) | **Hybrid** | DarkPlaces fog/lighting shifts encode stance spatially. Compositor applies 2D tint/pulse overlay. Both respond to same stimmung state. |

### 1.9 Live Media

| Requirement | Category | Rationale |
|---|---|---|
| Camera feed compositing | **Compositor/Drift** | CUDA compositor ingests camera feeds. DarkPlaces cannot composite external video. |
| YouTube live media playback | **Compositor/Drift** | yt-dlp pipeline. No DarkPlaces video playback. |
| v4l2loopback DarkPlaces capture | **Hybrid** | DarkPlaces outputs to `/dev/video52`. Compositor reads as primary background. The capture pipeline IS the boundary. |
| HLS / OBS output | **Compositor/Drift** | GStreamer hlssink2. Compositor-native. |

### 1.10 Working Mode

| Requirement | Category | Rationale |
|---|---|---|
| Dual BSP compilation (rnd/research) | **Native Quake** | `scripts/generate-screwm-map.py --mode rnd/research`. |
| Runtime mode switch | **Hybrid** | `hapax-theme-apply` sends RCON or `coupling.qc` polls mode file, triggers `map screwm-<mode>`. ~2s load screen. Compositor masks discontinuity by holding last-good frame. |
| Fog + brightness cvar adjustment | **Native Quake** | Instant, no map reload needed. |

### 1.11 Systemd and Lifecycle

| Requirement | Category | Rationale |
|---|---|---|
| hapax-darkplaces.service | **Native Quake** | Standalone systemd unit. WatchdogSec. GPU-pinned to 5060 Ti via dedicated Xorg `:82`. |
| Source-activation check | **Hybrid** | `hapax-compositor-runtime-source-check` gates both systems. |
| Fallback on DarkPlaces unavailable | **Compositor/Drift** | Compositor pins background black, keeps wards/cameras running. |

---

## 2. Correlation Mechanisms Required

### 2.1 Shared State via /dev/shm

Both systems converge on `/dev/shm` as the correlation bus. `coupling.qc`
reads `data/stimmung-energy.txt`, `data/voice-active.txt`, `data/working-mode.txt`
at 1s/5s intervals. The compositor reads from `/dev/shm/hapax-stimmung/state.json`
and `/dev/shm/hapax-compositor/` paths.

**Gap:** The paths don't match. `coupling.qc` reads from `data/` (relative to
DarkPlaces game dir), not `/dev/shm/`. Either QuakeC fopen must support absolute
paths (needs runtime validation — see R1 below), or an external bridge must copy
`/dev/shm` values into DarkPlaces' `data/` directory.

### 2.2 HOMAGE Coupling Bus

DarkPlaces must participate in `uniforms.custom[4]`:

- **Read:** DarkPlaces reads coupling values, maps `.x` (transition energy) to
  fog density, `.y` (palette accent hue) to light tint, `.z` (signature intensity)
  to particle density, `.w` (rotation phase) to camera interpolation.
- **Write:** DarkPlaces writes scene energy (camera velocity, light intensity,
  particle count) to a feedback file for the choreographer.

### 2.3 Mode Switch Synchronization

`hapax-theme-apply` propagates mode to both systems. The DarkPlaces map reload
(~2s) creates a visual discontinuity. The compositor should hold its last-good
DarkPlaces frame during the reload window, not flash black.

### 2.4 Choreographer Cadence Bridge

| Director mode | DarkPlaces camera period | Compositor ward transition |
|---|---|---|
| steady | ~90s pendulum | ~90s rotation cycle |
| deliberate | ~180s pendulum | ~180s rotation |
| rapid | ~30s pendulum | ~30s rotation |
| burst | Camera teleport | Netsplit-style mass transition |

Both read the director's current mode from shared state. Eventual consistency
within one tick is sufficient (cadences are 30-180s).

### 2.5 v4l2loopback as the Physical Boundary

`/dev/video52` is the physical seam. Properties:
- Latency: one frame (~33ms at 30fps). Acceptable.
- Resolution: 1280x720 matched. No scaling.
- Color: sRGB via OpenGL to CUDA upload (NV12). Caps negotiation critical.
- Failure: frozen frame causes v4l2 source health to degrade, then black after 2s.

---

## 3. Concrete Recommendations for Alpha

### R1. Validate QuakeC fopen for Absolute /dev/shm Paths

**Why first:** Every hybrid coupling depends on DarkPlaces reading shared memory.
`coupling.qc` currently uses relative `data/` paths. If `fopen` supports absolute
paths (`/dev/shm/hapax-stimmung/state.json`), the bridge simplifies dramatically.
If not, an external Python bridge must copy values into the game directory.

**Evidence:** Minimal QuakeC: `fopen("/dev/shm/hapax-test", FILE_READ)`, read one
line, log to console. Run via `darkplaces-attended-smoke.sh`.

**Failure predicate:** If `fopen` returns -1 for absolute paths, implement a Python
bridge timer (100ms interval) copying `/dev/shm` values to
`~/.darkplaces/screwm/data/`. This adds one moving part but preserves the
coupling contract.

### R2. Wire RCON Mode Switch in hapax-theme-apply

**Why second:** Mode switching is the simplest bidirectional correlation and proves
the control channel.

**Evidence:** After `hapax-working-mode research`, DarkPlaces fog shifts from amber
to blue-grey within 3s. OBS screenshot before/after.

**Failure predicate:** If RCON unreliable, fall back to config file swap +
`exec autoexec.cfg` polling.

### R3. Compositor Fallback Grace During Mode Switch

**Why third:** The ~2s map reload creates a visible seam. The compositor must not
flash black during intentional mode switches.

**Evidence:** Mode switch captured on OBS. No black frame visible. Compositor holds
last-good DarkPlaces frame during reload.

**Failure predicate:** If v4l2 source health triggers degradation before map reload
completes, add mode-switch suppression flag to source health evaluator.

### R4. End-to-End Stimmung Correlation Witness

**Why fourth:** Most visible proof of hybrid correlation. If camera and lighting
feel alive (responsive to stimmung), the boundary disappears.

**Evidence:** 30s recording showing camera speed and light intensity changing with
stimmung energy. Compare against existing hapax-imagination stimmung response.

**Failure predicate:** If QuakeC polling latency > 500ms, pre-process stimmung into
cvars via external Python bridge at 100ms.

### R5. Live Media Anchoring Strategy Decision

**Why fifth:** The operator says wards and live media must live "in the Screwm, not
on a fourth wall." Current architecture places them as compositor 2D overlays ON
TOP of the 3D scene. This is the highest-risk boundary decision.

**Evidence needed:** OBS recording comparing (a) current 2D overlay approach vs
(b) depth-keyed compositing that respects DarkPlaces geometry occlusion. If the
2D overlay approach feels like a fourth wall to the operator, depth-keying or
DarkPlaces engine modification becomes mandatory.

**Failure predicate:** If depth information is unavailable (DarkPlaces doesn't
export depth buffer via v4l2), the only path is engine modification to render
ward textures onto in-world geometry surfaces — which conflicts with the confirmed
dynamic texture replacement blocker (ISAP section 4.1). This may force a hybrid
approach where ward content is pre-rendered to static textures and swapped via
map reload.

---

## 4. Witness Requirements

### 4.1 Boundary Integrity Witness

Record 60s of composite output (DarkPlaces + wards + cameras). Show to unfamiliar
viewer. If they can identify where the 3D engine ends and the overlay begins on
first viewing, correlation is insufficient. OBS capture at 1080p with audio.

### 4.2 Mode Switch Continuity Witness

Trigger 3 mode switches in 5 minutes. Pass: no black frames, fog transition
smooth, ward palette updates within 1s of fog shift, sound shifts within 2s.

### 4.3 Stimmung Correlation Witness

Synthetic energy ramp 0.0 to 1.0 over 60s via `/dev/shm`. Pass: camera period
changes (150s to 120s), light intensity increases, fog density decreases. All
smooth, not stepped.

### 4.4 Temporal Effect Boundary Witness

Enable feedback loop in compositor while DarkPlaces renders. Pass: feedback
ghosting includes DarkPlaces geometry, not just ward text. Proves v4l2 to
compositor to glfeedback chain processes full composite.

### 4.5 Degradation Witness

Kill DarkPlaces while compositor runs. Pass: compositor does not crash, background
transitions to black within 2s, wards/cameras continue, DarkPlaces restart
recovers without compositor restart.

---

## 5. Boundary Summary

```
+-----------------------------------------------------------------------+
|                    NATIVE QUAKE (DarkPlaces)                          |
|  BSP geometry . entities . AoA MDL . dynamic lights . fog .          |
|  particles . ambient sound . camera path . GLSL bloom/fringe/        |
|  saturation . QuakeC cognitive coupling (coupling.qc) .              |
|  custom postprocess (vignette/grain/scanlines via UserVec) .         |
|  RCON mode receptor                                                   |
|                                                                       |
|  OUTPUT: /dev/video52 (v4l2loopback, 1280x720, sRGB)                |
+==================================+====================================+
|    CORRELATION LAYER             |                                    |
|  /dev/shm shared state           |  stimmung . homage coupling .     |
|  RCON mode commands              |  choreographer cadence .           |
|  scene energy feedback           |  mode switch synchronization      |
+==================================+====================================+
|                    COMPOSITOR/DRIFT (GStreamer)                        |
|  Camera feeds (CUDA) . Cairo wards (35) . ward transition FSM .      |
|  signal pips . detection overlays . temporal effects (feedback,       |
|  echo, diff, stutter, slitscan, pixsort) . 3D LUT color grading .   |
|  live media . HLS . v4l2sink(/dev/video42) . OBS output .            |
|  volumetric approximations . Sierpinski . waveform render .           |
|  reaction diffusion . fluid sim . graceful degradation               |
+-----------------------------------------------------------------------+
```

---

## 6. Deferred Items

| Item | Blocker | Next Step |
|---|---|---|
| Room-scoped Homage zones | Hybrid correlation design needed | Research zone-trigger to compositor palette swap protocol |
| Per-entity fog | DarkPlaces fog is global | Test height fog gradient texture for per-level variation |
| Waveform render | Audio buffer bridge absent | Design audio-to-shader bridge architecture |
| 3D depth for compositor effects | v4l2 exports flat 2D, no depth buffer | Research depth export (engine mod) or monocular depth estimation |
| Live media anchored in 3D world | Dynamic texture replacement blocked | Research pre-rendered texture swap via map reload vs depth-keyed compositing |
| Volumetric fog | No ray-marched volumes in DarkPlaces | Evaluate particle beam approximation sufficiency |

---

*This artifact is non-authoritative. Alpha must validate each boundary decision
with fresh runtime witnesses before committing to implementation.*
