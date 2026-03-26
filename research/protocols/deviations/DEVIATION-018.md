# Deviation Record: DEVIATION-018

**Date:** 2026-03-25
**Phase at time of change:** baseline
**Author:** Claude Opus 4.6 (beta session)

## What Changed

`agents/hapax_voice/conversation_pipeline.py`:
- Added `self._dmn_fn: Callable[[], str] | None = None` field (line 341)
- Added `("dmn", self._dmn_fn)` to enrichment callback loop (line 562)

These add a new optional callback slot for DMN buffer injection into the VOLATILE band. The callback is `None` by default and only populated when the voice daemon registers it.

## Why

The DMN (Default Mode Network) daemon provides continuous background situational awareness. Injecting its buffer into the voice context gives the voice daemon access to accumulated observations without requiring a separate code path. This is part of the impingement-driven activation cascade architecture.

## Impact on Experiment Validity

**Minimal.** The change adds an optional callback that defaults to `None`. When `None`, the behavior is identical to the pre-deviation code — the loop simply skips the entry. No existing enrichment callbacks are modified. The grounding quality experiment's baseline measurements are unaffected because DMN daemon is not running during baseline collection.

## Mitigation

If DMN context is suspected of influencing experiment results, set `self._dmn_fn = None` in the voice daemon init to disable it. The existing `_lockdown` flag in `_update_system_context()` already suppresses all enrichment callbacks during lockdown phases.
