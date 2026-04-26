"""Tests for ``agents.mail_monitor.bootstrap`` CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest import mock

from agents.mail_monitor import bootstrap as bootstrap_mod
from agents.mail_monitor.label_bootstrap import HAPAX_LABEL_NAMES

if TYPE_CHECKING:
    import pytest


def test_main_returns_one_when_credentials_unavailable(capsys: pytest.CaptureFixture) -> None:
    with mock.patch.object(bootstrap_mod, "load_credentials", return_value=None):
        rc = bootstrap_mod.main([])
    assert rc == 1
    err = capsys.readouterr().err
    assert "load_credentials returned None" in err


def test_main_returns_one_when_service_build_fails(
    capsys: pytest.CaptureFixture,
) -> None:
    with (
        mock.patch.object(bootstrap_mod, "load_credentials", return_value=mock.Mock()),
        mock.patch.object(bootstrap_mod, "build_gmail_service", return_value=None),
    ):
        rc = bootstrap_mod.main([])
    assert rc == 1
    assert "build_gmail_service returned None" in capsys.readouterr().err


def test_main_install_path_invokes_bootstrap_helpers(
    capsys: pytest.CaptureFixture,
) -> None:
    fake_service = mock.Mock()
    with (
        mock.patch.object(bootstrap_mod, "load_credentials", return_value=mock.Mock()),
        mock.patch.object(bootstrap_mod, "build_gmail_service", return_value=fake_service),
        mock.patch.object(
            bootstrap_mod,
            "bootstrap_labels",
            return_value={n: f"L_{n}" for n in HAPAX_LABEL_NAMES},
        ) as label_mock,
        mock.patch.object(
            bootstrap_mod,
            "bootstrap_filters",
            return_value={
                "verify": "F_v",
                "suppress": "F_s",
                "operational": "F_o",
                "discard": "F_d",
            },
        ) as filter_mock,
    ):
        rc = bootstrap_mod.main([])

    assert rc == 0
    label_mock.assert_called_once_with(fake_service)
    filter_mock.assert_called_once()
    out = capsys.readouterr().out
    assert "Hapax/Verify" in out
    assert "verify" in out


def test_main_check_returns_zero_when_all_present(
    capsys: pytest.CaptureFixture,
) -> None:
    fake_service = mock.Mock()
    fake_service.users().labels().list().execute.return_value = {
        "labels": [{"id": f"L_{n}", "name": n} for n in HAPAX_LABEL_NAMES]
    }
    fake_service.users().settings().filters().list().execute.return_value = {
        "filter": [
            {"id": "F1", "criteria": {"query": s["query"]}}
            for s in bootstrap_mod.load_filter_specs()
        ]
    }
    with (
        mock.patch.object(bootstrap_mod, "load_credentials", return_value=mock.Mock()),
        mock.patch.object(bootstrap_mod, "build_gmail_service", return_value=fake_service),
    ):
        rc = bootstrap_mod.main(["--check"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "MISSING" not in out


def test_main_check_returns_one_when_anything_missing(
    capsys: pytest.CaptureFixture,
) -> None:
    fake_service = mock.Mock()
    fake_service.users().labels().list().execute.return_value = {"labels": []}
    fake_service.users().settings().filters().list().execute.return_value = {"filter": []}
    with (
        mock.patch.object(bootstrap_mod, "load_credentials", return_value=mock.Mock()),
        mock.patch.object(bootstrap_mod, "build_gmail_service", return_value=fake_service),
    ):
        rc = bootstrap_mod.main(["--check"])

    assert rc == 1
    out = capsys.readouterr().out
    assert out.count("MISSING") >= 4
