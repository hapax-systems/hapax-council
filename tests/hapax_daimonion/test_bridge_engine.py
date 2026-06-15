from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from agents.hapax_daimonion import bridge_engine

if TYPE_CHECKING:
    import pytest


class _CountingTts:
    """Synthesize stub that counts calls; optional per-call delay."""

    def __init__(self, delay_s: float = 0.0) -> None:
        self.calls: list[str] = []
        self._delay_s = delay_s
        self._lock = threading.Lock()

    def synthesize(self, text: str, use_case: str) -> bytes:
        with self._lock:
            self.calls.append(text)
        if self._delay_s:
            time.sleep(self._delay_s)
        return b"\x00\x01"


def test_presynthesize_all_returns_true_and_fills_cache() -> None:
    engine = bridge_engine.BridgeEngine()
    tts = _CountingTts()

    assert engine.presynthesize_all(tts) is True
    assert len(engine._cache) == len(bridge_engine.ALL_PHRASES)
    assert len(tts.calls) == len(bridge_engine.ALL_PHRASES)


def test_second_run_skips_already_cached_phrases() -> None:
    """A retry after a completed run must not re-synthesize anything —
    duplicated full presynthesis cost ~80s of CPU per daemon restart."""
    engine = bridge_engine.BridgeEngine()
    tts = _CountingTts()
    engine.presynthesize_all(tts)

    assert engine.presynthesize_all(tts) is True
    assert len(tts.calls) == len(bridge_engine.ALL_PHRASES)


def test_concurrent_presynthesis_runs_once() -> None:
    """The startup background thread and the pipeline-start retry raced,
    each synthesizing all 51 phrases. The loser must skip and report False."""
    engine = bridge_engine.BridgeEngine()
    tts = _CountingTts(delay_s=0.01)
    results: dict[str, bool] = {}

    def _run(name: str) -> None:
        results[name] = engine.presynthesize_all(tts)

    first = threading.Thread(target=_run, args=("first",))
    second = threading.Thread(target=_run, args=("second",))
    first.start()
    time.sleep(0.05)  # first thread is mid-run
    second.start()
    first.join(timeout=30.0)
    second.join(timeout=30.0)

    assert sorted(results.values()) == [False, True]
    assert len(tts.calls) == len(bridge_engine.ALL_PHRASES)


def test_deterministic_index_uses_strong_hash_without_md5(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail_md5(*args: object, **kwargs: object) -> None:
        raise AssertionError("MD5 must not be used for bridge phrase selection")

    monkeypatch.setattr(bridge_engine.hashlib, "md5", _fail_md5)

    first = bridge_engine._deterministic_index("thinking", 3, "session-id-sensitive")
    second = bridge_engine._deterministic_index("thinking", 3, "session-id-sensitive")
    different = bridge_engine._deterministic_index("thinking", 4, "session-id-sensitive")

    assert first == second
    assert first != different
    assert isinstance(first, int)
