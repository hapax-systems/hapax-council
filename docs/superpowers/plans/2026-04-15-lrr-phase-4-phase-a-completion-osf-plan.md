# LRR Phase 4 — Phase A Completion + OSF Pre-Registration — Plan

**Date:** 2026-04-15
**Spec reference:** `docs/superpowers/specs/2026-04-15-lrr-phase-4-phase-a-completion-osf-design.md`
**Branch target:** `feat/lrr-phase-4-phase-a-completion`
**Unified phase mapping:** UP-6 (time-gated; ~400 LOC + operator sessions)

---

## 0. Preconditions

- [ ] LRR UP-0 + UP-1 + UP-5 closed
- [ ] Sprint 0 G3 gate resolved (Option 1 resolve-inside-LRR default, OR Option 2 document-as-blocker)
- [ ] Frozen-file pre-commit enforcement running (LRR Phase 1 item 4)
- [ ] Operator session cadence available for ≥10 voice grounding sessions
- [ ] OSF account accessible for pre-reg filing (operator action)
- [ ] Session claims: `lrr-state.yaml::phase_statuses[4].status: open`

---

## Execution order: G3 → cadence start → integrity checks (concurrent) → ORCID/Zenodo/GitHub Pages (idle fill) → OSF pre-reg (after ≥10) → data lock → collection_halt_at → handoff

### 1. G3 resolution (pre-phase-work)

- [ ] Identify G3 gate definition in sprint state files
- [ ] **Option 1 (default):** execute pending Measure 7.2 Claim 5 correlation analysis inside LRR
- [ ] **Option 2 (fallback):** document `blocked_on: sprint-0-g3` in condition.yaml + wait for external resolution
- [ ] Commit: `docs(lrr-phase-4): item G3 resolution (Option 1 or 2)`

### 2. Target sample size + daily data collection cadence

- [ ] Operator runs ≥10 voice grounding sessions under Qwen3.5-9B
- [ ] Each session writes reactions tagged with `cond-phase-a-baseline-qwen-001`
- [ ] No new code; existing LRR Phase 1 infrastructure handles tagging

### 3. Mid-collection integrity checks (runs every 3 sessions)

- [ ] Create `scripts/lrr-phase-4-integrity-check.sh` (~60 LOC):
  - [ ] `research-registry current` returns baseline condition
  - [ ] No frozen-file diffs applied
  - [ ] Qdrant point count growing
  - [ ] Langfuse traces tagged
- [ ] `systemd/user/hapax-lrr-phase-4-integrity.timer` (daily automated check)
- [ ] Commit: `feat(lrr-phase-4): item 3 mid-collection integrity check script + timer`

### 4. ORCID + Zenodo + GitHub Pages (idle-fill)

- [ ] Operator actions:
  - [ ] ORCID ID linked to research profile
  - [ ] Zenodo account + DOI reservation for `claim-shaikh-sft-vs-dpo`
- [ ] Code actions:
  - [ ] `docs/research/protocols/orcid-zenodo-setup.md` documentation (~100 lines)
  - [ ] `gh-pages/` branch setup OR `docs/` GitHub Pages config (~100 lines setup)
- [ ] Commit: `docs(lrr-phase-4): item 5 ORCID + Zenodo + GitHub Pages research infrastructure`

### 5. OSF project creation + pre-registration filing (after ≥10 sessions)

- [ ] **Operator actions:**
  - [ ] Create OSF project for `claim-shaikh-sft-vs-dpo`
  - [ ] Upload pre-registration doc
  - [ ] Generate pre-reg URL
  - [ ] **Operator sign-off on filing** — one-way step
- [ ] **Code actions:**
  - [ ] `research-registry.py set-osf <cond> <project_id>`
  - [ ] `research-registry.py file-prereg <cond> <url>`
  - [ ] condition.yaml auto-updated via CLI
- [ ] Commit: N/A (condition.yaml is session-local state, not repo)

### 6. Data integrity lock

- [ ] Create `scripts/lrr-phase-4-integrity-lock.sh` (~80 LOC):
  - [ ] Compute sha256 for each Condition A reactor log JSONL
  - [ ] Write to `~/hapax-state/research-registry/cond-phase-a-baseline-qwen-001/data-checksums.txt`
  - [ ] Qdrant snapshot export to `qdrant-snapshot.tgz`
- [ ] Run once at Phase 4 completion
- [ ] Commit: `feat(lrr-phase-4): item 6 data integrity lock script`

### 7. Condition A `collection_halt_at` marker

- [ ] Extend `research-registry.py` CLI with `set-collection-halt <cond> <ts>` subcommand (if not already in item #8 from Phase 1 queue)
- [ ] Call it at Phase 4 close with current timestamp
- [ ] condition.yaml updated (session-local)
- [ ] Commit: `feat(lrr-phase-4): item 7 collection_halt_at marker CLI extension`

---

## Phase 4 close

- [ ] ≥10 voice grounding sessions completed with Qwen3.5-9B tag
- [ ] OSF project + pre-reg filed + URL in registry
- [ ] Data checksums + Qdrant snapshot captured
- [ ] `collection_halt_at` marker written
- [ ] `RESEARCH-STATE.md` updated
- [ ] `lrr-state.yaml::phase_statuses[4].status: closed`
- [ ] Handoff: `docs/superpowers/handoff/2026-04-15-lrr-phase-4-complete.md`

---

## Cross-epic coordination

- **Phase 4 is substrate-independent** on the Condition A side per drop #62 §14 note; only the downstream Condition A' target is superseded
- **Post-§16 update (2026-04-15T22:45Z, queue #177 alignment patch):** Condition A' is no longer TBD. Per drop #62 §16, A' is scenario 2: OLMo 3-7B × {SFT, DPO, RLVR} as three parallel arms. Per drop #62 §17, scenario 2 execution pivoted to Option C (parallel TabbyAPI :5001 backend) after beta's #209 exllamav3 blocker. Queue #171's v0.0.28 matrix may retire Option C in favor of scenario 2 Option A. Phase 4 deliverables and execution order are unchanged by this framing update.
- **G3 Sprint 0 gate** may require non-LRR Bayesian schedule resolution
- **Phase 4 handoff unblocks Phase 5a** (scenario 2 OLMo parallel-arm execution)

---

## End

Compact plan for LRR Phase 4 Phase A Completion + OSF Pre-Registration. Time-gated by operator session cadence. Substrate-independent on Condition A.

— delta, 2026-04-15
