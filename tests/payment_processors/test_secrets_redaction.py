from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any
from unittest import mock

from agents.payment_processors import secrets

if TYPE_CHECKING:
    import pytest


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> Any:
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_pass_show_logs_redacted_key_and_no_stderr(caplog: pytest.LogCaptureFixture) -> None:
    raw_key = secrets.LIBERAPAY_PASSWORD_KEY
    stderr = "literal-password-material"
    with (
        mock.patch.object(subprocess, "run", return_value=_completed(returncode=1, stderr=stderr)),
        caplog.at_level("DEBUG", logger=secrets.__name__),
    ):
        assert secrets.pass_show(raw_key) is None

    assert raw_key not in caplog.text
    assert stderr not in caplog.text
    assert secrets._credential_ref(raw_key) in caplog.text


def test_pass_show_exception_log_omits_exception_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_key = secrets.LIBERAPAY_PASSWORD_KEY
    with (
        mock.patch.object(subprocess, "run", side_effect=FileNotFoundError("secret-path")),
        caplog.at_level("WARNING", logger=secrets.__name__),
    ):
        assert secrets.pass_show(raw_key) is None

    assert raw_key not in caplog.text
    assert "secret-path" not in caplog.text
    assert "FileNotFoundError" in caplog.text
