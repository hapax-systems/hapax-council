---
title: "Hapax Corpora: Research Synthesis"
generated: 2026-03-16
sources: 3 parallel research agents — (a) systems audit, (b+d) literature/design, (c) tech stack
total_sources: 100+
---

# Hapax Corpora: Research Synthesis

## The Five Questions

### Q1: How Should Hapax Think About Hapax Corpora?

**The display IS the agent's body, not a window into the agent.**

Merleau-Ponty's phenomenology: perception is an "existential act" emerging from
the dialectical intertwining of body and world. Digital phenomenology extends
this — corporeality and virtuality are "entangled and multidimensional phenomena."
The screen is not a representation of Hapax; it IS Hapax's mode of being.

A dashboard serves the user by presenting information. A corpora IS the agent.
The difference: information answers "what is the state?" while intention answers
"what is the agent attending to?" (Refik Anadol: "If a machine can learn, can it
also dream?")

**Key references:**
- teamLab Body Immersive: dissolve boundaries between viewer and artwork
- Refik Anadol: data is dreamed, not displayed
- Casey Reas: software reveals process, not results
- Bizzocchi's Re:Cycle: "reward viewer attention whenever it occurs"

**Principles:**
1. No chrome, frames, or UI containers — content fills the surface
2. Data is transformed into aesthetic experience
3. Show process and attention, not conclusions and metrics
4. React to operator presence (the agent "notices" you)
5. Feel situated in the physical room

### Q2: What Can Currently End Up There?

**14 categories, multi-cadence, vastly more data than should ever be shown.**

| Category | Sources | Cadence | Visual Potential |
|----------|---------|---------|-----------------|
| Video | 4 cameras, compositor, FX | 33ms (30fps) | Live feeds, composites |
| Perception | VAD, faces, presence, activity | 2.5s | Presence indicator, mode |
| Health/GPU | 99 checks, VRAM, containers | 30s | Status grid, sparklines |
| Nudges | 7 max, prioritized | 5min | Priority stack, actions |
| Briefing | Headline + action items | Daily | Headline card |
| Drift | 46 items, 11 high severity | Weekly | Severity matrix |
| Goals | Primary + secondary, staleness | 5min | Timeline, staleness |
| Scout | Adopt/evaluate/monitor | Weekly | Recommendation cards |
| Profile | 11 dimensions, 1000+ facts | Varies | Dimension matrix |
| Governance | Consent, axioms, contracts | Event | Coverage gauge, heartbeat |
| Events | Audit logs, SDLC, decisions | Continuous | Event timeline |
| Calendar | RAG-indexed events | Hourly | Meeting density |
| Audio | CLAP, genre, energy, VAD | 2.5-12s | Genre tags, energy meter |
| Generative | 9 shader presets + ambient | Per-frame | Full-canvas art |

**Plus:** Qdrant collections (claude-memory, profile-facts, documents,
axiom-precedents, studio-moments), weather, ntfy notifications, timer
schedules, agent registry, cost tracking.

**The key insight:** Curation is the design problem, not data availability.

### Q3: What Should IDEALLY End Up There?

**System state as mood, not metrics. External info as sensation, not widgets.**

| What | How It Should Manifest | NOT This |
|------|----------------------|----------|
| System health | Background color warmth | Dashboard gauge |
| Flow state | Visual stillness/stability | "FLOW: ACTIVE" text |
| Stress detected | Simpler visuals, less contrast | "You seem stressed" |
| Meeting approaching | Gradual color temperature shift | Calendar widget |
| Weather | Ambient light quality | Forecast panel |
| Nudge (high) | Shape/size change in a zone | Pop-up notification |
| Time passing | Slow color evolution | Digital clock |
| Music playing | Visual texture responds to audio | Genre label |
| Production mode | Visual intensity increases | Mode badge |
| Guest present | Subtle formality shift | "Guest detected" |

**The operator should never "read" the display — they should feel it.**

Information scent (Pirolli & Card): surface just enough to trigger recognition
without demanding processing. Preattentive channels (hue, size, motion onset)
for ambient communication — never text for ambient info.

**Generative beauty is not idle — it's the agent's resting state.**

### Q4: How Should Things Be Represented?

**Multiple valid representations per signal. Context determines which.**

Each signal maps to a rendering strategy based on display state:

| Signal | Ambient | Peripheral | Informational |
|--------|---------|------------|---------------|
| Health | Background warmth | Colored dot | Text + sparkline |
| Nudge | Zone glow | Title fade-in | Title + detail + action |
| Flow | Animation speed | State icon | Score + label |
| Calendar | Color temp shift | Time marker | Event card |
| Audio | Visual texture | Genre tag | Energy meter + genre |
| Governance | Teal accent | Badge | Status + contract list |

**Composition principles:**
- Layer stack: generative base → video (optional) → data zones → text
- Unify through shared tonal treatment (OKLCH with identity hue)
- Dynamic crossfade mixing, never hard cuts
- Visual priority through size, contrast, negative space

### Q5: What Is the Scope?

**Hapax Corpora = the visual manifestation of the agent's being.**

Scope includes:
- ✅ System state (as mood/posture)
- ✅ Perception state (operator presence, activity, flow)
- ✅ Biometric response (stress → calm, flow → stability)
- ✅ Signal surfacing (nudges, alerts, governance)
- ✅ Camera feeds (as injected content, not default)
- ✅ Generative art (the resting state)
- ✅ Time awareness (color evolution, not clock)
- ✅ Creative/performative modes (audio-reactive, rules suspended)
- ✅ External context (weather as light quality, not forecast)

Scope excludes:
- ❌ Direct mirroring of operator's screen
- ❌ Interactive widgets (this is not a dashboard)
- ❌ Text-heavy information display
- ❌ Notification pop-ups
- ❌ Settings or controls (use keyboard shortcuts)

---

## Design Boundaries

### The AuDHD Paradox: Predictable Novelty

The central design challenge. Autism needs predictable spatial relationships.
ADHD needs visual novelty. Solution: **predictable structure + novel content.**

"The subscription box metaphor: the delivery schedule is predictable and the
unboxing ritual becomes routine, while the contents change monthly."
(Hamstead, AuDHD research)

- Fixed spatial zones (autistic predictability)
- Varying content within zones (ADHD novelty)
- Soft boundaries and gradients, never hard edges
- All transitions 1-3 second crossfades

### The Alive Test (not the Wallpaper Test)

The research says "would you leave this on all day without it annoying you?"
But the operator rejects emptiness. The right question is: **"would you leave
this on all day without it BORING you?"** Hapax should be alive, playful,
surprising. The Ambient state is where Hapax has the MOST freedom, not the
least. When nothing needs attention, Hapax plays.

**Ambient state = time to be interesting:**
- Generative art that evolves in unexpected ways
- Camera feeds with experimental color grading
- Visual experiments, remixed shader presets
- Floating text fragments (interesting profile facts, not alerts)
- Images surfaced from Qdrant collections
- Occasional silliness — glitch art, unexpected color, visual puns

**The constraint is NOT "be quiet." It's "don't make my life worse":**
- Don't demand attention (no urgency indicators in Ambient)
- Don't show anxiety-inducing content (no errors, no red)
- Don't repeat (no loops under 30 minutes)
- Don't be ugly (maintain aesthetic coherence)
- Don't be predictable (ADHD needs novelty)
- DO surprise sometimes
- DO be visually rich
- DO fill the space

Requirements:
- No loops shorter than 30 minutes
- No high-contrast flashing
- Color adapts to time of day
- Content transitions: 2-4 seconds
- Never sub-200ms flashes or position jumps
- Negative space is OPTIONAL, not mandatory — visual richness preferred

### Fractal Fluency

Target mid-range fractal complexity (D=1.3-1.5). University of Oregon research:
viewing patterns in this range "can result in stress reduction of up to 60%."
Dynamic fractals maintain attention more than static equivalents.

### Color System

OKLCH for perceptual uniformity. Identity hue for Hapax (deep teal, matching
bass-forward aesthetic). All content mapped through OKLCH transforms.

- Dark mode default: background #0D1117
- Color temperature: 4500-6500K (red text causes highest fatigue)
- Severity: cool→warm gradient (not traffic-light)

### Typography

For peripheral/distance reading:
- Maximum 6-8 words visible at any time
- Minimum 48px for distance legibility
- Sans-serif (JetBrains Mono for code context)
- 140% line spacing
- Text only in Informational/Alert states — never in Ambient

---

## Tech Stack Architecture

### Recommended Stack

1. **Single Chromium tab** in kiosk mode, periodic reload every 6-8h
2. **Raw WebGL** for ambient shader (direct port of `ambient_fbm.frag`)
3. **HLS** for composited video (hardware H.264 decode, one connection)
4. **CSS transitions** for zone opacity (compositor thread, zero JS cost)
5. **React + polling** at 2s for signal state
6. **Self-throttled FPS**: ambient=15, peripheral=20, informational=30, performative=60

### Limits

- 6 concurrent HTTP connections per origin (MJPEG stream limit)
- WebGL shader at 15fps ≈ 3-5W GPU overhead (negligible)
- Memory safety: ring buffers, revoke blob URLs, periodic reload
- CSS mix-blend-mode breaks opacity transitions — avoid on video elements
- p5.js/Three.js are overkill — raw WebGL for single fullscreen quad

### Power Management

- AMBIENT state: 10-15 FPS, minimal GPU
- Display DPMS via `hyprctl dispatch dpms off` when operator absent
- GPU power management: `nvidia-smi -pm 1` for auto-downclock

---

## Sources

110+ sources across ambient intelligence, embodied cognition, calm technology,
multimodal fusion, affective computing, flow state research, proxemics,
privacy-preserving sensing, neurodivergent design, generative art, VJ culture,
broadcast graphics, browser rendering, WebGL performance, and ADHD/autism
visual design. Full citations in the research agent outputs.
