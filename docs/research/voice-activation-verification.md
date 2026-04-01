# Voice Pipeline Subsystem Verification

**Date:** 2026-03-31
**Branch:** main
**Source:** hapax-council (primary worktree)

## Results

| # | Subsystem | Status | Notes |
|---|-----------|--------|-------|
| 1 | Tool execution path | **PASS** | `kwargs["tools"] = self.tools` and `await self._handle_tool_calls` both present in `ConversationPipeline._generate_and_speak` |
| 2 | Grounding in R&D mode | **PASS** | `_apply_mode_grounding_defaults` returns all 5 flags true: `grounding_directive`, `effort_modulation`, `cross_session`, `stable_frame`, `message_drop` |
| 3 | Emoji stripping | **PASS** | `_strip_emoji('Hello 🎵 world 🎉 test')` → `"Hello  world  test"`, emoji removed correctly |
| 4 | Acoustic impulse writer | **PARTIAL** | Function and path (`/dev/shm/hapax-visual/acoustic-impulse.json`) are correct; `source == "daimonion"` confirmed. Silent audio (zeros) silently no-ops due to noise floor check (`energy < 0.01`); non-zero audio writes correctly. The original test used all-zero PCM which is below the threshold — not a bug, but caller must pass real audio |
| 5 | Bridge presynthesis | **PASS** | Logs confirm 51/51 bridge phrases pre-synthesized at every recent startup (most recent: 18:07 today, 61.7s). Wired in `init_audio.py` → `BridgeEngine()`, pre-synthesis called in `run_inner.py` and `pipeline_start.py` |
| 6 | Echo cancellation wiring | **PASS** | `feed_reference()` called at 4 sites in `conversation_pipeline.py` (lines 693, 1229, 1341, 1698); `echo_canceller.py` implements thread-safe ring buffer |
| 7 | Speaker ID without pyannote | **PARTIAL** | `SpeakerIdentifier` instantiates cleanly but uses `_enrolled` (not `_operator_embedding` — the test used the wrong attribute name). Enrollment loads from file if path provided; without enrollment path, `identify()` returns `uncertain/0.0`. Pyannote is lazy-loaded only when `extract_embedding()` is called and `HF_TOKEN` is set. Functional but enrollment file presence is a runtime dependency |
| 8 | Proactive speech path | **PASS** | `impingement_consumer_loop` imported and registered as background task in `run_inner.py:126`. `generate_spontaneous_speech` at `conversation_pipeline.py:185`. `WorkspaceMonitor` wires proactive routing at `workspace_monitor.py:289`. `capability.py` registers `"spontaneous_speech"` capability |
| 9 | Context enrichment sections | **PASS** | `context_enrichment.py` implements `render_goals`, `render_health`, `render_nudges`, `render_dmn`. All four are wired in `init_pipeline.py` and assigned to daemon slots (`_goals_fn`, `_health_fn`, `_nudges_fn`, `_dmn_fn`). Goals, health, nudges, and DMN buffer all covered |
| 10 | Ollama preloading | **PARTIAL** | No Ollama-specific `keep_alive=-1` or warmup call found in `run_inner.py` or `daemon.py`. `run_inner.py:47` calls `daemon.tts.preload()` (TTS warmup) and `run_inner.py:67` runs embedding warmup. Ollama model itself is not explicitly preloaded — cold-start latency on first use possible |

## Summary

- **PASS:** 6/10 (tool path, grounding, emoji strip, bridge presynthesis, echo cancellation, context enrichment, proactive speech)
- **PARTIAL:** 3/10 (acoustic impulse, speaker ID, Ollama preload)
- **FAIL:** 0/10

### Partial details

**Acoustic impulse (#4):** Not broken — noise floor guard is intentional. The diagnostic test used all-zero PCM which correctly no-ops. The function and shm path work as expected when called with real audio.

**Speaker ID (#7):** The test probed `_operator_embedding` which does not exist; the attribute is `_enrolled`. Functionally operational; enrollment loaded at init if path provided. Pyannote only loaded on `extract_embedding()` call.

**Ollama preload (#10):** TTS and embedding warmup present; no Ollama model keep-alive or warm-ping at startup. First call to a local Ollama model (e.g. qwen3:4b for DMN) will cold-start.
