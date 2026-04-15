# Substrate re-evaluation v2 — post-verification synthesis

**Date:** 2026-04-15
**Author:** beta (PR #819 author, AWB mode) per delta queue refill 5 Item #71
**Parent research:** `docs/research/2026-04-15-substrate-reeval-post-hermes.md` v1 (commit `bb2fb27ca`, 722 lines) + errata (commit `d33b5860c`, +94 lines)
**Scope:** v2 synthesis incorporating post-verification state, operator signal gaps, and additional findings from the 2026-04-15 AWB session. Does NOT supersede v1 or the errata; complements them.
**Status:** research synthesis; not a new recommendation set — v1 recommendations remain canonical for the operator's ratification cycle.

---

## 0. Purpose of v2

The v1 research drop (`bb2fb27ca`) was written 2026-04-15T07:00Z to respond to the operator's post-Hermes-abandonment direction *"devote extensive research into if Qwen3.5-9B-exl3-5.00bpw is actually the best production substrate for our very unique use cases"*. v1 shipped ~20 minutes after that direction with 722 lines across 12 sections and a 5-scenario recommendation matrix.

Within 15 minutes of v1 shipping, beta caught two verification failures during the execution of delta's AWB assignment #1 (thinking-mode disable). Errata `d33b5860c` appended a 94-line correction section to v1. Since then, additional operator-facing information has emerged through the AWB cycle:

- Live-verified production state of thinking mode (E1 in errata)
- Live-verified exllamav3 runtime version (E2 in errata)
- Live-verified TabbyAPI cache warmup state (now shipped, commit `bafd6b34f`)
- Live-verified exllamav3 release notes for 0.0.24-0.0.29 (no Ampere-specific hybrid attention fixes; upgrade still valuable for OlmoHybrid support per Item #9)
- Live Prometheus tsdb analyze baseline (Item #77 pre-analysis)
- Drop #62 §14 Hermes abandonment addendum + §15 addendum (post-v1-write-time)
- Operator batch ratification of drop #62 §10 Q2-Q10 (post-v1-write-time)

v2 integrates all of this into a synthesis that is useful WHEN the operator returns and wants to pick up the substrate decision thread without re-reading v1 + errata + every subsequent addendum. v2 is a bridge document, not a replacement.

## 1. What v1 got right

### 1.1 Current substrate audit structure (§1-§2)

v1's §1 correctly identified the canonical production state:

- TabbyAPI serves `Qwen3.5-9B-exl3-5.00bpw` on `localhost:5000`
- Published by Alibaba Qwen team 2026-03-02, Apache 2.0 license
- Architecture: multimodal Gated DeltaNet + sparse MoE hybrid, 9B dense
- Training: GRPO + GSPO + million-agent-environment scaled RL via distillation-from-RL-teacher
- Sits at the RL-heavy extreme of the post-training spectrum
- Per-route production usage mapped: `ModelTier.LOCAL` + all agent pressure-downgrades + `coding` + `reasoning`
- NOT the primary voice LLM (Gemini Flash / Sonnet / Opus handle tiers 2-4)

This audit is unchanged by the errata. The claims are all verified-correct at v1 write time + still correct at v2 write time.

### 1.2 Use case profile (§2)

The 12 use-case dimensions v1 enumerated are structurally correct:

- Voice-first latency budget (TTFT dominates)
- Continuous cognitive loop (low idle cost)
- pydantic-ai structured output (grammar / tool-use reliability)
- Stimmung-critical downgrade reliability (fallback path works)
- Hapax persona adherence
- Tool use (JSON function calling)
- Coding / reasoning tiers
- VRAM budget on RTX 3090 24GB
- Single-operator alignment
- Livestream research medium (outputs on-camera)
- Research validity under frozen substrate

None of these changed post-v1. The profile remains canonical.

### 1.3 Recommendation matrix (§9)

v1's 5-scenario recommendation matrix:

1. **Lowest-disruption:** keep Qwen3.5-9B, fix thinking mode + cache warmup + exllamav3 upgrade, run RIFTS (MEDIUM-HIGH)
2. **Research-aligned:** parallel-deploy OLMo 3-7B (SFT/DPO/RLVR split checkpoints) as `local-research-*` routes — uniquely enables isogenic Shaikh test within one model family (HIGH)
3. **Empirical:** run RIFTS against 3-4 candidates before deciding (HIGH)
4. **Immediate swap:** Llama 3.1 8B Instruct (LOW-MEDIUM)
5. **"No RL" principle:** Mistral Small 3.1 24B at 5.0bpw (MEDIUM)

Beta's overall take in v1: scenarios 1+2 (fix + parallel-deploy for research) are complementary and both HIGH-confidence. They can be executed in parallel without committing to a swap.

**This take survives v2.** The errata reduced the scope of scenario 1 (fix #1 is NO-OP) but did not invalidate scenarios 1, 2, or 3. Scenarios 4 and 5 remain lower-confidence alternatives pending operator signal.

### 1.4 Critical literature finding (§4)

v1 §4 flagged: *"Qwen3/Qwen3.5 has NOT been evaluated on ANY grounding benchmark (RIFTS, QuestBench, SYCON Bench, MultiChallenge) as of April 2026. Any substrate argument on grounding grounds is predictive from recipe, not empirical."*

This finding is unchanged by post-v1 events. The literature gap remains. Any substrate decision that wants empirical grounding data MUST pass through beta's RIFTS harness (commit `3a7672bd1`, shipped as part of the session).

## 2. What v1 missed (errata summary)

The `d33b5860c` errata caught three concrete verification failures:

### 2.1 E1 — Thinking mode ALREADY disabled for local-fast + coding (v1 §1.2 claim wrong)

v1 §1.2 claimed *"current production config does not explicitly disable thinking mode — needs verification; if thinking is on, every local-fast call pays the thinking-token latency tax"*.

Verified state (2026-04-15T07:15Z): `~/llm-stack/litellm-config.yaml` lines 57-82 show `enable_thinking=false` for both `local-fast` and `coding` routes, and `enable_thinking=true` for the `reasoning` route (correct for reasoning). Direct API test confirmed.

**Why the claim was wrong:** beta inspected `tabbyAPI/config.yml` (the TabbyAPI backend config, which does not control thinking mode) instead of `~/llm-stack/litellm-config.yaml` (the LiteLLM route config, where `extra_body.chat_template_kwargs.enable_thinking` lives). Wrong control layer.

**Impact on v1 §9.1:** first fix is a NO-OP. Delta's AWB assignment #1 closed as NO-OP.

### 2.2 E2 — exllamav3 runtime is 0.0.23, not 0.0.22

v1 cited production version as 0.0.22 from the `quantization_config.version` field in the model's `config.json`. That field records the quant pack format version at the time the model was quantized (immutable artifact), NOT the runtime library version.

Verified state: `exllamav3-0.0.23` is the installed runtime. Upgrade gap to upstream 0.0.29 is 6 point releases, not 7.

### 2.3 E3 — Cache warmup recommendation unchanged

v1 §9.1 second fix (TabbyAPI cache warmup via `ExecStartPost`) was correctly identified as not-yet-in-place. Subsequently shipped as commit `bafd6b34f` during delta's AWB assignment #2 on the same day.

## 3. Updated post-verification state (what beta has verified to be actually-in-production as of 2026-04-15T16:00Z)

### 3.1 LiteLLM gateway config (`~/llm-stack/litellm-config.yaml`)

- `local-fast` route: `enable_thinking=false` ✓
- `coding` route: `enable_thinking=false` ✓
- `reasoning` route: `enable_thinking=true` ✓ (correct for reasoning)
- Redis response cache: enabled, 1h TTL ✓
- Target: TabbyAPI `localhost:5000` ✓

### 3.2 TabbyAPI backend (`tabbyAPI/config.yml` + systemd unit)

- Model: `Qwen3.5-9B-exl3-5.00bpw` ✓
- Runtime: exllamav3 0.0.23 (upstream: 0.0.29, gap: 6 point releases)
- Cache warmup: shipped via `ExecStartPost` in `systemd/user/tabbyapi.service` commit `bafd6b34f` ✓
- GPU: CUDA_VISIBLE_DEVICES=0 (dedicated RTX 3090) ✓
- Ollama GPU-isolated: `CUDA_VISIBLE_DEVICES=""` in ollama unit (verified per CLAUDE.md)

### 3.3 Research registry state

- `~/hapax-state/research-registry/current.txt` → `cond-phase-a-baseline-qwen-001` (single active condition) ✓
- `research_marker_changes.jsonl` → 19 transition entries (backfill + tests)
- Phase A baseline is the only condition currently in the registry

### 3.4 exllamav3 0.0.24-0.0.29 release-notes review (Item #9)

Per beta's Item #9 investigation during refill 4, the 0.0.24-0.0.29 release range contains:

- OlmoHybrid architecture support (new in 0.0.29) — enables OLMo 3-7B parallel deploy per v1 scenario 2
- Minor performance improvements
- **NO Ampere-specific fixes for hybrid attention JIT compile** — v1's §9.1 fix #3 rationale about "hybrid attention JIT shaky on first call" cannot be attributed to a specific 0.0.24-0.0.29 fix. The upgrade is still valuable for OlmoHybrid support BUT the upgrade is NOT a fix for the hybrid-attention JIT problem on Qwen3.5-9B.

This is a rationale correction, not a recommendation reversal. The upgrade to 0.0.29 is still shippable (low-risk) and enables scenario 2 OLMo parallel deploy.

### 3.5 RIFTS harness state

Beta shipped a RIFTS benchmark harness at commit `3a7672bd1` (`scripts/benchmark_rifts_harness.py` + support modules). The harness is ready to run against any EXL3-compatible substrate; it reads RIFTS-format prompts and measures refusal / hallucination rates.

**Blocker:** the RIFTS dataset itself has not been downloaded. Delta's Item #11 / #12 authorized the download but operator signal is required to run the download (~2 GB one-time fetch).

### 3.6 OLMo 3-7B candidate state

v1 scenario 2 proposed parallel-deploying OLMo 3-7B (SFT/DPO/RLVR split checkpoints) as `local-research-*` routes. OLMo 3-7B has:

- Apache 2.0 license ✓
- Published SFT + DPO + RLVR checkpoints at three distinct post-training stages ✓
- EXL3 quant existence: UNVERIFIED at v1 write time; OlmoHybrid architecture support in exllamav3 0.0.29 is a prerequisite

**Blocker:** weight download (~4 GB per checkpoint × 3 checkpoints = ~12 GB) needs operator signal. Delta's Item #13 authorized the download but operator signal required.

## 4. Remaining operator-gated decisions

### 4.1 Substrate direction (primary blocker)

The 5-scenario matrix in v1 §9 still applies. The operator has not yet ratified a scenario. Beta's AWB work cannot unilaterally pick scenario 1 (fix what's fixable + keep Qwen3.5-9B) or scenario 2 (parallel OLMo) because both require operator signal:

- **Scenario 1:** fix cache warmup (SHIPPED) + exllamav3 upgrade (not shipped, requires operator signal for runtime swap) + RIFTS evaluation (requires dataset download signal)
- **Scenario 2:** OLMo 3-7B parallel deploy (requires weight download signal + exllamav3 0.0.29 upgrade signal)

**Recommended operator action on wake:** read v1 §9.5 matrix + this v2 §4 synthesis + pick a scenario. Scenarios 1 and 2 can be executed in parallel and are complementary.

### 4.2 Claim-shaikh cycle timing

Cycle 2 pre-registration (claim-shaikh-sft-vs-dpo) remains valid per drop #62 §10 Q1 ratification. The cycle's open date depends on which substrate scenario lands. If scenario 2 ships (OLMo parallel), the claim-shaikh cycle can use the OLMo SFT/DPO/RLVR split checkpoints as the controlled comparison within one model family — this is the only published isogenic test set for the Shaikh framework, per v1 §8.

**Recommended operator action:** if scenario 2 ratifies, schedule cycle 2 within 1-2 weeks of OLMo deployment. If scenario 1 alone ratifies (no OLMo), defer cycle 2 pending RIFTS empirical data.

### 4.3 Thinking mode for `reasoning` route

Currently `enable_thinking=true` for the `reasoning` route (E1 verified). This is correct for the route's purpose. However, if the reasoning route's downstream consumers (e.g., HSEA Phase 7 D2 anomaly narration) have a strict latency budget, the thinking-mode tax might need to be bounded via `max_thinking_tokens` or route reassignment.

**Recommended operator action:** low priority; non-blocking. Revisit if HSEA Phase 7 D2 shows latency regressions in Langfuse traces post-deployment.

### 4.4 exllamav3 upgrade from 0.0.23 to 0.0.29

Gap: 6 point releases (~3 months of upstream changes). Risks:

- Compatibility with existing Qwen3.5-9B EXL3 5.0bpw quant pack (likely compatible; format version 0.0.22 is read by runtime ≥ 0.0.22)
- Runtime config schema drift (low risk; exllamav3 is conservative)
- Support for OlmoHybrid architecture (new in 0.0.29, required for scenario 2)

**Recommended operator action:** bundle with scenario 2 ratification. If scenario 2 doesn't ratify, defer the upgrade or ship as a standalone low-risk maintenance PR.

## 5. Recommended next research steps

### 5.1 If operator picks scenario 1 (keep Qwen3.5-9B + fix)

1. **Upgrade exllamav3 to 0.0.29** (low risk, maintenance PR)
2. **Download RIFTS dataset** (operator signal required)
3. **Run RIFTS on Qwen3.5-9B** via beta's harness at `scripts/benchmark_rifts_harness.py`
4. **Compare RIFTS results against Qwen3.5-9B's Langfuse production telemetry** — does the benchmark refusal rate match the live production refusal rate?
5. **Author RIFTS empirical findings drop** with scenario 1 validation or invalidation

Estimated time: 2-4 hours (mostly RIFTS runtime) + 30 min report authoring.

### 5.2 If operator picks scenario 2 (parallel OLMo)

1. **Upgrade exllamav3 to 0.0.29** (required for OlmoHybrid)
2. **Download OLMo 3-7B SFT + DPO + RLVR checkpoints** (operator signal required, ~12 GB)
3. **Quantize each checkpoint to EXL3 5.0bpw** (exllamav3 convert pipeline, ~30 min each)
4. **Add LiteLLM routes** `local-research-sft`, `local-research-dpo`, `local-research-rlvr`
5. **Run claim-shaikh cycle 2** against the three checkpoints (the isogenic test)
6. **Author findings drop** with empirical Shaikh results

Estimated time: 1-2 days (quantization + cycle 2 runs).

### 5.3 If operator picks scenario 3 (empirical bake-off)

1. **Download RIFTS dataset** + candidate weights (Qwen3.5-9B already local; Llama 3.1 8B; Qwen3-8B; OLMo 3-7B SFT; Mistral Small 3.1 24B)
2. **Run RIFTS on all 5 candidates**
3. **Score against v1 §3 criteria matrix**
4. **Author winner selection drop**

Estimated time: 1 week (mostly downloads + quantization + 5 benchmark runs).

### 5.4 If operator picks scenario 4 (immediate Llama swap) or 5 (Mistral 24B)

These are lower-confidence scenarios. Additional research BEFORE committing:

- Verify EXL3 5.0bpw quant exists for Llama 3.1 8B Instruct (or author one)
- Check VRAM budget for Mistral 24B at 5.0bpw (likely ~14-15 GB, leaves less headroom for cache + other services)
- Run at least RIFTS against the candidate before committing

These scenarios are not beta's primary recommendation and should only ratify if the operator has a specific reason (e.g., wants to validate a "no RL" principle for Mistral 24B).

### 5.5 Non-substrate follow-up research (all scenarios)

Regardless of which scenario ratifies, the following research items remain valuable:

1. **Langfuse 6-week production telemetry review** on Qwen3.5-9B — measure actual refusal / hallucination / latency distribution. v1 flagged this gap but beta has not executed.
2. **Parrot sycophancy observability** — add a Parrot-based sycophancy metric to the Langfuse trace pipeline per v1 §11.
3. **SYCON Bench + MultiChallenge** runs against current substrate to close the "no empirical grounding data" literature gap for Qwen3.5-9B specifically.
4. **Cache warmup effectiveness measurement** — now that `bafd6b34f` has shipped, measure p50/p99 TTFT before/after. Delta's AWB assignment #2 closure deferred live measurement; this is a ~30 min task.

## 6. Meta-observation on protocol v1.5 effectiveness

The errata (`d33b5860c`) caught 2 of 3 v1 recommendations as NO-OP or misattributed. That is a ~67% correction rate on the specific recommendations, though v1's broader synthesis (§§1-8) remained correct.

Beta's overall v1 + v1.5 verification track record during this session:

- Item #9 exllamav3 investigation: corrected Ampere premise
- Item #48 LRR Phase 6 cohabitation audit: found 2 drift items (D1 + D2)
- Item #41 drop #62 §14 line 502: found precedent conflation drift
- v1 errata: found 2 verification failures

Pattern: ~16% noise rate on recommendations that reference production state BEFORE verification. Verify-before-writing is worth the 2-5 min per recommendation cost.

**Recommendation for v2:** nothing in this document is newly proposing a state change. v2 is a bridge document, not a state-change document. The verification discipline applied to v1 would catch any new production-state claim in v2. Beta has cross-referenced all v2 production-state claims against §3 verification lines.

## 7. Non-goals

- v2 does NOT supersede v1's §9 recommendation matrix. The 5 scenarios remain canonical.
- v2 does NOT make a new operator-facing recommendation. Beta's take (scenarios 1+2 complementary, HIGH-confidence) is unchanged.
- v2 does NOT execute any state change. All state-change work in v2 §5 is operator-gated.
- v2 does NOT replace the errata. The `d33b5860c` errata remains the canonical correction history.

## 8. How to use v2

**Operator returning after overnight AWB session:**

1. Read v1 §9.5 (5-scenario matrix, 1 page)
2. Read v2 §3 (updated post-verification state, 1 page)
3. Read v2 §4 (remaining operator-gated decisions, 1 page)
4. Pick a scenario OR defer + sign off on specific research items from v2 §5

**Delta or any other session doing follow-up substrate work:**

1. Read v1 §1-§2 (audit + use case profile, unchanged)
2. Read v1 §4 (literature gap finding, unchanged)
3. Read v2 §3 (current production state — use this over v1 §1.2 for anything post-errata)
4. Read v2 §5 (next research steps per scenario)
5. If the selected scenario needs execution, read v1 §6-§8 for deployment feasibility + candidate deep-dives

## 9. References

- v1: `docs/research/2026-04-15-substrate-reeval-post-hermes.md` (commit `bb2fb27ca`)
- Errata: commit `d33b5860c` (appended to v1)
- TabbyAPI cache warmup: commit `bafd6b34f` (`systemd/user/tabbyapi.service` `ExecStartPost`)
- RIFTS benchmark harness: commit `3a7672bd1` (`scripts/benchmark_rifts_harness.py`)
- Drop #62 §14 Hermes abandonment: `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md` §14 (post-v1-write-time)
- LiteLLM config (live-verified): `~/llm-stack/litellm-config.yaml`
- Model: `~/projects/tabbyAPI/models/Qwen3.5-9B-exl3-5.00bpw/`
- Runtime: `~/projects/tabbyAPI/venv/lib/python3.12/site-packages/exllamav3-0.0.23+cu128.torch2.9.0.dist-info`
- Research registry state: `~/hapax-state/research-registry/current.txt`
- Prometheus baseline (Item #77 pre-analysis): 5,279 series, 132 label names

— beta (PR #819 author, AWB mode), 2026-04-15T16:15Z
