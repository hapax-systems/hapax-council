from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
INSTALL_UNITS = REPO_ROOT / "systemd" / "scripts" / "install-units.sh"
PRESET = REPO_ROOT / "systemd" / "user-preset.d" / "hapax.preset"
ENSURE = REPO_ROOT / "scripts" / "ensure-screwm-gpu-drift-build.sh"
JUSTFILE = REPO_ROOT / "hapax-logos" / "justfile"
SA_WORKTREE = "%h/.cache/hapax/source-activation/worktree"
REBUILD_WORKTREE = "%h/.cache/hapax/rebuild/worktree"


def _read(name: str) -> str:
    return (UNITS_DIR / name).read_text(encoding="utf-8")


def test_screwm_gpu_drift_rebuild_service_builds_from_source_activation_worktree() -> None:
    service = _read("hapax-screwm-gpu-drift-rebuild.service")
    assert "After=hapax-source-activate.service" in service
    assert f"WorkingDirectory={SA_WORKTREE}" in service
    assert f"ExecStart={SA_WORKTREE}/scripts/ensure-screwm-gpu-drift-build.sh" in service
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in service
    assert "ConditionPathExists=%h/.cache/hapax/source-activation/last-success-sha" in service
    assert "Type=oneshot" in service
    assert "StartLimitIntervalSec=600" in service and "StartLimitBurst=3" in service
    # restarts BOTH drift daemons (restart-safe headless producers)
    assert "try-restart hapax-quake-drift-field.service" in service
    assert "try-restart hapax-screwm-media-drift.service" in service
    # SA-vs-rebuild-worktree isolation: must NOT touch the dedicated rebuild worktree
    assert REBUILD_WORKTREE not in service


def test_screwm_gpu_drift_rebuild_path_watches_source_activation() -> None:
    path = _read("hapax-screwm-gpu-drift-rebuild.path")
    assert "PathChanged=%h/.cache/hapax/source-activation/last-success-sha" in path
    assert "ConditionPathExists=%h/.config/hapax/enable-darkplaces-runtime" in path
    assert "Unit=hapax-screwm-gpu-drift-rebuild.service" in path
    assert "WantedBy=default.target" in path
    assert REBUILD_WORKTREE not in path


def test_screwm_gpu_drift_rebuild_path_is_enabled_by_deploy_defaults() -> None:
    assert "hapax-screwm-gpu-drift-rebuild.path" in INSTALL_UNITS.read_text(encoding="utf-8")
    assert "enable hapax-screwm-gpu-drift-rebuild.path" in PRESET.read_text(encoding="utf-8")


def test_ensure_screwm_gpu_drift_build_is_idempotent_and_uses_recipes() -> None:
    s = ENSURE.read_text(encoding="utf-8")
    assert "src_sha256=" in s  # content-hash stamp gate
    assert "flock" in s
    assert "build-target-screwm" in s  # dedicated CARGO_TARGET_DIR (decoupled from rebuild-logos)
    assert "just install-screwm-drift-field" in s
    assert "just install-screwm-media-drift" in s


def test_justfile_has_screwm_drift_install_recipes() -> None:
    j = JUSTFILE.read_text(encoding="utf-8")
    assert "install-screwm-drift-field:" in j
    assert "install-screwm-media-drift:" in j
    assert "--bin screwm_drift_field" in j and "--bin screwm_media_drift" in j
    assert "screwm-drift-field" in j and "screwm-media-drift" in j
    assert ".new" in j and ".prev" in j  # rename-trick + backup
