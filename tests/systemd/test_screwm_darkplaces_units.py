from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"


def _read(unit_name: str) -> str:
    return (UNITS_DIR / unit_name).read_text(encoding="utf-8")


def test_darkplaces_v4l2_service_remains_runtime_guarded_and_5060_pinned() -> None:
    body = _read("hapax-darkplaces-v4l2.service")

    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in body
    assert (
        "ExecStart=/usr/bin/bash -lc 'exec "
        '"$HOME/.cache/hapax/source-activation/worktree/scripts/darkplaces-v4l2-xorg.sh"'
        "'"
    ) in body
    assert "Environment=HAPAX_DARKPLACES_XORG_BUS_ID=PCI:5:0:0" in body
    assert "Environment=HAPAX_DARKPLACES_EXPECTED_GPU_INDEX=1" in body
    assert (
        'Environment="HAPAX_DARKPLACES_EXPECTED_GL_RENDERER=NVIDIA GeForce RTX 5060 Ti"'
    ) in body
    assert "Environment=HAPAX_DARKPLACES_V4L2_DEVICE=/dev/video52" in body


def test_darkplaces_state_bridge_follows_v4l2_renderer_unit() -> None:
    body = _read("hapax-darkplaces-bridge.service")

    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in body
    assert "PartOf=hapax-darkplaces.service hapax-darkplaces-v4l2.service" in body
    assert "After=hapax-darkplaces.service hapax-darkplaces-v4l2.service" in body
    assert "WantedBy=hapax-darkplaces.service hapax-darkplaces-v4l2.service" in body


def test_visual_stack_conditionally_wants_darkplaces_runtime_units() -> None:
    target = _read("hapax-visual-stack.target")
    v4l2 = _read("hapax-darkplaces-v4l2.service")
    bridge = _read("hapax-darkplaces-bridge.service")

    assert "hapax-darkplaces-v4l2.service" in target
    assert "hapax-darkplaces-bridge.service" in target
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in v4l2
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in bridge
