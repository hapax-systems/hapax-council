# LRR Phase 3 — Hardware Migration Validation + Substrate Preparation (plan)

**Spec:** `docs/superpowers/specs/2026-04-14-lrr-phase-3-hardware-validation-design.md` (see § 0.5 amendment 2026-04-15 for Hermes-framing supersession)
**Date:** 2026-04-14 (original), 2026-04-15 amendment
**Shipping order:** 3 PRs per beta's revised stage split (see `~/.cache/hapax/relay/context/2026-04-14-beta-phase-3-supplement-verified-preconditions.md` §2)

> **2026-04-15 amendment (queue #139):** Hermes 3 framing in the body of this plan is structurally obsolete per drop #62 §14 (Hermes abandonment) + §16 (substrate scenario 1+2 ratification). The partition work (Stage 1 + Stage 3) remains valid; Stage 2 "self-quantization" is removed from scope (Hermes is not being deployed). New Phase 5 spec at `docs/superpowers/specs/2026-04-15-lrr-phase-5-substrate-scenario-1-2-design.md` (PR #896) handles substrate-specific configuration. Spec §0.5 has the full amendment.

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

## Stage 2 — Pre-mobo, ships as Phase 3 PR #2 (deferred per operator)

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

## Close handoff

Phase 3 closes when all three PRs merge. The Phase 5 dependency (Hermes 3 swap) unblocks at the end of Stage 2 (PR #2, quant complete). Stage 3 is independent of Phase 5 — the mobo swap only affects items 4, 10, 11.

Per epic design §"Phase 3 — Handoff implications": Phase 3 is hardware + quant prep. Phase 5 is the actual swap. The gap between 3 and 4/5 is "control arm collection time" — hardware stays Option γ but TabbyAPI still runs Qwen because Condition A collection is still open.

## Risk register

See spec §5.
