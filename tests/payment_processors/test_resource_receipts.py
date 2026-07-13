"""Tests for governed money-rail resource receipts."""

from __future__ import annotations

import fcntl
import logging
import os
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

    guidance = resource_receipt_recovery_guidance(log_path=log_path)

    assert str(log_path) in guidance
    assert str(log_path.with_name(f"{log_path.name}.lock")) in guidance
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
