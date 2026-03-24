# Deviation Record: DEVIATION-010

**Date:** 2026-03-24
**Phase at time of change:** baseline (not yet started)
**Author:** Claude Opus 4.6 (alpha session)

## What Changed

`agents/hapax_voice/conversation_pipeline.py` — added `deliver_notification()` method (23 lines). Direct TTS delivery of queued notifications during active silence, bypassing LLM round-trip.

`agents/hapax_voice/cognitive_loop.py` — replaced TODO comment in `_handle_silence()` with actual dequeue-and-deliver call (10 lines). Requeues on failed delivery.

## Why

Feature audit identified that the entire notification infrastructure (NotificationQueue, NotificationRouter, NtfyListener, WorkspaceMonitor) was built and running but notifications silently expired — the last-mile delivery path was never wired. This is a functional gap, not a research change.

## Impact on Experiment Validity

None. The new method:
- Is only called during `active_silence_enabled` sessions (feature-flagged, off by default)
- Uses direct TTS (`_speak_sentence`), not the LLM generation path
- Does not modify system prompts, grounding ledger, acceptance scoring, conversation thread, or any experiment-relevant code path
- Does not fire during experiment sessions (active silence is disabled during baseline)

## Mitigation

Method is gated behind `active_silence_enabled` flag (default False). Experiment sessions do not enable active silence. No mitigation beyond existing feature gate required.
