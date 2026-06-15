"""Tests for the TTS torch intraop thread cap (audit SS7-P0).

The daimonion unit caps OMP_NUM_THREADS=2 process-wide, which throttled
CPU Kokoro to RTF 0.10-0.135. The TTS path raises its own torch intraop
pool from versioned code; true isolation is the Phase 1 server
extraction (see tts.py docstring).
"""

from __future__ import annotations

import sys
import types
from typing import TYPE_CHECKING

from agents.hapax_daimonion import tts

if TYPE_CHECKING:
    import pytest


class TestResolveTtsTorchThreads:
    def test_unset_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(tts.TTS_TORCH_THREADS_ENV, raising=False)
        assert tts.resolve_tts_torch_threads() == tts._DEFAULT_TTS_TORCH_THREADS

    def test_valid_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(tts.TTS_TORCH_THREADS_ENV, "6")
        assert tts.resolve_tts_torch_threads() == 6

    def test_invalid_value_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(tts.TTS_TORCH_THREADS_ENV, "many")
        assert tts.resolve_tts_torch_threads() == tts._DEFAULT_TTS_TORCH_THREADS

    def test_non_positive_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(tts.TTS_TORCH_THREADS_ENV, "0")
        assert tts.resolve_tts_torch_threads() == tts._DEFAULT_TTS_TORCH_THREADS


class TestPreloadAppliesThreadCap:
    def test_preload_raises_torch_intraop_threads(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[int] = []
        fake_torch = types.SimpleNamespace(set_num_threads=calls.append)
        monkeypatch.setitem(sys.modules, "torch", fake_torch)
        monkeypatch.delenv(tts.TTS_TORCH_THREADS_ENV, raising=False)
        monkeypatch.setenv(tts.TTS_BACKEND_ENV, "kokoro")

        mgr = tts.TTSManager()
        monkeypatch.setattr(mgr, "_get_kokoro", lambda: object())
        mgr.preload()

        assert calls == [tts._DEFAULT_TTS_TORCH_THREADS]

    def test_torch_failure_is_non_fatal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(_n: int) -> None:
            raise RuntimeError("cannot set num threads")

        fake_torch = types.SimpleNamespace(set_num_threads=_boom)
        monkeypatch.setitem(sys.modules, "torch", fake_torch)
        monkeypatch.setenv(tts.TTS_BACKEND_ENV, "kokoro")

        mgr = tts.TTSManager()
        monkeypatch.setattr(mgr, "_get_kokoro", lambda: object())
        mgr.preload()  # must not raise
