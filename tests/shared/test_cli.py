"""Tests for shared.cli — common CLI boilerplate for agents.

84-LOC argparse helper + output handler. Untested before this commit.
Tests use a tiny pydantic.BaseModel fixture and capture stdout/stderr
via pytest's capsys to verify each output mode without side effects.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from shared.cli import add_common_args, handle_output


class _Sample(BaseModel):
    """Minimal pydantic fixture for output handler tests."""

    name: str = "alpha"
    n: int = 7


# ── add_common_args ────────────────────────────────────────────────


class TestAddCommonArgs:
    def test_json_always_present(self) -> None:
        parser = argparse.ArgumentParser()
        add_common_args(parser)
        args = parser.parse_args(["--json"])
        assert args.json is True

    def test_save_flag_off_by_default(self) -> None:
        """Without ``save=True``, --save is NOT added."""
        parser = argparse.ArgumentParser()
        add_common_args(parser)
        with pytest.raises(SystemExit):
            parser.parse_args(["--save"])

    def test_save_flag_on_with_save_kwarg(self) -> None:
        parser = argparse.ArgumentParser()
        add_common_args(parser, save=True)
        args = parser.parse_args(["--save"])
        assert args.save is True

    def test_hours_default_is_24(self) -> None:
        parser = argparse.ArgumentParser()
        add_common_args(parser, hours=True)
        args = parser.parse_args([])
        assert args.hours == 24

    def test_hours_explicit_value(self) -> None:
        parser = argparse.ArgumentParser()
        add_common_args(parser, hours=True)
        args = parser.parse_args(["--hours", "72"])
        assert args.hours == 72

    def test_notify_flag(self) -> None:
        parser = argparse.ArgumentParser()
        add_common_args(parser, notify=True)
        args = parser.parse_args(["--notify"])
        assert args.notify is True


# ── handle_output: stdout modes ────────────────────────────────────


def _ns(**kwargs: object) -> argparse.Namespace:
    """Build a fake argparse.Namespace with the given attributes."""
    return argparse.Namespace(**kwargs)


class TestHandleOutputStdout:
    def test_json_mode_prints_model_dump_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        handle_output(_Sample(), _ns(json=True))
        out = capsys.readouterr().out
        assert '"name": "alpha"' in out
        assert '"n": 7' in out

    def test_human_formatter_when_not_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        handle_output(
            _Sample(),
            _ns(json=False),
            human_formatter=lambda r: f"hello {r.name}",
        )
        out = capsys.readouterr().out.strip()
        assert out == "hello alpha"

    def test_no_formatter_falls_back_to_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Without --json AND without human_formatter, output still goes
        to model_dump_json."""
        handle_output(_Sample(), _ns(json=False))
        out = capsys.readouterr().out
        assert '"name": "alpha"' in out


# ── handle_output: --save ──────────────────────────────────────────


class TestHandleOutputSave:
    def test_save_writes_to_path_with_default_formatter(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "out.json"
        handle_output(_Sample(), _ns(json=True, save=True), save_path=target)
        assert target.exists()
        assert '"name": "alpha"' in target.read_text()
        # Stderr "Saved to ..." breadcrumb should be present.
        assert f"Saved to {target}" in capsys.readouterr().err

    def test_save_uses_custom_formatter(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        handle_output(
            _Sample(),
            _ns(json=True, save=True),
            save_path=target,
            save_formatter=lambda r: f"{r.name}={r.n}",
        )
        assert target.read_text() == "alpha=7"

    def test_save_skipped_when_args_save_missing(self, tmp_path: Path) -> None:
        """If args has no .save attribute (or is False), no write occurs."""
        target = tmp_path / "no-write.json"
        handle_output(_Sample(), _ns(json=True), save_path=target)
        assert not target.exists()

    def test_save_skipped_when_save_path_none(self, tmp_path: Path) -> None:
        """Even with --save=True, no write if save_path is None."""
        # No path → no error, just silent skip.
        handle_output(_Sample(), _ns(json=True, save=True), save_path=None)
        # If we got here without raising, the skip worked.


# ── handle_output: --notify ────────────────────────────────────────


class TestHandleOutputNotify:
    def test_notify_calls_send_notification(self) -> None:
        with patch("shared.notify.send_notification") as mock_send:
            handle_output(
                _Sample(),
                _ns(json=True, notify=True),
                notify_title="alpha-notice",
                notify_formatter=lambda r: f"body for {r.name}",
            )
        mock_send.assert_called_once()
        title, body = mock_send.call_args.args
        assert title == "alpha-notice"
        assert body == "body for alpha"

    def test_notify_truncates_body_to_500(self) -> None:
        long_body = "x" * 800
        with patch("shared.notify.send_notification") as mock_send:
            handle_output(
                _Sample(),
                _ns(json=True, notify=True),
                notify_title="t",
                notify_formatter=lambda r: long_body,
            )
        body = mock_send.call_args.args[1]
        assert len(body) == 500

    def test_notify_skipped_without_title(self) -> None:
        """Empty notify_title → no notification even with --notify."""
        with patch("shared.notify.send_notification") as mock_send:
            handle_output(_Sample(), _ns(json=True, notify=True), notify_title="")
        mock_send.assert_not_called()
