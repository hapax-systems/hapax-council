"""Escalation recorder: run the escalation detector over recent logs and record every finding.

A user timer runs this every 10 minutes over a 12-minute window, so consecutive windows overlap.
Findings go to the existing coord event log (``shared.coord_event_log``) as a named service
writer, the same way ``hapax-liveness`` and the methodology dispatcher record their events, with
the fail-open spool. Lanes never write that log. Event ids are derived from each finding, so an
overlap records nothing twice.

A log the recorder cannot read (the journal, or docker events) is recorded as a
``detector_blind`` finding, and the run fails: silence must not look like "no escalation".

Bound: this records (class (c)); it prevents nothing. It runs as the lane user, so a lane can
stop the user timer; any stopped interval then shows as a gap in the log.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from shared.coord_event_log import CoordEvent, CoordEventLog, CoordWriter, DuplicateEventError
from shared.escalation_detector import Finding, docker_findings, journal_findings

AUTHORITY_CASE = "CASE-SYSTEM-INTEGRITY-20260611"
WRITER = "hapax-escalation-detector"
EVENT_TYPE = "escalation-finding"
WINDOW = timedelta(minutes=12)
_IDENTIFIERS = ("sudo", "su", "pkexec", "ksu")

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


class _Blind(Exception):
    pass


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)


def _json_lines(text: str) -> list[Any]:
    parsed: list[Any] = []
    for line in text.splitlines():
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return parsed


def _read(argv: list[str], runner: Runner) -> str:
    try:
        done = runner(argv)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise _Blind(f"{argv[0]} could not run: {exc}") from exc
    if done.returncode != 0:
        raise _Blind(f"{' '.join(argv[:2])} exited {done.returncode}: {done.stderr.strip()[:200]}")
    return done.stdout


def _journal(since: datetime, runner: Runner) -> list[Finding]:
    argv = ["/usr/bin/journalctl", "-o", "json", "--no-pager", "--since", since.isoformat()]
    argv += [f"SYSLOG_IDENTIFIER={ident}" for ident in _IDENTIFIERS]
    return journal_findings(_json_lines(_read(argv, runner)))


def _docker(since: datetime, until: datetime, runner: Runner) -> list[Finding]:
    argv = ["/usr/bin/docker", "events", "--since", since.isoformat(), "--until", until.isoformat()]
    argv += ["--filter", "type=container", "--format", "{{json .}}"]
    events = _json_lines(_read(argv, runner))
    ids = sorted({str((e.get("Actor") or {}).get("ID", "")) for e in events} - {""})
    inspects: list[Any] = []
    if ids:
        # A removed container is absent here; the detector records it as uninspectable.
        done = runner(["/usr/bin/docker", "inspect", *ids])
        try:
            inspects = json.loads(done.stdout or "[]")
        except json.JSONDecodeError:
            inspects = []
    return docker_findings(events, {str(i.get("Id", "")): i for i in inspects})


def _instant(at: str, fallback: datetime) -> datetime:
    """Journal timestamps are microseconds and docker's are nanoseconds since the epoch."""
    try:
        value = int(at)
    except ValueError:
        return fallback
    seconds = value / 1_000_000_000 if value > 10**17 else value / 1_000_000
    return datetime.fromtimestamp(seconds, tz=UTC)


def event_for(finding: Finding, *, now: datetime) -> CoordEvent:
    """The coord event for one finding; its id is derived from the finding, so it records once."""
    key = "|".join(str(v) for v in asdict(finding).values())
    return CoordEvent(
        event_id=f"escalation-{hashlib.sha256(key.encode()).hexdigest()[:32]}",
        timestamp=_instant(finding.at, now).isoformat(),
        event_type=EVENT_TYPE,
        actor=finding.subject or finding.source,
        subject=f"{finding.source}:{finding.kind}",
        authority_case=AUTHORITY_CASE,
        payload=asdict(finding),
    )


def _record(findings: Iterable[Finding], log: CoordEventLog, now: datetime) -> None:
    writer = CoordWriter.daemon(WRITER)
    for finding in findings:
        try:
            log.append(event_for(finding, now=now), writer=writer, fail_open=True)
        except DuplicateEventError:
            continue


def run(now: datetime, *, runner: Runner, log: CoordEventLog) -> int:
    """Record the window's findings; 1 when a log could not be read (recorded as blindness)."""
    since = now - WINDOW
    findings: list[Finding] = []
    blind = False
    for source, read in (
        ("journal", lambda: _journal(since, runner)),
        ("docker", lambda: _docker(since, now, runner)),
    ):
        try:
            findings.extend(read())
        except _Blind as exc:
            blind = True
            findings.append(Finding("detector_blind", source, "", str(exc), True, now.isoformat()))
    _record(findings, log, now)
    return 1 if blind else 0


def main() -> int:
    return run(datetime.now(UTC), runner=_run, log=CoordEventLog())


if __name__ == "__main__":
    raise SystemExit(main())
