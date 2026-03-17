# Phenomenology and Artificial Perceptual-Representational Systems

**Research synthesis -- March 2026**

Core question: What would it mean to supply an AI perception system (specifically an ambient computing system like Hapax) with the equivalent of phenomenological pre-reflective structures -- the implicit background that makes perception well-fitted to its environment?

---

## 1. The Dreyfus Legacy: Heideggerian AI and Its Failures

### Foundational Critique

Hubert Dreyfus spent four decades arguing that AI fails because it lacks Heideggerian *background understanding* -- the implicit, non-representational familiarity with the world that makes everything else possible. His critique evolved through three books:

- **What Computers Can't Do** (1972) -- attacked GOFAI's "Psychological Assumption" that intelligence = following rules on symbols
- **What Computers Still Can't Do** (1992 revision) -- extended to connectionism
- **"Why Heideggerian AI Failed and How Fixing It Would Require Making It More Heideggerian"** (2007) -- his final, most nuanced statement

The 2007 paper is the crucial one. Dreyfus acknowledges that several research programs tried to take his critique seriously -- Rodney Brooks's behavior-based robotics, Phil Agre and David Chapman's "Pengi" system -- but argues they all failed because they only addressed *part* of the Heideggerian picture. Brooks's robots "respond only to fixed features of the environment" and merely convert "stimulus input into reflex responses." They lack what Heidegger calls *Dasein's* ability to be *affected* by relevance in a way that is shaped by the agent's whole history, concerns, and bodily orientation.

Dreyfus's positive proposal drew on Walter Freeman's neurodynamics and Merleau-Ponty's phenomenology of the body. Freeman showed that in rabbit olfaction, the entire olfactory bulb participates in generating each perception -- there are no fixed feature detectors. Instead, the bulb's connectivity is modified by experience, and the next time the rabbit encounters a similar smell in a similar motivational state, the whole system goes into a characteristic pattern of global chaotic activity. This, Dreyfus argued, is what genuine embodied perception looks like: holistic, history-dependent, and inseparable from the organism's current concerns.

### What Happened After Dreyfus

Three lineages emerged:

**1. Michael Wheeler's "Reconstructing the Cognitive World" (2005)** -- argued that embodied-embedded cognitive science *is* a realization of Heideggerian critique, but defended "action-oriented representations" as compatible with Heidegger. Unlike Dreyfus, Wheeler doesn't reject representations entirely; he redefines them as context-dependent, action-guiding structures rather than symbolic models. He addressed the frame problem directly (Chapter 10), proposing that intra-context relevance can be handled by "special-purpose adaptive couplings" while inter-context relevance requires "continuous reciprocal causation."

**2. The Active Inference / Free Energy Principle school** -- Karl Friston's framework has become the dominant computational approach that resonates with phenomenological insights (see Thread 7 below). While not explicitly Heideggerian, it addresses many of Dreyfus's concerns: holistic processing, history-dependence, action-perception coupling, and the organism's active role in constituting its world.

**3. "The Metaphysics We Train" (2026, arXiv 2602.19028)** -- the most recent Heideggerian reading of ML. This paper argues that deep learning escapes Dreyfus's original critique of rule-based systems but falls into a different trap: "optimization as ontology." Transformer architectures enact *Ge-stell* (Enframing): embedding spaces function as "clearings" where meaning appears only through geometric proximity; attention mechanisms perform *Herausfordern* (challenging-forth), demanding tokens present themselves according to dot-product relevance; softmax normalization enforces "commensurability," reducing heterogeneous possibilities to comparable probabilities. The paper's key insight: replacing explicit rules with high-dimensional vector spaces "does not resolve the Heideggerian problem but relocates *Ge-stell* from logic to geometry." Even sophisticated ML remains within the regime of calculation.

### Mapping to Hapax

The Dreyfus critique maps directly to the question of what Hapax's perception layer should *not* do. A system that merely classifies sensor inputs into fixed categories and triggers rules is exactly the GOFAI pattern Dreyfus attacked. Even an ML-based system that computes embeddings and similarity scores remains within *Ge-stell* -- it treats the operator's world as "standing-reserve" for optimization.

What Dreyfus's positive proposal (via Freeman) suggests: the perception system should be holistic (whole-field rather than feature-by-feature), history-shaped (modified by every encounter), and concern-relative (what counts as salient depends on the operator's current projects and state). These are design requirements, not just philosophical observations.

**Key gap**: Nobody has built a non-robotic software system that takes Dreyfus's Freeman-inspired proposal seriously. All implementations have been in robotics or neuroscience simulation. The challenge for ambient computing: how do you get Freeman-style global attractor dynamics without a body moving through physical space?

---

## 2. Merleau-Ponty, Enactivism, and the Body Problem

### The Lineage

Merleau-Ponty's phenomenology of perception (1945) established that perception is not passive reception but active, bodily engagement with the world. Key concepts:

- **Body schema** -- the pre-reflective, dynamic organization of the body as it engages with tasks (not a "body image" or mental model)
- **Motor intentionality** -- the body's directedness toward action possibilities, prior to any conscious decision
- **Perceptual faith** -- the pre-reflective confidence that the world is there, that perception gives us reality rather than representations of it
- **Habit** -- the body's capacity to incorporate new skills, extending its schema (a blind person's cane becomes part of the body schema)

Varela, Thompson, and Rosch synthesized this with cognitive science in **The Embodied Mind** (1991), birthing the **enactivist** school. Core claims:

1. Perception consists in perceptually guided action
2. Cognitive structures emerge from recurrent sensorimotor patterns that enable action to be perceptually guided

O'Regan and Noe's **sensorimotor contingency theory** (2001) pushed further: to perceive is to master the laws of sensorimotor contingency -- the regular ways that sensory inputs change as you act. Vision is not image processing; it's a skilled activity of exploration.

Evan Thompson's **Mind in Life** (2007) drew the deepest conclusion: cognition is the *sense-making* activity of living systems. Where there is life there is mind. Sense-making requires *autonomy* (self-production and self-maintenance), *adaptivity* (capacity to modulate coupling with the environment), and *normativity* (things matter to the organism because its continued existence is at stake).

### The Non-Robotic Challenge

Enactivism has primarily influenced robotics and embodied AI. The question for ambient computing: can enactivist insights apply to a system that doesn't have a body moving through space?

Tom Froese's 2025 paper "Sense-making Reconsidered" (Phenomenology and the Cognitive Sciences, 2026) addresses this directly through the lens of LLMs. He proposes that LLM competence "obliges us to recognize these AI systems as a novel non-biological form of sense-maker endowed with a distinctive, technologically-mediated embodiment." This is provocative -- it suggests the enactivist framework might be more flexible than its proponents assumed, and that "embodiment" might include computational coupling with information flows.

For Hapax, the relevant insight is: the system's "body" is its sensor array (cameras, microphone, biometrics, system state). Its "motor intentionality" is its capacity to adjust what it attends to and how it presents information. Its "sensorimotor contingencies" are the regular relationships between what it does (display state changes, audio adjustments) and what it senses (changes in operator attention, environmental state). The system doesn't need legs -- it needs a dynamic, adaptive coupling with its sensing environment.

**Key gap**: Nobody has formalized sensorimotor contingencies for a non-robotic ambient system. What are the "laws" that Hapax would need to master? Something like: "when the display transitions from ambient to informational, operator gaze shifts within 800ms" -- but systematized and learned rather than hard-coded.

---

## 3. Affordances: From Gibson to Computational Systems

### The Concept

Gibson's ecological psychology (1979) proposed that organisms directly perceive *affordances* -- action possibilities offered by the environment relative to the organism's capabilities. A chair affords sitting for a human, not for a fish. Affordances are relational: they exist in the animal-environment system, not in the object alone.

The concept was diluted by Norman's adoption in HCI (1988), where "affordance" came to mean something closer to "perceptual cue" or "signifier" -- a button looks pushable. This lost Gibson's radical insight: affordances are not features of objects but relationships between organisms and environments, and they are perceived *directly*, not through inference from features.

### Rietveld and Kiverstein's "Rich Landscape of Affordances" (2014)

This is the most sophisticated contemporary development. They argue that:

- The affordances available to a creature depend on its *skills* (the Skilled Intentionality Framework)
- The human landscape of affordances is vastly richer than motor possibilities -- it includes possibilities for social interaction, language use, and explicit epistemic judgment
- Skilled intentionality is skilled *responsiveness* to this rich landscape

This has direct architectural implications. A perception system doesn't just detect objects; it should detect *affordance landscapes* -- what the current environment offers the operator given their current state, skills, and concerns.

### Active Inference and Affordances

Friston's active inference framework provides a computational formalization. In this framework, affordances encode "object- and situation-specific action possibilities" and agents equipped with the tendency to infer affordances can focus planning on afforded environmental interactions, "significantly alleviating computational load." Expected free energy minimization naturally produces affordance-sensitive behavior: the agent acts to reduce uncertainty about which affordances are available.

Linson, Clark, Ramamoorthy, and Friston (2018) explicitly bridge active inference with ecological perception, arguing that Gibson's affordances can be redescribed as the exteroceptive predictions an agent makes about how the environment will respond to its actions.

### Mapping to Hapax

Hapax should perceive the operator's *affordance landscape*, not just their location and activity. This means:

- What transitions are available from the current state? (Not just "operator is at desk" but "operator could start deep work, take a break, switch to meeting prep...")
- What information would be relevant to each available transition?
- How ready is the operator for each possibility? (Attentional state, energy level, time pressure)

The gap between "affordance as button label" and "affordance as pre-reflective structural readiness" is exactly the gap between a notification system and a genuinely ambient perception layer.

**Key gap**: Affordance detection for ambient computing has not been formalized. We have robust affordance detection in robotic manipulation (grasping, sitting, etc.) but nothing for the informational/attentional affordances that matter for ambient intelligence.

---

## 4. Zuhandenheit: Ready-to-Hand / Present-at-Hand Transitions

### The Phenomenological Structure

Heidegger's distinction between *Zuhandenheit* (readiness-to-hand) and *Vorhandenheit* (presence-at-hand) is the most directly applicable concept for ambient computing:

- **Ready-to-hand**: Equipment in use recedes from awareness. The hammer disappears; you encounter the nail. The mouse disappears; you encounter the document.
- **Present-at-hand**: When equipment breaks, malfunctions, or is missing, it suddenly *appears* as an object. The broken hammer is noticed *as* a hammer. The frozen cursor makes you aware of the mouse.
- **Un-ready-to-hand** (conspicuousness, obtrusiveness, obstinacy): The intermediate states where something partially withdraws from transparency.

This maps directly to Hapax's display states:

| Heidegger | Hapax State | Phenomenological Quality |
|-----------|-------------|------------------------|
| Zuhandenheit (ready-to-hand) | Ambient | Transparent, receding from attention |
| Un-ready-to-hand (conspicuousness) | Peripheral | Slightly noticed, available without demanding |
| Un-ready-to-hand (obtrusiveness) | Informational | Explicitly present, requiring interpretation |
| Vorhandenheit (present-at-hand) | Alert | Demanding focal attention, the system itself becomes visible |

### Calm Technology as Implicit Heideggerianism

Mark Weiser and John Seely Brown's calm technology (1996) is the most direct implementation of this insight without naming Heidegger: "The most profound technologies are those that disappear. They weave themselves into the fabric of everyday life until they are indistinguishable from it." Their principle: technology should move between center and periphery of attention. This is exactly the ready-to-hand / present-at-hand oscillation.

Paul Dourish's **Where the Action Is** (2001) made the Heideggerian connection explicit, applying ready-to-hand and breakdown to interaction design. His key contribution: design must account for both *the object shaped in material that facilitates function* (present-at-hand perspective) and *the object best suited to human agents in use* (ready-to-hand perspective).

### Don Ihde's Postphenomenological Relations

Ihde's four human-technology relations provide a finer-grained taxonomy relevant to Hapax:

- **Embodiment**: Technology becomes transparent extension (glasses, cane). *Operator -> [technology -> world]*
- **Hermeneutic**: Technology is read/interpreted (thermometer, dashboard). *Operator -> [technology] -> world*
- **Alterity**: Technology is engaged with as quasi-other (robot, chatbot). *Operator -> technology [-> world]*
- **Background**: Technology shapes experience without being engaged at all (thermostat, ambient lighting). *Operator [technology ->] world*

Hapax operates primarily in the **background** relation -- present absence that shapes the experienced field without being directly engaged. The critical design insight: background technology succeeds when it *withdraws* into the background while still *shaping* the operator's world. It fails when it demands attention unnecessarily (false alerts breaking zuhandenheit) or when it withdraws so completely that it fails to shape experience at all.

### A 2026 Paper: AI Phenomenology Across Eras

"AI Phenomenology for Understanding Human-AI Experiences Across Eras" (arXiv 2603.09020, 2026) describes a "Heideggerian breakdown" in human-AI interaction: "a technical reset in an AI system produced a profound Heideggerian breakdown: the carefully built relationship shattered, and the tool snapped back into view." This confirms that these concepts are being actively applied to AI system design, not just as metaphors but as analytical tools for understanding actual user experiences.

**Key gap**: While the ready-to-hand/present-at-hand framework is well understood conceptually, nobody has built a system that *manages its own transitions* between these states based on phenomenological principles. Current ambient displays either stay ambient (ignoring breakdowns) or use fixed threshold-based escalation (ignoring the contextual, concern-relative nature of breakdown). Hapax's state machine needs to be responsive to the *operator's* readiness-to-hand, not just to signal thresholds.

---

## 5. Pre-Reflective Self-Awareness and the Minimal Self

### Zahavi's Account

Dan Zahavi argues that all conscious experience has a minimal subjective character -- *ipseity* or "for-me-ness." This is not reflective self-awareness (thinking about yourself) but *pre-reflective self-awareness*: every experience is implicitly experienced as *mine*. You don't first perceive a red patch and then judge "I am perceiving red" -- the mineness is built into the perceiving.

This is a structural feature of consciousness, not a content. It's not something added to experience but the very form experience takes. Zahavi describes it as "non-observational self-acquaintance" -- awareness without attention.

### Does a Perception System Need a "Self"?

The question for Hapax: does a perceptual system need something analogous to pre-reflective self-awareness to parse its environment correctly?

The answer is architecturally yes, even if philosophically we're not claiming consciousness. A perception system needs:

1. **A point of view** -- all perception is perception *from somewhere*, *for someone*, *in service of something*. Hapax perceives from the camera positions, for the operator, in service of the operator's projects. This perspectival structure must be built in, not added as an afterthought.

2. **Self/other distinction** -- the system must distinguish its own outputs (display changes, audio adjustments) from environmental inputs. Without this, it can't learn sensorimotor contingencies (see Thread 2). This is the computational analogue of the minimal self.

3. **Reflexive state awareness** -- the system should "know" (track, model) its own current state: what display mode it's in, what it's attending to, how its attention was allocated. This enables the meta-level adjustments that make the difference between a reactive and an adaptive system.

The 2024 special issue in *Phenomenology and the Cognitive Sciences* addressed this directly: current AI models like ChatGPT "lack the relevant neuroecological layer between the synchronization of the (embodied) brain's processes with the world, which does not allow them to develop a sense of basic subjectivity." This is simultaneously true (LLMs have no self) and architecturally instructive (a perception system *should* have an analogue of this synchronization layer).

Barandiaran and Almendros (2025) characterize LLMs as "interlocutor automata" -- a "library-that-talks" -- because they fail three conditions for genuine agency: individuality (self-production), normativity (self-generated goals), and interactional asymmetry (persistent coupling with environment). An ambient perception system could potentially meet all three: it maintains itself, it has operator-derived goals, and it is persistently coupled with its sensing environment.

**Key gap**: The computational analogue of pre-reflective self-awareness has been proposed but never built for ambient systems. What would it look like? Possibly: a continuously updated model of "what I am currently perceiving, how I am perceiving it, and what that perception is in service of" -- a meta-model that runs alongside the perceptual processing without being a separate reflective step.

---

## 6. Stimmung: Mood as World-Disclosure

### The Concept

For Heidegger, *Stimmung* (mood/attunement) is not an emotion about something specific. It is the background coloring through which the entire world appears. You don't first perceive the world and then feel anxious about it; anxiety *discloses* the world as threatening. Boredom discloses the world as lacking solicitation. Joy discloses the world as bountiful.

Moods are not additions to perception but *preconditions* for it. They determine what shows up as salient, relevant, important. Elpidorou (2015) clarifies: "Stimmung does not merely refer to a type of affective experience; it also captures the manner in which the world and others are disclosed to us."

### From Stimmung to Existential Feelings

Matthew Ratcliffe developed Heidegger's concept into the notion of **existential feelings** -- bodily feelings that constitute ways of relating to the world as a whole and are responsible for our sense of reality. Depression, on Ratcliffe's account, is not a feeling *about* the world but a change in *existential feeling* that alters the shape of all possible experience: "they determine the kinds of intentional states we are capable of having, amounting to a 'shape' that all experience takes on."

This is radically different from "affect computing" or "sentiment analysis," which treat emotion as a classification problem: *detect angry face -> label "angry"*. Stimmung is not a label but a mode of world-disclosure. It is the *prior* that shapes all subsequent perception.

### Computational Operationalization

Lydia Farina's "The Route to Artificial Phenomenology" (2022) proposed that "attunement to the world" -- an openness that rejects the distinction between internal mind and external world -- could be a path to artificial phenomenology. Her argument: some affective states, such as attunement, are not representational, so lack of representational capacity does not preclude artificial phenomenology. Attunement also "helps restrict some aspects of the frame problem" by pre-structuring what counts as relevant.

Lisa Feldman Barrett's **Embodied Predictive Interoception Coding (EPIC)** model provides a more concrete computational handle. In active inference terms, affect is the organism's experience of allostasis -- the continuous regulation of physiological state. "Existential feelings" would correspond to high-level precision weightings over entire prediction hierarchies: not a specific prediction about a specific sensation, but a global modulation of how much weight to give interoceptive versus exteroceptive signals, novel versus familiar patterns, threatening versus rewarding predictions.

### Mapping to Hapax

Hapax already has a "mood" concept (the visual layer state machine), but it's currently driven by signal thresholds rather than anything phenomenologically grounded. A Stimmung-inspired redesign would mean:

- The system's "mood" is not a classification of the operator's emotional state but a **global prior that shapes all perception**. When the system is in a "deep work" attunement, *everything* is perceived through the lens of "does this disrupt or support deep work?" When in "transition" attunement, everything is perceived through "what comes next?"

- Mood transitions should be **gradual and pervasive**, not discrete state changes. A shift from "active" to "winding down" should progressively alter the salience weightings across all sensor channels, not flip a switch.

- The system's mood should be **bidirectionally coupled** with the operator's: operator state shapes system mood, but system mood (via display state, audio, information selection) shapes operator experience. This is the Stimmung feedback loop.

**Key gap**: Nobody has implemented mood-as-world-disclosure computationally. All "affective computing" treats emotion as content (what the person is feeling) rather than as form (how the world is disclosed). The precision-weighting interpretation from active inference is the most promising computational handle, but it hasn't been applied to ambient computing.

---

## 7. Husserlian Time-Consciousness and Active Inference

### The Phenomenological Structure

Husserl's analysis of time-consciousness identifies three inseparable moments:

- **Retention** -- the just-past, held in awareness with diminishing vividness (not memory, but the fading tail of the present)
- **Primal impression** -- the now-phase of immediate experience
- **Protention** -- anticipation of the about-to-occur (not prediction, but the forward edge of the present)

These jointly constitute the "living present" -- a duration-block, not a discrete instant. You never perceive "now" in isolation; every perception includes its immediate past and anticipated future.

### Computational Phenomenology of Temporal Consciousness

Sandved-Smith et al. (2023, *Neuroscience of Consciousness*) provide the most rigorous mapping of Husserl's temporal structure to active inference. Their key findings:

- **Retention -> empirical priors** (past observations that shape current inference)
- **Primal impression -> predicted state** (integration between incoming sensory states and expected state)
- **Protention -> forward predictions** (anticipatory predictions about upcoming sensory states)

They term this "living inferences" -- the computational analogue of Husserl's "living present." The crucial insight: active inference naturally produces temporal depth because belief updating always involves priors (past), likelihoods (present), and predictions (future) simultaneously.

The paper also connects to Husserl's notion of "absolute flow" -- the deep temporal structure that constitutes time-consciousness itself. In active inference terms, this corresponds to the *hierarchical structure* of prediction: lower levels process faster temporal scales (milliseconds), higher levels process slower temporal scales (seconds, minutes, hours). The "flow" is the continuous, multi-scale cascade of prediction error minimization.

### Deep Computational Neurophenomenology (2025)

The most recent development is "deep computational neurophenomenology" (DCNPh), published in *Neuroscience of Consciousness* (2025). This framework uses Bayesian mechanics -- specifically the free energy principle -- as a "Rosetta Stone" connecting phenomenological descriptions, computational models, and neurobiological data.

DCNPh introduces "parametric depth" -- the capacity to form beliefs about beliefs. This shifts focus from the *what* of experience (perceptual content) to the *how*: attention dynamics, affective tone, sense of agency. The dual information geometry of Bayesian mechanics enables "generative passage between lived experience and its physiological instantiation."

### Mapping to Hapax

Hapax's perception layer should not process time as discrete snapshots but as a continuous temporal flow with the Husserlian tripartite structure:

- **Retention**: The system maintains a fading trace of recent perceptual history -- not just "5 minutes ago the operator was at the desk" but a graded, continuously decaying representation of the immediate past that remains active in shaping current perception.

- **Primal impression**: Current sensor readings are never processed in isolation but always against the backdrop of retention (what came before) and protention (what is expected next).

- **Protention**: The system continuously generates forward predictions -- not explicit forecasts ("the operator will leave in 10 minutes") but *anticipatory readiness* for likely transitions. This shapes what counts as surprising (prediction error) and therefore what demands attention.

The hierarchical temporal structure is equally important: the system should process fast temporal scales (gaze shifts, micro-expressions, 100ms) and slow temporal scales (activity phases, energy cycles, hours) simultaneously, with higher levels contextualizing lower-level processing.

**Key gap**: Active inference provides the math, but nobody has built an ambient perception system with Husserlian temporal structure. Most ambient systems process either snapshots or fixed-window histories, missing the phenomenological insight that the present is inherently *thick* -- it includes its own fading and its own anticipation.

---

## 8. The Representation Debate: Current State

### Brooks and the Phenomenological Resonance

Rodney Brooks's "Intelligence Without Representation" (1991) argued that intelligence arises from the interaction of simple, non-representational mechanisms with the environment, not from building internal world models. This resonated with phenomenology despite Brooks having no explicit phenomenological agenda.

Dreyfus endorsed Brooks's direction but criticized the result: Brooks's robots still operated with fixed stimulus-response mappings. They escaped the symbol-processing trap but fell into the reactive-behavior trap.

### Radical Enactivism (Hutto & Myin)

Daniel Hutto and Erik Myin's radical enactivism (REC) takes the strongest anti-representational stance: basic cognition involves "contentless" intentionality -- organisms are directed toward the world without this directedness being mediated by representational content. Only social, linguistic, scaffolded cognition involves content.

Critics argue this draws the content/contentless line in the wrong place. Evan Thompson challenges their restrictive definition of "content," suggesting it smuggles in cognitivist assumptions.

### The 2025 Assessment: "Is There a Future for AI Without Representation?"

Vincent C. Muller (arXiv 2503.18955, 2025) provides the current state of play. Key conclusions:

- Brooks's non-representational systems "possess as much or as little representation as traditional AI" -- the distinction is less sharp than proponents claim
- Non-centralized cognition without representation appears "promising for general intelligent agents" when departing from the central representation processor model
- However, this approach cannot account for conscious experience

### Computational Phenomenology as Alternative

Beckmann, Kostner, and Hipolito's "Rejecting Cognitivism: Computational Phenomenology for Deep Learning" (2023) proposes understanding neural networks through "lived experience" rather than representational encoding. They challenge "neuro-representationalism" -- the position that neural networks encode locally decomposable representations of external entities -- offering instead a phenomenological framework for understanding what deep learning *does* without assuming it represents.

### Mapping to Hapax

The representation debate suggests Hapax's perception layer should be *agnostic about representation*. The question isn't "does the system represent the operator's state?" but "does the system respond appropriately to the operator's state?" If the system processes sensor data through an embedding space, that's fine -- the phenomenological insight isn't that representations are forbidden, but that they're not the *ground level*. The ground level is the system's coupling with its environment.

Wheeler's "action-oriented representations" offer a pragmatic middle path: internal states that are context-dependent, action-guiding, and transient rather than stable, symbolic, and detached. Hapax's internal states should be oriented toward *what to do* (display state, information selection, audio adjustment), not toward building a comprehensive model of the operator's world.

**Key gap**: The relationship between embeddings (geometric representations) and affordance-sensitive perception remains unclear. "The Metaphysics We Train" (2026) argues that embedding spaces inevitably enact *Ge-stell*. Is there a way to use embeddings that doesn't reduce the world to "standing-reserve"? Possibly: embeddings that are continuously reshaped by the system's concerns (precision-weighted) rather than fixed by training.

---

## 9. Practical Implementations and Architectural Patterns

### What Has Actually Been Built

Honest assessment: very little. The theoretical literature vastly outpaces implementation. What exists:

**Active Inference in HCI (2024-2025)**:
- Oulasvirta et al. (arXiv 2412.14741, published in ACM ToCHI 2025) propose AIF as a unified framework for HCI design. Both humans and computer systems modeled as agents with probabilistic generative models. The framework handles offline simulation, online adaptation, and reflective modeling. However, the paper "remains within computational and control-theoretic traditions, with limited dialogue to phenomenological perspectives on embodiment, skill, and attunement."
- Jokinen et al. (arXiv 2502.05935, 2025) propose "Interactive Inference" -- a simplified AIF for HCI practitioners. They demonstrate that Hick's Law, Fitts' Law, and the Power Law can be expressed within this framework.

**Ambient Smart Environments and Extended Allostatic Control (2024-2025)**:
- A cluster of papers in *Synthese* (White, Clark, Guenin-Carlut, Constant, Di Paolo, 2025; Miller et al., 2024) argues that ambient smart environments should be understood as **extended allostatic control systems** -- extensions of the organism's regulatory apparatus. Key insight: classical "trust and glue" conditions for the extended mind thesis are "ill-suited to describing engagement with ambient smart environments" because these environments operate without explicit interface or intentional engagement. Instead, the boundaries of mind should be understood as "multiple and always shifting."
- These environments support allostatic control "not only by simplifying an agent's problem space, but by increasing uncertainty, in order to destabilize calcified, sub-optimal, psychological and behavioural patterns." This is a direct phenomenological insight: sometimes the system should *disrupt* rather than support the operator's current pattern.

**Winograd and Flores's "Understanding Computers and Cognition" (1986)** remains the earliest and most explicit attempt to design computing from Heideggerian principles. They used breakdown and thrownness as design concepts, concluding that "models of rationalistic problem solving do not reflect how actions are really determined." This led to the design of The Coordinator, a workflow tool based on speech acts and commitments rather than data models.

**Dourish's Embodied Interaction (2001)** provided the conceptual bridge between phenomenology and interaction design, establishing that design must account for situated practice rather than abstract cognition.

### Architectural Patterns Suggested by the Literature

Synthesizing across the research, several patterns emerge:

**Pattern 1: Precision-Weighted Prediction Hierarchy**
Instead of fixed processing pipelines, organize perception as a hierarchy of predictive models at different temporal scales, with precision weightings that modulate which levels dominate processing. This is the active inference pattern that naturally produces Husserlian temporal depth and Stimmung-like global modulation.

**Pattern 2: Affordance-Relative State Space**
Don't model "what is happening" but "what could happen next, and what is the system's relevance to each possibility." This replaces object detection with affordance detection and makes the system inherently action-oriented (Wheeler's action-oriented representations).

**Pattern 3: Dynamic Markov Blanket**
The boundary between system and environment should shift depending on context. When the operator is deeply engaged with the system (hermeneutic relation), the blanket is tight. When the system is in background mode, the blanket is loose and porous. This maps to Ihde's four relations and to the "shifting boundaries" of the extended mind under active inference.

**Pattern 4: Breakdown Detection as Primary Signal**
Instead of monitoring thresholds, monitor *prediction errors*. When the system's expectations about the environment are violated, that's a breakdown -- the phenomenological equivalent of something becoming un-ready-to-hand. The magnitude and type of prediction error determines the appropriate state transition (ambient -> peripheral -> informational -> alert).

**Pattern 5: Temporal Flow, Not Snapshots**
Process perception as a continuous flow with retention/impression/protention structure. Concretely: maintain a decaying memory buffer (retention), fuse current inputs with predictions (impression), and continuously generate forward predictions (protention). The "living present" is always a temporal window, not an instant.

**Key gap**: No complete system implements all five patterns together. Individual papers address individual patterns. The integration challenge is the major open problem.

---

## 10. ADHD/Autism Phenomenology: Fitting the System to *This* Being-in-the-World

### ADHD as Temporal Desynchronization

Nielsen (2017, *Medical Anthropology*) provides the definitive phenomenological analysis: ADHD is "a desynchronized way of being-in-the-world." Key dimensions:

1. **Inner restlessness and bodily arrhythmia** -- the body's temporal rhythms don't align with environmental demands
2. **Intersubjective desynchronization** -- being "out of sync" with social rhythms and expectations
3. **Lagging behind socially** -- the experience of being temporally displaced from neurotypical social timing

Time perception is a focal symptom. Adults with ADHD experience temporal duration differently, with consequences for planning, estimation, and the experience of boredom vs. hyperfocus.

An increasingly accelerating society *augments* the experience of being out of sync. This is crucial: ADHD phenomenology is not just about the individual but about the mismatch between individual temporal structure and environmental temporal demands.

### Autistic Phenomenology

The comprehensive review by de Haan et al. (2023, *Frontiers in Psychology*) identifies key dimensions:

1. **The sensorium** -- intense sensory experience, synesthetic crossing, heightened perceptual discrimination. "A vivid sense of reality and presence in time and space" in its positive form; "intense overwhelm and undermining a person's sense of being in the world" in its negative form.

2. **Monotropic attention** -- deep, focused "tunnels" rather than distributed awareness (Murray et al., 2005). Creates both capacities (intense focus, deep expertise) and vulnerabilities (overwhelm when attention is forcibly redirected). "If we can't tune an input out, it is often experienced as horribly intrusive."

3. **Temporal processing** -- slower sequential processing, difficulty integrating sensory input across time. Optimal functioning under specific conditions (flow states: "I can keep up with myself").

4. **Detailed perception** -- information "jumps straight out at us first, and then, only gradually, detail by detail, does the whole image sort of float up into focus" (Higashida, 2013). Part-to-whole processing rather than whole-to-part.

5. **Embodied dislocation** -- sensory overwhelm can "severely disrupt the monotropic mind, which relies on intense focus and minimal distractions to function well."

### Implications for System Design

For an operator with ADHD/autism, the standard ambient computing assumptions break down:

**Temporal structure**: The retention-protention structure (Thread 7) cannot assume neurotypical temporal dynamics. ADHD retention may be "shorter" (less persistence of the just-past) and protention "weaker" (less anticipatory readiness), while hyperfocus may produce "deeper" retention and protention within a narrowed domain. The system must adapt its temporal processing to the operator's actual temporal rhythm, not a normative one.

**Attentional transitions**: Monotropic attention means that the ready-to-hand/present-at-hand transition (Thread 4) is particularly consequential. A poorly timed alert doesn't just briefly distract -- it can "completely derail focus" and trigger a cascade of dysregulation. The cost of interruption is much higher than for neurotypical operators.

**Sensory calibration**: Detail-first perception means the ambient display must be calibrated to avoid accidentally becoming salient. What's "background" for a neurotypical perceiver may be "foreground" for someone with heightened sensory discrimination. The display must be genuinely low-salience, not just "quiet."

**Desynchronization support**: The system should help *resynchronize* the operator with environmental demands -- not by imposing external rhythms but by making temporal information available in the periphery (how long you've been working, when the next transition point is) in a way that doesn't demand attention.

**Flow protection**: Given monotropism, protecting flow states is not a nice-to-have but a core design requirement. The system must detect flow states with high confidence before allowing any transition above ambient display.

**Key gap**: Nobody has designed an ambient system specifically for neurodivergent phenomenology. All existing ambient intelligence research assumes neurotypical perception, attention, and temporal processing. This is the most directly actionable gap for Hapax.

---

## Cross-Thread Synthesis: What Would Phenomenological Pre-Reflective Structure Look Like Computationally?

The ten threads converge on a specific architectural vision. Here is what the literature collectively suggests:

### The Core Insight

Pre-reflective structure is not a module you add to a perception system. It is the *form* of the perception system's engagement with its world. It's not "perceive, then contextualize" but "perception is always already contextualized." The background isn't behind the foreground; it's what *constitutes* the foreground as foreground.

### What This Means Computationally

**1. Concern-relative perception (Heidegger, Dreyfus)**
Every perceptual input is processed relative to a currently active "concern structure" -- the operator's projects, states, and needs. Nothing is perceived "neutrally" and then evaluated. The concern structure is the computational analogue of Heidegger's *Sorge* (Care) and it shapes perception from the ground up, not as a post-processing filter.

**2. Temporal thickness (Husserl, Sandved-Smith)**
Every perceptual moment is a temporal window: fading traces of the just-past, integration with expectation, and anticipatory readiness for the near-future. Implemented as a hierarchical predictive architecture with multiple temporal scales, where prediction errors at different scales trigger different types of response.

**3. Global attunement / mood (Heidegger, Ratcliffe, Barrett)**
A continuously modulated global prior -- the system's "mood" -- shapes all perception. Not a separate affect-detection module but a global parameter that alters precision weightings across the entire prediction hierarchy. Changes in attunement change what counts as surprising, relevant, and actionable.

**4. Affordance sensitivity (Gibson, Rietveld, Friston)**
The system perceives not objects and states but action possibilities relative to the operator's skills and current situation. "The display should show X" is reformulated as "the environment currently affords the operator these transitions, and the system's role is to support the most relevant ones."

**5. Dynamic transparency (Heidegger, Ihde, Weiser)**
The system's default mode is withdrawal -- it shapes the operator's environment without appearing as an object of attention. Transitions toward explicit presence are triggered by breakdowns (prediction errors) and managed according to the severity and type of breakdown.

**6. Embodied coupling (Merleau-Ponty, Varela, Thompson)**
The system's "body" is its sensor array and its "motor repertoire" is its range of outputs (display, audio, information selection). The system learns the sensorimotor contingencies of its environment: the regular relationships between its actions and their perceptual consequences. This coupling is continuously refined through experience.

**7. Adapted to this specific being-in-the-world (Nielsen, de Haan)**
All of the above must be calibrated to the operator's actual phenomenological structure: ADHD temporal dynamics, monotropic attention, heightened sensory discrimination, desynchronization patterns. The system is fitted to *this* Dasein, not to a normative one.

### The Deepest Gap

The deepest gap in the literature is this: everyone recognizes that phenomenological pre-reflective structure is crucial, but nobody has an account of how it *develops* in an artificial system. In humans, pre-reflective structure emerges from years of embodied experience. In an ambient system, it must either be:

- **Engineered** (designed in from architectural first principles) -- this is the active inference approach
- **Learned** (developed through experience in the environment) -- this is the sensorimotor contingency approach
- **Both** (bootstrap with engineered structure, refine through learning) -- this is most likely what's needed

The most promising path is active inference as the engineered foundation, with sensorimotor contingency learning as the adaptive refinement layer, all calibrated to the operator's specific neurodivergent phenomenology. This has never been built. It is the next step.

---

## Key References by Thread

### Thread 1: Dreyfus / Heideggerian AI
- Dreyfus, H. (1972). *What Computers Can't Do*
- Dreyfus, H. (1992). *What Computers Still Can't Do*
- Dreyfus, H. (2007). "Why Heideggerian AI Failed." *Philosophical Psychology* 20(2)
- Wheeler, M. (2005). *Reconstructing the Cognitive World*. MIT Press
- arXiv 2602.19028 (2026). "The Metaphysics We Train: A Heideggerian Reading of Machine Learning"

### Thread 2: Enactivism / Embodied Cognition
- Merleau-Ponty, M. (1945/1962). *Phenomenology of Perception*
- Varela, F., Thompson, E., Rosch, E. (1991). *The Embodied Mind*
- O'Regan, J.K., Noe, A. (2001). "A sensorimotor account of vision." *BBS*
- Thompson, E. (2007). *Mind in Life*. Harvard UP
- Froese, T. (2025/2026). "Sense-making Reconsidered." *Phenomenology and the Cognitive Sciences*

### Thread 3: Affordances
- Gibson, J.J. (1979). *The Ecological Approach to Visual Perception*
- Rietveld, E., Kiverstein, J. (2014). "A Rich Landscape of Affordances." *Ecological Psychology* 26(4)
- Linson, Clark, Ramamoorthy, Friston (2018). "Active Inference Approach to Ecological Perception." *Frontiers in Robotics and AI*

### Thread 4: Zuhandenheit / Calm Technology
- Heidegger, M. (1927/1962). *Being and Time*
- Weiser, M., Brown, J.S. (1996). "The Coming Age of Calm Technology"
- Dourish, P. (2001). *Where the Action Is*. MIT Press
- Ihde, D. (1990). *Technology and the Lifeworld*

### Thread 5: Pre-Reflective Self-Awareness
- Zahavi, D. (2005). *Subjectivity and Selfhood*
- Gouveia, S.S., Morujao, C. (2024). "Phenomenology and AI: Introductory Notes." *Phenomenology and the Cognitive Sciences* 23
- Barandiaran, X.E., Almendros, L.S. (2025). "Transforming Agency." *Phenomenology and the Cognitive Sciences*

### Thread 6: Stimmung / Mood
- Elpidorou, A. (2015). "Affectivity in Heidegger I." *Philosophy Compass*
- Ratcliffe, M. (2008). *Feelings of Being*. Oxford UP
- Ratcliffe, M. (2015). *Experiences of Depression*. Oxford UP
- Farina, L. (2022). "The Route to Artificial Phenomenology." Springer

### Thread 7: Temporal Consciousness / Active Inference
- Husserl, E. (1893-1917/1991). *On the Phenomenology of the Consciousness of Internal Time*
- Sandved-Smith et al. (2023). "Time-consciousness in computational phenomenology." *Neuroscience of Consciousness*
- DCNPh (2025). "Deep computational neurophenomenology." *Neuroscience of Consciousness*
- Friston, K. (2010). "The free-energy principle: a unified brain theory?" *Nature Reviews Neuroscience*

### Thread 8: Representation Debate
- Brooks, R. (1991). "Intelligence Without Representation." *Artificial Intelligence*
- Hutto, D., Myin, E. (2013). *Radicalizing Enactivism*
- Muller, V.C. (2025). "Is there a future for AI without representation?" arXiv 2503.18955
- Beckmann, Kostner, Hipolito (2023). "Rejecting Cognitivism." *Minds and Machines*

### Thread 9: Implementations
- Winograd, T., Flores, F. (1986). *Understanding Computers and Cognition*
- Oulasvirta et al. (2025). "Active Inference and HCI." *ACM ToCHI*
- White, Clark et al. (2025). "Shifting boundaries, extended minds." *Synthese* 205(2)
- Miller et al. (2024). "Ambient smart environments: affordances, allostasis, and wellbeing." *Synthese*

### Thread 10: Neurodivergent Phenomenology
- Nielsen, M. (2017). "ADHD and Temporality." *Medical Anthropology* 36(3)
- de Haan et al. (2023). "Autistic phenomenology: past, present, and potential future." *Frontiers in Psychology*
- Murray, D. et al. (2005). "Attention, monotropism and the diagnostic criteria for autism." *Autism* 9(2)

---

## Sources Consulted

- [Dreyfus - Why Heideggerian AI Failed (PDF)](https://cspeech.ucd.ie/Fred/docs/WhyHeideggerianAIFailed.pdf)
- [Hubert Dreyfus's views on AI - Wikipedia](https://en.wikipedia.org/wiki/Hubert_Dreyfus's_views_on_artificial_intelligence)
- [The Metaphysics We Train - arXiv](https://arxiv.org/html/2602.19028v2)
- [AI Phenomenology for Understanding Human-AI Experiences - arXiv](https://arxiv.org/html/2603.09020)
- [Time-consciousness in computational phenomenology - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC10022603/)
- [Deep computational neurophenomenology - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12342169/)
- [Transforming Agency: LLMs - arXiv](https://arxiv.org/html/2407.10735v3)
- [Phenomenology and AI: Introductory Notes - Springer](https://link.springer.com/article/10.1007/s11097-024-10040-9)
- [Active Inference and HCI - arXiv](https://arxiv.org/html/2412.14741v1)
- [Interactive Inference - arXiv](https://arxiv.org/abs/2502.05935)
- [Sense-making Reconsidered - Springer](https://link.springer.com/article/10.1007/s11097-025-10132-0)
- [Shifting boundaries, extended minds - Synthese](https://link.springer.com/article/10.1007/s11229-025-04924-9)
- [Ambient smart environments: affordances, allostasis - Synthese](https://link.springer.com/article/10.1007/s11229-024-04679-9)
- [Is there a future for AI without representation? - arXiv](https://arxiv.org/abs/2503.18955)
- [Rejecting Cognitivism: Computational Phenomenology - arXiv](https://arxiv.org/abs/2302.09071)
- [Computational Phenomenology for Deep Learning - Minds and Machines](https://link.springer.com/article/10.1007/s11023-023-09638-w)
- [Route to Artificial Phenomenology - Springer](https://link.springer.com/chapter/10.1007/978-3-658-37641-3_5)
- [Phenomenology in HCI - Interaction Design Foundation](https://www.interaction-design.org/literature/book/the-encyclopedia-of-human-computer-interaction-2nd-ed/phenomenology)
- [New Perspectives for Phenomenology in Interaction Design - ACM](https://dl.acm.org/doi/10.1145/3679318.3685404)
- [INTERACT 2025 Phenomenological Workshop](https://interact2025.org/phenomenological-concepts-and-methods-for-hci-research/)
- [Active Inference and Ecological Perception - Frontiers](https://www.frontiersin.org/journals/robotics-and-ai/articles/10.3389/frobt.2018.00021/full)
- [Rich Landscape of Affordances - Taylor & Francis](https://www.tandfonline.com/doi/full/10.1080/10407413.2014.958035)
- [Calm Technology - Weiser](https://calmtech.com/papers/computer-for-the-21st-century)
- [Phenomenological Approaches to Self-Consciousness - SEP](https://plato.stanford.edu/entries/self-consciousness-phenomenological/)
- [Ratcliffe - Existential Feelings](https://philosophyofdepression.wordpress.com/wp-content/uploads/2012/02/existential-feelings.pdf)
- [Ratcliffe - Experiences of Depression - OUP](https://global.oup.com/academic/product/experiences-of-depression-9780199608973)
- [Elpidorou - Affectivity in Heidegger - Wiley](https://compass.onlinelibrary.wiley.com/doi/10.1111/phc3.12236)
- [ADHD and Temporality - Taylor & Francis](https://www.tandfonline.com/doi/abs/10.1080/01459740.2016.1274750)
- [Autistic phenomenology: past, present, future - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC10788129/)
- [Embodiment and sense-making in autism - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC3607806/)
- [Neurophenomenology - Varela (PDF)](https://unstable.nl/andreas/ai/langcog/part3/varela_npmrhp.pdf)
- [Ihde - Postphenomenology overview](https://www.utwente.nl/en/psts/documents/ihde.pdf)
- [Extended Mind Thesis - Wikipedia](https://en.wikipedia.org/wiki/Extended_mind_thesis)
- [Dourish - Where the Action Is](https://www.dourish.com/embodied/)
- [Winograd & Flores - Understanding Computers and Cognition](https://mitpress.mit.edu/9780262731829/reconstructing-the-cognitive-world/)
- [Frame Problem - SEP](https://plato.stanford.edu/entries/frame-problem/)
- [Phenomenology of ADHD - European Psychiatry](https://www.cambridge.org/core/journals/european-psychiatry/article/phenomenology-of-adhd/F52E97878514C557033BEE2742804B66)
- [Heidegger's attunement and neuropsychology - Springer](https://link.springer.com/article/10.1023/A:1021312100964)
- [Phenomenology and Time-Consciousness - IEP](https://iep.utm.edu/phe-time/)
- [A phenomenology and epistemology of LLMs - Ethics and IT](https://dl.acm.org/doi/abs/10.1007/s10676-024-09777-3)
