"""Leak detector for the money-rail resource-receipt ledger env isolation.

Pure predicate consumed by the autouse per-test fixture teardown in
``tests/conftest.py`` and unit-proven in
``tests/support/test_ledger_env_guard.py``. It reports *why* a ledger env value
would expose the live production ledger or otherwise escape the per-test root the
isolation fixture owns, or ``None`` when the value is a safe per-test path.

``allowed_root`` MUST be the *already-resolved, immutable* per-test root that the
fixture captured at setup (``tmp_path.resolve()``). The predicate deliberately
does NOT re-resolve it: resolving the root at teardown would let a test body swap
the tmp root for a symlink so that both the env value and a late-resolved root
escape together and falsely pass. Only ``value`` is resolved here; it is compared
for *containment* within the immutable baseline.

Containment — not exact equality — is intentional: several tests legitimately
bind the env to a different within-root ledger filename (e.g. the support-copy
tests use ``money-rail-resource-receipts.jsonl``), so exact equality to one
expected filename would false-positive across the suite.

Ceiling: this is a post-hoc detector of end-of-test *state*, not a write-admission
guard. It cannot detect a deliberately temporary escape a test unsets and
restores within its body (the resolver reads the env at call time, so a
within-test window with the env removed is invisible once the value is put back),
nor an emission from a fixture finalizer that unwinds before this detector runs
(see ``tests/conftest.py`` for the exact teardown-ordering ceiling). It inspects
only the parent-process env value.
"""

from __future__ import annotations

from pathlib import Path

from agents.payment_processors.resource_receipts import (
    DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH,
    MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV,
)


def resource_receipt_env_leak_reason(value: str | None, *, allowed_root: Path) -> str | None:
    """Return why ``value`` would leak the live ledger or escape ``allowed_root``, else ``None``.

    ``value`` is the process value of
    ``HAPAX_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH`` observed at per-test teardown;
    ``allowed_root`` is the *immutable, already-resolved* per-test root the autouse
    isolation fixture captured at setup. A value is a leak when it is:

    * unset/empty — ``default_receipt_log_path`` would fall back to the canonical
      live ledger;
    * unresolvable (symlink loop, embedded NUL, other ``resolve`` error) — treated
      as unsafe rather than trusted, and reported with an actionable reason
      instead of raising;
    * resolved to the canonical live ledger — an explicit redirect at the
      production path; or
    * resolved *outside* ``allowed_root`` — any path the fixture does not own,
      including a *different* ``/dev/shm`` ledger or an inherited custom
      production path. Containment (not merely ``!= canonical``) is required so a
      noncanonical production path cannot pass.

    Only ``value`` is resolved (with ``Path.resolve(strict=False)``); a relative,
    ``..``-traversal, or symlink alias that escapes the immutable root — or that
    swaps the root itself — is therefore still detected. ``allowed_root`` is used
    verbatim (already resolved by the caller at setup), so the baseline cannot be
    moved by a mutation the test performs after setup.
    """

    if not value:
        return (
            f"{MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV} was left unset/empty during "
            "the test; the resolver would fall back to the canonical live ledger "
            f"{DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH} — restore the per-test "
            "env (e.g. monkeypatch.setenv) before returning"
        )
    try:
        resolved = Path(value).resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        return (
            f"{MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV} value {value!r} could not be "
            f"resolved at teardown ({exc!r}); treat an unresolvable ledger path as "
            "unsafe rather than trusting it — keep it bound to a resolvable per-test "
            "path"
        )
    try:
        canonical = DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        canonical = DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH
    if resolved == canonical:
        return (
            f"{MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV} was redirected to the canonical "
            f"live ledger {DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH} during the "
            "test; keep it bound to a per-test path"
        )
    if not resolved.is_relative_to(allowed_root):
        return (
            f"{MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV} resolved to {resolved}, outside "
            f"the per-test ledger root {allowed_root}, during the test; a value that "
            "is not the canonical live ledger can still be another /dev/shm ledger "
            "or an inherited production path — keep it bound within the per-test root"
        )
    return None
