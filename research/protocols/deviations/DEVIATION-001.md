# Deviation Record: DEVIATION-001

**Date:** 2026-03-30
**Phase at time of change:** baseline
**Author:** Claude Code (phase5 decomposition batch)

## What Changed

`agents/hapax_daimonion/conversation_pipeline.py`: Extracted 238 lines of
helper functions and constants (ThreadEntry dataclass, text processing
utilities, TTS chunking constants, stimmung downgrade logic) into a new
sibling file `conversation_helpers.py`. The pipeline file now imports from
helpers instead of defining them inline. Follow-up: added `_DENSITY_WORD_LIMITS`
and `_stimmung_downgrade` re-exports for test/external backward compat.

## Why

Codebase-wide decomposition of files >500 LOC. The conversation_pipeline.py
was 2083 lines. This refactor moves free functions out while leaving the
ConversationPipeline class unchanged. No behavioral changes.

## Impact on Experiment Validity

None. This is a pure structural refactor:
- No behavioral logic changed
- No constants modified
- No model routing affected
- ConversationPipeline class body is identical
- All imports resolve to the same functions

## Mitigation

- Import paths preserved via re-export
- No changes to any function signatures or return values
- External importers of ThreadEntry, _lcs_word_length, ConvState unaffected
