# Deviation Record: DEVIATION-023

**Date:** 2026-03-27
**Phase at time of change:** baseline
**Author:** Claude (alpha session)

## What Changed

`agents/hapax_voice/proofs/RESEARCH-STATE.md`:
- Updated "Last updated" header to include vocal chain and formant voice
- Added formant reference voice paragraph to session 18
- Added vocal chain capability paragraph to session 18
- Added impact assessment for vocal chain (none — downstream of all experiment code)

`docs/compendium.md`:
- Added "Vocal Chain — Hardware Speech Modulation" subsection to §7
- Added decision log entry for vocal chain semantic MIDI affordances

## Why

Research state convention requires updating after implementation progress. Vocal chain capability is infrastructure-only but must be documented for research continuity.

## Impact on Experiment Validity

None. Vocal chain processes audio external to the software pipeline (downstream of PyAudio output). MIDI CC output is additive — if hardware is disconnected, `MidiOutput` becomes a no-op. No experiment code, grounding mechanics, or response timing affected.

## Mitigation

Session entry and decision log explicitly note infrastructure-only scope. Impact assessment confirms no effect on experiment variables.
