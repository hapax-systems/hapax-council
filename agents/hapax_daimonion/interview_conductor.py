"""Interview conductor turn-state motor — ask → arm-silence → listen → STT → record.

cc-task voice-interview-conductor-turn-motor-20260615 (REQ-20260616 Track A, the private-rehearsal
first-viable gate). The voice motor (STT → salience → model_router → LLM → TTS → voice-fx → S-4 → broadcast)
is already built and Active; the ONE missing architectural piece is **turn orchestration**. This module
adds it as an isolated, unit-testable state machine.

HYBRID SAFETY (load-bearing): the **ask** leg is conductor-originated and does NOT re-enter STT routing
(``process_utterance`` is never called); the **answer** leg calls ``pipeline.stt.transcribe`` DIRECTLY. The
ask holds the pipeline speaking gate (``buffer.set_speaking``) for the duration of playback — the same gate
the live voice path uses — so the buffer stays deaf to Hapax's own question. Synthesis is a blocking CPU/GPU
call, so it runs off the event loop (``asyncio.to_thread``) and never stalls the async motor. A question that
fails to reach air is witnessed (``voice_output_witness``, drop-with-witness, never a spoken error) and
recorded as an abstention, never a fabricated fact.

Scope: this is the ask→listen→record MVP. The **decide** phase (branching/follow-up questions derived from
the answer) and the live answer-buffer capture + ``runner.begin_interview_silence`` handle injection are
follow-on tasks (see the cc-task).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InterviewFact:
    """One recorded interview turn: the conductor's question + the operator's transcribed answer.

    ``abstained`` marks a turn with no substantive answer — the question never reached air, or the
    operator stayed silent. Abstention is HEALTHY conduct: it is recorded (not silently dropped) and
    kept distinct from a real answer so downstream consumers never mistake silence for a fabricated fact.
    """

    question: str
    answer: str
    abstained: bool = False


class InterviewConductor:
    """Drives the operator interview as a sequence of ask → arm-silence → listen → STT → record turns.

    Args:
        pipeline: the daimonion conversation pipeline — uses ``.tts.synthesize`` (conductor-originated
            speech, run off the event loop), ``.buffer.set_speaking`` (the speaking gate held during the
            ask), ``._play_guarded_pcm`` (the guarded playback path, returns whether it reached air), and
            ``.stt.transcribe`` (the answer leg). ``process_utterance`` is deliberately never called.
        runner: the cpal runner — uses ``.begin_interview_silence`` to gate Hapax's autonomous
            interjections during the operator's answer.
        questions: the question queue (a stub list for the MVP; the compass-plan feed is a follow-on).
        capture_answer: ``async () -> bytes`` yielding the operator's answer audio after the silence
            window (mocked in tests; the live answer-buffer wiring is a follow-on).
    """

    def __init__(
        self,
        *,
        pipeline: Any,
        runner: Any,
        questions: Sequence[str],
        capture_answer: Callable[[], Awaitable[bytes]],
    ) -> None:
        self._pipeline = pipeline
        self._runner = runner
        self._questions = list(questions)
        self._capture_answer = capture_answer

    async def run(self) -> list[InterviewFact]:
        """Run the full interview, returning one InterviewFact per question.

        A question that never reaches air, or that draws a silent/blank answer, is recorded as an
        abstention (``abstained=True``) and the conductor moves on — it does NOT listen for an answer
        to a question the operator never heard, and it never fabricates a fact from silence.
        """
        facts: list[InterviewFact] = []
        for question in self._questions:
            if not await self._ask(question):
                # The question never reached air — nothing to answer. The drop was already
                # witnessed in _ask; record an abstention and skip the listen leg entirely.
                facts.append(InterviewFact(question=question, answer="", abstained=True))
                continue
            self._runner.begin_interview_silence()
            answer = await self._listen()
            if answer.strip():
                facts.append(InterviewFact(question=question, answer=answer))
            else:
                # Silence / blank transcription is an abstention, not a fabricated fact.
                facts.append(InterviewFact(question=question, answer="", abstained=True))
        return facts

    async def _ask(self, text: str) -> bool:
        """Synthesize + play one question. Returns True iff it actually reached air.

        Synthesis runs off the event loop via ``asyncio.to_thread`` so the blocking TTS call never
        stalls the async motor. The pipeline speaking gate is held for the duration of playback so the
        buffer stays deaf to Hapax's own voice. A question that produces no audio, or that the guarded
        path declines to play, is witnessed (drop-with-witness) and reported as not-played.
        """
        pcm = await asyncio.to_thread(self._pipeline.tts.synthesize, text, interview_mode=True)
        if not pcm:
            self._witness_unplayed(text, reason="interview_empty_synthesis")
            return False
        buffer = getattr(self._pipeline, "buffer", None)
        if buffer is not None:
            buffer.set_speaking(True)
        try:
            played: bool = await self._pipeline._play_guarded_pcm(
                pcm=pcm, text=text, source="interview"
            )
        finally:
            if buffer is not None:
                buffer.set_speaking(False)
        if not played:
            self._witness_unplayed(text, reason="interview_playback_declined")
        return played

    async def _listen(self) -> str:
        """Capture the operator's answer audio and transcribe it directly (never process_utterance)."""
        audio = await self._capture_answer()
        return (await self._pipeline.stt.transcribe(audio)) or ""

    @staticmethod
    def _witness_unplayed(text: str, *, reason: str) -> None:
        """Record a voice-output witness for a question that did not reach air (drop-with-witness)."""
        from agents.hapax_daimonion.voice_output_witness import record_drop

        record_drop(reason=reason, source="interview", text=text)
