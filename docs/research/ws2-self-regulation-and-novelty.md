# WS2 + WS4: Self-Regulation and Novelty Detection

**Research synthesis -- March 2026**

Combined workstreams because they share a core concern: the system knowing its own state and limits. WS2 addresses interoceptive self-monitoring (the system's awareness of its own condition). WS4 addresses competence boundaries (the system's honesty about what it does and does not recognize).

---

## 1. Problem: The Missing Interoception

### Philosophical Foundation

Biological perception is never raw data processing. It is always modulated by the organism's current state -- fatigue, arousal, confidence, metabolic demand. Heidegger's *Stimmung* (mood, attunement) names this pre-reflective background that colors all experience before any particular object is encountered. Merleau-Ponty's body schema includes proprioceptive and interoceptive awareness as constitutive of the perceptual field, not supplementary to it.

In active inference terms (Friston), interoception provides the precision weighting for all prediction error signals. When the organism is fatigued, prediction errors from exteroceptive channels are down-weighted; the system becomes less responsive to novelty and more conservative. When arousal is high, precision on exteroceptive signals increases; the system becomes hypervigilant. This is not a separate "self-monitoring module" bolted onto perception -- it is a global modulation that shapes every act of perception simultaneously.

An engineered system has no felt states. But it has measurable analogues: confidence levels on its own outputs, error rates over recent windows, resource pressure (VRAM, context window, API latency), recent decision quality (were its predictions confirmed or contradicted?), and processing throughput. The question is whether these signals can serve a *Stimmung*-like function -- globally modulating all processing rather than being treated as isolated data points.

### What Is Missing in Current LLM Systems

Most LLM-based systems treat each request as stateless. The model receives a prompt, generates a response, and forgets. There is no accumulation of self-state across invocations. If a model has been producing low-confidence outputs for the last hour, or if every sensor reading has been anomalous, nothing in the standard architecture adjusts the system's overall processing stance.

The existing Hapax architecture has infrastructure monitoring (99 health checks, GPU/VRAM tracking, reactive engine counters) but these are *reported* rather than *felt*. The health data goes to a dashboard; it does not modulate the perception engine's processing or the content scheduler's sampling.

---

## 2. Problem: Confabulation at the Competence Boundary

### Philosophical Foundation

Epistemic humility is not a feature to add; its absence is a structural defect. When a perceptual system encounters something outside its experience, the phenomenologically honest response is what Husserl called *epoché* -- a suspension of judgment. The system should bracket its assumptions rather than forcing the novel into familiar categories.

LLMs are notoriously bad at this. They confabulate with high confidence. A system built on LLMs inherits this defect unless architectural countermeasures are in place. The goal is not to prevent the system from ever being wrong -- that is impossible. The goal is to make the system's uncertainty *visible and actionable*, and to prevent it from producing high-confidence outputs when it is operating outside its competence.

This connects directly to the Hapax governance axioms. The `executive_function` axiom (weight 95) demands that errors include next actions. A system that silently confabulates violates this -- it produces an error disguised as a normal output, with no next action possible because the operator does not know an error occurred.

---

## 3. Prior Art: Self-Regulation

### 3.1 LLM Confidence Calibration

The core problem is well-documented: LLMs are systematically overconfident when verbalizing their uncertainty.

**Survey findings (2024-2025)**: A comprehensive survey by Gao et al. (2025, KDD / arXiv 2503.15850) taxonomizes LLM uncertainty methods into four families:

1. **White-box methods** -- access token logits/probabilities. Predictive entropy (Shannon entropy over the output distribution), token-level log-probabilities, and semantic entropy (clustering semantically equivalent outputs and computing entropy over clusters). These require API access to logprobs, which Claude and Gemini provide but Ollama local models expose more fully.

2. **Black-box sampling methods** -- generate multiple responses, measure consistency. Self-consistency (Wang et al., 2022) samples multiple chain-of-thought paths and takes majority vote. Semantic equivalence checking clusters responses by meaning rather than string match. The cost scales linearly with sample count.

3. **Verbalized confidence** -- prompt the model to state its confidence as a number. Xiong et al. (ICLR 2024, "Can LLMs Express Their Uncertainty?") showed this is consistently overconfident. Models say "90% confident" when they are correct roughly 60-70% of the time. The Dunning-Kruger effect in LLMs (2025, arXiv 2603.09985) confirmed this extends across model families.

4. **Hybrid / calibrated approaches** -- combine signals. QA-Calibration (ICLR 2025) post-hoc calibrates verbalized confidence using a held-out dataset. ADVICE (arXiv 2510.10913) makes verbalized confidence answer-dependent, improving calibration. Reward calibration in RLHF (PPO-M, arXiv 2410.09724) integrates confidence into training.

**Key insight for Hapax**: No single method is sufficient. White-box logprobs are cheap but don't capture semantic uncertainty. Verbalized confidence is overconfident. Sampling-based methods are expensive. The practical approach is a *tiered* system: cheap logprob signals as the fast baseline, verbalized confidence as a secondary signal with known bias correction, and occasional multi-sample consistency checks for high-stakes decisions.

### 3.2 Metacognitive AI Architectures

Several architectural patterns exist for systems that monitor their own performance:

**SOFAI / SOFAI-LM** (Srivastava et al., 2024-2025): A dual-process architecture inspired by Kahneman's System 1/System 2. A fast solver handles routine cases. A metacognitive module monitors the fast solver's confidence and routes low-confidence cases to a slow, deliberative solver. The metacognitive module maintains a state vector quantifying the system's "cognitive state" across dimensions. This is the closest existing architecture to what Hapax needs.

**MetaRAG** (2025): Advances retrieval-augmented generation to a self-regulating system. Explicit monitoring (similarity-based answer checking), evaluative criticism (internal/external knowledge sufficiency diagnosis via NLI), and adaptive planning (retrieval query adjustment, strategy repair). Demonstrates that RAG pipelines can be made self-aware about their own retrieval quality.

**LLM Introspection** (2025, arXiv 2505.13763): Evidence that LLMs can acquire knowledge of their internal activations that originates from those states rather than from training data. Models can be trained to predict properties of their own hidden states, achieving above-chance accuracy on tasks like "is the model currently uncertain?" This suggests introspection is not purely confabulatory -- there is a real signal, even if noisy.

**Interoceptive Active Inference** (Pezzulo et al., 2021; reviewed 2024): Computational models of biological interoception describe three model types: inference models (how internal states are inferred from signals), regulation models (how actions are selected based on internal states), and forecasting models (how actions change internal states). The key idea: interoceptive inference is hierarchical, with higher levels representing more abstract homeostatic goals. This maps directly to a system architecture where low-level metrics (VRAM usage, API latency) are integrated into higher-level assessments (system health, processing capacity, decision quality).

### 3.3 Dynamic System Prompts as Self-State Carriers

The system prompt is the closest existing mechanism to a global modulation channel in LLM-based architectures. Research on dynamic prompting supports this use:

**SPEAR** (Cetintemel et al., VLDB/CIDR 2026): Proposes treating prompts as "first-class runtime components" in adaptive LLM pipelines. Prompts become structured data that can be inspected, versioned, and dynamically modified based on runtime conditions. This directly supports the idea of a system prompt that updates with self-state information.

**Promptbreeder** (Fernando et al., 2024): Self-referential prompt evolution -- prompts that modify themselves based on task performance. Demonstrates that prompt content can be a closed-loop control signal, not just a static instruction set.

**Dynamic prompt adaptation** (2024-2025, multiple sources): Real-time modification of prompts based on session history, user inputs, environmental data. The pattern is established in production systems even if the academic literature is fragmented.

**For Hapax**: The system prompt for each LLM call already carries context (cycle mode, operator profile). Extending it with a self-state block -- current confidence trend, recent error rate, resource pressure, processing latency -- would create a Stimmung-like global modulation. The LLM would "know" the system's state and could adjust its processing accordingly (e.g., being more conservative when confidence is low, flagging more aggressively when error rates are rising).

### 3.4 Precision Weighting as Architectural Pattern

Active inference provides the theoretical framework for making self-state signals *modulate* rather than merely *inform*:

**Precision weighting** (Friston et al., extensively): In predictive processing, precision is the estimated reliability of a prediction error signal. High precision = the signal is trustworthy, amplify it. Low precision = the signal is noisy, attenuate it. Crucially, precision is *itself* a prediction that the system must infer -- it is not given by the data.

**Self-certainty training** (2025): Training LLMs on their own KL-based confidence (the divergence between the model's output distribution and a reference). A 3B-parameter model trained this way matched fully supervised GRPO on in-domain math while exceeding it on out-of-domain code. This demonstrates that self-certainty can be a useful training signal, not just a monitoring metric.

**Attention as precision** (multiple sources, 2020-2025): In active inference, attention *is* precision weighting -- selectively amplifying certain prediction error channels. The transformer attention mechanism is a coarse analogue: it dynamically weights which parts of the input are relevant. But standard attention is within-context, not cross-context. What is needed is a mechanism that adjusts attention *between* processing cycles based on accumulated self-state.

---

## 4. Prior Art: Novelty Detection and Competence Boundaries

### 4.1 Out-of-Distribution Detection for LLMs

OOD detection for LLMs is an active research area with distinct challenges compared to vision models:

**EOE -- Envisioning Outlier Exposure** (Cao et al., ICML 2024): Uses LLMs to *imagine* potential OOD examples without access to actual OOD data. The LLM's world knowledge generates plausible outliers for a given domain, which are then used to train an OOD detector. Demonstrated strong performance on text classification benchmarks. Relevant to Hapax because the system could use its own LLM to generate hypothetical anomalous perception states for self-calibration.

**LLMs for Anomaly Detection Survey** (Li et al., 2024, NAACL Findings 2025): Comprehensive survey covering how LLMs can both *detect* anomalies (using their world knowledge to identify unexpected patterns) and *be subject to* distributional shift (when their input distribution drifts from training). Key finding: LLMs are better at detecting semantic anomalies (things that don't make sense in context) than statistical anomalies (rare token sequences).

**Distributional Shift in Large Multimodal Models** (Zhang et al., CVPR 2025): Evaluated 15 large multimodal models on 20 datasets under distributional shift. Found that zero-shot generalization degrades significantly under domain shift even for the largest models. Implies that a multimodal perception system like Hapax cannot assume its models will generalize gracefully -- explicit shift detection is required.

### 4.2 Epistemic vs. Aleatoric Uncertainty Decomposition

The distinction matters practically: epistemic uncertainty ("I have not seen this before") should trigger escalation or abstention. Aleatoric uncertainty ("this situation is inherently ambiguous") should trigger richer context gathering.

**Input Clarification Ensembling** (Hou et al., ICML 2024 Oral): Generates clarified versions of ambiguous inputs, processes each through the LLM, and measures response divergence. If responses diverge across clarifications, the input is aleatoric-uncertain (genuinely ambiguous). If responses are consistent across clarifications but the model is still uncertain, the uncertainty is epistemic (the model lacks knowledge). This decomposition is directly actionable.

**Cross-Model Semantic Disagreement** (2025, OpenReview): Measures epistemic uncertainty as the gap between inter-model and intra-model response similarity. If the same model gives consistent but wrong answers, self-consistency misses the error. If different models disagree, epistemic uncertainty is high. Applicable to Hapax's multi-model architecture (Claude/Gemini/Ollama via LiteLLM) -- disagreement across models is a natural epistemic uncertainty signal.

**Fine-Grained Decomposition** (2025, arXiv 2509.22272): Argues the binary epistemic/aleatoric split is insufficient for LLMs and proposes finer categories: input ambiguity, reasoning path divergence, knowledge gaps, and decoding stochasticity. Each has different implications for system behavior.

**Confident Failures** (2025, OpenReview): Studies cases where models are simultaneously confident and wrong, showing that aleatoric and epistemic uncertainty play complementary roles in detecting these failures. Neither alone is sufficient; both must be tracked.

### 4.3 Graceful Degradation Patterns

When a system detects it is at its competence boundary, what should it *do*?

**Tiered degradation** (industry pattern, 2024-2025): Maintain multiple models of decreasing complexity. When the primary model's uncertainty exceeds a threshold, fall back to a simpler, more robust model. An LLM-based perception system might fall back from nuanced contextual interpretation to simple categorical classification, or from active inference to reactive rules.

**Circuit breaker pattern** (widespread in production systems): When error rates exceed a threshold, stop calling the failing component and switch to cached/default behavior. Prevents cascading failures. Applicable to LLM API calls that are timing out or returning degraded results.

**Uncertainty-gated escalation** (human-in-the-loop pattern): When system uncertainty exceeds a threshold, surface the uncertain state to the operator rather than acting on it. For Hapax, this means the visual layer showing "I'm not sure what's happening" rather than rendering a confident but wrong state.

**Rule-based fallback** (Forrester 2024): Maintain deterministic business rules that approximate model behavior for well-understood domains. Less accurate but 100% reliable. Hapax already has this pattern in its tiered architecture (Tier 3 deterministic agents as fallback for Tier 2 LLM agents).

### 4.4 Ensemble and Consistency Methods

**Self-Consistency** (Wang et al., 2022; widely extended through 2025): Sample multiple reasoning paths, take majority vote. The degree of agreement is a natural uncertainty estimate. Extended by confidence-aware self-consistency (2025, arXiv 2603.08999), which weights paths by intermediate confidence scores rather than treating all paths equally.

**Certified Self-Consistency** (2025, arXiv 2510.17472): Adds statistical guarantees to self-consistency -- provable bounds on the probability that the majority answer is correct, given the observed agreement level. Useful for determining when self-consistency actually provides meaningful confidence.

**Multi-model disagreement**: Running the same perception through Claude, Gemini, and a local Ollama model and measuring disagreement. This is naturally available in the Hapax architecture through LiteLLM routing. Disagreement across model families is a stronger novelty signal than within-model sampling because it captures genuine knowledge gaps rather than just decoding stochasticity.

---

## 5. Hapax Architecture Mapping

### 5.1 Where Self-State Already Lives

The Hapax system already tracks considerable self-state, but it is fragmented and non-modulatory:

| Signal | Current Location | Current Use |
|--------|-----------------|-------------|
| System health (99 checks) | `logos/data/health.py` → `health-history.jsonl` | Dashboard display, visual layer aggregator |
| GPU/VRAM | `logos/data/gpu.py` → `infra-snapshot.json` | Dashboard display, visual layer |
| Reactive engine counters | `logos/engine/__init__.py` (events, rules, actions, errors) | `/api/engine/status` endpoint |
| Processing latency | Langfuse traces | Observability dashboard |
| LLM call quality | Langfuse traces | Manual inspection |
| Perception backend health | `PerceptionBackend.available()` in perception engine | Skip unavailable backends |
| Content scheduler scores | Visual layer aggregator source scoring | Softmax sampling weights |

**Gap**: None of these signals feed back into the system's *processing*. Health data goes to the visual layer for display but does not modulate how the perception engine processes sensor data, how the reactive engine evaluates rules, or how LLM agents frame their prompts.

### 5.2 Where Self-Regulation Should Live

The self-regulation system needs to sit at a level that can influence all downstream processing -- analogous to how biological interoception modulates cortical processing globally.

**Proposed: `SystemStimmung` -- a global self-state vector**

```
Location: shared/stimmung.py (new module)
Updated by: a lightweight collector running every fast tick (15s)
Consumed by: every LLM call's system prompt, perception engine tick logic,
             reactive engine rule evaluation, content scheduler sampling
```

The `SystemStimmung` would aggregate:

1. **Confidence trend** -- rolling average of LLM confidence scores from Langfuse traces over the last N calls. Computed from logprob data where available (Ollama), verbalized confidence where not (Claude, Gemini), with known overconfidence bias correction.

2. **Error rate** -- reactive engine error count / action count over a sliding window. Health check degraded/failed ratio.

3. **Resource pressure** -- VRAM usage percentage, API latency trend (from Langfuse), context window utilization for ongoing conversations.

4. **Decision quality** -- were recent predictions/classifications confirmed or contradicted by subsequent observations? Requires a feedback loop from perception to a quality tracker.

5. **Processing throughput** -- events processed per minute in reactive engine, perception ticks completed on schedule vs. delayed.

6. **Novelty level** -- how many recent perception states fell outside the system's confidence bounds (see 5.3 below).

This vector would be:
- Written atomically to `/dev/shm/hapax-stimmung/state.json` (like the visual layer state)
- Injected into every LLM system prompt as a structured block
- Read by the perception engine to adjust tick rates (slow down when resource-pressured)
- Read by the reactive engine to adjust rule sensitivity (suppress non-critical rules when degraded)
- Read by the content scheduler to adjust sampling temperature (more conservative when uncertain)

### 5.3 Where Novelty Detection Should Live

Novelty detection maps to multiple points in the existing architecture:

**Perception Engine Level** (`agents/hapax_voice/perception.py`):

The perception engine already has tiered backends (FAST/SLOW/EVENT). Each backend's `contribute()` method produces `Behavior` values. Novelty detection would add a confidence/novelty annotation to each behavior:

- Each backend reports not just its readings but its confidence in those readings
- The perception engine aggregates per-backend confidence into a per-tick novelty score
- Anomalous combinations (high audio activity + low visual activity in a context where those usually correlate) flag cross-modal novelty

**LLM Agent Level** (any pydantic-ai agent):

For agents making LLM calls through LiteLLM, novelty detection involves:

- Extracting logprobs from the response (where available) and computing token-level entropy
- Adding verbalized confidence prompts with known bias correction
- For high-stakes decisions, multi-model consistency checks (route the same prompt to Claude and Gemini, compare)

**Reactive Engine Level** (`logos/engine/`):

When a filesystem event triggers rule evaluation, the system should assess whether the event pattern is familiar:

- Track the distribution of (event_type, doc_type, rules_matched) tuples
- Flag events that match no rules as potentially novel (rather than silently ignoring them)
- Track rule-match frequency to detect distribution shift (rules that used to match frequently stop matching)

**Visual Layer Level** (`agents/visual_layer_aggregator.py`):

The visual layer is the primary channel for communicating system state to the operator. When the system detects it is at its competence boundary:

- Shift visual rendering toward "uncertain" aesthetics (documented in WS3 visual encoding)
- Surface explicit "I don't recognize this pattern" signals rather than rendering a confident but potentially wrong state
- Use the Stimmung vector to drive overall visual tone -- a system under pressure looks different from a confident system

### 5.4 Integration Architecture

```
                        ┌──────────────────┐
                        │  SystemStimmung   │
                        │  (shared module)  │
                        └────────┬─────────┘
                                 │ writes /dev/shm/hapax-stimmung/
                                 │
              ┌──────────────────┼───────────────────┐
              │                  │                    │
              ▼                  ▼                    ▼
    ┌─────────────────┐ ┌───────────────┐ ┌──────────────────┐
    │ Perception      │ │ Reactive      │ │ LLM Agents       │
    │ Engine          │ │ Engine        │ │ (pydantic-ai)    │
    │                 │ │               │ │                  │
    │ - tick rate     │ │ - rule        │ │ - system prompt  │
    │   adjustment    │ │   sensitivity │ │   injection      │
    │ - backend       │ │ - cooldown    │ │ - confidence     │
    │   confidence    │ │   adjustment  │ │   extraction     │
    │ - cross-modal   │ │ - novel event │ │ - multi-model    │
    │   novelty       │ │   flagging    │ │   consistency    │
    └────────┬────────┘ └───────┬───────┘ └────────┬─────────┘
             │                  │                    │
             └──────────────────┼────────────────────┘
                                │ feeds back into
                                ▼
                        ┌──────────────────┐
                        │  SystemStimmung   │
                        │  (next tick)      │
                        └──────────────────┘
```

The loop is closed: Stimmung modulates processing, processing results feed back into Stimmung. This is the active inference precision-weighting loop, implemented as a software architecture pattern.

---

## 6. Implementation Possibilities

Ordered by feasibility (easiest first), with each building on the previous.

### Phase 1: Stimmung Collector (effort: low, value: foundation)

Create `shared/stimmung.py` with a `SystemStimmung` dataclass and a collector that reads existing data sources:

- Read `health-history.jsonl` for health trend
- Read `infra-snapshot.json` for GPU/VRAM pressure
- Read reactive engine status via internal API
- Compute rolling averages over configurable windows
- Write atomically to `/dev/shm/hapax-stimmung/state.json`
- Run as a 15-second timer in the logos API process

This requires no new data collection -- it aggregates what already exists. The `SystemStimmung` data structure becomes the single source of truth for "how is the system doing right now?"

### Phase 2: System Prompt Injection (effort: low-medium, value: high)

Modify the shared LLM call infrastructure to inject Stimmung into every system prompt:

```
[System State]
confidence_trend: 0.82 (stable)
error_rate_5m: 0.03
vram_pressure: 0.45
processing_latency_trend: rising
overall_stance: nominal
```

This is cheap -- it adds a few tokens to each prompt. The LLM receives the system's self-state as context and can adjust its behavior accordingly (more hedging language when confidence is low, more decisive when high). No fine-tuning needed; instruction-following models will respond to this context naturally.

### Phase 3: Per-Backend Confidence Annotation (effort: medium, value: high)

Extend the `PerceptionBackend` protocol to include confidence reporting:

- Each `contribute()` call also reports a confidence score (0-1) for each behavior it provides
- The perception engine computes a per-tick aggregate confidence
- Behaviors below a confidence threshold are flagged rather than treated as definitive
- Cross-modal consistency checks: when audio and visual backends disagree more than their historical correlation predicts, flag the perception tick as anomalous

This requires modifying each backend implementation but the interface change is small. The key insight: confidence should be a first-class part of the perception data model, not an afterthought.

### Phase 4: Langfuse-Based Decision Quality Tracking (effort: medium, value: medium-high)

Use Langfuse's custom scoring API to track decision quality over time:

- After each LLM-based decision, log the decision and the confidence
- When the outcome becomes observable (e.g., the perception engine's next tick confirms or contradicts a prediction), score the original decision
- Compute a rolling decision quality metric
- Feed this back into the Stimmung vector

Langfuse already supports custom numeric scores via its SDK. The work is in defining what "decision quality" means for each agent type and wiring the feedback loop.

### Phase 5: Multi-Model Consistency for High-Stakes Decisions (effort: medium-high, value: high)

For decisions that significantly affect system behavior (state machine transitions, classification overrides, anomaly flags):

- Route the same prompt to two different model families via LiteLLM (e.g., Claude + Gemini, or Claude + local Ollama)
- Compare responses semantically (not string-match)
- If models agree: high confidence, proceed
- If models disagree: flag as epistemically uncertain, use the more conservative interpretation, optionally surface to operator

Cost is 2x for affected calls, but these should be rare (only high-stakes decisions). The natural multi-model architecture of Hapax (LiteLLM already routes to multiple backends) makes this easier than in a single-model system.

### Phase 6: Novelty Detection in the Reactive Engine (effort: medium, value: medium)

Track the distribution of event patterns in the reactive engine:

- Maintain a frequency table of (event_type, doc_type, rules_matched) tuples
- Compute a novelty score for each incoming event based on how rare its pattern is
- Events matching no rules get special treatment: logged, flagged, and included in the Stimmung novelty dimension
- Distribution shift detection: if the recent event distribution diverges significantly from the historical distribution (e.g., KL divergence exceeds threshold), raise a system-level novelty alert

This is lightweight statistically but requires careful threshold tuning to avoid alert fatigue.

### Phase 7: Stimmung-Modulated Processing (effort: high, value: transformative)

Close the full loop -- make Stimmung actively modulate processing:

- **Perception engine**: Under high resource pressure, skip SLOW-tier backends and rely on FAST-tier only. Under high novelty, increase the slow tick frequency to gather more context.
- **Reactive engine**: Under high error rates, increase cooldown periods to reduce cascading failures. Under nominal conditions, allow tighter cooldowns for faster response.
- **Content scheduler**: Under low confidence, increase sampling temperature (explore more diverse content). Under high confidence, exploit the current best sources more aggressively.
- **Visual layer**: Encode Stimmung in the ambient visual rendering. A confident system has a calm, stable visual field. An uncertain system has subtle visual indicators of its state.

This is the full active-inference-style precision weighting loop. It is the most complex phase but also the most phenomenologically significant -- it makes the system's self-state *constitutive* of its processing rather than merely reported.

---

## 7. Supporting Technologies

### Libraries

| Tool | Purpose | Access Model | Notes |
|------|---------|-------------|-------|
| **UQLM** (CVS Health, 2025) | LLM uncertainty quantification | Black-box + white-box | Sampling-based (semantic entropy, CoCoA), logprob-based, LLM-as-judge. Python package, pip-installable. Most comprehensive single library. |
| **LM-Polygraph** (2024-2025) | Uncertainty estimation benchmark | White-box | Battery of UE methods for text generation. Widely adopted in research. Requires model access. |
| **posteriors** (Normal Computing) | Bayesian UQ | White-box | Bayesian computation for uncertainty-aware LLMs. More research-oriented. |
| **Langfuse** (existing) | LLM observability | API | Custom scoring via SDK. Trace-level metadata. No built-in uncertainty tracking but the scoring API supports it. Already deployed in Hapax stack. |
| **LiteLLM** (existing) | Multi-model routing | API | Enables multi-model consistency checks. Already deployed. Logprob passthrough for supported models. |

### Langfuse Integration Points

Langfuse does not natively track confidence or uncertainty, but its architecture supports it:

- **Custom scores**: Attach numeric confidence scores to any trace or span via `langfuse.score()`
- **Trace metadata**: Store per-call uncertainty metrics as trace metadata
- **Evaluation pipelines**: Define custom evaluation functions that compute uncertainty metrics over batches
- **Dashboard**: Custom metrics can be visualized alongside latency, cost, and error rates

The practical approach: instrument LLM calls to extract logprobs (where available), compute token-level entropy, and log both as Langfuse scores. Over time, this builds a dataset of confidence-outcome pairs that can be used for calibration.

### Active Inference Implementations

Several active inference libraries exist but none are directly applicable to LLM-based perception systems:

- **pymdp** (Heins et al., 2022): Python package for active inference in discrete state spaces. Could model the Stimmung state machine but would need adaptation for continuous signals.
- **SPM** (Friston lab): MATLAB-based, research-oriented. Not practical for production.
- **RxInfer.jl** (Julia): Reactive message passing for Bayesian inference. Architecturally interesting but wrong language ecosystem.

The most practical path is not to use an active inference library directly but to implement the *pattern* -- precision weighting, prediction error, closed-loop modulation -- in the existing Python/async architecture.

---

## 8. Open Questions

### Self-Regulation

1. **How often should Stimmung update?** Every 15s (fast tick) seems right for resource metrics. Decision quality needs longer windows (minutes to hours). Should Stimmung have multiple temporal scales, like biological interoception (fast autonomic + slow hormonal)?

2. **How should Stimmung affect LLM behavior?** Simply injecting state into the system prompt is a coarse mechanism. Does the model actually *change its behavior* based on self-state information in the prompt, or does it just generate text about being uncertain? This needs empirical testing.

3. **What is the right aggregation function?** Averaging across dimensions loses information. A system can be simultaneously healthy (low error rate) and uncertain (novel inputs). The Stimmung vector should preserve these independent dimensions rather than collapsing to a single score.

4. **Feedback loop stability**: If Stimmung modulates processing, and processing results feed back into Stimmung, can the loop oscillate? E.g., high uncertainty → conservative processing → fewer errors → low uncertainty → aggressive processing → more errors → high uncertainty. Biological systems solve this with multiple timescales and damping. The implementation needs similar stabilization.

5. **Calibration data**: To correct for verbalized overconfidence, we need a calibration dataset mapping stated confidence to actual accuracy. Where does this dataset come from in a single-operator ambient system? Langfuse traces over time could provide this, but it requires weeks of operation to accumulate.

### Novelty Detection

6. **What counts as "novel" vs. "rare but known"?** A sensor pattern the system has seen once before is technically in-distribution but practically novel. Threshold selection is crucial and probably needs to be adaptive.

7. **How to communicate novelty to the operator without being annoying?** "I don't recognize this pattern" is useful the first time and irritating the hundredth. The visual layer encoding of uncertainty needs to be ambient and non-disruptive -- a change in background tone, not a popup.

8. **Cross-modal novelty**: When is disagreement between perception backends a sign of genuine novelty vs. a backend malfunction? If the camera says someone is present but audio says silence, is that a novel situation (someone sitting quietly) or a broken microphone? The system needs a model of expected cross-modal correlation to distinguish the two.

9. **Epistemic vs. aleatoric distinction in practice**: The input clarification ensembling method (ICML 2024) is elegant but expensive. Is there a cheaper proxy? Perhaps: if uncertainty drops when more context is provided (e.g., adding the operator's recent activity history), it was epistemic. If it remains, it was aleatoric.

10. **Constitutional implications**: The `interpersonal_transparency` axiom requires consent before modeling non-operator persons. If the system detects novelty because an unfamiliar person is present, it must simultaneously (a) recognize the novelty and (b) refrain from modeling the person beyond what the consent framework allows. Novelty detection and governance are entangled.

---

## 9. Sources

### LLM Calibration and Uncertainty

- [Uncertainty Quantification and Confidence Calibration in Large Language Models: A Survey](https://arxiv.org/abs/2503.15850) -- Gao et al., KDD 2025. Comprehensive taxonomy.
- [A Survey of Uncertainty Estimation Methods on Large Language Models](https://aclanthology.org/2025.findings-acl.1101.pdf) -- ACL Findings 2025.
- [A Survey on Uncertainty Quantification of Large Language Models](https://dl.acm.org/doi/10.1145/3744238) -- ACM Computing Surveys.
- [Can LLMs Express Their Uncertainty? An Empirical Evaluation of Confidence Elicitation](https://arxiv.org/abs/2306.13063) -- Xiong et al., ICLR 2024.
- [Do LLMs Estimate Uncertainty Well?](https://proceedings.iclr.cc/paper_files/paper/2025/file/ef472869c217bf693f2d9bbde66a6b07-Paper-Conference.pdf) -- ICLR 2025.
- [The Dunning-Kruger Effect in Large Language Models](https://arxiv.org/html/2603.09985) -- 2025.
- [Mind the Confidence Gap: Overconfidence, Calibration, and Distractor Effects](https://arxiv.org/html/2502.11028v3) -- 2025.
- [ADVICE: Answer-Dependent Verbalized Confidence Estimation](https://arxiv.org/html/2510.10913v2) -- 2025.
- [QA-Calibration of Language Model Confidence Scores](https://assets.amazon.science/6d/70/c50b2eb141d3bcf1565e62b60211/qa-calibration-of-language-model-confidence-scores.pdf) -- ICLR 2025.
- [Taming Overconfidence in LLMs: Reward Calibration in RLHF](https://arxiv.org/pdf/2410.09724) -- 2024.
- [Cycles of Thought: Measuring LLM Confidence through Stable Explanations](https://arxiv.org/html/2406.03441v1) -- 2024.

### Metacognitive AI and Self-Monitoring

- [Language Models Are Capable of Metacognitive Monitoring and Control](https://arxiv.org/html/2505.13763v2) -- 2025.
- [Fast, Slow, and Metacognitive Thinking in AI](https://www.nature.com/articles/s44387-025-00027-5) -- npj AI, 2025.
- [Metacognitive AI: Framework and the Case for a Neurosymbolic Approach](https://www.semanticscholar.org/paper/Metacognitive-AI:-Framework-and-the-Case-for-a-Wei-Shakarian/1bcd28ff113e5a646a0522c60489bfa172c7d8d9) -- 2024.
- [Harnessing Metacognition for Safe and Responsible AI](https://www.mdpi.com/2227-7080/13/3/107) -- 2025.
- [Reviewing a Model of Metacognition for Application in Cognitive Architecture Design](https://www.mdpi.com/2079-8954/13/3/177) -- 2025.
- [Metacognitive Capabilities in LLMs](https://www.emergentmind.com/topics/metacognitive-capabilities-in-llms) -- Emergent Mind topic survey.

### Dynamic Prompting and Adaptive Systems

- [Making Prompts First-Class Citizens for Adaptive LLM Pipelines (SPEAR)](https://arxiv.org/html/2508.05012) -- Cetintemel et al., VLDB/CIDR 2026.
- [Dynamic Policy Induction for Adaptive Prompt Optimization](https://arxiv.org/html/2509.25267) -- 2025.
- [Optimizing Prompts via Task-Aware, Feedback-Driven Self-Refinement](https://aclanthology.org/2025.findings-acl.1025.pdf) -- ACL Findings 2025.
- [Think Beyond Size: Dynamic Prompting for More Effective Reasoning](https://arxiv.org/html/2410.08130v1) -- 2024.
- [Large Language Models Report Subjective Experience Under Self-Referential Processing](https://arxiv.org/html/2510.24797v1) -- 2025.

### Active Inference and Precision Weighting

- [A Beautiful Loop: An Active Inference Theory of Consciousness](https://www.sciencedirect.com/science/article/pii/S0149763425002970) -- Neuroscience & Biobehavioral Reviews, 2025.
- [Active Inference AI Systems for Scientific Discovery](https://arxiv.org/html/2506.21329v4) -- 2025.
- [Generating Meaning: Active Inference and the Scope and Limits of Passive AI](https://www.sciencedirect.com/science/article/pii/S1364661323002607) -- Trends in Cognitive Sciences, 2024.
- [The Missing Reward: Active Inference in the Era of Experience](https://arxiv.org/html/2508.05619v1) -- 2025.
- [Solving the Relevance Problem with Predictive Processing](https://www.tandfonline.com/doi/full/10.1080/09515089.2025.2460502) -- Philosophical Psychology, 2025.
- [Computational Models of Interoception and Body Regulation](https://pmc.ncbi.nlm.nih.gov/articles/PMC8109616/) -- Pezzulo et al., Trends in Neurosciences, 2021.

### Out-of-Distribution Detection

- [Envisioning Outlier Exposure by Large Language Models for OOD Detection](https://proceedings.mlr.press/v235/cao24d.html) -- Cao et al., ICML 2024.
- [Large Language Models for Anomaly and Out-of-Distribution Detection: A Survey](https://arxiv.org/abs/2409.01980) -- Li et al., NAACL Findings 2025.
- [OOD Detection with Positive and Negative Prompt Supervision](https://arxiv.org/html/2511.10923v1) -- 2025.
- [On the Out-Of-Distribution Generalization of Large Multimodal Models](https://openaccess.thecvf.com/content/CVPR2025/papers/Zhang_On_the_Out-Of-Distribution_Generalization_of_Large_Multimodal_Models_CVPR_2025_paper.pdf) -- CVPR 2025.

### Epistemic/Aleatoric Uncertainty Decomposition

- [Decomposing Uncertainty for Large Language Models through Input Clarification Ensembling](https://arxiv.org/abs/2311.08718) -- Hou et al., ICML 2024 Oral.
- [Fine-Grained Uncertainty Decomposition in Large Language Models](https://arxiv.org/pdf/2509.22272) -- 2025.
- [Efficient Epistemic Uncertainty Estimation via Knowledge Distillation](https://arxiv.org/html/2602.01956v1) -- 2025.
- [Uncovering Confident Failures: Complementary Roles of Aleatoric and Epistemic Uncertainty](https://openreview.net/forum?id=9Jq7wNrpUI) -- 2025.
- [Complementing Self-Consistency with Cross-Model Disagreement](https://openreview.net/forum?id=lOoRJo8xWy) -- 2025.
- [Uncertainty Quantification for Hallucination Detection](https://arxiv.org/html/2510.12040) -- 2025.

### Self-Consistency and Ensemble Methods

- [Certified Self-Consistency: Statistical Guarantees for Reliable Reasoning](https://arxiv.org/html/2510.17472) -- 2025.
- [Learning When to Sample: Confidence-Aware Self-Consistency](https://arxiv.org/html/2603.08999) -- 2025.
- [Towards Reliable LLM Grading Through Self-Consistency](https://www.preprints.org/manuscript/202512.0232/v1/download) -- 2025.

### Graceful Degradation

- [Building AI That Never Goes Down: The Graceful Degradation Playbook](https://medium.com/@mota_ai/building-ai-that-never-goes-down-the-graceful-degradation-playbook-d7428dc34ca3) -- MOTA AI, 2025.
- [AI Fail Safe Systems: Design, Strategies, and Fallback Plans](https://t3-consultants.com/ai-fail-safe-systems-design-strategies-fallback-plans/) -- T3 Consultants, 2024.
- [When AI Breaks: Building Degradation Strategies for Mission-Critical Systems](https://itsoli.ai/when-ai-breaks-building-degradation-strategies-for-mission-critical-systems/) -- ItSoli, 2024.

### Tools and Libraries

- [UQLM: A Python Package for Uncertainty Quantification in Large Language Models](https://arxiv.org/abs/2507.06196) -- CVS Health, JMLR 2025.
- [LM-Polygraph](https://github.com/IINemo/lm-polygraph) -- Uncertainty estimation for text generation.
- [posteriors: Uncertainty-Aware LLMs](https://www.normalcomputing.com/blog/posteriors-normal-computings-library-for-uncertainty-aware-llms-3) -- Normal Computing.
- [Langfuse: Open Source LLM Observability](https://langfuse.com/docs/observability/overview) -- Langfuse docs.
- [Awesome-LLM-Uncertainty-Reliability-Robustness](https://github.com/jxzhangjhu/Awesome-LLM-Uncertainty-Reliability-Robustness) -- Curated resource list.

### Interoception and Phenomenology

- [Phenomenology and Artificial Intelligence: Introductory Notes](https://awspntest.apa.org/record/2025-49265-001) -- APA, 2025.
- [A Review of Embodied Intelligence Systems](https://www.frontiersin.org/journals/robotics-and-ai/articles/10.3389/frobt.2025.1668910/full) -- Frontiers in Robotics and AI, 2025.
- [Active Inference, Computational Phenomenology, and Advanced Practice](https://meditation.mgh.harvard.edu/files/Tal_25_OSF.pdf) -- 2025.
