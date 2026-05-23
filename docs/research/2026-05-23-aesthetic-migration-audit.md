# Aesthetic Migration Audit: Logos Design Language to DarkPlaces Quake Engine

**Date:** 2026-05-23
**Purpose:** Catalog every visual commitment from the design language, HOMAGE framework, and reverie shader vocabulary that must migrate into DarkPlaces. Research only — no implementation decisions.

---

## 1. Design Language Visual Commitments (logos-design-language.md)

### 1.1 Color Semantic Contract

The entire color system is dual-palette and mode-driven. Every semantic color token has a Gruvbox (R&D) and Solarized (Research) value.

**Neutral scale** (10 tokens):
`bg`, `surface`, `elevated`, `border`, `border-muted`, `text-muted`, `text-secondary`, `text-primary`, `text-emphasis`, `text-bright`. Each has a Gruvbox hex and a Solarized hex. These govern all background, elevation, border, and text rendering.

**Semantic colors** (7 hues, each with -400 primary and -700 deep variant = 14 tokens):
`green`, `red`, `yellow`, `blue`, `orange`, `fuchsia`, `emerald`. Meanings: success/error/warning/info/accent/governance/ambient.

**Desktop accent mapping** (6 tokens):
`ACCENT_PRIMARY` (yellow-400), `ACCENT_ACTIVE` (green-400), `ACCENT_URGENT` (red-400), `ACCENT_INFO` (blue-400), `ACCENT_WARN` (orange-400), `ACCENT_CYAN` (emerald-400).

**Signal category colors** (8 categories): `context_time` (blue), `governance` (fuchsia), `work_tasks` (orange), `health_infra` (red), `profile_state` (green), `ambient_sensor` (emerald), `voice_session` (yellow), `system_state` (text-secondary).

**Stimmung stance colors** (4 stances): Nominal (transparent), Cautious (yellow 15%), Degraded (orange 25% + inset glow), Critical (red 35% + glow + pulse).

**Severity ladder** (5 levels): green → yellow → orange → red → zinc-700 (unknown).

**Detection overlay colors** (mode-INVARIANT by design): 5 object categories, 4 gaze directions, 6 emotion tints, consent states. These are fixed perceptual vocabulary — they do NOT switch with mode.

**Voice overlay colors** (mode-aware): 4 voice states (green/yellow/blue/zinc), 4 acceptance states (green/yellow/red/zinc).

**Migration requirement:** DarkPlaces must support the full dual-palette color system. Fog, lighting, particle colors, and any HUD elements need to switch between Gruvbox and Solarized palettes when working mode changes. Detection overlay colors are exempt from mode switching.

### 1.2 Mode System

Two modes: R&D (Gruvbox Hard Dark) and Research (Solarized Dark). Fortress is council-only gating, not a visual mode.

**What mode changes:** Color palette (every token), wallpaper, GTK theme.
**What mode does NOT change:** Spatial layout, typography (JetBrains Mono), animation tempo, information density, proportional system, compositor presets, ambient shaders.

**Propagation path:** `~/.cache/hapax/working-mode` → `hapax-theme-apply` script → surfaces. Script covers: Hyprland borders, wallpaper, foot terminal (USR1/USR2), waybar CSS swap, mako config swap, fuzzel config swap, hyprlock swap, GTK theme, cursor theme, hyprsunset color temperature.

**Migration requirement:** DarkPlaces needs a mode-switch receptor — either polling `~/.cache/hapax/working-mode` or receiving a signal from `hapax-theme-apply`. Lighting, fog color, sky, and texture tinting must respond to mode.

### 1.3 Proportional System

2px base unit. All spacing is integer multiples. This applies across desktop and Logos app.

**Migration consideration:** Quake's coordinate system is arbitrary units, not pixels. The proportional system governs UI elements, not 3D geometry. Ward overlays (still rendered by GStreamer compositor) continue to use the 2px base. DarkPlaces internal geometry is exempt. HUD elements (if any) should respect it.

### 1.4 Typography

Single typeface: JetBrains Mono. Everywhere. Size varies by context but family never changes.

**HOMAGE exception:** The HOMAGE framework overrides typography per-package. BitchX uses `Px437 IBM VGA 8x16` (CP437 raster). A QuakeHomage package would logically use a Quake-era font.

**Migration consideration:** DarkPlaces console and HUD text have their own font system (conchars). Ward text (still Cairo/Pango on GStreamer) keeps JetBrains Mono or HOMAGE fonts. DarkPlaces-internal text should use an authentic Quake-era bitmap font, which is consistent with HOMAGE philosophy.

### 1.5 Spatial Model

Five regions: Horizon (top), Field (middle-left), Ground (middle-center), Watershed (middle-right), Bedrock (bottom). Three depth states: Surface, Stratum, Core.

**Migration consideration:** The five-region terrain is a Logos React app concept. DarkPlaces replaces the Ground region's 3D content (the Screwm tower interior). Ward overlays and region structure remain in the compositor layer on top.

### 1.6 Signal System

8 signal categories with color affinity and severity-driven animation (breathing). Pip sizes: 6px/8px/10px by severity. Density constraints per depth level.

**Migration consideration:** Signals are rendered by `SignalCluster` components in the Logos React app and by `ZoneOverlay` on the compositor. DarkPlaces doesn't render signals directly. However, signal severity could influence DarkPlaces lighting/fog as an ambient channel.

### 1.7 Animation Vocabulary

4 families:
1. **Breathing** — sinusoidal opacity oscillation, ease-in-out, severity-driven tempo.
2. **Transitions** — 200-300ms, ease-out, no bounce/elastic/spring.
3. **Depth flash** — green-400 at 20% → transparent, 300ms single-shot.
4. **Decay** — linear opacity decay from 1.0 to min 0.3 over TTL.
5. **Ambient** — 12s cycle, drift not oscillate, 20-40% opacity text, 8-15% shapes.

**Migration requirement for DarkPlaces:**
- Breathing: achievable via QuakeC light pulsing or particle alpha oscillation.
- Transitions: camera moves, fog shifts. 200-300ms is achievable.
- Depth flash: translatable to brief light flash in the scene.
- Decay: particle system fade.
- Ambient: fog drift, slow light cycling, particle drift.

### 1.8 Stream Mode Considerations

Broadcast-safe constraints on stream-visible surfaces:
- Min 12px text on-stream.
- Saturation ceiling (luminance > 0.7 AND saturation > 0.85 → mute 15% chroma).
- Animation stability (opacity delta >= 0.5, or position/scale delta >= 2px, or color crossing semantic boundary).

**Migration requirement:** DarkPlaces output feeds into the GStreamer compositor which is captured for broadcast. DarkPlaces-rendered content is stream-visible and must respect the saturation ceiling and animation stability rules. Text (if any rendered by DarkPlaces) must be >= 12px equivalent.

---

## 2. HOMAGE Framework Requirements (2026-04-18 spec)

### 2.1 HomagePackage Abstraction

The existing Screwm-Quake ISAP (`2026-05-23-screwm-quake-hybrid-isap.md`) already proposes registering a `QuakeHomage` package. The framework requires:

- `name: str` — "quake" or "darkplaces"
- `grammar: GrammarRules` — punctuation/identity/content color roles, line-start marker, container shape, raster cell requirement, transition frame count, event rhythm, signed artefacts.
- `typography: TypographyStack` — Quake-era font (conchars-derived or similar).
- `palette: HomagePalette` — Quake's original palette or a stylized variant mapped to the semantic roles.
- `transition_vocabulary: TransitionVocab` — named transitions for entry/hold/exit/swap.
- `coupling_rules: CouplingRules` — bidirectional ward-shader contract.
- `signature_conventions: SignatureRules` — authored content rules.
- `voice_register_default: VoiceRegister` — which register DarkPlaces activates.

### 2.2 Transition FSM

Every Cairo source must implement `HomageTransitionalSource` mixin with states: `entering`, `hold`, `exiting`, `absent`. The choreographer reconciles pending transitions against concurrency rules (max 2 simultaneous entries/exits per tick, netsplit-burst every 120s+).

**Migration consideration:** Ward rendering is unchanged (still Cairo on GStreamer). The DarkPlaces scene itself is the background — it doesn't go through ward transitions. However, DarkPlaces camera changes, lighting shifts, and fog transitions should be synchronized with the choreographer's cadence to maintain compositional coherence.

### 2.3 Ward-Shader Coupling

Bidirectional contract via `uniforms.custom[4]`:
- `.x = active_transition_energy` (0..1)
- `.y = homage_palette_accent_hue_deg` (0..360)
- `.z = signature_artefact_intensity` (0..1)
- `.w = rotation_phase` (0..1)

Reverse channel: shaders emit `uniforms.shader_energy` via `/dev/shm/hapax-imagination/shader-feedback.json`.

**Migration requirement:** DarkPlaces must participate in this coupling. Options:
1. DarkPlaces reads the uniform values from shared memory and adjusts its rendering (fog density, light color, camera speed).
2. DarkPlaces writes its own energy metric (player movement speed, particle density, lighting intensity) to a feedback file that the choreographer reads.

### 2.4 IntentFamily Extensions

6 new intent families: `homage.rotation`, `homage.emergence`, `homage.swap`, `homage.cycle`, `homage.recede`, `homage.expand`.

**Migration consideration:** These drive ward animations, not DarkPlaces directly. But a QuakeHomage package could map these to DarkPlaces-native events (camera position change for emergence, fog shift for recede, light burst for expand).

### 2.5 Director Integration

The structural director gains `homage_rotation_mode` with 4 modes: `steady` (~90s), `deliberate` (~180s), `rapid` (~30s), `burst` (netsplit-style mass transition, every 120s+).

**Migration consideration:** DarkPlaces camera path cadence should align with the rotation mode. Steady → slow pendulum sweep. Rapid → faster camera movement. Burst → camera teleport between preset positions.

### 2.6 BitchX Anti-Patterns (applicable to ALL packages)

Violations that log metrics: emoji, anti-aliased text, proportional fonts, modern flat-UI, ISO-8601 timestamps, rounded corners, fade/dissolve transitions, Swiss-grid MOTD.

**Migration consideration for Quake package:** A QuakeHomage would define its own anti-patterns — e.g., PBR textures, high-poly models, anti-aliased edges, modern lighting (ray tracing), particle systems that look too smooth. The package must enforce authentic Quake I retro aesthetic.

---

## 3. Reverie Shader Vocabulary (62 WGSL Nodes)

### 3.1 Full Node Catalog

The 62 WGSL shader nodes in `agents/shaders/nodes/`:

**Always-on vocabulary (8 nodes):** `noise_gen`, `reaction_diffusion`, `colorgrade`, `drift`, `breathing`, `feedback`, `content_layer`, `postprocess`

**Satellite-recruitable (54 nodes):** `ascii`, `blend`, `bloom`, `chroma_key`, `chromatic_aberration`, `circular_mask`, `color_map`, `crossfade`, `diff`, `displacement_map`, `dither`, `droste`, `echo`, `edge_detect`, `emboss`, `fisheye`, `fluid_sim`, `glitch_block`, `grain_bump`, `halftone`, `invert`, `kaleidoscope`, `kuwahara`, `luma_key`, `mirror`, `nightvision_tint`, `noise_overlay`, `palette`, `palette_extract`, `palette_remap`, `particle_system`, `pixsort`, `posterize`, `rutt_etra`, `scanlines`, `sharpen`, `sierpinski_content`, `sierpinski_lines`, `slitscan`, `solid`, `strobe`, `stutter`, `syrup`, `thermal`, `threshold`, `tile`, `trail`, `transform`, `tunnel`, `vhs`, `vignette`, `voronoi_overlay`, `warp`, `waveform_render`

### 3.2 DarkPlaces Capability Mapping

**Direct mapping (DarkPlaces has native equivalent):**

| Shader Node | DarkPlaces Equivalent | Notes |
|---|---|---|
| `fog`/atmosphere (via `colorgrade`) | `gl_fog`, `r_fog_*` cvars | DarkPlaces has volumetric fog support |
| `particle_system` | DarkPlaces particle system | Extensive particle effects via effectinfo.txt |
| `bloom` | `r_bloom` cvar | DarkPlaces has built-in bloom |
| `colorgrade` | `r_glsl_postprocess_uservec*` | Custom GLSL post-processing supported |
| `vignette` | Post-process shader | Via DarkPlaces GLSL framework |
| `dither` | Not native but achievable via post-process | Low priority — Quake inherently has low color depth |
| `posterize` | Post-process shader | Fits Quake aesthetic naturally |

**Achievable via DarkPlaces GLSL post-processing:**

| Shader Node | Approach | Difficulty |
|---|---|---|
| `chromatic_aberration` | Post-process fragment shader | Low |
| `scanlines` | Post-process fragment shader | Low |
| `vhs` | Post-process fragment shader | Medium |
| `noise_overlay` | Post-process fragment shader | Low |
| `glitch_block` | Post-process fragment shader | Medium |
| `halftone` | Post-process fragment shader | Medium |
| `ascii` | Post-process fragment shader | Medium |
| `edge_detect` | Post-process fragment shader | Low |
| `invert` | Post-process fragment shader | Trivial |
| `threshold` | Post-process fragment shader | Trivial |
| `fisheye` | Post-process fragment shader | Low |
| `sharpen` | Post-process fragment shader | Low |

**Achievable via DarkPlaces engine features:**

| Shader Node | Approach | Notes |
|---|---|---|
| `breathing` | Light entity pulsing (QuakeC) | Sinusoidal light intensity modulation |
| `drift` | Camera movement (QuakeC) | Slow automated camera path |
| `feedback` | Not native — would need render-to-texture loop | Complex; DarkPlaces may support via FBO |
| `mirror` | DarkPlaces mirror entities | Limited support |
| `warp` | Texture warp (water/lava shaders) | Native Quake feature |
| `trail` | Particle trail effects | Native DarkPlaces feature |
| `blend` | Multi-texture blending | Native OpenGL |

**Needs different approach (no direct DarkPlaces equivalent):**

| Shader Node | Why | Alternative |
|---|---|---|
| `reaction_diffusion` | GPU compute simulation, no DarkPlaces equivalent | Pre-rendered texture sequences or leave to compositor layer |
| `fluid_sim` | Same — GPU compute | Pre-rendered or compositor layer |
| `voronoi_overlay` | Procedural generation, no DarkPlaces equivalent | Pre-rendered texture or compositor layer |
| `sierpinski_content` | Fractal rendering, requires compute | Leave to compositor layer (it's the central Hapax visual) |
| `sierpinski_lines` | Same | Compositor layer |
| `waveform_render` | Audio-reactive real-time rendering | Compositor layer (needs audio input) |
| `content_layer` | Composites external content | Compositor layer by definition |
| `noise_gen` | Procedural noise generation | Pre-baked noise textures or DarkPlaces noise shader |
| `rutt_etra` | Laser-scan aesthetic, requires vertex displacement | Pre-rendered or compositor |
| `slitscan` | Temporal buffer, requires frame history | Compositor layer |
| `displacement_map` | Requires external map input | Possible via DarkPlaces normal mapping |
| `droste` | Recursive zoom effect | Post-process shader (complex) |
| `kaleidoscope` | Mirror effect with rotation | Post-process shader (achievable) |
| `tunnel` | Radial zoom with tunnel geometry | Could be actual Quake geometry |
| `syrup` | Fluid-like distortion | Post-process shader |
| `pixsort` | Pixel sorting (requires sort algorithm) | Post-process shader (complex) |
| `stutter` | Frame hold/repeat | QuakeC frame rate manipulation |
| `strobe` | Rapid flash | QuakeC light strobe |
| `echo` | Temporal echo/ghosting | Would need FBO render-to-texture |
| `crossfade` | Cross-dissolve between sources | Compositor layer |
| `palette_extract` / `palette_remap` | Color palette analysis/remapping | Post-process shader |

**Not applicable (compositor-only by design):**

| Shader Node | Reason |
|---|---|
| `luma_key` | Video keying — compositor function |
| `chroma_key` | Video keying — compositor function |
| `circular_mask` | Masking — compositor function |
| `solid` | Solid color fill — compositor function |
| `diff` | Frame difference — compositor function |
| `postprocess` | Final output stage — compositor function |

### 3.3 Key Architectural Decision

The hybrid architecture (DarkPlaces renders 3D → v4l2loopback → GStreamer compositor) means **not all shader effects need to migrate to DarkPlaces**. The existing shader chain in the compositor continues to process the composited output. DarkPlaces provides the 3D scene; the compositor applies ward overlays and shader effects on top.

Effects that are scene-intrinsic (fog, lighting, particles, bloom) should live in DarkPlaces. Effects that are post-compositing (scanlines, VHS, color grading of the final output) can remain in the GStreamer shader chain.

---

## 4. Working Mode Propagation — Current Architecture

### 4.1 SSOT

File: `~/.cache/hapax/working-mode`. Values: `research`, `rnd`, `fortress`.

### 4.2 Writer

CLI: `hapax-working-mode [research|rnd]`. Also settable via `PUT /api/working-mode` (Logos API).

### 4.3 Readers

**Python agents:** `shared/working_mode.py` — `get_working_mode()` reads the file, defaults to RND on missing/invalid. Enum: `WorkingMode.RESEARCH`, `WorkingMode.RND`, `WorkingMode.FORTRESS`.

**Desktop surfaces (via `hapax-theme-apply` script):**
1. Hyprland borders + group/groupbar colors (hyprctl --batch)
2. Hyprpaper wallpapers (DP-1 primary, DP-2 secondary)
3. Foot terminal palette (USR1/USR2 signal)
4. Waybar CSS (symlink swap + SIGUSR2)
5. Mako notifications (symlink swap + makoctl reload)
6. Fuzzel launcher (symlink swap)
7. Hyprlock (symlink swap)
8. GTK theme + GTK4 color-scheme
9. Cursor theme (Bibata Classic vs Ice)
10. Hyprsunset color temperature (3200K rnd / 4500K research)

**Logos React app:** `ThemeProvider` reads `/api/working-mode`, selects palette, applies CSS custom properties to `<html>`.

**Compositor:** Mode-awareness is currently limited. The compositor Cairo wards are listed as "Low compliance" in the design language (§11.1) — arbitrary RGB tuples, generic font. The HOMAGE spec (§4.4) addresses this with `HomagePalette` that is mode-aware.

**Reverie (hapax-imagination):** Driven by stimmung, not working mode (§2.2 of design language — "Compositor presets are mode-invariant"). Color warmth in shaders is an open design question (§10.2).

### 4.4 DarkPlaces Integration Path

DarkPlaces needs a mode receptor. Options:
1. **File watcher:** QuakeC checks `~/.cache/hapax/working-mode` periodically (not native QuakeC — would need a helper).
2. **RCON command:** `hapax-theme-apply` sends an RCON command to DarkPlaces when mode changes. DarkPlaces responds by switching fog color, lighting warmth, texture tinting.
3. **Shared memory:** DarkPlaces reads from `/dev/shm/hapax-compositor/` like other surfaces.
4. **Environment reload:** DarkPlaces config files per mode, swapped by `hapax-theme-apply` + engine restart (too disruptive for 24/7 operation).

Best fit: **RCON** (option 2). DarkPlaces has native RCON support. `hapax-theme-apply` already runs as a bash script that propagates to multiple surfaces — adding an RCON send is one line. The RCON command triggers QuakeC that adjusts fog, lighting, and sky parameters.

---

## 5. Summary: What Must Migrate vs What Stays

### Must migrate TO DarkPlaces (scene-intrinsic):
- Fog system (mode-aware, Gruvbox warm / Solarized cool)
- Lighting palette (mode-aware, maps to semantic color tokens)
- Particle effects (mode-aware colors, breathing animation tempo)
- Bloom (if DarkPlaces handles it, otherwise compositor)
- Camera movement (aligned with HOMAGE rotation mode cadence)
- Scene geometry aesthetic (authentic Quake I BSP)

### Stays in GStreamer compositor (post-compositing):
- All 35+ Cairo ward overlays
- 12 GLSL shader chain effects (scanlines, VHS, color grading, etc.)
- Signal system rendering
- Detection overlays
- Ward transition FSM + choreographer
- Audio-reactive waveform render
- Sierpinski content rendering
- Content layer compositing
- Output routing (v4l2sink + HLS)

### Shared/bidirectional:
- HOMAGE coupling uniforms (custom[4]) — DarkPlaces reads and writes
- Stimmung → ambient parameters → both DarkPlaces and compositor
- Working mode → both surfaces simultaneously via `hapax-theme-apply`
- Choreographer cadence → DarkPlaces camera path timing

### New integration points needed:
1. DarkPlaces → v4l2loopback capture pipeline
2. RCON mode-switch receptor in `hapax-theme-apply`
3. Shared memory bridge for HOMAGE uniform coupling
4. QuakeC pendulum camera script with choreographer-synchronized cadence
5. DarkPlaces systemd user unit (`hapax-darkplaces.service`)
6. QuakeHomage package registration in `agents/studio_compositor/homage/`
