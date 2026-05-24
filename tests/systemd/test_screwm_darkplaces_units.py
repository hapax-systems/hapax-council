from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _read(unit_name: str) -> str:
    return (UNITS_DIR / unit_name).read_text(encoding="utf-8")


def test_darkplaces_v4l2_service_remains_runtime_guarded_and_uses_visible_xvfb_route() -> None:
    body = _read("hapax-darkplaces-v4l2.service")

    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in body
    assert (
        "ExecStart=/usr/bin/bash -lc 'exec "
        '"$HOME/.cache/hapax/source-activation/worktree/scripts/darkplaces-v4l2-xvfb.sh"'
        "'"
    ) in body
    assert "scripts/darkplaces-v4l2-xvfb.sh" in body
    assert "scripts/darkplaces-v4l2-xorg.sh" not in body
    assert "Environment=HAPAX_DARKPLACES_EXPECTED_GPU_INDEX=0" in body
    assert ('Environment="HAPAX_DARKPLACES_EXPECTED_GL_RENDERER=NVIDIA GeForce RTX 5090"') in body
    assert "Environment=HAPAX_DARKPLACES_V4L2_DEVICE=/dev/video52" in body


def test_darkplaces_xorg_launcher_disables_headless_screen_blanking() -> None:
    body = (SCRIPTS_DIR / "darkplaces-v4l2-xorg.sh").read_text(encoding="utf-8")

    for expected in (
        'Option "BlankTime" "0"',
        'Option "StandbyTime" "0"',
        'Option "SuspendTime" "0"',
        'Option "OffTime" "0"',
        'Option "NoPM" "true"',
        'Option "DPMS" "false"',
        "-s 0 \\",
        "-dpms \\",
    ):
        assert expected in body


def test_darkplaces_xvfb_launcher_disables_headless_screen_blanking() -> None:
    body = (SCRIPTS_DIR / "darkplaces-v4l2-xvfb.sh").read_text(encoding="utf-8")

    assert (
        'Xvfb "$DISPLAY_NUM" -screen 0 "${WIDTH}x${HEIGHT}x24" -nolisten tcp -s 0 -dpms &' in body
    )


def test_darkplaces_camera_defaults_to_stable_review_position() -> None:
    defs = (REPO_ROOT / "assets" / "quake" / "qc" / "defs.qc").read_text(encoding="utf-8")
    camera = (REPO_ROOT / "assets" / "quake" / "qc" / "camera.qc").read_text(encoding="utf-8")
    coupling = (REPO_ROOT / "assets" / "quake" / "qc" / "coupling.qc").read_text(encoding="utf-8")
    world = (REPO_ROOT / "assets" / "quake" / "qc" / "world.qc").read_text(encoding="utf-8")

    assert "vector AOA_CENTER = '0 0 176';" in defs
    assert "vector CAMERA_REVIEW_POS = '248 -176 248';" in defs
    assert "vector CAMERA_REVIEW_TARGET = '0 0 160';" in defs
    assert "vector(vector v) vectoangles = #51;" in defs
    assert "ang = vectoangles(target - pos);" in camera
    assert 'if (cvar("screwm_camera_orbit") > 0)' in camera
    assert "pos = CAMERA_REVIEW_POS;" in camera
    assert "CAMERA_ORBIT_PERIOD = 360.0;" in coupling
    assert "CAMERA_PERIOD = 120 + (1.0 - coupling_energy) * 30.0;" not in coupling
    assert "setorigin(self, CAMERA_REVIEW_POS);" in world


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
    obs_bridge = _read("hapax-obs-video50-yuyv-compat-bridge.service")

    assert "hapax-darkplaces-v4l2.service" in target
    assert "hapax-darkplaces-bridge.service" in target
    assert "hapax-obs-video50-yuyv-compat-bridge.service" in target
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in v4l2
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in bridge
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in obs_bridge
