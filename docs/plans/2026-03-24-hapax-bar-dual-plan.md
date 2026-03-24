# Hapax Bar — Dual Surface Implementation Plan

**Date:** 2026-03-24
**Design:** [hapax-bar-dual-design.md](2026-03-24-hapax-bar-dual-design.md)

---

## Phasing

Two phases. Phase 1 splits into two bars. Phase 2 refines visual design per the research findings.

---

## Phase 1: Split into Horizon + Bedrock

**Goal:** Two bars rendering on each monitor. Correct module assignment. Two seam windows.

### Tasks

1. **`hapax_bar/horizon.py`** (~50 lines)
   - New file. Creates the top bar `Astal.Window`.
   - Anchor: `TOP | LEFT | RIGHT`, exclusivity: `EXCLUSIVE`, height: 24px
   - Modules: workspaces, submap, window title, MPRIS, working mode badge, temporal ribbon
   - Layout: `Gtk.CenterBox` — left (workspaces + submap), center (window title + MPRIS), right (mode badge + temporal ribbon)
   - Namespace: `hapax-horizon` / `hapax-horizon-secondary`

2. **`hapax_bar/bedrock.py`** (~60 lines)
   - Rename/refactor from current `bar.py`.
   - Anchor: `BOTTOM | LEFT | RIGHT`, exclusivity: `EXCLUSIVE`, height: 32px
   - Modules: stimmung field (center, `hexpand`), volume, mic, cost whisper, system tray
   - Layout: `Gtk.CenterBox` — left (empty or minimal), center (stimmung field with consent beacon + voice orb), right (volume + mic + cost whisper + tray)
   - Namespace: `hapax-bedrock` / `hapax-bedrock-secondary`

3. **`hapax_bar/seam/seam_window.py`** update (~20 lines changed)
   - Parameterize with `position: str = "top" | "bottom"`
   - Anchor and revealer direction follow position
   - Remove fullscreen overlay pattern — use partial anchor (anchor own edge + LEFT + RIGHT only)

4. **`hapax_bar/seam/horizon_seam.py`** (~40 lines)
   - New file. Contains: temporal panel, nudge summary (placeholder), goals summary (placeholder)
   - Populated from existing seam panels where applicable

5. **`hapax_bar/seam/bedrock_seam.py`** (~30 lines)
   - New file. Wires existing panels: metrics, stimmung detail, voice, controls, session
   - These already exist — just compose them into the bedrock seam

6. **`hapax_bar/app.py`** update (~40 lines changed)
   - Import `horizon.create_horizon()` and `bedrock.create_bedrock()`
   - Create per monitor: 1 horizon bar + 1 bedrock bar + 2 seam windows
   - Wire stimmung reader → bedrock's stimmung field
   - Wire API polling → bedrock seam's metrics
   - Socket server unchanged (routes internally)

7. **CSS updates** — add horizon and bedrock distinct styles
   - Horizon: `window.horizon > centerbox { background-color: var(--bg-primary); opacity: 0.85; }`
   - Bedrock: `window.bedrock > centerbox { background-color: var(--bg-secondary); border-top: 1px solid var(--border); }`
   - Horizon text: 11px, `--text-dim` for ambient labels
   - Bedrock text: 12px, `--text-secondary` for interactive labels

8. **Delete `bar.py`** (replaced by horizon.py + bedrock.py)

9. **Test**: Both bars render on both monitors. Click stimmung field → bedrock seam slides up. Click temporal ribbon or mode badge → horizon seam slides down. All modules functional.

### Acceptance
- Two bars visible on each monitor (top 24px + bottom 32px)
- Workspace content shrinks by 56px total
- Horizon: workspaces, title, mpris, mode badge, temporal ribbon
- Bedrock: stimmung field, consent beacon, voice orb, volume, mic, cost, tray
- Two seam windows: horizon seam drops down, bedrock seam rises up
- Both dismiss on Escape or click-outside

---

## Phase 2: Visual Refinement

**Goal:** Apply the ISA-101 / Previc / calm technology visual design principles.

### Tasks

1. **Horizon visual treatment**
   - Semi-transparent background (CSS `opacity: 0.85` on centerbox)
   - Text at `--text-dim` in normal state
   - Color only on deviation: workspace accent, temporal countdown (blue), mode badge (mode color)
   - No animation except temporal ribbon circadian shift

2. **Bedrock visual treatment**
   - Opaque background with 1px top border
   - Stimmung field at 32px height (more gradient resolution)
   - Volume/mic labels at higher contrast
   - Interactive elements: hover state reveals slight background shift

3. **Stimmung field enlarged** — update particle radii, voice orb radius (6px → 10px), consent beacon height (32px instead of 24px) for the taller bedrock bar

4. **Horizon typography** — 11px for ambient text (title, mpris), 12px for workspace numbers and mode badge

5. **Test visual hierarchy**: Horizon should feel like it disappears when you're not looking at it. Bedrock should feel solid and grounded.

### Acceptance
- Horizon is visually quieter than bedrock
- Stimmung field has more visual resolution at 32px
- Color is absent from both bars in nominal system state (ISA-101)
- Mode switch changes both bars' palettes simultaneously

---

## Estimated Scope

| Phase | Files Created | Files Modified | Lines Est. |
|-------|-------------|---------------|-----------|
| 1 | 3 (horizon.py, horizon_seam.py, bedrock_seam.py) | 4 (app.py, seam_window.py, CSS ×2) | ~300 |
| 2 | 0 | 4 (stimmung_field.py, horizon.py, CSS ×2) | ~80 |
| **Total** | **3** | **~6** | **~380 lines** |

Delete: `bar.py` (replaced by horizon.py + bedrock.py)
