# Deviation Record: DEVIATION-028

**Date:** 2026-03-29
**Phase at time of change:** baseline
**Author:** beta session (Claude Code)

## What Changed

- `agents/hapax_daimonion/proofs/RESEARCH-STATE.md`: Added session 19c entry documenting VRAM headroom research and qwen3.5:4b DMN upgrade.
- `agents/hapax_daimonion/proofs/WORKSTATION-OPTIMIZATION.md`: Updated stale qwen3:4b reference to qwen3.5:4b with corrected VRAM figure (2.5GB → 5.6GB).

## Why

Documentation-only changes to keep research context accurate after infrastructure upgrade (PR #430 upgraded DMN model from qwen3:4b to qwen3.5:4b). No code behavior changes in these files.

## Impact on Experiment Validity

None. Both files are documentation/proofs, not experiment code. The DMN model upgrade itself (PR #430) does not affect experiment LLM paths, which route through `balanced`/`fast` tiers.

## Mitigation

Changes are strictly documentation. No model behavior, experiment parameters, or data collection paths were modified.
