# Prompt Compression Phase 2 — A/B Results (Conditions A vs B)

**Date:** 2026-04-12
**Owner:** beta
**Mode:** RESEARCH
**Spec:** `docs/superpowers/specs/2026-04-10-prompt-compression-research-plan-design.md` §4.2
**Implementation:** PR #638 (Phase 1.1 tool directory stripping is feature-flagged via `tool_recruitment_active`; sub-items 1.2–1.7 are unconditional and apply to both conditions)
**Run script:** `scripts/benchmark_prompt_compression_b6.py`
**Raw data:** `~/hapax-state/benchmarks/prompt-compression/phase2-ab-20260412T160219.json`

---

## 1. Scope

The research plan §4.2 defines four latency-benchmark conditions:

| Condition | Prompt | Model | Hardware |
|---|---|---|---|
| A | full (~2,200 tok) | Qwen3.5-9B | current |
| B | compressed (~1,000 tok) | Qwen3.5-9B | current |
| C | full | Hermes 3 70B | future |
| D | compressed | Hermes 3 70B | future |

**This run covers A and B only.** Conditions C and D require the Hermes 3 70B
hardware delivery (B5 in the work-stream split) and stay deferred. Within A/B,
the only Phase 1 optimization that is feature-flagged in the merged code is 1.1
(system prompt tool directory stripping); the other six Phase 1 sub-items are
unconditional and apply to both conditions identically. The A vs B delta
reported here therefore measures the Phase 1.1 effect specifically — the largest
single contribution per the spec (~391 tokens of the ~700 tok/turn total).

A representative slim policy block (`" Mode: focused. Be concise."`) is
appended to both conditions to keep them comparable. No conversation thread,
DMN buffer, phenomenal context, or tool schema injection — those grow the
absolute prompt size for both conditions equally and would dilute the
1.1-specific signal.

## 2. Setup

- **Endpoint:** `http://localhost:5000/v1/chat/completions` (TabbyAPI direct, bypassing the LiteLLM gateway hop)
- **Model:** `Qwen3.5-9B-exl3-5.00bpw` (EXL3 5.0 bpw, single GPU)
- **Trials per condition:** 20 (one per representative voice utterance)
- **Warmups per condition:** 3 (discarded)
- **Decoding:** `temperature=0`, `max_tokens=80`, non-streaming
- **Block order:** all condition A (warmup + measurements) then all condition B. This is the production-relevant case — the system prompt is stable across many turns, so the prefix cache stays warm. Alternating A/B every call would force cache thrashing on each call and is not representative.
- **Utterances:** 20 short voice queries spanning activation, status, action, search, and system categories. Listed in `scripts/benchmark_prompt_compression_b6.py:UTTERANCES`.

## 3. Aggregate results (n=20 per condition)

| Metric | A (full) | B (compressed) | Δ | Δ% |
|---|---:|---:|---:|---:|
| **prompt_tokens median** | 574 | 181 | **−393** | −68.5% |
| prompt_tokens p95 | 577 | 184 | −393 | −68.1% |
| **prompt_time median** | 0.295 s | 0.120 s | **−175 ms** | −59.3% |
| prompt_time p95 | 0.300 s | 0.130 s | −170 ms | −56.7% |
| completion_tokens (all) | 79 | 79 | 0 | — |
| completion_time median | 1.745 s | 1.775 s | +30 ms | +1.7% |
| completion_time p95 | 2.886 s | 1.965 s | −921 ms | −31.9% |
| **total_time median** | 2.040 s | 1.890 s | **−150 ms** | −7.4% |
| **total_time p95** | 3.176 s | 2.095 s | **−1081 ms** | −34.0% |
| wall_time median | 2.052 s | 1.907 s | −145 ms | −7.1% |

The token reduction (−393) matches the spec's ~391-token estimate for Phase 1.1
to within rounding. The prefill-time reduction (−175 ms median) is a clean
linear consequence of the token delta: at the measured Qwen prefill rate of
~1,707 tok/s (averaged across all 40 calls), 393 fewer tokens predict 230 ms of
saved prefill, and the observed 175 ms is in the same order of magnitude (the
gap is consistent with TabbyAPI's prefix-cache behavior partially absorbing the
shared prefix between same-condition calls).

The decode-time figures need a footnote: every response hit the
`max_tokens=80` cap, so completion length is constant and any difference in
`completion_time` is decode-rate variation, not output-length variation. The
condition A `completion_time` p95 outlier (2.89 s vs B's 1.96 s, or
+47%) is the dominant contributor to the 1,081 ms total_time tail benefit. With
constant decode length and identical decoding parameters, this likely reflects
GPU-side scheduling variance during the condition A block — interesting but
not load-bearing for the headline finding.

The headline finding is the **median prefill saving of 175 ms (59%)**, which
is causally tied to the 393-token reduction.

## 4. Per-utterance stability

Per-utterance prefill times are tightly clustered (`A` ∈ {0.29 s, 0.30 s},
`B` ∈ {0.11 s, 0.12 s, 0.13 s}). The Δ per utterance ranges from −160 ms to
−180 ms with no outliers — the effect is uniform across query categories
(activation, status, action, search, system).

| Utterance | A | B | Δ |
|---|---:|---:|---:|
| `hey hapax` | 0.290 s | 0.110 s | −180 ms |
| `you there` | 0.290 s | 0.120 s | −170 ms |
| `hapax good morning` | 0.290 s | 0.130 s | −160 ms |
| `thanks` | 0.290 s | 0.120 s | −170 ms |
| `what time is it` | 0.300 s | 0.120 s | −180 ms |
| `what's on my schedule today` | 0.300 s | 0.130 s | −170 ms |
| `any new emails this morning` | 0.300 s | 0.120 s | −180 ms |
| `what's the weather doing` | 0.300 s | 0.120 s | −180 ms |
| `text emma I'm running late` | 0.300 s | 0.120 s | −180 ms |
| `find my phone and ring it` | 0.300 s | 0.130 s | −170 ms |
| `open the studio app` | 0.290 s | 0.120 s | −170 ms |
| `lock my phone` | 0.290 s | 0.130 s | −160 ms |
| `search my emails for the studio contract` | 0.300 s | 0.130 s | −170 ms |
| `find that note about the new mic preset` | 0.300 s | 0.120 s | −180 ms |
| `what was the last thing I asked you` | 0.290 s | 0.130 s | −160 ms |
| `who emailed me yesterday` | 0.290 s | 0.130 s | −160 ms |
| `what's the system status` | 0.300 s | 0.120 s | −180 ms |
| `check governance health` | 0.300 s | 0.120 s | −180 ms |
| `any nudges I should look at` | 0.290 s | 0.130 s | −160 ms |
| `summarize today's briefing` | 0.290 s | 0.120 s | −170 ms |

## 5. Hermes 3 70B extrapolation

The spec's mutual-reinforcement argument hinges on the 70B's much slower
prefill rate (~50 tok/s estimated, vs the measured ~1,707 tok/s on Qwen3.5-9B).
At 50 tok/s, the same 393-token reduction would translate to a theoretical
prefill saving of:

```
393 tokens / 50 tok/s = 7.86 seconds
```

That figure is 45× the Qwen saving and is the actual reason Phase 1.1 matters
for the migration. On Qwen3.5-9B the 175 ms saving is real but small relative
to the ~2 s end-to-end voice turn; on Hermes 3 70B, an ~8 s saving would
collapse a turn from a "wait for it" feel to something close to current voice
latency. **The Qwen measurement validates that the savings exist; the Hermes
extrapolation is the actual operational payoff.**

This extrapolation assumes:

1. The 50 tok/s estimate from `docs/superpowers/specs/2026-04-10-hermes3-70b-voice-architecture-design.md` survives contact with the actual hardware. To be re-measured during B5 task 1.
2. The compressed prompt does not regress quality on a SFT-only model. To be measured by §4.4 (grounding directive compliance) once the hardware lands.
3. Phase 1.1's static 393-token saving is not absorbed by other prompt growth between now and migration. The risk is low — the conversation pipeline is stable and the only volatile growth path is DMN buffer, which 1.2 already addresses.

## 6. Decision-gate G-PC2 status

Per spec §4.7, G-PC2 has five criteria:

- [x] **Compressed prompt assembles correctly** (G-PC1 was met when PR #638 merged with full unit-test coverage; this run re-verifies that the assembled prompts are valid prompts the model accepts and answers without errors).
- [x] **Latency benchmark shows measurable TTFT improvement** — 175 ms median prefill reduction on the current model; ~7.9 s extrapolated on Hermes 3 70B (criterion threshold ≥50 ms easily met; the spec's threshold was set against the 70B condition and is exceeded by ~150×).
- [ ] **Grounding directive compliance equal or better on compressed format** — not measured here (covered by §4.4, requires hardware).
- [ ] **Tool recruitment unchanged** — not measured here (covered by §4.5, low-cost to add but not blocking).
- [ ] **KV-cache Q8 + compression introduces no quality degradation** — not measured here (covered by §4.3, requires hardware).

**Partial gate verdict:** the latency criterion is met. The remaining three
criteria are hardware-gated or covered by adjacent tasks (4.4, 4.5, 4.3) and
should be addressed when B5 lands.

## 7. Caveats and threats to validity

1. **Phase 1.1 isolation only.** The other six Phase 1 sub-items (DMN compression, policy compression, TOON expansion, Qdrant adaptive limits, LLMLingua-2 hardening, ContextAssembler caching) are unconditional in main and apply to both conditions. The A/B delta here is the 1.1 contribution alone, not the full Phase 1 effect. The spec estimated 1.1 at ~391 tokens of the ~700 tok/turn total — this run's measured 393 tokens matches that allocation exactly.
2. **`max_tokens=80` cap** truncated every response. Decode time variance therefore reflects per-call rate fluctuation, not real output length differences. For headline prefill numbers this does not matter; for the 1,081 ms p95 total tail benefit it weakens the causal story (it is more likely a scheduling-variance artifact than a compression effect).
3. **TTFT measured indirectly.** TabbyAPI's `prompt_time` field reports prefill duration, not the wall-clock interval between request submission and first streamed token. For a non-streaming request these are nearly equivalent; for streaming there would be an additional first-decode-step component (~22 ms at 45 tok/s). The measurement does not account for the streaming path's per-chunk dispatch overhead.
4. **Block order (all A, then all B), not interleaved.** Sequential blocks let the prefix cache warm within each block (production-realistic). Per-utterance results are tightly clustered, so temporal drift over the ~80 s run window is negligible, but a future replication should randomize block order to harden the conclusion.
5. **No system noise control.** The benchmark ran in normal R&D mode with all background hapax services live (compositor, DMN, reverie, etc.). Other GPU workloads on the same device would explain the condition A `completion_time` p95 outlier; a quiescent-system replication would tighten that tail.
6. **Single hardware configuration.** The 175 ms figure is model- and bpw-specific. EXL3 quantization, attention backend, and prefill batch shape all influence the prefill rate, and any of these changing would shift the absolute numbers. Ratios should be more stable than absolutes.
7. **Hermes 3 extrapolation is theoretical.** The 50 tok/s prefill estimate is from the migration design doc and has not been verified against actual layer-split inference on RTX 3090 + RTX 5060 Ti. The 7.86 s figure is a planning input, not a measurement.
8. **Sample size is borderline for stable tail estimates.** n=20 per condition gives roughly ±25 % variance on p95 and ±50 % on p99. The headline median is well-stabilised at this sample size, but any tail-focused conclusions should be re-run with n≥50 before being treated as publication-grade. Surfaced by the 2026-04-12 audit pass.
9. **`temperature=0` is not fully deterministic on EXL3.** Batch dispatch, GPU non-determinism, and ExLlamaV3's optimised kernels can introduce ~1–3 % variation in `completion_time` between identical requests even at zero temperature. This is captured under "rate fluctuation" in caveat 2 but should be named directly: zero temperature suppresses sampling variance, not execution variance. Surfaced by the 2026-04-12 audit pass.
10. **Module import side effects.** `from agents.hapax_daimonion.persona import system_prompt` triggers the `logos.voice` import chain (which configures loggers and reaches into shared infrastructure on first import). The import cost is paid once per script invocation and does not affect the timed measurements, but it means the script cannot be run in a fully isolated environment without the council venv. Surfaced by the 2026-04-12 audit pass.

## 8. Recommended next steps

1. **Add §4.5 (tool recruitment validation)** to the same harness — 20 utterances through `ToolRecruitmentGate.recruit()` with both prompt variants, assert recruited tool sets are identical. Cheap, no hardware dependency, would close another G-PC2 criterion.
2. **Hold §4.3 and §4.4** until B5 hardware arrives. They cannot be meaningfully run on the current model.
3. **Re-run this benchmark** as the first measurement on Hermes 3 70B after B5 task 1 (inference validation) to capture conditions C and D.
4. **Add streaming TTFT measurement** as a second mode in the script (use `stream=true` and time the gap between request send and first chunk arrival). Optional precision improvement; not required for the partial G-PC2 verdict above.
5. **Do not abandon Phase 1.1** based on the small Qwen-side saving. The whole point of compression is the migration payoff; Qwen is the safety net.

## 9. Reproduction

```sh
cd ~/projects/hapax-council--beta
uv run python scripts/benchmark_prompt_compression_b6.py --trials 20 --warmup 3
# results land in ~/hapax-state/benchmarks/prompt-compression/
```

The script depends only on `httpx` and `agents.hapax_daimonion.persona`
(both already in the project venv). It hits TabbyAPI at the default port and
fails fast if the daemon is unreachable. No credentials required.
