"""The recorder runs the escalation detector over recent logs and records every finding.

Findings go to the existing coord event log as a named service writer (never a lane), once each.
A log the recorder cannot read is recorded as blindness and fails the unit: silence must not look
like "no escalation".
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from shared import escalation_recorder as rec
from shared.coord_event_log import CoordEvent, CoordEventLog, CoordWriter
from shared.escalation_detector import Finding
from shared.escalation_recorder import AUTHORITY_CASE, EVENT_TYPE, WINDOW, WRITER, event_for, run

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 25, 9, 0, tzinfo=UTC)
CID = "c" * 64


def _us(dt: datetime) -> str:
    return str(int(dt.timestamp() * 1_000_000))


def _ns(dt: datetime) -> str:
    return str(int(dt.timestamp() * 1_000_000_000))


SUDO = {
    "SYSLOG_IDENTIFIER": "sudo",
    "MESSAGE": "hapax : TTY=pts/3 ; PWD=/home/hapax ; USER=root ; "
    "COMMAND=/usr/bin/tee /etc/claude-code/managed-settings.d/x.json",
    "__REALTIME_TIMESTAMP": _us(NOW - timedelta(minutes=5)),
}
PRIVILEGED_CREATE = {
    "Type": "container",
    "Action": "create",
    "Actor": {"ID": CID},
    "timeNano": _ns(NOW - timedelta(minutes=4)),
}
PRIVILEGED_INSPECT = [{"Id": CID, "HostConfig": {"Privileged": True}, "Mounts": []}]


class FakeHost:
    def __init__(
        self,
        *,
        journal: list[Any] | None = None,
        journal_rc: int = 0,
        events: list[Any] | None = None,
        events_rc: int = 0,
        inspects: list[Any] | None = None,
        docker_missing: bool = False,
    ) -> None:
        self.journal = [SUDO] if journal is None else journal
        self.journal_rc = journal_rc
        self.events = [PRIVILEGED_CREATE] if events is None else events
        self.events_rc = events_rc
        self.inspects = PRIVILEGED_INSPECT if inspects is None else inspects
        self.docker_missing = docker_missing
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        if argv[0].endswith("journalctl"):
            lines = [e if isinstance(e, str) else json.dumps(e) for e in self.journal]
            return subprocess.CompletedProcess(argv, self.journal_rc, "\n".join(lines), "")
        if self.docker_missing:
            raise FileNotFoundError(argv[0])
        if argv[1] == "events":
            lines = [json.dumps(e) for e in self.events]
            return subprocess.CompletedProcess(argv, self.events_rc, "\n".join(lines), "")
        if argv[1] == "inspect":
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.inspects), "")
        raise AssertionError(argv)


@pytest.fixture
def log(tmp_path: Path) -> CoordEventLog:
    return CoordEventLog(
        db_path=tmp_path / "ledger.db",
        jsonl_path=tmp_path / "ledger.jsonl",
        spool_dir=tmp_path / "spool",
    )


def recorded(log: CoordEventLog) -> list[CoordEvent]:
    return [e for e in log.replay().events if e.event_type == EVENT_TYPE]


# --- findings are recorded, once each ---


def test_sudo_and_privileged_container_findings_are_recorded(log: CoordEventLog) -> None:
    assert run(NOW, runner=FakeHost(), log=log) == 0
    kinds = sorted(e.payload["kind"] for e in recorded(log))
    assert kinds == ["container_escalated", "sudo"]
    sudo = next(e for e in recorded(log) if e.payload["kind"] == "sudo")
    assert sudo.payload["sensitive"] is True
    assert sudo.authority_case == AUTHORITY_CASE


def test_overlapping_runs_record_each_finding_once(log: CoordEventLog) -> None:
    run(NOW, runner=FakeHost(), log=log)
    run(NOW + timedelta(minutes=10), runner=FakeHost(), log=log)
    assert len(recorded(log)) == 2


def test_the_same_finding_has_the_same_event_id() -> None:
    finding = Finding("sudo", "journal", "root", "/usr/bin/id", False, _us(NOW))
    assert event_for(finding, now=NOW).event_id == event_for(finding, now=NOW).event_id
    later = Finding(
        "sudo", "journal", "root", "/usr/bin/id", False, _us(NOW + timedelta(seconds=1))
    )
    assert event_for(later, now=NOW).event_id != event_for(finding, now=NOW).event_id


def test_the_event_carries_the_whole_finding_and_its_time() -> None:
    finding = Finding("sudo", "journal", "root", "/usr/bin/id", True, _us(NOW))
    event = event_for(finding, now=NOW + timedelta(hours=1))
    assert event.event_type == EVENT_TYPE
    assert event.payload == {
        "kind": "sudo",
        "source": "journal",
        "subject": "root",
        "detail": "/usr/bin/id",
        "sensitive": True,
        "at": _us(NOW),
    }
    assert datetime.fromisoformat(event.timestamp) == NOW


def test_records_as_the_named_service_writer_never_a_lane(log: CoordEventLog, monkeypatch) -> None:
    writers: list[CoordWriter] = []
    real_append = log.append

    def spy(event: CoordEvent, *, writer: CoordWriter, fail_open: bool = False):
        writers.append(writer)
        return real_append(event, writer=writer, fail_open=fail_open)

    monkeypatch.setattr(log, "append", spy)
    run(NOW, runner=FakeHost(), log=log)
    assert writers and all(w.kind == "daemon" and w.name == WRITER for w in writers)


# --- the window: recent logs, overlapping the timer cadence ---


def test_the_logs_are_read_over_the_window(log: CoordEventLog) -> None:
    host = FakeHost()
    run(NOW, runner=host, log=log)
    journal = next(c for c in host.calls if c[0].endswith("journalctl"))
    events = next(c for c in host.calls if c[0].endswith("docker") and c[1] == "events")
    since = (NOW - WINDOW).isoformat()
    assert journal[journal.index("--since") + 1] == since
    assert events[events.index("--since") + 1] == since
    assert events[events.index("--until") + 1] == NOW.isoformat()
    for ident in ("sudo", "su", "pkexec", "ksu"):
        assert f"SYSLOG_IDENTIFIER={ident}" in journal


def test_the_timer_cadence_is_inside_the_window() -> None:
    timer = (REPO_ROOT / "systemd/units/hapax-escalation-detector.timer").read_text()
    assert "OnUnitActiveSec=10min" in timer
    assert timedelta(minutes=10) < WINDOW


# --- blindness is recorded and fails the unit ---


def test_an_unreadable_journal_is_recorded_and_fails(log: CoordEventLog) -> None:
    assert run(NOW, runner=FakeHost(journal_rc=1), log=log) == 1
    blind = [e for e in recorded(log) if e.payload["kind"] == "detector_blind"]
    assert [e.payload["source"] for e in blind] == ["journal"]


def test_an_unavailable_docker_is_recorded_and_fails(log: CoordEventLog) -> None:
    assert run(NOW, runner=FakeHost(docker_missing=True), log=log) == 1
    blind = [e for e in recorded(log) if e.payload["kind"] == "detector_blind"]
    assert [e.payload["source"] for e in blind] == ["docker"]
    assert any(e.payload["kind"] == "sudo" for e in recorded(log))


def test_failed_docker_events_are_recorded_and_fail(log: CoordEventLog) -> None:
    assert run(NOW, runner=FakeHost(events_rc=1), log=log) == 1
    assert any(e.payload["kind"] == "detector_blind" for e in recorded(log))


def test_a_malformed_journal_line_is_skipped_not_fatal(log: CoordEventLog) -> None:
    assert run(NOW, runner=FakeHost(journal=["{not json", SUDO]), log=log) == 0
    assert any(e.payload["kind"] == "sudo" for e in recorded(log))


def test_a_removed_container_is_still_recorded(log: CoordEventLog) -> None:
    assert run(NOW, runner=FakeHost(inspects=[]), log=log) == 0
    assert any(e.payload["kind"] == "container_uninspectable" for e in recorded(log))


def test_nothing_to_report_records_nothing(log: CoordEventLog) -> None:
    assert run(NOW, runner=FakeHost(journal=[], events=[]), log=log) == 0
    assert recorded(log) == []


# --- the runner is the detector's static caller, so its whitelist entries are gone ---


def test_the_detector_whitelist_entries_are_gone() -> None:
    whitelist = (REPO_ROOT / "scripts/vulture_whitelist.py").read_text()
    assert "journal_findings as _ed_journal_findings" not in whitelist
    assert "docker_findings as _ed_docker_findings" not in whitelist


# --- the unit ---


def test_the_unit_runs_the_recorder_from_the_active_release() -> None:
    service = (REPO_ROOT / "systemd/units/hapax-escalation-detector.service").read_text()
    timer = (REPO_ROOT / "systemd/units/hapax-escalation-detector.timer").read_text()
    assert "Hapax-Install-Scope: system" not in service
    assert (
        "ExecStart=%h/.cache/hapax/source-activation/worktree/.venv/bin/python "
        "-m shared.escalation_recorder"
    ) in service
    assert "Environment=PYTHONPATH=%h/.cache/hapax/source-activation/worktree" in service
    assert "# Hapax-Auto-Enable: true" in timer
    assert "Unit=hapax-escalation-detector.service" in timer


def test_main_runs_against_the_host_and_the_canonical_log(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run(now: datetime, *, runner: Any, log: Any) -> int:
        seen.update(now=now, runner=runner, log=log)
        return 0

    monkeypatch.setattr(rec, "run", fake_run)
    assert rec.main() == 0
    assert isinstance(seen["log"], CoordEventLog)
    assert seen["now"].tzinfo is not None
