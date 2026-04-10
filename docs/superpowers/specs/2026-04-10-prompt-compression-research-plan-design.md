# Prompt Compression Research Plan

**Date**: 2026-04-10
**Status**: Approved
**Session**: beta
**Depends on**: Hermes 3 70B Mono-Model Voice Architecture (2026-04-10)
**Context artifacts**: `~/.cache/hapax/relay/context/prompt-compression-research.md`, `~/.cache/hapax/relay/context/prompt-compression-touchpoint-audit.md`

---

## 1. Problem Statement

The hapax voice daemon constructs ~2,200 tokens of system context per turn in normal operation. The incoming Hermes 3 70B migration (EXL3 3.0bpw, layer-split across RTX 3090 + RTX 5060 Ti) processes prompt tokens at ~50 tok/s — roughly half the current Qwen3.5-9B rate. Every prompt token saved has 2x the latency ROI after migration. Voice latency directly implicates consent flow (governance violation, not UX — per axiom).

A comprehensive touchpoint audit identified 7 working compression mechanisms, 5 optimization targets, and 8 unleveraged opportunities across the system's 35+ LLM call sites. This plan organizes all optimizations and research items into a phased schedule keyed to the Hermes 3 70B migration timeline.

### 1.1 Mutual Reinforcement

Prompt compression and the mono-model migration are mutually reinforcing:
- The 70B model makes compression more valuable (slower tok/s → higher latency cost per token)
- Compression makes the 70B model more viable (lower prompt overhead → latency closer to current 9B)
- SFT-only models respond more reliably to terse compressed directives than verbose ones (Hermes 3 spec §2.3)
- Compressed context reduces KV-cache memory, increasing headroom on the 5060 Ti overflow GPU

They are designed as a single coordinated effort.

### 1.2 Theoretical Grounding

The compression approach is constrained by the Clark & Brennan grounding theory and CONTEXT-AS-COMPUTATION mechanistic framework:

- **Hard compression only for grounding-critical content.** Acceptance signals, operator verbatim vocabulary (conceptual pacts), and repair sequences must survive compression. Soft compression (GIST, AutoCompressor) destroys entrainment heads and in-context RL signals — rejected.
- **Positional compression preserved.** STABLE-first (primacy tail) + VOLATILE-last (recency) layout is mechanistically optimal. No restructuring.
- **Grounding state as compression signal.** Novel: no existing compression method uses Clark's contribution-acceptance state to determine compression ratio. Age is a proxy; grounding state is the direct measure.

Full theoretical analysis in `~/.cache/hapax/relay/context/prompt-compression-research.md`.

---

## 2. Current State

### 2.1 Working Compression Mechanisms

| Mechanism | Location | Tokens Saved | Theory Alignment |
|---|---|---|---|
| Tiered thread compression | `conversation_helpers.py:99-128` | ~100/turn | Clark's least effort; preserves acceptance at every tier |
| Tool recruitment gate | `conversation_pipeline.py:995-1009` | 700-1,000/turn | AffordancePipeline semantic selection; highest absolute savings |
| Phenomenal context fidelity | `phenomenal_context.py`, `phenomenal_layers.py` | ~100-200/turn | Upstream self-compression; tier-aware |
| Message drop | `conversation_pipeline.py:936-952` | 500-2,000/turn | Thread preserves grounding state of dropped turns |
| TOON encoding | `logos/_context_compression.py:21-31` | 40-60% per use | Lossless structured compression; 3 touchpoints |
| Staleness gates | Various | Variable | Temporal zero-token; prevents context pollution |
| Condition gating | `render_health()`, `render_stimmung()` | Variable | Nominal state = zero tokens |

### 2.2 Token Budget (Current)

| Component | Tokens | Position | Compression |
|---|---|---|---|
| Base system prompt | 1,300 | STABLE start | None |
| Conversation thread | 0-200 | STABLE | Tiered, max 10 entries |
| Sentinel fact | 25 | STABLE | None |
| Policy block | 0-400 | VOLATILE start | Context-dependent |
| Goals | 0-50 | VOLATILE | Top 5 active |
| Health | 0-30 | VOLATILE | Only when degraded |
| Nudges | 0-40 | VOLATILE | Top 3, 30s cache |
| DMN buffer | 0-500 | VOLATILE | Raw XML, no compression |
| Imagination | 0-200 | VOLATILE | Upstream determined |
| Phenomenal context | 0-300 | VOLATILE | Progressive fidelity |
| Salience context | 0-80 | VOLATILE | Scores only |
| Grounding directive | 30-50 | VOLATILE | Fixed templates |
| Effort level | 10-20 | VOLATILE | Discrete levels |
| Tool descriptions | 0-1,300 | kwargs["tools"] | Recruited subset |
| **Typical total** | **~2,200** | | |

### 2.3 Existing Infrastructure

- **TOON format** (`toon.encode()`): Lossless 40-60% token savings on structured data. Used in 3 places (axioms, knowledge search, env_context).
- **LLMLingua-2** (`logos/_context_compression.py:34-51`): BERT-base model on CPU, lazy-loaded. Used only in Logos chat compaction (`ChatSession._maybe_compact()`). Not used in voice pipeline (deliberate — `conversation_pipeline.py:938` comments "no lossy LLMLingua-2 compression needed").
- **KV-cache Q8**: Already specified in Hermes 3 migration plan (`cache_mode: Q8`).

---

## 3. Phase 1 — Software Optimizations (Pre-Hardware)

**Timing:** Now through hardware arrival (~2 days)
**Mode:** R&D
**Frozen paths touched:** None
**Goal:** Compress typical voice turn from ~2,200 to ~900-1,100 tokens

### 3.1 System Prompt Tool Directory Stripping

**Target:** ~1,000 tokens saved per turn
**Files:** `agents/hapax_daimonion/persona.py`
**Risk:** Very low

When `ToolRecruitmentGate` is active, replace `_SYSTEM_PROMPT` (1,300 tokens including full tool directory) with a minimal variant (~150-200 tokens: identity + personality + voice rules). Recruited tool schemas in `kwargs["tools"]` already carry complete descriptions — the natural language directory is redundant.

Experiment mode (`_EXPERIMENT_PROMPT`) already does this at ~300 tokens. This extends that discipline to normal voice operation.

**Implementation:**
- Create `_SYSTEM_PROMPT_MINIMAL` in `persona.py` (identity + personality block, no tool directory)
- Add `tool_recruitment_active` parameter to `system_prompt()` function
- `pipeline_start.py` passes this flag based on whether `ToolRecruitmentGate` is initialized
- Fallback: full prompt when recruitment gate is absent

**Validation:** Assemble 10 synthetic turns, verify recruited tools unchanged, verify LLM still receives all tool information via `kwargs["tools"]`.

### 3.2 DMN Buffer Compression

**Target:** 200-300 tokens saved per turn (96% reduction when stable)
**Files:** `agents/hapax_daimonion/context_enrichment.py`
**Risk:** Near-zero

Replace raw XML injection in `render_dmn()` with a parser that counts consecutive identical states and emits a compressed summary.

**Current output** (317 tokens):
```xml
<dmn_observation tick="43169" age="141s">stable</dmn_observation>
... (18 identical lines) ...
<dmn_evaluation tick="43181" age="44s"> Trajectory: stable. Concerns: none </dmn_evaluation>
```

**Compressed output** (~10-15 tokens):
```
DMN: stable (18 ticks, 141s span). Trajectory: stable. No concerns.
```

**When trajectory changes**, render the last N distinct observations:
```
DMN: stable (12 ticks) → elevated (3 ticks) → cautious (2 ticks, current). Concerns: resource_pressure.
```

**Implementation:**
- Parse `<dmn_observation>` and `<dmn_evaluation>` tags in `render_dmn()`
- Run-length encode consecutive identical states
- Render compressed summary
- ~30 lines of change

**Validation:** Unit tests covering stable, changing, and empty buffer states.

### 3.3 Policy Block Compression

**Target:** 100-250 tokens saved per turn
**Files:** `agents/hapax_daimonion/conversational_policy.py`
**Risk:** Low

Replace verbose natural language directives with single-line signals. SFT-only Hermes 3 responds more reliably to terse directives (spec §2.3: "aggressively encourages following system and instruction prompts exactly").

**Current** (~30 tokens per directive):
```
The operator appears to be in focused work mode. Match their energy — be concise and don't initiate conversation unless they engage.
```

**Compressed** (~5 tokens):
```
Mode: focused. Be concise.
```

**Implementation:**
- Rewrite each policy directive to a single-line signal format
- Activity mode, consent state, system warnings each become 3-8 tokens
- Preserve semantic content; remove rhetorical framing

**Validation:** Grounding directive compliance test (reused in Phase 2.4) on compressed vs verbose directives.

### 3.4 TOON Format Expansion

**Target:** 40-60% token savings at each new touchpoint
**Files:** Multiple across `agents/`, `shared/`, `logos/`
**Risk:** Near-zero (lossless)

Systematic rollout of `to_toon()` encoding to all structured data injections:

| Touchpoint | Current Format | Estimated Savings |
|---|---|---|
| Profile digest rendering | Markdown | 200→120 tokens |
| Health snapshots | Inline text | 30→15 tokens |
| Nudge rendering | Markdown list | 40→25 tokens |
| Qdrant document results | Markdown | 500→300 tokens |
| Qdrant profile results | Raw payload | 200→120 tokens |
| Scout evaluation results | Markdown | Variable |
| Briefing data assembly | Markdown | Variable |

**Implementation:**
- Import `to_toon` in each file
- Replace markdown/text formatting with `to_toon()` calls on structured data
- Preserve any non-structured text (narratives, descriptions) as-is

**Validation:** Token count comparison on 10 representative payloads per touchpoint.

### 3.5 Qdrant Retrieval Compression

**Target:** 200-400 tokens saved on retrieval-heavy turns
**Files:** `shared/knowledge_search.py`, `shared/profile_store.py`, `shared/affordance_pipeline.py`
**Risk:** Low

Three changes:

**(a) Result TOON encoding:** Covered by 3.4. All Qdrant payloads formatted via `to_toon()`.

**(b) Cross-collection deduplication:** When multiple context tools query different collections for the same agent turn, deduplicate results by embedding cosine similarity > 0.9. Implementation: maintain a per-turn result cache in `ContextAssembler`, compute pairwise cosine on result embeddings before injection, drop near-duplicates.

**(c) Adaptive result limits:** Reduce `limit` parameter based on model tier and pipeline:
- Voice pipeline: `limit=3` for documents (was 10), `limit=2` for profiles (was 5)
- LOCAL tier: same reduced limits
- CAPABLE/cloud agents: unchanged defaults

**Validation:** Compare retrieved result sets at old vs new limits on 20 representative queries. Measure recall of relevant results.

### 3.6 LLMLingua-2 Hardening

**Target:** No direct token savings — enables broader compression
**Files:** `shared/context_compression.py`, `logos/_context_compression.py`, health monitor
**Risk:** Near-zero

- Expose `_compressor is not None` in health monitor check (`check_llmlingua`)
- Add domain-aware `force_tokens` configuration: voice pipeline preserves `ACCEPT`, `CLARIFY`, `REJECT`, `IGNORE`, `REPAIR`, `GROUNDED`; retrieval preserves source citations
- Deduplicate the three copies of `_context_compression.py` (logos/, agents/, shared/) into a single `shared/context_compression.py` with re-exports
- Add startup log message confirming compressor availability

**Validation:** Health check reports compressor status. Force tokens preserved in compressed output.

### 3.7 Cross-Agent Context Deduplication

**Target:** Aggregate savings across the 35+ agent fleet
**Files:** `agents/_context.py` (`ContextAssembler`)
**Risk:** Low

Wire the existing `ContextAssembler` pattern to cache computed context fragments with TTL:

| Fragment | TTL | Shared By |
|---|---|---|
| Operator context | 60s | All pydantic-ai agents |
| Health snapshot | 30s | Briefing, drift, health monitor |
| Active goals | 60s | Orientation, briefing, interview, research |
| Profile digest | 300s | Profiler, interview, research |

**Implementation:**
- Add `@cached_fragment(ttl=N)` decorator in `ContextAssembler`
- Agents calling `get_system_prompt_fragment()` or context tools receive cached results
- Cache invalidated on TTL expiry or explicit flush

**Validation:** Verify cache hit rate via Langfuse trace metadata. Confirm stale data never exceeds TTL.

---

## 4. Phase 2 — Migration-Coupled Benchmarking (Hardware Day 1-3)

**Timing:** Interleaved with Hermes 3 70B migration tasks 1-11
**Mode:** R&D
**Goal:** Validate all Phase 1 optimizations against the new model

### 4.1 Prompt Token Budget Audit

**Timing:** During migration Phase 1 (inference validation)
**Method:** Run 10 synthetic voice turns with instrumented token counting. Measure actual token counts for each prompt component under both old (~2,200) and compressed (~1,000) prompts on Hermes 3 70B.
**Deliverable:** Ground-truth token budget table replacing estimates.

### 4.2 Latency Benchmarking

**Timing:** During migration Phase 1
**Method:** Measure TTFT and total response time across 4 conditions:

| Condition | Prompt | Model | Expected TTFT |
|---|---|---|---|
| A (old baseline) | ~2,200 tokens | Qwen3.5-9B | ~50-100ms |
| B (compressed baseline) | ~1,000 tokens | Qwen3.5-9B | ~30-60ms |
| C (old on new model) | ~2,200 tokens | Hermes 3 70B | ~300-400ms |
| D (compressed on new model) | ~1,000 tokens | Hermes 3 70B | ~200-280ms |

20 turns per condition, median/p95/p99. Primary success metric: D's TTFT < C's TTFT by ≥50ms.

### 4.3 KV-Cache Quantization Validation

**Timing:** During migration Phase 1
**Method:** Compare Q8 vs FP16 KV-cache on compressed prompt. 20 turns, output token overlap score. Also measure VRAM across 3 configurations:

| Config | KV-Cache | Prompt Tokens | Expected VRAM |
|---|---|---|---|
| Old + FP16 | FP16 | 2,200 | ~0.68 GB |
| Compressed + Q8 | Q8_0 | 1,000 | ~0.16 GB |
| Old + Q8 | Q8_0 | 2,200 | ~0.35 GB |

**Deliverable:** Confirmation that Q8 + compressed prompt introduces no quality degradation while reducing KV-cache VRAM by ~75%.

### 4.4 Grounding Directive Compliance

**Timing:** During migration Phase 2 (voice integration)
**Method:** Inject each of 6 Traum directive strategies (advance, rephrase, elaborate, present_reasoning, move_on, ungrounded_caution) in compressed format (Phase 1.3) vs original verbose format. Score compliance via existing `score_directive_compliance()`.

10 turns per directive × 2 formats × 2 models (Qwen3.5-9B, Hermes 3 70B) = 240 turns.

**Deliverable:** Compliance matrix. Tests both compression quality AND the SFT-only hypothesis from the mono-model spec. If Hermes 3 shows higher compliance on compressed directives, this validates both the model choice and the compression approach.

### 4.5 Tool Recruitment Validation

**Timing:** During migration Phase 2
**Method:** 20 operator utterances through `ToolRecruitmentGate.recruit()` with old prompt (tool directory present in system message) vs compressed prompt (directory stripped). Compare recruited tool sets.

**Expected:** Identical sets — recruitment uses embedding similarity against Qdrant affordances, not the system prompt directory.

**Deliverable:** Confirmation that tool directory stripping has zero effect on tool recruitment.

### 4.6 Phenomenal Context Attention Analysis (Opportunistic)

**Timing:** During migration Phase 1 (if ExllamaV2 exposes attention weights)
**Method:** Capture per-token attention patterns over the 20-turn latency benchmark set. Identify which phenomenal context tokens receive consistently low attention from Hermes 3 70B.

**Prerequisite:** ExllamaV2/V3 attention weight extraction. Check availability before attempting. Skip if unavailable or adds >2s overhead per turn.

**Deliverable:** Attention heatmap over phenomenal context layers. Feeds Phase 3.2.

### 4.7 Decision Gate G-PC2

**Criteria:**
- [ ] Compressed prompt assembles correctly (G-PC1, end of Phase 1)
- [ ] Latency benchmark shows measurable TTFT improvement (condition D < condition C by ≥50ms)
- [ ] Grounding directive compliance equal or better on compressed format
- [ ] Tool recruitment unchanged
- [ ] KV-cache Q8 + compression introduces no quality degradation

**If any optimization degrades quality:** Revert that specific item and re-benchmark. Phase 1 items are independent — any subset can ship.

---

## 5. Phase 3 — Research Extensions (Post-Migration Stable)

**Timing:** 1-2 weeks after Hermes 3 70B stabilization
**Mode:** R&D (3.1-3.3), RESEARCH for 3.4-3.5
**Goal:** Novel research contributions + Cycle 3 experiment design

### 5.1 GrndComp: Grounding-State-Aware Thread Compression

**Target:** Novel theoretical contribution + potential Cycle 3 treatment condition
**Files:** `agents/hapax_daimonion/conversation_helpers.py`
**Risk:** Medium (changes treatment variable if adopted for experiment)

Replace age-based compression tiers in `_render_thread()` with grounding-state-driven compression. `ThreadEntry` already carries `grounding_state` (grounded/in-repair/ungrounded/pending) and `acceptance` (ACCEPT/CLARIFY/REJECT/IGNORE).

**Compression rules:**

| Grounding State | Compression | Rationale |
|---|---|---|
| `in-repair` | Full fidelity (all ages) | Repair sequence needs all tokens (Traum 1994) |
| `ungrounded` | Operator verbatim text preserved | Failed conceptual pact must be visible for retry (Brennan 1996) |
| `grounded` + age ≥ 3 | Keyword + acceptance only | Understanding established — Clark's sufficient for current purposes |
| `pending` | Full fidelity | Not yet classified |

**Evaluation:** A/B comparison on 50 synthetic conversation traces with known grounding states. Three conditions:
- (A) Age-based compression (current)
- (B) GrndComp (grounding-state-aware)
- (C) LLMLingua-2 generic compression (control)

Scored on: thread token count, LLM grounding directive compliance, turn_pair_coherence.

**Success criterion (G-PC3):** GrndComp matches or beats age-based on turn_pair_coherence at lower token count.

### 5.2 Attention-Informed Phenomenal Context Pruning

**Target:** Empirically derived thresholds replacing hand-tuned values
**Files:** `agents/hapax_daimonion/phenomenal_layers.py`
**Risk:** Low (non-experiment path)
**Prerequisite:** Phase 2.6 attention data or dedicated capture pass

**Method:** Analyze per-token attention across 50+ voice turns on Hermes 3 70B. For each phenomenal context layer:
- Compute mean attention received
- Identify consistently ignored tokens/layers (<1% of total attention)
- Compare layer ordering against attention rank

**Deliverable:** Revised thresholds for surprise, confidence, staleness gates. Potentially revised tier assignments (e.g., if temporal depth is consistently ignored, demote from FAST to CAPABLE-only).

### 5.3 Turn-Specific Context Selection

**Target:** Further token savings by filtering irrelevant VOLATILE sections per turn
**Files:** `agents/hapax_daimonion/conversation_pipeline.py` (VOLATILE band assembly)
**Risk:** Medium

Apply the AffordancePipeline principle to context sections. Before each turn, score each VOLATILE section (goals, health, nudges, DMN, imagination, phenomenal, salience) against the operator's utterance using embedding similarity.

**Implementation:**
- Embed operator's last utterance (already computed for tool recruitment)
- Compute cosine similarity against fixed section label embeddings
- Inject only sections above threshold (0.15 — low bar, filters truly irrelevant only)
- Always inject: grounding directive, effort level (these are the treatment variable)

**Evaluation:** 50 real voice conversations. Measure: token savings per turn, false-negative rate (turns where a filtered section would have been useful — determined by whether the model's response references content from that section type).

**Success criterion (G-PC4):** False-negative rate < 5%.

### 5.4 Cycle 3 Experiment Design Integration

**Prerequisite:** GrndComp (5.1) shows positive or interesting results
**Risk:** Requires preregistration amendment

Draft preregistration amendment adding a dismantling comparison:

| Condition | Thread | Compression | Tests |
|---|---|---|---|
| A | Full thread | Age-based (current) | Baseline |
| B | Full thread | GrndComp | Grounding-aware vs age-aware compression |
| C | Full thread | LLMLingua-2 generic | Grounding-aware vs information-theoretic compression |
| D | No thread | N/A | Thread ablation control |

Tests three hypotheses:
1. Does the thread matter at all? (A/B/C vs D)
2. Does grounding-aware compression outperform generic? (B vs C)
3. Does any compression degrade grounding behavior? (A vs B/C)

SCED within-subjects design, BEST analysis, consistent with existing preregistration framework.

### 5.5 Compression Telemetry for Langfuse

**Files:** `agents/hapax_daimonion/conversation_pipeline.py` (requires DEVIATION record)
**Risk:** Low (observability-only, no behavioral change)

Per-turn Langfuse scores:
- `prompt_tokens_pre_compression` — token count before Phase 1 optimizations
- `prompt_tokens_post_compression` — token count after
- `compression_ratio` — pre/post
- `sections_filtered` — count of VOLATILE sections removed by turn-specific selection (5.3)
- `thread_compression_distribution` — count of DUs at each compression tier

**Justification for DEVIATION record:** Adds `hapax_score()` calls only. No model input/output change. Pattern identical to DEVIATION-025 (salience signals).

---

## 6. Decision Gates

| Gate | Phase | Criteria | Action on Failure |
|---|---|---|---|
| **G-PC1** | End of Phase 1 | Compressed prompt assembles; unit tests pass; token count < 1,200 typical | Fix failing items before hardware arrival |
| **G-PC2** | End of Phase 2 | TTFT improvement ≥50ms; directive compliance ≥ baseline; tool recruitment unchanged; KV-cache Q8 no degradation | Revert specific failing optimizations, re-benchmark |
| **G-PC3** | End of Phase 3.1 | GrndComp ≥ age-based on turn_pair_coherence at lower token count | Publish as negative result; keep age-based |
| **G-PC4** | End of Phase 3.3 | Turn-specific context selection false-negative rate < 5% | Raise threshold or abandon |

---

## 7. Schedule

| Item | Phase | Effort | Depends On | Frozen? |
|---|---|---|---|---|
| 3.1 Tool directory stripping | 1 | 2h | — | No |
| 3.2 DMN buffer compression | 1 | 2h | — | No |
| 3.3 Policy block compression | 1 | 2h | — | No |
| 3.4 TOON expansion | 1 | 4h | — | No |
| 3.5 Qdrant retrieval compression | 1 | 4h | 3.4 partial | No |
| 3.6 LLMLingua-2 hardening | 1 | 2h | — | No |
| 3.7 Cross-agent deduplication | 1 | 4h | — | No |
| 4.1 Token budget audit | 2 | 1h | Hardware + Phase 1 | No |
| 4.2 Latency benchmark | 2 | 2h | Hardware + Phase 1 | No |
| 4.3 KV-cache validation | 2 | 1h | Hardware | No |
| 4.4 Directive compliance | 2 | 4h | Hardware + 3.3 | No |
| 4.5 Tool recruitment validation | 2 | 1h | Hardware + 3.1 | No |
| 4.6 Attention analysis | 2 | 2h (opportunistic) | Hardware + ExllamaV2 attention API | No |
| 5.1 GrndComp | 3 | 8h | Stable Hermes 3 | No |
| 5.2 Attention pruning | 3 | 4h | 4.6 data | No |
| 5.3 Turn-specific selection | 3 | 6h | Stable Hermes 3 | No |
| 5.4 Cycle 3 design | 3 | 4h | 5.1 results | DEVIATION |
| 5.5 Compression telemetry | 3 | 2h | — | DEVIATION |

**Phase 1 total:** ~20h (fits in 2-day hardware wait)
**Phase 2 total:** ~11h (interleaved with migration days 1-3)
**Phase 3 total:** ~24h (spread over 1-2 weeks post-migration)

---

## 8. Key Citations

### Prompt Compression
- Li et al. (NAACL 2025) — Prompt Compression for LLMs: A Survey [arXiv:2410.12388]
- Jiang et al. (EMNLP 2023) — LLMLingua [arXiv:2310.05736]
- Pan et al. (ACL 2024) — LLMLingua-2
- Fang et al. (EMNLP Findings 2025) — Information Preservation in Prompt Compression [arXiv:2503.19114]
- Anthropic (Sep 2025) — Effective Context Engineering for AI Agents
- HyCo² (2025) — Beyond Hard and Soft [arXiv:2505.15774]
- KVzip (2025) — 3-4x conversation memory compression

### Attention and Position
- Xiao et al. (ICLR 2024) — Attention sinks / StreamingLLM
- Niu et al. (ACL 2025 Outstanding Paper) — Contextual entrainment heads
- ICLR 2025 — When Attention Sink Emerges
- Liu et al. (TACL 2024) — Lost in the Middle

### Grounding Theory
- Clark & Brennan (1991) — Grounding in communication
- Traum (1994) — Computational grounding acts
- Brennan & Clark (1996) — Conceptual pacts
- Shaikh et al. (NAACL 2024, ACL 2025) — RLHF degrades grounding; Rifts benchmark

### Mechanistic
- Von Oswald et al. (2023) — Mesa-optimization / prompt as program
- Todd et al. (ICLR 2024) — Function vectors
- Zou et al. (2023) — Representation engineering
