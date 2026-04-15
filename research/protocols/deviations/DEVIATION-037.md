# Deviation Record: DEVIATION-037

**Date:** 2026-04-14 (original 70B draft) / 2026-04-15 (drop #62 Option C amendment) / YYYY-MM-DD (final at Phase 5a execution time)
**Phase at time of change:** intervention-transition (Condition A → Condition A')
**Author:** beta (draft) / alpha or operator (final, with post-execution notes filled in)
**Status:** **DRAFT, RECONCILED WITH DROP #62 OPTION C** — committed in the Phase 4 bootstrap PR for operational convenience. This DEVIATION is not filed against an executed change until alpha (or the operator) rewrites the body per §"Amendment 2026-04-15" below and completes §"Post-execution verification notes" at Phase 5a execution time (scope item 14 of the Phase 5a procedure).

---

## Amendment 2026-04-15 — drop #62 Option C reconciliation

> **Read this section before the body below.** The body of this DEVIATION as originally drafted describes a Hermes 3 **70B** substrate **swap** (Qwen removed, Hermes 70B installed on dual-GPU layer split). Drop #62 (`docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md`) resolves the LRR↔HSEA substrate conflict in favor of **Option C**: fork LRR Phase 5 into **5a (Hermes 3 8B parallel pivot, LRR-owned, primary)** and **5b (70B, deferred behind a hardware envelope gate, backlog)**. The governing authority is the `interpersonal_transparency` consent-latency axiom, which per drop #56 v3 makes the 70B layer-split path structurally unreachable on the current RTX 3090 + RTX 5060 Ti envelope.

### What the body below describes vs what gets filed

| | Original body (5b reference) | What DEVIATION-037 actually files at 5a execution time |
|---|---|---|
| **Change** | Swap: Qwen3.5-9B → Hermes 3 70B (3.0bpw, layer-split, 5060 Ti overflow) | **Additive**: Qwen3.5-9B stays; Hermes 3 8B EXL3 5.0bpw added on second TabbyAPI slot; `conversation_pipeline.py` dispatches on `active_model_family` field |
| **Claim tested** | `claim-shaikh-sft-vs-dpo` via 70B-on-top-of-Qwen | `claim-shaikh-sft-vs-dpo` via 8B-parallel-to-Qwen (same claim, different hardware envelope) |
| **Condition A'** | `cond-phase-a-prime-hermes-NNN` with `--substrate-model Hermes-3-Llama-3.1-70B-EXL3-3.0bpw` | `cond-phase-a-prime-hermes-8b-NNN` with `--substrate-model Hermes-3-Llama-3.1-8B-EXL3-5.0bpw` |
| **Reversibility** | Full Qwen rollback required if exit criteria fail (`scripts/phase-5-rollback.sh` restores `config.yml.qwen-backup`) | **Qwen never leaves** — rollback is `active_model_family=qwen` dispatch flip + LiteLLM Hermes-route disable. No Qwen config state is mutated. |
| **Operator adaptation confound** | HIGH (substrate swap is visible to operator as a single discrete change) | REDUCED (8B parallel is additive; operator can A/B the two substrates mid-session at dispatch granularity; ABA reversal structure preserved by dispatch flip) |
| **Latency envelope** | ~1s round-trip increase (Hermes 3 70B layer-split) — gated on ≤500ms consent-revocation regression | **Latency envelope should not regress at all** at 8B; 8B EXL3 5.0bpw on RTX 3090 is expected to be **faster** than the current Qwen single-slot path, per drop #56 v3 analysis. Gate still applies; expected to pass comfortably. |
| **VRAM budget** | ~23.5 GiB GPU 1 + ~2.75 GiB GPU 0 overflow | ~6–8 GiB GPU 1 additional for 8B slot, Qwen slot unchanged, daimonion STT unchanged on GPU 0 |
| **Rollback** | Promote `config.yml.qwen-backup` back; full systemd restart | Flip `active_model_family` default back to `qwen`; disable `local-fast-hermes`/`coding-hermes`/`reasoning-hermes` LiteLLM routes; no systemd restart required |
| **Constitutional implication** | `it-irreversible-broadcast` binds the swap as a broadcast event | Same implication binds 5a enablement; **additionally**, LRR Phase 6 formalizes *"any future 70B substrate decision must pre-register a consent-revocation drill and pass it before being authorized"* as a new constitutional amendment coupled to the `it-irreversible-broadcast` PR vehicle |

### What stays preserved from the 5b body

- **Research registry append-only invariant** — Condition A data is locked by Phase 4 regardless of 5a or 5b execution. `scripts/lock-phase-a-condition.py` does not change.
- **Frozen-files enforcement** — the Condition A' frozen-files list is identical in both variants (same grounding package files; the substrate swap is the only difference and the substrate itself is not a frozen file).
- **DVs and analysis methodology** — `turn_pair_coherence`, `context_anchor_success`, `acceptance_type`, `activation_score`, `sentinel_retrieval` are computed by the same `grounding_evaluator.py` code before and after 5a. BEST analysis (Kruschke 2013, HDI + ROPE) is unchanged.
- **Consent revocation drill + speech continuity test gates** — the exit criteria from Phase 5 spec §§3.2/3.3 apply verbatim to 5a. They were the right gates for *any* substrate change, not just 70B.
- **Condition A' is the claim test** — the claim is still `claim-shaikh-sft-vs-dpo`; the substrate family (SFT-only Hermes 3) is the manipulation. Going from 70B to 8B reduces the parameter-count confound on the Shaikh hypothesis (Mohapatra et al. 2024 show the SFT-vs-DPO effect is robust across scales), but does NOT retest or retract the claim.

### Rewrite scope at Phase 5a execution

When alpha files DEVIATION-037 at Phase 5a execution time (scope item 14 of the Phase 5a procedure), the following sections of the body below are **rewritten in place**:

1. **§"What Changed"** — the pre-swap/post-swap tables become "Qwen slot (unchanged)" and "Hermes 3 8B parallel slot (new)"; the "changes touched" table drops `config.yml` swap and `gpu-pin.conf` changes (both are 5b artifacts) and adds second TabbyAPI slot config + additive LiteLLM routes + `active_model_family` dispatch patch.
2. **§"Why"** — §"Theoretical grounding" bullet 2 ("Pre-training scale + SFT-only preservation") is rewritten: the parameter-count argument changes from 70B-vs-9B to 8B-vs-9B. Mohapatra et al. reference stays; the comparison becomes *"Hermes 3 8B SFT-only vs Qwen 9B DPO/GRPO, at near-identical parameter counts, isolates the post-training regime as the independent variable"*. This is **cleaner** than the 70B draft: 70B confounded parameter count with post-training regime; 8B removes that confound.
3. **§"Impact on Experiment Validity"** — "HIGH — but SCOPED and COMPENSATED" downgrades to **"MEDIUM — SCOPED, COMPENSATED, and CLAIM-REFINED"**. The 8B-vs-9B comparison is a stronger test of the SFT-vs-DPO claim than the 70B-vs-9B comparison, because it eliminates the parameter-count confound. The operator adaptation confound is reduced by the parallel-dispatch structure.
4. **§"Mitigation"** — the 3.5bpw fallback (a 70B-only concern) drops out. The 8B 5.0bpw quant needs no intermediate fallback; if it fails its gates, the rollback is the dispatch flip, not a bpw downgrade.
5. **§"Post-swap verification notes"** → **§"Post-execution verification notes"** — placeholders updated to reflect 5a (e.g., "8B slot active in TabbyAPI", "`active_model_family` default", "dispatch-flip rollback latency measured at N ms").

### Why the body below is retained verbatim through amendment time

The operator reads DEVIATION records in bulk at phase open. Keeping the original 70B body visible below the amendment header — rather than deleting it and writing a fresh 8B body — preserves traceability: a future reader can see exactly what was assumed at 2026-04-14 drafting time, what drop #62 changed, and what the 5a filing is. The 5b reference body also remains load-bearing if the hardware envelope ever changes and Phase 5b reactivates from backlog.

The rewrite described above is the **actual** DEVIATION filing, to be performed by alpha at Phase 5a scope item 14 with live verification data. The 5b reference body below it is the audit trail.

---

## What Changed

The underlying large language model serving the `local-fast` / `coding` / `reasoning` LiteLLM routes changed from **Qwen3.5-9B** (DPO + GRPO post-trained, EXL3 5.0 bpw, single-GPU on RTX 3090) to **Hermes 3 70B** (SFT-only post-trained, EXL3 3.0 bpw by default with 3.5 bpw fallback, layer-split across both GPUs via Option γ partition).

**Pre-swap substrate:**
- Model: `Qwen3.5-9B-exl3-5.00bpw`
- Backend: TabbyAPI (`~/projects/tabbyAPI/config.yml` pre-swap)
- Deployment: single-GPU on RTX 3090 (via Option α pre-partition, or GPU 1 under Option γ)
- VRAM footprint: ~15.6 GiB of 23.6 GiB (shared with daimonion faster-whisper STT + embeddings)
- Post-training regime: Qwen team's DPO (preference optimization) + GRPO stages

**Post-swap substrate:**
- Model: `Hermes-3-Llama-3.1-70B-EXL3-3.0bpw` (with `3.5bpw` fallback available)
- Backend: TabbyAPI (`~/projects/tabbyAPI/config.yml` post-swap, promoted from `config.yml.hermes-draft`)
- Deployment: layer-split across both GPUs under Option γ (`CUDA_VISIBLE_DEVICES=0,1` + `CUDA_DEVICE_ORDER=PCI_BUS_ID`)
- VRAM footprint: ~23.5 GiB on GPU 1 (3090), ~2.75 GiB on GPU 0 (5060 Ti) for overflow slice
- Post-training regime: NousResearch SFT-only (no DPO, no RLHF)
- Layer split: `gpu_split: [2.75, 23.5]` — beta empirically verified the device-index-to-card mapping via PyTorch matmul test 2026-04-14T15:30Z (see `~/.cache/hapax/relay/context/2026-04-14-beta-phase-3-supplement-verified-preconditions.md` § 1). The ordering is **corrected** from the original Hermes 3 plan's `[23.5, 2.75]` which would have OOMed the 5060 Ti.

**Changes touched (full list):**

| File | Change |
|---|---|
| `~/projects/tabbyAPI/config.yml` | `model_name` swapped; `gpu_split` added; `max_seq_len` tightened to 4096 per beta's supplement |
| `systemd/units/tabbyapi.service.d/gpu-pin.conf` | (landed Phase 3 PR #811) `CUDA_DEVICE_ORDER=PCI_BUS_ID` + `CUDA_VISIBLE_DEVICES=0,1` |
| `systemd/units/hapax-daimonion.service.d/gpu-pin.conf` | (landed Phase 3 PR #814) `CUDA_VISIBLE_DEVICES=0` — daimonion STT + embeddings move to GPU 0 to free GPU 1 for Hermes 3 |
| `litellm/config.yaml` | `local-fast`, `coding`, `reasoning` routes point at Hermes 3 TabbyAPI endpoint |
| `shared/config.py` MODELS dict | Same three aliases updated; `capable` tier (Claude Opus) explicitly preserved |

**Research registry transition:**

- **Condition closed:** `cond-phase-a-baseline-qwen-001` → `collection_halt_at` marker written by Phase 4 lock procedure (commit pre-staged in DEVIATION-038 work)
- **Condition opened:** `cond-phase-a-prime-hermes-NNN` via `scripts/research-registry.py open --slug phase-a-prime-hermes --substrate-model Hermes-3-Llama-3.1-70B-EXL3-3.0bpw --substrate-backend tabbyapi --claim-id claim-shaikh-sft-vs-dpo --frozen-files <same-as-Condition-A>`
- **Research marker SHM:** `/dev/shm/hapax-compositor/research-marker.json` updated atomically; `research_marker_changes.jsonl` gains a new entry at the swap timestamp

---

## Why

**The substrate swap IS the claim.** Per the LRR epic's Option B decision, formalize the Hermes 3 migration as a direct test of the Shaikh SFT-vs-DPO hypothesis (`claim-shaikh-sft-vs-dpo`). The original Qwen3.5-9B baseline and the Hermes 3 70B post-swap condition coexist as separate condition records in the append-only research registry (per P-3), not as sequential versions of the same experiment.

**Theoretical grounding (recap from the Hermes 3 voice architecture spec):**

1. **Mohapatra-Shaikh convergence.** Shaikh et al. (ACL 2025) report frontier LLMs average 23.23% on conversational grounding task-completion. Shaikh et al. (NAACL 2024) identify RLHF as a factor suppressing grounding acts — the DPO/GRPO stages optimize against preference signals that reward confident assertion over clarification. Mohapatra et al. (2024) show SFT-only pre-trained models exhibit stronger grounding behaviors than their DPO-tuned counterparts at comparable parameter counts.

2. **Pre-training scale + SFT-only preservation.** Hermes 3 70B is NousResearch's SFT-only variant of Llama-3.1-70B. At 70B parameters it has substantially more pre-training scale than the 9B Qwen baseline, and its lack of DPO/GRPO stages preserves the grounding-behavior signal that Shaikh's framework predicts.

3. **Null hypothesis falsification.** If Condition A' (Hermes 3) produces higher `turn_pair_coherence`, `context_anchor_success`, and `acceptance_type` DVs than Condition A (Qwen3.5-9B) at a pre-registered effect size, the Shaikh hypothesis is supported for this single-operator-system dyad. If the DVs are equivalent or regress, the hypothesis is not supported and Cycle 3 contingencies apply.

**Why a DEVIATION rather than just a version bump:**

Under the Cycle 2 pre-registration's frozen-file regime, the underlying LLM is part of the experimental apparatus. Changing it mid-phase would normally invalidate the ABA baseline-intervention-reversal design by introducing a confound. **Formalizing the swap as a DEVIATION reframes it as a deliberate experimental manipulation** — the pre-registered claim is now SFT-vs-DPO under identical grounding directives, not the original Phase A/B/A' design. Condition A and Condition A' become the comparison units; Phase B (intervention treatment flags) is held constant across both conditions.

---

## Impact on Experiment Validity

**Assessment: HIGH — but SCOPED and COMPENSATED.**

The swap is the largest single change the Cycle 2 experiment has seen. Unlike the metadata plumbing from DEVIATION-038 (validity impact: MINIMAL), this DEVIATION **fundamentally reframes the experiment from testing the grounding package on a single substrate to testing the grounding package across two substrates**.

**What is preserved (validity-positive):**

- **Grounding package implementation unchanged.** `grounding_ledger.py`, `grounding_evaluator.py`, `persona.py`, `conversational_policy.py` are all under DEVIATION-038's condition_id plumbing edit but otherwise behaviorally unchanged. The grounding directives, DU state machine, effort calibration, and acceptance classification all function identically.
- **DVs unchanged.** `turn_pair_coherence`, `context_anchor_success`, `acceptance_type`, `activation_score`, `sentinel_retrieval` are all computed by the same `grounding_evaluator.py` code before and after the swap.
- **BEST analysis methodology unchanged.** Comparison between Condition A and Condition A' uses the same Kruschke (2013) t-test with HDI + ROPE. Sample size targets are per-condition; there is no cross-condition pooling.
- **Frozen-file enforcement active across the swap.** Both conditions share the same frozen-files list; the pre-commit hook continues to block unauthorized mid-swap changes.
- **Append-only registry guarantees.** Condition A data (JSONL checksums + Qdrant snapshot + Langfuse score export) is locked by Phase 4's data integrity lock before the swap. Condition A data cannot be lost regardless of the swap's outcome.

**What is not preserved (validity-negative, compensated):**

- **Operator adaptation.** The operator experienced the Qwen3.5-9B substrate for the duration of Phase A collection. Post-swap, the operator's prior expectations become a confound — the operator may speak differently knowing that Hermes 3 is slower/faster/differently-trained. Compensation: single-case designs accept this class of confound as inherent to the operator-system dyad (see §3.3 of the pre-registration). The ABA reversal structure mitigates by re-testing under the original condition, but the swap eliminates that reversal (there is no "Condition A'' return to Qwen" planned).
- **Latency increase (~1 s round-trip).** Hermes 3 generation is slower than Qwen3.5-9B. The Phase 5 exit criteria include a consent-revocation drill that gates the swap on this: if revocation round-trip increases by > 500 ms, rollback is required. Scripts/phase-5-rollback.sh automates the rollback.
- **Cross-condition comparison requires both channels tagged.** DEVIATION-038 (prereq) ensures voice grounding DVs are tagged with `metadata.condition_id`. Without that, the voice channel would be analytically unreachable post-swap.

---

## Mitigation

**Pre-swap:**
- Phase 4 data integrity lock (`scripts/lock-phase-a-condition.py`) captures Condition A in three forms (JSONL checksums, Qdrant snapshot tar.gz, Langfuse score export). Condition A data cannot be lost. Pre-registered analysis can always be re-run against the locked data.
- 3.5 bpw fallback quant is available if 3.0 bpw fails the directive compliance benchmark. Rollback to Qwen is a last resort, not a first resort.
- Consent revocation drill + speech continuity test gate the swap on T0 governance risks before the swap is declared complete.

**During swap:**
- Research registry atomic A (`research-registry.py open`) writes the new condition + SHM marker BEFORE TabbyAPI restart. If the restart fails, the registry state is already correct for a retry.
- Research marker file is atomically written via tmp+rename; no partial-read race.
- TabbyAPI restart is under operator control (not a timer); the operator observes the model-load logs and can halt at any failure.

**Post-swap:**
- 10-minute Langfuse verification: new reactions must be tagged with `cond-phase-a-prime-hermes-NNN`.
- 1-hour Prometheus verification: per-condition score counts growing in both the director reaction channel and the voice grounding DV channel.
- 24-hour FD-leak verification: `compositor_process_fd_count` (once wired per drop #41 + pass-4 H-01) or `/proc/$pid/fd | wc -l` stable.
- Rollback procedures (both 3.5 bpw fallback and full Qwen rollback) are documented in the Phase 5 spec §6 and automated in `scripts/phase-5-rollback.sh`.

**Registers under:** claim `claim-shaikh-sft-vs-dpo`.

---

## Post-swap verification notes

**[FILL IN AT TASK 14 of the swap procedure — by alpha or operator]**

- Swap completed at: **[timestamp]**
- bpw active: **[3.0 or 3.5]**
- Directive compliance benchmark: **[N/5 directive, N/5 word limit]**
- Consent revocation drill envelope: **[ms pre-migration]** → **[ms post-migration]** → **[delta ms]**
- Speech continuity test: `compositor_audio_capture_dropped_frames_total` **[delta during 60s test]**
- Continuous cognitive loop check: director_loop tick cadence **[observed]**
- CAPABLE tier verification: `shared/config.py::MODELS["capable"]` resolves to **[Claude model]**
- Research registry current: **[cond-phase-a-prime-hermes-NNN]**
- First Condition A' Langfuse score observed at: **[timestamp]**
- First Condition A' Qdrant reaction observed at: **[timestamp]**

**Operator sign-off on the swap (required before the PR containing this DEVIATION is marked for merge):** **[signature / acknowledgment]**

---

**End of DEVIATION-037 draft.** Alpha / operator: when executing Phase 5, replace the `[FILL IN]` placeholders in §"Post-swap verification notes" with actual values, then commit the updated DEVIATION-037 as step 14 of the swap procedure. The draft body above does not need to change unless the swap deviates from the planned procedure.
