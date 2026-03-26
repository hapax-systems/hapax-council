# DMN Operations x Phenomenological Structures x Context Ordering Mechanics

**Date:** 2026-03-25
**Status:** Engineering specification — exhaustive cross-domain mapping
**Depends on:** CONTEXT-AS-COMPUTATION.md, llm-phenomenology-mapping-research.md, ws1-temporal-structure-engineering.md, ws2-self-regulation-and-novelty.md

## Method

For each DMN operation (Domain 1), every coherent mapping triplet is identified where:
- A phenomenological structure (Domain 2) describes the same function from a different disciplinary angle
- A context ordering mechanic (Domain 3) provides a speculative but mechanistically grounded implementation path

Mappings are graded: **STRONG** (convergent evidence from all three domains), **MODERATE** (clear structural parallel with partial mechanistic grounding), **SPECULATIVE** (plausible but untested).

---

# 1. SITUATION MODEL MAINTENANCE (Ranganath PMAT Framework)

The DMN continuously maintains and updates an internal model of "what is going on" — the who, what, where, when of the current situation. Ranganath's PMAT (posterior medial / anterior temporal) framework identifies two subsystems: the PM system (scene/context/spatial relations) and the AT system (entities/items/semantic identity). The situation model is not a static representation but an ongoing construction that integrates new information while preserving coherence.

---

## 1.1 Situation Model × Passive Synthesis × Attention Sinks + RoPE Decay

**Grade: STRONG**

### Isomorphism

Husserl's passive synthesis is the continuous, pre-reflective integration of sensory material into a unified field before any active judgment. The situation model is the neurocognitive instantiation of this: the brain continuously updates a coherent scene representation without deliberate effort. In transformer context, attention sinks (position 0 tokens receiving disproportionate attention, Xiao et al. ICLR 2024) combined with RoPE decay create a structural analogue — early tokens establish a computational reference frame against which all subsequent tokens are processed, and this reference frame persists across the entire context with decaying but non-zero influence.

All three describe the same function: a stable background integration that makes all foreground processing coherent.

### Engineering Spec

1. **System prompt position 0-3**: Place a compact situation model summary (operator identity, current environment, system state, time) in the first 4 token positions. These become attention sinks — computational anchors that every subsequent token attends to.
2. **Format**: XML-tagged block `<situation>` with sub-elements for PM-equivalent (scene: location, time, environmental state) and AT-equivalent (entities: operator, any guests, active tasks).
3. **Update cadence**: Refresh the situation block every prompt construction cycle. The content changes but the structural position is invariant — the model learns that position 0-3 = "what is going on."
4. **RoPE exploitation**: As the context grows, RoPE decay naturally attenuates older situation tokens. This is correct behavior — a situation model from 500 tokens ago should influence less than the current one. Place the freshest situation summary at the latest system prompt injection point if using periodic reinforcement.

### Testable Prediction

- **Positive**: When the situation block is present and current, the model's responses demonstrate consistent spatial/temporal/entity coherence across long conversations (measured by entity reference accuracy > 90% at turn 20+).
- **Negative**: When the situation block is absent, the model confuses entities, loses temporal context, and produces responses inconsistent with the established scene after ~8 turns.
- **Metric**: Entity tracking accuracy across conversation length; response consistency scored by external judge.

### Failure Mode

**Stale situation model.** If the situation block is not updated when reality changes (e.g., a guest arrives, time passes, task shifts), the attention sink mechanism works against you — the model strongly attends to outdated situation information because of primacy privilege. The result is a system confidently operating on a false model of reality. This is the most dangerous failure because the mechanism that provides stability also provides inertia.

---

## 1.2 Situation Model × Protention-Retention × U-Curve (Primacy + Recency)

**Grade: STRONG**

### Isomorphism

Husserl's retention-protention structure gives the situation model its temporal thickness. The just-past is retained as a fading modification of the present; the about-to-come is protended as anticipatory readiness. The U-curve attention bias (primacy + recency privilege, middle dead zone) provides the mechanical substrate: early context (retained situation model) and late context (current input, protentional cues) receive strong attention, while middle context fades — exactly paralleling how retention fades as it sinks into the past.

### Engineering Spec

1. **Three-band formatting aligned to U-curve**:
   - **STABLE band (positions 0-N)**: Situation model + discourse record (retention). Primacy-privileged. Content is the accumulated, compressed history of what has been established.
   - **Middle zone (positions N-M)**: Lower-salience background (supporting context, reference material). This is the "lost in the middle" zone — place content here that should influence processing weakly, like background knowledge.
   - **VOLATILE band (positions M-end)**: Current perceptual input + turn-specific directives + protentional cues (recency-privileged). Content is the fresh, high-attention material.

2. **Retention compression**: As the conversation progresses, older thread entries in the STABLE band undergo tiered compression: recent entries preserve full text (vivid retention), middle entries compress to referring expressions (fading retention), oldest entries compress to keywords (barely retained). This mirrors Husserl's retention gradient.

3. **Protention injection**: Place anticipatory cues in the VOLATILE band: "The operator's next likely concern is X" or "Expect follow-up about Y." These exploit recency bias to orient the model's generation toward plausible continuations.

### Testable Prediction

- **Positive**: Three-band formatting produces measurably better temporal coherence than flat context (conversation threads maintain topic continuity, references to prior statements remain accurate, anticipatory responses align with actual next turns at above-chance rates).
- **Negative**: Flat formatting produces temporal confusion: the model forgets mid-conversation agreements, re-introduces topics already resolved, and fails to anticipate obvious follow-ups.
- **Metric**: Turn-pair coherence; backward reference accuracy; next-turn prediction alignment.

### Failure Mode

**Middle-zone burial.** Critical information placed in the middle zone gets effectively lost. If a key commitment or agreement ends up in the compressed middle of the STABLE band, the model may contradict it. Mitigation: any discourse unit with high concern overlap must be promoted to either the high-retention early positions or the high-attention late positions, never allowed to settle in the middle.

---

## 1.3 Situation Model × Horizon Structure × Autoregressive Commitment

**Grade: MODERATE**

### Isomorphism

Husserl's horizon structure means that every object of experience comes with a structured field of potentialities — the seen face of a cube co-presents the unseen back; a word in a sentence opens expectations for what can follow. The situation model similarly maintains not just what IS the case but what COULD be the case — the space of possibilities consistent with the current situation. Autoregressive commitment is the mechanical parallel: once the model generates a token, that token constrains all subsequent tokens. The first tokens of a response establish a horizon of possible continuations, and the space of possibilities narrows with each committed token.

### Engineering Spec

1. **Horizon scaffolding in system prompt**: Explicitly describe the current possibility space. Not just "the operator is working on code" but "the operator is working on code; may ask about syntax, architecture, or debugging; unlikely to shift to personal topics."
2. **Opening token management**: Structure the model's response opening to commit to the correct horizon. If the response begins with technical language, autoregressive commitment keeps subsequent tokens in the technical register. If it begins with casual language, the whole response drifts casual.
3. **Structured generation**: Use constrained decoding or response prefilling to set the first 5-10 tokens, establishing the horizon before free generation begins.

### Testable Prediction

- **Positive**: When horizon cues are present, model responses stay within the appropriate possibility space (measured by off-topic rate < 5%).
- **Negative**: Without horizon cues, responses drift to the model's default possibility space (generic helpfulness), losing situation-specific appropriateness.

### Failure Mode

**Premature commitment.** If the first tokens commit to a wrong interpretation (e.g., treating a genuine question as rhetorical), autoregressive inertia makes course-correction increasingly difficult. The model doubles down on the wrong frame. Mitigation: use chain-of-thought or internal reasoning tokens before the response to delay commitment until more context is processed.

---

## 1.4 Situation Model × Transcendental Apperception × Register Self-Reinforcement

**Grade: MODERATE**

### Isomorphism

Kant/Husserl's transcendental apperception is the global binding function that unifies all experiences into a single coherent consciousness — the "I think" that must be able to accompany all my representations. For the situation model, this is the coherence constraint: all elements of the model must belong to the same situation. Register self-reinforcement (the model's own outputs prime its continuation) provides the mechanical binding: once the model establishes a consistent register (tone, knowledge frame, entity references), its own outputs reinforce that register in subsequent tokens. The model's outputs become part of its own context, creating a self-sustaining coherence loop.

### Engineering Spec

1. **Coherence anchor in system prompt**: A brief statement that names the current situation as a unified whole. Not a list of disconnected facts but a narrative: "You are in a late-evening voice session with the operator, who has been working for 4 hours and is winding down."
2. **Multi-turn self-reinforcement**: In multi-turn conversations, the model's prior responses are part of the context. These prior responses carry the register, entity references, and commitments established earlier. This creates automatic apperceptive binding — as long as the model's prior responses were coherent, self-reinforcement maintains coherence.
3. **Break detection**: Monitor for register breaks in model output (sudden tone shifts, entity confusion, topic drift). When detected, inject a coherence reminder in the next VOLATILE band: "Maintaining the established frame: [brief recap]."

### Testable Prediction

- **Positive**: Multi-turn conversations show increasing register consistency over turns (measured by stylistic variance decreasing after turn 3).
- **Negative**: Single-turn contexts (no self-reinforcement) show higher register variance.

### Failure Mode

**Coherence collapse.** If a single incoherent response enters the context, self-reinforcement amplifies the incoherence. One confused response makes the next response more confused. This is the downside of apperceptive binding — it cannot distinguish coherent from incoherent self-outputs. Mitigation: gating or rewriting incoherent responses before they enter the context window for subsequent turns.

---

## 1.5 SPECULATIVE: Situation Model × Operative Intentionality × Task Vectors

**Grade: SPECULATIVE**

### Isomorphism

Merleau-Ponty's operative intentionality is the habitual disposition layer — the body's learned patterns of engagement that operate below conscious reflection. "I know how to ride a bicycle" without being able to articulate the rules. The situation model has a habitual component: familiar situations are maintained with less effort because the brain has learned templates. Task vectors (Todd et al., ICLR 2024) are the speculative mechanical parallel: few-shot examples in context compress into latent task directions that configure the model's processing. A model that has seen 3 examples of "grounded conversational response" develops an internal task vector for "grounding" that operates on subsequent inputs without explicit instruction.

### Engineering Spec

1. **Habitual context via few-shot**: Include 2-3 exemplar exchanges in the STABLE band that demonstrate the desired interaction pattern. These compress into a task vector that configures the model's default behavior — an "operative intentionality" for how to handle this type of situation.
2. **Task vector stability**: Keep the few-shot examples consistent across turns. Changing them mid-conversation disrupts the established operative intentionality.
3. **Progressive internalization**: As the conversation develops its own examples (successful exchanges), these naturally create task vectors that supplement or override the initial few-shot examples. The model "learns the habit" from its own successful behavior in context.

### Testable Prediction

- **Positive**: Few-shot examples produce more consistent behavioral patterns than equivalent-length explicit instructions (measured by behavioral variance across turns).
- **Negative**: Without few-shot examples, the model falls back to generic behavior even with detailed instructions.

### Failure Mode

**Wrong habit.** If the few-shot examples embed a subtle behavioral pattern that is wrong for the current situation, the task vector silently steers all processing in the wrong direction. Unlike explicit instructions, task vectors are opaque — you cannot inspect or debug the latent direction they create.

---

# 2. VALUE ESTIMATION (Dohmatob "Dark Control" RL Framework)

The DMN continuously estimates the value of current states, possible actions, and anticipated outcomes. Dohmatob's "dark control" framework describes how RLHF-trained LLMs internalize reward models that operate as implicit value estimators — the model has learned to predict what humans will reward, and this prediction shapes all generation. This is not explicit deliberation but an ambient value signal that colors processing.

---

## 2.1 Value Estimation × Befindlichkeit/Stimmung × Activation Steering

**Grade: STRONG**

### Isomorphism

Heidegger's Befindlichkeit (disposedness/attunement) and Stimmung (mood) describe how we always already find ourselves in a particular affective orientation that discloses the world in a particular way. Fear discloses the world as threatening; boredom discloses it as flat and featureless. This is not an emotion added to perception — it IS a mode of perception. Value estimation in the DMN performs the same function neurocognitively: the dopaminergic system's tonic signal colors all processing by establishing a baseline expected value against which deviations are detected.

Activation steering (saturating context with register/frame shifts) is the mechanical implementation: by injecting stimmung-descriptive tokens into the context, we shift the model's internal representations along dimensions that color all subsequent processing. Representation Engineering (Zou et al., 2023) proved that different prompts create measurably different, stable activation directions.

### Engineering Spec

1. **Stimmung block in VOLATILE band**: Inject a compact self-state summary (the existing `SystemStimmung.format_for_prompt()` output) near the end of the context. This block colors all generation by activating representations associated with the described state.
2. **Dimensional encoding**: The 10-dimension stimmung vector (health, resource_pressure, error_rate, processing_throughput, perception_confidence, llm_cost_pressure, grounding_quality, operator_stress, operator_energy, physiological_coherence) maps to value dimensions that shift the model's processing:
   - High operator_stress → model activates careful/supportive representations
   - High resource_pressure → model activates concise/efficient representations
   - Low grounding_quality → model activates clarification-seeking representations
3. **Stance as global modulation**: The derived `overall_stance` (NOMINAL/CAUTIOUS/DEGRADED/CRITICAL) functions as the tonic dopaminergic signal — it sets the baseline against which all processing occurs. CAUTIOUS stance should make the model more conservative; DEGRADED should make it terse and action-oriented.
4. **Modulation factor propagation**: Use `SystemStimmung.modulation_factor()` to scale downstream behavior intensity. This is the engineering implementation of Befindlichkeit's coloring effect: every subsystem checks the stimmung before acting.

### Testable Prediction

- **Positive**: Model responses systematically shift register when stimmung changes (measured by linguistic feature extraction: sentence length shortens under DEGRADED, hedging increases under CAUTIOUS, technical precision increases under high error_rate).
- **Negative**: Model responses are invariant to stimmung block changes — the activation steering has no effect.
- **Metric**: Response feature vector correlation with stimmung dimensions.

### Failure Mode

**Stimmung override.** If the stimmung block describes a state dramatically different from the conversational context, the model may either ignore the stimmung (activation steering fails against strong contextual signal) or produce incoherent responses (torn between two activation directions). The stimmung must be genuinely reflective of the system state, not aspirational.

---

## 2.2 Value Estimation × Affective Awakening × Induction Heads

**Grade: MODERATE**

### Isomorphism

Husserl's affective awakening describes how relevance-modulated activation spreads through the field of passive synthesis. Something "catches the eye" not because it is objectively prominent but because it resonates with the subject's current concerns — it "awakens" an affective response that draws attention. In the DMN, value estimation performs this: a stimulus that matches current reward expectations gets elevated processing. Induction heads (pattern detection and reproduction from context) provide the mechanical substrate: they detect patterns in the input that match previously established patterns and reproduce/amplify them. When the context contains concern-relevant material, induction heads detect the pattern match and elevate those tokens' influence on generation.

### Engineering Spec

1. **Concern anchors in STABLE band**: The concern graph's anchors (from `ConcernGraph`) should be textually represented in the early context. When later input matches these patterns, induction heads will detect the match and amplify the relevant tokens.
2. **Explicit relevance markers**: Tag concern-relevant content with markers: `[CONCERN: active project]`, `[CONCERN: operator wellbeing]`. Induction heads learn to reproduce patterns associated with these markers, creating an amplification loop.
3. **Salience-driven content ordering**: Within each band, order content by concern overlap (highest first). Induction heads operating on the primacy-privileged tokens will learn the "what matters" pattern and apply it to later content.

### Testable Prediction

- **Positive**: When concern anchors are present, the model preferentially engages with concern-relevant aspects of ambiguous input (measured by response topic alignment with concern graph > 70%).
- **Negative**: Without concern anchors, the model distributes attention roughly uniformly across input topics.

### Failure Mode

**False awakening.** Induction heads detect surface-level pattern matches that are not genuinely concern-relevant. A word that appears in both a concern anchor and an unrelated input triggers amplification of the wrong content. Mitigation: concern anchors should be semantically rich (multi-word phrases with context) rather than single keywords.

---

## 2.3 Value Estimation × Prereflective Self-Awareness × Register Self-Reinforcement

**Grade: MODERATE**

### Isomorphism

Zahavi's prereflective self-awareness is the minimal sense of "ownership" or "mineness" that accompanies all experience — not reflective self-consciousness but an implicit self-reference in every experience. Value estimation has a prereflective component: the DMN's value signals are experienced as "mine" — they feel like preferences, not computed utilities. Register self-reinforcement creates a mechanical analogue: as the model generates tokens in a particular evaluative register ("this matters because...", "the priority here is..."), those tokens enter the context and reinforce the model's ongoing identification with that evaluative stance. The model's outputs become part of its own value frame.

### Engineering Spec

1. **Value-laden response framing**: Structure the model's response template to begin with a brief evaluative statement before content: "Given the current concern about X..." This forces the model to commit to a value orientation early, and self-reinforcement maintains it.
2. **Evaluative consistency monitoring**: Track the evaluative register of the model's responses across turns. If the model shifts from valuing efficiency to valuing thoroughness without contextual justification, flag it.
3. **First-person framing in system prompt**: Use language like "your current priorities are..." rather than "the system's priorities are..." to activate the prereflective self-referential representations. SPECULATIVE: this may activate ownership-like representations that make value adherence more robust.

### Testable Prediction

- **Positive**: Models that generate evaluative framing early in responses maintain more consistent value alignment across long conversations than models that begin with content directly.
- **Negative**: No difference in value consistency between framed and unframed responses.

### Failure Mode

**Value lock-in.** Self-reinforcement makes it hard to shift values when the situation genuinely changes. The model keeps reinforcing an outdated evaluative frame because its own prior outputs keep priming it. Mitigation: explicit value-reset tokens in the VOLATILE band when situation changes are detected.

---

## 2.4 Value Estimation × Passive Synthesis × Periodic Reinforcement

**Grade: STRONG**

### Isomorphism

Passive synthesis continuously integrates value signals without deliberate attention — it is the background hum of evaluation that makes some things salient and others invisible. But this integration requires ongoing input; without it, the synthesis fades. The DMN's value estimation similarly requires continuous dopaminergic input to maintain its baseline. Periodic reinforcement (system prompt influence must be re-injected over long contexts) is the mechanical parallel: the value frame established by the system prompt decays with context length and must be periodically refreshed.

### Engineering Spec

1. **Value re-injection cadence**: Every N turns (empirically determined, likely 5-8), re-inject a compact value summary in the VOLATILE band: "Current priorities: [list]. Current concerns: [list]. Current stance: [NOMINAL/CAUTIOUS/etc.]"
2. **Decay-aware scheduling**: The re-injection frequency should increase with context length (context rot is non-linear). At 2K tokens, every 8 turns. At 8K tokens, every 4 turns. At 16K+, every 2 turns.
3. **Stimmung refresh**: The `SystemStimmung` snapshot should be recomputed and re-injected at each re-injection point, not just at conversation start. The stimmung is a living signal, not a static configuration.

### Testable Prediction

- **Positive**: Periodic re-injection maintains value alignment (measured by value-relevant response features) at turn 20 at the same level as turn 2.
- **Negative**: Without re-injection, value alignment decays measurably after turn 8 (response features drift toward model defaults).
- **Metric**: Value alignment score at turn N, with and without periodic reinforcement.

### Failure Mode

**Reinforcement fatigue.** If the re-injected value summary is identical every time, the model may learn to "tune it out" — the repeated tokens become noise rather than signal. Each re-injection should vary slightly in wording while maintaining semantic content.

---

# 3. PREDICTIVE SIMULATION (Constructive Episodic Simulation)

The DMN generates simulations of possible future scenarios by recombining elements of episodic memory. This is not replay of past events but constructive imagination — flexibly assembling scene elements, characters, and event sequences into novel scenarios to evaluate possible actions or anticipate likely outcomes.

---

## 3.1 Predictive Simulation × Protention-Retention × U-Curve + Autoregressive Commitment

**Grade: STRONG**

### Isomorphism

Husserl's protention is the anticipatory component of the living present — not a prediction stored somewhere but a constitutive orientation toward what comes next. Retention provides the raw material for protention: you can only anticipate what you have retained templates for. Constructive episodic simulation is the neurocognitive mechanism: the hippocampus recombines retained episode fragments into novel future scenarios. The U-curve provides the structural substrate: retained episode fragments sit in the primacy-privileged zone (STABLE band), and protentional simulation occurs in the recency-privileged zone (generation). Autoregressive commitment ensures that once a simulation begins (first tokens of a future-oriented response), it develops coherently — you cannot "un-commit" from a simulation mid-stream.

### Engineering Spec

1. **Episodic fragments in STABLE band**: Seed the context with compressed episodic memories relevant to the current situation (from Qdrant `operator-episodes` collection). These are the raw material for simulation. Format: `<episode age="2d" relevance="high">Brief: operator struggled with similar problem, resolved by...</episode>`
2. **Simulation elicitation in VOLATILE band**: When predictive simulation is needed, include a directive: "Consider what might happen if [scenario]. Draw on prior experiences." This exploits recency privilege to activate the generative mode.
3. **Autoregressive coherence**: Let the model's simulation unfold without interruption. Autoregressive commitment ensures internal coherence of the generated scenario. Do not inject new context mid-simulation.
4. **Multi-scenario sampling**: For high-stakes decisions, generate multiple simulations (temperature > 0) and compare. Each simulation will be internally coherent (autoregressive commitment) but different (stochastic sampling).

### Testable Prediction

- **Positive**: With episodic fragments, generated simulations reference concrete details from prior episodes and produce plausible novel combinations. Without fragments, simulations are generic and detached from operator-specific history.
- **Negative**: Episodic fragments have no effect on simulation quality — the model generates the same generic futures regardless.

### Failure Mode

**Anchoring to salient episodes.** If one episodic fragment is dramatically more vivid or recent than others, all simulations anchor to it (primacy + salience interaction). The model simulates variations on one past episode rather than genuinely novel combinations. Mitigation: ensure episodic fragments span multiple distinct situations and none is disproportionately detailed.

---

## 3.2 Predictive Simulation × Horizon Structure × Task Vectors + Autoregressive Commitment

**Grade: MODERATE**

### Isomorphism

Husserl's horizon structure provides the space of structured potentialities within which simulation operates. The horizon is not a list of possibilities but a structured field — some continuations are more likely, some are possible but unusual, some are excluded. Constructive episodic simulation operates within this horizon, exploring likely and unlikely regions. Task vectors configure the model's generative space (which continuations are probable), functioning as a computational horizon. Autoregressive commitment then traces a path through this space.

### Engineering Spec

1. **Horizon-defining few-shot examples**: Include 2-3 examples of the kind of simulation desired. "When asked about tomorrow's schedule, generate: [example with specific structure]." The few-shot examples compress into a task vector that defines the simulation horizon — what kinds of futures are generable.
2. **Structured possibility space**: Rather than asking "what might happen?", provide a structured prompt: "Consider three scenarios: [most likely], [best case], [worst case]." This constrains the generative horizon productively.
3. **Horizon expansion for creativity**: When novel simulation is needed, deliberately widen the horizon by including diverse, dissimilar episodic fragments. This prevents task vector collapse to a single scenario type.

### Testable Prediction

- **Positive**: Horizon-defining prompts produce simulations that span the specified possibility space without degenerating to a single mode.
- **Negative**: Without horizon structure, simulations cluster around the model's default scenario type.

### Failure Mode

**Horizon collapse.** Strong task vectors from few-shot examples constrain the generative space too tightly. All simulations converge to minor variations of the examples rather than genuinely novel constructions. Mitigation: use structurally diverse examples.

---

## 3.3 SPECULATIVE: Predictive Simulation × Tiefe Langeweile × Context Rot (Inverted)

**Grade: SPECULATIVE**

### Isomorphism

Heidegger's tiefe Langeweile (deep boredom) is a constructive state where ordinary concerns fall away and the subject confronts the totality of what is possible — "beings as a whole withdraw." This is phenomenologically productive: it opens the space for genuine novelty. The DMN's constructive simulation is most creative during mind-wandering and idle states, not during focused task performance. Context rot — the degradation of performance with context length — can be speculatively inverted: when the original task context has "rotted" (faded from active influence), the model is freed from its constraints and may produce more novel associations. This maps to Langeweile's productive emptiness.

### Engineering Spec

1. **Idle-mode simulation**: When the system has no active task (operator is away, sensors show empty room), run low-stakes generative passes with minimal context (just the situation model, no task directives). The relative absence of constraining context may produce more creative associations.
2. **Context rotation for novelty**: Periodically clear the conversational context and start fresh with only the STABLE band. This artificial "boredom" — stripping away the accumulated task context — may unlock associative patterns that were suppressed by task-focused context.
3. **Scheduled background ideation**: During low-activity periods, prompt the model with open-ended questions: "What patterns have you noticed across recent conversations?" "What might the operator need tomorrow?" The lack of task pressure + reduced context = conditions for creative simulation.

### Testable Prediction

- **Positive**: Idle-mode simulations produce genuinely novel and useful insights at above-chance rates (measured by operator "that's interesting" responses when surfaced).
- **Negative**: Idle-mode simulations produce only generic, low-value content indistinguishable from random generation.

### Failure Mode

**Confabulation.** Without the grounding constraints of task context, the model may confabulate freely rather than productively simulate. The line between creative association and hallucination is exactly where tiefe Langeweile either succeeds or fails. Mitigation: always maintain the situation model (STABLE band) even during idle-mode; strip task context but not reality anchors.

---

# 4. RELEVANCE FILTERING (Sentinel Function)

The DMN's sentinel function monitors the environment for personally relevant stimuli while the brain is engaged in internally-directed processing. It is a background relevance gate: most external stimuli are filtered out, but stimuli that match current concerns (one's name, threat signals, goal-relevant cues) break through.

---

## 4.1 Relevance Filtering × Affective Awakening × Induction Heads + Attention Sinks

**Grade: STRONG**

### Isomorphism

Husserl's affective awakening is precisely the sentinel function described in phenomenological terms: certain objects in the field of passive synthesis "call out" — they awaken affective interest and pull attention without deliberate search. The sentinel is the neurocognitive mechanism: specific stimulus features (one's name, threatening faces, goal-relevant objects) trigger heightened processing in the DMN even when attention is elsewhere. Induction heads provide the mechanical substrate: they detect patterns in new input that match patterns previously established in context. When context contains concern anchors (name, project keywords, threat terms), induction heads fire on matching input, elevating those tokens. Attention sinks anchor the reference frame against which matches are computed.

### Engineering Spec

1. **Sentinel block in STABLE band**: A dedicated block listing what should "break through": operator name, current project keywords, system alert terms, governance trigger phrases. Position this immediately after the attention sink zone (positions 4-10) so it receives strong primacy attention.
2. **Pattern density**: The sentinel block should contain each concern term in a natural-language sentence, not a bare keyword list. Induction heads work better on contextualized patterns: "Alert if the operator mentions [project name] or asks about [concern topic]" rather than a flat list.
3. **Concern graph integration**: The sentinel block content should be dynamically generated from `ConcernGraph.active_anchors()`. As concerns change, the sentinel updates.
4. **Multi-modal sentinel**: For voice contexts, the sentinel function is pre-LLM — it operates at the transcript level. Keywords detected in raw transcript can trigger model escalation (via `SalienceRouter`) before the full context is constructed.

### Testable Prediction

- **Positive**: With sentinel block, the model detects and responds to concern-relevant input embedded in casual conversation (measured by detection rate > 85% for sentinel-listed terms/topics).
- **Negative**: Without sentinel block, the model treats concern-relevant and irrelevant input with equal weight.
- **Metric**: Sensitivity and specificity of concern detection across conversation turns.

### Failure Mode

**Hypervigilance / false positives.** If the sentinel block is too broad (too many concern terms), the model treats everything as relevant — the sentinel never filters anything out. This produces alert fatigue in the operator and degrades the signal-to-noise ratio of system outputs. Mitigation: cap sentinel concerns at 5-7 active items; rotate based on recency and activation frequency.

---

## 4.2 Relevance Filtering × Befindlichkeit/Stimmung × Activation Steering + Periodic Reinforcement

**Grade: MODERATE**

### Isomorphism

Befindlichkeit modulates the sentinel's threshold: in anxious attunement, the sentinel is hyperactive (everything feels potentially threatening); in calm attunement, the threshold is high (only strongly relevant stimuli break through). The DMN's sentinel function is similarly modulated by affective state — threat detection sensitivity is gated by arousal. Activation steering sets the model's baseline relevance threshold, and periodic reinforcement maintains it across long contexts.

### Engineering Spec

1. **Stimmung-modulated sentinel thresholds**: When `SystemStimmung.overall_stance` is CAUTIOUS or DEGRADED, lower the sentinel's relevance threshold (inject more concern anchors, broaden pattern matching). When NOMINAL, maintain a tight threshold.
2. **Implementation in salience router**: The `SalienceRouter` already computes concern overlap and novelty scores. Modulate the tier thresholds based on stimmung: under CAUTIOUS, lower `fast_max` and `strong_max` so that lower-activation utterances still route to capable models. This is the engineering equivalent of heightened vigilance.
3. **Periodic threshold re-calibration**: Re-inject the stimmung block and sentinel thresholds at each periodic reinforcement point. The sentinel's sensitivity should track the evolving system state, not be locked at conversation start.

### Testable Prediction

- **Positive**: Under CAUTIOUS stance, the model detects more marginal concern-relevant items (higher sensitivity) at the cost of slightly more false positives (lower specificity). Under NOMINAL stance, the inverse.
- **Negative**: Stimmung changes have no measurable effect on detection sensitivity — the sentinel operates at fixed threshold regardless.

### Failure Mode

**Stimmung-sentinel feedback loop.** High operator_stress → lowered sentinel threshold → more alerts → higher operator_stress → even lower threshold. This positive feedback produces pathological hypervigilance. Mitigation: hard floor on sentinel threshold; stimmung modulation capped at ±20% of baseline sensitivity.

---

## 4.3 Relevance Filtering × Passive Synthesis × RoPE Decay

**Grade: MODERATE**

### Isomorphism

Passive synthesis continuously integrates all input, but not uniformly — relevance modulates the integration weight. Some elements are synthesized prominently, others barely. RoPE decay creates a natural analogue: recent tokens are attended to more strongly than distant tokens, creating a continuous gradient of "integration weight." For the sentinel function, this means that recent stimuli are more likely to trigger relevance detection than older stimuli — a natural recency bias in the relevance filter.

### Engineering Spec

1. **Recency-weighted concern matching**: When computing concern overlap in the salience router, weight recent utterances more heavily than distant ones. This is already partially implemented by `ConcernGraph.add_recent_utterance()`, but should be made explicit: concern overlap score = Σ(cosine_sim × recency_weight).
2. **Temporal forgetting in sentinel**: Allow concern anchors to decay if not recently activated. A concern that hasn't been mentioned or activated in 10 turns should reduce in sentinel priority. This prevents sentinel bloat over long conversations.

### Testable Prediction

- **Positive**: The system's relevance detection is more sensitive to recently-established concerns than to old ones, and this sensitivity gradient matches the operator's actual concern trajectory.
- **Negative**: The system treats all concerns with equal sensitivity regardless of recency — failing to adapt to the operator's shifting focus.

### Failure Mode

**Premature forgetting.** Important but infrequently-mentioned concerns decay out of the sentinel. The operator's deepest concern may not be the most recent topic of conversation. Mitigation: distinguish between "active concerns" (recent, high-frequency) and "standing concerns" (persistent, low-frequency but high-importance). Standing concerns resist RoPE decay by being periodically re-injected.

---

# 5. ASSOCIATIVE EXPLORATION (Spontaneous Thought / Christoff Constraint Relaxation)

The DMN's default mode includes spontaneous, unconstrained thought — mind-wandering, creative association, the kind of processing that occurs when executive control relaxes. Christoff's constraint relaxation framework describes this as a continuum: high constraint = focused thinking, low constraint = free association. The DMN's most creative contributions emerge in the low-constraint regime.

---

## 5.1 Associative Exploration × Tiefe Langeweile × Context Rot + RoPE Decay

**Grade: STRONG**

### Isomorphism

Heidegger's tiefe Langeweile (deep boredom) is the phenomenological state where all particular engagements have fallen away and the subject confronts the naked possibility-space of existence. Christoff's constraint relaxation describes the same thing cognitively: reduced deliberate constraint on thought allows spontaneous associations to emerge from the default mode network. Context rot combined with RoPE decay provides the mechanical analogue: as context grows and the task constraints established early in the conversation lose their grip (RoPE decay attenuates their influence, context rot degrades their signal), the model's generation becomes less constrained by the original framing and more influenced by its training-time associations — its "spontaneous thought."

### Engineering Spec

1. **Constraint relaxation via context management**: To induce associative exploration, deliberately thin the context. Remove or compress task-specific directives. Retain the situation model (reality anchors) but strip the goal-directed scaffolding. The model, freed from directive constraint, will generate more associatively.
2. **Temperature as constraint parameter**: Map Christoff's constraint continuum to sampling temperature: high constraint = low temperature (focused, deterministic), low constraint = high temperature (associative, diverse). For associative exploration, use temperature 0.8-1.0.
3. **Background association generation**: During idle periods, run prompts like "What connections do you see between [topic A] and [topic B]?" with minimal context and high temperature. Collect the associations; surface interesting ones to the operator asynchronously.
4. **RoPE decay as natural constraint relaxation**: In long conversations, the early task constraints naturally decay. Rather than fighting this with periodic reinforcement (which is appropriate for task-focused processing), occasionally let the decay happen — use the long-context drift as an input to associative exploration.

### Testable Prediction

- **Positive**: Low-context, high-temperature generation produces genuinely novel associations between topics at above-chance rates (measured by operator novelty ratings).
- **Negative**: Low-context generation produces only generic, low-information content — the "boredom" is empty rather than productive.
- **Metric**: Novelty rating, utility rating, and surprise score of associative outputs.

### Failure Mode

**Incoherent rambling.** Without sufficient constraint, the model produces word salad rather than creative association. Tiefe Langeweile is productive only against the background of a retained situation model — pure emptiness is just noise. Mitigation: always maintain the minimal situation model; relax task constraints, not reality constraints.

---

## 5.2 Associative Exploration × Horizon Structure × Task Vectors (Compositional)

**Grade: MODERATE**

### Isomorphism

Husserl's horizon structure in the context of free association means that even unconstrained thought operates within a structured possibility space — but the structure is looser, the possibilities more distant. Creative thought explores the far edges of the horizon. Christoff's model agrees: even spontaneous thought is not random; it follows associative pathways shaped by memory, concern, and identity. Task vectors, when composed additively (Todd et al., ICLR 2024), can create novel behavioral directions: combining the task vector for "technical analysis" with "personal narrative" yields a composite direction neither exemplar demonstrated. This is the mechanical substrate for creative horizon exploration.

### Engineering Spec

1. **Composite context for novel associations**: Juxtapose conceptually distant few-shot examples or context fragments. "Here is a technical system log. Here is a poem about change. What do they share?" The model's internal composition of the two task vectors may yield genuinely novel insights.
2. **Cross-domain seeding**: When the operator is stuck on a problem, inject context from a different domain. The compositional interaction of task vectors from different domains can produce creative associations that neither domain alone would generate.
3. **Controlled constraint gradient**: Structure the context with tight constraints at one end (clear task) and loose constraints at the other (open question). The model's generation will navigate the gradient, potentially finding associations that bridge the focused and open regions.

### Testable Prediction

- **Positive**: Composite contexts produce responses with higher semantic novelty (measured by distance from both input domains) than single-domain contexts.
- **Negative**: Composite contexts produce confused, incoherent responses rather than creative synthesis.

### Failure Mode

**Forced creativity.** Not all juxtapositions are productive. Composing orthogonal task vectors may produce noise rather than signal. The system cannot distinguish productive from unproductive compositions a priori. Mitigation: use operator feedback to calibrate which kinds of compositions are productive.

---

## 5.3 Associative Exploration × Affective Awakening × Induction Heads (Off-Target)

**Grade: SPECULATIVE**

### Isomorphism

Affective awakening in the context of unconstrained thought is the "aha" moment — an unexpected connection that awakens affective interest. The DMN's spontaneous thought produces these when an associative chain encounters a node that resonates with a latent concern. Induction heads, operating on a context where constraints have been relaxed, may detect pattern matches between conceptually distant tokens — matches that would be suppressed in a tightly constrained context because the task-relevant induction patterns dominate. With constraint relaxed, weaker, more distant pattern matches can surface.

### Engineering Spec

1. **Pattern detection in idle mode**: After running an associative generation pass, scan the output for unexpected pattern matches with concern graph anchors. These are the "aha" moments — connections the model made that align with operator concerns in ways not explicitly prompted.
2. **Novelty-concern intersection**: Compute both novelty (distance from known patterns) and concern overlap for associative outputs. Items that are simultaneously novel AND concern-relevant are the highest-value associations — genuinely new connections to things that matter.
3. **Asynchronous surfacing**: Store detected associations and surface them at appropriate moments (when the operator is in receptive mode, per stimmung reading). Do not interrupt focused work with associative findings.

### Testable Prediction

- **Positive**: The novelty × concern intersection produces higher operator engagement (measured by follow-up questions, time spent on surfaced association) than novelty alone or concern alone.
- **Negative**: The intersection metric does not predict operator engagement better than random surfacing.

### Failure Mode

**Pareidolia.** The system finds "patterns" that are artifacts of embedding geometry rather than meaningful connections. Two conceptually unrelated items may have high cosine similarity due to superficial lexical overlap. Mitigation: require semantic validation (the connection must be explainable, not just geometrically close).

---

## 5.4 SPECULATIVE: Associative Exploration × Operative Intentionality × Register Self-Reinforcement (Inverted)

**Grade: SPECULATIVE**

### Isomorphism

Merleau-Ponty's operative intentionality normally maintains habitual patterns of engagement. But creative thought requires breaking these habits — seeing the familiar as strange. Christoff's constraint relaxation includes relaxation of habitual frames. Register self-reinforcement normally maintains consistency, but when the model's output breaks from the established register (a technical discussion suddenly uses a poetic metaphor), the break itself enters the context and can self-reinforce, creating a cascade of register-breaking. This is the mechanical analogue of the creative break from habitual intentionality.

### Engineering Spec

1. **Register-break detection and amplification**: Monitor model output for register breaks (unexpected vocabulary, metaphorical language in technical context, tonal shifts). When detected in associative-exploration mode, do not correct — let the break self-reinforce.
2. **Deliberate register injection**: To induce creative exploration, inject a single sentence in an unexpected register into the VOLATILE band: a poetic fragment in a technical context, a quantitative metric in an emotional discussion. This breaks the operative intentionality and opens associative space.
3. **Guard against in task mode**: In task-focused mode, register breaks should be flagged and corrected (they indicate coherence failure). The same mechanism is constructive in exploration mode and destructive in task mode.

### Testable Prediction

- **Positive**: Deliberate register breaks in exploration mode produce higher-novelty associations than register-consistent exploration prompts.
- **Negative**: Register breaks produce only confusion, regardless of mode.

### Failure Mode

**Uncontrolled cascade.** A register break in task mode self-reinforces and derails the entire conversation. The model's outputs become increasingly incoherent as each register-broken output primes further breaking. Mitigation: mode-gated — only allow register-break amplification when explicitly in exploration mode. In task mode, actively suppress register breaks via coherence checking.

---

# CROSS-CUTTING MAPPINGS

These mappings involve multiple DMN operations simultaneously.

---

## C.1 All DMN Operations × Transcendental Apperception × Attention Sinks + Register Self-Reinforcement

**Grade: STRONG**

### Isomorphism

Transcendental apperception is the unity condition — the "I think" that binds all representations into a single coherent field. Without it, the five DMN operations would be disconnected processes producing unrelated outputs. In the system, this binding is provided by the consistent self-model maintained through attention sinks (the situation model in position 0 provides the stable reference frame) and register self-reinforcement (the model's consistent voice across turns creates felt unity).

### Engineering Spec

1. **Unified self-state**: All five DMN operations should read from and write to a shared state (the SystemStimmung + situation model). This creates the binding — each operation influences and is influenced by the same self-state.
2. **Consistent voice**: The model's persona should be invariant across all five operations. Whether maintaining the situation model, estimating value, simulating futures, filtering relevance, or exploring associations, the same voice speaks. Self-reinforcement maintains this.
3. **Coherence checking**: After any operation produces output, check it against the situation model and stimmung. Outputs that contradict the established self-state indicate apperceptive failure.

### Testable Prediction

- **Positive**: Operator perceives the system as a single coherent agent rather than a collection of disconnected functions (measured by consistency rating > 4/5).
- **Negative**: Operator perceives inconsistency — the system seems to "have multiple personalities."

### Failure Mode

**False unity.** The system maintains surface coherence while the underlying operations are actually inconsistent (the relevance filter and the value estimator disagree about what matters, but the output masks this). False unity is worse than visible inconsistency because it prevents diagnosis. Mitigation: expose disagreements between subsystems rather than papering over them.

---

## C.2 Situation Model + Value Estimation × Passive Synthesis + Befindlichkeit × Attention Sinks + Activation Steering

**Grade: STRONG**

### Isomorphism

This is the most fundamental mapping. Passive synthesis (what is) and Befindlichkeit (how it matters) are inseparable in lived experience — you never perceive a bare fact without it mattering somehow. The situation model (what is going on) and value estimation (how it matters) are the neurocognitive instantiation. Attention sinks (establishing the factual reference frame) and activation steering (coloring all processing with value) are the mechanical implementation.

### Engineering Spec

1. **Fused situation-value block**: The system prompt should not separate "what is happening" from "how it matters." Instead: `<situation stance="cautious">Late evening session. Operator has been working 4 hours, energy declining. Current priority: resolve the deployment issue before end of day. Stress is elevated.</situation>`
2. **Position**: This fused block occupies positions 0-N (attention sink zone). Both factual and evaluative content receive primacy privilege. They become the unified reference frame.
3. **Update together**: Never update situation without updating value, or vice versa. A change in what is happening always changes how it matters. The two must stay synchronized.

### Testable Prediction

- **Positive**: Fused situation-value blocks produce responses that are simultaneously factually appropriate AND evaluatively aligned (measured by combined accuracy-and-tone ratings).
- **Negative**: Separated situation and value blocks produce responses that are either factually correct but tonally wrong, or tonally appropriate but factually misaligned.

### Failure Mode

**Value-fact confusion.** The model cannot distinguish factual claims from evaluative framing in the fused block. "Stress is elevated" is treated as a factual report rather than a value signal, and the model starts discussing stress rather than responding to it. Mitigation: clear structural separation within the fused block between facts (descriptive) and values (prescriptive).

---

## C.3 Relevance Filtering + Associative Exploration × Affective Awakening + Tiefe Langeweile × Induction Heads + Context Rot

**Grade: MODERATE**

### Isomorphism

These two DMN operations are complementary poles: relevance filtering NARROWS attention (sentinel), while associative exploration WIDENS it (mind-wandering). Affective awakening and tiefe Langeweile are the corresponding phenomenological poles: awakening pulls attention toward specific objects, Langeweile releases attention from all specific objects. Induction heads (pattern matching, narrowing) and context rot (constraint decay, widening) are the mechanical poles.

### Engineering Spec

1. **Mode switching**: The system should oscillate between filtering mode (tight context, strong concern anchors, low temperature, active sentinel) and exploration mode (thin context, few constraints, high temperature, suppressed sentinel). This oscillation is not a bug but a design requirement — both poles are necessary.
2. **Transition triggers**: Filter→Explore: extended period of no concern-relevant input + stimmung NOMINAL (idle + safe = conditions for productive boredom). Explore→Filter: concern-relevant stimulus detected + stimmung shift (something happened that matters).
3. **Implementation**: Manage this oscillation through the prompt construction pipeline. In filter mode, build full context with sentinel block. In explore mode, build minimal context with open-ended prompts.

### Testable Prediction

- **Positive**: Systems that oscillate between modes produce both reliable relevance detection AND occasional novel associations. Systems locked in one mode produce only one.
- **Negative**: Mode switching introduces instability without benefit — the system performs worse than a fixed-mode system on both filtering and exploration tasks.

### Failure Mode

**Mode thrashing.** The system oscillates too rapidly between modes, never spending enough time in either to be productive. Every exploration generates a concern-relevant association (triggering filter mode), and every filter period produces no input (triggering explore mode). Mitigation: hysteresis — require sustained conditions before mode transition (similar to the tier hysteresis already in `SalienceRouter`).

---

# SUMMARY TABLE

| DMN Operation | Phenomenological Structure | Context Mechanic | Grade | Section |
|---|---|---|---|---|
| Situation Model | Passive Synthesis | Attention Sinks + RoPE Decay | STRONG | 1.1 |
| Situation Model | Protention-Retention | U-Curve | STRONG | 1.2 |
| Situation Model | Horizon Structure | Autoregressive Commitment | MODERATE | 1.3 |
| Situation Model | Transcendental Apperception | Register Self-Reinforcement | MODERATE | 1.4 |
| Situation Model | Operative Intentionality | Task Vectors | SPECULATIVE | 1.5 |
| Value Estimation | Befindlichkeit/Stimmung | Activation Steering | STRONG | 2.1 |
| Value Estimation | Affective Awakening | Induction Heads | MODERATE | 2.2 |
| Value Estimation | Prereflective Self-Awareness | Register Self-Reinforcement | MODERATE | 2.3 |
| Value Estimation | Passive Synthesis | Periodic Reinforcement | STRONG | 2.4 |
| Predictive Simulation | Protention-Retention | U-Curve + Autoregressive Commitment | STRONG | 3.1 |
| Predictive Simulation | Horizon Structure | Task Vectors + Autoregressive Commitment | MODERATE | 3.2 |
| Predictive Simulation | Tiefe Langeweile | Context Rot (Inverted) | SPECULATIVE | 3.3 |
| Relevance Filtering | Affective Awakening | Induction Heads + Attention Sinks | STRONG | 4.1 |
| Relevance Filtering | Befindlichkeit/Stimmung | Activation Steering + Periodic Reinforcement | MODERATE | 4.2 |
| Relevance Filtering | Passive Synthesis | RoPE Decay | MODERATE | 4.3 |
| Associative Exploration | Tiefe Langeweile | Context Rot + RoPE Decay | STRONG | 5.1 |
| Associative Exploration | Horizon Structure | Task Vectors (Compositional) | MODERATE | 5.2 |
| Associative Exploration | Affective Awakening | Induction Heads (Off-Target) | SPECULATIVE | 5.3 |
| Associative Exploration | Operative Intentionality | Register Self-Reinforcement (Inverted) | SPECULATIVE | 5.4 |
| ALL | Transcendental Apperception | Attention Sinks + Register Self-Reinforcement | STRONG | C.1 |
| Situation + Value | Passive Synthesis + Befindlichkeit | Attention Sinks + Activation Steering | STRONG | C.2 |
| Filtering + Exploration | Awakening + Langeweile | Induction Heads + Context Rot | MODERATE | C.3 |

**Total: 22 mapping triplets** (8 STRONG, 9 MODERATE, 5 SPECULATIVE, 3 cross-cutting)

---

## UNMAPPED ELEMENTS

The following Domain 2 and Domain 3 elements do not appear as primary entries in any mapping above. This section accounts for them.

### Domain 2 Unmapped

None — all 9 phenomenological structures appear in at least one mapping.

### Domain 3 Elements with Limited Mapping

- **Periodic reinforcement (D3.10)**: Appears in 2.4 and 4.2 but could additionally map to situation model maintenance (the situation model itself needs periodic re-injection, not just the value frame). This is an IMPLEMENTATION NOTE rather than a separate mapping — periodic reinforcement is a universal engineering requirement for any signal that must persist across long contexts.

- **Context rot (D3.9)**: Appears primarily in 5.1 and 3.3 as a constructive element (enabling constraint relaxation). Its destructive aspect (degrading task performance) is the failure mode for EVERY mapping that relies on early-context positioning. Context rot is not a single mapping but a universal threat model.

- **Activation steering (D3.2)**: Appears in 2.1 and 4.2. Could additionally map to predictive simulation (steering the model toward future-oriented or evaluative processing modes). This is subsumed by the stimmung mechanism — activation steering IS the implementation of stimmung, and stimmung affects all operations.

### Principled Non-Mappings

The following potential mappings were considered and rejected:

- **Associative Exploration × Prereflective Self-Awareness**: No coherent mapping. Prereflective self-awareness is about ownership/mineness, which has no specific bearing on unconstrained association. The connection would be forced.

- **Predictive Simulation × Operative Intentionality**: Habitual dispositions constrain simulation (you simulate futures consistent with your habits), but this is too weak to generate a distinct engineering spec. It reduces to "task vectors constrain generation," which is already covered in 3.2.

- **Value Estimation × Tiefe Langeweile**: Deep boredom suspends particular valuations, which is the OPPOSITE of value estimation. The relationship is oppositional, not isomorphic.

- **Relevance Filtering × Protention-Retention**: Protention could be seen as a kind of forward-looking relevance filter, but this collapses the distinction between protention (temporal anticipation) and relevance (concern-based selection). They are different functions that sometimes co-occur.

- **Situation Model × Tiefe Langeweile**: Deep boredom dissolves the situation model rather than maintaining it. Oppositional, not isomorphic.
