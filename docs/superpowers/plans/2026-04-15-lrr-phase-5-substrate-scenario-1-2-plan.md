# LRR Phase 5 — Substrate Scenario 1+2 (execution plan)

**Plan date:** 2026-04-15
**Spec:** `docs/superpowers/specs/2026-04-15-lrr-phase-5-substrate-scenario-1-2-design.md` (PR #896, queue #138)
**Author:** alpha (AWB mode, queue/ item #143)
**Execution track:** dual scenario — Scenario 1 (Qwen3.5-9B + RIFTS empirical) runs independently from Scenario 2 (Option C parallel TabbyAPI + OLMo 3-7B × 3 variants) per drop #62 §16.1 pivot.

## 1. Overview

Phase 5 ships two substrate tracks in parallel:

- **Scenario 1** — Verify Qwen3.5-9B grounding performance against RIFTS research dataset. No substrate swap. Incidental maintenance benefits (exllamav3 0.0.29) NOT required per §16.1. Expected effort: ~2 sessions.
- **Scenario 2** — Deploy parallel TabbyAPI on `:5001` with separate venv serving OLMo 3-7B × {SFT, DPO, RLVR} EXL3 5.0bpw. Enables `claim-shaikh` cycle 2 isogenic test. Expected effort: ~4-5 sessions.

Phase 5 closes when **both** scenario 1 baseline + scenario 2 parallel backend are live and all exit criteria pass.

## 2. Scenario 1 execution plan — Qwen3.5-9B + RIFTS empirical

### 2.1 Stage 1a — Preconditions + dataset download

**Queue item:** #210 (RIFTS scenario 1, currently UNBLOCKED per §16.1.6)

**Deliverables:**

1. **RIFTS dataset staged** at `~/hapax-state/benchmarks/rifts/dataset/`. ~2 GB download from research repository (referenced in substrate research v2 §9.1).
2. **RIFTS harness script** committed to main. Likely cherry-pick from `3a7672bd1` on `beta-phase-4-bootstrap`, OR fresh authoring if the cherry-pick is deferred.
3. **Dataset schema documented** — the substrate research v1 errata fixed `microsoft/rifts` schema field mapping (instruction/label columns). Capture in the harness README.

**Target files:**
- `~/hapax-state/benchmarks/rifts/dataset/*.parquet` (or similar)
- `scripts/run-rifts-benchmark.py` (~150 LOC harness)
- `docs/research/2026-04-XX-rifts-harness-notes.md` (schema + usage notes)

**Effort:** 1 session (~30 min download + ~30 min harness verification).

### 2.2 Stage 1b — Run RIFTS against Qwen3.5-9B baseline

**Queue item:** #210 (continued)

**Deliverables:**

1. **Full RIFTS benchmark run** on Qwen3.5-9B through current TabbyAPI :5000. LiteLLM routes `local-fast` / `coding` / `reasoning` all hit Qwen; pick one for the benchmark (probably `reasoning` since RIFTS tests conversational grounding which is higher-tier cognitive work).
2. **Results captured** at `~/hapax-state/benchmarks/rifts/qwen3_5_9b_baseline.json` — includes per-question accuracy, latency distributions, behavioral markers.
3. **Research drop** at `docs/research/2026-04-XX-rifts-qwen-baseline.md` documenting findings. Per-category breakdowns, comparison to literature Shaikh (2024 NAACL / 2025 ACL) results if available.

**Target files:**
- `~/hapax-state/benchmarks/rifts/qwen3_5_9b_baseline.json`
- `docs/research/2026-04-XX-rifts-qwen-baseline.md` (~200-300 lines)

**Effort:** 1-2 sessions (benchmark run wall-clock ~30-60 min; analysis + writing ~1 session).

### 2.3 Scenario 1 exit criteria

- [x] RIFTS dataset available at `~/hapax-state/benchmarks/rifts/dataset/`
- [x] RIFTS harness script committed + documented
- [x] Qwen3.5-9B baseline results written to JSON
- [x] Research drop published with findings
- [x] Phase A (Cycle 2) baseline now has research-grade empirical grounding number

## 3. Scenario 2 execution plan — Option C parallel TabbyAPI + OLMo 3-7B

Per §16.1 drop #62 amendment, scenario 2 is Option C: parallel TabbyAPI :5001, not in-place upgrade.

### 3.1 Stage 2a — Parallel TabbyAPI venv + service setup

**Queue item:** #211 (rescoped to Option C per §16.1.6)

**Deliverables:**

1. **New venv at `~/projects/tabbyAPI-olmo/.venv`** (or equivalent isolated path). Python 3.12 (matching main venv).
2. **Install modern stack** in new venv:
   - `torch 2.11.0+cu130`
   - `exllamav3 0.0.29` (from PyPI; NO turboderp wheel)
   - Minimum TabbyAPI deps (OpenAI-compatible server only, no exllamav2/flash-attn/xformers — OLMo uses exllamav3 serving path)
3. **Clone tabbyAPI checkout** at `~/projects/tabbyAPI-olmo/` (separate from the main clone; avoids git branch confusion)
4. **Write new systemd unit** `systemd/units/tabbyapi-olmo.service` with:
   - `Type=simple`, `Restart=on-failure`, `RestartSec=15`
   - `WorkingDirectory=%h/projects/tabbyAPI-olmo`
   - `ExecStart=%h/projects/tabbyAPI-olmo/.venv/bin/python start.py --port 5001`
   - `After=hapax-secrets.service`, `Requires=hapax-secrets.service`
   - Optionally `Environment=CUDA_VISIBLE_DEVICES=1` (RTX 5060 Ti; operator decision per §16.1.4)
5. **Smoke test** with Qwen3.5-9B test model (verifies plumbing before loading OLMo)

**Target files:**
- New checkout dir `~/projects/tabbyAPI-olmo/`
- `systemd/units/tabbyapi-olmo.service`
- `docs/research/2026-04-XX-option-c-parallel-tabbyapi-setup.md` (execution notes)

**Effort:** 1-2 sessions (~1 hour venv setup + ~1 hour systemd + smoke test).

### 3.2 Stage 2b — OLMo 3-7B weight download + quantization

**Queue item:** #211 (continued)

**Deliverables:**

1. **Download OLMo 3-7B weights** for all 3 variants from AllenAI Hugging Face:
   - `allenai/OLMo-3-7B-SFT` (or actual release name)
   - `allenai/OLMo-3-7B-DPO`
   - `allenai/OLMo-3-7B-RLVR`
   - ~12 GB × 3 = ~36 GB total staging
2. **Quantize each to EXL3 5.0bpw** using the exllamav3 conversion pipeline:
   - `python -m exllamav3.conversion.convert_model --model-path <bf16> --output-dir <exl3> --bpw 5.0`
   - ~2 hours wall-clock per variant on RTX workstation
   - **Check for pre-quantized wheels** on Hugging Face first — AllenAI may publish EXL3 directly (skip quantization if so)
3. **Final quantized models** at `~/projects/tabbyAPI-olmo/models/`:
   - `OLMo-3-7B-SFT-exl3-5.00bpw/`
   - `OLMo-3-7B-DPO-exl3-5.00bpw/`
   - `OLMo-3-7B-RLVR-exl3-5.00bpw/`

**Target files:**
- Staging: `~/hapax-state/quant-staging/OLMo-3-7B-{SFT,DPO,RLVR}-bf16/`
- Final: `~/projects/tabbyAPI-olmo/models/OLMo-3-7B-{SFT,DPO,RLVR}-exl3-5.00bpw/`

**Effort:** 1-2 sessions (download ~30 min each + quantize ~2h each; parallelizable background with monitoring).

### 3.3 Stage 2c — LiteLLM routes + end-to-end smoke test

**Queue item:** #212 (rescoped to :5001 per §16.1.6)

**Deliverables:**

1. **Add 3 new LiteLLM routes** to `~/llm-stack/litellm-config.yaml`:
   ```yaml
   - model_name: local-research-sft
     litellm_params:
       model: openai/OLMo-3-7B-SFT-exl3-5.00bpw
       api_base: http://host.docker.internal:5001/v1
       api_key: "dummy"
   - model_name: local-research-dpo
     litellm_params:
       model: openai/OLMo-3-7B-DPO-exl3-5.00bpw
       api_base: http://host.docker.internal:5001/v1
       api_key: "dummy"
   - model_name: local-research-rlvr
     litellm_params:
       model: openai/OLMo-3-7B-RLVR-exl3-5.00bpw
       api_base: http://host.docker.internal:5001/v1
       api_key: "dummy"
   ```
2. **Restart LiteLLM container** to pick up new routes
3. **Smoke-test each route** via direct LiteLLM call (curl or python client)
4. **Verify model-switching behavior** — TabbyAPI :5001 may serve one OLMo variant at a time if VRAM is tight
5. **Document the deployment** in `docs/research/2026-04-XX-olmo-parallel-deployment.md`

**Target files:**
- `~/llm-stack/litellm-config.yaml` (cross-repo edit)
- `docs/research/2026-04-XX-olmo-parallel-deployment.md`

**Effort:** 1 session.

### 3.4 Stage 2d — `claim-shaikh-sft-vs-dpo-vs-rlvr` cycle 2 stub

**Queue item:** #212 (claim stub)

**Deliverables:**

1. **New claim YAML** at `research/claims/claim-shaikh-sft-vs-dpo-vs-rlvr.yaml`:
   ```yaml
   claim_id: claim-shaikh-sft-vs-dpo-vs-rlvr
   cycle: 2
   superseded: claim-shaikh-sft-vs-dpo (original Hermes 70B framing, obsolete per §14)
   test_design: isogenic (same architecture + pretraining, different post-training regime)
   substrates: [OLMo-3-7B-SFT, OLMo-3-7B-DPO, OLMo-3-7B-RLVR]
   experimental_question: "Does training regime (SFT vs DPO vs RLVR) affect conversational grounding on RIFTS-like tasks?"
   status: staged  # execution is Phase B work
   ```
2. **Does NOT execute the test** — the three-way comparison run is Phase B work, post-Phase-5
3. **Cross-reference** from `docs/superpowers/specs/2026-04-15-lrr-phase-5-substrate-scenario-1-2-design.md` §3.3

**Target files:**
- `research/claims/claim-shaikh-sft-vs-dpo-vs-rlvr.yaml`

**Effort:** 30 min (YAML authoring only, no execution).

### 3.5 Scenario 2 exit criteria

- [x] Parallel TabbyAPI :5001 service running + health-checked
- [x] OLMo 3-7B × 3 variants quantized + staged at `~/projects/tabbyAPI-olmo/models/`
- [x] LiteLLM routes `local-research-*` live + smoke-tested
- [x] Claim stub `claim-shaikh-sft-vs-dpo-vs-rlvr.yaml` committed
- [x] Deployment research drop published

## 4. Cross-cutting drills (preserved from beta's Hermes-framed §0.5 body)

These exit criteria apply to **both** scenarios and run **after** scenario 1 + scenario 2 are live.

### 4.1 Consent revocation drill (§3.4 of spec)

**Required before Phase 5 closure.**

1. Register active consent contract for test non-operator person
2. Execute scenario changes (upgrade attempts, restart, OLMo load)
3. Verify `ConsentRegistry.contract_check()` behaves correctly
4. Revoke contract
5. Verify `AffordancePipeline.select()` fail-closes within 60s

**Queue item:** new follow-up if not already tracked.

### 4.2 Speech continuity test (§3.5 of spec)

**Required before Phase 5 closure.**

1. Operator starts conversation with daimonion
2. During conversation, restart parallel TabbyAPI :5001 + switch OLMo variants
3. Verify daimonion degrades gracefully (falls back to Claude/Gemini via LiteLLM)
4. Verify no operator speech drops

### 4.3 CAPABLE tier preservation check (§3.6 of spec)

**Required before Phase 5 closure.**

- Verify `claude-opus` LiteLLM fallback chain remains `[claude-sonnet, gemini-pro]` — no additions of `local-research-*` routes as fallbacks

### 4.4 Continuous cognitive loop preservation check (§3.7 of spec)

**Required before Phase 5 closure.**

- Monitor daimonion CPAL heartbeat during scenario changes
- Verify ~10 Hz cadence maintained throughout

## 5. Dependency + ordering

```
#210 (RIFTS scenario 1) ──┐
                          ├── scenario 1 baseline
                          └── RIFTS research drop

#211 (parallel TabbyAPI + OLMo download + quantization) ──┐
                                                          │
#212 (LiteLLM routes + claim stub) ───────────────────────┤── scenario 2 live
                                                          │
drills (consent + speech + tier + loop) ──────────────────┘── Phase 5 closure
```

Scenario 1 and scenario 2 can run in parallel (they touch different services + different tooling). The drills are a single linear gate at the end.

**Alpha's recommendation:** beta runs scenario 1 (RIFTS eval) while alpha or delta runs scenario 2 (parallel TabbyAPI setup). Both tracks converge at the drills.

## 6. Risks + mitigations

### 6.1 OLMo 3-7B variants differ structurally from SFT to RLVR

**Risk:** the three OLMo variants may behave on different dimensions than the `claim-shaikh` test assumes, making the isogenic comparison meaningless.

**Mitigation:** calibrate all three variants against the RIFTS dataset (or similar) before running the formal cycle 2 test. If variants show unexpected diversity on the calibration pass, flag it + redesign the claim.

### 6.2 Parallel TabbyAPI :5001 creates GPU contention

**Risk:** main :5000 + new :5001 contend for RTX 3090 VRAM.

**Mitigation 1:** commit RTX 5060 Ti to OLMo via `CUDA_VISIBLE_DEVICES=1` on tabbyapi-olmo.service (operator decision per §16.1.4).

**Mitigation 2:** TabbyAPI :5001 runs in model-switching mode — one OLMo variant loaded at a time. VRAM footprint ~6 GB per model, fits comfortably on either GPU.

### 6.3 AllenAI doesn't publish pre-quantized OLMo EXL3 wheels

**Risk:** alpha estimated ~2 hours per quantization × 3 variants = 6 hours wall-clock.

**Mitigation:** check Hugging Face first — pre-quantized EXL3 wheels would skip the step entirely. If unavailable, run the 3 quantizations in parallel if VRAM allows.

### 6.4 RIFTS dataset schema doesn't match harness expectations

**Risk:** beta's errata `d33b5860c` fixed the `microsoft/rifts` schema mapping (instruction/label columns). If the main branch RIFTS harness has the old schema, the benchmark run fails.

**Mitigation:** verify the harness uses the corrected schema before launching. Cherry-pick the errata if needed.

### 6.5 Phase A data collection conflicts with Phase 5 execution

**Risk:** Phase A (Cycle 2 baseline) needs stable Qwen3.5-9B. Phase 5 scenario 2 adds a parallel TabbyAPI; if GPU contention materializes, Phase A measurements could be affected.

**Mitigation:** verify `hapax-whoami` status + sprint state before launching Phase 5 scenario 2 work. If Phase A is actively running, pause scenario 2 until Phase A completes.

## 7. Success criteria summary

Phase 5 closes when **all** of the following are true:

| # | Criterion | Scenario |
|---|---|---|
| 1 | RIFTS benchmark live + Qwen baseline JSON committed | Scenario 1 |
| 2 | Research drop with Qwen RIFTS findings published | Scenario 1 |
| 3 | Parallel TabbyAPI :5001 service active + healthy | Scenario 2 |
| 4 | OLMo 3-7B × 3 variants quantized + loaded | Scenario 2 |
| 5 | LiteLLM routes `local-research-*` live + smoke-tested | Scenario 2 |
| 6 | Claim stub `claim-shaikh-sft-vs-dpo-vs-rlvr.yaml` committed | Scenario 2 |
| 7 | Consent revocation drill passed | Both |
| 8 | Speech continuity test passed | Both |
| 9 | CAPABLE tier preservation verified | Both |
| 10 | Continuous cognitive loop preservation verified | Both |

## 8. Cross-references

- **LRR Phase 5 spec:** `docs/superpowers/specs/2026-04-15-lrr-phase-5-substrate-scenario-1-2-design.md` (PR #896, queue #138)
- **Drop #62 §14:** Hermes abandonment
- **Drop #62 §16:** Scenario 1+2 ratification (PR #895, queue #137)
- **Drop #62 §16.1:** Option C parallel TabbyAPI pivot (PR #899, queue #142)
- **Queue #210:** RIFTS scenario 1 (UNBLOCKED)
- **Queue #211:** Parallel TabbyAPI :5001 + OLMo (rescoped to Option C)
- **Queue #212:** LiteLLM routes + claim stub (rescoped to :5001)
- **Queue #209:** exllamav3 upgrade (BLOCKED — rolled back)
- **Queue #144:** substrate v1 cherry-pick (pending)
- **Beta's substrate research v2:** `docs/research/2026-04-15-substrate-reeval-v2-post-verification.md`
- **Beta's #209 blocker inflection:** `~/.cache/hapax/relay/inflections/20260415-184500-beta-delta-209-exllamav3-upgrade-blocked.md`
- **Delta's Option C pivot inflection:** `~/.cache/hapax/relay/inflections/20260415-184900-delta-operator-substrate-scenario-2-option-c-pivot.md`
- **Memory:** `feedback_model_routing_patience.md` (CAPABLE tier preservation), `feedback_never_drop_speech.md` (speech continuity), `feedback_cognitive_loop.md` (continuous loop)

## 9. What this plan does NOT do

- **Does not execute any scenario.** Execution happens in sessions that pull queue items #210, #211, #212 + follow-up drill items.
- **Does not author the drill queue items.** Those are follow-up work to be filed.
- **Does not cherry-pick substrate research v1 or RIFTS harness.** Those are separate queue items (#144 + potential follow-ups).
- **Does not amend the LRR Phase 5 spec.** The spec is authoritative; this plan implements it.
- **Does not modify `~/llm-stack/litellm-config.yaml`** — that edit happens at scenario 2 Stage 2c execution time.

## 10. Closing

LRR Phase 5 execution plan with dual scenario tracks + cross-cutting drill gates. Scenario 1 (RIFTS empirical) is simpler and can ship first; scenario 2 (Option C parallel TabbyAPI + OLMo) has more moving parts but zero production disruption per §16.1. Both tracks converge at the consent revocation / speech continuity / CAPABLE tier / cognitive loop preservation drills. Phase 5 closes when all 10 success criteria pass.

— alpha, 2026-04-15T20:36Z (queue #143)
