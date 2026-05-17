"""Tests for interview thread persistence (no mid-session compression)."""

from __future__ import annotations

from unittest.mock import MagicMock

from agents.hapax_daimonion.pipeline_start import _resolve_message_drop_threshold


class TestResolveMessageDropThreshold:
    def test_default_is_12(self) -> None:
        daemon = MagicMock(spec=[])
        assert _resolve_message_drop_threshold(daemon) == 12

    def test_interview_disables_compression(self) -> None:
        daemon = MagicMock()
        prog = MagicMock()
        prog.role.value = "interview"
        daemon.programme_manager.store.active_programme.return_value = prog
        threshold = _resolve_message_drop_threshold(daemon)
        assert threshold >= 200

    def test_lecture_raises_threshold(self) -> None:
        daemon = MagicMock()
        prog = MagicMock()
        prog.role.value = "lecture"
        daemon.programme_manager.store.active_programme.return_value = prog
        assert _resolve_message_drop_threshold(daemon) == 50

    def test_listening_uses_default(self) -> None:
        daemon = MagicMock()
        prog = MagicMock()
        prog.role.value = "listening"
        daemon.programme_manager.store.active_programme.return_value = prog
        assert _resolve_message_drop_threshold(daemon) == 12

    def test_exception_returns_default(self) -> None:
        daemon = MagicMock()
        daemon.programme_manager.store.active_programme.side_effect = RuntimeError("boom")
        assert _resolve_message_drop_threshold(daemon) == 12
