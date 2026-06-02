"""The recovery scripts route their load-injecting actions through the governor.

Static assertions that the idle-watchdog and reaper call
``python3 -m shared.recovery_governor --permit/--record`` around their relaunch
and reap actions, fail open, and that NO process-group kill exists anywhere in
the new code or the touched scripts (the bounded-kill acceptance criterion). Plus
an end-to-end CLI smoke that the governor's permit/record/state verbs actually
run on this box.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
IDLE = REPO / "scripts" / "hapax-lane-idle-watchdog"
REAPER = REPO / "scripts" / "hapax-lane-reaper"
MODULE = REPO / "shared" / "recovery_governor.py"


# ── both scripts invoke the governor around their recovery actions ────────────


def test_idle_watchdog_permits_and_records_relaunch() -> None:
    text = IDLE.read_text()
    assert "recovery_governor --permit" in text
    assert "recovery_governor --record" in text
    # the permit gate guards the actual launcher invocation
    assert "governor_permit" in text and "$CLAUDE_LAUNCHER" in text


def test_reaper_permits_and_records_the_kill() -> None:
    text = REAPER.read_text()
    assert "recovery_governor --permit" in text
    assert "recovery_governor --record" in text
    # the gate wraps the kill-session path
    assert re.search(r"governor_permit[^\n]*\n[^\n]*tmux kill-session", text)


def test_both_scripts_fail_open_on_governor_error() -> None:
    # The CLI exit-code switch must treat any non-{0,75,2} exit as PERMIT so a
    # broken governor can never wedge the respawn floor / reaper (NEVER-FREEZE).
    for script in (IDLE, REAPER):
        text = script.read_text()
        assert "HAPAX_RECOVERY_GOVERNOR_OFF" in text  # legacy kill-switch honoured
        assert re.search(r"\*\)\s*return 0", text)  # default branch = fail-open permit


# ── bounded-kill contract: grep-clean of any process-group kill ───────────────


def test_no_process_group_kill_anywhere() -> None:
    pattern = re.compile(r"os\.killpg|killpg|kill\(-")
    for path in (MODULE, IDLE, REAPER):
        offenders = [
            f"{path.name}:{i}"
            for i, line in enumerate(path.read_text().splitlines(), 1)
            if pattern.search(line)
        ]
        assert not offenders, f"process-group kill found: {offenders}"


# ── end-to-end: the CLI the scripts shell out to actually runs ────────────────


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "shared.recovery_governor", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
        env={"HAPAX_RECOVERY_GOVERNOR_OFF": "1"},  # deterministic: legacy permit
    )


def test_cli_permit_runs_and_permits_when_disabled() -> None:
    proc = _run(["--permit", "lane:test-wiring"])
    assert proc.returncode == 0  # kill-switch → legacy permit


def test_cli_state_runs_and_prints_a_known_word() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "shared.recovery_governor", "--state"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.stdout.strip() in ("open", "paced", "closed", "degraded")
    assert proc.returncode in (0, 1, 2)
