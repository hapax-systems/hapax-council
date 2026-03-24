# Hapax Bar — Dual Surface Architecture

**Date:** 2026-03-24
**Status:** Design
**Supersedes:** hapax-bar-v2-design.md (single bar with stimmung field in center)
**Grounded in:** Logos design language §3.3, §4.1; ISA-101; Previc visual field theory; console meter bridge analogy

---

## 1. Architecture: Two Bars

Two physically separated `Astal.Window` layer-shell surfaces per monitor. Workspace content between them.

### Horizon Bar (top)

```
Anchor: TOP | LEFT | RIGHT
Exclusivity: EXCLUSIVE (24px)
Namespace: hapax-horizon
Layer: TOP
```

**Domain**: Time, work context, awareness. Answers: *what am I doing, when is it, what needs attention?*

**Visual character**: Ambient, peripheral, cool. Semi-transparent background (80% opacity). Low normal-state contrast (2-3:1). Color appears only when something deviates from baseline (ISA-101 Level 1). Fixed layout — never rearranges.

**Upper visual field** (Previc): extrapersonal space, optimized for visual search and scene perception. The operator glances up to check state, like checking a meter bridge.

### Bedrock Bar (bottom)

```
Anchor: BOTTOM | LEFT | RIGHT
Exclusivity: EXCLUSIVE (32px)
Namespace: hapax-bedrock
Layer: TOP
```

**Domain**: Foundations, health, governance, consent, controls. Answers: *is the system healthy, is anyone being recorded, what can I adjust?*

**Visual character**: Grounded, interactive, slightly warmer. Opaque background (100%). Higher contrast (4.5:1+). Clear interactive affordances. Supports direct manipulation (scroll, click, toggle).

**Lower visual field** (Previc): peripersonal space, optimized for visuomotor coordination. This is where the hands work. Like the channel strip and transport section of a mixing console.

### Spatial Separation

The operator's focal attention lives in the workspace between the bars. The bars occupy distinct neural pathways — ventral (top/identification) and dorsal (bottom/action). Physical distance creates cognitive separation without requiring the operator to mentally parse which zone of a single bar they're looking at.

---

## 2. Module Assignment

### Horizon (top, 24px)

| Module | Signal Category | Encoding |
|--------|----------------|----------|
| **Workspaces** | work_tasks | Buttons with accent highlight. Click to switch. |
| **Submap** | work_tasks | Text when active, hidden when not. |
| **Window Title** | work_tasks | Dim text, truncated. Current task context. |
| **MPRIS** | work_tasks | Artist — title, dim. Click play/pause. |
| **Working Mode** | work_tasks | [R&D] or [RES] badge. Click to toggle. |
| **Temporal Ribbon** | context_time | Circadian gradient + session duration + event countdown + clock. |

**6 elements.** All awareness/context. Three are text (title, mpris, mode badge), one is interactive buttons (workspaces), one is visual (temporal ribbon), one is conditional (submap). No system metrics, no health indicators, no controls beyond workspace switching and mode toggle.

**Animation**: Temporal ribbon shifts color temperature through the day. No breathing (that's stimmung on bedrock). No particles. The horizon is still and quiet — like a horizon.

### Bedrock (bottom, 32px)

| Module | Signal Category | Encoding |
|--------|----------------|----------|
| **Stimmung Field** | health_infra, system_state | GPU gradient + breathing + particles. Fills center. |
| **Consent Beacon** | governance | 8px full-height band, left edge of stimmung field. |
| **Voice Orb** | voice_session | 12px animated orb in stimmung field. Click to toggle daemon. |
| **Volume** | system_state | Compact label, scroll to adjust, click to mute. |
| **Mic** | system_state | Compact label, scroll to adjust, click to mute. |
| **Cost Whisper** | (governance/resource) | 12px vertical fill bar. Budget remaining. |
| **System Tray** | system_state | App icons with menus. |

**7 elements.** Infrastructure, health, governance, controls. The stimmung field is the dominant visual element — the system's mood rendered as ambient color. Interactive controls (volume, mic, tray) sit alongside it. The consent beacon is governance-mandated.

**Animation**: Breathing (stimmung stance), particle drift (agent activity), voice orb state transitions. The bedrock is alive with the system's vital signs — like a console's meters and blinkers.

---

## 3. Seam Layers

Two `SeamWindow` instances, one per bar. Each anchored to its own edge.

### Horizon Seam (slides down from top bar)

Content: expanded awareness information.

- **Temporal panel**: Session duration, next event name + countdown, daily meeting count
- **Nudge summary**: Active nudges (max 7) with act/dismiss buttons
- **Goals summary**: Active goals with status

### Bedrock Seam (slides up from bottom bar)

Content: expanded infrastructure detail and secondary controls.

- **Metrics panel**: Health fraction, GPU stats, CPU/mem/disk, docker, network, temp
- **Stimmung detail**: 10 dimensions with values, trends, freshness
- **Voice panel**: Voice state, routing tier, last utterance
- **Controls panel**: Voice start/stop/restart, studio toggle
- **Session panel**: Alpha/beta relay status (other session's branch, last activity)
- **Cost detail**: Today's spend, pace extrapolation, model breakdown

### Seam Window Architecture

```python
class SeamWindow(Astal.Window):
    def __init__(self, position: str = "top"):
        is_top = position == "top"
        anchor = (
            Astal.WindowAnchor.TOP if is_top else Astal.WindowAnchor.BOTTOM
        ) | Astal.WindowAnchor.LEFT | Astal.WindowAnchor.RIGHT
        super().__init__(
            namespace=f"hapax-seam-{position}",
            anchor=anchor,
            exclusivity=Astal.Exclusivity.IGNORE,
            keymode=Astal.Keymode.ON_DEMAND,
        )
        self._revealer = Gtk.Revealer(
            transition_type=(
                Gtk.RevealerTransitionType.SLIDE_DOWN if is_top
                else Gtk.RevealerTransitionType.SLIDE_UP
            ),
            valign=Gtk.Align.START if is_top else Gtk.Align.END,
        )
```

---

## 4. Visual Design

### Heights

| Bar | Height | Rationale |
|-----|--------|-----------|
| Horizon | 24px | Ambient awareness, no interactive targets > workspace buttons (already 24px viable) |
| Bedrock | 32px | Interactive controls need ≥28px targets. Stimmung field benefits from 8px more vertical resolution for gradient + particles |

Total exclusive zone: 56px (vs 24px currently). Workspace content area shrinks by 32px on each monitor.

### Backgrounds

| Bar | Background | Rationale |
|-----|-----------|-----------|
| Horizon | `--bg-primary` at 85% opacity | Semi-transparent, bleeds into workspace. Recedes (Gestalt ground). |
| Bedrock | `--bg-secondary` at 100% | Opaque, distinct boundary. Foreground (Gestalt figure). 1px top border `--border`. |

### Color Temperature

| Bar | Normal State | Abnormal State |
|-----|-------------|---------------|
| Horizon | Cool blue-gray (`--text-dim` for text, near-invisible background) | Warm accent when task/time signal fires (orange for work_tasks, blue for context_time) |
| Bedrock | Warm neutral gray (`--bg-secondary`, `--text-secondary` for labels) | Severity ladder (green → yellow → orange → red) via stimmung field |

### Typography

Both bars: JetBrains Mono (§1.6). Size varies:

| Bar | Text Size | Rationale |
|-----|-----------|-----------|
| Horizon | 11px | Ambient readability, peripheral. Slightly smaller = more recessive. |
| Bedrock | 12px | Interactive labels, needs legibility for click targets. |

### Spacing

2px base unit (§1.3). Gaps between modules: 4px (2 units). Internal padding: 2px vertical, 4-6px horizontal.

---

## 5. Stimmung Field in Bedrock

The stimmung field moves from center-of-single-bar to center-of-bedrock-bar. It gains 8px more height (32px vs 24px), giving better gradient resolution and larger particles.

**Rendering** (unchanged from v2):
- `do_snapshot()` with `append_linear_gradient()` for base gradient
- `push_opacity()` for breathing
- `append_cairo()` for particles, voice orb, consent beacon
- `add_tick_callback()` for vsync animation

**New**: The stimmung field in bedrock has more vertical space for the voice orb (14px radius instead of 6px) and consent beacon (full 32px height, more visible from across the room).

---

## 6. Horizon Bar Behavior

The horizon bar is **almost purely text** with one visual element (temporal ribbon). It should feel like a quiet informational strip — high readability, low visual noise.

**Normal state**: Dark background, dim text. The operator barely notices it. Only the workspace numbers and clock are readily visible.

**Activated state**: When a nudge fires, the working mode badge pulses, or a meeting approaches (temporal ribbon countdown), the relevant element gains color. The rest stays dim. ISA-101: color = deviation from normal.

**No animation** on the horizon bar except:
- Temporal ribbon color shift (gradual, circadian)
- Event countdown element (contracting)
- Nudge badge (brief flash when new nudge arrives, then settles to subtle indicator)

---

## 7. Multi-Monitor

Each monitor gets both bars (horizon top, bedrock bottom). Module assignment differs:

| Monitor | Horizon Modules | Bedrock Modules |
|---------|----------------|-----------------|
| HDMI-A-1 (primary) | Workspaces 1-5, submap, title, mpris, mode, temporal | Stimmung (full), consent, voice, vol, mic, cost, tray |
| DP-1 (secondary) | Workspaces 11-15, submap, title, temporal | Stimmung (full), consent, voice, vol |

Secondary monitor omits: MPRIS, mic, cost whisper, tray, working mode badge. These are primary-monitor-only.

---

## 8. Socket Protocol

Extended to address both bars:

```json
{"cmd": "theme", "mode": "research"}
{"cmd": "stimmung", "stance": "cautious", "dimensions": {...}}
{"cmd": "voice_state", "state": "listening"}
{"cmd": "nudge", "action": "flash", "count": 3}
{"cmd": "temporal", "next_event_minutes": 13, "event_name": "standup"}
{"cmd": "cost", "budget_remaining_pct": 72}
```

No bar-specific addressing needed — the app process routes to the correct bar/module internally.

---

## 9. File Layout Changes

```
hapax_bar/
├── app.py                     # Creates 4 windows per monitor (2 bars + 2 seams)
├── horizon.py                 # NEW: Horizon bar window factory
├── bedrock.py                 # NEW: Bedrock bar window factory (replaces bar.py)
├── seam/
│   ├── seam_window.py         # UPDATED: parameterized position="top"|"bottom"
│   ├── horizon_seam.py        # NEW: temporal + nudge + goals panels
│   ├── bedrock_seam.py        # NEW: metrics + stimmung + voice + controls + session
│   └── ...existing panels...
├── modules/
│   └── ...unchanged...
└── styles/
    ├── hapax-bar-rnd.css      # UPDATED: horizon + bedrock styles
    └── hapax-bar-research.css # UPDATED
```

---

## 10. Migration from Single Bar

The single-bar `bar.py` becomes `bedrock.py`. A new `horizon.py` is created. `app.py` changes from creating 1 bar per monitor to creating 2 (horizon + bedrock) + 2 seam windows per monitor.

The stimmung field, voice orb, consent beacon, agent heartbeat, and biometric modulation all stay in bedrock. The temporal ribbon, cost whisper, and working mode badge move to their correct bar.
