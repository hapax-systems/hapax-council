from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT = REPO_ROOT / "systemd" / "units" / "notify-failure@.service"


def test_notify_failure_routes_through_p0_intake():
    text = UNIT.read_text(encoding="utf-8")

    assert (
        "ExecStart=%h/.cache/hapax/source-activation/worktree/scripts/"
        "hapax-p0-incident-intake service-failed %i"
    ) in text
    assert "/usr/bin/notify-send" not in text
