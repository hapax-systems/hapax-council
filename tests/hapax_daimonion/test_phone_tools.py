"""Tests for phone voice command tool subprocess handling."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from agents.hapax_daimonion import phone_tools


def test_cli_returns_stdout_when_subprocess_succeeds() -> None:
    result = subprocess.CompletedProcess(
        args=["kdeconnect-cli"],
        returncode=0,
        stdout="Ringing\n",
        stderr="",
    )

    with patch("agents.hapax_daimonion.phone_tools.subprocess.run", return_value=result):
        assert phone_tools.find_phone() == "Ringing"


def test_cli_empty_success_can_return_done() -> None:
    result = subprocess.CompletedProcess(
        args=["kdeconnect-cli"],
        returncode=0,
        stdout="",
        stderr="",
    )

    with patch("agents.hapax_daimonion.phone_tools.subprocess.run", return_value=result):
        assert phone_tools.lock_phone() == "Done"


def test_cli_subprocess_failure_does_not_return_done() -> None:
    result = subprocess.CompletedProcess(
        args=["kdeconnect-cli"],
        returncode=1,
        stdout="",
        stderr="device unavailable\n",
    )

    with patch("agents.hapax_daimonion.phone_tools.subprocess.run", return_value=result):
        response = phone_tools.lock_phone()

    assert response.startswith("Failed:")
    assert "device unavailable" in response
    assert response != "Done"


def test_cli_subprocess_failure_without_stderr_reports_exit_code() -> None:
    result = subprocess.CompletedProcess(
        args=["kdeconnect-cli"],
        returncode=2,
        stdout="",
        stderr="",
    )

    with patch("agents.hapax_daimonion.phone_tools.subprocess.run", return_value=result):
        assert phone_tools.phone_notifications() == "Failed: exit 2"
