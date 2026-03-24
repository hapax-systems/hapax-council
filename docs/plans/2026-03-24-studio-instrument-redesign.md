# Studio Instrument Redesign

**Date**: 2026-03-24
**Status**: Implemented (PR #300, #301 merged 2026-03-24)
**Scope**: Unify composite/effect/HLS controls into one coherent studio instrument in the ground region detail pane

## Problem

Three fragmented surfaces (StudioDetailPane, StudioSidebar, StudioStream) partially duplicate studio controls with incompatible state management. Key creative parameters (filters, effect toggles, blend modes) are missing from the terrain-integrated surface. No keyboard shortcuts. No state persistence. Selector UX (dropdowns, scrolling lists) is wrong for a live performance tool where spatial memory and instant access matter.

## Principles (from Logos Design Language)

- **Functionalism**: Every element encodes state or affords interaction. No duplication.
- **Density**: Information small and close. Position fixed, state encoded through color.
- **Spatial memory**: Operator learns where controls live. They don't move.
- **Color is meaning**: Preset character communicated through color, not just text.
- **Depth model**: Surface = status glance. Stratum = structured overview. Core = full instrument.

## Design

### 1. One Surface: StudioDetailPane

Retire StudioSidebar and StudioStream as control surfaces. All studio controls live in StudioDetailPane (ground region detail pane, activated via `G` then `S`). The standalone `/studio` URL redirects to `/?region=ground&depth=core&split=studio`.

### 2. Section Hierarchy (top to bottom)

```
┌─────────────────────────────────┐
│ CAMERA                          │  Hero selector + status dots
├─────────────────────────────────┤
│ MODE          [Live] [FX] [HLS] │  Horizontal tab bar (3 modes)
├─────────────────────────────────┤
│ PRESET        (chip grid)       │  6×3 chip grid when FX mode
│               visible presets    │  Each chip: colored dot + name
│               at a glance       │  Active chip highlighted
├─────────────────────────────────┤
│ SOURCE        (chip grid)       │  Collapsible, shows GPU source
│               Camera ● Clean    │  when different from preset
│               ● Ghost ● VHS... │
├─────────────────────────────────┤
│ FILTERS       Live [dropdown]   │  Two filter selectors
│               Smooth [dropdown] │  Only when FX mode active
├─────────────────────────────────┤
│ EFFECTS       ○Scan ○Bands     │  Toggle row (inspector pattern)
│               ○Vig  ○Syrup     │  Colored dots, opacity toggle
│               [Reset]           │  Reset link when dirty
├─────────────────────────────────┤
│ RECORDING     ● 2:14  [Stop]   │  Compact: dot + timer + button
│               6/6 REC Consent OK│  One-line status summary
├─────────────────────────────────┤
│ VISUAL LAYER  (existing panel)  │  Unchanged
├─────────────────────────────────┤
│ AUDIO         ● Active ▮▮▮▮▮   │  Status + VU meter (compact)
└─────────────────────────────────┘
```

### 3. Mode Tab Bar

Replaces separate composite toggle + HLS toggle with a single horizontal tab bar:

| Tab | Mapping | Visual |
|-----|---------|--------|
| **Live** | `compositeMode=false, smoothMode=false` | Raw camera snapshot |
| **FX** | `compositeMode=true` | Composite canvas with presets |
| **HLS** | `smoothMode=true` | HLS smooth stream |

FX + HLS can be combined (both active). When FX tab is active and HLS is toggled within it, the HLS layer renders behind at 30% opacity (existing behavior). The tab bar uses the horizontal tab pattern from InvestigationTabs.

### 4. Preset Chip Grid

Replace the vertical scrolling button list with a 6-column chip grid:

```
┌──────┬──────┬──────┬──────┬──────┬──────┐
│Ghost │Trails│Scrwed│D.mosh│ VHS  │ Neon │
├──────┼──────┼──────┼──────┼──────┼──────┤
│ Trap │ Diff │NtVis │Silho │ThrmIR│PxSort│
├──────┼──────┼──────┼──────┼──────┼──────┤
│SlitSc│Fdbck │Hlftn │GltchB│ASCII │Clean │
└──────┴──────┴──────┴──────┴──────┴──────┘
```

Each chip:
- 2px colored left border indicating blend mode family:
  - `emerald-400`: source-over (Ghost, NightVision, Silhouette, Thermal IR, Slit-scan, Halftone, ASCII, Clean)
  - `yellow-400`: lighter/additive (Trails, Neon, Screwed, VHS, Pixsort, Feedback)
  - `orange-400`: difference (Datamosh, Diff, Glitch Blocks)
  - `fuchsia-400`: multiply (Trap)
- Active chip: `bg-zinc-800 text-zinc-200` with bright left border
- Inactive: `text-zinc-500 hover:bg-zinc-800/30`
- Click selects. Only visible when FX mode active.

### 5. Source Selector

Collapsible section below presets. Only needed when the operator wants a GPU-rendered effect source different from the composite preset. Most of the time, "Camera" is correct.

Use the same chip grid pattern at smaller scale (4-column). Collapsed by default showing only the current selection as a single line. Click to expand.

### 6. Effect Toggle Row

Use the InspectorChannelPanel toggle pattern:
- 4 toggles in a 2×2 grid: Scanlines, Glitch Bands, Vignette, Syrup
- Colored dot (opacity 1.0 active, 0.2 inactive) + label
- "Reset to preset" link appears when any toggle differs from preset defaults
- State stored as `effectOverrides` in context (nullable partial)

### 7. Keyboard Shortcuts

| Key | Action | Context |
|-----|--------|---------|
| `1`-`9`,`0` | Select preset 1-10 | When ground focused + FX mode |
| `Shift+1`-`8` | Select preset 11-18 | When ground focused + FX mode |
| `E` | Cycle mode (Live → FX → HLS) | When ground focused |
| `R` | Toggle recording | When ground focused |
| `[` / `]` | Previous / next preset | When ground focused + FX mode |

Registered in TerrainLayout's keydown handler, gated on `focusedRegion === "ground"`.

### 8. State Persistence

Add to `GroundStudioContext` and persist to localStorage:

```typescript
interface GroundStudioState {
  // existing
  heroRole: string;
  effectSourceId: string;
  smoothMode: boolean;
  compositeMode: boolean;
  presetIdx: number;
  liveFilterIdx: number;
  smoothFilterIdx: number;
  // new
  effectOverrides: Partial<CompositePreset["effects"]> | null;
}
```

localStorage key: `hapax-studio-state`. Read on mount, write on change.
Pattern: same try/catch as `ClassificationOverlayContext`.

### 9. URL Deep Linking

Extend terrain query params:
- `preset=trails` — activate FX mode with named preset
- `source=fx-vhs` — set effect source
- `hls=1` — activate HLS mode

These are secondary to localStorage (URL overrides localStorage on navigation).

## Files Changed

| File | Change |
|------|--------|
| `StudioDetailPane.tsx` | Full redesign: mode tabs, chip grid, effect toggles, compact recording |
| `GroundStudioContext.tsx` | Add effectOverrides, localStorage persistence |
| `TerrainLayout.tsx` | Add studio keyboard shortcuts (E, R, 1-9, [, ]) |
| `TerrainPage.tsx` | Extend TerrainParamSync for preset/source/hls params |

## Files Removed

| File | Reason |
|------|--------|
| `StudioSidebar.tsx` | Superseded by unified StudioDetailPane |
| `StudioStream.tsx` | Blend/tint cycling absorbed into StudioDetailPane; HLS player lives in CameraHero |

## Files Unchanged

| File | Reason |
|------|--------|
| `CompositeCanvas.tsx` | Rendering engine stays as-is (just fixed in prior PR) |
| `CameraHero.tsx` | Rendering paths stay as-is |
| `compositePresets.ts` | Preset data stays as-is |
| `effectSources.ts` | Source data stays as-is |
| `compositeFilters.ts` | Filter data stays as-is |
| `GroundRegion.tsx` | Depth routing stays as-is |

## Non-Goals

- Custom preset editor (save/load user presets) — future work
- Per-camera effect routing — future work
- Audio channel selection — future work
- WebGPU migration — separate effort
- StudioLiveGrid changes — grid view stays as-is at stratum depth
