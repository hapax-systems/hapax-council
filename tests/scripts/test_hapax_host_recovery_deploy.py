"""The boot restorer must enter the post-merge activation path."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_boot_restorer_waits_for_explicit_activation() -> None:
    service = (ROOT / "systemd/units/hapax-host-recovery-restore.service").read_text()
    assert "# Hapax-Parked: true" in service
    assert "# Hapax-Auto-Enable: true" not in service
    assert "WantedBy=default.target" in service
    for name in ("capture", "restore"):
        timer = (ROOT / f"systemd/units/hapax-host-recovery-{name}.timer").read_text()
        assert "# Hapax-Parked: true" in timer
        assert "# Hapax-Auto-Enable: true" not in timer


@pytest.fixture
def install_fixture(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    root = tmp_path / ".cache/hapax/source-activation"
    staging = tmp_path / "staging"
    (staging / "scripts").mkdir(parents=True)
    (staging / "systemd/units").mkdir(parents=True)
    for name in ("install-host-recovery", "hapax-host-recovery"):
        shutil.copy2(ROOT / "scripts" / name, staging / "scripts" / name)
    for name in (
        "hapax-host-recovery-capture.service",
        "hapax-host-recovery-capture.timer",
        "hapax-host-recovery-restore.service",
        "hapax-host-recovery-restore.timer",
    ):
        shutil.copy2(ROOT / "systemd/units" / name, staging / "systemd/units" / name)
    for command in (
        ("init", "-q"),
        ("add", "."),
        (
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ),
    ):
        subprocess.run(["git", "-C", str(staging), *command], check=True)
    head = subprocess.check_output(
        ["git", "-C", str(staging), "rev-parse", "HEAD"], text=True
    ).strip()
    release = root / "releases" / head
    release.parent.mkdir(parents=True)
    shutil.move(str(staging), release)
    (root / "worktree").symlink_to(release)
    (root / "current.json").write_text(
        json.dumps({"active_source_head": head, "active_source_target": str(release)})
    )
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "systemctl"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$HOME/systemctl.log"\n')
    fake.chmod(0o755)
    env = os.environ | {"HOME": str(tmp_path), "PATH": f"{bindir}:{os.environ['PATH']}"}
    return release / "scripts/install-host-recovery", env, tmp_path


def invoke(script: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(script), *args], env=env, capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize(
    ("head_case", "accepted"),
    [
        ("lowercase", True),
        ("uppercase", False),
        ("nonhex", False),
        ("short", False),
        ("long", False),
    ],
)
def test_active_source_head_requires_exact_lowercase_hex(
    install_fixture: tuple[Path, dict[str, str], Path],
    head_case: str,
    accepted: bool,
) -> None:
    script, env, home = install_fixture
    receipt_path = home / ".cache/hapax/source-activation/current.json"
    receipt = json.loads(receipt_path.read_text())
    head = receipt["active_source_head"]
    altered = {
        "lowercase": head,
        "uppercase": "A" + head[1:],
        "nonhex": "g" + head[1:],
        "short": head[:-1],
        "long": head + "0",
    }[head_case]
    receipt["active_source_head"] = altered
    receipt_path.write_text(json.dumps(receipt))
    result = invoke(script, env, "--prepare")
    if accepted:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
        assert "invalid active source head" in result.stderr
        assert not (home / ".local").exists()


def test_direct_install_refuses_before_any_act(
    install_fixture: tuple[Path, dict[str, str], Path],
) -> None:
    script, env, home = install_fixture
    result = invoke(script, env, "--install")
    assert result.returncode != 0
    assert not (home / ".local").exists()
    assert not (home / "systemctl.log").exists()


def test_arbitrary_source_refuses_before_any_act(
    install_fixture: tuple[Path, dict[str, str], Path],
) -> None:
    script, env, home = install_fixture
    result = invoke(script, env, "--source", str(ROOT), "--prepare")
    assert result.returncode != 0
    assert not (home / ".local").exists()
    assert not (home / "systemctl.log").exists()


def test_environment_destination_override_refuses_before_prepare(
    install_fixture: tuple[Path, dict[str, str], Path],
) -> None:
    script, env, home = install_fixture
    env["HAPAX_HOST_RECOVERY_BIN"] = str(home / "foreign/hapax-host-recovery")
    result = invoke(script, env, "--prepare")
    assert result.returncode != 0
    assert "override" in result.stderr
    assert not (home / "foreign").exists()


def test_modified_active_release_refuses_before_prepare(
    install_fixture: tuple[Path, dict[str, str], Path],
) -> None:
    script, env, home = install_fixture
    (script.parent / "hapax-host-recovery").write_text("tampered\n")
    result = invoke(script, env, "--prepare")
    assert result.returncode != 0
    assert "reviewed source binding refused" in result.stderr
    assert not (home / ".local").exists()


def test_check_refuses_missing_or_changed_installed_copy(
    install_fixture: tuple[Path, dict[str, str], Path],
) -> None:
    script, env, home = install_fixture
    assert invoke(script, env, "--check").returncode != 0
    assert invoke(script, env, "--prepare").returncode == 0
    installed = home / ".local/bin/hapax-host-recovery"
    installed.write_text("tampered\n")
    result = invoke(script, env, "--check")
    assert result.returncode != 0
    assert "script differs" in result.stderr
    assert not (home / "systemctl.log").exists()


def test_prepare_check_activation_are_separate_and_restore_is_not_run_now(
    install_fixture: tuple[Path, dict[str, str], Path],
) -> None:
    script, env, home = install_fixture
    assert invoke(script, env, "--activate").returncode != 0
    assert not (home / "systemctl.log").exists()
    assert invoke(script, env, "--prepare", "--report-host", "hapax-appendix").returncode == 0
    assert not (home / "systemctl.log").exists()
    assert invoke(script, env, "--check", "--report-host", "hapax-appendix").returncode == 0
    assert not (home / "systemctl.log").exists()
    assert invoke(script, env, "--activate", "--report-host", "hapax-appendix").returncode == 0
    calls = (home / "systemctl.log").read_text().splitlines()
    assert calls[0] == "--user daemon-reload"
    assert "--user enable hapax-host-recovery-restore.service" in calls
    assert all("--now hapax-host-recovery-restore.service" not in call for call in calls)
    assert "--user enable --now hapax-host-recovery-capture.timer" in calls
    assert "--user stop hapax-host-recovery-restore.timer" in calls
    assert "--user enable hapax-host-recovery-restore.timer" in calls
    assert all("enable --now hapax-host-recovery-restore.timer" not in call for call in calls)


def test_invalid_report_host_refuses_before_any_write(
    install_fixture: tuple[Path, dict[str, str], Path],
) -> None:
    script, env, home = install_fixture
    result = invoke(script, env, "--prepare", "--report-host", "bad/host")
    assert result.returncode != 0
    assert "invalid report host" in result.stderr
    assert not (home / ".local").exists()
    assert not (home / ".config").exists()


def test_unstated_existing_report_host_refuses_prepare(
    install_fixture: tuple[Path, dict[str, str], Path],
) -> None:
    script, env, home = install_fixture
    conf = home / ".config/systemd/user/hapax-host-recovery-restore.service.d/report.conf"
    conf.parent.mkdir(parents=True)
    conf.write_text("[Service]\nEnvironment=HAPAX_RECOVERY_REPORT_HOST=other-host\n")
    result = invoke(script, env, "--prepare")
    assert result.returncode != 0
    assert "report host" in result.stderr
    assert not (home / ".local").exists()
