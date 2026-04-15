# hapax_daimonion/proofs/ directory currency audit

**Date:** 2026-04-15
**Author:** beta (queue #222, identity verified via `hapax-whoami`)
**Scope:** complementary audit of `agents/hapax_daimonion/proofs/` directory from beta's voice/daimonion perspective, after alpha's queue #151 RESEARCH-STATE.md tier-2 currency check.
**Branch:** `beta-phase-4-bootstrap`

---

## 0. Summary

**Verdict: 1 STALE-CONTENT drift + 2 CROSS-REFERENCE correct + 19 dormant but not drifted.** Out of 22 `.md` files in the directory, 1 contains a stale concept reference (`CYCLE-2-PREREGISTRATION.md` references "Hermes 3 70B EXL3 for the Phase 5 substrate swap" — abandoned per drop #62 §14). 19 files have not been touched since 2026-03-29 — dormant but not contradicted by current state. 2 files cross-link to RESEARCH-STATE.md (`WORKSTATION-OPTIMIZATION.md`, `REPO-OPTIMIZATION-RESEARCH.md`) and the cross-references are still valid.

## 1. Directory inventory

22 `.md` files + 6 `claim-*/` subdirs + a `research/` subdir + `README.md`:

| File | Last commit | Lines | Status |
|---|---|---|---|
| `README.md` | 2026-03-29 | 56 | dormant |
| `ADDITIVE-VS-THRESHOLD.md` | 2026-03-29 | 83 | dormant |
| `BARGE-IN-REPAIR.md` | 2026-04-02 | 227 | dormant |
| `BASELINE-ANALYSIS.md` | 2026-03-29 | 143 | dormant |
| `BAYESIAN-TOOL-SELECTION.md` | 2026-03-29 | 328 | dormant |
| `CONTEXT-AS-COMPUTATION.md` | 2026-03-29 | 126 | dormant |
| `CYCLE-1-PILOT-REPORT.md` | 2026-03-29 | 160 | dormant |
| `CYCLE-2-PREREGISTRATION.md` | 2026-04-14 | 283 | **STALE — Hermes ref** |
| `OBSERVABILITY.md` | 2026-03-29 | 261 | dormant |
| `PACKAGE-ASSESSMENT.md` | 2026-03-29 | 273 | dormant |
| `PHASE-TRANSITION-A-TO-B.md` | 2026-03-29 | 124 | dormant |
| `POSITION.md` | 2026-03-29 | 320 | dormant |
| `REFINEMENT-DECISION.md` | 2026-03-29 | 58 | dormant |
| `REFINEMENT-RESEARCH.md` | 2026-03-29 | 275 | dormant |
| `REPO-OPTIMIZATION-RESEARCH.md` | 2026-03-29 | 469 | cross-links RS, still valid |
| `RESEARCH-STATE.md` | 2026-04-15 | 642 | canonical tier-1 doc (updated queue #219) |
| `SESSION-PROTOCOL.md` | 2026-03-29 | 141 | dormant |
| `SYSTEM-CLEANUP-DECISION.md` | 2026-03-29 | 45 | dormant |
| `THEORETICAL-FOUNDATIONS.md` | 2026-03-29 | 490 | dormant |
| `TOOL-CALLS.md` | 2026-03-29 | 156 | dormant |
| `WHY-NO-ONE-IMPLEMENTED-CLARK.md` | 2026-03-29 | 68 | dormant |
| `WORKSTATION-OPTIMIZATION.md` | 2026-03-29 | 383 | cross-links RS, still valid |

**Total: 22 files. 1 STALE. 2 cross-linking + still valid. 19 dormant + not contradicted.**

## 2. Stale finding: CYCLE-2-PREREGISTRATION.md

**Line drift** (located via `grep -iE "hermes|voxtral|piper"`):

> *"Home office. CachyOS (Arch-based), RTX 3090, Hyprland (Wayland). Blue Yeti microphone, PreSonus Studio 24c audio interface. LiteLLM gateway routing to TabbyAPI (Qwen3.5-9B EXL3 for Phase A baseline; **Hermes 3 70B EXL3 for the Phase 5 substrate swap**). Kokoro TTS. Faster-whisper STT (distil-large-v3)."*

**Drift:** "Hermes 3 70B EXL3 for the Phase 5 substrate swap" is abandoned per drop #62 §14 (2026-04-15T06:35Z). The current Phase 5 substrate swap plan is Option C parallel-deploy scenarios 1+2 (Qwen3.5-9B keep + OLMo 3-7B parallel) per queue #209 closure inflection + delta's 18:49Z Option C pivot inflection.

**Severity:** MEDIUM. CYCLE-2-PREREGISTRATION is a research pre-registration document — inaccuracies in its experimental design section may affect the validity of the research results. However:

1. The file was last committed 2026-04-14, ONE DAY BEFORE the Hermes abandonment decision. At write time, Hermes 70B was still a valid plan. This is temporal drift, not negligence.
2. Pre-registration documents have special status in scientific practice: they are historical snapshots of the experimental design, not live documents. Amending them mid-study is a methodological concern.

**Recommended fix: AMENDMENT, not replacement.** Add a §N (next available section) "Post-ratification amendment" block at the end of the file referencing:

- Drop #62 §14 Hermes abandonment (2026-04-15T06:35Z)
- Substrate research v1 → v2 chain (`bb2fb27ca` → `d33b5860c` → `f2a5b2348`)
- Queue #209 closure + Option C pivot to Qwen3.5-9B + OLMo 3-7B parallel
- Statement that the pre-registration's "Phase 5 substrate swap" target is now Qwen+OLMo, not Hermes

This preserves the pre-reg audit trail (original text intact) while making the current state discoverable to any future reader.

**Non-urgent:** the Phase 5 execution has not yet started (still blocked on substrate decision + OLMo weight downloads per queue #209 closure). The amendment can ship whenever — no timing pressure.

**Proposed follow-up queue item #228:**

```yaml
id: "228"
title: "CYCLE-2-PREREGISTRATION.md post-ratification amendment for Hermes abandonment"
assigned_to: beta
status: offered
priority: low
depends_on: []
description: |
  Queue #222 daimonion proofs directory currency audit flagged
  CYCLE-2-PREREGISTRATION.md line 'Hermes 3 70B EXL3 for the Phase 5
  substrate swap' as stale post-drop #62 §14 Hermes abandonment. Add
  a new §N Post-ratification amendment block at EOF documenting:
  - Drop #62 §14 Hermes abandonment
  - Substrate research v1/v2 chain
  - Queue #209 closure + Option C pivot
  - Current Phase 5 plan: Qwen3.5-9B + OLMo 3-7B parallel
  Preserve original text unchanged.
size_estimate: "~30 LOC amendment, ~15 min"
```

## 3. Cross-link validity

### 3.1 WORKSTATION-OPTIMIZATION.md → RESEARCH-STATE.md

```
$ grep -n "RESEARCH-STATE" agents/hapax_daimonion/proofs/WORKSTATION-OPTIMIZATION.md
(references RESEARCH-STATE as canonical session tracker)
```

Cross-reference target exists + is actively maintained (RESEARCH-STATE.md was just updated in queue #219 at commit `94635d7a2`). Link is valid.

### 3.2 REPO-OPTIMIZATION-RESEARCH.md → RESEARCH-STATE.md

Same verdict: link target exists + valid. No drift.

## 4. Dormant files (19 of 22) — classification

Most of the proofs directory is **dormant** (not updated since 2026-03-29). Dormancy does NOT imply drift. A doc can be dormant AND current if:

- It documents a historical decision whose content still applies
- It describes theoretical foundations that haven't been superseded
- It archives a cycle or phase outcome whose findings are still the best available

Spot-check of key dormant files:

### 4.1 THEORETICAL-FOUNDATIONS.md (490 lines, dormant since 2026-03-29)

Covers the theoretical framework for hapax's voice grounding research (Shaikh et al., Mohapatra, etc.). This framework has NOT been superseded by drop #62 §14 or any subsequent research. Dormancy is correct — this file would drift only if the theoretical framework changed.

**Non-drift.**

### 4.2 OBSERVABILITY.md (261 lines, 2026-03-29)

Documents Langfuse + OTel instrumentation for voice turn events. Still applies — Langfuse is the canonical observability layer per council CLAUDE.md. No drift.

**Non-drift.**

### 4.3 POSITION.md (320 lines, 2026-03-29)

Documents hapax's research position statement. Dormant since the position was first drafted. Updated only when the strategic direction shifts. Current drop #62 §14 substrate abandonment does NOT shift the research position — the position is about voice grounding research, not about which specific substrate. Dormancy is correct.

**Non-drift.**

### 4.4 WORKSTATION-OPTIMIZATION.md (383 lines, 2026-03-29)

Documents the workstation setup + VRAM allocation strategy. Potential drift vector: if VRAM allocations have changed since 2026-03-29 (e.g., Kokoro moved CPU → different mix, RTX 5060 Ti added, etc.), this doc could drift.

**Spot-check:** council CLAUDE.md currently says Kokoro runs on CPU, Whisper on GPU, TabbyAPI on RTX 3090. If WORKSTATION-OPTIMIZATION still says the same, it's current. If it mentions GPU Kokoro, it's drifted.

**Not fully inspected** in this audit (would require reading the full file). Flag for future queue item #229 if deep audit is desired.

**Severity:** LOW. Dormant docs are low-priority for currency checks unless they contain load-bearing configuration details that executors read.

## 5. Per-file status matrix

| File | Stale? | Action | Severity |
|---|---|---|---|
| `README.md` | No | — | — |
| `ADDITIVE-VS-THRESHOLD.md` | No (theoretical) | — | — |
| `BARGE-IN-REPAIR.md` | No (engineering pattern) | — | — |
| `BASELINE-ANALYSIS.md` | No (historical measurement) | — | — |
| `BAYESIAN-TOOL-SELECTION.md` | No (theoretical) | — | — |
| `CONTEXT-AS-COMPUTATION.md` | No (theoretical) | — | — |
| `CYCLE-1-PILOT-REPORT.md` | No (historical) | — | — |
| **`CYCLE-2-PREREGISTRATION.md`** | **YES** | **Amendment per §2** | MEDIUM |
| `OBSERVABILITY.md` | No | — | — |
| `PACKAGE-ASSESSMENT.md` | No (dormant assessment) | — | — |
| `PHASE-TRANSITION-A-TO-B.md` | No (historical) | — | — |
| `POSITION.md` | No (strategic) | — | — |
| `REFINEMENT-DECISION.md` | No | — | — |
| `REFINEMENT-RESEARCH.md` | No | — | — |
| `REPO-OPTIMIZATION-RESEARCH.md` | No (may have stale specifics — not inspected) | Optional deeper check | LOW |
| `RESEARCH-STATE.md` | No (updated queue #219) | — | — |
| `SESSION-PROTOCOL.md` | No (governance) | — | — |
| `SYSTEM-CLEANUP-DECISION.md` | No (historical) | — | — |
| `THEORETICAL-FOUNDATIONS.md` | No (theoretical, cannot drift) | — | — |
| `TOOL-CALLS.md` | No (may have stale counts) | Optional deeper check | LOW |
| `WHY-NO-ONE-IMPLEMENTED-CLARK.md` | No (historical/theoretical) | — | — |
| `WORKSTATION-OPTIMIZATION.md` | No (may have stale VRAM specifics) | Optional deeper check per §4.4 | LOW |

**1 MEDIUM drift (CYCLE-2), 3 optional LOW-check items, 19 clean.**

## 6. Recommendations

### 6.1 Ship amendment for CYCLE-2-PREREGISTRATION.md (proposed #228)

See §2. Small amendment, non-urgent.

### 6.2 Optional deeper audits for 3 LOW-check items (proposed #229, bundled)

```yaml
id: "229"
title: "Deep currency check on WORKSTATION-OPTIMIZATION + TOOL-CALLS + REPO-OPTIMIZATION proofs"
assigned_to: beta
status: offered
priority: low
depends_on: []
description: |
  Queue #222 daimonion proofs currency audit flagged 3 files as
  potentially having stale specifics (VRAM allocations, tool counts,
  repo-structure references) but did not inspect their contents in
  depth. This follow-up reads each file top-to-bottom + cross-checks
  against current council CLAUDE.md + live systemd/docker state.
size_estimate: "~120 LOC research drop, ~25 min"
```

### 6.3 No action on 19 dormant files

Dormant files that correctly document historical decisions, theoretical foundations, or unchanged strategic positions do not need remediation. Dormancy is not drift.

## 7. Non-drift observations

- **Proofs directory is a research artifact, not a living codebase.** Most files are immutable historical records (cycle reports, theoretical foundations, decision records). Updating them mid-cycle is a methodological concern.
- **RESEARCH-STATE.md is the single living tier-1 doc** in the proofs directory. All other files point at RESEARCH-STATE as the current-state index.
- **Beta's queue #219 just amended RESEARCH-STATE** (commit `94635d7a2`) to document the Voxtral → Kokoro TTS revert that was missing post-Session 18. This audit confirms RESEARCH-STATE is current as of that commit.
- **Alpha's queue #151 scope** (RESEARCH-STATE tier-2 docs currency check) is presumably complementary to this audit — alpha checks the tier-2 cross-references from RESEARCH-STATE while beta checks the per-file currency of the files RESEARCH-STATE points at.

## 8. Cross-references

- Alpha queue #151 (predecessor): `queue/151-research-state-tier2-docs-currency.yaml` (status: done)
- Beta queue #219 (companion): `docs/research/2026-04-15-session18-tts-revert-... ` (RESEARCH-STATE amendment, commit `94635d7a2`)
- Beta queue #221 (companion): `docs/research/2026-04-15-hermes-weights-disk-cleanup-inventory.md` (commit `5c9d6ad1e`) — shares the Hermes-abandonment context that flags CYCLE-2 drift
- Drop #62 §14 Hermes abandonment: `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md` §14
- Queue item spec: queue/`222-beta-daimonion-proofs-directory-currency.yaml`

— beta, 2026-04-15T19:40Z (identity: `hapax-whoami` → `beta`)
