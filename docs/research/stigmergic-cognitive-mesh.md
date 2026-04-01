# The Stigmergic Cognitive Mesh: Formalizing a Distributed Perceptual System

**Date:** 2026-03-31
**Status:** Active research
**Depends on:** [Phenomenology-AI Research](phenomenology-ai-perception-research.md), [Hapax Ontology](hapax-ontology-and-visual-fitment.md), [Exposition Level 1](../superpowers/exposition/level-1-what-is-this.md)

---

## Abstract

This document formalizes the cognitive/perceptual layer of the Hapax system as a distributed system in its own right — not a "layer" atop conventional infrastructure, but a distinct system class with its own coordination semantics, consistency model, failure modes, and health metrics. We introduce the term *stigmergic cognitive mesh* (SCM) to name this class and provide a formal characterization that distinguishes it from conventional distributed systems, cognitive architectures, and ambient intelligence platforms. The formalization serves five purposes simultaneously: verification of temporal properties, design guidance for architectural evolution, communication of the system's nature to external audiences, measurement of perceptual health, and a theoretical contribution regarding consent as a distributed system property.

---

## 1. Definition

### 1.1 The System Class

A **stigmergic cognitive mesh** is a distributed system in which:

1. **Stigmergic coordination.** Processes coordinate through environmental trace deposition and reading rather than directed message passing. A process writes a structured trace to a shared medium; other processes read that trace at their own cadence. There is no request, no response, no handshake, and no requirement that the writer know who will read. The shared medium is the sole coordination substrate.

2. **Heterogeneous temporal scales.** Processes operate at independently determined cadences with no global clock and no synchronization protocol. A 3-second perception process and a 22-second rendering process coexist without either adapting to the other's rate. Each process samples the shared medium at its own update frequency, observing a held value between the writer's updates.

3. **Emergent perceptual state.** The system has no single source of truth. Its state at any instant is the superposition of all traces currently deposited in the shared medium — a vector of independently updated dimensions with no coordinating transaction. No process holds the complete state; each observes a projection determined by which traces it reads.

4. **Perceptual control.** Processes control their perceptions, not their outputs. Each process maintains an implicit reference signal (what it expects to perceive) and acts to minimize the discrepancy between that reference and its actual perceptual input. A "failure" in this system is not a crashed process but a sustained discrepancy between reference and perception — a miscalibrated sensor, a stale signal treated as fresh, a prediction error that is not resolved.

5. **Consent as propagating constraint.** Data governance is not a boundary check but a system-wide property with propagation dynamics. Consent state changes must reach all processes that handle governed data, subject to the same heterogeneous-cadence propagation as any other signal. The consent constraint is analogous to consistency in distributed databases: it has levels (strong, eventual, causal), partition behavior (fail-closed), and staleness semantics.

6. **Observer-system circularity.** The operator is both the system's environment and a component of the system. The system's output (visual surface, voice, notifications) changes the operator's behavior, which changes the system's sensory input, which changes the system's output. This circularity is constitutive, not incidental — the system cannot be understood as an external tool acting on a passive user.

### 1.2 What an SCM Is Not

The definition gains precision by contrast with existing system classes.

**Not an actor system.** In the actor model (Hewitt, 1973), computation is triggered by directed messages between named actors. In an SCM, computation is triggered by reading environmental traces deposited by unnamed writers. An actor knows its recipients; an SCM process knows only its environment. The coordination topology is implicit in who reads what, not explicit in message routing.

**Not a microservice architecture.** Microservices coordinate through synchronous RPC or asynchronous message queues with delivery guarantees. An SCM has no delivery guarantees — a trace deposited in the shared medium may never be read if no process happens to look. There is no broker, no queue, no at-least-once semantics. The medium is passive; readers are active.

**Not a conventional cognitive architecture.** SOAR, ACT-R, and CLARION operate on a globally clocked cognitive cycle. An SCM has no global cycle. Processes are temporally independent and causally coupled only through the shared medium. The closest cognitive architecture is LIDA (Franklin et al.), whose asynchronous codelets parallel SCM processes, but LIDA still assumes a Global Workspace with serial broadcast — a centralized mechanism absent from an SCM.

**Not an ambient intelligence system.** Smart home platforms coordinate heterogeneous devices for utilitarian goals (comfort, energy efficiency, security). An SCM coordinates heterogeneous processes for perceptual self-maintenance — maintaining a coherent perceptual field for a single operator, not optimizing measurable objectives. The success criterion is not "did the system achieve the goal?" but "is the system perceiving accurately?"

**Not a digital twin.** A digital twin synchronizes a virtual model with a physical entity through bidirectional data threads. An SCM is not a model of the operator — it is an extension of the operator's cognitive process (Clark & Chalmers, 1998). The relationship is not representation but constitution: the system's Qdrant collections are external memory, its stimmung signal is external mood regulation, its agent network is external deliberation.

### 1.3 Positioning in the Literature

The SCM sits at the intersection of three established research traditions:

**Stigmergy** (Grassé, 1959; Theraulaz & Bonabeau, 1999) provides the coordination mechanism. Originally describing indirect coordination in termite colonies through pheromone traces, stigmergy has been formalized for multi-agent software systems (Fernandez-Marquez et al., 2013) and applied to swarm robotics and self-organizing systems. The SCM extends stigmergic coordination to cognitive processes with heterogeneous timescales — a combination not previously formalized. Traditional stigmergy assumes homogeneous agents depositing the same type of trace; the SCM involves heterogeneous agents depositing typed traces (stimmung dimensions, perception signals, imagination fragments) with different decay semantics.

**Perceptual Control Theory** (Powers, 1973) provides the control structure. PCT models organisms as hierarchical negative-feedback controllers that control perceptions, not outputs. The SCM applies this to a distributed system: each process controls a different perceptual variable, and the hierarchy emerges from the trace-reading dependencies rather than from explicit architectural layering. PCT has been applied to robotic control and organizational behavior, but not to distributed software systems operating as cognitive infrastructure.

**Autopoiesis** (Maturana & Varela, 1980) provides the self-maintenance frame. An autopoietic system continuously produces and maintains itself by creating its own components. The SCM's 24/7 recovery chain (kernel panic auto-reboot → hardware watchdog → display manager autologin → systemd lingering → service restart) is an autopoietic closure: the system produces the conditions for its own continued operation. The cognitive mesh adds a further autopoietic property: the system's perceptual processing produces the traces that coordinate its own perceptual processing.

**Active Inference** (Friston, 2010) provides the unifying dynamical principle. Each SCM process can be modeled as an active inference agent maintaining a generative model and minimizing prediction error. The stimmung signal functions as the system's empirical prior — the background expectation that biases all perception. The impingement event stream functions as the surprise signal — prediction errors that trigger belief updating across the mesh. Multi-timescale hierarchical processing is native to hierarchical active inference, making it the most natural dynamical framework for the SCM's heterogeneous cadences.

The **Viable System Model** (Beer, 1972) provides organizational structure. The SCM maps onto VSM's five subsystems with striking precision, as detailed in Section 2.

The **consent lattice** (see §5 and the exposition documents) extends information flow control (Myers & Liskov, 2000; Stefan et al., 2011) to distributed system propagation semantics — a combination that appears novel in the literature.

### 1.4 The Reference Implementation

The Hapax system is a concrete SCM comprising 14 cognitive processes, 5 transport layers, and 5 constitutional axioms operating on a single workstation with a Raspberry Pi edge fleet. The formalization in this document is derived from and grounded in this implementation, but stated in terms general enough to characterize the system class rather than the specific instance. Where implementation details illuminate the formalism, they are cited with code paths. The full ontological classification of the reference implementation — organs, flows, and boundary crossings — is documented in [Hapax Ontology & Visual Representational Fitment](hapax-ontology-and-visual-fitment.md).

---

## 2. Structure

### 2.1 Viable System Model Mapping

Stafford Beer's Viable System Model (1972) identifies five subsystems necessary for any system to maintain viability — the capacity for independent existence. The SCM maps onto these subsystems as follows.

**System 1 — Operations.** The 14 cognitive mesh components, each a viable unit with its own cadence, state, and failure recovery. In VSM terms, each S1 unit has operational autonomy: it reads traces, processes them according to its own logic, and deposits new traces, without requiring permission or synchronization from any coordinator.

| S1 Unit | Cadence | Controlled Perception | Trace Deposited |
|---------|---------|----------------------|-----------------|
| IR Perception | 3s | Operator spatial presence | `/dev/shm/hapax-sensors/ir_presence.json` |
| Contact Mic | continuous | Surface acoustic activity | perception-state signal |
| Voice Daemon | continuous | Conversational engagement | perception-state, OBS commands |
| DMN | 1s loop, 5s imagination | Cognitive background activity | `/dev/shm/hapax-imagination/current.json` |
| Imagination Resolver | event-driven | Content availability | `/dev/shm/hapax-imagination/content/active/slots.json` |
| Stimmung Sync | 15m | System self-assessment | `/dev/shm/hapax-stimmung/state.json` |
| Temporal Bonds | on-demand | Temporal coherence | TemporalBands (in-process) |
| Apperception | event-driven | Self-referential awareness | `/dev/shm/hapax-apperception/self-band.json` |
| Reactive Engine | inotify | Filesystem event response | Agent triggers, file writes |
| Studio Compositor | real-time | Camera composition | `/dev/video42` (v4l2loopback) |
| Visual Surface (Reverie) | real-time/30fps | Expressive visual field | `/dev/shm/hapax-visual/frame.jpg` |
| Voice Pipeline | continuous | Voice interaction state | Audio output, routing state |
| Content Engine | ~5s | Imagination fragment production | `/dev/shm/hapax-imagination/current.json` |
| Consent Engine | continuous | Consent coverage | Consent state, audit trail |

**System 2 — Coordination.** Anti-oscillation and conflict damping. In the SCM, S2 is the stimmung signal combined with the staleness threshold mechanism.

Stimmung functions as a coordination signal by providing a shared assessment of system state that all S1 units can read. When stimmung reports "degraded," resource-intensive operations (Phase 2 LLM calls, high-cadence imagination) voluntarily reduce their activity. This is not command-and-control — no S1 unit is ordered to reduce activity. Instead, each unit reads the stimmung trace and adjusts its own behavior according to its own logic. The coordination is stigmergic: mediated by the shared environment, not by directed communication.

Staleness thresholds provide damping. Each S1 unit defines a staleness threshold for each trace it reads. When a trace exceeds its threshold, the reader treats it as absent rather than stale — preventing old data from propagating through the system as if it were current. This is the SCM equivalent of pheromone evaporation in biological stigmergy: traces decay, and the decay rate is a design parameter.

**System 3 — Control.** Resource allocation and audit. In the SCM, S3 comprises the health monitor, VRAM watchdog, and reactive engine phase gating.

The health monitor reads all S1 units' state and reports aggregate health via the Logos API. The VRAM watchdog prevents GPU memory exhaustion by monitoring allocation across GPU-bound services (DMN, Reverie, Compositor, voice daemon). The reactive engine's 11 rules execute in phase order (8 deterministic Phase 0 rules before 3 GPU-bound Phase 1 rules before 3 cloud-LLM Phase 2 rules) with concurrency bounds (semaphore at max 2 concurrent cloud LLM calls).

S3 differs from S2 in that it has authority to intervene: the VRAM watchdog can kill processes; the phase gate can block rule execution. S2 (stimmung) only informs; S3 acts.

**System 4 — Intelligence.** Environmental scanning and adaptation. In the SCM, S4 comprises the scout agent, apperception self-model, and DMN imagination.

The scout agent scans external sources (technology landscape, tool ecosystem) for opportunities and threats relevant to the system's evolution. Apperception synthesizes a self-referential awareness signal from prediction errors, corrections, and cross-modal resonance — the system's capacity to observe itself. The DMN generates imagination fragments that are not responses to stimuli but spontaneous cognitive activity — the system's capacity for free association and anticipation.

S4 is where the SCM most diverges from conventional distributed systems, which have no equivalent of imagination or self-awareness. These labels are operationally grounded — the DMN produces structured fragments with measurable salience and material properties; apperception produces a coherence metric from 7 classified event sources — but whether they constitute "imagination" and "self-awareness" in any philosophically robust sense is a separate question addressed in the [Phenomenology-AI Research](../research/phenomenology-ai-perception-research.md).

**System 5 — Policy.** Identity and normative closure. In the SCM, S5 is the Hapax Constitution: 5 axioms, the consent lattice algebra, and the SDLC enforcement pipeline.

S5 defines what the system IS — a single-operator cognitive environment with specific ethical commitments. It constrains all other subsystems: S1 units cannot store data about non-operator persons without active consent contracts (interpersonal transparency axiom); S3 cannot allocate resources to multi-user features (single-user axiom); S4 cannot recommend management actions that involve generating evaluative language about individuals (management governance axiom).

The recursive property of VSM applies: the voice daemon (an S1 unit of the mesh) contains its own S1-S5 internally. Its 25 perception backends are S1 operations; its resource arbiter is S2 coordination; its executor is S3 control; its salience routing is S4 intelligence; its governance chains are S5 policy. This recursive viability means the voice daemon could, in principle, operate independently — and indeed it does during periods when other mesh components are unavailable.

### 2.2 Compositional Structure

The SCM has a compositional structure amenable to operadic description (Spivak, 2013). Each S1 unit is an **open system** with:

- **Inputs:** A set of typed trace readings (e.g., stimmung dimensions, IR perception signals)
- **Outputs:** A set of typed trace deposits (e.g., imagination fragments, perception state)
- **Parameters:** Configuration that shapes processing (e.g., staleness thresholds, cadence, model selection)

The shared medium (`/dev/shm` files, Qdrant collections, impingement JSONL) provides the **boundary objects** through which open systems compose. Two systems compose when one's output type matches another's input type at a shared boundary object.

**Composition rule:** The composition of systems A and B through shared boundary object X produces a composite system whose behavior is:
1. A deposits traces to X at A's cadence
2. B reads traces from X at B's cadence
3. B's behavior is influenced by A's traces, but not determined by them — B also reads other traces, applies its own logic, and deposits its own outputs

This is weaker than functional composition (where output determines input) and stronger than mere coexistence (where systems share no state). It is **stigmergic composition**: influence mediated by environment.

The **locality property** holds: adding or removing a component requires changes only to components that share boundary objects with it. A new perception backend can be added by writing traces to the appropriate `/dev/shm` path; no existing component requires modification. This property is not architectural aspiration — it is enforced by the stigmergic coordination pattern, which precludes direct inter-component coupling.

### 2.3 Transport Taxonomy

The SCM's transport mechanisms differ in coupling, ordering, and failure semantics:

| Transport | Formal Character | Coupling | Ordering | Failure Mode |
|-----------|-----------------|----------|----------|--------------|
| `/dev/shm` atomic JSON | Stigmergic trace | Write-read, no handshake | Last-writer-wins | Staleness (reader detects age) |
| Impingement JSONL | Causal event stream | Append-only, cursor-tracked | Causal (append order) | Cursor loss (reader re-reads from tail) |
| HTTP POST (Pi fleet) | Remote sensing | Request-response | Per-request | Timeout → staleness |
| UDS socket | Direct channel | Bidirectional, persistent | Stream-ordered | Connection loss → reconnect |
| Hardware I/O | Physical coupling | Device-mediated | Real-time | Device failure → signal absence |

The dominant transport is stigmergic trace (`/dev/shm` atomic JSON). The trace lifecycle is:

1. **Deposit:** Writer creates `{path}.tmp`, writes JSON, renames atomically to `{path}`. Kernel rename guarantees readers never see partial writes.
2. **Persist:** Trace exists as a file with a modification timestamp. Any process can read it at any time.
3. **Decay:** No explicit decay mechanism. Instead, readers compute `freshness_s = now - mtime` and compare against their configured `stale_threshold`.
4. **Expire:** When `freshness_s > stale_threshold`, the reader treats the trace as absent and invokes its fallback behavior (component-specific: apperception triggers "absence" source; stimmung reads health as critical; VLA drops the signal from fusion).

The impingement JSONL transport has different semantics: it is append-only and causally ordered. Each impingement carries a type (STATISTICAL_DEVIATION, PATTERN_MATCH, SALIENCE_INTEGRATION, ABSOLUTE_THRESHOLD) and a strength (0.0–1.0). Readers maintain a cursor (byte offset) and read only new entries. This provides causal ordering without synchronization — a reader always processes impingements in the order they were deposited, but may process them at any delay.

---

## 3. Dynamics

### 3.1 Active Inference Frame

Each SCM process can be modeled as an active inference agent (Friston, 2010) that maintains a generative model of its perceptual domain and acts to minimize variational free energy — the discrepancy between its model's predictions and its actual sensory input.

**Generative model.** Each process has an implicit generative model encoded in its processing logic. The IR perception backend's model predicts that when the operator is present, person detections will arrive from at least one Pi within the staleness window. The stimmung collector's model predicts that system health dimensions will remain within nominal bounds. The DMN's model predicts that recent observations will form coherent narratives amenable to imagination.

**Prediction error.** When sensory input diverges from the generative model's predictions, the process experiences prediction error. In the SCM, prediction error manifests as:
- **Impingements** (explicit): STATISTICAL_DEVIATION type impingements are literally surprise signals — a sensor value that deviates from the running average
- **Staleness** (implicit): A trace that should have been refreshed but wasn't is a negative prediction error — the expected signal failed to arrive
- **Apperception surprise** (computed): The temporal bonds module explicitly computes a surprise field by comparing protention (prediction) with impression (actuality)

**Prior.** The stimmung signal functions as the system's empirical prior — a background expectation that biases all processing. When stimmung is "nominal," processes operate with default sensitivity. When stimmung is "degraded," the prior shifts: processes expect more failures, reduce resource consumption, and lower salience thresholds. The stimmung prior is not centrally imposed; each process reads the stimmung trace and incorporates it into its own generative model according to its own weighting scheme.

**Action.** Active inference agents minimize free energy through two routes: updating beliefs (perception) or changing the world (action). SCM processes do both:
- **Perceptual inference:** Adjusting internal state to better explain sensory input (e.g., stimmung recomputing stance from fresh dimension readings)
- **Active inference:** Changing the environment to match predictions (e.g., voice daemon adjusting OBS scenes to match the expected visual state; imagination resolver fetching content to fill empty slots)

**Hierarchical organization.** Active inference naturally supports hierarchical processing with different timescales at each level (Friston, 2008). In the SCM:
- **Fast processes** (IR perception at 3s, contact mic continuous) update low-level sensory predictions
- **Medium processes** (DMN at 5s, stimmung at 15m) update mid-level contextual predictions
- **Slow processes** (visual surface at variable cadence, pattern consolidator daily) update high-level abstract predictions

Each level's predictions become the priors for the level below. IR perception's person detection becomes part of the context that shapes stimmung's self-assessment, which becomes the prior that shapes all other processes' behavior. This hierarchical influence propagation arises from the trace-reading dependencies — the causal structure is designed (someone decided which processes read which traces), but the hierarchical dynamics are a consequence of those design choices rather than an explicitly engineered hierarchy.

**Free energy of the mesh.** The aggregate free energy of the SCM is the sum of all processes' prediction errors, weighted by their perceptual significance. This provides a scalar health metric (see §4.3): low aggregate free energy indicates a well-calibrated mesh where all processes' models align with reality; high aggregate free energy indicates surprise — the mesh is encountering conditions its models do not predict.

### 3.2 Stigmergic Dynamics

The coordination dynamics of the SCM are formally stigmergic: processes coordinate indirectly through modification of the shared environment.

**Trace dynamics.** In biological stigmergy (ant pheromone trails), traces have continuous decay dynamics: pheromone concentration decreases exponentially over time, and reinforcement occurs when multiple agents deposit on the same path. The SCM's digital stigmergy differs in that traces do not continuously decay — they are either fresh or stale, a binary determined by the reader's staleness threshold. However, the functional equivalence holds:

| Biological Stigmergy | SCM Digital Stigmergy |
|----------------------|----------------------|
| Pheromone deposition | Atomic JSON write to `/dev/shm` |
| Pheromone concentration | Signal value (dimension reading, perception confidence) |
| Evaporation rate | Staleness threshold (per-reader, per-trace) |
| Trail reinforcement | High-cadence writer maintaining fresh traces |
| Trail extinction | Writer stops updating → trace expires → readers invoke fallback |
| Multi-pheromone | Multi-file: different trace types in different paths |

**Interference patterns.** When multiple processes deposit traces that a single reader combines, the combination follows component-specific fusion rules — not simple aggregation:

- **IR perception fusion:** Three Pis write independently. The fusion backend applies role-based priority: person detection = `any()` across Pis (disjunction); gaze/biometrics = desk Pi preferred (priority); hand activity = overhead Pi preferred (priority). This is a weighted priority fusion, not averaging.
- **Stimmung fusion:** 10 dimensions aggregated into stance via worst-non-stale rule: `overall_stance = worst(d for d in dimensions if d.freshness_s < stale_threshold)`. This is a pessimistic fusion — any single degraded dimension makes the whole system cautious.
- **Apperception fusion:** 7 event sources with transmuting internalization update rule: new observations are dampened by confidence and anti-inflation factor before integrating into self-dimensions. This is an adaptive fusion with built-in stability.

These fusion rules are the SCM's equivalent of nonlinear pheromone interaction in biological systems — the behavior of the composite cannot be predicted from the behavior of individual traces.

**Self-organization.** The SCM exhibits self-organizing behavior characteristic of stigmergic systems:

- **Positive feedback:** When the operator is actively engaged (high IR presence, high audio energy), high-salience imagination fragments are produced, which trigger more DMN activity, which produces more fragments. The system becomes more cognitively active in response to operator engagement.
- **Negative feedback:** When stimmung degrades, processes reduce their activity, which reduces resource pressure, which allows stimmung to recover. The system self-regulates toward homeostasis.
- **Fluctuation amplification:** A surprise signal (unexpected impingement) can cascade through the mesh, triggering apperception events, stimmung reassessment, and imagination redirection. A single unexpected observation can reorganize the system's cognitive state.

### 3.3 Temporal Verification

The SCM's heterogeneous timescales create verification challenges not addressed by standard temporal logic, which assumes a single global clock or synchronized local clocks. Multi-clock temporal logic provides the formal framework for expressing and verifying such properties.

**Local clocks.** Each S1 unit defines a local clock with its own tick rate:

```
Clock_IR       = 3s
Clock_DMN      = 1s (main loop), 5s (imagination)
Clock_Stimmung = 15min (sync), real-time (API reads)
Clock_Visual   = continuous (30fps fetch from Logos)
Clock_Apperception = event-driven (7 trigger sources)
```

**Cross-clock properties.** The following temporal properties are expressible and verifiable across these clocks:

**P1. Bounded propagation.** *An IR perception update is reflected in the voice daemon's perception state within one voice daemon perception cycle.* Formally: if IR perception deposits a trace at time t on Clock_IR, the voice daemon reads that trace before time t + Clock_Daimonion_FAST (where Clock_Daimonion_FAST is the FAST-tier perception backend update cadence, typically < 1s). This holds because the voice daemon reads IR traces on every FAST perception tick.

**P2. Consent freshness.** *A consent state change reaches all gated components within the maximum component cadence.* The worst-case propagation bound is max(cadences of all consent-gated components). Currently: max(voice daemon continuous, studio compositor real-time) ≈ immediate, because both gated components read consent state on every activation. The consent propagation is fast relative to the mesh's other signals.

**P3. Staleness safety.** *No component acts on data older than its configured staleness threshold.* This is a local safety invariant: each component checks `freshness_s < stale_threshold` before using a trace value. Violation means a bug in the component's reading logic, not a systemic failure. Verifiable by inspection of each component's trace-reading code.

**P4. Imagination liveness.** *If the DMN is active and at least one perception backend is producing fresh data, the imagination loop produces a new fragment within its configured cadence.* This is a conditional liveness property: under specified preconditions (DMN running, perception available), the system makes progress. The condition excludes cases where the DMN is deliberately idle (TPN active gate set) or where all perception is stale (no input to imagine about).

**P5. Stimmung convergence.** *After a perturbation (service restart, sensor failure), stimmung converges to a stable stance within one stimmung sync cycle.* This is a bounded convergence property. It holds because stimmung dimensions are computed from current readings (not accumulated history), so a transient failure resolves as soon as the next fresh reading arrives and the sync timer fires.

These properties are not aspirational — they are checkable against the codebase and, in several cases, observable in the system's runtime behavior through the health monitor and Langfuse traces.

---

## 4. Health Metrics

### 4.1 Perceptual Control Error

Perceptual Control Theory (Powers, 1973) provides a framework for health metrics that captures something conventional monitoring misses: whether the system is perceiving what it intends to perceive.

For each S1 unit, we identify:
- **Controlled perception:** The perceptual variable the process works to maintain at a reference value
- **Reference signal:** The expected value of that perception under normal conditions
- **Error signal:** The discrepancy between reference and current perception

| Component | Controlled Perception | Reference | Error Signal |
|-----------|----------------------|-----------|-------------|
| IR Perception | Operator presence signal | Continuous detection when present | False absence or false presence |
| Stimmung | System stance | Nominal | Deviation toward degraded/critical |
| Voice Daemon | Conversational coherence | Appropriate response latency, turn management | Latency spikes, missed utterances |
| DMN | Cognitive background activity | Regular imagination production | Fragment production stalls, empty buffers |
| Consent Engine | Consent coverage | 100% coverage of non-operator data | Unconsented data in pipeline |
| Apperception | Self-referential coherence | Stable self-dimensions with bounded variance | Coherence below floor (0.15 threshold) |
| Visual Surface | Expressive fidelity | Continuous frame production, responsive to stimmung | Frame drops, stale uniforms, parameter desynchronization |

**Aggregate control error** is the weighted sum of individual error signals:

```
E_mesh = Σ_i (w_i × |perception_i - reference_i|)
```

where weights `w_i` reflect the perceptual significance of each component (stimmung and consent are weighted highest because they propagate to all other components).

This metric reframes "is the system healthy?" as "is the system perceiving what it expects to perceive?" A system can be operationally healthy (all processes running, all containers up) while having high perceptual control error (stimmung miscalibrated, IR perception producing false detections, consent state stale). The PCT metric captures the latter; conventional monitoring captures the former. Both are necessary; neither is sufficient.

### 4.2 Integration Metric

Integrated Information Theory (Tononi, 2004) proposes that consciousness corresponds to integrated information (Φ) — information generated by a system above and beyond its parts. We do not claim a formal connection to IIT's phi, which is computationally intractable and designed for neural systems. However, the underlying question — "is this system genuinely integrated or merely aggregated?" — motivates a pragmatic metric: **integration depth**.

**Definition.** The integration depth of a component C is the number of non-adjacent components whose behavior measurably changes when C is removed or disabled.

- **Depth 0:** Only C's direct consumers are affected (mere aggregation)
- **Depth 1:** C's consumers' consumers are affected (one-hop integration)
- **Depth ≥ 2:** Effects propagate through the mesh beyond immediate neighbors (deep integration)

**Example.** Disabling the stimmung collector:
- Direct consumers (depth 0): health monitor loses stance, voice daemon loses system prior
- Indirect effect (depth 1): voice daemon's changed behavior affects OBS scene selection, which affects studio compositor's input
- Cascading effect (depth 2): compositor's changed output affects the visual feed, which is consumed by the visual surface, which affects the DMN's evaluative tick (it reads rendered frames)

Stimmung has high integration depth because it functions as the system prior — it shapes all other processes' behavior. Removing it doesn't just remove data; it removes the background against which all perception occurs.

**The test.** A mesh where all components have integration depth 0 is merely a bag of independent agents sharing a filesystem. A mesh where key components have integration depth ≥ 2 is genuinely integrated — its behavior cannot be decomposed into the behaviors of its parts. This distinction matters for design: new components should increase integration depth (contributing to the mesh's coherence) rather than merely coexisting.

### 4.3 Free Energy as Health Scalar

Active Inference (§3.1) provides a scalar health metric: the aggregate variational free energy of the mesh.

**Definition.** The free energy of the mesh at time t is:

```
F(t) = Σ_i surprise_i(t)
```

where `surprise_i(t)` is the prediction error of component i at time t — the degree to which its sensory input diverges from its generative model's predictions.

**Operationalization.** In the reference implementation, surprise is observable through:
- **Impingement rate:** High impingement rate = high surprise (many signals deviating from expectations)
- **Staleness count:** Many stale traces = many missing predictions (expected signals not arriving)
- **Apperception prediction error:** The temporal bonds surprise field explicitly computes prediction error
- **Stimmung deviation:** Distance from nominal stance = magnitude of systemic surprise

**Interpretation.** Free energy provides a qualitatively different signal from uptime or accuracy:

- **Low F(t):** The mesh's models align with reality. All components are perceiving what they expect. The system is well-calibrated to its environment. This is the homeostatic target.
- **High F(t), transient:** Something unexpected happened — a new stimulus, a sensor failure, an operator behavior change. The mesh will adapt (update its models) and F(t) will decrease. This is normal adaptive behavior.
- **High F(t), sustained:** The mesh's models are systematically wrong. The system is not adapting to its environment. This indicates a fundamental miscalibration requiring intervention — not a restart, but a model update.

The free energy scalar subsumes both operational health (a crashed service causes high surprise in its consumers) and perceptual health (a miscalibrated sensor causes high surprise in its fusion targets). It is the single most informative health metric for an SCM.

---

## 5. Consent as a Distributed System Property

### 5.1 The Existing Foundation

The Hapax system already possesses a rigorous consent algebra, documented in the [exposition documents](../superpowers/exposition/level-1-what-is-this.md). The key elements:

- **Consent labels** (from DLM, Myers & Liskov, 2000): Data carries a `ConsentLabel` specifying which persons' data is present and who has permission to process it
- **Consent lattice:** Labels form a join-semilattice under set union. When data streams are fused, the output carries the join of all input labels — consent requirements accumulate, never diminish
- **Floating labels** (from LIO, Stefan et al., 2011): As a computation observes higher-consent data, its own label floats upward, preventing laundering — once you've seen Alice's data, you can't write to a place that doesn't have Alice's consent
- **Algebraic proofs:** Commutativity, associativity, idempotence, and the flow relation's partial order are verified by hypothesis-based property tests

This foundation addresses the **data plane**: how consent labels propagate through transformations. What it does not address is the **control plane**: how consent *state changes* propagate through a distributed system with heterogeneous timescales.

### 5.2 Consent Consistency

In distributed databases, consistency defines the agreement guarantees among replicas. We apply this concept to consent:

**Strong consent consistency.** All components immediately reflect consent state changes. A consent revocation at time t is visible to all components at time t. This requires synchronization — either a global lock or a distributed consensus protocol — and would block processing during propagation. No SCM implements this, nor should one: the blocking cost is disproportionate, and the protection it provides (zero-latency revocation) is achievable through fail-closed defaults.

**Eventual consent consistency.** Consent state changes propagate through the trace bus. Components read consent state at their own cadence and eventually converge to the new state. Between the change and convergence, some components may operate under stale consent — processing data under a revoked contract. This is the current Hapax implementation.

**Causal consent consistency.** If component A's processing caused a consent state change (e.g., speaker identification triggered a new consent check), all components causally downstream of A see the new consent state before processing data that depends on A's output. This is stronger than eventual (it prevents specific stale-consent scenarios where downstream processing depends on the very data that triggered the consent change) and weaker than strong (it doesn't require global synchronization).

The **appropriate consistency level** depends on the latency of consent-relevant events. For the Hapax reference implementation, eventual consistency is acceptable because:
1. Consent changes are infrequent (contract activation/revocation happens at human timescales — minutes, not seconds)
2. Components handling governed data (voice pipeline, studio compositor) are continuous daemons, so any consent check would have near-zero propagation delay. (Note: the reference implementation currently logs consent events for audit rather than enforcing runtime gates — the formalism here describes the target architecture.)
3. The consent lattice's monotonic join property governs the *data plane*: data labels only float up through processing. However, this does not protect against stale *authorization state* on the control plane. A revocation (removing permission) makes the effective authorization more restrictive, but a component reading stale pre-revocation state would operate under the old, more-permissive grant — the opposite of safe. The data-plane monotonicity does not save the control plane. The actual safety guarantee comes from points 1 and 2: infrequent changes and near-zero propagation delay in continuous daemons

However, the formalism identifies a scenario where eventual consistency is insufficient: **consent revocation during active data flow.** If Alice revokes consent while her voice data is being processed through the pipeline, eventual consistency means some pipeline stages may still process her data under the revoked contract. Causal consent consistency would prevent this by ensuring that the revocation propagates causally through the pipeline before the data does.

### 5.3 Consent Propagation Dynamics

Consent state changes propagate through the SCM via the same stigmergic mechanism as all other signals:

1. **Deposit:** Consent engine writes updated state to its canonical path
2. **Propagation:** Gated components read consent state at their own cadence
3. **Enforcement:** Each gated component checks consent before processing governed data

**Propagation bound.** The worst-case delay between a consent state change and its enforcement across all gated components is:

```
T_consent = max(cadence_i for i in gated_components)
```

In the reference implementation, all consent-gated components are continuous daemons that check consent on every activation, so T_consent ≈ 0. But the formalism reveals that adding a batch-scheduled gated component with a long cadence would increase T_consent correspondingly — a design constraint that should be enforced architecturally.

**Partition behavior.** If the consent engine is unavailable (process crash, file corruption), gated components should fail closed — block all processing of governed data until consent state is available. This is the correct partition behavior: when the consent authority is unreachable, the safe default is denial. This parallels the fail-closed behavior of conventional authorization systems during authentication service outages.

**Consent staleness.** If the consent state file's modification time exceeds a staleness threshold, gated components should treat consent as revoked. This prevents a scenario where the consent engine crashes, its last-written state remains on disk indefinitely, and gated components continue operating under a frozen consent snapshot that may no longer reflect the operator's intent. The staleness threshold should be shorter than the consent engine's expected restart time.

### 5.4 The Novel Contribution

The combination of information flow control algebra (data plane) with distributed system propagation semantics (control plane) for consent management appears novel in the literature.

**Prior work in IFC** (Myers & Liskov, 2000; Stefan et al., 2011; Hedin & Sabelfeld, 2012) provides rigorous label algebras for tracking information flow through computations. This work assumes a single runtime or a tightly coupled distributed system with coordinated clocks. It does not address propagation delays in asynchronous, heterogeneous-cadence systems.

**Prior work in consent management** (Fatema et al., 2017; Rantos et al., 2019) provides formal models for GDPR compliance with dynamic consent states. This work treats consent as a static grant checked at a point in time, not as a distributed system property with propagation dynamics, consistency levels, and partition behavior.

**The SCM contribution** bridges these two bodies of work:
1. IFC provides the data-plane algebra (consent labels, lattice operations, floating labels)
2. Distributed systems theory provides the control-plane semantics (consistency levels, propagation bounds, partition behavior, staleness)
3. The combination yields a consent model that is both algebraically rigorous (provable label properties) and operationally realistic (bounded propagation, fail-closed partitions, staleness safety)

This combination is motivated by a concrete engineering need — the reference implementation must actually enforce consent across 14 asynchronous processes with heterogeneous cadences — but the formalization is general enough to apply to any system where data governance must propagate through a distributed processing pipeline without centralized synchronization.

---

## 6. Related Work and Open Questions

### 6.1 Adjacent Frameworks

Several frameworks partially address SCM concerns but were developed for different contexts:

**Global Workspace Theory** (Baars, 1988) provides a broadcast architecture that resembles the SCM's trace bus, but assumes synchronous serial broadcast. The SCM's asynchronous, multi-trace coordination is more general.

**Extended Mind Thesis** (Clark & Chalmers, 1998) provides philosophical grounding for treating the SCM as part of the operator's cognitive process, not an external tool. This framing is philosophically important but does not provide engineering formalism.

**4E Cognition** (Varela, Thompson, & Rosch, 1991) — embodied, embedded, enacted, extended — describes the theoretical commitments that motivate the SCM's design: the system is embodied (sensor array), embedded (in the operator's environment), enacted (actively engaged with the world through actuation), and extended (constitutive of the operator's cognitive process). See [Phenomenology-AI Research](phenomenology-ai-perception-research.md) for detailed mapping.

**Reaction-diffusion systems** provide mathematical models for signal propagation and pattern formation that could formalize the SCM's trace interference patterns. The SCM's discrete-process, discrete-trace architecture differs from continuous reaction-diffusion, but the qualitative dynamics (positive feedback, negative feedback, fluctuation amplification) are isomorphic.

### 6.2 Limitations of This Document

**Partial component coverage.** The S1 inventory (§2.1) lists 14 components, but the dynamics (§3) and health (§4) sections analyze only the 7 most interconnected. Contact Mic, Imagination Resolver, Reactive Engine, Studio Compositor, Voice Pipeline, Content Engine, and Temporal Bonds receive structural description but not dynamical or health-metric treatment. This reflects the document's focus on the mesh's coordination properties rather than exhaustive component analysis, but a complete formalization would extend to all 14.

**Observer-system circularity unformalized.** Property 6 (§1.1) asserts that operator-system circularity is constitutive, but sections 2–5 analyze the system as if the operator were external. Formalizing circularity would require modeling the operator's behavioral responses to system outputs and their effect on system inputs — a feedback loop that crosses the boundary between computational and psychological domains. This remains the deepest open problem in the formalization.

**Emergent state underspecified.** Property 3 (§1.1) defines emergent perceptual state as "the superposition of all traces," but no section formalizes what superposition means operationally — how it would be computed, what its properties are, or how it differs from a simple snapshot of all `/dev/shm` files. The fusion rules in §3.2 are component-specific; a general theory of emergent state in stigmergic systems is needed.

**Health metrics not yet instrumented.** The metrics in §4 are theoretical constructs grounded in available data sources but not yet computed by the reference implementation. Aggregate control error (§4.1) requires quantifying reference signals for all components, some of which are context-dependent. Integration depth (§4.2) requires ablation experiments. Free energy (§4.3) has identified proxies but no aggregation formula. These metrics are design targets, not operational tools — yet.

**Active Inference framing.** The AIF terminology in §3.1 provides useful vocabulary (prediction error, empirical prior, free energy) but much of the analytical content could be equivalently stated in PCT or cybernetic terms. The AIF framing is most valuable in §4.3 (free energy as health scalar) and least valuable in §3.1's component-level descriptions, where it relabels staleness checks as "negative prediction errors" without adding analytical power. A future revision may tighten the AIF contributions to where they genuinely exceed what PCT provides.

**Consent gating architecture.** The reference implementation currently audits consent events rather than enforcing runtime gates on component execution (§5.2–5.3). The formalism describes the target architecture. The gap between audit and enforcement is itself a research and engineering problem.

### 6.3 Open Questions

**Q1. Formal verification.** The temporal properties in §3.3 are currently verified informally (code inspection, runtime observation). Can they be formalized in a multi-clock temporal logic and verified automatically? This would require extracting a formal model from the codebase — a significant but valuable effort.

**Q2. Optimal staleness thresholds.** Each component's staleness threshold is currently set by engineering judgment. Can Active Inference provide a principled method for setting thresholds — e.g., the threshold that minimizes expected free energy given the component's generative model and the writer's cadence?

**Q3. Integration depth measurement.** The integration metric (§4.2) requires controlled experiments — disabling components and measuring effects. Can integration depth be estimated from the trace-reading dependency graph without runtime experiments?

**Q4. Consent latency bounds.** The current consent propagation bound is T_consent ≈ 0 because all gated components are continuous. If batch-scheduled gated components are added, what is the acceptable upper bound on T_consent? This is both an engineering question (what delay is tolerable?) and an ethical question (what delay violates the spirit of consent?). The existing consent latency obligation principle documents that voice latency impeding consent flow is a governance violation, not a UX issue — this principle should generalize to all consent propagation.

**Q5. Causal consent consistency.** Is causal consent consistency achievable in the SCM without adding explicit causal tracking (vector clocks, causal histories)? The impingement JSONL already provides causal ordering within its stream — can this be extended to consent propagation?

**Q6. Multi-SCM composition.** If the Hapax system is one SCM and a second SCM (e.g., Officium) shares infrastructure but has its own cognitive mesh, how do the two SCMs compose? Do they share a stimmung prior, or does each maintain its own? The operadic framework (§2.2) suggests they compose through shared boundary objects, but the dynamics of multi-SCM interaction are unexamined.

---

## References

Baars, B.J. (1988). *A Cognitive Theory of Consciousness*. Cambridge University Press.

Beer, S. (1972). *Brain of the Firm*. Allen Lane.

Bérard, B. et al. "Specification and Verification of Multi-Clock Systems." (Citation needs verification — included as representative of the multi-clock temporal logic literature.)

Clark, A. & Chalmers, D. (1998). "The Extended Mind." *Analysis*, 58(1), 7–19.


Fernandez-Marquez, J.L. et al. (2013). "Self-Managing and Self-Organising Mobile Computing Applications: A Separation of Concerns Approach." *33rd IEEE ICDCSW*.

Franklin, S. et al. (2016). "LIDA: A Systems-level Architecture for Cognition, Emotion, and Learning." *IEEE Transactions on Autonomous Mental Development*, 8(1), 19–30.

Friston, K. (2010). "The free-energy principle: a unified brain theory?" *Nature Reviews Neuroscience*, 11(2), 127–138.

Grassé, P.-P. (1959). "La reconstruction du nid et les coordinations interindividuelles chez *Bellicositermes natalensis* et *Cubitermes* sp." *Insectes Sociaux*, 6(1), 41–80.

Hedin, D. & Sabelfeld, A. (2012). "A Perspective on Information-Flow Control." *Software Safety and Security*, 319–347.

Hewitt, C. (1973). "A Universal Modular ACTOR Formalism for Artificial Intelligence." *IJCAI*.

Maturana, H. & Varela, F. (1980). *Autopoiesis and Cognition: The Realization of the Living*. D. Reidel.

Myers, A.C. & Liskov, B. (2000). "Protecting Privacy using the Decentralized Label Model." *ACM Transactions on Software Engineering and Methodology*, 9(4), 410–442.

Powers, W.T. (1973). *Behavior: The Control of Perception*. Aldine.

Spivak, D.I. (2013). "The operad of wiring diagrams: formalizing a graphical language for databases, recursion, and plug-and-play circuits." arXiv:1305.0297.

Stefan, D. et al. (2011). "Flexible Dynamic Information Flow Control in Haskell." *Haskell Symposium*, 95–106.

Theraulaz, G. & Bonabeau, E. (1999). "A brief history of stigmergy." *Artificial Life*, 5(2), 97–116.

Tononi, G. (2004). "An information integration theory of consciousness." *BMC Neuroscience*, 5, 42.

Varela, F., Thompson, E. & Rosch, E. (1991). *The Embodied Mind: Cognitive Science and Human Experience*. MIT Press.
