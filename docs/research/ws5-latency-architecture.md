# WS5: Latency Architecture for Phenomenological Perception

**Research synthesis -- March 2026**

Core problem: A being-in-the-world that is always two seconds behind the world is not in the world -- it is chasing the world. LLM inference operates at seconds; biological perception operates at milliseconds. For an ambient perceptual system, this latency gap must be solved architecturally, not by making LLMs faster.

The key insight: not everything needs to be fast. Human perception itself is a hierarchy of temporal scales -- saccades at 200ms, attention shifts at seconds, mood at minutes, existential orientation at hours. The architecture must *match* these scales, not beat them.

---

## 1. Problem: Temporal Incoherence

The Hapax system aspires to Heideggerian readiness-to-hand -- a perceptual background that recedes from attention while functioning, surfacing only when something breaks. Readiness-to-hand requires temporal coherence: the tool must respond within the timescale of the activity it supports. A hammer that takes two seconds to register impact is not a hammer; it is an obstacle.

Current situation: the system already has multiple processing tiers, but they emerged from engineering pragmatism rather than from principled temporal design. The question is whether the existing tiers *happen* to match the right biological timescales, and what gaps remain.

Three sub-problems:

1. **Tier design**: What processing belongs at each timescale? What is the minimum set of tiers?
2. **Inter-tier coordination**: How do slow layers inform fast layers without blocking them?
3. **Temporal coherence**: How does the system avoid presenting stale interpretations as current reality?

---

## 2. Prior Art

### 2.1 Subsumption Architecture (Brooks, 1986)

Rodney Brooks's subsumption architecture is the foundational reference for tiered reactive control. The architecture decomposes behavior into a hierarchy of layers, where each layer implements a particular level of behavioral competence. Lower layers handle primitive, time-critical behavior (obstacle avoidance); higher layers handle more complex behavior (exploration, planning). Higher layers can *subsume* (suppress or inhibit) lower layers, but lower layers can always operate independently if higher layers fail or are slow.

Key design properties:
- **No central representation**: Each layer couples sensors to actuators directly. No shared world model that all layers must wait for.
- **Graceful degradation**: If the deliberative layer crashes, the reactive layer still avoids obstacles. The system degrades to simpler behavior rather than failing entirely.
- **Layered finite state machines**: Each layer is simple; complexity emerges from layer interaction, not from any single layer.

This maps directly to the Hapax requirement. The display state machine (AMBIENT/PERIPHERAL/INFORMATIONAL/ALERT) is already a subsumption-like reactive layer. If the LLM interpretation layer goes down, the display state machine still functions on cached signals -- it degrades to "last known interpretation" rather than crashing.

### 2.2 Hybrid Reactive-Deliberative Architectures

The robotics literature extensively studied the tension between reactive and deliberative systems in the 1990s-2000s. The canonical solution is a hybrid architecture that runs two coordinated loops in parallel: a fast reactive loop that handles time-critical events and a slower deliberative loop that maintains goals and plans, with the loops sharing common memory and overseen by an arbitrator that resolves conflicts.

The three-layer architecture that emerged as standard in autonomous robotics:
- **Reactive layer**: Low-level, real-time sensor-to-actuator mappings. Handles obstacle avoidance, reflex-like behaviors. Microsecond to millisecond response.
- **Deliberative layer**: State estimation, planning, medium-term decision-making. Second to minute response.
- **Meta-cognitive layer**: Long-horizon goal management, strategy evaluation, adaptation. Minutes to hours.

This maps cleanly onto the four-tier model proposed for Hapax (see Section 4).

### 2.3 System 1 / System 2 in AI (Kahneman-inspired architectures)

Several 2024-2025 research programs apply Kahneman's dual-process theory to AI systems. The "System 0" framework (Cyberpsychology, Behavior, and Social Networking, 2025) proposes a layer *beneath* System 1 -- a pre-conscious cognitive extension that preprocesses information before it even reaches intuitive judgment. This resonates with Hapax's deterministic fast layer, which processes signals into display states without any interpretation.

The dual-process framing maps to Hapax as:
- **System 0**: DisplayStateMachine + ContentScheduler -- pure arithmetic, zero interpretation
- **System 1**: Local ML models (YOLO, BlazeFace, HSEmotion, Places365) -- fast pattern recognition, no reasoning
- **System 2**: LLM interpretation -- recontextualization, affordance reasoning, situation narrative

### 2.4 Real-Time LLM Systems in Production

Production systems that combine LLM inference with real-time requirements consistently use the same pattern: a fast deterministic path handles immediate user interaction while LLM inference runs asynchronously to enrich, correct, or reinterpret.

Key latency benchmarks (2025-2026):
- **Time to first token (TTFT)**: 100-500ms for cloud LLMs, 50-200ms for local models
- **Inter-token latency (ITL)**: 10-50ms for modern serving frameworks
- **End-to-end voice pipelines**: Streaming ASR + RAG + quantized LLM + TTS achieving sub-500ms total latency through pipelined parallelism

Real-time voice systems (the closest production analogy to ambient perception) solve this by streaming: the ASR produces partial results immediately, the LLM begins generating before the full prompt is assembled, and TTS begins speaking before the full response is complete. Each stage operates at its own cadence.

### 2.5 Edge-Cloud Hybrid Architectures

The edge-cloud AI pattern directly parallels the Hapax local/remote split. A 2025 paper found that hybrid edge-cloud processing for agentic AI workloads yields energy savings of up to 75% and cost reductions exceeding 80% compared to pure cloud processing. The pattern: edge handles latency-sensitive, privacy-sensitive, and high-frequency processing; cloud handles training, complex reasoning, and cross-session analysis.

The policy-based routing concept is relevant: a partitioning layer dynamically determines where computations should execute based on bandwidth, urgency SLAs, compute costs, and privacy requirements. Hapax already implements a form of this -- LiteLLM routes to Ollama (local) or Claude/Gemini (cloud) based on model alias, but does not yet route based on latency requirements.

### 2.6 Speculative Decoding and Predictive Caching

Speculative decoding uses a small "draft" model to generate candidate tokens that a larger "verifier" model confirms in batched parallel passes. Eagle3 (2025 state-of-the-art) achieves 2-3x speedup without quality loss by using hidden states from three layers of the verifier model.

More relevant to Hapax: **InstCache** (arXiv 2411.13820) proposes predictive caching of instruction-response pairs for LLM serving. The system pre-computes likely responses for anticipated queries. This maps to the Hapax scenario where the LLM could pre-compute situation interpretations for anticipated perceptual states (e.g., "operator returns to desk after absence" could be pre-cached as a recontextualization frame).

### 2.7 Small Language Model Capabilities (2025-2026)

NVIDIA's June 2025 position paper ("Small Language Models are the Future of Agentic AI") argues that the next advance in practical AI comes from models getting smaller, not larger. For repetitive, specialized tasks -- exactly what perception classification is -- SLMs (1-7B parameters) match or exceed frontier models when fine-tuned.

Current capability frontier for small models on RTX 3090 (24GB VRAM):
- **Ultra-compact (0.5-2B)**: Text classification, command parsing, structured output generation. 200-400 tokens/second via Ollama.
- **Compact (2-5B)**: Reasoning, summarization, code understanding. 100-200 tokens/second.
- **Standard (7-8B)**: Near-frontier performance on focused tasks. 80-110 tokens/second via Ollama with Q4_K_M quantization.

Key benchmark: Llama 3.2 3B, fine-tuned for a specific classification task, can match GPT-4 on that task while running at 200+ tokens/second locally. The latency for a 50-token classification response: ~250ms.

### 2.8 Knowledge Distillation for Perception

Task-specific distillation compresses frontier model capabilities into smaller, faster student models. A distilled model typically achieves 2-8x faster inference than its teacher. The pattern for Hapax: use Claude/Gemini to generate high-quality perceptual interpretations offline, then distill those interpretations into a local 3B model that can produce similar outputs in real time.

Microsoft's 2025 distillation framework and Alibaba's EasyDistill toolkit both demonstrate that enterprise-specific distillation is now practical without research-team resources.

### 2.9 Neuroscience of Temporal Hierarchies

The brain implements a strict temporal hierarchy in cortical processing:

- **Primary sensory areas**: Short intrinsic timescales (~10-50ms). Fast reaction to incoming stimuli. Analogous to the fast deterministic tier.
- **Association cortex**: Medium timescales (~100ms-1s). Integrates information across sensory modalities. Analogous to the local ML tier.
- **Prefrontal cortex**: Long timescales (~seconds-minutes). Maintains context, plans, goals. Analogous to the LLM interpretation tier.
- **Default mode network**: Very long timescales (~minutes-hours). Self-referential processing, consolidation. Analogous to the deep reflection tier.

A 2024 study (Journal of Neuroscience) demonstrated that information timescales increase hierarchically along the anatomical hierarchy of the visual system, while information-theoretic predictability *decreases*. In other words: lower layers are fast and predictable; higher layers are slow and surprising. This is exactly the structure needed for ambient perception -- the fast layers handle the predictable (state machine transitions), and the slow layers handle the novel (new situations requiring interpretation).

Neural oscillations dynamically adjust temporal resolution to perceptual demands. The brain increases resolution when the environment demands segregation of events and decreases it when integration is appropriate. This maps to the Hapax content scheduler's attention model -- high-urgency signals should increase the system's temporal resolution (faster polling), while calm periods can decrease it (longer intervals).

### 2.10 Human Perceptual Latency Requirements

Research on human perception and technology interaction establishes clear thresholds:

| Latency | Perception |
|---------|-----------|
| <13ms | Below conscious detection threshold |
| <100ms | Perceived as instantaneous |
| <200ms | Below "just noticeable difference" for most tasks |
| 200-400ms | Detectable; recruits attention and action control regions |
| <1s | Acceptable for interactive dialogue |
| >10s | Complete attention loss for average user |

For ambient displays specifically, the requirements are looser than for interactive systems. Weiser's calm technology principle states that peripheral information should move smoothly between the periphery and center of attention. The key is not raw speed but *temporal coherence* -- the display should not flicker, jump, or present obviously stale information. For ambient updates, 1-5 second latency is acceptable if transitions are smooth. For attention-demanding alerts, sub-second is necessary.

### 2.11 Calm Technology Design Principles

Mark Weiser and John Seely Brown (1995) established that calm technology operates primarily in the user's periphery, surfacing to the center of attention only when needed. Three core principles:
1. Attention resides mainly in the periphery
2. The technology increases peripheral awareness without overburdening
3. The technology conveys familiarity and temporal continuity (past, present, future awareness)

The latency implication: calm technology must never *demand* attention through temporal artifacts (lag, stutter, sudden updates). This means the fast tier must produce smooth, continuous output even when the slow tier is mid-computation. The system should always have something coherent to display, even if it is not the most current interpretation.

---

## 3. Hapax Architecture Mapping

### 3.1 Current Tiers (as built)

| Tier | Cadence | Components | Processing |
|------|---------|-----------|-----------|
| **DETERMINISTIC** | 15s tick | `VisualLayerAggregator.poll_fast()`, `DisplayStateMachine.tick()`, `ContentScheduler` | Pure logic. Polls health/GPU, computes state transitions, selects content. No ML, no LLM. Writes to `/dev/shm`. |
| **LOCAL ML** | 3-8s per source | Vision backend (YOLO11n ~3s/camera), BlazeFace (<5ms/frame CPU), HSEmotion (~20ms/face GPU), Places365 ResNet18 (~30ms GPU), Silero VAD (~5ms/frame CPU), SenseVoice, gaze/gesture (MediaPipe CPU) | GPU inference via VRAMLock coordination. Results cached in thread-safe structures. `contribute()` reads from cache, never blocks. |
| **API/COCKPIT** | 60s tick | `VisualLayerAggregator.poll_slow()` -- nudges, briefing, drift, goals, copilot | HTTP calls to cockpit API. Results are LLM-produced by upstream agents but cached server-side. |
| **LLM WORKSPACE** | Event-driven (~60s staleness) | `WorkspaceMonitor` -- screen capture + webcam → `WorkspaceAnalyzer` (Gemini Flash) | Full LLM call with multi-image input. 2-5 second latency. Triggered by focus change or staleness timer. |
| **REACTIVE ENGINE** | File-change events | inotify watcher → 12 rules → phased execution | LLM agents bounded at 2 concurrent. Seconds to minutes per agent. |

### 3.2 Data Flow

```
Cameras (3s)  ──► Vision Backend ──► perception-state.json ──► Aggregator (15s) ──► DisplayStateMachine
                                                                                          │
Microphone ──► Silero VAD ──► PresenceDetector ──► perception-state.json ──────────────────┘
                                                                                          │
Cockpit API (60s) ──► Aggregator ──────────────────────────────────────────────────────────┘
                                                                                          │
Hyprland IPC ──► WorkspaceMonitor ──► WorkspaceAnalyzer (LLM) ──► workspace_state.json ───┘
                                                                                          │
                                                                          VisualLayerState (JSON)
                                                                                          │
                                                                          /dev/shm/hapax-compositor/
                                                                                          │
                                                                          Studio Compositor (reads + renders)
```

### 3.3 What Works

The existing architecture already embodies tiered processing. Specific strengths:

1. **Subsumption-like degradation**: If the LLM workspace analyzer goes down, perception signals still flow through the deterministic path. The display state machine operates on whatever signals are available.

2. **Shared-memory IPC**: The `/dev/shm` path for compositor state is zero-copy and sub-microsecond. This is the right mechanism for the fast path.

3. **VRAMLock coordination**: GPU models take turns rather than competing. This prevents the classic problem where a heavy model starves the fast models.

4. **Perception state file as bus**: The `perception-state.json` file acts as a decoupling layer -- the perception engine writes, the aggregator reads, neither blocks the other.

5. **Two-cadence polling**: The 15s/60s split in the aggregator correctly separates fast-changing signals (health, GPU) from slow-changing signals (briefing, goals).

### 3.4 Gaps

**Gap 1: The 15-second deterministic tick is too slow for perceptual coherence.**
The DisplayStateMachine ticks every 15 seconds. For a calm ambient display, this means state transitions happen in 15-second jumps. A person entering the room would not be reflected in the visual layer for up to 15 seconds. The neuroscience literature shows that attention-relevant environmental changes should register within 200ms-1s. The fix: separate the *polling* cadence (can remain 15s for API calls) from the *state machine tick* cadence (should be 1-2s, reading from the already-written perception-state.json).

**Gap 2: No predictive pre-computation.**
The system reacts to perceptual changes after they happen. It never anticipates. The content scheduler scores content based on current state, but no component pre-computes likely next states and caches interpretations for them. Example: when the operator is in deep flow and has been for 30 minutes, the system could pre-compute the "flow break" interpretation (stretch reminder, pending nudges summary) so it is ready instantly when flow breaks.

**Gap 3: LLM interpretation is fire-and-forget.**
The WorkspaceAnalyzer calls Gemini Flash and waits for a response. There is no streaming, no partial result handling, and no timeout-with-fallback. If the LLM call takes 5 seconds, the workspace monitor is blocked for 5 seconds. There is no mechanism for the fast layer to use a partial or draft interpretation while the full interpretation completes.

**Gap 4: No local LLM for perception interpretation.**
The system uses Ollama for other tasks but not for perception. The workspace analyzer routes to Gemini Flash (cloud). For a system with an RTX 3090, a local 3-7B model could handle perception classification and basic situation narration with 200-500ms latency, eliminating the cloud round-trip.

**Gap 5: No temporal coherence signaling.**
The visual layer state has a timestamp but no concept of "confidence decay." A 15-second-old interpretation is presented with the same visual weight as a 1-second-old one. There should be a staleness gradient -- signals should visually fade as they age, and the system should indicate when it is operating on stale data.

**Gap 6: No dynamic cadence adjustment.**
All polling intervals are fixed. The neuroscience literature shows that biological perception dynamically adjusts temporal resolution based on environmental demands. When the environment is changing rapidly (person enters, alert fires), the system should increase its tick rate. When stable, it should decrease it to save resources.

**Gap 7: The perception state writer ticks at ~2.5s, but the aggregator only reads it every 15s.**
There is a 12.5-second information gap between when perception detects something and when the display reflects it. The perception state file is written every 2.5 seconds; the aggregator reads it every 15 seconds. The fix is trivial: read the perception state file on every aggregator tick, and increase the aggregator tick rate for the fast path.

---

## 4. Implementation Possibilities

Ordered by impact and feasibility. Each builds on the previous.

### 4.1 Decouple State Machine Tick from API Polling (Impact: HIGH, Effort: LOW)

Split the aggregator's single 15s loop into two:
- **Fast loop (1-2s)**: Read perception-state.json, run DisplayStateMachine, write visual-layer-state.json. Pure file I/O + arithmetic. Negligible CPU cost.
- **Slow loop (15s/60s)**: Poll cockpit API endpoints as currently implemented.

The fast loop always has access to the latest perception data. The slow loop enriches the signal set with API-derived information. The state machine merges both on every fast tick.

This single change eliminates Gaps 1 and 7. The visual layer goes from 15-second response to 1-2 second response for perception-derived signals, which is within the calm-technology acceptable range.

### 4.2 Temporal Coherence: Staleness-Weighted Opacity (Impact: MEDIUM, Effort: LOW)

Add an `age_s` field to `SignalEntry` (computed from source timestamp). The DisplayStateMachine multiplies zone opacity by a decay function: `opacity *= max(0.3, 1.0 - age_s / max_age_s)`. Signals fade as they age. The ambient shader subtly shifts when operating on stale data (e.g., slight desaturation).

This makes temporal coherence *visible*. The operator perceives the system's confidence in its own readings without conscious interpretation -- precisely the calm-technology design goal.

### 4.3 Local LLM for Perception Classification (Impact: HIGH, Effort: MEDIUM)

Deploy a fine-tuned 3B model (e.g., Llama 3.2 3B or Phi-3 Mini) via Ollama specifically for perception interpretation. This model would:
- Classify the current situation from perception state (200-500ms)
- Generate a one-sentence situation narrative
- Identify affordance changes ("new person entered," "operator switched from code to browser")

This replaces the Gemini Flash workspace analyzer call for the common case. The cloud LLM is reserved for complex situations (multi-person consent negotiation, ambiguous scenes, novel configurations). Route selection: the local model runs first; if its confidence is below threshold, the cloud model is queried as fallback.

Inference budget on RTX 3090: a Q4_K_M 3B model uses ~2GB VRAM and produces 200+ tokens/second. Even with VRAMLock sharing, a 50-token classification response completes in ~250ms. This is within the "perceived as instantaneous" threshold.

### 4.4 Predictive Pre-Computation (Impact: MEDIUM, Effort: MEDIUM)

Implement a small set of "likely next state" predictions that the LLM processes during idle time:

1. **Flow break anticipation**: When flow_score > 0.6 for >20 minutes, pre-compute the "flow break" frame (pending tasks summary, stretch reminder, time elapsed).
2. **Departure anticipation**: When operator is present, pre-compute the "departure" frame (end-of-session summary, tomorrow's first task).
3. **Arrival anticipation**: When operator is absent, pre-compute the "arrival" frame (morning briefing, overnight changes).
4. **Guest anticipation**: When a second person is detected, pre-compute the consent negotiation frame.

These are stored as pre-rendered `VisualLayerState` snapshots. When the triggering condition occurs, the fast layer selects the cached frame immediately rather than waiting for LLM inference. The cached frames are refreshed by the slow LLM tier on its normal cadence.

### 4.5 Dynamic Cadence (Impact: MEDIUM, Effort: LOW)

Replace fixed intervals with adaptive ones based on perceptual volatility:

```python
# Pseudocode
volatility = count_signal_changes_last_30s()
if volatility > HIGH_THRESHOLD:
    fast_interval = 0.5  # High change rate: increase temporal resolution
elif volatility > LOW_THRESHOLD:
    fast_interval = 1.0  # Normal
else:
    fast_interval = 2.0  # Stable: conserve resources
```

This mirrors the neural oscillation behavior where the brain dynamically adjusts temporal resolution. During rapid environmental change (person enters room, alert fires), the system responds at 500ms. During stable periods, it relaxes to 2s. This saves GPU cycles during the 80%+ of the time the system is in AMBIENT state.

### 4.6 Streaming LLM with Draft Fallback (Impact: MEDIUM, Effort: MEDIUM)

When the workspace analyzer or perception classifier makes an LLM call, use streaming to produce a "draft" interpretation after the first few tokens, then refine as the full response arrives:

1. Send prompt to LLM (local or cloud)
2. After first 10-20 tokens arrive (~100-200ms), extract a preliminary classification
3. Update the perception state with the draft classification (low confidence)
4. As the full response completes, replace the draft with the final interpretation

This eliminates the "all or nothing" pattern where the system has no interpretation for 2-5 seconds during inference. The fast layer always has *some* interpretation, even if preliminary.

### 4.7 Distillation Pipeline for Perception (Impact: HIGH, Effort: HIGH)

Build a continuous distillation loop:
1. **Collect**: Log all perception states and their corresponding LLM interpretations (already partially in place via Langfuse tracing).
2. **Curate**: Periodically review logged interpretation-pairs, filter high-quality examples.
3. **Distill**: Fine-tune a local 3B model on the curated dataset using LoRA.
4. **Deploy**: Swap the Ollama model for the fine-tuned version.
5. **Evaluate**: Monitor interpretation quality; fall back to cloud if degraded.

This is the long-term path to a local perception model that matches frontier quality on the specific domain of "Hapax operator at workstation." The model becomes increasingly specialized to the operator's specific environment, hardware, routines, and concerns -- approaching the Dreyfusian ideal of history-dependent, concern-relative perception.

### 4.8 Inference Framework Upgrade: vLLM or TensorRT-LLM (Impact: MEDIUM, Effort: HIGH)

Benchmarks show:
- **vLLM**: 793 TPS vs Ollama's 41 TPS in Red Hat's head-to-head test. P99 latency 80ms vs 673ms. PagedAttention + continuous batching.
- **TensorRT-LLM**: 62% faster than llama.cpp (Ollama's backend) on RTX 3090. FP8 quantization support.

For a single-user system with one GPU, the throughput advantage of vLLM is less relevant (no concurrent batching needed). The latency advantage is real: ~8x lower P99 latency means the 250ms local classification drops to ~30ms. Whether this matters depends on how many local LLM calls the system makes per second.

Recommendation: evaluate vLLM only after the local perception model (4.3) is proven. Ollama's simplicity is a significant operational advantage for a single-operator system.

---

## 5. Proposed Tier Architecture

After applying the implementation possibilities:

| Tier | Cadence | Function | Technology |
|------|---------|----------|-----------|
| **T0: Deterministic** | 0.5-2s adaptive | State machine, content scheduling, opacity computation, cached frame selection | Pure Python, `/dev/shm` IPC |
| **T1: Local Perception** | 2-8s per source | Object detection, face detection, emotion, gaze, gesture, scene, VAD | YOLO11n, BlazeFace, HSEmotion, Places365, Silero VAD, MediaPipe (GPU+CPU) |
| **T2: Local Interpretation** | 1-5s on change | Situation classification, narrative, affordance detection | Local 3B model via Ollama, 200-500ms per call |
| **T3: Cloud Interpretation** | Event-driven, 60s staleness | Complex scene analysis, novel situation interpretation, workspace analysis | Gemini Flash / Claude via LiteLLM |
| **T4: Deep Reflection** | Minutes-hours | Pattern recognition, profile updates, distillation data collection, session summaries | Reactive engine LLM agents, bounded at 2 concurrent |

Inter-tier coordination:
- Each tier writes to a shared state file (or `/dev/shm` for T0)
- Lower tiers never block waiting for higher tiers
- Higher tiers *enrich* lower-tier interpretations rather than *replacing* them
- Staleness is tracked per-signal; stale signals fade visually
- Pre-computed frames bridge the gap between T0 speed and T3/T4 depth

---

## 6. Open Questions

1. **VRAMLock contention**: Adding a local 3B interpretation model (T2) increases GPU competition with YOLO, HSEmotion, and Places365. Can VRAMLock schedule T2 inference in the gaps between T1 camera sweeps? What is the actual idle-time budget?

2. **Distillation quality threshold**: At what point does a distilled 3B model's interpretation quality degrade to the point where it harms rather than helps? What evaluation metric should gate the distillation deploy step?

3. **Predictive frame validity**: Pre-computed frames assume the future resembles the recent past. How quickly do pre-computed frames become misleading? Should there be a maximum cache age?

4. **Phenomenological adequacy**: The Dreyfus critique warns that feature-detection-and-classification is exactly the GOFAI pattern. Even with temporal coherence, is a tiered classification system fundamentally within *Ge-stell* (Enframing)? Does the distillation pipeline -- where the model becomes increasingly shaped by its specific environment -- begin to approach Freeman-style attractor dynamics, or is it still just better curve-fitting?

5. **Adaptive cadence stability**: Dynamic polling intervals could create oscillation (high volatility triggers fast polling, which detects more changes, which increases volatility). What damping function prevents this?

6. **Perception-action coupling**: The current system is perception-only -- it observes and displays but does not act. Merleau-Ponty's motor intentionality requires that perception and action form a loop. Does the operator's interaction with the display (glancing at it, ignoring it, adjusting settings) need to feed back into the perception tier to close this loop?

---

## 7. Sources

### Tiered and Reactive Architectures
- Brooks, R. (1986). [A Robust Layered Control System for a Mobile Robot](https://people.csail.mit.edu/brooks/papers/AIM-864.pdf). MIT AI Lab Memo.
- [Subsumption Architecture](https://en.wikipedia.org/wiki/Subsumption_architecture). Wikipedia.
- [Comparing the Top 5 AI Agent Architectures in 2025](https://www.marktechpost.com/2025/11/15/comparing-the-top-5-ai-agent-architectures-in-2025-hierarchical-swarm-meta-learning-modular-evolutionary/). MarkTechPost.
- [A Hybrid Cognitive Architecture to Generate, Control, Plan, and Monitor Behaviors for Interactive Autonomous Robots](https://link.springer.com/article/10.1007/s12369-024-01192-4). International Journal of Social Robotics, 2024.
- [System 0: Transforming Artificial Intelligence into a Cognitive Extension](https://www.liebertpub.com/doi/10.1089/cyber.2025.0201). Cyberpsychology, Behavior, and Social Networking, 2025.

### LLM Latency and Serving
- [Latency Optimization in LLM Streaming: Key Techniques](https://latitude.so/blog/latency-optimization-in-llm-streaming-key-techniques). Latitude, 2025.
- [Practical Guide to LLM Inference in Production](https://compute.hivenet.com/post/llm-inference-production-guide). Hivenet, 2025.
- [Toward Low-Latency End-to-End Voice Agents](https://arxiv.org/html/2508.04721v1). arXiv, 2025.
- [LLM Latency Benchmark by Use Cases](https://research.aimultiple.com/llm-latency-benchmark/). AIMultiple, 2026.
- [Ollama vs vLLM: Performance Benchmarking](https://developers.redhat.com/articles/2025/08/08/ollama-vs-vllm-deep-dive-performance-benchmarking). Red Hat, 2025.
- [vLLM vs TGI vs TensorRT-LLM vs Ollama](https://compute.hivenet.com/post/vllm-vs-tgi-vs-tensorrt-llm-vs-ollama). Hivenet, 2025.
- [Benchmarking LLM Inference Backends](https://www.bentoml.com/blog/benchmarking-llm-inference-backends). BentoML, 2025.

### Edge-Cloud and Hybrid Inference
- [Edge-Cloud Collaborative Computing on Distributed Intelligence](https://arxiv.org/html/2505.01821v1). arXiv, 2025.
- [Collaborative Inference and Learning between Edge SLMs and Cloud](https://arxiv.org/pdf/2507.16731). arXiv, 2025.
- [An Edge-Cloud Collaboration Framework for Generative AI Service Provision](https://arxiv.org/html/2401.01666v1). arXiv, 2024.
- [Beyond Cloud AI Orchestration: Why the Future is Hybrid Edge-Cloud Intelligence](https://flowfuse.com/blog/2025/10/the-ai-orchestration-hype/). FlowFuse, 2025.

### Speculative Decoding and Caching
- [Looking Back at Speculative Decoding](https://research.google/blog/looking-back-at-speculative-decoding/). Google Research, 2025.
- [InstCache: A Predictive Cache for LLM Serving](https://arxiv.org/abs/2411.13820). arXiv, 2024.
- [P-EAGLE: Faster LLM Inference with Parallel Speculative Decoding in vLLM](https://aws.amazon.com/blogs/machine-learning/p-eagle-faster-llm-inference-with-parallel-speculative-decoding-in-vllm/). AWS, 2025.
- [Efficient LLM System with Speculative Decoding](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2025/EECS-2025-224.html). UC Berkeley, 2025.

### Small Language Models
- Belcak, P. & Heinrich, G. (2025). [Small Language Models are the Future of Agentic AI](https://arxiv.org/abs/2506.02153). NVIDIA Research.
- [How Small Language Models Are Key to Scalable Agentic AI](https://developer.nvidia.com/blog/how-small-language-models-are-key-to-scalable-agentic-ai/). NVIDIA Technical Blog, 2025.
- [The State of LLMs 2025](https://magazine.sebastianraschka.com/p/state-of-llms-2025). Sebastian Raschka.
- [Efficient Inference for Edge Large Language Models: A Survey](https://www.sciopen.com/article/10.26599/TST.2025.9010166). Tsinghua Science and Technology, 2025.
- [A Review on Edge Large Language Models](https://dl.acm.org/doi/full/10.1145/3719664). ACM Computing Surveys, 2025.

### Knowledge Distillation
- [Knowledge Distillation and Dataset Distillation of LLMs: Emerging Trends](https://arxiv.org/abs/2504.14772). arXiv / Springer, 2025.
- [Why Enterprises Should Embrace LLM Distillation](https://snorkel.ai/blog/why-enterprises-should-embrace-llm-distillation/). Snorkel AI, 2025.
- [Distillation: Turning Smaller Models into High-Performance Solutions](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/distillation-turning-smaller-models-into-high-performance-cost-effective-solutio/4355029). Microsoft, 2025.

### Neuroscience of Temporal Processing
- [Signatures of Hierarchical Temporal Processing in the Mouse Visual System](https://pmc.ncbi.nlm.nih.gov/articles/PMC11373856/). PMC, 2024.
- [Uncovering a Timescale Hierarchy by Studying the Brain in a Natural Context](https://www.jneurosci.org/content/45/12/e2368242025). Journal of Neuroscience, 2025.
- [The Brain and Its Time: Intrinsic Neural Timescales Are Key for Input Processing](https://www.nature.com/articles/s42003-021-02483-6). Communications Biology, 2021.
- [Intrinsic Neural Timescales in the Temporal Lobe Support an Auditory Processing Hierarchy](https://www.jneurosci.org/content/43/20/3696). Journal of Neuroscience, 2023.

### Human Perceptual Latency
- [How Fast is Real-Time? Human Perception and Technology](https://www.pubnub.com/blog/how-fast-is-realtime-human-perception-and-technology/). PubNub.
- [Delays in Human-Computer Interaction and Their Effects on Brain Activity](https://pmc.ncbi.nlm.nih.gov/articles/PMC4712932/). PMC, 2016.
- [How Much Faster is Fast Enough? User Perception of Latency](https://www.tactuallabs.com/papers/howMuchFasterIsFastEnoughCHI15.pdf). CHI 2015.
- [Estimation of the Timing of Human Visual Perception from Magnetoencephalography](https://www.jneurosci.org/content/26/15/3981). Journal of Neuroscience, 2006.

### Calm Technology and Ambient Computing
- Weiser, M. & Brown, J.S. (1995). [Designing Calm Technology](https://people.csail.mit.edu/rudolph/Teaching/weiser.pdf). Xerox PARC.
- [Calm Technology: Principles and Patterns](https://calmtech.com/). CalmTech.
- [Principles of Calm Technology](https://www.caseorganic.com/post/principles-of-calm-technology). Amber Case.
