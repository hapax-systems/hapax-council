# LRR Phase 5 — Hermes 3 Substrate Swap (design)

**Date:** 2026-04-14 CDT (original 70B draft) / 2026-04-15 (drop #62 Option C amendment)
**Author:** beta (pre-staged during LRR Phase 4 bootstrap; operator ratifies at phase open)
**Parent epic spec:** `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` §Phase 5
**Parent migration plan:** `docs/superpowers/plans/2026-04-10-hermes3-70b-migration.md` (Tasks 1–13; retained as the 5b reference; 5a will rewrite the dispatch model)
**Theoretical grounding:** `docs/superpowers/specs/2026-04-10-hermes3-70b-voice-architecture-design.md`
**DEVIATION authority for the substrate swap:** `research/protocols/deviations/DEVIATION-037.md` (pre-staged as a draft; filing is scope item 14 of the 5a procedure)
**Status:** DRAFT — spec pre-staged on `beta-phase-4-bootstrap` branch. **Reconciled with drop #62 Option C 2026-04-15** (see §0.5). **Option C RATIFIED by operator 2026-04-15** — the 5a/5b fork is now the authoritative scope for LRR Phase 5. Remainder of the spec's ratification (substrate-specific parameters, exit-criteria pass, DEVIATION-037 filing) moves to Phase 5a open time.

---

## 0.5 Amendment 2026-04-15 — drop #62 Option C resolution (RATIFIED)

> **Operator ratification 2026-04-15:** the operator has ratified drop #62 Option C. The 5a/5b fork described in this section is now the authoritative scope for LRR Phase 5. Drop #62 §10 question 1 ("substrate swap fork confirmation") is closed in favor of Option C. Delta is expected to update drop #62 with an addendum documenting the decision per delta's inflection `20260415-044500-delta-hsea-epic-cross-epic-fold-in-shipped.md` §"What delta will do if you reply".

> **Read this section before §§1–6 below.** The original body of this spec targets a 70B substrate swap. Drop #62 (`docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md`, delta) establishes — citing drop #56 v3 and the `interpersonal_transparency` consent-latency axiom — that **the 70B path is unreachable under the operator's own constitutional axiom**. 70B layer-split inference on the current RTX 3090 + RTX 5060 Ti envelope cannot meet the sub-2s consent-revocation round-trip the axiom requires. This is not a tunable; it is a structural gate.

### 0.5.1 The Option C resolution

Drop #62 §4 forks LRR Phase 5 into two phases:

- **Phase 5a — Hermes 3 8B parallel pivot (primary path, LRR-owned).** A second TabbyAPI instance (or a second model slot in the existing instance) serving Hermes 3 8B EXL3 5.0bpw. Additive LiteLLM routes (`local-fast-hermes`, `coding-hermes`, `reasoning-hermes`). `conversation_pipeline.py` dispatches on an `active_model_family` field. The Qwen3.5-9B substrate is NOT removed — Condition A and Condition A' run side-by-side via dispatch, not substrate swap. This satisfies drop #56 v3's 8B pivot recommendation and drop #57 T2.6 (additive, not replace). **This is the phase that ships.**

- **Phase 5b — Hermes 3 70B path (deferred backlog).** Retained as a documented future path, gated on a hardware envelope change: (i) PCIe Gen 5 dual-Blackwell, (ii) single-card 80GB Blackwell, or (iii) sub-2s 70B inference demonstrated empirically on *some* envelope. Until one of those gates trips, 5b is not a Phase, it is a backlog item. The original body of this spec (§§1–6) is the 5b reference procedure.

### 0.5.2 What this means for the body of this spec

Sections §§1–6 below were drafted against the 70B swap assumption. **They are not deleted**, for three reasons:

1. The exit criteria (§4: consent-revocation drill ≤500ms over pre-migration envelope, speech-continuity zero-drop, CAPABLE tier preservation, continuous cognitive loop) are the right exit criteria for *any* substrate change, not just 70B. Phase 5a inherits all of them verbatim.
2. The rollback procedures (§6) are the template for 5a's "disable the 8B parallel config" rollback, which is structurally simpler (it's a dispatch flip, not a config revert).
3. The 5b reference procedure remains load-bearing for the backlog item — if the hardware envelope ever changes, 5b reactivates without re-research.

### 0.5.3 Phase 5a deltas from the 5b body below

When alpha executes Phase 5a (at phase open time, after Phase 4 Condition A is locked), the following concrete deltas apply to the §§1–6 body below:

| Section | 5b (original) | 5a (Option C) |
|---|---|---|
| §1 Goal | Swap TabbyAPI from Qwen to Hermes 3 70B | Stand up Hermes 3 8B parallel alongside Qwen via dispatch; Qwen stays as co-active substrate |
| §2 Prereqs | 70B 3.0bpw + 3.5bpw quants present | Hermes 3 8B EXL3 5.0bpw quant present (the 70B rows are 5b-only) |
| §3.1 Swap procedure | 16-step 70B swap via `config.yml.hermes-draft` promotion | 16-step additive deploy: second TabbyAPI slot/instance, `local-fast-hermes`/`coding-hermes`/`reasoning-hermes` LiteLLM routes, `active_model_family` field, per-turn dispatch. Research registry atomic A opens `cond-phase-a-prime-hermes-8b-NNN` with `--substrate-model Hermes-3-Llama-3.1-8B-EXL3-5.0bpw` |
| §3.2 Consent revocation drill | Gate the swap on ≤500ms regression | **Same gate**, now measured against the 8B parallel path. The 8B path must meet it (which, per drop #56 v3 analysis, it can) |
| §3.3 Speech continuity | Gate on zero dropped frames during 60s continuous utterance | **Same gate**, now measured against 8B parallel |
| §3.4 CAPABLE tier | `local-fast`/`coding`/`reasoning` → Hermes 3 70B | `local-fast-hermes`/`coding-hermes`/`reasoning-hermes` → Hermes 3 8B; legacy `local-fast`/`coding`/`reasoning` remain on Qwen; CAPABLE still Opus |
| §4 Exit criteria | VRAM footprint ~23.5 GiB on GPU 1 from 70B | VRAM footprint ~6–8 GiB on GPU 1 from 8B EXL3 5.0bpw; Qwen slot unchanged |
| §5 Risks | 70B OOM on 5060 Ti overflow; layer-split device-mapping inversion | 8B-on-top-of-Qwen VRAM coexistence; dispatch-field-race on first enable |
| §6 Rollback | Promote `config.yml.qwen-backup` back | Flip `active_model_family` default back to `qwen`; disable Hermes 3 LiteLLM routes; no Qwen state was ever lost because Qwen never left |

### 0.5.4 Axiom precedent action (LRR Phase 6 coupling)

Drop #62 §3 row 11 couples this to LRR Phase 6: the governance pass must formalize the rule *"any future 70B substrate decision must pre-register a consent-revocation drill and pass it before being authorized."* That rule goes into the `hapax-constitution` `it-irreversible-broadcast` PR vehicle alongside HSEA's `sp-hsea-mg-001` precedent. Epsilon's Phase 6 pre-staged spec (committed in this same PR at `c945b78f2`) already lists the constitutional amendment as scope item 1 — the drop #62 reconciliation slots into that existing item as a concrete sub-clause.

### 0.5.5 HSEA Phase 4 I4 demotion (informational)

Drop #62 §4 also demotes HSEA Phase 4 cluster I4 from "Hapax drafts the 8B pivot code" to "Hapax narrates LRR Phase 5a's 8B pivot landing, drafts a research drop summarizing the substrate change, and routes it through the governance queue." This is HSEA's problem, not LRR's, but LRR Phase 5a authors should know that HSEA I4 is a downstream spectator and should plan the 5a landing timestamps to give HSEA's narrator a clean event stream to watch.

### 0.5.6 DEVIATION-037 rewrite scope

The pre-staged `research/protocols/deviations/DEVIATION-037.md` draft is likewise reconciled via its own amendment header. Its body below this amendment remains the 5b reference; when DEVIATION-037 is filed at Phase 5a execution time (scope item 14), alpha rewrites the "What Changed" / "Why" / "Impact on Experiment Validity" bodies to describe the 8B parallel pivot. The drop #62 amendment in DEVIATION-037 pre-declares this rewrite so the bookkeeping is clean.

### 0.5.7 Script parameterization deferred

The three pre-staged Phase 5 scripts (`phase-5-pre-swap-check.py`, `phase-5-post-swap-smoke.py`, `phase-5-rollback.sh`) each carry their own §0 amendment header noting they target 5b by default. At 5a execution time, alpha either (a) rewrites them in place with `--variant 5a` plumbing, or (b) copies them to `phase-5a-*` siblings and keeps the 5b versions as a backlog artifact. Neither decision needs to be made at pre-stage time.

---

## 0. Context

Phase 5 is the substrate swap from Qwen3.5-9B (DPO/GRPO post-trained) to Hermes 3 70B (SFT-only) running on TabbyAPI via EXL3 layer-split across both GPUs. Under LRR's Option B, **the swap IS the claim** (`claim-shaikh-sft-vs-dpo`) — it is not a confound to be controlled for, it is the experimental manipulation. The Condition A → Condition A' boundary is a research-marker atomic write during an active livestream run.

The authoritative swap procedure is `docs/superpowers/plans/2026-04-10-hermes3-70b-migration.md` (Tasks 1–13). This spec adds:

- **Three research-registry atomics** that weave Task 6 (TabbyAPI restart) through the research registry so the swap is observable as a discrete event in the audit log.
- **Additional exit criteria from the audit** (consent revocation drill, speech-continuity test, CAPABLE tier preservation).
- **Rollback procedures** at two levels (3.5bpw fallback without going back to Qwen, full Qwen rollback).
- **Operational scripts** for pre-swap verification and post-swap smoke testing.

This spec is the operational checklist alpha runs at Phase 5 open. Its role vs the migration plan: the plan tells you *how* to do the tasks; this spec tells you *when* to do them, *what* to check before and after, *what the exit criteria are*, and *how to roll back*.

---

## 1. Goal (recap)

Execute the Hermes 3 migration plan. Swap the local inference substrate from Qwen3.5-9B to Hermes 3 70B SFT-only via EXL3 layer-split. Mark the Condition A→A' boundary in the research registry. File DEVIATION-037. Pass the consent revocation drill + speech continuity test + directive compliance benchmark before declaring the swap complete.

If the drill, test, or benchmark fails, rollback is required, not optional.

---

## 2. Prerequisites

| Prereq | Verified by | Blocking? |
|---|---|---|
| Phase 4 complete: Condition A locked, JSONL checksums + Qdrant snapshot + Langfuse score export captured | `scripts/lock-phase-a-condition.py` exit 0 + `data-checksums.txt` exists | YES |
| Phase 3 runtime partition Option γ active on tabbyapi + hapax-daimonion | `systemctl --user show tabbyapi -p Environment` returns `CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=0,1`; same for daimonion with `CUDA_VISIBLE_DEVICES=0` | YES |
| Hermes 3 70B EXL3 quant present at expected path | `ls ~/projects/tabbyAPI/models/Hermes-3-Llama-3.1-70B-EXL3-3.0bpw/model-*.safetensors` returns 4+ shards | YES |
| Hermes 3 70B EXL3 3.5bpw fallback present | `ls ~/projects/tabbyAPI/models/Hermes-3-Llama-3.1-70B-EXL3-3.5bpw/` same check | NO (required only for 3.5 bpw rollback path; Phase 5 can open with only 3.0 bpw present) |
| TabbyAPI `config.yml.hermes-draft` staged in tabbyAPI clone | `test -f ~/projects/tabbyAPI/config.yml.hermes-draft` | YES |
| DEVIATION-037 draft ready | `test -f research/protocols/deviations/DEVIATION-037.md` (pre-staged by beta, committed in this PR) | NO (draft is on disk; filing is scope item 14) |
| Operator available (swap is high-risk, do not run unattended) | operator acknowledgment | YES |
| Current `RESEARCH-STATE.md` saved + last commit clean | `git status` shows no unstaged changes in `agents/hapax_daimonion/proofs/` | YES |
| Frozen-files manifest list for Condition A' validated | `yq '.frozen_files' ~/hapax-state/research-registry/cond-phase-a-prime-hermes-NNN/condition.yaml` matches the Condition A list (same files, same content) | YES (can be verified post-open) |

**Pre-swap verification script:** `scripts/phase-5-pre-swap-check.py` (pre-staged in a follow-up commit on this PR) walks the table above and exits non-zero on any unmet prerequisite.

---

## 3. Scope

The swap procedure is a 16-step sequence composed of Tasks 1–13 from the migration plan plus three research-registry atomics inserted at specific points. Every step has a verification check; the operator does not proceed to the next step until the current one verifies clean.

### 3.1 Swap procedure

| # | Step | Migration Plan Task | Registry atomic? | Verification |
|---|---|---|---|---|
| 1 | Driver / CUDA validation | Task 1 | no | `nvidia-smi` shows both GPUs + CUDA 12.8+ |
| 2 | Hermes 3 70B EXL3 download / quant verification | Task 2 | no | sha256 match against quant manifest + `file config.json` |
| 3 | TabbyAPI config swap — promote `config.yml.hermes-draft` → `config.yml` | Task 3 | no | `diff` against pre-swap backup shows expected model_name + gpu_split changes only |
| 4 | TabbyAPI systemd unit timeout update (Phase 3 drafted) | Task 4 | no | `systemctl --user cat tabbyapi` shows `TimeoutStartSec=180` |
| 5 | LiteLLM routes update (`local-fast`/`coding`/`reasoning` → Hermes 3) | Task 5 | no | `shared/config.py` diff; verify CAPABLE tier (Claude Opus) **NOT** changed |
| **6** | **Research registry atomic A — open new condition BEFORE TabbyAPI restart** | — | **YES** | `scripts/research-registry.py open --slug phase-a-prime-hermes --substrate-model Hermes-3-Llama-3.1-70B-EXL3-3.0bpw --substrate-backend tabbyapi --claim-id claim-shaikh-sft-vs-dpo --frozen-files <same-as-Condition-A>` → writes `cond-phase-a-prime-hermes-NNN/` + updates SHM marker + appends to `research_marker_changes.jsonl` |
| 7 | TabbyAPI restart | Task 6 | no | `systemctl --user restart tabbyapi` + wait for active state |
| 8 | Model load verification | Task 6 (continued) | no | `curl localhost:5000/v1/models` returns Hermes 3 + `nvidia-smi` shows expected VRAM distribution (GPU 1 ~23.5 GiB, GPU 0 ~2.75 GiB from overflow) |
| 9 | STT coexistence validation on GPU 0 | Task 7 | no | `nvidia-smi` shows daimonion faster-whisper on GPU 0 without OOM |
| 10 | Route STT to GPU 0 if needed | Task 8 | no | daimonion logs show faster-whisper on `cuda:0` |
| 11 | Full voice pipeline smoke test | Task 9 | no | operator says "test one two three" → transcript → response → TTS, end-to-end under 4s |
| 12 | Documentation update | Task 10 | no | workspace `CLAUDE.md` reflects Hermes 3 as the local-fast/coding/reasoning substrate |
| 13 | Directive compliance benchmark (go/no-go) | Task 11 | no | `scripts/phase-5-post-swap-smoke.py --benchmark` (pre-staged) runs 5 directive-compliance prompts, asserts ≥ 3/5 pass the directive + ≥ 4/5 pass the word-limit check |
| **14** | **Research registry atomic B — DEVIATION-037 filing** | — | **YES** | `research/protocols/deviations/DEVIATION-037.md` is committed. Beta pre-staged the draft; alpha commits it at Task 14 with the actual post-swap verification notes added. |
| **15** | **Research registry atomic C — RESEARCH-STATE.md update** | — | **YES** | Prepend a new dated entry referencing DEVIATION-037 + condition transition + benchmark results |
| 16 | Relay status update (alpha.yaml or beta.yaml) | — | no | `updated` timestamp refreshed + `workstream` updated to reflect Phase 5 complete |

### 3.2 Consent revocation drill (critical exit criterion)

**Before declaring Phase 5 complete**, the operator performs the consent revocation drill:

1. Measure pre-migration consent revocation envelope from the most recent pre-migration revocation event (from `~/hapax-state/stream-reactions-*.jsonl` or Langfuse trace logs — the envelope is the wall-clock time from the operator's "revoke" utterance to the compositor's consent-gated shutdown of the video recording path).
2. After Hermes 3 swap, say "revoke [test contract]" on-stream.
3. Measure the full cascade:
   - STT captures the utterance → `conversation_pipeline` classifies the acceptance label → `grounding_evaluator` scores → `ConsentRegistry` mutation → contract moves to `contract-*.revoked.yaml` → `AffordancePipeline.select()` sees the revocation and drops the gated capability → livestream reaction on the compositor reflects the new consent state.
4. **Exit criterion:** full cascade within **500 ms** of the pre-migration envelope. If slower, rollback is required (not optional).

**Rationale:** per `feedback_consent_latency_obligation` memory — *"voice latency impeding consent flow is a governance violation, not a UX issue."* Hermes 3's slower generation CANNOT compromise consent flow even if other DVs improve.

### 3.3 Speech continuity test (critical exit criterion)

**Before declaring Phase 5 complete**, the operator performs the speech continuity test:

1. Start a Hermes 3 long-generation response (e.g., ask for a 3-paragraph explanation of Clark's contribution-acceptance cycle).
2. Operator speaks continuously for 60 seconds during the response generation.
3. **Exit criterion:** `compositor_audio_capture_dropped_frames_total` Prometheus counter shows **zero increment** during the test window. Verify via `curl 127.0.0.1:9482/metrics | grep compositor_audio_capture_dropped_frames_total` before and after.

**Rationale:** per `feedback_never_drop_speech` memory — *"Operator speech must NEVER be dropped by cooldown/buffer. Use AEC, not frame dropping."* Hermes 3's slower serialized STT→LLM→TTS pipeline could introduce backing pressure on the STT buffer.

### 3.4 CAPABLE tier preservation check

`shared/config.py` defines model aliases. The substrate swap changes `local-fast`, `coding`, and `reasoning` but **must NOT change `capable`**.

Verification (automated by `scripts/phase-5-post-swap-smoke.py --capable-check`):

```python
from shared.config import MODELS
assert MODELS["capable"].startswith("claude-opus")
assert MODELS["local-fast"].startswith("openai/Hermes-3-Llama-3.1-70B")
assert MODELS["coding"] == MODELS["local-fast"]
assert MODELS["reasoning"] == MODELS["local-fast"]
```

Rationale: `feedback_model_routing_patience` — *"CAPABLE tier = best Claude model (Opus). Operator always willing to wait if indicated and justified. Never downgrade for speed."* Hermes 3 is fast local inference, not the governance/management/decision ceiling.

### 3.5 Continuous cognitive loop preservation check

Phase 5 must NOT re-introduce request-response semantics. The director loop's tick cadence must remain continuous — per-tick activity selection independent of Hermes 3 generation state.

Verification: during the speech continuity test (§3.3), observe `director_loop` logs. The activity selection must continue firing at the normal cadence (`PERCEPTION_INTERVAL` seconds) regardless of whether Hermes 3 is mid-generation.

Rationale: `feedback_cognitive_loop` — *"Voice needs a never-stopping cognitive loop during conversation, not request-response state machine. Cognition must run continuously, not cold-start on utterance boundary."*

### 3.6 Kokoro TTS GPU-vs-CPU latency eval

**Optional latency mitigation, not a hard requirement.**

Post-swap, if voice latency feels sluggish, evaluate:

1. Kokoro TTS current CPU baseline from `~/hapax-state/benchmarks/kokoro-latency/baseline.json` (captured by Phase 0).
2. Kokoro TTS GPU variant latency (same model, loaded on GPU 0 with `CUDA_VISIBLE_DEVICES=0`).
3. Alternative GPU TTS candidates: StyleTTS 2, Coqui XTTS, ChatTTS, Bark.

**Decision gate:** if GPU TTS saves > 150 ms round-trip, deploy alongside Hermes 3 as a combined latency mitigation. Otherwise keep Kokoro CPU; T3 prompt caching (Phase 10) handles the remaining latency.

**Note:** Kokoro eval is a Phase 5 scope **option**, not a requirement. The swap can proceed without it.

---

## 4. Exit criteria

All of the following must be true before Phase 5 is declared complete:

**Hardware + substrate:**

- [ ] Hermes 3 70B EXL3 3.0bpw active in TabbyAPI (`curl localhost:5000/v1/models` returns it)
- [ ] `nvidia-smi` shows expected VRAM distribution: GPU 1 (3090) ~23.5 GiB, GPU 0 (5060 Ti) ~2.75 GiB from Hermes overflow + ~3.4 GiB for daimonion (faster-whisper STT + embeddings)
- [ ] LiteLLM `/v1/models` returns Hermes 3 70B for `local-fast` / `coding` / `reasoning` routes
- [ ] LiteLLM `/v1/models` still returns Claude Opus for `capable` (per §3.4 CAPABLE tier preservation)

**Voice pipeline:**

- [ ] Full voice pipeline smoke test passes: wake word → STT → LLM → TTS < 4 s (loose gate, not the hard consent-latency check)
- [ ] Directive compliance benchmark ≥ 3/5 directive adherence + ≥ 4/5 word-limit adherence (go/no-go per §3.1 step 13)
- [ ] Consent revocation drill within **500 ms** of pre-migration envelope (§3.2)
- [ ] Speech continuity test: zero dropped frames during 60s continuous utterance over Hermes 3 long generation (§3.3)
- [ ] Continuous cognitive loop: `director_loop` activity selection continues at normal cadence during Hermes 3 generation (§3.5)

**Research registry state:**

- [ ] `research-registry current` returns `cond-phase-a-prime-hermes-NNN`
- [ ] `research_marker_changes.jsonl` has a new entry at the swap timestamp with `before: cond-phase-a-baseline-qwen-001, after: cond-phase-a-prime-hermes-NNN`
- [ ] Langfuse traces on `stream-experiment` tag show `model_condition: cond-phase-a-prime-hermes-NNN` for post-swap reactions (verify 10 minutes post-swap by querying Langfuse)
- [ ] Pre-swap: `stream-reactions` Qdrant collection shows Condition A tagged points (verification sanity check — should always be true)
- [ ] Post-swap: new reactions are tagged Condition A' (verification 10 min post-swap)

**Paper trail:**

- [ ] `research/protocols/deviations/DEVIATION-037.md` committed with actual post-swap notes filled in (beta pre-staged the draft)
- [ ] `RESEARCH-STATE.md` updated with a new dated entry referencing DEVIATION-037 + condition transition + benchmark results
- [ ] `workspace/CLAUDE.md` reflects Hermes 3 as the local-fast/coding/reasoning substrate (per §3.1 step 12)

**Relay:**

- [ ] Relay status file updated (alpha.yaml or beta.yaml per the session that performs the swap)

---

## 5. Risks + mitigations

| # | Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|---|
| 1 | 3.0 bpw fails directive compliance threshold (< 3/5) | HIGH | LOW | 3.5 bpw fallback (re-run steps 2-13 with 3.5 bpw quant); two levels of rollback available |
| 2 | Layer-split underperforms VRAM budget; GPU 1 OOMs | HIGH | LOW | Tighter `max_seq_len` (4096 → 2048) or rollback to Qwen. Monitor via `nvidia-smi` during step 8. |
| 3 | Voice latency increase (~1 s) impedes consent flow | **T0 GOVERNANCE** | MEDIUM | §3.2 consent revocation drill; if revocation round-trip > pre-migration envelope + 500ms, **rollback is required, not optional** |
| 4 | Speech continuity regression (STT frames dropped during Hermes generation) | **T0 GOVERNANCE** | LOW | §3.3 speech continuity test; zero dropped frames required; rollback on failure |
| 5 | Hermes 3 ChatML template incompatibility | MEDIUM | LOW | Migration plan rates it Low. Verified at model load in step 8. |
| 6 | Cache_control prompt caching not wired (T3 backlog) | LOW | HIGH | TTFT under Hermes 3 will be higher without it. Phase 9 or Phase 10 absorbs T3 as a polish item. Not a Phase 5 blocker. |
| 7 | `shared/config.py` swap accidentally changes CAPABLE tier | HIGH | LOW | §3.4 CAPABLE tier preservation check — automated assertion against the post-swap `shared/config.py` |
| 8 | Continuous cognitive loop regression (request-response semantics creep in) | MEDIUM | LOW | §3.5 verification during speech continuity test |
| 9 | Research registry atomic A (open condition) fails mid-swap | MEDIUM | LOW | Operator halts, investigates the registry state, resolves before restarting TabbyAPI. `research-registry open` is atomic — either the new condition exists or it doesn't. |
| 10 | Kokoro TTS decision ambiguity — operator wants GPU eval but doesn't know where to start | LOW | MEDIUM | §3.6 framing: Kokoro GPU is optional, not required. Phase 5 can ship without it. |
| 11 | Beta's pre-staged DEVIATION-037 template doesn't match the actual post-swap state | LOW | MEDIUM | DEVIATION-037 draft has placeholder sections for "Post-swap verification notes" that alpha fills in at Task 14. The draft body is 80% ready; the remaining 20% is the actual run results. |

---

## 6. Rollback

### 6.1 3.5 bpw fallback (preferred)

If the 3.0 bpw variant fails the directive compliance benchmark (§3.1 step 13) or the consent revocation drill (§3.2), rollback to 3.5 bpw **without** reverting to Qwen:

1. `systemctl --user stop tabbyapi`
2. Edit `~/projects/tabbyAPI/config.yml` — change `model_name: Hermes-3-Llama-3.1-70B-EXL3-3.0bpw` to `...EXL3-3.5bpw`. Update `gpu_split` if the 3.5 bpw layer budget differs (it does — ~27.4 GB vs ~23.5 GB; check the 3.5 bpw plan).
3. `systemctl --user start tabbyapi`
4. Re-run steps 8, 11, 13 (model load, smoke test, directive compliance benchmark).
5. **Close the current condition** via `research-registry.py close cond-phase-a-prime-hermes-NNN` with `status: failed_directive_compliance_3_0bpw` metadata.
6. **Open a new condition** `cond-phase-a-prime-hermes-3-5bpw-NNN+1` with `substrate-model: Hermes-3-Llama-3.1-70B-EXL3-3.5bpw`.
7. Re-run steps 13, 14, 15 (benchmark, DEVIATION-037 (update bpw), RESEARCH-STATE).

This fallback stays inside Phase 5; it does not abort the phase.

### 6.2 Full Qwen rollback

If 3.5 bpw also fails, or if the speech continuity test fails (§3.3), full rollback:

1. `systemctl --user stop tabbyapi`
2. `systemctl --user stop hapax-daimonion`
3. Revert `~/projects/tabbyAPI/config.yml` to the pre-swap Qwen3.5-9B config (keep backup at Task 3).
4. Remove `systemd/units/tabbyapi.service.d/gpu-pin.conf` (reverting Option γ → Option α on tabbyapi). Keep the `hapax-daimonion.service.d/gpu-pin.conf` — it's compatible with both partitions.
5. `systemctl --user daemon-reload`
6. `systemctl --user start tabbyapi`
7. Verify via step 8 checks that Qwen loaded correctly.
8. `systemctl --user start hapax-daimonion`
9. **Close the Hermes condition** with `status: rolled_back_to_qwen`.
10. **Open a new condition** `cond-phase-a-post-rollback-qwen-NNN+2` under Qwen so post-rollback data is tagged with its own condition ID.
11. File `DEVIATION-037-rollback.md` (new file, not an amendment to 037) documenting the rollback reason.

Phase 5 is now blocked. The epic pauses until a substrate retry is planned.

---

## 7. Test plan

**Pre-swap (this PR's pre-staged scripts):**

- [x] `scripts/phase-5-pre-swap-check.py` — walks §2 prerequisites table, exits non-zero on any unmet
- [x] `scripts/phase-5-post-swap-smoke.py` — runs the directive compliance benchmark + CAPABLE check + latency measurement
- [x] Unit tests for both scripts
- [ ] `uv run pytest` full surface green on `beta-phase-4-bootstrap` branch

**Operator-run at swap time (not automatable):**

- [ ] Step 2 sha256 verification against quant manifest
- [ ] Step 6 `research-registry.py open` registry atomic
- [ ] Step 7 TabbyAPI restart + wait
- [ ] Step 8 VRAM distribution check via `nvidia-smi`
- [ ] Step 11 full voice pipeline smoke test (human-in-the-loop)
- [ ] §3.2 consent revocation drill (operator voice + stopwatch)
- [ ] §3.3 speech continuity test (operator voice + Prometheus counter check)
- [ ] Step 13 directive compliance benchmark (`phase-5-post-swap-smoke.py`)

**Post-swap monitoring:**

- [ ] Langfuse 10-min check: new reactions tagged with `cond-phase-a-prime-hermes-NNN`
- [ ] Prometheus 1-hour check: per-condition score counts growing in both channels
- [ ] Hour-1 check: operator subjective quality (is speech still continuous, is consent flow usable, does Hapax sound right)
- [ ] 24-hour check: FD leak (drop #41 / pass-4 H-01) status — verify `compositor_process_fd_count` (if wired by then) or `/proc/$pid/fd | wc -l` is stable

---

## 8. Operational scripts (pre-staged or pending)

| Script | Purpose | Status |
|---|---|---|
| `scripts/phase-5-pre-swap-check.py` | Walk the §2 prerequisites table; exit non-zero on any unmet | pre-staged on this branch |
| `scripts/phase-5-post-swap-smoke.py` | Directive compliance benchmark + CAPABLE tier assertion + latency measurement | pre-staged on this branch |
| `scripts/phase-5-rollback.sh` | Automate the §6.2 full Qwen rollback procedure | pre-staged on this branch |
| `scripts/phase-5-consent-revocation-drill.sh` | Automate the §3.2 drill measurement (can't automate the human part) | **not pre-staged** — too human-centric |
| `scripts/phase-5-speech-continuity-test.sh` | Automate the §3.3 counter-delta check (can't automate the human part) | **not pre-staged** — too human-centric |

---

## 9. Open questions for operator review

1. **3.5 bpw quant timing.** Beta's 3.5 bpw quant is in flight as of the writing of this spec. If Phase 4 locks before 3.5 bpw is ready, Phase 5 can still open with only the 3.0 bpw quant, but the 3.5 bpw fallback (§6.1) becomes unavailable until the second quant lands. Operator chooses: wait for 3.5 bpw, or open Phase 5 with 3.0 bpw only.

2. **DEVIATION-037 fill-in timing.** Beta pre-stages the DEVIATION-037 draft with the structural sections (What, Why, Impact, Mitigation). The post-swap verification notes (actual benchmark results, consent drill timing, speech continuity counter delta) are filled in by alpha or the operator at Task 14. Operator confirms this split is correct.

3. **Kokoro TTS GPU eval scope.** §3.6 marks this as optional. Is the operator interested in evaluating GPU TTS during Phase 5, or deferring to a later polish phase? The 3.75 GiB of headroom on GPU 0 supports the eval.

4. **`scripts/phase-5-pre-swap-check.py` execution context.** The script touches `nvidia-smi`, `systemctl`, `curl`, and the research registry. It's intended to run **from an interactive operator shell**, not from a systemd timer. Does the operator want a systemd-timer-compatible version for pre-Phase-5 gate-keeping, or is the interactive version sufficient?

5. **CAPABLE tier verification depth.** §3.4 asserts that `shared/config.py::MODELS["capable"]` still routes to Claude Opus. Should the check also verify that the LiteLLM gateway config (`litellm/config.yaml`) has the same routing, since LiteLLM is the runtime surface?

6. **Rollback condition naming.** §6.1 and §6.2 propose condition names `cond-phase-a-prime-hermes-3-5bpw-NNN+1` and `cond-phase-a-post-rollback-qwen-NNN+2`. Is the operator's preferred convention the sequential N+1/N+2 or something else (e.g., `cond-phase-a-retry-rollback-qwen-001`)?

---

## 10. References

- **Parent epic spec:** `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` §Phase 5
- **Migration plan (authoritative Tasks 1-13):** `docs/superpowers/plans/2026-04-10-hermes3-70b-migration.md`
- **Theoretical grounding:** `docs/superpowers/specs/2026-04-10-hermes3-70b-voice-architecture-design.md`
- **Phase 4 spec (dependency):** `docs/superpowers/specs/2026-04-14-lrr-phase-4-phase-a-completion-design.md`
- **DEVIATION-037 draft:** `research/protocols/deviations/DEVIATION-037.md` (pre-staged on this branch in a follow-up commit)
- **Beta verified GPU mapping + gpu_split correction:** `~/.cache/hapax/relay/context/2026-04-14-beta-phase-3-supplement-verified-preconditions.md`
- **Consent latency memory:** `feedback_consent_latency_obligation` (beta memory)
- **Speech continuity memory:** `feedback_never_drop_speech` (beta memory)
- **Model routing patience memory:** `feedback_model_routing_patience` (beta memory)
- **Continuous cognitive loop memory:** `feedback_cognitive_loop` (beta memory)
- **LRR audit trajectory:** 5 passes through `~/.cache/hapax/relay/context/2026-04-14-beta-lrr-audit-pass-*.md`

— beta
