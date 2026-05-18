"""Tests for per-programme max_turns configuration."""

from __future__ import annotations

from unittest.mock import MagicMock

from agents.hapax_daimonion.conversation_helpers import _MAX_TURNS, _PROGRAMME_MAX_TURNS
from agents.hapax_daimonion.pipeline_start import _resolve_max_turns


class TestResolveMaxTurns:
    def test_returns_default_without_programme_manager(self) -> None:
        daemon = MagicMock(spec=[])
        assert _resolve_max_turns(daemon) == _MAX_TURNS

    def test_returns_default_with_no_active_programme(self) -> None:
        daemon = MagicMock()
        daemon.programme_manager.store.active_programme.return_value = None
        assert _resolve_max_turns(daemon) == _MAX_TURNS

    def test_interview_returns_120(self) -> None:
        daemon = MagicMock()
        prog = MagicMock()
        prog.role.value = "interview"
        daemon.programme_manager.store.active_programme.return_value = prog
        assert _resolve_max_turns(daemon) == 120

    def test_lecture_returns_60(self) -> None:
        daemon = MagicMock()
        prog = MagicMock()
        prog.role.value = "lecture"
        daemon.programme_manager.store.active_programme.return_value = prog
        assert _resolve_max_turns(daemon) == 60

    def test_listening_returns_default(self) -> None:
        daemon = MagicMock()
        prog = MagicMock()
        prog.role.value = "listening"
        daemon.programme_manager.store.active_programme.return_value = prog
        assert _resolve_max_turns(daemon) == _MAX_TURNS

    def test_exception_returns_default(self) -> None:
        daemon = MagicMock()
        daemon.programme_manager.store.active_programme.side_effect = RuntimeError("store broken")
        assert _resolve_max_turns(daemon) == _MAX_TURNS


class TestProgrammeMaxTurnsMap:
    def test_interview_in_map(self) -> None:
        assert "interview" in _PROGRAMME_MAX_TURNS
        assert _PROGRAMME_MAX_TURNS["interview"] >= 100

    def test_all_values_positive(self) -> None:
        for role, turns in _PROGRAMME_MAX_TURNS.items():
            assert turns > 0, f"{role} has non-positive max_turns"
