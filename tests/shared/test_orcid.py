"""Tests for ``shared.orcid.operator_orcid``.

Covers the env-var fallback path added by the
``orcid-config-write-automation`` cc-task plus the existing
pass-store fallback.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import shared.orcid as orcid_module
from shared.orcid import ORCID_ENV_VAR, operator_orcid


def _clear_cache() -> None:
    """Reset the module-level lru_cache between tests."""
    operator_orcid.cache_clear()


class TestEnvVarFallback:
    def test_env_var_wins(self, monkeypatch):
        _clear_cache()
        monkeypatch.setenv(ORCID_ENV_VAR, "0009-0001-5146-4548")
        # If pass were called it would error; the env var should win first.
        with patch.object(orcid_module.subprocess, "run") as mock_run:
            assert operator_orcid() == "0009-0001-5146-4548"
            mock_run.assert_not_called()

    def test_env_var_whitespace_stripped(self, monkeypatch):
        _clear_cache()
        monkeypatch.setenv(ORCID_ENV_VAR, "  0009-0001-5146-4548  ")
        assert operator_orcid() == "0009-0001-5146-4548"

    def test_empty_env_var_falls_back_to_pass(self, monkeypatch):
        _clear_cache()
        monkeypatch.setenv(ORCID_ENV_VAR, "")
        with patch.object(orcid_module.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="0009-0001-5146-4548\n",
                stderr="",
            )
            assert operator_orcid() == "0009-0001-5146-4548"
            mock_run.assert_called_once()


class TestPassStoreFallback:
    def test_pass_show_success(self, monkeypatch):
        _clear_cache()
        monkeypatch.delenv(ORCID_ENV_VAR, raising=False)
        with patch.object(orcid_module.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="0009-0001-5146-4548\n",
                stderr="",
            )
            assert operator_orcid() == "0009-0001-5146-4548"

    def test_pass_show_failure_returns_none(self, monkeypatch):
        _clear_cache()
        monkeypatch.delenv(ORCID_ENV_VAR, raising=False)
        with patch.object(orcid_module.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr="not found",
            )
            assert operator_orcid() is None

    def test_pass_not_installed_returns_none(self, monkeypatch):
        _clear_cache()
        monkeypatch.delenv(ORCID_ENV_VAR, raising=False)
        with patch.object(
            orcid_module.subprocess,
            "run",
            side_effect=FileNotFoundError(),
        ):
            assert operator_orcid() is None

    def test_pass_timeout_returns_none(self, monkeypatch):
        _clear_cache()
        monkeypatch.delenv(ORCID_ENV_VAR, raising=False)
        with patch.object(
            orcid_module.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd=[], timeout=5.0),
        ):
            assert operator_orcid() is None

    def test_pass_empty_stdout_returns_none(self, monkeypatch):
        _clear_cache()
        monkeypatch.delenv(ORCID_ENV_VAR, raising=False)
        with patch.object(orcid_module.subprocess, "run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="\n",
                stderr="",
            )
            assert operator_orcid() is None
