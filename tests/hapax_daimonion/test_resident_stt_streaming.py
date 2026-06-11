"""Tests for resident streaming STT endpointing."""

from __future__ import annotations

import asyncio

import pytest

from agents.hapax_daimonion.resident_stt import (
    ResidentSTT,
    StreamingSTTConfig,
    StreamingSTTEvent,
    StreamingSTTSession,
)


class _FakeStreamingBackend:
    supports_streaming = True

    def __init__(self, partials: list[str]) -> None:
        self.partials = list(partials)
        self.reset_count = 0
        self.final_audio = b""

    def load(self) -> None:
        return

    def reset_stream(self) -> None:
        self.reset_count += 1

    def stream_step(self, audio_bytes: bytes, sample_rate: int) -> str:
        assert sample_rate == 16000
        self.final_audio += audio_bytes
        if not self.partials:
            return ""
        return self.partials.pop(0)

    def transcribe_sync(
        self,
        audio_bytes: bytes,
        sample_rate: int,
        language: str,
        speculative: bool,
    ) -> str:
        assert sample_rate == 16000
        assert language == "en"
        assert speculative is False
        return "fallback final" if audio_bytes else ""


def _frame(fill: int = 1) -> bytes:
    return bytes([fill, 0]) * 480


def _fast_config() -> StreamingSTTConfig:
    return StreamingSTTConfig(
        frame_ms=30,
        chunk_ms=60,
        pre_roll_ms=30,
        endpoint_silence_ms=60,
        min_utterance_ms=30,
        speech_start_frames=1,
    )


def test_streaming_session_emits_partials_and_endpointed_final() -> None:
    backend = _FakeStreamingBackend(["hel", "hello", "hello there"])
    session = StreamingSTTSession(backend, config=_fast_config())

    events: list[StreamingSTTEvent] = []
    events.extend(session.accept_audio(_frame(1), vad_probability=0.9))
    events.extend(session.accept_audio(_frame(2), vad_probability=0.9))
    events.extend(session.accept_audio(_frame(3), vad_probability=0.9))
    events.extend(session.accept_audio(_frame(4), vad_probability=0.01))
    events.extend(session.accept_audio(_frame(5), vad_probability=0.01))

    partials = [event for event in events if not event.is_final]
    finals = [event for event in events if event.is_final]

    assert [event.text for event in partials] == ["hel", "hello"]
    assert len(finals) == 1
    assert finals[0].text == "hello there"
    assert finals[0].reason == "silence_endpoint"
    assert finals[0].audio_bytes
    assert backend.reset_count >= 2


@pytest.mark.asyncio
async def test_resident_stt_queues_streaming_final_for_cpal() -> None:
    backend = _FakeStreamingBackend(["operator partial", "operator final"])
    stt = ResidentSTT(streaming_config=_fast_config())
    stt._backend = backend
    stt._stream_session = StreamingSTTSession(backend, config=_fast_config())

    await stt.accept_stream_frame(_frame(1), vad_probability=0.9)
    await stt.accept_stream_frame(_frame(2), vad_probability=0.9)
    await stt.accept_stream_frame(_frame(3), vad_probability=0.01)
    await stt.accept_stream_frame(_frame(4), vad_probability=0.01)

    final = stt.pop_stream_final()
    assert final is not None
    assert final.text == "operator final"
    assert stt.pop_stream_final() is None


def test_accept_stream_frame_is_noop_without_streaming_backend() -> None:
    stt = ResidentSTT()
    assert asyncio.run(stt.accept_stream_frame(_frame(), vad_probability=0.9)) == []
