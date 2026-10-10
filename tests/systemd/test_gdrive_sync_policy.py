from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS = REPO_ROOT / "systemd" / "units"
ACTIVATION = "%h/.cache/hapax/source-activation/worktree"
GOOGLE_SYNC_UNITS = ("gdrive-sync", "gmail-sync", "gcalendar-sync", "langfuse-sync")


def test_gdrive_sync_polls_every_minute_without_overlap() -> None:
    # Operator 2026-09-24: "sync is 15 min, but prolly should be 1".
    timer = (UNITS / "gdrive-sync.timer").read_text(encoding="utf-8")

    assert "Description=gdrive sync (every minute)" in timer
    assert "OnUnitInactiveSec=1min" in timer
    assert "OnBootSec=2min" in timer
    assert "OnCalendar=" not in timer
    # a randomized delay would stretch every 1-minute tick
    assert "RandomizedDelaySec" not in timer
    assert "Persistent=true" not in timer


@pytest.mark.parametrize("name", GOOGLE_SYNC_UNITS)
def test_google_sync_unit_runs_deploy_tree_and_alarms_on_failure(name: str) -> None:
    # 2026-09-17..24: podium ran the Pi6 variants (.venv-sync, no OnFailure=);
    # every run failed 203/EXEC and nothing alarmed.
    service = (UNITS / f"{name}.service").read_text(encoding="utf-8")

    assert "OnFailure=notify-failure@%n.service" in service
    assert f"ExecStart={ACTIVATION}/.venv/bin/python -m agents.{name.replace('-', '_')} --auto" in (
        service
    )
    assert ".venv-sync" not in service
    assert "uv run" not in service


@pytest.mark.parametrize(("name", "memory_max"), [("gdrive-sync", "3G"), ("gmail-sync", "1536M")])
def test_google_sync_memory_max_covers_measured_peak(name: str, memory_max: str) -> None:
    # Measured on podium 2026-09-24: gdrive 1.5G peak, gmail 658M uncapped.
    service = (UNITS / f"{name}.service").read_text(encoding="utf-8")

    assert f"MemoryMax={memory_max}" in service


def test_gdrive_drop_hot_sync_units_are_retired() -> None:
    assert not (UNITS / "rclone-gdrive-drop.service").exists()
    assert not (UNITS / "rclone-gdrive-drop.timer").exists()


def test_backblaze_remote_timer_is_retired_but_manual_service_receipt_remains() -> None:
    assert not (UNITS / "hapax-backup-remote.timer").exists()
    assert (UNITS / "hapax-backup-remote.service").exists()
