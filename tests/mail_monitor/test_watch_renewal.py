"""Tests for ``agents.mail_monitor.watch_renewal``."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest import mock

from prometheus_client import REGISTRY

from agents.mail_monitor import watch_renewal
from agents.mail_monitor.label_bootstrap import HAPAX_LABEL_NAMES

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _counter(result: str) -> float:
    val = REGISTRY.get_sample_value(
        "hapax_mail_monitor_watch_renewal_total",
        {"result": result},
    )
    return val or 0.0


def test_renew_once_returns_false_when_credentials_missing() -> None:
    before = _counter("no_credentials")
    with mock.patch.object(watch_renewal, "load_credentials", return_value=None):
        assert watch_renewal.renew_once() is False
    assert _counter("no_credentials") - before == 1.0


def test_renew_once_returns_false_when_service_build_fails() -> None:
    before = _counter("no_credentials")
    with (
        mock.patch.object(watch_renewal, "load_credentials", return_value=mock.Mock()),
        mock.patch.object(watch_renewal, "build_gmail_service", return_value=None),
    ):
        assert watch_renewal.renew_once() is False
    assert _counter("no_credentials") - before == 1.0


def test_renew_once_returns_false_when_project_id_missing() -> None:
    before = _counter("no_project")
    with (
        mock.patch.object(watch_renewal, "load_credentials", return_value=mock.Mock()),
        mock.patch.object(watch_renewal, "build_gmail_service", return_value=mock.Mock()),
        mock.patch.object(watch_renewal, "_pass_show", return_value=None),
    ):
        assert watch_renewal.renew_once() is False
    assert _counter("no_project") - before == 1.0


def test_renew_once_returns_false_when_label_bootstrap_fails() -> None:
    from agents.mail_monitor.label_bootstrap import LabelBootstrapError

    before = _counter("label_bootstrap_error")
    with (
        mock.patch.object(watch_renewal, "load_credentials", return_value=mock.Mock()),
        mock.patch.object(watch_renewal, "build_gmail_service", return_value=mock.Mock()),
        mock.patch.object(watch_renewal, "_pass_show", return_value="my-project"),
        mock.patch.object(
            watch_renewal,
            "bootstrap_labels",
            side_effect=LabelBootstrapError("403 forbidden"),
        ),
    ):
        assert watch_renewal.renew_once() is False
    assert _counter("label_bootstrap_error") - before == 1.0


def test_renew_once_returns_true_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full happy path: creds + service + project + labels + watch all OK."""
    from agents.mail_monitor import watch as watch_mod

    monkeypatch.setattr(watch_mod, "WATCH_STATE_PATH", tmp_path / "watch.json")
    before = _counter("success")

    fake_label_ids = {name: f"L_{name}" for name in HAPAX_LABEL_NAMES}
    fake_service = mock.Mock()
    fake_service.users.return_value.watch.return_value.execute.return_value = {
        "historyId": "abc",
        "expiration": "9999999999000",
    }

    with (
        mock.patch.object(watch_renewal, "load_credentials", return_value=mock.Mock()),
        mock.patch.object(watch_renewal, "build_gmail_service", return_value=fake_service),
        mock.patch.object(watch_renewal, "_pass_show", return_value="my-project"),
        mock.patch.object(watch_renewal, "bootstrap_labels", return_value=fake_label_ids),
    ):
        assert watch_renewal.renew_once() is True

    assert _counter("success") - before == 1.0
    body = fake_service.users.return_value.watch.call_args.kwargs["body"]
    assert body["topicName"] == "projects/my-project/topics/hapax-mail-monitor"
    assert body["labelFilterAction"] == "INCLUDE"
    assert set(body["labelIds"]) == set(fake_label_ids.values())


def test_renew_once_handles_watch_http_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.mail_monitor import watch as watch_mod

    monkeypatch.setattr(watch_mod, "WATCH_STATE_PATH", tmp_path / "watch.json")

    from googleapiclient.errors import HttpError

    before = _counter("api_error")

    fake_label_ids = {name: f"L_{name}" for name in HAPAX_LABEL_NAMES}
    fake_service = mock.Mock()
    fake_service.users.return_value.watch.return_value.execute.side_effect = HttpError(
        resp=mock.Mock(status=403), content=b"insufficient pubsub permission"
    )

    with (
        mock.patch.object(watch_renewal, "load_credentials", return_value=mock.Mock()),
        mock.patch.object(watch_renewal, "build_gmail_service", return_value=fake_service),
        mock.patch.object(watch_renewal, "_pass_show", return_value="my-project"),
        mock.patch.object(watch_renewal, "bootstrap_labels", return_value=fake_label_ids),
    ):
        assert watch_renewal.renew_once() is False
    assert _counter("api_error") - before == 1.0


def test_main_returns_zero_on_success() -> None:
    with mock.patch.object(watch_renewal, "renew_once", return_value=True):
        assert watch_renewal.main([]) == 0


def test_main_returns_one_on_failure() -> None:
    with mock.patch.object(watch_renewal, "renew_once", return_value=False):
        assert watch_renewal.main([]) == 1


def test_module_pre_registers_all_outcome_labels() -> None:
    for outcome in (
        "success",
        "no_credentials",
        "no_project",
        "label_bootstrap_error",
        "api_error",
        "watch_error",
    ):
        val = REGISTRY.get_sample_value(
            "hapax_mail_monitor_watch_renewal_total",
            {"result": outcome},
        )
        assert val is not None, outcome
