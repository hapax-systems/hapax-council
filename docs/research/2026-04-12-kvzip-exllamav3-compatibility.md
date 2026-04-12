# KVzip and ExLlamaV2/V3 Compatibility

**Date:** 2026-04-12
**Status:** Research note
**Session:** beta
**Context:** B7 from 2026-04-12 work-stream split; input to prompt compression Phase 2 benchmark plan (`docs/superpowers/specs/2026-04-10-prompt-compression-research-plan-design.md` §4.3).

---

## 1. Question

Can KVzip (Kim et al., NeurIPS 2025) be used with the TabbyAPI / ExLlamaV2 / ExLlamaV3 inference stack that serves Hapax voice, as specified for the Hermes 3 70B migration?

## 2. KVzip summary

KVzip is a query-agnostic KV cache compression method. It quantifies the importance of each cached K-V pair by measuring how well the underlying LLM can reconstruct the original context from that pair, then evicts low-importance pairs. Reported results on Qwen2.5, Gemma3, and Llama 3.1 at context lengths up to 170K tokens: 3–4× cache memory reduction and roughly 2× decoding latency improvement with negligible task-quality loss (QA, retrieval, reasoning, code comprehension) [arXiv:2505.23416](https://arxiv.org/abs/2505.23416).

Two operating modes are documented:

- **Context-dependent:** importance is scored at prefill time, then the cache is pruned.
- **Context-independent:** per-head importance scores are precomputed, allowing zero runtime overhead.

Mechanism class: **eviction** (remove pairs). This is orthogonal to **quantization** (reduce bits per pair).

## 3. Implementation surface

KVzip's reference implementation lives at [snu-mllab/KVzip](https://github.com/snu-mllab/KVzip). Stack:

- HuggingFace Transformers as the model host
- Flash-Attention 2.7.4+, CUDA 12.1, Python 3.10
- Per-model attention monkey-patches in `attention/attn.py`
- Custom CUDA kernels for non-uniform per-head budget allocation, adapted from AdaKV

It is explicitly not a drop-in cache class. It modifies attention forward passes and depends on kernels that assume the HF Transformers attention layout. The authors note that Gemma3, whose static KV cache design has no matching optimized kernel, does not realize the full speedup.

NVIDIA [`kvpress`](https://github.com/NVIDIA/kvpress) adds KVzip as one "press" among several compression methods. `kvpress` is likewise HF Transformers-only and integrates with the transformers `QuantizedCache` class; no path is documented for GPTQ, AWQ, EXL2, EXL3, or any non-transformers backend.

## 4. ExLlamaV2 / V3 cache surface

ExLlamaV2 and V3 (`turboderp-org/exllamav2`, `turboderp-org/exllamav3`) implement their own CUDA attention kernels and expose KV cache as a fixed set of C++-backed classes — `ExLlamaV2Cache` (FP16), `ExLlamaV2Cache_Q4`, `ExLlamaV2Cache_Q6`, `ExLlamaV2Cache_Q8`. ExLlamaV3 extends this to 2–8 bit cache quantization with independent K and V bit widths. These caches are hardcoded into the attention implementation; there is no Python-level hook for per-head eviction strategies.

TabbyAPI consumes these classes directly. From `backends/exllamav2/model.py`:

```python
from exllamav2 import (
    ExLlamaV2Cache_Q4,
    ExLlamaV2Cache_Q6,
    ExLlamaV2Cache_Q8,
    ...
)
```

The `cache_mode` config field is validated as `"FP16"` or a `"Q*"` prefix string and used to select one of the above classes. No cache abstraction layer sits between TabbyAPI and ExLlama.

ExLlamaV3 ships a "HF Transformers plugin" that allows loading EXL3-quantized model weights under `transformers`. It does not make ExLlamaV3's own attention kernels run under `transformers`, and the transformers path would forgo the throughput advantages that motivate using ExLlamaV3 for Hermes 3 70B in the first place.

## 5. Compatibility assessment

Direct compatibility: **none.** KVzip's implementation targets transformers attention, and neither KVzip nor kvpress documents any non-transformers integration. ExLlamaV2/V3 exposes no swappable cache interface for eviction strategies.

Indirect paths and their cost:

| Path | Description | Cost |
|---|---|---|
| Run Hermes 3 70B under `transformers` with KVzip | Load EXL3 weights via the ExLlamaV3 HF plugin, apply KVzip monkey-patches to transformers attention | Forgoes ExLlamaV3 attention speedup; contradicts the Hermes 3 migration motivation (§2 of the Hermes design spec). |
| Port KVzip to ExLlamaV3 | Reimplement per-head eviction inside ExLlamaV3's C++/CUDA attention kernels | Substantial engineering: AdaKV-style non-uniform head budgeting at the kernel level. No upstream pull request exists. |
| Compose at a different layer | Apply KVzip-style eviction at prompt assembly time (drop low-importance tokens from the prompt, not from the cache) | Collapses the method to prompt-level compression; loses the cache-side speedup and is effectively already covered by Phase 1 token savings. |

No path is cheap. The first preserves correctness but cancels the reason for adopting ExLlamaV3. The second is a non-trivial kernel port with unknown maintenance cost. The third is not really KVzip.

## 6. Interaction with Phase 2 benchmark plan

The Phase 2 plan (`2026-04-10-prompt-compression-research-plan-design.md` §4.3) already specifies KV-cache quantization at Q8 as the cache-side compression lever, which is supported natively by ExLlamaV3 with independent K/V bit selection. Memory reduction reported for Q8 cache in published llama.cpp measurements is approximately 2× vs FP16, with "minimal quality impact" [smcleod.net](https://smcleod.net/2024/12/bringing-k/v-context-quantisation-to-ollama/). KVzip's 3–4× eviction-side savings would stack multiplicatively with Q8 in principle (orthogonal mechanisms), giving 6–8× theoretical reduction, but only if the engineering cost of the kernel port is accepted.

## 7. Recommendation

For Phase 2, use ExLlamaV3 native Q8 cache quantization as planned. Do not pursue KVzip integration on the current serving stack. Revisit KVzip if either of the following becomes true:

1. A community-maintained ExLlamaV3 port of KVzip-style eviction appears upstream.
2. The Hermes 3 70B migration's measured VRAM headroom under Q8 is insufficient for target context lengths, and the quality cost of dropping to Q4 is unacceptable.

Prompt-level compression (already in place via Phase 1, PR #638) remains the highest-ROI lever on the current stack.

## 8. Sources

- Kim et al., *KVzip: Query-Agnostic KV Cache Compression with Context Reconstruction*, NeurIPS 2025 — [arXiv:2505.23416](https://arxiv.org/abs/2505.23416)
- [snu-mllab/KVzip](https://github.com/snu-mllab/KVzip) — reference implementation
- [NVIDIA/kvpress](https://github.com/NVIDIA/kvpress) — compression library incorporating KVzip
- [turboderp-org/exllamav2](https://github.com/turboderp-org/exllamav2), [turboderp-org/exllamav3](https://github.com/turboderp-org/exllamav3) — inference library
- [theroyallab/tabbyAPI](https://github.com/theroyallab/tabbyAPI) `backends/exllamav2/model.py` — cache class usage
- `docs/superpowers/specs/2026-04-10-prompt-compression-research-plan-design.md` §4 — Phase 2 benchmark plan
- `docs/superpowers/specs/2026-04-10-hermes3-70b-voice-architecture-design.md` — Hermes 3 migration target
