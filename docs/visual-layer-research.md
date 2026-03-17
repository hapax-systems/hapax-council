---
title: Visual Communication Layer — Research & Design Framework
generated: 2026-03-16
sources: 110+ papers across ambient intelligence, embodied cognition, calm technology, multimodal fusion, affective computing, flow state, proxemics, privacy-preserving sensing, neurodivergent support, creative environments, peripheral attention, signal prioritization, visual encoding, attention-aware presentation, notification state machines, generative visual design, VJ culture, ADHD/autism visual design
method: two-phase deep research synthesis
---

# Visual Communication Layer — Research & Design Framework

## Architecture Overview

A persistent visual stream where Hapax communicates without speaking. Operates in
Weiser's periphery (calm technology). Scales from "pleasant generative ambient"
through "glanceable information" to "breaking alert" to "performative creative
canvas."

### Three-Layer Rendering Stack

```
Layer 3 (top):    Cairo Informational Overlay  — data-driven elements per category
Layer 2 (middle): Post-processing FX           — color grading, vignette, glow
Layer 1 (bottom): Generative Shader Base       — noise flow field / audio-reactive
```

### Five-State Machine

| State | When | Character | Time Spent |
|-------|------|-----------|------------|
| **Ambient** | No signals OR deep flow | Generative shader only, muted organic movement | 80%+ |
| **Peripheral** | 1-2 non-critical signals, flow < 0.6 | Subtle indicators at ~40% opacity | ~15% |
| **Informational** | 3+ signals OR idle with queue | Structured layout, readable text | ~4% |
| **Alert** | Critical/Serious signal | Color shift, prominent signal, slow pulse | ~1% |
| **Performative** | Production + music + flow | Audio-reactive, rules suspended | <1% |

### Transition Timings (ADHD/sensory-safe)

- Escalation (toward Alert): 200-500ms
- De-escalation: 5-15 seconds
- To Performative: 2-3 second crossfade
- From Performative: 5-10 second gradual return
- All animations >= 500ms. No flicker > 3Hz.

## Signal Taxonomy

6 visual categories mapped to fixed spatial zones:

| Category | Zone | Hue Family | Signals |
|----------|------|------------|---------|
| **Context/Time** | Top-left | Soft blue | Calendar, briefing, daily summary |
| **Governance** | Top-right | Teal/cyan | Consent status, axiom compliance |
| **Work/Tasks** | Left edge | Amber/warm | Nudges, open loops, goals, scout |
| **Health/Infra** | Bottom-right | Green→red | System health, GPU, containers |
| **Profile/State** | Center-top | White/neutral | Flow indicator, activity mode |
| **Ambient/Sensor** | Bottom strip | Varies | Audio energy, genre, weather |

## Visual Variable Budget (5 channels)

1. **Position** — fixed zones (most accurate perceptual channel)
2. **Hue** — 6 categorical families, all desaturated 30%
3. **Size** — 3 levels: subtle (8-12px), normal (16-24px), prominent (32px+)
4. **Opacity** — continuous 0.0-1.0, primary transition mechanism
5. **Slow motion** — drift/pulse for change detection, never > 2Hz

## Color Palette (neurodivergent-safe)

- Background: `#0D1117` (dark blue-grey)
- Ambient base: `#1B4332` → `#2D6A4F` (muted forest green)
- Severity: Off `#586069`, Standby `#58A6B1`, Normal `#3FB950`, Caution `#D2A044`, Serious `#D47B3C`, Critical `#DA3633` (Astro UXDS, desaturated 30%)
- Text: `#C9D1D9` on `rgba(0,0,0,0.6)` backgrounds

## Key Design Principles

### From Ambient Intelligence
- User-centeredness over technology-push
- Social intelligence alongside cognitive intelligence
- Ubiquity + transparency

### From Calm Technology (Weiser/Case)
- Smallest possible attention demand
- Make use of the periphery
- Can communicate but doesn't need to speak
- The right amount is the minimum needed

### From Embodied Cognition (Brooks)
- Subsumption: lower layers work independently
- Data flows bottom-up, not top-down
- Reactive behavior over central planning

### From Affective Computing (Picard)
- Modulate, don't comment (never verbalize detected emotional state)
- Operator-legible mappings (transparent if investigated)
- Override always available (physical controls trump system)
- No affect logging (sense-act-forget)

### From Flow State Research
- 23-minute recovery cost per interruption (Gloria Mark)
- HRV U-shaped relationship with flow
- Flow protection is highest-value intervention
- ADHD hyperfocus ≠ flow (distinguish and handle differently)

### From Signal Prioritization (ATC/ICU/Trading)
- Phase-based decluttering (fighter HUD pattern)
- Aggregation before display (ICU Early Warning Score)
- Red is sacred (overuse = alarm fatigue)
- Spatial consistency (zones are learnable)

### From Visual Encoding (Bertin/Mackinlay/Cleveland)
- Position is most accurate channel
- Limit simultaneous preattentive features to 4-5
- Self-describing encodings (no memorization required)
- Sparkline density over dashboard density

### From Neurodivergent Visual Design
- Muted, desaturated palette (no pure white/black)
- No flicker > 3Hz, no rapid animation
- Maximum 3-5 simultaneous information chunks
- At most 1 visual interruption per 30min during deep work
- Consistency above all (same place, same meaning, always)
- Motion communicates change, not decoration

## Failure Modes to Avoid

1. **Technology-push**: Building because you can, not because it serves
2. **Attention theft**: Every visual interruption costs 23 minutes if it breaks flow
3. **Speaking when silence serves**: Visual layer supplements voice, doesn't justify more speech
4. **Alarm fatigue**: Overusing urgency colors/animations destroys their power
5. **Affect commentary**: Never render "you seem stressed" — modulate environment instead
6. **Unpredictable changes**: All shifts gradual and legible
7. **Surveillance creep**: Ephemeral sensing, no affect logging
8. **Social norm violation**: Reduce expressiveness when others present
9. **Dashboard disease**: The ambient state is an aquarium, not a control panel

## Implementation Requirements (leveraging existing infrastructure)

### Already built:
- `cairooverlay` on every compositor frame (reads perception-state.json)
- `glshader` available in GStreamer pipeline
- Cockpit API at :8051 with all signal data
- `studio_effects.py` with 9 GPU shader presets
- `perception-state.json` with flow state, audio energy, consent phase
- Compositor status at `~/.cache/hapax-compositor/status.json`

### Needs building:
1. **Signal aggregator** — polls cockpit API, produces VisualLayerState JSON
2. **Generative ambient shader** — Perlin noise fBM flow field, uniforms from system health
3. **Audio-reactive shader variant** — FFT band uniforms for performative mode
4. **Enhanced Cairo overlay** — renders 6 category zones, state-machine-gated
5. **Transition engine** — manages crossfades via interpolated uniforms/opacity
6. **State machine controller** — reads flow state + signal urgency, drives layer states

## Research Sources

### Ambient Intelligence & Calm Technology
- Aarts & de Ruiter (2009, 2011) — AmI research perspectives
- ISTAG (2001-2003) — foundational AmI vision
- Weiser & Brown (1995, 1996) — calm technology
- Amber Case (2015) — calm technology principles
- Ishii et al. — ambientROOM, Tangible Bits

### Embodied Cognition & Situated AI
- Brooks — subsumption architecture
- Varela, Thompson, Rosch — The Embodied Mind
- Friston — active inference / free energy principle
- Gibson — ecological psychology, affordances

### Perception & Visualization
- Pousman & Stasko (2006) — ambient information systems taxonomy
- Mankoff et al. (2003) — ambient display heuristics
- Skog et al. (2003) — informative art
- Bertin (1967), Mackinlay (1986), Cleveland & McGill (1984) — visual encoding
- Healey — preattentive visual features

### Signal Prioritization
- FAA ATC display standards
- NASA color design for ATM
- ICU alarm fatigue research
- Astro UXDS status system
- McCrickard & Chewar — IRC notification framework

### Affective Computing & Flow
- Picard — affective computing
- Csikszentmihalyi — flow dimensions
- Gloria Mark — interruption cost (23 minutes)
- Physiological flow assessment via wearables (2025)
- Creative flow EEG in jazz improvisers (2024)

### Neurodivergent Design
- Neurodiversity Design System
- Sensory processing in autism (PMC)
- ADHD working memory (Nature)
- Sensory-friendly visual design guidelines
- ADHD hyperfocus vs flow distinction

### Creative Environments & VJ Culture
- teamLab Borderless — immersive responsive art
- Glow with the Flow (2026) — AI ambient lightscapes
- TouchDesigner, Resolume, VDMX — VJ tools
- Audio reactivity analysis techniques

### Privacy
- Cavoukian — Privacy by Design
- SoK: Privacy-enhancing Smart Home Hubs (PETS 2022)
- Zero Data Retention architecture
- Edge-only processing research
