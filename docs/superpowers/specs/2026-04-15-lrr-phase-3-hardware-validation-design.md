# LRR Phase 3 — Hardware Migration Validation + Substrate Preparation (post-§14 reframed) — Design Spec

**Date:** 2026-04-15
**Author:** delta (pre-staging extraction with heavy §14 reframing)
**Status:** DRAFT pre-staging — HEAVILY SUPERSEDED by drop #62 §14 (Hermes abandonment 2026-04-15T06:35Z)
**Epic reference:** `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` §5 Phase 3
**Plan reference:** `docs/superpowers/plans/2026-04-15-lrr-phase-3-hardware-validation-plan.md`
**Branch target:** `feat/lrr-phase-3-hardware-validation`
**Cross-epic authority:** drop #62 §5 UP-5 + §14 Hermes abandonment
**Unified phase mapping:** **UP-5 Hardware validation + substrate prep** (drop #62 §5, originally "Hermes 8B prep" per §14 5b→unreachable)

> **2026-04-15T08:00Z critical supersession note:** the original LRR Phase 3 spec centered on **Hermes 3 70B partition reconciliation (Option γ) + Hermes 3 70B quant download + TabbyAPI config.yml.hermes-draft**. Per drop #62 §14, the Hermes 3 path (both 70B and 8B parallel) is abandoned by operator direction at 2026-04-15T06:35Z. **Items 1, 6, 7, 8 of the original Phase 3 scope are no longer relevant in their Hermes form.** The remaining substrate-agnostic items (2 driver verification, 3 PSU audit, 4 PCIe link width, 5 thermal validation, 10 cable hygiene, 11 brio-operator re-measurement) remain valid and shippable. If the operator ratifies a new substrate per beta's research §9 (Qwen3.5-9B + fixes OR OLMo 3-7B parallel), Phase 3 opener retargets items 1/6/7/8 to the new substrate.

---

## 1. Phase goal (post-§14 reframed)

**Original goal** (superseded): reconcile dual-GPU partition + download Hermes 3 70B quant + prepare TabbyAPI config for substrate swap.

**Reframed goal:** validate the hardware envelope is stable for sustained Qwen3.5-9B inference (the post-Hermes production substrate per beta's research §9 primary recommendation). Ship substrate-agnostic hardware validation items (driver, PSU, PCIe, thermal, cable, brio-operator re-measurement). **Defer items 1/6/7/8 (Hermes 70B partition + quant + config)** until operator ratifies whether to parallel-deploy OLMo 3-7B (per beta's research §9 complementary recommendation) or keep Qwen3.5-9B alone.

**What this phase is (post-§14):** hardware envelope validation for production Qwen3.5-9B. This is mostly VERIFICATION work — confirming what's already running is running cleanly — rather than new substrate preparation.

**What this phase is NOT (post-§14):** no Hermes 3 70B download, no Option γ partition reconciliation (the dual-GPU partition stays at its current α state), no 70B config draft.

---

## 2. Dependencies + preconditions

1. **LRR UP-0 + UP-1 + UP-3 closed.**
2. **Operator substrate ratification per §14.** Phase 3 opener needs to know whether the operator has committed to "keep Qwen3.5-9B alone" or "parallel-deploy OLMo 3-7B on a second TabbyAPI slot". Without this, Phase 3 scopes conservatively (substrate-agnostic items only) and defers items 1/6/7/8 until ratification.
3. **Hardware baseline unchanged:** RTX 3090 + RTX 5060 Ti, PCIe Gen 4 dual-GPU, 590 driver, current TabbyAPI config at `CUDA_VISIBLE_DEVICES=1` (single-GPU).

---

## 3. Deliverables (post-§14 reframed)

### 3.1 Item 2 — Driver version verification (substrate-agnostic, SHIPS)

- **Scope:** verify current driver 590.48.01 + CUDA 12.8+ + both GPUs visible + basic compute test on both devices
- **Success criteria:** `nvidia-smi -L` lists both cards; `python3 -c "import torch; print(torch.cuda.device_count())"` returns 2; CUDA test OK
- **Target files:** none (verification commands + result doc at `docs/hardware/driver-state-2026-04-15.md`)
- **Size:** ~30 LOC + 50 lines markdown

### 3.2 Item 3 — PSU audit + combined-load stress test (substrate-agnostic, SHIPS)

- **Scope:** 30-minute combined-load stress test per Sprint 5b F8 + Sprint 7 F2. TabbyAPI + compositor + imagination + Reverie mixer all engaged. Monitor `nvidia-smi --query-gpu=power.draw,clocks_throttle_reasons.hw_power_brake_slowdown` on both GPUs at 1s cadence.
- **Success criteria:** no `hw_power_brake_slowdown` events; combined power peak < PSU rating × 0.8
- **Target files:** `scripts/psu-stress-test.sh` (~100 LOC), result log at `~/hapax-state/hardware-validation/psu-2026-04-15.log`
- **Size:** ~100 LOC + log

### 3.3 Item 4 — PCIe link width verification (substrate-agnostic, SHIPS)

- **Scope:** `lspci -vvs 03:00.0 | grep LnkSta` for 5060 Ti; same for 3090. Document actual Gen + lanes.
- **Success criteria:** both cards at expected Gen/lane (Gen 5 x4 minimum for layer-split tolerance; Gen 4 x16 is better)
- **Target files:** `docs/hardware/pcie-link-state-2026-04-15.md` (~40 lines markdown)
- **Size:** ~40 lines

### 3.4 Item 5 — Thermal validation (substrate-agnostic, SHIPS)

- **Scope:** 30-min combined-load thermal measurement. Success: 5060 Ti <75°C, 3090 <70°C under sustained load.
- **Target files:** `~/hapax-state/hardware-validation/thermal-2026-04-15.log`
- **Size:** ~50 lines log

### 3.5 Item 10 — Cable hygiene pass (substrate-agnostic, SHIPS)

- **Scope:** Per Sprint 7 F8. Full operator inspection of USB + DisplayPort + audio cables. Identify damaged/loose cables; standardize on known-good models. Document in `docs/hardware/cable-inventory.md`
- **Target files:** `docs/hardware/cable-inventory.md` (~80 lines markdown)
- **Note:** This is operator-hand work; schedule alongside the PSU stress test
- **Size:** ~80 lines

### 3.6 Item 11 — brio-operator 28fps deficit re-measurement (substrate-agnostic, SHIPS)

- **Scope:** Per Sprint 1 F2 + Sprint 7 F1 (R3 from alpha close-out). 5-min measurement of `brio-operator` fps under nominal load. If fps hits ~30.5 (matching other cameras), the root cause was TabbyAPI inference contention on GPU 1 under Option α partition. If still ~28.5, the original 4 candidates remain (hero=True, metrics lock, queue depth, hardware).
- **Target files:** `scripts/measure-brio-operator-fps.sh` (~60 LOC), result at `~/hapax-state/camera-validation/brio-operator-fps-2026-04-15.log`
- **Size:** ~60 LOC + log

### 3.7 Item 1 — DEFERRED: Partition reconciliation α→γ (superseded by §14)

- **Original scope:** change `CUDA_VISIBLE_DEVICES=1` to `0,1` with `CUDA_DEVICE_ORDER=PCI_BUS_ID`; move `hapax-dmn` to GPU 0; reconcile budgets for Hermes 3 70B
- **Superseded status:** Hermes 3 70B abandoned per drop #62 §14. The dual-GPU partition reconfiguration targeting 70B layer-split is no longer needed.
- **Post-§14 decision:** if operator ratifies parallel-deploy OLMo 3-7B per beta's research §9, a reduced version of item 1 may still be relevant: a secondary TabbyAPI instance on GPU 0 (separate from the primary Qwen3.5-9B instance on GPU 1) running OLMo 3-7B. But this is a different configuration than the original Option γ and requires fresh specification at Phase 3 open time
- **Target files:** N/A (deferred)

### 3.8 Item 6 — DEFERRED: Hermes 3 70B EXL3 3.0bpw acquisition (superseded)

- **Superseded status:** Hermes 3 70B abandoned per drop #62 §14. Beta killed the 3.5bpw quant at layer 57/80 at 2026-04-15T06:20Z.
- **Post-§14 decision:** no Hermes 3 download. If operator ratifies OLMo 3-7B, the replacement acquisition is the OLMo SFT + DPO quants from HuggingFace (`turboderp/Olmo-Hybrid-Instruct-SFT-7B-exl3` + `UnstableLlama/Olmo-Hybrid-Instruct-DPO-7B-exl3`). See beta's substrate research §5 + §6.
- **Target files:** N/A (deferred)

### 3.9 Item 7 — DEFERRED: TabbyAPI config.yml.hermes-draft (superseded)

- **Superseded status:** no Hermes 3 swap, no Hermes config draft needed. PR #826 + PR #839 already shipped and then superseded the draft `tabbyapi-hermes8b.service` unit.
- **Post-§14 decision:** if operator ratifies OLMo parallel-deploy, new config drafts at `~/projects/tabbyAPI/config.yml.olmo-sft` + `config.yml.olmo-dpo`. Beta's nightly queue item #12 starts this work.
- **Target files:** N/A (deferred; future OLMo configs by beta per their queue)

### 3.10 Item 8 — DEFERRED: TabbyAPI systemd timeout increase to 180s (partially kept)

- **Original scope:** increase `TimeoutStartSec=120→180` because 70B load is slower
- **Post-§14 status:** the 180s TimeoutStartSec was kept by beta's cache warmup commit `bafd6b34f` (on `beta-phase-4-bootstrap` PR #819) with an updated rationale comment acknowledging the Hermes 70B abandonment. The 180s ceiling remains valid as headroom for the cache warmup retry window.
- **Post-§14 decision:** NO ACTION needed — beta already handled this as a side effect of assignment #2 cache warmup.
- **Target files:** `systemd/units/tabbyapi.service` — already updated by beta at `bafd6b34f`

### 3.11 Item 9 — MODIFIED: Rollback plan (reframed as "current-Qwen-is-production-baseline")

- **Original scope:** rollback procedure if Hermes 3 fails
- **Reframed scope:** document the current Qwen3.5-9B production baseline as the "don't rollback, this IS production" reference. If the operator ever decides to swap to OLMo or any other substrate, the baseline reference is what they compare against.
- **Target files:** `docs/research/protocols/substrate-production-baseline-2026-04-15.md` (~100 lines markdown)
- **Size:** ~100 lines markdown

---

## 4. Phase-specific decisions

1. **§14 supersession** is the dominant decision — 4 of 11 original items (1, 6, 7 — plus partial 8) are obsolete; 7 items remain shippable
2. **Substrate-agnostic items ship normally** — driver, PSU, PCIe, thermal, cable, camera re-measurement, baseline doc
3. **Deferred items** (1, 6, 7, 9-original) depend on operator substrate ratification per §14
4. **Item 8** (TimeoutStartSec) already shipped via beta's assignment #2 cache warmup
5. **Phase 3 size shrinks from original ~800 LOC to ~400 LOC** post-§14 reframing

---

## 5. Exit criteria (post-§14 reframed)

- Driver verified (item 2)
- PSU stress test passed (item 3)
- PCIe link widths documented (item 4)
- Thermals verified (item 5)
- Cable hygiene audited (item 10)
- brio-operator fps re-measured (item 11)
- Current Qwen3.5-9B production baseline documented (item 9 reframed)
- `lrr-state.yaml::phase_statuses[3].status == closed`
- Items 1/6/7 explicitly deferred in handoff doc with §14 cross-reference
- Handoff doc

---

## 6. Risks + mitigations

| Risk | Mitigation |
|---|---|
| Operator substrate ratification doesn't come before Phase 3 opens | Phase 3 ships substrate-agnostic items only + defers items 1/6/7 |
| PSU stress test reveals power brake events | Fall back to reduced load; document the finding |
| Thermals exceed spec | Operator inspection of case airflow + mitigations from Sprint 7 F7 |
| brio-operator fps still 28.5 after Qwen-only baseline | 4 original candidates remain as investigation targets |
| Cable hygiene surfaces unexpected hardware issues | Surface via inflection; operator decides repair timeline |

---

## 7. Open questions

1. **Operator substrate ratification status** — unknown at write time; Phase 3 opener must check
2. **PSU rating** — operator reads label if not in existing docs
3. **brio-operator deficit root cause** — depends on re-measurement result

---

## 8. Plan

`docs/superpowers/plans/2026-04-15-lrr-phase-3-hardware-validation-plan.md`. Execution order: item 2 (driver) → item 4 (PCIe) → item 3 (PSU stress) → item 5 (thermal, runs during stress) → item 11 (brio re-measure) → item 10 (cable hygiene, operator-coordinated) → item 9 (baseline doc).

---

## 9. End

Pre-staging spec for LRR Phase 3, HEAVILY reframed post-drop #62 §14 Hermes abandonment. 7 of 11 original items retained as substrate-agnostic hardware validation; 4 items deferred pending operator substrate ratification.

Eighteenth complete extraction in delta's pre-staging queue this session.

— delta, 2026-04-15
