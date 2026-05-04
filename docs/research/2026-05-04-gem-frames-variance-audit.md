# GEM Frames Variance Audit

Date: 2026-05-04
Task: `gem-frames-variance-audit`
Branch: `codex/cx-violet-gem-frames-variance-audit`

## Surface

Producer:

- `agents/hapax_daimonion/gem_producer.py` tails the impingement bus for
  `gem.emphasis.*` and `gem.composition.*` intent families, then writes
  `/dev/shm/hapax-compositor/gem-frames.json`.
- `agents/hapax_daimonion/run_inner.py` starts `gem_producer_loop` with the
  daemon background tasks.

Consumer:

- `agents/studio_compositor/gem_source.py` reads `gem-frames.json` into
  `GemFrame` rows and renders the active GEM ward.

Tests:

- `tests/hapax_daimonion/test_gem_producer.py`
- `tests/hapax_daimonion/test_gem_authoring_agent.py`
- `tests/studio_compositor/test_gem_source.py`

## Runtime Finding

At audit start, the live file was:

```json
{"frames": [{"text": " ", "hold_ms": 100}], "written_ts": 1777864629.9330642}
```

The file existed at `/dev/shm/hapax-compositor/gem-frames.json`, size 77, with
mtime `2026-05-03 22:17:09.933143485 -0500`. This is a valid JSON payload but
not renderable GEM content. Before this patch, the compositor accepted it as a
real one-frame sequence, so the GEM ward could sit on an inert space frame
instead of falling back to `» hapax «` or holding the last valid authored frame.

## Code Finding

`origin/main` had drift between tests and implementation:

- Existing producer tests expected non-GEM, empty, and emoji payloads to return
  no frames.
- The implementation returned `[GemFrame(text=" ", hold_ms=100)]`, which the
  loop then published.
- The emphasis template docstring described a three-frame sequence, while the
  implementation emitted one long-held frame.

This created both a blank-frame failure and a low-variance failure.

## Patch

- Invalid, non-GEM, empty, corrupt, and emoji-only producer inputs now return no
  frames, so the loop does not overwrite the last valid sequence.
- `write_frames_atomic()` refuses a payload with no renderable frame.
- The compositor frame reader ignores whitespace-only and emoji-containing
  frame entries and falls back when nothing renderable remains.
- The emphasis template again emits three distinct frames for one authored
  emphasis, restoring minimal sequence variance without adding LLM calls.

## Follow-Ups

- `gem-frame-runtime-witness-metric`: emit a small health row for frame count,
  blank-frame rejections, stale age, and distinct-text count.
- `gem-authoring-semantic-novelty-ledger`: compare recent authored GEM texts
  against rolling history to detect low semantic variance beyond exact repeats.
