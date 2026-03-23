# Deviation Record: DEVIATION-005

**Date:** 2026-03-22
**Phase at time of change:** baseline
**Author:** alpha (Claude Opus 4.6)

## What Changed

Rewritten: `agents/hapax_voice/proofs/CYCLE-2-PREREGISTRATION.md` — comprehensive update to reflect current research state.

Changes:
- Title and research question expanded from "thread injection" to "structured grounding package"
- Background section now includes theoretical basis (Clark, Traum), mechanistic basis (context-as-computation), counter-position, and RLHF correction angle
- Hypotheses reference full package, not just stable_frame
- Phase definitions show all treatment flags
- IV section restructured: 4 treatment components + 1 diagnostic instrument (was 3+1+cross-session separately)
- Carryover concern for A-B-A design documented
- Priors clarified as Cycle 2 Phase A (not Cycle 1)
- Data directory specified as cycle-2 subdirectory
- Analysis code note: stats.py needs BEST implementation
- Added Section 11 (theoretical references)
- Removed personal identifying information
- Added exploratory analyses (quantile comparison, RLHF monitoring)

## Why

Pre-registration document was stale — reflected the state before the refinement research (28 agents), context-as-computation findings, and implementation of Batches 1-4. The IV description was incomplete (only mentioned thread, not ledger/effort/memory). Multiple sections referenced outdated parameters.

## Impact on Experiment Validity

**None on data collection** (Phase A baseline). Pre-registration is not yet filed on OSF. This update brings the document to the current state of the research BEFORE filing, which is the correct sequence. The document will be frozen at filing time.

## Mitigation

Pre-registration must be filed on OSF before Phase B data collection begins. The SHA of the commit containing this version will be recorded as the pre-registration anchor point.
