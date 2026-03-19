# Epistemic Audit: Conversational Continuity Design

**Date**: 2026-03-19
**Purpose**: Honest assessment of what is grounded, what is transferred, what is novel, and what is hoped for in the conversational continuity design.

---

## Classification: KNOW / BELIEVE / HOPE

### KNOW (empirically validated, directly applicable)

| Claim | Evidence | Source |
|-------|----------|--------|
| Context rot degrades LLM performance with increasing input | 39% average drop across 18 frontier models; architectural, not solvable by training | Chroma Research 2025-2026 |
| Positional bias follows U-curve (attend to beginning + end, not middle) | Replicated across models and tasks; >30% accuracy drop in middle | Liu et al., Stanford/TACL 2024 |
| Conversational silence >400ms creates perceived awkwardness | Replicated psycholinguistic finding | Twilio 2025, Trillet benchmarks |
| Episodic memory retrieval improves task accuracy | 26% higher accuracy vs OpenAI memory (LOCOMO benchmark) | Mem0 arXiv 2504.19413 |
| LLMs are significantly worse than humans at grounding | 3x less likely to initiate clarification, 16x less likely to follow up | Shaikh et al., ACL 2025 (Microsoft Rifts) |

### BELIEVE (plausible transfer, not validated for our context)

| Claim | Basis | Gap |
|-------|-------|-----|
| Clark's grounding theory applies to human-LLM conversation | Theory well-established for human-human; emerging evidence shows it applies *differently* to human-AI | No validated transfer model; LLMs ground differently (arXiv 2601.19792) |
| Stable system prompt position exploits primacy bias to counteract context rot | Combines two validated phenomena (position bias + degradation) | Not tested as an integrated claim |
| Active inference provides the right theoretical lens for conversation design | FEP is a mathematical principle, not an empirical claim; specific derived models can be tested | No specific derivation for "conversation continuity through stable context"; potentially unfalsifiable |
| Three-layer memory architecture produces continuity | Industry consensus pattern (Mem0, MemGPT, Redis AI) | Only utility metrics measured; "continuity of identity" is a phenomenological claim without empirical backing |

### HOPE (novel, burden of proof entirely on us)

| Claim | Status | Risk |
|-------|--------|------|
| Numeric salience signals (activation=0.78) produce proportional self-modulation in LLM responses | Adjacent research: LLMs can monitor activations along specific learned directions (NeurIPS 2025). But our mechanism (formatted numbers in context) is untested. | Model may threshold, ignore, or attend inconsistently |
| Concern graph produces meaningful conversational priority | Entirely novel; no prior art found | No external validation; no measurement protocol defined |
| "Phenomenal context" (Husserlian temporal bands) is a coherent construct for AI orientation | Term does not exist in the literature; our invention | No external definition, validation, or critique |
| Conversation thread summary preserves Clark-style common ground | Our design; borrows Clark's vocabulary but implements something categorically different (unidirectional injection, not bidirectional collaboration) | May produce *anchoring* without producing *grounding* |

---

## Vocabulary Mismatches Identified

| We say | Clark/theory says | The actual mechanism |
|--------|-------------------|---------------------|
| "Grounding" | Bidirectional collaborative mutual understanding with uptake signals | Unidirectional context injection at a privileged position |
| "Conversational frame" | Shared generative model negotiated by both parties | Static system prompt rebuilt per turn |
| "Repair" | Collaborative recovery from breakdown with initiation + completion | Silence avoidance via bridge phrase (prevents repair need, doesn't perform repair) |
| "Episodic memory" | Lived experience recalled with temporal, emotional, contextual markers | Vector-stored text summary retrieved by embedding similarity |
| "Identity continuity" | Phenomenological experience of persistent self across time | Database retrieval of prior session summary |

These mismatches are not bugs in the design — the engineering works. But the theoretical framing overstates the grounding. The design should be honest about what it implements vs what the theories describe.

---

## Validation Infrastructure

### Existing Observability Stack

| Tool | What it gives us | How it supports proof |
|------|------------------|----------------------|
| **Langfuse** (:3000) | Per-LLM-call traces with I/O, latency, tokens, model, session grouping | Custom scores per turn (`hapax_score`), session-level evaluation, LLM-as-judge Live Evaluators, RAGAS integration for faithfulness |
| **Grafana** | Time-series dashboards, alerting | Trend visualization for conversation quality metrics; before/after phase markers |
| **PostgreSQL** | Structured audit data | Queryable experiment results; join with session tags for factorial analysis |
| **Qdrant** | Vector similarity search across 6 collections | operator-corrections = grounding failure log; operator-episodes = cross-session validation; probe question ground truth |
| **EventLog** | Structured events with session IDs, action types | Session lifecycle events; timing data; experimental condition tagging |
| **Perception state writer** | JSON snapshots every 2.5s (turn_phase, temperature, readiness) | Extensible for real-time conversation quality metrics; flows to Grafana |
| **Salience diagnostics** | Activation breakdowns per utterance | Correlation analysis: does activation predict response quality? |
| **ConversationalModel** | Temperature, engagement, turn count, tier history | Continuous operational quality signal; covariate for experiments |
| **Stimmung** | System health/stance | Controls for system pressure effects on conversation quality |

### Measurement Methods

#### 1. Operationalize hypotheses

Each claim → measurable prediction → null hypothesis → metric:

| Claim | Prediction | Null | Metric | Source |
|-------|-----------|------|--------|--------|
| Stable frame improves coherence | Cross-turn reference accuracy increases | Reference accuracy independent of frame presence | Reference accuracy score (LLM evaluator per turn) | Langfuse custom score |
| Salience injection causes self-modulation | Response length/depth correlates with activation score | Response properties independent of activation | Pearson correlation (activation, response_tokens) | Langfuse trace metadata |
| Episodic memory produces session continuity | Model references prior session content when relevant | Model never references prior sessions | Prior-session reference rate (boolean per turn) | LLM evaluator |
| Tool call suppression prevents contradiction | Zero self-contradiction events per tool-call turn | Contradiction rate unchanged | Contradiction detection (LLM evaluator) | Langfuse custom score |

#### 2. Experimental design (single-user)

**N-of-1 trial / SCED methodology** — designed for establishing effects in a single subject:

**ABAB Reversal Design:**
```
Phase A (baseline): 5+ sessions without component
Phase B (treatment): 5+ sessions with component
Phase A' (reversal): 5+ sessions without component (should degrade)
Phase B' (reinstatement): 5+ sessions with component (should improve again)
```
If metric improves during B phases and degrades during A phases, causation established.

**Multiple Baseline Design** (for multi-component system):
```
Week 1: baseline (nothing) — measure all metrics
Week 2: introduce stable frame only — grounding metrics should improve
Week 3: add episodic memory — session continuity metrics should improve
Week 4: add salience injection — self-modulation metrics should improve
```
Staggered onset establishes causation per component.

**Statistical methods:**
- Tau-U statistic (non-overlap measure, handles autocorrelation)
- Bayesian change-point detection
- Randomization tests (permute phase assignments)
- Visual analysis with phase boundary markers

#### 3. Interaction effects

**Build-up design** (15 conditions vs 32 for full factorial):
1. Nothing (baseline)
2. Each component alone (5 conditions)
3. Most promising pairs (3-5 pairwise, chosen by theory)
4. Full system (all components)
5. Remove one from full system (5 ablation conditions)

Fit linear model with interaction terms:
```
metric = β₀ + Σβᵢ(componentᵢ) + Σβᵢⱼ(componentᵢ × componentⱼ) + ε
```
Interaction terms reveal synergistic (super-additive) or antagonistic (sub-additive) effects.

#### 4. Operationalizing Clark's grounding mechanisms

For each of Clark's three mechanisms, a computational detector:

**Presentation** (introducing new information):
- LLM evaluator classifies each sentence: new_fact / opinion / proposal / question / elaboration
- Score: `presentation_count` per turn

**Acceptance** (listener signals understanding):
- LLM evaluator classifies response to prior turn: ACCEPT / CLARIFY / REJECT / IGNORE
- Score: `acceptance_type` (categorical), `grounding_success` (ACCEPT or CLARIFY = success)

**Evidence of understanding** (correct later reference):
- Track "grounded facts" (presented + accepted pairs)
- Check subsequent turns for correct/incorrect/missing references
- Score: `reference_accuracy` per turn, `grounding_completeness` per session

**Detection pipeline** (post-hoc on Langfuse traces, not in hot path):
```
Per turn:
  1. Classify: presentation / acceptance / reference (LLM evaluator)
  2. If presentation: add to grounded_facts buffer
  3. If acceptance: mark corresponding presentation as grounded
  4. If reference: check against grounded_facts for accuracy
  5. Push scores to Langfuse
  6. At session end: compute grounding_completeness
```

#### 5. Causal attribution (did it work for the reasons we think?)

Beyond "did it improve?" — "did it improve because of the mechanism we hypothesized?"

- **Ablation**: Remove component, measure if the SPECIFIC predicted metric degrades (not just any metric)
- **Correlation**: Does the injected signal (activation=0.78) actually correlate with the predicted outcome (response depth)? If correlation is flat, the mechanism isn't working as theorized.
- **Probe questions**: Sentinel facts in the stable frame. If the model retrieves them, the frame is being used. If not, the improvement comes from elsewhere.
- **Counterfactual testing**: Same utterance, same context, different salience scores. Does the response change in the predicted direction?

#### 6. Observer-accessible proof structure

Three audiences, three artifact types:

**For the operator** (subjective): Blind A/B comparisons, post-session Likert ratings (coherence, felt-understanding, naturalness), experience sampling over time.

**For the developer** (objective): Langfuse dashboards with grounding/coherence trends, statistical reports with effect sizes and credible intervals, automated evaluation logs with full reasoning.

**For external reviewers** (reproducible): Pre-registered hypotheses, raw Langfuse exports, analysis scripts, configuration snapshots per condition, evaluation prompts and judge model specifications.

```
proofs/
  claim-001-stable-frame/
    hypothesis.md          # Pre-registered prediction
    design.md              # ABAB design with conditions
    data/
      langfuse-export/     # Raw trace data
      session-tags.csv     # Which session had which config
      operator-ratings.csv # Subjective scores
    analysis/
      analysis.py          # Statistical analysis
      results.md           # Effect sizes, plots, credible intervals
    artifacts/
      transcripts/         # Representative conversation excerpts
      dashboards/          # Grafana snapshots
```

### Operational vs Research Metrics

**Always-on (production):**
- Turn latency, temperature, engagement, tier distribution (ConversationalModel)
- Grounding score (LLM-as-judge Live Evaluator, per turn)
- Context utilization (periodic probe questions)
- Error rate (Langfuse trace failures)

**Test sessions only (research):**
- Ablation deltas, interaction effects, position sensitivity
- Deep coherence evaluation (full transcript LLM analysis)
- Subjective ratings (operator Likert scales)
- Probe question accuracy (sentinel fact retrieval)

---

## Novel Components Requiring Validation

### 1. Salience signal injection
- **Hypothesis to test**: Injecting activation/novelty/concern scores into system prompt causes measurable correlation between scores and response properties (length, specificity, hedging, tool use probability)
- **Null hypothesis**: Response properties are independent of injected scores
- **Required**: Controlled experiment with varied scores on identical utterances

### 2. Concern graph priority
- **Hypothesis to test**: Concern graph anchors cause the model to prioritize topics that overlap with active concerns over topics that don't
- **Null hypothesis**: Topic prioritization is independent of concern overlap scores
- **Required**: A/B test with and without concern context injection

### 3. Phenomenal context orientation
- **Hypothesis to test**: Including temporal bands (stimmung, impression, protention) in context causes the model to reference temporal state appropriately ("you seem to be in flow" when flow score is high)
- **Null hypothesis**: Model ignores temporal band signals or uses them inconsistently
- **Required**: Ablation study removing phenomenal context layers

### 4. Stable frame vs volatile context separation
- **Hypothesis to test**: Separating stable thread from volatile environment reduces the "context skipping" the operator reports
- **Null hypothesis**: The separation has no measurable effect on cross-turn reference accuracy
- **Required**: Before/after measurement of cross-turn coherence with operator feedback

---

## References

### Empirical Studies (KNOW tier)
- Chroma Research (2025-2026). "Context Rot: How Increasing Input Tokens Impacts LLM Performance." https://research.trychroma.com/context-rot
- Liu et al. (2024). "Lost in the Middle: How Language Models Use Long Contexts." Stanford/TACL. https://cs.stanford.edu/~nfliu/papers/lost-in-the-middle.arxiv2023.pdf
- Shaikh et al. (2025). "Navigating Rifts in Human-LLM Grounding." ACL 2025. https://aclanthology.org/2025.acl-long.1016/
- Mem0 (2025). "Building Production-Ready AI Agents with Scalable Long-Term Memory." arXiv:2504.19413. https://arxiv.org/html/2504.19413v1

### Theoretical Frameworks (BELIEVE tier)
- Clark & Brennan (1991). "Grounding in Communication." https://web.stanford.edu/~clark/1990s/Clark,%20H.H.%20_%20Brennan,%20S.E.%20_Grounding%20in%20communication_%201991.pdf
- Friston et al. (2015). "Active inference, communication and hermeneutics." https://pmc.ncbi.nlm.nih.gov/articles/PMC4502445/
- Friston et al. (2020). "A World Unto Itself: Human Communication as Active Inference." https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2020.00417/full
- arXiv 2601.19792. "LVLMs and Humans Ground Differently in Referential Communication." https://arxiv.org/html/2601.19792

### Adjacent Research (informing novel components)
- Li & Xiong (2025). "LLMs Can Perform Metacognitive Monitoring of Their Own Internal Activations." NeurIPS 2025. arXiv:2505.13763
- arXiv 2602.01999. "Meta-Cognitive Activation in R1-Style LLMs."
- Liu et al. (2025). "Proactive Conversational Agents with Inner Thoughts." CHI 2025. https://dl.acm.org/doi/10.1145/3706598.3713760
- GetStream (2025). "How Do You Prevent Voice Gaps with Speculative Tool Calling?" https://getstream.io/blog/speculative-tool-calling-voice/
- arXiv 2601.19952. "LTS-VoiceAgent: Listen-Think-Speak Framework."
- Galbraith et al. (2024). "Analysis of Dialogue Repair in Voice Assistants." https://pmc.ncbi.nlm.nih.gov/articles/PMC11586770/

### Measurement Tools (for validation protocol)
- Microsoft Rifts Benchmark. https://github.com/microsoft/rifts
- Common Ground Benchmark (2026). arXiv:2602.21337. https://arxiv.org/html/2602.21337v1
- DEAM: Dialogue Coherence Evaluation. arXiv:2203.09711
- Meng et al. "Causal Tracing / ROME." https://rome.baulab.info/
- Anthropic (2025). "Circuit Tracing in Language Models." https://transformer-circuits.pub/2025/attribution-graphs/methods.html

### Safety Considerations
- arXiv 2501.11739. "Episodic Memory in AI Agents Poses Risks." https://arxiv.org/abs/2501.11739
