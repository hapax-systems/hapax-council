"""Tests for ``agents.mail_monitor.label_bootstrap``.

Mocks the Gmail discovery client; asserts idempotency, error
propagation, and the exact set of labels created.
"""

from __future__ import annotations

from unittest import mock

import pytest
from prometheus_client import REGISTRY

from agents.mail_monitor import label_bootstrap
from agents.mail_monitor.label_bootstrap import (
    HAPAX_LABEL_NAMES,
    LabelBootstrapError,
    bootstrap_labels,
)


def _service_double(
    *,
    existing: list[dict[str, str]] | None = None,
    create_returns: list[dict[str, str]] | None = None,
    list_raises: Exception | None = None,
    create_raises: Exception | None = None,
) -> mock.Mock:
    """Build a chainable Gmail service double.

    The Gmail discovery API is fluent: ``service.users().labels().list(
    userId="me").execute()``. The double mirrors that surface.
    """
    service = mock.Mock()

    list_call = service.users.return_value.labels.return_value.list
    if list_raises is not None:
        list_call.return_value.execute.side_effect = list_raises
    else:
        list_call.return_value.execute.return_value = {"labels": existing or []}

    create_call = service.users.return_value.labels.return_value.create
    if create_raises is not None:
        create_call.return_value.execute.side_effect = create_raises
    else:
        # Each call returns the next from create_returns.
        create_call.return_value.execute.side_effect = create_returns or []

    return service


def _counter_value(label: str, result: str) -> float:
    val = REGISTRY.get_sample_value(
        "hapax_mail_monitor_label_installs_total",
        {"label": label, "result": result},
    )
    return val or 0.0


def test_bootstrap_creates_all_four_when_account_is_empty() -> None:
    before_created = {name: _counter_value(name, "created") for name in HAPAX_LABEL_NAMES}
    create_returns = [{"id": f"L_{name}", "name": name} for name in HAPAX_LABEL_NAMES]
    service = _service_double(existing=[], create_returns=create_returns)

    result = bootstrap_labels(service)

    assert result == {name: f"L_{name}" for name in HAPAX_LABEL_NAMES}
    create_call = service.users.return_value.labels.return_value.create
    assert create_call.call_count == 4
    for name in HAPAX_LABEL_NAMES:
        assert _counter_value(name, "created") - before_created[name] == 1.0


def test_bootstrap_is_no_op_on_second_run() -> None:
    """Idempotency: when all 4 labels exist, no create calls happen."""
    before_exists = {name: _counter_value(name, "exists") for name in HAPAX_LABEL_NAMES}
    existing = [{"id": f"L_{name}", "name": name} for name in HAPAX_LABEL_NAMES]
    service = _service_double(existing=existing)

    result = bootstrap_labels(service)

    assert result == {name: f"L_{name}" for name in HAPAX_LABEL_NAMES}
    create_call = service.users.return_value.labels.return_value.create
    create_call.assert_not_called()
    for name in HAPAX_LABEL_NAMES:
        assert _counter_value(name, "exists") - before_exists[name] == 1.0


def test_bootstrap_creates_only_missing() -> None:
    """Partial install: 2 labels exist, 2 are created."""
    existing = [
        {"id": "L_v", "name": "Hapax/Verify"},
        {"id": "L_s", "name": "Hapax/Suppress"},
    ]
    create_returns = [
        {"id": "L_o", "name": "Hapax/Operational"},
        {"id": "L_d", "name": "Hapax/Discard"},
    ]
    service = _service_double(existing=existing, create_returns=create_returns)

    result = bootstrap_labels(service)

    assert result == {
        "Hapax/Verify": "L_v",
        "Hapax/Suppress": "L_s",
        "Hapax/Operational": "L_o",
        "Hapax/Discard": "L_d",
    }
    create_call = service.users.return_value.labels.return_value.create
    assert create_call.call_count == 2
    created_names = {call.kwargs["body"]["name"] for call in create_call.call_args_list}
    assert created_names == {"Hapax/Operational", "Hapax/Discard"}


def test_bootstrap_raises_when_list_fails() -> None:
    from googleapiclient.errors import HttpError

    err = HttpError(resp=mock.Mock(status=500), content=b"server error")
    service = _service_double(list_raises=err)

    before_errors = {name: _counter_value(name, "error") for name in HAPAX_LABEL_NAMES}
    with pytest.raises(LabelBootstrapError):
        bootstrap_labels(service)
    # Every label gets an "error" tally because list failed before any
    # per-label decision could be made.
    for name in HAPAX_LABEL_NAMES:
        assert _counter_value(name, "error") - before_errors[name] == 1.0


def test_bootstrap_raises_when_create_fails() -> None:
    from googleapiclient.errors import HttpError

    err = HttpError(resp=mock.Mock(status=403), content=b"insufficient scope")
    service = _service_double(existing=[], create_raises=err)

    before_error = _counter_value("Hapax/Verify", "error")
    with pytest.raises(LabelBootstrapError):
        bootstrap_labels(service)
    assert _counter_value("Hapax/Verify", "error") - before_error == 1.0


def test_label_create_body_uses_show_visibility() -> None:
    """Visibility settings ensure labels appear in the Gmail web UI."""
    create_returns = [{"id": f"L_{name}", "name": name} for name in HAPAX_LABEL_NAMES]
    service = _service_double(existing=[], create_returns=create_returns)

    bootstrap_labels(service)

    create_call = service.users.return_value.labels.return_value.create
    for call in create_call.call_args_list:
        body = call.kwargs["body"]
        assert body["labelListVisibility"] == "labelShow"
        assert body["messageListVisibility"] == "show"


def test_module_pre_registers_all_outcome_labels() -> None:
    for name in HAPAX_LABEL_NAMES:
        for outcome in ("exists", "created", "error"):
            val = REGISTRY.get_sample_value(
                "hapax_mail_monitor_label_installs_total",
                {"label": name, "result": outcome},
            )
            assert val is not None, (name, outcome)


def test_label_names_match_spec() -> None:
    assert label_bootstrap.HAPAX_LABEL_NAMES == [
        "Hapax/Verify",
        "Hapax/Suppress",
        "Hapax/Operational",
        "Hapax/Discard",
    ]
