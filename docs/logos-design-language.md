# Logos Design Language

Authority document for all visual surfaces of the hapax system. This document governs color, typography, spatial organization, animation, and mode-driven theming across the desktop environment and the Logos application.

**Status:** Normative
**Supersedes:** `docs/superpowers/specs/2026-03-10-hyprland-aesthetic-design.md` (color tables and config blocks; design principles retained)
**Companion documents:**
- `docs/logos-ui-reference.md` — Region content specification (what appears where at each depth)
- `docs/research/visual-design-parameters-research.md` — Aspirational; GPU visual surface techniques, not yet normative

---

## 1. Governing Principles

These principles are inherited from the desktop aesthetic spec and remain in force across all surfaces.

1. **Functionalism.** Every visual element carries information. Nothing is decorative. An element that does not encode state, afford interaction, or provide spatial orientation must be removed.

2. **Minimalism.** Black negative space is the canvas. Elements are flat on darkness. No depth simulation through shadows, frosted glass, or gradient backgrounds. The one exception is the investigation overlay's backdrop treatment (§7).

3. **Proportional system.** All spacing derives from a 2px base unit. Gaps, borders, padding are integer multiples. This applies to both the desktop compositor and the Logos application.

4. **Color is meaning.** No color is arbitrary. Every hue encodes a semantic category. Saturation encodes severity. Brightness encodes importance. Gray is normal; color demands attention (ISA-101 "going gray" principle).

5. **Density.** Information is rendered small and close. The operator builds spatial memory of where things live. Position is fixed; state is encoded through color, pattern, and motion within each position.

6. **Single typeface.** JetBrains Mono everywhere. Desktop, terminal, status bar, application. No proportional fonts. Size varies by context but the family never changes.

---

## 2. Mode System

The system has exactly two working modes. Mode governs the color palette across all visual surfaces simultaneously.

| Mode | Palette | Character | When |
|------|---------|-----------|------|
| **R&D** | Gruvbox Hard Dark | Warm, textured, energetic | Building, coding, producing, streaming |
| **Research** | Solarized Dark | Cool, clinical, precise | Reading, analyzing, writing, reviewing |

### 2.1 What mode changes

- **Color palette** — Every semantic color token switches between Gruvbox and Solarized values (§3).
- **Wallpaper** — Mode-specific background image.
- **GTK theme** — Application chrome follows mode.

### 2.2 What mode does NOT change

- **Spatial layout** — The five-region terrain, grid proportions, and region positions are mode-invariant.
- **Typography** — JetBrains Mono at the same sizes in both modes.
- **Animation tempo** — Breathing rates, transition durations, and easing curves are state-driven (§6), not mode-driven.
- **Information density** — Both modes show the same content at the same depth levels.
- **Terrain metaphor** — The geological strata metaphor holds in both modes. Solarized makes terrain feel like ice core or deep ocean stratigraphy rather than warm earth, but the spatial model is identical.
- **Proportional system** — 2px base unit, gap ratios, border widths.
- **Compositor presets** — The 12 visual effect presets are mode-invariant. They serve production/streaming, not ambient theming.
- **Ambient shader** — The GPU visual surface techniques (R-D, physarum, voronoi, wave, feedback) are driven by system state (stimmung), not working mode. Color warmth in shaders is an open design question (§10).

### 2.3 Mode propagation

Mode is set via `hapax-working-mode` script or `PUT /api/working-mode`. Propagation path:

1. State file: `~/.cache/hapax/working-mode`
2. Desktop: `hapax-theme-apply` → Hyprland borders, wallpaper, mako config, fuzzel config, hyprlock config, foot terminal signal, GTK theme; hapax-bar receives theme via control socket (`{"cmd":"theme","mode":"..."}` → instant CSS swap, no restart)
3. Logos app: `ThemeProvider` reads `/api/working-mode`, selects palette, applies CSS custom properties to `<html>`

---

## 3. Color Semantic Contract

This is the single source of truth for color meaning. All surfaces — desktop, terminal, Logos app — must derive their colors from this contract.

### 3.1 Palette tokens

Each token has a Gruvbox value and a Solarized value. Tokens are named by function, not by hue.

**Neutral scale** (background → text):

| Token | Gruvbox | Solarized | Usage |
|-------|---------|-----------|-------|
| `bg` | `#1d2021` | `#002b36` | Primary background |
| `surface` | `#282828` | `#073642` | Elevated surfaces (panels, bars, modals) |
| `elevated` | `#3c3836` | `#0a4050` | Secondary elevation (hover states, active panels) |
| `border` | `#504945` | `#2f525b` | Visible borders and dividers |
| `border-muted` | `#665c54` | `#436068` | Subtle structural borders |
| `text-muted` | `#928374` | `#586e75` | Disabled text, timestamps, counters |
| `text-secondary` | `#bdae93` | `#657b83` | Secondary labels, inactive items |
| `text-primary` | `#ebdbb2` | `#839496` | Body text, values, content |
| `text-emphasis` | `#fbf1c7` | `#93a1a1` | Headings, active labels |
| `text-bright` | `#fdf4c9` | `#fdf6e3` | Maximum contrast (rare, headlines only) |

**Semantic colors** (each has a -400 primary and -700 deep variant):

| Semantic | Gruvbox -400 | Gruvbox -700 | Solarized -400 | Solarized -700 | Meaning |
|----------|-------------|-------------|----------------|----------------|---------|
| `green` | `#b8bb26` | `#79740e` | `#859900` | `#4e5c00` | Success, healthy, active, consent-granted |
| `red` | `#fb4934` | `#9d0006` | `#dc322f` | `#8e100e` | Error, critical, alert, consent-denied |
| `yellow` | `#fabd2f` | `#b57614` | `#b58900` | `#735600` | Warning, cautious, actionable, interactive |
| `blue` | `#83a598` | `#076678` | `#268bd2` | `#0e507e` | Information, temporal, context, navigation |
| `orange` | `#fe8019` | `#af3a03` | `#cb4b16` | `#7b2d0d` | Accent, tasks, urgency, activity |
| `fuchsia` | `#d3869b` | `#8f3f71` | `#d33682` | `#831f50` | Governance, consent, special authority |
| `emerald` | `#8ec07c` | `#427b58` | `#2aa198` | `#19615c` | Ambient, sensor, environmental, secondary-positive |

### 3.2 Desktop accent mapping

The desktop environment uses a simplified subset. The theme `.conf` files must map to this contract:

| Desktop token | Maps to | Gruvbox | Solarized |
|---------------|---------|---------|-----------|
| `ACCENT_PRIMARY` | `yellow-400` | `#fabd2f` | `#b58900` |
| `ACCENT_ACTIVE` | `green-400` | `#b8bb26` | `#859900` |
| `ACCENT_URGENT` | `red-400` | `#fb4934` | `#dc322f` |
| `ACCENT_INFO` | `blue-400` | `#83a598` | `#268bd2` |
| `ACCENT_WARN` | `orange-400` | `#fe8019` | `#cb4b16` |
| `ACCENT_CYAN` | `emerald-400` | `#8ec07c` | `#2aa198` |

Note: `ACCENT_PRIMARY` is the hero color for focus/active state. In Gruvbox this is warm yellow. In Solarized this is muted gold — NOT blue. The Solarized `.conf` currently maps `ACCENT_PRIMARY` to `#268bd2` (blue). This is a known drift that must be corrected to match this contract, or this contract must be amended with rationale. See §10.

### 3.3 Signal category colors

Signal colors are semantic, not decorative. They must be theme-aware — derived from palette tokens, not hardcoded hex.

| Category | Token | Gruvbox | Solarized | Region affinity |
|----------|-------|---------|-----------|-----------------|
| `context_time` | `blue-400` | `#83a598` | `#268bd2` | horizon |
| `governance` | `fuchsia-400` | `#d3869b` | `#d33682` | bedrock |
| `work_tasks` | `orange-400` | `#fe8019` | `#cb4b16` | horizon |
| `health_infra` | `red-400` | `#fb4934` | `#dc322f` | bedrock |
| `profile_state` | `green-400` | `#b8bb26` | `#859900` | field |
| `ambient_sensor` | `emerald-400` | `#8ec07c` | `#2aa198` | ground |
| `voice_session` | `yellow-400` | `#fabd2f` | `#b58900` | ground |
| `system_state` | `text-secondary` | `#bdae93` | `#657b83` | bedrock |

Implementation requirement: all signal color lookups must resolve through the current palette, never through hardcoded hex strings.

### 3.4 Stimmung stance colors

Stimmung borders and glows use semantic colors at reduced opacity:

| Stance | Color token | Border opacity | Glow | Animation |
|--------|------------|----------------|------|-----------|
| Nominal | (none) | transparent | none | none |
| Cautious | `yellow-400` | 15% | none | none |
| Degraded | `orange-400` | 25% | inset 8px at 6% | 6s breathing cycle |
| Critical | `red-400` | 35% | inset 12px at 8% | 2s breathing cycle + 1.15x scale pulse |

Implementation requirement: stimmung border colors in `Region.tsx` must use CSS custom properties (`var(--color-orange-400)` etc.), not hardcoded `rgba()` values. The `@keyframes` in `index.css` already do this correctly via `color-mix()`.

### 3.5 Depth border colors

Region borders at each depth level:

| Depth | Border | Glow |
|-------|--------|------|
| Surface | transparent | none |
| Stratum | `zinc-500` at 8% opacity | inset 20px at 3% opacity |
| Core | `zinc-500` at 15% opacity | inset 30px at 6% opacity |

Implementation requirement: depth borders in `Region.tsx` must derive from palette tokens, not hardcoded warm-tan `rgba(180, 160, 120, ...)` values.

### 3.6 Voice overlay colors

Voice state and acceptance colors are **mode-aware UI chrome**, not a fixed perceptual vocabulary like detection overlays. They must use palette tokens and switch with mode.

| Voice state | Token | Semantic |
|-------------|-------|----------|
| Listening/transcribing | `green-400` | Active, receiving input |
| Thinking/processing | `yellow-400` | Caution, processing |
| Speaking/responding | `blue-400` | Information, output |
| Default/idle | `zinc-500` | Muted, inactive |

| Acceptance | Token | Semantic |
|------------|-------|----------|
| ACCEPT | `green-400` | Success |
| CLARIFY | `yellow-400` | Warning |
| REJECT | `red-400` | Error |
| IGNORE | `zinc-500` | Muted |

Frustration, context anchor, and biometric monitoring bars follow the standard severity ladder (§3.7).

### 3.7 Severity ladder

Many components display a health/severity state using a three-or-four-step color ladder. This is the canonical mapping used everywhere severity appears (biometric indicators, axiom compliance dots, stimmung stance labels, battery/load bars, flow node status):

| Level | Token | Semantic | Used for |
|-------|-------|----------|----------|
| Healthy/nominal/active | `green-400` | Success | Presence, compliance, battery, flow active |
| Warning/cautious/stale | `yellow-400` | Caution | Elevated stress, degraded stance, stale data |
| Degraded/urgent | `orange-400` | Urgency | Degraded stimmung, high load |
| Critical/error/failed | `red-400` | Alert | Failed checks, critical stance, low battery |
| Unknown/inactive/neutral | `zinc-700` | Structure | Disconnected, null state, unknown |

Components must not invent their own severity colors. Use the ladder tokens above. For inline styles: `var(--color-green-400)` etc. For canvas: `palette["green-400"]` from `useTheme()`.

### 3.8 Detection overlay colors

Detection overlays encode perceptual classification. These colors are functional (operator must instantly read gaze direction, emotion, consent status) and are therefore **mode-invariant by design**. Detection colors do not change with working mode.

Rationale: detection overlay colors encode a fixed perceptual vocabulary (cyan = screen gaze, yellow = hardware gaze, etc.). Changing these per mode would break the operator's trained visual recognition. The overlay renders on top of camera feeds where background palette is irrelevant.

**Object category colors** (bounding boxes and labels):

| Category | Hex | Semantic |
|----------|-----|----------|
| `person` | `#8ec07c` | Sage green — living entity, highest importance |
| `furniture` | `#bdae93` | Tan — static room structure |
| `electronics` | `#83a598` | Teal — active devices, screens |
| `instrument` | `#fabd2f` | Yellow — creative tools, studio gear |
| `container` | `#d3869b` | Mauve — storage, boxes, bags |

**Gaze direction colors** (person halo, primary enrichment):

| Direction | Hex | Semantic |
|-----------|-----|----------|
| `screen` | `#83a598` | Teal — engaged with digital work |
| `hardware` | `#fabd2f` | Yellow — hands-on with physical equipment |
| `person` | `#d3869b` | Mauve — social attention, face-to-face |
| `away` | `#7c8a74` | Muted sage — disengaged, looking elsewhere |

**Emotion tint colors** (secondary enrichment, applied when gaze not available):

| Emotion | Hex | Semantic |
|---------|-----|----------|
| `happy` | `#b8bb26` | Bright green — positive affect |
| `sad` | `#83a598` | Teal — withdrawn affect |
| `angry` | `#fb4934` | Red — high-arousal negative |
| `surprise` | `#fe8019` | Orange — novel stimulus |
| `fear` | `#d3869b` | Mauve — threat response |
| `disgust` | `#bdae93` | Tan — aversion |

**Consent and state colors**:

| State | Hex | Semantic |
|-------|-----|----------|
| Consent suppressed | `#665c54` | Zinc-600 — fully desaturated, person enrichments withheld |
| Exiting frame | `#504945` | Zinc-700 — fading toward background |

**Label and pill backgrounds**: Detection label pills use the detection color at 80% opacity (`+ "cc"`) as background, with `bg` token (`#1d2021` Gruvbox / `#002b36` Solarized) as text. Annotation pills use `bg` token at 87% opacity. These background values are mode-invariant because they serve as contrast surfaces against camera feeds, not as themed UI chrome.

**Consent gating behavior**:
- Persons without an active consent contract render with the suppressed color (`#665c54`). All person enrichments (gaze, emotion, posture, gesture, action, depth) are withheld.
- The operator's own person is identified via the `operator` camera role and is never suppressed (the operator is the system owner; no self-consent contract required).
- Confidence percentages are withheld for consent-suppressed persons (label shows category only).
- When consent phase is `consent_refused`, non-operator person detections are removed entirely from the overlay.

**IR-optimized presets**: The presets `NightVision`, `Silhouette`, and `Thermal IR` activate a high-saturation variant palette for visibility against monochrome camera feeds. This is preset-driven, not mode-driven.

| Category | IR Hex | Gaze | IR Hex |
|----------|--------|------|--------|
| `person` | `#00ffaa` | `screen` | `#44eeff` |
| `furniture` | `#ffcc66` | `hardware` | `#ffee44` |
| `electronics` | `#66ddff` | `person` | `#ff88dd` |
| `instrument` | `#ffee44` | `away` | `#99aa88` |
| `container` | `#ff99cc` | | |

**Breathing animation for detections**: Detection overlays use novelty (0.0–1.0) to drive breathing period, analogous to but independent from the severity-driven signal breathing (§6). The novelty scale maps familiarity: static familiar objects do not breathe; novel or entering entities breathe faster.

| Novelty | Period | Behavior |
|---------|--------|----------|
| < 0.1 | none | Static — no animation |
| 0.1–0.3 | 8s | Slow awareness |
| 0.3–0.6 | 4s | Moderate attention |
| 0.6–0.8 | 1.5s | High novelty |
| ≥ 0.8 | 0.6s | Brand new entity |

**Halo opacity by entity type**: Person detections render at full opacity. Non-person detections scale by novelty and mobility: novel (> 0.5) at 60%, dynamic at 50%, static familiar at 25%.

**Classification Inspector** (`C` key): A separate diagnostic overlay exempt from §4 density rules and §5 signal caps. Uses theme-aware colors from `useTheme().palette` (not the mode-invariant detection palette above). This is an operator diagnostic tool for inspecting all per-camera classifications at full density. See `docs/plans/2026-03-23-classification-inspector-design.md`.

---

## 4. Spatial Model

Logos organizes by domain of awareness, not by feature. The terrain metaphor structures five domains as geological strata.

### 4.1 Five regions

| Region | Position | Domain | Keyboard |
|--------|----------|--------|----------|
| Horizon | Top, full width | Time — briefing, nudges, goals, engine | `H` |
| Field | Middle-left | Cognition — agents, sensors, operator state | `F` |
| Ground | Middle-center | Presence — cameras, ambient, physical space | `G` |
| Watershed | Middle-right | Flow — data movement, events, profile | `W` |
| Bedrock | Bottom, full width | Foundations — health, cost, governance, consent | `B` |

### 4.2 Three depth states

Each region has three depth states. Depth controls information density, not navigation.

| Depth | Character | Signal density |
|-------|-----------|----------------|
| Surface | Minimal — 1-line summaries, compact pips | max 3 pips |
| Stratum | Structured — panels, grids, charts | max 5 pips + sparklines |
| Core | Immersive — hero content, full detail | all signals by category |

Depth cycling: press the region's key repeatedly to cycle surface → stratum → core → surface.

When a middle-row region reaches core depth, it spans the full middle row width. Horizon and bedrock collapse to minimal height (~3-4vh) to maximize space for the expanded region.

### 4.3 Navigation model

Terrain is the primary and default interface. The routing model is:

- `/` and `/terrain` — Terrain (always rendered)
- `/hapax` — Full-screen generative visual (escape hatch)
- All legacy page routes (`/chat`, `/insight`, `/demos`, `/flow`, `/studio`, `/visual`) redirect to terrain with appropriate query parameters

Investigation overlay (`/` key) provides Chat, Insight, and Demos as tabs within a modal. These are not separate pages.

Query parameters sync terrain state for deep-linking: `?region=X&depth=Y&overlay=investigation&tab=Z&demo=name`.

---

## 5. Signal System

Signals surface state changes across all domains. Each signal has: category (one of 8), title, detail text, severity (0.0–1.0), source identifier.

### 5.1 Signal categories

The 8 categories, their semantic meaning, and their region affinity are defined in §3.3. Categories are exhaustive — every signal must belong to exactly one.

| Category | Generates from |
|----------|---------------|
| `context_time` | Temporal context, circadian state, calendar events |
| `governance` | Axiom violations, consent phase transitions, SDLC events |
| `work_tasks` | Nudges, deadlines, open loops, stale follow-ups |
| `health_infra` | Health checks, container status, service failures |
| `profile_state` | Profile dimension changes, fact synthesis, knowledge gaps |
| `ambient_sensor` | Presence detection, environmental readings, room state |
| `voice_session` | Voice daemon state, routing tier, conversation events |
| `system_state` | Stimmung transitions, mode changes, engine rule activations |

### 5.2 Signal severity and animation

Severity drives visual urgency through breathing animation:

| Severity range | Animation | Tempo | Scale |
|----------------|-----------|-------|-------|
| < 0.2 | none | — | 1.0x |
| 0.2 – 0.4 | `signal-breathe-slow` | 8s | 1.0x |
| 0.4 – 0.7 | `signal-breathe-mod` | 4s | 1.0x |
| 0.7 – 0.85 | `signal-breathe-fast` | 1.5s | 1.0x |
| > 0.85 | `signal-breathe-crit` | 0.6s | 1.15x pulse |

Signal pip sizes: 6px (severity < 0.4), 8px (0.4–0.85), 10px (≥ 0.85).

### 5.3 Signal routing

Signals route from backend collectors to frontend pips:

1. **Backend**: Collectors produce typed events (health check failed, presence changed, etc.)
2. **Classification**: Events are tagged with one of 8 categories and a severity score
3. **Region mapping**: Each category has a primary region affinity (§3.3)
4. **Rendering**: `SignalCluster` components at region corners render pips using the current palette's color for that category's token

**Density constraints**: At Surface depth, max 3 signals per zone, max 5 total visible (ranked by severity). At Stratum depth, max 5 per zone with sparklines. At Core depth, all signals rendered grouped by category. These limits are enforced by `SignalCluster` (for terrain pips) and `ZoneOverlay` (for perception canvas zones).

The backend classification is performed by the visual layer aggregator's `map_*` functions, which tag events with categories and severity scores. The frontend renders them through `SignalCluster` (terrain pips) and `ZoneOverlay` (perception canvas zones).

---

## 6. Animation Vocabulary

All animations in Logos fall into one of four families:

### 6.1 Breathing

Sinusoidal opacity oscillation. Used for: signal pips, stimmung borders, node liveness.

- Easing: `ease-in-out`
- Tempo: driven by severity or cadence (never by mode)
- Range: varies by context (signals: 0.3–1.0; stimmung: 8%–35% border opacity)

### 6.2 Transitions

State changes between depths, overlays, and focus. Short, decisive, not decorative.

- Duration: 200–300ms
- Easing: `ease-out` (quick departure, gentle arrival) for overlays and modals; CSS `snap` bezier (`0.25, 1.0, 0.5, 1.0`) for window management
- No bounce, no elastic, no spring physics

### 6.3 Depth flash

Brief border highlight when a region changes depth. Confirms the operator's action.

- Color: `green-400` at 20% opacity → transparent
- Duration: 300ms
- Single-shot, not looping

### 6.4 Decay

Time-based fade for stale or aging elements. Used for: event ripples, signal freshness.

- Pattern: opacity decays linearly from 1.0 to min-opacity over TTL
- Min-opacity: 0.3 (never fully invisible while present)

### 6.5 Ambient

Slow, continuous, organic motion for the resting state. Used for: ground surface shapes, cycling text.

- Cycle time: 12s for text fragments
- Motion: drift, not oscillate — elements move in one direction, then are replaced
- Opacity: low (20–40% for text, 8–15% for shapes)

---

## 7. Exceptions and Special Cases

### 7.1 Investigation overlay backdrop

The investigation overlay uses `backdrop-filter: blur(16px)` and a subtle box-shadow. This is the single exception to the "no blur, no shadows" principle.

Rationale: the overlay sits at z-40 over the terrain. Without backdrop treatment, text-on-text creates an unreadable mess. The blur is functional — it creates a readable surface for the Chat/Insight/Demos content while preserving awareness of the terrain underneath. This is not decorative depth simulation; it is a legibility mechanism.

The backdrop background color must use the `surface` palette token at 88% opacity, not a hardcoded value.

### 7.2 Classification inspector overlay

The classification inspector overlay (`C` key) uses the same `backdrop-filter: blur(16px)` and box-shadow treatment as the investigation overlay (§7.1). Same rationale: legibility over camera feed content. The inspector is exempt from §4 density rules and §5 signal caps — it is a diagnostic tool that intentionally shows all per-camera classifications at full density. Colors in the inspector are **theme-aware** (derived from `useTheme().palette`), unlike the terrain detection overlay (§3.8) which is mode-invariant.

### 7.3 Hyprland border colors

The live Hyprland config currently uses BBS-era cyan (`#00c8c8`) for active borders. The `hapax-theme-apply` script overrides this at mode switch time to the current palette's `ACCENT_PRIMARY`. The static config should be updated to match the R&D default (`#fabd2f`) so that the system looks correct before the first mode switch after boot.

### 7.3 Desktop background

Both the desktop aesthetic spec (`#0a0a0a` void) and Gruvbox (`#1d2021`) claim the background. In practice, `#0a0a0a` is the Hyprland compositor background (visible only in gaps between windows), while `#1d2021`/`#002b36` is the application surface color. Both are correct for their surface. The compositor background remains `#0a0a0a` in both modes — it is the void beneath the terrain.

---

## 8. Synchronization Requirements

### 8.1 Single source of truth

The canonical color definitions live in two places that must remain synchronized:

1. **Desktop**: `~/.config/hapax/themes/{gruvbox-dark,solarized-dark}.conf` — consumed by `hapax-theme-apply`
2. **Logos app**: `hapax-logos/src/theme/palettes.ts` — consumed by `ThemeProvider`

There is currently no automated synchronization. A validation step should be added (CI or pre-commit) that compares the `.conf` token values against `palettes.ts` and fails on drift.

### 8.2 No hardcoded colors in components

Components must not contain hex color literals for any color that participates in theming.

**Two access patterns** (both are theme-aware):

1. **DOM inline styles** — use CSS custom properties with hue-shade naming:
   - `var(--color-green-400)` for solid colors
   - `color-mix(in srgb, var(--color-green-400) N%, transparent)` for opacity variants
   - Note: semantic names like `var(--color-border)` do NOT exist. Use hue-shade: `var(--color-zinc-700)`

2. **Canvas/JS rendering** — use `useTheme()` hook for hex values:
   - `palette["green-400"]` returns the current hex string (e.g. `"#b8bb26"` or `"#859900"`)
   - `colors.success` returns the same hex via semantic alias
   - These update via React re-render on mode switch

3. **Tailwind classes** — `text-green-400`, `bg-zinc-900` (resolve through CSS custom properties at runtime)

**Token-to-property reference:**

| Design doc name | CSS property | Tailwind | `palette` key |
|-----------------|-------------|----------|---------------|
| `bg` | `var(--color-zinc-950)` | `bg-zinc-950` | `"zinc-950"` |
| `surface` | `var(--color-zinc-900)` | `bg-zinc-900` | `"zinc-900"` |
| `elevated` | `var(--color-zinc-800)` | `bg-zinc-800` | `"zinc-800"` |
| `border` | `var(--color-zinc-700)` | `border-zinc-700` | `"zinc-700"` |
| `border-muted` | `var(--color-zinc-600)` | `border-zinc-600` | `"zinc-600"` |
| `text-muted` | `var(--color-zinc-500)` | `text-zinc-500` | `"zinc-500"` |
| `text-secondary` | `var(--color-zinc-400)` | `text-zinc-400` | `"zinc-400"` |
| `text-primary` | `var(--color-zinc-200)` | `text-zinc-200` | `"zinc-200"` |
| `text-emphasis` | `var(--color-zinc-100)` | `text-zinc-100` | `"zinc-100"` |

Hardcoded hex is permitted only for:
- Detection overlay perceptual colors (§3.8) — fixed by design
- IR-optimized preset colors — preset-specific by design
- The compositor void background `#0a0a0a` — mode-invariant by design

---

## 9. Document Hierarchy

| Document | Status | Governs |
|----------|--------|---------|
| **This document** (`logos-design-language.md`) | **Normative** | Color contract, spatial model, animation vocabulary, mode system, synchronization |
| `logos-ui-reference.md` | **Normative** | Region content (what appears at each depth), signal behavior, keyboard shortcuts, demo mode |
| `superpowers/specs/2026-03-10-hyprland-aesthetic-design.md` | **Historical** | Design principles (§1 of this doc) retained. Color tables, config blocks superseded. |
| `research/visual-design-parameters-research.md` | **Aspirational** | GPU visual surface parameters (R-D, physarum, wave, sediment). Not yet normative. Becomes normative when implemented and validated. |

When documents conflict, this document wins on color, mode, spatial model, and animation. The UI reference wins on content (what data appears where). The research doc is advisory only.

---

## 10. Open Design Questions

These are identified gaps that need operator decisions before they can become normative.

### 10.1 Solarized ACCENT_PRIMARY

The current Solarized `.conf` maps `ACCENT_PRIMARY` to `#268bd2` (blue). This document's contract (§3.2) specifies `yellow-400` (`#b58900`). The question: should the Solarized hero color be gold (consistent cross-mode semantic) or blue (Solarized's natural hero)?

- **Argument for gold**: The operator learns one color = focus. Mode switch changes warmth, not meaning.
- **Argument for blue**: Solarized's identity IS blue. Forcing gold onto Solarized feels like wearing someone else's clothes.

Current recommendation: gold. Cross-mode semantic consistency is more valuable than palette purity. The operator switches modes frequently enough that relearning "focus = blue" would create friction.

### 10.2 Ambient shader color warmth

`AmbientShader.tsx` hardcodes warm-only GLSL colors ("never blue/white"). Should the shader respond to mode?

- **Argument for mode-aware**: Research mode should feel cool. Warm amber blobs on a cool blue background would clash.
- **Argument for mode-invariant**: The shader represents the system's resting presence. Presence is warm regardless of analytical mode. The warmth is phenomenological, not decorative.

Current recommendation: mode-aware, but subtly. Shift the shader's base palette from warm-amber (R&D) to cool-teal (Research) while preserving the organic motion language. The shapes are the same; the temperature changes.

### 10.3 Cycling text content per mode

`AmbientCanvas` cycles 15 hardcoded philosophical fragments. Should Research mode show different text?

- **Argument for different**: Research fragments could be citations, methodology reminders, or analytical prompts.
- **Argument for same**: The fragments express system values, not task-specific content. They shouldn't change with mode.

Current recommendation: same fragments for both modes. The content expresses identity, not activity. The ContentScheduler (when fully wired) should drive ambient text from profile facts and system state, making this question moot.

### 10.4 Signal backend formalization — RESOLVED

The visual layer aggregator's `map_*` functions serve as the backend classification system. Each function tags events with one of 8 categories and a severity score. Signals flow: API poll → `map_*` → `VisualLayerState.signals` → frontend `SignalCluster`/`ZoneOverlay` rendering. No separate `SignalCollector` service needed — the aggregator IS the collector.

---

## 11. Scope

This section lists every visual surface the operator sees and whether it falls under this design language.

### 11.1 Governed surfaces

These surfaces must comply with §1–§8. All colors must derive from §3, all typography from §1.6, all spacing from §1.3.

| Surface | Config location | Mode switching | Current compliance |
|---------|----------------|----------------|--------------------|
| **Logos React app** | `hapax-logos/src/` | ThemeProvider + CSS custom properties | High — active development target |
| **hapax-bar** | `hapax_bar/styles/hapax-bar-{rnd,research}.css` | Instant CSS swap via control socket or API poll | Full — GTK4 CSS custom properties, design-language compliant |
| **Mako notifications** | `~/.config/mako/config-{rnd,research}` | Config swap via `hapax-theme-apply` | High — minor border token issue |
| **Fuzzel launcher** | `~/.config/fuzzel/fuzzel-{rnd,research}.ini` | Config swap via `hapax-theme-apply` | High — inherits §10.1 question |
| **Hyprland compositor** | `~/.config/hypr/hyprland.conf` | `hyprctl keyword` via `hapax-theme-apply` | Medium — static defaults stale, group colors unwired |
| **Hyprlock lock screen** | `~/.config/hypr/hyprlock-{rnd,research}.conf` | Config swap via `hapax-theme-apply` | Low — wrong font, R&D config has BBS colors |
| **Foot terminal** | `~/.config/foot/foot.ini` | USR1/USR2 signal switching `[colors-dark]`/`[colors-light]` | Low — `[colors-dark]` is full BBS palette, not Gruvbox |
| **Officium React app** | `hapax-officium/officium-web/src/` | **Not implemented** | Low — no ThemeProvider, hardcoded Gruvbox only |
| **Studio compositor overlays** | `agents/studio_compositor.py` | **Not implemented** | Low — arbitrary RGB tuples, generic font |

### 11.2 Governed surfaces — requirements

**Foot terminal**: `[colors-dark]` (activated by USR1 for R&D mode) must use Gruvbox palette values from §3.1. `[colors-light]` (activated by USR2 for Research mode) already uses correct Solarized values. Section names are fixed by foot's convention.

**Hyprlock**: Must use JetBrains Mono per §1.6. R&D config must use Gruvbox tokens from §3.1 for outline, font color, and clock label. Research config is already correct.

**Officium React app**: Must implement ThemeProvider with CSS custom property injection, reading working mode from `~/.cache/hapax/working-mode`. Must have dual palettes (Gruvbox/Solarized) matching council's `palettes.ts`. This is a separate engineering effort in the hapax-officium repository.

**Studio compositor overlays**: Cairo rendering must use JetBrains Mono (`ctx.select_font_face("JetBrains Mono", ...)`). Signal zone colors must align with §3.3 category colors. The 30% desaturation for ADHD/autism safety is approved as a documented accessibility variant — apply desaturation to the §3.3 colors rather than using arbitrary values. Consent badge and recording indicator colors must use §3.1 semantic tokens (green-400 for allowed, red-400 for refused, yellow-400 for pending, orange-400 for blocked).

### 11.3 Excluded surfaces

These surfaces are explicitly NOT governed by this design language.

| Surface | Rationale |
|---------|-----------|
| **VS Code extension** | Lives inside VS Code's UI and must respect the host editor's theme. Uses VS Code design tokens (`--vscode-*`) exclusively. The extension is a content delivery surface, not a state representation surface. |
| **hapax-watch (Wear OS)** | Platform conventions (Material Design 3) govern wearable UI. Forcing desktop aesthetic onto a watch would violate platform expectations and harm usability. |
| **OpenWebUI, Grafana, Langfuse, n8n** | Third-party Docker UIs with default themes. Not operator-facing as primary surfaces. Theming these provides negligible value relative to maintenance cost. |
| **Tauri/wgpu GPU visual surface** | Governed by the aspirational `research/visual-design-parameters-research.md`. Will become normative when implemented. See §9. |

### 11.4 Adjacent but separate: visual layer ambient parameters

The visual layer aggregator produces ambient parameters (`color_warmth`, `speed`, `turbulence`, `brightness`, `hue_shift`) that drive the GPU visual surface and compositor background. These parameters are a *rendering control system*, not a color palette. They are:

- Derived from stimmung stance, biometrics, activity, and circadian rhythm
- Continuously variable (not discrete tokens)
- Intentionally decoupled from working mode (stimmung drives visual temperature, not mode)

These parameters should be formalized in their own specification (parameter ranges, derivation rules, biometric thresholds) but are not part of this document's color/typography/spacing contract.
