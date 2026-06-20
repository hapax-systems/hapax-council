from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
PRESET = REPO_ROOT / "systemd" / "user-preset.d" / "hapax.preset"
UNIT = "hapax-darkplaces-boot-containment.service"

GATE = "%h/.config/hapax/enable-darkplaces-runtime"


def _read(unit_name: str) -> str:
    return (UNITS_DIR / unit_name).read_text(encoding="utf-8")


def test_boot_containment_strips_the_runtime_gate() -> None:
    body = _read(UNIT)
    # The whole point: remove the persistent gate so the renderer cannot
    # auto-start unattended at boot (2026-05-23 attended-only audit).
    assert f"ExecStart=/usr/bin/rm -f {GATE}" in body
    assert "Type=oneshot" in body


def test_boot_containment_runs_before_every_renderer_unit() -> None:
    body = _read(UNIT)
    before = next(
        (ln for ln in body.splitlines() if ln.startswith("Before=")),
        "",
    )
    # Must order before EVERY unit that evaluates the gate's ConditionPathExists,
    # or the gate could still be present when they start.
    for unit in (
        "hapax-visual-stack.target",
        "hapax-darkplaces-v4l2.service",
        "hapax-darkplaces-obs-media-stream.service",
        "hapax-darkplaces-bridge.service",
        "hapax-screwm-speech-wave-producer.service",
        "hapax-darkplaces.service",
    ):
        assert unit in before, f"{unit} not ordered after the boot-containment guard"


def test_boot_containment_is_wanted_by_boot_targets() -> None:
    body = _read(UNIT)
    install = next(
        (ln for ln in body.splitlines() if ln.startswith("WantedBy=")),
        "",
    )
    assert "default.target" in install
    assert "graphical-session.target" in install


def test_renderer_units_still_gate_on_the_runtime_flag() -> None:
    # The guard only matters because the renderer units gate on the flag; if that
    # contract ever changes, this guard's stripping is a no-op and must be revisited.
    for unit in (
        "hapax-darkplaces-v4l2.service",
        "hapax-darkplaces-obs-media-stream.service",
    ):
        assert f"ConditionPathExists={GATE}" in _read(unit), unit


def test_boot_containment_is_enabled_in_preset() -> None:
    preset = PRESET.read_text(encoding="utf-8")
    assert f"enable {UNIT}" in preset
