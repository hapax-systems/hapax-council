"""Static pins for the operator-awareness systemd unit."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT = REPO_ROOT / "systemd" / "units" / "hapax-operator-awareness.service"


def _service_lines() -> set[str]:
    return {
        line.strip()
        for line in UNIT.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def test_uv_wrapped_notify_service_accepts_child_notifications() -> None:
    lines = _service_lines()

    assert "Type=notify" in lines
    assert "ExecStart=%h/.local/bin/uv run python -m agents.operator_awareness" in lines
    assert "NotifyAccess=all" in lines
