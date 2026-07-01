"""Tests for the Stage-0 durable append-only JSONL sink primitive."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

import shared.durable_jsonl_sink as sink_mod
from shared.durable_jsonl_sink import (
    GENESIS_HASH,
    DurableJsonlSink,
    DurableSinkAppendError,
    DurableSinkPathError,
    DurableSinkValueError,
    validate_chain,
)


def _trusted_sink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DurableJsonlSink:
    root = tmp_path / "durable"
    root.mkdir()
    monkeypatch.setattr(sink_mod, "_mount_fstype_for_path", lambda _path: "btrfs")
    return DurableJsonlSink(root)


def _codes(path: Path, *, stream_id: str = "payment-event") -> set[str]:
    return {issue.code for issue in validate_chain(path, stream_id=stream_id).issues}


def _json_line(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"))


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
    with pytest.raises(DurableSinkPathError, match="absent.*next action"):
        DurableJsonlSink(tmp_path / "missing-root")


def test_configured_root_must_be_absolute() -> None:
    with pytest.raises(DurableSinkPathError, match="must be absolute.*next action"):
        DurableJsonlSink("relative-root")


def test_configured_root_must_be_directory(tmp_path: Path) -> None:
    root = tmp_path / "durable-file"
    root.write_text("not a directory", encoding="utf-8")

    with pytest.raises(DurableSinkPathError, match="not a directory.*next action"):
        DurableJsonlSink(root)


def test_configured_root_refuses_unknown_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "durable"
    root.mkdir()
    monkeypatch.setattr(sink_mod, "_mount_fstype_for_path", lambda _path: None)

    with pytest.raises(DurableSinkPathError, match="filesystem type.*next action"):
        DurableJsonlSink(root)


def test_configured_root_refuses_volatile_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "durable"
    root.mkdir()
    monkeypatch.setattr(sink_mod, "_mount_fstype_for_path", lambda _path: "tmpfs")

    with pytest.raises(DurableSinkPathError, match="volatile filesystem tmpfs.*next action"):
        DurableJsonlSink(root)


def test_configured_root_refuses_world_writable_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "durable"
    root.mkdir()
    root.chmod(0o777)
    monkeypatch.setattr(sink_mod, "_mount_fstype_for_path", lambda _path: "btrfs")

    try:
        with pytest.raises(DurableSinkPathError, match="world-writable.*next action"):
            DurableJsonlSink(root)
    finally:
        root.chmod(0o700)


def test_mount_fstype_for_path_uses_decoded_longest_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    durable_root = tmp_path / "durable root"
    nested = durable_root / "nested"
    nested.mkdir(parents=True)
    parent_mount = str(tmp_path).replace(" ", r"\040")
    durable_mount = str(durable_root).replace(" ", r"\040")
    mounts = f"dev-parent {parent_mount} ext4 rw 0 0\ndev-durable {durable_mount} btrfs rw 0 0\n"
    real_read_text = Path.read_text

    def fake_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self == Path("/proc/mounts"):
            return mounts
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(sink_mod.Path, "read_text", fake_read_text)

    assert sink_mod._mount_fstype_for_path(nested) == "btrfs"


def test_mount_fstype_for_path_fails_closed_when_proc_mounts_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "durable"
    root.mkdir()

    def fake_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self == Path("/proc/mounts"):
            raise OSError("permission denied")
        return Path.read_text(self, *args, **kwargs)

    monkeypatch.setattr(sink_mod.Path, "read_text", fake_read_text)

    assert sink_mod._mount_fstype_for_path(root) is None


def test_make_row_rejects_invalid_stream_id_with_next_action() -> None:
    with pytest.raises(DurableSinkValueError, match="stream_id.*next action"):
        sink_mod.make_row(
            stream_id="../bad",
            data_class="financial_receipt",
            source_receipt_ref="receipt://payment/1",
            payload={"idx": 1},
            prior_hash=GENESIS_HASH,
        )


def test_make_row_rejects_blank_required_text_with_next_action() -> None:
    with pytest.raises(DurableSinkValueError, match="data_class.*next action"):
        sink_mod.make_row(
            stream_id="payment-event",
            data_class=" ",
            source_receipt_ref="receipt://payment/1",
            payload={"idx": 1},
            prior_hash=GENESIS_HASH,
        )


def test_make_row_rejects_invalid_prior_hash_with_next_action() -> None:
    with pytest.raises(DurableSinkValueError, match="prior_hash.*next action"):
        sink_mod.make_row(
            stream_id="payment-event",
            data_class="financial_receipt",
            source_receipt_ref="receipt://payment/1",
            payload={"idx": 1},
            prior_hash="not-a-sha",
        )


def test_make_row_rejects_non_mapping_payload_with_next_action() -> None:
    with pytest.raises(DurableSinkValueError, match="payload must be a mapping.*next action"):
        sink_mod.make_row(
            stream_id="payment-event",
            data_class="financial_receipt",
            source_receipt_ref="receipt://payment/1",
            payload=cast("Any", ["not", "a", "mapping"]),
            prior_hash=GENESIS_HASH,
        )


def test_make_row_rejects_non_canonical_payload_with_next_action() -> None:
    with pytest.raises(DurableSinkValueError, match="canonical JSON encodable.*next action"):
        sink_mod.make_row(
            stream_id="payment-event",
            data_class="financial_receipt",
            source_receipt_ref="receipt://payment/1",
            payload={"bad": float("nan")},
            prior_hash=GENESIS_HASH,
        )


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


def test_chain_validation_catches_malformed_rows(tmp_path: Path) -> None:
    valid = sink_mod.make_row(
        stream_id="payment-event",
        data_class="financial_receipt",
        source_receipt_ref="receipt://payment/1",
        payload={"idx": 1},
        prior_hash=GENESIS_HASH,
        timestamp="2026-07-01T00:00:00Z",
    ).as_dict()
    missing_field = dict(valid)
    missing_field.pop("payload")
    invalid_hash = dict(valid, row_hash="bad")
    stream_mismatch = dict(valid, stream_id="chronicle")
    invalid_text = dict(valid, data_class=" ")
    invalid_stream = dict(valid, stream_id="../bad")
    schema_mismatch = dict(valid, schema_version=2)
    invalid_payload = dict(valid, payload=["bad"])
    hash_mismatch = dict(valid, payload={"idx": 999})
    uncanonicalizable = dict(valid, payload={"bad": float("nan")})
    path = tmp_path / "payment-event.jsonl"
    path.write_text(
        "\n".join(
            [
                "",
                "{not json",
                "[]",
                _json_line(missing_field),
                _json_line(invalid_hash),
                _json_line(stream_mismatch),
                _json_line(invalid_text),
                _json_line(invalid_stream),
                _json_line(schema_mismatch),
                _json_line(invalid_payload),
                _json_line(hash_mismatch),
                _json_line(uncanonicalizable),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = validate_chain(path, stream_id="payment-event")

    assert result.valid is False
    assert {
        "blank_line",
        "invalid_json",
        "not_object",
        "missing_field",
        "invalid_row_hash",
        "stream_id_mismatch",
        "invalid_text_field",
        "invalid_stream_id",
        "schema_version_mismatch",
        "invalid_payload",
        "row_hash_mismatch",
        "uncanonicalizable_row",
    } <= {issue.code for issue in result.issues}


def test_validate_chain_rejects_non_file_stream_path(tmp_path: Path) -> None:
    path = tmp_path / "payment-event.jsonl"
    path.mkdir()

    result = validate_chain(path, stream_id="payment-event")

    assert result.valid is False
    assert result.issues[0].code == "not_file"


def test_validate_chain_rejects_invalid_stream_id_argument(tmp_path: Path) -> None:
    with pytest.raises(DurableSinkValueError, match="stream_id.*next action"):
        validate_chain(tmp_path / "unused.jsonl", stream_id="../bad")


def test_path_for_stream_rejects_invalid_stream_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = _trusted_sink(tmp_path, monkeypatch)

    with pytest.raises(DurableSinkValueError, match="stream_id.*next action"):
        sink.path_for_stream("../bad")


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
    real_ftruncate = sink_mod.os.ftruncate
    calls = 0
    truncations: list[int] = []

    def flaky_write(fd: int, data: bytes | memoryview) -> int:
        nonlocal calls
        if calls == 0:
            calls += 1
            return real_write(fd, data[: max(1, len(data) // 2)])
        raise OSError("simulated short device write")

    def recording_ftruncate(fd: int, length: int) -> None:
        truncations.append(length)
        real_ftruncate(fd, length)

    monkeypatch.setattr(sink_mod.os, "write", flaky_write)
    monkeypatch.setattr(sink_mod.os, "ftruncate", recording_ftruncate)
    with pytest.raises(DurableSinkAppendError):
        sink.append(
            stream_id="payment-event",
            data_class="financial_receipt",
            source_receipt_ref="receipt://payment/2",
            payload={"idx": 2},
            timestamp="2026-07-01T00:00:01Z",
        )

    assert path.read_text(encoding="utf-8") == original
    assert truncations == [len(original.encode("utf-8"))]
    assert validate_chain(path, stream_id="payment-event").valid is True
