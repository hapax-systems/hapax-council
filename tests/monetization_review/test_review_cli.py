"""Operator review CLI smoke tests.

Non-interactive paths: ``--list``, ``--prune``, ``--signal-reload``.
Interactive path uses monkeypatched ``input`` / ``subprocess.run``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from agents.monetization_review import cli
from agents.monetization_review.flagged_store import FlaggedStore

if TYPE_CHECKING:
    import pytest


def _seed_flagged(root: Path, *, capability: str, payload: str, ts: float) -> None:
    """Helper — write one flagged record at the given ts."""
    store = FlaggedStore(root=root)
    store.record_block(
        capability_name=capability,
        surface="tts",
        rendered_payload=payload,
        risk="medium",
        reason="ring2 escalated",
        now=ts,
    )


class TestList:
    def test_list_empty_prints_no_payloads(self, tmp_path: Path, capsys: Any) -> None:
        rc = cli.main(
            [
                "--flagged-dir",
                str(tmp_path / "flagged"),
                "--whitelist",
                str(tmp_path / "wl.yaml"),
                "--list",
            ]
        )
        assert rc == 0
        captured = capsys.readouterr()
        assert "No flagged payloads" in captured.out

    def test_list_renders_records(self, tmp_path: Path, capsys: Any) -> None:
        flagged_dir = tmp_path / "flagged"
        ts = datetime(2026, 4, 25, 12, tzinfo=UTC).timestamp()
        _seed_flagged(flagged_dir, capability="knowledge.web_search", payload="text one", ts=ts)
        rc = cli.main(
            [
                "--flagged-dir",
                str(flagged_dir),
                "--whitelist",
                str(tmp_path / "wl.yaml"),
                "--list",
            ]
        )
        assert rc == 0
        captured = capsys.readouterr()
        assert "knowledge.web_search" in captured.out
        assert "ring2 escalated" in captured.out


class TestPrune:
    def test_prune_removes_old(self, tmp_path: Path, capsys: Any) -> None:
        flagged_dir = tmp_path / "flagged"
        old_ts = (datetime.now(tz=UTC) - timedelta(days=10)).timestamp()
        _seed_flagged(flagged_dir, capability="cap", payload="p", ts=old_ts)
        rc = cli.main(
            [
                "--flagged-dir",
                str(flagged_dir),
                "--whitelist",
                str(tmp_path / "wl.yaml"),
                "--prune",
            ]
        )
        assert rc == 0
        captured = capsys.readouterr()
        assert "Pruned 1" in captured.out


class TestSignalReload:
    def test_signal_reload_skips_when_systemctl_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cli, "_has_systemctl", lambda: False)
        rc = cli.main(["--signal-reload"])
        assert rc == 0

    def test_signal_reload_invokes_systemctl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cli, "_has_systemctl", lambda: True)
        with patch("agents.monetization_review.cli.subprocess.run") as mock_run:
            rc = cli.main(["--signal-reload"])
        assert rc == 0
        # Each daemon should have a systemctl call.
        assert mock_run.call_count == len(cli.RELOAD_DAEMONS)
        for unit, call in zip(cli.RELOAD_DAEMONS, mock_run.call_args_list, strict=True):
            args, _ = call
            assert args[0][0] == "systemctl"
            assert args[0][-1] == unit


class TestInteractiveReview:
    def test_quit_exits_cleanly(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        flagged_dir = tmp_path / "flagged"
        ts = datetime(2026, 4, 25, 12, tzinfo=UTC).timestamp()
        _seed_flagged(flagged_dir, capability="cap.one", payload="hello", ts=ts)
        # First prompt → 'q'
        responses = iter(["q"])
        monkeypatch.setattr(cli, "_prompt", lambda *a, **kw: next(responses))
        rc = cli.main(
            [
                "--flagged-dir",
                str(flagged_dir),
                "--whitelist",
                str(tmp_path / "wl.yaml"),
                "--no-reload",
            ]
        )
        assert rc == 0

    def test_whitelist_choice_appends_to_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        flagged_dir = tmp_path / "flagged"
        wl_path = tmp_path / "wl.yaml"
        ts = datetime(2026, 4, 25, 12, tzinfo=UTC).timestamp()
        _seed_flagged(flagged_dir, capability="cap.one", payload="hello world", ts=ts)
        # First prompt → 'w', then 'q'
        responses = iter(["w", "q"])
        monkeypatch.setattr(cli, "_prompt", lambda *a, **kw: next(responses))
        rc = cli.main(
            [
                "--flagged-dir",
                str(flagged_dir),
                "--whitelist",
                str(wl_path),
                "--no-reload",
            ]
        )
        assert rc == 0
        text = wl_path.read_text()
        assert "hello world" in text

    def test_capability_choice_appends_to_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        flagged_dir = tmp_path / "flagged"
        wl_path = tmp_path / "wl.yaml"
        ts = datetime(2026, 4, 25, 12, tzinfo=UTC).timestamp()
        _seed_flagged(flagged_dir, capability="cap.one", payload="payload", ts=ts)
        responses = iter(["c", "q"])
        monkeypatch.setattr(cli, "_prompt", lambda *a, **kw: next(responses))
        rc = cli.main(
            [
                "--flagged-dir",
                str(flagged_dir),
                "--whitelist",
                str(wl_path),
                "--no-reload",
            ]
        )
        assert rc == 0
        text = wl_path.read_text()
        assert "cap.one" in text


class TestSighupHandler:
    def test_install_handler_calls_on_reload_on_signal(self) -> None:
        import signal as signal_module

        callback = MagicMock()
        cli.install_inprocess_sighup_handler(callback)
        # Programmatically deliver SIGHUP — verifies the handler runs.
        # The handler swallows callback exceptions; here the callback is
        # a Mock so calling it is safe.
        installed = signal_module.getsignal(signal_module.SIGHUP)
        assert callable(installed)
        installed(signal_module.SIGHUP, None)
        callback.assert_called_once()

    def test_handler_swallows_callback_exception(self) -> None:
        import signal as signal_module

        def raising() -> None:
            raise RuntimeError("boom")

        cli.install_inprocess_sighup_handler(raising)
        installed = signal_module.getsignal(signal_module.SIGHUP)
        # Must NOT propagate.
        installed(signal_module.SIGHUP, None)
