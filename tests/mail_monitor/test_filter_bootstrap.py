"""Tests for ``agents.mail_monitor.filter_bootstrap``.

Asserts idempotency, partial-install correctness, body shape, and
that the YAML spec matches what the spec file requires.
"""

from __future__ import annotations

from unittest import mock

import pytest
from prometheus_client import REGISTRY

from agents.mail_monitor.filter_bootstrap import (
    FilterBootstrapError,
    bootstrap_filters,
    load_filter_specs,
)
from agents.mail_monitor.label_bootstrap import HAPAX_LABEL_NAMES

# Stable label-id mapping the tests pass through bootstrap_filters.
LABEL_IDS = {name: f"id-{name}" for name in HAPAX_LABEL_NAMES}


def _service_double(
    *,
    existing: list[dict] | None = None,
    create_returns: list[dict] | None = None,
    list_raises: Exception | None = None,
    create_raises: Exception | None = None,
) -> mock.Mock:
    """Chainable double for ``service.users().settings().filters()``."""
    service = mock.Mock()
    filters_chain = service.users.return_value.settings.return_value.filters.return_value
    if list_raises is not None:
        filters_chain.list.return_value.execute.side_effect = list_raises
    else:
        filters_chain.list.return_value.execute.return_value = {"filter": existing or []}
    if create_raises is not None:
        filters_chain.create.return_value.execute.side_effect = create_raises
    else:
        filters_chain.create.return_value.execute.side_effect = create_returns or []
    return service


def _existing(spec: dict, label_ids: dict[str, str], filter_id: str) -> dict:
    """Build a Gmail-side filter dict equivalent to ``spec``."""
    from agents.mail_monitor.filter_bootstrap import _resolve_label_id

    return {
        "id": filter_id,
        "criteria": {"query": spec["query"]},
        "action": {
            "addLabelIds": [_resolve_label_id(name, label_ids) for name in spec["add_labels"]],
            "removeLabelIds": [
                _resolve_label_id(name, label_ids) for name in spec["remove_labels"]
            ],
        },
    }


def _counter_value(filter_id: str, result: str) -> float:
    val = REGISTRY.get_sample_value(
        "hapax_mail_monitor_filter_installs_total",
        {"filter": filter_id, "result": result},
    )
    return val or 0.0


# ── filters.yaml ─────────────────────────────────────────────────────


def test_filters_yaml_has_four_specs_with_expected_ids() -> None:
    specs = load_filter_specs()
    assert {s["id"] for s in specs} == {
        "verify",
        "suppress",
        "operational",
        "discard",
    }


def test_discard_removes_inbox() -> None:
    """Spec §2: Hapax/Discard filter removes INBOX (mail skips inbox)."""
    specs = {s["id"]: s for s in load_filter_specs()}
    assert specs["discard"]["remove_labels"] == ["INBOX"]


def test_verify_removes_inbox() -> None:
    """Spec §2: Hapax/Verify filter removes INBOX (auto-handled mail)."""
    specs = {s["id"]: s for s in load_filter_specs()}
    assert specs["verify"]["remove_labels"] == ["INBOX"]


def test_suppress_keeps_inbox() -> None:
    """Spec §3.C: SUPPRESS replies stay in INBOX so operator can audit."""
    specs = {s["id"]: s for s in load_filter_specs()}
    assert specs["suppress"]["remove_labels"] == []


def test_operational_keeps_inbox() -> None:
    specs = {s["id"]: s for s in load_filter_specs()}
    assert specs["operational"]["remove_labels"] == []


# ── bootstrap_filters ─────────────────────────────────────────────────


def test_bootstrap_creates_all_four_when_account_is_empty() -> None:
    specs = load_filter_specs()
    create_returns = [{"id": f"F_{s['id']}"} for s in specs]
    service = _service_double(existing=[], create_returns=create_returns)
    before = {s["id"]: _counter_value(s["id"], "created") for s in specs}

    result = bootstrap_filters(service, LABEL_IDS)

    assert result == {s["id"]: f"F_{s['id']}" for s in specs}
    create_call = service.users.return_value.settings.return_value.filters.return_value.create
    assert create_call.call_count == 4
    for s in specs:
        assert _counter_value(s["id"], "created") - before[s["id"]] == 1.0


def test_bootstrap_is_no_op_when_all_filters_already_exist() -> None:
    specs = load_filter_specs()
    existing = [_existing(s, LABEL_IDS, f"F_{s['id']}") for s in specs]
    service = _service_double(existing=existing)
    before = {s["id"]: _counter_value(s["id"], "exists") for s in specs}

    result = bootstrap_filters(service, LABEL_IDS)

    assert result == {s["id"]: f"F_{s['id']}" for s in specs}
    create_call = service.users.return_value.settings.return_value.filters.return_value.create
    create_call.assert_not_called()
    for s in specs:
        assert _counter_value(s["id"], "exists") - before[s["id"]] == 1.0


def test_bootstrap_creates_only_missing_filters() -> None:
    specs = load_filter_specs()
    # First two already installed; last two missing.
    existing = [_existing(specs[0], LABEL_IDS, "F_v"), _existing(specs[1], LABEL_IDS, "F_s")]
    create_returns = [
        {"id": "F_o"},
        {"id": "F_d"},
    ]
    service = _service_double(existing=existing, create_returns=create_returns)

    result = bootstrap_filters(service, LABEL_IDS)

    assert result == {"verify": "F_v", "suppress": "F_s", "operational": "F_o", "discard": "F_d"}
    create_call = service.users.return_value.settings.return_value.filters.return_value.create
    assert create_call.call_count == 2


def test_match_requires_both_query_and_label_set_equality() -> None:
    """A pre-existing filter with the same query but different labels
    must NOT count as already-installed; bootstrap creates a new one."""
    specs = load_filter_specs()
    verify_spec = next(s for s in specs if s["id"] == "verify")

    # Existing filter with same query but only adds one label (no remove).
    rogue = {
        "id": "F_rogue",
        "criteria": {"query": verify_spec["query"]},
        "action": {
            "addLabelIds": [LABEL_IDS["Hapax/Verify"]],
            # Missing removeLabelIds=[INBOX] — operator-managed dup.
            "removeLabelIds": [],
        },
    }
    other_existing = [_existing(s, LABEL_IDS, f"F_{s['id']}") for s in specs if s["id"] != "verify"]
    create_returns = [{"id": "F_v_new"}]
    service = _service_double(
        existing=[rogue, *other_existing],
        create_returns=create_returns,
    )

    result = bootstrap_filters(service, LABEL_IDS)

    assert result["verify"] == "F_v_new"  # newly created, rogue ignored
    create_call = service.users.return_value.settings.return_value.filters.return_value.create
    assert create_call.call_count == 1


def test_create_body_resolves_label_names_to_ids() -> None:
    specs = load_filter_specs()
    create_returns = [{"id": f"F_{s['id']}"} for s in specs]
    service = _service_double(existing=[], create_returns=create_returns)

    bootstrap_filters(service, LABEL_IDS)

    create_call = service.users.return_value.settings.return_value.filters.return_value.create
    bodies = [c.kwargs["body"] for c in create_call.call_args_list]
    by_query = {b["criteria"]["query"]: b for b in bodies}

    discard_spec = next(s for s in specs if s["id"] == "discard")
    discard_body = by_query[discard_spec["query"]]
    assert discard_body["action"]["addLabelIds"] == [LABEL_IDS["Hapax/Discard"]]
    # INBOX is a Gmail system label id — passed through literally rather
    # than resolved via LABEL_IDS.
    assert discard_body["action"]["removeLabelIds"] == ["INBOX"]


def test_bootstrap_raises_when_label_ids_incomplete() -> None:
    incomplete = {name: f"id-{name}" for name in HAPAX_LABEL_NAMES[:2]}
    service = _service_double(existing=[])
    with pytest.raises(FilterBootstrapError, match="missing names"):
        bootstrap_filters(service, incomplete)


def test_bootstrap_raises_when_list_fails() -> None:
    from googleapiclient.errors import HttpError

    err = HttpError(resp=mock.Mock(status=500), content=b"server error")
    service = _service_double(list_raises=err)

    before = {s["id"]: _counter_value(s["id"], "error") for s in load_filter_specs()}
    with pytest.raises(FilterBootstrapError):
        bootstrap_filters(service, LABEL_IDS)
    for s in load_filter_specs():
        assert _counter_value(s["id"], "error") - before[s["id"]] == 1.0


def test_bootstrap_raises_when_create_fails() -> None:
    from googleapiclient.errors import HttpError

    err = HttpError(resp=mock.Mock(status=403), content=b"forbidden")
    service = _service_double(existing=[], create_raises=err)

    before = _counter_value("verify", "error")
    with pytest.raises(FilterBootstrapError):
        bootstrap_filters(service, LABEL_IDS)
    assert _counter_value("verify", "error") - before == 1.0


# ── filter_bootstrap module-level pre-registration ────────────────────


def test_module_pre_registers_all_filter_outcome_labels() -> None:
    for spec in load_filter_specs():
        for outcome in ("exists", "created", "error"):
            val = REGISTRY.get_sample_value(
                "hapax_mail_monitor_filter_installs_total",
                {"filter": spec["id"], "result": outcome},
            )
            assert val is not None, (spec["id"], outcome)
