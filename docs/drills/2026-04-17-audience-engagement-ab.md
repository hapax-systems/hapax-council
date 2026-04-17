# audience-engagement-ab drill — 2026-04-17

**Description:** A/B research-mode chat behavior across two stream windows and compare engagement metrics.

**Mode:** dry-run
**Started at:** 2026-04-17T13:07:08.593428+00:00

## Pre-checks

- ✅ chat_reactor importable

## Steps executed

- Window A: default chat-reactor sensitivity
- Window B: research-mode chat-reactor sensitivity
- Record reaction count, unique-author count, dwell time for each window
- Tag any audience-feedback that calls out the difference

## Post-checks

- ✅ engagement delta recorded — operator fills in the comparison in the drill doc

## Outcome

**Passed:** yes

## Operator notes

Live run (by alpha, 2026-04-17T13:07Z):

- `agents.studio_compositor.chat_reactor.PresetReactor` import probe green.
- Did NOT execute the A/B windows — requires two live stream sessions with YouTube audience, which is operator-scheduled. Drill is inherently attended.
- Metric-capture plan for the next paired sessions: Stream Moments collector (`/api/studio_moments`) already records reaction counts per preset; we pull two equivalent windows across the two sensitivity settings from the `studio-moments` Qdrant collection and diff engagement at the preset-class level (not per-author — operator and beta have repeatedly pinned that no per-author chat state is persisted; see `agents/studio_compositor/chat_reactor.py` docstring + its caplog test).
- Follow-up: define the "research-mode sensitivity" knob in `chat_reactor.PresetReactor` (it's hard-coded today) before the first A/B so the window B is well-defined.
