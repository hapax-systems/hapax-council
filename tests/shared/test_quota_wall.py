"""Tests for quota wall detection and relay receipt handling."""

from __future__ import annotations

import json
from pathlib import Path

from shared.quota_wall import (
    QUOTA_WALL_EXIT_CODE,
    QuotaWallSignal,
    clear_quota_wall_receipt,
    detect_quota_wall,
    handle_quota_wall,
    is_quota_blocked,
    write_quota_wall_receipt,
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def test_detect_rate_limit_event(tmp_path: Path) -> None:
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        [
            {"type": "assistant", "message": {"content": []}},
            {
                "type": "rate_limit_event",
                "rate_limit_info": {
                    "status": "rejected",
                    "resetsAt": 1778277600,
                    "rateLimitType": "seven_day",
                    "isUsingOverage": True,
                },
            },
        ],
    )

    signal = detect_quota_wall(output)
    assert signal is not None
    assert signal.kind == "rate_limit_event"
    assert signal.resets_at == 1778277600
    assert signal.rate_limit_type == "seven_day"
    assert signal.is_overage is True


def test_detect_api_retry_429(tmp_path: Path) -> None:
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        [
            {
                "type": "system",
                "subtype": "api_retry",
                "error_status": 429,
                "error": "rate_limit",
                "attempt": 1,
            },
        ],
    )

    signal = detect_quota_wall(output)
    assert signal is not None
    assert signal.kind == "api_retry_429"


def test_detect_error_rate_limit_on_assistant(tmp_path: Path) -> None:
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        [
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Rate limited"}]},
                "error": "rate_limit",
            },
        ],
    )

    signal = detect_quota_wall(output)
    assert signal is not None
    assert signal.kind == "error_rate_limit"


def test_no_detection_on_normal_output(tmp_path: Path) -> None:
    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello"}]}},
            {"type": "system", "subtype": "init"},
        ],
    )

    signal = detect_quota_wall(output)
    assert signal is None


def test_no_detection_on_missing_file(tmp_path: Path) -> None:
    output = tmp_path / "nonexistent.jsonl"
    signal = detect_quota_wall(output)
    assert signal is None


def test_detection_uses_tail_only(tmp_path: Path) -> None:
    output = tmp_path / "output.jsonl"
    records = [{"type": "assistant", "message": {"content": []}} for _ in range(100)]
    records[5] = {
        "type": "rate_limit_event",
        "rate_limit_info": {"status": "rejected", "rateLimitType": "daily"},
    }
    _write_jsonl(output, records)

    signal = detect_quota_wall(output, tail_lines=10)
    assert signal is None

    signal = detect_quota_wall(output, tail_lines=100)
    assert signal is not None


def test_write_quota_wall_receipt(tmp_path: Path, monkeypatch: object) -> None:
    import shared.quota_wall as qw

    monkeypatch.setattr(qw, "RELAY_RECEIPT_DIR", tmp_path / "receipts")

    signal = QuotaWallSignal(
        kind="rate_limit_event",
        resets_at=1778277600,
        rate_limit_type="seven_day",
        is_overage=True,
    )
    path = write_quota_wall_receipt("beta", signal)
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "role: beta" in content
    assert "status: quota_blocked" in content
    assert "signal_kind: rate_limit_event" in content
    assert "rate_limit_type: seven_day" in content
    assert "is_overage: True" in content


def test_clear_receipt(tmp_path: Path, monkeypatch: object) -> None:
    import shared.quota_wall as qw

    monkeypatch.setattr(qw, "RELAY_RECEIPT_DIR", tmp_path / "receipts")

    signal = QuotaWallSignal(
        kind="rate_limit_event", resets_at=None, rate_limit_type=None, is_overage=False
    )
    write_quota_wall_receipt("gamma", signal)
    assert is_quota_blocked("gamma")
    assert clear_quota_wall_receipt("gamma") is True
    assert not is_quota_blocked("gamma")


def test_clear_receipt_nonexistent(tmp_path: Path, monkeypatch: object) -> None:
    import shared.quota_wall as qw

    monkeypatch.setattr(qw, "RELAY_RECEIPT_DIR", tmp_path / "receipts")
    assert clear_quota_wall_receipt("nonexistent") is False


def test_handle_quota_wall_returns_exit_code(tmp_path: Path, monkeypatch: object) -> None:
    import shared.quota_wall as qw

    monkeypatch.setattr(qw, "RELAY_RECEIPT_DIR", tmp_path / "receipts")

    output = tmp_path / "output.jsonl"
    _write_jsonl(
        output,
        [
            {
                "type": "rate_limit_event",
                "rate_limit_info": {"status": "rejected", "rateLimitType": "daily"},
            },
        ],
    )

    code = handle_quota_wall("delta", output)
    assert code == QUOTA_WALL_EXIT_CODE
    assert is_quota_blocked("delta")


def test_handle_quota_wall_clears_on_normal_exit(tmp_path: Path, monkeypatch: object) -> None:
    import shared.quota_wall as qw

    monkeypatch.setattr(qw, "RELAY_RECEIPT_DIR", tmp_path / "receipts")

    signal = QuotaWallSignal(
        kind="rate_limit_event", resets_at=None, rate_limit_type=None, is_overage=False
    )
    write_quota_wall_receipt("epsilon", signal)
    assert is_quota_blocked("epsilon")

    output = tmp_path / "output.jsonl"
    _write_jsonl(output, [{"type": "assistant", "message": {"content": []}}])

    code = handle_quota_wall("epsilon", output)
    assert code == 0
    assert not is_quota_blocked("epsilon")


def test_quota_wall_signal_to_dict() -> None:
    signal = QuotaWallSignal(
        kind="api_retry_429", resets_at=1778277600, rate_limit_type="daily", is_overage=False
    )
    d = signal.to_dict()
    assert d == {
        "kind": "api_retry_429",
        "resets_at": 1778277600,
        "rate_limit_type": "daily",
        "is_overage": False,
    }
