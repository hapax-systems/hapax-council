"""Interview conductor turn-state motor — ask → arm-silence → listen → STT → record.

cc-task voice-interview-conductor-turn-motor-20260615 (REQ-20260616 Track A, the private-rehearsal
first-viable gate). The voice motor (STT → salience → model_router → LLM → TTS → voice-fx → S-4 → broadcast)
is already built and Active; the ONE missing architectural piece is **turn orchestration**. This module
adds it as an isolated, unit-testable state machine.

HYBRID SAFETY (load-bearing): the **ask** leg is conductor-originated and does NOT re-enter STT routing;
the **answer** leg calls ``pipeline.stt.transcribe`` DIRECTLY and NEVER ``process_utterance`` — so the live
broadcast path is left untouched. This is the mocked-TDD MVP; the live answer-buffer capture and the
``runner.begin_interview_silence`` handle injection are follow-on tasks (see the cc-task).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InterviewFact:
    """One recorded interview turn: the conductor's question + the operator's transcribed answer."""

    question: str
    answer: str


class InterviewConductor:
    """Drives the operator interview as a sequence of ask → arm-silence → listen → STT → record turns.

    Args:
        pipeline: the daimonion conversation pipeline — uses ``.tts.synthesize`` (conductor-originated
            speech), ``._play_guarded_pcm`` (the guarded playback path), and ``.stt.transcribe`` (the
            answer leg). ``process_utterance`` is deliberately never called.
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
        """Run the full interview, returning one InterviewFact per question."""
        facts: list[InterviewFact] = []
        for question in self._questions:
            await self._ask(question)
            self._runner.begin_interview_silence()
            answer = await self._listen()
            facts.append(InterviewFact(question=question, answer=answer))
        return facts

    async def _ask(self, text: str) -> None:
        pcm = self._pipeline.tts.synthesize(text, interview_mode=True)
        await self._pipeline._play_guarded_pcm(pcm=pcm, text=text, source="interview")

    async def _listen(self) -> str:
        audio = await self._capture_answer()
        return await self._pipeline.stt.transcribe(audio)
