"""The boot restorer must enter the post-merge activation path."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_boot_restorer_is_marked_for_auto_enable() -> None:
    service = (ROOT / "systemd/units/hapax-host-recovery-restore.service").read_text()
    assert "# Hapax-Auto-Enable: true" in service
    assert "WantedBy=default.target" in service
