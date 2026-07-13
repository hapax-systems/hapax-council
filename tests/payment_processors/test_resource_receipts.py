"""Tests for governed money-rail resource receipts."""

from __future__ import annotations

import fcntl
import logging
import os
import sqlite3
import time
from datetime import UTC, datetime
from multiprocessing import get_context
from pathlib import Path

import pytest

from agents.payment_processors import resource_receipts as resource_receipts_mod
from agents.payment_processors.resource_receipts import (
    MoneyRailReceiptOperation,
    MoneyRailResourceReceipt,
    MoneyRailResourceReceiptError,
    append_resource_receipt,
    build_resource_receipt,
    commit_prepared_resource_receipt,
    load_resource_receipt,
    receipt_reference,
    record_payment_event_resource_receipt,
    require_resource_receipt,
    resource_receipt_exists,
    resource_receipt_matches,
    resource_receipt_recovery_guidance,
    retract_prepared_resource_receipt,
    tail_resource_receipts,
)

_SQLITE_MAX_POSITIVE_INTEGER = 9_223_372_036_854_775_807


def _receipt(
    *,
    external_id: str = "delivery-1",
    raw_payload_sha256: str = "a" * 64,
    created_at: datetime = datetime(2026, 6, 30, 4, 0, tzinfo=UTC),
):
    return build_resource_receipt(
        rail="github-sponsors",
        operation=MoneyRailReceiptOperation.INGRESS,
        route_path="/api/payment-rails/github-sponsors",
        external_id=external_id,
        event_kind="created",
        raw_payload_sha256=raw_payload_sha256,
        downstream_action="publication_bus.publish_event",
        created_at=created_at,
    )


def _child_append_receipt(log_path: str, external_id: str) -> None:
    receipt = _receipt(
        external_id=external_id,
        raw_payload_sha256=f"{abs(hash(external_id)):064x}"[-64:],
    )
    if not append_resource_receipt(receipt, log_path=Path(log_path)):
        raise SystemExit(1)


def _child_commit_receipt(log_path: str, receipt_json: str) -> None:
    receipt = MoneyRailResourceReceipt.model_validate_json(receipt_json)
    if commit_prepared_resource_receipt(receipt, log_path=Path(log_path)) is None:
        raise SystemExit(1)


def _child_commit_receipt_after_marker(log_path: str, receipt_json: str, start_marker: str) -> None:
    _wait_for_marker(Path(start_marker))
    _child_commit_receipt(log_path, receipt_json)


def _child_expect_receipt_absent(log_path: str, ref: str) -> None:
    if resource_receipt_exists(ref, log_path=Path(log_path)):
        raise SystemExit(1)


def _child_commit_then_crash(log_path: str, receipt_json: str) -> None:
    receipt = MoneyRailResourceReceipt.model_validate_json(receipt_json)
    if commit_prepared_resource_receipt(receipt, log_path=Path(log_path)) is None:
        os._exit(2)
    os._exit(19)


def _child_duplicate_fail_after_success(
    log_path: str,
    receipt_json: str,
    committed_marker: str,
    success_marker: str,
) -> None:
    receipt = MoneyRailResourceReceipt.model_validate_json(receipt_json)
    if commit_prepared_resource_receipt(receipt, log_path=Path(log_path)) is None:
        raise SystemExit(1)
    Path(committed_marker).write_text("committed", encoding="utf-8")
    _wait_for_marker(Path(success_marker))
    if not retract_prepared_resource_receipt(receipt, log_path=Path(log_path)):
        raise SystemExit(1)


def _child_duplicate_success_after_failure_commit(
    log_path: str,
    receipt_json: str,
    committed_marker: str,
    success_marker: str,
) -> None:
    _wait_for_marker(Path(committed_marker))
    receipt = MoneyRailResourceReceipt.model_validate_json(receipt_json)
    if commit_prepared_resource_receipt(receipt, log_path=Path(log_path)) is None:
        raise SystemExit(1)
    Path(success_marker).write_text("success", encoding="utf-8")


def _wait_for_marker(path: Path) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise SystemExit(2)


def _index_metadata(log_path: Path) -> dict[str, str]:
    with sqlite3.connect(resource_receipts_mod._receipt_index_path(log_path)) as conn:
        return dict(conn.execute("SELECT key, value FROM metadata"))


def _sqlite_master_objects(log_path: Path) -> tuple[tuple[str, str, str], ...]:
    with sqlite3.connect(resource_receipts_mod._receipt_index_path(log_path)) as conn:
        return tuple(
            conn.execute(
                "SELECT type, name, tbl_name FROM sqlite_master "
                "WHERE name NOT GLOB 'sqlite_*' ORDER BY type, name, tbl_name"
            )
        )


def _indexed_locator(log_path: Path, receipt_id: str) -> tuple[int, int, str]:
    with sqlite3.connect(resource_receipts_mod._receipt_index_path(log_path)) as conn:
        row = conn.execute(
            "SELECT row_offset, row_length, raw_line_sha256 FROM receipts WHERE receipt_id = ?",
            (receipt_id,),
        ).fetchone()
    assert row is not None
    return row


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def _record_invalid_locator_pread(
    monkeypatch: pytest.MonkeyPatch,
    *,
    invalid_offset: int,
    invalid_length: int,
) -> list[tuple[int, int]]:
    invalid_calls: list[tuple[int, int]] = []
    real_pread = resource_receipts_mod.os.pread

    def _recording_pread(fd: int, length: int, offset: int) -> bytes:
        if offset == invalid_offset and length == invalid_length:
            invalid_calls.append((offset, length))
            raise OverflowError("byte string is too large")
        return real_pread(fd, length, offset)

    monkeypatch.setattr(resource_receipts_mod.os, "pread", _recording_pread)
    return invalid_calls


def _zero_receipts_table_root_page(log_path: Path) -> None:
    index_path = resource_receipts_mod._receipt_index_path(log_path)
    with sqlite3.connect(index_path) as conn:
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        row = conn.execute(
            "SELECT rootpage FROM sqlite_master WHERE type = 'table' AND name = 'receipts'"
        ).fetchone()
    assert row is not None
    root_page = row[0]
    assert root_page > 1
    with index_path.open("r+b") as fh:
        fh.seek((root_page - 1) * page_size)
        fh.write(b"\0" * page_size)
        fh.flush()
        os.fsync(fh.fileno())


class _TrackingConnection:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self.closed = False

    def __getattr__(self, name: str):
        return getattr(self._conn, name)

    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback):
        return self._conn.__exit__(exc_type, exc, traceback)

    def close(self) -> None:
        self.closed = True
        self._conn.close()


def test_default_receipt_log_path_resolves_env_at_call_time(tmp_path, monkeypatch) -> None:
    """The resolver reflects the env at call time; the constant is a pure fallback.

    Regression for the import-time capture bug: the module constant must be the
    fixed canonical /dev/shm path, not whatever the environment held at import,
    and ``default_receipt_log_path()`` must re-read the env on every call so an
    env transition (or an unset) takes effect immediately.
    """

    # The canonical fallback constant is the fixed /dev/shm path, not env-derived.
    canonical_fallback = Path("/dev/shm/hapax-monetization/resource-receipts.jsonl")
    assert canonical_fallback == resource_receipts_mod.DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH

    path_a = tmp_path / "ledger-a.jsonl"
    path_b = tmp_path / "ledger-b.jsonl"

    monkeypatch.setenv(resource_receipts_mod.MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV, str(path_a))
    assert resource_receipts_mod.default_receipt_log_path() == path_a

    # A later env transition is honored at call time — no import-time capture.
    monkeypatch.setenv(resource_receipts_mod.MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV, str(path_b))
    assert resource_receipts_mod.default_receipt_log_path() == path_b

    # With the env unset, the resolver falls back to the canonical constant.
    monkeypatch.delenv(resource_receipts_mod.MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV, raising=False)
    assert (
        resource_receipts_mod.default_receipt_log_path()
        == resource_receipts_mod.DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH
    )


def test_receipt_never_grants_spend_or_public_projection() -> None:
    receipt = _receipt()

    assert receipt.receive_only is True
    assert receipt.spend_authority_granted is False
    assert receipt.provider_spend_authorized is False
    assert receipt.public_projection_allowed is False
    assert receipt.no_perk_or_relationship_granted is True


def test_append_is_idempotent_by_receipt_id(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt()

    assert append_resource_receipt(receipt, log_path=log_path)
    assert append_resource_receipt(receipt, log_path=log_path)

    rows = tail_resource_receipts(log_path=log_path)
    assert len(rows) == 1
    assert rows[0].receipt_id == receipt.receipt_id


def test_append_reuses_duplicate_with_matching_stable_semantics(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    first = _receipt(
        external_id="delivery-stable",
        raw_payload_sha256="b" * 64,
        created_at=datetime(2026, 6, 30, 4, 0, tzinfo=UTC),
    )
    duplicate = _receipt(
        external_id="delivery-stable",
        raw_payload_sha256="b" * 64,
        created_at=datetime(2026, 6, 30, 4, 5, tzinfo=UTC),
    )

    assert first.receipt_id == duplicate.receipt_id
    assert append_resource_receipt(first, log_path=log_path)
    assert append_resource_receipt(duplicate, log_path=log_path)

    rows = tail_resource_receipts(log_path=log_path)
    assert len(rows) == 1
    assert rows[0].created_at == first.created_at


def test_append_refuses_duplicate_id_with_conflicting_semantics(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(external_id="delivery-conflict", raw_payload_sha256="c" * 64)
    conflicting = receipt.model_copy(update={"downstream_action": "other.action"})

    assert append_resource_receipt(receipt, log_path=log_path)
    assert not append_resource_receipt(conflicting, log_path=log_path)

    rows = tail_resource_receipts(log_path=log_path)
    assert len(rows) == 1
    assert rows[0].downstream_action == "publication_bus.publish_event"


def test_append_conflict_logs_quarantine_guidance(tmp_path, caplog) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(external_id="delivery-conflict-log", raw_payload_sha256="3" * 64)
    conflicting = receipt.model_copy(update={"downstream_action": "other.action"})
    caplog.set_level(logging.WARNING, logger=resource_receipts_mod.__name__)

    assert append_resource_receipt(receipt, log_path=log_path)
    assert not append_resource_receipt(conflicting, log_path=log_path)

    assert "repair or quarantine" in caplog.text
    assert str(log_path.with_name(f"{log_path.name}.lock")) in caplog.text
    assert "preserve valid committed receipts" in caplog.text


def test_recovery_guidance_names_quarantine_and_sidecar_lock(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    index_path = resource_receipts_mod._receipt_index_path(log_path)

    guidance = resource_receipt_recovery_guidance(log_path=log_path)

    assert str(log_path) in guidance
    assert str(index_path) in guidance
    for artifact in resource_receipts_mod._sqlite_artifact_paths(index_path):
        assert str(artifact) in guidance
    assert str(log_path.with_name(f"{log_path.name}.lock")) in guidance
    assert "preserve or copy the JSONL unchanged" in guidance
    assert "quarantine or rebuild only the derived index" in guidance
    assert "reserve ledger-row repair for independently proven ledger corruption" in guidance
    assert "repair or quarantine" in guidance
    assert "preserve valid committed receipts" in guidance


def test_append_completes_short_os_writes(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(external_id="delivery-short-write", raw_payload_sha256="d" * 64)
    real_write = resource_receipts_mod.os.write
    writes: list[int] = []

    def short_write(fd: int, data: object) -> int:
        view = memoryview(data)  # type: ignore[arg-type]
        chunk = view[: min(17, len(view))]
        writes.append(len(chunk))
        return real_write(fd, chunk)

    monkeypatch.setattr(resource_receipts_mod.os, "write", short_write)

    assert append_resource_receipt(receipt, log_path=log_path)
    assert len(writes) > 1
    rows = tail_resource_receipts(log_path=log_path)
    assert [row.receipt_id for row in rows] == [receipt.receipt_id]


def test_append_refuses_zero_progress_write(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(external_id="delivery-zero-write", raw_payload_sha256="e" * 64)

    monkeypatch.setattr(resource_receipts_mod.os, "write", lambda _fd, _data: 0)

    assert not append_resource_receipt(receipt, log_path=log_path)
    assert tail_resource_receipts(log_path=log_path) == []


def test_append_fails_closed_on_torn_final_line(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    existing = _receipt(external_id="delivery-before-torn", raw_payload_sha256="f" * 64)
    after_torn = _receipt(external_id="delivery-after-torn", raw_payload_sha256="1" * 64)
    log_path.write_text(
        existing.model_dump_json() + "\n" + '{"receipt_schema":1',
        encoding="utf-8",
    )

    assert not append_resource_receipt(after_torn, log_path=log_path)
    rows = tail_resource_receipts(log_path=log_path)
    assert [row.receipt_id for row in rows] == [existing.receipt_id]
    assert not resource_receipt_exists(receipt_reference(after_torn), log_path=log_path)


def test_append_fails_closed_on_torn_final_line_with_quarantine_guidance(tmp_path, caplog) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    existing = _receipt(external_id="delivery-before-torn-guidance", raw_payload_sha256="6" * 64)
    after_torn = _receipt(external_id="delivery-after-torn-guidance", raw_payload_sha256="7" * 64)
    log_path.write_text(
        existing.model_dump_json() + "\n" + '{"receipt_schema":1',
        encoding="utf-8",
    )
    caplog.set_level(logging.WARNING, logger=resource_receipts_mod.__name__)

    assert not append_resource_receipt(after_torn, log_path=log_path)

    assert "torn final money-rail resource receipt line" in caplog.text
    assert "repair or quarantine" in caplog.text
    assert "preserve valid committed receipts" in caplog.text


def test_admission_rejects_complete_json_without_commit_newline(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(external_id="delivery-complete-json-torn", raw_payload_sha256="9" * 64)
    ref = receipt_reference(receipt)
    log_path.write_text(receipt.model_dump_json(), encoding="utf-8")

    assert load_resource_receipt(ref, log_path=log_path) is None
    assert not resource_receipt_exists(ref, log_path=log_path)
    assert not resource_receipt_matches(
        ref,
        rail=receipt.rail,
        operation=receipt.operation,
        external_id="delivery-complete-json-torn",
        log_path=log_path,
    )


def test_admission_lookup_waits_for_lock_and_rejects_uncommitted_json_line(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    lock_path = log_path.with_name(f"{log_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    receipt = _receipt(external_id="delivery-locked-torn", raw_payload_sha256="a" * 64)
    ref = receipt_reference(receipt)
    log_path.write_text(receipt.model_dump_json(), encoding="utf-8")

    ctx = get_context("spawn")
    with lock_path.open("a", encoding="utf-8") as lock_fh:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        proc = ctx.Process(
            target=_child_expect_receipt_absent,
            args=(str(log_path), ref),
        )
        proc.start()
        try:
            proc.join(timeout=0.5)
            assert proc.is_alive()
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)

    proc.join(timeout=5)
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=5)
    assert proc.exitcode == 0


def test_append_waits_on_process_receipt_log_lock(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    lock_path = log_path.with_name(f"{log_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    ctx = get_context("spawn")
    with lock_path.open("a", encoding="utf-8") as lock_fh:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        proc = ctx.Process(
            target=_child_append_receipt,
            args=(str(log_path), "delivery-child"),
        )
        proc.start()
        try:
            proc.join(timeout=0.5)
            assert proc.is_alive()
            assert tail_resource_receipts(log_path=log_path) == []
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)

    proc.join(timeout=5)
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=5)
    assert proc.exitcode == 0
    rows = tail_resource_receipts(log_path=log_path)
    assert len(rows) == 1
    assert rows[0].external_id_sha256 is not None


def test_multi_process_distinct_receipts_survive_concurrent_appends(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    ctx = get_context("spawn")
    receipts = [
        _receipt(external_id=f"delivery-distinct-{idx}", raw_payload_sha256=f"{idx:064x}"[-64:])
        for idx in range(16)
    ]
    procs = [
        ctx.Process(target=_child_commit_receipt, args=(str(log_path), receipt.model_dump_json()))
        for receipt in receipts
    ]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(timeout=5)
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=5)
        assert proc.exitcode == 0

    assert {receipt.receipt_id for receipt in tail_resource_receipts(log_path=log_path)} == {
        receipt.receipt_id for receipt in receipts
    }


def test_multi_process_identical_receipts_reuse_one_row(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(external_id="delivery-identical", raw_payload_sha256="2" * 64)
    ctx = get_context("spawn")
    procs = [
        ctx.Process(target=_child_commit_receipt, args=(str(log_path), receipt.model_dump_json()))
        for _ in range(16)
    ]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(timeout=5)
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=5)
        assert proc.exitcode == 0

    rows = tail_resource_receipts(log_path=log_path)
    assert [row.receipt_id for row in rows] == [receipt.receipt_id]


def test_multi_process_conflicting_receipt_identity_fails_closed(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    start_marker = tmp_path / "start-conflict-race"
    receipt = _receipt(external_id="delivery-conflict-race", raw_payload_sha256="8" * 64)
    conflicting = receipt.model_copy(update={"downstream_action": "other.action"})
    assert receipt.receipt_id == conflicting.receipt_id
    assert resource_receipts_mod._stable_receipt_semantics(
        receipt
    ) != resource_receipts_mod._stable_receipt_semantics(conflicting)

    ctx = get_context("spawn")
    procs = [
        ctx.Process(
            target=_child_commit_receipt_after_marker,
            args=(
                str(log_path),
                (receipt if idx % 2 == 0 else conflicting).model_dump_json(),
                str(start_marker),
            ),
        )
        for idx in range(16)
    ]
    for proc in procs:
        proc.start()
    start_marker.write_text("go", encoding="utf-8")

    exitcodes: list[int] = []
    for proc in procs:
        proc.join(timeout=10)
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=5)
        assert proc.exitcode in {0, 1}
        exitcodes.append(proc.exitcode)

    assert exitcodes.count(0) == 8
    assert exitcodes.count(1) == 8
    rows = tail_resource_receipts(log_path=log_path)
    assert len(rows) == 1
    assert rows[0].receipt_id == receipt.receipt_id
    assert resource_receipts_mod._stable_receipt_semantics(rows[0]) in (
        resource_receipts_mod._stable_receipt_semantics(receipt),
        resource_receipts_mod._stable_receipt_semantics(conflicting),
    )


def test_retract_compat_hook_does_not_remove_committed_receipts(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    target = _receipt(external_id="delivery-target", raw_payload_sha256="1" * 64)
    unrelated = _receipt(external_id="delivery-other", raw_payload_sha256="2" * 64)
    assert append_resource_receipt(target, log_path=log_path)
    assert append_resource_receipt(unrelated, log_path=log_path)

    assert retract_prepared_resource_receipt(target, log_path=log_path)

    assert {receipt.receipt_id for receipt in tail_resource_receipts(log_path=log_path)} == {
        target.receipt_id,
        unrelated.receipt_id,
    }


def test_multi_process_duplicate_receipt_survives_failed_worker_retract(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    committed_marker = tmp_path / "failing-worker-committed"
    success_marker = tmp_path / "success-worker-committed"
    receipt = _receipt(external_id="delivery-shared", raw_payload_sha256="3" * 64)
    ctx = get_context("spawn")
    failing = ctx.Process(
        target=_child_duplicate_fail_after_success,
        args=(
            str(log_path),
            receipt.model_dump_json(),
            str(committed_marker),
            str(success_marker),
        ),
    )
    successful = ctx.Process(
        target=_child_duplicate_success_after_failure_commit,
        args=(
            str(log_path),
            receipt.model_dump_json(),
            str(committed_marker),
            str(success_marker),
        ),
    )

    failing.start()
    successful.start()
    for proc in (failing, successful):
        proc.join(timeout=5)
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=5)
        assert proc.exitcode == 0

    rows = tail_resource_receipts(log_path=log_path)
    assert [row.receipt_id for row in rows] == [receipt.receipt_id]


def test_multi_process_crash_after_commit_leaves_retryable_receipt(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(external_id="delivery-crash", raw_payload_sha256="4" * 64)
    ctx = get_context("spawn")
    proc = ctx.Process(
        target=_child_commit_then_crash,
        args=(str(log_path), receipt.model_dump_json()),
    )

    proc.start()
    proc.join(timeout=5)
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=5)
    assert proc.exitcode == 19

    assert [row.receipt_id for row in tail_resource_receipts(log_path=log_path)] == [
        receipt.receipt_id
    ]
    assert commit_prepared_resource_receipt(receipt, log_path=log_path) == receipt_reference(
        receipt
    )
    assert [row.receipt_id for row in tail_resource_receipts(log_path=log_path)] == [
        receipt.receipt_id
    ]


def test_require_resource_receipt_fails_closed_when_missing(tmp_path) -> None:
    receipt = _receipt()
    ref = receipt_reference(receipt)

    assert resource_receipt_exists(ref, log_path=tmp_path / "missing.jsonl") is False
    with pytest.raises(
        MoneyRailResourceReceiptError,
        match="missing money-rail resource receipt.*repair or quarantine",
    ):
        require_resource_receipt(ref, log_path=tmp_path / "missing.jsonl")


def test_payment_event_receipt_ref_is_idempotent_for_same_event(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"

    first = record_payment_event_resource_receipt(
        rail="lightning",
        external_id="invoice-1",
        event_kind="settled",
        downstream_action="lightning.poll_once",
        log_path=log_path,
    )
    second = record_payment_event_resource_receipt(
        rail="lightning",
        external_id="invoice-1",
        event_kind="settled",
        downstream_action="lightning.poll_once",
        log_path=log_path,
    )

    assert second == first
    rows = tail_resource_receipts(log_path=log_path)
    assert len(rows) == 1
    assert receipt_reference(rows[0]) == first


def test_resource_receipt_matches_rail_operation_and_external_id(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    ref = record_payment_event_resource_receipt(
        rail="liberapay",
        external_id="r-liberapay-001",
        event_kind="payin_succeeded",
        downstream_action="liberapay.poll_once",
        log_path=log_path,
    )

    assert ref is not None
    assert resource_receipt_matches(
        ref,
        rail="liberapay",
        operation=MoneyRailReceiptOperation.PAYMENT_EVENT_APPEND,
        external_id="r-liberapay-001",
        log_path=log_path,
    )
    assert not resource_receipt_matches(
        ref,
        rail="lightning",
        operation=MoneyRailReceiptOperation.PAYMENT_EVENT_APPEND,
        external_id="r-liberapay-001",
        log_path=log_path,
    )
    assert not resource_receipt_matches(
        ref,
        rail="liberapay",
        operation=MoneyRailReceiptOperation.PAYMENT_EVENT_APPEND,
        external_id="different-receipt",
        log_path=log_path,
    )


def test_resource_receipt_exists_scans_beyond_tail_window(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    first = build_resource_receipt(
        rail="github-sponsors",
        operation=MoneyRailReceiptOperation.INGRESS,
        route_path="/api/payment-rails/github-sponsors",
        external_id="delivery-0",
        event_kind="created",
        raw_payload_sha256="0" * 64,
        downstream_action="publication_bus.publish_event",
        created_at=datetime(2026, 6, 30, 4, 0, tzinfo=UTC),
    )

    for idx in range(250):
        receipt = build_resource_receipt(
            rail="github-sponsors",
            operation=MoneyRailReceiptOperation.INGRESS,
            route_path="/api/payment-rails/github-sponsors",
            external_id=f"delivery-{idx}",
            event_kind="created",
            raw_payload_sha256=f"{idx:064x}"[-64:],
            downstream_action="publication_bus.publish_event",
            created_at=datetime(2026, 6, 30, 4, 0, tzinfo=UTC),
        )
        assert append_resource_receipt(receipt, log_path=log_path)

    assert resource_receipt_exists(receipt_reference(first), log_path=log_path)


def test_steady_state_append_reconciles_only_from_verified_size(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    first = _receipt(external_id="delivery-index-1", raw_payload_sha256="1" * 64)
    second = _receipt(external_id="delivery-index-2", raw_payload_sha256="2" * 64)
    third = _receipt(external_id="delivery-index-3", raw_payload_sha256="3" * 64)
    assert append_resource_receipt(first, log_path=log_path)
    assert append_resource_receipt(second, log_path=log_path)
    verified_size = log_path.stat().st_size
    starts: list[int] = []
    real_iter = resource_receipts_mod._iter_ledger_receipt_rows

    def _recording_iter(target: Path, *, start_offset: int, fail_closed: bool):
        starts.append(start_offset)
        yield from real_iter(target, start_offset=start_offset, fail_closed=fail_closed)

    monkeypatch.setattr(resource_receipts_mod, "_iter_ledger_receipt_rows", _recording_iter)

    assert append_resource_receipt(third, log_path=log_path)

    assert starts == [verified_size]
    assert 0 not in starts
    assert int(_index_metadata(log_path)["line_count"]) == 3


def test_old_row_lookup_uses_index_locator_without_zero_offset_scan(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    first = _receipt(external_id="delivery-lookup-1", raw_payload_sha256="1" * 64)
    old = _receipt(external_id="delivery-lookup-2", raw_payload_sha256="2" * 64)
    latest = _receipt(external_id="delivery-lookup-3", raw_payload_sha256="3" * 64)
    for receipt in (first, old, latest):
        assert append_resource_receipt(receipt, log_path=log_path)
    old_offset, _old_length, _old_hash = _indexed_locator(log_path, old.receipt_id)
    assert old_offset > 0
    iter_starts: list[int] = []
    pread_offsets: list[int] = []
    real_iter = resource_receipts_mod._iter_ledger_receipt_rows
    real_read = resource_receipts_mod._read_exact_ledger_row

    def _recording_iter(target: Path, *, start_offset: int, fail_closed: bool):
        iter_starts.append(start_offset)
        yield from real_iter(target, start_offset=start_offset, fail_closed=fail_closed)

    def _recording_read(target: Path, *, row_offset: int, row_length: int) -> bytes:
        pread_offsets.append(row_offset)
        return real_read(target, row_offset=row_offset, row_length=row_length)

    monkeypatch.setattr(resource_receipts_mod, "_iter_ledger_receipt_rows", _recording_iter)
    monkeypatch.setattr(resource_receipts_mod, "_read_exact_ledger_row", _recording_read)

    assert load_resource_receipt(receipt_reference(old), log_path=log_path) == old

    assert iter_starts == []
    assert old_offset in pread_offsets
    assert 0 not in pread_offsets


def test_old_row_lookup_does_not_permission_chmod_or_fsync_private_files(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    first = _receipt(external_id="delivery-permission-lookup-1", raw_payload_sha256="1" * 64)
    old = _receipt(external_id="delivery-permission-lookup-2", raw_payload_sha256="2" * 64)
    latest = _receipt(external_id="delivery-permission-lookup-3", raw_payload_sha256="3" * 64)
    for receipt in (first, old, latest):
        assert append_resource_receipt(receipt, log_path=log_path)
    assert _mode(log_path) == 0o600
    assert _mode(resource_receipts_mod._receipt_index_path(log_path)) == 0o600
    chmod_calls: list[int] = []
    fsync_calls: list[int] = []
    real_fchmod = resource_receipts_mod.os.fchmod
    real_fsync = resource_receipts_mod.os.fsync

    def _recording_fchmod(fd: int, mode: int) -> None:
        chmod_calls.append(mode)
        real_fchmod(fd, mode)

    def _recording_fsync(fd: int) -> None:
        fsync_calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(resource_receipts_mod.os, "fchmod", _recording_fchmod)
    monkeypatch.setattr(resource_receipts_mod.os, "fsync", _recording_fsync)

    assert load_resource_receipt(receipt_reference(old), log_path=log_path) == old

    assert chmod_calls == []
    assert fsync_calls == []


def test_preexisting_world_readable_ledger_indexed_public_lookup_repairs_mode(
    tmp_path,
) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(external_id="delivery-world-readable-indexed", raw_payload_sha256="1" * 64)
    assert append_resource_receipt(receipt, log_path=log_path)
    os.chmod(log_path, 0o644)

    assert resource_receipt_exists(receipt_reference(receipt), log_path=log_path)
    assert load_resource_receipt(receipt_reference(receipt), log_path=log_path) == receipt

    assert _mode(log_path) == 0o600
    assert _mode(resource_receipts_mod._receipt_index_path(log_path)) == 0o600


def test_preexisting_world_readable_ledger_durable_append_repairs_mode_and_succeeds(
    tmp_path,
) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    first = _receipt(external_id="delivery-world-readable-append-1", raw_payload_sha256="1" * 64)
    second = _receipt(external_id="delivery-world-readable-append-2", raw_payload_sha256="2" * 64)
    log_path.write_bytes((first.model_dump_json() + "\n").encode())
    os.chmod(log_path, 0o644)

    resource_receipts_mod._append_line_durable(
        log_path,
        (second.model_dump_json() + "\n").encode(),
    )

    assert _mode(log_path) == 0o600
    assert [row.receipt_id for row in tail_resource_receipts(log_path=log_path)] == [
        first.receipt_id,
        second.receipt_id,
    ]


def test_preexisting_world_readable_ledger_tail_stream_repairs_mode_and_loads(
    tmp_path,
) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipts = [
        _receipt(
            external_id=f"delivery-world-readable-tail-{idx}", raw_payload_sha256=f"{idx:064x}"
        )
        for idx in range(2)
    ]
    log_path.write_bytes(
        b"".join((receipt.model_dump_json() + "\n").encode() for receipt in receipts)
    )
    os.chmod(log_path, 0o644)

    assert [row.receipt_id for row in tail_resource_receipts(log_path=log_path)] == [
        receipt.receipt_id for receipt in receipts
    ]
    assert _mode(log_path) == 0o600


def test_missing_index_bootstraps_by_streaming_authoritative_jsonl(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipts = [
        _receipt(external_id=f"delivery-bootstrap-{idx}", raw_payload_sha256=f"{idx:064x}"[-64:])
        for idx in range(12)
    ]
    log_path.write_bytes(b"".join((r.model_dump_json() + "\n").encode() for r in receipts))
    starts: list[int] = []
    real_iter = resource_receipts_mod._iter_ledger_receipt_rows

    def _recording_iter(target: Path, *, start_offset: int, fail_closed: bool):
        starts.append(start_offset)
        yield from real_iter(target, start_offset=start_offset, fail_closed=fail_closed)

    monkeypatch.setattr(resource_receipts_mod, "_iter_ledger_receipt_rows", _recording_iter)

    assert load_resource_receipt(receipt_reference(receipts[-1]), log_path=log_path) == receipts[-1]

    metadata = _index_metadata(log_path)
    assert starts == [0]
    assert int(metadata["verified_size"]) == log_path.stat().st_size
    assert int(metadata["line_count"]) == len(receipts)


def test_valid_external_tail_is_indexed_from_verified_size(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    first = _receipt(external_id="delivery-external-before", raw_payload_sha256="1" * 64)
    external = _receipt(external_id="delivery-external-tail", raw_payload_sha256="2" * 64)
    assert append_resource_receipt(first, log_path=log_path)
    verified_size = log_path.stat().st_size
    resource_receipts_mod._append_line_durable(
        log_path,
        (external.model_dump_json() + "\n").encode(),
    )
    starts: list[int] = []
    real_iter = resource_receipts_mod._iter_ledger_receipt_rows

    def _recording_iter(target: Path, *, start_offset: int, fail_closed: bool):
        starts.append(start_offset)
        yield from real_iter(target, start_offset=start_offset, fail_closed=fail_closed)

    monkeypatch.setattr(resource_receipts_mod, "_iter_ledger_receipt_rows", _recording_iter)

    assert load_resource_receipt(receipt_reference(external), log_path=log_path) == external

    assert starts == [verified_size]
    assert int(_index_metadata(log_path)["line_count"]) == 2


def test_failure_after_log_fsync_before_index_commit_recovers_on_retry(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(external_id="delivery-index-crash", raw_payload_sha256="4" * 64)
    calls = 0
    real_reconcile = resource_receipts_mod._reconcile_receipt_index

    def _fail_second_reconcile(conn, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise MoneyRailResourceReceiptError("simulated index commit failure")
        return real_reconcile(conn, target)

    monkeypatch.setattr(resource_receipts_mod, "_reconcile_receipt_index", _fail_second_reconcile)

    assert not append_resource_receipt(receipt, log_path=log_path)
    assert [row.receipt_id for row in tail_resource_receipts(log_path=log_path)] == [
        receipt.receipt_id
    ]

    monkeypatch.setattr(resource_receipts_mod, "_reconcile_receipt_index", real_reconcile)

    assert append_resource_receipt(receipt, log_path=log_path)
    assert [row.receipt_id for row in tail_resource_receipts(log_path=log_path)] == [
        receipt.receipt_id
    ]
    assert load_resource_receipt(receipt_reference(receipt), log_path=log_path) == receipt


def test_index_tail_reconcile_fails_closed_on_torn_tail(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    first = _receipt(external_id="delivery-torn-index-before", raw_payload_sha256="1" * 64)
    after = _receipt(external_id="delivery-torn-index-after", raw_payload_sha256="2" * 64)
    assert append_resource_receipt(first, log_path=log_path)
    with log_path.open("ab") as fh:
        fh.write(b'{"receipt_schema":1')

    assert not append_resource_receipt(after, log_path=log_path)
    assert load_resource_receipt(receipt_reference(after), log_path=log_path) is None


def test_index_tail_reconcile_fails_closed_on_conflicting_tail(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(external_id="delivery-conflicting-tail", raw_payload_sha256="1" * 64)
    conflicting = receipt.model_copy(update={"downstream_action": "other.action"})
    unrelated = _receipt(external_id="delivery-conflicting-tail-after", raw_payload_sha256="2" * 64)
    assert append_resource_receipt(receipt, log_path=log_path)
    resource_receipts_mod._append_line_durable(
        log_path,
        (conflicting.model_dump_json() + "\n").encode(),
    )

    assert not append_resource_receipt(unrelated, log_path=log_path)
    assert load_resource_receipt(receipt_reference(unrelated), log_path=log_path) is None


def test_index_tail_reconcile_accepts_identical_tail_without_new_locator(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(external_id="delivery-identical-tail", raw_payload_sha256="1" * 64)
    unrelated = _receipt(external_id="delivery-identical-tail-after", raw_payload_sha256="2" * 64)
    assert append_resource_receipt(receipt, log_path=log_path)
    first_offset, _first_length, _first_hash = _indexed_locator(log_path, receipt.receipt_id)
    resource_receipts_mod._append_line_durable(
        log_path,
        (receipt.model_dump_json() + "\n").encode(),
    )

    assert append_resource_receipt(unrelated, log_path=log_path)

    assert _indexed_locator(log_path, receipt.receipt_id)[0] == first_offset
    assert int(_index_metadata(log_path)["line_count"]) == 3


def test_index_fails_closed_on_truncated_ledger(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    first = _receipt(external_id="delivery-truncate-before", raw_payload_sha256="1" * 64)
    after = _receipt(external_id="delivery-truncate-after", raw_payload_sha256="2" * 64)
    assert append_resource_receipt(first, log_path=log_path)
    with log_path.open("r+b") as fh:
        fh.truncate(log_path.stat().st_size - 1)

    assert not append_resource_receipt(after, log_path=log_path)
    assert load_resource_receipt(receipt_reference(first), log_path=log_path) is None


def test_corrupt_index_is_replaced_by_full_stream_validation(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    first = _receipt(external_id="delivery-corrupt-index-1", raw_payload_sha256="1" * 64)
    second = _receipt(external_id="delivery-corrupt-index-2", raw_payload_sha256="2" * 64)
    assert append_resource_receipt(first, log_path=log_path)
    assert append_resource_receipt(second, log_path=log_path)
    resource_receipts_mod._receipt_index_path(log_path).write_bytes(b"not sqlite")

    assert load_resource_receipt(receipt_reference(first), log_path=log_path) == first

    metadata = _index_metadata(log_path)
    assert int(metadata["verified_size"]) == log_path.stat().st_size
    assert int(metadata["line_count"]) == 2


def test_lookup_fails_closed_on_stale_locator(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    first = _receipt(external_id="delivery-stale-locator-1", raw_payload_sha256="1" * 64)
    second = _receipt(external_id="delivery-stale-locator-2", raw_payload_sha256="2" * 64)
    assert append_resource_receipt(first, log_path=log_path)
    assert append_resource_receipt(second, log_path=log_path)
    second_offset, second_length, second_hash = _indexed_locator(log_path, second.receipt_id)
    with sqlite3.connect(resource_receipts_mod._receipt_index_path(log_path)) as conn:
        conn.execute(
            "UPDATE receipts SET row_offset = ?, row_length = ?, raw_line_sha256 = ? "
            "WHERE receipt_id = ?",
            (second_offset, second_length, second_hash, first.receipt_id),
        )

    assert load_resource_receipt(receipt_reference(first), log_path=log_path) is None


@pytest.mark.parametrize(
    "locator_case",
    ("huge_row_length", "huge_row_offset", "length_beyond_eof"),
)
def test_lookup_fails_closed_on_out_of_bounds_index_locator_without_invalid_pread(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    locator_case: str,
) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(
        external_id=f"delivery-out-of-bounds-{locator_case}",
        raw_payload_sha256="1" * 64,
    )
    assert append_resource_receipt(receipt, log_path=log_path)
    row_offset, row_length, _row_hash = _indexed_locator(log_path, receipt.receipt_id)

    if locator_case == "huge_row_length":
        invalid_offset = row_offset
        invalid_length = _SQLITE_MAX_POSITIVE_INTEGER
        update_sql = "UPDATE receipts SET row_length = ? WHERE receipt_id = ?"
        update_values = (invalid_length, receipt.receipt_id)
    elif locator_case == "huge_row_offset":
        invalid_offset = _SQLITE_MAX_POSITIVE_INTEGER
        invalid_length = row_length
        update_sql = "UPDATE receipts SET row_offset = ? WHERE receipt_id = ?"
        update_values = (invalid_offset, receipt.receipt_id)
    else:
        invalid_offset = row_offset
        invalid_length = log_path.stat().st_size - row_offset + 1
        update_sql = "UPDATE receipts SET row_length = ? WHERE receipt_id = ?"
        update_values = (invalid_length, receipt.receipt_id)

    with sqlite3.connect(resource_receipts_mod._receipt_index_path(log_path)) as conn:
        conn.execute(update_sql, update_values)
    invalid_pread_calls = _record_invalid_locator_pread(
        monkeypatch,
        invalid_offset=invalid_offset,
        invalid_length=invalid_length,
    )

    assert load_resource_receipt(receipt_reference(receipt), log_path=log_path) is None
    assert invalid_pread_calls == []


def test_append_lookup_refuses_out_of_bounds_locator_without_duplicate_append(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(
        external_id="delivery-append-out-of-bounds-locator",
        raw_payload_sha256="1" * 64,
    )
    assert append_resource_receipt(receipt, log_path=log_path)
    before = log_path.read_bytes()
    row_offset, _row_length, _row_hash = _indexed_locator(log_path, receipt.receipt_id)
    invalid_length = _SQLITE_MAX_POSITIVE_INTEGER
    with sqlite3.connect(resource_receipts_mod._receipt_index_path(log_path)) as conn:
        conn.execute(
            "UPDATE receipts SET row_length = ? WHERE receipt_id = ?",
            (invalid_length, receipt.receipt_id),
        )
    invalid_pread_calls = _record_invalid_locator_pread(
        monkeypatch,
        invalid_offset=row_offset,
        invalid_length=invalid_length,
    )

    assert not append_resource_receipt(receipt, log_path=log_path)
    assert invalid_pread_calls == []
    assert log_path.read_bytes() == before
    assert [row.receipt_id for row in tail_resource_receipts(log_path=log_path)] == [
        receipt.receipt_id
    ]


def test_lookup_fails_closed_on_raw_hash_mismatch(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(external_id="delivery-raw-hash-mismatch", raw_payload_sha256="1" * 64)
    assert append_resource_receipt(receipt, log_path=log_path)
    with sqlite3.connect(resource_receipts_mod._receipt_index_path(log_path)) as conn:
        conn.execute(
            "UPDATE receipts SET raw_line_sha256 = ? WHERE receipt_id = ?",
            ("0" * 64, receipt.receipt_id),
        )

    assert load_resource_receipt(receipt_reference(receipt), log_path=log_path) is None


def test_receipt_index_sidecar_is_private_under_permissive_umask(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(external_id="delivery-private-index", raw_payload_sha256="1" * 64)
    original_umask = os.umask(0o022)
    try:
        assert append_resource_receipt(receipt, log_path=log_path)
    finally:
        os.umask(original_umask)
    index_path = resource_receipts_mod._receipt_index_path(log_path)

    assert _mode(log_path) == 0o600
    assert _mode(index_path) == 0o600

    index_path.write_bytes(b"not sqlite")
    os.chmod(index_path, 0o644)

    assert load_resource_receipt(receipt_reference(receipt), log_path=log_path) == receipt
    assert _mode(index_path) == 0o600


def test_corrupt_index_rebuild_neutralizes_stale_rollback_journal(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    first = _receipt(external_id="delivery-stale-journal-1", raw_payload_sha256="1" * 64)
    second = _receipt(external_id="delivery-stale-journal-2", raw_payload_sha256="2" * 64)
    log_path.write_bytes(
        b"".join((receipt.model_dump_json() + "\n").encode() for receipt in (first, second))
    )
    index_path = resource_receipts_mod._receipt_index_path(log_path)
    index_path.write_bytes(b"not sqlite")
    journal_path = index_path.with_name(f"{index_path.name}-journal")
    journal_path.write_bytes(b"stale rollback journal from old derived index")

    assert load_resource_receipt(receipt_reference(second), log_path=log_path) == second

    assert not journal_path.exists()
    assert _mode(index_path) == 0o600
    assert load_resource_receipt(receipt_reference(first), log_path=log_path) == first
    assert _index_metadata(log_path)["final_row_sha256"]


def test_receipt_index_replacement_durably_removes_stale_artifacts_before_replace(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index_path = tmp_path / "resource-receipts.jsonl.index.sqlite3"
    tmp_index_path = tmp_path / ".resource-receipts.jsonl.index.sqlite3.tmp-test"
    tmp_index_path.write_bytes(b"replacement")
    artifacts = set(resource_receipts_mod._sqlite_artifact_paths(index_path))
    for artifact in artifacts:
        artifact.write_bytes(b"stale")
    calls: list[str] = []
    real_unlink = Path.unlink
    real_replace = resource_receipts_mod.os.replace

    def _recording_unlink(self: Path) -> None:
        if self in artifacts:
            calls.append(f"delete:{self.name}")
        real_unlink(self)

    def _recording_fsync(path: Path) -> None:
        calls.append(f"fsync:{path}")

    def _recording_replace(src: Path, dst: Path) -> None:
        calls.append(f"replace:{src}->{dst}")
        real_replace(src, dst)

    monkeypatch.setattr(Path, "unlink", _recording_unlink)
    monkeypatch.setattr(resource_receipts_mod, "_fsync_directory", _recording_fsync)
    monkeypatch.setattr(resource_receipts_mod.os, "replace", _recording_replace)

    resource_receipts_mod._install_receipt_index_replacement(tmp_index_path, index_path)

    assert calls == [
        f"delete:{index_path.name}-journal",
        f"delete:{index_path.name}-wal",
        f"delete:{index_path.name}-shm",
        f"fsync:{tmp_path}",
        f"replace:{tmp_index_path}->{index_path}",
        f"fsync:{tmp_path}",
    ]
    assert index_path.read_bytes() == b"replacement"
    assert _mode(index_path) == 0o600
    assert all(not artifact.exists() for artifact in artifacts)


def test_receipts_table_root_page_corruption_rebuilds_once_on_lookup(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(external_id="delivery-root-page-corrupt", raw_payload_sha256="1" * 64)
    assert append_resource_receipt(receipt, log_path=log_path)
    _zero_receipts_table_root_page(log_path)
    index_path = resource_receipts_mod._receipt_index_path(log_path)
    with sqlite3.connect(index_path) as conn:
        assert tuple(conn.execute("PRAGMA table_info(receipts)")) == (
            resource_receipts_mod._EXPECTED_RECEIPTS_TABLE_INFO
        )
        assert dict(conn.execute("SELECT key, value FROM metadata"))["line_count"] == "1"
        with pytest.raises(sqlite3.DatabaseError, match="malformed"):
            conn.execute(
                "SELECT row_offset FROM receipts WHERE receipt_id = ?",
                (receipt.receipt_id,),
            ).fetchone()
    starts: list[int] = []
    replacement_targets: list[Path] = []
    real_iter = resource_receipts_mod._iter_ledger_receipt_rows
    real_replace = resource_receipts_mod._replace_receipt_index_from_ledger

    def _recording_iter(target: Path, *, start_offset: int, fail_closed: bool):
        starts.append(start_offset)
        yield from real_iter(target, start_offset=start_offset, fail_closed=fail_closed)

    def _recording_replace(target: Path) -> None:
        replacement_targets.append(target)
        real_replace(target)

    monkeypatch.setattr(resource_receipts_mod, "_iter_ledger_receipt_rows", _recording_iter)
    monkeypatch.setattr(
        resource_receipts_mod, "_replace_receipt_index_from_ledger", _recording_replace
    )

    assert load_resource_receipt(receipt_reference(receipt), log_path=log_path) == receipt
    assert replacement_targets == [log_path]
    assert starts == [0]

    assert load_resource_receipt(receipt_reference(receipt), log_path=log_path) == receipt
    assert replacement_targets == [log_path]
    assert starts == [0]


@pytest.mark.parametrize("failure_point", ("connect", "reconcile", "query"))
def test_persistent_second_attempt_index_failure_fails_closed_with_one_rebuild(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(
        external_id=f"delivery-persistent-{failure_point}", raw_payload_sha256="1" * 64
    )
    assert append_resource_receipt(receipt, log_path=log_path)
    _zero_receipts_table_root_page(log_path)
    expected_index_path = resource_receipts_mod._receipt_index_path(log_path)
    replacement_targets: list[Path] = []
    tracked_connections: list[_TrackingConnection] = []
    real_replace = resource_receipts_mod._replace_receipt_index_from_ledger
    real_connect = resource_receipts_mod._connect_receipt_index
    real_reconcile = resource_receipts_mod._reconcile_receipt_index

    def _recording_replace(target: Path) -> None:
        replacement_targets.append(target)
        real_replace(target)
        if failure_point == "query":
            _zero_receipts_table_root_page(target)

    def _tracking_connect(index_path: Path):
        if failure_point == "connect" and replacement_targets and index_path == expected_index_path:
            raise sqlite3.DatabaseError("persistent connect corruption")
        conn = _TrackingConnection(real_connect(index_path))
        tracked_connections.append(conn)
        return conn

    def _maybe_failing_reconcile(conn, target: Path) -> None:
        if failure_point == "reconcile" and replacement_targets and target == log_path:
            raise sqlite3.DatabaseError("persistent reconcile corruption")
        real_reconcile(conn, target)

    monkeypatch.setattr(
        resource_receipts_mod, "_replace_receipt_index_from_ledger", _recording_replace
    )
    monkeypatch.setattr(resource_receipts_mod, "_connect_receipt_index", _tracking_connect)
    monkeypatch.setattr(resource_receipts_mod, "_reconcile_receipt_index", _maybe_failing_reconcile)

    assert load_resource_receipt(receipt_reference(receipt), log_path=log_path) is None

    assert replacement_targets == [log_path]
    assert tracked_connections
    assert all(conn.closed for conn in tracked_connections)


def test_sqlite_interface_error_fails_closed_without_rebuild_and_closes(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(external_id="delivery-interface-error", raw_payload_sha256="1" * 64)
    assert append_resource_receipt(receipt, log_path=log_path)
    tracked_connections: list[_TrackingConnection] = []
    replacement_targets: list[Path] = []
    real_connect = resource_receipts_mod._connect_receipt_index

    def _tracking_connect(index_path: Path):
        conn = _TrackingConnection(real_connect(index_path))
        tracked_connections.append(conn)
        return conn

    def _interface_error_reconcile(conn, target: Path) -> None:
        raise sqlite3.InterfaceError("simulated sqlite interface fault")

    def _recording_replace(target: Path) -> None:
        replacement_targets.append(target)

    monkeypatch.setattr(resource_receipts_mod, "_connect_receipt_index", _tracking_connect)
    monkeypatch.setattr(
        resource_receipts_mod, "_reconcile_receipt_index", _interface_error_reconcile
    )
    monkeypatch.setattr(
        resource_receipts_mod, "_replace_receipt_index_from_ledger", _recording_replace
    )

    assert load_resource_receipt(receipt_reference(receipt), log_path=log_path) is None

    assert replacement_targets == []
    assert tracked_connections
    assert all(conn.closed for conn in tracked_connections)


def test_append_post_jsonl_interface_error_is_retryable_without_rebuild(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    existing = _receipt(
        external_id="delivery-append-interface-before",
        raw_payload_sha256="1" * 64,
    )
    appended = _receipt(
        external_id="delivery-append-interface-after",
        raw_payload_sha256="2" * 64,
    )
    assert append_resource_receipt(existing, log_path=log_path)
    tracked_connections: list[_TrackingConnection] = []
    replacement_targets: list[Path] = []
    real_connect = resource_receipts_mod._connect_receipt_index
    real_reconcile = resource_receipts_mod._reconcile_receipt_index

    def _tracking_connect(index_path: Path):
        conn = _TrackingConnection(real_connect(index_path))
        tracked_connections.append(conn)
        return conn

    def _post_jsonl_interface_error_reconcile(conn, target: Path) -> None:
        metadata = dict(conn.execute("SELECT key, value FROM metadata"))
        if target == log_path and target.stat().st_size > int(metadata["verified_size"]):
            raise sqlite3.InterfaceError("simulated post-jsonl reconcile interface fault")
        real_reconcile(conn, target)

    def _recording_replace(target: Path) -> None:
        replacement_targets.append(target)

    monkeypatch.setattr(resource_receipts_mod, "_connect_receipt_index", _tracking_connect)
    monkeypatch.setattr(
        resource_receipts_mod,
        "_reconcile_receipt_index",
        _post_jsonl_interface_error_reconcile,
    )
    monkeypatch.setattr(
        resource_receipts_mod, "_replace_receipt_index_from_ledger", _recording_replace
    )

    assert not append_resource_receipt(appended, log_path=log_path)

    assert replacement_targets == []
    assert tracked_connections
    assert all(conn.closed for conn in tracked_connections)
    assert int(_index_metadata(log_path)["line_count"]) == 1
    assert [row.receipt_id for row in tail_resource_receipts(log_path=log_path)] == [
        existing.receipt_id,
        appended.receipt_id,
    ]

    monkeypatch.setattr(resource_receipts_mod, "_reconcile_receipt_index", real_reconcile)
    monkeypatch.setattr(resource_receipts_mod, "_connect_receipt_index", real_connect)

    assert append_resource_receipt(appended, log_path=log_path)
    assert int(_index_metadata(log_path)["line_count"]) == 2
    assert load_resource_receipt(receipt_reference(appended), log_path=log_path) == appended


def test_replacement_sqlite_interface_error_fails_closed_at_public_boundary(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(
        external_id="delivery-replacement-interface-error",
        raw_payload_sha256="1" * 64,
    )
    log_path.write_bytes((receipt.model_dump_json() + "\n").encode())

    def _interface_error_replace(target: Path) -> None:
        raise sqlite3.InterfaceError("simulated replacement interface fault")

    monkeypatch.setattr(
        resource_receipts_mod,
        "_replace_receipt_index_from_ledger",
        _interface_error_replace,
    )

    assert load_resource_receipt(receipt_reference(receipt), log_path=log_path) is None


def test_persistent_sqliteevil_trigger_rebuilds_before_append_result_can_succeed(
    tmp_path,
) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    existing = _receipt(external_id="delivery-trigger-before", raw_payload_sha256="1" * 64)
    appended = _receipt(external_id="delivery-trigger-after", raw_payload_sha256="2" * 64)
    assert append_resource_receipt(existing, log_path=log_path)
    with sqlite3.connect(resource_receipts_mod._receipt_index_path(log_path)) as conn:
        conn.executescript(
            """
            CREATE TRIGGER sqliteEvil
            AFTER INSERT ON receipts
            BEGIN
                DELETE FROM receipts WHERE receipt_id = NEW.receipt_id;
            END;
            """
        )
    assert any(obj[0] == "trigger" for obj in _sqlite_master_objects(log_path))

    assert append_resource_receipt(appended, log_path=log_path)

    assert load_resource_receipt(receipt_reference(appended), log_path=log_path) == appended
    assert [row.receipt_id for row in tail_resource_receipts(log_path=log_path)] == [
        existing.receipt_id,
        appended.receipt_id,
    ]
    assert _sqlite_master_objects(log_path) == resource_receipts_mod._EXPECTED_SQLITE_MASTER_OBJECTS


def test_unexpected_index_view_rebuilds_from_authoritative_jsonl(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(external_id="delivery-extra-view", raw_payload_sha256="1" * 64)
    assert append_resource_receipt(receipt, log_path=log_path)
    with sqlite3.connect(resource_receipts_mod._receipt_index_path(log_path)) as conn:
        conn.execute("CREATE VIEW receipt_ids AS SELECT receipt_id FROM receipts")
    assert any(obj[0] == "view" for obj in _sqlite_master_objects(log_path))

    assert load_resource_receipt(receipt_reference(receipt), log_path=log_path) == receipt

    assert _sqlite_master_objects(log_path) == resource_receipts_mod._EXPECTED_SQLITE_MASTER_OBJECTS


def test_append_lookup_recovers_receipts_table_root_page_corruption(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(external_id="delivery-append-root-corrupt", raw_payload_sha256="1" * 64)
    assert append_resource_receipt(receipt, log_path=log_path)
    _zero_receipts_table_root_page(log_path)
    starts: list[int] = []
    real_iter = resource_receipts_mod._iter_ledger_receipt_rows

    def _recording_iter(target: Path, *, start_offset: int, fail_closed: bool):
        starts.append(start_offset)
        yield from real_iter(target, start_offset=start_offset, fail_closed=fail_closed)

    monkeypatch.setattr(resource_receipts_mod, "_iter_ledger_receipt_rows", _recording_iter)

    assert append_resource_receipt(receipt, log_path=log_path)

    assert starts == [0]
    assert [row.receipt_id for row in tail_resource_receipts(log_path=log_path)] == [
        receipt.receipt_id
    ]


def test_append_nested_index_recovery_budget_allows_only_one_replacement(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    existing = _receipt(external_id="delivery-append-budget-existing", raw_payload_sha256="1" * 64)
    appended = _receipt(external_id="delivery-append-budget-new", raw_payload_sha256="2" * 64)
    assert append_resource_receipt(existing, log_path=log_path)
    _zero_receipts_table_root_page(log_path)
    replacement_targets: list[Path] = []
    reconcile_calls = 0
    real_replace = resource_receipts_mod._replace_receipt_index_from_ledger
    real_reconcile = resource_receipts_mod._reconcile_receipt_index

    def _recording_replace(target: Path) -> None:
        replacement_targets.append(target)
        real_replace(target)

    def _fail_post_append_reconcile(conn, target: Path) -> None:
        nonlocal reconcile_calls
        reconcile_calls += 1
        if target == log_path and reconcile_calls == 3:
            raise sqlite3.DatabaseError("persistent post-append reconcile corruption")
        real_reconcile(conn, target)

    monkeypatch.setattr(
        resource_receipts_mod, "_replace_receipt_index_from_ledger", _recording_replace
    )
    monkeypatch.setattr(
        resource_receipts_mod, "_reconcile_receipt_index", _fail_post_append_reconcile
    )

    assert not append_resource_receipt(appended, log_path=log_path)

    assert replacement_targets == [log_path]
    assert [row.receipt_id for row in tail_resource_receipts(log_path=log_path)] == [
        existing.receipt_id,
        appended.receipt_id,
    ]


def test_same_column_weak_receipts_and_metadata_schema_rebuilds(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(external_id="delivery-weak-schema", raw_payload_sha256="1" * 64)
    log_path.write_bytes((receipt.model_dump_json() + "\n").encode())
    index_path = resource_receipts_mod._receipt_index_path(log_path)
    with sqlite3.connect(index_path) as conn:
        conn.executescript(
            """
            CREATE TABLE receipts (
                receipt_id TEXT,
                row_offset TEXT,
                row_length INTEGER,
                rail TEXT,
                raw_line_sha256 TEXT,
                stable_semantics_sha256 TEXT
            );
            CREATE TABLE metadata (
                key TEXT,
                value TEXT
            );
            INSERT INTO metadata(key, value) VALUES ('schema_version', '1');
            """
        )

    assert load_resource_receipt(receipt_reference(receipt), log_path=log_path) == receipt

    with sqlite3.connect(index_path) as conn:
        assert tuple(conn.execute("PRAGMA table_info(receipts)")) == (
            resource_receipts_mod._EXPECTED_RECEIPTS_TABLE_INFO
        )
        assert tuple(conn.execute("PRAGMA table_info(metadata)")) == (
            resource_receipts_mod._EXPECTED_METADATA_TABLE_INFO
        )


def test_malformed_index_row_fails_closed_without_type_error(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    receipt = _receipt(external_id="delivery-malformed-index-row", raw_payload_sha256="1" * 64)
    assert append_resource_receipt(receipt, log_path=log_path)
    with sqlite3.connect(resource_receipts_mod._receipt_index_path(log_path)) as conn:
        conn.execute("PRAGMA ignore_check_constraints=ON")
        conn.execute(
            "UPDATE receipts SET row_offset = ? WHERE receipt_id = ?",
            ("not-an-integer", receipt.receipt_id),
        )

    assert load_resource_receipt(receipt_reference(receipt), log_path=log_path) is None


def test_ledger_inode_identity_change_fails_closed(tmp_path) -> None:
    log_path = tmp_path / "resource-receipts.jsonl"
    first = _receipt(external_id="delivery-inode-before", raw_payload_sha256="1" * 64)
    replacement = _receipt(external_id="delivery-inode-after", raw_payload_sha256="2" * 64)
    assert append_resource_receipt(first, log_path=log_path)
    replacement_path = tmp_path / "replacement.jsonl"
    replacement_path.write_bytes((replacement.model_dump_json() + "\n").encode())
    os.replace(replacement_path, log_path)

    assert load_resource_receipt(receipt_reference(first), log_path=log_path) is None
