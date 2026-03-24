# Logos UI/UX Reference

Comprehensive reference for the hapax-logos visual interface. Written for narration generators and demo pipelines — describes what is visible, why it looks the way it does, and what each element means.

> **Color, mode, spatial model, and animation vocabulary** are governed by [`docs/logos-design-language.md`](logos-design-language.md). This document governs **region content** — what appears where at each depth.

## Design Philosophy

Logos is not a dashboard. It is a spatial representation of system awareness.

Conventional software organizes by feature — a settings page, a chat page, a status page. Logos organizes by domain of awareness. Time. Cognition. Presence. Flow. Infrastructure. These five domains are always visible simultaneously, at varying levels of detail.

The metaphor is geological terrain. Layers of awareness stacked vertically, each with depth that can be revealed. Surface is calm. Core is immersive. The operator controls depth by clicking or pressing keyboard shortcuts, choosing how much attention to give each domain.

The visual language adapts to working mode: Gruvbox Hard Dark (warm, textured) in R&D mode, Solarized Dark (cool, clinical) in Research mode. Dense information rendered small. Nothing is decorative — every visual element encodes system state.

## The Five Regions

### Horizon (Top, spans full width)

Horizon is about time. What needs attention now, what the system has synthesized recently, what is coming.

**Surface:** A one-line briefing summary on the left. The top three nudges as compact pills on the right. Signal indicator dots in the corner.

**Stratum:** Three-column grid. Left: goals with progress tracking. Center: the full nudge list with priority scores and suggested actions, plus the copilot observation banner. Right: the reactive engine status showing recent rule activations.

**Core:** Everything from stratum plus the full briefing panel — headline, body text in markdown, and action items.

Nudges are the executive function mechanism. Each nudge represents something the system noticed that might need attention: a stale follow-up, an open loop, documentation drifting from reality, a missed deadline approaching. They have priority scores and categories. The system generates them; the operator acts on or dismisses them.

### Field (Middle row, left column)

Field is about cognition. What agents are doing, what sensors detect, what the system knows about the operator right now.

**Surface:** Agent summary (which agent is running, elapsed time), freshness panel (how recently each agent produced data), and operator vitals if biometric data is available — heart rate pulsing at actual tempo, stress indicator (1.5s breathing), physiological load bar (4-step green/yellow/orange/red severity ladder), sleep deficit, phone battery (4-step severity ladder).

**Stratum:** All surface panels plus scout recommendations, drift detection summary, management panel (1:1 staleness, coaching items), and the agent grid — every agent with a run button.

**Core:** The perception canvas. A live compositor snapshot with signal zone overlays positioned at fixed coordinates. Each zone represents a signal category and contains scrollable signal cards. A sidebar provides channel toggles, overlay mode selection (off/minimal/full), and signal breakdown by category.

The perception canvas is the most visually distinctive element. It composites the camera snapshot with semi-transparent zones, each containing real-time signals color-coded by category. It is the system looking at itself through the lens of its own sensor fusion.

### Ground (Middle row, center column)

Ground is about physical presence. The room, the cameras, the ambient state.

**Surface:** The ambient canvas — three drifting organic shapes in warm brown tones with slowly cycling text fragments. A small camera pip (120×68 pixels, 5fps, sepia-tinted) sits in the bottom-right corner. A presence indicator shows operator presence confidence and interruptibility score. The activity label shows what the system thinks the operator is doing (coding, making music, deep work, etc.) with a secondary line showing music genre when playing, LLM classification when CLAP is silent, or flow decomposition contributors (gaze + posture + calm + quiet) when in flow. This is the visual resting state of the system. Calm, warm, unhurried.

**Stratum:** A camera grid replaces the ambient canvas. Six camera feeds in a 2-column layout. Each feed has a color-coded border: red for recording, amber for stale, green for active, grey for inactive. Detection overlays at tier 1 (minimal boxes) appear on each feed.

**Core:** The hero camera fills the entire region. A single feed at high frame rate with full detection overlays — labeled bounding boxes for every detected entity. A secondary camera strip along the bottom allows quick role switching. The presence indicator and signal cluster remain.

Detection overlay coloring encodes rich perceptual information. Colors are **mode-invariant** — they do not change with R&D/Research mode. The complete color vocabulary is documented in design language §3.8. Summary:
- **Person gaze direction** (halo): Teal (screen), yellow (hardware), mauve (person), muted sage (away)
- **Emotion** (secondary tint): Green (happy), teal (sad), red (angry), orange (surprise), mauve (fear), tan (disgust)
- **Motion:** Moving persons shift warm yellow. Persons dwelling 60+ seconds shift cool blue.
- **Consent:** Persons without consent contracts are fully desaturated to grey (`#665c54`). The operator's own person (identified via operator camera role) is never suppressed. Enrichments (gaze, emotion, posture, gesture, action, depth) are withheld for non-consenting persons. When consent is refused, non-operator persons are removed entirely.
- **Non-persons:** Objects (furniture `#bdae93`, instruments `#fabd2f`, electronics `#83a598`, containers `#d3869b`) are drawn dimmer, with opacity scaled by novelty and mobility.
- **IR presets** (NightVision, Silhouette, Thermal IR): High-saturation variant palette for monochrome feed visibility.

The compositor also hosts 12 visual effect presets:
- **Ghost:** Transparent echoes with fading 4-frame trails. Subtle pan/zoom drift.
- **Trails:** Bright additive motion trails with hue shifting. Lighter blend mode.
- **Screwed:** Named after Houston chopped-and-screwed music. Heavy warping, band displacement, syrup gradients, stutter phases. The visual equivalent of slowed, pitched-down production.
- **Datamosh:** Simulated codec glitch artifacts. Difference blending, high contrast, band displacement with stutter.
- **VHS:** Lo-fi tape warmth. Soft blur, sepia tone, tracking noise, slice warping, intermittent stutters.
- **Neon:** Color-cycling glow with 4-degree hue rotation per tick. 8-frame trails, lighter blend, vignette.
- **Trap:** Dark, oppressive mood. Multiply blend, strong vignette, syrup gradient.
- **Diff:** Motion detection. Difference blend reveals movement as bright areas against black.
- **NightVision:** Green phosphor monochrome with scanlines and vignette. Optimized for IR camera feeds.
- **Silhouette:** High-contrast IR shapes. 3.0 contrast, minimal color.
- **Thermal IR:** Inverted monochrome with hue rotation for heat-map appearance.
- **Clean:** Near-invisible processing. Slight contrast and saturation boost, faint vignette.

The compositor runs a dual ring buffer canvas. One buffer for live frames polled at 100ms intervals, one for delayed overlay frames at 200ms with a three-frame offset. This enables temporal effects like trails and ghosting. The architecture is equivalent to a broadcast video switcher.

These effects are functional, not decorative. The operator produces music and streams live. Effects composite in real time over camera feeds during production sessions.

### Watershed (Middle row, right column)

Watershed is about flow. How data and decisions move through the system.

**Surface:** A flow summary showing the stimmung stance (with color-coded dot), active node count, and active flow count. Below that, an event ripple stack — the four newest watershed events, color-coded by category, with decay animation based on time-to-live.

**Stratum:** Flow summary plus a profile panel showing the operator profile across 11 dimensions with population counts, top gaps, and freshness indicators.

**Core:** A full directed acyclic graph of system flow rendered with React Flow. Nine nodes (perception, stimmung, temporal, apperception, phenomenal, voice, compositor, engine, consent) connected by edges that highlight when active. The graph polls every 3 seconds.

### Bedrock (Bottom, spans full width)

Bedrock is about foundations. Infrastructure health, resource usage, governance compliance, consent status.

**Surface:** Five axiom compliance dots (color-coded green/yellow/orange/red). Health summary (healthy/total checks). The stimmung stance word (healthy/degraded/critical). Cost tax percentage. Signal indicator dots.

**Stratum/Core:** A scrollable panel grid:
- **Health:** Overall status, healthy/total/failed counts, failed check list, 7-day history chart, auto-fix button.
- **VRAM:** GPU name, memory usage (total/used/free in MB), temperature, loaded model names.
- **Containers:** All Docker containers with name, service, state, health, image, ports.
- **Cost:** Today/period/daily average costs, top 3 models by cost, tax percentage.
- **Consent:** Active consent contracts, coverage by principal, overhead (latency/memory).
- **Governance:** Heartbeat score (0–1, color-coded), axiom count, coverage by principal, carrier facts.
- **Accommodations** (collapsible): Active accommodations — time anchoring, soft framing, energy-aware scheduling, peak/low hours.
- **Timers:** Systemd timer status (unit, next fire, last fired).

## Signal System

Signals are the system's way of surfacing state changes across all domains. Each signal has a category, title, detail text, severity (0–1), and source identifier.

Eight categories, each with a theme-aware color token (see design language §3.3) and zone position on the perception canvas:
- **context_time** — `blue-400`, top-left zone. Sources: briefing, calendar proximity, pattern predictions.
- **governance** — `fuchsia-400`, top-right zone. Sources: consent phase, axiom violations, SDLC events.
- **work_tasks** — `orange-400`, left edge. Sources: nudges, deadlines, stale follow-ups.
- **health_infra** — `red-400`, bottom-right. Sources: health checks, container status, dead-letter queue.
- **profile_state** — `green-400`, center-top. Sources: flow state, episode boundaries, model disagreement.
- **ambient_sensor** — `emerald-400`, bottom strip. Sources: audio energy, music genre.
- **voice_session** — `yellow-400`, bottom-center. Sources: voice state, routing tier, grounding.
- **system_state** — `zinc-400`, bottom-left. Sources: stimmung transitions, mode changes.

Signal severity drives visual intensity through breathing animations:
- Below 0.2: no animation
- 0.2–0.4: 8-second slow breathing
- 0.4–0.7: 4-second moderate breathing
- 0.7–0.85: 1.5-second fast breathing
- Above 0.85: 0.6-second critical breathing with scale pulse

Signal pip sizes: 6px (severity < 0.4), 8px (0.4–0.85), 10px (≥ 0.85). Pips aggregate in clusters at the corner of each region. Clusters have three density levels matching depth: compact (surface, max 3 per zone), summary (stratum, max 5 with trend sparklines), full (core, all signals grouped by category). Max 5 signals total visible at any time, ranked by severity.

## Stimmung Visualization

Stimmung (system self-state) manifests as region border coloring:
- **Nominal:** No visible border effect. Clean edges.
- **Cautious:** 15% yellow blend on borders. No animation.
- **Degraded:** Orange border glow with `stimmung-breathe-degraded` animation (6-second cycle). Subtle inset shadow.
- **Critical:** Red border glow with `stimmung-breathe-critical` animation (2-second cycle, includes scale pulse to 1.15x). Strong inset shadow.

The stimmung cascade flows top-right to bottom-left because the five regions stack vertically and the CSS grid renders each border independently, creating a visual waterfall of the system's self-assessment.

## Investigation Overlay

Activated by pressing `/`. A 60% width, 90% height centered modal with translucent backdrop blur. Three tabs:

- **Chat:** Direct LLM conversation with streaming responses. Full system tool access.
- **Insight:** RAG-powered document search with Mermaid diagram support and follow-up refinement.
- **Demos:** Gallery of pre-generated demo recordings with video/audio playback.

The overlay auto-hides when the voice daemon is active. Escape dismisses it.

## Classification Inspector

Activated by pressing `C`. A diagnostic overlay (80% width, 90% height) for inspecting per-camera classification data at full density. Exempt from signal density rules — this is an operator tool, not a perception interface.

**Left pane:** Live MJPEG camera feed with canvas-rendered detection boxes. Camera selector dropdown for all 6 cameras (3 Brio, 3 C920). Detection boxes drawn with theme-aware colors (not the mode-invariant terrain detection palette).

**Right pane:** 12 toggleable classification channels in 3 groups:
- **Classification (7):** Detections (YOLO), Gaze direction, Emotion, Posture, Gesture, Scene type, Action
- **Per-Camera (2):** Motion, Depth
- **Temporal (3):** Trajectory, Novelty, Dwell

Each channel has a colored dot from the active theme palette, a toggle switch, and renders its data on the camera canvas when enabled. Person detections show enrichment chips (gaze, emotion, posture, gesture, action, depth) inside the bounding box. Dwell time renders in the box corner. Novelty draws a dashed halo. Trajectory draws a directional arrow.

A confidence threshold slider (0.0–1.0, default 0.3) filters low-confidence detections. All toggle states persist to localStorage.

Colors use `useTheme().palette` tokens — they switch with R&D/Research mode. This is distinct from the terrain's detection overlay (design language §3.8) which uses mode-invariant hardcoded colors for trained perceptual recognition.

## Keyboard Shortcuts

- `H/F/G/W/B` — Focus and cycle depth on Horizon/Field/Ground/Watershed/Bedrock
- `/` — Toggle investigation overlay (Chat/Insight/Demos)
- `C` — Toggle classification inspector (per-camera detection diagnostic)
- `S` — Toggle split pane for focused region
- `D` — Cycle detection tier (1: persons, 2: objects, 3: enrichments)
- `Shift+D` — Toggle detection overlay visibility
- `?` — Toggle system manual drawer
- `Ctrl+P` — Command palette
- `Escape` — Hierarchical dismiss (overlay → split → region collapse → unfocus)

## Visual Layer State Machine

The display state determines overall visual density:
- **Ambient:** Minimal. Organic canvas, subtle pips. System at rest.
- **Peripheral:** 1–2 signals at 40% opacity. Light awareness.
- **Informational:** 3+ signals, structured zone layout. Active monitoring.
- **Alert:** Color shift, pulse, prominence. Something needs attention.
- **Performative:** Audio-reactive parameters. Production/streaming mode.

Transitions between states are driven by signal count, severity thresholds, and operator activity mode. The **deep flow gate** (flow_score ≥ 0.6) suppresses all non-critical signals to AMBIENT state. Only severity ≥ 0.85 breaks through deep flow. PERFORMATIVE mode activates during music production with audio energy and deep flow — all data zones suppress, the ambient shader becomes audio-reactive.

## Demo Mode

Activated by URL parameter: `?demo={name}`. The DemoRunner component loads a script manifest (hand-crafted TypeScript or LLM-generated JSON), fetches pre-rendered WAV audio files, and plays them via Web Audio API with hardware-synced timing. Actions fire at exact timestamps via requestAnimationFrame polling. Press Space to start, Escape to stop. A subtle bottom bar shows the current scene title and progress.
