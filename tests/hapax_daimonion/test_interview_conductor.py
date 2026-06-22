"""TDD for the interview conductor turn-state motor.

cc-task: voice-interview-conductor-turn-motor-20260615 (REQ-20260616 Track A, the private-rehearsal
first-viable gate). The conductor is the ONE missing architectural piece on the already-built voice motor:
a turn-state machine **ask → arm-silence → listen → STT → record**.

HYBRID SAFETY (the load-bearing invariant): the ask leg is conductor-originated and does NOT re-enter STT
routing (``process_utterance`` is never called); the answer leg calls ``pipeline.stt.transcribe`` DIRECTLY.
The ask holds the pipeline speaking gate during playback; synthesis runs off the event loop; a question that
never reaches air, or a silent answer, is witnessed + recorded as an abstention, never a fabricated fact.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

from agents.hapax_daimonion import interview_conductor
from agents.hapax_daimonion.interview_conductor import (
    InterviewConductor,
    InterviewFact,
    InterviewQuestion,
    InterviewStateSnapshot,
    InterviewStateWriter,
)

if TYPE_CHECKING:
    import pytest


def _mock_pipeline(answer: str = "the operator's answer") -> MagicMock:
    pipeline = MagicMock()
    # tts.synthesize is sync (-> pcm bytes); the play + transcribe legs are async.
    pipeline.tts.synthesize = MagicMock(return_value=b"PCM-FOR-QUESTION")
    pipeline._play_guarded_pcm = AsyncMock(return_value=True)
    pipeline.stt.transcribe = AsyncMock(return_value=answer)
    pipeline.process_utterance = AsyncMock()  # must NEVER be called
    return pipeline


def test_interview_state_writer_atomically_writes_ward_contract(tmp_path: Path) -> None:
    target = tmp_path / "interview-state.json"
    writer = InterviewStateWriter(target)

    writer(
        InterviewStateSnapshot(
            active=True,
            current_question="What should the ward show?",
            topic="broadcast",
            depth="level-2",
            rationale="N1 needs the current prompt.",
            source_refs=("spec:a", "task:b"),
            topics_explored=2,
            topics_total=4,
            facts_recorded=1,
        )
    )

    assert json.loads(target.read_text(encoding="utf-8")) == {
        "active": True,
        "current_question": "What should the ward show?",
        "topic": "broadcast",
        "depth": "level-2",
        "rationale": "N1 needs the current prompt.",
        "source_refs": ["spec:a", "task:b"],
        "topics_explored": 2,
        "topics_total": 4,
        "facts_recorded": 1,
    }
    assert list(tmp_path.glob(".interview-state.json.tmp.*")) == []


def test_interview_state_writer_uses_unique_tmp_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "interview-state.json"
    writer = InterviewStateWriter(target)
    tmp_names: list[str] = []

    def _replace(src: object, dst: object) -> None:
        src_path = Path(src)
        tmp_names.append(src_path.name)
        src_path.unlink()
        Path(dst).write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(interview_conductor.os, "replace", _replace)

    writer(InterviewStateSnapshot(active=True, current_question="Q1"))
    writer(InterviewStateSnapshot(active=True, current_question="Q2"))

    assert len(tmp_names) == 2
    assert len(set(tmp_names)) == 2
    assert list(tmp_path.glob(".interview-state.json.tmp.*")) == []


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


async def test_conductor_writes_active_question_state_before_listen_and_final_inactive() -> None:
    states: list[InterviewStateSnapshot] = []
    pipeline = _mock_pipeline(answer="answer with one fact")
    question = InterviewQuestion(
        text="Which question is on screen?",
        topic="interview",
        depth="level-1",
        rationale="The operator should see the live conductor prompt.",
        source_refs=("docs/superpowers/specs/interview.md",),
    )

    async def _capture() -> bytes:
        assert states[-1] == InterviewStateSnapshot(
            active=True,
            current_question="Which question is on screen?",
            topic="interview",
            depth="level-1",
            rationale="The operator should see the live conductor prompt.",
            source_refs=("docs/superpowers/specs/interview.md",),
            topics_explored=0,
            topics_total=1,
            facts_recorded=0,
        )
        return b"ANSWER-AUDIO"

    conductor = InterviewConductor(
        pipeline=pipeline,
        runner=MagicMock(),
        questions=[question],
        capture_answer=_capture,
        state_writer=states.append,
    )

    facts = await conductor.run()

    assert facts == [
        InterviewFact(question="Which question is on screen?", answer="answer with one fact")
    ]
    assert states == [
        InterviewStateSnapshot(
            active=True,
            current_question="Which question is on screen?",
            topic="interview",
            depth="level-1",
            rationale="The operator should see the live conductor prompt.",
            source_refs=("docs/superpowers/specs/interview.md",),
            topics_explored=0,
            topics_total=1,
            facts_recorded=0,
        ),
        InterviewStateSnapshot(
            active=False,
            topics_explored=1,
            topics_total=1,
            facts_recorded=1,
        ),
    ]


async def test_conductor_state_counts_abstentions_without_recording_facts() -> None:
    states: list[InterviewStateSnapshot] = []
    pipeline = _mock_pipeline(answer="   ")
    conductor = InterviewConductor(
        pipeline=pipeline,
        runner=MagicMock(),
        questions=["Q1"],
        capture_answer=AsyncMock(return_value=b"A"),
        state_writer=states.append,
    )

    facts = await conductor.run()

    assert facts == [InterviewFact(question="Q1", answer="", abstained=True)]
    assert states[-1] == InterviewStateSnapshot(
        active=False,
        topics_explored=1,
        topics_total=1,
        facts_recorded=0,
    )


async def test_empty_queue_state_writer_emits_single_inactive_snapshot() -> None:
    states: list[InterviewStateSnapshot] = []
    conductor = InterviewConductor(
        pipeline=_mock_pipeline(),
        runner=MagicMock(),
        questions=[],
        capture_answer=AsyncMock(),
        state_writer=states.append,
    )

    facts = await conductor.run()

    assert facts == []
    assert states == [
        InterviewStateSnapshot(
            active=False,
            topics_explored=0,
            topics_total=0,
            facts_recorded=0,
        )
    ]


async def test_unplayed_question_state_writer_emits_inactive_without_active_prompt() -> None:
    states: list[InterviewStateSnapshot] = []
    pipeline = _mock_pipeline()
    pipeline._play_guarded_pcm = AsyncMock(return_value=False)
    with patch("agents.hapax_daimonion.voice_output_witness.record_drop"):
        conductor = InterviewConductor(
            pipeline=pipeline,
            runner=MagicMock(),
            questions=["Q1"],
            capture_answer=AsyncMock(),
            state_writer=states.append,
        )
        facts = await conductor.run()

    assert facts == [InterviewFact(question="Q1", answer="", abstained=True)]
    assert states == [
        InterviewStateSnapshot(
            active=False,
            topics_explored=1,
            topics_total=1,
            facts_recorded=0,
        )
    ]


async def test_state_writer_failure_does_not_abort_interview_turn() -> None:
    state_writer = MagicMock(side_effect=OSError("shm unavailable"))
    pipeline = _mock_pipeline(answer="answer still recorded")
    conductor = InterviewConductor(
        pipeline=pipeline,
        runner=MagicMock(),
        questions=["Q1"],
        capture_answer=AsyncMock(return_value=b"A"),
        state_writer=state_writer,
    )

    facts = await conductor.run()

    assert facts == [InterviewFact(question="Q1", answer="answer still recorded")]
    assert state_writer.call_count == 2
    pipeline.process_utterance.assert_not_called()


async def test_state_writer_runs_off_the_event_loop_thread() -> None:
    main_thread = threading.current_thread()
    writer_threads: list[threading.Thread] = []

    def _writer(snapshot: InterviewStateSnapshot) -> None:
        writer_threads.append(threading.current_thread())

    conductor = InterviewConductor(
        pipeline=_mock_pipeline(answer="answer"),
        runner=MagicMock(),
        questions=["Q1"],
        capture_answer=AsyncMock(return_value=b"A"),
        state_writer=_writer,
    )

    await conductor.run()

    assert writer_threads
    assert all(thread is not main_thread for thread in writer_threads)


async def test_state_writer_failure_log_includes_next_action(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=interview_conductor.__name__)
    conductor = InterviewConductor(
        pipeline=_mock_pipeline(answer="answer still recorded"),
        runner=MagicMock(),
        questions=["Q1"],
        capture_answer=AsyncMock(return_value=b"A"),
        state_writer=MagicMock(side_effect=OSError("shm unavailable")),
    )

    facts = await conductor.run()

    assert facts == [InterviewFact(question="Q1", answer="answer still recorded")]
    assert "interview_state_write_failed" in caplog.text
    assert "next_action=check" in caplog.text


async def test_listen_failure_clears_active_state_before_reraising() -> None:
    states: list[InterviewStateSnapshot] = []

    async def _capture() -> bytes:
        raise RuntimeError("capture failed")

    conductor = InterviewConductor(
        pipeline=_mock_pipeline(answer="unused"),
        runner=MagicMock(),
        questions=["Q1"],
        capture_answer=_capture,
        state_writer=states.append,
    )

    try:
        await conductor.run()
    except RuntimeError as exc:
        assert str(exc) == "capture failed"
    else:
        raise AssertionError("capture failure should propagate")

    assert states == [
        InterviewStateSnapshot(
            active=True,
            current_question="Q1",
            topics_explored=0,
            topics_total=1,
            facts_recorded=0,
        ),
        InterviewStateSnapshot(
            active=False,
            topics_explored=0,
            topics_total=1,
            facts_recorded=0,
        ),
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


async def test_synthesis_runs_off_the_event_loop() -> None:
    # CRITICAL fix: tts.synthesize is a blocking CPU/GPU call and must run in a worker thread
    # (asyncio.to_thread), never on the event loop. Capture the thread it executes on.
    main_thread = threading.current_thread()
    seen: dict[str, object] = {}

    def _synth(*a: object, **k: object) -> bytes:
        seen["thread"] = threading.current_thread()
        return b"PCM"

    pipeline = _mock_pipeline()
    pipeline.tts.synthesize = MagicMock(side_effect=_synth)
    conductor = InterviewConductor(
        pipeline=pipeline,
        runner=MagicMock(),
        questions=["Q1"],
        capture_answer=AsyncMock(return_value=b"A"),
    )
    await conductor.run()
    assert seen["thread"] is not main_thread  # ran off the event loop


async def test_ask_holds_speaking_gate_around_playback() -> None:
    gate: list[object] = []
    pipeline = _mock_pipeline()
    pipeline.buffer.set_speaking = MagicMock(side_effect=lambda v: gate.append(v))

    async def _play(**k: object) -> bool:
        gate.append("play")
        return True

    pipeline._play_guarded_pcm = AsyncMock(side_effect=_play)
    conductor = InterviewConductor(
        pipeline=pipeline,
        runner=MagicMock(),
        questions=["Q1"],
        capture_answer=AsyncMock(return_value=b"A"),
    )
    await conductor.run()
    # gate True BEFORE play, gate False AFTER — buffer stays deaf to Hapax's own question.
    assert gate == [True, "play", False]


async def test_unplayed_question_records_abstention_and_skips_listen() -> None:
    pipeline = _mock_pipeline()
    pipeline._play_guarded_pcm = AsyncMock(return_value=False)  # never reached air
    runner = MagicMock()
    capture_answer = AsyncMock()
    with patch("agents.hapax_daimonion.voice_output_witness.record_drop") as drop:
        conductor = InterviewConductor(
            pipeline=pipeline, runner=runner, questions=["Q1"], capture_answer=capture_answer
        )
        facts = await conductor.run()
    assert facts == [InterviewFact(question="Q1", answer="", abstained=True)]
    capture_answer.assert_not_awaited()  # did NOT listen to an unheard question
    pipeline.stt.transcribe.assert_not_awaited()
    runner.begin_interview_silence.assert_not_called()
    drop.assert_called_once()  # the drop was witnessed


async def test_empty_answer_recorded_as_abstention_not_fact() -> None:
    pipeline = _mock_pipeline(answer="   ")  # blank/whitespace transcription
    conductor = InterviewConductor(
        pipeline=pipeline,
        runner=MagicMock(),
        questions=["Q1"],
        capture_answer=AsyncMock(return_value=b"A"),
    )
    facts = await conductor.run()
    assert facts == [InterviewFact(question="Q1", answer="", abstained=True)]
    pipeline.process_utterance.assert_not_called()


async def test_empty_synthesis_witnessed_and_not_played() -> None:
    pipeline = _mock_pipeline()
    pipeline.tts.synthesize = MagicMock(return_value=b"")  # synthesis produced nothing
    with patch("agents.hapax_daimonion.voice_output_witness.record_drop") as drop:
        conductor = InterviewConductor(
            pipeline=pipeline, runner=MagicMock(), questions=["Q1"], capture_answer=AsyncMock()
        )
        facts = await conductor.run()
    assert facts == [InterviewFact(question="Q1", answer="", abstained=True)]
    pipeline._play_guarded_pcm.assert_not_awaited()  # nothing to play
    drop.assert_called_once()
