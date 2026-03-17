# Visual Design Parameters Research

**Date**: 2026-03-17
**Status**: Complete — all 6 pre-planning questions answered
**Depends on**: [Hapax Ontology & Visual Fitment](hapax-ontology-and-visual-fitment.md), [Multi-Technique Rendering Architecture](multi-technique-rendering-architecture.md)

---

## Q1: Gray-Scott Parameter Space

The definitive map is Munafo's xmorphia (extends Pearson's 14-type classification). Key finding: **very slight parameter changes produce drastic pattern changes near regime boundaries**. The health-to-parameter mapping must be nonlinear — compress "healthy" into a stable regime interior, reserve boundary-crossing for genuine state changes.

### Regime Map for Hapax States

| System State | F Range | k Range | Visual Pattern | Pearson Type |
|---|---|---|---|---|
| Nominal | 0.035-0.042 | 0.060-0.065 | Stable spots/stripes | kappa/lambda |
| Cautious | 0.030-0.035 | 0.055-0.060 | Labyrinthine, slowly shifting | mu |
| Degraded | 0.020-0.030 | 0.050-0.055 | Pulsing solitons, unstable | epsilon |
| Critical | 0.010-0.020 | 0.045-0.050 | Spiral waves, pattern collapse | alpha decay |
| Recovery | Trajectory from degraded → nominal | — | Pattern regrowth from seed spots | — |

### Key Design Decision
Nonlinear mapping. Health dimension [0.0, 0.3] maps to a SMALL region of parameter space (stable interior). [0.3, 0.85] crosses one boundary. [0.85, 1.0] crosses into collapse territory. This prevents visual noise from normal health fluctuations.

Sources: mrob.com/pub/comp/xmorphia, karlsims.com/rd.html, visualpde.com

---

## Q2: Spatial Layout

**Key finding: calm technology literature strongly favors FIXED spatial positions.** Don't use force-directed layout. The operator builds a mental model of "what lives where." Position is predictable; state is encoded through color, pattern, and motion within each region.

### Proposed Layout (Center-Weighted Salience)

```
┌────────────────────────────────────────────┐
│                                            │
│  ┌─────────┐               ┌─────────┐    │
│  │ CONTEXT │               │GOVERNANC│    │
│  │ TIME    │               │  E      │    │
│  └─────────┘               └─────────┘    │
│                                            │
│  ┌──────┐    ╔════════════╗   ┌──────┐    │
│  │WORK  │    ║ PERCEPTION ║   │HEALTH│    │
│  │TASKS │    ║  (center)  ║   │INFRA │    │
│  │      │    ║            ║   │      │    │
│  └──────┘    ╚════════════╝   └──────┘    │
│                                            │
│  ┌─────────────────────────────────────┐   │
│  │         SYSTEM STATE (stimmung)     │   │
│  └─────────────────────────────────────┘   │
│  ┌─────────────────────────────────────┐   │
│  │ ▓▓▓▓▓▓  SEDIMENT (accumulations) ▓▓│   │
│  └─────────────────────────────────────┘   │
└────────────────────────────────────────────┘
```

Center = perception (most-glanced, fastest heartbeat). Periphery = infrastructure, governance (stable, rarely changing). Bottom = accumulations (history grows upward). System state spans width (broadcast, affects everything).

---

## Q3: Color Palette

**Key finding: ISA-101 "going gray" principle.** Gray is normal, color means attention needed. Saturation IS the severity encoding. More saturated = more urgent.

**ADHD finding: blue discrimination is impaired.** Don't encode critical transitions on blue-yellow axis alone.

### Oklch Palette for Stimmung Stances

| Stance | L (lightness) | C (chroma) | H (hue) | Character |
|---|---|---|---|---|
| Idle/resting | 15-20% | 0.01-0.02 | 80-90° (warm gray) | Near-monochrome, minimal |
| Nominal/flowing | 25-35% | 0.03-0.06 | 160-180° (teal-green) | Cool, calm, present |
| Cautious | 35-40% | 0.06-0.10 | 80-100° (amber) | Warm, alert |
| Degraded | 40-50% | 0.10-0.15 | 30-50° (orange-red) | Hot, demanding |
| Critical | 50-60% | 0.15-0.20 | 0-20° (red-magenta) | Maximum saturation |

Color space: **Oklch** (polar Oklab) for all interpolation. No hue shifts during transitions. Perceptually uniform.

---

## Q4: Ripple/Wave Physics

**Key finding: R-D waves permanently alter the pattern.** Don't perturb the R-D field directly for transient events. Instead, overlay a **separate damped 2D wave equation** that modulates the R-D field's visual output (brightness/displacement) without changing its chemistry.

### Wave Parameters

| Parameter | Value | Effect |
|---|---|---|
| Propagation speed (c) | 3-5 px/frame | Visible but not jarring |
| Damping (gamma) | 0.1-0.2 | Natural decay, 5-15 frames visible |
| Initial amplitude | 0.1-0.5 (proportional to event severity) | Visible ripple |
| Composition mode | Multiplicative on R-D output | Modulates brightness without altering chemistry |

Multiple simultaneous ripples naturally interfere (superposition). High event rates create standing wave textures — "busy" as a visual quality.

---

## Q5: Sediment/Stratification

**Key finding: Visual Sedimentation (Huron & Vuillemot 2013, IEEE TVCG) directly solves this.** Three-phase lifecycle:

1. **Particle phase**: New items fall as individual particles (recent, identifiable)
2. **Settling phase**: Particles compress and aggregate (recent history)
3. **Strata phase**: Fully compressed into colored layers (deep history)

This gives **temporal zoom for free**: read top-to-bottom = recent-to-ancient. No separate history UI needed.

### Encoding

| Sediment Property | Encodes |
|---|---|
| Layer thickness | Duration of activity period |
| Layer color | Activity type (coding=teal, music=amber, browsing=gray) |
| Layer texture | Event density / complexity |
| Erosion patterns | Corrections / corrections that overrode prior patterns |
| Gaps (unconformities) | System downtime / mode changes |

Renders as a 1D height strip at the bottom of the canvas. R-D field above, sediment below, interface between = where current activity meets accumulated history.

---

## Q6: Technique Selection

**Key findings:**

1. **Draco's constraint model** transfers to technique selection. Encode "which layer for this state" as soft constraints with learned weights. Hard constraints prevent cognitive overload (e.g., never show all 5 layers at full opacity during critical alarm).

2. **Attention-aware visualization** (Srinivasan 2024): organs the operator hasn't looked at recently should gradually increase visual prominence. Creates natural attention-balancing feedback.

3. **VJ tool pattern**: Continuous mixing weights (like faders), not discrete switching. Each technique has a weight [0,1] that modulates opacity, scale, animation speed. Crossfade, don't cut.

### Selection Inputs

| Input | Effect on Technique Mix |
|---|---|
| System volatility | High → emphasize wave/ripple layer |
| Operator attention state | Low → reduce complexity, increase signal-to-noise |
| Information density | High → emphasize sediment and particle layers |
| Stimmung stance | Drives color regime and R-D parameters |
| Time of day | Night → reduce brightness and motion globally |
| Audio energy | Bass → R-D pulse, beat → feedback flash |
| Flow state | Deep flow → suppress all non-R-D layers, maximize calm |

### Architecture

Model as a **5-channel mixer** with continuous faders:
```
[R-D field]     ████████████░░░░  0.75
[Physarum flow]  ██████░░░░░░░░░░  0.40
[Voronoi cells]  ████░░░░░░░░░░░░  0.25
[Wave overlay]   ██░░░░░░░░░░░░░░  0.15
[Sediment]       ████████░░░░░░░░  0.50
```

Each fader driven by a weighted combination of the selection inputs. The content scheduler already does this for text content — extend the same softmax sampling to visual technique weights.
