# Deviation Record: DEVIATION-030

**Date:** 2026-03-30
**Phase at time of change:** baseline
**Author:** Claude Code (beta session)

## What Changed

`agents/hapax_daimonion/conversation_pipeline.py` line 818: changed
`from shared.governance.says import Says` to `from agents._governance import Says`.

Import-only change. No behavioral, algorithmic, or data-flow modification.

## Why

Governance dissolution refactor (Phase 5): vendoring shared.governance types
into consumer modules to eliminate cross-module dependency. The Says type is
now provided by agents/_governance.py (a vendored copy of the same code).

## Impact on Experiment Validity

None. The change is a pure import path redirect. The Says class definition,
interface, and behavior are identical. No runtime behavior is affected.

## Mitigation

- Vendored copy is byte-identical to shared/governance/says.py Says class
- All 135 governance tests pass after the change
- All 92 consent integration tests pass after the change
