# Hapax Bar — Reconception

**Date:** 2026-03-24
**Status:** Design vision
**Premise:** Now that we have fine-grained programmatic control over the bar, what should it actually be?

---

## The Problem with What We Built

The current hapax-bar is waybar reimplemented in Python. Twenty text modules displaying bracketed numbers: `[hpx:105/105] [gpu:52°C 8.5G] [cpu:23%] [mem:62%]`. It is an **information refrigerator wearing a radiator's clothes** — always visible, but requiring focal attention to decode symbolic encodings. The operator must read numbers, parse abbreviations, and mentally compute whether `62%` memory is normal.

This is a monitoring surface. It demands the cognitive process (situation assessment) rather than supporting the state (situation awareness). For an operator whose executive function infrastructure exists precisely because sustained monitoring is a documented cognitive challenge, this is architecturally wrong.

## What the Bar Ought to Be

The bar is the **most peripheral Logos surface** — always visible, never navigated to, occupying the thinnest possible spatial slice at the edge of visual attention. By the design language's own logic (§1.5: "Position is fixed; state is encoded through color, pattern, and motion"), the bar should encode system state through **preattentive visual features**, not through text that requires reading.

### Three Principles

**1. The bar is a VU meter, not a readout.**

The operator is a hip hop producer. The perceptual vocabulary is already there: a VU meter shows loudness through needle position relative to a learned reference (0 VU). You don't read the number — you attune to the shape. The needle's deviation from normal draws your eye only when something is wrong. A meter bridge across 24 channels gives panoramic peripheral awareness of the mix through the overall visual contour, not through reading individual values.

The bar should work the same way. System health is not `[hpx:105/105]` — it is a color. A color that is gray when nominal, that warms toward amber when something drifts, that pulses when critical. The operator's eye learns to rest on gray and snap to color. This is the ISA-101 "going gray" principle already specified in §1.4 of the design language.

**2. The bar is attuned to stimmung, not polled on interval.**

The current bar polls the Logos API on fixed intervals (30s health, 5min mode). It has no awareness of system mood. But stimmung is the system's continuously-variable affective state — it already integrates health, resource pressure, error rate, perception confidence, operator biometrics, and grounding quality into a unified stance (nominal/cautious/degraded/critical).

The bar should **render stimmung directly**. Not as a label, but as a pervasive visual quality. When stimmung is nominal, the bar is quiet — dark, low-contrast, barely there. When stimmung shifts to cautious, the bar warms slightly, the severity modules gain subtle luminance. When degraded, breathing animation appears. When critical, the bar pulses. This is §6.1 (breathing animation encodes urgency through frequency) applied to the bar as a whole.

The operator doesn't check the bar. The operator is **attuned** to it — aware of its visual temperature in peripheral vision, the same way you're attuned to engine noise while driving. An unusual change is noticed immediately without focal attention.

**3. The bar reveals seams, not symbols.**

Chalmers' seamful design: show the system's actual state rather than abstracting it behind numbers. The bar should honestly radiate operational reality. Not `[dock:13]` but the visual presence or absence of infrastructure health. Not `[net:192.168.1.100]` but the visual solidity or fragility of connectivity. The representation should match the operator's mental model (am I connected? is the system healthy? is something wrong?) rather than the system's internal metrics.

---

## The Reconceived Bar

### Structure: Three Zones

Instead of left/center/right filled with text modules, the bar has three functional zones:

**Left: Spatial Anchor**
Workspaces and submap. These remain interactive buttons because workspace switching is a focal action. But workspace occupancy is encoded through luminance (occupied = visible, empty = nearly invisible), and the focused workspace uses the mode accent color. This is the bar's only deliberately focal zone.

**Center: Stimmung Field**
The center of the bar is not a text display. It is a **continuous ambient field** — a narrow strip that renders stimmung as color temperature and subtle motion. Think of it as the ground surface compressed into 24 pixels of height. In nominal state, it is the background color with perhaps a slow drift of faint particles (§6.5 ambient animation). As stimmung shifts, the field's color temperature changes. As individual systems degrade, localized color variations appear — warm spots in the field corresponding to areas of concern.

The center field replaces: health status, GPU, CPU, memory, disk, docker, temperature, systemd failed, and idle inhibitor. All of these are **symptoms of stimmung dimensions**, and stimmung already synthesizes them.

**Right: Interaction Points**
The interactive modules: volume (scroll to adjust), working mode (click to toggle), clock, tray. These require or afford interaction and therefore must remain as discrete widgets. But they are rendered minimally — the working mode badge and clock are the only text on the right side. Volume is a tiny pip whose color encodes mute state.

### Detail on Demand: The Seam Layer

When the operator hovers over the center stimmung field, the bar expands (or a popover descends) showing the **seam layer** — the actual metrics behind the mood. This is where `105/105`, `52°C`, `23% CPU` live. Not as the primary representation, but as the inspectable detail behind the ambient encoding. Chalmers' principle: seams are available when the task is to understand the infrastructure, but concealed during normal operation.

This matches Pousman & Stasko's periphery-to-center transition: the bar is peripheral by default, focal on demand.

### Visual Vocabulary

| State | Bar Appearance | Preattentive Feature |
|-------|---------------|---------------------|
| Stimmung nominal | Dark, low contrast, still | Gray baseline (ISA-101) |
| Stimmung cautious | Slight warmth, faint luminance increase | Color shift (preattentive) |
| Stimmung degraded | Amber undertone, slow breathing (4s) | Motion + color (preattentive) |
| Stimmung critical | Red undertone, fast pulse (0.6s, 1.15×) | Rapid motion + high saturation (preattentive + popout) |
| Single check failed | Localized warm spot in stimmung field | Color anomaly in spatial position |
| Working mode switch | Palette transition across entire bar | Global color change (preattentive) |
| Recording active | Privacy indicator pulses red | Motion + color (popout) |
| Media playing | Subtle waveform in left zone | Organic motion |

Every encoding uses preattentive features (color, motion, size, luminance) rather than symbolic features (text, numbers, icons). The operator's visual system processes these in under 500ms without focal attention.

### Stimmung Integration

The bar subscribes to stimmung via `/dev/shm/hapax-voice/perception-state.json` or the Logos API. The visual rendering maps stimmung dimensions to the bar's appearance:

- **Overall stance** → bar background color temperature
- **health dimension** → spatial region of the stimmung field
- **resource_pressure** → breathing animation rate
- **error_rate** → color saturation in affected region
- **perception_confidence** → ambient particle density
- **operator_stress** (biometric) → very subtle desaturation of the whole bar (the system backs off visually when the operator is stressed)

The last point is critical and novel: **the bar responds to the operator's state, not just the system's state.** When watch biometrics indicate high stress or fatigue, the bar becomes quieter — less contrast, slower animation, fewer visual demands. The system accommodates rather than adds to cognitive load. This directly implements the accommodation philosophy from the executive function research.

### What Disappears

The following modules have no equivalent in the reconceived bar:

- **CPU percentage** — subsumed by stimmung resource_pressure
- **Memory percentage** — subsumed by stimmung resource_pressure
- **Disk percentage** — rarely urgent, available in seam layer
- **Temperature number** — subsumed by stimmung; critical temp triggers stimmung degradation
- **Docker count** — subsumed by health dimension; zero containers triggers stimmung degradation
- **Health fraction** — the fraction `105/105` is a monitoring metric; the bar shows the *feeling* of health, not the number
- **GPU stats** — subsumed by resource_pressure; VRAM critical triggers stimmung
- **Systemd failed count** — triggers stimmung degradation directly
- **Network IP** — connectivity is encoded as visual solidity, not an address string
- **Idle inhibitor label** — a single dim indicator, not a text label

These metrics still exist. They live in the seam layer, in the Logos app terrain (bedrock region), in the health monitor. The bar doesn't need to replicate them because the bar is not a dashboard. It is a **peripheral awareness surface**.

### What Remains as Text

Only four text elements survive:

1. **Workspace numbers** (1-5) — spatial anchor, focal interaction target
2. **Working mode badge** ([R&D] or [RES]) — identity of the operator's current stance
3. **Clock** — temporal anchor
4. **Submap name** — when active, needs to be read (it names the current keybinding mode)

Everything else is color, motion, and spatial position.

---

## Relationship to Logos Design Language

This reconception is not a departure from the design language — it is its most faithful application. The current text-based bar violates several governing principles:

- §1.1 (Functionalism): Numbers that could be encoded as color are not encoding information efficiently
- §1.4 (Color is meaning): The bar uses color for severity classes but still relies primarily on text
- §1.5 (Density as spatial memory): The bar uses text that must be read rather than positions that encode state
- §6 (Animation families): The bar uses none of the four animation families despite having the technical capability
- §3.7 (Severity ladder): The bar shows severity as CSS classes but doesn't use the ladder as its primary visual encoding

The reconceived bar fully implements:
- **ISA-101 "going gray"**: Normal state is gray; color = attention demand
- **Breathing animation**: Stimmung urgency encoded as animation tempo
- **Severity ladder**: The only color vocabulary, applied to the stimmung field
- **Mode invariance**: Spatial layout unchanged between R&D and Research; only palette shifts
- **Depth control**: Seam layer is the bar's equivalent of surface → stratum depth transition

---

## Relationship to Music Production

The bar becomes a **meter bridge for the system**.

A meter bridge does not show 24 individual numbers. It shows 24 columns of light whose relative heights form a visual contour. The producer attunes to the contour, not the values. When a channel clips, the red light at the top draws the eye — color popout, not number reading.

The hapax bar's stimmung field works the same way. The overall color temperature is the contour. A hot spot in the field is a clip indicator. The severity ladder is the meter scale. The breathing animation is the integration time — slow breathing is a VU meter (averaged, perceptual), fast breathing is a peak meter (instantaneous, alerting).

The producer doesn't monitor the meter bridge. The producer is **attuned** to it.

---

## Implementation Path

The existing hapax-bar codebase supports this reconception without rewrite. The changes are:

1. **Add stimmung subscription** — read from `/dev/shm` or API, map to color temperature
2. **Replace text modules with a `StimmungField` widget** — a custom `Gtk.DrawingArea` that renders the ambient field using Cairo
3. **Add breathing animation** — `GLib.timeout_add` driving opacity/scale oscillation based on stimmung stance
4. **Add seam layer popover** — the existing text modules move here, shown on hover
5. **Reduce right-side modules** — keep only volume pip, mode badge, clock, tray
6. **Add biometric modulation** — read operator stress from perception state, dampen bar visual energy

The socket protocol already supports this: `{"cmd": "stimmung", "stance": "cautious", "dimensions": {...}}` can drive the field directly.

---

## What This Makes Possible

When the bar is a stimmung surface rather than a monitoring dashboard:

- **The operator develops attunement** — implicit ongoing awareness of system health without cognitive cost
- **Accommodation is architectural** — the bar responds to operator state, backing off when stress is high
- **The calm technology promise is fulfilled** — the bar moves naturally between periphery and center
- **The design language is unified** — the bar speaks the same visual language as the Logos terrain
- **Executive function is externalized, not demanded** — the operator doesn't need sustained attention to maintain SA

The bar stops being a thing you read and becomes a thing you feel.
