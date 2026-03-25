---
id: DEVIATION-013
date: 2026-03-24
phase: baseline
paths:
  - agents/hapax_voice/conversation_pipeline.py
justification: |
  Infrastructure change only — adding atomic write (tmp+rename) and debug
  logging to the GQI shared memory write path. No changes to experiment
  variables, grounding logic, prompt construction, or model behavior.
  The GQI write was already present but used non-atomic write without
  logging. This change makes the write observable and crash-safe.
risk: none
approved_by: operator
---

## Changes

- `conversation_pipeline.py`: GQI write to `/dev/shm/hapax-voice/grounding-quality.json`
  uses atomic tmp+rename pattern (prevents partial reads by stimmung consumer).
  Added `log.debug` on success and failure (was silent `except: pass`).

## Impact on Experiment

None. The GQI value, computation, and frequency are unchanged. Only the
I/O mechanism and observability are improved. No experiment variables
(grounding directive, effort level, acceptance scoring, thread rendering)
are affected.
