# LRR Phase 3 — Hardware Validation + Substrate Preparation (post-§14 reframed) — Plan

**Date:** 2026-04-15
**Spec reference:** `docs/superpowers/specs/2026-04-15-lrr-phase-3-hardware-validation-design.md`
**Branch target:** `feat/lrr-phase-3-hardware-validation`
**Unified phase mapping:** UP-5 (post-§14 reframed; ~400 LOC)

---

## 0. Preconditions

- [ ] LRR UP-0 + UP-1 + UP-3 closed
- [ ] Operator substrate ratification per drop #62 §14 (or accept "conservative shipping substrate-agnostic items only")
- [ ] Hardware baseline unchanged (RTX 3090 + RTX 5060 Ti, PCIe Gen 4, 590 driver, TabbyAPI on `CUDA_VISIBLE_DEVICES=1`)
- [ ] Session claims: `lrr-state.yaml::phase_statuses[3].status: open`

---

## Execution order: item 2 → 4 → 3 → 5 (runs during stress) → 11 → 10 → 9-reframed → 1/6/7/8 deferred

### 1. Item 2 — Driver version verification (substrate-agnostic)

- [ ] `nvidia-smi -L` shows both GPUs
- [ ] `nvidia-smi | grep "CUDA Version"` ≥ 12.8
- [ ] `python3 -c "import torch; print(torch.cuda.device_count())"` returns 2
- [ ] Basic CUDA test on both devices
- [ ] Write `docs/hardware/driver-state-2026-04-15.md` (~50 lines result doc)
- [ ] Commit: `docs(lrr-phase-3): item 2 driver version verification`

### 2. Item 4 — PCIe link width verification

- [ ] `sudo lspci -vvs 03:00.0 | grep LnkSta` for 5060 Ti
- [ ] `sudo lspci -vvs 07:00.0 | grep LnkSta` for 3090
- [ ] Document in `docs/hardware/pcie-link-state-2026-04-15.md`
- [ ] Commit: `docs(lrr-phase-3): item 4 PCIe link width verification`

### 3. Item 3 — PSU audit + combined-load stress test

- [ ] Create `scripts/psu-stress-test.sh` (~100 LOC) with 30-min combined load
- [ ] Launch: TabbyAPI + compositor + imagination + Reverie all engaged
- [ ] Monitor: `nvidia-smi --query-gpu=power.draw,clocks_throttle_reasons.hw_power_brake_slowdown --format=csv -l 1`
- [ ] Success: no `hw_power_brake_slowdown` events; peak power < PSU × 0.8
- [ ] Write log at `~/hapax-state/hardware-validation/psu-2026-04-15.log`
- [ ] Commit: `feat(lrr-phase-3): item 3 PSU audit + combined-load stress test script`

### 4. Item 5 — Thermal validation (runs concurrent with item 3)

- [ ] During the 30-min PSU test, monitor temps:
  - 5060 Ti: < 75°C
  - 3090: < 70°C
- [ ] Write log at `~/hapax-state/hardware-validation/thermal-2026-04-15.log`
- [ ] Commit: `docs(lrr-phase-3): item 5 thermal validation`

### 5. Item 11 — brio-operator 28fps deficit re-measurement

- [ ] Create `scripts/measure-brio-operator-fps.sh` (~60 LOC)
- [ ] 5-min fps measurement under nominal load
- [ ] If ~30.5 fps: root cause closed (was TabbyAPI inference contention)
- [ ] If ~28.5 fps: 4 original candidates remain (hero=True, metrics lock, queue depth, hardware)
- [ ] Write result at `~/hapax-state/camera-validation/brio-operator-fps-2026-04-15.log`
- [ ] Commit: `feat(lrr-phase-3): item 11 brio-operator fps re-measurement`

### 6. Item 10 — Cable hygiene pass (operator-coordinated)

- [ ] Operator physical inspection of USB + DisplayPort + audio cables
- [ ] Identify damaged/loose cables
- [ ] Write `docs/hardware/cable-inventory.md` (~80 lines)
- [ ] Commit: `docs(lrr-phase-3): item 10 cable hygiene pass + inventory`

### 7. Item 9 — REFRAMED: Current Qwen3.5-9B production baseline doc

- [ ] Write `docs/research/protocols/substrate-production-baseline-2026-04-15.md` (~100 lines)
- [ ] Document current Qwen3.5-9B as the "this IS production, not a rollback target" reference
- [ ] Cross-reference drop #62 §14 + beta's substrate research
- [ ] Commit: `docs(lrr-phase-3): item 9-reframed current Qwen3.5-9B production baseline`

### 8. Items 1/6/7 — DEFERRED per drop #62 §14

- [ ] **NO-OP** per spec §3.7/§3.8/§3.9
- [ ] Item 8 (TimeoutStartSec) already shipped by beta's `bafd6b34f` cache warmup commit — no action
- [ ] Document deferrals in the handoff doc with §14 cross-reference

---

## Phase 3 close

- [ ] 7 substrate-agnostic items shipped + verified
- [ ] 4 items (1/6/7 + partial 8) explicitly deferred with rationale
- [ ] `lrr-state.yaml::phase_statuses[3].status: closed`
- [ ] Handoff: `docs/superpowers/handoff/2026-04-15-lrr-phase-3-complete.md`

---

## Cross-epic coordination

- **Drop #62 §14 reframing** is the dominant decision; 4 items deferred pending operator substrate ratification
- **Beta's `bafd6b34f`** already handled item 8 (TimeoutStartSec)
- **If operator ratifies OLMo 3-7B parallel-deploy** per beta's research §9, items 1/6/7 get new targets (OLMo instead of Hermes); reopen Phase 3 or ship as delta

---

## End

Compact plan for LRR Phase 3 (post-§14 reframed). Pre-staging.

— delta, 2026-04-15
