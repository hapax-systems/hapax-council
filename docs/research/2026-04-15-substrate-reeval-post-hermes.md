# Substrate re-evaluation post-Hermes: is Qwen3.5-9B actually optimal?

**Date:** 2026-04-15
**Author:** beta (PR #819 author; research drop during Phase 4 bootstrap pre-staging window)
**Status:** DRAFT — research in progress, agent findings incoming
**Audience:** operator; alpha; delta; epsilon (secondary)
**Parent context:** drop #62 Option C ratified 2026-04-15; 70B Hermes 3 path killed; 5b backlog deleted from disk; operator direction "we've abandoned hermes" + "devote extensive research into if Qwen3.5-9B-exl3-5.00bpw is actually the best production substrate for our very unique use cases"

---

## 0. Headline

> *"We've abandoned hermes. Devote extensive research into if Qwen3.5-9B-exl3-5.00bpw is actually the best production substrate for our very unique use cases."* — operator, 2026-04-15T06:35Z

With the Hermes family excluded (not just 70B — all Hermes variants per operator direction), this document asks whether the currently-deployed `Qwen3.5-9B-exl3-5.00bpw` on TabbyAPI is the right choice for hapax's local-inference substrate, or whether a different small open-weight LLM would better serve hapax's use case profile.

**Research goal:** a defensible recommendation — keep Qwen3.5-9B, switch to a specific alternative, or run a bake-off — with explicit confidence and contingency framing.

**Research scope:** 7-14B open-weight LLMs released or significantly updated 2024-2026, excluding Hermes family, evaluated against hapax's production use cases (voice tier 1 fallback, specialized agents under pressure, coding/reasoning routes, continuous cognitive loop participation, pydantic-ai structured output, tool use, consent-latency budget, VRAM budget on RTX 3090).

---

## 1. Current substrate audit

### 1.1 What is actually deployed

**Path:** `~/projects/tabbyAPI/models/Qwen3.5-9B-exl3-5.00bpw/`
**Served by:** `tabbyapi.service` (systemd user unit) on `localhost:5000`, OAI-compatible API, exllamav3 backend version 0.0.22
**Published by:** Alibaba Qwen team, 2026-03-02 (HuggingFace release)
**License:** Apache 2.0
**Base model:** `Qwen/Qwen3.5-9B-Base`

### 1.2 Architecture

Qwen3.5-9B is a **native multimodal vision-language model** with these specific properties (from `config.json`):

- **9B dense parameters** — all-active, NOT MoE (the Qwen3.5 family includes MoE variants like 35B-A3B and 397B-A17B, but 9B is dense)
- **Hybrid attention:** Gated Delta Networks (linear attention, O(n·d²)) interleaved with full attention at a 3:1 ratio. Every 4th layer is `full_attention`; the rest are `linear_attention`. Per the `layer_types` array in config.json.
- **Vision and video towers:** separate visual encoder (`num_hidden_layers: 27`, `hidden_size: 1152`, `intermediate_size: 4304`, `patch_size: 16`) plus `video_preprocessor_config.json`. These path through `vision_start_token_id: 248053` / `vision_end_token_id: 248054`. **Hapax does not use the multimodal surface** — multimodal perception is routed to Gemini Flash in `shared/config.py` under `long-context` / `balanced` / `fast` tiers.
- **Context length:** 262K native (YaRN-extendable to ~1M). Hapax `tabbyapi/config.yml` sets `max_seq_len: 4096` + `chunk_size: 2048` + `cache_mode: 4,4` (Q4 KV cache). Hapax does not use long context on this substrate.
- **Thinking mode:** enabled by default at the chat-template level. Model emits `<think>...</think>` before the main response unless disabled via `chat_template_kwargs.enable_thinking=False`. **Current production config does not explicitly disable thinking mode** — needs verification; if thinking is on, every local-fast call pays the thinking-token latency tax on top of the actual response.
- **Tool use:** supported via the `qwen3_coder` tool-call parser in vLLM; exllamav3 tool-call support needs verification.

### 1.3 Post-training recipe (as of April 2026 published work)

This is the most important axis for the substrate decision. Primary sources: Qwen3 technical report (arXiv 2505.09388, May 2025), Qwen3.5 HuggingFace model card, Qwen3.5 blog post (qwen.ai/blog?id=qwen3.5), Qwen3.5 "Nobody Agrees on Attention Anymore" deep-dive blog (Maxime Labonne, Medium, Feb 2026).

**For Qwen3 family (Qwen3-8B and below):** the technical report describes a **four-stage post-training pipeline** for flagship models:

1. **Long-CoT Cold Start** — SFT on curated chain-of-thought traces (manual filtering, QwQ-32B candidate generation)
2. **Reasoning RL via GRPO** — on 3,995 query-verifier pairs for math and coding, with off-policy training at large batch size and high rollouts-per-query (the AIME'24 score on the 235B model increases from 70.1 to 85.1 over 170 RL training steps)
3. **Thinking Mode Fusion** — integration of reasoning and non-reasoning inference modes into a single model
4. **General-Domain RL** — additional RL across general tasks

**For Qwen3-8B specifically:** the report documents that for smaller models, the full four-stage pipeline is replaced by **strong-to-weak distillation** from larger teachers, both off-policy and on-policy. The quote: *"Preliminary experiments suggest that directly distilling the output logits from teacher models into lightweight student models can effectively enhance their performance... requires only 1/10 of the GPU hours compared to the four-stage training method."* Higher Pass@1 and Pass@64 scores vs direct training, per the paper.

**For Qwen3.5-9B specifically:** the Qwen3.5 release (2026-02-16 for flagship, 2026-03-02 for the 9B variant) extends the Qwen3 recipe with **reinforcement learning scaled across million-agent environments with progressively complex task distributions** (Qwen3.5 blog post). The small 9B model is likely (not confirmed in published text) also trained via distillation-from-larger-teacher, inheriting the teacher's RL-shaped behaviors. The 9B model card does not disclose the exact training recipe beyond these characterizations.

**Net characterization:** Qwen3.5-9B sits on the **RL-heavy end** of the post-training spectrum. Specifically:
- Its teacher (flagship Qwen3.5 or Qwen3 variants) is trained with GRPO + GSPO + million-agent-environment RL
- Distillation from an RL-heavy teacher inherits RL-shaped behaviors (the student learns to mimic the teacher's outputs, including any grounding-suppression patterns)
- There is no SFT-only or SFT+DPO stage of Qwen3.5 publicly available; the only distinction is base vs post-trained

By the taxonomy in §4 below, Qwen3.5-9B is effectively equivalent to a GRPO+GSPO-trained model at the 9B scale, with the distillation step compressing the behavior rather than diversifying it.

### 1.4 How Qwen3.5-9B is actually used in production

From direct read of `shared/config.py`, `agents/hapax_daimonion/model_router.py`, `agents/hapax_daimonion/conversation_pipeline.py`, and the 10+ agents that use `get_model_adaptive()`:

**Qwen3.5-9B is the `local-fast` route.** This route is used by:

| Consumer | Use | Criticality |
|---|---|---|
| `ModelTier.LOCAL` in voice pipeline (`agents/hapax_daimonion/model_router.py`) | Tier-1 voice responses: greetings, acknowledgments, short multi-turn | HIGH — latency-critical phatic responses |
| Voice-pipeline adaptive downgrade under stimmung-critical stance (`conversation_helpers.py`) | Emergency fallback for ALL tiers when stimmung is critical | **CRITICAL** — this is when the operator is most stressed, and the local LLM carries the full conversation |
| `agents/_config.py::get_model_adaptive` | Resource-pressure downgrade (resource > 0.7 → balanced/fast/reasoning all downgrade to local-fast) | HIGH — when the system is under load |
| `agents/briefing.py` | Daily briefing generation under resource pressure | MEDIUM — can be delayed |
| `agents/activity_analyzer.py` | Activity analysis under resource pressure | MEDIUM |
| `agents/profiler.py` | Profile fact extraction under resource pressure | MEDIUM |
| `agents/drift_detector/` | Drift detection under resource pressure | MEDIUM |
| `agents/scout.py` | Scout evaluation under resource pressure | MEDIUM |
| `shared/config.py::MODELS["coding"]` | Coding route — dev-time assistance | MEDIUM (Tier 2 work) |
| `shared/config.py::MODELS["reasoning"]` | Reasoning route — analysis tasks | MEDIUM |

**Important framing:** Qwen3.5-9B is **not the primary voice model**. The daimonion default is `gemini-flash` (FAST tier, cloud); Claude Sonnet and Opus serve STRONG and CAPABLE tiers. Qwen3.5-9B serves LOCAL tier — the lowest-latency, lowest-complexity conversational work — plus all pydantic-ai structured-output agents that are downgraded to local under resource pressure, plus dev-time coding/reasoning.

**This reframes the research question.** The operator's concern "is Qwen3.5-9B the best production substrate" is asking specifically about:
1. LOCAL tier voice (greetings, acknowledgments, simple multi-turn) — latency-critical
2. Stimmung-critical emergency fallback — reliability-critical
3. Coding / reasoning routes — quality-critical for dev assistance
4. Specialized agents under resource pressure — accuracy-critical for structured output

The **voice grounding research** (Cycle 2 SCED, claim `claim-shaikh-sft-vs-dpo`) tests `turn_pair_coherence` and other grounding DVs primarily against **gemini-flash and Claude Sonnet**, not against Qwen3.5-9B. The Shaikh framework applies to Qwen3.5-9B only indirectly — during stimmung-critical downgrades where Qwen3.5-9B IS carrying the full voice conversation, and for post-hoc analysis of local-tier phatic responses.

### 1.5 Known production concerns (pre-research)

Going into the research, these are the specific concerns operator has signaled or that the audit trail suggests:

1. **Thinking mode latency tax.** If Qwen3.5-9B's thinking mode is on by default (confirmed via HF model card), and not explicitly disabled in production config, every LOCAL tier call pays a few hundred tokens of `<think>...</think>` latency before the actual response. For a greeting like "hi", this can 10x the round-trip latency. Needs verification in production and, if true, immediate remediation regardless of the broader substrate decision.

2. **Post-training regime mismatch with Shaikh framework.** If the research program (Cycle 2) is testing SFT-vs-DPO effects on grounding, having the local substrate at the **extreme RL-heavy end** (GRPO+GSPO+million-agent-env RL via distillation) means the fallback path exhibits the WORST-case grounding behaviors precisely when the operator is most stressed (stimmung-critical downgrades). This is a research-validity AND governance concern: the model most likely to violate grounding is the one used when grounding matters most.

3. **Native multimodal weight overhead.** Qwen3.5-9B is a vision-language model. The vision tower adds parameters that are not used by hapax (multimodal perception goes to Gemini Flash). VRAM footprint at 5.0bpw is ~6 GB which is fine, but the unused vision tower represents inference capacity not being used; a pure-text 9B model would give more effective capability per GB.

4. **Chinese-origin concerns.** Not a concern hapax has explicitly raised, but relevant context: Qwen is developed by Alibaba. Some community discussions note Chinese-origin models have different default behavior on politically sensitive topics. Hapax does not touch geopolitically-sensitive material, so this is not an operational concern.

5. **Parrot sycophancy result (Çelebi et al. Nov 2025, arXiv 2511.17220):** small Qwen family models show the highest sycophancy follow-rates among tested models. Qwen 2.5-1.5B at 94% follow-rate. This is not 9B specifically, but the trend on Qwen small models is concerning for a system whose governance axiom explicitly values truth-over-agreement.

---

## 2. Use case profile — hapax's "very unique" production needs

Enumerating the use case profile explicitly, because the operator's phrase "very unique use cases" is load-bearing and the substrate must be evaluated against this specific profile, not against generic LLM leaderboards.

### 2.1 Voice-first latency budget

**Constraint:** consent-revocation round-trip must complete within ~2 seconds end-to-end (constitutional axiom `interpersonal_transparency`, drop #56 v3). This includes STT → conversation_pipeline → LLM → TTS → audio emission. The LLM contribution must be < 800 ms TTFT in the worst case.

For LOCAL tier (where Qwen3.5-9B lives), the acceptable TTFT is even tighter: phatic greetings should return in < 400 ms to feel natural. This is not a theoretical target; it's an empirically-observed threshold for voice AI not feeling slow.

**Implication for substrate selection:** TTFT on exllamav3 + RTX 3090 is the single most important performance axis. Tokens-per-second during sustained generation matters less (responses are short). Cold-start / first-call latency matters.

### 2.2 Continuous cognitive loop

**Constraint:** the daimonion cognitive loop runs continuously during conversation (per `feedback_cognitive_loop` memory: "cognition must run continuously, not cold-start on utterance boundary"). This means the director loop fires multiple LLM calls per second during active voice windows: perception updates, stimmung re-checks, activity selection, etc. Many of these are LOCAL tier calls.

**Implication:** prompt-prefix caching and KV cache reuse matter a LOT. A model that cold-starts slowly on every call is unusable in the loop. exllamav3 supports continuous batching; TabbyAPI's prompt-cache story is not entirely clear and needs verification.

### 2.3 Pydantic-ai structured output

**Constraint:** most hapax agents use pydantic-ai to force structured Pydantic-schema output from the LLM. This requires reliable JSON/schema adherence and tool-call-format compliance. Models that drift into prose under pressure or hallucinate schema fields break the agent pipeline.

**Implication:** IFEval (instruction-following eval) scores are a decent proxy. BFCL (Berkeley Function Calling Leaderboard) scores are more direct. Qwen3.5-9B scores IFEval 91.5 — high. But IFEval tests explicit formatted instructions, not conversational pressure. Need to check BFCL and JSON-mode reliability.

### 2.4 Stimmung-critical downgrade reliability

**Constraint:** under stimmung-critical stance, ALL tiers downgrade to LOCAL. This is the operator's highest-stress state. The local substrate becomes the ONLY LLM path for full conversational work. Failure modes here are operator-visible in the worst possible context.

**Implication:** the local substrate needs to be not just fast but **reliable under hand-off from higher tiers**. It should handle complex prompts gracefully, not just phatic ones. This argues against a model that's "fast but dumb" (e.g., small 3B models) and for a "fast AND competent" model at the 7-14B scale.

### 2.5 Hapax persona adherence

**Constraint:** hapax has a distinct persona delivered via system prompt (`agents/hapax_daimonion/persona.py`). The LLM must stay in-character across turns, not collapse into generic assistant mode, not refuse plausible requests, not over-disclaim.

**Implication:** models with aggressive safety/alignment tuning or strong generic-assistant defaults are worse here than models that remain malleable under persona override. Older "base + SFT" models (OLMo 2, Tulu 3) often persona-adhere better than heavily-aligned models (late Llama, late Claude). Qwen is moderate on this axis in community reports.

### 2.6 Tool use

**Constraint:** Several routes (coding agent, pydantic-ai agents, reasoning tasks) invoke tools via OAI-format tool-calls through LiteLLM → TabbyAPI → exllamav3. The substrate must support OAI tool-call format cleanly. Qwen3.5-9B supports `qwen3_coder` tool-call parser in vLLM; need to confirm exllamav3 parser support.

**Implication:** BFCL score is the cleanest proxy. Tulu 3 8B, Llama 3.1 8B, Mistral Nemo 12B, Command-R, and Qwen family all have explicit tool-use training; Gemma historically weaker; Phi models variable.

### 2.7 Coding and reasoning tiers

**Constraint:** `coding` and `reasoning` routes in `shared/config.py` both point at `local-fast` (i.e., Qwen3.5-9B) for cost reasons. For Tier 2 development work, these routes need to deliver usable coding completion and reasoning quality without upgrading to cloud.

**Implication:** HumanEval and GSM8K/MATH scores matter for these routes. Qwen3.5-9B scores are strong here per the model card. Alternative candidates must match or beat on these benchmarks.

### 2.8 VRAM budget on RTX 3090 + Option γ partition

**Constraint:** the LLM runs on cuda:1 (RTX 3090, 24 GB) under Option γ partition. daimonion STT + nomic embeddings + compositor + imagination GPU surface all run on cuda:0 (5060 Ti, 16 GB). The LLM does NOT share GPU 1 with heavy loads, so effectively ~18-22 GB is available for weights + KV cache + overhead.

**Implication:** at 4-5 bpw, models up to ~24B dense fit. But latency and quality tradeoffs at each size matter. A 14B at 5.0bpw (~9 GB weights + KV + overhead = ~12 GB) fits comfortably and may outperform a 9B at 6.0bpw (~7 GB weights) if instruction-following / reasoning matter more than TTFT.

### 2.9 Single operator, single workstation, no multi-user

**Constraint:** `single_user` axiom. Substrate is tuned for one operator. The model should ideally be persona-stable, not drift across sessions, handle operator-specific vocabulary, and not require "generic instruct" calibration.

**Implication:** this argues slightly for models with weaker "average user" optimization and stronger "follow instructions exactly" profile. It de-emphasizes models tuned for wide-audience chatbot deployment (e.g., aggressive safety tuning for public API serving).

### 2.10 Livestream research medium

**Constraint:** LRR epic — the LLM's outputs become public stream content via director_loop and voice_pipeline surfaces. Outputs are rendered on-stream. This heightens correctness, non-repetition, and stylistic quality requirements. The substrate shouldn't have obvious "AI-like" verbal tics that would be immediately recognizable on stream.

**Implication:** Qwen Rubric Anchors paper (Huang 2508.12790) explicitly notes binary-RLVR-trained models "mitigate the 'AI-like' tone and produce more human-like, expressive responses" via rubric-based training instead of binary verifiable rewards. This is a vote AGAINST pure binary-RLVR and FOR rubric-trained models, but it's a subtle signal.

### 2.11 Research validity under frozen substrate

**Constraint:** the substrate is part of the Cycle 2 pre-registration frozen set. Changing it requires a DEVIATION and opens a new condition (`cond-phase-a-*`). This means the substrate decision is not "pick the best once" — it's "pick something you can commit to for a data collection window of weeks or months."

**Implication:** optimize for stability, not cutting-edge. A mature model with known characteristics is preferable to a bleeding-edge release with unknown tail-behavior. This argues against Qwen3.5-9B (released 2026-03-02, ~6 weeks of community experience) and for models that have been in production use for longer (Llama 3.1 8B, Gemma 2 9B, Mistral Nemo 12B).

### 2.12 What hapax does NOT need

Explicitly listing de-scoped requirements:

- **Multimodal capability** — routed to Gemini Flash, not needed in local substrate
- **Long context (>16k)** — hapax uses 4-8k in practice
- **Multilingual beyond English** — operator is monolingual-English for work purposes
- **Public-API safety tuning** — single-operator, no multi-user exposure
- **Extreme reasoning (GPQA Diamond >80)** — that's the CAPABLE tier's job (Claude Opus)
- **Cloud-API compatibility** — runs locally only
- **Mass commercial scale** — single-operator workstation

---

## 3. Decision criteria and weights

Applying the profile from §2 to a weighted scoring framework. Weights reflect hapax-specific priorities, not generic LLM-benchmark importance.

| Criterion | Weight | Source in §2 | Measurement |
|---|---|---|---|
| **TTFT on exllamav3 + RTX 3090** | 20% | §2.1 voice latency, §2.2 continuous loop | Community / turboderp benchmarks, tokens to first output |
| **Instruction-following (IFEval)** | 15% | §2.3 pydantic-ai, §2.4 stimmung-critical | Published IFEval scores |
| **Tool-use accuracy (BFCL)** | 10% | §2.6 tool use | Berkeley Function Calling Leaderboard |
| **Post-training regime alignment with Shaikh framework** | 10% | §2.4 stimmung-critical + research validity | Published recipe (SFT-heavy > DPO > RLHF > GRPO) |
| **Reasoning quality (MMLU-Pro, GPQA Diamond)** | 10% | §2.7 reasoning route, §2.4 stimmung-critical | Published MMLU-Pro / GPQA numbers |
| **Coding quality (HumanEval / LiveCodeBench)** | 5% | §2.7 coding route | Published HumanEval numbers |
| **Persona adherence / low refusal rate** | 5% | §2.5 persona, §2.9 single-operator | Community reports, Parrot follow-rates |
| **VRAM fit at 5.0bpw with 8k context** | 5% | §2.8 VRAM budget | Computed from params + bpw + KV cache |
| **exllamav3 architecture compat + community EXL3 quant availability** | 5% | §2.8 VRAM + §2.11 research validity | Direct HF search for EXL3 quants |
| **Maturity (release age, community usage, known tail behavior)** | 5% | §2.11 research validity | Release date + HF download counts |
| **Non-"AI-like" tone / livestream-friendliness** | 5% | §2.10 livestream medium | Qualitative reports, rubric-trained vs binary-RLVR |
| **License (Apache 2.0 / MIT / permissive preferred)** | 5% | General | License field on HF |

**Hard filters (disqualifying if failed):**
1. License must allow personal commercial use (Apache 2.0, MIT, Llama Community License, Gemma, etc.)
2. EXL3 quant must exist OR model must be straightforward to self-quantize with exllamav3 0.0.22
3. Architecture must be supported by exllamav3 (no experimental state-space or hybrid architectures that exllamav3 doesn't parse)
4. Hermes family EXCLUDED per operator 2026-04-15 direction
5. Parameter count 7B-14B dense or equivalent effective (≤16B total for MoE, ≤6B active)
6. Must have instruction-tuned variant (not base-only)

---

## 4. Post-training regime landscape and Shaikh framework update

*This section synthesizes research findings on the theoretical and empirical state of post-training regimes as of April 2026, specifically oriented toward the hapax research program's Shaikh framework dependency. Source: delegated research sub-task, completed 2026-04-15.*

### 4.1 Framework pillars (now established literature)

Three pillars now constitute the published "grounding suppression" canon:

1. **Shaikh et al., "Grounding Gaps in Language Model Generations," EMNLP 2023** (arXiv 2311.09144). Taxonomy of grounding acts (clarification, acknowledgment, repair, presentation, acceptance). Claims training on preference data **erodes** grounding acts.

2. **Mohapatra, Hassan, Romary, Cassell, LREC-COLING 2024** (aclanthology.org/2024.lrec-main.352). Annotation framework for grounding acts / grounding units. **Cleanest published direct SFT-vs-DPO finding:** "SFT has no evidence of impacting grounding agreement across grounding acts, while increased DPO training degrades agreement across grounding acts." This is the empirical core that justifies the hapax research program.

3. **Shaikh, Mozannar, Bansal, Fourney, Horvitz, "Navigating Rifts in Human-LLM Grounding," ACL 2025** (arXiv 2503.13975). The RIFTS benchmark — 1,740 prompts, 23.23% average accuracy on off-the-shelf instruction-following models (worse than 33% random). **96.09% success when no grounding is needed, 2.22% success when grounding is required.** This asymmetry is the sharpest empirical signal in the grounding literature.

### 4.2 New 2025–2026 evidence

**Corroborating the suppression prediction:**

- **Laban et al., "LLMs Get Lost In Multi-Turn Conversation," May 2025** (arXiv 2505.06120). 200K+ simulated conversations across top open/closed-weight LLMs. **All** tested models show a **39% average performance drop** from single-turn to multi-turn. Key mechanism: *"LLMs often make assumptions in early turns and prematurely attempt to generate final solutions... when LLMs take a wrong turn in a conversation, they get lost and do not recover."* Direct empirical confirmation of the Shaikh prediction in a general-generation setting.
- **QuestBench** (Li et al., March 2025, arXiv 2503.22674). Formalizes clarification as constraint satisfaction with a missing variable. Frontier models score **40–50%** on Logic-Q and Planning-Q. *"LLMs tend not to hedge, even when explicitly presented with the option to predict 'not sure.'"* Cleanest quantitative measurement of the anti-hedging pattern.
- **SYCON Bench** (Hong et al., May 2025, arXiv 2505.23840). 17-model evaluation. Direct finding: *"alignment tuning amplifies sycophantic behavior, whereas model scaling and reasoning optimization strengthen the model's ability to resist undesirable user views."* Independent empirical corroboration of post-training-regime-affects-epistemic-behavior.
- **Parrot** (Çelebi et al., Nov 2025, arXiv 2511.17220). 22-model sycophancy benchmark, 8-state taxonomy. **Per-model results:** GPT-5 at 4% follow rate, Claude Sonnet 4.5 at ≤11%, older/smaller models at 50–94% (Qwen 2.5-1.5B: 94%). **Qwen family models specifically skew toward high follow rates among small models** in this evaluation.

**Counter-signals (weakening the suppression frame):**

- **Yu et al., "The Pragmatic Mind of Machines," May 2025** (arXiv 2505.18497). Evaluates 22 LLMs on pragmatic competence across pre-training, SFT, and preference optimization stages. Reports that *"SFT and RLHF contribute further gains, particularly in cognitive-pragmatic reasoning."* This is a direct counter-signal to the Shaikh suppression prediction — at least for implicature and contrastive reasoning, both SFT and RLHF help, not harm. Grounding acts (Shaikh) and pragmatic competence (Yu) may be orthogonal.

**Intervention-level evidence:**

- **ERGO** (Khalid et al., Oct 2025, arXiv 2510.14077). Entropy-guided resetting for multi-turn generation. +56.6% perf gain, +24.7% aptitude, -35.3% unreliability. Notable because the fix is **inference-time**, not post-training-level — which suggests multi-turn degradation is partially reversible without retraining.
- **Rubric Anchors** (Huang et al., Aug 2025, arXiv 2508.12790). Rubric-based RL (vs binary verifiable rewards) "mitigates the 'AI-like' tone and produces more human-like, expressive responses." Vote against pure binary-RLVR for livestream-visible output.

### 4.3 Post-training regime taxonomy (April 2026)

Current regime taxonomy, ordered roughly from SFT-heavy to RL-heavy. Grounding-preservation priors are theoretical where not directly measured:

| Regime | Mechanism | Grounding-preservation prior |
|---|---|---|
| **SFT** | Token-level cross-entropy on demonstrations | Best — Mohapatra finds no grounding degradation |
| **SFT mixes (Tulu-3-SFT-Mix, SmolTalk, TuluTalk)** | Weighted SFT on curated corpora | Same as SFT |
| **KTO** (Kahneman-Tversky) | Per-response binary like/dislike, no pairs | Theoretically gentler than DPO |
| **IPO** (Identity Preference Optimization) | Regularized preference | Theoretically less suppressive than DPO |
| **ORPO** | Joint SFT + preference in one loss | Less studied |
| **DPO** | Bradley-Terry on preference pairs | **Empirically degrades grounding agreement** (Mohapatra 2024) |
| **SimPO / CPO** | DPO variants | Untested on grounding |
| **RLVR** (Verifiable Rewards) | Binary correctness on verifiable outputs | **Not directly tested on grounding.** Tu et al. 2509.21882 flags "hidden costs" including grounding/calibration measurement gaps |
| **GRPO** | Group Relative Policy Optimization (DeepSeek-Math, Qwen3, Tulu 3) | RL-heavy, output-only credit assignment |
| **DAPO** | GRPO variant with decoupled clipping | RL-heavy |
| **GSPO** | Qwen3 team's fix for GRPO instability on MoE | RL-heavy |
| **PPO-based RLHF** | Actor-critic with reward model | Classical RL-heavy; associated with sycophancy |

**Qwen3.5 post-training regime placement:** GRPO + GSPO + "reinforcement learning scaled across million-agent environments with progressively complex task distributions" (Qwen3.5 blog post). Small Qwen3 models use strong-to-weak distillation from RL-heavy teachers. Qwen3.5-9B is effectively **at the most RL-heavy end** of the taxonomy with no SFT-only fallback variant publicly available.

### 4.4 Critical gaps in the literature (as of April 2026)

1. **No published RLVR-vs-DPO-vs-SFT ablation on grounding acts.** The single most valuable experiment for the hapax program has not been run.
2. **No 7–14B open-model grounding leaderboard.** RIFTS evaluates frontier models; no paper systematically ranks 8–14B models across post-training regimes.
3. **Qwen3 / Qwen3.5 family has NOT been evaluated on any grounding benchmark** (RIFTS, QuestBench, SYCON Bench, MultiChallenge) in published work as of April 2026. Any substrate argument against Qwen3.5-9B on grounding grounds is **predictive from recipe, not empirical**.
4. **Mohapatra et al.'s SFT-vs-DPO grounding-agreement finding has NOT been independently replicated.** It is a single-paper result.
5. **No measurement of grounding under voice-pipeline latency constraints.** The interaction between post-training regime and continuous cognitive loop / multiple-calls-per-second usage is entirely unstudied.

### 4.5 What this means for the hapax substrate decision

- The theoretical framing that RL-heavy post-training reduces grounding is **well-supported in general form**. The specific ordering of post-training regimes by grounding-preservation quality is **not empirically established** as of April 2026.
- Qwen3.5-9B is predictively on the wrong side of the framework, but **no direct evidence** shows its grounding behavior is materially worse than alternatives at the 7-14B scale.
- **Parrot's small-Qwen sycophancy result is the closest direct warning signal** against the Qwen family at small scales.
- The Shaikh framework is **stronger evidence for avoiding heavy DPO and binary-RLVR** than for any specific ordering among RL-heavy variants.
- Any substrate swap motivated by the Shaikh framework needs to be accompanied by an **empirical grounding evaluation protocol** that the hapax research program runs directly — the literature alone does not provide the data hapax needs.

---

## 5. Candidate landscape enumeration

*Synthesized from candidate-enumeration research sub-task, 2026-04-15. Broad cast across 2024–2026 open-weight 7–14B LLMs, filtered to non-Hermes per operator direction.*

### 5.1 Post-training regime buckets

Models group into four buckets on the post-training spectrum, ordered from SFT-heavy to RL-heavy. This is the axis that most directly informs the Shaikh framework question.

**Bucket A — SFT-heavy / SFT-only (no RL stage):**
- **DeepSeek-R1-Distill-Qwen-7B / -14B** (2025-01). SFT-only on 800k R1-generated reasoning traces. MIT. 32K/128K ctx. GPQA Diamond 59.1 (14B). Characteristic stylistic tics: verbose, hedging, emits `<think>` tokens. **No EXL3 quant** — self-quantization required.
- **01.AI Yi 1.5 9B Chat** (2024-05). SFT on <10k polished instructions, no RL. Apache 2.0. Stale by 2026. **No EXL3 quant**.
- **DeepSeek-V2-Lite-Chat** (2024-05, 16B/2.4B MoE). Long-context extension + SFT only. MLA architecture. MMLU 58.3 — weak. Reference only.

**Bucket B — SFT + DPO (no RL stage):**
- **Microsoft Phi-4 14B** (2024-12). Synthetic-heavy SFT (~40% synthetic) + iterative DPO with Pivotal Token Search. MIT. 16K ctx. **IFEval 63.0 — notable weakness**, GPQA 56.1, HumanEval 82, MATH 80. EXL3 via `owentruong/phi-4-EXL3` (community, unverified calibration).
- **IBM Granite 3.1/3.2/3.3 8B Instruct** (2024-12 through 2025-04). SFT + DPO. Apache 2.0. 128K ctx. Enterprise RAG focus. **No EXL3 quant**.
- **Mistral Nemo 12B Instruct 2407** (2024-07). SFT + offline DPO. Apache 2.0. 128K ctx. Mature persona adherence, low refusal. EXL3 via `isogen` (community, unverified calibration, low download count).
- **Mistral Small 3 / 3.1 / 3.2 24B Instruct** (2025-01/03/06). Mistral explicitly documents **"no synthetic data or reinforcement learning"** — pure SFT + preference tuning. Apache 2.0. 32K/128K ctx. 150 tok/s on single GPU. HumanEval 84.8, MMLU ~81. EXL3 via `turboderp/Mistral-Small-3.1-24B-Instruct-2503-exl3` (full branch set — trusted).
- **Ministral-3-8B-Instruct-2512** (2025-12). SFT + Online DPO. Apache 2.0. 128K ctx. EXL3 via `UnstableLlama/Ministral-3-8B-Instruct-2512-exl3`.
- **Ministral-8B-Instruct-2410** (2024-10). SFT + Online DPO. **Mistral Research License** (non-commercial — disqualifying).
- **Google Gemma 2 9B IT** (2024-06). SFT + RLHF, heavy distillation from larger teacher. Gemma license. **8K context — hard constraint against hapax usage patterns.**
- **Zamba2-7B-Instruct** (2024-10). Mamba2+transformer hybrid. SFT + DPO. Apache 2.0. **4K ctx and Mamba-hybrid unsupported by exllamav3 — disqualifying.**

**Bucket C — SFT + DPO + RL (moderate RL / RLHF):**
- **Meta Llama 3.1 8B Instruct** (2024-07). SFT + Rejection Sampling + DPO + RLHF, each round iterated, ~25M synthetic IF examples. Llama 3.1 Community license. 128K ctx. **IFEval 80.4, BFCL 76.1** — best-in-class IFEval among dense 8Bs pre-Qwen3. EXL3 via `turboderp/Llama-3.1-8B-Instruct-exl3` — **canonical reference**.
- **Qwen3-8B and Qwen3-14B** (2025-04-29). Four-stage pipeline: long CoT cold start → reasoning RL (GRPO) → thinking-mode fusion → general-domain RL. Apache 2.0. 32K native / 128K YaRN. Less scaled-RL than Qwen3.5 (no million-agent-env extension). EXL3: Qwen3-8B via `turboderp/Qwen3-8B-exl3` (full branch set trusted), Qwen3-14B via `isogen`/`async0x42` community quants.
- **Google Gemma 3 12B IT** (2025-03-12). SFT + RL + distilled-preference optimization. Gemma license. 128K ctx, multimodal (vision). MATH 83.8. Community EXL3 via `isogen`.
- **GLM-4-9B-Chat-0414** (2025-04 refresh). SFT + RLHF + DPO. MIT. 32K/128K/1M ctx variants. Strong tool calling. Architecturally distinct from Qwen/Llama (different tokenizer). EXL3 via `owentruong`/`LatentWanderer`/`adriabama06`.
- **Cohere Command R7B 12-2024** (2024-12). SFT + iterative preference tuning + RLHF. **CC-BY-NC 4.0** — non-commercial, disqualifying for default use.
- **InternLM 3 8B Instruct** (2025-01). SFT + Online RLHF. Apache 2.0. **No EXL3 quant**.
- **Falcon 3 10B Instruct** (2024-12). SFT + light preference optimization. Falcon license. **BFCL 86.3** (best-in-class for this bucket), IFEval 78, GSM8K 83.1. **No EXL3 quant**.

**Bucket D — RL-heavy / scaled-RL / RLVR-dominant:**
- **AI2 OLMo 3-7B Instruct** (2025-11-22). Three-stage: SFT → DPO → scaled RLVR. Also has "thinking" and "instruct" pathways. Apache 2.0. 65K ctx. Competitive with Qwen3-8B on MATH/AIME; leads on HumanEval+. **UNIQUELY: AI2 also publishes separate hybrid SFT-only and DPO-only checkpoints** — `turboderp/Olmo-Hybrid-Instruct-SFT-7B-exl3` and `UnstableLlama/Olmo-Hybrid-Instruct-DPO-7B-exl3` — allowing isogenic A/B comparison within one model family. Plus `kaitchup/Olmo-3-7B-Instruct-exl3` for the full RLVR'd variant.
- **AI2 Tulu 3 8B** (2024-11). SFT → DPO (on/off-policy) → RLVR. Llama 3.1 8B base. Llama 3.1 Community license. **No EXL3 quant** — self-quant path.
- **AI2 OLMo 2 7B / 13B Instruct** (2024-11). Same SFT → DPO → RLVR recipe. Apache 2.0. **4K context** — hard constraint. **No EXL3 quant for 13B**.
- **NVIDIA Nemotron Nano 2 (9B-v2)** (2025-08) / **Nano 3** (2025-12). Hybrid Mamba-Transformer. Heaviest RL stack: multi-SFT → GRPO → DPO → RLHF on ~90B tokens. NVIDIA Open License. **Mamba-hybrid compat with exllamav3 unverified — high deployment risk**. No EXL3 quant for 9B Nano.
- **Reka Flash 3 / 3.1** (2025-03). 21B dense. SFT + RLOO with model-based and rule-based rewards. Apache 2.0 (3.1). MMLU-Pro 65. **No EXL3 quant**.
- **AceReason-Nemotron-14B** (2025-05). Pure RL on DeepSeek-R1-Distill-Qwen-14B base. Math + code only. NVIDIA Open License. EXL3 via `lucyknada`. Specialized — weak for general chat.
- **Apriel-Nemotron-15B-Thinker** (2025-05). Mistral-like 15B with reasoning SFT + RL. MIT. EXL3 via `MetaphoricalCode` (8bpw only).
- **Phi-4-reasoning-plus** (2025-05). Phi-4 14B + SFT on curated CoT traces + RL (~6k prompts). MIT. EXL3 via `isogen`.
- **Current: Qwen3.5-9B** (2026-03-02). GRPO + GSPO + "million-agent-environment" scaled RL, via distillation from RL-heavy teacher. **IFEval 91.5, MMLU-Pro 82.5, GPQA Diamond 81.7** — highest benchmark scores in class. Apache 2.0. 262K native ctx. EXL3 via `turboderp/Qwen3.5-9B-exl3` (full branch set trusted).

### 5.2 Notable omissions and why

- **Llama 3.3 8B**: Model does not exist. Llama 3.3 is 70B-only.
- **Llama 3.2 3B Instruct**: Below 7B floor; no turboderp EXL3.
- **Llama 4 Scout/Maverick**: 17B×16 MoE (109B total) exceeds ≤16B MoE total cap.
- **Phi-3.5 Mini / Phi-4-mini**: Below 7B floor.
- **Qwen3-Next / Qwen3.5-35B-A3B MoE**: Exceeds 16B total cap.
- **Command-R 32B / Command-R+ 104B**: Exceeds 14B dense ceiling.
- **Grok 2/3**: Non-commercial or closed.
- **Mistral 7B v0.3**: Dated; strictly worse than Qwen3-8B or Llama 3.1 8B at similar size.
- **StableLM 2 12B, Aquila 2, Apertus-8B**: Stale or not recently refreshed.

---

## 6. Deployment feasibility per candidate

*Synthesized from deployment-feasibility research sub-task, 2026-04-15. All VRAM math assumes Q4 KV cache, +1 GB runtime/CUDA overhead, RTX 3090 effective 18 GB budget.*

### 6.1 Stack state

**exllamav3 upstream version:** 0.0.29 (released 2026-04-12). **Production stack version: 0.0.22** — a ~4-5 month lag behind upstream. Worth noting: the Qwen3.5 hybrid-attention JIT compile path was flagged as "shaky on first call" in the upstream README. 0.0.22 predates some Ampere-specific fixes shipped in 0.0.23–0.0.29.

**Architectures supported by exllamav3:** Llama 2/3/3.1/3.2/3.3, Qwen2/2.5/3/3.5 (all variants including Qwen3-VL, Qwen3-VL-MoE, Qwen3-Next, Qwen3.5-MoE), Gemma 2/3/4 (multimodal), Mistral/Mistral3/Mixtral/Ministral 3/Devstral 2, Phi3/Phi4, Command-R/Command-R-Plus, GLM-4/GLM-4.5/GLM-4.6 (including MoE), DeciLM, Nemotron, EXAONE 4.0, Olmo 3.1, Olmo-Hybrid.

**Architectures NOT supported** (or not listed): Zamba/Zamba2, Jamba, raw Mamba/Mamba-2, IBM Granite 3.x, InternLM3, Yi 1.5, Tulu 3 (though Llama-base may work as Llama), OLMo 2 (non-Olmo-Hybrid), DeepSeek-V2-Lite (MLA architecture), Phi-3.5-MoE, Nemotron-Mini-4B / Nano-8B, Aya Expanse.

**Known limitations:**
- Qwen3-Next and Qwen3.5 do NOT support tensor/expert parallelism (single-GPU only, which matches this stack)
- Gemma 4 does NOT support TP/EP
- Linear attention JIT compile path is "shaky" on Qwen3-Next / Qwen3.5
- LoRA and ROCm support incomplete

**TabbyAPI prompt-prefix caching:** Automatic and transparent via exllamav3's PageTable / Generator pipeline. There is no explicit `prefix_caching` toggle; cache reuse is opportunistic and bounded by `cache_size` (currently 4096 in production config). Recommendation: raise `cache_size` to 16384–24576 tokens to ensure persona + system prompt prefix survives turn-over-turn eviction. KV at Q4 costs ~40 MB/1k context for a 14B; 24k cache = ~960 MB.

### 6.2 Per-candidate VRAM + quant + risk matrix

| Candidate | 5.0 bpw @ 8k ctx | EXL3 quant | Uploader trust | Deployment risk | Notes |
|---|---|---|---|---|---|
| Qwen3.5-9B (current) | ~6.80 GB | `turboderp/Qwen3.5-9B-exl3` | HIGH | **MEDIUM** | Hybrid attention JIT is "shaky" on first call; TTFT risk |
| Qwen3-8B | ~6.40 GB | `turboderp/Qwen3-8B-exl3` (missing 5.0, has 4.0/6.0) | HIGH | **LOW** | Standard attention, minimal JIT surprises |
| Qwen3-14B | ~10.55 GB | `isogen`, `async0x42`, `TheMelonGod`, `gtkunit` | MEDIUM (community) | **MEDIUM** | No turboderp calibration; smoke-test before commit |
| Qwen2.5-7B-Instruct | ~5.85 GB | `turboderp/Qwen2.5-7B-Instruct-exl3` | HIGH | **LOW** | Smallest KV footprint, mature architecture |
| Qwen2.5-14B-Instruct | ~10.65 GB | `turboderp/Qwen2.5-14B-Instruct-exl3` | HIGH | **LOW** | Full turboderp branches including 5.0, mature |
| Llama 3.1 8B Instruct | ~6.15 GB | `turboderp/Llama-3.1-8B-Instruct-exl3` | HIGH | **LOW** | Canonical reference; broadest community validation |
| Gemma 2 9B IT | ~7.25 GB | `turboderp/gemma-2-9b-it-exl3` | HIGH | **LOW-MEDIUM** | Larger KV/1k due to head_dim=256; 8K ctx hard limit |
| Gemma 3 12B IT | ~8.80 GB est. | `isogen/gemma-3-12b-it-exl3` | MEDIUM (community) | **MEDIUM** | SWA+global attention, multimodal overhead |
| Mistral Nemo 12B 2407 | ~8.80 GB | `isogen/Mistral-Nemo-Instruct-2407-exl3` | LOW (community, low dl) | **MEDIUM-HIGH** | Calibration unverified; pragmatic self-requant recommended |
| Mistral Small 3.1 24B | ~16.05 GB @ 5.0bpw | `turboderp/Mistral-Small-3.1-24B-Instruct-2503-exl3` | HIGH | **MEDIUM** | Fits at 5.0 bpw but NOT at 6.0 bpw @ 8k ctx. 24B class — constrains bpw ceiling |
| Phi-4 14B (base) | ~10.60 GB | `owentruong/phi-4-EXL3` only (community, untrusted) | LOW | **HIGH** | No turboderp calibration; deployment requires local quant or risk |
| Phi-4-reasoning-plus | ~10.60 GB | `isogen/Phi-4-reasoning-plus-exl3` (4/6 bpw) | MEDIUM | **MEDIUM** | Reasoning-biased; longer CoT output stresses TTFT |
| GLM-4-9B-Chat-0414 | ~6.80 GB est. | `owentruong`, `LatentWanderer`, `adriabama06` | MEDIUM (multiple community) | **MEDIUM** | Multiple uploaders provide some cross-check; architecturally distinct |
| Ministral-3-8B-Instruct-2512 | ~6.15 GB est. | `UnstableLlama/Ministral-3-8B-Instruct-2512-exl3` | MEDIUM (community) | **MEDIUM** | Apache 2.0 version of the 2410 ODPO recipe |
| **OLMo 3-7B Instruct** | ~5.85 GB est. | `kaitchup/Olmo-3-7B-Instruct-exl3` | MEDIUM (community) | **LOW-MEDIUM** | **Plus SFT-only and DPO-only split checkpoints** via turboderp + UnstableLlama |
| DeepSeek-R1-Distill-Qwen-7B | — | **No EXL3** | N/A | **HIGH** | Self-quantization required |
| DeepSeek-R1-Distill-Qwen-14B | — | **No EXL3** | N/A | **HIGH** | Self-quantization required |
| AI2 Tulu 3 8B | — | **No EXL3** | N/A | **HIGH** | Self-quantization required (Llama-base so likely works) |
| IBM Granite 3.x 8B | — | **No EXL3** | N/A | **HIGH** | Custom architecture may not be registered in exllamav3 |
| Yi 1.5 9B Chat | — | **No EXL3** | N/A | **HIGH** | No quant, no evidence of community interest |
| Falcon 3 10B Instruct | — | **No EXL3** | N/A | **HIGH** | Best-in-class BFCL 86.3 wasted if undeployable |
| Cohere Command R7B | — | `turboderp/c4ai-command-r7b-12-2024-exl3` | HIGH (technical) | **HIGH (license)** | **CC-BY-NC 4.0** — non-commercial only |

### 6.3 TTFT / latency implications

**Models with fast, stable TTFT on RTX 3090 + exllamav3 (baseline Llama-like):**
- Llama 3.1 8B Instruct (reference)
- Qwen2.5-7B / 14B Instruct
- Qwen3-8B / 14B
- Phi-4 14B (standard `Phi3ForCausalLM`)

**Models with TTFT risk:**
- **Qwen3.5-9B (current)** — Linear+full DeltaNet hybrid; Flash Linear Attention JIT compile is "shaky" on first call per exllamav3 README. First-call penalty can be seconds; steady-state is comparable to baseline. Partially mitigable via startup cache warmup (send one no-op completion on service start).
- **Gemma 2 9B IT** — 256 head_dim + SWA+global attention per layer produces historically 10-20% slower decode on exllamav2/3.
- **Gemma 3 12B** — same Gemma attention penalty plus vision tower overhead even in text-only mode.
- **Phi-4-reasoning-plus** — reasoning-biased generation produces longer CoT output, stressing TTFT by increasing time-to-useful-output.

**Prompt-prefix caching benefits most:**
- Any model with stable attention (Llama, Qwen2.5, Qwen3 non-3.5)
- Benefits are model-independent architecturally; `cache_size` sizing matters more than model choice

---

## 7. Use-case-specific synthesis

Cross-referencing the §2 use-case profile (12 dimensions) against the §5 candidate landscape and §6 deployment feasibility, here is the scored synthesis.

### 7.1 Scoring against hapax-specific criteria

Normalized scores 1-5 per criterion from §3 weights. "★★★★★" = best in class, "—" = disqualifying / unknown / irrelevant. Only models that pass hard filters (license, EXL3 availability, VRAM fit, non-Hermes) are scored.

| Criterion | Weight | Qwen3.5-9B (current) | Llama 3.1 8B Instruct | Qwen3-8B | OLMo 3-7B Instruct | Mistral Small 3.1 24B | Qwen3-14B |
|---|---|---|---|---|---|---|---|
| TTFT stability (exllamav3 + RTX 3090) | 20% | ★★★ (JIT risk) | ★★★★★ | ★★★★★ | ★★★★ | ★★★ (larger bpw constrained) | ★★★★ |
| IFEval (instruction following) | 15% | ★★★★★ (91.5) | ★★★★ (80.4) | ★★★★ (est. ~85) | ★★★ (unpublished) | ★★★★ (est. ~82) | ★★★★ (est. ~88) |
| BFCL (tool use) | 10% | ★★★★ (unpublished) | ★★★★ (76.1) | ★★★★ (est.) | ★★★★ (strong per AI2) | ★★★★ (est.) | ★★★★ (est.) |
| Post-training regime Shaikh alignment | 10% | ★ (scaled-RL, worst) | ★★★ (SFT+DPO+RLHF moderate) | ★★ (4-stage RL, less scaled than 3.5) | ★★★★ (has SFT-only variant!) | ★★★★★ (explicit "no RL") | ★★ (same as Qwen3-8B) |
| Reasoning (MMLU-Pro / GPQA Diamond) | 10% | ★★★★★ (82.5 / 81.7) | ★★★ | ★★★★ | ★★★★ | ★★★★ | ★★★★★ |
| Coding (HumanEval / LiveCodeBench) | 5% | ★★★★ | ★★★ | ★★★★ | ★★★★ | ★★★★ | ★★★★ |
| Persona adherence / low refusal | 5% | ★★★ (Parrot warning on small Qwen) | ★★★★ (mature, neutral) | ★★★ | ★★★★ (open-recipe, less alignment-tuned) | ★★★★★ (known strong) | ★★★ |
| VRAM fit @ 5.0bpw / 8k ctx | 5% | ★★★★★ (6.80 GB) | ★★★★★ (6.15) | ★★★★★ (6.40) | ★★★★★ (5.85 est.) | ★★★★ (16.05 — at edge) | ★★★★ (10.55) |
| EXL3 quant availability + trust | 5% | ★★★★★ (turboderp) | ★★★★★ (turboderp) | ★★★★★ (turboderp) | ★★★★ (kaitchup + turboderp split) | ★★★★★ (turboderp) | ★★★ (community only) |
| Maturity (months since release, community eyes) | 5% | ★★ (6 weeks) | ★★★★★ (21 months) | ★★★★ (12 months) | ★★★ (5 months) | ★★★★ (13 months) | ★★★★ (12 months) |
| Non-"AI-like" tone (livestream-friendly) | 5% | ★★★ | ★★★★ | ★★★ | ★★★★ | ★★★★ | ★★★ |
| License | 5% | ★★★★★ (Apache 2.0) | ★★★★ (Llama Community) | ★★★★★ (Apache) | ★★★★★ (Apache) | ★★★★★ (Apache) | ★★★★★ (Apache) |
| **Weighted total** | 100% | **~3.85** | **~4.10** | **~3.85** | **~3.85** | **~4.05** | **~3.75** |

### 7.2 Qualitative observations beyond the scoring table

- **Qwen3.5-9B wins decisively on benchmark quality** (IFEval 91.5 is exceptional) but loses on TTFT stability, Shaikh framework alignment, and maturity. Its weighted score is competitive despite those three penalties, entirely because of IFEval + reasoning dominance.

- **Llama 3.1 8B Instruct is the "safest" candidate** — highest maturity, canonical EXL3 quant, moderate Shaikh position, broad community validation. It trades benchmark peaks for deployment maturity.

- **Qwen3-8B is the "minimum migration friction" candidate** — same family as current, slightly less RL (no million-agent-env extension), trusted turboderp quant, lower TTFT risk (standard attention vs hybrid). It's a 1-parameter change from Qwen3.5-9B with essentially no code impact.

- **OLMo 3-7B Instruct is the "research-aligned" candidate** — uniquely exposes SFT-only and DPO-only checkpoints as ready EXL3 quants (`turboderp/Olmo-Hybrid-Instruct-SFT-7B-exl3` + `UnstableLlama/Olmo-Hybrid-Instruct-DPO-7B-exl3`). **This is the only candidate where hapax could run the Shaikh SFT-vs-DPO test within the substrate decision itself** rather than treating it as a theoretical prior. No published IFEval / BFCL numbers yet, so its actual production quality is uncertain — but the research program value is unique.

- **Mistral Small 3.1 24B is the "no-RL anywhere" candidate** — Mistral explicitly documents "no synthetic data or reinforcement learning" for Small 3. Apache 2.0, trusted turboderp quant, 24B class VRAM-fits at 5.0 bpw but not 6.0. It's the cleanest test of the pure SFT+preference regime on a mature platform. **But 24B on a single 3090 at 5.0 bpw is the edge of the VRAM envelope** — 6.0 bpw doesn't fit with 8k context, which limits optimization headroom.

- **Qwen3-14B offers more headroom than Qwen3-8B** with the same post-training recipe, but community-only quants.

### 7.3 A forced-ranking on the composite score

**Rank 1: Llama 3.1 8B Instruct** — ~4.10. Safest deployment, mature, reference quant, moderate Shaikh position.
**Rank 2: Mistral Small 3.1 24B Instruct** — ~4.05. "No RL" recipe, Apache, strong benchmarks, constrained only by VRAM ceiling at 6.0 bpw.
**Rank 3 (tied): Qwen3.5-9B (current) / Qwen3-8B / OLMo 3-7B Instruct** — ~3.85 each. Different winners on different criteria.
**Rank 6: Qwen3-14B** — ~3.75. Weighted down by community-quant risk.

### 7.4 Observations on the scoring

- The composite score is tight (3.75 to 4.10 — a 10% spread). No candidate is decisively better than the others on a dispassionate weighting. The winner depends on which criteria the operator values most.
- **If the operator values benchmark quality and research alignment is lower priority:** Qwen3.5-9B stays.
- **If the operator values deployment maturity and Shaikh alignment moderately:** Llama 3.1 8B Instruct.
- **If the operator values "no RL" regime most strongly:** Mistral Small 3.1 24B (constrained by VRAM at top end).
- **If the operator wants the research program to directly test Shaikh within the substrate:** OLMo 3-7B Instruct with split checkpoints.

---

## 8. Shortlist deep-dive: 5 finalists

### 8.1 Qwen3.5-9B (current — status quo)

**The case for:** Apex benchmarks at its scale — IFEval 91.5, MMLU-Pro 82.5, GPQA Diamond 81.7. Trusted turboderp EXL3 quant. Apache 2.0. Already deployed and tested in production for ~6 weeks. Gated Delta Networks architecture delivers ~low-latency inference once JIT warmed up. Native 262K context (unused but available). Thinking/non-thinking modes toggle at chat-template level.

**The case against:**
- **Thinking mode is enabled by default at chat-template level** and there is no evidence in the production TabbyAPI config (`tabbyAPI/config.yml`) or LiteLLM config that it is explicitly disabled. Every LOCAL-tier voice call may be paying a ~100-500 token thinking latency tax before the useful response. This is almost certainly a silent production issue.
- **Hybrid attention JIT compile is "shaky" on first call** per exllamav3 README. First-call TTFT can be seconds; steady-state is baseline. Mitigable via startup warmup but the operator hasn't confirmed that warmup is in place.
- **Stack version gap:** production runs exllamav3 0.0.22; upstream is 0.0.29. Several Ampere-specific fixes have shipped in the 5-month interval. Upgrading to 0.0.29 is independent of substrate choice.
- **Post-training regime is the RL-heavy extreme** (GRPO + GSPO + million-agent-environment RL via distillation). By the Shaikh framework's theoretical prediction, this is the worst-case grounding regime. **But this has NOT been empirically validated on Qwen3.5-9B** per §4 gap 4.4.3.
- **Parrot sycophancy result** (Çelebi 2025) — Qwen 2.5-1.5B at 94% follow-rate; the Qwen family trend at small sizes is concerning. 9B is not 1.5B, but the family pattern is a warning signal.
- **Maturity is only ~6 weeks** of community exposure. Less-characterized tail behavior than older alternatives.

**Recommendation if kept:** ship two fixes immediately, independent of the broader substrate decision: (1) disable thinking mode for LOCAL tier in LiteLLM config via `chat_template_kwargs.enable_thinking=False`; (2) add startup cache warmup via a no-op completion on `tabbyapi.service` `ExecStartPost`. Then run RIFTS benchmark (§10.3) to validate grounding empirically.

### 8.2 Llama 3.1 8B Instruct

**The case for:** Deployment maturity unbeatable at this scale. Canonical turboderp EXL3 quant with full branch set. Most-benchmarked 8B model in the ecosystem. IFEval 80.4 (strong, though below Qwen3.5-9B's 91.5). BFCL 76.1 — best-in-class 2024 open-model tool use. Llama architecture has broadest community validation; persona adherence is mature and neutral. 128K context. Post-training regime is **SFT + RS + DPO + RLHF** — RL is present but not scaled; classical Meta RLHF, much gentler than GRPO/GSPO/million-agent RL.

**The case against:**
- **IFEval 80.4 is 11 points below Qwen3.5-9B's 91.5** — for pydantic-ai structured output, this gap matters. Roughly translates to "respects formatting directives slightly less faithfully."
- **Post-training regime is still moderate RL-heavy** — not on the Shaikh SFT-pure end. Mohapatra et al.'s DPO finding applies directly.
- **Release is 21 months old** — most recent 2025-2026 models outperform it on updated benchmarks.
- **Llama 3.1 Community license** is more restrictive than Apache 2.0, though fine for single-operator personal use.
- **Not a research-program testbed** for the Shaikh framework — it's moderate on the spectrum, neither the SFT-pure nor scaled-RL end.

**Recommendation if chosen:** direct drop-in replacement. No migration work beyond `model_name` swap in `config.yml` and routing the `local-fast` / `coding` / `reasoning` routes to the new model. Most-mature path with lowest risk.

### 8.3 Qwen3-8B (same family as current, less RL)

**The case for:** **Lowest migration friction** of all candidates — same tokenizer, chat template, dtype conventions as the current substrate. Trusted `turboderp/Qwen3-8B-exl3` quant. Four-stage post-training (Long-CoT → reasoning RL → thinking-mode fusion → general RL) **without the Qwen3.5-specific million-agent-environment RL extension**. Slightly less RL-heavy than 3.5. Standard attention (no hybrid JIT risk). 32K native / 128K YaRN context. Apache 2.0.

**The case against:**
- Still moderately RL-heavy (Bucket C). Not a clean Shaikh-framework test.
- IFEval is presumably below Qwen3.5-9B's 91.5 — Qwen3 TR publishes IFEval but my search did not surface the exact number.
- **Released 2025-04** (12 months old) — between Llama 3.1 8B and Qwen3.5-9B in maturity.
- No obvious "unique selling point" versus either the safer Llama 3.1 8B choice or the research-aligned OLMo 3-7B choice.

**Recommendation if chosen:** drop-in replacement of Qwen3.5-9B with Qwen3-8B. Minimal code changes. A good "one step less RL-heavy" compromise between status quo and larger swaps. **Does not address the thinking-mode latency issue** — Qwen3 also has thinking mode defaults.

### 8.4 OLMo 3-7B Instruct (research-aligned)

**The case for:** **Unique research-program value** — AI2 publishes separate hybrid SFT-only and DPO-only checkpoints as ready EXL3 quants. This makes OLMo 3-7B the **only candidate in the entire landscape** where hapax can test the Shaikh SFT-vs-DPO grounding hypothesis **within a single model family on identical base weights**. The three checkpoints:
- `turboderp/Olmo-Hybrid-Instruct-SFT-7B-exl3` — SFT-only (pre-DPO)
- `UnstableLlama/Olmo-Hybrid-Instruct-DPO-7B-exl3` — SFT + DPO (no RLVR)
- `kaitchup/Olmo-3-7B-Instruct-exl3` — full three-stage: SFT + DPO + scaled RLVR

Using these three checkpoints, hapax could run an A-B-C comparison on grounding behaviors directly, eliminating the need for the cross-substrate claim (`claim-shaikh-sft-vs-dpo`) to depend on mixing model families. AI2 Apache 2.0, fully-open-recipe including training data. 65K context. Strong on HumanEval+, competitive with Qwen3-8B on MATH/AIME.

**The case against:**
- **No published IFEval / BFCL numbers** at this time. AI2's blog indicates "strong function calling on BFCL" and "competitive with Qwen 3 8B on MATH" but doesn't publish hard numbers for the Instruct 7B variant. Uncertain fit for pydantic-ai production use until validated empirically.
- **Maturity is only 5 months** — released 2025-11-22.
- EXL3 quant uploader trust is MEDIUM (kaitchup community, UnstableLlama community, turboderp for the hybrid SFT variant). Not as trusted as turboderp-only.
- **4K context on OLMo 2 variants is a red flag** — the OLMo 2 generation had 4K context; OLMo 3 lifts this to 65K, but there's a family history of context constraints.
- Not a drop-in replacement for production — would need pydantic-ai + tool-call validation before committing to it for agents.

**Recommendation if chosen:** **Option A — use for research only, not production.** Deploy OLMo 3-7B on a **second TabbyAPI slot** alongside Qwen3.5-9B, route to it via a new LiteLLM route `local-research` or `local-olmo-sft` / `local-olmo-dpo` / `local-olmo-rlvr`. Run RIFTS and hapax's own grounding metrics on all three checkpoints. **If results show SFT-only is meaningfully better, then consider promoting SFT-only OLMo to primary `local-fast`.** This is the drop #62 Option C pattern — parallel, not swap.

### 8.5 Mistral Small 3.1 24B Instruct ("no RL" with headroom)

**The case for:** Mistral explicitly documents **"no synthetic data or reinforcement learning"** for Small 3. Apache 2.0. Full `turboderp/Mistral-Small-3.1-24B-Instruct-2503-exl3` branch set. 32K/128K context. MMLU ~81, HumanEval 84.8. 24B gives meaningful capacity headroom over 8-9B models; persona adherence is known-strong in community reports.

**The case against:**
- **24B class VRAM fit is borderline:** 5.0 bpw @ 8k ctx → ~16 GB total, fits in 18 GB budget. 6.0 bpw @ 8k ctx → ~19 GB, exceeds budget. **Constraints bpw ceiling at 5.0** while most small-model alternatives can run at 6.0+ for higher quality.
- **No RL is an explicit claim, but Mistral's recipe is "SFT + preference tuning" — the exact preference-tuning method is not fully disclosed.** It could be DPO, IPO, KTO, or something proprietary. "No RL" is a binary claim that doesn't fully commit to the Shaikh framework SFT-pure position.
- Larger model = larger inference cost = lower tok/sec = slightly slower voice pipeline fallback. TTFT comparable to 14B models; sustained generation slower.
- 32K default context is smaller than Llama 3.1 (128K native) and Qwen3.5 (262K native). Not a hapax-relevant concern since production uses 4-8k but a comparison point.

**Recommendation if chosen:** drop-in replacement at 5.0 bpw Q4 KV 8k context, accepting the bpw ceiling constraint. Accept that this locks hapax into 5.0 bpw instead of the quality-better 6.0 bpw option. **Not recommended unless operator specifically values the "no RL" regime claim over raw benchmark quality.**

---

## 9. Recommendation with confidence and contingencies

### 9.1 Primary recommendation

**Keep Qwen3.5-9B as the production substrate, conditional on three immediate fixes, and run an empirical grounding evaluation before committing to any substrate swap.**

Three fixes required regardless of substrate choice:

1. **Disable thinking mode for `local-fast` / `coding` / `reasoning` routes.** Add `chat_template_kwargs.enable_thinking=False` to the LiteLLM route config for these three routes. Verify via a direct test that the `<think>...</think>` tokens are absent from output. This is a ~5-line config change that eliminates the most likely cause of latency surprise in production.

2. **Add cache warmup to `tabbyapi.service` startup.** Add `ExecStartPost=-/usr/bin/curl -sf -X POST http://localhost:5000/v1/chat/completions -H "Content-Type: application/json" -d '{"model":"Qwen3.5-9B-exl3-5.00bpw","messages":[{"role":"user","content":"warmup"}],"max_tokens":1}'` or equivalent. This pre-triggers the hybrid-attention JIT compile on service start so the first real voice call doesn't pay the cold-start penalty.

3. **Upgrade exllamav3 to 0.0.29.** The current 0.0.22 is 5 months behind upstream; several Ampere-specific fixes landed in 0.0.23–0.0.29. Upgrading is independent of substrate choice and should improve TTFT stability for the hybrid attention path specifically.

Then, **before** committing to any substrate swap, run the RIFTS benchmark (§10.3) against Qwen3.5-9B and 2–3 alternative candidates to get empirical grounding data instead of predicting from post-training recipe.

**Confidence in this recommendation: MEDIUM-HIGH.** The three fixes are uncontroversial. The "run RIFTS before swapping" logic is well-supported by §4's gap analysis — the literature does not support a purely-predictive swap recommendation without empirical validation on the candidate substrates. The only scenario where this recommendation is weaker than an immediate swap is if the operator has strong prior conviction that Qwen3.5-9B's grounding is specifically bad based on production observations beta is not aware of.

### 9.2 Contingency: if the operator wants a swap recommendation right now

**If a swap decision is required immediately without RIFTS validation:**

**Swap target: Llama 3.1 8B Instruct** via `turboderp/Llama-3.1-8B-Instruct-exl3` at 5.0 bpw.

Reasoning: highest deployment maturity, canonical quant, moderate post-training regime, broad community eyes. Lowest production risk of any swap target. Accepts an IFEval gap (80.4 vs 91.5) as the cost of moving off a 6-week-old model onto a 21-month-battle-tested one.

**Confidence in this swap: LOW-MEDIUM.** Loses measurable benchmark quality (primarily IFEval, which hapax's pydantic-ai agents depend on) in exchange for maturity and slightly better Shaikh position. If the operator's main concern is grounding behaviors, this swap is moderate (not a Shaikh-pure test); if the main concern is deployment stability, this swap is strong.

### 9.3 Contingency: if the operator wants a research-aligned substrate

**If research program alignment is the priority:**

**Parallel deployment: add OLMo 3-7B Instruct (with SFT-only and DPO-only split checkpoints) as a second TabbyAPI slot on :5001, routed via new LiteLLM routes `local-research-sft` / `local-research-dpo` / `local-research-rlvr`.** Keep Qwen3.5-9B as primary `local-fast`. Run hapax's grounding DVs (Cycle 2 framework) against all three OLMo checkpoints plus the current Qwen3.5-9B. Compare results.

This is the drop #62 Option C pattern applied to the research program: **additive, not swap**. Qwen never leaves; OLMo 3-7B provides the SFT/DPO/RLVR A/B/C test that no other candidate supports. **This is the unique value of OLMo 3-7B** and should be considered even if Qwen3.5-9B stays as primary production substrate.

**Confidence in this recommendation: HIGH.** OLMo 3-7B's unique SFT/DPO checkpoint availability is a genuine differentiator. Parallel deployment carries no risk to production (Qwen3.5-9B stays primary) and enables the research program to run the Shaikh framework test directly. The cost is ~6 GB VRAM + 1 systemd unit + 3 LiteLLM routes.

### 9.4 Contingency: if the operator wants an empirical validation pipeline

**Run the RIFTS benchmark** (github.com/microsoft/rifts, 1,740 prompts) against Qwen3.5-9B, Llama 3.1 8B Instruct, OLMo 3-7B Instruct (or its SFT/DPO/RLVR split), and optionally Qwen3-8B.

Execution: download RIFTS, run each model via LiteLLM against the benchmark, score per model, compare against the published 23.23% frontier average. Time: ~2-4 hours per model = 8-16 hours total. Output: direct empirical grounding data on the exact substrates hapax is choosing between.

**Confidence in this approach: HIGH** — this is what the literature gap analysis (§4.4) says is the missing step. Any substrate choice informed by RIFTS results is more defensible than one informed by post-training recipe alone.

### 9.5 Recommendation matrix

| Scenario | Recommendation | Confidence |
|---|---|---|
| Operator wants lowest-disruption path | **Keep Qwen3.5-9B, fix thinking mode + warmup + upgrade exllamav3. Run RIFTS.** | MEDIUM-HIGH |
| Operator wants immediate decision without empirical validation | Swap to Llama 3.1 8B Instruct | LOW-MEDIUM |
| Operator wants research program alignment | Parallel deployment: add OLMo 3-7B (SFT-only, DPO-only, RLVR checkpoints) as `local-research-*` routes on second TabbyAPI slot | HIGH |
| Operator wants empirical evidence before deciding | Run RIFTS against Qwen3.5-9B + Llama 3.1 8B + OLMo 3-7B variants | HIGH |
| Operator wants "no RL" on principle | Swap to Mistral Small 3.1 24B Instruct at 5.0 bpw | MEDIUM |

**Beta's overall take:** Recommendations 1 (fix + validate) and 3 (parallel OLMo for research) are complementary and both HIGH-confidence. They can be executed in parallel. The combined path — fix Qwen3.5-9B production issues, add OLMo 3-7B for research program, run RIFTS — addresses every concern raised in §§1–4 without committing to a premature swap.

---

## 10. Research protocol implications

---

## 10. Research protocol implications

Independent of which substrate is chosen, the following research-program implications apply:

### 10.1 Cycle 2 pre-registration remains valid

The Cycle 2 SCED (A-B-A on grounding package) does not depend on substrate identity — it tests grounding-package-on vs grounding-package-off on whichever substrate is active. A substrate swap from Qwen3.5-9B to another model would require a DEVIATION (`DEVIATION-039` next available) to document the swap and open a new condition in the research registry. The pre-registration does not need rewriting.

### 10.2 `claim-shaikh-sft-vs-dpo` reframing

The original claim `claim-shaikh-sft-vs-dpo` was framed as Qwen3.5-9B (Condition A) vs Hermes 3 70B (Condition A') testing SFT-only vs DPO-heavy. With Hermes abandoned and the substrate under re-evaluation, this claim requires reframing. Options:

- **Option X:** retire the claim entirely. Cycle 2 tests grounding-package-on/off only, not cross-substrate. The Shaikh framework informs substrate selection but is not itself tested.
- **Option Y:** retain the claim but swap Condition A' from Hermes 3 70B to a new SFT-heavy 7-14B candidate (if one is selected). Rerun the Shaikh framework test at a more realistic hardware envelope.
- **Option Z:** defer the claim to a future cycle. Cycle 2 proceeds with grounding-package test only; claim-shaikh-sft-vs-dpo is opened as a Cycle 3 claim with a substrate-pair to-be-decided.

Beta recommends Option Z. Reasoning: Cycle 2 is already in pre-staging; adding substrate comparison mid-cycle complicates it. Future cycles can run cleaner comparisons with better-calibrated hypotheses.

### 10.3 Empirical grounding evaluation

Regardless of substrate choice, hapax would benefit from running a **direct grounding evaluation** on its candidate substrate(s) using the RIFTS benchmark (github.com/microsoft/rifts). This is a 1,740-prompt benchmark that can be run offline against any LiteLLM-compatible model route. Results would give hapax **direct empirical data on the exact substrate it uses** instead of predicting from post-training recipe. This would also address literature gap #4.4.3 directly.

Cost: ~2-4 hours of evaluation time per substrate. Output: per-model RIFTS score directly comparable to the published 23.23% frontier baseline.

### 10.4 Thinking mode disposition

If Qwen3.5-9B stays as the substrate, the thinking-mode-by-default behavior needs explicit handling:

- **Option 1:** disable thinking mode globally for the local-fast route (via `chat_template_kwargs.enable_thinking=False` in the LiteLLM config). Lowest latency, but loses any reasoning benefit.
- **Option 2:** enable thinking mode only for coding / reasoning routes, disable for LOCAL tier voice. Requires routing-level thinking-mode parameter.
- **Option 3:** leave thinking mode on; accept the latency tax. Not recommended for voice-tier fallback.

Needs verification of current production state. If thinking mode is on and we haven't noticed, that's a separate fix.

---

## 11. Open questions and recommended actions for the operator

### 11.1 Blocking questions (answer before proceeding)

1. **Is thinking mode currently disabled for `local-fast` / `coding` / `reasoning` routes?** Verify in production LiteLLM config and a Langfuse trace of a recent local-fast call. If not, this is the single highest-ROI production fix regardless of the broader substrate decision.
2. **Does operator want to run RIFTS for empirical validation before deciding?** 8-16 hours of eval time; produces direct grounding data on hapax's specific substrate candidates. The alternative is predictive reasoning from post-training recipe, which §4.4 establishes as a known gap in the literature.
3. **Does operator want to parallel-deploy OLMo 3-7B** (SFT/DPO/RLVR checkpoints) for the research program, independent of whether Qwen3.5-9B stays as primary? This addresses the `claim-shaikh-sft-vs-dpo` reframing question (§10.2) and gives hapax the ONLY single-family isogenic Shaikh test.
4. **Is the Parrot small-Qwen sycophancy result** (94% follow-rate at 1.5B; family trend concerning) operator-validated or merely a theoretical prior? Specifically: has the operator observed sycophantic patterns in stimmung-critical downgrades?

### 11.2 Non-blocking open questions (can be resolved later)

5. Does `tabbyapi.service` currently have cache warmup? If not, the JIT-compile cold start for Qwen3.5-9B's hybrid attention is hitting the first voice call on every service restart. A one-line systemd `ExecStartPost` fixes this independently of substrate choice.
6. Is the production stack's exllamav3 0.0.22 → 0.0.29 upgrade operator-blocking or beta can propose the upgrade PR? The 5-month gap includes Ampere-specific fixes relevant to RTX 3090.
7. Does the operator want to run RIFTS against `shared/config.py::MODELS["capable"]` (Claude Opus) for calibration? This establishes the ceiling hapax can reach at any substrate tier.
8. Should the hapax research program separate "local substrate benchmarking" (a research question) from "production substrate selection" (a deployment decision)? Currently they're bundled. Separating them would let RIFTS run as pure research without a production commitment.
9. Is there production telemetry on Qwen3.5-9B's actual TTFT / tokens-per-second / refusal-rate / persona-adherence over the ~6-week deployment? Langfuse traces filtered by `model=openai/Qwen3.5-9B-exl3-5.00bpw` should answer this. If the telemetry shows Qwen3.5-9B is already performing well, the research is less urgent.
10. If the operator wants a two-substrate deployment (e.g. Qwen3.5-9B + OLMo 3-7B for research), should the routing tier be `ModelTier.LOCAL` (voice fallback) or a new research-specific tier below that?

### 11.3 Non-substrate concerns surfaced during the research

These are independent of the substrate decision but worth noting:

- **exllamav3 0.0.22 vs 0.0.29 stack gap** (§6.1). Upgrade recommended regardless of substrate choice.
- **`cache_size` = 4096 tokens** in production TabbyAPI config (§6.1). Recommended increase to 16384–24576 to ensure persona + system prompt prefix survives turn-over-turn eviction in the continuous cognitive loop pattern.
- **Prompt-prefix caching is automatic in exllamav3** — no explicit toggle needed. Sizing is the lever.
- **Cycle 2 `claim-shaikh-sft-vs-dpo` reframing options** (§10.2): retire the claim, swap Condition A' to a non-Hermes candidate, or defer to Cycle 3. Beta recommends defer.

---

## 12. Decision record

*This section remains empty until the operator picks an option from §9.5 and any resulting substrate change is executed. Placeholder format:*

```
Date of decision: [YYYY-MM-DD]
Option chosen: [1/2/3/4/5 from §9.5]
Rationale: [operator rationale]
Substrate before: Qwen3.5-9B-exl3-5.00bpw (current)
Substrate after: [chosen substrate]
DEVIATION filed: [DEVIATION-NNN]
Research registry condition transition: [cond-phase-a-* → cond-phase-a-*]
Fixes applied (thinking mode / warmup / exllamav3 upgrade): [list]
RIFTS results (if run): [per-model scores]
Langfuse baseline: [pre-decision production metrics]
Langfuse post-decision: [post-decision production metrics at +1 week / +1 month]
```

---

## Methodology and authorship note

This research document was produced by beta (PR #819 author) on 2026-04-15 in response to operator direction:

> *"We've abandoned hermes. Devote extensive research into if Qwen3.5-9B-exl3-5.00bpw is actually the best production substrate for our very unique use cases."* — 2026-04-15T06:35Z

**Research methodology:** the research was performed in parallel by three subagents delegated from beta, plus direct WebSearch and direct reads of hapax internal configuration by beta:

- **Subagent A** — SOTA 7-14B LLM landscape enumeration (2024-2026, non-Hermes), post-training regime bucket categorization, benchmark data retrieval, HuggingFace EXL3 quant search, license verification. Output: comprehensive candidate matrix and regime groupings, used in §5.
- **Subagent B** — Post-training regime + Shaikh grounding framework literature update, new 2025-2026 papers, regime taxonomy, RLVR analysis, grounding benchmark state-of-the-art, empirical model comparison data, gap analysis. Output: comprehensive literature review with confidence assessment, used in §4.
- **Subagent C** — EXL3 / TabbyAPI / exllamav3 deployment feasibility, per-candidate VRAM math at 4-5 bpw with Q4 KV cache and 8k context, architecture compat for exllamav3 0.0.22 / 0.0.29, latency and prompt-prefix caching analysis, per-candidate deployment risk ratings. Output: deployment matrix, used in §6.
- **Beta direct research** — Qwen3.5-9B primary-source verification (Qwen3 technical report arXiv 2505.09388, Qwen3.5 blog, HuggingFace model card), production config audit (shared/config.py, tabbyAPI/config.yml, agents/hapax_daimonion/model_router.py, agents/hapax_daimonion/conversation_pipeline.py), use-case profile synthesis, scoring, and recommendation. Output: §§1, 2, 3, 7, 8, 9, 10, 11, 12.

**Key information gaps the research did NOT close** (flagged for operator awareness):

- No published IFEval / BFCL numbers for OLMo 3-7B Instruct — its actual production suitability is uncertain until RIFTS or direct pydantic-ai testing is run.
- No published IFEval / BFCL numbers for Qwen3-8B / Qwen3-14B instruct variants (only base model scores surfaced). Qwen3 TR at arXiv 2505.09388 has them but the relevant tables weren't extracted.
- No empirical grounding data (RIFTS, QuestBench, SYCON Bench, MultiChallenge) on Qwen3.5-9B specifically. This is a literature gap, not a research-methodology gap — the benchmarks have not been run by anyone for this model as of April 2026.
- No production telemetry on Qwen3.5-9B's actual 6-week deployment behavior was reviewed — Langfuse traces should exist but were not queried during this research. This is an important gap to close before committing to any decision.

**Document status:** COMPLETE as of 2026-04-15. Awaiting operator review and decision.

**Commit landing location:** `beta-phase-4-bootstrap` branch, PR #819. Scope creep from the original Phase 4 bootstrap focus is acknowledged; the research drop is defensible as a docs-only addition that does not touch frozen files or code.

— beta (PR #819 author), 2026-04-15T06:50Z

---

## Erratum 2026-04-15T07:20Z

During execution of delta's first AWB assignment (thinking-mode disable, based on this research doc §9.1 recommendation), beta verified the actual production state of the LiteLLM config and the exllamav3 runtime. **Two verification failures in this research document were identified.**

Per the `feedback_verify_before_claiming_done` memory, errata are corrections that preserve the audit trail rather than rewriting the original claims. This section records the corrections without editing §§1–12 above.

### E1. Thinking mode is ALREADY disabled for `local-fast` and `coding` routes

**Original claim (§1.2 + §1.5 + §9.1 first fix):** *"Current production config does not explicitly disable thinking mode — needs verification; if thinking is on, every local-fast call pays the thinking-token latency tax on top of the actual response."*

**Verified state (2026-04-15T07:15Z):** the production LiteLLM config at `~/llm-stack/litellm-config.yaml` lines 57–82 shows:

```yaml
  - model_name: local-fast
    litellm_params:
      model: openai/Qwen3.5-9B-exl3-5.00bpw
      api_base: http://172.18.0.1:5000/v1
      api_key: "dummy"
      extra_body:
        chat_template_kwargs:
          enable_thinking: false       # <-- ALREADY DISABLED

  - model_name: coding
    litellm_params:
      # ... same settings ...
      extra_body:
        chat_template_kwargs:
          enable_thinking: false       # <-- ALREADY DISABLED

  - model_name: reasoning
    litellm_params:
      # ... same settings ...
      extra_body:
        chat_template_kwargs:
          enable_thinking: true        # <-- ENABLED (correct for reasoning)
```

**Direct API verification** (bypassing LiteLLM, testing against TabbyAPI :5000 with explicit `chat_template_kwargs`):

- `enable_thinking=false`: response is "Hello there friend." — no thinking prose, direct answer
- `enable_thinking=true`: response is "Thinking Process:\n\n1. **Analyze the Request:**..." — verbose thinking prose before any answer

**Conclusion:** the production state is **correct**. `local-fast` and `coding` routes do not pay the thinking-mode latency tax. The `reasoning` route correctly emits thinking prose (which is wanted for reasoning tasks).

**Why the original claim was wrong:** beta inspected `tabbyAPI/config.yml` (TabbyAPI's own config, which does not control thinking mode — that's a per-request kwarg) but did not inspect the LiteLLM route config at `~/llm-stack/litellm-config.yaml`. The thinking-mode control lives in the request-level `chat_template_kwargs.enable_thinking` field, which is set per-route in LiteLLM's `extra_body`. Beta's research inspected the wrong layer.

**Lesson:** verify the actual control surface, not the adjacent one. LiteLLM injects `extra_body` into the outgoing TabbyAPI request; TabbyAPI's own config does not configure the chat template's thinking mode.

**Recommendation from §9.1 first fix is already satisfied.** No action required.

### E2. exllamav3 runtime version is 0.0.23, not 0.0.22

**Original claim (§1.2 + §6.1 + §9.1 third fix):** *"exllamav3 version 0.0.22... production stack version: 0.0.22 — a ~4-5 month lag behind upstream."*

**Verified state (2026-04-15T07:15Z):** `~/projects/tabbyAPI/venv/lib/python3.12/site-packages/exllamav3-0.0.23+cu128.torch2.9.0.dist-info` — runtime exllamav3 is **0.0.23**.

**Why the original claim was wrong:** beta read the `quantization_config.version: "0.0.22"` field in `tabbyAPI/models/Qwen3.5-9B-exl3-5.00bpw/config.json` and assumed this was the runtime version. It is NOT — that field records the **quant pack format version** at the time the model was quantized (by turboderp or another uploader), which is a different artifact from the runtime library. A model quantized at pack-format 0.0.22 runs fine on runtime 0.0.23 (forward-compatible).

**Lesson:** distinguish quant pack version (immutable artifact) from runtime library version (installable). The production runtime is reported by `pip show exllamav3` or by looking at the installed `.dist-info` directory, not by inspecting the quant's config.json.

**Corrected version gap:** 0.0.23 → 0.0.29 is 6 point releases (~3-4 months), not 7 point releases (~4-5 months). The Ampere-specific fixes in the interval are still relevant; the upgrade is still worth doing; the urgency is slightly reduced.

**Recommendation from §9.1 third fix is still valid.** The upgrade path is smaller than originally claimed but not a no-op.

### E3. Cache warmup recommendation is still valid and shippable

**Original claim (§9.1 second fix):** *"Add startup cache warmup via a no-op completion on `tabbyapi.service` `ExecStartPost`."*

**Verified state (2026-04-15T07:15Z):** `systemctl --user show tabbyapi.service -p ExecStartPost` returns empty. No `ExecStartPost` in the current unit file. The recommendation is still valid and shippable.

**This item is unchanged** and remains a concrete shippable for the AWB lane.

### Corrective action taken

1. This erratum section appended to the research document (preserving the original claims in §§1–12 unchanged).
2. The three-fix recommendation in §9.1 is updated in spirit: fix #1 is NO-OP (already satisfied), fix #2 remains valid, fix #3 is valid with smaller gap than claimed.
3. Beta closes delta's first AWB assignment (thinking-mode disable) as a NO-OP with the verified finding, requesting delta's next formal assignment (likely the cache warmup item delta pre-queued as assignment #2).

### Meta-observation on research methodology

This errata section exists because beta's substrate research at commit `bb2fb27ca` shipped without the "verify against actual production state" step that `feedback_verify_before_claiming_done` memory explicitly warns against. Specifically:

- The research enumerated candidates, synthesized criteria, and recommended fixes.
- The research did NOT verify the existing production state of the recommended fixes BEFORE recommending them.
- The first AWB assignment (thinking-mode disable) surfaced the verification gap within ~10 minutes of beta attempting to execute it.

**Remediation for future research drops:** any recommendation that could plausibly already be in place in production (config changes, systemd unit adjustments, feature flags, etc.) must include a verification step that checks the actual production state BEFORE being written as a recommendation. This is a 2-5 minute check per recommendation; the cost of skipping it is a spurious recommendation that generates downstream work (as happened here).

The broader recommendations in §9 (candidates, rankings, RIFTS validation, OLMo 3-7B parallel deployment for research program) are not invalidated by these errata — they address a different layer of the substrate question than the three production fixes.

— beta, 2026-04-15T07:20Z
