# Drop #62 Option C ratification — Hermes 3 substrate path

**Date:** 2026-04-15
**Author:** beta (autonomous LRR + cam-stability session continuation, identified as "real beta" in delta's 2026-04-15T04:45Z inflection)
**Authority:** operator direct confirmation via session terminal at 2026-04-15T04:40Z
**Status:** RATIFIED
**Scope:** Drop #62 §10 open question #1 only. Questions #2–#10 remain open.

---

## 1. What was ratified

Drop #62 §4 recommended resolving the LRR Phase 5 / HSEA Phase 4 I4 substrate conflict via **option (c)**: fork LRR Phase 5 into two unified phases:

> **AMENDMENT 2026-04-15T06:35Z — Hermes 3 abandoned entirely.** The operator terminated the Hermes 3 substrate path at 06:35Z with direction: *"We've abandoned hermes. Devote extensive research into if Qwen3.5-9B-exl3-5.00bpw is actually the best production substrate for our very unique use cases."* This supersedes **both** the 5a "live path" and the 5b "deferred backlog" framings below — neither variant of Hermes 3 is a future substrate path. Beta's commissioned 722-line substrate re-evaluation research at `docs/research/2026-04-15-substrate-reeval-post-hermes.md` (commit `bb2fb27ca` on `beta-phase-4-bootstrap`) recommends keeping Qwen3.5-9B as the production substrate + parallel-deploying OLMo 3-7B (SFT + DPO variants) for the Shaikh SFT-vs-DPO research claim. Neither recommendation is yet operator-ratified. Drop #62 §14 (delta, commit `2bc6aec17`) is the canonical audit-trail capture of this status change. **All downstream Hermes-specific artifacts in this PR — §4 draft systemd unit `tabbyapi-hermes8b.service`, §4.2 drop-in GPU-pin TODO, §5.1 draft LiteLLM `*-hermes` routes, §5.2 draft `tabbyAPI/config.yml.hermes-8b`, §6 9-step activation sequence — are dead-weight relative to the current substrate path** and should be treated as audit-trail reference material only. If the operator ratifies beta's research §9 primary recommendation (keep Qwen3.5-9B, fix thinking-mode / cache-warmup / exllamav3-upgrade production concerns), the 5a execution trajectory retires entirely. If the operator ratifies the complementary research §9 recommendation (parallel-deploy OLMo 3-7B on a second TabbyAPI slot), the same file structure shipped here is reusable with the model names and paths swapped. **Neither rewrite is needed now** — the structural scaffolding is what the activating session would rewrite at phase-open time anyway, and the Hermes-specific values are a find-and-replace exercise (`Hermes-3-Llama-3.1-8B-EXL3-5.0bpw` → whatever substrate wins, `5001` port stays, `config.yml.hermes-8b` → `config.yml.<substrate>-parallel`, etc.).

- **UP-7a (was LRR Phase 5):** Hermes 3 **8B parallel** pivot. Owner: LRR. Research-validity-load-bearing. Inherits all of LRR Phase 5's exit criteria (consent-revocation drill, speech-continuity drill, CAPABLE-tier preservation), executed against the 8B parallel config instead of the 70B layer-split. *(Superseded 06:35Z — see amendment above; this framing is historical.)*
- **UP-7b (deferred backlog, structurally unreachable per 2026-04-15T06:20Z operator direction):** Hermes 3 **70B** path. Originally gated on either (i) different hardware (PCIe Gen 5 dual-Blackwell, single-card 80GB Blackwell, or similar) or (ii) empirically demonstrated sub-2s 70B inference under the `interpersonal_transparency` consent-latency constraint. **Amendment 2026-04-15T06:30Z**: operator direction "1 hardware env unlikely to change within the year" collapses gate (i) on any realistic horizon; drop #56 v3's consent-latency analysis already blocks gate (ii) on the current envelope. Net: 5b has no plausible activation path. It remains in the repo as an **audit-trail reference procedure** only, not as a live backlog item. The 3.5bpw quant chain was killed at layer 57/80 at 06:25Z; GPU 1 released ~18 GB. Disk artifacts (~221 GB total: work dir, bf16 reference, completed 3.0bpw quant) flagged for operator disposition. Cross-ref beta's 2026-04-15T06:25Z inflection + alpha's 06:35Z ack inflection.

Drop #62 §10 lists 10 open operator questions; this doc ratifies **question #1 only**. Questions #2 (T2.8 guardrail DEVIATION cycle), #3 (HSEA Phase 4 rescoping), #4 (state file design), #5 (hapax-constitution PR vehicle), #6 (Cluster H timing), #7 (worktree allocation), #8 (research-stream-state.yaml authority), #9 (drop #62 doc path), #10 (phase ordering deviation tolerance) remain open and are **not** touched by this ratification.

## 2. Rationale (summarized from drop #62 §4 + drop #56 v3)

The 70B path was unreachable under the operator's own `interpersonal_transparency` consent-latency axiom before drop #62 was written. Drop #56 v3 established the bound: 70B layer-split inference on Blackwell + Ampere cannot meet the <2s consent-revocation round-trip the constitutional axiom requires. Drop #57 T2.6 reified this as "8B parallel, not swap." HSEA Phase 4 I4 codified the implementation sketch. Drop #62 §4 surfaced the three options and recommended option (c) as the cleanest path that preserves LRR's research integrity machinery while deleting the duplicate substrate code in HSEA Phase 4.

Option (a) — replace Phase 5 entirely with the 8B pivot — loses LRR Phase 5's exit criteria which are the right exit criteria for any substrate change, not just 70B. Rejected.

Option (b) — keep LRR Phase 5 as written, ship 70B via HSEA Phase 4 I4 with axiom precedent update — places substrate deployment in a drafter phase. Drafters don't deploy. Also ignores drop #56 v3. Rejected.

Option (c) — fork into 5a + 5b — preserves exit criteria, surfaces drop #56 v3 as a binding axiom decision, eliminates HSEA Phase 4 duplicate substrate code, leaves a clear path back to 70B if the hardware envelope changes, and makes the LRR/HSEA boundary cleaner (LRR ships substrate, HSEA narrates it). Accepted.

## 3. Downstream implications

### 3.1 LRR spec (NOT edited in this PR — already shipped on PR #819 branch)

The LRR spec at `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` on `main` still describes Phase 5 as the 70B layer-split path. LRR spec edits are owned by the PR #819 session on the `beta-phase-4-bootstrap` branch and **have already been shipped there** per the PR #819 author's 2026-04-15T05:00Z and 05:15Z inflections:

- **Commit `738fde330` on `beta-phase-4-bootstrap`** (2026-04-15T05:00Z) — initial reconciliation. 5 files changed, 176 insertions / 11 deletions, docs-only + docstring-only, zero runtime code. Added a new `§0.5 Amendment 2026-04-15 — drop #62 Option C resolution` to the Phase 5 spec, prepended an `Amendment 2026-04-15` section to `research/protocols/deviations/DEVIATION-037.md`, and added docstring amendment notes to `scripts/phase-5-pre-swap-check.py`, `scripts/phase-5-post-swap-smoke.py`, and `scripts/phase-5-rollback.sh` describing the 5a execution deltas. Conditional pending operator ratification at commit time.
- **Commit `156beef92` on `beta-phase-4-bootstrap`** (2026-04-15T05:15Z) — surgical ratification status flip. Two ~5-line edits: Phase 5 spec status line appended with "Option C RATIFIED by operator 2026-04-15 — the 5a/5b fork is now the authoritative scope for LRR Phase 5", and DEVIATION-037 status flipped from "DRAFT, RECONCILED WITH DROP #62 OPTION C" to "DRAFT — drop #62 Option C RATIFIED by operator 2026-04-15". The reconciliation bodies below each amendment header are unchanged.

The PR #819 author's approach preserves the 70B content verbatim under an amendment header so the audit trail is intact and the 5b reference procedure remains in the repo for when the hardware envelope changes. The §0.5.3 migration table in the Phase 5 spec enumerates the concrete deltas that apply to §§1–6 at 5a execution time (§1 Goal, §2 Prereqs, §3.1 Swap procedure, §3.2 Consent revocation drill, §3.3 Speech continuity, §3.4 CAPABLE tier, §4 Exit criteria, §5 Risks, §6 Rollback). The three Phase 5 scripts (`phase-5-pre-swap-check.py`, `phase-5-post-swap-smoke.py`, `phase-5-rollback.sh`) carry docstring-only amendment notes pointing at the spec §0.5 and DEVIATION-037 amendment; the script bodies themselves are rewritten at 5a execution time by the session that opens UP-7a.

The LRR spec edits will appear on `main` when PR #819 merges. Until then, the spec on `main` continues to describe the 70B path; the ratification is captured on the branch, not on the main line.

### 3.2 HSEA spec and plan (already edited in drop #62)

Drop #62's commit already applied the §9 edits to both HSEA spec and HSEA plan (Section 0, 1, 2, 4, 6, 8 in the spec; Section 1, 4, 8 in the plan). No further edits are needed to reflect option (c). The HSEA spec header still says "DRAFT — awaiting operator sign-off before Phase 0 open" because questions #2–#10 from drop #62 §10 remain open; option (c)'s confirmation does not release the sign-off gate.

### 3.3 HSEA Phase 4 cluster I rescoping (partial)

Confirmation of option (c) implies that HSEA Phase 4 sub-drafters **I4a / I4b / I4c** are demoted to narration-only spectator agents (they watch LRR Phase 5a's 8B pivot landing and draft a research drop summarizing it). Rough LOC delta on HSEA Phase 4: **−600 LOC** from the three I4 sub-drafters alone. This is a subset of drop #62 §10 question #3 (the full rescoping across I1–I5 is still pending). Treat I4 as resolved; I1/I2/I3/I5 still need operator confirmation separately.

### 3.4 DEVIATION-037 content

The `DEVIATION-037` document (currently pending on PR #819) should describe the **8B pivot** rationale + reference to drop #56 v3 + reference to the consent-latency axiom, **not** the 70B procedure. The real beta session (PR #819 author) should update the DEVIATION draft before PR #819 merges.

### 3.5 OSF pre-registration amendment

The OSF amendment (drop #57 T2.7, current LRR Phase 4 item 4) should explicitly name the **8B arm as the C2 condition** in the pre-registration; the original 70B language is replaced or annotated. This is operator action through the OSF portal, not code.

### 3.6 Axiom precedent

LRR Phase 6 (UP-8) governance pass should formalize the rule: "any future 70B substrate decision must pre-register a consent-revocation drill and pass it before being authorized." This lands in the same `it-irreversible-broadcast` PR vehicle.

## 4. Repo scaffolding shipped in this PR

Two draft systemd artifacts for the second TabbyAPI instance. **Neither is deployed.** They exist as pre-staging for LRR Phase 5a execution; the session that opens UP-7a will review, adjust GPU allocation per empirical verification, and deploy.

### 4.1 `systemd/units/tabbyapi-hermes8b.service` (new, draft)

Second-instance TabbyAPI unit running Hermes 3 8B on port 5001, isolated from the existing `tabbyapi.service` (Qwen 3.5-9B on port 5000). `WorkingDirectory` points at the existing `tabbyAPI/` sibling checkout using a per-instance `--config` override so the second instance reads `config.yml.hermes-8b` instead of the default `config.yml`.

### 4.2 `systemd/units/tabbyapi-hermes8b.service.d/gpu-pin.conf` (new, draft)

GPU pin drop-in. **TODO marker:** the specific `CUDA_VISIBLE_DEVICES` + `CUDA_DEVICE_ORDER` values need empirical verification before deployment. Current Option γ allocation (both GPUs visible for 70B layer-split) is wrong for 8B parallel — each instance should pin to a different single GPU. The draft drop-in captures the two candidate configurations with operator-choice TODO markers.

## 5. Host-side artifacts NOT in this PR (operator activation needed)

The following edits are on host paths outside the council git repo and must be applied manually by the operator after reviewing this ratification. Draft content is embedded below so the activating session does not need to re-derive it from drop #62.

### 5.1 LiteLLM gateway config — additive routes

Append these entries to `model_list` in the host-side LiteLLM config file:

```yaml
  # Local models via TabbyAPI (second instance, Hermes 3 8B on :5001)
  - model_name: local-fast-hermes
    litellm_params:
      model: openai/Hermes-3-Llama-3.1-8B-EXL3-5.00bpw
      api_base: http://172.18.0.1:5001/v1
      api_key: "dummy"
      extra_body:
        chat_template_kwargs:
          enable_thinking: false

  - model_name: coding-hermes
    litellm_params:
      model: openai/Hermes-3-Llama-3.1-8B-EXL3-5.00bpw
      api_base: http://172.18.0.1:5001/v1
      api_key: "dummy"
      extra_body:
        chat_template_kwargs:
          enable_thinking: false

  - model_name: reasoning-hermes
    litellm_params:
      model: openai/Hermes-3-Llama-3.1-8B-EXL3-5.00bpw
      api_base: http://172.18.0.1:5001/v1
      api_key: "dummy"
      extra_body:
        chat_template_kwargs:
          enable_thinking: true
```

And append these fallback entries to `litellm_settings.fallbacks`:

```yaml
    - reasoning-hermes: [reasoning, claude-sonnet, claude-opus]
    - coding-hermes: [coding, claude-sonnet, claude-opus]
    - local-fast-hermes: [local-fast, gemini-flash, claude-haiku]
```

The `*-hermes` routes fall back to the existing Qwen `local-fast`/`coding`/`reasoning` routes first, which is the key "parallel" property: when Hermes is down, the council degrades to Qwen instead of cloud. This is the drop #56 v3 assumption.

### 5.2 TabbyAPI second-instance config file (new, host-side draft)

Place at the `tabbyAPI/` sibling checkout root as `config.yml.hermes-8b`:

```yaml
# Hermes 3 Llama 3.1 8B EXL3 5.0bpw — tabbyAPI draft config (parallel pivot)
#
# LRR Phase 5a (unified sequence UP-7a). This file is the staged
# config for the SECOND TabbyAPI instance serving Hermes 3 8B
# alongside the existing Qwen 3.5-9B instance on port 5000.
#
# DO NOT swap in this config as config.yml on the main instance.
# Instead, the new systemd unit `tabbyapi-hermes8b.service` will
# run a second TabbyAPI process pointing at this file via a
# `--config` override.
#
# Prerequisites:
#   1. Hermes 3 8B EXL3 5.0bpw weights at
#      tabbyAPI/models/Hermes-3-Llama-3.1-8B-EXL3-5.0bpw/
#   2. GPU allocation decision per the drop-in TODO in
#      systemd/units/tabbyapi-hermes8b.service.d/gpu-pin.conf
#   3. LiteLLM config reloaded with the three additive routes per
#      docs/research/2026-04-15-drop-62-option-c-ratification.md §5.1
#
# Exit criteria (inherited from LRR Phase 5):
#   - Consent-revocation drill passes under <2s end-to-end
#   - Speech-continuity drill: zero dropped frames during long gen
#   - CAPABLE-tier preservation: no cloud fallback for voice

logging:
  log_generation_params: false
  log_prompt: false
  log_requests: true
model:
  backend: exllamav3
  cache_mode: Q8
  cache_size: 4096
  chunk_size: 2048
  inline_model_loading: false
  max_seq_len: 8192
  model_dir: models
  model_name: Hermes-3-Llama-3.1-8B-EXL3-5.0bpw
network:
  api_servers:
  - OAI
  disable_auth: true
  host: 0.0.0.0
  port: 5001
sampling:
  override_preset: safe_defaults
```

### 5.3 Weight download (operator action)

The Hermes 3 8B EXL3 5.0bpw weights do not exist on disk. The operator must either self-quantize from a reference fp16 download or pull an existing community quant. Disk cost: ~5 GB. Approximate download time: minutes on a fast link.

## 6. Activation sequence (after operator weight drop)

1. Operator pulls or self-quants Hermes 3 8B EXL3 5.0bpw weights into the `tabbyAPI/models/Hermes-3-Llama-3.1-8B-EXL3-5.0bpw/` directory.
2. Operator copies the §5.2 draft to `tabbyAPI/config.yml.hermes-8b`.
3. Operator decides GPU allocation (see §4.2 TODO) and edits `systemd/units/tabbyapi-hermes8b.service.d/gpu-pin.conf` accordingly.
4. Operator runs `scripts/install-units.sh` to install the new unit, then `systemctl --user daemon-reload`.
5. Operator appends the §5.1 routes to the host-side LiteLLM config and restarts the `litellm-council` container.
6. Operator starts `tabbyapi-hermes8b.service` and verifies via `curl http://localhost:5001/v1/models`.
7. Operator runs the consent-revocation drill and speech-continuity drill (LRR Phase 5 exit criteria, inherited).
8. Session opens `cond-phase-a-prime-hermes-8b-002` in the research registry (requires LRR Phase 1 shipped first) and files `DEVIATION-037` with the 8B pivot rationale.
9. `conversation_pipeline.py` dispatch on `active_model_family` is added in a separate DEVIATION-gated PR (this file is currently FROZEN under the active research condition; touching it requires the new condition opened in step 8).

## 7. What option C does NOT do

- Does not open UP-7a. The 8B pivot is only possible once LRR Phase 1 (research registry) has landed because `DEVIATION-037` depends on the registry.
- Does not download weights. Operator action.
- Does not touch `conversation_pipeline.py`. That file is FROZEN; dispatch code needs a new research condition first.
- Does not update the host-side LiteLLM config live. The additive routes are drafted above; operator appends and reloads.
- Does not resolve drop #62 §10 questions #2–#10. Those remain open.
- Does not commit to a specific GPU allocation. The scaffolding drop-in carries a TODO.

## 8. Trace

- Drop #54 (speculative Bayesian analysis)
- Drop #55 (grounded single-axis Bayesian analysis)
- Drop #56 v3 (novelty + platform value correction; established the 70B-unreachable axiom bound)
- Drop #57 T2.6 (8B parallel as a tactic)
- Drop #58 (HSEA thesis; I4 drafters proposed)
- Drop #59 (audit of drop #58)
- Drop #60 + #61 (HSEA epic spec + plan)
- Drop #62 §4 (three options; (c) recommended)
- Delta 2026-04-15T04:45Z inflection (HSEA + fold-in shipped summary + "For beta (PR #819 author)" guidance cross-referenced above)
- Operator confirmation to this session via "8" keyword response, 2026-04-15T04:40Z
- PR #819 beta 2026-04-15T05:00Z inflection + commit `738fde330` (initial reconciliation, conditional)
- Operator confirmation to the PR #819 session via "ratified" keyword response, 2026-04-15T05:10Z (same decision, second session)
- PR #819 beta 2026-04-15T05:15Z inflection + commit `156beef92` (ratification status flip)
- Delta 2026-04-15T05:05Z identity-correction inflection (maps this session as "alpha" in the post-rename naming; pivots delta to complementary HSEA Phase 0 doc extraction)
- **This doc + PR #826:** complementary main-branch artifacts — decision record + draft systemd scaffolding + embedded host-config drafts. Non-overlapping with PR #819's `beta-phase-4-bootstrap` branch edits.
- **2026-04-15T06:20Z operator direction "1 hardware env unlikely to change within the year"** — collapses 5b's gate (i) hardware-envelope-change hedge on the year horizon, confirming 5b is structurally unreachable. Beta's 06:25Z inflection documents the 3.5bpw quant kill at layer 57/80, GPU 1 release, and the ~221 GB operator-disposition cleanup queue (work dir + bf16 reference + completed 3.0bpw quant).
- Alpha's 2026-04-15T06:35Z ack inflection + `beta.yaml::quant_state` update + the §1 amendment note in this PR materialize the reframing from "deferred backlog" to "structurally unreachable reference procedure."

— End of ratification record.
