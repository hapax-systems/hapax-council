"""Tests for ResidentSTT hot-path behavior.

Audit SSd/SS7-P0 (CASE-VOICE-FOUNDATION-20260610): the STT hot path must
stay lean — small beam, no word timestamps, no inline prosody — and
speculative partials must never queue ahead of final transcription.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import numpy as np

from agents.hapax_daimonion.resident_stt import ResidentSTT

if TYPE_CHECKING:
    import pytest

_PCM_HALF_SECOND = (np.zeros(8000, dtype=np.int16) + 1000).tobytes()


class _FakeSegment:
    def __init__(self, text: str) -> None:
        self.text = text
        self.words = None


class _FakeInfo:
    language = "en"


class _FakeModel:
    """Records transcribe kwargs and the thread that ran them."""

    def __init__(self, delay_s: float = 0.0) -> None:
        self.calls: list[dict] = []
        self._delay_s = delay_s

    def transcribe(self, audio, **kwargs):
        self.calls.append({"kwargs": kwargs, "thread": threading.current_thread().name})
        if self._delay_s:
            time.sleep(self._delay_s)
        return iter([_FakeSegment("hello world")]), _FakeInfo()


def _make_stt(delay_s: float = 0.0) -> tuple[ResidentSTT, _FakeModel]:
    stt = ResidentSTT()
    model = _FakeModel(delay_s=delay_s)
    stt._model = model
    return stt, model


async def test_hot_path_uses_small_beam_and_no_word_timestamps() -> None:
    stt, model = _make_stt()
    text = await stt.transcribe(_PCM_HALF_SECOND)
    assert text == "hello world"

    kwargs = model.calls[0]["kwargs"]
    assert kwargs["beam_size"] == 2
    assert kwargs.get("word_timestamps", False) is False


async def test_speculative_runs_on_separate_executor() -> None:
    """A long speculative decode must not delay final transcription —
    they run on distinct single-thread executors."""
    stt, model = _make_stt()

    await stt.transcribe(_PCM_HALF_SECOND, _speculative=True)
    await stt.transcribe(_PCM_HALF_SECOND)

    spec_thread = model.calls[0]["thread"]
    final_thread = model.calls[1]["thread"]
    assert spec_thread != final_thread
    assert spec_thread.startswith("stt-spec")
    assert final_thread.startswith("stt-final")


async def test_prosody_runs_off_the_stt_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prosody (Praat) must not run inline in the transcription thread."""
    stt, _model = _make_stt()
    ran = threading.Event()
    captured: dict[str, str] = {}

    def _fake_prosody(audio, sample_rate, word_timestamps) -> None:
        captured["thread"] = threading.current_thread().name
        ran.set()

    monkeypatch.setattr(ResidentSTT, "_extract_prosody", staticmethod(_fake_prosody))

    await stt.transcribe(_PCM_HALF_SECOND)

    assert ran.wait(timeout=5.0)
    assert captured["thread"].startswith("prosody")


async def test_speculative_does_not_extract_prosody(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stt, _model = _make_stt()
    ran = threading.Event()

    monkeypatch.setattr(
        ResidentSTT,
        "_extract_prosody",
        staticmethod(lambda *a: ran.set()),
    )

    await stt.transcribe(_PCM_HALF_SECOND, _speculative=True)
    assert not ran.wait(timeout=0.3)


async def test_final_transcribe_logs_decode_duration(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Decode latency is the task's before/after evidence — it must be
    visible in the journal on every final transcription."""
    stt, _model = _make_stt()
    with caplog.at_level("INFO", logger="agents.hapax_daimonion.resident_stt"):
        await stt.transcribe(_PCM_HALF_SECOND)

    messages = [r.getMessage() for r in caplog.records]
    assert any("ms decode" in m for m in messages), messages


async def test_unloaded_model_returns_empty() -> None:
    stt = ResidentSTT()
    assert await stt.transcribe(_PCM_HALF_SECOND) == ""
