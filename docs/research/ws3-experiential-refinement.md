# WS3: Experiential Refinement -- Skill Development for Stateless Perceptual Systems

**Date**: 2026-03-16
**Status**: Research synthesis -- Workstream 3 of phenomenological engineering project
**Depends on**: [LLM-Phenomenology Mapping Research](llm-phenomenology-mapping-research.md), [WS1: Temporal Structure](ws1-temporal-structure-engineering.md), [WS2: Self-Regulation](ws2-self-regulation-and-novelty.md)
**Sources**: 90+ papers, systems, and frameworks, 2022-2026

---

## 1. Problem

### The Philosophical Requirement

Merleau-Ponty's central claim about perception is that it is a *skilled bodily activity*. A novice perceives differently from an expert -- not because the expert applies additional reasoning after perception, but because the perceptual field itself is structured by experience. A chess grandmaster literally sees the board differently: patterns leap out, threats are pre-reflectively salient, possible moves present themselves without deliberation. Dreyfus's skill model (novice through expert) traces how explicit rule-following gives way to *intuitive* responsiveness as competence develops. At mastery, the practitioner does not think about rules at all -- they perceive situations directly as calling for particular responses.

This is "pre-reflective skill development." The skill is not a post-hoc reasoning layer; it shapes what is perceived and how it is experienced. An ambient computing system that perceives an operator must develop analogous skill: getting better at interpreting *this specific operator* in *this specific environment* with *these specific patterns*. Early interactions should be tentative and often wrong. After months, the system should have a developed perceptual fluency -- not because the model weights changed, but because the accumulated context around the model has been refined by experience.

### The Engineering Contradiction

An LLM does not learn through deployment. Each inference is fresh. The model that interprets a perception signal at month six is the same model that interpreted it at day one. Whatever "skill" the system develops must reside entirely in the infrastructure *around* the model: the context it receives, the memories it retrieves, the corrections it has accumulated, the patterns it has been shown to recognize.

This is a significant constraint but also an opportunity. Biological skill development is opaque -- you cannot inspect what changed in a chess master's visual cortex. An engineered system's "skill" is entirely legible: it is stored in databases, expressed in retrieval results, and visible in the context window. If the system misinterprets something, you can find the memory that led to the misinterpretation and correct it. If it develops a correct pattern, you can see exactly which accumulated experiences support it.

The full space of what is possible when you invest seriously in experiential refinement infrastructure is vast. The research literature from 2024-2026 has converged on the insight that memory architecture is the primary differentiator in LLM-based agent systems -- more important than model selection, prompt engineering, or tool integration. This workstream maps the complete landscape.

---

## 2. Prior Art

### 2.1 Memory Architectures for LLM Systems

The field has crystallized around a taxonomy of memory types that mirrors cognitive science distinctions. The survey "Memory in the Age of AI Agents" (Shichun-Liu et al., December 2024, arXiv 2512.13564) identifies four core types:

1. **Episodic memory**: Records of specific past events with full context -- when they happened, what signals were present, what interpretation was made, what outcome occurred. The AI analogue of "I remember the last time the operator was in this exact situation."

2. **Semantic memory**: General facts extracted from experience -- "the operator usually codes in the evening," "loud music correlates with flow state." These are abstracted from episodes and do not carry specific temporal context.

3. **Procedural memory**: Learned sequences of actions -- "when presence drops to zero and it's after 11pm, the operator has gone to bed." These are if-then patterns that become automatic responses.

4. **Working memory**: The current context window contents -- the active set of information being used for the current inference. Limited by context window size, managed by what gets included.

A comprehensive 2026 survey "From Storage to Experience: A Survey on the Evolution of LLM Agent Memory Mechanisms" formalizes the development process into three stages: Storage (trajectory preservation), Reflection (trajectory refinement), and Experience (trajectory abstraction). This maps directly to the Hapax architecture's current evolution: the perception engine stores trajectories (perception state snapshots), but reflection and experience stages are unbuilt.

### 2.2 Dominant Systems and Frameworks

#### MemGPT / Letta

MemGPT (Packer et al., October 2023, arXiv 2310.08560) was the first system to propose treating LLM memory as a virtual memory management problem, analogous to operating system paging. The LLM's context window is "RAM" -- fast but limited. External storage is "disk" -- large but requiring explicit retrieval. The LLM itself manages page-in/page-out decisions.

MemGPT evolved into Letta, an open-source framework. As of early 2026, Letta V1 has rearchitected away from the original heartbeat-based loop toward a simpler agent architecture using the Responses API and native reasoning. The key idea survives: the agent is responsible for its own memory management, deciding what to store, what to retrieve, and what to forget.

**Relevance to Hapax**: The self-managed memory concept is compelling for a system that runs continuously. The perception engine could include memory management as an explicit part of its processing loop -- after each interpretation, decide what to remember.

#### Mem0

Mem0 (April 2025, arXiv 2504.19413) is the most production-mature memory layer. It dynamically extracts, consolidates, and retrieves salient information from ongoing conversations. Key results: 26% relative improvement in LLM-as-a-Judge metrics, 91% lower p95 latency, 90%+ token cost savings compared to full-context approaches.

Mem0's enhanced variant uses graph-based memory representations to capture relational structures. It achieves ~2% additional improvement over flat memory through relationship modeling.

**Relevance to Hapax**: Mem0's hybrid storage (Postgres for long-term facts and episodic summaries, vector store for semantic retrieval) maps well to Hapax's existing infrastructure (Qdrant for vectors, JSONL for structured audit trails). The extraction/consolidation pipeline is directly applicable.

#### Zep / Graphiti

Zep (Rasmussen, January 2025, arXiv 2501.13956) introduced a temporal knowledge graph architecture that outperforms MemGPT on the Deep Memory Retrieval benchmark (94.8% vs 93.4%). On the more challenging LongMemEval benchmark, Zep achieves up to 18.5% accuracy improvement while reducing latency by 90%.

Zep's core innovation is Graphiti, a temporally-aware knowledge graph engine with three hierarchical tiers:

1. **Episode subgraph**: Raw input data (messages, text, JSON) as non-lossy storage from which entities and relations are extracted.
2. **Semantic entity subgraph**: Entities extracted from episodes, resolved against existing graph entities, with explicitly typed relationships.
3. **Community subgraph**: High-level domain summaries providing abstract context.

The critical feature is Graphiti's **bi-temporal model**: every graph edge tracks both when an event occurred and when it was ingested, with explicit validity intervals. This means you can query "what did the system believe about X at time T" and "what actually happened with X at time T" independently.

**Relevance to Hapax**: The bi-temporal model is essential for a perceptual system. A correction at 3pm changes what the system knows *now*, but the original interpretation at 1pm should remain accessible as history. The three-tier hierarchy maps to: perception snapshots (episodes), extracted patterns (semantic entities), and operator model summaries (communities). Graphiti is open-source and could be integrated with Hapax's existing Qdrant infrastructure.

#### A-Mem

A-Mem (Xu et al., NeurIPS 2025, arXiv 2502.12110) introduces self-organizing memory following the Zettelkasten method. When a new memory is added, the system generates structured notes with contextual descriptions, keywords, and tags, then analyzes existing memories to establish semantic links. Critically, adding new memories can *trigger updates to existing memories* -- the knowledge network continuously refines itself.

**Relevance to Hapax**: This is the closest to genuine skill development. If a correction to an activity classification triggers updates to all related perceptual memories ("every time I thought 'idle' at 10pm with music playing, it was actually 'winding down'"), the system's future interpretations improve globally rather than just for the specific corrected instance.

#### Memento

Memento (August 2025, arXiv 2508.16153) demonstrates "fine-tuning LLM agents without fine-tuning LLMs." It uses memory-based online reinforcement learning, formalized as a Memory-augmented Markov Decision Process (M-MDP) with a neural case-selection policy. Past experiences are stored in an episodic Case Bank, and a learned selector determines which past cases to include in context for new decisions.

Results: 87.88% Pass@3 on GAIA validation, with case-based memory adding 4.7-9.6 absolute percentage points on out-of-distribution tasks.

**Relevance to Hapax**: This is precisely the architecture for experiential refinement. The perception engine accumulates cases (perception-interpretation-outcome triples), and a learned retrieval policy selects the most relevant past cases for each new perception. The system "improves" by growing its case bank and refining its selection policy, not by retraining.

#### MemVerse

MemVerse (December 2025, arXiv 2512.03627) implements a dual-path architecture inspired by fast/slow thinking. The fast pathway is a parametric memory model providing immediate recall by periodically distilling knowledge from long-term memory. The slow pathway is hierarchical retrieval-based memory structured as knowledge graphs. A memory orchestrator governs interactions between the two paths through rule-based control logic (no trainable parameters).

Results: 84.48% on ScienceQA, 90.40% on MSR-VTT, demonstrating multimodal reasoning capability.

**Relevance to Hapax**: The dual-path model maps to a natural architecture split: fast path = pre-computed operator profile + recent perception summaries (available without retrieval), slow path = full episodic memory of past perception events (retrieved on demand). The orchestrator concept fits the existing reactive engine pattern.

#### Amazon Bedrock AgentCore Episodic Memory

AWS's AgentCore (GA December 2025) provides a production episodic memory system that captures structured episodes recording context, reasoning process, actions, and outcomes. A reflection agent analyzes episodes to extract broader insights: successful strategies, improvement opportunities, common failure modes, and cross-episode lessons.

**Relevance to Hapax**: The reflection agent pattern is key. Raw episodes are necessary but insufficient -- the system needs periodic reflection that distills episodes into higher-level insights. "The last 50 times the operator corrected 'idle' to 'thinking', the common pattern was: face present, no typing for >5 min, browser on documentation page."

### 2.3 Correction-Driven Learning

#### MemPrompt

MemPrompt (Madaan et al., 2022) established the core pattern: maintain a searchable memory of past corrections. When processing a new input, search for relevant past corrections. If a similar misunderstanding was corrected before, include the correction in context. The system learns from corrections without retraining.

This is the simplest possible experiential refinement mechanism and it works. The key insight is that corrections are high-signal data -- an operator who takes the time to correct the system is providing direct supervision.

#### MemOrb

MemOrb (2025, arXiv 2509.18713) extends correction learning to multi-turn interactions. It distills interactions into "compact strategy reflections" stored in a shared memory bank. On future interactions, relevant reflections are retrieved to guide decision-making. Key result: MemOrb reduces repetitive clarifications and correctly reuses prior explanations.

**Relevance to Hapax**: The existing activity correction endpoint (operator corrects what the system thinks they are doing, 30min TTL) is a seed of this. The correction currently expires. It should instead be stored permanently as a perception-correction pair, embedded for semantic retrieval, and consulted on all future activity classifications.

#### MemAlign

MemAlign (Databricks, 2025) maintains Working Memory by combining principles from Semantic Memory (stable rules) with examples from Episodic Memory (specific past cases). Users can delete or overwrite past records, and identifying outdated records triggers automatic cleanup.

**Relevance to Hapax**: The explicit operator control over memory contents aligns with Hapax's governance axioms. The operator should be able to inspect, correct, and delete any experiential memory. The `interpersonal_transparency` axiom (weight 88) requires this for any memories involving non-operator persons.

### 2.4 Operator Modeling and Personalization

#### Dynamic User Profile Modeling

RLPA (2025, arXiv 2505.15456) introduces reinforcement learning for profile-aligned adaptation. The system infers, retains, and leverages user profiles through ongoing interaction with dual-level rewards (profile-level and response-level). The profile evolves with the user rather than being static.

#### Difference-Aware User Modeling

DPL (ACL 2025 Findings, arXiv 2503.02450) measures "what makes you unique" -- rather than modeling the operator in absolute terms, it models how the operator differs from typical users. This focuses the profile on high-information-content features.

#### PersonalLLM

PersonalLLM (ICLR 2025) provides synthetic personal preference models for benchmarking personalization algorithms. Key finding: personalization from interaction history requires approximately 50-100 interactions before meaningful differentiation emerges.

**Relevance to Hapax**: The existing profile system (11 dimensions, behavioral facts from sync agents) is already a form of operator modeling. The extension is: perception-specific dimensions. How does *this* operator's "coding" look different from the generic model? When *this* operator says "I'm fine," what do the biosignals say? The profile system needs perception-derived behavioral dimensions that accumulate from perceptual experience.

### 2.5 Episodic Memory: Events vs. Facts

The distinction between episodic and semantic memory is critical for experiential refinement.

**Episodic memories** are specific: "On Tuesday at 2:17pm, the system classified the operator as 'idle' based on no typing + low audio energy. The operator corrected to 'reading documentation.' Flow score was 0.4, face present, browser active on MDN."

**Semantic memories** are general: "When the operator is reading documentation, typing stops but face remains present and browser is active. This is not idle."

The progression from episodic to semantic is consolidation -- the system gradually extracts general patterns from specific episodes. The Ebbinghaus forgetting curve (1885) describes how specific memories decay exponentially, while consolidated knowledge persists. FOREVER (January 2026, arXiv 2601.03938) and MSSR (March 2026, arXiv 2603.09892) apply this principle to LLM continual learning, scheduling replay based on time-dependent retention that mirrors biological memory consolidation.

Research by Pezzuto et al. on the Autobiographical Memory Interview distinguishes:
- **Specific episodic**: A single event with specific time, place, and sensory detail
- **General episodic**: Repeated events or extended events ("I usually code at night")
- **Semantic personal**: Personal facts without temporal context ("I prefer VSCode")

All three types serve experiential refinement. A perceptual system needs specific episodes (for correction retrieval), general episodes (for pattern recognition), and semantic personal facts (for operator modeling). A benchmark by Park et al. (2025, arXiv 2501.13121) tested these distinctions with 196 events across 37 dates, 35 locations, and 34 entities, generating 686 questions to evaluate retrieval across episodic dimensions.

### 2.6 Context Compression and Hierarchical Memory

As experiential memory grows, context window limits become binding. Several approaches address this.

#### Hierarchical Summarization

The most established approach: progressively compress older memories while preserving essential information. Short-term memory holds recent events verbatim. Medium-term holds compressed summaries of recent sessions. Long-term stores extracted facts and patterns. When processing a query, the system draws from all tiers, allocating more context budget to recent history.

Recursively Summarizing (Xu et al., 2023, arXiv 2308.15022) demonstrated this for long-term dialogue: recursive summarization of conversation segments enables retrieval over much longer histories than raw storage allows.

#### KVzip

KVzip (Seoul National University, 2025) compresses conversation memory in the key-value cache by 3-4x while maintaining accuracy and doubling response speed. It supports contexts up to 170,000 tokens and allows memory reuse across queries without recompression.

**Relevance to Hapax**: For a continuously running perceptual system, KV cache compression could enable maintaining much longer "recent history" windows without proportional cost increases. The perception engine processes a tick every 2.5 seconds; at full context, that is 34,560 perception events per day.

#### JetBrains Context Engineering

JetBrains Research (December 2025) published work on "Cutting Through the Noise: Smarter Context Management for LLM-Powered Agents," addressing how to select which memories to include in context when the full memory exceeds window limits. Their approach combines relevance scoring with recency weighting and task-specific filtering.

### 2.7 Temporal Knowledge Management

Memories age. The operator changes. The environment changes. Old corrections may no longer apply. Several approaches address this.

#### Temporal Decay Functions

The standard approach uses decay functions that reduce memory salience over time. MemoryBank employs Ebbinghaus-inspired forgetting curves, refreshing memories on retrieval and pruning those below a salience threshold. Mnemosyne uses a hybrid scoring function combining connectivity (how linked is this memory?), frequency of reinforcement (how often has it been confirmed?), recency, and entropy (how much information does it carry?).

The key insight from FOREVER (2026): decay should be measured in "model time" (magnitude of optimizer updates / system state changes) rather than wall clock time. A memory from yesterday in a rapidly changing context is "older" than a memory from last week in a stable context.

#### Explicit Validity Intervals

Zep/Graphiti's approach: every fact has explicit start and end timestamps for its validity period. When new information contradicts an existing fact, the old fact's validity is closed and the new fact begins. Both remain queryable -- you can ask "what was true then" and "what is true now."

**Relevance to Hapax**: This is essential for a system where the operator's patterns change (started working from home, got new equipment, changed schedule). Rather than deleting old patterns, close their validity. If the operator reverts to old patterns, the old memories are still available.

#### Active Forgetting

"Memory Power Asymmetry in Human-AI Relationships" (December 2024, arXiv 2512.06616) raises a philosophical point relevant to Hapax's governance: AI systems that remember everything create power asymmetries. The `interpersonal_transparency` axiom already addresses this for non-operator persons, but even for the operator, selective forgetting may be important. The operator should be able to say "forget that period" and have it be genuinely forgotten, not merely suppressed.

"Forgetful but Faithful" (December 2024, arXiv 2512.12856) proposes a cognitive memory architecture for privacy-aware agents that can genuinely forget while maintaining faithful operation on remaining memories.

### 2.8 Knowledge Graphs for Experience Representation

#### LLM-Empowered Knowledge Graph Construction

A comprehensive 2025 survey (arXiv 2510.20345) traces the shift from rule-based to LLM-driven knowledge graph construction. Two paradigms:

- **Schema-based**: Define entity types and relation types upfront. Extract instances that conform to the schema. High consistency, limited flexibility.
- **Schema-free**: Let the LLM discover entities and relations from data. High flexibility, requires post-hoc normalization.

For experiential refinement, a hybrid approach is natural: the schema defines the structure of perception events (timestamp, signals, interpretation, confidence, outcome, correction) while the LLM discovers emergent patterns and relationships between events.

#### AriGraph

AriGraph (IJCAI 2025) combines knowledge graphs with episodic memory for embodied agents. The agent maintains a graph that encodes both general world knowledge (semantic) and specific past events (episodic). When encountering a new situation, both types of knowledge inform reasoning.

**Relevance to Hapax**: This is the pattern for fusing the operator profile (semantic knowledge about the operator) with perception episodes (specific past events). The graph structure enables reasoning like: "The operator is in state X (semantic: they prefer deep work in the evening) + they just switched from browser to terminal (episodic: last time this happened after 9pm, they coded for 3 hours uninterrupted) = high probability of entering flow state, suppress notifications."

### 2.9 Fine-Tuning as Skill Crystallization

At some point, accumulated experience may warrant crystallizing patterns into model weights rather than relying on retrieval.

#### LoRA and QLoRA

LoRA (Hu et al., 2021) enables parameter-efficient fine-tuning by training low-rank adaptation matrices. QLoRA (Dettmers et al., 2023) combines this with 4-bit quantization, enabling fine-tuning of 70B parameter models on a single 24GB GPU (directly applicable to Hapax's RTX 3090).

#### TreeLoRA: Continual Learning

TreeLoRA (ICML 2025) introduces layer-wise adapters organized in a hierarchical tree based on gradient similarity. This enables efficient continual learning -- new tasks get new branches without catastrophic forgetting of old tasks.

#### MSSR: Memory-Aware Adaptive Replay

MSSR (March 2026, arXiv 2603.09892) schedules fine-tuning replay based on time-dependent retention, progressively expanding replay intervals as model stability increases. Outperforms state-of-the-art replay baselines on reasoning-intensive benchmarks.

**Relevance to Hapax**: The path is: (1) accumulate episodic experience in Qdrant, (2) extract correction patterns and operator-specific interpretations, (3) when patterns are stable and well-confirmed, fine-tune a local Ollama model with LoRA/QLoRA on the crystallized patterns. The local model handles "fast path" perception (pattern matching on well-known situations) while the cloud model handles "slow path" perception (novel or ambiguous situations). This directly implements Dreyfus's skill model: the fine-tuned local model is the "expert" that perceives patterns directly, while the cloud model is the "novice" that must deliberate.

### 2.10 Active Learning and Uncertainty-Driven Queries

#### LLM-Based Active Learning

A comprehensive survey "From Selection to Generation" (ACL 2025, arXiv 2502.11767) covers how LLMs can actively select which data points to learn from. ActiveLLM assesses uncertainty and diversity without supervision, making it suitable for few-shot and bootstrapping scenarios.

#### Uncertainty Quantification

ICLR 2025 work on "Do LLMs Estimate Uncertainty Well?" shows that uncertainty estimation remains a challenge. Not all elicitation methods perform well under aleatoric (inherently random) uncertainty. The practical implication: the system should be more cautious about asking for corrections when the underlying situation is genuinely ambiguous, versus when the system is simply inexperienced.

**Relevance to Hapax**: The perception engine should track its own confidence and actively seek correction when uncertain. "I classified your activity as 'idle' but I'm only 40% confident -- you haven't moved for 20 minutes but your heart rate is elevated. Are you thinking about something?" The WS2 self-regulation work (confidence calibration, metacognitive monitoring) directly enables this.

### 2.11 Multimodal Experience Storage

#### MemVerse Multimodal Architecture

MemVerse (December 2025) directly addresses multimodal memory. Its hierarchical retrieval-based memory structures multimodal experiences as knowledge graphs, with the memory orchestrator managing cross-modal relationships.

#### TeleMem

TeleMem (January 2026, arXiv 2601.06037) builds long-term multimodal memory for agentic AI, combining a multimodal memory module with ReAct-style reasoning in a closed-loop observe-think-act process.

#### Embodied AI Data Storage

A 2025 survey on multimodal data storage for embodied AI (arXiv 2508.13901) identifies five complementary storage architectures for multi-sensor data: Graph Databases (relationships), Multi-Model Databases (heterogeneous data), Data Lakes (raw archival), Vector Databases (semantic retrieval), and Time-Series Databases (temporal queries). The recommendation is not to choose one but to use them in combination.

**Relevance to Hapax**: The perception engine already produces 30+ behavioral signals from cameras, microphone, biometrics, and system state. These multimodal perception events need a storage architecture that preserves cross-modal relationships. "The operator's heart rate spiked (biometric) while the face detector showed a frown (visual) and typing speed increased (system) -- this combination has historically meant frustration with a bug, not excitement about a breakthrough."

### 2.12 Transfer Across Contexts

#### Analogical Prompting

Analogical prompting (Yasunaga et al., 2024) draws on relevant past experiences to tackle new problems, inspired by how humans use analogical reasoning. The approach outperforms zero-shot and few-shot chain-of-thought across reasoning tasks.

#### Cross-Context Generalization Challenges

LLMs show strong generalization across domains in principle, but experience transfer in agent systems remains limited. The challenge is structural: experiences are typically stored with the context they occurred in, and retrieving them for a different context requires recognizing structural similarity despite surface differences.

**Relevance to Hapax**: Experience gained in one operator context ("coding late at night produces flow state but also leads to hyperfocus where meals are skipped") should transfer to related contexts ("writing late at night may also trigger hyperfocus"). This requires storing experiences with abstracted pattern descriptions, not just raw signal values. The activity mode taxonomy (coding, production, research, meeting, away, idle) already provides one level of abstraction; adding higher-level categories (focused-creative-work, consumptive-activity, social-interaction) would enable cross-context transfer.

### 2.13 Technologies and Frameworks

#### Qdrant Advanced Features (2025-2026)

Qdrant's 2025 capabilities directly relevant to experiential memory:

- **Payload filtering with datetime range queries**: Temporal queries on perception events ("all corrections from the last 30 days")
- **Score-Boosting Reranking**: Blend vector similarity with business signals (recency, confidence, correction count)
- **Maximal Marginal Relevance (MMR)**: Balance relevance and diversity in retrieval -- avoid returning 10 variants of the same pattern
- **Conditional updates** (Qdrant 1.16): Update a memory only if certain conditions are met (e.g., don't overwrite a high-confidence memory with low-confidence data)
- **Full-text filtering with multilingual tokenization**: Search memories by keywords as well as semantics
- **ACORN algorithm**: Higher-quality filtered HNSW queries for complex filter+similarity searches

#### Other Relevant Technologies

- **Neo4j / Graphiti**: Temporal knowledge graphs with validity intervals. Graphiti is open-source and designed for agent memory.
- **LangChain Memory**: Modular memory management with short-term (conversation), long-term (cross-session), and entity memory. Best for chaining tasks.
- **LlamaIndex Memory**: FIFO queue with overflow to long-term blocks. Integrates well with document retrieval. Composable with query engines.
- **Langfuse**: Already deployed in Hapax. Full LLM call tracing provides the audit trail for understanding what context led to what interpretation.
- **Ollama + LoRA**: Local fine-tuning pipeline for skill crystallization. RTX 3090 supports QLoRA for models up to 70B.
- **CLAP embeddings**: Already used for studio-moments. Can embed multimodal perception events for cross-modal retrieval.

---

## 3. Hapax Architecture Mapping

### 3.1 What Already Exists

The existing Hapax architecture has substantial infrastructure that can be extended for experiential refinement:

| Component | Current State | Experiential Refinement Extension |
|-----------|--------------|----------------------------------|
| **Qdrant (4+1 collections)** | `claude-memory`, `profile-facts`, `documents`, `axiom-precedents`, `studio-moments` | Add `perception-episodes`, `perception-corrections`, `operator-patterns` collections |
| **Profile system** | 11 dimensions, behavioral facts from sync agents, `ProfileStore` with semantic search | Add perception-derived dimensions: `activity-signatures`, `temporal-patterns`, `context-responses` |
| **Perception engine** | 30+ behaviors from cameras, mic, biometrics, system state; writes to `perception-state.json` every 2.5s | Extend to also write episodes to Qdrant with full signal context |
| **Activity mode classifier** | Rule-based: coding, production, research, meeting, away, idle, unknown | Augment with retrieved past episodes for similar signal patterns |
| **Perception state writer** | Atomic JSON snapshots to disk for external consumers | Dual-write: disk for real-time consumers, Qdrant for episodic memory |
| **Reactive engine** | inotify watcher, 12 rules, phased execution | Add rules for correction processing, pattern extraction, memory consolidation |
| **Langfuse** | Full LLM call tracing | Mine traces for perception accuracy feedback (was the interpretation used successfully?) |
| **Health history** | JSONL audit trail | Cross-reference with perception episodes for system-state-aware interpretation |
| **Content scheduler** | 10 content sources, relevance matrix, freshness decay | Content relevance improves as operator activity patterns become known |
| **Activity correction endpoint** | Operator corrects activity label, 30min TTL | Extend to permanent correction store with semantic embedding for retrieval |
| **Consent infrastructure** | `ConsentGatedWriter`, `ConsentRegistry`, consent contracts | Gate all experiential memory involving non-operator persons through consent |

### 3.2 The Perception-Episode Schema

The fundamental unit of experiential memory is the **perception episode**: a structured record of what the system perceived, how it interpreted it, and what happened next.

```
PerceptionEpisode:
  id: uuid
  timestamp: datetime
  duration_seconds: float

  # Raw signals (what was perceived)
  signals:
    face_count: int
    operator_present: bool
    flow_score: float
    activity_mode: string
    audio_energy_rms: float
    vad_confidence: float
    top_emotion: string
    emotion_valence: float
    emotion_arousal: float
    gaze_direction: string
    posture: string
    detected_action: string
    scene_type: string
    # ... all 30+ perception behaviors

  # Interpretation (what the system concluded)
  interpretation:
    activity_label: string
    confidence: float
    interruptibility: float
    flow_state: string
    reasoning: string  # why this interpretation

  # Context (what else was true)
  context:
    time_of_day: string
    day_of_week: string
    cycle_mode: string  # dev/prod
    recent_corrections: list[CorrectionRef]
    active_consents: list[string]

  # Outcome (what actually happened)
  outcome:
    was_corrected: bool
    correction_label: string | null
    correction_timestamp: datetime | null
    subsequent_signals: SignalSummary  # what happened in the next 30min
    interpretation_used_by: list[string]  # which downstream systems used this

  # Metadata
  embedding: vector[768]  # semantic embedding of the episode
  consolidated_into: uuid | null  # reference to pattern if consolidated
  validity: {start: datetime, end: datetime | null}
```

### 3.3 The Correction-Memory Loop

The most immediately impactful architecture: every operator correction creates a permanent, retrievable memory.

Current flow:
```
Perception tick → Activity classifier → perception-state.json → (consumed by studio, cockpit)
                                                                 ↑
Operator correction → 30min TTL override ────────────────────────┘
```

Extended flow:
```
Perception tick → Activity classifier → perception-state.json → (consumed)
                          ↑                      |
                 Retrieved corrections          ↓
                          ↑              Episode writer → Qdrant (perception-episodes)
                          |
Operator correction → Correction store → Qdrant (perception-corrections)
                          |                      ↓
                          └──────── Pattern extractor (reactive engine rule)
                                         ↓
                                  Qdrant (operator-patterns)
```

### 3.4 New Infrastructure Required

1. **`perception-episodes` Qdrant collection**: 768-dim vectors (nomic-embed-text), payload per the episode schema above. Estimated growth: ~34,560 episodes/day at 2.5s intervals (will need downsampling -- only store episodes where something changes or periodically, not every tick).

2. **`perception-corrections` Qdrant collection**: Smaller, higher-value. Each correction links to the episode it corrected. Payload includes the original interpretation, the correction, and extracted features that distinguish this case.

3. **`operator-patterns` Qdrant collection**: Consolidated patterns extracted from multiple episodes. "When signals X, Y, Z co-occur after 9pm, the operator is winding down, not idle."

4. **Episode writer agent**: Tier 3 (deterministic). Monitors perception state, detects significant changes, writes episodes to Qdrant with full signal context. Deduplicates near-identical consecutive states.

5. **Correction processor**: Reactive engine rule. When a correction arrives, embeds it, stores it in `perception-corrections`, and triggers pattern re-evaluation.

6. **Consolidation agent**: Tier 2 (LLM). Runs periodically (daily? weekly?). Reviews recent episodes, extracts patterns, writes to `operator-patterns`. Applies temporal decay to old patterns. This is the "reflection" stage from the Storage-Reflection-Experience progression.

7. **Retrieval-augmented activity classifier**: Replace or augment the current rule-based `classify_activity_mode()` with a function that retrieves relevant past episodes and corrections before classifying.

---

## 4. Implementation Possibilities

Ordered from simplest to most ambitious. Each level subsumes all previous levels.

### Level 1: Correction Memory (weeks of work)

Store every operator correction permanently. On each activity classification, retrieve relevant past corrections via semantic search. If a similar situation was corrected before, prefer the correction.

- Extend activity correction endpoint to write to Qdrant
- Add semantic embedding of correction context (signals + label)
- Retrieve top-3 corrections at classification time
- Include retrieved corrections in activity classifier logic
- Dashboard in cockpit showing correction history

This alone would eliminate the "same mistake twice" problem. The system would never again classify "reading documentation" as "idle" after being corrected once, because the correction memory would be retrieved for any future low-typing-high-presence situation.

### Level 2: Episodic Memory (1-2 months of work)

Write perception episodes to Qdrant. Implement change detection to avoid storing redundant episodes. Build retrieval-augmented interpretation.

- Episode writer agent with intelligent downsampling (store on signal change, on correction, on periodic heartbeat)
- Episode schema with full signal context
- Semantic search over episodes for "situations like this one"
- Include relevant past episodes in perception prompts
- Temporal decay on episode relevance (recent episodes weighted higher)
- Qdrant payload filtering for time-of-day, day-of-week, activity-mode queries

The system would learn temporal patterns: "This signal combination at 10pm on a weekday has historically meant X."

### Level 3: Pattern Consolidation (2-3 months of work)

LLM-driven reflection that extracts general patterns from specific episodes.

- Consolidation agent runs daily, reviews uncategorized episodes
- Extracts if-then patterns: "IF face_present AND typing_stopped AND browser_on_docs THEN activity = reading_documentation (confidence 0.85, based on 47 episodes, 3 corrections)"
- Patterns stored with validity intervals (bi-temporal model)
- Old patterns that stop being confirmed decay in confidence
- New patterns that contradict old patterns close old pattern validity
- Pattern library browsable in cockpit web UI

The system develops "intuitions" -- pre-computed interpretations for known situations that are fast and confident, paralleling Dreyfus's expert-level pattern recognition.

### Level 4: Active Correction Seeking (3-4 months of work)

The system asks for corrections when uncertain, rather than waiting for the operator to notice errors.

- Confidence calibration from WS2 self-regulation work
- Uncertainty threshold below which the system asks
- Question framing that is minimally intrusive (ambient notification, not interruption)
- Diminishing query frequency as the system improves (don't keep asking about the same thing)
- "Exploration budget" -- a fixed number of queries per day to avoid annoyance
- Feedback from answers improves both the specific classification and the confidence calibrator

This is where the system transitions from passive learning to active learning. AuDHD accommodations (per operator profile) constrain when and how questions are asked -- never during flow state, prefer quick multiple-choice over open-ended.

### Level 5: Cross-Modal Experience Fusion (4-6 months of work)

Link experiences across perception modalities. A heart rate spike + frown + fast typing is a *combined experience* that means something the individual signals do not.

- Multi-signal episode embeddings (not just text descriptions, but fused vector representations)
- CLAP-style cross-modal embeddings for audio-visual-biometric fusion
- Pattern extraction that spans modalities: "When biometric arousal is high AND visual signals show concentration AND audio is silent, operator is in deep debugging flow -- this is different from biometric arousal high AND visual shows tension AND audio has sighing, which is frustration"
- Multimodal Qdrant collections with named vectors per modality
- Cross-modal retrieval: query by any modality, retrieve episodes matching across all modalities

### Level 6: Temporal Knowledge Graph (6-9 months of work)

Replace flat vector storage with a temporal knowledge graph following the Graphiti/Zep pattern.

- Entity nodes: operator states (flow, idle, frustrated, creative), activities (coding, reading, meeting), contexts (time-of-day, environment, social situation)
- Relationship edges with validity intervals: "coding after 9pm → flow_likely (valid 2026-01-15 to present, confidence 0.82, 156 episodes)"
- Community nodes for high-level summaries: "evening coding sessions" as a recognized context with known properties
- Graph queries that combine entity matching with temporal filtering
- Contradiction detection: new patterns that conflict with existing graph relationships
- Graph visualization in cockpit web UI

This would give the system a genuine "world model" of the operator's patterns -- not just isolated memories but a connected understanding of how activities, states, contexts, and outcomes relate.

### Level 7: Skill Crystallization via Fine-Tuning (9-12 months of work)

When patterns are stable and well-confirmed, crystallize them into local model weights.

- Extract training data from consolidated patterns and their supporting episodes
- LoRA fine-tuning on Ollama local model (RTX 3090 supports QLoRA for 7B-70B models)
- Dual-model architecture: fine-tuned local model for "fast path" (known patterns), cloud model for "slow path" (novel situations)
- Continuous evaluation: compare fine-tuned model predictions against cloud model and corrections
- TreeLoRA for continual learning: new patterns get new branches without forgetting old ones
- MSSR-style replay scheduling: reinforce fading patterns before they are lost
- Automatic rollback if fine-tuned model accuracy degrades

This is the full Dreyfus skill model in engineering: the fine-tuned model is the expert that sees patterns directly, the cloud model is the reflective practitioner that handles the unfamiliar, and the correction memory is the learning mechanism that drives improvement.

### Level 8: Autonomous Experience Architecture (12+ months of work)

The system manages its own experiential architecture, following A-Mem's self-organizing principle.

- Memory orchestrator that decides what to store, retrieve, consolidate, and forget
- Self-evaluating: the system monitors which memories actually improve its accuracy
- Memory pruning based on measured utility (not just temporal decay)
- Automatic schema evolution: new perception signals automatically get incorporated into the episode schema
- Cross-context transfer: experiences from one operator context automatically inform related contexts
- Meta-learning: the system learns how to learn -- which types of experiences are most valuable, how often to consolidate, when to crystallize into weights

---

## 5. Open Questions

### Architecture Questions

1. **Episode sampling rate**: 34,560 ticks per day at 2.5s intervals is too many to store raw. What is the right downsampling strategy? Change detection? Fixed intervals? Significance scoring? The answer affects storage costs, retrieval quality, and temporal resolution.

2. **Embedding strategy for perception episodes**: Should episodes be embedded as text descriptions ("face present, typing stopped, browser on docs, 10pm Tuesday") or as structured vectors (one dimension per signal)? Text embeddings enable semantic similarity ("situations like this"), structured vectors enable exact signal matching. Probably both.

3. **Consolidation frequency**: How often should the reflection agent run? Too frequent = wasteful; too rare = patterns take too long to emerge. Likely adaptive: more frequent when corrections are happening, less frequent during stable periods.

4. **Graph vs. flat vector**: At what scale does a knowledge graph outperform flat vector search? For 1,000 episodes, vector search is probably sufficient. For 100,000 episodes with complex inter-relationships, graph queries become essential. The transition point needs empirical testing.

5. **Fine-tuning trigger**: What criteria determine when patterns are "stable enough" to warrant crystallization into model weights? Number of confirming episodes? Time since last contradiction? Correction rate below threshold? This needs a formal stability metric.

### Governance Questions

6. **Consent for non-operator memories**: If the system learns "when a guest is present, the operator behaves differently," is that a memory about the operator or the guest? The `interpersonal_transparency` axiom requires consent for modeling non-operator persons. Perception episodes during guest presence need special handling -- perhaps storing the operator's behavioral shift without storing information about the guest.

7. **Right to forget**: The operator should be able to delete experiential memories. But if a memory has been consolidated into a pattern, and the pattern has been crystallized into model weights, deletion requires unwinding all three levels. What does "genuine forgetting" look like across the full stack?

8. **Experience portability**: If the operator switches hardware or reinstalls the system, should experiential memory be portable? This implies an export/import mechanism for the full memory stack.

### Phenomenological Questions

9. **Skill vs. bias**: How do you distinguish "the system has learned this operator's patterns" (skill) from "the system has overfitted to recent behavior and cannot handle change" (bias)? The temporal decay mechanisms address this partially, but there may be more fundamental approaches.

10. **Perceptual fluency vs. perceptual blindness**: As the system becomes skilled at interpreting familiar patterns, does it become *worse* at noticing novel patterns? Expert chess players can miss unusual positions because their pattern recognition is tuned to common ones. The WS2 novelty detection work is the counter-mechanism, but the interaction between skill development and novelty sensitivity needs explicit design.

11. **The interpretation spiral**: If the system retrieves past episodes to inform current interpretation, and those past episodes were themselves informed by earlier retrievals, interpretation quality could spiral upward (self-reinforcing accuracy) or downward (self-reinforcing error). What circuit breakers prevent error spirals? Regular "clean" interpretations without memory retrieval, compared against memory-augmented interpretations, could detect divergence.

12. **Temporal horizons for different skills**: Some perceptual skills should develop quickly (learning the operator's daily schedule), others slowly (learning the operator's long-term creative patterns). Should different types of memory have different consolidation rates?

---

## 6. Sources

### Foundational Surveys and Taxonomies

- [Memory in the Age of AI Agents](https://arxiv.org/abs/2512.13564) -- Shichun-Liu et al., December 2024. Comprehensive taxonomy of agent memory types.
- [From Human Memory to AI Memory](https://arxiv.org/html/2504.15965v2) -- Survey on memory mechanisms in the era of LLMs, April 2025.
- [Rethinking Memory in AI: Taxonomy, Operations, Topics, and Future Directions](https://arxiv.org/html/2505.00675v2) -- May 2025.
- [Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Emerging Frontiers](https://arxiv.org/html/2603.07670) -- March 2026.
- [From Storage to Experience: A Survey on the Evolution of LLM Agent Memory Mechanisms](https://www.preprints.org/manuscript/202601.0618/v1/download) -- January 2026.
- [Agent Memory Paper List](https://github.com/Shichun-Liu/Agent-Memory-Paper-List) -- Curated paper collection, continuously updated.
- [Awesome Memory for Agents](https://github.com/TsinghuaC3I/Awesome-Memory-for-Agents) -- TsinghuaC3I curated collection.

### Memory Systems and Frameworks

- [MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/abs/2310.08560) -- Packer et al., October 2023. Virtual context management.
- [Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory](https://arxiv.org/abs/2504.19413) -- April 2025. Production memory layer.
- [Zep: A Temporal Knowledge Graph Architecture for Agent Memory](https://arxiv.org/abs/2501.13956) -- Rasmussen, January 2025. Temporal knowledge graphs.
- [Graphiti: Build Real-Time Knowledge Graphs for AI Agents](https://github.com/getzep/graphiti) -- Open-source temporal knowledge graph engine.
- [A-Mem: Agentic Memory for LLM Agents](https://arxiv.org/abs/2502.12110) -- Xu et al., NeurIPS 2025. Self-organizing Zettelkasten-style memory.
- [MemVerse: Multimodal Memory for Lifelong Learning Agents](https://arxiv.org/abs/2512.03627) -- December 2025. Dual-path multimodal architecture.
- [Memento: Fine-tuning LLM Agents without Fine-tuning LLMs](https://arxiv.org/abs/2508.16153) -- August 2025. Case-bank memory for experience-based improvement.
- [TeleMem: Building Long-Term and Multimodal Memory for Agentic AI](https://arxiv.org/abs/2601.06037) -- January 2026.
- [Letta V1 Architecture](https://www.letta.com/blog/letta-v1-agent) -- Rearchitected agent loop, 2025.
- [Intro to Letta](https://docs.letta.com/concepts/memgpt/) -- Documentation.
- [Amazon Bedrock AgentCore Episodic Memory](https://aws.amazon.com/blogs/machine-learning/build-agents-to-learn-from-experiences-using-amazon-bedrock-agentcore-episodic-memory/) -- December 2025.

### Correction-Driven and Feedback Learning

- [MemPrompt](https://memprompt.com/) -- Madaan et al., 2022. Learning from user feedback via memory.
- [MemOrb: A Plug-and-Play Verbal-Reinforcement Memory Layer](https://arxiv.org/html/2509.18713) -- September 2025.
- [MemAlign: Building Better LLM Judges From Human Feedback](https://www.databricks.com/blog/memalign-building-better-llm-judges-human-feedback-scalable-memory) -- Databricks, 2025.
- [MemoryBench: A Benchmark for Memory and Continual Learning](https://arxiv.org/html/2510.17281v2) -- October 2025.
- [Training Language Models to Self-Correct via Reinforcement Learning (SCoRe)](https://arxiv.org/abs/2409.12917) -- 2024.

### Personalization and Operator Modeling

- [PersonalLLM](https://proceedings.iclr.cc/paper_files/paper/2025/file/a730abbcd6cf4a371ca9545db5922442-Paper-Conference.pdf) -- ICLR 2025. Benchmarking personalization.
- [Teaching Language Models to Evolve with Users (RLPA)](https://arxiv.org/html/2505.15456v1) -- May 2025. Dynamic profile modeling.
- [Measuring What Makes You Unique (DPL)](https://arxiv.org/abs/2503.02450) -- ACL 2025 Findings. Difference-aware modeling.
- [Personalized Language Modeling from Personalized Human Feedback](https://arxiv.org/abs/2402.05133) -- February 2024.
- [PREMIUM: LLM Personalization with Individual-level Preference Feedback](https://openreview.net/forum?id=N1pya6kv3g) -- 2025.
- [Enabling Personalized Long-term Interactions through Persistent Memory and User Profiles](https://arxiv.org/abs/2510.07925) -- October 2025.

### Episodic Memory and Benchmarks

- [Episodic Memories Generation and Evaluation Benchmark](https://arxiv.org/html/2501.13121v1) -- January 2025.
- [Memoria: A Scalable Agentic Memory Framework for Personalized Conversational AI](https://arxiv.org/html/2512.12686v1) -- December 2024.
- [Human-Like Remembering and Forgetting in LLM Agents: ACT-R-Inspired](https://dl.acm.org/doi/10.1145/3765766.3765803) -- HAI 2025.
- [Multiple Memory Systems for Enhancing Long-term Memory of Agent](https://arxiv.org/html/2508.15294v1) -- August 2025.

### Context Compression and Management

- [Recursively Summarizing Enables Long-Term Dialogue Memory](https://arxiv.org/abs/2308.15022) -- Xu et al., 2023.
- [KVzip: AI tech compresses LLM chatbot conversation memory 3-4x](https://techxplore.com/news/2025-11-ai-tech-compress-llm-chatbot.html) -- November 2025.
- [Cutting Through the Noise: Smarter Context Management](https://blog.jetbrains.com/research/2025/12/efficient-context-management/) -- JetBrains Research, December 2025.
- [Context Engineering: Optimizing LLM Memory for Production AI Agents](https://medium.com/@kuldeep.paul08/context-engineering-optimizing-llm-memory-for-production-ai-agents-6a7c9165a431) -- October 2025.
- [LLM Chat History Summarization Guide](https://mem0.ai/blog/llm-chat-history-summarization-guide-2025) -- Mem0, 2025.

### Temporal Knowledge and Forgetting

- [FOREVER: Forgetting Curve-Inspired Memory Replay for Continual Learning](https://arxiv.org/abs/2601.03938) -- January 2026.
- [MSSR: Memory-Aware Adaptive Replay for Continual LLM Fine-Tuning](https://arxiv.org/abs/2603.09892) -- March 2026.
- [Memory Power Asymmetry in Human-AI Relationships](https://arxiv.org/html/2512.06616v1) -- December 2024.
- [Forgetful but Faithful: A Cognitive Memory Architecture for Privacy-Aware Agents](https://arxiv.org/html/2512.12856v1) -- December 2024.
- [Mastering Memory Consistency in AI Agents: 2025 Insights](https://sparkco.ai/blog/mastering-memory-consistency-in-ai-agents-2025-insights) -- 2025.

### Knowledge Graphs

- [LLM-empowered Knowledge Graph Construction: A Survey](https://arxiv.org/abs/2510.20345) -- October 2025.
- [Injecting Knowledge Graphs into Large Language Models](https://arxiv.org/abs/2505.07554) -- May 2025.
- [AriGraph: Learning Knowledge Graph World Models with Episodic Memory](https://www.ijcai.org/proceedings/2025/0002.pdf) -- IJCAI 2025.
- [LLM-TEXT2KG 2025: 4th International Workshop](https://aiisc.ai/text2kg2025/) -- Workshop proceedings.

### Fine-Tuning and Continual Learning

- [Fine-Tuning LLMs with LoRA: 2025 Guide](https://amirteymoori.com/fine-tuning-llms-with-lora-a-practical-guide-for-2025/) -- 2025.
- [TreeLoRA: Efficient Continual Learning via Layer-Wise LoRAs](https://www.lamda.nju.edu.cn/qianyy/paper/ICML25_TreeLoRA.pdf) -- ICML 2025.
- [LoRAFusion: Efficient LoRA Fine-Tuning for LLMs](https://arxiv.org/html/2510.00206v1) -- October 2025.
- [Continual Learning of Large Language Models: A Comprehensive Survey](https://dl.acm.org/doi/10.1145/3735633) -- ACM Computing Surveys 2025.
- [SuRe: Surprise-Driven Prioritised Replay](https://www.arxiv.org/pdf/2511.22367) -- November 2025.

### Active Learning and Uncertainty

- [From Selection to Generation: A Survey of LLM-based Active Learning](https://arxiv.org/html/2502.11767v1) -- ACL 2025.
- [Do LLMs Estimate Uncertainty Well?](https://proceedings.iclr.cc/paper_files/paper/2025/file/ef472869c217bf693f2d9bbde66a6b07-Paper-Conference.pdf) -- ICLR 2025.
- [Active Learning and Human Feedback for Large Language Models](https://intuitionlabs.ai/articles/active-learning-hitl-llms) -- IntuitionLabs, 2025.
- [mem-agent: Equipping LLM Agents with Memory Using RL](https://huggingface.co/blog/driaforall/mem-agent-blog) -- HuggingFace, 2025.

### Multimodal Memory

- [A Survey on Multimodal Retrieval-Augmented Generation](https://arxiv.org/abs/2504.08748) -- April 2025.
- [Multimodal Data Storage and Retrieval for Embodied AI](https://arxiv.org/html/2508.13901v1) -- August 2025.

### Cross-Context and Transfer

- [EvolveR: Self-Evolving LLM Agents through an Experience-Driven Lifecycle](https://arxiv.org/html/2510.16079v1) -- October 2025.
- [Learning Hierarchical Procedural Memory for LLM Agents](https://arxiv.org/pdf/2512.18950) -- December 2025.

### Frameworks and Tools

- [Mem0 Platform](https://github.com/mem0ai/mem0) -- Open-source universal memory layer.
- [Qdrant Documentation: Filtering](https://qdrant.tech/documentation/concepts/filtering/) -- Advanced payload filtering.
- [Qdrant 2025 Recap](https://qdrant.tech/blog/2025-recap/) -- Feature summary.
- [Qdrant 1.16: Tiered Multitenancy & Conditional Updates](https://qdrant.tech/blog/qdrant-1.16.x/) -- 2025.
- [LlamaIndex Memory Documentation](https://developers.llamaindex.ai/python/framework/module_guides/deploying/agents/memory/) -- Agent memory modules.
- [LangChain Memory Overview](https://docs.langchain.com/oss/python/concepts/memory) -- Memory concepts.
- [The 6 Best AI Agent Memory Frameworks for 2026](https://machinelearningmastery.com/the-6-best-ai-agent-memory-frameworks-you-should-try-in-2026/) -- Comparative review.
- [Beyond the Bubble: Context-Aware Memory Systems in 2025](https://www.tribe.ai/applied-ai/beyond-the-bubble-how-context-aware-memory-systems-are-changing-the-game-in-2025) -- Tribe AI overview.
