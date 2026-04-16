---
title: Daimonion code-narration prep (LRR Phase 9)
date: 2026-04-16
queue_item: '239'
epic: lrr
phase: 9
status: prep
---

# Daimonion code-narration — prep inventory

Per LRR Phase 9 spec: daimonion narrates the operator's code/research activity on-stream. This doc catalogs the integration points needed so Phase 9 execution can begin without rediscovery.

## Integration surface inventory

### 1. Daimonion module hooks

The CPAL loop (`agents/hapax_daimonion/cpal_runner.py`) is the sole audio coordinator (per project memory: "CPAL sole coordinator"). Code-narration must go through `CpalRunner.process_impingement()` — not bypass it with direct TTS calls.

Candidate hook points:

- `agents/hapax_daimonion/run_loops_aux.py::impingement_consumer_loop` — reads `/dev/shm/hapax-dmn/impingements.jsonl`; already handles textual + notification modalities. Code-narration impingements would enter here with modality `auditory` → CPAL speaks them.
- `shared/impingement_consumer.ImpingementConsumer` with `cursor_path=<Path>` mode for daimonion (correctness-critical cursor).
- Spontaneous-speech surfacing via CPAL gain/error modulation — the existing path for DMN-originated speech.

**Integration contract:** a code-narration source writes `{"source": "code_narration", "narrative": "...", "modality": "auditory", "stimmung": {...}}` to `/dev/shm/hapax-dmn/impingements.jsonl`. Daimonion consumes via existing cursor; CPAL speaks.

### 2. chat-signals.json consumer path

Phase 9 §scope calls for chat-structure → stimmung → activity-selection loop. Chat-monitor currently emits structural signals to `/dev/shm/hapax-compositor/chat-signals.json` (verified: chat-monitor.service is live per 2026-04-16 runbook; waiting on `YOUTUBE_VIDEO_ID`).

Consumer chain needed:

1. `agents/stimmung/` reads chat-signals → updates stimmung dimensions (pace, density, tension proxy).
2. `agents/studio_compositor/chat_reactor.py::PresetReactor` (exists; reads chat keywords → preset mutations with 30s cooldown + consent guardrails). Already wired.
3. **Missing:** stimmung-to-activity selection — the director loop (`activity-selection`) needs to read stimmung dimensions directly. Currently activity selection runs on interval + recent-activity only. Adding chat-derived stimmung → director loop weight would close this.

### 3. YouTube description auto-update integration

Spec calls for YouTube description to update when Hapax advances a research objective. Requires:

- YouTube Data API credentials (already present via `scripts/youtube-auth.py` + OAuth token flow).
- A writer module that assembles description text from current `/dev/shm/hapax-dmn/current.json` + active research objective.
- Rate limiting: YouTube quota is ~1000 units/day; a description update costs ~50 units. Cap at 5 updates per stream = 250 units; plenty of headroom.

**Integration point:** new `agents/studio_compositor/youtube_description.py` (not yet created) called from director loop when `research_objective_advance` event fires. Updates via `youtube.videos().update()` with snippet.description field.

### 4. Operator-voice-over-YouTube PipeWire ducking

Spec calls for operator voice to duck YouTube PiP audio. Current state: `agents/studio_compositor/audio_ducking.py` exists (PR #778 audio ducking envelope replacing mute_all cliff). Extension needed:

- Add VAD signal source: Silero VAD already in daimonion (`agents/hapax_daimonion/stt/`). Publish `operator_speech_active` to `/dev/shm/hapax-compositor/voice-state.json`.
- Extend `audio_ducking.py` to read this signal in addition to Hapax-TTS signal; apply duck envelope to YouTube PiP source when active.
- PipeWire filter-chain variant or direct pw-loopback volume control.

## Sequencing

Execution order at Phase 9 open time:

1. Hook 1 (daimonion impingement channel for code-narration) — simplest, zero cross-system
2. Hook 2 (chat-signal → stimmung → director-loop wiring) — moderate, touches 3 modules
3. Hook 4 (operator-voice ducking) — small, localized to compositor audio stack
4. Hook 3 (YouTube description update) — requires API credential verification + quota strategy

Hooks 1 + 2 can run in parallel on separate branches. Hook 3 + 4 depend on operator authorization (quota usage, voice-tracking privacy posture).

## Not in scope for prep

The actual code-narration logic (what to narrate, when to narrate, narration template patterns) is Phase 9 authoring-time work. This prep doc only maps the integration surface.

## Open questions (for Phase 9 opener)

1. Does daimonion's current impingement consumer respect `source: "code_narration"` differently from other impingements (e.g., consent gating, cooldown)? — likely needs explicit whitelist.
2. Is `agents/stimmung/` the right home for chat-structure → stimmung-dimension mapping, or does that belong in `agents/studio_compositor/chat_reactor.py`? — architectural decision for Phase 9.
3. YouTube description updates as Hapax-voice (first-person narrative) vs operator-voice (third-person summary) — persona decision, lands in Phase 7.

— beta, 2026-04-16
