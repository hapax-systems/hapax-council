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


def test_backblaze_remote_timer_is_retired_but_manual_service_receipt_remains() -> None:
    assert not (UNITS / "hapax-backup-remote.timer").exists()
    assert (UNITS / "hapax-backup-remote.service").exists()
