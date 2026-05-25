# Screwm-Quake Full Migration — Design Specification

> **Authority Case:** CASE-SCREWM-QUAKE-MIGRATION-20260523
> **Risk Tier:** T3_HIGH
> **Parent Research:** 12-agent audit (2026-05-23): DarkPlaces capabilities, dynamic texture API, shader node catalog, sound system, working mode propagation, QuakeC coupling, aesthetic migration
> **Axiom Compliance:** single_user (100), executive_function (95)
> **Design Language:** `docs/logos-design-language.md` — §11 governed surface
> **HOMAGE Spec:** `docs/superpowers/specs/2026-04-18-homage-framework-design.md`
> **Render Architecture:** `docs/superpowers/specs/2026-05-10-livestream-render-architecture-shadow-plan.md`
> **Research Artifacts:** `docs/research/2026-05-23-darkplaces-capabilities-audit.md`, `docs/research/2026-05-23-quakec-live-coupling-audit.md`, `docs/research/2026-05-23-aesthetic-migration-audit.md`

## 1. Problem

The Screwm (Tower of Babel interior) is rendered by hapax-imagination via custom wgpu/WGSL shaders. The operator directive is to fully migrate the visual rendering surface into the DarkPlaces Quake engine. This is not a hybrid coexistence — DarkPlaces becomes THE renderer, hapax-imagination retires.

All prior aesthetic commitments must migrate: design language (Gruvbox/Solarized mode system), HOMAGE framework (BitchX/Enlightenment-Moksha), reverie shader vocabulary (62 WGSL nodes), stimmung-driven animation, audio reactivity, and spatial perspective management.

Nothing is given up. Everything is gained.

## 2. Goals

> **2026-05-24 migration-target correction:** DarkPlaces is the rendering
> substrate, not the aesthetic subject. The target is to recreate the last
> non-Quake Screwm, including all wards, drift, and effects, inside the new
> environment as far as DarkPlaces can bear it. Temporary compositor bridges
> are parity gaps to close, not the desired endpoint.

1. DarkPlaces renders the Screwm tower as a Quake BSP map with CC0 textures, colored lighting, fog, and spatial audio.
2. QuakeC drives camera, lighting, fog, and entity behavior based on live cognitive state (/dev/shm signals).
3. 39 reverie shader nodes (EXCELLENT+GOOD tiers) migrate to DarkPlaces GLSL post-processing.
4. 11 temporal shader nodes (DIFFICULT tier: feedback, echo, diff, stutter, slitscan, pixsort) remain in GStreamer glfeedback chain as post-compositor effects.
5. All legacy wards receive in-engine spatial anchors/panes, baked identity materials, physical drift carriers, and CSQC-driven in-world pulse/state coupling; projected CSQC text/line overlays are diagnostic only, and dynamic Cairo/GStreamer ward rendering remains a temporary bridge only where DarkPlaces runtime texture limits block live content today.
6. Working mode propagation: dual BSP compilation (screwm-rnd.bsp / screwm-research.bsp) + runtime fog/brightness adjustment.
7. QuakeHomage registered as third HomagePackage.
8. hapax-imagination retires after Phase 4 shader port is verified.
9. Stable 24/7 as a systemd user unit.

## 3. Non-Goals

- Using proprietary id Software/Bethesda textures.
- PBR/photorealistic rendering.
- Patching DarkPlaces engine source code (use capabilities as-is; revisit in Phase 5 if needed).
- Porting waveform_render node (requires audio buffer bridge — deferred).

## 4. Research-Grounded Constraints

### 4.1 Dynamic Texture Replacement: BLOCKED

DarkPlaces cannot reload textures at runtime without `r_restart`/`vid_restart`, which pauses the engine visibly. No QuakeC builtin exists for texture injection. No FBO/RTT support documented. This is confirmed via source code audit of `r_textures.h`, `gl_textures.c`, and `dpextensions.qc`.

**Decision:** live texture replacement remains blocked, so naive
texture-swapping wards cannot be the runtime strategy. This does **not** move
wards back to the fourth wall. Ward identity, anchors, drift carriers, and
state-reactive light coupling belong inside DarkPlaces; any GStreamer/Cairo
ward remains a documented temporary bridge until its dynamic content has an
engine-native strategy.

### 4.2 Shader Node Migration Tiers

62 WGSL nodes cataloged. Migration feasibility:

| Tier | Count | Approach | Timeline |
|---|---|---|---|
| EXCELLENT | 11 | Direct GLSL port, 1:1 | Phase 4 (1-2w) |
| GOOD | 28 | Standard GLSL techniques | Phase 4 (1-2w) |
| MODERATE | 11 | Custom GLSL, non-trivial | Phase 5 (2-4w) |
| DIFFICULT | 11 | Frame accumulator plugin or stay in glfeedback | Phase 5 / deferred |
| IMPOSSIBLE | 1 | waveform_render — needs audio buffer bridge | Deferred |

### 4.3 Working Mode: Dual BSP Strategy

Texture palette cannot swap at runtime without map reload. Solution: compile two BSPs from the same geometry with different texture assignments:
- `screwm-rnd.bsp` — warm Gruvbox textures (brown stone, amber lights)
- `screwm-research.bsp` — cool Solarized textures (blue-grey stone, white lights)

Mode switch triggers `map screwm-<mode>` via rcon or config reload. Brief load screen is acceptable (< 2s for a 14KB BSP). Fog color and r_brightness adjust via cvars.

### 4.4 QuakeC File I/O

DarkPlaces dpextensions provide `fopen`/`fclose`/`fgets` for reading external files. To be verified at runtime. Fallback: config file polling via `exec` console command.

## 5. Architecture

```
┌─────────────────────────────────────────────────────────┐
│ DarkPlaces (GPU: 5060 Ti, ~200-500MB VRAM)              │
│  ├─ Tower BSP (8 octagonal walls, ramps, floor, ceiling)│
│  ├─ AoA MDL entity (current tetrix + sphere, rotating)  │
│  ├─ 6 colored lights (per-level semantic colors)         │
│  ├─ Fog (density + color, mode-aware)                    │
│  ├─ 5 ambient sound zones (entity-based, 128 channels)  │
│  ├─ QuakeC camera (stable review + optional manual/orbit)│
│  ├─ QuakeC cognitive coupling (/dev/shm reader)          │
│  ├─ GLSL post-processing (39 ported shader nodes)        │
│  └─ Output: window → v4l2loopback /dev/video52           │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────┐
│ GStreamer Compositor (preserved, enhanced)               │
│  ├─ DarkPlaces /dev/video52 as PRIMARY background        │
│  ├─ Legacy Cairo wards only where not yet engine-native  │
│  ├─ 11 temporal shader effects (feedback, echo, diff,    │
│  │   stutter, slitscan — require frame history)          │
│  ├─ Camera feeds (cudacompositor, unchanged)              │
│  └─ Output: v4l2sink(/dev/video42) + HLS                 │
└─────────────────────────────────────────────────────────┘
```

### 5.1 Rendering Responsibility Split

**DarkPlaces owns (spatial):**
- All 3D geometry, lighting, fog, particles
- AoA entity rendering and animation
- Camera path and viewport
- Spatial audio
- Post-processing shader nodes that don't require frame history

**GStreamer compositor owns (temporal + bridge surfaces):**
- Legacy Cairo/Pango ward bridges only where DarkPlaces cannot yet host the
  dynamic content natively
- Temporal effects (feedback loops, frame differencing)
- Camera feed compositing
- Output routing (v4l2sink, HLS, OBS)
- HOMAGE choreographer and transition FSM

This split is principled: DarkPlaces excels at spatial rendering; GStreamer excels at temporal compositing and 2D overlays. Neither capability is wasted.

## 6. Sensory Environment

### 6.1 Tower Level Architecture

| Level | Y (Quake units) | Texture Theme | Fog | Lighting | Sound |
|---|---|---|---|---|---|
| Perception | -64 → 32 | Warm stone, earth | Dense amber | Dim, flickering warm | Low rumble, sensor hum |
| Cognition | 32 → 128 | Cool stone, carved | Medium blue-grey | Steady cool white | Processing clicks, data flow |
| Communication | 128 → 224 | Metal, grating | Light green tint | Pulsing directional | Whisper fragments, static |
| Expression | 224 → 320 | Dark metal, ornate | Sparse magenta | Dynamic colored | Musical undertones, synthesis |
| Grounding | 320 → 416 | Gold stone, polished | Clear golden | Bright convergent | Resonant drone, harmonics |

### 6.2 Sound Implementation

- Entity-based ambient emitters at each level boundary
- `SOUNDFLAG_FORCELOOP` for continuous drones
- 7 channels per entity for layered sonic texture
- OGG Vorbis format (streaming for large files)
- Volume/pitch modulation via QuakeC for stimmung response
- Background music via `cdtracks/` for overarching theme

### 6.3 Working Mode Sonic Shift

- R&D mode: warmer, louder ambient (energy)
- Research mode: cooler, quieter ambient (precision)
- Fog color + light color + sound volume all shift together

## 7. Live Cognitive Coupling

QuakeC reads /dev/shm state files via dpextensions `fopen`/`fgets` (verified capability TBD; fallback: config file `exec` polling).

| Signal | Source File | DarkPlaces Effect |
|---|---|---|
| Stimmung energy | `stimmung.json` | Light intensity multiplier, fog density, bounded postprocess pressure |
| Working mode | `~/.cache/hapax/working-mode` | Map swap (rnd↔research), fog color, r_brightness |
| Voice activity | `voice-state.json` | AoA rotation speed, light pulse frequency |
| Content density | `active_wards.json` | Sound volume scaling, fog clarity |
| Homage state | `homage-active.json` | Ward transition coupling via `uniforms.custom[4]` equivalent |

### 7.1 Camera Path

The production/review default is a stable noclip camera aimed into the
in-scroom ward/source field. This is intentional: the operator needs a fixed
OBS-reviewable posture while the migration is still being judged. Optional
motion remains available through `screwm_camera_orbit 1`, and headless manual
control is gated by `hapax-screwm-camera-gamepad.service` plus
`data/camera-manual.txt`; both are off by default. The gamepad bridge fails
closed unless an Xbox/Microsoft/XInput joystick is visible or the operator
explicitly supplies `--device`/`--allow-any-joystick`, preventing keyboard
joystick interfaces from unexpectedly taking over the POV.

The view body is QuakeC-owned, `MOVETYPE_NOCLIP`, and `SOLID_NOT`, so the POV
can move through the space freely when manual control is enabled and cannot be
shoved by BSP/player collision.

## 8. QuakeHomage Package

New `HomagePackage` registered in `shared/homage_package.py`:

```python
class QuakeHomage(HomagePackage):
    name = "quake"
    palette = HomagePalette(
        muted=(0.35, 0.30, 0.25, 1.0),       # Quake brown
        bright=(0.75, 0.70, 0.60, 1.0),       # Quake tan
        accent_cyan=(0.30, 0.55, 0.55, 1.0),  # Slipgate teal
        accent_magenta=(0.60, 0.20, 0.20, 1.0), # Blood red
        accent_green=(0.42, 0.56, 0.14, 1.0), # Quake olive
        accent_yellow=(0.70, 0.55, 0.25, 1.0), # Quake gold
        accent_red=(0.55, 0.00, 0.00, 1.0),   # Dark blood
        accent_blue=(0.20, 0.30, 0.45, 1.0),  # Quake steel
        terminal_default=(0.65, 0.60, 0.50, 1.0),
        background=(0.10, 0.08, 0.06, 1.0),   # Near-black brown
    )
    typography = HomageTypography(
        primary="Px437 IBM VGA 8x16",
        fallbacks=["Terminus", "Unscii", "DejaVu Sans Mono"],
        size_compact=10, size_normal=14, size_large=18, size_banner=24,
    )
    grammar = GrammarRules(
        punctuation_colour_role="accent_yellow",
        identity_colour_role="accent_green",
        container_shape="angular",
        line_start_marker="▌",
        raster_cell_required=True,
        transition_frame_count=6,  # Hard cuts, Quake-speed
    )
    anti_patterns = ["emoji", "rounded-corners", "fade-transitions", "proportional-font", "gradient-backgrounds"]
```

Transition vocabulary: teleport flash (white burst, 3 frames), quad damage pulse (blue overlay, 6 frames), slipgate shimmer (teal wave).

Signature artefacts: Quake console messages (`Playing demo ...`, `Connection accepted`), level title cards (gold text on brown), kill-feed-format ward state changes (`* Perception ward entered the tower`).

## 9. Aesthetic Migration Contract

### 9.1 Design Language Compliance

| DL Principle | Migration Approach |
|---|---|
| Functionalism (§1.1) | Tower geometry encodes 5-level cognitive hierarchy. Not decorative. |
| Minimalism (§1.2) | Quake's dark environments + fog = black negative space canvas |
| Proportional system (§1.3) | BSP grid-aligned (32-unit base = 1m). All geometry on grid. |
| Color is meaning (§1.4) | Per-level texture+light colors encode semantic categories |
| Density (§1.5) | Ward identities rendered small and close via CSQC projection; full live contents bridge through compositor only while texture-upload limits remain |
| Single typeface (§1.6) | JetBrains Mono for wards; Px437 for QuakeHomage artefacts |

### 9.2 HOMAGE Framework Integration

QuakeHomage is a third HomagePackage alongside BitchX and Enlightenment-Moksha. The choreographer, transition FSM, and shader coupling mechanisms are unchanged for compositor-owned live ward contents, while CSQC now carries the in-engine ward identity/drift layer and the compositor path remains the bridge for richer dynamic ward surfaces until runtime texture upload is solved.

The difference: when QuakeHomage is active, ward transitions use Quake-speed hard cuts (6 frames) instead of BitchX zero-chrome or Enlightenment soft envelopes (20 frames).

### 9.3 Reverie Vocabulary Preservation

62 WGSL nodes → DarkPlaces GLSL post-processing (39 nodes Phase 4-5) + GStreamer glfeedback (11 temporal nodes) + deferred (1 waveform node).

The visual vocabulary is preserved in full. The execution environment changes from wgpu to DarkPlaces GLSL + glfeedback, but the operator sees the same effects.

## 10. Deliverables

### D1: DarkPlaces Engine + Configuration [COMPLETE]
- `darkplaces-git` installed from AUR
- Game directory: `~/.darkplaces/screwm/`
- Config: `~/.darkplaces/screwm/config.cfg`

### D2: Tower BSP Map Generator [COMPLETE]
- `scripts/generate-screwm-map.py`
- Output: `assets/quake/maps/screwm.bsp` (13KB, compiles clean)

### D3: Texture/Asset Provenance [COMPLETE]
- LibreQuake v0.09-beta BSD art/media assets provide external free-content
  base game data outside this repository under `~/.darkplaces/id1/`.
- Screwm WAD textures, maps, AoA model, ambient OGG loops, QuakeC/CSQC
  binaries, GLSL shader, and runtime configs are project-authored/generated
  assets documented in `assets/quake/LICENSES.md`.

### D4: QuakeC Camera + Cognitive Coupling Mod [IN PROGRESS]
- `assets/quake/qc/` — defs.qc, camera.qc, world.qc, coupling.qc
- Compiled progs.dat
- Stable noclip review POV is default; optional controller/manual camera is gated.
- Live coupling currently drives AoA spin, fog, postprocess vectors, source/ward
  lights, audio reactivity, and working-mode map changes. Camera motion remains
  opt-in during review.

### D5: AoA/Tetrix Anchor MDL [COMPLETE]
- `scripts/generate-aoa-mdl.py`
- `assets/quake/models/aoa.mdl`
- Spawned and rotated by QuakeC at `AOA_CENTER`.
- Geometry follows the authored `aoa-tetrix-v2` root with an attendant sphere
  instead of the retired flat/legacy Sierpinski-only anchor.

### D6: v4l2loopback Capture [COMPLETE - BOUNDED SMOKE PASSED]
- `/etc/modprobe.d/v4l2loopback-hapax.conf` updated (video52=DarkPlaces in the unified 14-device config)
- `scripts/darkplaces-capture.sh`
- `scripts/darkplaces-v4l2-xorg.sh` for OBS-free headless capture on a
  dedicated NVIDIA Xorg server
- `scripts/darkplaces-v4l2-xvfb.sh` retained as a software-display fallback
  only; it is not the production GPU-pinned path
- `scripts/darkplaces-gl-preflight.sh` as a direct launch and systemd
  fail-closed GPU guard
- `scripts/darkplaces-attended-smoke.sh` for bounded topology/evidence capture
  before runtime reactivation, including `glxinfo` preflight and DarkPlaces
  `GL_RENDERER` assertion against the expected GPU
- Dedicated Xorg probe validated on 2026-05-23: `DISPLAY=:82 glxinfo -B`
  reported `NVIDIA GeForce RTX 5060 Ti/PCIe/SSE2` using `BusID PCI:5:0:0`
- Bounded v4l2 smoke passed on 2026-05-24:
  `scripts/darkplaces-attended-smoke.sh --v4l2 --duration-s 10` completed in
  `/home/hapax/hapax-state/hardware-validation/darkplaces-screwm-20260524T013220Z-1591390`
  with `GL_RENDERER: NVIDIA GeForce RTX 5060 Ti/PCIe/SSE2`.
- `/dev/video52` readback captured a nonblank 1280x720 Screwm frame:
  `/home/hapax/hapax-state/hardware-validation/darkplaces-screwm-20260524T013220Z-1591390/screwm-video52-frame.png`.
- Follow-up bounded v4l2 smoke passed on 2026-05-24:
  `scripts/darkplaces-attended-smoke.sh --v4l2 --duration-s 20` completed in
  `/home/hapax/hapax-state/hardware-validation/darkplaces-screwm-20260524T023733Z-1312953`
  with `GL_RENDERER: NVIDIA GeForce RTX 5060 Ti/PCIe/SSE2`.
- That run captured a nonblank 1280x720 `/dev/video52` readback frame at
  `/home/hapax/hapax-state/hardware-validation/darkplaces-screwm-20260524T023733Z-1312953/screwm-video52-readback.png`
  and kernel logs showed no data-fabric sync-flood, Xid, AER, MCE, or GPU-fallen-off
  evidence during the bounded window.
- Desktop caveat: the dedicated Xorg path correlated with KDE/PowerDevil DRM/DDC
  hotplug churn and apparent desktop blanking around 2026-05-23T21:37:54-21:38:00
  CDT. Treat `scripts/darkplaces-v4l2-xorg.sh` as a validation harness, not the
  production always-on route, until a follow-up run proves no desktop display
  disturbance.
- Display-safe fallback smoke passed on 2026-05-24:
  `scripts/darkplaces-attended-smoke.sh --xvfb --duration-s 12` completed in
  `/home/hapax/hapax-state/hardware-validation/darkplaces-screwm-20260524T024639Z-1801937`.
  It captured a nonblank `/dev/video52` readback frame at
  `/home/hapax/hapax-state/hardware-validation/darkplaces-screwm-20260524T024639Z-1801937/screwm-video52-xvfb-readback.png`
  without desktop display churn or kernel GPU risk evidence. This route rendered
  on RTX 5090, so it is a safe fallback witness, not final 5060 Ti allocation.
- Runtime activation remains opt-in; persistent module config changes require
  module reload or reboot to be guaranteed across boot.

### D7: Compositor Source Integration [IN PROGRESS]
- `/dev/video52` is declared in `config/compositor-layouts/default.json` as
  the `darkplaces` v4l2 source with `role=darkplaces_background`.
- `_FALLBACK_LAYOUT` mirrors the on-disk DarkPlaces source so rescue startup
  does not fall back to the pre-migration source catalog.
- `SourceRegistry` now accepts passive `v4l2` layout handles; DarkPlaces
  remains consumed by the GStreamer graph, not Cairo blitting.
- `pipeline.py` resolves DarkPlaces device/caps from layout state first, then
  environment/default fallback, and refuses OBS Virtual Camera unless explicitly
  overridden to avoid OBS/compositor loops.
- CUDA compositor ingress uploads the DarkPlaces v4l2 feed into
  CUDAMemory/NV12 before connecting to `cudacompositor`.
- Fallback path if DarkPlaces unavailable: leave the compositor background
  pinned black and publish a degraded runtime state; do not silently reintroduce
  fourth-wall ward overlays as the migration target.
- Runtime evidence collected: production compositor launches with DarkPlaces as
  the primary source and no external ward layout assignments; ward identity is
  carried by the in-scroom BSP/WAD field.

### D7a: CSQC Ward State Coupling [IN PROGRESS]
- `assets/quake/csqc/csprogs.dat` loads as a DarkPlaces CSQC module.
- CSQC preserves the server-rendered world and keeps projected ward
  `drawstring`/`drawline` output behind opt-in `screwm_csqc_overlay 1`.
- CSQC reads `data/working-mode.txt`, `data/stimmung-energy.txt`, and
  `data/voice-active.txt` plus all 36 `data/ward-XX.txt` and
  `data/ward-active-XX.txt` exports from the game directory to modulate
  engine-side dynamic lights.
- Ward identity and the first drift graph are in BSP/WAD geometry/materials;
  CSQC is now the live coupling layer, not the default ward text surface.
- CSQC also carries live six-camera/source state into in-world dynamic lights
  using separate semantic priority and fresh-frame evidence scalars.
- HOMAGE activation is exported from `homage-active.json` /
  `homage-substrate-package.json` into DarkPlaces-readable scalars; QuakeHomage
  now enters the in-scroom ward/source lightfield instead of remaining only a
  compositor-side package marker.
- The old visual-layer and Stimmung surfaces are exported as
  `IN_SCROOM_VISUAL_LAYER_STATE`: display state, stance, eight visual zones,
  ambient speed/turbulence/warmth/brightness, transition progress, health,
  resource, error, grounding, exploration, audience, operator energy,
  coherence, and audio presence are embodied as scroom-local light pressure.
- The visual-chain and effect-drift systems are exported as
  `IN_SCROOM_EFFECT_DRIFT_STATE`: nine canonical visual-chain dimensions,
  noise/drift/color/feedback/aperture pressure, active pass ratio, max delta,
  parameter-region count, and tonal/atmospheric/temporal/texture/edge family
  pressure all feed in-engine structures instead of remaining shader-side
  abstractions.
- The current imagination fragment is exported as
  `IN_SCROOM_IMAGINATION_FRAGMENT`: canonical dimensions, salience,
  continuation, and water/fire/earth/air/void material selection modulate the
  AoA/tetrix intent region inside the scroom.
- Live RGBA source manifests are exported as
  `IN_SCROOM_CONTENT_SOURCE_MANIFESTS`: source freshness, opacity, layer, area,
  and count become in-world source-plane pressure. This is the containment path
  for legacy visual-pool and overlay-zone content while runtime texture
  replacement remains blocked.
- The GEM recruitment/mural surface is exported as
  `IN_SCROOM_GEM_RECRUITMENT_MURAL`: recruitment score/freshness, frame
  freshness/count, layer density/opacity, hold pressure, and narrative pressure
  modulate the in-scroom GEM/recruitment region instead of remaining only a
  compositor CP437 band.

### D8: hapax-darkplaces Systemd Unit [COMPLETE]
- `systemd/units/hapax-darkplaces-v4l2.service`
- Runtime opt-in gated after 2026-05-23 AMD data-fabric reset evidence
- GPU selection requires validation: `CUDA_VISIBLE_DEVICES` does not pin OpenGL
- Current `:0` GL preflight reports RTX 5090; `DRI_PRIME=1` and NVIDIA offload
  envs did not switch it on this host during containment testing.
- Mesa/Zink GLX device-selection probes also reported RTX 5090; the 5060 Ti is
  visible as `PCI:5:0:0` but has no display devices attached.
- `scripts/darkplaces-v4l2-xorg.sh --probe-only` starts a bounded dedicated
  root Xorg server on `PCI:5:0:0`, runs the GL preflight against `DISPLAY=:82`,
  then tears it down. This validated the 5060 Ti GL route without launching
  DarkPlaces.
- `hapax-darkplaces-v4l2.service` now uses the display-safe Xvfb feed route for
  the active always-on service because the dedicated Xorg option can disturb the
  desktop display stack and currently produced black x11grab readback in live
  testing.
- DarkPlaces units run scripts from the source-activation worktree, with
  `hapax-compositor-runtime-source-check` gating required scripts/assets before
  startup, so production cannot silently launch stale lane-local migration code.
- The unit is `Type=notify`/`NotifyAccess=all` with `WatchdogSec=30s`. Both
  `scripts/darkplaces-v4l2-xvfb.sh` and `scripts/darkplaces-v4l2-xorg.sh` emit
  `READY=1` only after DarkPlaces and the ffmpeg v4l2 writer are alive, and emit
  `WATCHDOG=1` only while both remain alive.
- Runtime evidence on 2026-05-24 after repeated deploy/restart cycles:
  `hapax-darkplaces-v4l2`, `hapax-darkplaces-bridge`,
  `hapax-v4l2-bridge`, and `studio-compositor` active; renderer unit
  `Type=notify`, `WatchdogUSec=30s`, `NRestarts=0`, and fresh
  `WatchdogTimestamp`. The controller service remained opt-in/inactive.
- Restart=always

### D9: QuakeHomage Package [COMPLETE]
- `agents/studio_compositor/homage/quake.py`
- Palette, typography, grammar, transitions, artefacts
- Registered by `agents/studio_compositor.homage` at import time.
- Runtime package activation is bridged into the DarkPlaces game directory as
  `data/homage-*.txt`, where CSQC folds it into ward/drift/source lighting.

### D10: Dual BSP Mode Compilation
- `scripts/generate-screwm-map.py --mode rnd` / `--mode research`
- Texture set swap: warm Gruvbox vs cool Solarized
- Fog color + lighting presets per mode

### D11: Ambient Sound Design
- OGG files per tower level in `assets/quake/sound/ambient/`
- Entity-based emitters in BSP map
- QuakeC sound triggers
- Five ambient zones are precached and spawned by `world.qc`.

### D12: GLSL Post-Processing Port (Phase 4)
- 39 shader nodes as DarkPlaces GLSL post-processing passes
- Performance validation on 5060 Ti
- Visual fidelity comparison vs wgpu originals
- Live Reverie scalars now drive DarkPlaces UserVec1-4 scroom fields:
  salience/trace/temporal/spectral plus material, inversion, aperture, and
  thermal pressure. Positive UserVec4.x is material emboss only; implicit UV
  rotation is not part of the stable review baseline.
- UserVec2.w now carries a bounded sharpen pass, driven by live salience and
  audio onset, so in-scroom ward panels regain material edge definition after
  fog and bloom without adding camera-like motion.
- Aperture pressure is non-destructive edge attenuation, and horizontal signal
  shear is bounded by live signal noise so the fixed noclip review POV remains
  readable while the effect vocabulary remains embodied in the scroom.
- The review baseline has no clocked global brightness pulses: shader strobe
  and breathing are disabled, and CSQC ward/source/drift dynamic-light radii
  are driven by live state scalars rather than periodic `sin(time)` terms.
- Until all 39 Phase 4 shader nodes are ported with visual parity, the
  visual-chain/effect-drift exporter is the intentional containment layer for
  migrated shader intent. It does not satisfy the Phase 4 parity gate by
  itself, but it prevents the legacy Scroom systems from living only in the
  fourth-wall compositor while the GLSL node port proceeds.

### D13: hapax-imagination Retirement (Phase 6)
- Remove from default.target
- Archive systemd unit
- Update CLAUDE.md references

## 11. Mutation Surface

- source: `scripts/` (3 files: map generator, AoA generator, capture script)
- source: `assets/quake/` (new directory: maps, textures, qc, models, sound, config)
- source: `config/darkplaces/` (v4l2loopback config)
- source: `config/compositor-layouts/default.json` (DarkPlaces source addition)
- source: `agents/studio_compositor/` (compositor integration, QuakeHomage)
- source: `shared/homage_package.py` (registry update)
- source: `systemd/units/` (hapax-darkplaces.service)
- runtime: v4l2loopback device /dev/video52
- runtime: GPU VRAM ~200-500MB on 5060 Ti
- retirement: hapax-imagination.service (Phase 6)

## 12. Migration Phases

| Phase | Scope | Duration | Evidence Gate |
|---|---|---|---|
| 0: Foundation | DarkPlaces installed, BSP compiles, systemd unit | **DONE** | BSP loads in engine |
| 1: Tower Live | Textures, lights, fog, v4l2 capture, compositor integration | 2-4h | OBS shows DarkPlaces carrying wards in-scroom |
| 2: Camera + AoA | Stable noclip review camera, optional manual/orbit camera, AoA MDL, sound emitters | 4-8h | Stable review POV, optional free movement, AoA visible, sound per level |
| 3: Mode Coupling | Dual BSPs, fog/brightness mode switch, stimmung coupling | 1-2d | Working mode change shifts tower aesthetic |
| 4: Shader Port P1 | 39 EXCELLENT+GOOD nodes as GLSL post-processing | 1-2w | Visual parity with reverie for ported nodes |
| 5: Shader Port P2 | 11 MODERATE nodes, accumulator plugin investigation | 2-4w | Extended visual vocabulary in DarkPlaces |
| 6: Retirement | hapax-imagination removed from boot chain | After P4 | All production visual output via DarkPlaces |

## 13. Axiom Compliance

| Axiom | Weight | Approach |
|---|---|---|
| `single_user` | 100 | Single render surface, no per-viewer customization |
| `executive_function` | 95 | DarkPlaces ships pre-configured, operator does not tune |
| `corporate_boundary` | 90 | CC0/BSD textures only, no proprietary assets |
| `interpersonal_transparency` | 88 | No personal data rendered in Quake scene; wards respect existing consent gates |
| `management_governance` | 85 | LLMs prepare tower content and aesthetic; operator approves |

## 14. Evidence Gates

- [x] DarkPlaces renders the Scroom/Screwm substrate with textures at 1920×1080/60
- [x] v4l2loopback /dev/video52 captures DarkPlaces output
- [x] Layout/registry/pipeline contracts declare DarkPlaces as the v4l2 background source
- [x] All 36 non-DarkPlaces Screwm visual sources have in-scroom BSP/WAD anchors
- [x] In-world BSP drift carriers connect the ward field
- [x] Compositor accepts DarkPlaces as primary background without external ward overlays
- [x] Stable QuakeC review POV is noclip/free-camera, with optional manual/orbit movement gated off by default
- [x] AoA/tetrix anchor with attendant sphere visible and rotating
- [x] 5 ambient sound zones are present and spawned by QuakeC
- [x] Working mode switch changes fog color + texture set
- [x] Stimmung/audio/Reverie state modulates AoA spin, fog, postprocess fields, and ward/source light intensity
- [x] Visual-layer, visual-chain/effect-drift, imagination-fragment, content-source manifest, and GEM recruitment/mural intent is exported into DarkPlaces as in-scroom scalar fields
- [x] Texture/asset provenance documented in `assets/quake/LICENSES.md`
- [x] Systemd unit starts/restarts cleanly with WatchdogSec
- [ ] 1-hour stability test without memory growth or crashes
- [ ] 39 shader nodes ported with visual parity (Phase 4)
- [ ] hapax-imagination disabled without regression (Phase 6)
- [ ] OBS screenshot verification of final composite at each phase
