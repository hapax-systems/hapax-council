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

1. DarkPlaces renders the Screwm tower as a Quake BSP map with CC0 textures, colored lighting, fog, and spatial audio.
2. QuakeC drives camera, lighting, fog, and entity behavior based on live cognitive state (/dev/shm signals).
3. 39 reverie shader nodes (EXCELLENT+GOOD tiers) migrate to DarkPlaces GLSL post-processing.
4. 11 temporal shader nodes (DIFFICULT tier: feedback, echo, diff, stutter, slitscan, pixsort) remain in GStreamer glfeedback chain as post-compositor effects.
5. Wards remain in GStreamer compositor overlay (DarkPlaces cannot reload textures at runtime — research-confirmed blocker).
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

**Decision:** Wards stay in GStreamer compositor overlay. DarkPlaces owns spatial rendering; the compositor owns information overlays and temporal effects.

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
│  ├─ AoA MDL entity (Sierpinski tetrahedron, rotating)   │
│  ├─ 6 colored lights (per-level semantic colors)         │
│  ├─ Fog (density + color, mode-aware)                    │
│  ├─ 5 ambient sound zones (entity-based, 128 channels)  │
│  ├─ QuakeC camera (pendulum path, stimmung-driven)       │
│  ├─ QuakeC cognitive coupling (/dev/shm reader)          │
│  ├─ GLSL post-processing (39 ported shader nodes)        │
│  └─ Output: window → v4l2loopback /dev/video52           │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────┐
│ GStreamer Compositor (preserved, enhanced)               │
│  ├─ DarkPlaces /dev/video52 as PRIMARY background        │
│  ├─ 35 Cairo wards (BitchX/Enlightenment/Quake homage)  │
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

**GStreamer compositor owns (temporal + informational):**
- 35 Cairo/Pango ward overlays
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
| Stimmung energy | `stimmung.json` | Camera speed (120-150s period), light intensity multiplier, fog density |
| Working mode | `~/.cache/hapax/working-mode` | Map swap (rnd↔research), fog color, r_brightness |
| Voice activity | `voice-state.json` | AoA rotation speed, light pulse frequency |
| Content density | `active_wards.json` | Sound volume scaling, fog clarity |
| Homage state | `homage-active.json` | Ward transition coupling via `uniforms.custom[4]` equivalent |

### 7.1 Camera Path

QuakeC implements Catmull-Rom spline interpolation between 6 control points:

```
S0: (0, -32, 120)   → looking center, perception level
S1: (80, 64, 80)    → offset right, cognition
S2: (-60, 160, 100)  → offset left, communication
S3: (40, 256, -80)   → offset right rear, expression
S4: (-40, 352, 60)   → offset left, grounding
S5: (0, -32, 120)   → return to S0 (pendulum)
```

Period: `120.0 + (1.0 - energy) * 30.0` seconds (stimmung-driven, matching current scene.rs).

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
| Density (§1.5) | Wards rendered small and close via compositor overlay |
| Single typeface (§1.6) | JetBrains Mono for wards; Px437 for QuakeHomage artefacts |

### 9.2 HOMAGE Framework Integration

QuakeHomage is a third HomagePackage alongside BitchX and Enlightenment-Moksha. The choreographer, transition FSM, and shader coupling mechanisms are unchanged — wards still render via Cairo, still use HomageTransitionalSource mixin, still emit coupling payloads to `uniforms.custom[4]`.

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

### D3: CC0 Texture Pipeline [IN PROGRESS — epsilon lane]
- LibreQuake (BSD), Aquilarius (CC0), Kaz115 (CC0)
- `assets/quake/textures/`, `assets/quake/LICENSES.md`

### D4: QuakeC Camera + Cognitive Coupling Mod [IN PROGRESS — beta lane]
- `assets/quake/qc/` — defs.qc, camera.qc, world.qc, coupling.qc
- Compiled progs.dat

### D5: AoA Sierpinski Tetrahedron MDL [IN PROGRESS — delta lane]
- `scripts/generate-aoa-mdl.py`
- `assets/quake/models/aoa.mdl`

### D6: v4l2loopback Capture [IN PROGRESS]
- `/etc/modprobe.d/v4l2loopback-hapax.conf` updated (video52=DarkPlaces in the unified 14-device config)
- `scripts/darkplaces-capture.sh`
- `scripts/darkplaces-v4l2-xvfb.sh` for OBS-free headless capture
- `scripts/darkplaces-attended-smoke.sh` for bounded topology/evidence capture
  before runtime reactivation, including `GL_RENDERER` assertion against the
  expected GPU
- Activation requires module reload

### D7: Compositor Source Integration [IN PROGRESS]
- Interpipe producer for /dev/video52 source
- Layout JSON update: DarkPlaces as background layer
- Fallback path if DarkPlaces unavailable

### D8: hapax-darkplaces Systemd Unit [IN PROGRESS]
- `systemd/units/hapax-darkplaces.service`
- Runtime opt-in gated after 2026-05-23 AMD data-fabric reset evidence
- GPU selection requires validation: `CUDA_VISIBLE_DEVICES` does not pin OpenGL
- `hapax-darkplaces-v4l2.service` headless feed option
- Launch validation requires `HAPAX_DARKPLACES_SMOKE_ACK=1` and an attended
  run of `scripts/darkplaces-attended-smoke.sh`; the default expected GPU index
  is 1 until a new GPU allocation spec supersedes it.
- Restart=always

### D9: QuakeHomage Package
- `agents/studio_compositor/homage/quake.py`
- Palette, typography, grammar, transitions, artefacts

### D10: Dual BSP Mode Compilation
- `scripts/generate-screwm-map.py --mode rnd` / `--mode research`
- Texture set swap: warm Gruvbox vs cool Solarized
- Fog color + lighting presets per mode

### D11: Ambient Sound Design
- OGG files per tower level in `assets/quake/sound/ambient/`
- Entity-based emitters in BSP map
- QuakeC sound triggers

### D12: GLSL Post-Processing Port (Phase 4)
- 39 shader nodes as DarkPlaces GLSL post-processing passes
- Performance validation on 5060 Ti
- Visual fidelity comparison vs wgpu originals

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
| 1: Tower Live | Textures, lights, fog, v4l2 capture, compositor integration | 2-4h | OBS shows DarkPlaces + wards composite |
| 2: Camera + AoA | QuakeC pendulum camera, AoA MDL, sound emitters | 4-8h | Smooth camera traversal, AoA visible, sound per level |
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

- [ ] DarkPlaces renders tower BSP with textures at 1280×720
- [ ] v4l2loopback /dev/video52 captures DarkPlaces output
- [ ] Compositor accepts DarkPlaces as background source with wards overlay
- [ ] QuakeC pendulum camera traverses tower smoothly (120-150s period)
- [ ] AoA Sierpinski tetrahedron visible and rotating at tower center
- [ ] 5 ambient sound zones audible with distinct sonic character
- [ ] Working mode switch changes fog color + texture set
- [ ] Stimmung energy modulates camera speed + light intensity
- [ ] Textures CC0/BSD licensed (LICENSES.md audit)
- [ ] Systemd unit starts/stops/restarts cleanly with WatchdogSec
- [ ] 1-hour stability test without memory growth or crashes
- [ ] 39 shader nodes ported with visual parity (Phase 4)
- [ ] hapax-imagination disabled without regression (Phase 6)
- [ ] OBS screenshot verification of final composite at each phase
