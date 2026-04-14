# Hermes-3-70B VRAM sizing — pre-flight for LRR Phase 5

**Date:** 2026-04-14
**Author:** delta (beta role)
**Scope:** Pre-flight VRAM / tensor-parallel feasibility for the
`NousResearch/Hermes-3-Llama-3.1-70B-bf16` weights alpha staged
via `hf download` to `~/hapax-state/quant-staging/`. Alpha's
retirement handoff (PR #800) flags LRR Phase 5 as hardware-gated
on "Hermes 3 classifier fallback"; this drop asks whether the
current rig can actually host Hermes 3 70B at any quant level,
and at what tradeoffs.
**Register:** scientific, neutral
**Status:** investigation only — no code change. Math + quant
table for alpha's Phase 5 integration planning

## Headline

**Four findings.**

1. **Hermes-3-Llama-3.1-70B bf16 is ~141 GB on disk** (30
   safetensors shards × ~4.7 GB, confirmed by live
   `ls -la`). Not loadable on this rig at any precision
   higher than Q8. Quantization is mandatory.
2. **Combined rig VRAM is ~40 GB** (RTX 5060 Ti 16 GB +
   RTX 3090 24 GB). After current residents (compositor
   3.0 GB + hapax-imagination 0.3 GB + studio_person_detector
   0.3 GB on GPU 0; TabbyAPI Qwen 3.5 9B 5.8 GB + daimonion
   3.4 GB on GPU 1), **free space is ~11.8 GB on GPU 0 and
   ~14.9 GB on GPU 1** — 26.7 GB combined free right now.
3. **Only Q2_K fits on a single 24 GB GPU** for a 70 B Llama
   architecture (~26 GB weight + minimal KV cache). Everything
   larger requires tensor-parallel (TP2) split across both
   GPUs, which **monopolizes the 5060 Ti** and blocks
   compositor + imagination use of that device — the
   sprint-5 delta audit's durability fix for F1/F6 becomes
   irrelevant because GPU 0 becomes inference-owned.
4. **The existing TabbyAPI + daimonion residents on the 3090
   consume ~9.1 GB**, leaving ~15.5 GB free. Loading Hermes
   3 at **Q2_K (~26 GB) would require unloading Qwen 3.5
   first** — the two models cannot both live on the 3090
   simultaneously. If TabbyAPI is intended to host Hermes
   3 as its primary model and drop Qwen, that's a routing
   change in LiteLLM's config; if both are meant to coexist,
   the rig cannot do that.

**Net implication.** The Hermes-3-70B model as downloaded
will NOT drop into the existing dual-GPU partition without
significant trade-offs. Alpha's Phase 5 plan needs to pick
one of four paths (§ 4 below), and each of them changes
something the current rig depends on. **This is blocking
information for Phase 5 kick-off.**

## 1. Current VRAM census

Captured 2026-04-14T15:46 UTC:

```text
$ nvidia-smi --query-gpu=index,name,memory.total,memory.free --format=csv
index  name                        memory.total [MiB]  memory.free [MiB]
0      NVIDIA GeForce RTX 5060 Ti  16 311              11 804
1      NVIDIA GeForce RTX 3090     24 576              14 944
```

By compute process:

| PID | process | GPU | VRAM used |
|---|---|---|---|
| 3394171 (new) | studio-compositor | 0 (5060 Ti) | ~3.0 GB |
| 3417146 | hapax-imagination | 0 (5060 Ti) | ~0.3 GB |
| n/a | studio_person_detector | 0 (5060 Ti) | ~0.3 GB |
| 1509 | tabbyAPI (Qwen 3.5 9B EXL3 5.0bpw) | 1 (3090) | 5.8 GB |
| 3026071 | hapax-daimonion | 1 (3090) | 3.4 GB |

Combined **used: ~12.8 GB**, **free: ~26.7 GB** across both
GPUs. The split is ~3.6 GB used / ~11.8 GB free on GPU 0 and
~9.1 GB used / ~14.9 GB free on GPU 1.

## 2. Hermes-3-Llama-3.1-70B weight size at common quants

Llama 70B architecture (80 layers × ~870 M params/layer + embeddings):

| quant | bits/param | approx weight size | fits 24 GB? | fits 40 GB combined? |
|---|---|---|---|---|
| bf16 / fp16 | 16 | **141 GB** (confirmed from download shards) | no | no |
| Q8_0 | 8.5 | ~74 GB | no | no |
| Q6_K | 6.6 | ~57 GB | no | no |
| Q5_K_M | 5.7 | ~50 GB | no | no |
| Q4_K_M | 4.8 | ~42 GB | no | **no** (barely over) |
| Q4_K_S | 4.5 | ~38 GB | no | **yes** (2 GB margin, no KV cache headroom) |
| Q3_K_L | 3.9 | ~33 GB | no | yes (7 GB margin) |
| Q3_K_M | 3.7 | ~31 GB | no | yes (9 GB margin) |
| Q3_K_S | 3.5 | ~28 GB | no | yes (12 GB margin) |
| **Q2_K** | 3.2 | **~26 GB** | **yes (barely, 3090 only)** | yes (14 GB margin) |
| Q2_K_S | 2.6 | ~22 GB | **yes (3090)** | yes (18 GB margin) |

Sizes are approximate; exact figures depend on which
quantization mix and whether it's GGUF, EXL2, or AWQ format.
TabbyAPI's current Qwen 3.5 model uses EXL3 at 5.0bpw so
alpha's quant tool of choice is likely exllamav2/v3 — EXL2/3
sizes are roughly equivalent to GGUF Q at the same bit rate.

**KV cache overhead not included in the above.** KV cache
for Llama 70B with a 4k context at fp16 is ~2.5 GB; at 16k
context, ~10 GB. Most quant + context combinations eat
meaningfully into the available-after-weight budget.

## 3. Hypothesis tests

### H1 — "Qwen 3.5 9B and Hermes 3 70B coexist on the 3090"

**Refuted.** Qwen 3.5 9B at EXL3 5.0bpw is 5.8 GB. Hermes
3 70B at any size > Q2_K_S (~22 GB) + 2.6 GB KV cache pushes
the total over 24 GB. Even Q2_K is tight: 22 GB + 2.6 GB =
24.6 GB, over the 3090's limit. **They cannot coexist.**

### H2 — "Hermes 3 fits on the 5060 Ti alone at any useful quant"

**Refuted.** 16 GB total on the 5060 Ti minus ~3.6 GB for
compositor + imagination + person detector leaves ~12.4 GB
for weights + KV cache. Even Q2_K_S (~22 GB) is far too
large. The 5060 Ti cannot host a 70 B model at all.

### H3 — "TP2 across both GPUs at Q3_K_M (~31 GB) works and
leaves compositor headroom"

**Partially supported.** 31 GB of weights + 4 GB KV cache +
~10 GB overhead = 45 GB needed, vs 40 GB available. Close,
but 45 > 40. Q3_K_S at 28 GB works: 28 + 4 + 4 overhead ≈
36 GB. But the compositor's 3.0 GB on GPU 0 + imagination's
0.3 GB = 3.3 GB of co-resident load on the 5060 Ti side
has to be evicted to make room. **The compositor can't run
concurrently with Hermes 3 on the 5060 Ti.** That's the
trade.

### H4 — "CPU inference is viable for a classifier fallback"

**Supported, with caveats.** Llama.cpp can run 70B Q4_K_M
on CPU-only at ~1-3 tokens/sec on a 16-core Ryzen. That's
too slow for real-time classification (sub-second decisions)
but works for **batch overnight experiments**. If alpha's
Phase 5 use of Hermes 3 is batch-mode research evaluation
rather than live chat classification, CPU inference is
feasible and doesn't touch the dual-GPU partition at all.

### H5 — "Alpha intends a CPU or offloaded path already, given the quant-staging directory name"

**Unverified.** The download target
`~/hapax-state/quant-staging/Hermes-3-Llama-3.1-70B-bf16/`
contains the word `quant-staging`, implying the weights are
being staged for an offline quantization pass — not to be
run live from the bf16 files. Standard workflow would be:
bf16 download → quantize with llama.cpp `llama-quantize` or
exllamav3 `convert.py` → output GGUF / EXL3 to a "models"
directory → load via TabbyAPI / llama.cpp server. The
quantization tool and target bit rate are not obvious from
the download directory alone.

## 4. Four viable paths for alpha

Ordered by preservation of current behavior:

### Path A — "Quant to Q2_K on 3090, replace Qwen 3.5"

1. Quantize Hermes 3 bf16 → Hermes 3 Q2_K (GGUF or EXL3 ~3 bpw)
2. Update TabbyAPI config to load Hermes 3 Q2_K as the
   primary model (dropping Qwen 3.5)
3. Update LiteLLM routes so `local-fast` / `coding` /
   `reasoning` aliases point at Hermes 3

**Preserves:** dual-GPU partition, compositor on 5060 Ti,
daimonion access to the 3090 for whisper STT.
**Breaks:** any agent that routes to Qwen 3.5 specifically.
LiteLLM cache entries with Qwen responses become stale.
**Quality trade:** Q2_K is a noticeable quant hit for a
large model — 70 B at Q2_K is roughly equivalent in
quality to ~30 B at Q4_K. Acceptable for a "classifier
fallback" use case (Phase 5's stated purpose) but worse than
Qwen 3.5 9B for general code/reasoning tasks.

### Path B — "TP2 across both GPUs at Q3_K_S, compositor evicted"

1. Quantize Hermes 3 bf16 → Hermes 3 Q3_K_S (~28 GB)
2. TabbyAPI config: tensor-parallel size 2, span both GPUs
3. Move compositor + imagination off GPU 0 — but **there's
   nowhere else to put them** (the only other GPU is the
   3090, which is now shared with Hermes 3 residency).

**Preserves:** higher quant quality (Q3_K_S > Q2_K).
**Breaks:** the entire visual partition. Compositor would
have to fall back to CPU compositing (cairocompositor
instead of cudacompositor, per pipeline.py:41). That kills
the effect graph's GPU shader path and is a much bigger
regression than a quant drop.

### Path C — "CPU inference via llama.cpp for batch research"

1. Quantize Hermes 3 bf16 → Q4_K_M or Q5_K_M (~42-50 GB)
2. Run llama-cpp-server or llama.cpp binary on the CPU
   only, with `-ngl 0` (no GPU offload)
3. Point the LRR Phase 9 classifier's Tier 3 escalation
   path at the CPU endpoint

**Preserves:** both dual-GPU partition and full precision.
**Breaks:** real-time response. Classification latency
jumps from ~50 ms (local LLM hot path) to 1-5 seconds
per query. Not acceptable for live chat classification
during a stream; fine for overnight research ingestion.

### Path D — "Don't ship Hermes 3 70B, use a smaller model"

1. Drop Hermes 3 70B in favor of **Hermes 3 8B** or
   **Hermes 3 3B** (same family, same prompt format, far
   smaller)
2. 8B at Q4_K_M is ~5 GB — drops into the existing Qwen 3.5
   9B slot on the 3090 with minimal disruption
3. Quality of a 3B/8B classifier is lower than a 70B but
   matches the expected precision of a "fast classifier
   fallback" — the kind of decision that's meant to be
   cheap

**Preserves:** everything.
**Breaks:** the "70B classifier" ambition. Phase 5 might
need a design update.

## 5. Recommended action

Delta's recommendation, in priority order:

1. **Confirm with the operator** which path Phase 5 intends
   before alpha's next session starts the integration. The
   quant-staging directory name suggests path A or B, but
   the trade-offs differ sharply.
2. **If path A**, pre-stage the quantization pass now — it
   takes hours for a 70B bf16 → Q2_K conversion on this
   rig. Running it before alpha's next session avoids a
   sprint-long idle wait.
3. **If path C** (CPU batch), test it end-to-end with
   llama-cpp-server on a smaller model first to validate
   the integration path. Hermes 3 8B would work as the
   validation target.
4. **If path D**, redirect the download — delete the 70B
   bf16 shards (saves 141 GB) and pull Hermes 3 8B bf16 (~
   16 GB) instead. Much faster quantization, much faster
   test iteration.

Delta has **no visibility** into which path alpha or the
operator has committed to. This drop is pre-flight data so
that whichever path is picked is an informed choice, not a
surprise at integration time.

## 6. References

- Retirement handoff: `docs/superpowers/handoff/2026-04-14-
  alpha-continuation-retirement.md` — Phase 5 gated on
  "Hermes 3 classifier fallback"
- Download directory:
  `~/hapax-state/quant-staging/Hermes-3-Llama-3.1-70B-bf16/`
  (30 safetensors shards, ~141 GB total)
- `nvidia-smi --query-gpu=...` at 2026-04-14T15:46 UTC —
  current VRAM census
- `nvidia-smi --query-compute-apps=...` same time —
  per-process VRAM
- Llama 70B quant size table sourced from public
  llama.cpp quantization reports; exact numbers vary by
  quant mix and metadata overhead
- Workspace CLAUDE.md § Host services — TabbyAPI serves
  Qwen 3.5 9B EXL3 5.0bpw at ~5.8 GB
