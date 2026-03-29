# Deviation Record: DEVIATION-024

**Date:** 2026-03-29
**Phase at time of change:** baseline
**Author:** Claude (beta session)

## What Changed

`agents/hapax_voice/conversation_pipeline.py` lines 432-453: `generate_spontaneous_speech` now detects `source == "imagination"` impingements and uses an imagination-specific prompt that includes the fragment narrative and content reference summaries, instead of the generic metric-based prompt.

`agents/hapax_voice/__main__.py` lines 1894-1900: proactive gate now calls `generate_spontaneous_speech(imp)` via `asyncio.create_task` when the gate passes, instead of only logging.

## Why

Completes the proactive utterance TTS path. Previously, the proactive gate would fire and log but no speech would be generated. Now high-salience imagination fragments (≥0.8) that pass the gate conditions trigger actual LLM generation + TTS output through the existing spontaneous speech pipeline.

## Impact on Experiment Validity

Low. Changes are in the spontaneous speech path (not the main conversation loop). The imagination-specific prompt only activates when `source == "imagination"` — existing cascade-recruited speech uses the unchanged metric-based prompt. The `_lockdown` flag does not gate spontaneous speech generation (it gates volatile context only).

## Mitigation

Both paths (imagination and non-imagination) terminate at `_speak_sentence()` — same TTS output path, same audio output. No experiment variables affected.
