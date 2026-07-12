"""The projection-only supervisor must not mint P0 tasks through notifications."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR = REPO_ROOT / "scripts" / "hapax-lane-supervisor"
SERVICE = REPO_ROOT / "systemd" / "units" / "hapax-lane-supervisor.service"


def test_supervisor_does_not_reference_incident_intake_or_alert_writer() -> None:
    text = SUPERVISOR.read_text(encoding="utf-8")
    assert "hapax-p0-incident-intake" not in text
    assert "hapax-alert" not in text
    assert "notification" not in text.lower()


def test_service_has_no_task_minting_onfailure_edge() -> None:
    text = SERVICE.read_text(encoding="utf-8")
    assert "OnFailure=" not in text
    assert "notify-failure@" not in text
