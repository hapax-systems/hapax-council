"""Source-activation consumer audit regression tests.

Verifies that systemd units and hook scripts resolve executable source
through the symlink layer (%h/.local/bin/hapax-*) or the activation
worktree, not hardcoded canonical checkout paths.

ISAP: SLICE-SOURCE-ACTIVATION-CONSUMER-AUDIT (CASE-SDLC-REFORM-001)
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UNITS_DIR = REPO_ROOT / "systemd" / "units"
SCRIPTS_DIR = REPO_ROOT / "scripts"

CANONICAL_SCRIPT_PATTERN = str(Path.home() / "projects" / "hapax-council" / "scripts") + "/"
ACTIVATION_WORKTREE = "%h/.cache/hapax/source-activation/worktree"


def _script_based_units() -> list[Path]:
    """Units whose ExecStart was migrated from canonical script paths."""
    migrated = [
        "cache-cleanup.service",
        "disk-space-check.service",
        "hapax-audio-routing-check.service",
        "hapax-audio-stage-check.service",
        "hapax-audio-optional-device-state.service",
        "hapax-daimonion-quarantine-watchdog.service",
        "hapax-egress-audit-rotate.service",
        "hapax-evil-pet-scene.service",
        "hapax-imagination-watchdog.service",
        "hapax-lrr-phase-4-integrity.service",
        "hapax-option-c-pin-watchdog.service",
        "hapax-pin-check.service",
        "hapax-post-merge-deploy.service",
        "hapax-pr-admission-auto.service",
        "hapax-private-monitor-recover.service",
        "hapax-recent-impingements.service",
        "hapax-stream-auto-private.service",
        "hapax-systemd-reconcile.service",
        "hapax-v4l2-watchdog.service",
        "hapax-youtube-video-id.service",
        "hapax-youtube-viewer-count.service",
        "tailscale-cleanup.service",
        "video-retention.service",
        "vram-watchdog.service",
    ]
    return [UNITS_DIR / name for name in migrated]


class TestNoCanonicalExecStart:
    @pytest.mark.parametrize(
        "unit_path",
        _script_based_units(),
        ids=[p.name for p in _script_based_units()],
    )
    def test_no_hardcoded_canonical_script_path(self, unit_path: Path) -> None:
        text = unit_path.read_text(encoding="utf-8")
        assert CANONICAL_SCRIPT_PATTERN not in text, (
            f"{unit_path.name} still references canonical script path"
        )


class TestRenamedScriptsExist:
    RENAMED = [
        "hapax-cache-cleanup",
        "hapax-disk-space-check",
        "hapax-audio-routing-check",
        "hapax-audio-stage-check",
        "hapax-evil-pet-configure-base",
        "hapax-lrr-phase-4-integrity-check",
        "hapax-option-c-repin",
        "hapax-vram-watchdog",
        "hapax-tailscale-cleanup",
        "hapax-video-retention",
        "hapax-recent-impingements-producer",
        "hapax-youtube-viewer-count-producer",
        "hapax-youtube-video-id-publisher",
    ]

    @pytest.mark.parametrize("script_name", RENAMED)
    def test_script_exists(self, script_name: str) -> None:
        path = SCRIPTS_DIR / script_name
        assert path.exists(), f"Renamed script {script_name} missing from scripts/"

    @pytest.mark.parametrize("script_name", RENAMED)
    def test_script_executable(self, script_name: str) -> None:
        path = SCRIPTS_DIR / script_name
        if path.exists():
            mode = os.stat(path).st_mode
            assert mode & stat.S_IXUSR, f"{script_name} is not executable"


class TestSessionContextSourceResolution:
    def test_axiom_loading_prefers_activation_worktree(self) -> None:
        text = (REPO_ROOT / "hooks" / "scripts" / "session-context.sh").read_text()
        assert "source-activation/worktree" in text, (
            "session-context.sh should prefer activation worktree for axiom loading"
        )
        assert "COUNCIL_SOURCE=" in text

    def test_calendar_prefers_activation_worktree(self) -> None:
        text = (REPO_ROOT / "hooks" / "scripts" / "session-context.sh").read_text()
        assert "CALENDAR_SOURCE=" in text, (
            "session-context.sh should prefer activation worktree for calendar context"
        )


class TestConductorSourceResolution:
    def test_conductor_prefers_activation_worktree(self) -> None:
        text = (REPO_ROOT / "hooks" / "scripts" / "conductor-start.sh").read_text()
        assert "source-activation/worktree" in text, (
            "conductor-start.sh should prefer activation worktree"
        )


class TestEnvVarOverrides:
    def test_rebuild_logos_has_override(self) -> None:
        text = (SCRIPTS_DIR / "rebuild-logos.sh").read_text()
        assert "HAPAX_COUNCIL_DIR" in text

    def test_freshness_check_has_override(self) -> None:
        text = (SCRIPTS_DIR / "freshness-check.sh").read_text()
        assert "HAPAX_COUNCIL_DIR" in text


class TestSymlinkSweepInSourceActivate:
    def test_sweep_loop_exists(self) -> None:
        text = (SCRIPTS_DIR / "hapax-source-activate").read_text()
        assert "sweep_count" in text, "hapax-source-activate should have a symlink sweep step"
        assert "scripts/hapax-" in text

    def test_cc_task_tools_are_allowlisted_for_activation_sweep(self) -> None:
        text = (SCRIPTS_DIR / "hapax-source-activate").read_text()
        assert "cc-claim" in text
        assert "cc-close" in text


class TestCcPrMergeWatcherSourceResolution:
    def test_pr_merge_watcher_unit_uses_activation_worktree(self) -> None:
        text = (UNITS_DIR / "hapax-cc-pr-merge-watcher.service").read_text()
        execution_lines = [
            line
            for line in text.splitlines()
            if line.startswith(("ExecStart=", "WorkingDirectory=", "Environment=PYTHONPATH="))
        ]
        assert execution_lines
        assert all("%h/projects/hapax-council" not in line for line in execution_lines)
        assert any("%h/.cache/hapax/source-activation/worktree" in line for line in execution_lines)
        assert any("scripts/cc-pr-merge-watcher.py" in line for line in execution_lines)


class TestOptionalAudioDeviceStateSourceResolution:
    def test_optional_audio_unit_uses_activation_worktree(self) -> None:
        text = (UNITS_DIR / "hapax-audio-optional-device-state.service").read_text()
        execution_lines = [
            line
            for line in text.splitlines()
            if line.startswith(
                (
                    "ConditionPathExists=",
                    "ExecStart=",
                    "WorkingDirectory=",
                    "Environment=PYTHONPATH=",
                )
            )
        ]
        assert execution_lines
        assert all("%h/projects/hapax-council" not in line for line in execution_lines)
        assert any(ACTIVATION_WORKTREE in line for line in execution_lines)
        assert any("scripts/hapax-audio-optional-device-state" in line for line in execution_lines)

    def test_optional_audio_script_exists_and_is_executable(self) -> None:
        path = SCRIPTS_DIR / "hapax-audio-optional-device-state"
        assert path.exists()
        assert os.stat(path).st_mode & stat.S_IXUSR
