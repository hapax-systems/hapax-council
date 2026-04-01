# Voice Pipeline Full Activation

**Date:** 2026-03-31
**Status:** Design
**Scope:** 15 items across 3 tiers — make every voice subsystem functional before first use

## Problem

The voice pipeline is architecturally complete but untested end-to-end. Multiple subsystems are wired in code but disabled at runtime, gated behind flags, or silently failing. The operator has never used voice because there's no point until everything works. This spec closes every gap so the first session is a complete experience.

## Excluded

- MIDI capabilities (vocal chain, MC actuation) — deferred per operator instruction
- Research experiment protocol changes (frozen code paths)
- New features not already designed

---

## Tier 1: Pipeline won't function correctly without these

### 1.1 Tool execution verification and activation

**Current state:** PR #427 (DEVIATION-026) claims tool execution is re-enabled. `ToolRegistry` is wired, `ToolContext` built per utterance. But the wiring agent found a TODO comment at `conversation_pipeline.py:~1189` suggesting the actual call path may still be gated.

**Fix:** Verify the tool execution path is live. If still gated, the call is in frozen code — file DEVIATION-028 (functional: enables existing tool handler with per-tool 3s timeout, no behavioral change to experiment). The changes are:
1. Ensure `kwargs["tools"] = tools` is uncommented (line ~1233-1234)
2. Ensure `_handle_tool_calls()` is called (not logged-and-skipped)
3. Verify per-tool timeout wrapping exists

**Verification:** `uv run python -c "from agents.hapax_daimonion.conversation_pipeline import ConversationPipeline; print('tool path importable')"` + check that `_handle_tool_calls` is reachable (not behind `if False` or `return` early).

### 1.2 Ollama model preloading

**Current state:** Queue item #009 marked done. Models load lazily on first use (~5s cold start for qwen3.5:4b). The preloading mechanism may exist but isn't verified.

**Fix:** Verify Ollama preload. If missing, add to daemon startup (after STT/TTS preload):
```python
# In run_inner.py, after STT and TTS preload
await asyncio.to_thread(_preload_ollama_models)
```
Where `_preload_ollama_models()` calls `ollama.generate(model="qwen3.5:4b", prompt="warmup", keep_alive=-1)` for each model in the budget. The `keep_alive=-1` flag tells Ollama to keep the model loaded indefinitely.

**Verification:** After daemon restart, first perception tick should complete in <500ms (not 5s).

### 1.3 Grounding activation in R&D mode

**Current state:** PR #427 added `_apply_mode_grounding_defaults()` in `pipeline_start.py`. In R&D mode, all grounding features should be on. Need to verify the flag actually propagates to `ConversationPipeline` at runtime.

**Fix:** Verify by reading the code path:
1. `pipeline_start.py` reads working mode
2. If R&D: sets `enable_grounding=True`, `stable_frame=True`, `grounding_directive=True`, `effort_modulation=True`, `cross_session=True`
3. These flags reach `ConversationPipeline.__init__` and gate the grounding subsystems

If any flag isn't propagating, fix the wiring. If the experiment freeze blocks changes to `conversation_pipeline.py`, the fix is upstream in `pipeline_start.py` or `__main__.py` (both unfrozen).

**Verification:** Start daemon in R&D mode, check logs for "Grounding features active" or equivalent. Verify GQI is computed (check `/dev/shm/hapax-daimonion/grounding-quality.json` exists after a turn).

### 1.4 Context enrichment verification

**Current state:** The system prompt can include goals, health, nudges, DMN buffer, imagination narrative, temporal context. These sections are assembled in `conversation_helpers.py` and `env_context.py`. Unknown if they populate with real data at runtime.

**Fix:** Add a one-time diagnostic that logs the assembled system prompt during a turn. Verify each enrichment section is present and non-empty:
- Goals (from goals API or reactive engine)
- Health summary (from health-history.jsonl)
- Active nudges (from nudge files)
- DMN buffer (from `/dev/shm/hapax-dmn/buffer.txt`)
- Imagination narrative (from `/dev/shm/hapax-dmn/imagination-current.json`)
- Temporal context XML (from VLA temporal bands)

If any section is empty, trace the data source and wire it. Most likely: some sections are gated behind `experiment_mode` or `phenomenal_stimmung_only` flags that need to be off in R&D mode.

**Verification:** Log the assembled context length and section names at INFO level during the first turn of each session.

### 1.5 Intelligence-first routing enforcement

**Current state:** Memory says "always CAPABLE" (Claude Opus). Salience router still has 5 tiers with thresholds (CANNED ≤0.15, LOCAL ≤0.20, FAST ≤0.55, STRONG ≤0.75, CAPABLE >0.75). The router computes activation scores for effort calibration, but the tier selection contradicts the intelligence-first decision.

**Fix:** Two changes:
1. In `salience_router.py` or `model_router.py`: set floor to CAPABLE for all non-CANNED utterances. CANNED stays (zero-latency phatic acknowledgments are valuable). Everything else → CAPABLE.
2. Keep activation score computation — it feeds effort calibration and context annotations. Just don't use it for tier selection.

This is the operator's strongest directive on voice architecture. The salience router becomes a context annotator, not a model selector.

**Verification:** After change, any non-phatic utterance should route to CAPABLE. Check model_router logs.

---

## Tier 2: Degraded experience without these

### 2.1 Active silence

**Current state:** Shipped dark (`active_silence_enabled: False`). Cognitive loop has the code for notification delivery at 8s+ silence and wind-down at 20s+.

**Fix:** Enable the flag in default config. The implementation exists (cognitive_loop.py Batch 6). Verify the notification queue feeds correctly and the temperature gate prevents interrupting operator thought.

**Verification:** During a session, stay silent for 10s. System should deliver a pending notification if one exists. Stay silent 20s+: system should signal wind-down.

### 2.2 Fortress voice modulation

**Current state:** Fortress crisis chains exist (`agents/fortress/chains/crisis.py`). `SystemAwarenessCapability` reads DMN degradation. But no voice behavior changes when stimmung is degraded/critical.

**Fix:** Wire stimmung stance into response generation:
1. In `conversation_pipeline.py` or `persona.py` (check freeze status): when `stimmung_stance` is `degraded` or `critical`, inject a directive: "System is under stress. Be concise and direct. Prioritize actionable information."
2. In the effort calibration: force EFFICIENT when stance is degraded/critical (override GQI-based level).

If `conversation_pipeline.py` is frozen, inject the directive via `pipeline_start.py` or the VOLATILE band assembly (which may be unfrozen).

**Verification:** Simulate degraded stimmung (write to SHM), start a turn, verify the directive appears in the prompt.

### 2.3 Proactive speech verification

**Current state:** The path exists: impingement → affordance pipeline → proactive gate → speech capability → TTS. PR #467 wired `VocalChainCapability.activate_from_impingement()` and `ExpressionCoordinator`. But never tested end-to-end.

**Fix:** Write a synthetic impingement to `/dev/shm/hapax-dmn/impingements.jsonl` with `source: "test.proactive"`, `type: "salience_integration"`, `strength: 0.8`. Verify it flows through to speech output within 60s. If it doesn't, trace the path and fix the break.

**Verification:** Write test impingement, hear speech within 60s.

### 2.4 Stimmung voice behavior modulation

**Current state:** Stimmung is read by `system_awareness.py` and surfaces as an informational gate. But stimmung dimensions (health, resource_pressure, error_rate, etc.) don't modulate voice behavior beyond the binary degraded/critical check.

**Fix:** Wire stimmung dimensions into context enrichment:
1. Include overall stance and top contributing dimensions in the system prompt (VOLATILE band)
2. Use stimmung to modulate effort level: degraded → EFFICIENT, critical → EFFICIENT with emergency directive
3. Use resource_pressure to gate HEAVY tools (already done in ToolCapability.available())

This overlaps with 2.2 (Fortress modulation). Implement together.

**Verification:** Check system prompt includes stimmung stance. Check effort level adjusts with stance.

### 2.5 Acoustic impulse writer in TTS

**Current state:** PR #499 added the Daimonion acoustic impulse writer. ReverieMixer reads it for cross-modal coupling. Need to verify TTS playback actually writes impulse data to `/dev/shm/hapax-visual/acoustic-impulse.json`.

**Fix:** Verify the write happens during TTS playback. If not wired, add to `tts.py` or `audio_executor.py`:
```python
# After TTS synthesis, write acoustic impulse
impulse = {"source": "daimonion", "timestamp": time.time(), "signals": {"energy": rms_energy}}
Path("/dev/shm/hapax-visual/acoustic-impulse.json").write_text(json.dumps(impulse))
```

**Verification:** During TTS playback, check that `/dev/shm/hapax-visual/acoustic-impulse.json` updates. Reverie should show visual response to speech.

---

## Tier 3: Polish

### 3.1 Speaker verification dependency

**Current state:** `pyannote` embedding model fails to load. Speaker verification is fail-open (after 2 attempts, continues without verification). This means the system can't distinguish operator from guests reliably.

**Fix:** Either install the missing dependency (`uv pip install pyannote.audio`) or, if it conflicts with the environment, remove the pyannote path and rely on the simpler cosine-similarity speaker ID that uses the cached operator embedding (`speaker_embedding.npy`). The simpler path may already work — verify.

**Verification:** Check speaker ID logs during a session. If "Speaker verified: operator" appears, the simpler path works.

### 3.2 Emoji stripping in TTS path

**Current state:** Queue item #008 marked done. Need to verify emoji is actually stripped before text reaches Voxtral.

**Fix:** Grep for the emoji strip function, verify it's called in the TTS synthesis path.

**Verification:** `grep -r "strip.*emoji\|emoji.*strip\|remove.*emoji" agents/hapax_daimonion/` should show the function. Trace from pipeline response text → TTS input.

### 3.3 DEVIATION-025 for activation telemetry

**Current state:** Sprint 0 identified this as the critical path for salience validation. Three `hapax_score()` calls needed in `conversation_pipeline.py` for `novelty`, `concern_overlap`, `dialog_feature_score`.

**Fix:** File DEVIATION-025. Add 3 lines after the salience router returns:
```python
hapax_score("novelty", breakdown.novelty)
hapax_score("concern_overlap", breakdown.concern_overlap)
hapax_score("dialog_feature_score", breakdown.dialog_feature_score)
```
This is observability-only — no model input/output change. Impact: none on experiment validity.

**Verification:** After a voice session, query Langfuse for these score names. Should see entries.

### 3.4 Bridge phrase presynthesis

**Current state:** BridgeEngine presynthesizes common phrases at session start. With Voxtral (API-based, ~2-3s latency), caching is critical for responsive "thinking" signals.

**Fix:** Verify presynthesis runs at session start. Check that cached audio exists before the first turn. If Voxtral doesn't support presynthesis well (API latency on short phrases), consider keeping a small set of locally-generated bridge phrases (eSpeak-NG or cached Voxtral).

**Verification:** Check logs for "Bridge phrases cached" or equivalent at session start. Measure time from utterance-end to first bridge phrase playback — should be <200ms from cache.

### 3.5 Echo cancellation quality

**Current state:** PipeWire AEC is broken on 1.6.x. Using speexdsp application-level AEC (500ms tail). The concern is self-transcription — STT picking up the system's own TTS output.

**Fix:** Verify echo cancellation works:
1. During TTS playback, check that the echo canceller reference is being fed
2. After TTS ends, verify STT doesn't transcribe the system's speech
3. Check `POST_TTS_COOLDOWN` (2.0s) prevents premature listening

If self-transcription occurs, increase cooldown or improve AEC reference feeding.

**Verification:** During a 5-turn conversation, check transcription logs for any system-speech content. Should see zero self-transcriptions.

---

## Implementation approach

These 15 items decompose into 3 categories:

**Verification-only (check if already working, fix if not):** 1.1, 1.2, 1.3, 1.4, 2.3, 2.5, 3.1, 3.2, 3.4, 3.5

**Configuration changes (flip flags, adjust thresholds):** 1.5, 2.1

**New wiring (small code changes):** 2.2, 2.4, 3.3

Most items are verification — the code exists, we just need to confirm it works and fix what doesn't. The implementation plan should be organized as a verification sweep (items that might already work) followed by targeted fixes for what's broken, followed by the small amount of new wiring.

## Files likely touched

| File | Items | Frozen? |
|------|-------|---------|
| `agents/hapax_daimonion/conversation_pipeline.py` | 1.1, 3.3 | YES — need DEVIATION-025/028 |
| `agents/hapax_daimonion/salience_router.py` | 1.5 | No |
| `agents/hapax_daimonion/model_router.py` | 1.5 | No |
| `agents/hapax_daimonion/run_inner.py` | 1.2 | No |
| `agents/hapax_daimonion/pipeline_start.py` | 1.3, 2.2, 2.4 | No |
| `agents/hapax_daimonion/cognitive_loop.py` | 2.1 | No |
| `agents/hapax_daimonion/tts.py` | 2.5, 3.2 | No |
| `agents/hapax_daimonion/daemon.py` | 1.2 | No |
| `agents/hapax_daimonion/speaker_id.py` | 3.1 | No |
| `agents/hapax_daimonion/env_context.py` | 1.4 | No |
| `agents/hapax_daimonion/bridge_engine.py` | 3.4 | No |
| `agents/hapax_daimonion/echo_canceller.py` | 3.5 | No |
| `research/protocols/deviations/DEVIATION-025.md` | 3.3 | N/A (new) |
| `research/protocols/deviations/DEVIATION-028.md` | 1.1 | N/A (new) |
