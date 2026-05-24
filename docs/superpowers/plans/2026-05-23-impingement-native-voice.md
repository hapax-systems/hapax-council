# Impingement-Native Voice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dissolve the ConversationPipeline sidecar so operator speech enters the impingement field as a dominant signal, competing on force rather than bypassing the cascade.

**Architecture:** AudioPerceptionBackend emits operator-speech impingements (strength ~1.0). ConversationalResponse capability is recruited via AffordancePipeline when speech wins. Unified SpeechProduction handles all TTS output with ResourceArbiter-enforced preemption. CPAL runner's utterance processing path is removed.

**Tech Stack:** Python 3.12, Silero VAD, Parakeet TDT (ONNX), Chatterbox TTS, PipeWire pw-cat, Qdrant affordances, ResourceArbiter, JSONL impingement bus.

---

### Task 1: AudioPerceptionBackend — Impingement Emitter

**Files:**
- Create: `agents/hapax_daimonion/audio_perception.py`
- Create: `tests/hapax_daimonion/test_audio_perception.py`

This is the core fix. ConversationBuffer's VAD + speech segmentation logic is preserved but wrapped in a PerceptionBackend that emits impingements instead of buffering utterances for direct pickup.

- [ ] **Step 1: Write failing test for AudioPerceptionBackend impingement emission**

```python
"""tests/hapax_daimonion/test_audio_perception.py"""
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_daimonion.audio_perception import AudioPerceptionBackend


class TestAudioPerceptionBackend:
    def _make_backend(self):
        stt = MagicMock()
        stt.transcribe = AsyncMock(return_value="hello hapax")
        stt.is_loaded = True
        speaker_id = MagicMock()
        speaker_id.identify.return_value = ("operator", 0.92)
        return AudioPerceptionBackend(stt=stt, speaker_id=speaker_id)

    def test_provides_audio_behaviors(self):
        backend = self._make_backend()
        assert "speech_detected" in backend.provides
        assert "audio_event" in backend.provides

    def test_name(self):
        backend = self._make_backend()
        assert backend.name == "audio"

    @pytest.mark.asyncio
    async def test_operator_speech_emits_impingement(self):
        backend = self._make_backend()
        backend.start()

        # Simulate speech detection completing with a transcribed utterance
        backend._emit_speech_impingement(
            transcript="hello hapax",
            speaker="operator",
            speaker_confidence=0.92,
            vad_confidence=0.95,
            duration_s=1.2,
            energy_db=-14.0,
        )

        imps = backend.drain_impingements()
        assert len(imps) == 1
        imp = imps[0]
        assert imp["source"] == "audio.operator_speech"
        assert imp["type"] == "PATTERN_MATCH"
        assert imp["strength"] >= 0.85
        assert imp["content"]["transcript"] == "hello hapax"
        assert imp["content"]["speaker"] == "operator"

    @pytest.mark.asyncio
    async def test_non_operator_speech_lower_strength(self):
        backend = self._make_backend()
        backend.start()

        backend._emit_speech_impingement(
            transcript="some guest talking",
            speaker="unknown",
            speaker_confidence=0.3,
            vad_confidence=0.90,
            duration_s=2.0,
            energy_db=-18.0,
        )

        imps = backend.drain_impingements()
        assert len(imps) == 1
        assert imps[0]["source"] == "audio.scene"
        assert imps[0]["strength"] < 0.5

    @pytest.mark.asyncio
    async def test_strength_is_vad_times_speaker_posterior(self):
        backend = self._make_backend()
        backend.start()

        backend._emit_speech_impingement(
            transcript="test",
            speaker="operator",
            speaker_confidence=0.80,
            vad_confidence=0.90,
            duration_s=1.0,
            energy_db=-12.0,
        )

        imps = backend.drain_impingements()
        assert abs(imps[0]["strength"] - 0.72) < 0.01  # 0.90 * 0.80

    def test_drain_clears_queue(self):
        backend = self._make_backend()
        backend.start()
        backend._emit_speech_impingement(
            transcript="a", speaker="operator",
            speaker_confidence=0.9, vad_confidence=0.9,
            duration_s=1.0, energy_db=-12.0,
        )
        assert len(backend.drain_impingements()) == 1
        assert len(backend.drain_impingements()) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/hapax_daimonion/test_audio_perception.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.hapax_daimonion.audio_perception'`

- [ ] **Step 3: Implement AudioPerceptionBackend**

```python
"""agents/hapax_daimonion/audio_perception.py

AudioPerceptionBackend — perception backend that emits operator speech
as impingements into the cognitive substrate.

Replaces ConversationBuffer's role as the primary audio ingestion point.
Instead of buffering utterances for direct pickup by CPAL runner _tick(),
this backend runs VAD + speech segmentation + speculative STT and emits
impingements to /dev/shm/hapax-dmn/impingements.jsonl.

Operator-directed speech produces PATTERN_MATCH impingements at strength
~1.0, dominating exploration (0.2-0.6) and narrative drive (0.12-0.40).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

IMPINGEMENT_BUS = Path("/dev/shm/hapax-dmn/impingements.jsonl")
OPERATOR_SPEAKER_THRESHOLD = 0.60


class AudioPerceptionBackend:
    """Perception backend for audio scene understanding.

    Implements the PerceptionBackend protocol (perception.py).
    """

    def __init__(
        self,
        stt: Any = None,
        speaker_id: Any = None,
    ) -> None:
        self._stt = stt
        self._speaker_id = speaker_id
        self._pending_impingements: deque[dict] = deque(maxlen=32)
        self._active = False

    @property
    def name(self) -> str:
        return "audio"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"speech_detected", "audio_event", "vad_confidence"})

    @property
    def tier(self) -> str:
        return "FAST"

    def available(self) -> bool:
        return self._stt is not None and self._stt.is_loaded

    def start(self) -> None:
        self._active = True
        log.info("AudioPerceptionBackend started")

    def stop(self) -> None:
        self._active = False

    def contribute(self, behaviors: dict) -> None:
        pass

    def _emit_speech_impingement(
        self,
        transcript: str,
        speaker: str,
        speaker_confidence: float,
        vad_confidence: float,
        duration_s: float,
        energy_db: float,
        utterance_ref: str | None = None,
    ) -> None:
        is_operator = speaker == "operator" and speaker_confidence >= OPERATOR_SPEAKER_THRESHOLD
        strength = vad_confidence * speaker_confidence if is_operator else vad_confidence * 0.3

        imp = {
            "id": str(uuid.uuid4()),
            "timestamp": time.time(),
            "source": "audio.operator_speech" if is_operator else "audio.scene",
            "type": "PATTERN_MATCH" if is_operator else "STATISTICAL_DEVIATION",
            "strength": round(min(1.0, strength), 4),
            "content": {
                "transcript": transcript,
                "audio_event": "directed_speech" if is_operator else "ambient_speech",
                "speaker": speaker,
                "speaker_confidence": round(speaker_confidence, 4),
                "energy_db": round(energy_db, 1),
                "duration_s": round(duration_s, 2),
            },
        }
        if utterance_ref:
            imp["content"]["utterance_bytes_ref"] = utterance_ref

        self._pending_impingements.append(imp)
        self._write_to_bus(imp)
        log.info(
            "Audio impingement: source=%s strength=%.2f speaker=%s transcript=%.40s",
            imp["source"], imp["strength"], speaker, transcript,
        )

    def _write_to_bus(self, imp: dict) -> None:
        try:
            with IMPINGEMENT_BUS.open("a") as f:
                f.write(json.dumps(imp) + "\n")
        except OSError:
            log.debug("Failed to write impingement to bus", exc_info=True)

    def drain_impingements(self) -> list[dict]:
        result = list(self._pending_impingements)
        self._pending_impingements.clear()
        return result

    async def process_utterance(
        self,
        audio_bytes: bytes,
        vad_confidence: float,
        duration_s: float,
        energy_db: float,
    ) -> None:
        if not self._active or self._stt is None:
            return

        transcript = await self._stt.transcribe(audio_bytes)
        if not transcript or not transcript.strip():
            return

        speaker = "unknown"
        speaker_confidence = 0.0
        if self._speaker_id is not None:
            try:
                speaker, speaker_confidence = self._speaker_id.identify(audio_bytes)
            except Exception:
                log.debug("Speaker ID failed", exc_info=True)

        self._emit_speech_impingement(
            transcript=transcript,
            speaker=speaker,
            speaker_confidence=speaker_confidence,
            vad_confidence=vad_confidence,
            duration_s=duration_s,
            energy_db=energy_db,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/hapax_daimonion/test_audio_perception.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_daimonion/audio_perception.py tests/hapax_daimonion/test_audio_perception.py
git commit -m "feat(daimonion): AudioPerceptionBackend emits operator speech as impingements"
```

---

### Task 2: Wire AudioPerceptionBackend into ConversationBuffer utterance emission

**Files:**
- Modify: `agents/hapax_daimonion/cpal/runner.py` (lines 500-514)
- Modify: `agents/hapax_daimonion/run_inner.py` (lines 305-320)
- Create: `tests/hapax_daimonion/test_audio_perception_integration.py`

The CPAL runner currently polls `_perception.get_utterance()` in `_tick()` and directly processes utterances. We bridge this: when an utterance is detected, instead of calling `_process_utterance()`, we route it through AudioPerceptionBackend which emits an impingement. The impingement consumer loop picks it up via the normal path.

- [ ] **Step 1: Write failing integration test**

```python
"""tests/hapax_daimonion/test_audio_perception_integration.py"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.hapax_daimonion.audio_perception import AudioPerceptionBackend


class TestAudioPerceptionBusIntegration:
    @pytest.mark.asyncio
    async def test_process_utterance_writes_to_bus(self, tmp_path):
        bus_path = tmp_path / "impingements.jsonl"
        bus_path.touch()

        stt = MagicMock()
        stt.transcribe = AsyncMock(return_value="testing one two three")
        stt.is_loaded = True
        speaker_id = MagicMock()
        speaker_id.identify.return_value = ("operator", 0.88)

        backend = AudioPerceptionBackend(stt=stt, speaker_id=speaker_id)
        backend._active = True

        # Override bus path for test
        import agents.hapax_daimonion.audio_perception as mod
        original = mod.IMPINGEMENT_BUS
        mod.IMPINGEMENT_BUS = bus_path
        try:
            await backend.process_utterance(
                audio_bytes=b"\x00" * 16000,
                vad_confidence=0.95,
                duration_s=1.5,
                energy_db=-14.0,
            )
        finally:
            mod.IMPINGEMENT_BUS = original

        lines = bus_path.read_text().strip().split("\n")
        assert len(lines) == 1
        imp = json.loads(lines[0])
        assert imp["source"] == "audio.operator_speech"
        assert imp["content"]["transcript"] == "testing one two three"
        assert imp["strength"] > 0.8
```

- [ ] **Step 2: Run test to verify it passes (uses existing implementation)**

Run: `uv run pytest tests/hapax_daimonion/test_audio_perception_integration.py -v`
Expected: PASS (AudioPerceptionBackend.process_utterance already writes to bus)

- [ ] **Step 3: Modify CPAL runner _tick to route utterances through AudioPerceptionBackend**

In `agents/hapax_daimonion/cpal/runner.py`, replace the utterance processing block (lines ~500-514) with:

```python
        # 4. Route utterances through AudioPerceptionBackend
        # Instead of processing directly, emit as impingement. The impingement
        # consumer loop will recruit ConversationalResponse via affordance pipeline.
        if self._production.is_producing or self._buffer.is_speaking:
            fresh = self._perception.get_utterance()
            if fresh is not None:
                self._queued_utterance = fresh
        else:
            utterance = self._queued_utterance or self._perception.get_utterance()
            self._queued_utterance = None
            if utterance is not None:
                if self._audio_perception is not None:
                    asyncio.create_task(
                        self._audio_perception.process_utterance(
                            audio_bytes=utterance,
                            vad_confidence=0.95,
                            duration_s=len(utterance) / (16000 * 2),
                            energy_db=-12.0,
                        )
                    )
                else:
                    asyncio.create_task(self._process_utterance(utterance))
```

- [ ] **Step 4: Add AudioPerceptionBackend to CpalRunner constructor**

In `agents/hapax_daimonion/cpal/runner.py` `__init__`, add parameter:

```python
    def __init__(
        self,
        buffer,
        stt,
        salience_router,
        *,
        audio_output=None,
        grounding_ledger=None,
        tts_manager=None,
        echo_canceller=None,
        daemon=None,
        audio_perception=None,  # NEW
    ):
        ...
        self._audio_perception = audio_perception
```

- [ ] **Step 5: Wire AudioPerceptionBackend in run_inner.py**

In `agents/hapax_daimonion/run_inner.py`, after creating the CpalRunner (around line 305), create and pass AudioPerceptionBackend:

```python
    from agents.hapax_daimonion.audio_perception import AudioPerceptionBackend

    audio_perception = AudioPerceptionBackend(
        stt=daemon.resident_stt,
        speaker_id=getattr(daemon, "_speaker_id", None),
    )
    audio_perception.start()

    daemon._cpal_runner = CpalRunner(
        buffer=daemon._conversation_buffer,
        stt=daemon.resident_stt,
        salience_router=daemon._salience_router,
        audio_output=daemon._audio_output,
        grounding_ledger=grounding_ledger,
        tts_manager=daemon.tts,
        echo_canceller=daemon._echo_canceller,
        daemon=daemon,
        audio_perception=audio_perception,  # NEW
    )
```

- [ ] **Step 6: Run existing CPAL tests to verify no regression**

Run: `uv run pytest tests/hapax_daimonion/test_cpal_runner.py -v`
Expected: All tests PASS (existing _process_utterance path still works as fallback)

- [ ] **Step 7: Commit**

```bash
git add agents/hapax_daimonion/cpal/runner.py agents/hapax_daimonion/run_inner.py tests/hapax_daimonion/test_audio_perception_integration.py
git commit -m "feat(daimonion): route utterances through AudioPerceptionBackend impingement emitter"
```

---

### Task 3: Handle audio.operator_speech impingements in CPAL runner

**Files:**
- Modify: `agents/hapax_daimonion/cpal/runner.py` (process_impingement method)
- Create: `tests/hapax_daimonion/test_operator_speech_impingement.py`

When `process_impingement()` receives an `audio.operator_speech` impingement, it should delegate to the existing `_process_utterance()` logic (which will later become the ConversationalResponse capability). This closes the loop: utterance → impingement → recruitment → response.

- [ ] **Step 1: Write failing test**

```python
"""tests/hapax_daimonion/test_operator_speech_impingement.py"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_daimonion.cpal.runner import CpalRunner


class TestOperatorSpeechImpingement:
    def _make_runner(self):
        buffer = MagicMock()
        buffer.speech_active = False
        buffer.speech_duration_s = 0.0
        buffer.is_speaking = False
        buffer.get_utterance.return_value = None
        buffer.speech_frames_snapshot = []
        stt = MagicMock()
        stt.transcribe = AsyncMock(return_value="")
        router = MagicMock()
        router.route.return_value = MagicMock(tier="CAPABLE")
        return CpalRunner(buffer=buffer, stt=stt, salience_router=router)

    @pytest.mark.asyncio
    async def test_operator_speech_impingement_triggers_conversation(self):
        runner = self._make_runner()
        runner._pipeline = AsyncMock()
        runner._pipeline._running = True

        imp = SimpleNamespace(
            source="audio.operator_speech",
            strength=0.95,
            content={
                "transcript": "hey hapax what's going on",
                "audio_event": "directed_speech",
                "speaker": "operator",
                "speaker_confidence": 0.92,
                "duration_s": 1.5,
            },
            interrupt_token=None,
        )

        with patch(
            "agents.hapax_daimonion.cpal.runner.resolve_playback_decision",
            return_value=SimpleNamespace(
                allowed=True,
                destination=SimpleNamespace(value="private"),
                target="hapax-private",
                media_role="Assistant",
                reason_code="ok",
                safety_gate={},
            ),
        ):
            await runner.process_impingement(imp)

        runner._pipeline.process_utterance_from_transcript.assert_called_once()
        call_args = runner._pipeline.process_utterance_from_transcript.call_args
        assert "hey hapax" in call_args[0][0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/hapax_daimonion/test_operator_speech_impingement.py -v`
Expected: FAIL — `process_impingement` doesn't handle `audio.operator_speech` source

- [ ] **Step 3: Add operator speech handling to process_impingement**

In `agents/hapax_daimonion/cpal/runner.py`, add at the top of `process_impingement()` (before the impingement adapter):

```python
    async def process_impingement(self, impingement) -> None:
        source = getattr(impingement, "source", "")

        # Operator speech — dominant impingement, recruits conversation
        if source == "audio.operator_speech" and self._pipeline is not None:
            content = getattr(impingement, "content", {})
            transcript = content.get("transcript", "")
            if transcript:
                log.info(
                    "CPAL: operator speech impingement (strength=%.2f): %.40s",
                    getattr(impingement, "strength", 0),
                    transcript,
                )
                if hasattr(self._pipeline, "process_utterance_from_transcript"):
                    await self._pipeline.process_utterance_from_transcript(transcript)
                else:
                    log.warning("Pipeline lacks process_utterance_from_transcript")
            return

        # ... existing impingement processing below
```

- [ ] **Step 4: Add process_utterance_from_transcript to ConversationPipeline**

In `agents/hapax_daimonion/conversation_pipeline.py`, add method:

```python
    async def process_utterance_from_transcript(self, transcript: str) -> None:
        """Process a pre-transcribed operator utterance.

        Called when operator speech arrives as an impingement with transcript
        already attached (AudioPerceptionBackend ran STT speculatively).
        Skips STT, goes directly to LLM response generation.
        """
        if not self._running:
            await self.start()

        # Build context and generate response using existing LLM path
        self._update_system_context()

        import litellm

        from shared.config import MODELS

        grounded_model = MODELS["local-fast"]
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": transcript},
        ]

        # Append to conversation thread
        self._conversation_thread.append({"role": "user", "content": transcript})

        response = await asyncio.wait_for(
            litellm.acompletion(
                model=f"openai/{grounded_model}",
                messages=self.messages + [{"role": "user", "content": transcript}],
                max_tokens=200,
                temperature=0.7,
                api_key=__import__("os").environ.get("LITELLM_API_KEY", ""),
                api_base=_voice_litellm_base,
                timeout=10,
            ),
            timeout=15,
        )

        text = response.choices[0].message.content.strip()
        if text:
            log.info("Conversation response: %s", text[:80])
            self._conversation_thread.append({"role": "assistant", "content": text})
            await self._speak_sentence(text)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/hapax_daimonion/test_operator_speech_impingement.py tests/hapax_daimonion/test_cpal_runner.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add agents/hapax_daimonion/cpal/runner.py agents/hapax_daimonion/conversation_pipeline.py tests/hapax_daimonion/test_operator_speech_impingement.py
git commit -m "feat(daimonion): operator speech impingements recruit conversation via process_impingement"
```

---

### Task 4: Wire ResourceArbiter into audio output claims

**Files:**
- Modify: `agents/hapax_daimonion/cpal/runner.py`
- Modify: `agents/hapax_daimonion/arbiter.py`
- Create: `tests/hapax_daimonion/test_audio_arbiter.py`

The ResourceArbiter exists with correct priorities but isn't wired into the audio path. Wire it so speech production claims `audio_output` and higher-priority claims preempt lower-priority in-flight playback.

- [ ] **Step 1: Write failing test for preemption**

```python
"""tests/hapax_daimonion/test_audio_arbiter.py"""
from agents.hapax_daimonion.arbiter import ResourceArbiter, ResourceClaim
from agents.hapax_daimonion.resource_config import DEFAULT_PRIORITIES


class TestAudioOutputPreemption:
    def test_conversation_preempts_exploration(self):
        arbiter = ResourceArbiter(DEFAULT_PRIORITIES)

        exploration_claim = ResourceClaim(
            resource="audio_output",
            chain="exploration_speech",
            priority=15,
            command="exploration narration",
        )
        arbiter.claim(exploration_claim)

        conversation_claim = ResourceClaim(
            resource="audio_output",
            chain="conversation",
            priority=100,
            command="operator response",
        )
        arbiter.claim(conversation_claim)

        winner = arbiter.resolve("audio_output")
        assert winner is not None
        assert winner.chain == "conversation"
        assert winner.priority == 100

    def test_exploration_does_not_preempt_conversation(self):
        arbiter = ResourceArbiter(DEFAULT_PRIORITIES)

        conversation_claim = ResourceClaim(
            resource="audio_output",
            chain="conversation",
            priority=100,
            command="operator response",
        )
        arbiter.claim(conversation_claim)

        exploration_claim = ResourceClaim(
            resource="audio_output",
            chain="exploration_speech",
            priority=15,
            command="exploration narration",
        )
        arbiter.claim(exploration_claim)

        winner = arbiter.resolve("audio_output")
        assert winner.chain == "conversation"
```

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/hapax_daimonion/test_audio_arbiter.py -v`
Expected: PASS (arbiter already resolves by priority)

- [ ] **Step 3: Add arbiter claim to operator speech impingement handler**

In `agents/hapax_daimonion/cpal/runner.py`, modify the operator speech handler in `process_impingement()`:

```python
        if source == "audio.operator_speech" and self._pipeline is not None:
            content = getattr(impingement, "content", {})
            transcript = content.get("transcript", "")
            if transcript:
                # Claim audio_output at conversation priority — preempts exploration
                if self._daemon is not None and hasattr(self._daemon, "arbiter"):
                    from agents.hapax_daimonion.arbiter import ResourceClaim

                    claim = ResourceClaim(
                        resource="audio_output",
                        chain="conversation",
                        priority=100,
                        command=f"operator_speech: {transcript[:40]}",
                    )
                    self._daemon.arbiter.claim(claim)
                    self._kill_inflight_playback()

                log.info(
                    "CPAL: operator speech impingement (strength=%.2f): %.40s",
                    getattr(impingement, "strength", 0),
                    transcript,
                )
                if hasattr(self._pipeline, "process_utterance_from_transcript"):
                    await self._pipeline.process_utterance_from_transcript(transcript)
            return
```

- [ ] **Step 4: Implement _kill_inflight_playback**

In `agents/hapax_daimonion/cpal/runner.py`:

```python
    def _kill_inflight_playback(self) -> None:
        """Kill any in-flight pw-cat playback to make room for higher-priority speech."""
        if self._audio_output is not None and hasattr(self._audio_output, "kill"):
            self._audio_output.kill()
            log.info("CPAL: killed in-flight playback for preemption")
        self._buffer.set_speaking(False)
```

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/hapax_daimonion/ -v -q`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add agents/hapax_daimonion/cpal/runner.py tests/hapax_daimonion/test_audio_arbiter.py
git commit -m "feat(daimonion): wire ResourceArbiter into audio output with preemption"
```

---

### Task 5: Remove speaking gate from exploration surfacing LLM path

**Files:**
- Modify: `agents/hapax_daimonion/cpal/runner.py` (lines ~1282-1332)
- Modify: `tests/hapax_daimonion/test_cpal_runner.py`

The exploration surfacing path currently holds set_speaking(True) for the entire LLM+TTS duration. The speaking gate should only be held during actual TTS playback (which `_speak_sentence` already manages internally).

- [ ] **Step 1: Verify current exploration surfacing code**

Read `agents/hapax_daimonion/cpal/runner.py` lines 1282-1332 to confirm the speaking gate is still set at the outer level.

- [ ] **Step 2: Remove outer speaking gate from exploration surfacing**

The `set_speaking(True)` at line ~1287 and the 3s holdover sleep were already partially removed in an earlier fix. Verify the `finally` block only has `set_speaking(False)` (no sleep) and that there's no `set_speaking(True)` before the `generate_spontaneous_speech` call.

If `set_speaking(True)` is still present before the try block, remove it. The `_speak_sentence()` inside `generate_spontaneous_speech` manages its own per-sentence speaking gate.

- [ ] **Step 3: Add exploration arbiter claim**

Before exploration surfacing calls `generate_spontaneous_speech`, add an arbiter claim at exploration priority:

```python
            if self._daemon is not None and hasattr(self._daemon, "arbiter"):
                from agents.hapax_daimonion.arbiter import ResourceClaim

                current_winner = self._daemon.arbiter.resolve("audio_output")
                if current_winner is not None and current_winner.priority > 15:
                    log.info("CPAL: exploration deferred — higher-priority claim on audio_output")
                    record_drop(
                        reason="audio_output_preempted",
                        source=source,
                        destination=destination.value,
                        target=destination_target,
                        media_role=destination_role,
                        text=effect.narrative,
                        terminal_state="inhibited",
                    )
                    return

                claim = ResourceClaim(
                    resource="audio_output",
                    chain="exploration_speech",
                    priority=15,
                    command=f"exploration: {effect.narrative[:40]}",
                )
                self._daemon.arbiter.claim(claim)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/hapax_daimonion/test_cpal_runner.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_daimonion/cpal/runner.py
git commit -m "fix(daimonion): exploration surfacing uses arbiter, no outer speaking gate"
```

---

### Task 6: Restart daimonion and verify end-to-end

**Files:** None (operational verification)

- [ ] **Step 1: Restart daimonion**

```bash
systemctl --user restart hapax-daimonion
```

- [ ] **Step 2: Wait for startup and check logs**

```bash
sleep 25
journalctl --user -u hapax-daimonion --since '30s ago' --no-pager -o cat | grep -iE 'AudioPerception|audio.*impingement|operator_speech|chatterbox.*ready|parakeet'
```

Expected: AudioPerceptionBackend started, Parakeet loaded, Chatterbox ready.

- [ ] **Step 3: Test operator speech generates impingement**

Speak to the system and check:

```bash
sleep 10
journalctl --user -u hapax-daimonion --since '15s ago' --no-pager -o cat | grep -iE 'audio.*impingement|operator.*speech.*impingement|conversation.*response'
```

Expected: `Audio impingement: source=audio.operator_speech strength=0.9x` followed by conversation response.

- [ ] **Step 4: Test exploration is preempted by speech**

Wait for exploration to start, then speak:

```bash
journalctl --user -u hapax-daimonion --since '30s ago' --no-pager -o cat | grep -iE 'killed.*inflight|preempt|operator.*speech|exploration.*deferred'
```

Expected: `killed in-flight playback for preemption` when operator speaks during exploration.

- [ ] **Step 5: Commit verification notes**

```bash
git add -A
git commit -m "feat(daimonion): impingement-native voice Phase 1 — operator speech as dominant impingement"
```
