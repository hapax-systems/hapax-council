"""Static pins for the PR review-team dispatch systemd units."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEMD_ROOT = REPO_ROOT / "systemd"
UNITS_DIR = SYSTEMD_ROOT / "units"
PRESET = SYSTEMD_ROOT / "user-preset.d" / "hapax.preset"
README = SYSTEMD_ROOT / "README.md"


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


def test_pr_review_dispatch_service_is_timer_driven_only() -> None:
    text = (UNITS_DIR / "hapax-pr-review-dispatch.service").read_text(encoding="utf-8")
    assert "[Install]" not in text
    assert "WantedBy=default.target" not in text


def test_pr_review_dispatch_has_no_seat_refresh_hook() -> None:
    text = (UNITS_DIR / "hapax-pr-review-dispatch.service").read_text(encoding="utf-8")
    pre_hooks = [line for line in text.splitlines() if line.startswith("ExecStartPre=")]
    assert pre_hooks == []
    assert "hapax-glmcp-seat-refresh" not in text


def test_pr_review_dispatch_timer_has_single_periodic_cadence() -> None:
    text = (UNITS_DIR / "hapax-pr-review-dispatch.timer").read_text(encoding="utf-8")
    assert "OnUnitActiveSec=10min" in text
    assert "OnCalendar=" not in text


def test_pr_review_dispatch_timer_is_preset_enabled() -> None:
    preset_lines = {
        line.strip()
        for line in PRESET.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "enable hapax-pr-review-dispatch.timer" in preset_lines


def test_pr_review_dispatch_runbook_has_recheck_commands() -> None:
    text = README.read_text(encoding="utf-8")
    assert "systemctl --user list-timers --all hapax-pr-review-dispatch.timer" in text
    assert (
        "systemctl --user status hapax-pr-review-dispatch.timer "
        "hapax-pr-review-dispatch.service --no-pager"
    ) in text
    assert "uv run python scripts/cc-pr-review-dispatch.py --pr <PR_NUMBER>" in text


def test_committed_refresh_pair_cannot_opt_into_mutable_root() -> None:
    service = (UNITS_DIR / "hapax-glmcp-seat-refresh.service").read_text()
    timer = (UNITS_DIR / "hapax-glmcp-seat-refresh.timer").read_text()
    for text in (service, timer):
        directives = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith(("#", ";"))
        ]
        assert all("--allow-mutable-root" not in line for line in directives)
        assert all(
            not line.startswith(("EnvironmentFile=", "PassEnvironment=")) for line in directives
        )
    unset = set()
    for line in service.splitlines():
        if line.startswith("UnsetEnvironment="):
            unset.update(line.split("=", 1)[1].split())
    assert {"HAPAX_COUNCIL", "HAPAX_GLMCP_SEAT_ROOT_OVERRIDE", "BASH_ENV", "ENV"} <= unset
    assert "Unit=" not in timer  # Same-name committed service is the only timer target.


def test_quota_killswitch_covers_both_actual_producers() -> None:
    text = (UNITS_DIR / "hapax-quota-telemetry.service").read_text()
    comment = " ".join(
        line.removeprefix("# ") for line in text.splitlines() if line.startswith("#")
    )
    assert "mask --now hapax-quota-telemetry.timer hapax-glmcp-seat-refresh.timer" in comment
    assert "stop hapax-quota-telemetry.service hapax-glmcp-seat-refresh.service" in comment
    assert (
        "systemctl --user is-active hapax-quota-telemetry.timer hapax-glmcp-seat-refresh.timer hapax-quota-telemetry.service hapax-glmcp-seat-refresh.service"
        in comment
    )
    assert "all four must report inactive" in comment


def test_refresh_envelope_excludes_boot_and_unmeasured_post_activation_witness() -> None:
    script = (REPO_ROOT / "scripts/hapax-glmcp-seat-refresh").read_text()
    assert "OnBootSec=2min is a boot-time exception" in script
    assert "continuous-run guarantee" in script
    assert "24-hour no-lapse witness is post-activation and unmeasured" in script


@pytest.mark.parametrize(
    "filename", ["scripts/hapax-glmcp-seat-refresh", "systemd/units/hapax-glmcp-seat-refresh.timer"]
)
def test_refresh_boot_exception_names_bound_and_unmeasured_witness(filename: str) -> None:
    comments = " ".join(
        line.removeprefix("# ")
        for line in (REPO_ROOT / filename).read_text().splitlines()
        if line.startswith("#")
    )
    assert "OnBootSec=2min is a boot-time exception" in comments
    assert "OnBootSec plus one round-trip" in comments
    assert "24-hour no-lapse witness is post-activation and unmeasured" in comments


def test_environment_home_specifier_matches_installed_systemd_documentation() -> None:
    if shutil.which("man") is None:
        pytest.skip(
            "man is absent in CI; cannot read installed systemd.exec(5) Environment= documentation"
        )
    result = subprocess.run(
        ["man", "-P", "cat", "systemd.exec"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "MANWIDTH": "80",
            "MAN_KEEP_FORMATTING": "0",
            "SYSTEMD_COLORS": "0",
            "GROFF_NO_SGR": "1",
            "TERM": "dumb",
            "LC_ALL": "C",
        },
    )
    if result.returncode and "No manual entry for systemd.exec" in result.stderr:
        pytest.skip(
            "installed systemd.exec(5) man page is absent; cannot verify Environment= documentation"
        )
    assert result.returncode == 0, result.stderr
    manual = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    manual = re.sub(".\x08", "", manual)
    environment = re.split(r"(?m)^\s*Environment=\s*$", manual)[1].split("EnvironmentFile=", 1)[0]
    quote = 'Specifier expansion is performed, see the "Specifiers" section in systemd.unit(5).'
    other_quote = "The usual specifiers are expanded in all assignments (see below)."
    assert quote in " ".join(environment.split())
    assert other_quote in " ".join(manual.split())
    service = (UNITS_DIR / "hapax-glmcp-seat-refresh.service").read_text()
    comments = " ".join(
        line.removeprefix("# ") for line in service.splitlines() if line.startswith("#")
    )
    assert "Environment=HOME=%h" in service.splitlines()
    # The unit no longer quotes the manual; it carries exercised evidence (coordinator
    # measurement 2026-09-05, read-only user-manager inspection): three installed units
    # carry HOME=%h verbatim and the manager's parsed view shows the home path with zero
    # remaining %h; the round-4 systemd-run result was a transient D-Bus property.
    for installed_unit in (
        "hapax-cc-task-offer-ready.service",
        "hapax-claude-account-live-observe.service",
        "hapax-determine.service",
    ):
        assert installed_unit in comments
    assert "zero remaining %h" in comments
    assert "Result=success" in comments
    assert "transient D-Bus property" in comments
