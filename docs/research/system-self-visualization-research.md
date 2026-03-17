# System Self-Visualization Research

Research into visual representation techniques for a complex adaptive system that needs to display its own internal state as an ambient visual field on a studio monitor. Not dashboard information visualization -- a system making itself visible.

Date: 2026-03-16

---

## 1. Biological / Organic System Visualization

### Reaction-Diffusion Systems

Turing's 1952 "Chemical Basis of Morphogenesis" proposed reaction-diffusion as the mechanism for biological pattern formation. The Gray-Scott model produces spots, stripes, labyrinthine structures, and pulsing solitons depending on two parameters (feed rate, kill rate). This is a continuous field that self-organizes -- exactly the visual metaphor for a system generating its own representation.

- **Best at showing**: Emergent structure, regime changes, system health (healthy parameters produce stable patterns; unhealthy ones collapse or explode)
- **Real-time/ambient**: Yes. GPU fragment shaders run Gray-Scott at 60fps trivially. Amanda Ghassaei's gpu-io library and Karl Sims' tutorial provide reference implementations
- **WebGL/canvas**: Yes. Multiple browser implementations exist, including WebGPU compute shader versions
- **Key insight for Hapax**: Map system parameters (agent load, latency, error rate) to Gray-Scott feed/kill rates. The visual field self-organizes into patterns that reflect system health without needing explicit chart reading. Pattern collapse = system distress

Sources:
- [WebGPU Reaction Diffusion](https://shi-yan.github.io/webgpuunleashed/Compute/reaction_diffusion.html)
- [Gray-Scott Parameterization (MROB)](http://www.mrob.com/pub/comp/xmorphia/index.html)
- [Karl Sims Reaction Diffusion Tutorial](https://www.karlsims.com/rd.html)
- [gpu-io Reaction Diffusion](https://apps.amandaghassaei.com/gpu-io/examples/reaction-diffusion/)
- [Biological Modeling - Turing Patterns](https://biologicalmodeling.org/prologue/reaction-diffusion)

### Vascular Network / Circulatory Flow

Medical visualization of blood flow uses 1D hemodynamic models overlaid on 3D vascular geometry, with color-coded flow velocity, pressure, and wall shear stress. VasNetMR (ACM SIGGRAPH 2024) enables interactive mixed-reality exploration of whole-body vascular flow distribution.

- **Best at showing**: Flow rate, pressure, bottlenecks, distribution across a branching network
- **Real-time/ambient**: 1D models run on laptops in minutes; reduced-order models enable real-time
- **WebGL/canvas**: 3D rendering requires WebGL; 2D schematic versions straightforward
- **Key insight for Hapax**: The 5 circulatory systems map directly to a vascular metaphor. Flow width = throughput, color = health, pulsing = activity. Bottlenecks become visually obvious as constrictions

Sources:
- [3D Vascular Network Visualization Platform (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC11047578/)
- [VasNetMR (ACM)](https://dl.acm.org/doi/10.1145/3703619.3706031)
- [Vascular Network Modeling in Brain Tissue (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10643724/)

### Neural Activation Maps

Brain activity heatmaps use color intensity mapped to neural firing rates across anatomical regions. UCSF's seizure propagation visualization uses "line length" algorithms on EEG traces, converting them to color intensity on a 3D brain model -- showing how activity moves in space and time.

- **Best at showing**: Which regions are active, propagation patterns, intensity gradients
- **Real-time/ambient**: Yes, EEG-based systems run in real-time
- **WebGL/canvas**: brainglobe-heatmap renders in 2D (matplotlib) and 3D (brainrender); browser versions feasible
- **Key insight for Hapax**: Map agent activation to regions on a spatial layout. Color intensity = activity level. Show cascade effects as activation spreads through reactive engine rules

Sources:
- [3D Seizure Heatmap (UCSF)](https://www.ucsf.edu/news/2021/07/421156/3-d-heat-map-animation-shows-how-seizures-spread-brains-patients-epilepsy)
- [brainglobe-heatmap](https://brainglobe.info/documentation/brainglobe-heatmap/index.html)

### Metabolic Pathway Animation

Pathway Tools (BioCyc) overlays transcriptomics, metabolomics, and flux data onto organism-scale metabolic maps, producing animated zoomable displays. GEM-Vis handles time-course data on large-scale networks. Users step through timepoints or play as continuous animation.

- **Best at showing**: Transformation chains, flux rates, bottlenecks in processing pipelines
- **Real-time/ambient**: Designed for analysis but animation capability exists
- **WebGL/canvas**: d3flux provides browser-based pathway visualization
- **Key insight for Hapax**: The reactive engine's rule chains are metabolic pathways. Data enters, gets transformed through agent stages, exits as actions. Animate the flow of work items through the pipeline

Sources:
- [Pathway Tools Visualization (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC7911265/)
- [GEM-Vis Time-Series Metabolomic Data (BMC)](https://bmcbioinformatics.biomedcentral.com/articles/10.1186/s12859-020-3415-z)
- [CAVE Cloud Platform (Oxford Academic)](https://academic.oup.com/nar/article/51/W1/W70/7157517)

### Physarum (Slime Mold) Simulation

Physarum polycephalum simulation: agents leave chemical trails, sense trail concentrations, move toward strongest trails. Simple rules produce complex organic network structures that find efficient paths. Multiple WebGL implementations run entirely on GPU via fragment shaders.

- **Best at showing**: Network formation, path optimization, organic connectivity, self-organization
- **Real-time/ambient**: Yes. GPU implementations handle 1M+ agents at 60fps
- **WebGL/canvas**: Multiple mature implementations (nicoptere/physarum, Bewelge/Physarum-WebGL, gpu-io)
- **Key insight for Hapax**: Agent-to-agent communication paths could self-organize visually using Physarum dynamics. Strong communication channels become thick trails; unused paths fade. The network topology emerges from actual system behavior

Sources:
- [Physarum WebGL (hayden.gg)](https://hayden.gg/physarum/)
- [gpu-io Physarum](https://apps.amandaghassaei.com/gpu-io/examples/physarum/)
- [Fast Physarum Simulation WebGL2](https://maximilianklein.github.io/showcase/physarum/)
- [Physarum Implementation Details](https://jbaker.graphics/writings/physarum.html)

---

## 2. Network Flow Visualization

### Animated Particle Flow (Netflix Vizceral)

Netflix built Vizceral to understand microservice architecture state at a glance during traffic failovers. WebGL canvas renders animated dots flowing between nodes, with particle count proportional to traffic volume (sampled, not 1:1). Three zoom levels: inter-region, inter-service, single-service focus. Color encodes packet type/health.

- **Best at showing**: Relative flow volume, connection health, system topology
- **Real-time/ambient**: Designed for exactly this. Glanceable operational awareness
- **WebGL/canvas**: Yes, native WebGL. React and Web Component wrappers available
- **Key insight for Hapax**: This is the closest existing precedent to what Hapax needs. Vizceral's philosophy -- "relative information is much more actionable than exact numbers" -- aligns perfectly with ambient display. The three-level zoom (global/cluster/node) maps to Hapax's tier structure

Sources:
- [Netflix Vizceral (GitHub)](https://github.com/Netflix/vizceral)
- [Vizceral Open Source (Netflix TechBlog)](https://netflixtechblog.com/vizceral-open-source-acc0c32113fe)
- [sFlow Real-Time Vizceral](https://blog.sflow.com/2017/09/real-time-traffic-visualization-using.html)

### Flow Network Components

flow-network is a React component for animated workflow visualization, originally for large-scale workflow systems, repurposed for Apache Kafka and RabbitMQ message bus visualization. Particles flow along directed edges.

- **Best at showing**: Message flow, queue depth, processing rates
- **Real-time/ambient**: Yes, designed for real-time monitoring
- **WebGL/canvas**: WebGL with React integration

Sources:
- [flow-network (GitHub)](https://github.com/joewood/flow-network)

### ccNetViz

Lightweight WebGL library for large network graphs where edges can be animated with a priori velocities to show relative rates of information flow. Handles networks with hundreds of thousands of nodes.

- **Best at showing**: Large-scale network topology with flow rates
- **Real-time/ambient**: Yes, designed for interactive exploration
- **WebGL/canvas**: Native WebGL

Sources:
- [ccNetViz (Oxford Academic)](https://academic.oup.com/bioinformatics/article/36/16/4527/5855130)
- [ccNetViz Demo](https://helikarlab.github.io/ccNetViz/)

### Sankey / Alluvial Diagrams

Sankey diagrams show flow between categories with link width proportional to quantity. Alluvial diagrams add temporal steps. Flourish provides animated versions where flows animate from source to target.

- **Best at showing**: Distribution, transformation, where resources go
- **Real-time/ambient**: Traditionally static analysis tools. Animated versions exist but are better for transitions than continuous display
- **WebGL/canvas**: D3.js implementations widely available
- **Key insight for Hapax**: Useful for showing data transformation through the reactive engine pipeline, but too structured for ambient display. Better as a detail-on-demand view than the primary ambient field

Sources:
- [Flourish Animated Sankey](https://flourish.studio/blog/animating-sankey-visualisations/)
- [Sankey Diagram (data-to-viz)](https://www.data-to-viz.com/graph/sankey.html)

---

## 3. Ambient Information Displays

### Pousman-Stasko Taxonomy (Foundational)

The canonical taxonomy of ambient information systems identifies four design dimensions:
1. **Information Capacity** -- how much data the display encodes
2. **Notification Level** -- how aggressively it demands attention (change blindness → interruption)
3. **Representational Fidelity** -- abstract/indexical vs. literal/iconic
4. **Aesthetic Emphasis** -- decorative vs. informative priority

Four design patterns emerge: symbolic sculptural displays, multiple-information consolidators, information monitor panels, and high-throughput textual displays.

- **Key insight for Hapax**: Hapax's visual field should be a "multiple-information consolidator" with high information capacity, low notification level (peripheral), low-to-medium representational fidelity (abstract/organic rather than literal charts), and high aesthetic emphasis. This is the InfoCanvas pattern

Sources:
- [Taxonomy of Ambient Information Systems (Pousman & Stasko, AVI 2006)](https://faculty.cc.gatech.edu/~stasko/papers/avi06.pdf)
- [Semantic Scholar](https://www.semanticscholar.org/paper/A-taxonomy-of-ambient-information-systems:-four-of-Pousman-Stasko/c289b3bd951450c17b01aa85e10d61746dc5d6a6)

### Ambient Orb / Ambient Devices

The Ambient Orb (2002) encodes a single scalar value as color on a frosted glass sphere. Green/amber/red for stock market direction. Simplicity is the point: pre-attentive processing of color, no cognitive load.

- **Best at showing**: Single scalar health/direction indicator
- **Real-time/ambient**: Designed for exactly this
- **Key insight for Hapax**: The Orb is the minimum viable ambient display. Hapax needs much higher information capacity, but the principle holds: encode system state in properties that are pre-attentively processed (color, motion, texture) rather than requiring reading

Sources:
- [Ambient Devices (Wikipedia)](https://en.wikipedia.org/wiki/Ambient_device)

### InfoCanvas

Users compose personalized ambient scenes where data values map to visual properties of scene elements (sun position = time, cloud density = email volume, tree health = stock portfolio). Art-like scenes that encode multiple data streams.

- **Best at showing**: Multiple data streams simultaneously via metaphorical encoding
- **Real-time/ambient**: Designed for continuous peripheral display
- **WebGL/canvas**: Originally Java; concept easily implemented in canvas/WebGL
- **Key insight for Hapax**: The scene-composition approach -- where visual elements have dual meaning as both aesthetic objects and data encodings -- is powerful. A "landscape" that IS the system state rather than representing it

Sources:
- [InfoCanvas (ResearchGate)](https://www.researchgate.net/publication/228397324_The_InfoCanvas_Information_conveyance_through_personalized_expressive_art)
- [InfoCanvas at AVI (ACM)](https://dl.acm.org/doi/10.1145/1556262.1556268)

### Ambient Analytics (2025 Research)

Recent work extends calm technology into immersive environments via AR, progressing from visual analytics to "ambient analytics." Visualizations reside in the attentional periphery, integrated with the environment, minimizing cognitive load. Continuous exposure over extended periods rather than focused analytical sessions.

- **Best at showing**: Complex multi-dimensional data as environmental texture
- **Real-time/ambient**: Core design goal
- **Key insight for Hapax**: The shift from "visualization you look at" to "environment you inhabit" is exactly Hapax's trajectory. The visual field IS the room's information atmosphere

Sources:
- [Ambient Analytics (arXiv)](https://arxiv.org/html/2602.19809v1)
- [Calm Technology Principles](https://calmtech.com/)

---

## 4. State Machine Visualization

### Statecharts (Harel, 1987)

Harel's statecharts extend flat state machines with three innovations: hierarchy (nested states), concurrency (parallel regions), and communication (broadcast events). Small diagrams express complex behavior. The visual formalism itself is compact -- zooming reveals detail.

- **Best at showing**: Current state within a hierarchical system, concurrent subsystem states, transition paths
- **Real-time/ambient**: XState Visualizer highlights active states in real-time
- **WebGL/canvas**: SVG-based; could be rendered on canvas
- **Key insight for Hapax**: The 5-state machine (perception/regulation/temporal/visual/experiential) with nested agent states maps directly to hierarchical statecharts. Active state highlighting gives instant system-mode awareness

Sources:
- [Statecharts: A Visual Formalism (Harel, 1987)](https://www.sciencedirect.com/science/article/pii/0167642387900359)
- [statecharts.dev](https://statecharts.dev/)
- [XState Visualizer](https://stately.ai/viz)

### State as Visual Regime

Rather than drawing state diagrams, represent state through visual regime changes: the entire visual field shifts character when the system changes state. A "perception-heavy" state looks different from a "self-regulation" state -- different color palette, different motion dynamics, different texture.

- **Key insight for Hapax**: Don't visualize the state machine as a diagram. Let the state machine drive the visual vocabulary selection. Each state has a visual signature. Transitions are gradual morphs between signatures

---

## 5. Temporal Visualization

### Horizon Charts

Fold area charts into colored bands to show multiple time series in minimal vertical space. Deeper/darker colors = higher values. Invented by Saito et al. (2005). Excellent for showing dozens of parallel time series.

- **Best at showing**: Trends, anomalies, relative patterns across many parallel series
- **Real-time/ambient**: Can scroll/update in real-time
- **WebGL/canvas**: Observable Plot has native horizon chart support; D3.js implementations exist
- **Key insight for Hapax**: Could show agent activity histories as stacked horizon bands -- but this is dashboard thinking, not ambient. Better as a detail view

Sources:
- [Horizon Chart (Wikipedia)](https://en.wikipedia.org/wiki/Horizon_chart)
- [Observable Plot Horizon Chart](https://observablehq.com/@observablehq/plot-horizon)

### Trail Effects / Motion Blur as History

In animation and generative art, trails and motion blur show temporal thickness: where something was, not just where it is. Particle trails naturally encode velocity and direction. Fade rate encodes how far back history reaches.

- **Best at showing**: Velocity, direction, recent history, momentum
- **Real-time/ambient**: Native to real-time rendering (just don't clear the framebuffer fully)
- **WebGL/canvas**: Trivial in WebGL -- multiply previous frame by decay factor before drawing new frame
- **Key insight for Hapax**: This is the primary ambient temporal technique. Every visual element should leave trails proportional to its rate of change. Fast-changing elements have long trails (high activity). Stable elements appear solid (no trail). The visual field itself encodes temporal thickness without any explicit time axis

### Temporal Layering

The concept of showing past/present/future simultaneously. Ghosted previous states behind current state. Predicted states ahead with decreasing opacity. The visual field becomes a temporal window rather than a snapshot.

- **Best at showing**: Trajectory, momentum, predicted direction
- **Real-time/ambient**: Yes, with appropriate decay/prediction
- **Key insight for Hapax**: Combine with reaction-diffusion or particle systems. The chemical trail IS the past. The current particle positions ARE the present. The flow field direction IS the predicted future. No separate temporal display needed -- time is embedded in the visual physics

---

## 6. Adaptive / Generative Visualization

### Draco: Constraint-Based Visualization Recommendation

Draco (UW Interactive Data Lab) formalizes visualization design knowledge as logical constraints in Answer Set Programming. Given data properties and a partial specification, Draco's constraint solver finds optimal visualizations from the Vega-Lite grammar space. Weights learned from perceptual experiments.

- **Best at showing**: Automated selection of appropriate visual encodings for given data
- **Real-time/ambient**: The constraint solving is fast; selection could happen in real-time
- **WebGL/canvas**: Output is Vega-Lite specs, renderable in browsers
- **Key insight for Hapax**: A system that selects its own visual representation based on what it needs to express. When perception is dominant, choose flow visualization. When self-regulation is active, choose pulsing/breathing. The grammar of graphics becomes a selection space for self-expression

Sources:
- [Draco 2 (UW IDL)](https://idl.cs.washington.edu/files/2023-Draco2-VIS.pdf)
- [Draco GitHub](https://github.com/uwdata/draco)
- [DracoGPT (arXiv)](https://arxiv.org/pdf/2408.06845)
- [Draco Knowledge Base Visual Analytics](https://arxiv.org/pdf/2307.12866)

### Grammar of Graphics as Selection Space

Wilkinson's Grammar of Graphics decomposes visualization into orthogonal components: data, aesthetics, geometry, statistics, coordinates, facets. Vega-Lite implements this as a declarative JSON grammar. The system could maintain a vocabulary of visual "words" (mark types, encoding channels, scales) and compose them based on current state.

- **Key insight for Hapax**: Define a visual grammar specific to Hapax's domain: {particle-flow, reaction-diffusion, voronoi-cells, trail-decay, pulse-breathing, color-field} as mark types, mapped to system properties. The visual field is a sentence in this grammar, rewritten as system state changes

Sources:
- [Vega-Lite](https://vega.github.io/vega-lite/)
- [Generative AI for Visualization (ScienceDirect)](https://www.sciencedirect.com/science/article/pii/S2468502X24000160)
- [Visualization Recommendation Survey](https://www.sciencedirect.com/science/article/pii/S2468502X20300292)

### Autopoietic Self-Representation

Autopoiesis (Maturana & Varela, 1972): a system that produces and maintains itself. An autopoietic visualization would be one where the system's visual representation is itself a product of the system's operation -- not an external observer's chart, but the system's own self-produced visible surface.

- **Key insight for Hapax**: The visual layer is not a dashboard ABOUT the system. It IS the system making itself visible. The reaction-diffusion patterns are not metaphors for system state -- they ARE system state, expressed in a visual medium. The system doesn't have a visualization; it has a skin

Sources:
- [Autopoiesis (Wikipedia)](https://en.wikipedia.org/wiki/Autopoiesis)

---

## 7. Boundary Visualization

### Voronoi Tessellation for Dynamic Boundaries

GPU-accelerated Voronoi tessellation creates organic cellular boundaries that shift as seed points move. Jump Flooding Algorithm runs at 60fps for 65K+ seeds at 1024x1024. Cell boundaries form naturally from proximity relationships.

- **Best at showing**: Territory, influence, proximity relationships, organic partitioning
- **Real-time/ambient**: Yes, GPU-native at high framerates
- **WebGL/canvas**: Multiple implementations; The Book of Shaders covers Worley/cellular noise
- **Key insight for Hapax**: Agent territories as Voronoi cells. Cell size = agent's current scope of influence. Cell color = agent state. Boundaries emerge from the agents' positions in a conceptual space, not drawn explicitly. As agents become more/less active, their cells grow/shrink organically

Sources:
- [GPU Voronoi (nickmcd.me)](https://nickmcd.me/2020/08/01/gpu-accelerated-voronoi/)
- [The Book of Shaders - Cellular Noise](https://thebookofshaders.com/12/)
- [Jump Flooding Algorithm (comp.nus.edu.sg)](https://www.comp.nus.edu.sg/~tants/cvt.html)

### Gradient Boundaries / Membrane Metaphors

Scalar field visualization uses color gradients where boundaries are regions of high gradient magnitude (rapid change) rather than sharp lines. Edge detection in scalar fields identifies material boundaries where gradient magnitude is large; interior regions produce smooth fields.

- **Best at showing**: Fuzzy boundaries, transition zones, permeability
- **Real-time/ambient**: Standard shader technique
- **WebGL/canvas**: Fragment shader with gradient computation
- **Key insight for Hapax**: The system boundary is not a line. It's a gradient from "fully inside the system" (agents, local state) through "partially inside" (API calls in flight, sensor data arriving) to "fully outside" (the external world). Render this as a luminance/color gradient that pulses with data flow across the boundary. Osmotic metaphor: data flowing inward increases "pressure" on one side, visible as brightness/density

Sources:
- [Gradient Vector Flow (Wikipedia)](https://en.wikipedia.org/wiki/Gradient_Vector_Flow)
- [Fuzzy Systems Visualization (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/S0167739X04000512)

---

## Synthesis: A Visual Vocabulary for Hapax Self-Representation

### Technique Selection Matrix

| Technique | Shows | Ambient? | GPU/WebGL? | Hapax Application |
|-----------|-------|----------|------------|-------------------|
| Reaction-diffusion | Health, regime, emergence | Yes | Yes (fragment shader) | Background field reflecting system health parameters |
| Physarum trails | Connectivity, path optimization | Yes | Yes (compute/fragment) | Agent communication network self-organizing |
| Particle flow (Vizceral-style) | Flow rate, volume, direction | Yes | Yes (WebGL) | Data flowing through circulatory systems |
| Voronoi cells | Territory, influence, boundaries | Yes | Yes (JFA shader) | Agent scope/influence regions |
| Neural activation heatmap | Activity intensity, propagation | Yes | Yes (texture overlay) | Agent activation levels across the system |
| Trail decay / motion blur | Temporal thickness, velocity | Yes | Yes (framebuffer feedback) | History embedded in visual physics |
| Gradient boundaries | Fuzzy edges, permeability | Yes | Yes (fragment shader) | System/environment boundary |
| Color field / Stimmung | Mood, overall state | Yes | Yes (uniform colors) | Global system attunement |

### Architectural Recommendation

**Layer 1 -- Ground Field**: Reaction-diffusion or Perlin noise field driven by aggregate system health metrics. This is the "Stimmung" layer -- the background mood. Parameters map to Gray-Scott feed/kill rates or noise octave weights. Healthy system = stable organic patterns. Distressed system = pattern collapse or turbulence.

**Layer 2 -- Flow Network**: Particle flow along edges connecting the 5 circulatory systems and their constituent agents. Width = throughput, speed = latency (inverse), color = data type. This is the Vizceral layer, but with organic rather than geometric routing (use Physarum-style path optimization instead of straight lines).

**Layer 3 -- Agent Field**: Voronoi tessellation where each agent is a seed point. Cell size = current scope of activity. Cell interior color/texture = agent state. Cell boundaries pulse with inter-agent communication. Active agents glow; dormant agents dim.

**Layer 4 -- Temporal Skin**: Framebuffer feedback with configurable decay. Everything leaves trails. Fast activity = long visible trails. Stability = clean sharp forms. The visual field naturally accumulates temporal thickness without any explicit time axis.

**Layer 5 -- Boundary Membrane**: Gradient field at the system edge showing data flowing in (sensor input, API responses) and out (notifications, file writes, visual output). Brightness = flow rate. The membrane breathes with system I/O.

### Key Design Principles (from the research)

1. **Pre-attentive processing over reading**: Encode in color, motion, texture, size -- never in text or numbers for the ambient field
2. **Relative over absolute**: Vizceral's insight -- when tracking many things, relative differences matter more than exact values
3. **Emergent over designed**: Let visual structure emerge from system dynamics (Physarum, reaction-diffusion) rather than pre-designing layouts
4. **Temporal embedding over time axes**: History lives in trails and decay, not in chart axes
5. **State as visual regime**: System mode changes the entire visual vocabulary, not just a highlighted state in a diagram
6. **Autopoietic surface**: The visualization is not about the system; it IS the system's visible surface. The system produces its own appearance as a byproduct of operation

### Implementation Path

All recommended techniques are implementable in WebGL fragment/vertex shaders:
- Reaction-diffusion: ping-pong framebuffer with Gray-Scott compute
- Physarum: agent positions in texture, trail map as separate framebuffer
- Particle flow: vertex shader with transform feedback (WebGL2) or texture-encoded positions
- Voronoi: Jump Flooding Algorithm in fragment shader
- Trail decay: multiply previous frame by decay factor before compositing new frame
- Gradient boundary: distance field computed from system topology

Total GPU cost is manageable on integrated graphics. Each layer is a separate render pass composited via alpha blending.
