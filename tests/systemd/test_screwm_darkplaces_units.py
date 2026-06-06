from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
SCRIPTS_DIR = REPO_ROOT / "scripts"
INSTALL_UNITS = REPO_ROOT / "systemd" / "scripts" / "install-units.sh"
USER_PRESET = REPO_ROOT / "systemd" / "user-preset.d" / "hapax.preset"


def _read(unit_name: str) -> str:
    return (UNITS_DIR / unit_name).read_text(encoding="utf-8")


def test_darkplaces_v4l2_service_remains_runtime_guarded_and_uses_visible_xvfb_route() -> None:
    body = _read("hapax-darkplaces-v4l2.service")

    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in body
    assert "Wants=hapax-screwm-camera-gamepad.service" in body
    assert "hapax-screwm-drift-state-source.service" in body
    assert "hapax-screwm-imagination-source-publisher.service" in body
    assert "hapax-darkplaces-bridge.service" in body
    assert "hapax-quake-live-youtube.service" in body
    assert "hapax-quake-live-ward-atlas.service" in body
    assert "hapax-quake-live-aoa-atlas.service" in body
    assert "hapax-quake-live-reverie.service" in body
    assert "hapax-screwm-media-drift.service" in body
    assert "hapax-screwm-speech-wave-producer.service" in body
    assert (
        "After=hapax-screwm-media-drift.service hapax-quake-live-youtube.service "
        "hapax-quake-live-reverie.service "
        "hapax-quake-live-ward-atlas.service hapax-quake-live-aoa-atlas.service "
        "hapax-screwm-drift-state-source.service "
        "hapax-screwm-imagination-source-publisher.service\n"
    ) in body
    for role in (
        "brio-operator",
        "brio-room",
        "brio-synths",
        "brio-operator-ir",
        "brio-room-ir",
        "brio-synths-ir",
        "c920-desk",
        "c920-room",
        "c920-overhead",
    ):
        assert f"hapax-quake-live-camera@{role}.service" in body
    assert "Type=notify" in body
    assert "NotifyAccess=all" in body
    assert "WatchdogSec=30s" in body
    assert "TimeoutStartSec=180s" in body
    assert "TimeoutStopSec=3s" in body
    assert "KillMode=control-group" in body
    assert "SendSIGKILL=yes" in body
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
    assert "Environment=DARKPLACES_FPS=30" in body
    assert "Environment=HAPAX_DARKPLACES_V4L2_ENABLE=1" in body


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


def test_darkplaces_launchers_ensure_persistent_live_texture_binary() -> None:
    ensure = (SCRIPTS_DIR / "ensure-darkplaces-live-texture-build.sh").read_text(encoding="utf-8")

    assert "HAPAX_DARKPLACES_LIVE_TEXTURE_ROOT" in ensure
    assert "assets/quake/darkplaces/hapax-live-texture.patch" in ensure
    assert "$HOME/.cache/hapax/darkplaces-live-texture" in ensure
    assert "make -C" in ensure
    assert "sdl-release" in ensure
    assert "patch_sha256=" in ensure

    for launcher in ("darkplaces-v4l2-xvfb.sh", "darkplaces-v4l2-xorg.sh"):
        body = (SCRIPTS_DIR / launcher).read_text(encoding="utf-8")
        assert 'DARKPLACES_BIN="${HAPAX_DARKPLACES_BIN:-}"' in body
        assert "resolve_darkplaces_bin()" in body
        assert "ensure-darkplaces-live-texture-build.sh" in body
        assert 'DARKPLACES_BIN="$(resolve_darkplaces_bin)"' in body


def test_darkplaces_launchers_force_diagnostic_screen_postprocess_off() -> None:
    for launcher in ("darkplaces-v4l2-xvfb.sh", "darkplaces-v4l2-xorg.sh"):
        body = (SCRIPTS_DIR / launcher).read_text(encoding="utf-8")
        assert "+r_glsl_postprocess 0" in body
        assert "+r_glsl_postprocess_ruttetra_enable 0" in body
        assert '+r_glsl_postprocess_uservec1 "0 0 0 0"' in body
        assert '+r_glsl_postprocess_uservec2 "0 0 0 0"' in body
        assert '+r_glsl_postprocess_uservec3 "0 0 0 0"' in body
        assert '+r_glsl_postprocess_uservec4 "0 0 0 0"' in body
        assert "+set screwm_qc_screen_postprocess 0" in body


def test_darkplaces_live_texture_rebuild_path_watches_source_activation_patch() -> None:
    service = _read("hapax-darkplaces-live-texture-rebuild.service")
    path = _read("hapax-darkplaces-live-texture-rebuild.path")

    assert "WorkingDirectory=%h/.cache/hapax/source-activation/worktree" in service
    assert "ConditionPathExists=%h/.cache/hapax/source-activation/last-success-sha" in service
    assert (
        "ConditionPathExists=%h/.cache/hapax/source-activation/worktree/"
        "scripts/ensure-darkplaces-live-texture-build.sh"
    ) in service
    assert (
        "ConditionPathExists=%h/.cache/hapax/source-activation/worktree/"
        "assets/quake/darkplaces/hapax-live-texture.patch"
    ) in service
    assert (
        "ExecStart=%h/.cache/hapax/source-activation/worktree/"
        "scripts/ensure-darkplaces-live-texture-build.sh"
    ) in service
    assert "try-restart hapax-darkplaces-v4l2.service" in service
    assert "StartLimitIntervalSec=600" in service
    assert "%h/.cache/hapax/rebuild/worktree" not in service

    assert "PathChanged=%h/.cache/hapax/source-activation/current.json" not in path
    assert "PathChanged=%h/.cache/hapax/source-activation/last-success-sha" in path
    assert (
        "PathChanged=%h/.cache/hapax/source-activation/worktree/"
        "assets/quake/darkplaces/hapax-live-texture.patch"
    ) in path
    assert "\nPathExists=" not in path
    assert "Unit=hapax-darkplaces-live-texture-rebuild.service" in path
    assert "%h/.cache/hapax/rebuild/worktree" not in path


def test_darkplaces_live_texture_rebuild_path_is_enabled_by_deploy_defaults() -> None:
    install_units = INSTALL_UNITS.read_text(encoding="utf-8")
    preset = USER_PRESET.read_text(encoding="utf-8")

    assert "AUTO_ENABLE_PATHS=(" in install_units
    assert "hapax-darkplaces-live-texture-rebuild.path" in install_units
    assert 'systemctl --user enable --now "$path_name"' in install_units
    assert "enable hapax-darkplaces-live-texture-rebuild.path" in preset


def test_darkplaces_launchers_bind_youtube_camera_and_ward_atlas_textures() -> None:
    autoexec = (REPO_ROOT / "assets" / "quake" / "config" / "autoexec.cfg").read_text(
        encoding="utf-8"
    )
    for body in (
        autoexec,
        (SCRIPTS_DIR / "darkplaces-v4l2-xvfb.sh").read_text(encoding="utf-8"),
        (SCRIPTS_DIR / "darkplaces-v4l2-xorg.sh").read_text(encoding="utf-8"),
    ):
        assert "hapax_live_texture_enable 1" in body or "+hapax_live_texture_enable 1" in body
        assert "hapax_live_texture_name progs/aoa_sphere.mdl_0" in body or (
            "+hapax_live_texture_name progs/aoa_sphere.mdl_0" in body
        )
        assert "quake-live-yt.bgra" in body
        assert "hapax_live_texture_width 2048" in body or "+hapax_live_texture_width 2048" in body
        assert "hapax_live_texture_height 1024" in body or "+hapax_live_texture_height 1024" in body
        for slot, texture, frame in (
            ("2", "cam_bop", "quake-live-cam-brio-operator.bgra"),
            ("3", "cam_brm", "quake-live-cam-brio-room.bgra"),
            ("4", "cam_bsy", "quake-live-cam-brio-synths.bgra"),
            ("5", "cam_cdk", "quake-live-cam-c920-desk.bgra"),
            ("6", "cam_crm", "quake-live-cam-c920-room.bgra"),
            ("7", "cam_cov", "quake-live-cam-c920-overhead.bgra"),
        ):
            prefix = f"hapax_live_texture{slot}"
            assert f"{prefix}_enable 1" in body or f"+{prefix}_enable 1" in body
            assert f"{prefix}_name {texture}" in body or f"+{prefix}_name {texture}" in body
            assert frame in body
            assert f"{prefix}_width 1280" in body or f"+{prefix}_width 1280" in body
            assert f"{prefix}_height 720" in body or f"+{prefix}_height 720" in body
        assert "hapax_live_texture8_enable 1" in body or "+hapax_live_texture8_enable 1" in body
        assert "hapax_live_texture8_name ward_atlas" in body or (
            "+hapax_live_texture8_name ward_atlas" in body
        )
        assert "quake-live-ward-atlas.bgra" in body
        assert "hapax_live_texture8_width 2048" in body or "+hapax_live_texture8_width 2048" in body
        assert (
            "hapax_live_texture8_height 2304" in body or "+hapax_live_texture8_height 2304" in body
        )
        for slot, texture, frame in (
            ("9", "w09", "quake-live-ticker-grounding.bgra"),
            ("10", "w22", "quake-live-ticker-precedent.bgra"),
            ("11", "w27", "quake-live-ticker-chronicle.bgra"),
        ):
            prefix = f"hapax_live_texture{slot}"
            assert f"{prefix}_enable 1" in body or f"+{prefix}_enable 1" in body
            assert f"{prefix}_name {texture}" in body or f"+{prefix}_name {texture}" in body
            assert frame in body
            assert f"{prefix}_width 1344" in body or f"+{prefix}_width 1344" in body
            assert f"{prefix}_height 176" in body or f"+{prefix}_height 176" in body
        assert "hapax_live_texture12_enable 1" in body or "+hapax_live_texture12_enable 1" in body
        assert "hapax_live_texture12_name w05" in body or "+hapax_live_texture12_name w05" in body
        assert "quake-live-reverie.bgra" in body
        assert "hapax_live_texture12_width 960" in body or "+hapax_live_texture12_width 960" in body
        assert (
            "hapax_live_texture12_height 540" in body or "+hapax_live_texture12_height 540" in body
        )
        assert "hapax_live_texture13_enable 1" in body or "+hapax_live_texture13_enable 1" in body
        assert "hapax_live_texture13_name speech_wave" in body or (
            "+hapax_live_texture13_name speech_wave" in body
        )
        assert "quake-live-speech-wave.bgra" in body
        assert "hapax_live_texture13_width 512" in body or (
            "+hapax_live_texture13_width 512" in body
        )
        assert "hapax_live_texture13_height 128" in body or (
            "+hapax_live_texture13_height 128" in body
        )
        assert "hapax_live_texture14_enable 1" in body or "+hapax_live_texture14_enable 1" in body
        assert "hapax_live_texture14_name progs/aoa.mdl_0" in body or (
            "+hapax_live_texture14_name progs/aoa.mdl_0" in body
        )
        assert "quake-live-aoa-atlas.bgra" in body
        assert "hapax_live_texture14_width 2048" in body or (
            "+hapax_live_texture14_width 2048" in body
        )
        assert "hapax_live_texture14_height 2048" in body or (
            "+hapax_live_texture14_height 2048" in body
        )


def test_quake_live_media_services_feed_youtube_camera_and_ward_atlas_slots() -> None:
    youtube = _read("hapax-quake-live-youtube.service")
    camera = _read("hapax-quake-live-camera@.service")
    ticker = _read("hapax-quake-live-ticker@.service")
    atlas = _read("hapax-quake-live-ward-atlas.service")
    reverie = _read("hapax-quake-live-reverie.service")
    aoa_atlas = _read("hapax-quake-live-aoa-atlas.service")
    speech = _read("hapax-screwm-speech-wave-producer.service")

    assert "PartOf=hapax-visual-stack.target" in youtube
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in youtube
    assert "scripts/quake-live-media-source.py --source youtube" in youtube
    assert "--url-file /dev/shm/hapax-compositor/youtube-video-id.txt" in youtube
    assert "--youtube-fallback canary" in youtube
    assert "--fps 3 --width 2048 --height 1024 --projection sphere-front" in youtube
    assert "--sphere-front-aspect 1.7777777778" in youtube
    assert "--mask none --mask-background 0c0b0d" in youtube
    assert "--freshness-overlay" not in youtube
    assert "--output /dev/shm/hapax-compositor/quake-live-yt.bgra" in youtube
    assert "--meta /dev/shm/hapax-compositor/quake-live-yt.json" in youtube
    assert "Environment=HAPAX_QUAKE_GPU_DRIFT=1" in youtube
    assert "Environment=HAPAX_QUAKE_GPU_PROJECTION=1" in youtube
    assert "Environment=HAPAX_QUAKE_YOUTUBE_GPU_DECODE=1" in youtube
    assert "Restart=always" in youtube

    assert "PartOf=hapax-visual-stack.target" in camera
    assert "PartOf=hapax-visual-stack.target hapax-darkplaces-v4l2.service" in camera
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in camera
    assert "config/quake-live-cameras/%i.env" in camera
    assert "scripts/quake-live-media-source.py --source camera" in camera
    assert "--camera-role %i" in camera
    assert "--camera-fps ${HAPAX_QUAKE_LIVE_TEXTURE_INPUT_FPS}" in camera
    assert "--output ${HAPAX_QUAKE_LIVE_TEXTURE_OUTPUT}" in camera
    assert "--meta ${HAPAX_QUAKE_LIVE_TEXTURE_META}" in camera
    assert "Environment=HAPAX_QUAKE_GPU_DRIFT=1" in camera
    assert "Restart=always" in camera

    assert "Environment=HAPAX_QUAKE_TICKER_GPU_DRIFT=1" in ticker
    assert "scripts/quake-live-ticker-source.py" in ticker
    assert "--output ${HAPAX_QUAKE_TICKER_OUTPUT}" in ticker

    assert "PartOf=hapax-visual-stack.target hapax-darkplaces-v4l2.service" in atlas
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in atlas
    assert ".venv/bin/python %h/.cache/hapax/source-activation/worktree/" in atlas
    assert "scripts/quake-live-ward-atlas-source.py" in atlas
    assert "--width 2048 --height 2304 --columns 4" in atlas
    assert "--fps 0.1" in atlas
    assert "--cell-width 512 --cell-height 256" in atlas
    assert "--drift on --drift-intensity 1.6" in atlas
    assert "--output /dev/shm/hapax-compositor/quake-live-ward-atlas.bgra" in atlas
    assert "--meta /dev/shm/hapax-compositor/quake-live-ward-atlas.json" in atlas
    assert "Environment=HAPAX_QUAKE_WARD_ATLAS_GPU_DRIFT=1" in atlas
    assert "Restart=always" in atlas

    assert "PartOf=hapax-visual-stack.target hapax-darkplaces-v4l2.service" in reverie
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in reverie
    assert "Environment=HAPAX_QUAKE_REVERIE_GPU_DRIFT=1" in reverie
    assert "--require-file scripts/quake-live-reverie-source.py" in reverie
    assert "--require-file scripts/quake_media_drift.py" in reverie
    assert "scripts/quake-live-reverie-source.py --fps 4 --width 960 --height 540" in reverie
    assert "--input /dev/shm/hapax-sources/reverie.rgba" in reverie
    assert "--output /dev/shm/hapax-compositor/quake-live-reverie.bgra" in reverie
    assert "--meta /dev/shm/hapax-compositor/quake-live-reverie.json" in reverie

    assert "PartOf=hapax-visual-stack.target hapax-darkplaces-v4l2.service" in aoa_atlas
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in aoa_atlas
    assert "Environment=HAPAX_QUAKE_AOA_ATLAS_GPU_DRIFT=1" in aoa_atlas
    assert "--require-file scripts/quake-live-aoa-atlas-source.py" in aoa_atlas
    assert "scripts/quake-live-aoa-atlas-source.py --fps 4 --width 2048 --height 2048" in aoa_atlas
    assert "--columns 32 --cell-size 64" in aoa_atlas
    assert "--output /dev/shm/hapax-compositor/quake-live-aoa-atlas.bgra" in aoa_atlas
    assert "--meta /dev/shm/hapax-compositor/quake-live-aoa-atlas.json" in aoa_atlas
    assert "--controls /dev/shm/hapax-compositor/aoa-face-controls.json" in aoa_atlas

    assert "PartOf=hapax-visual-stack.target hapax-darkplaces-v4l2.service" in speech
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in speech
    assert "--require-file scripts/screwm-speech-wave-producer.py" in speech
    assert "scripts/screwm-speech-wave-producer.py" in speech
    assert ".venv/bin/python %h/.cache/hapax/source-activation/worktree/" in speech

    drift = _read("hapax-screwm-drift-state-source.service")
    assert "PartOf=hapax-visual-stack.target hapax-darkplaces-v4l2.service" in drift
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in drift
    assert "scripts/screwm-drift-state-source.py --fps 1" in drift
    assert "--effect-drift /dev/shm/hapax-visual/screwm-effect-drift-fallback-state.json" in drift

    source_publisher = _read("hapax-screwm-imagination-source-publisher.service")
    assert "PartOf=hapax-visual-stack.target hapax-darkplaces-v4l2.service" in source_publisher
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in source_publisher
    assert "--require-file scripts/screwm-imagination-source-publisher.py" in source_publisher
    assert (
        "scripts/screwm-imagination-source-publisher.py --fps 1 --width 320 --height 180"
        in source_publisher
    )
    assert "--ttl-ms 3000" in source_publisher

    config_dir = REPO_ROOT / "config" / "quake-live-cameras"
    expected = {
        "brio-operator": ("cam_bop", "quake-live-cam-brio-operator.bgra"),
        "brio-room": ("cam_brm", "quake-live-cam-brio-room.bgra"),
        "brio-synths": ("cam_bsy", "quake-live-cam-brio-synths.bgra"),
        "c920-desk": ("cam_cdk", "quake-live-cam-c920-desk.bgra"),
        "c920-room": ("cam_crm", "quake-live-cam-c920-room.bgra"),
        "c920-overhead": ("cam_cov", "quake-live-cam-c920-overhead.bgra"),
    }
    for role, (texture, frame) in expected.items():
        env = (config_dir / f"{role}.env").read_text(encoding="utf-8")
        assert f"HAPAX_QUAKE_CAMERA_ROLE={role}" in env
        assert f"HAPAX_QUAKE_LIVE_TEXTURE_NAME={texture}" in env
        assert frame in env
        assert "HAPAX_QUAKE_CAMERA_SIZE=1280x720" in env
        assert "HAPAX_QUAKE_CAMERA_FPS=10" in env
        if role.startswith("brio-"):
            assert "HAPAX_QUAKE_CAMERA_RESERVED_FOR_IR=1" in env
        assert "HAPAX_QUAKE_LIVE_TEXTURE_WIDTH=1280" in env
        assert "HAPAX_QUAKE_LIVE_TEXTURE_HEIGHT=720" in env
        assert "HAPAX_QUAKE_LIVE_TEXTURE_FPS=5" in env
        assert "HAPAX_QUAKE_LIVE_TEXTURE_INPUT_FPS=10" in env

    ir_expected = {
        "brio-operator-ir": (
            "ir_bop",
            "quake-live-ir-brio-operator.bgra",
            "usb-046d_Logitech_BRIO_5342C819-video-index2",
        ),
        "brio-room-ir": (
            "ir_brm",
            "quake-live-ir-brio-room.bgra",
            "usb-046d_Logitech_BRIO_43B0576A-video-index2",
        ),
        "brio-synths-ir": (
            "ir_bsy",
            "quake-live-ir-brio-synths.bgra",
            "usb-046d_Logitech_BRIO_9726C031-video-index2",
        ),
    }
    for role, (texture, frame, device_id) in ir_expected.items():
        env = (config_dir / f"{role}.env").read_text(encoding="utf-8")
        assert f"HAPAX_QUAKE_CAMERA_ROLE={role}" in env
        assert f"HAPAX_QUAKE_CAMERA_DEVICE=/dev/v4l/by-id/{device_id}" in env
        assert "HAPAX_QUAKE_CAMERA_FORMAT=gray" in env
        assert "HAPAX_QUAKE_CAMERA_SIZE=340x340" in env
        assert "HAPAX_QUAKE_CAMERA_FPS=10" in env
        assert f"HAPAX_QUAKE_LIVE_TEXTURE_NAME={texture}" in env
        assert frame in env
        assert "HAPAX_QUAKE_LIVE_TEXTURE_WIDTH=340" in env
        assert "HAPAX_QUAKE_LIVE_TEXTURE_HEIGHT=340" in env
        assert "HAPAX_QUAKE_LIVE_TEXTURE_FPS=6" in env
        assert "HAPAX_QUAKE_LIVE_TEXTURE_INPUT_FPS=10" in env


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
    assert 'V4L2_ENABLE="${HAPAX_DARKPLACES_V4L2_ENABLE:-1}"' in body
    assert 'if [ "$V4L2_ENABLE" = "1" ]; then' in body
    assert "need_cmd gst-launch-1.0" in body
    assert "notify_systemd --ready" in body
    assert "WATCHDOG=1" in body
    assert "HAPAX_DARKPLACES_WATCHDOG_INTERVAL_SECONDS" in body
    assert "DarkPlaces renderer running" in body
    assert (
        'Xvfb "$DISPLAY_NUM" -screen 0 "${WIDTH}x${HEIGHT}x24" -nolisten tcp -s 0 -dpms &' in body
    )
    assert 'v4l2-ctl -d "$DEVICE" --set-parm="$FPS"' in body
    assert 'ximagesrc display-name="$DISPLAY_NUM" use-damage=0 show-pointer=false' in body
    assert '! v4l2sink device="$DEVICE" sync=false &' in body
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

    assert "vector AOA_CENTER = '0 -555 224';" in defs
    assert "vector AOA_SPHERE_CENTER = '0 -555 224';" in defs
    assert "vector CAMERA_REVIEW_POS = '0 -2380 164';" in defs
    assert "vector CAMERA_REVIEW_TARGET = '0 -555 224';" in defs
    assert ".float scale;" in defs
    assert ".float alpha;" in defs
    assert ".vector colormod;" in defs
    assert ".float glow_size;" in defs
    assert "float EF_FULLBRIGHT = 512;" in defs
    assert "float EF_DOUBLESIDED = 32768;" in defs
    assert "float EF_ADDITIVE = 32;" in defs
    assert "float AOA_MODEL_SCALE = 1.0;" in defs
    assert "float AOA_SPHERE_MODEL_SCALE = 1.0;" in defs
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
    assert "coupling_read_effect_review_preset" in coupling
    assert 'fopen("data/effect-review-preset.txt", FILE_READ)' in coupling
    assert "coupling_apply_effect_review_preset" in coupling
    assert "coupling_screen_postprocess_enabled" in coupling
    assert "coupling_clear_screen_postprocess" in coupling
    assert 'cvar_set("r_glsl_postprocess", "0")' in coupling
    assert 'cvar_set("r_glsl_postprocess_uservec1"' in coupling
    assert "localcmd(cmd);" not in coupling
    assert "coupling_write_uservecs(0.04, 3.55" in coupling
    assert "coupling_write_uservecs(0.03, 1.90" in coupling
    assert "float base_rot = 0.0;" in coupling
    assert "coupling_voice_active * 1.5" in coupling
    assert "float aoa_drift_pressure = coupling_clamp_range(" in coupling
    assert (
        "aoa_entity.screwm_spin_y = base_rot + voice_boost + audio_boost + aoa_spin_boost;"
        in coupling
    )
    assert "aoa_entity.alpha = coupling_clamp_range" in coupling
    assert "aoa_entity.glow_size = coupling_clamp_range" in coupling
    assert "aoa_sphere_entity.screwm_spin_y = coupling_clamp_range" in coupling
    assert "aoa_sphere_entity.glow_size = coupling_clamp_range" in coupling
    assert "UserVec2: scan_field, edge_glow, posterize, sharpen" in autoexec
    assert "mortar_lines" not in autoexec
    assert "r_glsl_postprocess 0" in autoexec
    assert "set screwm_qc_screen_postprocess 0" in autoexec
    assert 'r_glsl_postprocess_uservec1 "0 0 0 0"' in autoexec
    assert 'r_glsl_postprocess_uservec2 "0 0 0 0"' in autoexec
    assert 'r_glsl_postprocess_uservec3 "0 0 0 0"' in autoexec
    assert 'cvar("screwm_player_noclip_control") > 0' in world
    assert "void(entity view) screwm_player_noclip_body" in world
    assert "void(entity view) screwm_follow_camera_body" in world
    assert 'camera_read_norm("data/camera-manual.txt", 0) > 0' in world
    assert "aoa_entity.scale = AOA_MODEL_SCALE;" in world
    assert "ent.angles_y = 180;" in world
    assert 'setmodel(aoa_sphere_entity, "progs/aoa_sphere.mdl");' in world
    assert "setorigin(aoa_sphere_entity, AOA_SPHERE_CENTER);" in world
    assert "aoa_entity.alpha = 0.16;" in world
    assert "aoa_entity.colormod = '0.86 0.92 1.02';" in world
    assert "aoa_entity.effects = aoa_entity.effects + EF_ADDITIVE;" in world
    assert "aoa_sphere_entity.screwm_spin_y = 0;" in world
    assert "screwm_player_noclip_body(self);" in world
    assert "screwm_follow_camera_body(self);" in world
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
    assert "--wait-for-device --wait-interval 1" in body
    assert "StartLimitIntervalSec=0" in body
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
    assert "hapax-screwm-media-drift.service" in target
    assert "hapax-quake-live-reverie.service" in target
    assert "hapax-quake-live-ward-atlas.service" in target
    assert "hapax-quake-live-aoa-atlas.service" in target
    assert "hapax-screwm-speech-wave-producer.service" in target
    assert "hapax-screwm-camera-gamepad.service" not in target
    assert "Wants=hapax-screwm-camera-gamepad.service" in v4l2
    assert "hapax-screwm-speech-wave-producer.service" in v4l2
    assert "hapax-darkplaces-bridge.service" in v4l2
    assert "Wants=hapax-screwm-media-drift.service" in v4l2
    assert "hapax-obs-video50-yuyv-compat-bridge.service" not in v4l2
    assert "hapax-obs-video50-yuyv-compat-bridge.service" not in target
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in v4l2
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in bridge
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in gamepad
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in obs_bridge


def test_screwm_gpu_services_use_darkplaces_runtime_marker_and_live_cutover() -> None:
    ward_atlas_gpu = _read("hapax-ward-atlas-gpu.service")
    media_drift = _read("hapax-screwm-media-drift.service")

    for body in (ward_atlas_gpu, media_drift):
        assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in body
        assert "ConditionPathExists=%h/.cache/hapax/enable-darkplaces-runtime" not in body

    assert "Environment=HAPAX_SCREWM_DRIFT_SLOTS=" in media_drift
    assert "After=hapax-secrets.service\n" in media_drift
    assert "After=hapax-secrets.service hapax-darkplaces-v4l2.service" not in media_drift
    assert "Before=hapax-darkplaces-v4l2.service" in media_drift
    assert "Environment=HAPAX_SCREWM_DRIFT_FULL_HASH_EVERY_N=10" in media_drift
    assert "Restart=always" in media_drift
    for slot in (
        "yt:2048x1024:1.6:sphere-front:1820x1024:0c0b0d",
        "cam-brio-operator:1280x720",
        "cam-brio-room:1280x720",
        "cam-brio-synths:1280x720",
        "cam-c920-desk:1280x720",
        "cam-c920-room:1280x720",
        "cam-c920-overhead:1280x720",
        "ward-atlas:2048x2304",
        "ticker-grounding:1344x176",
        "ticker-precedent:1344x176",
        "ticker-chronicle:1344x176",
        "reverie:960x540",
        "aoa-atlas:2048x2048:2.25",
    ):
        assert slot in media_drift
    assert "Environment=HAPAX_WARD_ATLAS_SLOTS=ward-atlas:2048x2304@2" in ward_atlas_gpu
    assert (
        "HAPAX_WARD_ATLAS_SLOTS=ward-atlas:2048x2304@2,ticker-grounding:1344x176@8,"
        "ticker-precedent:1344x176@8,ticker-chronicle:1344x176@8"
    ) in ward_atlas_gpu
    assert "# Environment=HAPAX_WARD_ATLAS_ACTIVE_SLOTS=ward-atlas" in ward_atlas_gpu
    assert "HAPAX_WARD_ATLAS_FPS" not in ward_atlas_gpu
    assert "HAPAX_WARD_ATLAS_REAL" not in ward_atlas_gpu
    assert "ExecStart=%h/.local/bin/screwm-ward-atlas" in ward_atlas_gpu
    assert "ExecStart=%h/.local/bin/screwm-media-drift" in media_drift


def test_screwm_audio_reactivity_taps_obs_bound_broadcast_source() -> None:
    body = _read("hapax-screwm-audio-reactivity.service")

    assert "Environment=HAPAX_SCREWM_AUDIO_TARGET=hapax-broadcast-normalized" in body
    assert "Environment=HAPAX_SCREWM_AUDIO_TARGET=hapax-broadcast-normalized-capture" not in body
    assert "--require-file scripts/screwm-audio-reactivity-source.py" in body
    assert "scripts/screwm-audio-reactivity-source.py" in body
