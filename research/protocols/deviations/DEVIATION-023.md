# Deviation Record: DEVIATION-023

**Date:** 2026-03-27
**Phase at time of change:** baseline
**Author:** Claude (beta session)

## What Changed

`agents/hapax_voice/conversation_pipeline.py` lines 622-632: added imagination context injection block in `_update_system_context`, after the existing goals/health/nudges/DMN context loop and before phenomenal context.

## Why

Wiring the imagination bus into the voice daemon's system context. The imagination context function is injected via the same pattern used by goals, health, nudges, and DMN context functions -- guarded by `_lockdown` and wrapped in a non-fatal try/except.

## Impact on Experiment Validity

Minimal. The change adds an optional context section to the system prompt that is only active when `_imagination_fn` is set (not None) and lockdown is off. During baseline, the imagination bus produces no fragments, so the section will be empty or absent. No existing context functions are modified.

## Mitigation

The imagination context block is gated by `getattr(self, "_imagination_fn", None)` -- returns None if unset, producing no output. The existing context loop and all other context sources are unchanged. Baseline measurements are unaffected unless the imagination bus is explicitly activated.
