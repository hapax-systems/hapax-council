"""Tests for per-programme silence timeout configuration."""

from __future__ import annotations

from unittest.mock import MagicMock

from agents.hapax_daimonion.conversation_helpers import (
    _PROGRAMME_SILENCE_TIMEOUT,
    _SILENCE_TIMEOUT_S,
)
from agents.hapax_daimonion.pipeline_start import _resolve_silence_timeout


class TestResolveSilenceTimeout:
    def test_returns_default_without_programme_manager(self) -> None:
        daemon = MagicMock(spec=[])
        assert _resolve_silence_timeout(daemon) == _SILENCE_TIMEOUT_S

    def test_returns_default_with_no_active_programme(self) -> None:
        daemon = MagicMock()
        daemon.programme_manager.store.active_programme.return_value = None
        assert _resolve_silence_timeout(daemon) == _SILENCE_TIMEOUT_S

    def test_interview_returns_180(self) -> None:
        daemon = MagicMock()
        prog = MagicMock()
        prog.role.value = "interview"
        daemon.programme_manager.store.active_programme.return_value = prog
        assert _resolve_silence_timeout(daemon) == 180.0

    def test_lecture_returns_60(self) -> None:
        daemon = MagicMock()
        prog = MagicMock()
        prog.role.value = "lecture"
        daemon.programme_manager.store.active_programme.return_value = prog
        assert _resolve_silence_timeout(daemon) == 60.0

    def test_listening_returns_default(self) -> None:
        daemon = MagicMock()
        prog = MagicMock()
        prog.role.value = "listening"
        daemon.programme_manager.store.active_programme.return_value = prog
        assert _resolve_silence_timeout(daemon) == _SILENCE_TIMEOUT_S

    def test_exception_returns_default(self) -> None:
        daemon = MagicMock()
        daemon.programme_manager.store.active_programme.side_effect = RuntimeError("broken")
        assert _resolve_silence_timeout(daemon) == _SILENCE_TIMEOUT_S


class TestProgrammeSilenceTimeoutMap:
    def test_interview_in_map(self) -> None:
        assert "interview" in _PROGRAMME_SILENCE_TIMEOUT
        assert _PROGRAMME_SILENCE_TIMEOUT["interview"] >= 180.0

    def test_all_values_exceed_default(self) -> None:
        for role, timeout in _PROGRAMME_SILENCE_TIMEOUT.items():
            assert timeout > _SILENCE_TIMEOUT_S, f"{role} timeout not above default"
