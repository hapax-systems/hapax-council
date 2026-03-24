# Hapax Bar v2 — Implementation Plan

**Date:** 2026-03-24
**Design:** [hapax-bar-v2-design.md](2026-03-24-hapax-bar-v2-design.md)

---

## Phasing

Three phases. Each leaves the bar functional. Phase 1 is the critical transformation; phases 2-3 add polish.

---

## Phase 1: Stimmung Field + Seam Layer

**Goal:** Replace 12 text modules with the stimmung field. Move metrics to seam layer. Bar becomes an awareness surface.

### Tasks

1. **`hapax_bar/stimmung.py`** — Stimmung state reader (~60 lines)
   - Read `/dev/shm/hapax-stimmung/state.json` via `GLib.timeout_add(2000)`
   - Parse into stance + dimension dict
   - Fallback: nominal if file missing
   - Read `/dev/shm/hapax-compositor/visual-layer-state.json` for voice_session, biometrics, activity_label

2. **`hapax_bar/modules/stimmung_field.py`** — Custom `Gtk.Widget` (~200 lines)
   - Subclass `Gtk.Widget`, override `do_snapshot()`
   - Base layer: `append_linear_gradient()` with stops derived from dimension values
   - Breathing layer: `push_opacity()` with sinusoidal oscillation per stance
   - Particle layer: `append_cairo()` for drifting particles
   - Voice orb: drawn as radial gradient in particle layer
   - Consent beacon: 8px band at left edge
   - `add_tick_callback()` for vsync animation
   - Properties: stance, dimensions dict, voice_state, consent_state, agent_count

3. **`hapax_bar/seam/seam_window.py`** — Overlay window (~80 lines)
   - `Astal.Window` with `IGNORE` exclusivity, fullscreen anchor
   - `Gtk.Revealer` with slide-down transition (200ms)
   - Click handler on transparent surround → dismiss
   - Escape key → dismiss
   - `margin_top = 26` (bar height + 2px gap)

4. **`hapax_bar/seam/metrics_panel.py`** — Metrics display (~80 lines)
   - Relocate health, GPU, CPU, memory, disk, docker, network, temperature, systemd
   - Display as compact grid of labeled values
   - Severity colors from CSS classes
   - Data from existing `logos_client.py` polling (unchanged)

5. **`hapax_bar/seam/stimmung_detail.py`** — Dimension readout (~40 lines)
   - 10 dimensions: name, value, trend arrow (▲▼▬)
   - Freshness indicator for stale dimensions
   - Stance label with severity color

6. **`bar.py` update** — Rewire center zone
   - Remove: health, gpu, cpu, memory, disk, docker, temperature, systemd, idle modules from bar surface
   - Add: `StimmungField` as center zone widget
   - Wire stimmung reader → field properties
   - Wire click on stimmung field → seam window toggle

7. **`app.py` update** — Create seam window
   - Instantiate seam window in `do_command_line()`
   - Register with application
   - Wire dismiss handler

8. **CSS updates** — Stimmung field + seam layer styles
   - Seam window background, panel styles, grid layout
   - Remove now-unused module styles (or keep for seam layer reuse)

### Acceptance
- Bar renders stimmung field with color gradient responding to live stimmung state
- Breathing animation visible when stance is cautious/degraded/critical
- Click stimmung field → seam layer slides down showing all metrics
- Click outside seam layer → dismisses
- No text modules in center zone
- Working mode badge, volume, clock, tray still on right zone

---

## Phase 2: Voice Orb + Consent Beacon + Agent Heartbeat

**Goal:** The three continuous-awareness elements that are novel to hapax.

### Tasks

1. **Voice orb rendering** in `stimmung_field.py` (~50 lines added)
   - Read `voice_session.state` from visual layer state
   - Draw animated orb at left-third of stimmung field
   - State machine: off/idle/listening/processing/speaking/degraded
   - Click detection on orb → toggle voice daemon via `subprocess`

2. **Consent beacon rendering** in `stimmung_field.py` (~30 lines added)
   - Read perception state consent_phase + guest_present
   - Draw 8px full-height band at left edge
   - Red when recording, amber when perceiving, absent when off
   - Pulse when guest present

3. **Agent heartbeat** in `stimmung_field.py` (~20 lines added)
   - Read `GET /api/agents/runs/current` on 10s poll
   - Map running agent count to particle speed parameter
   - No new widget — parameter feeds into existing particle system

4. **Seam voice panel** — `hapax_bar/seam/voice_panel.py` (~30 lines)
   - Voice state, routing tier, activation level, last utterance

5. **Seam controls panel** — `hapax_bar/seam/controls_panel.py` (~50 lines)
   - Voice: start/stop/restart buttons
   - Studio: toggle visual layer button

### Acceptance
- Voice orb visible and animating per voice daemon state
- Click orb toggles voice daemon
- Consent beacon shows red when recording active
- Particles speed up when LLM agents are running
- Seam layer shows voice detail and control buttons

---

## Phase 3: Temporal Ribbon + Cost Whisper + Biometric Modulation

**Goal:** The novel time/cost/accommodation elements.

### Tasks

1. **`hapax_bar/modules/temporal_ribbon.py`** (~80 lines)
   - `Gtk.DrawingArea` with `set_draw_func()`
   - Circadian gradient: color temperature shifts by hour
   - Calendar countdown: import `CalendarContext`, show contracting element when event within 60min
   - Session duration: faint fill from left
   - Replaces clock module in right zone (clock text at right end of ribbon)

2. **`hapax_bar/modules/cost_whisper.py`** (~40 lines)
   - `Gtk.DrawingArea` with `set_draw_func()`
   - Vertical fill bar: budget remaining
   - Color thresholds: green (>75%), neutral (50-75%), amber (25-50%), red (<25%)
   - Tooltip: today's spend, average, budget remaining %

3. **Biometric modulation** in `stimmung_field.py` (~15 lines added)
   - When `operator_stress.value > 0.5`: reduce particle count 50%, breathing amplitude 30%
   - When `operator_energy.value < 0.3`: dim color contributions 20%
   - Smooth transitions (lerp over 2s) to avoid jarring changes

4. **Seam temporal panel** — `hapax_bar/seam/temporal_panel.py` (~30 lines)
   - Session duration
   - Next event name + countdown
   - Daily meeting count

5. **Seam session panel** — `hapax_bar/seam/session_panel.py` (~40 lines)
   - Read relay protocol files (`~/.cache/hapax/relay/`)
   - Show other session's branch, last activity, PR state

### Acceptance
- Temporal ribbon shows circadian gradient and event countdown
- Cost whisper shows budget remaining
- Bar visually quieter when operator stress is elevated
- Seam layer shows session and temporal detail

---

## Estimated Scope

| Phase | Files Modified | Files Created | New Lines (est.) |
|-------|---------------|---------------|-----------------|
| 1 | 3 (bar.py, app.py, CSS) | 5 (stimmung.py, stimmung_field.py, seam_window.py, metrics_panel.py, stimmung_detail.py) | ~500 |
| 2 | 1 (stimmung_field.py) | 2 (voice_panel.py, controls_panel.py) | ~200 |
| 3 | 1 (stimmung_field.py) | 4 (temporal_ribbon.py, cost_whisper.py, temporal_panel.py, session_panel.py) | ~300 |
| **Total** | | **~11 new files** | **~1,000 lines** |

---

## Testing Strategy

- Run `python3 -m hapax_bar` alongside waybar (waybar disabled, hapax-bar via systemd)
- Visual verification per phase acceptance criteria
- Smoke test seam layer on dedicated Hyprland workspace (Playwright on empty workspace per feedback memory)
- Stimmung field testable with mock data: write synthetic JSON to `/dev/shm/hapax-stimmung/state.json`
- Consent beacon testable by toggling perception: `systemctl --user stop studio-compositor` → beacon disappears
