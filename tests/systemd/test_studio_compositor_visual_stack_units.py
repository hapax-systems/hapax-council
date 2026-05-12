from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
STUDIO = UNITS_DIR / "studio-compositor.service"
BRIDGE = UNITS_DIR / "hapax-v4l2-bridge.service"
VIDEO42_GUARD = UNITS_DIR / "hapax-video42-format-guard.service"
OBS = UNITS_DIR / "hapax-obs-livestream.service"
OBS_SOURCE_RESET = UNITS_DIR / "hapax-obs-v4l2-source-reset.service"
LIVE_SURFACE_GUARD = UNITS_DIR / "hapax-live-surface-guard.service"
HLS_NO_CACHE = UNITS_DIR / "hapax-hls-no-cache.service"
LAYOUT_MODE_DROPIN = UNITS_DIR / "studio-compositor.service.d" / "layout-mode-persist.conf"
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


def test_studio_compositor_starts_bridge_sidecar() -> None:
    parser = _load_unit(STUDIO)
    wants = parser.get("Unit", "Wants")
    requires = parser.get("Unit", "Requires")
    after = parser.get("Unit", "After")
    assert "hapax-v4l2-bridge.service" in wants
    assert "hapax-live-surface-guard.service" in wants
    assert "hapax-hls-no-cache.service" in wants
    assert "hapax-obs-v4l2-source-reset.service" in wants
    assert "hapax-video42-format-guard.service" in requires
    assert "hapax-video42-format-guard.service" in after
    assert "hapax-hls-no-cache.service" in after


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


def test_simple_bridge_unit_does_not_claim_systemd_watchdog_without_sd_notify() -> None:
    parser = _load_unit(BRIDGE)
    assert parser.get("Service", "Type") == "simple"
    assert parser.get("Service", "WatchdogSec", fallback=None) is None


def test_obs_v4l2_source_reset_runs_from_activation_worktree_with_notify_watchdog() -> None:
    parser = _load_unit(OBS_SOURCE_RESET)
    assert parser.get("Unit", "After") == (
        "pipewire.service studio-compositor.service hapax-obs-livestream.service"
    )
    assert parser.get("Unit", "PartOf") == "studio-compositor.service"
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
    assert "--reset-cooldown 60" in parser.get("Service", "ExecStart")
    assert "hapax-compositor-runtime-source-check" in parser.get("Service", "ExecStartPre")
    lines = _active_unit_lines(OBS_SOURCE_RESET)
    assert all("%h/projects/hapax-council" not in line for line in lines)


def test_live_surface_guard_runs_from_activation_worktree() -> None:
    parser = _load_unit(LIVE_SURFACE_GUARD)
    assert parser.get("Service", "WorkingDirectory") == SOURCE_ROOT
    assert parser.get("Service", "ExecStart").startswith(f"{SOURCE_ROOT}/.venv/bin/python")
    assert "agents.live_surface_guard" in parser.get("Service", "ExecStart")
    assert "--require-obs-decoder" in parser.get("Service", "ExecStart")
    assert (
        "--textfile-path %h/.local/share/node_exporter/textfile_collector/"
        "hapax-live-surface-guard.prom"
    ) in parser.get("Service", "ExecStart")
    assert parser.get("Service", "EnvironmentFile") == "-%t/hapax-secrets.env"
    assert "hapax-compositor-runtime-source-check" in parser.get("Service", "ExecStartPre")
    lines = _active_unit_lines(LIVE_SURFACE_GUARD)
    assert all("%h/projects/hapax-council" not in line for line in lines)


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
