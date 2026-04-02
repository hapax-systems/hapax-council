# CPAL Audit Fixes — All 15 Findings

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all 15 findings from the CPAL audit: 2 critical, 5 important, 5 fragility, 3 dead code.

**Architecture:** Wiring fixes in pipeline_start.py (grounding ledger + audio output), session_events.py (hotkey path + engagement hooks), runner.py (utterance queue + blocking TTS), run_loops.py (duplicate check), plus cleanup of dead code.

---

## Task A: Pipeline wiring — grounding ledger + audio output + unwiring on close

Fixes audit #2 (stale pipeline ref), #4 (grounding ledger), #5 (audio output).

**Files:**
- Modify: `agents/hapax_daimonion/pipeline_start.py` — wire ledger + audio after pipeline.start()
- Modify: `agents/hapax_daimonion/pipeline_lifecycle.py` — unwire CPAL on pipeline stop

**Changes:**

In `pipeline_start.py`, after the existing `daemon._cpal_runner.set_pipeline()` call, add:

```python
    # Wire grounding ledger for GQI feedback loop
    if getattr(daemon._conversation_pipeline, "_grounding_ledger", None) is not None:
        daemon._cpal_runner.set_grounding_ledger(
            daemon._conversation_pipeline._grounding_ledger
        )

    # Wire audio output for T1 acknowledgments + backchannels
    if getattr(daemon._conversation_pipeline, "_audio_output", None) is not None:
        daemon._cpal_runner._audio_output = daemon._conversation_pipeline._audio_output
```

In `pipeline_lifecycle.py` `stop_pipeline()`, after stopping the pipeline, add:

```python
    if daemon._cpal_runner is not None:
        daemon._cpal_runner.set_pipeline(None)
        daemon._cpal_runner._audio_output = None
```

---

## Task B: Hotkey path — buffer activation + CPAL wiring

Fixes audit #1 (hotkey path deaf).

**Files:**
- Modify: `agents/hapax_daimonion/session_events.py`

Extract shared session-open logic from `on_engagement_detected` into a helper `_open_session(daemon, trigger)`. Both `on_engagement_detected` and `handle_hotkey` call it.

```python
async def _open_session(daemon: VoiceDaemon, trigger: str) -> None:
    """Open session, activate buffer, start pipeline, wire CPAL."""
    acknowledge(daemon, "activation")
    daemon.governor.engagement_active = True
    daemon._frame_gate.set_directive("process")
    daemon.session.open(trigger=trigger)
    daemon.session.set_speaker("operator", confidence=1.0)
    daemon._conversation_buffer.activate()
    log.info("Session opened via %s", trigger)
    daemon.event_log.set_session_id(daemon.session.session_id)
    daemon.event_log.emit("session_lifecycle", action="opened", trigger=trigger)

    if daemon._conversation_pipeline is None:
        try:
            await daemon._start_pipeline()
            if daemon._cpal_runner is not None:
                daemon._cpal_runner.set_pipeline(daemon._conversation_pipeline)
            log.info("Pipeline started for CPAL T3")
        except Exception:
            log.exception("Pipeline start failed — closing session")
            await close_session(daemon, reason="pipeline_start_failed")
```

Then `on_engagement_detected` does gain boost + axiom veto + calls `_open_session`.
`handle_hotkey` "toggle"/"open" does axiom veto + calls `_open_session`.

This also fixes audit #12 (pipeline start failure leaves zombie session) — the except block now closes the session.

---

## Task C: Engagement lifecycle hooks

Fixes audit #3 (context window + follow-up window inert).

**Files:**
- Modify: `agents/hapax_daimonion/session_events.py` — call `notify_session_closed` in `close_session`
- Modify: `agents/hapax_daimonion/cpal/runner.py` — call `notify_system_spoke` after T3 completes

In `close_session()`, before `daemon.session.close()`:
```python
    if hasattr(daemon, "_engagement"):
        daemon._engagement.notify_session_closed()
```

In `runner.py` `_process_utterance()`, after successful T3 (line ~310):
```python
    if self._daemon is not None and hasattr(self._daemon, "_engagement"):
        self._daemon._engagement.notify_system_spoke()
```

---

## Task D: CPAL runner hardening — blocking TTS + utterance drop + thread safety

Fixes audit #8 (blocking TTS), #9 (utterance drop), #7 (ensure_future fragility).

**Files:**
- Modify: `agents/hapax_daimonion/cpal/runner.py` — fix TTS in tick, log dropped utterances
- Modify: `agents/hapax_daimonion/run_inner.py` — thread-safe engagement callback

**Session timeout TTS** (runner.py ~line 190): wrap in executor:
```python
    loop = asyncio.get_running_loop()
    pcm = await loop.run_in_executor(None, d.tts.synthesize, msg, "conversation")
```

**Utterance dropping** (runner.py ~line 203): log when dropping:
```python
    if utterance is not None and self._processing_utterance:
        log.info("CPAL: utterance arrived during processing — queued for next tick")
        self._queued_utterance = utterance
    elif utterance is not None:
        asyncio.create_task(self._process_utterance(utterance))
```

And at the start of the utterance check, try the queued one first:
```python
    utterance = self._queued_utterance or self._perception.get_utterance()
    self._queued_utterance = None
```

**Thread-safe engagement** (run_inner.py ~line 64):
```python
    daemon._engagement = EngagementClassifier(
        on_engaged=lambda: daemon._loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(on_engagement_detected(daemon))
        ),
    )
```

---

## Task E: Duplicate engagement check + filesystem read cadence

Fixes audit #6 (duplicate check), #11 (filesystem read every tick), #10 (VAD chunk doc).

**Files:**
- Modify: `agents/hapax_daimonion/run_loops.py` — remove outer duplicate engagement check
- Modify: `agents/hapax_daimonion/cpal/runner.py` — throttle _apply_gain_drivers

Remove lines 80-92 in `run_loops.py` (the outer duplicate engagement check that runs after the VAD while loop).

In `_apply_gain_drivers`, add a tick counter to only read every 10 ticks (~1.5s):
```python
    self._gain_driver_tick = getattr(self, "_gain_driver_tick", 0) + 1
    if self._gain_driver_tick % 10 != 0:
        return
```

---

## Task F: Dead code cleanup

Fixes audit #13 (_engagement_signal), #14 (buffer barge-in), #15 (stale doc).

**Files:**
- Modify: `agents/hapax_daimonion/daemon.py` — remove `_engagement_signal`
- Modify: `agents/hapax_daimonion/conversation_buffer.py` — remove dead barge-in fields
- Modify: `agents/hapax_daimonion/proofs/BARGE-IN-REPAIR.md` — update stale reference

Remove `self._engagement_signal = asyncio.Event()` from daemon.py.
Remove `BARGE_IN_PROB`, `BARGE_IN_CONSECUTIVE`, `_barge_in_speech_count`, `barge_in_detected` from conversation_buffer.py.
Update BARGE-IN-REPAIR.md cognitive_loop reference to CPAL runner.

---

## Verification

After all tasks:
```bash
uv run pytest tests/ -q --tb=line --ignore=tests/hapax_daimonion/test_audio_input.py
grep -rn "_engagement_signal\|BARGE_IN_PROB\|cognitive_loop" agents/hapax_daimonion/ --include="*.py" | grep -v __pycache__ | grep -v test
```
