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
import json
import logging
import os
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_INTERVIEW_STATE_PATH = Path("/dev/shm/hapax-compositor/interview-state.json")
LOGGER = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class InterviewQuestion:
    """Question plus ward-facing metadata for the N1 interview card."""

    text: str
    topic: str = ""
    depth: str = ""
    rationale: str = ""
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class InterviewStateSnapshot:
    """JSON envelope consumed by ``InterviewQuestionWard``."""

    active: bool
    current_question: str = ""
    topic: str = ""
    depth: str = ""
    rationale: str = ""
    source_refs: tuple[str, ...] = ()
    topics_explored: int = 0
    topics_total: int = 0
    facts_recorded: int = 0

    def to_json_dict(self) -> dict[str, object]:
        return {
            "active": self.active,
            "current_question": self.current_question,
            "topic": self.topic,
            "depth": self.depth,
            "rationale": self.rationale,
            "source_refs": list(self.source_refs),
            "topics_explored": self.topics_explored,
            "topics_total": self.topics_total,
            "facts_recorded": self.facts_recorded,
        }


class InterviewStateWriter:
    """Atomic file writer for the compositor interview question ward."""

    def __init__(self, path: Path = DEFAULT_INTERVIEW_STATE_PATH) -> None:
        self.path = path

    def __call__(self, snapshot: InterviewStateSnapshot) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}")
        try:
            tmp.write_text(
                json.dumps(snapshot.to_json_dict(), sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(tmp, self.path)
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass


def _normalize_question(question: str | InterviewQuestion) -> InterviewQuestion:
    if isinstance(question, InterviewQuestion):
        return question
    return InterviewQuestion(text=question)


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
        state_writer: Optional N1 compositor ward feed. Omitted in unit tests and until the live-wiring
            task instantiates the conductor; pass ``InterviewStateWriter()`` to write the SHM contract.
    """

    def __init__(
        self,
        *,
        pipeline: Any,
        runner: Any,
        questions: Sequence[str | InterviewQuestion],
        capture_answer: Callable[[], Awaitable[bytes]],
        state_writer: Callable[[InterviewStateSnapshot], None] | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._runner = runner
        self._questions = [_normalize_question(question) for question in questions]
        self._capture_answer = capture_answer
        self._state_writer = state_writer

    async def run(self) -> list[InterviewFact]:
        """Run the full interview, returning one InterviewFact per question.

        A question that never reaches air, or that draws a silent/blank answer, is recorded as an
        abstention (``abstained=True``) and the conductor moves on — it does NOT listen for an answer
        to a question the operator never heard, and it never fabricates a fact from silence.
        """
        facts: list[InterviewFact] = []
        total = len(self._questions)
        wrote_inactive = False
        for question in self._questions:
            if not await self._ask(question.text):
                # The question never reached air — nothing to answer. The drop was already
                # witnessed in _ask; record an abstention and skip the listen leg entirely.
                facts.append(InterviewFact(question=question.text, answer="", abstained=True))
                await self._write_state(None, active=False, facts=facts, topics_total=total)
                wrote_inactive = True
                continue
            await self._write_state(question, active=True, facts=facts, topics_total=total)
            wrote_inactive = False
            self._runner.begin_interview_silence()
            answer = await self._listen()
            if answer.strip():
                facts.append(InterviewFact(question=question.text, answer=answer))
            else:
                # Silence / blank transcription is an abstention, not a fabricated fact.
                facts.append(InterviewFact(question=question.text, answer="", abstained=True))
        if not wrote_inactive:
            await self._write_state(None, active=False, facts=facts, topics_total=total)
        return facts

    async def _write_state(
        self,
        question: InterviewQuestion | None,
        *,
        active: bool,
        facts: Sequence[InterviewFact],
        topics_total: int,
    ) -> None:
        writer = self._state_writer
        if writer is None:
            return
        writer_path = getattr(writer, "path", DEFAULT_INTERVIEW_STATE_PATH)
        try:
            await asyncio.to_thread(
                self._write_state_sync,
                writer,
                question,
                active=active,
                facts=facts,
                topics_total=topics_total,
            )
        except Exception:
            LOGGER.warning(
                "interview_state_write_failed; next_action=check %s parent directory, "
                "permissions, and studio compositor ward poller",
                writer_path,
                exc_info=True,
            )

    @staticmethod
    def _write_state_sync(
        writer: Callable[[InterviewStateSnapshot], None],
        question: InterviewQuestion | None,
        *,
        active: bool,
        facts: Sequence[InterviewFact],
        topics_total: int,
    ) -> None:
        writer(
            InterviewStateSnapshot(
                active=active,
                current_question=question.text if question is not None else "",
                topic=question.topic if question is not None else "",
                depth=question.depth if question is not None else "",
                rationale=question.rationale if question is not None else "",
                source_refs=question.source_refs if question is not None else (),
                topics_explored=len(facts),
                topics_total=topics_total,
                facts_recorded=sum(1 for fact in facts if not fact.abstained),
            )
        )

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
