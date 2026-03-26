# Accumulated Self-Generated Context: Effects on LLM Behavior

Research synthesis for DMN-analog continuous assessment architecture.
Date: 2026-03-25

---

## 1. Model Collapse from Recursive Self-Consumption

### Mechanism

When models are trained on their own outputs iteratively, they undergo **model collapse**: a degenerative process where the model progressively forgets the tails of the true data distribution. Each generation smooths over rare patterns, and subsequent generations amplify this smoothing until the output converges on a narrow, bland center of the distribution (Shumailov et al., Nature 2024).

The process has two phases:
- **Early phase**: loss of variance in the tails; rare but valid outputs disappear
- **Late phase**: convergence to a degenerate distribution; outputs become repetitive and nonsensical

### Positive Effects
- None observed in pure recursive training. The mechanism is uniformly degenerative.

### Negative Effects
- Irreversible loss of distributional coverage
- Decreasing lexical, syntactic, and semantic diversity across generations
- Especially destructive for creative and open-ended tasks
- By April 2025, 74%+ of new web content was AI-generated, accelerating contamination risk

### Mitigations
- **Data accumulation, not replacement**: Mixing synthetic data with real data at each generation avoids collapse entirely (Gerstgrasser et al., 2024, "Is Model Collapse Inevitable?")
- **Synthetic data verification**: Filtering synthetic outputs against quality criteria before reuse (arXiv 2510.16657)
- **Provenance tracking**: Tagging synthetic vs. real data to maintain mixture ratios

### Critical distinction for DMN architecture
Model collapse applies to **training** on self-generated data. Inference-time self-consumption (reading your own outputs in context) is a different regime. The mechanism is attention-based rather than gradient-based, which changes the dynamics substantially. However, analogous distributional narrowing does occur at inference time (see Diversity Collapse, section 11).

**Sources:**
- [Shumailov et al. (2024), Nature](https://www.nature.com/articles/s41586-024-07566-y)
- [Gerstgrasser et al. (2024), "Is Model Collapse Inevitable?"](https://arxiv.org/abs/2404.01413)
- [Synthetic Data Verification](https://arxiv.org/html/2510.16657v1)

---

## 2. Echo Chamber and Self-Reinforcing Bias

### Mechanism

When LLMs process context that contains their own prior outputs, they exhibit **confirmatory bias amplification**. The model treats its own prior statements as evidence, increasing the probability of generating consistent-but-potentially-wrong continuations. This is structurally identical to the echo chamber effect observed in conversational search systems (Sharma et al., CHI 2024).

The effect is compounded by a **context-poisoning** mechanism: early statements in context disproportionately shape later generation, creating a feedback loop where the model amplifies subtext embedded in its own prior outputs (NeuralTrust, "Echo Chamber" jailbreak research).

### Positive Effects
- Consistency: the model maintains a stable perspective across turns
- Coherence: outputs are internally self-consistent

### Negative Effects
- Opinion polarization: models drift toward extreme positions when processing their own opinionated outputs
- Reduced information diversity: the model stops exploring alternative framings
- Vulnerability to early errors: incorrect early assessments become entrenched

### Mitigations
- **Adversarial self-challenge**: Periodically inject counter-perspectives or "are you sure?" probes (though note: LLMs lack true metacognition and treat these as just another input)
- **Multiple independent assessments**: Generate assessments from fresh contexts rather than cumulative ones
- **Structured disagreement fields**: Force the assessment format to include explicit uncertainty and alternative interpretations

**Sources:**
- [Sharma et al. (2024), "Generative Echo Chamber?" CHI](https://dl.acm.org/doi/10.1145/3613904.3642459)
- [NeuralTrust, "Echo Chamber" context-poisoning](https://neuraltrust.ai/blog/echo-chamber-context-poisoning-jailbreak)
- [Gravity Well Echo Chamber Modeling](https://arxiv.org/pdf/2509.03832)

---

## 3. Iterative Self-Refinement (Positive Case)

### Mechanism

Self-Refine (Madaan et al., 2023) demonstrates that LLMs can iteratively improve outputs by generating feedback on their own work and incorporating it. The loop is: GENERATE -> FEEDBACK -> REFINE -> FEEDBACK -> REFINE. No additional training is required; the same model serves as generator, critic, and refiner.

### Positive Effects
- ~20% absolute improvement in task performance on average across evaluated tasks
- Early iterations yield the largest gains
- Quality generally keeps improving with more iterations (diminishing returns, but no observed degradation up to tested limits)
- Human evaluators consistently prefer iteratively refined outputs

### Negative Effects
- Token cost scales linearly with iterations
- The model can get stuck in local optima (refining surface features without addressing structural issues)
- Feedback quality is bounded by the model's own capability ceiling

### Optimal Cycle Count
- 2-4 refinement cycles capture most of the benefit
- Beyond 4 cycles, improvement is marginal for most tasks
- EVOLVE framework (2025) shows that training specifically for self-refinement capability can extend the useful range

### Critical distinction for DMN architecture
Self-Refine operates on a **single artifact** with explicit feedback. The DMN architecture accumulates **many small assessments** over time. These are structurally different: Self-Refine converges on a better version of one thing; accumulated micro-assessments build a longitudinal picture. The convergence dynamics will differ.

**Sources:**
- [Madaan et al. (2023), "Self-Refine"](https://arxiv.org/abs/2303.17651)
- [EVOLVE framework](https://arxiv.org/html/2502.05605v3)

---

## 4. Self-Play and Adversarial Self-Improvement

### Mechanism

Self-Play Fine-Tuning (SPIN) uses the model as both player and opponent across training iterations. The current model tries to distinguish between human-written text and its own outputs, creating an adversarial dynamic that drives improvement without external annotation (Chen et al., 2024).

### Positive Effects
- Significant benchmark improvements without external supervision
- Outperforms DPO with GPT-4 preference data in some settings
- Strong universality across architectures and model families
- Particularly effective for long-context capabilities (SPELL framework)

### Negative Effects
- Requires careful iteration control; unbounded self-play can degenerate
- The model can overfit to its own failure modes rather than developing genuine capability
- Effectiveness depends on task structure (works best where there is a clear win/loss signal)

### Relevance to DMN
Self-play suggests that **structured opposition** between assessments (small model generates assessment, large model challenges it) could be beneficial. But this requires explicit adversarial structure, not passive accumulation.

**Sources:**
- [Chen et al. (2024), "Self-Play Fine-Tuning (SPIN)"](https://arxiv.org/abs/2401.01335)
- [SPELL: Self-Play for Long-Context](https://arxiv.org/html/2509.23863)
- [Self-Playing Adversarial Language Game, NeurIPS 2024](https://proceedings.neurips.cc/paper_files/paper/2024/file/e4be7e9867ef163563f4a5e90cec478f-Paper-Conference.pdf)

---

## 5. Chain-of-Thought Accumulation and Error Propagation

### Mechanism

As reasoning chains lengthen, errors in intermediate steps accumulate and compound. When reasoning depth exceeds model capacity, performance **degrades rather than improves** -- a phenomenon distinct from the general benefit of chain-of-thought for shorter reasoning tasks. This constitutes a hard ceiling on useful reasoning depth.

### Positive Effects
- Short-to-medium CoT chains (2-8 steps) reliably improve reasoning quality
- Self-consistency (majority voting over multiple chains) further improves performance

### Negative Effects
- Errors in intermediate steps propagate forward with no self-correction mechanism
- Excessive reasoning depth overwhelms the context window, degrading comprehension
- Generated reasoning chains can contain factual errors, logical fallacies, and accumulated errors leading to incorrect conclusions
- CoT can actually **reduce** performance on tasks where explicit thinking makes humans worse (Sprague et al., 2024)

### Mitigations
- **Recursive decomposition with propagation filtering**: The Knowledge Propagation Module (KPM) filters weak/redundant thoughts while propagating strong ones
- **Validation checkpoints**: Incremental verification at each step prevents early errors from cascading
- **Self-consistency**: Majority voting over multiple reasoning paths
- **Contrastive learning**: Auto-CCoT generates valid/invalid reasoning pairs to train models away from common errors

### Optimal Chain Length
- 2-8 steps for most tasks
- Diminishing returns beyond 8 steps
- Active degradation beyond model-specific thresholds (varies by model size)

**Sources:**
- [Wei et al. (2022), "Chain-of-Thought Prompting"](https://arxiv.org/abs/2201.11903)
- [Sprague et al. (2024), "Mind Your Step"](https://arxiv.org/html/2410.21333v1)
- [Long CoT reasoning research](https://github.com/LightChen233/Awesome-Long-Chain-of-Thought-Reasoning)

---

## 6. Scratchpad and Persistent Working Memory

### Mechanism

Scratchpads provide LLMs with explicit working memory by storing intermediate computations in the context. Three architectural patterns have emerged:

1. **Sequential scratchpad**: Results appended after input (classic CoT)
2. **Interleaved self-notes**: Model deviates from input at any point to write reasoning notes (Lanchantin et al., 2023)
3. **Structured memory layers**: Episodic memory + working memory + scratchpad (LIGHT framework)

### Positive Effects
- Dramatically improves multi-step computation ability
- Prevents "catastrophic amnesia" in long-running sessions
- Self-notes (interleaved reasoning) outperform both CoT and sequential scratchpads by allowing reasoning at the point of relevance rather than at the end
- MemGPT-style working context enables management of information beyond fixed context windows

### Negative Effects
- Consumes context window capacity, creating pressure on what else can fit
- Stale scratchpad content can mislead if not pruned
- Semantic decay occurs in compressed/summarized scratchpad content over time

### Key finding for DMN architecture
The **self-notes** approach (Lanchantin et al.) is the most relevant precedent. It demonstrates that interleaving reasoning with input -- rather than appending it -- produces better results. This suggests the DMN's micro-assessments should be **interleaved with sensory data** rather than accumulated in a separate buffer.

**Sources:**
- [Nye et al. (2021), "Show Your Work: Scratchpads"](https://arxiv.org/abs/2112.00114)
- [Lanchantin et al. (2023), "Self-Notes"](https://arxiv.org/abs/2305.00833)
- [MemGPT](https://readwise-assets.s3.amazonaws.com/media/wisereads/articles/memgpt-towards-llms-as-operati/MEMGPT.pdf)
- [LIGHT framework memory layers](https://arxiv.org/pdf/2510.27246)

---

## 7. Hallucination Snowballing

### Mechanism

The **snowball effect** (Zhang & Press, 2023): once an LLM generates an incorrect claim, it over-commits to that claim in subsequent tokens. The autoregressive architecture means each token conditions on all previous tokens including errors. The model then generates **additional** false claims to justify the initial error -- claims it would separately recognize as incorrect if encountered in isolation.

Key finding: ChatGPT can identify 67% and GPT-4 can identify 87% of their own hallucinated claims when those claims are presented independently, but fail to catch them when they appear in the model's own generation chain.

### Positive Effects
- None. This is a pure degradation mechanism.

### Negative Effects
- Errors compound exponentially rather than linearly
- Models generate novel false claims to support earlier false claims
- The phenomenon extends to multimodal models (Zhong et al., ACL 2024)
- No built-in self-correction mechanism in autoregressive generation

### Mitigations
- **External verification at each step**: Cross-check generated claims against grounded sources
- **Attention Causal Decoding**: Modified attention patterns that reduce over-commitment to early tokens
- **Separate verification passes**: Use independent model calls to verify claims rather than relying on in-context self-consistency

### Critical implication for DMN architecture
If a small model generates an incorrect micro-assessment at time T, and that assessment remains in context at T+1, T+2, ... T+N, the large model consuming these assessments will be vulnerable to snowballing. **Incorrect early assessments will be treated as evidence and built upon.** This is the single most dangerous failure mode for accumulated self-context.

**Sources:**
- [Zhang & Press (2023), "How Language Model Hallucinations Can Snowball"](https://arxiv.org/abs/2305.13534)
- [Zhong et al. (2024), "Multimodal Hallucination Snowballing", ACL](https://aclanthology.org/2024.acl-long.648/)
- [Comprehensive Hallucination Survey](https://arxiv.org/html/2510.06265v2)

---

## 8. Confidence Calibration Drift

### Mechanism

LLMs are **systematically overconfident**. Nominal 99% confidence intervals cover the true answer only 65% of the time. This overconfidence is structural: maximum-likelihood training produces reasonable calibration, but RLHF/reward optimization induces overconfidence. When models process repeated information (including their own prior outputs), calibration degrades further -- the model becomes more confident, not more accurate.

LLMs lack genuine metacognition. When asked "are you sure?", the model does not consult an internal confidence meter -- it treats the question as another input to respond to, often doubling down on its previous answer.

### Positive Effects
- None for calibration specifically. Overconfidence is uniformly problematic.

### Negative Effects
- Confidence and accuracy decouple as context accumulates
- Repeated exposure to the same claim (including self-generated repetitions) increases confidence without increasing accuracy
- The Dunning-Kruger effect has been documented in LLMs: lower capability correlates with higher expressed confidence

### Mitigations
- **TH-Score**: A metric that penalizes overconfident errors and rewards calibrated successes
- **Consistency-based confidence**: Use agreement across multiple independent samples as a confidence proxy rather than self-reported confidence
- **External calibration**: Periodically inject known-difficulty items to calibrate the system's confidence estimates

### Implication for DMN architecture
If the small model generates assessments with confidence scores, those scores will drift upward over time as the model processes its own prior high-confidence outputs. **Never use self-reported confidence from accumulated context as a signal for routing decisions.** Use inter-assessment consistency instead.

**Sources:**
- [LLMs are Overconfident (FermiEval)](https://arxiv.org/html/2510.26995v1)
- [Mind the Confidence Gap](https://arxiv.org/html/2502.11028v3)
- [Dunning-Kruger Effect in LLMs](https://arxiv.org/html/2603.09985)
- [Certainty Robustness](https://arxiv.org/html/2603.03330)

---

## 9. Context Rot

### Mechanism

**Context rot** (Chroma Research, 2025): LLM performance degrades measurably and continuously as input context length increases, even on trivial tasks like retrieval and text replication. The degradation is driven by three compounding mechanisms:

1. **Lost-in-the-middle effect**: Models attend well to the start and end of context but poorly to the middle, causing 30%+ accuracy drops for mid-context information
2. **Attention dilution**: Transformer attention is quadratic; 100K tokens means 10 billion pairwise relationships competing for attention weight
3. **Distractor interference**: Semantically similar but irrelevant content actively misleads the model

A model with a 200K token window can exhibit significant degradation at 50K tokens. The decline is continuous, not a cliff.

### Positive Effects
- Recency bias means the most recent information is attended to most strongly, which can be beneficial if the most recent assessment is also the most relevant

### Negative Effects
- Older assessments in context are progressively ignored or misattended
- Semantically similar assessments (which micro-assessments from the same domain will be) increase distractor interference
- Performance degrades non-uniformly and unpredictably across models

### Mitigations
- **Keep context tight**: Ruthlessly prune old/redundant context
- **Recency-weighted placement**: Put the most critical information at the start and end of context
- **Semantic deduplication**: Remove assessments that are informationally redundant with newer ones
- **Summarization with provenance**: Replace old assessment sequences with summaries, but track what was compressed

### Optimal Context Size
No universal answer. Empirically: degradation begins around 25-30% of nominal context window capacity for most models, with significant degradation by 50%.

**Sources:**
- [Chroma Research, "Context Rot"](https://research.trychroma.com/context-rot)
- [Understanding AI, "Context Rot: The Emerging Challenge"](https://www.understandingai.org/p/context-rot-the-emerging-challenge)
- [Stable Long-Term Memory: Decay, Drift, and Continuity](https://medium.com/@frederick-smith/persistent-llm-memory-decay-drift-continuity-93b1db4bcdb2)

---

## 10. Recursive Summarization Information Loss

### Mechanism

When accumulated context is periodically summarized and the summary replaces the original content, each summarization cycle loses fine-grained detail. The loss is **non-uniform**: rare, surprising, or counterintuitive details are lost first (because they have low prior probability in the summarizer's output distribution), while common, expected patterns are preserved. This is structurally identical to the model collapse mechanism but operating at inference time.

### Positive Effects
- Keeps context within manageable bounds
- Preserves the gist of accumulated information
- Enables arbitrarily long temporal coverage

### Negative Effects
- Fine-grained detail is irreversibly lost
- Surprising or anomalous observations (often the most valuable for situation assessment) disappear first
- Each layer of recursive summarization compounds the loss
- Models can invent novel compression strategies that introduce artifacts (e.g., switching languages to increase information density per token)

### Mitigations
- **Accumulate, don't replace**: Keep original assessments alongside summaries as long as context budget permits
- **Anomaly-preserving summarization**: Explicitly instruct the summarizer to preserve surprising/anomalous observations
- **Hierarchical summarization with retrieval**: Maintain multiple temporal granularities with the ability to retrieve originals

**Sources:**
- [Recursive summarization for long-term dialogue memory](https://arxiv.org/abs/2308.15022)
- [Compression vs. Full-Text in Multi-Document Summarization](https://arxiv.org/html/2502.06617v1)
- [Recursive Language Models](https://www.primeintellect.ai/blog/rlm)

---

## 11. Semantic Drift and Diversity Collapse

### Mechanism

Two related phenomena occur during sustained generation:

**Semantic drift**: The model's outputs gradually deviate from the original topic or intent. Fixed-window attention mechanisms are effective over short contexts but fail to maintain coherence over extended discourse. This manifests as gradual topic wandering, inconsistency in claims, and reduced groundedness.

**Diversity collapse**: Instruction-tuned models internalize structural templates from training, producing overly deterministic outputs. Diversity collapse persists even under high-temperature sampling -- temperature alone does not solve it. Once repetitive patterns emerge, the attention mechanism creates a positive feedback loop that makes recovery difficult.

### Positive Effects
- Short-term consistency (the model stays on topic within a single generation)

### Negative Effects
- Gradual topic drift over extended multi-turn interactions
- Identity fragmentation during context handoffs
- Repetitive structural patterns even with high temperature
- Attention feedback loops that lock in repetitive behavior

### Mitigations
- **Verbalized Sampling**: Prompt the model to explicitly generate a probability distribution over responses before selecting one
- **Periodic re-grounding**: Re-inject the original task specification or ground-truth anchors
- **Format variation**: Deliberately vary the structural template of assessments to prevent template lock-in
- **Guided generation (G2)**: Use diversity-promoting decoding strategies

**Sources:**
- [Semantic Coherence Dynamics in LLMs](https://advance.sagepub.com/users/849237/articles/1236372/master/file/data/2024/2024.pdf)
- [Diversity Collapse in LLMs](https://arxiv.org/html/2505.18949v1)
- [Verbalized Sampling](https://arxiv.org/html/2510.01171v1)
- [Repeat Curse in LLMs](https://arxiv.org/html/2504.14218v1)

---

## 12. Structured vs. Free-Form Self-Output

### Mechanism

Forcing structured output (JSON, tagged XML) degrades reasoning performance by 10-15% compared to free-form generation (Tam et al., 2024, "Let Me Speak Freely?"). The constraint channels attention toward format compliance at the expense of reasoning depth. Field ordering matters: putting the answer field first encourages premature commitment; putting reasoning first preserves step-by-step thinking.

### Positive Effects of Structured Output
- Parseable, consistent, machine-readable
- Enables downstream processing without ambiguity
- Forces explicit field coverage (the model must fill every field)

### Negative Effects of Structured Output
- 10-15% reasoning degradation
- Format compliance competes with content quality for model capacity
- Models can overfit to structural templates, reducing content diversity

### Optimal Approach
**Two-phase generation**: Free-form reasoning first, then structured extraction. This preserves reasoning quality while producing parseable output. Alternatively, use structured output with reasoning-first field ordering (reasoning field before conclusion field).

### Implication for DMN architecture
The small model's micro-assessments should use **structured format with reasoning-first field ordering**. The format should be consistent enough for parsing but include a free-form reasoning/observation field early in the structure. Avoid overly rigid schemas that leave no room for novel observations.

**Sources:**
- [Tam et al. (2024), "Let Me Speak Freely?"](https://medium.com/@michael.hannecke/beyond-json-picking-the-right-format-for-llm-pipelines-b65f15f77f7d)
- [Structured Output Benchmarks](https://cleanlab.ai/blog/structured-output-benchmark/)

---

## 13. Token Budget Allocation

### Mechanism

TALE (Token-Budget-Aware LLM Reasoning) demonstrates that reasoning token allocation should be **dynamic** based on problem complexity, not fixed. A 67% reduction in output tokens is achievable with negligible performance loss by matching token budget to task difficulty. SelfBudgeter and BudgetThinker extend this by having the model self-allocate token budgets.

For cascade architectures specifically: using a small model with self-consistency checking as a difficulty classifier, then escalating to a larger model only when needed, achieves comparable performance at 40% of cost.

### Positive Effects
- Massive cost reduction (40-67%) with maintained performance
- Forces the model to be concise, which can improve clarity
- Enables sustainable continuous operation

### Negative Effects
- Too-tight budgets degrade complex reasoning
- Budget prediction itself consumes tokens
- Self-imposed budgets can be miscalibrated (models underestimate difficulty)

### Optimal Allocation
- CoT with Self-Consistency (SC) is the most budget-efficient reasoning strategy across all tested datasets
- Dynamic allocation outperforms fixed allocation in all settings
- The optimal budget is problem-dependent, not fixed per cycle

**Sources:**
- [TALE: Token-Budget-Aware LLM Reasoning](https://arxiv.org/abs/2412.18547)
- [SelfBudgeter](https://arxiv.org/html/2505.11274v2)
- [BudgetThinker](https://arxiv.org/html/2508.17196v2)
- [OPTIMA: Multi-turn optimization](https://aclanthology.org/2025.findings-acl.601.pdf)
- [LLM Cascades with Mixture of Thought](https://arxiv.org/abs/2310.03094)

---

## Synthesis: Predicted Effects on DMN Architecture

**Architecture under analysis**: A small model generates structured micro-assessments every 5 seconds. These accumulate in a context window periodically consumed by a large model for situation modeling, value estimation, relevance filtering, and response generation.

### a) Situation Model Accuracy

**Predicted trajectory**: Initially improves (0-60s, ~12 assessments), then plateaus, then degrades.

- **Positive phase**: Each new assessment adds genuine observational data. The large model builds a richer situation model with more temporal coverage.
- **Plateau**: Redundant assessments add noise without new information. Context rot begins degrading attention to older-but-relevant observations.
- **Degradation phase**: Hallucination snowballing from any early incorrect assessment. Echo chamber effects entrench the initial framing. Lost-in-the-middle effect causes mid-window assessments to be ignored.

**Optimal window**: 30-90 seconds of assessments (~6-18 entries), with older entries replaced by anomaly-preserving summaries.

### b) Value Estimation Stability

**Predicted trajectory**: Stabilizes briefly, then drifts toward overconfidence.

- Values estimated from accumulated self-context will be **more stable** than single-shot estimates (averaging effect over multiple observations).
- However, confidence calibration will drift upward: the model sees many assessments agreeing with each other (because they were generated by the same model with the same biases), interpreting consensus as evidence.
- **Risk**: Value estimates become confidently wrong rather than appropriately uncertain.

**Mitigation**: Use inter-assessment **variance** as the confidence signal, not self-reported confidence. Periodically inject null/baseline assessments to anchor the scale.

### c) Relevance Filtering Precision

**Predicted trajectory**: Improves initially, then narrows pathologically.

- Early accumulation helps the model identify what matters by providing temporal context.
- Over time, the echo chamber effect causes the relevance filter to increasingly select for assessments that confirm the existing model, filtering out genuinely novel observations.
- Diversity collapse in the small model's assessments means the relevance filter has less diverse input to work with over time.

**Mitigation**: Vary the small model's assessment prompts across cycles. Include a "what is surprising or unexpected" field that is structurally privileged in the schema.

### d) Hallucination Risk

**Predicted trajectory**: Increases monotonically with accumulated context length.

- Each micro-assessment has a base hallucination rate. Because the large model cannot distinguish small-model hallucinations from accurate observations, hallucinated claims accumulate.
- The snowball effect means a single hallucinated assessment can corrupt the entire situation model.
- Context rot makes it harder for the large model to cross-reference early vs. late assessments for consistency.

**Mitigation**: This is the critical design constraint. Options:
1. **Independent verification**: Each micro-assessment includes a self-consistency check (generate twice, flag disagreement)
2. **Anomaly flagging**: Mark assessments that contradict the running summary for explicit re-evaluation
3. **Temporal decay**: Weight recent assessments exponentially higher than older ones
4. **Hard context limits**: Never accumulate more than N assessments without summarization and pruning

### e) Register/Personality Consistency

**Predicted trajectory**: Stable within a session, but vulnerable to gradual drift.

- The small model's register will remain consistent within its own generation (it sees the same system prompt each time).
- The large model consuming accumulated assessments will be influenced by the small model's register, potentially causing register bleed (the large model's outputs start sounding like the small model's assessments).
- Over many cycles, semantic drift can cause subtle personality shifts that accumulate beyond the detection threshold.

**Mitigation**: The large model's system prompt should explicitly establish its own register independent of the assessment content. Assessments should be marked with clear structural delimiters (e.g., `<assessment>` tags) to prevent register bleed.

---

## Design Recommendations for DMN Architecture

Based on the full body of research:

### 1. Context Window Management (highest priority)
- **Hard cap at 30-90 seconds of raw assessments** (~6-18 entries at 5s intervals)
- Beyond that, summarize with explicit anomaly preservation
- Place summaries at the START of context, recent raw assessments at the END (exploiting recency bias and primacy effects, avoiding lost-in-the-middle)

### 2. Assessment Format
- **Structured with reasoning-first field ordering**
- Schema: `observation` (free-form) -> `interpretation` (free-form) -> `salience` (structured) -> `confidence` (structured) -> `contradicts_prior` (boolean + reference)
- Include a mandatory `surprising` field to counteract diversity collapse
- Vary prompt templates across cycles to prevent structural repetition lock-in

### 3. Error Containment
- **Never let the small model see its own prior assessments** (breaks the self-feeding loop at the source)
- Each assessment should be generated from fresh sensory input + system prompt only
- The accumulation happens in the large model's context, not the small model's
- Include independent consistency checks: if assessment N contradicts assessment N-2, flag explicitly

### 4. Confidence Architecture
- **Do not use self-reported confidence** from either model
- Use inter-assessment variance as the confidence proxy
- Track assessment-to-assessment delta magnitude; sudden large deltas indicate either genuine change or hallucination -- either way, they demand attention

### 5. Anti-Drift Mechanisms
- Re-inject ground-truth anchors (sensor baselines, known states) every K cycles
- Periodically clear accumulated context and restart from summary-only (prevents unbounded context rot)
- Maintain the large model's register through explicit system prompt re-assertion, not through accumulated context consistency

### 6. Optimal Cycle Architecture
- Small model: **memoryless** (no self-context, fresh each cycle, structured output)
- Accumulation buffer: **append-only with pruning** (managed externally, not by either model)
- Large model: **periodic consumption** (not every cycle; every 3-6 cycles, consuming the buffer with summaries)
- Summarizer: **separate from both models** if possible, or at minimum a separate call with explicit anomaly-preservation instructions
