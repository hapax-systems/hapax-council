# TabbyAPI config audit — local inference tuning + Phase 5 readiness

**Date:** 2026-04-14
**Author:** delta (beta role)
**Scope:** Reviews the current `tabbyAPI/config.yml` serving
Qwen 3.5 9B on the 3090. Asks: is the config tuned for the
current workload, and what specifically needs to change for
LRR Phase 5's Hermes 3 integration (ref drop #15 sizing)?
**Register:** scientific, neutral
**Status:** investigation only — three config-tuning
candidates for immediate review plus a readiness checklist
for Phase 5

## Headline

**Three findings for the current Qwen 3.5 config.**

1. **`max_seq_len: 4096` is unnecessarily small.** Qwen 3.5 9B
   natively supports ≥ 32 k context. Raising the cap to 32 k
   would cost ~1 GB additional VRAM for the enlarged KV cache
   at `cache_mode: 4,4` (Q4 KV quant) — well within the 3090's
   available headroom of ~15 GB free. Agents that want to fit
   longer system prompts or retrieval context into
   `local-fast`/`coding`/`reasoning` routes currently have a
   hard cap they can't see until a request fails. If alpha's
   LRR experiments or chat classifier Phase 5 fallback need
   longer inputs, they hit this cap first.
2. **`cache_size` matches `max_seq_len` exactly (both 4096).**
   Safe, but means **exactly one concurrent request of
   maximum length** can be in flight. Any two requests that
   each want near-max context contend for KV pages. Raising
   `max_seq_len` without raising `cache_size` disproportionately
   would let one request starve another. Paired adjustment
   required.
3. **No explicit prompt-prefix caching configuration.**
   ExllamaV3 supports prefix-cache reuse across requests
   that share a token prefix (repeated system prompts, RAG
   templates). The config has no flag one way or the other.
   **Default behavior varies by TabbyAPI/ExllamaV3 version**
   — needs verification in the source or a controlled test.
   If prefix caching is off, every repeated-prefix request
   re-prefills from scratch. This is the local-inference
   equivalent of the Anthropic prompt-cache gap flagged in
   drop #8.

## 1. `max_seq_len: 4096` is too small

### 1.1 Qwen 3.5 9B's actual capability

- **Native context**: 32 k tokens (RoPE theta 1 000 000)
- **Extended**: up to 128 k via YaRN scaling (optional)
- **Architecture**: GQA with 32 attention heads, 8 KV heads,
  head dim 128, 28 layers

### 1.2 KV cache sizing (per-token memory)

Per-token KV cache cost:
`2 (K+V) × 8 (KV heads) × 128 (head dim) × bytes × 28 layers`

| cache_mode | bits per element | bytes per element | bytes per token | VRAM @ 4 k | VRAM @ 16 k | VRAM @ 32 k | VRAM @ 128 k |
|---|---|---|---|---|---|---|---|
| fp16 / bf16 | 16 | 2 | 114 688 | 447 MB | 1.79 GB | 3.58 GB | 14.3 GB |
| Q8 | 8 | 1 | 57 344 | 224 MB | 896 MB | 1.79 GB | 7.16 GB |
| **Q4 (`4,4`)** | 4 | 0.5 | **28 672** | **112 MB** | **448 MB** | **896 MB** | **3.58 GB** |

**Current config at `max_seq_len: 4096`, `cache_mode: 4,4`**:
KV cache reserves ~112 MB. The model weights at EXL3
5.00 bpw are ~5.8 GB. Total TabbyAPI footprint on the 3090:
~5.9 GB.

**Proposed bump to `max_seq_len: 32768`**: KV cache
reserves ~900 MB instead of ~112 MB. Delta: +800 MB on
the 3090. The 3090 currently has ~14.9 GB free (per drop
#15 § 1). **Headroom after the bump: ~14 GB** — still very
comfortable.

### 1.3 Why this matters

Agents that route to TabbyAPI today are capped at 4 k total
(system prompt + user + assistant + tool calls). That's
tight for any realistic agent:

- A typical pydantic-ai agent with a persona + tool schemas
  + a few retrieval hits already eats 2 k of prompt before
  user input.
- The Phase 9 chat classifier fallback (if it uses TabbyAPI
  via the `reasoning` route in degradation mode) can easily
  exceed 4 k with 20 chat messages of context + system
  prompt.
- Prompt-compression benchmark drop (drop #15 § references)
  refers to a `benchmark_prompt_compression_b6.py` script —
  the fact that alpha is benchmarking prompt compression at
  all suggests length is a real concern.

The 4 k cap is a historical choice from when VRAM was tighter
or the backend was different. With EXL3 + Q4 KV cache, the
numbers above say the constraint is no longer load-bearing.

### 1.4 The patch

```yaml
# tabbyAPI/config.yml
model:
  backend: exllamav3
  cache_mode: 4,4
  cache_size: 32768          # was 4096
  chunk_size: 2048
  inline_model_loading: false
  max_seq_len: 32768         # was 4096
  model_dir: models
  model_name: Qwen3.5-9B-exl3-5.00bpw
```

Restart cost: 30–60 s per TabbyAPI CLAUDE.md. Do it during
an intentional idle window.

## 2. `cache_size` vs `max_seq_len` ratio

**Current:** `cache_size = max_seq_len = 4096` — only one
request at max length in flight simultaneously. Any concurrent
requests share the remaining budget.

**Why the 1:1 ratio matters:** `cache_size` is the total
KV page budget. If three agents send 3 k-token prompts
concurrently, the third one blocks until one of the first
two finishes. Under the router aliases
`local-fast`/`coding`/`reasoning`, there's no queue
visibility — callers see a stall as request latency.

**Recommended ratio:** `cache_size ≥ 2 × max_seq_len` for
a workstation with one primary caller plus occasional
secondary callers. At `max_seq_len: 32768`, `cache_size:
65536` costs ~1.8 GB KV cache at Q4 — still fits
comfortably on the 3090.

For a workstation with N expected concurrent callers,
`cache_size = N × max_seq_len` is the upper-comfortable
bound.

## 3. Prompt prefix caching — status unknown

ExllamaV3 supports cross-request KV cache reuse for
requests that share a common prefix (system prompt +
persona + tool schemas, with only the user turn differing).
**This is the local-inference analogue to Anthropic's
prompt cache** — and drops #8 / #9 flagged that Anthropic
prompt caching is unused across the council's LLM callers.

If TabbyAPI's prefix cache is also off or unused, every
request re-prefills the shared prefix. For a director_loop
routed through TabbyAPI (alpha has discussed this option
in prior drops), this would mean ~5 000 token re-prefills
every 90 s of runtime — ~3 000 token-compute-seconds/hour
of wasted work.

**Verification path (not done in this drop):**

1. Check if TabbyAPI's `config_sample.yml` mentions a
   `prompt_cache` or `prefix_cache` option.
2. Check if ExllamaV3's generator accepts a
   `past_key_values` / `cache_key` parameter at the API
   layer.
3. If either exists, measure prefill time for two
   consecutive same-prefix requests via direct curl to
   `:5000`. First should be slow (cold); second should
   be much faster (warm).

If prefix caching is supported and off, enabling it is
another config change. If it's supported and on by default,
verify with the test. If it's not supported (ExllamaV3
version gap), flag for upstream.

## 4. Phase 5 readiness — Hermes 3 switch checklist

Drop #15 establishes that Hermes 3 70B at Q2_K (~26 GB) is
the only version that fits on the 3090 alone. When alpha
pivots TabbyAPI to serve Hermes 3, the config changes
needed:

```yaml
# tabbyAPI/config.yml — Phase 5 target
model:
  backend: exllamav3
  cache_mode: 4,4                       # unchanged — Q4 KV
  cache_size: 8192                      # trimmed — Hermes 3 at Q2 tighter VRAM
  chunk_size: 1024                      # trimmed — smaller chunks, lower peak
  inline_model_loading: false
  max_seq_len: 8192                     # Hermes 3 70B context is 128k
  model_dir: models                      # — but KV budget caps practical
  model_name: Hermes-3-Llama-3.1-70B-exl3-2.62bpw
```

Rationale:

- **Weights**: Hermes 3 70B EXL3 Q2_K (~2.62 bpw) is ~24 GB.
  On a 24 GB 3090, that leaves ~500 MB for KV — not enough.
  The math only works if:
  - `max_seq_len` is pulled back to ~8 k (KV at Q4: ~6.5 GB
    for 70 B arch, still doesn't fit — **this is too tight
    to serve**)
  - OR the operator accepts an occasional OOM and model
    reload cycle
  - OR TP2 is enabled across both GPUs (drop #15 path B)
- **`model_name` swap** is the headline change. Same keys,
  different string.
- **`cache_size` and `max_seq_len` paired downgrade** from
  the Qwen 32 k suggestion in § 1. Hermes 3 70B has much
  larger per-token KV than Qwen 9B (bigger hidden dim,
  more KV heads, deeper model), so the budget shrinks.
- **`chunk_size` downgrade** matches the smaller KV budget.

**Likely outcome**: single-GPU Hermes 3 70B Q2_K at 8 k
context is right at the edge of 24 GB. Drop #15 path B
(TP2 across both GPUs) is more robust but kills the
compositor GPU path. Drop #15 path D (Hermes 3 8B
instead) avoids the whole tradeoff.

**Recommendation:** don't pre-commit the Phase 5 config
until the operator picks a path. The config changes are
path-specific.

## 5. Non-perf observations (noted, not flagged)

- **`inline_model_loading: false`** means the model is
  loaded at startup. Advantage: steady-state latency is
  low (no lazy load). Disadvantage: can't swap models
  without a TabbyAPI restart. For Phase 5 Hermes 3
  integration, the Qwen → Hermes transition is a full
  TabbyAPI restart (30–60 s downtime). Not new but worth
  remembering.
- **`disable_auth: true`** is correct for the single-
  operator workstation. No change recommended.
- **Harmony-style tool-call extractor** (per TabbyAPI
  CLAUDE.md): local patch in
  `endpoints/OAI/utils/chat_completion.py` to handle
  Qwen 3.5's unusual tool-call template. When Hermes 3
  becomes the model, the patch may become inert — Hermes
  uses Llama-3 tool-call syntax which TabbyAPI's
  upstream path handles natively. Verify on model swap.
- **`cache_mode: 4,4`** is Q4 KV cache — aggressive but
  stable for Qwen. For Hermes 3 the quality impact of
  Q4 KV on a quant-compressed 70 B model may compound.
  Benchmark before committing.

## 6. Follow-ups for alpha

Ordered by ratio:

1. **Bump `max_seq_len` and `cache_size` to 32 768**
   in current Qwen config. 30–60 s downtime. ~800 MB
   extra VRAM on the 3090. Unblocks all agents that
   want longer context. Tier: **ship today**.
2. **Verify prefix-cache status**. Two-minute source
   check + one-minute curl test. If off, enabling it
   is another config line. If on, document.
3. **Defer Phase 5 config rewrite** until the operator
   picks a path (§ 4 above). Don't edit config for a
   hypothetical swap.
4. **Benchmark Q2_K quality on Hermes 3 (if path A)**
   before shipping. Phase 5 classifier quality is the
   actual gate — VRAM was just the feasibility gate.

## 7. References

- `~/projects/tabbyAPI/config.yml` — live config, 22 lines
- `~/projects/tabbyAPI/CLAUDE.md` — context on local patches
  and GPU isolation contract
- `docs/research/2026-04-14-hermes-3-70b-vram-sizing.md`
  (drop #15) — Phase 5 sizing math this drop builds on
- `docs/research/2026-04-14-director-loop-prompt-cache-gap.md`
  (drop #8) — the Anthropic prompt cache gap that motivates
  the § 3 investigation for the local-inference analogue
- Qwen 3.5 9B architecture specs (public) — 32 attention
  heads, 8 KV heads, head dim 128, 28 layers, RoPE
  theta 1 000 000
- ExllamaV3 cache mode conventions — `N,N` indicates bits
  per element for K and V separately (e.g. `4,4` = Q4
  K + Q4 V)
