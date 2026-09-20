"""Pins for the L5 bare-host capability probe unit.

The unit is source-only in this task (not installed). These tests read the
unit files themselves and run the CLI the ExecStart names, so the files
cannot drift from what is claimed.
"""

from __future__ import annotations

import json
from configparser import ConfigParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE = REPO_ROOT / "systemd" / "units" / "hapax-bare-host-capability-probe.service"
TIMER = REPO_ROOT / "systemd" / "units" / "hapax-bare-host-capability-probe.timer"
CLI = REPO_ROOT / "scripts" / "hapax-bare-host-capability-probe"


def _service() -> str:
    return SERVICE.read_text(encoding="utf-8")


def _timer() -> str:
    return TIMER.read_text(encoding="utf-8")


def _timer_parser() -> ConfigParser:
    parser = ConfigParser()
    parser.read_string(_timer())
    return parser


def test_assert_path_exists_is_in_unit_not_service() -> None:
    text = _service()
    unit, _, rest = text.partition("[Service]")
    assert "AssertPathExists=" in unit
    assert "AssertPathExists=" not in rest
    assert "scripts/hapax-bare-host-capability-probe" in unit


def test_unit_uses_store_fast_tmpdir_and_notify_failure() -> None:
    text = _service()
    assert "Environment=TMPDIR=/store-fast/tmp" in text
    assert "OnFailure=notify-failure@%n.service" in text
    assert "PYTHONPATH=%h/.cache/hapax/source-activation/worktree" in text


def test_execstart_names_the_checked_in_cli() -> None:
    text = _service()
    assert "hapax-bare-host-capability-probe" in text
    assert CLI.is_file()
    assert CLI.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3")


def test_timer_is_daily_persistent_and_names_the_service() -> None:
    parser = _timer_parser()
    assert parser.get("Timer", "Persistent").lower() == "true"
    assert parser.get("Timer", "OnCalendar") == "*-*-* 05:27:00"
    assert parser.get("Timer", "Unit") == "hapax-bare-host-capability-probe.service"


def test_cli_writes_receipts_and_renders_absent_as_a_row(tmp_path: Path) -> None:
    import subprocess
    import sys

    roster = tmp_path / "hosts.json"
    roster.write_text(
        json.dumps(
            [
                {
                    "name": "podium",
                    "ip": "100.64.0.1",
                    "os": "darwin",
                    "tags": [],
                    "online": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    receipts = tmp_path / "receipts"
    proc = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--hosts-json",
            str(roster),
            "--receipt-dir",
            str(receipts),
            "--now",
            "2026-08-18T07:32:00Z",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    landed = list((receipts / "bare-host-cli").glob("*.json"))
    assert landed, proc.stdout
    assert "bare-host capability shapes" in proc.stdout
    assert list(receipts.glob("*.json")) == []
