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
        self.chunks: list[bytes] = []

    def load(self) -> None:
        return

    def reset_stream(self) -> None:
        self.reset_count += 1

    def stream_step(self, audio_bytes: bytes, sample_rate: int) -> str:
        assert sample_rate == 16000
        self.chunks.append(audio_bytes)
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
    # One reset starts the utterance stream; one reset clears it after endpointing.
    assert backend.reset_count == 2


def test_streaming_session_does_not_replay_stale_pre_roll_between_utterances() -> None:
    cfg = StreamingSTTConfig(
        frame_ms=30,
        chunk_ms=30,
        pre_roll_ms=90,
        endpoint_silence_ms=30,
        min_utterance_ms=30,
        speech_start_frames=1,
    )
    backend = _FakeStreamingBackend(["first", "first done", "", "second"])
    session = StreamingSTTSession(backend, config=cfg)

    session.accept_audio(_frame(1), vad_probability=0.9)
    session.accept_audio(_frame(2), vad_probability=0.01)

    backend.chunks.clear()
    session.accept_audio(_frame(7), vad_probability=0.01)
    session.accept_audio(_frame(9), vad_probability=0.9)

    assert [chunk[0] for chunk in backend.chunks] == [7, 9]


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


def test_nemo_load_failure_falls_back_to_whisper(monkeypatch):
    """Review finding 2026-06-11: Nemotron load failure must not leave the
    daemon deaf — Whisper fallback with a clear WARNING."""
    from agents.hapax_daimonion import resident_stt as rs

    class BoomNeMo:
        def __init__(self, *a, **k):
            raise RuntimeError("nemo not staged")

    loaded = {}

    class FakeWhisper:
        supports_streaming = False

        def __init__(self, model, device, compute_type):
            loaded["model"] = model

        def load(self):
            loaded["loaded"] = True

    monkeypatch.setattr(rs, "_NeMoStreamingBackend", BoomNeMo)
    monkeypatch.setattr(rs, "_WhisperBackend", FakeWhisper)
    stt = rs.ResidentSTT(model="nvidia/nemotron-speech-streaming-en-0.6b")
    stt.load()
    assert loaded.get("loaded"), "whisper fallback did not load"
    assert loaded["model"] == "distil-large-v3"
    assert stt._backend is not None
