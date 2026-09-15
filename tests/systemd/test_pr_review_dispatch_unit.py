"""Static pins for the PR review-team dispatch systemd units."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEMD_ROOT = REPO_ROOT / "systemd"
UNITS_DIR = SYSTEMD_ROOT / "units"
PRESET = SYSTEMD_ROOT / "user-preset.d" / "hapax.preset"
README = SYSTEMD_ROOT / "README.md"
AUTHORITY_ENV_FILE = "-/run/user/%U/hapax-public-gate-authority.env"


@pytest.fixture(autouse=True)
def synthetic_path(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir))


def _unit_values(name: str, section: str, directive: str) -> list[str]:
    values = []
    current_section = ""
    for raw in (UNITS_DIR / name).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("["):
            current_section = line.strip("[]")
        elif current_section == section and line.startswith(directive + "="):
            values.append(line.split("=", 1)[1])
    return values


def test_review_dispatch_loads_only_optional_authority_file() -> None:
    assert _unit_values("hapax-pr-review-dispatch.service", "Service", "EnvironmentFile") == [
        AUTHORITY_ENV_FILE
    ]


def test_review_dispatch_wants_and_orders_secrets_producer() -> None:
    for directive in ("Wants", "After"):
        dependencies = " ".join(
            _unit_values("hapax-pr-review-dispatch.service", "Unit", directive)
        ).split()
        assert "hapax-secrets.service" in dependencies, directive
        assert "network-online.target" in dependencies, directive


def test_publish_orchestrator_loads_both_optional_environment_files() -> None:
    assert _unit_values("hapax-publish-orchestrator.service", "Service", "EnvironmentFile") == [
        "-/run/user/%U/hapax-secrets.env",
        AUTHORITY_ENV_FILE,
    ]


def test_review_dispatch_environment_has_no_provider_routing_variables() -> None:
    lines = _unit_values("hapax-pr-review-dispatch.service", "Service", "Environment")
    lines += _unit_values("hapax-pr-review-dispatch.service", "Service", "EnvironmentFile")
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        assert all(name not in line for line in lines)
    assert all("hapax-secrets.env" not in line for line in lines)


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
