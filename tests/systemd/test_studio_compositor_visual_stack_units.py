from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
STUDIO = UNITS_DIR / "studio-compositor.service"
BRIDGE = UNITS_DIR / "hapax-v4l2-bridge.service"
BRIDGE_WATCHDOG = UNITS_DIR / "hapax-v4l2-bridge-watchdog.service"
BRIDGE_WATCHDOG_TIMER = UNITS_DIR / "hapax-v4l2-bridge-watchdog.timer"
VIDEO42_GUARD = UNITS_DIR / "hapax-video42-format-guard.service"
OBS = UNITS_DIR / "hapax-obs-livestream.service"
OBS_SOURCE_RESET = UNITS_DIR / "hapax-obs-v4l2-source-reset.service"
OBS_SOURCE_RESET_VIDEO52_DROPIN = (
    UNITS_DIR / "hapax-obs-v4l2-source-reset.service.d" / "zzzz-screwm-quake-video52.conf"
)
SCREWM_OBS_MEDIA_STREAM = UNITS_DIR / "hapax-darkplaces-obs-media-stream.service"
SCREWM_OBS_LIVESTREAM = UNITS_DIR / "hapax-obs-screwm-livestream.service"
LIVE_SURFACE_GUARD = UNITS_DIR / "hapax-live-surface-guard.service"
RTSP_LOOPBACK_WATCHDOG = UNITS_DIR / "hapax-rtsp-loopback-watchdog.service"
RTSP_LOOPBACK_WATCHDOG_TIMER = UNITS_DIR / "hapax-rtsp-loopback-watchdog.timer"
HLS_NO_CACHE = UNITS_DIR / "hapax-hls-no-cache.service"
REVERIE = UNITS_DIR / "hapax-reverie.service"
PARAMETRIC_HEARTBEAT = UNITS_DIR / "hapax-parametric-modulation-heartbeat.service"
LAYOUT_MODE_DROPIN = UNITS_DIR / "studio-compositor.service.d" / "layout-mode-persist.conf"
MALLOC_ARENA_DROPIN = UNITS_DIR / "studio-compositor.service.d" / "malloc-arena.conf"
SCREWM_QUAKE_LAYOUT = REPO_ROOT / "config" / "compositor-layouts" / "screwm-quake.json"
SCREWM_V4L2_BRIDGE_DROPIN = (
    UNITS_DIR / "hapax-v4l2-bridge.service.d" / "zzzz-screwm-quake-primary.conf"
)
OBS_YUYV_BRIDGE = UNITS_DIR / "hapax-obs-video50-yuyv-compat-bridge.service"
SOURCE_ROOT = "%h/.cache/hapax/source-activation/worktree"


def _load_unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment]
    parser.read(path, encoding="utf-8")
    return parser


def _active_unit_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _raw_keys(path: Path, section: str, key: str) -> list[str]:
    in_section = False
    values: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            in_section = line == f"[{section}]"
            continue
        if not in_section or not line or line.startswith("#") or "=" not in line:
            continue
        current_key, _, value = line.partition("=")
        if current_key.strip() == key:
            values.append(value.strip())
    return values


def test_studio_compositor_runs_from_activation_worktree() -> None:
    parser = _load_unit(STUDIO)
    assert parser.get("Service", "WorkingDirectory") == SOURCE_ROOT
    assert parser.get("Service", "ExecStart").startswith(f"{SOURCE_ROOT}/.venv/bin/python")
    assert parser.get("Service", "Environment", fallback="") is not None
    lines = _active_unit_lines(STUDIO)
    execution_lines = [
        line
        for line in lines
        if line.startswith(("ExecStart=", "ExecStartPre=", "ExecStopPost=", "WorkingDirectory="))
    ]
    assert execution_lines
    assert all("%h/projects/hapax-council" not in line for line in execution_lines)
    assert any("hapax-compositor-runtime-source-check" in line for line in execution_lines)
    assert any("hapax-v4l2-video42-format-guard --verify-only" in line for line in lines)
    assert any("v4l2-bridge.sock*" in line and "-delete" in line for line in execution_lines)
    assert any("HAPAX_COMPOSITOR_LAYOUT_PATH=" in line for line in lines)


def test_reverie_and_parametric_heartbeat_run_from_activation_worktree() -> None:
    for unit in (REVERIE, PARAMETRIC_HEARTBEAT):
        parser = _load_unit(unit)
        assert parser.get("Service", "WorkingDirectory") == SOURCE_ROOT
        assert parser.get("Service", "ExecStart").startswith(f"{SOURCE_ROOT}/.venv/bin/python")
        exec_start_pre = "\n".join(_raw_keys(unit, "Service", "ExecStartPre"))
        assert "hapax-compositor-runtime-source-check" in exec_start_pre
        lines = _active_unit_lines(unit)
        execution_lines = [
            line
            for line in lines
            if line.startswith(("ExecStart=", "ExecStartPre=", "WorkingDirectory="))
        ]
        assert all("%h/projects/hapax-council" not in line for line in execution_lines)
        assert any(f"PYTHONPATH={SOURCE_ROOT}" in line for line in lines)


def test_studio_compositor_starts_bridge_sidecar() -> None:
    parser = _load_unit(STUDIO)
    wants = parser.get("Unit", "Wants")
    requires = parser.get("Unit", "Requires")
    after = parser.get("Unit", "After")
    assert "hapax-v4l2-bridge.service" in wants
    assert "hapax-live-surface-guard.service" in wants
    assert "hapax-hls-no-cache.service" in wants
    assert "hapax-obs-v4l2-source-reset.service" not in wants
    assert "hapax-video42-format-guard.service" in requires
    assert "hapax-video42-format-guard.service" in after
    assert "hapax-hls-no-cache.service" in after


def test_screwm_quake_runtime_skips_legacy_studio_compositor() -> None:
    lines = _active_unit_lines(STUDIO)

    assert "ConditionPathExists=!%h/.config/hapax/enable-darkplaces-runtime" in lines
    assert not (
        UNITS_DIR / "studio-compositor.service.d" / "zzzz-screwm-quake-primary.conf"
    ).exists()
    assert "hapax-obs-video50-yuyv-compat-bridge.service" not in (
        REPO_ROOT / "systemd" / "units" / "hapax-visual-stack.target"
    ).read_text(encoding="utf-8")
    assert "hapax-darkplaces-obs-media-stream.service" in (
        REPO_ROOT / "systemd" / "units" / "hapax-visual-stack.target"
    ).read_text(encoding="utf-8")


def test_screwm_quake_layout_keeps_ward_surface_inside_darkplaces() -> None:
    from shared.compositor_model import Layout

    layout = Layout.model_validate_json(SCREWM_QUAKE_LAYOUT.read_text(encoding="utf-8"))

    assert layout.name == "screwm-quake"
    assert {source.id for source in layout.sources} == {"darkplaces"}
    assert layout.assignments == []
    assert {surface.geometry.kind for surface in layout.surfaces} == {"video_out"}


def test_screwm_v4l2_bridge_profile_matches_runtime_format_contract() -> None:
    lines = _active_unit_lines(SCREWM_V4L2_BRIDGE_DROPIN)

    for expected in (
        "TimeoutStartSec=120s",
        "Environment=HAPAX_V4L2_BRIDGE_ENABLED=1",
        "Environment=HAPAX_V4L2_BRIDGE_WIDTH=640",
        "Environment=HAPAX_V4L2_BRIDGE_HEIGHT=480",
        "Environment=HAPAX_V4L2_BRIDGE_RAW_FORMAT=BGRx",
        "Environment=HAPAX_V4L2_BRIDGE_PIXEL_FORMAT=BGR4",
        "Environment=HAPAX_V4L2_BRIDGE_WAIT_SECONDS=90",
        "Environment=HAPAX_V4L2_VIDEO42_PIXEL_FORMAT=BGR4",
    ):
        assert expected in lines


def test_obs_video50_bridge_is_guarded_as_manual_fallback() -> None:
    parser = _load_unit(OBS_YUYV_BRIDGE)

    assert parser.get("Unit", "ConditionPathExists") == "/usr/bin/ffmpeg"
    unit_lines = _active_unit_lines(OBS_YUYV_BRIDGE)
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in unit_lines
    assert "ConditionPathExists=/dev/video52" in unit_lines
    assert "ConditionPathExists=/dev/video50" in unit_lines
    assert parser.get("Unit", "Conflicts") == "studio-fx-output.service"
    assert parser.get("Unit", "After") == "hapax-darkplaces-v4l2.service"
    assert not parser.has_option("Unit", "Wants")
    assert parser.get("Unit", "PartOf") == "hapax-darkplaces-v4l2.service"
    assert parser.get("Service", "TimeoutStopSec") == "3s"
    assert parser.get("Service", "KillMode") == "control-group"
    assert parser.get("Service", "SendSIGKILL") == "yes"
    assert "width=1920,height=1080,pixelformat=YUYV" in "\n".join(unit_lines)
    assert "--set-parm=60" in "\n".join(unit_lines)
    assert "-c sustain_framerate=1" in "\n".join(unit_lines)
    exec_start = parser.get("Service", "ExecStart")
    assert "-input_format yuyv422" in exec_start
    assert "-video_size 1920x1080" in exec_start
    assert "-framerate 60" in exec_start
    assert "-i /dev/video52" in exec_start
    assert "-vf fps=60" in exec_start
    assert "-pix_fmt yuyv422 -r 60 /dev/video50" in exec_start
    assert not parser.has_section("Install")


def test_screwm_darkplaces_obs_media_stream_publishes_x11_as_udp_mpegts() -> None:
    parser = _load_unit(SCREWM_OBS_MEDIA_STREAM)
    lines = _active_unit_lines(SCREWM_OBS_MEDIA_STREAM)
    script = REPO_ROOT / "scripts" / "darkplaces-obs-media-stream.sh"
    script_text = script.read_text(encoding="utf-8")

    assert parser.get("Unit", "After") == "hapax-darkplaces-v4l2.service"
    assert parser.get("Unit", "Wants") == "hapax-darkplaces-v4l2.service"
    assert parser.get("Unit", "PartOf") == (
        "hapax-darkplaces-v4l2.service hapax-visual-stack.target"
    )
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in lines
    assert parser.get("Service", "WorkingDirectory") == SOURCE_ROOT
    assert "hapax-compositor-runtime-source-check" in parser.get("Service", "ExecStartPre")
    assert parser.get("Service", "ExecStart").endswith("scripts/darkplaces-obs-media-stream.sh\"'")
    assert "Environment=HAPAX_DARKPLACES_DISPLAY=:82" in lines
    assert (
        "Environment=HAPAX_DARKPLACES_OBS_MEDIA_OUTPUT_URL=udp://127.0.0.1:30552?pkt_size=1316"
        in lines
    )
    assert "Environment=HAPAX_DARKPLACES_OBS_MEDIA_ENCODER=auto" in lines
    assert "format=yuv420p" in script_text
    assert "HAPAX_DARKPLACES_OBS_MEDIA_ENCODER" in script_text
    assert "-c:v h264_nvenc" in script_text
    assert "-zerolatency 1" in script_text
    assert "-c:v libx264" in script_text
    assert "repeat-headers=1" in script_text
    assert "-f mpegts" in script_text
    assert script.exists()
    assert script.stat().st_mode & 0o100


def test_screwm_obs_livestream_uses_ffmpeg_media_source_instead_of_v4l2() -> None:
    parser = _load_unit(SCREWM_OBS_LIVESTREAM)
    lines = _active_unit_lines(SCREWM_OBS_LIVESTREAM)
    exec_start_post = parser.get("Service", "ExecStartPost")

    assert parser.get("Unit", "After") == (
        "hapax-darkplaces-v4l2.service hapax-darkplaces-obs-media-stream.service"
    )
    assert parser.get("Unit", "Wants") == (
        "hapax-darkplaces-v4l2.service hapax-darkplaces-obs-media-stream.service"
    )
    assert parser.get("Unit", "Conflicts") == "hapax-obs-livestream.service"
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in lines
    assert parser.get("Service", "ExecStart") == (
        "/usr/bin/obs --profile LegomenaLive --collection Untitled --scene Scene --startstreaming"
    )
    assert "hapax-obs-ffmpeg-source-ensure" in parser.get("Service", "ExecStartPre")
    assert "hapax-obs-ffmpeg-source-ensure" in exec_start_post
    assert '--source-name "DarkPlaces Screwm Media"' in exec_start_post
    assert (
        '--input-url "udp://127.0.0.1:30552?fifo_size=1000000&overrun_nonfatal=1"'
        in exec_start_post
    )
    assert '--disable-source "Video Capture Device (V4L2)"' in exec_start_post
    assert "studio-compositor.service" not in parser.get("Unit", "After")
    assert "hapax-v4l2-video42-format-guard" not in "\n".join(lines)


def test_video42_format_guard_runs_from_activation_worktree() -> None:
    parser = _load_unit(VIDEO42_GUARD)
    assert parser.get("Unit", "Before") == (
        "studio-compositor.service hapax-v4l2-bridge.service hapax-obs-livestream.service"
    )
    assert parser.get("Unit", "ConditionPathExists") == "/dev/video42"
    assert parser.get("Service", "Type") == "oneshot"
    assert parser.get("Service", "RemainAfterExit") == "yes"
    assert parser.get("Service", "WorkingDirectory") == SOURCE_ROOT
    assert parser.get("Service", "ExecStart") == (
        f"{SOURCE_ROOT}/scripts/hapax-v4l2-video42-format-guard"
    )
    assert "hapax-compositor-runtime-source-check" in parser.get("Service", "ExecStartPre")


def test_v4l2_bridge_runs_from_activation_worktree_and_is_supervised_by_studio() -> None:
    parser = _load_unit(BRIDGE)
    assert parser.get("Unit", "Requires") == (
        "hapax-video42-format-guard.service studio-compositor.service"
    )
    assert parser.get("Unit", "After") == (
        "hapax-video42-format-guard.service studio-compositor.service"
    )
    assert parser.get("Unit", "BindsTo") == "studio-compositor.service"
    assert parser.get("Unit", "PartOf") == "studio-compositor.service"
    assert parser.get("Unit", "ConditionPathExists") == f"{SOURCE_ROOT}/scripts/hapax-v4l2-bridge"
    assert parser.get("Service", "WorkingDirectory") == SOURCE_ROOT
    assert parser.get("Service", "ExecStart").startswith(f"{SOURCE_ROOT}/scripts/hapax-v4l2-bridge")
    exec_start_pre = "\n".join(_raw_keys(BRIDGE, "Service", "ExecStartPre"))
    assert "hapax-compositor-runtime-source-check" in exec_start_pre
    assert "hapax-v4l2-video42-format-guard --verify-only" in exec_start_pre
    assert parser.get("Service", "Restart") == "on-failure"
    lines = _active_unit_lines(BRIDGE)
    assert any("HAPAX_V4L2_BRIDGE_WAIT_SECONDS=60" in line for line in lines)
    assert any("HAPAX_V4L2_BRIDGE_ENABLED=1" in line for line in lines)


def test_v4l2_bridge_watchdog_runs_from_activation_worktree() -> None:
    parser = _load_unit(BRIDGE_WATCHDOG)
    assert parser.get("Service", "Type") == "oneshot"
    assert parser.get("Service", "WorkingDirectory") == SOURCE_ROOT
    assert parser.get("Unit", "ConditionPathExists") == (
        f"{SOURCE_ROOT}/scripts/hapax-v4l2-bridge-watchdog"
    )
    assert parser.get("Service", "ExecStart").startswith(
        f"{SOURCE_ROOT}/scripts/hapax-v4l2-bridge-watchdog --apply"
    )
    assert (
        "--textfile-path %h/.local/share/node_exporter/textfile_collector/"
        "hapax-v4l2-bridge-watchdog.prom"
    ) in parser.get("Service", "ExecStart")
    assert f"PYTHONPATH={SOURCE_ROOT}" in "\n".join(_active_unit_lines(BRIDGE_WATCHDOG))
    assert "hapax-compositor-runtime-source-check" in parser.get("Service", "ExecStartPre")
    assert "studio-compositor.service" in parser.get("Unit", "After")
    assert "hapax-v4l2-bridge.service" in parser.get("Unit", "After")


def test_v4l2_bridge_watchdog_timer_polls_at_incident_cadence() -> None:
    parser = _load_unit(BRIDGE_WATCHDOG_TIMER)
    assert parser.get("Timer", "OnUnitActiveSec") == "10"
    assert parser.get("Timer", "AccuracySec") == "1s"
    assert parser.get("Install", "WantedBy") == "timers.target"


def test_simple_bridge_unit_does_not_claim_systemd_watchdog_without_sd_notify() -> None:
    parser = _load_unit(BRIDGE)
    assert parser.get("Service", "Type") == "simple"
    assert parser.get("Service", "WatchdogSec", fallback=None) is None


def test_obs_v4l2_source_reset_runs_from_activation_worktree_with_notify_watchdog() -> None:
    parser = _load_unit(OBS_SOURCE_RESET)
    assert parser.get("Unit", "After") == (
        "pipewire.service hapax-darkplaces-v4l2.service hapax-obs-livestream.service"
    )
    assert not parser.has_option("Unit", "Wants")
    assert parser.get("Unit", "PartOf") == "hapax-visual-stack.target"
    assert parser.get("Unit", "ConditionPathExists") == (
        f"{SOURCE_ROOT}/scripts/hapax-obs-v4l2-source-reset"
    )
    assert parser.get("Service", "Type") == "notify"
    assert parser.get("Service", "NotifyAccess") == "main"
    assert parser.get("Service", "WorkingDirectory") == SOURCE_ROOT
    assert parser.get("Service", "WatchdogSec") == "120"
    assert parser.get("Service", "ExecStart").startswith(
        f"{SOURCE_ROOT}/scripts/hapax-obs-v4l2-source-reset"
    )
    assert '--source-name "Video Capture Device (V4L2)"' in parser.get("Service", "ExecStart")
    assert "--poll-interval 15" in parser.get("Service", "ExecStart")
    assert "--stall-threshold 60" in parser.get("Service", "ExecStart")
    assert "--reset-cooldown 60" in parser.get("Service", "ExecStart")
    assert "--device-id /dev/video50" in parser.get("Service", "ExecStart")
    assert "--resolution 1920x1080" in parser.get("Service", "ExecStart")
    assert "--framerate 30" in parser.get("Service", "ExecStart")
    assert "--pixelformat YUYV" in parser.get("Service", "ExecStart")
    assert "--disable-buffering" in parser.get("Service", "ExecStart")
    assert "--auto-reset-input" in parser.get("Service", "ExecStart")
    assert "--producer-service" not in parser.get("Service", "ExecStart")
    assert "hapax-obs-video50-yuyv-compat-bridge.service" not in parser.get(
        "Service",
        "ExecStart",
    )
    assert "--producer-restart-after-obs-resets" not in parser.get("Service", "ExecStart")
    assert "--obs-log-v4l2-errors" in parser.get("Service", "ExecStart")
    assert "--ignore-static-screenshot-stalls" in parser.get("Service", "ExecStart")
    assert "--max-static-ignore-seconds 75" in parser.get("Service", "ExecStart")
    assert "--screenshot-width 160" in parser.get("Service", "ExecStart")
    assert "--screenshot-height 90" in parser.get("Service", "ExecStart")
    assert parser.get("Service", "Restart") == "no"
    assert "hapax-compositor-runtime-source-check" in parser.get("Service", "ExecStartPre")
    lines = _active_unit_lines(OBS_SOURCE_RESET)
    assert all("%h/projects/hapax-council" not in line for line in lines)


def test_screwm_obs_v4l2_reset_dropin_pins_obs_to_direct_darkplaces_video52() -> None:
    lines = _active_unit_lines(OBS_SOURCE_RESET_VIDEO52_DROPIN)
    joined = "\n".join(lines)

    assert "ConditionPathExists=!%h/.config/hapax/enable-darkplaces-runtime" in lines
    assert "ExecStart=" in lines
    assert "--poll-interval 15" in joined
    assert "--stall-threshold 60" in joined
    assert "--device-id /dev/video52" in joined
    assert "--framerate 30" in joined
    assert "--pixelformat YUYV" in joined
    assert "--producer-service hapax-darkplaces-v4l2.service" in joined
    assert "--obs-log-v4l2-errors" not in joined
    assert "--ignore-static-screenshot-stalls" in joined
    assert "--producer-restart-after-obs-resets 0" in joined
    assert "--max-static-ignore-seconds 0" in joined
    assert "--recreate-input-on-reset" in joined
    assert "--screenshot-width 160" in joined
    assert "--screenshot-height 90" in joined
    assert "--device-id /dev/video50" not in joined
    assert "--pixelformat NV12" not in joined
    assert "--obs-log-v4l2-errors" not in joined
    assert "--recreate-input-on-reset" in joined
    assert "--producer-service hapax-darkplaces-v4l2.service" in joined
    assert "--producer-restart-after-obs-resets 0" in joined
    assert "--max-static-ignore-seconds 0" in joined
    assert "--ignore-static-screenshot-stalls" in joined
    assert "--prom-path %h/.local/share/node_exporter/textfile_collector/" in joined


def test_live_surface_guard_runs_from_activation_worktree() -> None:
    parser = _load_unit(LIVE_SURFACE_GUARD)
    assert parser.get("Unit", "After") == "studio-compositor.service"
    assert not parser.has_option("Unit", "Wants")
    assert parser.get("Service", "WorkingDirectory") == SOURCE_ROOT
    assert parser.get("Service", "ExecStart").startswith(f"{SOURCE_ROOT}/.venv/bin/python")
    assert "agents.live_surface_guard" in parser.get("Service", "ExecStart")
    assert "--require-hls" not in parser.get("Service", "ExecStart")
    assert "--require-obs-decoder" in parser.get("Service", "ExecStart")
    assert "--poll-interval 5" in parser.get("Service", "ExecStart")
    assert '--obs-source-name "Video Capture Device (V4L2)"' in parser.get(
        "Service",
        "ExecStart",
    )
    assert (
        "--textfile-path %h/.local/share/node_exporter/textfile_collector/"
        "hapax-live-surface-guard.prom"
    ) in parser.get("Service", "ExecStart")
    assert parser.get("Service", "EnvironmentFile") == "-%t/hapax-secrets.env"
    assert "hapax-compositor-runtime-source-check" in parser.get("Service", "ExecStartPre")
    lines = _active_unit_lines(LIVE_SURFACE_GUARD)
    assert all("%h/projects/hapax-council" not in line for line in lines)


def test_rtsp_loopback_watchdog_runs_from_activation_worktree() -> None:
    parser = _load_unit(RTSP_LOOPBACK_WATCHDOG)
    assert parser.get("Service", "Type") == "oneshot"
    assert parser.get("Service", "WorkingDirectory") == SOURCE_ROOT
    assert parser.get("Unit", "ConditionPathExists") == (
        f"{SOURCE_ROOT}/scripts/hapax-rtsp-loopback-watchdog"
    )
    assert parser.get("Service", "ExecStart").startswith(
        f"{SOURCE_ROOT}/scripts/hapax-rtsp-loopback-watchdog --apply"
    )
    assert (
        "--textfile-path %h/.local/share/node_exporter/textfile_collector/"
        "hapax-rtsp-loopback-watchdog.prom"
    ) in parser.get("Service", "ExecStart")
    assert f"PYTHONPATH={SOURCE_ROOT}" in "\n".join(_active_unit_lines(RTSP_LOOPBACK_WATCHDOG))
    assert "hapax-compositor-runtime-source-check" in parser.get("Service", "ExecStartPre")
    assert "hapax-rtsp-pi4-brio.service" in parser.get("Unit", "After")
    assert "hapax-rtsp-pi5-c920.service" in parser.get("Unit", "After")


def test_rtsp_loopback_watchdog_timer_polls_at_incident_cadence() -> None:
    parser = _load_unit(RTSP_LOOPBACK_WATCHDOG_TIMER)
    assert parser.get("Timer", "OnUnitActiveSec") == "10"
    assert parser.get("Timer", "AccuracySec") == "1s"
    assert parser.get("Install", "WantedBy") == "timers.target"


def test_hls_no_cache_service_runs_from_activation_worktree() -> None:
    parser = _load_unit(HLS_NO_CACHE)
    assert parser.get("Service", "WorkingDirectory") == SOURCE_ROOT
    assert parser.get("Service", "ExecStart").startswith(f"{SOURCE_ROOT}/.venv/bin/python")
    assert "agents.live_surface_guard.hls_no_cache_server" in parser.get(
        "Service",
        "ExecStart",
    )
    assert "--port 8988" in parser.get("Service", "ExecStart")
    lines = _active_unit_lines(HLS_NO_CACHE)
    assert all("%h/projects/hapax-council" not in line for line in lines)


def test_runtime_source_check_script_exists_and_is_executable() -> None:
    script = REPO_ROOT / "scripts" / "hapax-compositor-runtime-source-check"
    assert script.exists()
    assert script.stat().st_mode & 0o100


def test_video42_format_guard_script_exists_and_is_executable() -> None:
    script = REPO_ROOT / "scripts" / "hapax-v4l2-video42-format-guard"

    assert script.exists()
    assert script.stat().st_mode & 0o100


def test_hls_no_cache_wrapper_exists_and_is_executable() -> None:
    script = REPO_ROOT / "scripts" / "hapax-hls-no-cache-server"

    assert script.exists()
    assert script.stat().st_mode & 0o100


def test_obs_livestream_unit_orders_after_guard_and_compositor() -> None:
    parser = _load_unit(OBS)
    assert parser.get("Unit", "Requires") == (
        "hapax-video42-format-guard.service studio-compositor.service"
    )
    assert parser.get("Unit", "After") == (
        "hapax-video42-format-guard.service studio-compositor.service"
    )
    assert parser.get("Service", "ExecStart") == (
        "/usr/bin/obs --profile LegomenaLive --collection Untitled --scene Scene --startstreaming"
    )
    exec_start_pre = "\n".join(_raw_keys(OBS, "Service", "ExecStartPre"))
    assert "hapax-compositor-runtime-source-check" in exec_start_pre
    assert "hapax-v4l2-video42-format-guard --verify-only" in exec_start_pre
    assert "hapax-live-surface-preflight --require-hls" in exec_start_pre


def test_layout_mode_persistence_runs_from_activation_worktree() -> None:
    parser = _load_unit(LAYOUT_MODE_DROPIN)
    assert parser.get("Service", "ExecStartPost") == (
        f"{SOURCE_ROOT}/scripts/studio-compositor-post-start.sh"
    )
    assert parser.get("Service", "ExecStop") == (
        f"{SOURCE_ROOT}/scripts/studio-compositor-persist-mode.sh"
    )
    lines = _active_unit_lines(LAYOUT_MODE_DROPIN)
    assert all("%h/projects/hapax-council" not in line for line in lines)


def test_layout_mode_persistence_scripts_exist_and_are_executable() -> None:
    for name in ("studio-compositor-post-start.sh", "studio-compositor-persist-mode.sh"):
        script = REPO_ROOT / "scripts" / name
        assert script.exists()
        assert script.stat().st_mode & 0o100


def test_studio_compositor_constrains_glibc_arenas() -> None:
    parser = _load_unit(MALLOC_ARENA_DROPIN)
    assert parser.get("Service", "Environment") == "MALLOC_ARENA_MAX=2"
