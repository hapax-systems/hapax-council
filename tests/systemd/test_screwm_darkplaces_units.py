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
    assert "Wants=hapax-screwm-camera-gamepad.service" in body
    assert "Type=notify" in body
    assert "NotifyAccess=all" in body
    assert "WatchdogSec=30s" in body
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
    assert "Environment=HAPAX_DARKPLACES_WATCHDOG_INTERVAL_SECONDS=10" in body
    assert "Environment=HAPAX_DARKPLACES_JOY_INDEX=1" in body
    assert "Environment=DARKPLACES_WIDTH=1920" in body
    assert "Environment=DARKPLACES_HEIGHT=1080" in body
    assert "Environment=DARKPLACES_FPS=60" in body


def test_darkplaces_launchers_use_native_xbox_joystick_input() -> None:
    for launcher in ("darkplaces-v4l2-xvfb.sh", "darkplaces-v4l2-xorg.sh"):
        body = (SCRIPTS_DIR / launcher).read_text(encoding="utf-8")
        assert 'JOY_INDEX="${HAPAX_DARKPLACES_JOY_INDEX:-1}"' in body
        assert "+joy_enable 1" in body
        assert '+joy_index "$JOY_INDEX"' in body
        assert "+joy_axisforward 1" in body
        assert "+joy_axisside 0" in body
        assert "+joy_axisyaw 3" in body
        assert "+joy_axispitch 4" in body
        assert "+joy_sensitivityforward -1" in body
        assert "+joy_deadzoneforward 0.12" in body
        assert "+cl_forwardspeed 360" in body


def test_darkplaces_xorg_launcher_disables_headless_screen_blanking() -> None:
    body = (SCRIPTS_DIR / "darkplaces-v4l2-xorg.sh").read_text(encoding="utf-8")

    assert "need_cmd systemd-notify" in body
    assert "notify_systemd --ready" in body
    assert "WATCHDOG=1" in body
    assert "HAPAX_DARKPLACES_WATCHDOG_INTERVAL_SECONDS" in body
    for expected in (
        'Option "BlankTime" "0"',
        'Option "StandbyTime" "0"',
        'Option "SuspendTime" "0"',
        'Option "OffTime" "0"',
        'Option "NoPM" "true"',
        'Option "DPMS" "false"',
        "-s 0 \\",
        "-dpms \\",
        "+viewsize 120",
        "+scr_viewsize 120",
        "+scr_centertime 0",
        "+scr_sbaralpha 0",
        "+sbar_alpha_bg 0",
        "+sbar_alpha_fg 0",
        "+sbar_hudselector 0",
        "+sbar_x 10000",
        "+sbar_y 10000",
        "+scr_infobar_height 0",
        "+scr_infobartime_off 0",
        "+scr_showbrand 0",
        "+cl_showfps 0",
        "+cl_showtime 0",
        "+cl_showdate 0",
        "+cl_showspeed 0",
        "+cl_shownet 0",
    ):
        assert expected in body


def test_darkplaces_xvfb_launcher_disables_headless_screen_blanking() -> None:
    body = (SCRIPTS_DIR / "darkplaces-v4l2-xvfb.sh").read_text(encoding="utf-8")

    assert "need_cmd systemd-notify" in body
    assert "notify_systemd --ready" in body
    assert "WATCHDOG=1" in body
    assert "HAPAX_DARKPLACES_WATCHDOG_INTERVAL_SECONDS" in body
    assert (
        'Xvfb "$DISPLAY_NUM" -screen 0 "${WIDTH}x${HEIGHT}x24" -nolisten tcp -s 0 -dpms &' in body
    )
    for expected in (
        "+viewsize 120",
        "+scr_viewsize 120",
        "+scr_centertime 0",
        "+scr_sbaralpha 0",
        "+sbar_alpha_bg 0",
        "+sbar_alpha_fg 0",
        "+sbar_hudselector 0",
        "+sbar_x 10000",
        "+sbar_y 10000",
        "+scr_infobar_height 0",
        "+scr_infobartime_off 0",
        "+scr_showbrand 0",
        "+cl_showfps 0",
        "+cl_showtime 0",
        "+cl_showdate 0",
        "+cl_showspeed 0",
        "+cl_shownet 0",
    ):
        assert expected in body


def test_darkplaces_camera_defaults_to_stable_review_position() -> None:
    defs = (REPO_ROOT / "assets" / "quake" / "qc" / "defs.qc").read_text(encoding="utf-8")
    camera = (REPO_ROOT / "assets" / "quake" / "qc" / "camera.qc").read_text(encoding="utf-8")
    coupling = (REPO_ROOT / "assets" / "quake" / "qc" / "coupling.qc").read_text(encoding="utf-8")
    autoexec = (REPO_ROOT / "assets" / "quake" / "config" / "autoexec.cfg").read_text(
        encoding="utf-8"
    )
    world = (REPO_ROOT / "assets" / "quake" / "qc" / "world.qc").read_text(encoding="utf-8")

    assert "vector AOA_CENTER = '0 -455 176';" in defs
    assert "vector CAMERA_REVIEW_POS = '0 -760 205';" in defs
    assert "vector CAMERA_REVIEW_TARGET = '0 -455 184';" in defs
    assert ".float scale;" in defs
    assert "float AOA_MODEL_SCALE = 0.62;" in defs
    assert "vector(vector v) vectoangles = #51;" in defs
    assert "ang = vectoangles(target - pos);" in camera
    assert 'if (cvar("screwm_camera_orbit") > 0)' in camera
    assert 'cvar("screwm_camera_file_control") > 0' in camera
    assert 'camera_read_norm("data/camera-manual.txt", 0) > 0' in camera
    assert 'camera_read_float("data/camera-origin-x.txt"' in camera
    assert 'camera_read_float("data/camera-pitch.txt"' in camera
    assert 'camera_read_float("data/camera-yaw.txt"' in camera
    assert "camera_apply_file_fov();" in camera
    assert "pos = CAMERA_REVIEW_POS;" in camera
    assert "CAMERA_ORBIT_PERIOD = 360.0;" in coupling
    assert "CAMERA_PERIOD = 120 + (1.0 - coupling_energy) * 30.0;" not in coupling
    assert "float base_rot = 3.0;" in coupling
    assert "coupling_voice_active * 8.0" in coupling
    assert "coupling_energy * 4.0" in coupling
    assert "UserVec2: mortar_lines, edge_glow, posterize, sharpen" in autoexec
    assert 'r_glsl_postprocess_uservec2 "0.05 0.18 0 0.03"' in autoexec
    assert 'cvar("screwm_player_noclip_control") > 0' in world
    assert "void(entity view) screwm_player_noclip_body" in world
    assert "aoa_entity.scale = AOA_MODEL_SCALE;" in world
    assert "screwm_player_noclip_body(self);" in world
    assert "setorigin(self, CAMERA_REVIEW_POS);" in world
    assert "self.angles = vectoangles(CAMERA_REVIEW_TARGET - CAMERA_REVIEW_POS);" in world


def test_darkplaces_state_bridge_follows_v4l2_renderer_unit() -> None:
    body = _read("hapax-darkplaces-bridge.service")

    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in body
    assert "PartOf=hapax-darkplaces.service hapax-darkplaces-v4l2.service" in body
    assert "After=hapax-darkplaces.service hapax-darkplaces-v4l2.service" in body
    assert "--require-file scripts/darkplaces-state-export.py" in body
    assert "WantedBy=hapax-darkplaces.service hapax-darkplaces-v4l2.service" in body


def test_screwm_camera_gamepad_service_is_opt_in_and_headless() -> None:
    body = _read("hapax-screwm-camera-gamepad.service")

    assert "PartOf=hapax-darkplaces-v4l2.service" in body
    assert "After=hapax-darkplaces-v4l2.service" in body
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in body
    assert "ConditionPathExists=%h/.config/hapax/enable-screwm-camera-gamepad" in body
    assert "--require-file scripts/screwm-camera-gamepad.py" in body
    assert "scripts/screwm-camera-gamepad.py" in body
    assert "--device /dev/input/js" not in body
    assert "WantedBy=hapax-darkplaces-v4l2.service" in body


def test_visual_stack_conditionally_wants_darkplaces_runtime_units() -> None:
    target = _read("hapax-visual-stack.target")
    v4l2 = _read("hapax-darkplaces-v4l2.service")
    bridge = _read("hapax-darkplaces-bridge.service")
    gamepad = _read("hapax-screwm-camera-gamepad.service")
    obs_bridge = _read("hapax-obs-video50-yuyv-compat-bridge.service")

    assert "hapax-darkplaces-v4l2.service" in target
    assert "hapax-darkplaces-bridge.service" in target
    assert "hapax-screwm-camera-gamepad.service" not in target
    assert "Wants=hapax-screwm-camera-gamepad.service" in v4l2
    assert "hapax-obs-video50-yuyv-compat-bridge.service" in target
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in v4l2
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in bridge
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in gamepad
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in obs_bridge
