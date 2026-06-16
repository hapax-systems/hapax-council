"""TDD for the interview conductor turn-state motor.

cc-task: voice-interview-conductor-turn-motor-20260615 (REQ-20260616 Track A, the private-rehearsal
first-viable gate). The conductor is the ONE missing architectural piece on the already-built voice motor:
a turn-state machine **ask → arm-silence → listen → STT → record**.

HYBRID SAFETY (the load-bearing invariant): the ask leg is conductor-originated and does NOT re-enter STT
routing; the answer leg calls ``pipeline.stt.transcribe`` DIRECTLY and NEVER ``process_utterance`` — so the
live broadcast path is untouched. This is a mocked-TDD MVP; the live answer-buffer capture + runner-handle
injection are follow-on tasks.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from agents.hapax_daimonion.interview_conductor import InterviewConductor, InterviewFact


def _mock_pipeline(answer: str = "the operator's answer") -> MagicMock:
    pipeline = MagicMock()
    # tts.synthesize is sync (-> pcm bytes); the play + transcribe legs are async.
    pipeline.tts.synthesize = MagicMock(return_value=b"PCM-FOR-QUESTION")
    pipeline._play_guarded_pcm = AsyncMock(return_value=True)
    pipeline.stt.transcribe = AsyncMock(return_value=answer)
    pipeline.process_utterance = AsyncMock()  # must NEVER be called
    return pipeline


async def test_conductor_runs_full_turn_per_question_and_records_facts() -> None:
    pipeline = _mock_pipeline(answer="my name is Oudepode")
    runner = MagicMock()
    capture_answer = AsyncMock(return_value=b"ANSWER-AUDIO")
    questions = ["What is your name?", "How are you today?"]

    conductor = InterviewConductor(
        pipeline=pipeline, runner=runner, questions=questions, capture_answer=capture_answer
    )
    facts = await conductor.run()

    # ASK leg: TTS synthesize per question, interview_mode=True (conductor-originated prosody)
    assert pipeline.tts.synthesize.call_count == 2
    for call in pipeline.tts.synthesize.call_args_list:
        assert call.kwargs.get("interview_mode") is True
    # played via the guarded pcm path, tagged source="interview"
    assert pipeline._play_guarded_pcm.await_count == 2
    for call in pipeline._play_guarded_pcm.await_args_list:
        assert call.kwargs["source"] == "interview"
        assert call.kwargs["pcm"] == b"PCM-FOR-QUESTION"
    # silence armed after each question
    assert runner.begin_interview_silence.call_count == 2
    # ANSWER leg: stt.transcribe DIRECTLY; process_utterance NEVER (broadcast path untouched)
    assert pipeline.stt.transcribe.await_count == 2
    pipeline.process_utterance.assert_not_called()
    # facts recorded
    assert facts == [
        InterviewFact(question="What is your name?", answer="my name is Oudepode"),
        InterviewFact(question="How are you today?", answer="my name is Oudepode"),
    ]


async def test_conductor_turn_ordering_ask_then_arm_then_listen() -> None:
    calls: list[str] = []
    pipeline = MagicMock()
    pipeline.tts.synthesize = MagicMock(
        side_effect=lambda *a, **k: (calls.append("ask:synth"), b"PCM")[1]
    )

    async def _play(**k: object) -> bool:
        calls.append("ask:play")
        return True

    pipeline._play_guarded_pcm = AsyncMock(side_effect=_play)

    async def _transcribe(audio: bytes) -> str:
        calls.append("listen:stt")
        return "ans"

    pipeline.stt.transcribe = AsyncMock(side_effect=_transcribe)
    runner = MagicMock()
    runner.begin_interview_silence = MagicMock(
        side_effect=lambda *a, **k: calls.append("arm:silence")
    )

    async def _capture() -> bytes:
        calls.append("listen:capture")
        return b"AUDIO"

    capture_answer = AsyncMock(side_effect=_capture)

    conductor = InterviewConductor(
        pipeline=pipeline, runner=runner, questions=["Q1"], capture_answer=capture_answer
    )
    await conductor.run()

    assert calls == ["ask:synth", "ask:play", "arm:silence", "listen:capture", "listen:stt"]


async def test_empty_queue_yields_no_facts_and_touches_nothing() -> None:
    pipeline = _mock_pipeline()
    runner = MagicMock()
    conductor = InterviewConductor(
        pipeline=pipeline, runner=runner, questions=[], capture_answer=AsyncMock()
    )
    facts = await conductor.run()
    assert facts == []
    pipeline.tts.synthesize.assert_not_called()
    runner.begin_interview_silence.assert_not_called()
    pipeline.process_utterance.assert_not_called()
