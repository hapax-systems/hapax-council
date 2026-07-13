"""Proof for the money-rail ledger env leak predicate.

Narrow, deterministic unit proof of the detection logic that the autouse
per-test isolation fixture in ``tests/conftest.py`` runs at teardown. The
fixture's end-to-end engagement (real teardown ordering) is proven separately
by ``test_default_receipt_log_path_resolves_env_at_call_time``, which restores
the per-test env after its deliberate ``delenv`` so the detector stays green.
"""

from __future__ import annotations

from agents.payment_processors.resource_receipts import (
    DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH,
)
from tests.support.ledger_env_guard import resource_receipt_env_leak_reason


def test_per_test_path_is_not_a_leak(tmp_path) -> None:
    assert resource_receipt_env_leak_reason(str(tmp_path / "resource-receipts.jsonl")) is None


def test_unset_env_is_a_leak() -> None:
    reason = resource_receipt_env_leak_reason(None)
    assert reason is not None
    assert "unset" in reason


def test_empty_env_is_a_leak() -> None:
    reason = resource_receipt_env_leak_reason("")
    assert reason is not None
    assert "unset" in reason


def test_canonical_live_ledger_is_a_leak() -> None:
    reason = resource_receipt_env_leak_reason(str(DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH))
    assert reason is not None
    assert "canonical live ledger" in reason


def test_dotdot_alias_of_canonical_ledger_is_a_leak() -> None:
    # A ``..``-normalizing alias of the live ledger must be caught: lexical
    # comparison would miss it, resolve(strict=False) does not.
    canonical = DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH
    alias = str(canonical.parent / "nonexistent-sub" / ".." / canonical.name)
    assert alias != str(canonical)  # lexically distinct
    reason = resource_receipt_env_leak_reason(alias)
    assert reason is not None
    assert "canonical live ledger" in reason


def test_unrelated_relative_path_is_not_a_leak() -> None:
    # A genuinely different relative path (even with ``..``) resolves away from
    # the live ledger and must not be flagged.
    assert resource_receipt_env_leak_reason("some/other/../ledger.jsonl") is None
