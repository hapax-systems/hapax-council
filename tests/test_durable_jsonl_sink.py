"""Tests for the Stage-0 durable append-only JSONL sink primitive."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import shared.durable_jsonl_sink as sink_mod
from shared.durable_jsonl_sink import (
    GENESIS_HASH,
    DurableJsonlSink,
    DurableSinkAppendError,
    DurableSinkPathError,
    validate_chain,
)


def _trusted_sink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DurableJsonlSink:
    root = tmp_path / "durable"
    root.mkdir()
    monkeypatch.setattr(sink_mod, "_mount_fstype_for_path", lambda _path: "btrfs")
    return DurableJsonlSink(root)


def _codes(path: Path, *, stream_id: str = "payment-event") -> set[str]:
    return {issue.code for issue in validate_chain(path, stream_id=stream_id).issues}


def test_append_rows_include_required_chain_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = _trusted_sink(tmp_path, monkeypatch)

    first = sink.append(
        stream_id="payment-event",
        data_class="financial_receipt",
        source_receipt_ref="receipt://payment/1",
        payload={"rail": "lightning", "amount_msat": 1000},
        timestamp="2026-07-01T00:00:00Z",
    )
    second = sink.append(
        stream_id="payment-event",
        data_class="financial_receipt",
        source_receipt_ref="receipt://payment/2",
        payload={"rail": "lightning", "amount_msat": 2000},
        timestamp="2026-07-01T00:00:01Z",
    )

    assert first.prior_hash == GENESIS_HASH
    assert second.prior_hash == first.row_hash
    path = sink.path_for_stream("payment-event")
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert lines[0] == first.as_dict()
    assert lines[1] == second.as_dict()
    for row in lines:
        assert set(row) == {
            "schema_version",
            "timestamp",
            "stream_id",
            "data_class",
            "source_receipt_ref",
            "prior_hash",
            "row_hash",
            "payload",
        }
        assert row["stream_id"] == "payment-event"
        assert row["data_class"] == "financial_receipt"
        assert row["source_receipt_ref"].startswith("receipt://payment/")

    validation = validate_chain(path, stream_id="payment-event")
    assert validation.valid is True
    assert validation.row_count == 2
    assert validation.tail_hash == second.row_hash


def test_configured_root_must_already_exist(tmp_path: Path) -> None:
    with pytest.raises(DurableSinkPathError, match="absent"):
        DurableJsonlSink(tmp_path / "missing-root")


def test_configured_root_refuses_volatile_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "durable"
    root.mkdir()
    monkeypatch.setattr(sink_mod, "_mount_fstype_for_path", lambda _path: "tmpfs")

    with pytest.raises(DurableSinkPathError, match="volatile filesystem tmpfs"):
        DurableJsonlSink(root)


def test_chain_validation_catches_modified_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = _trusted_sink(tmp_path, monkeypatch)
    for idx in range(2):
        sink.append(
            stream_id="chronicle",
            data_class="chronicle_event",
            source_receipt_ref=f"receipt://chronicle/{idx}",
            payload={"idx": idx},
            timestamp=f"2026-07-01T00:00:0{idx}Z",
        )
    path = sink.path_for_stream("chronicle")
    lines = path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[1])
    tampered["payload"]["idx"] = 999
    lines[1] = json.dumps(tampered, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = validate_chain(path, stream_id="chronicle")
    assert result.valid is False
    assert "row_hash_mismatch" in {issue.code for issue in result.issues}


def test_chain_validation_catches_reordered_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = _trusted_sink(tmp_path, monkeypatch)
    for idx in range(3):
        sink.append(
            stream_id="payment-event",
            data_class="financial_receipt",
            source_receipt_ref=f"receipt://payment/{idx}",
            payload={"idx": idx},
            timestamp=f"2026-07-01T00:00:0{idx}Z",
        )
    path = sink.path_for_stream("payment-event")
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([lines[1], lines[0], lines[2]]) + "\n", encoding="utf-8")

    assert "prior_hash_mismatch" in _codes(path)


def test_chain_validation_catches_missing_middle_and_tail_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = _trusted_sink(tmp_path, monkeypatch)
    rows = [
        sink.append(
            stream_id="payment-event",
            data_class="financial_receipt",
            source_receipt_ref=f"receipt://payment/{idx}",
            payload={"idx": idx},
            timestamp=f"2026-07-01T00:00:0{idx}Z",
        )
        for idx in range(3)
    ]
    path = sink.path_for_stream("payment-event")
    lines = path.read_text(encoding="utf-8").splitlines()

    path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    assert "prior_hash_mismatch" in _codes(path)

    path.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")
    result = validate_chain(
        path,
        stream_id="payment-event",
        expected_tail_hash=rows[-1].row_hash,
        expected_count=3,
    )
    assert result.valid is False
    assert {"tail_hash_mismatch", "row_count_mismatch"} <= {issue.code for issue in result.issues}


def test_partial_append_rolls_back_and_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = _trusted_sink(tmp_path, monkeypatch)
    sink.append(
        stream_id="payment-event",
        data_class="financial_receipt",
        source_receipt_ref="receipt://payment/1",
        payload={"idx": 1},
        timestamp="2026-07-01T00:00:00Z",
    )
    path = sink.path_for_stream("payment-event")
    original = path.read_text(encoding="utf-8")
    real_write = sink_mod.os.write
    calls = 0

    def flaky_write(fd: int, data: bytes | memoryview) -> int:
        nonlocal calls
        if calls == 0:
            calls += 1
            return real_write(fd, data[: max(1, len(data) // 2)])
        raise OSError("simulated short device write")

    monkeypatch.setattr(sink_mod.os, "write", flaky_write)
    with pytest.raises(DurableSinkAppendError):
        sink.append(
            stream_id="payment-event",
            data_class="financial_receipt",
            source_receipt_ref="receipt://payment/2",
            payload={"idx": 2},
            timestamp="2026-07-01T00:00:01Z",
        )

    assert path.read_text(encoding="utf-8") == original
    assert validate_chain(path, stream_id="payment-event").valid is True
