"""Static pins for the MediaMTX user unit."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT = REPO_ROOT / "systemd" / "units" / "mediamtx.service"


def _sections() -> dict[str, set[str]]:
    sections: dict[str, set[str]] = {}
    current = ""
    for raw_line in UNIT.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line.strip("[]")
            sections.setdefault(current, set())
            continue
        sections.setdefault(current, set()).add(line)
    return sections


def test_restart_limit_and_failure_hook_live_in_unit_section() -> None:
    sections = _sections()

    assert "StartLimitBurst=10" in sections["Unit"]
    assert "StartLimitIntervalSec=600" in sections["Unit"]
    assert "OnFailure=notify-failure@%n.service" in sections["Unit"]

    service = sections["Service"]
    assert "StartLimitBurst=10" not in service
    assert "StartLimitIntervalSec=600" not in service
    assert "OnFailure=notify-failure@%n.service" not in service


def test_mediamtx_is_not_lifecycle_bound_to_compositor() -> None:
    sections = _sections()

    assert "PartOf=studio-compositor.service" not in sections["Unit"]
    assert "After=network-online.target hapax-secrets.service" in sections["Unit"]
