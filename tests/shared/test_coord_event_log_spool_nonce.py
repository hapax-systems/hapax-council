"""WS0: spool filenames carry a nonce so colliding intents never clobber.

A daemon-down fail-open intent must survive on disk until the daemon ingests it
on boot; if two intents with an identical timestamp + event_id mapped to the same
filename, the second would overwrite the first and a coordination authorization
would be silently lost (coordination reform Phase 4 §4.3).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from shared import coord_event_log
from shared.coord_event_log import CoordEvent, CoordEventLog, CoordWriter

if TYPE_CHECKING:
    import pytest


def _event(event_id: str = "evt-dup") -> CoordEvent:
    return CoordEvent(
        event_id=event_id,
        timestamp="2026-05-31T14:00:00Z",
        event_type="sdlc.stage_transition",
        actor="zeta",
        subject="reform-fix-eventlog-ssot-ledger-20260531",
        authority_case="CASE-SDLC-REFORM-001",
        payload={"from_stage": "S6", "to_stage": "S7"},
    )


def _log(tmp_path: Path) -> CoordEventLog:
    return CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )


def test_spool_nonce_prevents_clobber_on_identical_timestamp_and_event_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Freeze the timestamp so the uuid4 nonce is the ONLY differentiator: this
    # isolates the regression the nonce fixes (same ts + same event_id).
    monkeypatch.setattr(coord_event_log, "_now_iso", lambda: "2026-05-31T14:00:00Z")
    log = _log(tmp_path)
    event = _event("evt-dup")

    first = log.spool_fail_open(event, writer=CoordWriter.shim(lane="zeta"), reason="kernel_down")
    second = log.spool_fail_open(event, writer=CoordWriter.shim(lane="zeta"), reason="kernel_down")

    assert first.spool_path is not None and second.spool_path is not None
    assert first.spool_path != second.spool_path

    files = sorted(log.spool_dir.glob("*.jsonl"))
    assert len(files) == 2
    for path in files:
        record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        assert record["event"]["event_id"] == "evt-dup"


def test_spool_filename_contains_timestamp_event_id_and_nonce(tmp_path: Path) -> None:
    log = _log(tmp_path)
    receipt = log.spool_fail_open(
        _event("evt-shape"), writer=CoordWriter.shim(lane="zeta"), reason="kernel_down"
    )

    assert receipt.spool_path is not None
    name = receipt.spool_path.name
    assert name.endswith(".jsonl")
    assert "evt-shape" in name
    # timestamp + event_id + nonce → at least three '-'-joined segments before .jsonl
    stem = name[: -len(".jsonl")]
    assert stem.count("-") >= 2
