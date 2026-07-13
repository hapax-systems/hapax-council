"""Leak detector for the money-rail resource-receipt ledger env isolation.

Pure predicate consumed by the autouse per-test fixture teardown in
``tests/conftest.py`` and unit-proven in
``tests/support/test_ledger_env_guard.py``. It reports *why* a ledger env value
would expose the live production ledger, or ``None`` when the value is a safe
per-test path.

Ceiling: this detects a value that a test left *persistently* unset or pointed
at the canonical live ledger by teardown. It cannot detect a deliberately
temporary escape that a test unsets and then restores before returning — the
resolver reads the env at call time, so a within-test window with the env
removed is invisible once the value is put back.
"""

from __future__ import annotations

from pathlib import Path

from agents.payment_processors.resource_receipts import (
    DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH,
    MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV,
)


def resource_receipt_env_leak_reason(value: str | None) -> str | None:
    """Return why ``value`` would leak the live ledger, or ``None`` when safe.

    ``value`` is the process value of
    ``HAPAX_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH`` observed at per-test teardown.
    A leak is an unset/empty env (``default_receipt_log_path`` would fall back to
    the canonical live ledger) or an env that *resolves* to the canonical live
    ledger. Both sides are normalized with ``Path.resolve(strict=False)`` so a
    relative, ``..``, or symlink alias of the live ledger is still detected; a
    per-test path resolves away from the live ledger and is safe.
    """

    if not value:
        return (
            f"{MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV} was left unset/empty during "
            "the test; the resolver would fall back to the canonical live ledger "
            f"{DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH} — restore the per-test "
            "env (e.g. monkeypatch.setenv) before returning"
        )
    if Path(value).resolve(strict=False) == DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH.resolve(
        strict=False
    ):
        return (
            f"{MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV} was redirected to the canonical "
            f"live ledger {DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH} during the "
            "test; keep it bound to a per-test path"
        )
    return None
