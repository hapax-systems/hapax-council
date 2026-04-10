# Hermes 3 70B Mono-Model Voice Architecture

**Date**: 2026-04-10
**Status**: Approved
**Session**: beta
**Hardware prerequisite**: Platform upgrade (RTX 5060 Ti 16GB, Ryzen 7 7700X, ASUS TUF X870-PLUS WIFI, 64GB DDR5)

---

## 1. Problem Statement

The hapax voice daemon implements Clark & Brennan's (1991) conversational grounding theory via a Traum (1994) DU state machine, grounding ledger, effort calibration, and phenomenal context rendering. The current local model (Qwen3.5-9B, EXL3 5.0bpw) uses full DPO/GRPO post-training, which — per Shaikh et al. (NAACL 2024, ACL 2025) — actively suppresses the grounding acts the system is designed to elicit.

Two research findings converge to motivate a model change:

1. **Mohapatra et al. (EMNLP 2024)**: Pre-training data size directly correlates with grounding ability. Larger models produce more grounding acts.
2. **Shaikh et al. (NAACL 2024)**: DPO/RLHF monotonically degrades grounding acts. Preference data literally trains models that asking questions is "bad."

The theoretical optimum is the largest available SFT-only model. Maximum grounding capability from scale, maximum grounding preservation from avoiding DPO. This is not a practical compromise — it is what the grounding theory demands.

An incoming hardware platform (RTX 3090 24GB + RTX 5060 Ti 16GB = 40GB VRAM) makes this viable.

## 2. Theoretical Foundation

Every design decision traces to existing commitments. Nothing is grafted.

### 2.1 Intelligence Decomposition

The system requires different kinds of intelligence for different processes. RLHF improves some and degrades others:

| Kind | Where needed | RLHF effect | Implication |
|---|---|---|---|
| Grounding competence (contribution-acceptance cycles, repair, conceptual pacts) | Voice conversation loop | Destroys (Shaikh: 77.5% fewer acts; DPO monotonic) | SFT-only required |
| Instruction compliance (system prompt, protocol adherence) | VOLATILE band directives, all agents | Degrades at scale (MathIF: inverse correlation) | SFT-only preferred |
| Controllability (responsiveness to external correction) | Grounding ledger directives, effort calibration | Destroys (base: 0% bias, RLHF: rho=0.036) | SFT-only required |
| Generative diversity (imagination, novelty) | Imagination/reverie, Bachelardian expression | Reduces (0% -> 28.5% single-cluster rate) | SFT-only preferred |
| Reasoning capability (structured output, multi-step logic) | Reactive engine agents, tool recruitment | Improves | Cloud models (Claude/Gemini) appropriate |
| Multimodal perception (visual frame understanding) | DMN evaluative tick | N/A (specialized model) | Gemini Flash (non-negotiable) |

### 2.2 The Mono-Model Argument

Grounding is not a per-call property. It is sequential, context-dependent, emergent from the model's internal state evolution across a conversation (synthesis Section 2). Two different models processing the same grounding ledger state produce incommensurable response dynamics.

The voice conversation loop AND imagination/reverie both require SFT-only properties (grounding preservation + generative diversity). A single SFT-only model serving both is theoretically convergent — the same properties serve both needs.

### 2.3 The Deployment Paradox Resolution

arXiv 2601.08842 found RLHF models resist correction in natural conversation but respond to "architectural overrides (system prompts, structured formats)." Hapax implements grounding directives via the VOLATILE band — architectural overrides by design. SFT-only models should respond to these with high fidelity, since SFT preserves base controllability while adding conversational fluency.

### 2.4 Active Inference Compatibility

The SCM commits to Friston's (2010) active inference framework. SFT-only models preserve base-model uncertainty expression. RLHF models suppress uncertainty ("I don't know" treated as penalty). A model that can express uncertainty feeds the prediction error signals the SCM depends on. RLHF breaks the active inference loop.

### 2.5 PCT Hierarchy Alignment

Powers (1973): behavior controls perceptions, not outputs. Stimmung is gain scheduling. GQI is effort calibration. The LLM sits at the bottom of the PCT hierarchy, executing directives set by reference values above. SFT-only models are responsive to reference signals; RLHF models resist reference adjustment.

### 2.6 Sycophancy as Anti-Grounding

arXiv 2602.01002 confirms RLHF creates an "Assertiveness Prior" dominating conversation. This structurally conflicts with Clark & Brennan's repair sequences — a sycophantic model won't flag misunderstanding, request clarification, or initiate repair. It is incompatible with the DU state machine's REPAIR_1/REPAIR_2 states.

### 2.7 Conceptual Pact Preservation

arXiv 2503.07457 shows users rapidly entrain to model vocabulary (94% within 5 interactions). A model that substitutes "correct" terminology for established shared vocabulary violates Brennan & Clark (1996) pacts. SFT-only models with strong system prompt compliance can be directed to preserve established vocabulary; RLHF models override system prompt vocabulary with their trained preferences.

## 3. Model Selection

### 3.1 Selected Model

**`NousResearch/Hermes-3-Llama-3.1-70B`**

| Property | Value | Source |
|---|---|---|
| Post-training | SFT-only | Technical report (arXiv 2408.11857): "For larger model sizes, DPO provides only negligible performance improvements, so [we] chose to remain with the SFT-phase checkpoints" |
| Base architecture | Llama 3.1 70B | 128K context, GQA (8 KV heads / 64 Q heads), native tool calling tokens |
| Parameters | 70B | |
| Training data | ~390M tokens synthetic, 69% output / 31% instruction | |
| System prompt design | Core goal: "aggressively encourages following system and instruction prompts exactly" | |
| Alignment philosophy | "Neutrally aligned" — steerable via system prompt, no built-in political/ethical bias | |
| Chat template | ChatML (`<\|im_start\|>system`) | Compatible with existing prompt construction |
| License | Llama 3.1 Community License | |

### 3.2 Eliminated Candidates

| Model | Reason for elimination |
|---|---|
| Hermes 4 70B | SFT + DPO — grounding degradation |
| Qwen3.5-9B (current) | DPO/GRPO post-training — grounding suppression |
| OpenHermes 2.5 (7B) | 4K sliding window context — VOLATILE band constraint; Mohapatra: 70B > 7B |
| SPIN iter1-3 (7B) | 4K sliding window; scale disadvantage |
| Tulu 3 SFT (8B) | GPT-4o distillation concern; poor AlpacaEval (12.4); scale disadvantage |
| Dolphin 3.0 (8B) | Orthogonal goal (uncensored); RLHFlow preference shaping |
| Hermes 3 8B | SFT + DPO at 8B scale |
| Gemma 3 27B | SFT + RLHF (WARM, RLEF) |
| All MoE models | ExllamaV2/TabbyAPI incompatible or VRAM-inefficient |

### 3.3 Research Horizon: SPIN-on-Llama-3.1-70B

Theoretical ideal: apply SPIN (distribution-matching alignment) to Llama 3.1 70B base. Combines maximum scale + grounding-preserving alignment + zero DPO contamination. Requires significant compute for training. Identified as a future research sprint, not immediate deployment target.

## 4. Hardware Platform

### 4.1 New Configuration

| Component | Specification |
|---|---|
| CPU | AMD Ryzen 7 7700X (Zen 4, AM5, 8C/16T, 4.5/5.4 GHz) |
| Motherboard | ASUS TUF GAMING X870-PLUS WIFI (AM5, PCIe 5.0) |
| RAM | 64GB DDR5 G.Skill Trident Z5 Neo (2x32GB, EXPO) |
| GPU 0 (primary) | NVIDIA RTX 3090 24GB GDDR6X (Ampere sm_86, 936 GB/s) |
| GPU 1 (secondary) | NVIDIA RTX 5060 Ti 16GB GDDR7 OC (Blackwell sm_120, 448 GB/s) |
| PCIe primary slot | x16 Gen 5 |
| PCIe secondary slot | x4 Gen 5 |
| Total VRAM | 40 GB |

### 4.2 Driver Requirements

- NVIDIA driver R570+ required (supports both Ampere and Blackwell)
- Target: driver 575.57.08 (confirmed working for mixed-generation setups)
- CUDA 12.8+ required for Blackwell sm_120
- PyTorch cu128 wheels required for ExllamaV2/V3

### 4.3 Known Risks

- Reports of Blackwell "GPU fallen off the bus" with driver 580.x
- DF SIGSEGV (sdl2-compat) previously occurred on 595.58 — needs testing on new driver
- Mixed-generation GPU support is evolving; thorough Phase 1 validation required

## 5. GPU Architecture

### 5.1 Strategy: Layer Splitting (Autosplit)

NOT tensor parallelism. Voice is batch=1, latency-sensitive. The trade-off:

| Method | PCIe syncs/token | Latency overhead/token | Throughput | Best for |
|---|---|---|---|---|
| Tensor parallelism | 80 (once per layer) | ~5ms (x4 slot) | Higher (parallel) | Batched inference |
| Layer splitting | 1 (at GPU boundary) | <0.1ms | Lower (sequential) | Single-request, low-latency |

Voice pipeline generates one response at a time. Latency matters more than throughput. Layer splitting wins.

### 5.2 Quantization: EXL3 3.0 bpw

| bpw | Model size | Layers on 5060 Ti | Free on 5060 Ti | Quality note |
|---|---|---|---|---|
| 3.0 | 26.25 GB | ~3/80 | ~6.5 GB | EXL3 "sweet spot"; +5% perplexity vs 4.0; 70B at 3.0 >> 9B at 5.0 |
| 3.5 | 30.6 GB | ~9/80 | ~2.4 GB | Excellent quality; tighter margin |
| 4.0 | 35.0 GB | ~15/80 | ~0 GB | Best quality; insufficient headroom |

Start with 3.0 bpw. Benchmark quality. Upgrade to 3.5 if headroom allows and quality delta justifies it.

### 5.3 VRAM Layout (3.0 bpw)

| Component | GPU | VRAM | Persistence |
|---|---|---|---|
| Hermes 3 70B layers 0-76 | RTX 3090 | ~23.5 GB | Persistent |
| Hermes 3 70B layers 77-79 | RTX 5060 Ti | ~2.75 GB | Persistent |
| faster-whisper distil-large-v3 (INT8) | RTX 5060 Ti | ~2.5 GB | Persistent (daemon startup) |
| KV cache (Q8_0, 4K tokens max) | Split proportionally | ~0.6 GB | Per-request |
| Activations + framework overhead | Both | ~1.0 GB | Per-request |
| CUDA contexts | Both | ~1.0 GB | Persistent |
| **Free headroom** | **RTX 5060 Ti** | **~6.5 GB** | Available |

### 5.4 KV Cache

Llama 3.1 70B with GQA (8 KV heads, 80 layers, head_dim=128):
- Per token (FP16): 0.31 MB
- Per token (Q8_0): 0.16 MB

Voice context: ~1200-1600 tokens typical, max ~4000 tokens.
- Q8_0 at 4000 tokens: 620 MB — fits comfortably in headroom

### 5.5 Inference Performance

| Metric | Hermes 3 70B @ 3.0bpw | Current Qwen3.5-9B @ 5.0bpw |
|---|---|---|
| Token generation (batch=1) | ~45-55 tok/s | ~100+ tok/s |
| 80-token voice response | ~1.5-1.8s | ~0.7-0.8s |
| Time-to-first-token | ~200-400ms | ~50-100ms |

Latency increase ~1s. Within design envelope (cloud tiers operate 1-3s; effort calibration and word limits keep responses short).

## 6. Service Configuration

### 6.1 TabbyAPI

```yaml
model:
  model_dir: models/Hermes-3-Llama-3.1-70B-EXL3-3.0bpw
  max_seq_len: 8192
  gpu_split: [23.5, 12.5]
  cache_mode: Q8

network:
  host: 0.0.0.0
  port: 5000
```

Tensor parallelism disabled (autosplit mode). ExllamaV2/V3 fills 3090 first, overflows to 5060 Ti.

### 6.2 LiteLLM Routes

| Route | Backend | Change |
|---|---|---|
| `local-fast` | TabbyAPI :5000 → Hermes 3 70B | Model upgrade |
| `coding` | TabbyAPI :5000 → Hermes 3 70B (thinking disabled) | Model upgrade |
| `reasoning` | TabbyAPI :5000 → Hermes 3 70B (thinking enabled) | Model upgrade |
| `balanced` | Claude Sonnet 4 | Unchanged |
| `fast` | Gemini 2.5 Flash | Unchanged |
| `claude-opus` | Claude Opus 4 | Unchanged |
| `gemini-flash` | Gemini 2.5 Flash | Unchanged |

### 6.3 CUDA Device Routing

| Process | CUDA Device | Notes |
|---|---|---|
| TabbyAPI (Hermes 3 70B) | CUDA:0 (primary) + CUDA:1 (overflow) | Autosplit handles distribution |
| faster-whisper STT | CUDA:1 | Persistent 2.5 GB reservation |
| Ollama (embedding) | CPU only | CUDA_VISIBLE_DEVICES="" unchanged |
| Kokoro TTS | CPU only | Unchanged |

### 6.4 Systemd Changes

**tabbyapi.service**: Update model path, add gpu_split configuration, increase TimeoutStartSec to 180s (larger model load).

**hapax-daimonion.service**: No service changes. Model selection is via LiteLLM route, not daemon config.

## 7. Voice Pipeline Integration

### 7.1 What Changes

- `local-fast` LiteLLM route resolves to Hermes 3 70B (was Qwen3.5-9B)
- Phenomenal context can use full CAPABLE tier rendering (128K context eliminates 4K constraint)
- Grounding directives in VOLATILE band should see improved compliance (SFT controllability)
- Token generation latency increases ~1s
- System prompt format: ChatML compatible with Hermes 3

### 7.2 What Does Not Change

- Grounding ledger, DU state machine, GQI computation — all unchanged, all frozen
- Acceptance classifier — model-agnostic, measures output
- Effort calibration and word limits — unchanged
- Conversation thread and cross-session memory — unchanged
- Salience router — unchanged (annotates context, doesn't select model in intelligence-first mode)
- All frozen experiment code paths — unchanged
- TTS (Kokoro 82M, CPU) — unchanged
- STT (faster-whisper, GPU) — unchanged process, different CUDA device

### 7.3 STT/LLM Coexistence

Voice pipeline states are sequential: LISTENING -> TRANSCRIBING -> THINKING -> SPEAKING. STT and LLM inference don't overlap within the voice pipeline.

Edge case: Reactive engine Phase 1 (GPU LLM) triggers during voice LISTENING. Both TabbyAPI and STT active on 5060 Ti simultaneously. Mitigated by persistent VRAM reservations — STT (2.5 GB) and model layers (2.75 GB) are pre-allocated. KV cache adds ~0.3 GB transiently. Total: ~5.5 GB of 12.5 GB usable. No conflict.

### 7.4 Non-Voice Workloads

All non-voice agents using `local-fast` route are automatically upgraded to Hermes 3 70B. Cloud routes unchanged. GPU semaphore remains at 1 concurrent. Reactive engine Phase 1/Phase 2 separation unchanged.

## 8. Experiment Program Interaction

### 8.1 Recommended Path

Complete current Phase A baseline with Qwen3.5-9B, then introduce Hermes 3 70B via deviation record.

### 8.2 Deviation Record (DEVIATION-033)

- **What**: Underlying LLM changed from Qwen3.5-9B (DPO/GRPO) to Hermes 3 70B (SFT-only)
- **Why**: Mohapatra-Shaikh convergence — pre-training scale improves grounding capability; SFT-only preserves it. The model change is theoretically motivated by the same research program the experiment tests.
- **Impact**: Potentially strengthens treatment effect (SFT-only more responsive to grounding directives). Model change becomes an additional independent variable. Phase A' establishes new baseline.
- **Mitigation**: Phase A data preserved. Analysis documents model change as confound. If Phase B effect increases relative to Phase A under Qwen3.5-9B, this is evidence for the SFT-only hypothesis.

### 8.3 Alternative: New Experimental Condition

The model swap itself could be formalized as a new claim: "Does an SFT-only model produce measurably higher turn_pair_coherence than a DPO model under identical grounding directives?" This is a direct test of the Shaikh hypothesis in hapax's production environment.

## 9. Migration Path

### Phase 0: Hardware Install

1. Swap CPU (5800XT -> 7700X), motherboard (B550 -> X870), RAM (DDR4 -> DDR5)
2. Install RTX 5060 Ti in secondary PCIe x4 slot (3090 stays in primary x16)
3. Boot, verify both GPUs detected (`nvidia-smi`)
4. Install driver 575.57.08
5. Verify CUDA 12.8+, both GPUs functional

### Phase 1: Inference Validation

1. Download or quantize Hermes 3 70B EXL3 3.0bpw
2. Configure TabbyAPI with `gpu_split: [23.5, 12.5]`
3. Benchmark: generation speed, quality spot-check, VRAM stability
4. Test faster-whisper on CUDA:1 simultaneously with TabbyAPI inference
5. Run grounding directive compliance tests (inject directives, measure adherence)
6. Sustained load test (30min continuous inference, monitor VRAM, thermals)

### Phase 2: Voice Integration

1. Update LiteLLM config (local-fast -> Hermes 3 70B endpoint)
2. Update TabbyAPI systemd unit (model path, gpu_split, timeout)
3. Test voice pipeline end-to-end (wake word -> STT -> LLM -> TTS)
4. Verify grounding ledger directive compliance in live conversation
5. Monitor latency, VRAM, thermals under sustained conversation
6. Spot-check imagination/reverie diversity with new model

### Phase 3: Experiment Alignment

1. File deviation record (DEVIATION-033) if experiment is active
2. Establish new baseline measurements with Hermes 3 70B
3. Begin Langfuse trace collection for turn_pair_coherence
4. Compare directive_compliance DV between Qwen3.5-9B and Hermes 3 baselines

## 10. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Mixed-gen GPU driver instability | Medium | High | Thorough Phase 1 testing; fallback to 3090-only with smaller model |
| 3.0 bpw quality insufficient for directive compliance | Low | Medium | Benchmark before committing; upgrade to 3.5 bpw |
| Voice latency too high (~1.5-2s generation) | Medium | Medium | Effort calibration constrains response length; tune word limits down |
| EXL3 3.0bpw quant not pre-made for Hermes 3 | Medium | Low | Self-quantize from HF weights; GGUF fallback via llama.cpp |
| Experiment baseline invalidation | Medium | High | Complete Phase A first; deviation record; data preserved |
| PCIe x4 bandwidth insufficient for layer overflow | Low | Low | Only 3/80 layers on 5060 Ti; minimal cross-GPU traffic |
| Thermal throttling under sustained dual-GPU load | Low | Medium | Monitor nvidia-smi; X870 VRM adequate |
| Hermes 3 ChatML template incompatible with prompt construction | Low | Low | ChatML is standard; existing system uses similar format |

## 11. Success Criteria

| Criterion | Measure | Target |
|---|---|---|
| Model loads and generates | TabbyAPI serves completions across both GPUs | Functional |
| Voice round-trip latency | End-to-end STT -> LLM -> TTS | < 4s |
| Grounding directive compliance | `directive_compliance` DV from grounding_evaluator | > 50% (vs Qwen3.5-9B baseline) |
| System prompt adherence | Manual spot-check of VOLATILE band injection | Faithful following |
| VRAM stability | nvidia-smi under 30min sustained use | No OOM, no progressive growth |
| STT coexistence | faster-whisper on 5060 Ti during LLM inference | < 200ms transcription latency |
| Generative diversity | Response variety in imagination context | No single-cluster collapse |
| KV cache headroom | Q8_0 cache at 4K tokens | Fits in remaining VRAM |

## 12. References

### Grounding Theory
- Clark, H.H. & Brennan, S.E. (1991). Grounding in communication.
- Brennan, S.E. & Clark, H.H. (1996). Conceptual pacts and lexical choice in conversation.
- Traum, D.R. (1994). A computational theory of grounding in natural language conversation.

### LLM Grounding Research
- Shaikh et al. (NAACL 2024). Grounding Gaps in Language Model Generations. arXiv:2311.09144.
- Shaikh et al. (ACL 2025). Navigating Rifts in Human-LLM Grounding. arXiv:2503.13975.
- Mohapatra et al. (EMNLP 2024). Evaluating the Effectiveness of LLMs in Establishing Conversational Grounding.
- Mohapatra et al. (LREC-COLING 2024). Conversational Grounding: Annotation and Analysis.

### Alignment & Controllability
- arXiv:2601.08842. Resisting Correction: How RLHF Makes Language Models Ignore External Safety Signals.
- arXiv:2602.01002. How RLHF Amplifies Sycophancy.
- arXiv:2503.07457. LLMs syntactically adapt their language use to their conversational partner.

### Model
- Hermes 3 Technical Report. arXiv:2408.11857.
- Chen et al. (ICML 2024). Self-Play Fine-Tuning. arXiv:2401.01335.

### Theoretical Frameworks
- Powers, W.T. (1973). Behavior: The Control of Perception.
- Friston, K. (2010). The free-energy principle: a unified brain theory.
- Bachelard, G. Poetic material imagination (water, fire, earth, air, void).
