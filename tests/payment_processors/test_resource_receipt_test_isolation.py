"""Hermetic regression for money-rail resource-receipt test isolation.

The root ``tests/conftest.py`` establishes a session-private receipt quarantine
before collection and a function-scoped autouse fixture that binds every test to
``tmp_path/resource-receipts.jsonl``. These tests prove the resulting isolation
properties without reading or depending on the production ``/dev/shm`` ledger:

* per-test resolver state — the call-time resolver points at the per-test path;
* default-path emission — a default (no explicit ``log_path``) emission lands in
  the per-test ledger;
* call-time late import — a module imported mid-test resolves the safe path;
* ordinary child process — a plain Python child inherits the safe path via the
  environment;
* non-live collection state — under a hostile inherited ledger env, a
  collection-time emission is redirected to the quarantine, never the inherited
  value;
* collection fail-closed — if a collection-time emission is silently dropped
  (a None ref), the child collection exits nonzero rather than reporting a false
  isolated success.

Task: cc-task-money-rails-resource-receipt-ledger-20260630.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from agents.payment_processors import resource_receipts
from agents.payment_processors.resource_receipts import MoneyRailReceiptOperation

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Collection-time probe (see ``test_collection_stays_off_inherited_live_ledger``).
# Guarded so it only fires inside the controlled hostile-inherited subprocess and
# never perturbs an ordinary test run.
_COLLECT_PROBE_FLAG = "_HAPAX_RECEIPT_ISOLATION_COLLECT_PROBE"
_COLLECT_PROBE_MARKER = "_HAPAX_RECEIPT_ISOLATION_COLLECT_MARKER"
# Fault injection for the child-side failure guarantee: when set, the probe emits
# to this explicit (deliberately unwritable) ledger so the append fails closed and
# the ref is None. Only ``test_collection_fails_closed_when_probe_receipt_drops``
# sets it; an ordinary run leaves it unset and emits at the resolved default.
_COLLECT_PROBE_FORCE_FAIL_PATH = "_HAPAX_RECEIPT_ISOLATION_COLLECT_FORCE_FAIL_PATH"

if os.environ.get(_COLLECT_PROBE_FLAG) == "1":  # pragma: no cover - subprocess only
    _probe_resolved = resource_receipts.default_receipt_log_path()
    _forced_fail_path = os.environ.get(_COLLECT_PROBE_FORCE_FAIL_PATH)
    _probe_ref = resource_receipts.record_external_api_poll_receipt(
        rail="lightning",
        endpoint="collection-probe",
        downstream_action="test.isolation.collection_probe",
        log_path=Path(_forced_fail_path) if _forced_fail_path else None,
    )
    # Child-side failure guarantee: a None ref means the emission was silently
    # dropped. Fail the collection loudly *before* writing the marker so
    # ``--collect-only`` exits nonzero instead of a dropped receipt masquerading
    # as isolated success. The marker is written only once this guarantee holds.
    assert _probe_ref is not None, (
        f"collection-time resource receipt emission returned no ref (resolved={_probe_resolved})"
    )
    _probe_marker = os.environ.get(_COLLECT_PROBE_MARKER)
    if _probe_marker:
        Path(_probe_marker).write_text(
            json.dumps({"resolved": str(_probe_resolved), "ref": _probe_ref}),
            encoding="utf-8",
        )


def test_resolver_binds_to_per_test_tmp_ledger(tmp_path: Path) -> None:
    resolved = resource_receipts.default_receipt_log_path()
    assert resolved == tmp_path / "resource-receipts.jsonl"
    # The resolver must not point at the live default constant.
    assert resolved != resource_receipts.DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH


def test_default_emission_lands_in_per_test_ledger(tmp_path: Path) -> None:
    expected = tmp_path / "resource-receipts.jsonl"
    ref = resource_receipts.record_external_api_poll_receipt(
        rail="lightning",
        endpoint="default-emit",
        downstream_action="test.isolation.default_emit",
    )
    assert ref is not None
    assert expected.exists()
    # A default read resolves the same per-test path an explicit read names.
    default_read = resource_receipts.tail_resource_receipts()
    assert [receipt.operation for receipt in default_read] == [
        MoneyRailReceiptOperation.EXTERNAL_API_POLL
    ]
    assert resource_receipts.tail_resource_receipts(log_path=expected) == default_read


def test_late_imported_module_resolves_per_test_ledger(tmp_path: Path, monkeypatch) -> None:
    expected = tmp_path / "resource-receipts.jsonl"
    helper = tmp_path / "hapax_late_receipt_probe.py"
    helper.write_text(
        textwrap.dedent(
            """
            from agents.payment_processors import resource_receipts

            RESOLVED = resource_receipts.default_receipt_log_path()
            REF = resource_receipts.record_external_api_poll_receipt(
                rail="lightning",
                endpoint="late-import",
                downstream_action="test.isolation.late_import",
            )
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    module_name = "hapax_late_receipt_probe"
    try:
        late_module = importlib.import_module(module_name)
        assert expected == late_module.RESOLVED
        assert late_module.REF is not None
        assert resource_receipts.tail_resource_receipts(log_path=expected)
    finally:
        sys.modules.pop(module_name, None)


def test_child_process_inherits_per_test_ledger(tmp_path: Path) -> None:
    expected = tmp_path / "resource-receipts.jsonl"
    # The autouse fixture set the env in os.environ; an ordinary child inherits it.
    script = textwrap.dedent(
        """
        from agents.payment_processors import resource_receipts

        ref = resource_receipts.record_external_api_poll_receipt(
            rail="lightning",
            endpoint="child",
            downstream_action="test.isolation.child",
        )
        assert ref is not None
        print(resource_receipts.default_receipt_log_path())
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(expected)
    receipts = resource_receipts.tail_resource_receipts(log_path=expected)
    assert [receipt.operation for receipt in receipts] == [
        MoneyRailReceiptOperation.EXTERNAL_API_POLL
    ]


def test_collection_stays_off_inherited_live_ledger(tmp_path: Path) -> None:
    """A hostile inherited ledger env is neutralized before collection.

    Runs ``pytest --collect-only`` in a child that inherits a hostile
    ``HAPAX_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH`` pointing at a sentinel. The
    root conftest's ``pytest_configure`` establishes the quarantine before this
    module is imported, so the collection-time probe emission resolves to the
    quarantine and the hostile sentinel is never created. The child exits zero,
    the probe commits a real (non-null) receipt into the quarantine, and the
    quarantine directory is removed by the child's fail-closed unconfigure.
    """

    sentinel = tmp_path / "hostile-inherited-ledger.jsonl"
    marker = tmp_path / "collection-probe-resolved.json"
    env = {
        **os.environ,
        "HAPAX_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH": str(sentinel),
        _COLLECT_PROBE_FLAG: "1",
        _COLLECT_PROBE_MARKER: str(marker),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            str(Path(__file__).resolve()),
        ],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    combined = result.stdout + result.stderr
    # Zero child exit: collection itself must succeed, so the child's fail-closed
    # unconfigure (strict quarantine removal) also completed without error.
    assert result.returncode == 0, combined
    # The collection-time probe ran and recorded its resolved ledger + ref.
    assert marker.exists(), combined
    probe = json.loads(marker.read_text(encoding="utf-8"))
    resolved = probe["resolved"]
    # Non-null probe receipt: the redirected emission committed a real receipt,
    # so this is genuine isolation of a live write, not a silently skipped one.
    assert probe["ref"], probe
    # Redirected to the session quarantine, never the hostile inherited sentinel.
    assert "hapax-resource-receipt-quarantine" in resolved, resolved
    assert resolved != str(sentinel), resolved
    # Strict sentinel absence: the hostile inherited ledger was never created.
    assert not sentinel.exists(), combined
    # Post-child quarantine removal: the child's unconfigure removed the whole
    # quarantine directory (its receipt landed there, and nothing lingers).
    assert not Path(resolved).parent.exists(), resolved


def test_collection_fails_closed_when_probe_receipt_drops(tmp_path: Path) -> None:
    """A dropped collection-time receipt makes the child collection exit nonzero.

    Forces the collection-time probe to emit at a guaranteed-unwritable ledger
    (a receipt path *beneath a regular file*, so the durable append's ``mkdir``
    raises ``OSError`` on Linux, macOS, and Windows alike), so
    ``record_external_api_poll_receipt`` fails closed and returns ``None``. The
    probe's ``assert _probe_ref is not None`` then fails during module import, so
    ``pytest --collect-only`` reports a collection error, exits nonzero, and the
    resolved-path marker is never written. This is the child-side guarantee that
    backs the parent-side ref assertion: a silently dropped receipt can never
    masquerade as isolated success.
    """

    marker = tmp_path / "collection-probe-resolved.json"
    # A receipt path beneath a regular file: mkdir of the parent fails with
    # OSError (NotADirectoryError) cross-platform, so the durable append fails
    # closed. Portable substitute for a /dev/null-style unwritable path.
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("not a directory\n", encoding="utf-8")
    unwritable = blocked_parent / "resource-receipts.jsonl"
    env = {
        **os.environ,
        _COLLECT_PROBE_FLAG: "1",
        _COLLECT_PROBE_MARKER: str(marker),
        _COLLECT_PROBE_FORCE_FAIL_PATH: str(unwritable),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            str(Path(__file__).resolve()),
        ],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    combined = result.stdout + result.stderr
    # Child-side failure guarantee: dropped receipt => nonzero collection exit.
    assert result.returncode != 0, combined
    # The marker is written only after the ref guarantee holds, so it is absent.
    assert not marker.exists(), combined
    # The failure is the probe's ref guarantee, not an unrelated crash.
    assert "returned no ref" in combined, combined
