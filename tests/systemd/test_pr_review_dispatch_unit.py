"""Static pins for the PR review-team dispatch systemd units."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEMD_ROOT = REPO_ROOT / "systemd"
UNITS_DIR = SYSTEMD_ROOT / "units"
PRESET = SYSTEMD_ROOT / "user-preset.d" / "hapax.preset"


def test_pr_review_dispatch_units_are_install_visible() -> None:
    assert (UNITS_DIR / "hapax-pr-review-dispatch.service").exists()
    assert (UNITS_DIR / "hapax-pr-review-dispatch.timer").exists()
    assert not (SYSTEMD_ROOT / "hapax-pr-review-dispatch.service").exists()
    assert not (SYSTEMD_ROOT / "hapax-pr-review-dispatch.timer").exists()


def test_pr_review_dispatch_service_uses_source_activation_worktree() -> None:
    text = (UNITS_DIR / "hapax-pr-review-dispatch.service").read_text(encoding="utf-8")
    execution_lines = [
        line
        for line in text.splitlines()
        if line.startswith(("ExecStart=", "WorkingDirectory=", "Environment=PYTHONPATH="))
    ]
    assert execution_lines
    assert all("%h/.cache/hapax/rebuild/worktree" not in line for line in execution_lines)
    assert all("%h/projects/hapax-council" not in line for line in execution_lines)
    assert any("%h/.cache/hapax/source-activation/worktree" in line for line in execution_lines)
    assert any("scripts/cc-pr-review-dispatch.py --all --apply" in line for line in execution_lines)


def test_pr_review_dispatch_timer_is_preset_enabled() -> None:
    preset_lines = {
        line.strip()
        for line in PRESET.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "enable hapax-pr-review-dispatch.timer" in preset_lines
