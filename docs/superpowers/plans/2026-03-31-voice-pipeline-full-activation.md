# Voice Pipeline Full Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify and activate every voice subsystem so the first voice session is a complete experience.

**Architecture:** Verification sweep (10 items already wired in code), then targeted fixes (5 items needing changes). Most work is confirming existing wiring, not writing new code.

**Tech Stack:** Python 3.12, asyncio, LiteLLM, Ollama, Voxtral TTS, PipeWire

**Spec:** `docs/superpowers/specs/2026-03-31-voice-pipeline-full-activation-design.md`

---

### Task 1: Verification sweep — confirm 10 subsystems are wired

This task reads code and runs diagnostic commands to confirm items that appear already wired. No code changes unless something is broken.

**Files:**
- Read-only verification across ~15 files

- [ ] **Step 1: Verify tool execution is live**

Check `agents/hapax_daimonion/conversation_pipeline.py:996-997` passes tools to LLM, and line 1197 calls `_handle_tool_calls`. Check `pipeline_start.py:186` resolves tools from ToolRegistry. In R&D mode, `tool_capability.py:59` only gates tools in research mode.

Run: `uv run python -c "
from agents.hapax_daimonion.pipeline_start import _resolve_tools
print('Tool resolution importable')
"`
Expected: prints "Tool resolution importable"

**Status expected:** ALREADY WIRED. Stale TODO comment at line 1189-1190 is misleading — execution path is live.

- [ ] **Step 2: Verify grounding activates in R&D mode**

Check `pipeline_start.py:16-33` — `_apply_mode_grounding_defaults()` sets `grounding_directive`, `effort_modulation`, `cross_session`, `stable_frame`, `message_drop` via `setdefault()` when mode is R&D and `experiment_mode` is not set.

Run: `uv run python -c "
flags = {}
from agents.hapax_daimonion.pipeline_start import _apply_mode_grounding_defaults
_apply_mode_grounding_defaults(flags)
print(flags)
"`
Expected: `{'grounding_directive': True, 'effort_modulation': True, 'cross_session': True, 'stable_frame': True, 'message_drop': True}` (if current working mode is R&D)

**Status expected:** ALREADY WIRED.

- [ ] **Step 3: Verify emoji stripping in TTS path**

Check `conversation_pipeline.py:1643` calls `_strip_emoji(text)` before TTS. Check `conversation_helpers.py:49` defines the function.

Run: `uv run python -c "
from agents.hapax_daimonion.conversation_helpers import _strip_emoji
print(_strip_emoji('Hello 🎵 world 🎉'))
"`
Expected: `Hello  world ` (emojis removed)

**Status expected:** ALREADY WIRED.

- [ ] **Step 4: Verify acoustic impulse writer in TTS**

Check `tts_executor.py:66-69` calls `write_acoustic_impulse()` after TTS playback. Check `acoustic_impulse.py:21` writes to `/dev/shm/hapax-visual/acoustic-impulse.json`.

Run: `uv run python -c "
from agents.hapax_daimonion.acoustic_impulse import write_acoustic_impulse
import numpy as np
write_acoustic_impulse(np.zeros(4800, dtype=np.int16).tobytes(), sample_rate=24000, channels=1)
import json
print(json.loads(open('/dev/shm/hapax-visual/acoustic-impulse.json').read())['source'])
"`
Expected: `daimonion`

**Status expected:** ALREADY WIRED.

- [ ] **Step 5: Verify bridge phrase presynthesis**

Check `run_inner.py:54-61` calls `daemon._bridge_engine.presynthesize_all(daemon.tts)` at startup. Verify logs show "Bridge phrases presynthesized at startup" during daemon boot.

Run: `journalctl --user -u hapax-daimonion.service --since "5 min ago" --no-pager | grep -i "bridge"`
Expected: "Bridge phrases presynthesized at startup" (or "Bridge presynthesis at startup failed" if Voxtral API unreachable)

**Status expected:** ALREADY WIRED (may fail if Voxtral API unreachable during boot).

- [ ] **Step 6: Verify echo cancellation reference feeding**

Check `echo_canceller.py` has `feed_reference()` called during TTS playback. Check `audio_preprocess.py` or `tts_executor.py` feeds the reference.

Run: `grep -rn "feed_reference\|echo.*ref\|aec.*ref" agents/hapax_daimonion/ | grep -v __pycache__ | head -10`

**Status expected:** ALREADY WIRED.

- [ ] **Step 7: Verify speaker ID works without pyannote**

Check `speaker_id.py` for fallback path when pyannote fails. The daemon log shows "Speaker identifier loaded from speaker_embedding.npy" — the cosine similarity path works independently.

Run: `uv run python -c "
from agents.hapax_daimonion.speaker_id import SpeakerIdentifier
si = SpeakerIdentifier()
print(f'Has embedding: {si._operator_embedding is not None}')
"`

**Status expected:** ALREADY WIRED with fallback.

- [ ] **Step 8: Verify proactive speech path exists**

Check that impingement consumer loop reads impingements, runs affordance pipeline, and can trigger speech. Check `run_loops_aux.py` or equivalent.

Run: `grep -rn "proactive\|impingement_consumer_loop\|spontaneous.*speech" agents/hapax_daimonion/ | grep -v __pycache__ | head -10`

**Status expected:** WIRED but untested end-to-end.

- [ ] **Step 9: Verify context enrichment sections**

Check `env_context.py` or `conversation_helpers.py` for enrichment sections (goals, health, nudges, DMN, imagination, temporal).

Run: `grep -rn "goals\|health.*summary\|nudge\|dmn.*buffer\|imagination.*narrative\|temporal.*context" agents/hapax_daimonion/env_context.py agents/hapax_daimonion/persona.py | head -20`

**Status expected:** Partially wired — some sections may be gated behind experiment flags.

- [ ] **Step 10: Document verification results**

Create a verification checklist file documenting which items passed and which need fixes. This drives Tasks 2-6.

- [ ] **Step 11: Commit verification results**

```bash
git add docs/research/voice-activation-verification.md
git commit -m "docs: voice pipeline verification sweep — 10 subsystems checked"
```

---

### Task 2: Intelligence-first routing — collapse tiers to CAPABLE

**Files:**
- Modify: `agents/hapax_daimonion/salience_router.py:330-338`

- [ ] **Step 1: Read current tier mapping**

Read `salience_router.py:325-340` to understand the `_activation_to_tier` method.

Current logic (lines 330-338):
```python
if activation <= t["canned_max"]:
    return ModelTier.LOCAL
if activation <= t["local_max"]:
    return ModelTier.LOCAL
if activation <= t["fast_max"]:
    return ModelTier.FAST
if activation <= t["strong_max"]:
    return ModelTier.STRONG
return ModelTier.CAPABLE
```

- [ ] **Step 2: Collapse tiers**

Replace the tier selection in `_activation_to_tier` to always return CAPABLE for non-CANNED:

```python
# Intelligence-first: CANNED stays for zero-latency phatic.
# Everything else → CAPABLE. Activation score still computed
# for effort calibration and context annotations.
return ModelTier.CAPABLE
```

The CANNED path is handled earlier in `route()` (line 152-154, phatic detection). `_activation_to_tier` is only called for non-phatic utterances. So returning CAPABLE unconditionally is correct.

- [ ] **Step 3: Run salience router tests**

Run: `uv run pytest tests/ -k "salience" -q`
Expected: Some tests may fail if they assert specific tier outputs. Update test expectations.

- [ ] **Step 4: Commit**

```bash
git add agents/hapax_daimonion/salience_router.py
git commit -m "feat(voice): intelligence-first routing — always CAPABLE for non-phatic"
```

---

### Task 3: Active silence — enable notification delivery during pauses

**Files:**
- Modify: `agents/hapax_daimonion/config.py:227`

- [ ] **Step 1: Enable the flag**

In `config.py:227`, change:
```python
active_silence_enabled: bool = False  # ships dark — contextual actions during silence
```
to:
```python
active_silence_enabled: bool = True
```

- [ ] **Step 2: Verify cognitive loop handles it**

Read `cognitive_loop.py:358` — confirms `if self._active_silence_enabled:` gates the notification delivery and wind-down logic. Read the implementation to verify it's complete (notification delivery at 8s+, wind-down at 20s+).

- [ ] **Step 3: Run cognitive loop tests**

Run: `uv run pytest tests/ -k "cognitive" -q`
Expected: All pass (the flag is passed via constructor, tests may use explicit True/False)

- [ ] **Step 4: Commit**

```bash
git add agents/hapax_daimonion/config.py
git commit -m "feat(voice): enable active silence — notifications during pauses"
```

---

### Task 4: Ollama model preloading at daemon startup

**Files:**
- Modify: `agents/hapax_daimonion/run_inner.py` (after line 70)

- [ ] **Step 1: Add Ollama preload after embedding warmup**

After line 70 in `run_inner.py` (after embedding warmup), add:

```python
    # Preload Ollama models for perception (avoid 5s cold start on first tick)
    try:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            for model in ["qwen3.5:4b", "nomic-embed-text-v2-moe"]:
                resp = await client.post(
                    "http://127.0.0.1:11434/api/generate",
                    json={"model": model, "prompt": "warmup", "keep_alive": -1},
                )
                if resp.status_code == 200:
                    log.info("Ollama model preloaded: %s", model)
                else:
                    log.warning("Ollama preload failed for %s: %d", model, resp.status_code)
    except Exception:
        log.warning("Ollama preload failed (non-fatal)", exc_info=True)
```

- [ ] **Step 2: Verify daemon starts and preloads**

Run: `systemctl --user restart hapax-daimonion.service && sleep 25 && journalctl --user -u hapax-daimonion.service --since "30 sec ago" --no-pager | grep -i "ollama.*preload"`
Expected: "Ollama model preloaded: qwen3.5:4b" and "Ollama model preloaded: nomic-embed-text-v2-moe"

- [ ] **Step 3: Commit**

```bash
git add agents/hapax_daimonion/run_inner.py
git commit -m "feat(voice): preload Ollama models at daemon startup"
```

---

### Task 5: Stimmung voice modulation + Fortress crisis directive

**Files:**
- Modify: `agents/hapax_daimonion/pipeline_start.py` (system prompt injection)
- Modify: `agents/hapax_daimonion/persona.py` (if unfrozen) or `pipeline_start.py` (if frozen)

- [ ] **Step 1: Check if persona.py is frozen**

Run: `grep "persona.py" agents/hapax_daimonion/proofs/experiment-freeze-manifest.txt 2>/dev/null || echo "not in freeze manifest"`

If frozen: inject directive in `pipeline_start.py` (unfrozen) before prompt construction.
If not frozen: inject in `persona.py` system prompt builder.

- [ ] **Step 2: Add stimmung-aware directive injection**

In `pipeline_start.py`, after reading stimmung stance (line 159-167), inject a directive into the system prompt when stance is non-nominal:

```python
_stimmung_directive = ""
if _stimmung_stance == "degraded":
    _stimmung_directive = (
        "\n\n[SYSTEM STATE: DEGRADED] The system is under resource pressure. "
        "Be concise and direct. Prioritize actionable information. "
        "Avoid open-ended exploration."
    )
elif _stimmung_stance == "critical":
    _stimmung_directive = (
        "\n\n[SYSTEM STATE: CRITICAL] The system is in crisis. "
        "Keep responses to one sentence. Only essential information. "
        "Suggest the operator check system health."
    )
```

Pass `_stimmung_directive` to the system prompt builder (append to the prompt string before passing to `ConversationPipeline`).

- [ ] **Step 3: Wire stimmung to effort calibration**

In the same `pipeline_start.py`, after grounding defaults are applied, override effort level when stimmung is non-nominal:

```python
if _stimmung_stance in ("degraded", "critical"):
    _exp["effort_override"] = "EFFICIENT"
```

Then in the grounding ledger or effort calibration path, check for `effort_override` and use it if present. If frozen code prevents this, the directive injection in Step 2 is sufficient — the LLM will self-constrain from the system prompt.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/ -k "pipeline_start or persona" -q`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_daimonion/pipeline_start.py
git commit -m "feat(voice): stimmung-aware response modulation + crisis directive"
```

---

### Task 6: DEVIATION-025 — activation telemetry

**Files:**
- Create: `research/protocols/deviations/DEVIATION-025.md`
- Modify: `agents/hapax_daimonion/conversation_pipeline.py` (3 lines, observability-only)

- [ ] **Step 1: File the deviation record**

Create `research/protocols/deviations/DEVIATION-025.md`:

```markdown
# DEVIATION-025: Activation Score Telemetry

**Date:** 2026-03-31
**Phase:** A (baseline)
**Path:** agents/hapax_daimonion/conversation_pipeline.py
**Zone:** Inner (absolute freeze)

## Change

Add 3 `hapax_score()` calls after salience router returns, logging:
- `novelty` (float, 0-1)
- `concern_overlap` (float, 0-1)
- `dialog_feature_score` (float, 0-1)

## Justification

Observability-only. These calls log numeric scores to Langfuse traces.
They do not alter:
- Model input (system prompt unchanged)
- Model output (response unchanged)
- Model selection (tier unchanged)
- Any behavioral parameter

The salience router already computes these values every turn. This
change makes them visible in Langfuse for Sprint 1 correlation analysis
(Measure 7.2).

## Impact on experiment validity

None. Scores are written after the turn completes. No feedback loop.
```

- [ ] **Step 2: Add the 3 score calls**

Find the location in `conversation_pipeline.py` where the salience router returns an `ActivationBreakdown`. Add after it:

```python
from agents._telemetry import hapax_score
hapax_score("novelty", breakdown.novelty)
hapax_score("concern_overlap", breakdown.concern_overlap)
hapax_score("dialog_feature_score", breakdown.dialog_feature_score)
```

The exact location depends on where `breakdown` is available — check `process_utterance()` for the salience router call.

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/ -k "pipeline" -q`
Expected: All pass (new lines are telemetry-only)

- [ ] **Step 4: Commit**

```bash
git add research/protocols/deviations/DEVIATION-025.md agents/hapax_daimonion/conversation_pipeline.py
git commit -m "feat(voice): DEVIATION-025 — activation score telemetry to Langfuse"
```

---

### Task 7: Clean up stale comments + final verification

**Files:**
- Modify: `agents/hapax_daimonion/conversation_pipeline.py:993-995` (stale comment)
- Modify: `agents/hapax_daimonion/conversation_pipeline.py:1189-1190` (stale TODO)

- [ ] **Step 1: Remove stale tool comments**

In `conversation_pipeline.py`, line 993-995:
```python
# Old:
            # Tools disabled for voice pacing — tool execution + second LLM
            # round-trip adds 10-15s latency that destroys conversation flow.
            # The model answers from system prompt context instead.
# New: (delete these 3 lines — tools are now live)
```

Line 1189-1190:
```python
# Old:
            # TODO: re-enable with tight per-tool timeouts (3s cap) once latency
            # is under control.
# New: (delete these 2 lines — tools are re-enabled with per-tool timeouts)
```

- [ ] **Step 2: Run full affected test suite**

Run: `uv run pytest tests/test_daimonion*.py tests/test_cognitive*.py tests/test_salience*.py tests/test_tool_*.py -q`
Expected: All pass

- [ ] **Step 3: Run lint**

Run: `uv run ruff check agents/hapax_daimonion/conversation_pipeline.py agents/hapax_daimonion/salience_router.py agents/hapax_daimonion/config.py agents/hapax_daimonion/run_inner.py agents/hapax_daimonion/pipeline_start.py`
Expected: Clean

- [ ] **Step 4: Verify daemon starts clean**

Run: `systemctl --user restart hapax-daimonion.service && sleep 20 && systemctl --user is-active hapax-daimonion.service`
Expected: `active`

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_daimonion/conversation_pipeline.py
git commit -m "chore(voice): remove stale tool-disabled comments"
```
