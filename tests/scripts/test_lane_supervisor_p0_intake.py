from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR = REPO_ROOT / "scripts" / "hapax-lane-supervisor"


def test_lane_supervisor_default_escalation_uses_p0_intake_before_raw_desktop():
    text = SUPERVISOR.read_text(encoding="utf-8")

    intake = text.index("hapax-p0-incident-intake")
    raw_desktop = text.index("notify-send -u critical")
    assert intake < raw_desktop
    assert "--technical" in text
    assert "--priority urgent" in text
