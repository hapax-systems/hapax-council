"""`python -m shared.coord_event_log ingest-spool` — the canonical drain verb.

Row `coord-ledger-appendix-mirror-destroys-local-appends-20260925`: the
disposition of spooled fail-open intents is "ingest them idempotently into the
canonical ledger ... with before and after counts". The daemon boot path has
`ingest_spool`/`boot_reconcile`, but the operator-run repair needs a CLI verb
that prints the counts; the module CLI previously exposed only `append`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from shared import coord_event_log
from shared.coord_event_log import CoordEvent, CoordEventLog, CoordWriter

if TYPE_CHECKING:
    import pytest


def _event(event_id: str = "evt-cli-1") -> CoordEvent:
    return CoordEvent(
        event_id=event_id,
        timestamp="2026-09-25T00:00:00Z",
        event_type="coord_dispatch.launch_failed",
        actor="kimi-2",
        subject="coord-ledger-appendix-mirror-destroys-local-appends-20260925",
        authority_case="CASE-SDLC-REFORM-001",
        payload={"k": 1},
    )


def _log(tmp_path: Path) -> CoordEventLog:
    return CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )


def test_ingest_spool_cli_drains_and_prints_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    log = _log(tmp_path)
    log.spool_fail_open(_event(), writer=CoordWriter.shim(lane="kimi-2"), reason="daemon_down")
    log.spool_fail_open(
        _event("evt-cli-2"), writer=CoordWriter.shim(lane="kimi-2"), reason="daemon_down"
    )

    rc = coord_event_log.main(["ingest-spool"])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ingested"] == 2
    assert out["duplicates"] == 0
    assert out["failed"] == 0
    assert sorted(out["removed"])  # consumed filenames are reported
    assert sum(1 for e in log.replay().events if e.event_id.startswith("evt-cli-")) == 2


def test_ingest_spool_cli_reports_duplicates_on_redelivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    log = _log(tmp_path)
    log.spool_fail_open(_event(), writer=CoordWriter.shim(lane="kimi-2"), reason="daemon_down")
    assert coord_event_log.main(["ingest-spool"]) == 0
    capsys.readouterr()

    # Redelivered intent (forwarding path delivered the same event_id twice).
    log.spool_fail_open(_event(), writer=CoordWriter.shim(lane="kimi-2"), reason="forwarded")
    rc = coord_event_log.main(["ingest-spool"])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ingested"] == 0
    assert out["duplicates"] == 1
    assert out["failed"] == 0
    assert sum(1 for e in log.replay().events if e.event_id == "evt-cli-1") == 1
