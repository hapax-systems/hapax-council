# Multi-Model Cognitive Architectures: DMN/TPN Dual-Process LLM Systems

**Date:** 2026-03-25
**Status:** Literature review — comprehensive survey
**Relevance:** Voice daemon architecture (continuous local model + on-demand cloud model)

---

## 1. Theoretical Foundations

### 1.1 Dual-Process Theory (Kahneman) Applied to LLM Systems

Kahneman's System 1 (fast, automatic, low-effort) and System 2 (slow, deliberate, high-effort) maps directly onto multi-model architectures where a small/fast model handles continuous background processing while a large/capable model handles deliberative reasoning.

In LLM terms: System 1 = direct forward pass through a model to produce an immediate response. System 2 = intermediate reasoning steps, chain-of-thought, tree-of-thought, or escalation to a more capable model. The LLM2 framework (Tian et al., NAACL 2025) formalizes this by combining an LLM (System 1) with a process-based verifier (System 2) — the LLM generates candidates, the verifier provides process-level feedback to distinguish desirable from undesirable outputs.

A key result from distillation research: System 2 reasoning can be compressed into System 1 architectures. By training a small model to map inputs directly to the refined outputs of a larger reasoning model, the small model inherits reasoning capabilities without the inference-time cost. This is relevant for background cognition — a distilled small model can carry more capability than its parameter count suggests.

**Sources:**
- [System 1 vs System 2 in Modern AI](https://www.gloqo.ai/insights/combining_system_1_and_system_2_thinking/)
- [Distilling System 2 into System 1](https://medium.com/@EleventhHourEnthusiast/distilling-system-2-into-system-1-ab56e17d01f7)
- [Dual-process theories as potential architectures](https://www.frontiersin.org/journals/cognition/articles/10.3389/fcogn.2024.1356941/pdf)
- [LLM2: Let Large Language Models Harness System 2 Reasoning](https://aclanthology.org/2025.naacl-short.15/)
- [Reasoning on a Spectrum: Aligning LLMs to System 1 and System 2](https://arxiv.org/pdf/2502.12470)

### 1.2 DMN/TPN Neuroscience Mapping

The Default Mode Network (DMN) is not merely "task-negative" — it is active during internal goal-oriented and conceptual cognitive tasks including social cognition, autobiographical memory, and situation model maintenance. The DMN continuously metabolizes substantial energy to maintain neuronal computation during free-ranging thought. The Task-Positive Network (TPN) activates for focused external attention.

The critical insight: the DMN is not idle processing. It maintains a continuously updated situation model (who/what/where/when), consolidates memories, simulates future scenarios, and generates spontaneous thought. This is computationally expensive background work, not merely waiting.

**Sources:**
- [Default mode network - Wikipedia](https://en.wikipedia.org/wiki/Default_mode_network)
- [Tasks activating the default mode network map multiple functional systems](https://pmc.ncbi.nlm.nih.gov/articles/PMC9098625/)

### 1.3 System i — The Background Discovery Layer

Eugene Asahara (2026) proposes System i (using the imaginary unit symbol) as a third cognitive system: a continuous background discovery process that operates behind the scenes. The three-system model: System 2 (conscious reasoning) relies on System 1 (practiced behaviors) and System i (constantly running background process). System i continuously mines data and relationships to surface candidates for insight. Like the imaginary unit in mathematics, it is not directly observable in the output but is essential for structure and coherence.

In AI implementation: a background discovery layer (System i) continuously mines large spaces of data and relationships, validates analytical patterns, builds ML models, and deploys them. It also continuously updates existing models with current data and tests new models.

This is the closest published articulation to the hapax voice daemon's architecture: a continuously-running local model maintaining situational awareness that feeds into on-demand deliberative processing.

**Source:**
- [System i: The Default Mode Network of AGI](https://eugeneasahara.com/2026/01/08/system-0-the-default-mode-network-of-agi/)

---

## 2. Concrete Multi-Model Architectures

### 2.1 SOFAI / SOFAI-LM (IBM Research)

**Architecture:** Fast solver (LLM, e.g., Granite 3.3 8B without thinking) + Slow solver (LRM, e.g., DeepSeek R1 8B) + Metacognitive module.

**Interaction pattern:** Fast solvers activate independently as soon as a problem instance is provided. The metacognitive module waits for the fast solver to propose a solution, then decides whether to adopt it or activate the slow solver. The metacognitive module monitors the LLM's performance and provides targeted, iterative feedback with relevant examples, enabling progressive refinement without additional fine-tuning.

**State persistence:** The metacognitive module maintains a model of self, model of others, and model of the world — persistent state that governs routing decisions.

**Information flow:** Fast solver proposes → metacognition evaluates → accept or escalate to slow solver. The metacognitive module can also provide feedback to the fast solver for iterative refinement.

**Performance:** SOFAI-LM achieves 94% of LRM (reasoning model) performance while reducing inference costs by 75%. Combining both modalities yields higher decision quality with less resource consumption than either alone. Evidence for emergent human-like behaviors including skill learning, adaptability, and cognitive control.

**Failure modes:** Fast solver overconfidence (metacognition must catch this). The metacognitive module itself requires calibration — poor metacognition wastes resources or misses errors.

**Sources:**
- [SOFAI-LM: A Cognitive Architecture for Building Efficient and Reliable Reasoning Systems](https://research.ibm.com/publications/sofai-lm-a-cognitive-architecture-for-building-efficient-and-reliable-reasoning-systems-with-llms)
- [Language Models Coupled with Metacognition Can Outperform Reasoning Models](https://arxiv.org/abs/2508.17959)
- [Fast, slow, and metacognitive thinking in AI](https://www.nature.com/articles/s44387-025-00027-5)
- [Thinking Fast and Slow in AI](https://sites.google.com/view/sofai/home)

### 2.2 CoALA (Cognitive Architectures for Language Agents)

**Architecture:** Modular framework organizing agents along three dimensions: information storage (working memory + long-term memory), action space (internal + external), and decision-making (interactive loop with planning and execution).

**Memory structure:**
- Working Memory — short-term scratchpad holding immediate context
- Episodic Memory — records of past events
- Semantic Memory — factual knowledge about the world
- Procedural Memory — how to perform tasks

**Decision cycle:** Each cycle: retrieval + reasoning → propose candidate actions → evaluate → select best action → execute → repeat. Internal actions (reasoning, retrieval, learning) and external actions (tool use, environment interaction) are treated uniformly.

**State persistence:** Yes — long-term memory (episodic, semantic, procedural) persists across interactions. Working memory is per-cycle.

**Context management:** The framework explicitly separates what's in the current context window (working memory) from what's stored externally (long-term memory). Retrieval actions move information between these stores.

**Sources:**
- [Cognitive Architectures for Language Agents](https://arxiv.org/abs/2309.02427)
- [CoALA Explained - Cognee](https://www.cognee.ai/blog/fundamentals/cognitive-architectures-for-language-agents-explained)

### 2.3 Letta / MemGPT (LLM-as-Operating-System)

**Architecture:** LLM manages its own memory like an OS manages RAM and disk. Two-tier memory: main context (in-context, like RAM) and external context (out-of-context, like disk). The LLM uses tool calls to page information in and out.

**State persistence:** Core design principle — agents have persistent, self-editing memory. The LLM actively decides what to remember, what to forget, and what to retrieve. Memory blocks are updated based on learned information. Archival storage persists facts long-term. Strategic search queries retrieve relevant context when needed.

**Information flow:** The agent's inner monologue drives memory management. During each step, the agent can: edit in-context memory blocks, insert/search archival storage, and send messages to the user. The context window is a managed resource, not a passive input.

**Context management:** Virtual context management inspired by OS page tables. The model sees a fixed-size context window but has access to unbounded external storage. Interrupts manage control flow between the agent and the user/environment.

**Relevance to hapax voice:** Letta's self-editing memory is directly applicable. A continuously-running background model could maintain a Letta-style memory system — editing situation model blocks, archiving completed episodes, retrieving relevant context when the cloud model is invoked.

**Sources:**
- [Letta v1 Agent Loop](https://www.letta.com/blog/letta-v1-agent)
- [MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/abs/2310.08560)
- [Letta Research Background](https://docs.letta.com/concepts/letta/)

### 2.4 Reflexion (Verbal Reinforcement Learning)

**Architecture:** Three components — Actor (generates text/actions), Evaluator (scores outputs), Self-Reflection (generates verbal reinforcement cues). Not weight updates but linguistic self-improvement stored in episodic memory.

**State persistence:** Yes — reflective text is maintained in an episodic memory buffer across trials. The agent accumulates self-knowledge about what worked and what did not.

**Information flow:** Actor generates → environment provides feedback → Self-Reflection converts feedback to natural language analysis → stored in memory buffer → provided as context for subsequent Actor attempts. The "semantic gradient" tells the actor concretely what to improve.

**Performance:** 91% pass@1 on HumanEval (vs. GPT-4's 80% at the time). The key insight: verbal self-reflection stored as persistent memory is a viable alternative to gradient-based learning.

**Relevance:** The background model could maintain a running Reflexion-style memory — recording what worked, what failed, and why — and feed these reflections into the cloud model's context.

**Sources:**
- [Reflexion: Language Agents with Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366)
- [NeurIPS 2023 - Reflexion](https://github.com/noahshinn/reflexion)

### 2.5 Mixture-of-Agents (MoA)

**Architecture:** Layered architecture where each layer comprises multiple LLM agents. Each agent in layer N receives all outputs from layer N-1 as auxiliary information. Models specialize: some excel as proposers (generating diverse initial responses), others as aggregators (synthesizing multiple inputs into a refined output).

**Key finding — collaborativeness:** LLMs generate better responses when presented with outputs from other models, even less capable ones. Multi-proposer configurations consistently outperform single-proposer, indicating that input diversity from different models enhances output quality.

**Performance:** MoA using only open-source LLMs achieved 65.1% on AlpacaEval 2.0 vs. GPT-4 Omni's 57.5%.

**Relevance:** The background model's output can serve as a "proposer" input to the cloud model's "aggregator" role. Even if the background model is weaker, its continuous situation tracking adds signal that improves the cloud model's output.

**Sources:**
- [Mixture-of-Agents Enhances Large Language Model Capabilities](https://arxiv.org/abs/2406.04692)
- [Together MoA](https://www.together.ai/blog/together-moa)

---

## 3. Routing and Cascading Systems

### 3.1 RouteLLM (UC Berkeley / Anyscale)

**Architecture:** A trained router classifies query complexity and routes to either a strong (expensive) model or a weak (cheap) model. The router is trained on human preference data from Chatbot Arena.

**Routing approaches:** SW Ranking, Matrix Factorization, BERT-based classification, causal LLM classification.

**Performance:** 85% cost reduction on MT Bench, 45% on MMLU, 35% on GSM8K while maintaining 95% of GPT-4 performance. Strong generalization — routers trained on one model pair (GPT-4 + Mixtral) generalize to other pairs without retraining.

**Source:** [RouteLLM](https://lmsys.org/blog/2024-07-01-routellm/)

### 3.2 FrugalGPT (Stanford)

**Architecture:** LLM cascade — queries sent sequentially to increasingly capable (expensive) models. A generation scoring function assesses response reliability. If reliable, return immediately; if not, escalate to the next model.

**Key components:** Generation scoring function + LLM router. The router learns the optimal sequence of models to query and the reliability threshold for each.

**Performance:** Matches GPT-4 performance with up to 98% cost reduction, or improves accuracy over GPT-4 by 4% at the same cost.

**Source:** [FrugalGPT](https://arxiv.org/abs/2305.05176)

### 3.3 AutoMix (Self-Verification Routing)

**Architecture:** Small model generates initial answer → same small model self-verifies via entailment checking → POMDP-based router decides whether to escalate to a larger model.

**Key innovation:** Self-verification formulated as an entailment problem. The small model checks whether its answer is consistent with the source context. A POMDP handles the inherent noise in self-verification — observations (confidence scores) are unreliable estimates of the true state (question difficulty).

**Performance:** Over 50% cost reduction for comparable performance. In N=3 model scenarios, AutoMix strategically skips non-performant intermediate models and routes directly from small to large when necessary.

**Source:** [AutoMix: Automatically Mixing Language Models](https://arxiv.org/abs/2310.12963)

### 3.4 ACAR (Adaptive Complexity & Attribution Routing)

**Architecture:** Uses self-consistency variance as a task difficulty signal. When multiple samples from a fast model agree, the task is easy. When they disagree, route to diverse model perspectives.

**Source:** [ACAR](https://arxiv.org/html/2602.21231)

### 3.5 Speculative Cascades (Google Research)

Hybrid of speculative decoding and cascading. Achieves better cost-quality tradeoffs than either approach alone.

**Source:** [Speculative Cascades](https://research.google/blog/speculative-cascades-a-hybrid-approach-for-smarter-faster-llm-inference/)

---

## 4. Edge-Cloud Collaborative Inference

### 4.1 Token-Level Mixture (SLM + LLM)

**Architecture:** An on-device Small Language Model (e.g., TinyLlama) generates tokens. A confidence-based MLP router decides per-token whether to accept the SLM's output or offload to a cloud LLM.

**Key finding:** In multi-document QA, only 3% of tokens need LLM generation to achieve comparable quality. Routing just 7% of tokens to the cloud LLM yields 60%+ accuracy improvement with 80%+ cost reduction vs. full LLM inference.

**Communication:** When SLM and LLM share a tokenizer, communication is just token IDs — minimal bandwidth.

**Source:** [Token Level Routing Inference System](https://aclanthology.org/2025.acl-demo.16.pdf)

### 4.2 Apple Intelligence Model

Apple's on-device model (~3B parameters) handles natural language tasks locally. Complex requests are delegated to cloud-based models. Huawei's Pangu model follows the same pattern in HarmonyOS.

**Source:** [A Survey on Collaborative Mechanisms Between Large and Small Language Models](https://arxiv.org/html/2505.07460v1)

### 4.3 CE-CoLLM (Cloud-Edge Collaborative LLM)

Efficient and adaptive architecture that partitions the LLM into edge and cloud portions. First several layers processed at edge, subsequent layers in cloud. Partitioning ensures inference is consistent with full cloud-based LLM without accuracy impact.

**Source:** [CE-CoLLM](https://arxiv.org/html/2411.02829v1)

---

## 5. Continuous Context-Aware Agents

### 5.1 ContextAgent (NeurIPS 2025)

**Architecture:** The first context-aware proactive agent that incorporates extensive sensory contexts from wearables (video, audio) to understand user intentions without manual instructions. It extracts multi-dimensional contexts from massive sensory perceptions, combines them with persona contexts from historical data, predicts the necessity for proactive services, and automatically calls tools when needed.

**Key innovation:** Proactive-oriented context extraction derives both sensory and persona contexts from egocentric video/audio. A context-aware reasoner integrates both context types for reasoning.

**Performance:** Outperforms baselines by 8.5% in proactive predictions and 6.0% in tool calling accuracy.

**Relevance to hapax voice:** This is the closest published system to the desired architecture — continuous sensory processing feeding into proactive LLM reasoning. However, ContextAgent does not maintain a continuously-running background model; it processes sensor data on-demand.

**Sources:**
- [ContextAgent: Context-Aware Proactive LLM Agents](https://arxiv.org/abs/2505.14668)
- [ContextAgent GitHub](https://github.com/openaiotlab/ContextAgent)

---

## 6. Metacognitive Monitoring

### 6.1 Current State of LLM Self-Assessment

LLMs exhibit systematic overconfidence — they assign high confidence even when incorrect. Most models begin interactions with excessive certainty (average 72.92% confidence). Larger models with stronger language capabilities tend to be worse at calibration. This is a Dunning-Kruger effect in LLMs.

Metacognitive sensitivity (the ability to discriminate between correct and incorrect answers via confidence judgments) is distinct from metacognitive calibration (the alignment between confidence and actual accuracy). Current LLMs have moderate sensitivity but poor calibration.

**Practical approaches:** Metacognitive prompting, staged reflection, hierarchical meta-agent architectures, representation-level self-assessment, and explicit feedback loops.

**Relevance:** A background model's metacognitive abilities determine the quality of its escalation decisions. If the background model cannot reliably assess when it is uncertain, it will either escalate too often (defeating the purpose) or too rarely (missing important signals). Self-consistency sampling (AutoMix, ACAR) provides a model-agnostic uncertainty signal that does not rely on the model's own confidence calibration.

**Sources:**
- [Metacognitive Capabilities in LLMs](https://www.emergentmind.com/topics/metacognitive-capabilities-in-llms)
- [The Dunning-Kruger Effect in Large Language Models](https://arxiv.org/html/2603.09985v1)
- [Language Models Are Capable of Metacognitive Monitoring](https://arxiv.org/html/2505.13763v2)

### 6.2 Critic Architectures

Dual-critic systems employ a language-based critic (context-sensitive feedback) and a value-based critic (quantitative long-term reward estimates). This dual architecture enhances decision-making by leveraging complementary strengths. OpenAI's research demonstrates that LLM critics help catch LLM bugs — separate evaluation models find errors that the generating model misses.

**Sources:**
- [CRITIC: Large Language Models Can Self-Correct](https://arxiv.org/abs/2305.11738)
- [LLM Critics Help Catch LLM Bugs](https://cdn.openai.com/llm-critics-help-catch-llm-bugs-paper.pdf)

---

## 7. Specific Questions

### 7.1 Has anyone used a continuously-running local model for situational awareness feeding cloud calls?

**Partial implementations exist, no exact match found.**

The closest systems:
1. **System i** (Asahara, 2026) — Theoretical proposal for a continuously-running background discovery layer. Described architecturally but not as a published implementation with benchmarks.
2. **ContextAgent** (NeurIPS 2025) — Continuous sensory processing from wearables feeding into proactive LLM reasoning, but processes on-demand rather than maintaining a continuously-running model.
3. **Apple Intelligence** — On-device 3B model running locally, escalating to cloud, but reactive (not continuously running).
4. **SOFAI-LM** — Fast solver activates on problem arrival, not continuously. The metacognitive module maintains persistent state but does not run inference continuously.
5. **Token-level routing** — SLM generates tokens continuously during inference, routing hard tokens to cloud, but only during active generation (not ambient monitoring).

**Gap in the literature:** No published system maintains a continuously-running local LLM that builds and updates a persistent situation model in the background, then provides that model as context enrichment when a cloud model is invoked for deliberative reasoning. This is an open research direction.

### 7.2 Has anyone studied the optimal pulse rate for periodic LLM inference?

**No direct study found.**

Related findings:
- OS scheduling noise can delay LLM inference by 2-11ms in high-performance settings.
- Background daemons and interrupts cause tail latency spikes.
- Continuous batching and chunked prefill processing are the standard approaches for managing periodic inference loads.
- The ContextAgent processes sensor data in segments (video/audio chunks) but does not report an optimal polling interval.

**Relevant design considerations:**
- The interval should be driven by the rate of meaningful state change in the monitored environment, not by a fixed timer.
- For a voice daemon monitoring audio + biometric + stimmung signals: human conversational dynamics change on the order of seconds (prosody shifts), physiological signals change on the order of minutes (HRV, skin temperature), and situational context changes on the order of minutes to hours.
- A multi-rate architecture (fast audio processing at ~100ms, physiological integration at ~5-10s, situation model update at ~30-60s) would match the temporal structure of the input signals.

### 7.3 What is the minimum model size for useful background cognition?

**Empirical thresholds from the literature:**

| Size | Capabilities | Limitations |
|------|-------------|-------------|
| Sub-1B | Basic classification, sentiment | No reasoning, no coherent generation |
| 1-3B | Simple text tasks, draft generation, specialized domains | Fails on multistep reasoning. Does not benefit from long CoT. Performs better with shorter, simpler reasoning chains. |
| 3B | Emerging self-verification abilities (TinyZero). Reasoning can emerge through pure RL even at this scale. | Inconsistent. Not reliable for complex tasks. |
| 7-13B | Strong balance of speed, accuracy, cost. Complex instruction following, code generation. | Still below frontier on hard reasoning. |

**Key findings for background cognition:**
- High-quality 1-3B models trained on the same data as larger models increasingly compare with 7B models. The quality of training data matters more than parameter count for basic capabilities.
- Small models (<=3B) do not consistently benefit from distillation of long chain-of-thought from larger models. They perform better when fine-tuned on shorter, simpler reasoning chains aligned with their intrinsic capacity.
- For situation model maintenance (the DMN analogue), the task is primarily: summarize current state, detect meaningful changes, assess uncertainty, format context for the cloud model. This is classification + summarization, not complex reasoning — plausibly achievable at 3B with task-specific fine-tuning.
- Apple ships a ~3B on-device model for production use in Apple Intelligence.

**Recommendation for hapax voice:** A 3B model (e.g., Qwen 2.5 3B, Phi-3.5 Mini 3.8B) is the minimum viable size for background situation model maintenance. A 7B model (e.g., Qwen 2.5 7B, Mistral 7B) provides a comfortable margin for self-verification and uncertainty estimation. Both fit comfortably on the RTX 3090 alongside the voice pipeline's existing VRAM usage (whisper + TTS).

**Sources:**
- [LLM Model Sizes Explained](https://apxml.com/courses/getting-started-local-llms/chapter-3-finding-selecting-local-llms/model-sizes-parameters)
- [Small Language Models - IBM](https://www.ibm.com/think/topics/small-language-models)
- [Small Models Struggle to Learn from Strong Reasoners](https://arxiv.org/html/2502.12143v1)
- [Best Open-Source Small Language Models in 2026](https://www.bentoml.com/blog/the-best-open-source-small-language-models)

---

## 8. Synthesis: Architecture Patterns for Hapax Voice

### 8.1 What the Literature Supports

| Pattern | Evidence Level | Applicable System |
|---------|---------------|-------------------|
| Small model generates, large model verifies/refines | Strong (speculative decoding, AutoMix, FrugalGPT) | Voice cognition loop |
| Self-consistency as uncertainty signal | Strong (AutoMix, ACAR) | Escalation trigger |
| Metacognitive module governs routing | Strong (SOFAI-LM) | Stimmung-aware routing |
| Persistent episodic memory across interactions | Strong (Reflexion, MemGPT/Letta) | Voice situation model |
| Weak model output improves strong model output | Strong (MoA collaborativeness) | Background context enrichment |
| Token-level routing (easy local, hard cloud) | Moderate (edge-cloud research) | Real-time voice response |
| Continuous background inference for situational awareness | Speculative (System i, no published implementation) | DMN-analogue daemon |
| Multi-rate temporal architecture | Theoretical (matches neuroscience) | Multi-signal integration |

### 8.2 Proposed Architecture Mapping

```
┌─────────────────────────────────────────────────────┐
│ Background Model (local, 3-7B, continuous)          │
│ ┌─────────────┐  ┌──────────────┐  ┌─────────────┐ │
│ │ Situation    │  │ Episodic     │  │ Self-       │ │
│ │ Model        │  │ Memory       │  │ Verification│ │
│ │ (DMN/CoALA)  │  │ (Reflexion)  │  │ (AutoMix)   │ │
│ └──────┬───────┘  └──────┬───────┘  └──────┬──────┘ │
│        │                 │                  │        │
│        └────────┬────────┘                  │        │
│                 ▼                           │        │
│        ┌────────────────┐                   │        │
│        │ Context Package │◄─────────────────┘        │
│        │ (for cloud)     │                           │
│        └────────┬────────┘                           │
└─────────────────┼───────────────────────────────────┘
                  │
         ┌────────┴────────┐
         │ Metacognitive   │ ← Stimmung + confidence
         │ Router (SOFAI)  │   + self-consistency
         └────────┬────────┘
                  │ escalation trigger
                  ▼
┌─────────────────────────────────────────────────────┐
│ Deliberative Model (cloud, Claude, on-demand)       │
│ Receives: situation model + episodic memory +       │
│           uncertainty assessment + operator profile  │
└─────────────────────────────────────────────────────┘
```

### 8.3 Open Questions for Implementation

1. **VRAM budget:** What is the actual VRAM cost of keeping a 3B or 7B model loaded alongside whisper + TTS on the 3090? Quantized (Q4/Q5) versions reduce this substantially.
2. **Inference cadence:** The multi-rate approach (audio 100ms, physio 5-10s, situation 30-60s) has no published validation. The right cadence likely needs empirical tuning against the operator's actual interaction patterns.
3. **Context package format:** What does the background model send to the cloud model? A structured JSON situation model? Natural language summary? Embedding vector? The MoA research suggests natural language (the cloud model benefits from seeing another model's textual output), while the token-routing research suggests embeddings/hidden states for tighter integration.
4. **Self-verification reliability at 3B:** AutoMix's entailment-based self-verification has been validated at 7B+. Whether a 3B model can reliably self-verify is an open empirical question. Self-consistency sampling (multiple generations, check agreement) may be more robust at small sizes than entailment checking.
5. **Memory management:** How large does the episodic memory buffer grow? Letta's approach (self-editing memory with archival storage) provides a pattern, but the background model must be capable enough to make good memory management decisions.
