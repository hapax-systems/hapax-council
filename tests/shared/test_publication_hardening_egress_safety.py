"""Tests for shared.publication_hardening.egress_safety."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from shared.publication_hardening.egress_safety import (
    DEFAULT_RATE_LIMIT,
    EgressDecision,
    EgressSafetyEnvelope,
)


def test_proceed_when_no_kill_switch_and_under_rate(tmp_path: Path) -> None:
    kill_switch = tmp_path / "KILL_SWITCH"
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    envelope = EgressSafetyEnvelope(
        kill_switch_path=kill_switch, log_dir=log_dir, held_dir=tmp_path / "held"
    )
    result = envelope.check()
    assert result.decision == EgressDecision.PROCEED
    assert result.rate_window_count == 0


def test_kill_switch_blocks_egress(tmp_path: Path) -> None:
    kill_switch = tmp_path / "KILL_SWITCH"
    kill_switch.write_text("emergency stop")
    envelope = EgressSafetyEnvelope(
        kill_switch_path=kill_switch,
        log_dir=tmp_path / "log",
        held_dir=tmp_path / "held",
    )
    result = envelope.check()
    assert result.decision == EgressDecision.KILL_SWITCHED
    assert "kill switch" in result.reason


def test_rate_limit_blocks_when_exceeded(tmp_path: Path) -> None:
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    now = datetime.now(UTC)
    for i in range(5):
        (log_dir / f"artifact-{i}.omg-weblog.json").write_text(
            json.dumps(
                {
                    "result": "ok",
                    "dispatched_at": (now - timedelta(hours=1)).isoformat(),
                }
            )
        )
    envelope = EgressSafetyEnvelope(
        kill_switch_path=tmp_path / "KILL_SWITCH",
        log_dir=log_dir,
        held_dir=tmp_path / "held",
        rate_limit=5,
        rate_window_hours=24,
    )
    result = envelope.check()
    assert result.decision == EgressDecision.RATE_LIMITED
    assert result.rate_window_count == 5
    assert result.rate_limit == 5


def test_rate_limit_ignores_old_dispatches(tmp_path: Path) -> None:
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    old_time = datetime.now(UTC) - timedelta(hours=48)
    for i in range(10):
        (log_dir / f"artifact-{i}.omg-weblog.json").write_text(
            json.dumps({"result": "ok", "dispatched_at": old_time.isoformat()})
        )
    envelope = EgressSafetyEnvelope(
        kill_switch_path=tmp_path / "KILL_SWITCH",
        log_dir=log_dir,
        held_dir=tmp_path / "held",
        rate_limit=5,
        rate_window_hours=24,
    )
    result = envelope.check()
    assert result.decision == EgressDecision.PROCEED
    assert result.rate_window_count == 0


def test_rate_limit_ignores_non_ok_results(tmp_path: Path) -> None:
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    now = datetime.now(UTC)
    for i, status in enumerate(["denied", "error", "deferred", "auth_error", "dropped"]):
        (log_dir / f"artifact-{i}.surface.json").write_text(
            json.dumps({"result": status, "dispatched_at": now.isoformat()})
        )
    envelope = EgressSafetyEnvelope(
        kill_switch_path=tmp_path / "KILL_SWITCH",
        log_dir=log_dir,
        held_dir=tmp_path / "held",
        rate_limit=3,
        rate_window_hours=24,
    )
    result = envelope.check()
    assert result.decision == EgressDecision.PROCEED
    assert result.rate_window_count == 0


def test_kill_switch_property(tmp_path: Path) -> None:
    kill_switch = tmp_path / "KILL_SWITCH"
    envelope = EgressSafetyEnvelope(
        kill_switch_path=kill_switch,
        log_dir=tmp_path / "log",
        held_dir=tmp_path / "held",
    )
    assert not envelope.kill_switch_active
    kill_switch.write_text("")
    assert envelope.kill_switch_active


def test_default_rate_limit_is_20() -> None:
    assert DEFAULT_RATE_LIMIT == 20


def test_missing_log_dir_counts_zero(tmp_path: Path) -> None:
    envelope = EgressSafetyEnvelope(
        kill_switch_path=tmp_path / "KILL_SWITCH",
        log_dir=tmp_path / "nonexistent_log_dir",
        held_dir=tmp_path / "held",
        rate_limit=5,
    )
    result = envelope.check()
    assert result.decision == EgressDecision.PROCEED
    assert result.rate_window_count == 0


def test_malformed_log_files_are_skipped(tmp_path: Path) -> None:
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    (log_dir / "corrupt.json").write_text("not json")
    (log_dir / "missing-fields.json").write_text("{}")
    envelope = EgressSafetyEnvelope(
        kill_switch_path=tmp_path / "KILL_SWITCH",
        log_dir=log_dir,
        held_dir=tmp_path / "held",
        rate_limit=5,
    )
    result = envelope.check()
    assert result.decision == EgressDecision.PROCEED
    assert result.rate_window_count == 0
