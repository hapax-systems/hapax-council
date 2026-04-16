---
title: LRR Phase 5 — substrate scenario 1+2 — execution closure
date: 2026-04-16
author: beta (single-session LRR takeover)
phase: 5
epic: lrr
status: closed
supersedes_blockers:
  - Phase 7 persona spec (was: PENDING SUBSTRATE)
  - Phase 8 content programming
  - Phase 9 closed-loop feedback
  - Phase 10 observability
---

# LRR Phase 5 — execution closure

**Spec:** `docs/superpowers/specs/2026-04-15-lrr-phase-5-substrate-scenario-1-2-design.md` (PR #896)
**Plan:** `docs/superpowers/plans/2026-04-15-lrr-phase-5-substrate-scenario-1-2-plan.md` (PR #900)
**Scenario origin:** drop #62 §16 (substrate ratification 2026-04-15T18:21Z) + §17 (Option C pivot 2026-04-15T18:49Z)

## Closure criterion

Phase 5 closes when both substrate tracks reach live, verifiable state.

| Track | State | Evidence |
|---|---|---|
| Scenario 1 (Qwen3.5-9B + RIFTS baseline) | ✅ shipped | PR #934 — harness + Qwen baseline + GPT-4 labeler + `--split` flag |
| Scenario 2 (OLMo 3-7B parallel TabbyAPI `:5001`) | ✅ shipped | PR #932 (TabbyAPI deploy) + PR #933 (LiteLLM `local-research-instruct` route) |

## Scenario 1 — Qwen3.5-9B RIFTS baseline

Shipped PRs:

- **PR #934** (queue #210/#227/#241/#243 bundled) — `scripts/run_rifts_benchmark.py` harness, Qwen baseline results, GPT-4 judge labeler, `--split` flag.
- RIFTS dataset: `microsoft/rifts` via HuggingFace; schema captured in `research/benchmarks/rifts/README.md`.
- Baseline results: `research/benchmarks/rifts/results-local-fast-qwen-*.jsonl` on main.

Scenario 1 exit criteria (per spec):

- [x] Dataset staged, harness committed, schema documented
- [x] Qwen baseline rates computed (refusal / question-asking / normal / hallucination)
- [x] GPT-4 labeler wired for scale-up labeling
- [x] `--split` flag supports per-category subset runs

## Scenario 2 — OLMo 3-7B parallel TabbyAPI

Shipped PRs:

- **PR #932** — Parallel TabbyAPI instance on `:5001` serving OLMo-3-7B-Instruct EXL3 5.0bpw on GPU 1 (RTX 3090).
- **PR #933** — LiteLLM `local-research-instruct` route pointed at `:5001`; smoke-tested `ROUTE_OK`.

Pivot note: original spec targeted OLMo-2-7B; exllamav3 0.0.29 supports `Olmo3ForCausalLM` natively but NOT `Olmo2ForCausalLM`. Pivoted to **OLMo-3-7B-Instruct** via kaitchup pre-quant branch `bpw-5.0-h8`. Documented in PR #932 doc.

Scenario 2 exit criteria (per spec):

- [x] Parallel backend live on `:5001`, separate venv, GPU 1 pinned via `CUDA_VISIBLE_DEVICES=1`
- [x] OLMo weights downloaded (pre-quant)
- [x] LiteLLM route `local-research-instruct` wired with langfuse callback
- [x] UFW rule allows docker bridge → host `:5001`
- [x] Smoke test passes
- [ ] Three-variant comparison (SFT / DPO / RLVR) — **deferred** to cycle 2 execution follow-up (queue #212.3)
- [ ] `claim-shaikh` cycle 2 full run — deferred (awaits operator authorization on cycle-2 kickoff)

Scenario 2 closure is **infrastructure-complete**. The OLMo-SFT variant is the default currently loaded (the Instruct tune); DPO/RLVR variant swaps are trivial on-disk model reloads, not blocking.

## Observability finding during Phase 5 execution

Queue #242 (Langfuse 6-week comparison) surfaced:

1. **Root cause:** LiteLLM had no `langfuse` success_callback wired. All Qwen3.5-9B production traffic invisible to Langfuse.
2. **Compounding:** MinIO inode exhaustion (100%) blocked Langfuse blob writes for ~2 days; ClickHouse metadata survived (no TTL).
3. **Remediation (shipped PR #936):**
   - Added `langfuse` to LiteLLM `success_callback` + `failure_callback`
   - MinIO retention lifecycle 14d → 3d
   - LANGFUSE_SAMPLE_RATE 0.3 → 0.1
   - Filesystem-level purge of `/data/minio/langfuse/events/.../trace` >3 days old
   - ClickHouse `max_concurrent_queries_for_user` 8 → 16 to survive recovery spike
   - Defensive scaffolding: `agents/_langfuse_local.py` durable local trace reader + `agents/langfuse_sync.py` JSONL writer extension

Post-fix state: 46K+ observations ingested in the first hour after the fix; queues drained.

## Downstream unblocks

Phase 5 closure unblocks:

- **Phase 7** — persona spec authoring (was: PENDING SUBSTRATE)
- **Phase 8** — content programming via research objectives
- **Phase 9** — closed-loop feedback + narration + chat integration
- **Phase 10** — observability / drills / polish (polish slice)

## Deferred follow-ups (not blocking closure)

- **Queue #212.3** — OLMo three-variant comparison (DPO, RLVR). Requires swapping model on disk + second TabbyAPI restart per variant.
- **Claim-shaikh cycle 2** — full comparative run; awaits operator scheduling.
- **Queue #243 LiteLLM `local-fast` callback capture** — 30 smoke-test calls produced 0 Langfuse observations post-LiteLLM restart. Likely cold-start window or sample-rate interaction with openai-compatible local routes. Separate diagnostic ticket.

## References

- Drop #62 cross-epic fold-in: `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md`
- Phase 5 spec: `docs/superpowers/specs/2026-04-15-lrr-phase-5-substrate-scenario-1-2-design.md`
- Phase 5 plan: `docs/superpowers/plans/2026-04-15-lrr-phase-5-substrate-scenario-1-2-plan.md`
- OLMo-3 deploy: `docs/research/2026-04-16-olmo-3-parallel-tabbyapi-deploy.md`
- LiteLLM route: `docs/research/2026-04-16-olmo-litellm-route-and-cycle-2-deferral.md`
- Langfuse gap finding: `docs/research/2026-04-16-rifts-langfuse-comparison-gap-finding.md`
- LRR coverage audit: `docs/research/2026-04-15-lrr-epic-coverage-audit.md`

— beta, 2026-04-16
