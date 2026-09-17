from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS = REPO_ROOT / "systemd" / "units"


def test_gdrive_sync_is_daily_background_reconciliation() -> None:
    timer = (UNITS / "gdrive-sync.timer").read_text(encoding="utf-8")

    assert "Description=gdrive sync (daily)" in timer
    assert "OnCalendar=*-*-* 18:30:00" in timer
    assert "RandomizedDelaySec=30min" in timer
    assert "OnUnitActiveSec=6h" not in timer
    assert "Persistent=true" not in timer


def test_gdrive_drop_hot_sync_units_are_retired() -> None:
    assert not (UNITS / "rclone-gdrive-drop.service").exists()
    assert not (UNITS / "rclone-gdrive-drop.timer").exists()


def test_backblaze_remote_timer_is_source_controlled_and_the_service_remains() -> None:
    """Until 2026-09-02 this test pinned the 2026-06-06 'B2 retired' policy while podium ran
    hapax-backup-remote.timer every night from an installed copy the repository did not hold.
    Measured 2026-09-02: the B2 run completes nightly (4 m 43 s that day) and the storage registry
    now records it enabled/daily; B2 and R2 are the two off-site copies in different failure
    domains. The timer is source-controlled here so the runtime and the record agree."""
    timer = UNITS / "hapax-backup-remote.timer"
    assert timer.exists()
    assert "OnCalendar=" in timer.read_text()
    assert (UNITS / "hapax-backup-remote.service").exists()
