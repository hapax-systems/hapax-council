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
    Snapshot,
    snapshot_id_for,
)
from shared.coord_projection import CoordProjection


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


def test_default_paths_are_a_user_writable_coord_ledger_outside_worktrees() -> None:
    # Must NOT be the old root-owned /var/lib/hapax/coord that uid 1000 could never
    # provision — that default left R2 unmaterialized and R3 inert (reform-improve
    # coord SSOT provisioning).
    for path in (DEFAULT_LEDGER_DB, DEFAULT_JSONL_MIRROR, DEFAULT_SPOOL_DIR):
        assert not str(path).startswith("/var/lib/"), path

    # One fixed `.../hapax/coord` tree; the three artifacts share that base.
    coord = DEFAULT_LEDGER_DB.parent
    assert coord.name == "coord"
    assert coord.parent.name == "hapax"
    assert coord / "ledger.db" == DEFAULT_LEDGER_DB
    assert coord / "ledger.jsonl" == DEFAULT_JSONL_MIRROR
    assert coord / "spool" == DEFAULT_SPOOL_DIR

    # Outside every git worktree (NEW-4).
    repo_root = Path.cwd().resolve()
    for path in (DEFAULT_LEDGER_DB, DEFAULT_JSONL_MIRROR, DEFAULT_SPOOL_DIR):
        assert path.is_absolute()
        assert not path.resolve().is_relative_to(repo_root)
        assert "evidence" not in path.parts


def test_coord_base_dir_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from shared.coord_event_log import coord_base_dir, default_grant_dir, default_grant_key

    for var in ("HAPAX_COORD_DIR", "HAPAX_COORD_GRANT_DIR", "HAPAX_COORD_GRANT_KEY"):
        monkeypatch.delenv(var, raising=False)

    # 1. Clean env → user-writable ~/.cache/hapax/coord (no XDG override).
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    cache_coord = Path.home() / ".cache" / "hapax" / "coord"
    assert coord_base_dir() == cache_coord
    assert default_grant_dir() == cache_coord / "grants"
    assert default_grant_key() == cache_coord / "grant-key"

    # 2. XDG_CACHE_HOME is honored.
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert coord_base_dir() == tmp_path / "xdg" / "hapax" / "coord"

    # 3. HAPAX_COORD_DIR (test/sandbox isolation) wins over XDG.
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "iso"))
    assert coord_base_dir() == tmp_path / "iso"
    assert default_grant_dir() == tmp_path / "iso" / "grants"
    assert default_grant_key() == tmp_path / "iso" / "grant-key"

    # 4. An explicit grant override wins over the resolved base.
    monkeypatch.setenv("HAPAX_COORD_GRANT_DIR", str(tmp_path / "g"))
    monkeypatch.setenv("HAPAX_COORD_GRANT_KEY", str(tmp_path / "k"))
    assert default_grant_dir() == tmp_path / "g"
    assert default_grant_key() == tmp_path / "k"


def test_provision_coord_tree_creates_writable_tree_and_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from shared.coord_event_log import default_event_log, provision_coord_tree

    base = tmp_path / "coord"
    monkeypatch.setenv("HAPAX_COORD_DIR", str(base))
    monkeypatch.delenv("HAPAX_COORD_GRANT_DIR", raising=False)
    monkeypatch.delenv("HAPAX_COORD_GRANT_KEY", raising=False)

    result = provision_coord_tree()
    assert result.base_dir == base
    assert result.grant_dir == base / "grants"
    assert (base / "spool").is_dir()
    assert (base / "grants").is_dir()
    grant_key = base / "grant-key"
    assert grant_key.exists()
    assert oct(grant_key.stat().st_mode & 0o777) == "0o600", "grant key must not be world-readable"
    assert result.key_created is True

    # A real append now succeeds against the provisioned, writable tree.
    receipt = default_event_log().append(_event(), writer=CoordWriter.daemon())
    assert receipt.appended is True
    assert (base / "ledger.db").exists()

    # Idempotent: a second run creates nothing new and reuses the operator key.
    key_bytes = grant_key.read_bytes()
    again = provision_coord_tree()
    assert again.key_created is False
    assert grant_key.read_bytes() == key_bytes


def test_provision_coord_tree_fails_loud_when_unwritable(tmp_path: Path) -> None:
    from shared.coord_event_log import CoordEventLogError, provision_coord_tree

    # A regular file standing where the base dir must go: mkdir raises, and the
    # provisioner must surface it LOUDLY rather than silently degrade.
    blocker = tmp_path / "blocked"
    blocker.write_text("not a dir", encoding="utf-8")
    target = blocker / "coord"
    with pytest.raises(CoordEventLogError):
        provision_coord_tree(
            base_dir=target,
            grant_dir=target / "grants",
            grant_key=target / "grant-key",
        )


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


# --- snapshot compaction (event-sourcing checkpoint primitives) ---------------
# Snapshot-ONLY slice (bb-event-sourced-substrate): a checkpoint of the folded
# projection so a read can resume from a serialized state + the tail instead of
# always re-folding from sequence zero. Purely additive — NO event is ever deleted
# (prune is a separate, deliberately deferred operation). Generalizes the proven
# replay_decision_log fold (shared/policy_decide.py) into the coord substrate.


def _canon(record: object) -> str:
    """The canonical JSON byte-form the snapshot equality is asserted against."""
    return json.dumps(record, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _stage_event(eid: str, subject: str, to_stage: str, no_go: dict | None = None) -> CoordEvent:
    return CoordEvent(
        event_id=eid,
        timestamp="2026-06-02T12:00:00Z",
        event_type="sdlc.stage_transition",
        actor="beta",
        subject=subject,
        authority_case="CASE-SDLC-REFORM-001",
        payload={"to_stage": to_stage, "no_go_snapshot": no_go or {}},
    )


def test_snapshot_id_for_is_deterministic_and_distinct() -> None:
    assert snapshot_id_for(7) == snapshot_id_for(7)  # stable across calls
    assert snapshot_id_for(7) != snapshot_id_for(8)  # keyed by through_sequence
    assert snapshot_id_for(7).startswith("coord-snap-")


def test_write_snapshot_persists_and_latest_snapshot_reads_it_back(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.append(_event(), writer=CoordWriter.daemon())

    snap = log.write_snapshot('{"tasks":{}}', through_sequence=1, writer=CoordWriter.daemon())

    assert isinstance(snap, Snapshot)
    assert snap.through_sequence == 1
    assert snap.snapshot_id == snapshot_id_for(1)
    assert log.latest_snapshot() == snap


def test_latest_snapshot_is_none_without_a_snapshot(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.append(_event(), writer=CoordWriter.daemon())
    assert log.latest_snapshot() is None


def test_latest_snapshot_returns_the_highest_through_sequence(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.write_snapshot('{"tasks":{}}', through_sequence=1, writer=CoordWriter.daemon())
    log.write_snapshot('{"tasks":{}}', through_sequence=3, writer=CoordWriter.daemon())
    log.write_snapshot('{"tasks":{}}', through_sequence=2, writer=CoordWriter.daemon())

    latest = log.latest_snapshot()
    assert latest is not None
    assert latest.through_sequence == 3


def test_write_snapshot_is_idempotent_on_the_same_sequence(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.write_snapshot('{"tasks":{}}', through_sequence=2, writer=CoordWriter.daemon())
    log.write_snapshot('{"tasks":{}}', through_sequence=2, writer=CoordWriter.daemon())

    with sqlite3.connect(log.db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM coord_snapshots").fetchone()[0]
    assert count == 1  # deterministic snapshot_id → one row per (through_sequence, schema)


def test_lane_writer_cannot_write_a_snapshot(tmp_path: Path) -> None:
    log = _log(tmp_path)
    with pytest.raises(DirectLaneWriteError):
        log.write_snapshot('{"tasks":{}}', through_sequence=1, writer=CoordWriter.lane("beta"))


def test_replay_since_sequence_returns_only_the_tail(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.append(_stage_event("e1", "task-1", "S6"), writer=CoordWriter.daemon())
    log.append(_stage_event("e2", "task-1", "S7"), writer=CoordWriter.daemon())
    log.append(_stage_event("e3", "task-2", "S6"), writer=CoordWriter.daemon())

    tail = log.replay(since_sequence=2)

    assert [event.event_id for event in tail.events] == ["e3"]


def test_replay_default_still_returns_full_history(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.append(_stage_event("e1", "task-1", "S6"), writer=CoordWriter.daemon())
    log.append(_stage_event("e2", "task-1", "S7"), writer=CoordWriter.daemon())

    assert [event.event_id for event in log.replay().events] == ["e1", "e2"]


def test_snapshot_does_not_delete_any_events(tmp_path: Path) -> None:
    # SNAPSHOT-ONLY guarantee: snapshotting is purely additive; the event log is
    # never truncated (prune is a separate, deliberately deferred operation).
    log = _log(tmp_path)
    log.append(_stage_event("e1", "task-1", "S6"), writer=CoordWriter.daemon())
    log.append(_stage_event("e2", "task-1", "S7"), writer=CoordWriter.daemon())

    log.snapshot(CoordProjection)

    assert [event.event_id for event in log.replay().events] == ["e1", "e2"]


def test_snapshot_then_replay_projection_is_byte_identical_to_full_replay(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.append(
        _stage_event("e1", "task-1", "S6", {"release_authorized": False}),
        writer=CoordWriter.daemon(),
    )
    log.append(_stage_event("e2", "task-1", "S7"), writer=CoordWriter.daemon())

    snap = log.snapshot(CoordProjection)
    assert snap.through_sequence == 2

    # Events that land AFTER the checkpoint must be folded from the tail.
    log.append(
        CoordEvent(
            event_id="e3",
            timestamp="2026-06-02T12:01:00Z",
            event_type="sdlc.authorization_flip",
            actor="beta",
            subject="task-1",
            authority_case="CASE-SDLC-REFORM-001",
            payload={"field": "release_authorized", "old": False, "new": True},
        ),
        writer=CoordWriter.daemon(),
    )
    log.append(_stage_event("e4", "task-2", "S6"), writer=CoordWriter.daemon())

    from_zero = CoordProjection.from_replay(log.replay())
    from_snap = log.replay_projection(CoordProjection, from_snapshot=True)

    assert _canon(from_snap.to_record()) == _canon(from_zero.to_record())
    # The tail genuinely contributed (post-snapshot flip + a brand-new task).
    assert from_snap.tasks["task-1"].stage == "S7"
    assert from_snap.tasks["task-1"].no_go["release_authorized"] is True
    assert "task-2" in from_snap.tasks


def test_replay_projection_without_a_snapshot_matches_full_replay(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.append(_stage_event("e1", "task-1", "S6"), writer=CoordWriter.daemon())
    log.append(_stage_event("e2", "task-1", "S7"), writer=CoordWriter.daemon())

    from_zero = CoordProjection.from_replay(log.replay())
    from_driver = log.replay_projection(CoordProjection, from_snapshot=True)  # no snapshot yet

    assert _canon(from_driver.to_record()) == _canon(from_zero.to_record())
