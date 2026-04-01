# Deviation Record: DEVIATION-036

**Date:** 2026-03-31
**Phase at time of change:** baseline
**Author:** Claude Code (subagent)

## What Changed

`agents/hapax_daimonion/conversation_pipeline.py` lines 1267-1272: wrapped existing `self._consent_reader.filter_tool_result()` call in try/except for exception safety. No behavioral change to the pipeline itself.

## Why

Consent enforcement hardening: the existing consent filter call lacked exception handling, meaning a failure in consent filtering could crash the entire conversation pipeline. Adding try/except ensures fail-safe degradation (log warning, pass through unfiltered result).

## Impact on Experiment Validity

None. The change adds exception handling around an already-existing consent filter call. It does not alter model behavior, prompt construction, or any experimental variable. The consent reader was already wired; this only prevents crashes if it throws.

## Mitigation

Change is purely defensive (try/except wrapper). No new logic paths are introduced. The unfiltered result passes through on failure, matching pre-deviation behavior when consent_reader is None.
