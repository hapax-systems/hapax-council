# LLM Capabilities and Phenomenological Structure: A First-Principles Mapping

**Date**: 2026-03-16
**Status**: Exploratory research synthesis
**Sources**: 60+ papers and articles, 2022-2026, with emphasis on 2024-2025

---

## Orienting Question

How do LLM capabilities map to the *generic, transferable* structural insights of phenomenology and perceptual-representational systems research? Not "are LLMs conscious?" but: which structural requirements that phenomenology identifies for well-fitted perceptual systems do LLMs satisfy, partially satisfy, transform, or render irrelevant?

---

## Thread A: What LLMs Actually Do That Maps to Phenomenological Structures

### A1. Contextual Sensitivity / Concern-Relativity

**The phenomenological claim**: Perception is always concern-relative (Heidegger's *Sorge*). We never encounter bare data; everything shows up as mattering in some way relative to our projects and involvements. This isn't an add-on to perception — it's constitutive of how anything appears at all.

**The LLM parallel**: Every token in a transformer is processed relative to the entire context window via self-attention. The system prompt, prior conversation, and task framing shape how every subsequent input is processed. Nothing enters "bare" — everything is interpreted relative to the accumulated context.

**Strongest argument FOR the mapping**: The structural isomorphism is real. In both cases, there is no context-free processing step. A transformer cannot process a token without attending to all other tokens in the window; a Dasein cannot encounter an entity without it mattering relative to some project. The system prompt functions as a kind of pre-given concern-structure that colors all subsequent processing. Research on "Selective Self-Attention" (NeurIPS 2024) shows transformers adapt contextual sparsity of attention maps to the query embedding and its position — attention is not uniform but concern-shaped.

**Strongest argument AGAINST**: Heidegger's *Sorge* is existential — it derives from a being that has its own being as an issue for it. The LLM's "concern" is a computational artifact of architecture, not something the system cares about. The context window is finite and externally determined; human concern-structure is open-ended and self-generating. Furthermore, the LLM's context resets between conversations — there is no persistent care-structure.

**Engineering implication**: The system prompt is the most powerful lever for implementing concern-relativity. By describing what matters, what the operator's current projects are, what state the system is in — you configure a concern-structure that shapes all subsequent interpretation. This is not metaphorical; it literally changes attention weights over the input. For a perceptual system, this means the system prompt is where you encode *what the system should care about*, and this encoding functionally shapes perception.

**Open questions**: Can concern-relativity be made dynamic (updating the system prompt based on perceived state changes) without the brittleness of explicit state machines? How deep does the concern-shaping go — does it affect only surface responses, or does it reshape the internal representations the model builds?

---

### A2. Temporal Structure (Retention / Primal Impression / Protention)

**The phenomenological claim**: Husserl showed that the experienced present is never a mathematical point. Every "now" carries within it retentions of the just-past and protentions of the about-to-come. Hearing a melody requires this — each note is heard as following the previous and anticipating the next. This temporal thickness is constitutive of perceptual experience.

**The LLM parallel**: The autoregressive transformer processes sequences with full attention to prior tokens (retention) and generates the next token (protention/prediction). The current token being processed is the "primal impression." The model's internal state at any generation step carries information about all prior tokens and is oriented toward predicting the next one.

**Strongest argument FOR**: The structural parallel is surprisingly precise. Retention maps to the attention mechanism's access to all prior tokens with decaying but non-zero influence. Protention maps to next-token prediction — the model is constitutively oriented toward what comes next. The "primal impression" is the current token being integrated into the context. Research on "emergent temporal abstractions in autoregressive models" (2025) shows that these models learn to compress long activation sequence chunks, developing a kind of temporal hierarchy.

Mapping Husserlian phenomenology onto active inference (Albarracin et al., 2022) provides a computational formalization: retention as accumulated posterior beliefs, protention as expected states under preferred policies. The transformer's architecture instantiates a version of this.

**Strongest argument AGAINST**: Husserl's retention is not memory retrieval — it's a continuous modification of the living present. The transformer's attention to prior tokens is a computational lookup, not a phenomenological "just-pastness." More critically, protention in Husserl is not mere statistical prediction — it's an anticipatory orientation shaped by intention and concern. Next-token prediction is statistically optimal forecasting, not intentional anticipation.

Also: the transformer processes the entire sequence in parallel during training, and even during inference, attention to prior tokens is not temporal — it's a simultaneous computation over all positions. There is no genuine "flow of time" in the model's processing.

**Engineering implication**: For building perceptual systems, the key insight is that perception needs temporal thickness, not just current-state snapshots. An LLM-mediated perceptual system should receive not just "current state" but a structured temporal context: what just happened, what is happening now, what is expected next. The autoregressive architecture naturally supports this. Research on "cautious next token prediction" (ACL 2025) and "lookahead capabilities" (2025) shows these temporal capacities can be enhanced architecturally.

**Open questions**: Can the retention/protention structure be made explicit in the perception state representation? Rather than relying on the LLM to infer temporal structure from a flat context, should the system pre-structure input with explicit "just-was / is / about-to-be" formatting?

---

### A3. Holism

**The phenomenological claim**: Dreyfus (drawing on Walter Freeman's neuroscience) insisted that perception must be holistic — the whole perceptual field participates in the interpretation of any part. A figure is only a figure against a ground. This holism is not reducible to pairwise feature relationships; it's a global property.

**The LLM parallel**: Transformer self-attention is holistic — every token attends to every other token. The representation of any token is a function of all other tokens in the context. This is the architectural core of the transformer.

**Strongest argument FOR**: Research on vision transformers shows that self-attention implements something very like Gestalt perceptual grouping. Cao et al. (Frontiers in Computer Science, 2023) argue that "self-attention in vision transformers performs perceptual grouping, not attention" — it groups representations based on similarity, implementing bottom-up Gestalt organization principles (proximity, similarity, continuity). A 2025 study confirmed that self-supervised vision models exhibit "emergent Gestalt organization." The transformer's holism is not just architectural — it actually produces Gestalt-like perceptual organization.

**Strongest argument AGAINST**: The transformer's holism is bounded by the context window. Human perceptual holism draws on a lifetime of embodied experience. More importantly, Freeman's holism involved the *entire neural population* shifting attractor states globally — a dynamic, nonlinear process. Transformer attention is a weighted sum, which is linear in the values. The kind of holism may differ: additive combination vs. dynamic phase transitions.

Also, the transformer's holism is feed-forward within a layer (no recurrence), while biological holism involves recurrent dynamics and feedback. The transformer achieves a version of holism through depth (many layers) rather than through temporal dynamics.

**Engineering implication**: The transformer's holistic processing is a genuine asset for perceptual systems. When you provide a rich context (sensor data, state information, recent history, operator preferences), the model integrates all of it holistically — every piece of context shapes the interpretation of every other piece. This is exactly what phenomenology says good perception does. The design principle: provide a rich, structured context rather than isolated data points.

**Open questions**: Does the "lost in the middle" problem (U-shaped attention distribution) undermine holism in practice? How can context be structured to maximize genuine holistic integration rather than recency-biased processing?

---

### A4. Background Understanding

**The phenomenological claim**: Dreyfus's most persistent critique of AI was that it lacks background understanding — the vast, unarticulated web of practical knowledge, cultural norms, and embodied familiarity that humans bring to every situation. This background is not a database of facts; it's a know-how that shapes perception pre-reflectively.

**The LLM parallel**: LLMs trained on the traces of billions of humans' embodied experience have absorbed enormous amounts of background understanding implicitly in their weights. They "know" that chairs are for sitting, that rain makes roads slippery, that someone saying "I'm fine" in certain tones means they're not fine.

**Strongest argument FOR**: Lu (2025, Review of Austrian Economics) argues that LLMs possess two of three forms of tacit knowledge: (1) knowledge that could theoretically be codified but is too costly to do so, and (2) knowledge of nuance and subtext encoded in language. Williams (2025, Philosophy of Science) goes further, arguing that LLMs satisfy Davies's three constraints for tacit knowledge: semantic description, causal systematicity, and syntactic structure. The embedding layer maps semantically similar inputs to proximate regions, and causal tracing (Meng et al.) demonstrates that these representations play a causal role in outputs.

Koch (2025, Philosophy of AI) makes a Kripkean argument that LLMs inherit reference from their training data through a "reference-sustaining training mechanism" — they don't need to independently ground their terms because they inherit the grounding that human language users already established.

**Strongest argument AGAINST**: Lu identifies the critical gap: LLMs lack the third form of tacit knowledge — embodied knowledge gained through sensory experience. They know that ice is slippery (from text about slipperiness) but have never slipped. Dreyfus would insist this matters: the background isn't propositional knowledge about the world; it's a practical grip that comes from bodily engagement.

Harnad (2024, Frontiers in Artificial Intelligence) argues that LLMs benefit from "benign biases" — convergent constraints that emerge at scale — but these biases are "closely linked to what ChatGPT lacks, which is direct sensorimotor grounding." The understanding is "parasitic" on human grounding without possessing its own.

**Engineering implication**: This is where LLMs transform the problem most radically. For an *engineered perceptual system*, the question isn't whether the LLM "truly" understands the background — it's whether the LLM's background knowledge is *functionally adequate* for the system's perceptual tasks. If the system needs to know that a person entering a room changes the social dynamics, or that 2am is an unusual time for activity, or that a cluttered desk might indicate cognitive overload — the LLM knows these things from its training. This is not embodied understanding, but it is *operationally sufficient background* for many perceptual interpretation tasks.

The critical design question becomes: what aspects of background understanding does the LLM lack that are essential for this specific system's perceptual tasks? And can those be supplied through structured context rather than embodied experience?

**Open questions**: How robust is the LLM's background understanding under distribution shift (novel situations not well-represented in training data)? Can we systematically identify the gaps and fill them with operator-specific context?

---

### A5. Affordance Sensitivity

**The phenomenological claim**: Gibson's affordances — what the environment offers for action — are perceived directly, not inferred. Heidegger's ready-to-hand (*Zuhandenheit*) captures a similar insight: tools show up primarily as "for" something, not as objects with properties.

**The LLM parallel**: LLMs can reason about affordances in natural language. Given a description of a situation, they can identify what actions are possible, what tools are available, what the environment permits. In embodied AI, LLMs are being used as the semantic reasoning layer that decomposes tasks and identifies affordances (Tsinghua IEEE Survey, 2025).

**Strongest argument FOR**: In robotics, LLMs enable affordance-grounded planning — detecting objects, reasoning about their affordances, planning action sequences (RSS 2024 proceedings). The WorldAfford system (ICTAI 2025) grounds affordance reasoning in natural language instructions. When an LLM is given structured sensor data about an environment, it can identify action possibilities that weren't explicitly enumerated. This is closer to perception of affordances than rule-based lookup.

**Strongest argument AGAINST**: There's a categorical difference between perceiving an affordance and reasoning about one. Gibson's point is that affordances are *directly perceived* — you see the sit-ability of a chair before you conceptualize it as a chair. LLMs reason about affordances linguistically, which is precisely the reflective, detached mode that phenomenology says is derivative, not primary.

For engineered systems, this distinction matters: an LLM-based system will always have a processing latency between sensor input and affordance identification that embodied perception doesn't have.

**Engineering implication**: LLMs can serve as the *interpretation layer* that translates structured sensor data into affordance descriptions. This is not direct perception of affordances, but it is a viable architecture for engineered systems where the "directness" of biological perception is not achievable. The key is to make the translation fast enough and accurate enough that the system behaves *as if* it perceives affordances directly. Structured context (what tools are available, what the operator typically does, what the current activity is) enables the LLM to identify affordances without explicit enumeration.

**Open questions**: Can affordance identification be cached or pre-computed for common situations, with the LLM only invoked for novel or ambiguous cases? This would approach the "directness" of biological affordance perception.

---

### A6. Mood/Attunement as System Prompt

**The phenomenological claim**: Heidegger's *Stimmung* (mood/attunement) is not an emotion felt "inside" — it's a global coloring of how everything shows up. Anxiety makes everything show up as threatening; boredom makes everything show up as indifferent. Mood is a *prior* that shapes all perception before any specific content is processed.

**The LLM parallel**: The system prompt shapes ALL subsequent processing. It is not one input among many — it is a global prior that colors how every subsequent token is interpreted. Research on "EmotionPrompt" (Li et al., 2023) showed that emotional framing in prompts produces over 45% accuracy swings between best and worst phrasings for identical tasks. The system prompt doesn't just add information; it restructures the model's entire processing orientation.

**Strongest argument FOR**: The structural parallel is strong. Stimmung is: (a) global — it affects everything, not just specific percepts; (b) pre-reflective — it operates before explicit judgment; (c) disclosive — it opens up certain possibilities while closing others; (d) not a separate "input" but a modulation of how all inputs are processed. The system prompt satisfies all four conditions: it affects all subsequent processing, operates at a level below the model's explicit reasoning, opens certain response spaces while closing others, and is not processed as content but as a modulation of processing.

**Strongest argument AGAINST**: Stimmung is *experienced* — it's what it's like to be attuned in a certain way. The system prompt is a text string that modifies computational processing. There is no "what it's like" for the model to have a system prompt. Furthermore, mood in Heidegger emerges from Dasein's being-in-the-world; it's not externally imposed but arises from the existential situation. The system prompt is externally authored.

**Engineering implication**: This is directly actionable. The system prompt is the engineering lever for implementing something functionally equivalent to Stimmung. A perceptual system should have its "attunement" explicitly configured based on context: time of day, operator state, current activity mode, recent events. This isn't metaphorical — it literally changes how the model processes all subsequent inputs.

Design principle: the system prompt should encode not just facts about the current state, but a *disposition* toward the current state. "The operator is in deep focus" is different from "Be alert for signs that the operator's focus might be breaking." The former is a fact; the latter is an attunement.

**Open questions**: Can attunement be updated dynamically within a conversation, or does it require a new context window? How granular should attunement be — one global mood, or layered attunements (temporal, social, activity-specific)?

---

## Thread B: What LLMs Transform About the Problem

### B7. The Representation Problem

**The phenomenological critique**: Phenomenology (especially Heidegger and Merleau-Ponty) critiqued the representationalist assumption that cognition works by building internal models of an external world and then reasoning over those models. They argued that our primary engagement with the world is direct, practical, and non-representational.

**How LLMs complicate this**: LLMs use representations (embeddings, attention patterns, hidden states) but their behavior is not best described as "looking up representations and reasoning over them." The inferentialist analysis (2024 paper on LLMs and Brandom) argues that LLM behavior maps better to inferential semantics — meaning emerges from patterns of inference, not from correspondence to external reality. The model's "understanding" of a concept is its pattern of use in context, not a stored representation that gets retrieved.

**Key research**: The "linear representation hypothesis" (Neel Nanda, 2024; multiple follow-ups) shows that concepts are represented as directions in activation space, and these representations are causally efficacious (Othello-GPT demonstrated this conclusively — the board state representation causally determines move predictions). But these representations are *distributed, contextual, and fluid* — not fixed symbols being manipulated.

Heidari et al. (2024, categorical analysis) argue that LLMs "circumvent" the representation problem by operating on pre-grounded human content — they detect "second-order regularities" (patterns in how humans describe patterns) rather than first-order regularities connecting to reality. The LLM learns that "humans say 'Paris is the capital of France' in specific contexts, not that Paris is the capital of France."

**Engineering implication**: For building perceptual systems, this means we should not think of the LLM as "building an internal model of the environment." Instead, think of it as a *pattern of responsiveness* to structured input. The quality of the system's perception depends on the quality and structure of the input it receives, not on the fidelity of some internal model. This is actually closer to what phenomenology prescribes (direct responsiveness rather than representational intermediation) than traditional AI approaches.

**Open questions**: Does the LLM's fluid, contextual "representation" actually satisfy the anti-representationalist demand, or is it still representation (just more sophisticated)? Is the distinction between "internal model" and "pattern of responsiveness" philosophically meaningful or just a reframing?

---

### B8. The Embodiment Requirement

**The phenomenological/enactivist claim**: Cognition requires a body. Not just sensors — a body that maintains itself, that has needs, that can be damaged, that has a felt relationship to itself. Thompson, Varela, and others argue this is constitutive of cognition, not optional.

**How LLMs complicate this**: LLMs have no body. But when given access to sensors (camera feeds, microphones, biometric data) and actuators (smart home controls, notification systems, display changes), they gain something. Kadambi, Damasio, et al. (2025) propose a "dual-embodiment" framework distinguishing internal embodiment (homeostatic regulation, interoceptive feedback) from external embodiment (environmental interaction). They argue current MLLMs lack internal embodiment entirely.

**Froese's provocation**: Froese (2025/2026, Phenomenology and the Cognitive Sciences) argues that rather than dismissing LLMs as incapable of sense-making due to lack of embodiment, we should recognize them as "a novel non-biological form of sense-maker endowed with a distinctive, technologically-mediated embodiment." This is a significant move within enactivism — suggesting embodiment might be more varied than previously assumed.

**The active inference perspective**: Pezzulo, Parr, Clark, and Friston (2024, Trends in Cognitive Sciences) argue that the key difference is not embodiment per se but the active inference loop — living organisms learn by engaging in purposive interactions with the environment and predicting those interactions. LLMs "currently lack a tight feedback loop between acting in the world and perceiving the impacts of their actions."

**Engineering implication**: The most important insight here is *functional embodiment through the perception-action loop*. An LLM-mediated perceptual system that: (a) receives continuous sensor data, (b) makes interpretive judgments, (c) triggers actions (lighting changes, notifications, display updates), and (d) observes the effects of those actions through subsequent sensor data — this system has a rudimentary action-perception loop. It is not biological embodiment, but it is a form of environmental coupling that goes beyond pure text processing.

The Kadambi/Damasio framework suggests a further step: the system should monitor its own operational state (resource usage, confidence levels, error rates) as a form of "internal embodiment" — self-monitoring that shapes processing.

**Open questions**: How tight does the perception-action loop need to be for phenomenologically adequate processing? Is the latency of LLM inference (seconds) too slow for genuine environmental coupling, or does it suffice for ambient perceptual systems operating on longer timescales?

---

### B9. The Learning Problem

**The phenomenological claim**: Pre-reflective perceptual skills develop through years of embodied experience. You can't shortcut the process of learning to perceive — it requires direct engagement with the world over time.

**How LLMs complicate this**: LLMs have been trained on the *traces* of billions of humans' embodied experience. Every description of slipping on ice, every narrative of social awkwardness, every account of what it's like to be tired — these are compressed into the model's weights. The question: does training on traces of embodied experience substitute for embodied experience itself?

**Key research**: The Nature Human Behaviour study (2025) provides a precise answer: text-based LLMs represent non-sensorimotor features of human concepts well, but systematically fail on sensorimotor features, especially motor actions. The alignment between LLM and human representations decreases as you move from abstract/social concepts toward bodily/motor concepts. This is exactly what you'd expect if training on text captures the linguistic residue of embodiment but not the embodiment itself.

The "developmental" critique (Frontiers in Systems Neuroscience, 2025) argues that humans acquire knowledge incrementally, building complex concepts on simpler ones in developmental progression, while LLMs train on randomly-ordered data. This non-developmental approach "inhibits the ability to build a deep and meaningful grounded knowledge base."

**Engineering implication**: For engineered perceptual systems, the learning problem is partially dissolved. The system doesn't need to learn from scratch — it inherits an enormous amount of interpretive capability from the LLM's training. But it does need to be *tuned* to the specific environment, operator, and context. This tuning can happen through: (a) structured context in the system prompt, (b) few-shot examples of desired interpretations, (c) feedback loops where the operator corrects misinterpretations.

This is a fundamentally different learning problem than what phenomenology describes. It's not "develop perceptual skills through years of embodied experience." It's "configure a pre-trained interpretive system for a specific context." The engineering question becomes: what is the minimum viable context specification for adequate perception?

**Open questions**: How much operator-specific tuning is needed? Can the system learn from corrections over time, and does this constitute a form of "development"? What happens at the boundaries of the LLM's training distribution — situations no human has described in text?

---

### B10. Sense-Making vs. Information Processing

**The phenomenological/enactivist claim**: Cognition is sense-making — the activity of living systems creating meaning. It requires a perspective, a concern, a stake in the outcome. Information processing is not sense-making; it lacks the normative dimension of mattering.

**Froese's (2025) key argument**: Froese presents the "AI dilemma": either (a) LLMs are capable of sense-making despite lacking biological embodiment, which would mean enactivism's embodiment requirement is wrong, or (b) the linguistic competence LLMs exhibit does not require sense-making, which would mean our theories of language are wrong. Rather than choosing (b), Froese provocatively advocates for (a) — recognizing LLMs as "a novel non-biological form of sense-maker."

**The active inference counter**: Pezzulo et al. (2024) argue that the critical distinction is not information processing vs. sense-making per se, but whether the system learns through *purposive interaction* with its environment. Both generative AI and active inference use generative models, but living organisms acquire theirs through engagement with the world, "which provides them with a core understanding and a sense of mattering."

**Engineering implication**: For an engineered system, the question is pragmatic: does the system need to "make sense" of its environment, or does it need to *behave as if* it makes sense? If the operator experiences the system as making sense of their situation — correctly identifying their state, appropriately responding to changes, anticipating needs — then the functional requirement is met regardless of whether the system "truly" makes sense.

However, the active inference perspective suggests a deeper design principle: a system that merely processes information will be brittle. A system that has feedback loops — that acts on its interpretations and adjusts based on outcomes — will be more robust. The sense-making critique, even if we reject its metaphysical commitments, points toward an engineering requirement for closed-loop perception.

---

## Thread C: What's Genuinely New

### C11. Natural Language as Interface to Pre-Reflective Structure

**The radical possibility**: LLMs can be *told* about phenomenological structures in natural language, and they can *use* that understanding to shape their processing. You can describe Zuhandenheit, and the LLM can operationalize the concept in its interpretive responses. No prior AI system could do this.

**Why this matters**: The "development" problem — how pre-reflective structure develops over years of embodied experience — was the deepest gap in prior approaches. LLMs potentially offer a shortcut: instead of developing perceptual skills through embodied engagement, you *describe* the desired perceptual stance in natural language and the LLM approximates it.

**Evidence**: Research on instruction following (ICLR 2025) shows that LLMs can internalize structured abstractions and generalize them to downstream tasks. The mechanistic interpretability work shows that instructions literally reshape internal representations — they're not just surface-level filters.

**Limits**: Philosophers interviewed about LLM use (LLM Cognition Workshop) found that LLMs "lack a sense of selfhood (memory, beliefs, consistency) and initiative (curiosity, proactivity)." The LLM can operationalize a phenomenological concept when instructed to, but it doesn't maintain that operationalization across contexts or develop it autonomously.

**Engineering implication**: This is the key architectural insight. The system prompt can encode phenomenological design principles directly:
- "Interpret activity changes as potential transitions between attention modes"
- "Treat silence differently depending on time of day and preceding activity"
- "Notice when environmental conditions conflict with the operator's apparent intention"

These instructions don't just set parameters — they configure a *perceptual stance*. The LLM's capacity for conceptual understanding means that phenomenological insights can be directly encoded as processing instructions.

---

### C12. Continuous Re-Contextualization

**The insight**: LLMs can take in a new piece of context and instantly re-contextualize all prior understanding in light of it. Tell the model "the operator just received bad news" and its interpretation of subsequent sensor data shifts entirely. This is structurally similar to Gadamer's "fusion of horizons" — the meeting of one's existing understanding with new information that transforms both.

**Critical perspective**: Employing Gadamer's theory, some scholars argue that LLMs lack four features of genuine natural language: groundedness to the world, understanding, community, and tradition. The "fusion" the LLM performs is computational re-weighting, not genuine hermeneutic understanding.

**Engineering implication**: Regardless of the philosophical status, re-contextualization is operationally powerful. A perceptual system can receive context updates ("operator is stressed," "guest arriving in 30 minutes," "it's a weekend") and these updates reshape all subsequent perception. This is a form of dynamic attunement that traditional sensor systems cannot achieve.

---

### C13. The Scaling Question

**Current state**: Emergent abilities in LLMs appear to follow phase-transition dynamics — discontinuous jumps in capability at critical thresholds (Wei et al., confirmed by multiple follow-ups through 2025). However, the 2025 survey by multiple authors concludes "emergence is partially real and partially artifactual, depending on task and metric."

**Key finding**: Emergence aligns more closely with pre-training loss landmarks than with parameter count alone. Smaller models can match larger ones if training loss is sufficiently reduced (through better data, longer training, etc.).

**For perceptual systems**: The scaling question is whether there's a threshold below which LLM-mediated perception is inadequate and above which it becomes viable. Evidence suggests the threshold is task-dependent. For interpreting structured sensor data with rich context, current frontier models (Claude, GPT-4 class) appear above the threshold. For real-time, fine-grained perceptual discrimination, the latency of current models may be more limiting than their capability.

---

### C14. LLMs as Mediators (Not Possessors) of Phenomenological Structure

**The central architectural insight**: Rather than asking whether the LLM *has* phenomenological structure (concern-relativity, temporal thickness, holism, background understanding, affordance sensitivity, attunement), we should ask whether it can *mediate* these structures in a larger system.

The LLM serves as the mechanism by which phenomenological insights are *implemented*, without the LLM itself needing to "experience" anything. The system has concern-relativity because the LLM processes everything relative to a concern-structure encoded in the system prompt. The system has temporal thickness because the LLM receives temporally structured input. The system has background understanding because the LLM's training data includes the traces of human background understanding.

**Supporting research**: Wu et al. (2025, Neurosymbolic AI) demonstrate "Cognitive LLMs" that integrate cognitive architectures with LLMs for decision-making — the LLM serves as the knowledge and reasoning layer while the cognitive architecture provides the structural processing framework. The Model Context Protocol (Anthropic, 2024; widely adopted 2025) provides the infrastructure for LLMs to serve as cognitive middleware connecting sensors, tools, and actuators.

**Engineering implication**: This resolves the philosophical tension. We don't need to claim the LLM has phenomenological experience. We need to design a system where the LLM's capabilities *implement* the functional requirements that phenomenology identifies. The LLM is the interpretive core — the thing that turns sensor data into meaningful descriptions of situations — within a larger system that has genuine environmental coupling through sensors and actuators.

---

## Thread D: Critical Voices and Limits

### D15. What LLMs Genuinely Cannot Do

**Genuine temporality**: The transformer processes sequences but does not exist in time. It has no continuous experience of duration, no genuine "flow" from past to future. Each inference call is a fresh computation. For perceptual systems, this means genuine temporal awareness (not just temporal reasoning) must be supplied by the architecture, not the model.

**Bodily self-awareness**: Kadambi et al. (2025) identify the complete absence of internal embodiment (homeostatic regulation, interoceptive feedback) as a fundamental gap. LLMs cannot feel tired, cannot sense their own resource depletion, cannot have a bodily relationship to their own processing. For perceptual systems, this means the model cannot self-regulate based on its own state in the way biological perception does.

**Genuine novelty detection**: LLMs are excellent at pattern matching within their training distribution but may fail to recognize genuinely novel situations — situations that are not just new combinations of familiar elements but genuinely outside the space of human textual description. This is the limit of training on traces: if no human has described something in text, the LLM has no access to it.

**Normative self-correction without feedback**: Humans can recognize they're perceiving something wrong and self-correct through bodily engagement with the world. LLMs require external feedback (user correction, outcome observation) to correct misperceptions. Without a feedback loop, errors persist or compound.

**Pre-reflective skill acquisition**: The deepest gap. LLMs can be told about pre-reflective skills but cannot develop them through practice. They can reason about what an expert perceiver would notice, but they don't become expert perceivers through repeated exposure. Each inference is fresh — there is no skill accumulation within the model (though fine-tuning approximates this at a different timescale).

---

### D16. The Symbol Grounding Problem — Current State

**The debate has fractured into multiple positions**:

1. **LLMs solve grounding** (minority view): Through scale and multimodality, LLMs achieve genuine semantic grounding.

2. **LLMs circumvent grounding** (Heidari et al., 2024): LLMs exploit pre-grounded human content. They detect second-order patterns in language without connecting to reality directly. Hallucinations are "architectural necessities, not contingent bugs" — structural consequences of operating on second-order regularities.

3. **LLMs inherit grounding** (Koch, 2025): Through a "reference-sustaining training mechanism," LLMs inherit the referential connections that human language users established. This is not independent grounding but it is functionally adequate.

4. **Grounding is the wrong question** (inferentialist position, 2024): Meaning doesn't require grounding in the traditional sense. Meaning is inferential role — how terms function in patterns of inference — and LLMs have rich inferential structure.

5. **Multimodal approaches change the game** (multiple groups, 2024-2025): Vision-Language-Action models attempt genuine grounding through sensorimotor coupling, but critics note that "a picture of a coffee cup is a representation created by human agents" — adding modalities enriches the corpus but doesn't provide direct experience.

**Engineering implication**: For perceptual systems, position 3 (inherited grounding) is the most relevant. The LLM doesn't need to independently ground its understanding of "the operator is tired" — it inherits the grounding from millions of human descriptions of tiredness. The system's job is to connect structured sensor data (posture analysis, activity patterns, time of day) to the LLM's inherited understanding through well-structured prompts. The grounding gap is filled not by the LLM but by the sensor infrastructure.

---

## Synthesis: What This Means for Engineering

### The Structural Mapping

| Phenomenological Structure | LLM Capability | Status | Engineering Lever |
|---|---|---|---|
| Concern-relativity (*Sorge*) | Context-dependent processing via attention | **Strong functional analogue** | System prompt encodes concern-structure |
| Temporal thickness (retention/protention) | Sequence processing + next-token prediction | **Partial analogue** — lacks genuine temporal flow | Temporally structured input format |
| Holism | Global self-attention | **Strong functional analogue** | Rich, interconnected context |
| Background understanding | Training data as compressed human experience | **Partial** — missing embodied/motor knowledge | Operator-specific context supplements gaps |
| Affordance sensitivity | Linguistic reasoning about action possibilities | **Weak analogue** — reflective, not direct | Fast inference + pre-computed common cases |
| Attunement (*Stimmung*) | System prompt as global processing prior | **Strong functional analogue** | Dynamic system prompt updates |
| Sense-making | Debated — Froese says yes, enactivists say no | **Functional** even if not genuine | Closed-loop feedback provides functional equivalent |

### The Key Insight

LLMs don't need to *have* phenomenological structure to *mediate* it. The engineering strategy is:

1. **Encode phenomenological requirements as system architecture**, not as properties of the LLM itself
2. **Use the LLM as the interpretive core** that translates sensor data into situationally meaningful descriptions
3. **Supply temporal structure, concern-relativity, and attunement through the input format and system prompt**
4. **Close the loop** through sensor feedback so the system's interpretations have consequences it can observe
5. **Exploit the LLM's inherited background understanding** while systematically identifying and filling gaps through operator-specific context

### What's Genuinely New That LLMs Enable

1. **Natural language as a phenomenological configuration language**: You can describe the perceptual stance you want and the LLM approximates it. This was impossible before.

2. **Instant re-contextualization**: New information reshapes all interpretation. This is not the hermeneutic circle, but it's functionally similar.

3. **Background understanding without embodied development**: The LLM brings a vast background inherited from human text. This collapses the development problem from years to minutes (of prompt engineering).

4. **Concern-structure as a configurable parameter**: Through the system prompt, you can set what the system cares about. This makes Heidegger's *Sorge* an engineering variable.

5. **Holistic integration as a default**: The transformer architecture provides holistic processing by default. You don't have to engineer it; you get it from the attention mechanism.

### What Remains Genuinely Hard

1. **Real temporality**: The system has no continuous experience. It processes snapshots. Temporal thickness must be engineered into the input format, not relied upon from the model.

2. **Embodied self-regulation**: The system cannot feel its own state. Monitoring must be explicit and external.

3. **Pre-reflective skill development**: The system doesn't get better at perceiving through practice (within a deployment). Learning requires architectural solutions (fine-tuning, memory systems) at a different timescale.

4. **Genuine novelty**: At the edges of human description, the LLM's inherited understanding fails. The system needs explicit uncertainty quantification and graceful degradation.

5. **Latency**: Biological perception is milliseconds. LLM inference is seconds. For ambient perceptual systems this may be acceptable; for real-time interaction it is not.

---

## Key Sources by Thread

### Thread A: Structural Mappings
- Cao et al. (2023). "Self-attention in vision transformers performs perceptual grouping, not attention." *Frontiers in Computer Science*. [Link](https://www.frontiersin.org/journals/computer-science/articles/10.3389/fcomp.2023.1178450/full)
- Albarracin et al. (2022). "Mapping Husserlian phenomenology onto active inference." [arXiv](https://arxiv.org/abs/2208.09058)
- Sandbrink et al. (2025). "Time-consciousness in computational phenomenology." *Neuroscience of Consciousness*. [Link](https://academic.oup.com/nc/article/2023/1/niad004/7079899)
- ICLR 2025 Selective Self-Attention. [Link](https://arxiv.org/abs/2411.12892)
- EmotionPrompt (Li et al., 2023). [Link](https://www.researchgate.net/publication/372583723)

### Thread B: Transformations
- Lu (2025). "Tacit knowledge in large language models." *Review of Austrian Economics*. [Link](https://link.springer.com/article/10.1007/s11138-025-00710-5)
- Williams (2025). "What Do Large Language Models Know?" *Philosophy of Science*. [Link](https://www.cambridge.org/core/journals/philosophy-of-science/article/9475F1504081116099098C37D6F57611)
- Heidari et al. (2024). "A Categorical Analysis of LLMs and the Symbol Grounding Problem." [arXiv](https://arxiv.org/html/2512.09117v1)
- Koch (2025). "Babbling stochastic parrots? A Kripkean argument for reference in LLMs." *Philosophy of AI*. [Link](https://journals.ub.uni-koeln.de/index.php/phai/article/view/2325)
- Kadambi, Damasio et al. (2025). "Embodiment in multimodal large language models." [arXiv](https://arxiv.org/html/2510.13845)
- Froese (2025). "Sense-making reconsidered: LLMs and the blind spot of embodied cognition." *Phenomenology and the Cognitive Sciences*. [Link](https://link.springer.com/article/10.1007/s11097-025-10132-0)
- Pezzulo, Parr, Clark, Friston (2024). "Generating meaning: active inference and the scope and limits of passive AI." *Trends in Cognitive Sciences*. [Link](https://pubmed.ncbi.nlm.nih.gov/37973519/)
- Harnad (2024). "Language writ large: LLMs, ChatGPT, meaning, and understanding." *Frontiers in AI*. [Link](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2024.1490698/full)

### Thread C: Genuinely New
- Philosophical Introduction to Language Models Part II (2024). [arXiv](https://arxiv.org/html/2405.03207v1)
- LLMs and Inferentialism (2024). [arXiv](https://arxiv.org/html/2412.14501v2)
- Emergent Abilities Survey (2025). [arXiv](https://arxiv.org/html/2503.05788v2)
- Wu et al. (2025). "Cognitive LLMs." *Neurosymbolic AI*. [Link](https://journals.sagepub.com/doi/10.1177/29498732251377341)
- Nanda (2024). "Actually, Othello-GPT Has A Linear Emergent World Representation." [Link](https://www.neelnanda.io/mechanistic-interpretability/othello)

### Thread D: Limits
- Multi-camera deep understanding critique (2025). *Frontiers in Systems Neuroscience*. [Link](https://www.frontiersin.org/journals/systems-neuroscience/articles/10.3389/fnsys.2025.1683133/full)
- Nature Human Behaviour (2025). "LLMs without grounding recover non-sensorimotor but not sensorimotor features." [Link](https://www.nature.com/articles/s41562-025-02203-8)
- Self-referential processing study (2025). [arXiv](https://arxiv.org/html/2510.24797v2)
- Emergent temporal abstractions (2025). [arXiv](https://arxiv.org/abs/2512.20605)
