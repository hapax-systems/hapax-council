# Deviation Record: DEVIATION-016

**Date:** 2026-03-25
**Phase at time of change:** baseline
**Author:** beta session (Claude Code)

## What Changed

Updated `agents/hapax_voice/proofs/RESEARCH-STATE.md` with session 17 entry documenting perceptual system hardening (PR #322, 20 fixes across 6 subsystems).

## Why

RESEARCH-STATE.md must be updated after every session with implementation progress per the file's own update convention. Session 17 made significant changes to the perceptual substrate consumed by the voice pipeline (grounding ledger, apperception cascade, stimmung thresholds, phenomenal context).

## Impact on Experiment Validity

None. All 20 fixes are in the perceptual/infrastructure substrate. No changes to experiment code paths (persona.py, conversational_policy.py, experiment prompt, DV scoring). The grounding ledger fixes (H7, M5) affect the IGNORE acceptance branch and effort de-escalation hysteresis, but these are mechanical correctness fixes that make existing designed behavior work as specified, not behavioral changes.

## Mitigation

Documentation-only change to a frozen file. The actual code changes (PR #322) were not in frozen paths.
