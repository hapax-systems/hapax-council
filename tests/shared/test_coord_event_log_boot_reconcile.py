"""Tests for coord event-log spool ingestion + boot reconcile (master design §4.3).

The daemon heap is DERIVED: on boot it replays the canonical log and drains any
fail-open spool intents written while it was down, so no authorization lives only
in a process image.
"""

from __future__ import annotations

from pathlib import Path

from shared.coord_event_log import CoordEvent, CoordEventLog, CoordWriter


def _log(tmp_path: Path) -> CoordEventLog:
    return CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )


def _event(event_id: str = "evt-1") -> CoordEvent:
    return CoordEvent(
        event_id=event_id,
        timestamp="2026-05-31T00:00:00Z",
        event_type="sdlc.stage_transition",
        actor="zeta",
        subject="task-x",
        authority_case="CASE-SDLC-REFORM-001",
        payload={"from_stage": "S6", "to_stage": "S7"},
    )


def test_ingest_spool_appends_and_removes(tmp_path: Path) -> None:
    log = _log(tmp_path)
    receipt = log.spool_fail_open(
        _event(), writer=CoordWriter.shim(lane="zeta"), reason="daemon_down"
    )
    assert receipt.spool_path is not None and receipt.spool_path.exists()

    result = log.ingest_spool()
    assert result.ingested == 1
    assert result.duplicates == 0
    assert result.failed == 0
    assert not receipt.spool_path.exists()  # consumed file removed
    assert any(e.event_id == "evt-1" for e in log.replay().events)  # now canonical


def test_ingest_spool_is_idempotent_on_duplicate(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.append(_event(), writer=CoordWriter.daemon())  # already canonical
    spooled = log.spool_fail_open(
        _event(), writer=CoordWriter.shim(lane="zeta"), reason="daemon_down"
    )

    result = log.ingest_spool()
    assert result.duplicates == 1
    assert result.ingested == 0
    assert spooled.spool_path is not None and not spooled.spool_path.exists()  # still removed
    assert sum(1 for e in log.replay().events if e.event_id == "evt-1") == 1


def test_ingest_spool_leaves_malformed_file(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.spool_dir.mkdir(parents=True, exist_ok=True)
    bad = log.spool_dir / "2026-bad-evt.jsonl"
    bad.write_text("{not valid json", encoding="utf-8")

    result = log.ingest_spool()
    assert result.failed == 1
    assert result.ingested == 0
    assert bad.exists()  # left in place so the intent is not lost


def test_ingest_spool_removes_the_lock_sidecar_with_the_consumed_intent(
    tmp_path: Path,
) -> None:
    """A consumed intent leaves NO residue — including the flock sidecar.

    Production census on 2026-09-25 (row
    coord-ledger-appendix-mirror-destroys-local-appends-20260925): 43 orphaned
    `.jsonl.lock` sidecars in the live spool dir, one per intent consumed since
    June — `ingest_spool` unlinked the intent but not the `append_jsonl` lock.
    """
    log = _log(tmp_path)
    receipt = log.spool_fail_open(
        _event(), writer=CoordWriter.shim(lane="zeta"), reason="daemon_down"
    )
    assert receipt.spool_path is not None
    lock_sidecar = receipt.spool_path.with_name(receipt.spool_path.name + ".lock")
    assert lock_sidecar.exists()

    result = log.ingest_spool()

    assert result.ingested == 1
    assert not receipt.spool_path.exists()
    assert not lock_sidecar.exists(), "the consumed intent's lock sidecar must go with it"


def test_ingest_spool_redelivered_intent_is_ingested_exactly_once(tmp_path: Path) -> None:
    """A forwarded spool can deliver the same intent twice; the ledger lands it once.

    The coord-ledger mirror row routes appendix-side writers to a forwarding
    spool the canonical writer ingests; forwarding can redeliver (rsync re-run
    before the source cleanup). `event_id UNIQUE` makes the second delivery an
    idempotent duplicate: consumed, counted, never a second canonical row.
    """
    log = _log(tmp_path)
    log.spool_fail_open(_event(), writer=CoordWriter.shim(lane="zeta"), reason="daemon_down")
    first = log.ingest_spool()
    assert (first.ingested, first.duplicates, first.failed) == (1, 0, 0)

    # Redelivery: the same intent arrives again as a fresh spool file.
    log.spool_fail_open(_event(), writer=CoordWriter.shim(lane="zeta"), reason="forwarded")
    second = log.ingest_spool()

    assert (second.ingested, second.duplicates, second.failed) == (0, 1, 0)
    assert sum(1 for e in log.replay().events if e.event_id == "evt-1") == 1


def test_ingest_spool_noop_when_no_spool_dir(tmp_path: Path) -> None:
    result = _log(tmp_path).ingest_spool()
    assert (result.ingested, result.duplicates, result.failed) == (0, 0, 0)


def test_boot_reconcile_replays_then_ingests(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.append(_event("canon-1"), writer=CoordWriter.daemon())
    log.spool_fail_open(
        _event("spool-1"), writer=CoordWriter.shim(lane="zeta"), reason="daemon_down"
    )

    result = log.boot_reconcile()
    assert result.replayed >= 1  # canonical events present before ingest
    assert result.spool_ingested == 1
    assert result.spool_failed == 0
    ids = {e.event_id for e in log.replay().events}
    assert {"canon-1", "spool-1"} <= ids


def test_boot_reconcile_to_record_is_json_shaped(tmp_path: Path) -> None:
    record = _log(tmp_path).boot_reconcile().to_record()
    assert record["replayed"] == 0
    assert record["spool_ingested"] == 0
    assert isinstance(record["errors"], list)
