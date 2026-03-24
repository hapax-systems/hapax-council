# Deviation Record: DEVIATION-009

**Date:** 2026-03-23
**Phase at time of change:** baseline
**Author:** Claude Opus 4.6 (alpha session)

## What Changed

`agents/hapax_voice/proofs/RESEARCH-STATE.md` — added Session 14 entry documenting infrastructure-only work: ingestion pipeline audit, classification inspector, overlay compliance, design language §3.8 completion, signal surfacing.

## Why

RESEARCH-STATE.md is the continuity document for multi-session context. Session 14 performed extensive infrastructure work that must be recorded for future sessions to understand the current system state. The update is documentation-only — recording what was built, not changing experiment code.

## Impact on Experiment Validity

None. All changes in Session 14 are infrastructure-only (data integrity, UI features, design language spec). No changes to: experiment prompts, grounding ledger, acceptance scoring, STT pipeline, conversation policy, phenomenal context, salience router, or any code path exercised during experiment sessions.

## Mitigation

Session 14 entry explicitly states "Infrastructure-only. No changes to experiment code, grounding theory, or research design." at the top, consistent with Sessions 5–13.

---

**Date:** 2026-03-24
**Phase at time of change:** baseline (not yet started)
**Author:** Claude Code (alpha session)

## What Changed

`agents/hapax_voice/proofs/RESEARCH-STATE.md`: Updated session 13 entry to include
stale test repair work (PR #287). Added paragraph documenting 9 test files fixed.

## Why

Research continuity convention requires updating RESEARCH-STATE.md after sessions
with implementation progress. The test repair was infrastructure-only.

## Impact on Experiment Validity

None. RESEARCH-STATE.md is documentation. Not read by experiment code.
Baseline data collection has not yet begun.

## Mitigation

No mitigation required.
