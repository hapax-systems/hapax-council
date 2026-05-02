"""Tests for the runway_bigpitch CLI orchestrator."""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.runway_bigpitch.__main__ import main


def test_dry_run_prints_request_body_and_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("A cinematic shot of a granular vinyl substrate.")
    rc = main(
        [
            "--prompt-file",
            str(prompt),
            "--duration",
            "60",
        ]
    )
    assert rc == 0
    output = capsys.readouterr().out
    assert "DRY-RUN" in output
    assert "promptText" in output
    assert "gen3a_turbo" in output
    assert '"watermark": true' in output, "contest watermark requirement must be visible in dry-run"


def test_missing_prompt_file_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--prompt-file", str(tmp_path / "nonexistent.md")])
    assert rc == 2
    err = capsys.readouterr().err
    assert "not found" in err


def test_empty_prompt_file_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = tmp_path / "empty.md"
    prompt.write_text("   \n  \n")
    rc = main(["--prompt-file", str(prompt)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "empty" in err


def test_invalid_duration_raises_validation_error(tmp_path: Path) -> None:
    """Pydantic GenerateRequest enforces 1<=duration<=180 — bad values
    surface as ValidationError before the request reaches the API."""
    from pydantic import ValidationError

    prompt = tmp_path / "p.md"
    prompt.write_text("ok")
    with pytest.raises(ValidationError):
        main(["--prompt-file", str(prompt), "--duration", "1000"])


def test_no_watermark_flag_disables_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--no-watermark`` is for non-contest dry-runs only."""
    prompt = tmp_path / "p.md"
    prompt.write_text("ok")
    rc = main(["--prompt-file", str(prompt), "--no-watermark"])
    assert rc == 0
    output = capsys.readouterr().out
    assert '"watermark": false' in output


def test_live_without_api_key_exits_3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("RUNWAY_API_KEY", raising=False)
    prompt = tmp_path / "p.md"
    prompt.write_text("ok")
    rc = main(["--prompt-file", str(prompt), "--live"])
    assert rc == 3
    err = capsys.readouterr().err
    assert "RUNWAY_API_KEY" in err
