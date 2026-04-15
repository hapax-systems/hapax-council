# LRR Phase 3 — Hardware Migration Validation + Substrate Preparation (plan)

**Spec:** `docs/superpowers/specs/2026-04-14-lrr-phase-3-hardware-validation-design.md` (see § 0.5 amendment 2026-04-15 for Hermes-framing supersession)
**Date:** 2026-04-14 (original), 2026-04-15 spec amendment (queue #139), 2026-04-15 plan refresh (queue #157)
**Shipping order:** 3 PRs per beta's revised stage split (see `~/.cache/hapax/relay/context/2026-04-14-beta-phase-3-supplement-verified-preconditions.md` §2)

> **2026-04-15 amendment (queue #139 spec + queue #157 plan refresh):** Hermes 3 framing below is **structurally obsolete** per drop #62 §14 (Hermes abandonment) + §16 (substrate scenario 1+2 ratification, PR #895) + §17 (Option C parallel TabbyAPI pivot, PR #899).
>
> **Post-§16 scope changes:**
>
> - **Stage 1 (partition α→γ)** — SUBSTRATE-AGNOSTIC, ships as originally planned. All items remain valid EXCEPT item 7 (`config.yml.hermes-draft`) which is obsolete — the new TabbyAPI config is a Phase 5 Stage 2c deliverable per the substrate-scenario-1+2 plan.
> - **Stage 2 (Hermes 70B self-quantization)** — **REMOVED FROM SCOPE.** Hermes is permanently abandoned. The replacement work (OLMo 3-7B × 3 variant quantization) moves to **LRR Phase 5 Stage 2b** per `docs/superpowers/plans/2026-04-15-lrr-phase-5-substrate-scenario-1-2-plan.md` (PR #900).
> - **Stage 3 (post-mobo re-verification)** — SUBSTRATE-AGNOSTIC, ships as originally planned. Items 3/4/5 re-verify, item 10 cable hygiene, item 11 BRIO replacement — all unchanged.
>
> **Historical body below preserved** per the audit-trail pattern (same as beta's Phase 5 spec §0.5 Option C amendment). Stage 2 subsection kept as `[HISTORICAL — REMOVED FROM SCOPE]` rather than deleted. Phase 3 execution session reads this amendment first + applies the scope changes.
>
> **Cross-references:** drop #62 §14 + §16 + §17 in `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md`; Phase 3 spec §0.5 amendment (PR #897); Phase 5 new spec (PR #896 queue #138) + plan (PR #900 queue #143); beta's #209 blocker inflection.

## Stage 1 — Pre-mobo, ships today as Phase 3 PR #1 (this PR)

| Item | Subject | File(s) |
|---|---|---|
| 1 | Partition reconciliation α→γ | `systemd/units/tabbyapi.service.d/gpu-pin.conf`, `systemd/units/hapax-dmn.service.d/gpu-pin.conf` |
| 2 | Driver + CUDA verification | documented in spec §1.2 (beta-verified) |
| 7 | TabbyAPI config draft | `~/projects/tabbyAPI/config.yml.hermes-draft` (local tabbyAPI repo) |
| 8 | `tabbyapi.service` timeout raise | `systemd/units/tabbyapi.service` TimeoutStartSec 120 → 180 |
| 9 | Rollback plan | documented in spec §3 |
| — | `install-units.sh` extension | `systemd/scripts/install-units.sh` (handle `*.service.d/` drop-ins) |
| — | Regression pin | `tests/test_install_units_sweep_pin.py` extended with drop-in walk assertions |

**Operational follow-ups (same PR, second commit)** — these are verification runs that land their findings in spec §6:

| Item | Subject | Tool |
|---|---|---|
| 0 | Formal sm_120 precondition check via systemd override | `scripts/phase-3-sm120-precheck.sh` (TBD) |
| 3 | PSU combined-load stress test (30 min) | `nvidia-smi --query-gpu=power.draw,clocks_throttle_reasons.hw_power_brake_slowdown --format=csv -l 1` during sustained compositor+TabbyAPI+imagination load |
| 4 | PCIe link width verification (now unblocked per operator) | `sudo lspci -vvs 03:00.0 \| grep LnkSta` (5060 Ti); `sudo lspci -vvs 07:00.0 \| grep LnkSta` (3090) |
| 5 | Thermal validation during stress | `nvidia-smi --query-gpu=temperature.gpu --format=csv -l 5` during the 30-min stress |

All four operational tasks can run without restarting anything if scheduled during a nominal compositor load window.

## Stage 2 — [HISTORICAL — REMOVED FROM SCOPE per queue #157 post-§16]

> **This entire Stage 2 is structurally obsolete.** Hermes 3 70B is permanently abandoned per drop #62 §14. Self-quantization is no longer in scope for Phase 3. The replacement work — OLMo 3-7B × 3 variant quantization (SFT, DPO, RLVR) — is now LRR Phase 5 Stage 2b per `docs/superpowers/plans/2026-04-15-lrr-phase-5-substrate-scenario-1-2-plan.md` §3.2. The body below is preserved as historical audit trail only.

### [HISTORICAL] Stage 2 — Pre-mobo, ships as Phase 3 PR #2 (deferred per operator)

| Item | Subject | Notes |
|---|---|---|
| 6 | Hermes 3 70B EXL3 3.0bpw self-quantization | BF16 download already complete at `~/hapax-state/quant-staging/Hermes-3-Llama-3.1-70B-bf16/` (beta ran `hf download` at 15:30Z and confirmed all 30 safetensors shards). Self-quantization via `exllamav3.conversion.convert_model` is a multi-hour compute window on the 3090. Operator explicitly deferred: "do everything we can sans Hermes prep completion" |

Operator will schedule the quant window. Once complete, Phase 3 PR #2 ships:

- The EXL3 3.0bpw weights at `~/projects/tabbyAPI/models/Hermes-3-Llama-3.1-70B-EXL3-3.0bpw/` (verified size ~26-27 GB)
- Optional 3.5bpw fallback quant for insurance
- Update spec §6 with actual load-time measurements
- Update `config.yml.hermes-draft` if the draft needed any post-measurement tweaks

## Stage 3 — Post-mobo, ships as Phase 3 PR #3 (~2026-04-16+)

| Item | Subject | Notes |
|---|---|---|
| 3 (re-verify) | PSU stress re-run under new mobo topology | Mobo power-delivery characteristics may shift |
| 4 (re-verify) | PCIe link width re-verification | Slot topology changes mean 5060 Ti's lanes may shift Gen 5 x4 → Gen 5 x16 |
| 5 (re-verify) | Thermals re-validation | Case airflow may change if slots reverse |
| 10 | Cable hygiene pass | Operator physical inspection during install window |
| 11 | BRIO replacement + post-swap fps verification | BRIO replacement coordinated with install. **Delta brio-operator deep research warning:** if the replacement shows the same 27.94 fps deficit, the cause is NOT the original BRIO body. See `~/.cache/hapax/relay/context/2026-04-14-beta-brio-operator-deep-research.md`. Verify post-swap fps before declaring C1 closed. |

## Close handoff (post-§16 scope)

Phase 3 closes when **Stages 1 + 3** (both substrate-agnostic) merge. **Stage 2 is removed** — OLMo quantization work is LRR Phase 5 Stage 2b per the new substrate-scenario-1+2 plan.

**Post-§16 dependency shift:**
- ~~Phase 5 dependency (Hermes 3 swap) unblocks at the end of Stage 2 (PR #2, quant complete).~~
- **New:** Phase 5 depends on Phase 3 Stage 1 (partition) being complete + drop #62 §16 ratification being shipped (both ✓). Phase 3 Stage 3 (post-mobo) is independent of Phase 5 — the mobo swap only affects items 4, 10, 11.

Per epic design §"Phase 3 — Handoff implications": Phase 3 is hardware + partition prep (originally + quant prep; quant prep moved to Phase 5 per post-§16 scope). Phase 5 is the actual substrate deployment (now substrate scenario 1+2 parallel, not Hermes swap). The gap between 3 and 4/5 is "control arm collection time" — hardware stays Option γ but TabbyAPI :5000 continues serving Qwen3.5-9B for Phase A baseline collection. Scenario 2's OLMo deployment (Phase 5 Stage 2a-2c) runs on parallel TabbyAPI :5001 without disrupting :5000 Qwen service per §17 Option C.

## Risk register

See spec §5.
