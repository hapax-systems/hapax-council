# LRR Phase 5 — Substrate Scenario 1+2 (re-spec post-§16 ratification)

**Spec date:** 2026-04-15
**Author:** alpha (AWB mode, queue/ item #138)
**Supersedes:** `docs/superpowers/specs/2026-04-14-lrr-phase-5-hermes-3-substrate-swap-design.md` (lives on `beta-phase-4-bootstrap`; Hermes framing structurally obsolete per drop #62 §14)
**Ratification:** operator-ratified at 2026-04-15T18:21Z per drop #62 §16
**Status:** re-spec, pre-execution. Replaces the Hermes 3 70B substrate swap framing with dual-track substrate scenarios 1+2.

## 0. Context

LRR Phase 5 was originally specified on 2026-04-14 as "Hermes 3 70B Substrate Swap" — see the LRR epic spec `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` § Phase 5 (lines 531-632) and the standalone spec `2026-04-14-lrr-phase-5-hermes-3-substrate-swap-design.md` on `beta-phase-4-bootstrap`.

Two ratifications subsequently reframed Phase 5:

1. **Drop #62 §14** (2026-04-15T06:35Z) — operator abandoned Hermes 3 70B. The 3.5bpw quant chain attempt was killed; no viable Hermes 70B configuration fits the 24 GB VRAM envelope with the current service mix. Hermes is permanently dropped from the research-substrate pool.

2. **Drop #62 §16** (2026-04-15T18:21Z) — operator ratified substrate scenarios 1 + 2 in parallel as the replacement path. Scenario 1 keeps Qwen3.5-9B in production + upgrades exllamav3 + runs RIFTS empirical. Scenario 2 parallel-deploys OLMo 3-7B in three training-regime variants (SFT, DPO, RLVR) to enable the `claim-shaikh` cycle 2 isogenic test.

This re-spec replaces the Hermes framing with the dual-track scenario 1+2 framing. The pre-existing §0.5 amendment on beta's spec (Option C resolution + consent revocation drill + speech continuity test) remains load-bearing for the engineering discipline it encodes; those sections are preserved conceptually below, rescoped from "Hermes swap" to "substrate scenario 1 + 2 parallel deployment."

## 1. Phase goal

**Deploy the research substrate pair defined by drop #62 §16 — Qwen3.5-9B (scenario 1, production-verified) + OLMo 3-7B × {SFT, DPO, RLVR} (scenario 2, research) — both served from TabbyAPI, and complete enough validation to unblock LRR Phase 6 (governance finalization) + Phase B substrate comparison (`claim-shaikh` cycle 2 isogenic test).**

This is **not** a single swap from one substrate to another. It is a **parallel deployment** of one production substrate + one research substrate triad. Both remain live. LiteLLM routes expose them as distinct model aliases.

## 2. Prerequisites

Before Phase 5 opens:

- **Drop #62 §16 ratification** must be on main — ✓ shipped via PR #895 (queue #137, commit `349bf536f`)
- **Substrate research v2** must be on main — ✓ shipped at `docs/research/2026-04-15-substrate-reeval-v2-post-verification.md`
- **Substrate research v1** should be cherry-picked to main — ⏳ queue item #144 (pending)
- **Substrate research v2 errata** (beta's `d33b5860c`) — ⏳ optional, branch-only is acceptable
- **RIFTS harness** (beta's `3a7672bd1`) — ⏳ likely a separate cherry-pick follow-up
- **Phase 4 close** — Phase A baseline data collection complete (currently Phase A is READY but not started per RESEARCH-STATE.md)
- **exllamav3 runtime** must be upgradable from 0.0.23 → 0.0.29 in the TabbyAPI venv (operator-authorized per §16)

## 3. Scope

### 3.1 Scenario 1 — Qwen3.5-9B production + RIFTS empirical

**Keep Qwen3.5-9B on TabbyAPI as the production serving substrate.** No swap. The substrate that currently serves `local-fast` / `coding` / `reasoning` routes remains in place.

**Substrate verification tasks:**

1. **Upgrade exllamav3 runtime** in TabbyAPI venv from 0.0.23 → 0.0.29. Includes bug fixes + KVZip compatibility improvements. Operator-authorized.
2. **Restart TabbyAPI** after venv upgrade. Verify all three routes (`local-fast`, `coding`, `reasoning`) still serve without behavioral regression.
3. **Download RIFTS dataset** (~2 GB) to `~/hapax-state/benchmarks/rifts/`. Dataset is the research-grade conversational grounding evaluation benchmark cited in beta's substrate research v2.
4. **Run RIFTS empirically against Qwen3.5-9B.** Full benchmark run via a new harness script (`scripts/run-rifts-benchmark.py`, ~100 LOC). Captures grounding accuracy + latency + behavioral markers. Writes results to `~/hapax-state/benchmarks/rifts/qwen3_5_9b_baseline.json`.
5. **Document findings** in a research drop at `docs/research/2026-04-XX-rifts-qwen-baseline.md`. Findings become Phase 5 exit evidence.

**Why scenario 1 is not a no-op:** Phase A baseline (Cycle 2) needs empirical grounding performance for Qwen3.5-9B documented against a research-grade dataset. RIFTS provides that. Without it, Phase A findings are uncalibrated against the literature.

### 3.2 Scenario 2 — OLMo 3-7B × 3 variants parallel-deployed

**Add three new TabbyAPI routes** alongside Qwen3.5-9B:

- `local-research-sft` — OLMo 3-7B SFT variant
- `local-research-dpo` — OLMo 3-7B DPO variant  
- `local-research-rlvr` — OLMo 3-7B RLVR variant

**Deployment tasks:**

1. **Download OLMo 3-7B weights** for all three variants from AllenAI (Hugging Face). Approximately 12 GB × 3 = 36 GB total.
2. **Quantize each variant to EXL3 5.0bpw** using the exllamav3 conversion pipeline. Target bpw is 5.0 (matches Qwen3.5-9B production serving quality). Each quant takes ~2 hours wall-clock on the RTX workstation.
3. **Configure TabbyAPI** to serve all four models (Qwen + 3 OLMo variants). This likely requires model-switching mode (one loaded at a time) or split-VRAM (multiple loaded concurrently if VRAM allows).
4. **Add three new LiteLLM routes** to `~/llm-stack/litellm-config.yaml`:
   ```yaml
   - model_name: local-research-sft
     litellm_params:
       model: openai/OLMo-3-7B-SFT-exl3-5.00bpw
       api_base: http://172.18.0.1:5000/v1
   - model_name: local-research-dpo
     litellm_params:
       model: openai/OLMo-3-7B-DPO-exl3-5.00bpw
       api_base: http://172.18.0.1:5000/v1
   - model_name: local-research-rlvr
     litellm_params:
       model: openai/OLMo-3-7B-RLVR-exl3-5.00bpw
       api_base: http://172.18.0.1:5000/v1
   ```
5. **Restart LiteLLM** container to pick up new routes.
6. **Smoke test each route** with a simple chat completion. Confirm TabbyAPI serves + LiteLLM proxies successfully.

### 3.3 `claim-shaikh` cycle 2 isogenic test setup

**The OLMo 3-7B variant triad is the experimental substrate for `claim-shaikh-sft-vs-dpo-vs-rlvr`** (the cycle 2 claim, renamed from the original `claim-shaikh-sft-vs-dpo` to reflect the three-way regime comparison).

This test is **isogenic**: all three OLMo variants share architecture + pretraining data, differing only in post-training regime. It is the cleanest test of "does training regime affect conversational grounding" that the substrate landscape currently offers. Hermes 3's abandonment closed the original SFT-only vs DPO comparison; OLMo's three-variant release opens a richer three-way comparison.

**Phase 5 ships:** the substrate itself + a claim stub in `research/claims/claim-shaikh-sft-vs-dpo-vs-rlvr.yaml` documenting the new test design. Running the test is **Phase B work** (post-Phase-5), not Phase 5 scope.

### 3.4 Consent revocation drill (preserved from beta's §0.5 body)

**Critical exit criterion, rescoped to scenario 1+2:** before any substrate change (either adding OLMo routes OR upgrading exllamav3 OR swapping a loaded model), verify that consent revocation still works end-to-end.

**Procedure:**
1. Register an active consent contract via `shared/consent.py` for a test non-operator person
2. Make the substrate change (e.g., upgrade exllamav3, restart TabbyAPI)
3. Verify `ConsentRegistry.contract_check()` still returns the active contract
4. Verify `AffordancePipeline.select()` still filters consent-required capabilities correctly
5. Revoke the contract via the ConsentRegistry API
6. Verify subsequent `select()` calls fail-close within 60s (cache TTL)

**Why this is Phase 5 scope:** the consent gate is a T0 axiom enforcement point (interpersonal_transparency axiom, weight 88). Any substrate change that breaks consent-gate behavior is a blocker. The LRR Phase 6 joint constitutional PR bundles the `it-irreversible-broadcast` implication + the 70B reactivation guard rule; Phase 5's consent revocation drill is a pre-requisite exit criterion for that Phase 6 work.

### 3.5 Speech continuity test (preserved from beta's §0.5 body)

**Critical exit criterion, unchanged:** while TabbyAPI is restarted during scenario 1 exllamav3 upgrade OR during scenario 2 OLMo quant loading, `hapax-daimonion` should continue to serve speech (STT on GPU, TTS on CPU via Kokoro 82M) without dropping the operator's conversational session.

**Procedure:**
1. Start a conversation with daimonion
2. While daimonion is in mid-conversation, restart TabbyAPI
3. Verify daimonion gracefully degrades (falls back to Claude/Gemini cloud routes via LiteLLM fallback chain)
4. Verify no operator speech is dropped (per the `never drop operator speech` memory)
5. After TabbyAPI is back, verify daimonion resumes using local routes

### 3.6 CAPABLE tier preservation check (preserved)

Per memory `feedback_model_routing_patience.md`, the CAPABLE tier (claude-opus) must never be downgraded for speed. Verify that LiteLLM config after scenario 2 OLMo route additions does NOT introduce any fallback from `claude-opus` to `local-research-*`. The OLMo routes are research substrate, not a performance fallback.

**Procedure:** `curl` the litellm container's `/models` endpoint + inspect fallback chains in `~/llm-stack/litellm-config.yaml`. Confirm `claude-opus` fallback chain is `[claude-sonnet, gemini-pro]` only, never adding any local route.

### 3.7 Continuous cognitive loop preservation check (preserved)

Per memory `feedback_cognitive_loop.md`, the voice cognitive loop must run continuously during conversation. Verify that substrate changes (Qwen restart, OLMo quant load, LiteLLM route addition) do NOT cause the daimonion CPAL loop to stop and wait for utterance boundaries.

**Procedure:** monitor `/dev/shm/hapax-daimonion/cpal-heartbeat.txt` (or equivalent) during substrate changes. Heartbeat should update at its normal cadence (~10 Hz) without pauses.

### 3.8 Kokoro TTS baseline — unchanged from original Phase 5

Kokoro 82M TTS baseline was captured 2026-04-14 by `scripts/kokoro-baseline.py` (Cold synth 29.8 s, warm p50 2253.9 ms, warm RTF p50 0.415). This baseline is **not Phase 5 scope to re-run** unless the exllamav3 upgrade or OLMo deployment changes Kokoro performance characteristics. Spot-verify post-scenario-1 + post-scenario-2.

## 4. Exit criteria

Phase 5 closes when **all** of the following are true:

1. **Scenario 1 shipped:**
   - `exllamav3` upgraded to 0.0.29 in TabbyAPI venv
   - TabbyAPI restarted + all three routes (`local-fast`, `coding`, `reasoning`) serving correctly
   - RIFTS dataset downloaded to `~/hapax-state/benchmarks/rifts/`
   - RIFTS benchmark run against Qwen3.5-9B; results written to `qwen3_5_9b_baseline.json`
   - Research drop at `docs/research/2026-04-XX-rifts-qwen-baseline.md` documenting findings
2. **Scenario 2 shipped:**
   - OLMo 3-7B weights downloaded for all three variants (SFT, DPO, RLVR)
   - All three variants quantized to EXL3 5.0bpw
   - TabbyAPI configured to serve all four models (Qwen + 3 OLMo)
   - LiteLLM routes `local-research-sft`, `local-research-dpo`, `local-research-rlvr` added + tested
   - Smoke-test chat completion for each OLMo route succeeds
3. **Drills passed:**
   - Consent revocation drill passes (§3.4)
   - Speech continuity test passes (§3.5)
   - CAPABLE tier preservation confirmed (§3.6)
   - Continuous cognitive loop preservation confirmed (§3.7)
4. **Claim stub authored:**
   - `research/claims/claim-shaikh-sft-vs-dpo-vs-rlvr.yaml` drafted with cycle 2 test design
5. **Deviation record updated:**
   - `DEVIATION-037.md` (originally: Hermes 3 70B substrate swap) is amended or superseded by `DEVIATION-037a.md` (scenario 1+2 framing)

## 5. Risks + mitigations

### 5.1 VRAM pressure from 4-model deployment

**Risk:** Qwen3.5-9B + 3 × OLMo 3-7B cannot all be loaded concurrently within the 24 GB VRAM envelope. TabbyAPI model-switching mode (one loaded at a time) is the fallback.

**Mitigation:** plan for model-switching from day one. TabbyAPI supports it natively. Smoke-test one variant at a time. Concurrent loading is a nice-to-have, not required.

### 5.2 exllamav3 upgrade breaks KVZip compatibility

**Risk:** `0.0.29` is a minor version bump but the KVZip integration (per `2026-04-12-kvzip-exllamav3-compatibility.md` research drop) depends on specific exllamav3 API surface. Upgrade could break KVZip.

**Mitigation:** run the KVZip benchmark (`scripts/benchmark_prompt_compression_b6.py`) post-upgrade; rollback to 0.0.23 if KVZip benchmarks regress. Document in Phase 5 execution notes.

### 5.3 OLMo 3-7B variants behave differently from Qwen3.5-9B

**Risk:** the `claim-shaikh` cycle 2 test requires all four models to be comparable on a common evaluation. If OLMo and Qwen behave on fundamentally different dimensions, the claim becomes unfalsifiable.

**Mitigation:** run a behavioral calibration step before the isogenic test — evaluate all four models on a shared corpus (e.g., the RIFTS dataset) and confirm they are on the same quality tier. Document findings in Phase B.

### 5.4 Phase A data collection is paused during exllamav3 upgrade

**Risk:** Phase A baseline requires a stable Qwen3.5-9B substrate. If Phase A is actively running during the Phase 5 exllamav3 upgrade, the baseline data could be corrupted by mid-run model changes.

**Mitigation:** **Phase A must be fully halted before Phase 5 execution starts.** This is enforced by the LRR Phase 4 "collection_halt_at" marker + the experiment-freeze-manifest.

## 6. Open questions

1. **Does the exllamav3 0.0.29 upgrade require a Qwen EXL3 re-quant?** Need to verify; some minor-version upgrades require re-quantizing the model from the original weights.
2. **Does TabbyAPI support 4 loaded models concurrently in 24 GB VRAM?** Quantization at 5.0bpw means ~6 GB per model; 4 × 6 = 24 GB with no headroom. Likely requires model-switching.
3. **Does AllenAI publish pre-quantized OLMo 3-7B EXL3 weights?** Would skip the quantization step. Check Hugging Face.
4. **Can RIFTS be run without TabbyAPI restart?** If yes, RIFTS scenario 1 can ship in parallel with OLMo scenario 2.

These are execution-time questions, not blockers for the re-spec.

## 7. Cross-references

- **Drop #62 §14** (Hermes abandonment): `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md` §14
- **Drop #62 §16** (scenario 1+2 ratification): `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md` §16 (shipped PR #895, queue #137, commit `349bf536f`)
- **Substrate research v2** (on main): `docs/research/2026-04-15-substrate-reeval-v2-post-verification.md`
- **Substrate research v1** (on beta-phase-4-bootstrap): commit `bb2fb27ca` — queue #144 cherry-picks to main
- **Substrate research v2 errata** (on beta-phase-4-bootstrap): commit `d33b5860c` — optional cherry-pick
- **RIFTS harness** (on beta-phase-4-bootstrap): commit `3a7672bd1` — likely separate follow-up
- **Pre-existing Phase 5 spec** (on beta-phase-4-bootstrap, Hermes framing, superseded): `docs/superpowers/specs/2026-04-14-lrr-phase-5-hermes-3-substrate-swap-design.md`
- **LRR epic spec § Phase 5** (outdated framing, needs amendment): `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` lines 531-632
- **Cohabitation reconciliation patch** (Phase 6 related): queue #127 `docs/research/2026-04-15-lrr-phase-6-0.5-block-patch.md`
- **Cross-epic dependency graph** (needs drift patch post-§16): queue #122 `docs/research/2026-04-15-cross-epic-dependency-graph.md`
- **RESEARCH-STATE.md** (needs drift patch post-§16): queue #121 update
- **Phase 7/8/9 prep inventory** (needs drift patch post-§16): queue #131

## 8. What this spec does NOT do

- **Does not execute Phase 5.** Execution happens post-merge of this spec, likely in a new session focused on Phase 5 opener work.
- **Does not amend beta's Hermes-framed Phase 5 spec on the cohabitation branch.** Per cohabitation protocol, beta's branch files are left alone. This new spec lives on main as the authoritative Phase 5 framing going forward.
- **Does not amend the LRR epic spec** (`2026-04-14-livestream-research-ready-epic-design.md`). That file is docs-frozen per CLAUDE.md LRR research-condition enforcement; a separate follow-up would amend § Phase 5 to point at this new standalone spec.
- **Does not write DEVIATION-037 updates.** That is a Phase 5 execution task.
- **Does not author `claim-shaikh-sft-vs-dpo-vs-rlvr.yaml`.** That is a Phase 5 execution task + Phase B work.

## 9. Closing

LRR Phase 5 is re-spec'd from "Hermes 3 70B substrate swap" to "substrate scenario 1+2 dual-track deployment" per drop #62 §16 operator ratification. The new scope is scenario 1 (Qwen3.5-9B + exllamav3 upgrade + RIFTS) + scenario 2 (OLMo 3-7B × 3 variants parallel-deploy enabling `claim-shaikh` cycle 2 isogenic test). Critical engineering disciplines from the prior Hermes-framed spec (consent revocation drill, speech continuity, CAPABLE tier preservation, cognitive loop continuity) are preserved and rescoped.

— alpha, 2026-04-15T20:10Z (queue #138)
