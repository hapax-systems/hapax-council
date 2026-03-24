# Hapax Bar v2 — Formal Design Document

**Date:** 2026-03-24
**Status:** Design
**Prerequisite:** [hapax-bar-reconception.md](2026-03-24-hapax-bar-reconception.md), [hapax-bar-interaction-model.md](2026-03-24-hapax-bar-interaction-model.md)
**Scope:** Transform hapax-bar from text dashboard to stimmung-driven awareness surface

---

## 1. Architecture

### 1.1 Window Model

Two window types, both `Astal.Window` layer-shell surfaces:

**Bar windows** (one per monitor):
- Layer: `TOP`
- Anchor: `TOP | LEFT | RIGHT`
- Exclusivity: `EXCLUSIVE` (24px exclusive zone)
- Namespace: `hapax-bar` / `hapax-bar-secondary`
- Content: three zones (spatial anchor, stimmung field, interaction points)

**Seam window** (singleton, initially hidden):
- Layer: `TOP`
- Anchor: `TOP | BOTTOM | LEFT | RIGHT` (fullscreen overlay)
- Exclusivity: `IGNORE` (no exclusive zone claim)
- Keymode: `ON_DEMAND`
- Namespace: `hapax-bar-seam`
- Content: `Gtk.Revealer` containing metrics panel + secondary controls
- Dismissal: click on transparent surround area, or Escape key

Rationale: `Gtk.Popover` clips on narrow layer-shell surfaces (Astal#278). Separate overlay window is the established pattern (HyprPanel).

### 1.2 Rendering Pipeline

The stimmung field uses a custom `Gtk.Widget` subclass with `do_snapshot()`:

```
Frame Clock (vsync, display refresh rate)
    │
    ├── add_tick_callback()
    │       └── update animation state (t, breathing phase, particle positions)
    │       └── queue_draw() if state changed
    │
    └── do_snapshot()
            ├── append_linear_gradient()     ← GPU-composited base color field
            ├── push_opacity(breathing)       ← GPU-composited breathing
            ├── append_cairo(rect)            ← particles, orbs (software, 61K pixels)
            └── pop()
```

Performance budget: ~1-2ms per frame on 2560x24. 16.6ms budget at 60fps. 90%+ headroom.

### 1.3 Data Sources

| Source | Path | Read Method | Update Rate |
|--------|------|-------------|-------------|
| Stimmung | `/dev/shm/hapax-stimmung/state.json` | File read + JSON parse | 1-3s poll |
| Visual layer state | `/dev/shm/hapax-compositor/visual-layer-state.json` | File read | 3s poll |
| Perception | `~/.cache/hapax-voice/perception-state.json` | File read | 3s poll |
| Health | `GET :8051/api/health` | HTTP | 30s poll |
| Calendar | `CalendarContext.meetings_in_range(1)` | Python import | 60s poll |
| Cost | `GET :8051/api/cost` | HTTP | 5min poll |
| Working mode | `~/.cache/hapax/working-mode` | File read | On socket push |

All file reads via `GLib.timeout_add()`. No threads — GLib main loop only.

### 1.4 Animation System

Three animation families from the design language:

**Breathing** (§6.1): Sinusoidal opacity oscillation encoding stimmung urgency.
- Nominal: no breathing (static)
- Cautious: 8s period, 0.05 amplitude
- Degraded: 4s period, 0.1 amplitude
- Critical: 0.6s period, 0.15 amplitude + 1.15× scale pulse

**Ambient drift** (§6.5): Particles move slowly through the stimmung field.
- Direction: left-to-right only (drift, not oscillate)
- Speed: proportional to agent activity level
- Density: proportional to perception confidence
- Opacity: 20-40% (per §6.5)

**Decay** (§6.4): Stale data fades.
- Elements older than their TTL fade toward min-opacity (0.3)
- Applied to seam layer metrics when API data is stale

---

## 2. Bar Zones

### 2.1 Left Zone: Spatial Anchor

Unchanged from v1. Interactive workspace buttons + submap indicator.

- Workspace buttons: click to switch, accent color for focused
- Occupied workspaces: normal luminance; empty: dim
- Submap: `[name]` text when active, hidden when not
- MPRIS: condensed media indicator (artist - title), click play/pause, scroll next/prev

### 2.2 Center Zone: Stimmung Field

A custom `StimmungField` widget (`Gtk.Widget` subclass, `do_snapshot()`).

**Visual layers** (bottom to top):
1. **Base gradient**: Linear gradient across bar width. Color stops derived from stimmung dimensions. Nominal = near-invisible dark gradient matching bar background. As dimensions shift, localized color variations appear.
2. **Breathing overlay**: Full-field opacity oscillation driven by stimmung stance.
3. **Particle drift**: Small radial gradient dots drifting left-to-right. Density = perception confidence. Speed = agent activity.
4. **Voice orb**: 12px animated circle. Position: left-third of stimmung field. Color + animation = voice state.
5. **Consent beacon**: Full-height band at left edge of stimmung field. Red when recording, amber when perceiving, absent when off.

**Stimmung-to-color mapping**:

Each stimmung dimension maps to a position in the gradient and a color contribution:

| Dimension | Position | Color when elevated |
|-----------|----------|-------------------|
| health | 0-15% | red-400 |
| resource_pressure | 15-30% | orange-400 |
| error_rate | 30-45% | red-400 |
| processing_throughput | 45-55% | yellow-400 (inverted: high throughput = dim) |
| perception_confidence | 55-65% | emerald-400 (inverted: low confidence = amber) |
| llm_cost_pressure | 65-75% | orange-400 |
| operator_stress | 75-85% | (not colored — modulates overall brightness down) |
| operator_energy | 85-95% | (not colored — modulates overall brightness) |

Dimensions at 0.0 contribute nothing (gray). As a dimension rises toward 1.0, its color contribution increases at its spatial position. The operator learns where in the gradient to look for which concern — spatial memory, per §1.5.

**Interactions**:
- Hover: cursor changes to indicate expandable
- Click: toggles seam layer window
- No scroll behavior

### 2.3 Right Zone: Interaction Points

Minimal text + controls:

| Widget | Type | Content |
|--------|------|---------|
| Working mode badge | `Gtk.Button` | `[R&D]` or `[RES]`, click to toggle |
| Volume pip | `Gtk.DrawingArea` | Small bar encoding volume level + mute color. Scroll ±2%, click mute |
| Temporal ribbon | `Gtk.DrawingArea` | Color gradient shifting through day; countdown element if event approaching |
| Cost whisper | `Gtk.DrawingArea` | Budget-remaining fill level (green→amber→red) |
| Clock | `Gtk.Label` | `HH:MM`, click toggles format |
| Tray | `AstalTray` widget | System tray icons |

---

## 3. Seam Layer

### 3.1 Structure

A `Gtk.Box` (vertical) inside a `Gtk.Revealer` inside the seam window. Positioned below the bar via `margin_top = 24`. Width = 600px, centered or aligned to click position.

### 3.2 Content Panels

**Metrics panel** (top):
```
Health: 105/105 healthy               GPU: 52°C  8.5G/24G  12%
CPU: 23%  Mem: 62%  Disk: 45%         Docker: 13  Failed: 0
Net: 192.168.1.100 (eth0)             Temp: 52°C
```

**Stimmung detail** (middle):
```
Stance: cautious
  health: 0.05 ▬  resource: 0.00 ▬  errors: 0.00 ▬
  throughput: 0.15 ▼  perception: 0.25 ▬  cost: 0.11 ▬
  grounding: 0.40 ▬ (stale 44min)
  stress: 0.00 ▬  energy: 0.70 ▬  coherence: 0.50 ▬
```

**Voice panel** (if voice active):
```
Voice: listening  Routing: CAPABLE  Activation: 0.45
Last: "what about the failing checks"
```

**Temporal panel**:
```
Session: 2h 47m  Next: Standup in 13m
```

**Secondary controls**:
- Voice daemon: [Start] [Stop] [Restart] buttons
- Studio: [Toggle Visual Layer] button
- Nudges: list with [Act] [Dismiss] per nudge (max 7)

**Session panel** (relay protocol):
```
Beta: feat/design-language on hapax-council--beta
  Last: 3h ago  PR #282: merged
```

### 3.3 Styling

Seam layer uses the same CSS custom properties as the bar. Background: `--bg-secondary` with 95% opacity. Text: `--text-primary`. Values use severity ladder colors. JetBrains Mono. No decoration.

---

## 4. Novel Elements

### 4.1 Voice Orb

12px animated circle in the stimmung field.

**State machine**:
```
off → (systemctl start) → idle
idle → (VAD detect) → listening
listening → (utterance end) → processing
processing → (LLM complete) → speaking
speaking → (TTS complete) → idle
any → (GPU contention) → degraded
any → (systemctl stop) → off
```

**Visual encoding**:

| State | Color | Animation | Speed |
|-------|-------|-----------|-------|
| off | absent | — | — |
| idle | dim `--text-dim` | slow drift (0.3px/s) | 12s cycle |
| listening | bright `--yellow-400` | gentle pulse (scale 1.0→1.05) | 2s |
| processing | `--blue-400` | spinning ring | 0.5s |
| speaking | `--green-400` | expanding rings | 1s |
| degraded | desaturated `--zinc-700` | irregular flicker | random |

**Data source**: `/dev/shm/hapax-compositor/visual-layer-state.json` → `voice_session.state` and `voice_session.active`.

**Click action**: `systemctl --user start/stop hapax-voice.service` (toggle).

### 4.2 Consent Beacon

Full-height (24px) band, 8px wide, at the left edge of the stimmung field.

| State | Color | Source |
|-------|-------|--------|
| Perception off | Absent | `perception-state.json` not updating |
| Perceiving, no recording | `--yellow-400` at 40% | `consent_phase != "recording"` |
| Recording to disk | `--red-400` at 100% | `consent_phase == "recording"` |
| Guest present | `--red-400` pulsing | `guest_present == true` |

Must be visible from across a room. The 8px×24px band at full red-400 saturation against a dark bar background is high-contrast enough for 3-5 meter visibility.

### 4.3 Agent Heartbeat

Encoded as particle drift speed in the stimmung field:

| State | Particle speed | Source |
|-------|---------------|--------|
| No agents running | 0.1px/s (near-still) | `/api/agents/runs/current` |
| Background maintenance | 0.5px/s | Agent count > 0, no LLM |
| Active LLM agent | 2px/s | Running agent has LLM tier |
| Multiple concurrent | 4px/s + density increase | Multiple running |

Not a separate widget — it's a parameter of the stimmung field's particle system.

### 4.4 Temporal Ribbon

60px wide `Gtk.DrawingArea` in the right zone, between cost whisper and clock.

**Visual encoding**:
- Background gradient shifts color temperature through the day (cool morning → warm afternoon → dim evening). Driven by hour-of-day, not stimmung.
- If `CalendarContext.meetings_in_range(1)` returns an event within 60 minutes: a contracting element appears, shrinking as the event approaches. Color: `--blue-400`.
- Session duration encoded as a faint fill from left, growing rightward over hours.

**Data source**: `datetime.now()` for circadian position, `CalendarContext` for next event, session start time from process uptime.

### 4.5 Cost Whisper

30px wide `Gtk.DrawingArea` in the right zone.

- Vertical fill bar (bottom-to-top) showing budget remaining
- 100% = green tint, 50% = neutral, 25% = amber, 10% = red
- No numbers in ambient view
- Hover tooltip: `$14.37 today ($7.20 avg) — 72% budget remaining`

**Data source**: `GET /api/cost` every 5 minutes.

---

## 5. Stimmung Subscription

### 5.1 File Watcher

Poll `/dev/shm/hapax-stimmung/state.json` every 2 seconds via `GLib.timeout_add(2000)`.

```python
def _poll_stimmung(self) -> bool:
    try:
        data = json.loads(Path("/dev/shm/hapax-stimmung/state.json").read_text())
        self._stance = data.get("overall_stance", "nominal")
        self._dimensions = {
            k: v for k, v in data.items()
            if isinstance(v, dict) and "value" in v
        }
        self.queue_draw()
    except (FileNotFoundError, json.JSONDecodeError):
        pass  # stimmung not running — render as nominal
    return GLib.SOURCE_CONTINUE
```

### 5.2 Stance-to-Animation Mapping

```python
BREATHING_PARAMS = {
    "nominal":  {"period": 0,    "amplitude": 0},
    "cautious": {"period": 8.0,  "amplitude": 0.05},
    "degraded": {"period": 4.0,  "amplitude": 0.10},
    "critical": {"period": 0.6,  "amplitude": 0.15, "scale_pulse": 1.15},
}
```

### 5.3 Biometric Modulation

When `operator_stress.value > 0.5` or `operator_energy.value < 0.3`:
- Reduce particle count by 50%
- Reduce breathing amplitude by 30%
- Dim non-critical color contributions by 20%

The bar backs off when the operator is stressed. The system accommodates rather than adds to cognitive load.

---

## 6. File Layout

```
hapax_bar/
├── __init__.py
├── __main__.py
├── app.py                    # Application + window management
├── bar.py                    # Bar window factory (zones, module wiring)
├── reactive.py               # Variable, Binding, hook (unchanged)
├── theme.py                  # CSS loading + mode switch (unchanged)
├── stimmung.py               # Stimmung file reader + state
├── logos_client.py            # HTTP client for Logos API (unchanged)
├── socket_server.py           # Control socket (extended protocol)
├── modules/
│   ├── __init__.py
│   ├── stimmung_field.py     # NEW: custom Gtk.Widget with do_snapshot()
│   ├── voice_orb.py          # NEW: voice state indicator (drawn in stimmung field)
│   ├── consent_beacon.py     # NEW: recording/perception indicator
│   ├── temporal_ribbon.py    # NEW: circadian + session + countdown
│   ├── cost_whisper.py       # NEW: budget-remaining fill bar
│   ├── workspaces.py         # Unchanged
│   ├── window_title.py       # Unchanged (moves to center, rendered subtly)
│   ├── submap.py             # Unchanged
│   ├── audio.py              # Simplified to volume pip only
│   ├── mpris.py              # Condensed, text only when playing
│   ├── working_mode.py       # Badge only, socket-driven
│   ├── clock.py              # Simplified
│   └── tray.py               # Unchanged
├── seam/
│   ├── __init__.py
│   ├── seam_window.py        # Astal.Window overlay + Revealer
│   ├── metrics_panel.py      # Health, GPU, CPU, mem, disk, docker, net, temp
│   ├── stimmung_detail.py    # 10-dimension readout with trends
│   ├── voice_panel.py        # Voice state detail
│   ├── temporal_panel.py     # Session + next event
│   ├── controls_panel.py     # Secondary controls (voice, studio, nudges)
│   └── session_panel.py      # Alpha/beta relay status
└── styles/
    ├── hapax-bar-rnd.css      # Updated with stimmung field styles
    └── hapax-bar-research.css # Updated
```

---

## 7. Migration from v1

v2 is an evolution of v1, not a rewrite. The changes:

| v1 Component | v2 Change |
|-------------|-----------|
| 12 text modules (right zone) | Replaced by stimmung field + 5 compact widgets |
| `logos_client.py` HTTP polling | Kept, supplemented by `/dev/shm` file reads |
| CSS themes | Extended with stimmung field + seam layer styles |
| Socket protocol | Extended with stimmung/voice/perception/temporal/cost commands |
| `Gtk.Box` center zone | Replaced by `StimmungField` custom widget |
| Click-to-open-htop handlers | Moved to seam layer secondary controls |

The workspace buttons, tray, MPRIS, and audio modules carry forward. The module interface doesn't change — v2 adds new modules and removes text-heavy ones.

---

## 8. Resolved Technical Decisions

| Decision | Resolution | Rationale |
|----------|-----------|-----------|
| Popover vs separate window for seam layer | **Separate `Astal.Window`** | Popovers clip on narrow layer-shell surfaces (Astal#278) |
| Cairo vs GtkSnapshot for stimmung field | **`do_snapshot()` hybrid** | GPU gradients via `append_linear_gradient()`, particles via `append_cairo()` |
| Animation timing | **`add_tick_callback()`** | Vsync-aligned, proper frame timing via `FrameClock` |
| Stimmung data source | **`/dev/shm` file read** | Lower latency than API, already written by visual layer aggregator |
| Calendar data | **`CalendarContext` import** | Direct Python access, no HTTP overhead, cached state file |
| Seam layer position | **Top-anchored, below bar** | `margin_top = 24`, centered, 600px wide |
| Breathing animation | **Global opacity oscillation** | `push_opacity()` on entire stimmung field, GPU-composited |
| Biometric modulation | **Dampen visual energy** | Reduce particles, breathing, color when stress high |
