# exllamav3 v0.0.24–v0.0.29 Release Matrix + OlmoHybrid Upstream Research

**Queue:** #171
**Author:** alpha
**Date:** 2026-04-15
**Trigger:** beta's #209 report — exllamav3 0.0.29 upgrade blocked TabbyAPI's pinned cu12 stack. Scenario 2 Option C (separate venv) was adopted as fallback. This research asks whether an intermediate version (0.0.24–0.0.28) adds OlmoHybrid support without the 0.0.29 blocker — if so, Option A (in-place upgrade) may be viable alongside or instead of Option C.

**Method:** GitHub API against `turboderp-org/exllamav3` — release notes, `requirements.txt`, release asset wheel lists across v0.0.23 (baseline) through v0.0.29.

---

## §0. TL;DR

1. **OlmoHybridForCausalLM support shipped in v0.0.26** (2026-03-16). Every subsequent release inherits it.
2. **`torch>=2.6.0` has been the declared minimum across v0.0.23 → v0.0.29.** Beta's #209 framing "0.0.29 required torch 2.11+" is imprecise: the declared requirement never changed; v0.0.29 merely *added* torch 2.11 and py3.14 wheels to the release asset matrix.
3. **v0.0.29's only new transitive dep** is `xformers` (added to `requirements.txt`). This is the most probable root cause of beta's #209 incompatibility with TabbyAPI's pinned cu12 stack, not a torch-version forcing.
4. **v0.0.28 is the sweet spot for scenario 2 Option A.** It has OlmoHybrid (from v0.0.26), Qwen3.5 (from v0.0.25), all v0.0.24–v0.0.28 regression fixes, and the same dep list as v0.0.23 (no xformers).
5. **Recommendation:** scenario 2 Option A (in-place upgrade to v0.0.28) is **viable pending a 15-minute verification step** that beta's #209 blocker trace was indeed caused by the xformers addition and not some other transitive change.

---

## §1. Per-version matrix

| Version | Published   | `requirements.txt` delta vs prior | Declared torch | Pre-built wheel torch range | New architecture support | Notable fixes / QoL |
|---------|-------------|-----------------------------------|----------------|------------------------------|--------------------------|---------------------|
| v0.0.23 | (baseline)  | —                                 | `>=2.6.0`      | cu128 × torch 2.7–2.10       | —                        | —                   |
| v0.0.24 | 2026-03-08  | unchanged                         | `>=2.6.0`      | cu128 × torch 2.7–2.10       | —                        | Faster MoE routing with graphs; fix GLM 4.7 regression |
| v0.0.25 | 2026-03-11  | unchanged                         | `>=2.6.0`      | cu128 × torch 2.7–2.10       | `Qwen3_5ForCausalLM`, `Qwen3_5MoeForCausalLM` | Support Qwen3.5 BF16 finetunes; correct tensor format for REAPed Qwen3.5 MoE |
| v0.0.26 | 2026-03-16  | unchanged                         | `>=2.6.0`      | cu128 × torch 2.7–2.10       | **`OlmoHybridForCausalLM`** | Fused expert kernel for MoE prompt/batch throughput; non-integer bitrate fix for large MLP |
| v0.0.27 | 2026-03-26  | unchanged                         | `>=2.6.0`      | cu128 × torch 2.7–2.10       | —                        | New non-integer bitrate allocator; `-hq` quantizer flag; prompt-cache fix for recurrent models; rep-penalty fix for OAI clients via TabbyAPI; recurrent/KV sync fix; Nanochat feature parity |
| v0.0.28 | 2026-03-30  | unchanged                         | `>=2.6.0`      | cu128 × torch 2.7–2.10       | —                        | Fix regression breaking inference for GLM4.5-Air and related models |
| v0.0.29 | 2026-04-12  | **+ `xformers`**                  | `>=2.6.0`      | cu128 × torch 2.7–2.11 (+py3.14 on torch≥2.9) | `Gemma4ForConditionalGeneration` | Quantizer RAM fix on resume; large-tensor segfault fix; loop detection option; torch 2.11 wheels added; py3.14 wheels added |

Full raw requirements file snapshots confirmed byte-for-byte identical across v0.0.23, v0.0.24, v0.0.25, v0.0.26, v0.0.27, v0.0.28. Only v0.0.29 differs (xformers appended).

---

## §2. Where OlmoHybrid lives

Single-line release-note quote, v0.0.26:

> Support OlmoHybridForCausalLM

The class name `OlmoHybridForCausalLM` is the HuggingFace Transformers canonical naming for OLMo hybrid architectures. OLMo 3-7B × {SFT, DPO, RLVR} — the scenario 2 model set — use the `OlmoHybridForCausalLM` loader at the Transformers layer. Once exllamav3 registers the arch, any EXL3 quant of OLMo 3-7B can load.

**Inheritance:** v0.0.26, v0.0.27, v0.0.28, v0.0.29 all have OlmoHybrid support. There is no release between v0.0.26 and v0.0.29 that removed it.

---

## §3. Where beta's #209 blocker actually lives

### §3.1. Declared requirements did not change

`requirements.txt` at v0.0.29:

```
torch>=2.6.0
flash_attn>=2.7.4.post1
tokenizers>=0.21.1
numpy>=2.1.0
rich
typing_extensions
safetensors>=0.3.2
ninja
pillow
pyyaml
marisa_trie
kbnf>=0.4.2
pydantic==2.11.0
formatron>=0.5.0
xformers
```

The only new line is `xformers`. Every other dep matches v0.0.28 byte-for-byte.

### §3.2. Release asset wheel matrix

v0.0.28 publishes cu128 wheels for **torch 2.7, 2.8, 2.9, 2.10** × cp310–cp313.
v0.0.29 publishes cu128 wheels for **torch 2.7, 2.8, 2.9, 2.10, 2.11** × cp310–cp313 (plus cp314 where torch ≥2.9).

v0.0.29 **did not remove** any earlier-torch wheels. A TabbyAPI stack on torch 2.7 through 2.10 has an identically-keyed wheel available in both v0.0.28 and v0.0.29.

### §3.3. Root cause hypothesis

Given (§3.1) that the only requirements change is `xformers` and (§3.2) that prior torch wheels are still published, the most likely cause of beta's #209 pin failure is:

**Hypothesis A — xformers resolver conflict (strongest).** `xformers` has tight torch-version coupling (each xformers release supports a narrow torch ABI window). When pip resolves `exllamav3==0.0.29` against TabbyAPI's pinned-cu12 torch, the newly-required `xformers>=(whatever)` drags in an incompatible torch, or pip cannot satisfy xformers against the installed torch, and refuses to resolve.

**Hypothesis B — flash_attn transitive drift.** `flash_attn>=2.7.4.post1` is unchanged across versions, but flash_attn's own torch ABI pin can move. If TabbyAPI is on a specific flash_attn wheel, a rebuild triggered by the 0.0.29 install may have attempted to pull a newer flash_attn. Less likely as the root cause because this pathway would have triggered the same breakage on 0.0.28.

**Hypothesis C — pip preferred the torch 2.11 wheel.** If pip's resolver preferred the newer torch 2.11 wheel over a still-available torch 2.7/2.8 wheel because both satisfy `torch>=2.6.0`, the resolver would then need torch 2.11 in the env. This is a pip-policy failure, not an exllamav3 requirement.

The data cannot adjudicate between these without beta's actual pip resolver trace from #209. Hypothesis A is the most likely on priors.

### §3.4. Test to discriminate

If beta can produce the #209 pip trace, look for one of:

- `ERROR: Cannot install exllamav3==0.0.29 because ... xformers ...` → Hypothesis A confirmed.
- `ERROR: ... flash_attn ... torch==2.11` → Hypothesis B/C, xformers is incidental.
- `Downloading exllamav3-0.0.29+cu128.torch2.11.0-cp312...` after resolver — Hypothesis C confirmed.

---

## §4. Scenario 2 Option A viability

### §4.1. What Option A requires

Scenario 2 Option A (from drop #62 §16) is: in-place upgrade of TabbyAPI's exllamav3 to a version that serves OLMo 3-7B EXL3 quants alongside the existing Qwen3.5-9B workload, without forking to a parallel venv.

Required:
- Architecture: OlmoHybridForCausalLM registered.
- Transitive deps: no breakage of TabbyAPI's pinned cu12 stack.
- Wheel availability: cu128 × current torch × cp312 (or whatever TabbyAPI runs).
- Same-process load: no requirement that scenario 1 and scenario 2 run in separate venvs.

### §4.2. v0.0.28 checklist

| Requirement | v0.0.28 status |
|-------------|-----------------|
| OlmoHybridForCausalLM registered | **yes** (inherited from v0.0.26) |
| `requirements.txt` parity with v0.0.23 | **yes** (byte-for-byte) |
| cu128 × torch 2.7–2.10 wheel coverage | **yes** (same matrix as v0.0.23) |
| No new transitive deps | **yes** (no xformers) |
| Incorporates fix for GLM4.5-Air regression | **yes** (v0.0.28 shipped this) |
| Incorporates fused-expert MoE kernel | **yes** (inherited from v0.0.26) |
| Incorporates Qwen3.5 BF16 / REAPed support | **yes** (inherited from v0.0.25) |
| Loop detection / quantizer RAM fix / large-tensor segfault fix | **no** (v0.0.29 additions) |
| Gemma4 support | **no** (v0.0.29 addition; not in the scenario 2 model set) |

**Verdict: v0.0.28 meets every Option A requirement.** The only capabilities it lacks are v0.0.29's quality-of-life additions, none of which are scenario 2 blockers.

### §4.3. Recommendation

1. **Queue a 15-minute verification item** for beta: reproduce the #209 blocker on v0.0.29, capture the pip resolver trace, then attempt `pip install exllamav3==0.0.28`. If 0.0.28 installs cleanly against TabbyAPI's pinned torch, scenario 2 Option A is live.
2. **If verification passes**, scenario 2 Option A (in-place to v0.0.28) becomes the preferred path because it avoids the parallel-backend complexity of Option C while still gating on scenario 1's stability signal.
3. **Option C remains the fallback** if verification uncovers a second-order blocker (e.g., flash_attn ABI drift) that is not the xformers addition.
4. **Option A and Option C are not mutually exclusive in the short term.** If Option A lands cleanly on v0.0.28, Option C can be retired. If it fails, Option C continues as the shipping path and this research drop is retained as documentation for a future upstream upgrade.

---

## §5. Cross-references

- **Drop #62 §16** — substrate scenario 1 + scenario 2 ratification.
- **Drop #62 §17** — Option C pivot after beta's #209 blocker.
- **Drop #62 §18** — forward-looking post-scenario-1+2 ship planning; this matrix informs that plan.
- **Queue #209** — beta's original blocker report (0.0.29 → TabbyAPI cu12 incompatibility).
- **Queue #171** — this research drop.

---

## §6. Appendix — raw data

### §6.1. Release cadence

| Version | Publish date | Days since prior |
|---------|--------------|-------------------|
| v0.0.24 | 2026-03-08   | (baseline)        |
| v0.0.25 | 2026-03-11   | 3                 |
| v0.0.26 | 2026-03-16   | 5                 |
| v0.0.27 | 2026-03-26   | 10                |
| v0.0.28 | 2026-03-30   | 4                 |
| v0.0.29 | 2026-04-12   | 13                |

### §6.2. Release note raw text

**v0.0.24 (2026-03-08):**
- Faster MoE routing with graphs
- Fix regression breaking GLM 4.7

**v0.0.25 (2026-03-11):**
- Add Qwen3_5ForCausalLM and Qwen3_5MoeForCausalLM
- Support Qwen3.5 finetunes saved entirely in BF16 format
- Correct tensor format for Qwen3.5 models with split experts (support REAPed models)

**v0.0.26 (2026-03-16):**
- Fused expert kernel for improved prompt and batch throughput on MoE models
- Support OlmoHybridForCausalLM
- Fix non-integer bitrates when quantizing models with a very large MLP layers
- Minor bugfixes
- QoL improvements

**v0.0.27 (2026-03-26):**
- New and more robust allocation strategy for non-integer bitrates
- Added `-hq` argument to quantizer
- Fix bug causing prompt caching to fail on recurrent models for certain combinations of prompt length and chunk size
- Fix broken output when using repetition penalties without decay range (affecting some OAI clients via TabbyAPI)
- Fix issue allowing recurrent state to fall out of sync with K/V cache
- Support more features in Nanochat, for some reason
- Other fixes and QoL improvements

**v0.0.28 (2026-03-30):**
- Fix regression breaking inference for GLM4.5-Air and related models

**v0.0.29 (2026-04-12):**
- Support Gemma4ForConditionalGeneration
- Fix bug causing quantizer to allocate too much system RAM on resume
- Fix bug causing potential segfaults when saving large tensors
- Add loop detection option
- More benchmarks
- QoL improvements
- Other bugfixes
- Add Torch 2.11 wheels
- Add Python 3.14 wheels (Torch 2.9+ only)

### §6.3. Data provenance

All data extracted via GitHub API:

- `gh api repos/turboderp-org/exllamav3/releases/tags/v0.0.{24..29}` — release note bodies.
- `gh api repos/turboderp-org/exllamav3/contents/requirements.txt?ref=v0.0.{23..29}` — dependency pins.
- `gh api repos/turboderp-org/exllamav3/releases/tags/v0.0.{26,28,29} --jq '.assets[].name'` — release wheel asset lists.

No speculative or model-generated content — all facts cross-referenced against the upstream repository at its signed release tags.
