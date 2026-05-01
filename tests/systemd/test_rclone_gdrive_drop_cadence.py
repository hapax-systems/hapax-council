"""Cadence pin for the rclone gdrive-drop timer.

Per cc-task ``rclone-gdrive-drop-cadence-decision`` (closed 2026-05-01):
the operator's CLAUDE.md states "Google Drive drop folder:
``~/gdrive-drop/`` syncs from ``gdrive:drop`` every 30s via rclone systemd
timer." The on-disk timer briefly drifted to 5s, then drifted back —
PR #1730 bundled the cadence-fix with unrelated audio/CPU work and
was closed without merge.

The 5s cadence was empirically counterproductive: bisync averages ~14s
runtime, so 5s OnUnitActiveSec produced back-to-back invocations with
zero idle time, churning disk + network for a drop folder that
receives new files minute-scale at most.

These pins prevent the cadence from drifting back to the unintended
5s value.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TIMER = REPO_ROOT / "systemd" / "units" / "rclone-gdrive-drop.timer"


def test_timer_unit_exists() -> None:
    assert TIMER.is_file(), f"rclone-gdrive-drop.timer missing at {TIMER}"


def test_cadence_is_30_seconds() -> None:
    """``OnUnitActiveSec`` must be 30s — the operator-documented cadence."""
    body = TIMER.read_text(encoding="utf-8")
    assert "OnUnitActiveSec=30s" in body, (
        "rclone-gdrive-drop.timer cadence must be 30s; the 5s drift was "
        "operator-rejected after empirical observation that bisync "
        "averages ~14s runtime, so 5s = continuous churn"
    )
    assert "OnUnitActiveSec=5s" not in body, (
        "5s cadence regression detected — see "
        "cc-task rclone-gdrive-drop-cadence-decision for rationale"
    )


def test_boot_delay_matches_active_cadence() -> None:
    """``OnBootSec`` should match ``OnUnitActiveSec`` so the first run
    after boot follows the same idle-time invariant as steady-state."""
    body = TIMER.read_text(encoding="utf-8")
    assert "OnBootSec=30s" in body, (
        "OnBootSec must match the 30s active cadence; mismatched values "
        "produce a faster-than-intended first cycle right after boot"
    )
