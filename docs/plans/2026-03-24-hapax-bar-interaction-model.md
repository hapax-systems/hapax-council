# Hapax Bar — Interaction Model

**Date:** 2026-03-24
**Companion to:** [hapax-bar-reconception.md](2026-03-24-hapax-bar-reconception.md)
**Question:** What interactive functionality belongs on the bar, and how should it work?

---

## The Constraint Set

Two cognitive profiles create complementary constraints:

| ADHD need | Autism need | Resolution |
|-----------|------------|------------|
| Minimal steps to act | Predictable behavior | Single-action controls in fixed positions |
| Co-located with task | No surprise relocations | Always-visible, never rearranging |
| Few options visible | Consistent options visible | Stable, minimal control surface |
| Immediate feedback | Predictable feedback | Deterministic, instant response |
| Low activation energy | No unpredictable state changes | Direct manipulation, no hidden modes |

The combined design ethic: **Controls are visible, singular, fixed, immediate, and reversible.** They are operable from within the focal task without context switching. They never rearrange, disappear, or change meaning.

Barkley's point-of-performance principle: controls must be at the site of the action, not in a settings panel. The bar passes this test by default — it is always visible. But only if the controls are discoverable without reading.

---

## Three Interaction Tiers

### Tier 0: Ambient (no interaction required)

These are radiative surfaces — the operator attunes to them without touching them. They belong in the **stimmung field** (center zone).

- Stimmung color temperature (system health/mood)
- Breathing animation (urgency encoding via §6.1)
- Voice state orb (idle/listening/processing/speaking/degraded)
- Agent activity pulse (aggregate energy of background work)
- Consent beacon (privacy governance — visible across the room)
- Biometric modulation (bar dims when operator is stressed)
- Perception confidence (ambient particle density)

**Design rule**: Only preattentive features (color, motion, luminance, size). No text. No numbers. Processable in <500ms without focal attention.

### Tier 1: Single-Action Controls (one touch, immediate effect)

Six controls on the bar surface. No menus, no dropdowns, no multi-step flows.

| Control | Gesture | Effect | Feedback |
|---------|---------|--------|----------|
| **Workspace buttons** | Click | Switch workspace | Accent highlight |
| **Volume** | Scroll | ±2% volume | Pip color/size |
| **Volume mute** | Click | Toggle mute | Pip goes gray (ISA-101) |
| **Working mode** | Click | Toggle RND↔Research | Entire bar palette shifts |
| **Voice orb** | Click | Toggle voice daemon | Orb appears/disappears |
| **Clock format** | Click | Toggle short↔long | Text changes |

**Why so few?** Each control is a micro-decision the ADHD brain must process (Hick's Law, amplified by executive function deficit). Six controls is the cognitive budget for a peripheral surface. More controls belong in the seam layer.

### Tier 2: Seam Layer (hover/expand for detail and secondary controls)

Hover or click the stimmung field → bar expands into a popover. Chalmers' seamful design: seams available when the task is to understand, concealed during normal operation.

**Metrics (inspect only)**:
- Health fraction and failed check names
- GPU: temp, VRAM, utilization
- CPU, memory, disk percentages
- Docker container count and systemd failed units
- Network interface and IP
- LLM cost (budget remaining %, daily sparkline)
- Session duration and time-to-next-obligation
- Circadian position (visual energy curve)

**Secondary controls**:
- Voice daemon: start/stop/restart (three discrete buttons)
- Studio compositor: toggle visual layer
- Mic gain adjustment (slider)
- Nudge actions (act/dismiss on visible nudges)
- Accommodation management (confirm/disable)

**Session panel**:
- Other session's branch, last commit, activity heartbeat
- PR state (CI passing/failing/pending)
- Conflict warning if branches overlap

The seam layer is a **popover, not a navigation.** It appears over the current workspace without destroying context. Dismisses on click-away or Escape.

### Tier 3: Deep Actions (Logos app or CLI)

Too complex for a bar: flow state graph, consent contracts, agent configuration, scout reviews, drift reports, briefing deep-dive, profile inspection. The bar indicates these have something worth looking at; the Logos app hosts the actual interaction.

---

## Novel Elements Unique to Hapax

### Voice Orb

A 12-16px orb in the stimmung field encoding voice daemon state:

| State | Visual | Feature |
|-------|--------|---------|
| Idle (cognitive loop) | Slow drift, dim | Low luminance, slow motion |
| Listening (VAD) | Brightens, gentle pulse | Luminance increase |
| Processing | Spinning/flowing | Rapid motion |
| Speaking (TTS) | Expanding rings | Size change + motion |
| Degraded (GPU contention) | Flickering, desaturated | Irregular motion |
| Off | Absent | — |

Click to toggle voice daemon on/off. The most frequently toggled hapax-specific service.

### Consent Beacon

When cameras capture or audio records/streams, a full-height colored band at one end of the bar:

- Red: recording to disk
- Amber: perception active, not recording (analysis only)
- Absent: perception off

Visible from across a room. The interpersonal_transparency axiom (weight 88) requires it. This is a governance surface, not a UX feature.

### Agent Heartbeat

Subtle animation in the stimmung field encoding aggregate agent activity:

- Still: no agents running
- Gentle drift: background maintenance agents
- Visible pulse: active LLM agent
- Energetic motion: multiple concurrent agents

Click to expand in seam layer: current agent name, duration, cancel button.

### Temporal Ribbon

Replaces the clock. A thin horizontal element encoding:

- **Session duration**: how long since work started (filling bar)
- **Time to next obligation**: shrinking countdown if calendar event approaching
- **Circadian position**: color temperature shifts through the day

The clock time is still available on click, but the primary encoding is visual. Addresses time blindness without demanding focal attention.

### Cost Whisper

LLM cost as budget-remaining fill level:

- Full (green tint): well within budget
- Half (no tint): normal pace
- Low (amber tint): above typical daily pace
- Empty (red tint): approaching limit

No numbers in the ambient view. Detail on hover: spend today, pace extrapolation, model breakdown. Awareness of trajectory without dollar-amount anxiety.

---

## What Moves Off the Bar

| Function | Where it goes | Why |
|----------|--------------|-----|
| App launcher | Fuzzel (Super+D) | Launch is focal; bar is peripheral |
| Notification center | Mako + Logos app | Events, not state; bar shows state |
| Bluetooth/WiFi management | CLI or Logos app | Rare, multi-step; violates single-action |
| Network settings | NetworkManager TUI | Connectivity visible via stimmung |
| Power menu | Fuzzel or hyprctl | Rare; not bar-frequency |
| System monitor | htop, nvtop (keybinds) | Deep inspection, not awareness |

---

## Socket Protocol Extensions

```json
{"cmd": "stimmung", "stance": "cautious", "dimensions": {...}}
{"cmd": "voice_state", "state": "listening"}
{"cmd": "agent_activity", "running": 3, "current": "health_monitor"}
{"cmd": "perception", "recording": true, "cameras": 4, "consent_phase": "active"}
{"cmd": "temporal", "session_minutes": 47, "next_event_minutes": 13}
{"cmd": "cost", "budget_remaining_pct": 72}
```

---

## Summary

Traditional bars ask: *"What information can we fit in 24 pixels?"*
Hapax asks: *"What awareness can we sustain in 24 pixels?"*

Six controls. One ambient field. One expandable seam layer. Everything else radiates.

The bar becomes what Weiser described: technology that "engages both the center and the periphery of our attention, and in fact moves back and forth between the two." It fulfills its function as externalized executive function — sustaining the operator's situation awareness without demanding the sustained attention that is precisely what the system exists to compensate for.
