from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from shared.coord_event_log import (
    DEFAULT_JSONL_MIRROR,
    DEFAULT_LEDGER_DB,
    DEFAULT_SPOOL_DIR,
    CoordEvent,
    CoordEventLog,
    CoordWriter,
    DirectLaneWriteError,
)


def _event(event_id: str = "evt-1") -> CoordEvent:
    return CoordEvent(
        event_id=event_id,
        timestamp="2026-05-31T14:05:36Z",
        event_type="sdlc.stage_transition",
        actor="cx-cyan",
        subject="reform-4a-event-log-20260531",
        authority_case="CASE-SDLC-REFORM-001",
        parent_spec=(
            "~/Documents/Personal/30-areas/hapax/coordination-reform-master-design-2026-05-30.md"
        ),
        payload={"from_stage": "S6_IMPLEMENTATION", "to_stage": "S7_RELEASE"},
    )


def _log(tmp_path: Path) -> CoordEventLog:
    return CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )


def test_default_paths_are_single_coord_ledger_outside_worktrees() -> None:
    assert Path("/var/lib/hapax/coord/ledger.db") == DEFAULT_LEDGER_DB
    assert Path("/var/lib/hapax/coord/ledger.jsonl") == DEFAULT_JSONL_MIRROR
    assert Path("/var/lib/hapax/coord/spool") == DEFAULT_SPOOL_DIR

    repo_root = Path.cwd().resolve()
    for path in (DEFAULT_LEDGER_DB, DEFAULT_JSONL_MIRROR, DEFAULT_SPOOL_DIR):
        assert path.is_absolute()
        assert not path.resolve().is_relative_to(repo_root)
        assert "evidence" not in path.parts


def test_append_persists_sqlite_wal_and_jsonl_mirror(tmp_path: Path) -> None:
    log = _log(tmp_path)
    receipt = log.append(_event(), writer=CoordWriter.daemon())

    assert receipt.appended is True
    assert receipt.spooled is False
    assert receipt.sequence == 1
    assert receipt.db_path == tmp_path / "coord" / "ledger.db"
    assert receipt.jsonl_path == tmp_path / "coord" / "ledger.jsonl"

    with sqlite3.connect(receipt.db_path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        row = conn.execute(
            "SELECT sequence, event_id, event_type, actor, subject FROM coord_events"
        ).fetchone()
    assert row == (
        1,
        "evt-1",
        "sdlc.stage_transition",
        "cx-cyan",
        "reform-4a-event-log-20260531",
    )

    mirror_rows = [
        json.loads(line) for line in receipt.jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    assert mirror_rows == [log.replay().events[0].to_record()]


def test_replay_falls_back_to_jsonl_mirror_when_sqlite_is_corrupt(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.append(_event(), writer=CoordWriter.daemon())
    log.db_path.write_bytes(b"this is not sqlite")
    log.db_path.with_name("ledger.db-wal").unlink(missing_ok=True)
    log.db_path.with_name("ledger.db-shm").unlink(missing_ok=True)

    result = log.replay(fail_open=True)

    assert result.degraded is True
    assert result.source == "jsonl_mirror"
    assert result.events[0].event_id == "evt-1"
    assert result.errors


def test_replay_skips_corrupt_jsonl_lines_during_fail_open(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.db_path.parent.mkdir(parents=True)
    log.db_path.write_bytes(b"not sqlite")
    log.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    log.jsonl_path.write_text(
        json.dumps(_event("evt-1").to_record(sequence=1), sort_keys=True)
        + "\nnot json\n"
        + json.dumps(_event("evt-2").to_record(sequence=2), sort_keys=True)
        + "\n",
        encoding="utf-8",
    )

    result = log.replay(fail_open=True)

    assert [event.event_id for event in result.events] == ["evt-1", "evt-2"]
    assert result.degraded is True
    assert any("line 2" in error for error in result.errors)


def test_append_spools_fail_open_when_canonical_log_is_unavailable(tmp_path: Path) -> None:
    db_path = tmp_path / "coord" / "ledger.db"
    db_path.mkdir(parents=True)
    log = CoordEventLog(
        db_path=db_path,
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )

    receipt = log.append(_event("evt-spool"), writer=CoordWriter.daemon(), fail_open=True)

    assert receipt.appended is False
    assert receipt.spooled is True
    assert receipt.sequence is None
    assert not log.jsonl_path.exists()
    spool_files = sorted(log.spool_dir.glob("*.jsonl"))
    assert len(spool_files) == 1
    spooled = json.loads(spool_files[0].read_text(encoding="utf-8").splitlines()[0])
    assert spooled["event"]["event_id"] == "evt-spool"
    assert spooled["reason"].startswith("canonical_append_failed:")


def test_lane_writer_cannot_write_canonical_log_or_spool(tmp_path: Path) -> None:
    log = _log(tmp_path)

    with pytest.raises(DirectLaneWriteError):
        log.append(_event(), writer=CoordWriter.lane("cx-cyan"), fail_open=True)

    assert not log.db_path.exists()
    assert not log.jsonl_path.exists()
    assert not log.spool_dir.exists()


def test_shim_can_spool_fail_open_without_touching_canonical_log(tmp_path: Path) -> None:
    log = _log(tmp_path)

    receipt = log.spool_fail_open(
        _event("evt-shim-spool"),
        writer=CoordWriter.shim(lane="cx-cyan"),
        reason="kernel_down",
    )

    assert receipt.appended is False
    assert receipt.spooled is True
    assert not log.db_path.exists()
    assert not log.jsonl_path.exists()
    assert receipt.spool_path is not None
    spooled = json.loads(receipt.spool_path.read_text(encoding="utf-8").splitlines()[0])
    assert spooled["writer"] == {"name": "cc-task-gate", "kind": "shim", "lane": "cx-cyan"}
    assert spooled["reason"] == "kernel_down"


def test_legacy_authority_case_ledger_is_not_git_tracked() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    if not (repo_root / ".git").exists():
        pytest.skip("git metadata not available")

    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "evidence/authority-case-ledger.jsonl"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode != 0
