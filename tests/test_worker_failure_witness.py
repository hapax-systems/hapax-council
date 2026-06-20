"""Tests for worker_failure_witness — the guarded worker family-availability witness + receipt."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from shared.failure_classification import FailureCode, FailureReceipt
from shared.worker_failure_witness import (
    WORKER_AVAILABILITY_DEGRADE_CODES,
    WORKER_FAMILY_AVAILABILITY_STATE,
    append_failure_receipt_record,
    update_worker_family_availability,
)

_NOW = "2026-06-20T18:30:00+00:00"
_NON_DEGRADE = sorted(c for c in FailureCode if c not in WORKER_AVAILABILITY_DEGRADE_CODES)


def test_allowlist_is_exactly_quota_and_provider_outage() -> None:
    assert (
        frozenset({FailureCode.QUOTA_EXHAUSTION, FailureCode.PROVIDER_OUTAGE})
        == WORKER_AVAILABILITY_DEGRADE_CODES
    )
    # the conservative exclusions are load-bearing, pin them explicitly
    assert FailureCode.UNKNOWN not in WORKER_AVAILABILITY_DEGRADE_CODES
    assert FailureCode.TRANSIENT not in WORKER_AVAILABILITY_DEGRADE_CODES
    assert FailureCode.AUTH_FAILURE not in WORKER_AVAILABILITY_DEGRADE_CODES


@pytest.mark.parametrize("code", _NON_DEGRADE)
def test_non_degrade_code_never_witnesses_and_leaves_no_file(tmp_path, code: FailureCode) -> None:
    state = tmp_path / "worker-family-availability.json"
    wrote = update_worker_family_availability(
        family="claude", code=code, now_iso=_NOW, state_path=state
    )
    assert wrote is False
    assert not state.exists()  # complete no-op for an absent family — no auto-degrade


@pytest.mark.parametrize("code", sorted(WORKER_AVAILABILITY_DEGRADE_CODES))
def test_degrade_code_writes_one_iso_key(tmp_path, code: FailureCode) -> None:
    state = tmp_path / "worker-family-availability.json"
    wrote = update_worker_family_availability(
        family="claude", code=code, now_iso=_NOW, state_path=state
    )
    assert wrote is True
    data = json.loads(state.read_text())
    assert list(data) == ["claude"]  # exactly one key — the failing family
    datetime.fromisoformat(data["claude"])  # ISO-parseable, mirrors the review-plane format


def test_degrade_does_not_flip_a_sibling_family(tmp_path) -> None:
    state = tmp_path / "w.json"
    state.write_text(json.dumps({"codex": "2026-06-20T17:00:00+00:00"}))
    update_worker_family_availability(
        family="claude", code=FailureCode.QUOTA_EXHAUSTION, now_iso=_NOW, state_path=state
    )
    data = json.loads(state.read_text())
    assert data["codex"] == "2026-06-20T17:00:00+00:00"  # sibling untouched
    assert data["claude"] == _NOW  # only the failing family added


def test_recovery_clears_a_prior_degrade(tmp_path) -> None:
    state = tmp_path / "w.json"
    state.write_text(json.dumps({"claude": "2026-06-20T17:00:00+00:00"}))
    wrote = update_worker_family_availability(
        family="claude", code=FailureCode.TRANSIENT, now_iso=_NOW, state_path=state
    )
    assert wrote is False
    assert "claude" not in json.loads(state.read_text())  # cleared


def test_worker_witness_is_a_distinct_file_from_the_review_plane() -> None:
    # The worker witness must NOT live in the review-team plane (review_team.FAMILY_OUTAGE_STATE).
    assert "review-team" not in str(WORKER_FAMILY_AVAILABILITY_STATE)
    assert WORKER_FAMILY_AVAILABILITY_STATE.name == "worker-family-availability.json"
    assert WORKER_FAMILY_AVAILABILITY_STATE.parent.name == "capability"


def test_witness_module_is_a_leaf_no_coord_dispatch_cycle() -> None:
    # coord_dispatch is BELOW the CapabilityAdapter; the witness module must stay a leaf so the
    # launcher can use it alongside coord_dispatch without an import cycle. Check the actual IMPORT
    # statements (the docstring legitimately mentions coord_dispatch), not the raw source text.
    import ast

    import shared.worker_failure_witness as wfw

    tree = ast.parse(open(wfw.__file__, encoding="utf-8").read())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert not any("coord_dispatch" in m for m in imported), (
        f"witness module must not import coord_dispatch: {sorted(imported)}"
    )
    # the full worker-path import chain resolves in one interpreter (no circular import)
    import importlib

    for module in (
        "shared.coord_dispatch",
        "shared.capability_adapter_protocol",
        "shared.failure_classification",
        "shared.worker_failure_witness",
    ):
        importlib.import_module(module)


def test_receipt_append_is_envelope_plus_dumped_receipt(tmp_path) -> None:
    ledger = tmp_path / "failure-classification.jsonl"
    receipt = FailureReceipt(
        code=FailureCode.QUOTA_EXHAUSTION,
        raw_signal="You've hit your usage limit",
        platform="claude",
        route_id="claude.headless.opus",
    )
    ok = append_failure_receipt_record(
        task_id="t1",
        lane="cc-sdlc",
        returncode=70,
        receipt=receipt,
        now_iso=_NOW,
        ledger_path=ledger,
    )
    assert ok is True
    line = json.loads(ledger.read_text().splitlines()[-1])
    # envelope fields the FailureReceipt model does not carry
    assert line["ts"] == _NOW and line["task_id"] == "t1" and line["lane"] == "cc-sdlc"
    assert line["returncode"] == 70
    # dumped receipt fields (lossless)
    assert line["code"] == "quota_exhaustion"
    assert line["raw_signal"] == "You've hit your usage limit"
    assert line["platform"] == "claude" and line["route_id"] == "claude.headless.opus"
