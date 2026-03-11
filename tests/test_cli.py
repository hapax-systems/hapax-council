"""Tests for shared.cli -- common CLI boilerplate."""
from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from pydantic import BaseModel

from shared.cli import add_common_args, handle_output


class FakeOutput(BaseModel):
    headline: str = "test headline"
    count: int = 42


# -- add_common_args --------------------------------------------------------

def test_add_common_args_json():
    parser = argparse.ArgumentParser()
    add_common_args(parser)
    args = parser.parse_args(["--json"])
    assert args.json is True


def test_add_common_args_default_no_json():
    parser = argparse.ArgumentParser()
    add_common_args(parser)
    args = parser.parse_args([])
    assert args.json is False


def test_add_common_args_with_save():
    parser = argparse.ArgumentParser()
    add_common_args(parser, save=True)
    args = parser.parse_args(["--save"])
    assert args.save is True


def test_add_common_args_with_hours():
    parser = argparse.ArgumentParser()
    add_common_args(parser, hours=True)
    args = parser.parse_args(["--hours", "48"])
    assert args.hours == 48


def test_add_common_args_hours_default():
    parser = argparse.ArgumentParser()
    add_common_args(parser, hours=True)
    args = parser.parse_args([])
    assert args.hours == 24


def test_add_common_args_with_notify():
    parser = argparse.ArgumentParser()
    add_common_args(parser, notify=True)
    args = parser.parse_args(["--notify"])
    assert args.notify is True


def test_add_common_args_no_save_without_flag():
    """--save shouldn't be available unless save=True is passed."""
    parser = argparse.ArgumentParser()
    add_common_args(parser, save=False)
    with pytest.raises(SystemExit):
        parser.parse_args(["--save"])


# -- handle_output ----------------------------------------------------------

def test_handle_output_json(capsys):
    result = FakeOutput()
    args = argparse.Namespace(json=True, save=False, notify=False)
    handle_output(result, args)
    captured = capsys.readouterr()
    assert '"headline"' in captured.out
    assert '"test headline"' in captured.out


def test_handle_output_human_formatter(capsys):
    result = FakeOutput()
    args = argparse.Namespace(json=False, save=False, notify=False)
    handle_output(result, args, human_formatter=lambda r: f"Headline: {r.headline}")
    captured = capsys.readouterr()
    assert "Headline: test headline" in captured.out


def test_handle_output_fallback_to_json(capsys):
    """Without human_formatter and without --json, falls back to JSON."""
    result = FakeOutput()
    args = argparse.Namespace(json=False, save=False, notify=False)
    handle_output(result, args)
    captured = capsys.readouterr()
    assert '"headline"' in captured.out


def test_handle_output_save(tmp_path, capsys):
    result = FakeOutput()
    save_file = tmp_path / "output.json"
    args = argparse.Namespace(json=False, save=True, notify=False)
    handle_output(result, args, save_path=save_file)
    assert save_file.exists()
    assert '"headline"' in save_file.read_text()
    assert "Saved to" in capsys.readouterr().err


def test_handle_output_save_with_formatter(tmp_path, capsys):
    result = FakeOutput()
    save_file = tmp_path / "output.md"
    args = argparse.Namespace(json=False, save=True, notify=False)
    handle_output(
        result, args,
        save_path=save_file,
        save_formatter=lambda r: f"# {r.headline}",
    )
    assert save_file.read_text() == "# test headline"


@patch("shared.notify.send_notification")
def test_handle_output_notify(mock_notify, capsys):
    result = FakeOutput()
    args = argparse.Namespace(json=False, save=False, notify=True)
    handle_output(
        result, args,
        notify_title="Test Agent",
        notify_formatter=lambda r: r.headline,
    )
    mock_notify.assert_called_once_with("Test Agent", "test headline")


def test_handle_output_no_notify_without_title(capsys):
    """Notify is skipped if no notify_title is provided."""
    result = FakeOutput()
    args = argparse.Namespace(json=False, save=False, notify=True)
    # Should not raise even with notify=True but no title
    handle_output(result, args)


def test_handle_output_save_no_path(capsys):
    """Save is skipped if no save_path is provided."""
    result = FakeOutput()
    args = argparse.Namespace(json=False, save=True, notify=False)
    handle_output(result, args)  # No save_path — should not raise
