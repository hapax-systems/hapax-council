# Deviation Record: DEVIATION-032

**Date:** 2026-03-30
**Phase at time of change:** baseline
**Author:** hapax

## What Changed

`agents/hapax_daimonion/grounding_ledger.py` — `_STRATEGY_DIRECTIVES` dict and `grounding_directive()` method updated to encode Traum (1994) responsive grounding acts as directive text. No state machine logic changed. Specifically:

- `rephrase` directive: added Acknowledge act prefix before Repair
- `elaborate` directive: reframed as Request-Repair (ask what's unclear)
- `present_reasoning` directive: added Acknowledge act prefix before reasoning presentation
- `neutral` directive: added check-understanding act (Request-Acknowledge)
- `move_on` directive: added "start fresh" instruction
- `grounding_directive()`: added explicit `PENDING + len >= 2` branch (was already default neutral)

## Why

Gap closure task: strategy directives previously described what to do (rephrase, elaborate) without encoding the responsive grounding act sequence Traum specifies. REPAIR_1 should be Acknowledge+Repair, not just Repair. The change makes the LLM directive text conform to the grounding theory the ledger is built on.

## Impact on Experiment Validity

Minimal. The state machine transitions (what states are reached under what signals) are unchanged. Only the natural language directive text injected into VOLATILE band is modified. Experiment metrics based on state transition sequences are unaffected. If experiment measures directive text quality or LLM behavior, this is an intentional improvement, not a confound.

## Mitigation

All 31 existing grounding ledger tests pass. 6 new tests added covering the Traum act encodings. No state transition logic was modified.
