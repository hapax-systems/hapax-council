"""Interactive conversation TTS look-ahead tests."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_daimonion.conversation_pipeline import ConversationPipeline, ConvState


def _chunk(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=content, tool_calls=None),
                finish_reason=None,
            )
        ]
    )


class _AsyncChunkStream:
    def __init__(
        self,
        chunks: list[str],
        *,
        before_yield: dict[int, Callable[[], Awaitable[None]]] | None = None,
        after_yield: dict[int, Callable[[], None]] | None = None,
    ) -> None:
        self._chunks = chunks
        self._before_yield = before_yield or {}
        self._after_yield = after_yield or {}
        self._index = 0

    def __aiter__(self) -> _AsyncChunkStream:
        return self

    async def __anext__(self) -> SimpleNamespace:
        if self._index >= len(self._chunks):
            raise StopAsyncIteration
        await asyncio.sleep(0)
        callback = self._before_yield.get(self._index)
        if callback is not None:
            await callback()
        chunk = self._chunks[self._index]
        callback_after = self._after_yield.get(self._index)
        self._index += 1
        if callback_after is not None:
            callback_after()
        return _chunk(chunk)


def _pipeline_for_generate() -> ConversationPipeline:
    pipeline = object.__new__(ConversationPipeline)
    pipeline._running = True  # type: ignore[attr-defined]
    pipeline.state = ConvState.THINKING
    pipeline.messages = [{"role": "system", "content": "system context"}]  # type: ignore[attr-defined]
    pipeline.llm_model = "test-model"  # type: ignore[attr-defined]
    pipeline._turn_model = "test-model"  # type: ignore[attr-defined]
    pipeline._turn_model_tier = "FAST"  # type: ignore[attr-defined]
    pipeline._experiment_flags = {"message_drop": False, "volatile_lockdown": True}  # type: ignore[attr-defined]
    pipeline._grounding_ledger = None  # type: ignore[attr-defined]
    pipeline.tools = []  # type: ignore[attr-defined]
    pipeline._tool_recruitment_gate = None  # type: ignore[attr-defined]
    pipeline.turn_count = 1  # type: ignore[attr-defined]
    pipeline.buffer = None  # type: ignore[attr-defined]
    pipeline._emit = MagicMock()  # type: ignore[method-assign]
    pipeline._handle_tool_calls = AsyncMock()  # type: ignore[method-assign]
    pipeline._last_assistant_end = 0.0  # type: ignore[attr-defined]
    return pipeline


@pytest.mark.asyncio
async def test_generate_and_speak_streams_next_clause_while_first_tts_is_pending() -> None:
    pipeline = _pipeline_for_generate()
    first_started = asyncio.Event()
    first_finished = asyncio.Event()
    second_chunk_requested = asyncio.Event()
    spoken: list[str] = []

    async def _speak(text: str) -> str:
        if text == "First complete clause.":
            first_started.set()
            await second_chunk_requested.wait()
            first_finished.set()
        spoken.append(text)
        return text

    async def _before_second_chunk() -> None:
        await asyncio.wait_for(first_started.wait(), timeout=0.5)
        assert not first_finished.is_set()
        second_chunk_requested.set()

    pipeline._speak_sentence = _speak  # type: ignore[method-assign]
    stream = _AsyncChunkStream(
        ["First complete clause. ", "Second complete clause. "],
        before_yield={1: _before_second_chunk},
    )

    with patch("litellm.acompletion", AsyncMock(return_value=stream)):
        await asyncio.wait_for(pipeline._generate_and_speak(), timeout=1.0)

    assert spoken == ["First complete clause.", "Second complete clause."]
    assert pipeline.messages[-1] == {
        "role": "assistant",
        "content": "First complete clause. Second complete clause.",
    }


@pytest.mark.asyncio
async def test_generate_and_speak_bounds_tts_queue_to_one_lookahead_clause() -> None:
    pipeline = _pipeline_for_generate()
    first_release = asyncio.Event()
    third_chunk_returned = asyncio.Event()
    started: list[str] = []

    async def _speak(text: str) -> str:
        started.append(text)
        if text == "First complete clause.":
            await first_release.wait()
        return text

    pipeline._speak_sentence = _speak  # type: ignore[method-assign]
    stream = _AsyncChunkStream(
        [
            "First complete clause. ",
            "Second complete clause. ",
            "Third complete clause. ",
        ],
        after_yield={2: third_chunk_returned.set},
    )

    with patch("litellm.acompletion", AsyncMock(return_value=stream)):
        task = asyncio.create_task(pipeline._generate_and_speak())
        await asyncio.wait_for(third_chunk_returned.wait(), timeout=1.0)
        await asyncio.sleep(0.05)
        assert started == ["First complete clause.", "Second complete clause."]
        first_release.set()
        await asyncio.wait_for(task, timeout=1.0)

    assert started == [
        "First complete clause.",
        "Second complete clause.",
        "Third complete clause.",
    ]
