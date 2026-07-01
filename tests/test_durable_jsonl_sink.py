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
    DurableSinkChainError,
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

    with pytest.raises(DurableSinkPathError, match="non-durable filesystem tmpfs.*next action"):
        DurableJsonlSink(root)


@pytest.mark.parametrize("fstype", ["devtmpfs", "proc", "sysfs", "devpts", "cgroup2"])
def test_configured_root_refuses_known_non_durable_filesystems(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fstype: str
) -> None:
    root = tmp_path / "durable"
    root.mkdir()
    monkeypatch.setattr(sink_mod, "_mount_fstype_for_path", lambda _path: fstype)

    with pytest.raises(DurableSinkPathError, match=f"non-durable filesystem {fstype}.*next action"):
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


def test_append_refuses_existing_corrupt_stream_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = _trusted_sink(tmp_path, monkeypatch)
    row = sink.append(
        stream_id="payment-event",
        data_class="financial_receipt",
        source_receipt_ref="receipt://payment/1",
        payload={"idx": 1},
        timestamp="2026-07-01T00:00:00Z",
    )
    path = sink.path_for_stream("payment-event")
    tampered = row.as_dict()
    tampered["payload"] = {"idx": 999}
    original_corrupt_text = _json_line(tampered) + "\n"
    path.write_text(original_corrupt_text, encoding="utf-8")

    with pytest.raises(DurableSinkChainError, match="next action"):
        sink.append(
            stream_id="payment-event",
            data_class="financial_receipt",
            source_receipt_ref="receipt://payment/2",
            payload={"idx": 2},
            timestamp="2026-07-01T00:00:01Z",
        )

    assert path.read_text(encoding="utf-8") == original_corrupt_text


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


def test_chain_validation_rejects_newline_truncated_tail_and_append_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = _trusted_sink(tmp_path, monkeypatch)
    row = sink.append(
        stream_id="payment-event",
        data_class="financial_receipt",
        source_receipt_ref="receipt://payment/1",
        payload={"idx": 1},
        timestamp="2026-07-01T00:00:00Z",
    )
    path = sink.path_for_stream("payment-event")
    truncated_tail = _json_line(row.as_dict())
    path.write_text(truncated_tail, encoding="utf-8")

    result = validate_chain(path, stream_id="payment-event")

    assert result.valid is False
    assert result.row_count == 0
    assert result.tail_hash == GENESIS_HASH
    assert {issue.code for issue in result.issues} == {"missing_newline"}
    with pytest.raises(DurableSinkChainError, match="next action"):
        sink.append(
            stream_id="payment-event",
            data_class="financial_receipt",
            source_receipt_ref="receipt://payment/2",
            payload={"idx": 2},
            timestamp="2026-07-01T00:00:01Z",
        )
    assert path.read_text(encoding="utf-8") == truncated_tail


def test_validate_chain_rejects_non_file_stream_path(tmp_path: Path) -> None:
    path = tmp_path / "payment-event.jsonl"
    path.mkdir()

    result = validate_chain(path, stream_id="payment-event")

    assert result.valid is False
    assert result.issues[0].code == "not_file"


def test_validate_chain_rejects_invalid_stream_id_argument(tmp_path: Path) -> None:
    with pytest.raises(DurableSinkValueError, match="stream_id.*next action"):
        validate_chain(tmp_path / "unused.jsonl", stream_id="../bad")


def test_validate_chain_reports_read_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "payment-event.jsonl"
    path.write_text("", encoding="utf-8")
    real_open = Path.open

    def failing_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self == path:
            raise OSError("simulated read failure")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(sink_mod.Path, "open", failing_open)

    result = validate_chain(path, stream_id="payment-event")

    assert result.valid is False
    assert {issue.code for issue in result.issues} == {"read_error"}
    with pytest.raises(DurableSinkChainError, match="next action"):
        result.raise_for_issues()


def test_append_refuses_non_utf8_stream_as_chain_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = _trusted_sink(tmp_path, monkeypatch)
    path = sink.path_for_stream("payment-event")
    path.write_bytes(b"\xff\n")

    result = validate_chain(path, stream_id="payment-event")

    assert result.valid is False
    assert {issue.code for issue in result.issues} == {"decode_error"}
    with pytest.raises(DurableSinkChainError, match="next action"):
        sink.append(
            stream_id="payment-event",
            data_class="financial_receipt",
            source_receipt_ref="receipt://payment/1",
            payload={"idx": 1},
            timestamp="2026-07-01T00:00:00Z",
        )


def test_chain_validation_exception_includes_next_action(tmp_path: Path) -> None:
    path = tmp_path / "payment-event.jsonl"
    path.write_text("{not json\n", encoding="utf-8")
    result = validate_chain(path, stream_id="payment-event")

    with pytest.raises(DurableSinkChainError, match="next action"):
        result.raise_for_issues()


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


def test_zero_progress_append_rolls_back_and_raises(
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

    monkeypatch.setattr(sink_mod.os, "write", lambda _fd, _data: 0)

    with pytest.raises(DurableSinkAppendError) as exc_info:
        sink.append(
            stream_id="payment-event",
            data_class="financial_receipt",
            source_receipt_ref="receipt://payment/2",
            payload={"idx": 2},
            timestamp="2026-07-01T00:00:01Z",
        )

    assert "storage write errors" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, DurableSinkAppendError)
    assert "no progress" in str(exc_info.value.__cause__)
    assert path.read_text(encoding="utf-8") == original


def test_append_lock_open_failure_has_next_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = _trusted_sink(tmp_path, monkeypatch)
    real_open = sink_mod.os.open

    def failing_lock_open(path: Any, flags: int, mode: int = 0o777) -> int:
        if str(path).endswith(".lock"):
            raise PermissionError("simulated lock open failure")
        return real_open(path, flags, mode)

    monkeypatch.setattr(sink_mod.os, "open", failing_lock_open)

    with pytest.raises(DurableSinkAppendError, match="lock .*next action"):
        sink.append(
            stream_id="payment-event",
            data_class="financial_receipt",
            source_receipt_ref="receipt://payment/1",
            payload={"idx": 1},
            timestamp="2026-07-01T00:00:00Z",
        )

    assert not sink.path_for_stream("payment-event").exists()


def test_append_lock_acquire_failure_has_next_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = _trusted_sink(tmp_path, monkeypatch)

    def failing_flock(_fd: int, op: int) -> None:
        if op == sink_mod.fcntl.LOCK_EX:
            raise OSError("simulated lock acquire failure")

    monkeypatch.setattr(sink_mod.fcntl, "flock", failing_flock)

    with pytest.raises(DurableSinkAppendError, match="acquire durable sink lock.*next action"):
        sink.append(
            stream_id="payment-event",
            data_class="financial_receipt",
            source_receipt_ref="receipt://payment/1",
            payload={"idx": 1},
            timestamp="2026-07-01T00:00:00Z",
        )

    assert not sink.path_for_stream("payment-event").exists()


def test_append_lock_release_failure_has_next_action_after_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = _trusted_sink(tmp_path, monkeypatch)
    real_open = sink_mod.os.open
    real_close = sink_mod.os.close
    lock_fds: list[int] = []
    closed_lock_fds: list[int] = []

    def failing_unlock(_fd: int, op: int) -> None:
        if op == sink_mod.fcntl.LOCK_UN:
            raise OSError("simulated lock release failure")

    def recording_open(path: Any, flags: int, mode: int = 0o777) -> int:
        fd = real_open(path, flags, mode)
        if str(path).endswith(".lock"):
            lock_fds.append(fd)
        return fd

    def recording_close(fd: int) -> None:
        if fd in lock_fds:
            closed_lock_fds.append(fd)
        real_close(fd)

    monkeypatch.setattr(sink_mod.os, "open", recording_open)
    monkeypatch.setattr(sink_mod.os, "close", recording_close)
    monkeypatch.setattr(sink_mod.fcntl, "flock", failing_unlock)

    with pytest.raises(DurableSinkAppendError, match="release durable sink lock.*next action"):
        sink.append(
            stream_id="payment-event",
            data_class="financial_receipt",
            source_receipt_ref="receipt://payment/1",
            payload={"idx": 1},
            timestamp="2026-07-01T00:00:00Z",
        )

    result = validate_chain(sink.path_for_stream("payment-event"), stream_id="payment-event")
    assert result.valid is True
    assert result.row_count == 1
    assert closed_lock_fds == lock_fds


def test_append_stream_open_failure_has_next_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = _trusted_sink(tmp_path, monkeypatch)
    real_open = sink_mod.os.open

    def failing_stream_open(path: Any, flags: int, mode: int = 0o777) -> int:
        if Path(path).name == "payment-event.jsonl":
            raise PermissionError("simulated stream open failure")
        return real_open(path, flags, mode)

    monkeypatch.setattr(sink_mod.os, "open", failing_stream_open)

    with pytest.raises(DurableSinkAppendError, match="stream file .*next action"):
        sink.append(
            stream_id="payment-event",
            data_class="financial_receipt",
            source_receipt_ref="receipt://payment/1",
            payload={"idx": 1},
            timestamp="2026-07-01T00:00:00Z",
        )

    assert not sink.path_for_stream("payment-event").exists()


def test_partial_append_raises_even_when_rollback_truncate_fails(
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
    truncations: list[int] = []

    def flaky_write(fd: int, data: bytes | memoryview) -> int:
        nonlocal calls
        if calls == 0:
            calls += 1
            return real_write(fd, data[: max(1, len(data) // 2)])
        raise OSError("simulated device write failure")

    def failing_ftruncate(_fd: int, length: int) -> None:
        truncations.append(length)
        raise OSError("simulated rollback failure")

    monkeypatch.setattr(sink_mod.os, "write", flaky_write)
    monkeypatch.setattr(sink_mod.os, "ftruncate", failing_ftruncate)

    with pytest.raises(DurableSinkAppendError, match="validate the stream chain"):
        sink.append(
            stream_id="payment-event",
            data_class="financial_receipt",
            source_receipt_ref="receipt://payment/2",
            payload={"idx": 2},
            timestamp="2026-07-01T00:00:01Z",
        )

    assert truncations == [len(original.encode("utf-8"))]
    assert validate_chain(path, stream_id="payment-event").valid is False


def test_directory_fsync_success_opens_readonly_and_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[tuple[Path, int]] = []
    fsynced: list[int] = []
    closed: list[int] = []

    def fake_open(path: Any, flags: int, _mode: int = 0o777) -> int:
        opened.append((Path(path), flags))
        return 99

    def recording_fsync(fd: int) -> None:
        fsynced.append(fd)

    def recording_close(fd: int) -> None:
        closed.append(fd)

    monkeypatch.setattr(sink_mod.os, "open", fake_open)
    monkeypatch.setattr(sink_mod.os, "fsync", recording_fsync)
    monkeypatch.setattr(sink_mod.os, "close", recording_close)

    sink_mod._fsync_directory(tmp_path)

    assert opened == [(tmp_path, sink_mod.os.O_RDONLY)]
    assert fsynced == [99]
    assert closed == [99]


def test_directory_open_failure_has_next_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_open(_path: Any, _flags: int, _mode: int = 0o777) -> int:
        raise PermissionError("simulated directory open failure")

    monkeypatch.setattr(sink_mod.os, "open", failing_open)

    with pytest.raises(DurableSinkAppendError, match="open durable sink directory.*next action"):
        sink_mod._fsync_directory(tmp_path)


def test_directory_fsync_failure_has_next_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[int] = []

    def fake_open(_path: Any, _flags: int, _mode: int = 0o777) -> int:
        return 99

    def failing_fsync(fd: int) -> None:
        assert fd == 99
        raise OSError("simulated fsync failure")

    def recording_close(fd: int) -> None:
        closed.append(fd)

    monkeypatch.setattr(sink_mod.os, "open", fake_open)
    monkeypatch.setattr(sink_mod.os, "fsync", failing_fsync)
    monkeypatch.setattr(sink_mod.os, "close", recording_close)

    with pytest.raises(DurableSinkAppendError, match="fsync durable sink directory.*next action"):
        sink_mod._fsync_directory(tmp_path)

    assert closed == [99]
