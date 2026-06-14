# Local Judge Validation — CompassVerifier-7B (cost-offload Tier-1, shadow-infra increment)

**Date:** 2026-06-14 · **Authority:** ISAP `S5-CAPACITY-ROUTING-COST-OFFLOAD-TIER1`
· task `cc-task-cost-offload-local-judge-stack` · REQ `REQ-20260613-sdlc-cost-offload-program`.
**Verdict:** served + routed + quant-validated. **Quant is intact; promotion bars are NOT
yet met → ship default-OFF / shadow.** Deploy + ops: `docs/runbooks/local-judge-stack.md`.
Adapter: `shared/local_judge.py`. Harness: `scripts/cost-offload/`.

> **Scope of this increment (this does NOT close the Tier-1 task).** This PR lands
> AC1/AC2/AC4/AC5 — the judge is served, routed, quant-validated, and fallback-proven.
> **AC3 (council-distribution agreement) and AC6 (a real gate repointed) remain
> OUTSTANDING**, so the *realized* marginal cost saving from this diff is **$0 by
> design**: the judge ships `shadow=True` and offloads nothing until the agreement
> gate clears on council traffic. Realizing the offload (the conservative pre-screen /
> escalation composition on a fitting answer-verification gate) is tracked as the
> follow-on `cc-task-cost-offload-local-judge-realize`. This is deliberate, not an
> omission: the measured κ 0.70 / non-conservative skew (below) means promoting now
> would trade quality for cost, which the cost-offload invariant forbids.
>
> **Closure semantics (no false satisfaction).** Merging this PR closes
> `cc-task-cost-offload-local-judge-stack` to `done` **only on its re-scoped predicate
> — the four infra ACs above, all met**. The parent task was explicitly re-scoped
> (2026-06-14, in its own frontmatter) to the shadow-infra increment; the former AC3
> and AC6 are *removed from this task* and tracked **open** in the follow-on. So no
> dashboard reads "Tier-1 realized offload done" — the realized-offload predicate
> stays visibly open until the follow-on closes it.

## Setup

- **Model:** CompassVerifier-7B (Apache-2.0, Qwen2.5-7B fine-tune), GGUF **Q5_K_M** (5.4 GB).
- **Serving:** `llama.cpp:server-cuda` on appendix GPU1 (RTX 5060 Ti, sm_120 Blackwell;
  image is natively Blackwell-capable — `ARCHS=...,1200`, `BLACKWELL_NATIVE_FP4=1`),
  `:5001`, 8 continuous-batch slots × 8192 ctx.
- **Route:** podium LiteLLM `local-judge` → `http://192.168.68.50:5001/v1`, fallback `[claude-haiku]`.
- **Eval:** full VerifierBench `test` (2817 items; expert gold `gold_judgment` ∈ {A=correct,
  B=incorrect, C=invalid}), official `CV_PROMPT` (non-CoT, single-letter) + `process_judgment`
  parser, greedy decoding. **Zero provider spend** — gold labels are the dataset's own.

## Results (n=2690 scored; 127 / 4.5% ctx-skipped, all >8192-token pathological inputs)

| Metric | Value | Bar | Verdict |
|---|---|---|---|
| **Binary CORRECT F1** (A vs B,C) | **83.14** | within ±3 of published **83.4** | **PASS** (Δ0.26) |
| Macro-F1 (A/B/C) | 79.73 | — | — |
| Accuracy / agreement vs gold | 83.79% | AC3: ≥90% | **below** |
| Cohen's κ vs gold | 0.703 | AC3: ≥0.80 | **below** |
| Conservative-skew | false-accept 239 > false-reject 145 | AC3: conservative | **not met** |

Per-class F1: A 83.1 · B 85.7 · C 70.3. Per-domain agreement: Knowledge 90.9% ·
General-Reasoning 86.8% · Science 84.8% · **Math 76.7%** (weakest — answer-equivalence
on math is the hard case).

Confusion (rows=gold, cols=pred):

```
       A     B     C
A    947   143     2
B    207  1205    35
C     32    17   102
```

## Interpretation

- **AC4 (quant integrity) — PASS.** Binary F1 83.14 ≈ published 83.4 confirms the GGUF
  Q5_K_M quant did not degrade the judge; the served model performs at CompassVerifier-7B
  spec.
- **AC3 (frontier-agreement) — bars NOT met on adversarial public gold.** Against
  VerifierBench's expert reference the judge agrees 83.8% (κ 0.70) and its errors are
  **not conservative-skewed**: **8.88% of all items are false-accepts** (judge says
  CORRECT where gold says INCORRECT/INVALID) — the dangerous direction for a gate.
  VerifierBench is a deliberately hard verifier-stress set, so this is in-family with
  the model's published capability, not a quant defect — but it means the judge **cannot
  be promoted to authoritative as-is**. AC3's 90% / κ0.80 / conservative bars are defined
  for the **council gate's own distribution** and must be evaluated from shadow traffic
  (`shadow_compare` → `~/.cache/hapax/local-judge-shadow.jsonl`), not from adversarial
  public gold. The public result **calibrates** the promotion decision: promotion will
  also require **conservative composition** (escalate disagreements / pair with a
  confirmer) rather than acting unilaterally on a bare CORRECT verdict.

## Acceptance criteria

| AC | Status | Evidence |
|---|---|---|
| AC1 — served on appendix :5001 GPU1, 3090 unchanged | ✅ | judge 8.7 GB on GPU1; GPU0/3090 held at **18234 MiB** before/during/after |
| AC2 — `local-judge` route on :4000, <2s TTFT | ✅ | routes through gateway; ~44 ms prompt-eval, single-token verdict |
| AC3 — ≥150 council items, agreement ≥90% ∧ κ≥0.8, conservative | ⏳ shadow | public-gold proxy: 83.8% / κ0.70 / not-conservative → **stays shadow**; council-distribution gate accumulates via `shadow_compare` |
| AC4 — F1 within ±3 of 83.4 | ✅ | binary F1 **83.14** (Δ0.26) |
| AC5 — fallback chain exercised | ✅ | `:5001` stopped → `local-judge` served by `claude-haiku-4-5`, no hard error |
| AC6 — one real gate repointed, $0 marginal | ⚠️ adapter shipped | reusable shadow `LocalJudge` adapter is the substrate; **no existing council gate is a clean answer-verification fit** (existing LLM-judges — `eval_grounding`, `demo_eval` — are gold-free quality judges); first real consumer is the grounding-fitness Step-6 grader |

## Notes / follow-ons

- **127 ctx-skips (4.5%)** are VerifierBench's pathological >8192-token items, not a judge
  defect; production council inputs are far shorter. A larger per-slot context (`-c` ÷ `-np`)
  closes the gap if a full-coverage number is later wanted.
- **AC6 finding** is a genuine slice-scoping result for the cost-offload program: the
  council's high-volume LLM-judging is mostly **gold-free quality judging** (rubric/GenRM
  territory), not answer-verification. CompassVerifier's offload surface here is the
  grounding-fitness eval grading + future mechanical correctness gates — narrower than the
  REQ assumed. Recorded for the program matrix.
