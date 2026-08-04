from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "scripts" / "install-p0-oom-containment"
OOM_ENFORCER = REPO_ROOT / "scripts" / "hapax-oom-score-enforce"
OOM_TRIGGER = REPO_ROOT / "scripts" / "hapax-oom-score-trigger"
OOM_SUDOERS = REPO_ROOT / "config" / "root-required" / "hapax-oom-score-enforce.sudoers"
ROOT_FAILURE_INTAKE = REPO_ROOT / "scripts" / "hapax-root-failure-intake"
REPO_HEAD = subprocess.run(
    ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True, text=True, capture_output=True
).stdout.strip()
OOM_PACKAGE_FILES = tuple(
    line
    for line in (REPO_ROOT / "config" / "root-required" / "oom-containment.files")
    .read_text(encoding="utf-8")
    .splitlines()
    if line and not line.startswith("#")
)
PROTECTED_USER_UNIT_SCORES = {
    "pipewire.service": -900,
    "pipewire-pulse.service": -900,
    "wireplumber.service": -900,
    "hapax-daimonion.service": -500,
    "studio-compositor.service": -800,
    "hapax-imagination.service": -800,
}
PROTECTED_USER_UNIT_RUNTIME = {
    "pipewire.service": {
        "Slice": "session.slice",
        "MemoryLow": "536870912",
        "MemoryMin": "268435456",
        "NoNewPrivileges": "yes",
    },
    "pipewire-pulse.service": {
        "Slice": "session.slice",
        "MemoryLow": "536870912",
        "MemoryMin": "268435456",
        "NoNewPrivileges": "yes",
    },
    "wireplumber.service": {
        "Slice": "session.slice",
        "MemoryLow": "536870912",
        "MemoryMin": "268435456",
        "NoNewPrivileges": "yes",
    },
    "hapax-daimonion.service": {
        "Slice": "app.slice",
        "MemoryLow": "2147483648",
        "MemoryMin": "1073741824",
    },
    "studio-compositor.service": {
        "Slice": "app.slice",
        "MemoryLow": "6442450944",
        "MemoryMin": "3221225472",
    },
    "hapax-imagination.service": {
        "Slice": "app.slice",
        "MemoryLow": "6442450944",
        "MemoryMin": "3221225472",
    },
}
RECOVERY_SYSTEM_UNIT_SCORES = {
    "apcupsd.service": -900,
    "systemd-logind.service": -800,
    "systemd-resolved.service": -800,
    "systemd-timesyncd.service": -800,
    "NetworkManager.service": -800,
    "dbus-broker.service": -900,
    "sshd.service": 0,
}
RECOVERY_SYSTEM_UNIT_PIDS = {
    unit: 200 + index for index, unit in enumerate(RECOVERY_SYSTEM_UNIT_SCORES)
}
SAFE_AUDIT_ENVIRONMENT = "PATH=/usr/local/sbin:/usr/local/bin:/usr/bin:/bin"


def _copy_oom_package(dest_root: Path) -> None:
    for relative in OOM_PACKAGE_FILES:
        dest = dest_root / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, dest)


@pytest.fixture(autouse=True)
def _isolate_installed_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_OOM_ENFORCE_TEST_MODE", "1")
    monkeypatch.setenv("HAPAX_OOM_TARGET_USER", "hapax")
    monkeypatch.setenv("HAPAX_OOM_TARGET_UID", "1000")
    monkeypatch.setenv("HAPAX_OOM_TARGET_GID", "1000")
    monkeypatch.setenv("HAPAX_OOM_TARGET_HOME", str(tmp_path / "target-home"))
    monkeypatch.setenv("HAPAX_OOM_EFFECTIVE_UID", "1000")
    monkeypatch.setenv("HAPAX_POST_MERGE_ROOT_DEFER_DIR", str(tmp_path / "root-required"))
    monkeypatch.setenv("HAPAX_ROOT_REQUIRED_STATE_ROOT", str(tmp_path / "root-state"))
    monkeypatch.setenv(
        "HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT", str(tmp_path / "installed-source")
    )
    monkeypatch.setenv(
        "HAPAX_OOM_POLICY_AUDIT_DEST", str(tmp_path / "sbin" / "hapax-oom-policy-audit")
    )
    monkeypatch.setenv(
        "HAPAX_ROOT_REQUIRED_AUDIT_DEST",
        str(tmp_path / "sbin" / "hapax-root-required-deploy-audit"),
    )
    monkeypatch.setenv("HAPAX_OOM_TRIGGER_DEST", str(tmp_path / "bin" / "hapax-oom-score-trigger"))
    monkeypatch.setenv(
        "HAPAX_OOM_SUDOERS_DEST", str(tmp_path / "sudoers.d" / "hapax-oom-score-enforce")
    )
    monkeypatch.setenv(
        "HAPAX_OOM_SUDOERS_REFERENCE_DEST",
        str(tmp_path / "share" / "hapax-oom-score-enforce.sudoers"),
    )
    monkeypatch.setenv("HAPAX_OOM_SUDOERS_OWNER_UID", str(os.getuid()))
    monkeypatch.setenv("HAPAX_OOM_SUDOERS_OWNER_GID", str(os.getgid()))
    fake_visudo = tmp_path / "visudo"
    fake_visudo.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_visudo.chmod(0o755)
    monkeypatch.setenv("HAPAX_OOM_VISUDO", str(fake_visudo))
    monkeypatch.setenv("HAPAX_OOM_SYSTEMD_USER_DIR", str(tmp_path / "systemd-user-default"))
    monkeypatch.setenv("HAPAX_ROOT_REQUIRED_GIT_REPO", str(REPO_ROOT))


def _unit_cgroup(unit: str) -> str:
    return f"/user.slice/user-1000.slice/user@1000.service/app.slice/{unit}"


def _enforcer_system_manager_cases(pid: int = 900) -> str:
    return "\n".join(
        [
            '  "show user@1000.service -p ActiveState --value") printf "active\\n" ;;',
            f'  *"show user@1000.service -p MainPID --value"*) printf "{pid}\\n" ;;',
            '  *"show user@1000.service -p ControlGroup --value"*) printf "/user.slice/user-1000.slice/user@1000.service\\n" ;;',
        ]
    )


def _enforcer_user_unit_cases(
    unit_pids: dict[str, int], unit_cgroups: dict[str, str] | None = None
) -> str:
    unit_cgroups = unit_cgroups or {unit: _unit_cgroup(unit) for unit in unit_pids}
    cases = []
    for unit, pid in unit_pids.items():
        cases.append(f'  *"show {unit} -p MainPID --value"*) printf "{pid}\\n" ;;')
        cases.append(
            f'  *"show {unit} -p ControlGroup --value"*) '
            f'printf "{unit_cgroups.get(unit, "")}\\n" ;;'
        )
    return "\n".join(cases)


def _systemctl_user_unit_cases(
    unit_pids: dict[str, int] | None = None,
    unit_cgroups: dict[str, str] | None = None,
    effective_overrides: dict[str, dict[str, str]] | None = None,
) -> str:
    unit_pids = unit_pids or {}
    effective_overrides = effective_overrides or {}
    unit_cgroups = unit_cgroups or {
        unit: _unit_cgroup(unit) for unit in unit_pids if unit in PROTECTED_USER_UNIT_SCORES
    }
    cases = []
    for audit_unit in (
        "hapax-oom-policy-audit.service",
        "hapax-root-required-deploy-audit.service",
    ):
        exec_start = (
            "/usr/local/sbin/hapax-oom-policy-audit --json"
            if audit_unit == "hapax-oom-policy-audit.service"
            else "/usr/local/sbin/hapax-root-required-deploy-audit"
        )
        cases.append(
            f"  *--user\\ show\\ {audit_unit}\\ -p\\ TimeoutStartUSec\\ --value*) "
            "printf '%s\\n' '2min' ;;"
        )
        cases.append(
            f"  *--user\\ show\\ {audit_unit}\\ -p\\ Environment\\ --value*) "
            f"printf '%s\\n' '{SAFE_AUDIT_ENVIRONMENT}' ;;"
        )
        cases.extend(
            [
                f"  *--user\\ show\\ {audit_unit}\\ -p\\ FragmentPath\\ --value*) "
                f"printf '%s\\n' \"${{HAPAX_OOM_SYSTEMD_USER_DIR:-/home/hapax/.config/systemd/user}}/{audit_unit}\" ;;",
                f"  *--user\\ show\\ {audit_unit}\\ -p\\ DropInPaths\\ --value*) printf '\\n' ;;",
                f"  *--user\\ show\\ {audit_unit}\\ -p\\ ExecStart\\ --value*) "
                f"printf '%s\\n' '{{ path={exec_start.split()[0]} ; argv[]={exec_start} ; }}' ;;",
                f"  *--user\\ show\\ {audit_unit}\\ -p\\ OnFailure\\ --value*) "
                f"printf '%s\\n' 'notify-failure@{audit_unit}.service' ;;",
                f"  *--user\\ show\\ {audit_unit}\\ -p\\ User\\ --value*) printf '\\n' ;;",
            ]
        )
    for timer, target, on_boot, on_active in (
        (
            "hapax-oom-policy-audit.timer",
            "hapax-oom-policy-audit.service",
            "2min",
            "5min",
        ),
        (
            "hapax-root-required-deploy-audit.timer",
            "hapax-root-required-deploy-audit.service",
            "3min",
            "10min",
        ),
    ):
        cases.extend(
            [
                f"  *--user\\ show\\ {timer}\\ -p\\ FragmentPath\\ --value*) "
                f"printf '%s\\n' \"${{HAPAX_OOM_SYSTEMD_USER_DIR:-/home/hapax/.config/systemd/user}}/{timer}\" ;;",
                f"  *--user\\ show\\ {timer}\\ -p\\ DropInPaths\\ --value*) printf '\\n' ;;",
                f"  *--user\\ show\\ {timer}\\ -p\\ Unit\\ --value*) printf '%s\\n' '{target}' ;;",
                f"  *--user\\ show\\ {timer}\\ -p\\ TimersMonotonic\\ --value*) "
                f"printf '%s\\n' 'OnBootUSec={on_boot} OnUnitActiveUSec={on_active}' ;;",
            ]
        )
    for unit in PROTECTED_USER_UNIT_SCORES:
        cases.append(
            f"  *--user\\ show\\ {unit}\\ -p\\ OOMScoreAdjust\\ --value*) printf '%s\\n' '100' ;;"
        )
        cases.append(
            f"  *--user\\ show\\ {unit}\\ -p\\ MainPID\\ --value*) "
            f"printf '%s\\n' '{unit_pids.get(unit, 0)}' ;;"
        )
        cases.append(
            f"  *--user\\ show\\ {unit}\\ -p\\ ControlGroup\\ --value*) "
            f"printf '%s\\n' '{unit_cgroups.get(unit, '')}' ;;"
        )
        for key, expected in PROTECTED_USER_UNIT_RUNTIME[unit].items():
            actual = effective_overrides.get(unit, {}).get(key, expected)
            cases.append(
                f"  *--user\\ show\\ {unit}\\ -p\\ {key}\\ --value*) printf '%s\\n' '{actual}' ;;"
            )
    return "\n".join(cases)


def _systemctl_app_slice_cases() -> str:
    return "\n".join(
        [
            '  *"--user show app.slice -p MemoryHigh --value"*) printf "77309411328\\n" ;;',
            '  *"--user show app.slice -p MemoryMax --value"*) printf "94489280512\\n" ;;',
            '  *"--user show app.slice -p MemorySwapMax --value"*) printf "8589934592\\n" ;;',
            '  *"--user show app.slice -p MemoryLow --value"*) printf "17179869184\\n" ;;',
            '  *"--user show app.slice -p MemoryMin --value"*) printf "8589934592\\n" ;;',
            '  *"--user show session.slice -p MemoryHigh --value"*) printf "infinity\\n" ;;',
            '  *"--user show session.slice -p MemoryMax --value"*) printf "infinity\\n" ;;',
            '  *"--user show session.slice -p MemorySwapMax --value"*) printf "infinity\\n" ;;',
            '  *"--user show session.slice -p MemoryLow --value"*) printf "2147483648\\n" ;;',
            '  *"--user show session.slice -p MemoryMin --value"*) printf "1073741824\\n" ;;',
        ]
    )


def _systemctl_recovery_unit_cases(unit_pids: dict[str, int] | None = None) -> str:
    unit_pids = unit_pids or {}
    cases = []
    for unit, score in RECOVERY_SYSTEM_UNIT_SCORES.items():
        cases.append(f"  *\"show {unit} -p OOMScoreAdjust --value\"*) printf '%s\\n' '{score}' ;;")
        cases.append(
            f"  *\"show {unit} -p MainPID --value\"*) printf '%s\\n' '{unit_pids.get(unit, 0)}' ;;"
        )
    cases.append('  *"show sshd.service -p OOMPolicy --value"*) printf "continue\\n" ;;')
    return "\n".join(cases)


def _systemctl_system_memory_cases(
    recovery_unit_pids: dict[str, int] | None = None,
    *,
    user_manager_score: int = 100,
) -> str:
    cases = [
        '  *"show hapax-oom-score-enforce.service -p TimeoutStartUSec --value"*) printf "25s\\n" ;;',
        '  *"show hapax-oom-score-enforce.service -p FragmentPath --value"*) printf "%s\\n" "${HAPAX_OOM_SYSTEMD_SYSTEM_DIR:-/etc/systemd/system}/hapax-oom-score-enforce.service" ;;',
        '  *"show hapax-oom-score-enforce.service -p DropInPaths --value"*) printf "\\n" ;;',
        '  *"show hapax-oom-score-enforce.service -p ExecStart --value"*) printf "%s\\n" "{ path=/usr/local/sbin/hapax-oom-score-enforce ; argv[]=/usr/local/sbin/hapax-oom-score-enforce --apply ; }" ;;',
        '  *"show hapax-oom-score-enforce.service -p OnFailure --value"*) printf "%s\\n" "hapax-root-failure-intake@hapax-oom-score-enforce.service.service" ;;',
        '  *"show hapax-oom-score-enforce.service -p User --value"*) printf "\\n" ;;',
        '  *"show hapax-root-failure-intake@hapax-oom-score-enforce.service.service -p FragmentPath --value"*) printf "%s\\n" "${HAPAX_OOM_SYSTEMD_SYSTEM_DIR:-/etc/systemd/system}/hapax-root-failure-intake@.service" ;;',
        '  *"show hapax-root-failure-intake@hapax-oom-score-enforce.service.service -p DropInPaths --value"*) printf "\\n" ;;',
        '  *"show hapax-root-failure-intake@hapax-oom-score-enforce.service.service -p ExecStart --value"*) printf "%s\\n" "{ path=/usr/local/sbin/hapax-root-failure-intake ; argv[]=/usr/local/sbin/hapax-root-failure-intake hapax-oom-score-enforce.service ; }" ;;',
        '  *"show hapax-root-failure-intake@hapax-oom-score-enforce.service.service -p User --value"*) printf "hapax\\n" ;;',
        f'  *"show hapax-root-failure-intake@hapax-oom-score-enforce.service.service -p Environment --value"*) printf "{SAFE_AUDIT_ENVIRONMENT}\\n" ;;',
        '  *"show hapax-root-failure-intake@hapax-oom-score-enforce.service.service -p StartLimitIntervalUSec --value"*) printf "1h\\n" ;;',
        '  *"show hapax-root-failure-intake@hapax-oom-score-enforce.service.service -p StartLimitBurst --value"*) printf "1\\n" ;;',
        '  *"show hapax-oom-score-enforce.timer -p FragmentPath --value"*) printf "%s\\n" "${HAPAX_OOM_SYSTEMD_SYSTEM_DIR:-/etc/systemd/system}/hapax-oom-score-enforce.timer" ;;',
        '  *"show hapax-oom-score-enforce.timer -p DropInPaths --value"*) printf "\\n" ;;',
        '  *"show hapax-oom-score-enforce.timer -p Unit --value"*) printf "hapax-oom-score-enforce.service\\n" ;;',
        '  *"show hapax-oom-score-enforce.timer -p TimersMonotonic --value"*) printf "%s\\n" "OnBootUSec=30s OnUnitActiveUSec=30s" ;;',
        '  *"show system.slice -p MemoryHigh --value"*) printf "infinity\\n" ;;',
        '  *"show system.slice -p MemoryMax --value"*) printf "infinity\\n" ;;',
        '  *"show system.slice -p MemorySwapMax --value"*) printf "infinity\\n" ;;',
        '  *"show system.slice -p MemoryLow --value"*) printf "25769803776\\n" ;;',
        '  *"show system.slice -p MemoryMin --value"*) printf "12884901888\\n" ;;',
        '  *"show user.slice -p MemoryHigh --value"*) printf "infinity\\n" ;;',
        '  *"show user.slice -p MemoryMax --value"*) printf "infinity\\n" ;;',
        '  *"show user.slice -p MemorySwapMax --value"*) printf "infinity\\n" ;;',
        '  *"show user.slice -p MemoryLow --value"*) printf "21474836480\\n" ;;',
        '  *"show user.slice -p MemoryMin --value"*) printf "10737418240\\n" ;;',
        '  *"show user-1000.slice -p MemoryHigh --value"*) printf "85899345920\\n" ;;',
        '  *"show user-1000.slice -p MemoryMax --value"*) printf "103079215104\\n" ;;',
        '  *"show user-1000.slice -p MemorySwapMax --value"*) printf "8589934592\\n" ;;',
        '  *"show user-1000.slice -p MemoryLow --value"*) printf "21474836480\\n" ;;',
        '  *"show user-1000.slice -p MemoryMin --value"*) printf "10737418240\\n" ;;',
        '  *"show user@1000.service -p MemoryHigh --value"*) printf "85899345920\\n" ;;',
        '  *"show user@1000.service -p MemoryMax --value"*) printf "103079215104\\n" ;;',
        '  *"show user@1000.service -p MemorySwapMax --value"*) printf "8589934592\\n" ;;',
        '  *"show user@1000.service -p MemoryLow --value"*) printf "21474836480\\n" ;;',
        '  *"show user@1000.service -p MemoryMin --value"*) printf "10737418240\\n" ;;',
        f'  *"show user@1000.service -p OOMScoreAdjust --value"*) printf "{user_manager_score}\\n" ;;',
        '  *"show user@1000.service -p OOMPolicy --value"*) printf "continue\\n" ;;',
    ]
    return "\n".join([*cases, _systemctl_recovery_unit_cases(recovery_unit_pids)])


def test_p0_oom_containment_source_check_passes() -> None:
    result = subprocess.run(
        [str(INSTALLER), "--check"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "p0 oom containment install/check complete" in result.stdout
    earlyoom = (REPO_ROOT / "config" / "earlyoom" / "default").read_text(encoding="utf-8")
    assert "--ignore (" in earlyoom
    assert "'(" not in earlyoom
    assert "systemd-resolved" not in earlyoom
    assert "systemd-timesyncd" not in earlyoom
    earlyoom_args = next(
        line for line in earlyoom.splitlines() if line.startswith("EARLYOOM_ARGS=")
    )
    assert "hapax-imagination" not in earlyoom_args
    assert "studio-compositor" not in earlyoom_args
    assert "logos-api" not in earlyoom
    assert "officium-api" not in earlyoom
    assert "systemd-resolve" in earlyoom
    assert "systemd-timesyn" in earlyoom
    assert "hapax-imaginati" in earlyoom
    assert "studio-composit" not in earlyoom_args


def test_oom_enforcer_service_bounds_each_timer_activation() -> None:
    service = (REPO_ROOT / "systemd/units/hapax-oom-score-enforce.service").read_text(
        encoding="utf-8"
    )

    assert "Type=oneshot" in service
    assert "TimeoutStartSec=25s" in service


def test_recurring_oom_audit_services_bound_each_timer_activation() -> None:
    for unit in (
        "hapax-oom-policy-audit.service",
        "hapax-root-required-deploy-audit.service",
    ):
        service = (REPO_ROOT / "systemd" / "units" / unit).read_text(encoding="utf-8")
        assert "Type=oneshot" in service
        assert "TimeoutStartSec=2min" in service


def test_source_check_rejects_production_sudoers_identity_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HAPAX_OOM_SUDOERS_DEST", "/etc/sudoers.d/hapax-oom-score-enforce")
    monkeypatch.setenv("HAPAX_OOM_TARGET_USER", "hapax")
    monkeypatch.setenv("HAPAX_OOM_TARGET_UID", "999")
    monkeypatch.setenv("HAPAX_OOM_TARGET_GID", "1000")
    monkeypatch.setenv("HAPAX_OOM_TARGET_HOME", "/home/hapax")
    monkeypatch.setenv(
        "HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT",
        "/home/hapax/.local/state/hapax/root-required/current-source",
    )

    result = subprocess.run(
        [str(INSTALLER), "--check"],
        text=True,
        capture_output=True,
        check=False,
        env=os.environ.copy(),
    )

    assert result.returncode == 1
    assert "fixed to hapax/UID 1000" in result.stderr
    assert "next action:" in result.stderr


def test_whole_script_root_mode_refuses_user_owned_lock_symlink(tmp_path: Path) -> None:
    state_root = tmp_path / "root-state"
    state_root.mkdir()
    protected = tmp_path / "protected-target"
    protected.write_text("sentinel\n", encoding="utf-8")
    lock = state_root / ".lock"
    lock.symlink_to(protected)
    live = tmp_path / "sbin" / "hapax-oom-score-enforce"

    result = subprocess.run(
        [str(INSTALLER), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_ENFORCER_DEST": str(live),
            "HAPAX_OOM_INSTALL_SUDO": "",
            "HAPAX_OOM_INSTALL_TEST_ACTUAL_UID": "0",
            "HAPAX_ROOT_REQUIRED_STATE_ROOT": str(state_root),
            "HAPAX_ROOT_REQUIRED_LOCK_FILE": str(lock),
        },
    )

    assert result.returncode == 2
    assert "whole-script root execution is refused" in result.stderr
    assert protected.read_text(encoding="utf-8") == "sentinel\n"
    assert lock.is_symlink()
    assert not live.exists()


def test_nonroot_installer_refuses_shared_lock_symlink_before_mutation(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    protected = tmp_path / "protected-target"
    protected.write_text("sentinel\n", encoding="utf-8")
    lock = state_root / ".lock"
    lock.symlink_to(protected)
    live = tmp_path / "sbin" / "hapax-oom-score-enforce"

    result = subprocess.run(
        [str(INSTALLER), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_ENFORCER_DEST": str(live),
            "HAPAX_OOM_INSTALL_SUDO": "",
            "HAPAX_ROOT_REQUIRED_STATE_ROOT": str(state_root),
            "HAPAX_ROOT_REQUIRED_LOCK_FILE": str(lock),
            "HAPAX_ROOT_REQUIRED_LOCK_HELD": "1",
        },
    )

    assert result.returncode == 1
    assert "refused unsafe shared lock" in result.stderr
    assert protected.read_text(encoding="utf-8") == "sentinel\n"
    assert lock.is_symlink()
    assert not live.exists()


def test_installer_rejects_forged_inherited_lock_descriptor_before_mutation(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    lock = state_root / ".lock"
    forged = tmp_path / "forged-lock"
    forged_fd = os.open(forged, os.O_CREAT | os.O_RDWR, 0o600)
    live = tmp_path / "sbin" / "hapax-oom-score-enforce"
    try:
        result = subprocess.run(
            [str(INSTALLER), "--install"],
            text=True,
            capture_output=True,
            check=False,
            pass_fds=(forged_fd,),
            env={
                **os.environ,
                "HAPAX_OOM_ENFORCER_DEST": str(live),
                "HAPAX_OOM_INSTALL_SUDO": "",
                "HAPAX_ROOT_REQUIRED_STATE_ROOT": str(state_root),
                "HAPAX_ROOT_REQUIRED_LOCK_FILE": str(lock),
                "HAPAX_ROOT_REQUIRED_LOCK_FD": str(forged_fd),
            },
        )
    finally:
        os.close(forged_fd)

    assert result.returncode == 1
    assert "refused invalid shared lock descriptor" in result.stderr
    assert not lock.exists()
    assert not live.exists()


def test_p0_oom_containment_install_and_verify_live_against_temp_destinations(
    tmp_path: Path,
) -> None:
    system_dir = tmp_path / "systemd-system"
    target_home = tmp_path / "target-home"
    root_home = tmp_path / "root-home"
    user_dir = target_home / ".config" / "systemd" / "user"
    user_control_dir = target_home / ".config" / "systemd" / "user.control"
    stale_user_system_units = (
        "hapax-root-failure-intake@.service",
        "hapax-oom-score-enforce.service",
        "hapax-oom-score-enforce.timer",
    )
    for unit in stale_user_system_units:
        path = user_dir / unit
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[Unit]\nDescription=stale user copy\n", encoding="utf-8")
    stale_control = user_control_dir / "app.slice.d" / "50-MemoryHigh.conf"
    stale_control.parent.mkdir(parents=True)
    stale_control.write_text("[Slice]\nMemoryHigh=1G\n", encoding="utf-8")
    stale_low = user_control_dir / "app.slice.d" / "50-MemoryLow.conf"
    stale_min = user_control_dir / "app.slice.d" / "50-MemoryMin.conf"
    stale_low.write_text("[Slice]\nMemoryLow=64G\n", encoding="utf-8")
    stale_min.write_text("[Slice]\nMemoryMin=32G\n", encoding="utf-8")
    legacy_audio_overrides = {
        "pipewire.service.d/override.conf": "[Service]\nOOMScoreAdjust=-900\nLimitNOFILE=8192\n",
        "pipewire-pulse.service.d/override.conf": "[Service]\nOOMScoreAdjust=-900\n",
        "wireplumber.service.d/override.conf": "[Service]\nOOMScoreAdjust=-900\n",
    }
    for relative, content in legacy_audio_overrides.items():
        path = user_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    earlyoom_dest = tmp_path / "earlyoom"
    enforcer_dest = tmp_path / "sbin" / "hapax-oom-score-enforce"
    root_failure_dest = tmp_path / "sbin" / "hapax-root-failure-intake"
    root_defer = tmp_path / "root-required"
    installed_source = tmp_path / "current-source"
    snapshot_dest = installed_source / "scripts" / "install-p0-oom-containment"
    snapshot_dest.parent.mkdir(parents=True)
    snapshot_target = tmp_path / "snapshot-symlink-target"
    snapshot_target.write_text("do not overwrite\n", encoding="utf-8")
    snapshot_dest.symlink_to(snapshot_target)
    sibling_dir = root_defer / "other-sha" / "oom-containment"
    sibling_dir.mkdir(parents=True)
    (sibling_dir / "RUNBOOK.txt").write_text("run other installer\n", encoding="utf-8")
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _write_proc(proc_root, 900, name="systemd", uid=1000, oom_score=100)
    _write_recovery_procs(proc_root)
    systemctl_calls = tmp_path / "systemctl-calls.txt"
    systemctl_calls.write_text("", encoding="utf-8")
    systemctl_calls.chmod(0o666)
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {systemctl_calls!s}\n"
        f'if [[ "$*" == "--user enable --now hapax-oom-policy-audit.timer" ]]; then test -x {tmp_path / "sbin" / "hapax-oom-policy-audit"!s} && test -f {user_dir / "hapax-oom-policy-audit.timer"!s} || exit 42; fi\n'
        f'if [[ "$*" == "--user enable --now hapax-root-required-deploy-audit.timer" ]]; then test -x {tmp_path / "sbin" / "hapax-root-required-deploy-audit"!s} && test -f {user_dir / "hapax-root-required-deploy-audit.timer"!s} || exit 43; fi\n'
        'case "$*" in\n'
        '  *"show user@1000.service -p MainPID --value"*) printf "900\\n" ;;\n'
        f"{_systemctl_system_memory_cases(RECOVERY_SYSTEM_UNIT_PIDS)}\n"
        f"{_systemctl_user_unit_cases()}\n"
        f"{_systemctl_app_slice_cases()}\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)
    runuser_calls = tmp_path / "runuser-calls.txt"
    fake_runuser = tmp_path / "runuser"
    fake_runuser.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {runuser_calls!s}\n"
        'while [ "$1" != "--" ]; do shift; done\n'
        "shift\n"
        'exec "$@"\n',
        encoding="utf-8",
    )
    fake_runuser.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER), "--install", "--verify-live"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(root_home),
            "HAPAX_OOM_SYSTEMD_SYSTEM_DIR": str(system_dir),
            "HAPAX_OOM_SYSTEMD_USER_DIR": str(user_dir),
            "HAPAX_OOM_SYSTEMD_USER_CONTROL_DIR": str(user_control_dir),
            "HAPAX_OOM_TARGET_UID": "1000",
            "HAPAX_OOM_TARGET_HOME": str(target_home),
            "HAPAX_OOM_EARLYOOM_DEST": str(earlyoom_dest),
            "HAPAX_OOM_ENFORCER_DEST": str(enforcer_dest),
            "HAPAX_ROOT_FAILURE_INTAKE_DEST": str(root_failure_dest),
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_EFFECTIVE_UID": "0",
            "HAPAX_OOM_RUNUSER": str(fake_runuser),
            "HAPAX_OOM_INSTALL_SUDO": "",
            "HAPAX_OOM_PROC_ROOT": str(proc_root),
            "HAPAX_POST_MERGE_ROOT_DEFER_DIR": str(root_defer),
            "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": REPO_HEAD,
            "HAPAX_ROOT_REQUIRED_GIT_REPO": str(REPO_ROOT),
            "HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT": str(installed_source),
        },
    )

    assert result.returncode == 0, result.stderr
    assert sibling_dir.exists()
    assert (
        tmp_path / "root-state" / "installed-receipts" / "oom-containment.sha"
    ).read_text().strip() == REPO_HEAD
    assert (installed_source / "scripts" / "install-p0-oom-containment").is_file()
    assert not snapshot_dest.is_symlink()
    assert snapshot_dest.read_bytes() == INSTALLER.read_bytes()
    assert snapshot_target.read_text(encoding="utf-8") == "do not overwrite\n"
    user_manager_dropin = (system_dir / "user@1000.service.d" / "oom.conf").read_text(
        encoding="utf-8"
    )
    assert "OOMScoreAdjust=100" in user_manager_dropin
    assert "MemoryMax=96G" in user_manager_dropin
    app_dropin = user_dir / "app.slice.d" / "oom-containment.conf"
    assert app_dropin.is_file()
    assert not app_dropin.is_symlink()
    assert "MemorySwapMax=8G" in app_dropin.read_text(encoding="utf-8")
    assert "MemoryLow=16G" in app_dropin.read_text(encoding="utf-8")
    session_dropin = user_dir / "session.slice.d" / "oom-containment.conf"
    assert session_dropin.is_file()
    assert not session_dropin.is_symlink()
    assert "MemoryLow=2G" in session_dropin.read_text(encoding="utf-8")
    assert "MemoryMin=1G" in session_dropin.read_text(encoding="utf-8")
    assert (system_dir / "user-1000.slice.d" / "oom-containment.conf").is_file()
    assert "MemoryMin=10G" in (system_dir / "user.slice.d" / "oom-containment.conf").read_text(
        encoding="utf-8"
    )
    assert "MemoryLow=24G" in (system_dir / "system.slice.d" / "oom-containment.conf").read_text(
        encoding="utf-8"
    )
    assert "EARLYOOM_ARGS=" in earlyoom_dest.read_text(encoding="utf-8")
    assert enforcer_dest.is_file()
    trigger_dest = Path(os.environ["HAPAX_OOM_TRIGGER_DEST"])
    sudoers_dest = Path(os.environ["HAPAX_OOM_SUDOERS_DEST"])
    sudoers_reference = Path(os.environ["HAPAX_OOM_SUDOERS_REFERENCE_DEST"])
    assert trigger_dest.is_file() and os.access(trigger_dest, os.X_OK)
    assert sudoers_dest.is_file()
    assert sudoers_dest.stat().st_mode & 0o777 == 0o440
    assert sudoers_dest.stat().st_uid == os.getuid()
    assert sudoers_dest.stat().st_gid == os.getgid()
    assert sudoers_reference.is_file()
    assert sudoers_reference.stat().st_mode & 0o777 == 0o444
    assert sudoers_reference.stat().st_uid == os.getuid()
    assert sudoers_reference.stat().st_gid == os.getgid()
    assert root_failure_dest.is_file()
    assert (tmp_path / "sbin" / "hapax-oom-policy-audit").is_file()
    assert (tmp_path / "sbin" / "hapax-root-required-deploy-audit").is_file()
    for unit in (
        "hapax-oom-policy-audit.service",
        "hapax-oom-policy-audit.timer",
        "hapax-root-required-deploy-audit.service",
        "hapax-root-required-deploy-audit.timer",
    ):
        unit_path = user_dir / unit
        assert unit_path.is_file()
        assert not unit_path.is_symlink()
    for unit in stale_user_system_units:
        assert not (user_dir / unit).exists()
    assert not stale_control.exists()
    assert not stale_low.exists()
    assert not stale_min.exists()
    for relative in legacy_audio_overrides:
        assert "OOMScoreAdjust=" not in (user_dir / relative).read_text(encoding="utf-8")
    assert "LimitNOFILE=8192" in (user_dir / "pipewire.service.d" / "override.conf").read_text(
        encoding="utf-8"
    )
    assert not (root_home / ".config" / "systemd").exists()
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "daemon-reload" in calls
    assert "enable --now earlyoom.service" in calls
    assert "restart earlyoom.service" in calls
    assert "set-property --runtime user.slice" in calls
    assert "is-enabled --quiet earlyoom.service" in calls
    assert "is-active --quiet earlyoom.service" in calls
    assert (
        f"-u hapax -- env XDG_RUNTIME_DIR=/run/user/1000 {fake_systemctl} --user daemon-reload"
        in runuser_calls.read_text(encoding="utf-8")
    )
    user_calls = runuser_calls.read_text(encoding="utf-8")
    assert "--user enable --now hapax-oom-policy-audit.timer" in user_calls
    assert "--user enable --now hapax-root-required-deploy-audit.timer" in user_calls
    assert "--user is-enabled --quiet hapax-oom-policy-audit.timer" in user_calls
    assert "--user is-active --quiet hapax-root-required-deploy-audit.timer" in user_calls
    assert "--user show hapax-oom-policy-audit.service -p TimeoutStartUSec --value" in user_calls
    assert (
        "--user show hapax-root-required-deploy-audit.service -p TimeoutStartUSec --value"
        in user_calls
    )
    assert "--user show hapax-oom-policy-audit.service -p Environment --value" in user_calls
    assert (
        "--user show hapax-root-required-deploy-audit.service -p Environment --value" in user_calls
    )
    for unit in stale_user_system_units:
        assert f"--user disable --now {unit}" in user_calls


def test_unversioned_oom_install_source_fails_before_live_mutation(tmp_path: Path) -> None:
    source = tmp_path / "not-a-repo"
    source.mkdir()
    live = tmp_path / "live-earlyoom"

    result = subprocess.run(
        [str(INSTALLER), "--source", str(source), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_INSTALL_SUDO": "",
            "HAPAX_OOM_EARLYOOM_DEST": str(live),
            "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": "",
        },
    )

    assert result.returncode == 1
    assert "source has no package SHA" in result.stderr
    assert not live.exists()


@pytest.mark.parametrize("drift_kind", ("symlink", "git_mode"))
def test_claimed_oom_commit_rejects_substituted_source_before_live_mutation(
    tmp_path: Path,
    drift_kind: str,
) -> None:
    source = tmp_path / "staged"
    _copy_oom_package(source)
    relative = Path("config/earlyoom/default")
    candidate = source / relative
    if drift_kind == "symlink":
        candidate.unlink()
        candidate.symlink_to(REPO_ROOT / relative)
    else:
        candidate.chmod(0o755)
    live = tmp_path / "live-earlyoom"

    result = subprocess.run(
        [str(INSTALLER), "--source", str(source), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_INSTALL_SUDO": "",
            "HAPAX_OOM_EARLYOOM_DEST": str(live),
            "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": REPO_HEAD,
            "HAPAX_ROOT_REQUIRED_GIT_REPO": str(REPO_ROOT),
        },
    )

    assert result.returncode == 1
    assert "not a regular file with the claimed Git mode" in result.stderr
    assert str(relative) in result.stderr
    assert not live.exists()


def test_claimed_oom_commit_rejects_tracked_destination_mode_drift(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "oom-mode@example.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "OOM Mode Test"], cwd=repo, check=True)
    _copy_oom_package(repo)
    relative = Path("scripts/install-p0-oom-containment")
    (repo / relative).chmod(0o644)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "mode drift"], cwd=repo, check=True, capture_output=True)
    candidate_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()
    live = tmp_path / "live-earlyoom"

    result = subprocess.run(
        [str(INSTALLER), "--source", str(repo), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_INSTALL_SUDO": "",
            "HAPAX_OOM_EARLYOOM_DEST": str(live),
            "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": candidate_sha,
            "HAPAX_ROOT_REQUIRED_GIT_REPO": str(repo),
        },
    )

    assert result.returncode == 1
    assert "Git mode violates the destination contract" in result.stderr
    assert str(relative) in result.stderr
    assert not live.exists()


def test_oom_manifest_shrink_fails_before_live_mutation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "oom-test@example.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "OOM Test"], cwd=repo, check=True)
    _copy_oom_package(repo)
    manifest = repo / "config/root-required/oom-containment.files"
    retired_rel = "config/earlyoom/retired-policy"
    manifest.write_text(manifest.read_text(encoding="utf-8") + f"{retired_rel}\n", encoding="utf-8")
    retired = repo / retired_rel
    retired.parent.mkdir(parents=True, exist_ok=True)
    retired.write_text("formerly installed\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "installed package"], cwd=repo, check=True, capture_output=True
    )
    installed_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()

    manifest.write_text(
        (REPO_ROOT / "config/root-required/oom-containment.files").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    retired.unlink()
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "candidate drops path"], cwd=repo, check=True, capture_output=True
    )
    candidate_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()

    receipt_root = tmp_path / "receipts"
    receipt_root.mkdir()
    receipt = receipt_root / "oom-containment.sha"
    receipt.write_text(f"{installed_sha}\n", encoding="utf-8")
    live = tmp_path / "live-earlyoom"
    result = subprocess.run(
        [str(INSTALLER), "--source", str(repo), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_INSTALL_SUDO": "",
            "HAPAX_OOM_EARLYOOM_DEST": str(live),
            "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": candidate_sha,
            "HAPAX_ROOT_REQUIRED_GIT_REPO": str(repo),
            "HAPAX_ROOT_REQUIRED_INSTALLED_RECEIPT_ROOT": str(receipt_root),
        },
    )

    assert result.returncode == 1
    assert f"refusing OOM package removal or rename of {retired_rel}" in result.stderr
    assert "explicit governed live-removal handling" in result.stderr
    assert receipt.read_text(encoding="utf-8").strip() == installed_sha
    assert not live.exists()


def test_oom_install_implies_live_verification() -> None:
    body = INSTALLER.read_text(encoding="utf-8")
    assert 'if [ "$INSTALL" -eq 1 ]; then\n    VERIFY_LIVE=1\nfi' in body
    assert "$TARGET_HOME/.cache/hapax/source-activation/worktree" in body


def test_oom_install_without_verify_flag_cannot_advance_receipts_after_live_probe_failure(
    tmp_path: Path,
) -> None:
    system_dir = tmp_path / "systemd-system"
    user_dir = tmp_path / "systemd-user"
    user_control_dir = tmp_path / "systemd-user-control"
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        f"{_systemctl_system_memory_cases()}\n"
        f"{_systemctl_user_unit_cases()}\n"
        f"{_systemctl_app_slice_cases()}\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_SYSTEMD_SYSTEM_DIR": str(system_dir),
            "HAPAX_OOM_SYSTEMD_USER_DIR": str(user_dir),
            "HAPAX_OOM_SYSTEMD_USER_CONTROL_DIR": str(user_control_dir),
            "HAPAX_OOM_EARLYOOM_DEST": str(tmp_path / "earlyoom"),
            "HAPAX_OOM_ENFORCER_DEST": str(tmp_path / "sbin/hapax-oom-score-enforce"),
            "HAPAX_ROOT_FAILURE_INTAKE_DEST": str(tmp_path / "sbin/hapax-root-failure-intake"),
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_INSTALL_SUDO": "",
            "HAPAX_OOM_PROC_ROOT": str(proc_root),
            "HAPAX_OOM_TARGET_UID": "1000",
        },
    )

    assert result.returncode == 1
    assert "unable to read live user@1000.service MainPID" in result.stderr
    state_root = tmp_path / "root-state"
    assert not (state_root / "installed-receipts/oom-containment.sha").exists()
    assert not (state_root / "desired-receipts/oom-containment.sha").exists()
    assert not (tmp_path / "installed-source").exists()


def test_oom_install_rejects_stale_loaded_enforcer_timeout_before_receipts(
    tmp_path: Path,
) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"show hapax-oom-policy-audit.service -p TimeoutStartUSec --value"* ]]; then printf "2min\\n"; fi\n'
        'if [[ "$*" == *"show hapax-root-required-deploy-audit.service -p TimeoutStartUSec --value"* ]]; then printf "2min\\n"; fi\n'
        f'if [[ "$*" == *"show hapax-oom-policy-audit.service -p Environment --value"* ]]; then printf "{SAFE_AUDIT_ENVIRONMENT}\\n"; fi\n'
        f'if [[ "$*" == *"show hapax-root-required-deploy-audit.service -p Environment --value"* ]]; then printf "{SAFE_AUDIT_ENVIRONMENT}\\n"; fi\n'
        'if [[ "$*" == *"show hapax-oom-score-enforce.service -p TimeoutStartUSec --value"* ]]; then printf "infinity\\n"; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_SYSTEMD_SYSTEM_DIR": str(tmp_path / "systemd-system"),
            "HAPAX_OOM_SYSTEMD_USER_DIR": str(tmp_path / "systemd-user"),
            "HAPAX_OOM_SYSTEMD_USER_CONTROL_DIR": str(tmp_path / "systemd-user-control"),
            "HAPAX_OOM_EARLYOOM_DEST": str(tmp_path / "earlyoom"),
            "HAPAX_OOM_ENFORCER_DEST": str(tmp_path / "sbin/hapax-oom-score-enforce"),
            "HAPAX_ROOT_FAILURE_INTAKE_DEST": str(tmp_path / "sbin/hapax-root-failure-intake"),
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_INSTALL_SUDO": "",
            "HAPAX_OOM_PROC_ROOT": str(proc_root),
            "HAPAX_OOM_TARGET_UID": "1000",
        },
    )

    assert result.returncode == 1
    assert (
        "live hapax-oom-score-enforce.service TimeoutStartUSec drift: actual=infinity expected=25s"
    ) in result.stderr
    state_root = tmp_path / "root-state"
    assert not (state_root / "installed-receipts/oom-containment.sha").exists()
    assert not (tmp_path / "installed-source").exists()


def test_oom_install_rejects_stretched_effective_enforcer_timer_before_receipts(
    tmp_path: Path,
) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        '  *"show hapax-oom-score-enforce.timer -p TimersMonotonic --value"*) '
        "printf '%s\\n' 'OnBootUSec=30s OnUnitActiveUSec=1d' ;;\n"
        f"{_systemctl_system_memory_cases()}\n"
        f"{_systemctl_user_unit_cases()}\n"
        f"{_systemctl_app_slice_cases()}\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_SYSTEMD_SYSTEM_DIR": str(tmp_path / "systemd-system"),
            "HAPAX_OOM_SYSTEMD_USER_DIR": str(tmp_path / "systemd-user"),
            "HAPAX_OOM_SYSTEMD_USER_CONTROL_DIR": str(tmp_path / "systemd-user-control"),
            "HAPAX_OOM_EARLYOOM_DEST": str(tmp_path / "earlyoom"),
            "HAPAX_OOM_ENFORCER_DEST": str(tmp_path / "sbin/hapax-oom-score-enforce"),
            "HAPAX_ROOT_FAILURE_INTAKE_DEST": str(tmp_path / "sbin/hapax-root-failure-intake"),
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_INSTALL_SUDO": "",
            "HAPAX_OOM_PROC_ROOT": str(proc_root),
            "HAPAX_OOM_TARGET_UID": "1000",
        },
    )

    assert result.returncode == 1
    assert "effective hapax-oom-score-enforce.timer cadence drift" in result.stderr
    assert "OnUnitActiveUSec=1d" in result.stderr
    state_root = tmp_path / "root-state"
    assert not (state_root / "installed-receipts/oom-containment.sha").exists()
    assert not (tmp_path / "installed-source").exists()


def test_oom_install_rejects_effective_failure_intake_dropin_before_receipts(
    tmp_path: Path,
) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    fake_systemctl = tmp_path / "systemctl"
    failure_unit = "hapax-root-failure-intake@hapax-oom-score-enforce.service.service"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        f'  *"show {failure_unit} -p DropInPaths --value"*) '
        "printf '%s\\n' '/etc/systemd/system/hapax-root-failure-intake@.service.d/override.conf' ;;\n"
        f'  *"show {failure_unit} -p ExecStart --value"*) '
        "printf '%s\\n' '{ path=/usr/bin/true ; argv[]=/usr/bin/true ; }' ;;\n"
        f"{_systemctl_system_memory_cases()}\n"
        f"{_systemctl_user_unit_cases()}\n"
        f"{_systemctl_app_slice_cases()}\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_SYSTEMD_SYSTEM_DIR": str(tmp_path / "systemd-system"),
            "HAPAX_OOM_SYSTEMD_USER_DIR": str(tmp_path / "systemd-user"),
            "HAPAX_OOM_SYSTEMD_USER_CONTROL_DIR": str(tmp_path / "systemd-user-control"),
            "HAPAX_OOM_EARLYOOM_DEST": str(tmp_path / "earlyoom"),
            "HAPAX_OOM_ENFORCER_DEST": str(tmp_path / "sbin/hapax-oom-score-enforce"),
            "HAPAX_ROOT_FAILURE_INTAKE_DEST": str(tmp_path / "sbin/hapax-root-failure-intake"),
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_INSTALL_SUDO": "",
            "HAPAX_OOM_PROC_ROOT": str(proc_root),
            "HAPAX_OOM_TARGET_UID": "1000",
        },
    )

    assert result.returncode == 1
    assert f"effective {failure_unit} unit-source drift" in result.stderr
    assert "override.conf" in result.stderr
    state_root = tmp_path / "root-state"
    assert not (state_root / "installed-receipts/oom-containment.sha").exists()
    assert not (tmp_path / "installed-source").exists()


@pytest.mark.parametrize(
    ("property_name", "bad_value", "expected_error"),
    [
        ("ExecStart", "{ path=/usr/bin/true ; argv[]=/usr/bin/true ; }", "ExecStart drift"),
        ("User", "root", "identity/limit drift"),
        ("Environment", "PATH=/tmp/shadow", "identity/limit drift"),
        ("StartLimitIntervalUSec", "infinity", "identity/limit drift"),
        ("StartLimitBurst", "99", "identity/limit drift"),
    ],
)
def test_oom_install_rejects_effective_failure_intake_property_drift_before_receipts(
    tmp_path: Path,
    property_name: str,
    bad_value: str,
    expected_error: str,
) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    fake_systemctl = tmp_path / "systemctl"
    failure_unit = "hapax-root-failure-intake@hapax-oom-score-enforce.service.service"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        f'  *"show {failure_unit} -p {property_name} --value"*) '
        f"printf '%s\\n' '{bad_value}' ;;\n"
        f"{_systemctl_system_memory_cases()}\n"
        f"{_systemctl_user_unit_cases()}\n"
        f"{_systemctl_app_slice_cases()}\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_SYSTEMD_SYSTEM_DIR": str(tmp_path / "systemd-system"),
            "HAPAX_OOM_SYSTEMD_USER_DIR": str(tmp_path / "systemd-user"),
            "HAPAX_OOM_SYSTEMD_USER_CONTROL_DIR": str(tmp_path / "systemd-user-control"),
            "HAPAX_OOM_EARLYOOM_DEST": str(tmp_path / "earlyoom"),
            "HAPAX_OOM_ENFORCER_DEST": str(tmp_path / "sbin/hapax-oom-score-enforce"),
            "HAPAX_ROOT_FAILURE_INTAKE_DEST": str(tmp_path / "sbin/hapax-root-failure-intake"),
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_INSTALL_SUDO": "",
            "HAPAX_OOM_PROC_ROOT": str(proc_root),
            "HAPAX_OOM_TARGET_UID": "1000",
        },
    )

    assert result.returncode == 1
    assert f"effective {failure_unit} {expected_error}" in result.stderr
    state_root = tmp_path / "root-state"
    assert not (state_root / "installed-receipts/oom-containment.sha").exists()
    assert not (tmp_path / "installed-source").exists()


def test_oom_install_rejects_mutable_loaded_audit_path_before_receipts(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"show hapax-oom-policy-audit.service -p TimeoutStartUSec --value"* ]]; then printf "2min\\n"; fi\n'
        'if [[ "$*" == *"show hapax-root-required-deploy-audit.service -p TimeoutStartUSec --value"* ]]; then printf "2min\\n"; fi\n'
        'if [[ "$*" == *"show hapax-oom-policy-audit.service -p Environment --value"* ]]; then printf "PATH=/tmp/shadow\\n"; fi\n'
        f'if [[ "$*" == *"show hapax-root-required-deploy-audit.service -p Environment --value"* ]]; then printf "{SAFE_AUDIT_ENVIRONMENT}\\n"; fi\n'
        'if [[ "$*" == *"show hapax-oom-score-enforce.service -p TimeoutStartUSec --value"* ]]; then printf "25s\\n"; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_SYSTEMD_SYSTEM_DIR": str(tmp_path / "systemd-system"),
            "HAPAX_OOM_SYSTEMD_USER_DIR": str(tmp_path / "systemd-user"),
            "HAPAX_OOM_SYSTEMD_USER_CONTROL_DIR": str(tmp_path / "systemd-user-control"),
            "HAPAX_OOM_EARLYOOM_DEST": str(tmp_path / "earlyoom"),
            "HAPAX_OOM_ENFORCER_DEST": str(tmp_path / "sbin/hapax-oom-score-enforce"),
            "HAPAX_ROOT_FAILURE_INTAKE_DEST": str(tmp_path / "sbin/hapax-root-failure-intake"),
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_INSTALL_SUDO": "",
            "HAPAX_OOM_PROC_ROOT": str(proc_root),
        },
    )

    assert result.returncode == 1
    assert (
        "live hapax-oom-policy-audit.service Environment drift: "
        "actual=PATH=/tmp/shadow expected to contain " + SAFE_AUDIT_ENVIRONMENT
    ) in result.stderr
    state_root = tmp_path / "root-state"
    assert not (state_root / "installed-receipts/oom-containment.sha").exists()


@pytest.mark.parametrize(
    ("property_name", "bad_value"),
    (
        ("Slice", "wrong.slice"),
        ("MemoryLow", "0"),
        ("MemoryMin", "0"),
        ("NoNewPrivileges", "no"),
    ),
)
def test_oom_install_rejects_effective_protected_unit_reservation_drift_before_receipts(
    tmp_path: Path,
    property_name: str,
    bad_value: str,
) -> None:
    system_dir = tmp_path / "systemd-system"
    user_dir = tmp_path / "systemd-user"
    user_control_dir = tmp_path / "systemd-user-control"
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _write_proc(
        proc_root,
        900,
        name="systemd",
        uid=1000,
        oom_score=100,
        cgroup="/user.slice/user-1000.slice/user@1000.service",
    )
    _write_recovery_procs(proc_root)
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        '  *"show user@1000.service -p MainPID --value"*) printf "900\\n" ;;\n'
        f"{_systemctl_system_memory_cases(RECOVERY_SYSTEM_UNIT_PIDS)}\n"
        f"{_systemctl_app_slice_cases()}\n"
        f"{_systemctl_user_unit_cases(effective_overrides={'pipewire.service': {property_name: bad_value}})}\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_SYSTEMD_SYSTEM_DIR": str(system_dir),
            "HAPAX_OOM_SYSTEMD_USER_DIR": str(user_dir),
            "HAPAX_OOM_SYSTEMD_USER_CONTROL_DIR": str(user_control_dir),
            "HAPAX_OOM_EARLYOOM_DEST": str(tmp_path / "earlyoom"),
            "HAPAX_OOM_ENFORCER_DEST": str(tmp_path / "sbin/hapax-oom-score-enforce"),
            "HAPAX_ROOT_FAILURE_INTAKE_DEST": str(tmp_path / "sbin/hapax-root-failure-intake"),
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_INSTALL_SUDO": "",
            "HAPAX_OOM_PROC_ROOT": str(proc_root),
            "HAPAX_OOM_TARGET_UID": "1000",
        },
    )

    assert result.returncode == 1
    assert f"live user unit {property_name} drift for pipewire.service" in result.stderr
    state_root = tmp_path / "root-state"
    assert not (state_root / "installed-receipts/oom-containment.sha").exists()
    assert not (state_root / "desired-receipts/oom-containment.sha").exists()
    assert not (tmp_path / "installed-source").exists()


def _write_proc(
    proc_root: Path,
    pid: int,
    *,
    name: str,
    uid: int,
    oom_score: int,
    cgroup: str | None = None,
) -> None:
    pid_dir = proc_root / str(pid)
    pid_dir.mkdir(parents=True, exist_ok=True)
    (pid_dir / "status").write_text(
        f"Name:\t{name}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n", encoding="utf-8"
    )
    (pid_dir / "oom_score_adj").write_text(f"{oom_score}\n", encoding="utf-8")
    if cgroup is not None:
        (pid_dir / "cgroup").write_text(f"0::{cgroup}\n", encoding="utf-8")


def _write_recovery_procs(proc_root: Path) -> None:
    for unit, pid in RECOVERY_SYSTEM_UNIT_PIDS.items():
        _write_proc(
            proc_root,
            pid,
            name=unit.removesuffix(".service"),
            uid=0,
            oom_score=RECOVERY_SYSTEM_UNIT_SCORES[unit],
            cgroup=f"/system.slice/{unit}",
        )


def test_stale_deferred_oom_package_drains_without_rolling_back_newer_install(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "oom-test@example.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "OOM Test"], cwd=repo, check=True)
    marker = repo / "marker"
    marker.write_text("A\n", encoding="utf-8")
    subprocess.run(["git", "add", "marker"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "A"], cwd=repo, check=True, capture_output=True)
    sha_a = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()
    marker.write_text("B\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "B"], cwd=repo, check=True, capture_output=True)
    sha_b = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()

    defer_root = tmp_path / "root-required"
    drain_dir = defer_root / sha_a / "oom-containment"
    drain_dir.mkdir(parents=True)
    (drain_dir / "RUNBOOK.txt").write_text("stale A\n", encoding="utf-8")
    receipt_root = defer_root / "installed-receipts"
    receipt_root.mkdir()
    receipt = receipt_root / "oom-containment.sha"
    receipt.write_text(f"{sha_b}\n", encoding="utf-8")
    live_marker = tmp_path / "live-earlyoom"
    live_marker.write_text("newer B policy\n", encoding="utf-8")
    (drain_dir / ".hapax-root-required-package-sha").write_text(f"{sha_a}\n", encoding="utf-8")

    result = subprocess.run(
        [str(INSTALLER), "--source", str(drain_dir), "--install", "--verify-live"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_INSTALL_SUDO": "",
            "HAPAX_OOM_EARLYOOM_DEST": str(live_marker),
            "HAPAX_POST_MERGE_ROOT_DEFER_DIR": str(defer_root),
            "HAPAX_ROOT_REQUIRED_DRAIN_DIR": str(drain_dir),
            "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": sha_a,
            "HAPAX_ROOT_REQUIRED_INSTALLED_RECEIPT_ROOT": str(receipt_root),
            "HAPAX_ROOT_REQUIRED_GIT_REPO": str(repo),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "superseded" in result.stdout
    assert drain_dir.is_dir()
    assert (drain_dir / "DRAINED.txt").is_file()
    assert not (drain_dir / "RUNBOOK.txt").exists()
    assert receipt.read_text(encoding="utf-8").strip() == sha_b
    assert live_marker.read_text(encoding="utf-8") == "newer B policy\n"


def test_installed_oom_repair_cannot_erase_newer_desired_receipt(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "oom-test@example.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "OOM Test"], cwd=repo, check=True)
    marker = repo / "marker"
    marker.write_text("A\n", encoding="utf-8")
    subprocess.run(["git", "add", "marker"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "A"], cwd=repo, check=True, capture_output=True)
    sha_a = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()
    marker.write_text("B\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "B"], cwd=repo, check=True, capture_output=True)
    sha_b = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()

    defer_root = tmp_path / "root-required"
    drain_dir = defer_root / sha_a / "oom-containment"
    drain_dir.mkdir(parents=True)
    (drain_dir / "RUNBOOK.txt").write_text("stale repair A\n", encoding="utf-8")
    (drain_dir / ".hapax-root-required-package-sha").write_text(f"{sha_a}\n", encoding="utf-8")
    installed_root = tmp_path / "root-state" / "installed-receipts"
    desired_root = tmp_path / "root-state" / "desired-receipts"
    installed_root.mkdir(parents=True)
    desired_root.mkdir(parents=True)
    installed = installed_root / "oom-containment.sha"
    desired = desired_root / "oom-containment.sha"
    installed.write_text(f"{sha_a}\n", encoding="utf-8")
    desired.write_text(f"{sha_b}\n", encoding="utf-8")
    live_marker = tmp_path / "live-earlyoom"
    live_marker.write_text("installed A policy\n", encoding="utf-8")

    result = subprocess.run(
        [str(INSTALLER), "--source", str(drain_dir), "--install", "--verify-live"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_INSTALL_SUDO": "",
            "HAPAX_OOM_EARLYOOM_DEST": str(live_marker),
            "HAPAX_POST_MERGE_ROOT_DEFER_DIR": str(defer_root),
            "HAPAX_ROOT_REQUIRED_DRAIN_DIR": str(drain_dir),
            "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": sha_a,
            "HAPAX_ROOT_REQUIRED_INSTALLED_RECEIPT_ROOT": str(installed_root),
            "HAPAX_ROOT_REQUIRED_DESIRED_RECEIPT_ROOT": str(desired_root),
            "HAPAX_ROOT_REQUIRED_GIT_REPO": str(repo),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "superseded by desired" in result.stdout
    assert installed.read_text(encoding="utf-8").strip() == sha_a
    assert desired.read_text(encoding="utf-8").strip() == sha_b
    assert live_marker.read_text(encoding="utf-8") == "installed A policy\n"
    assert (drain_dir / "DRAINED.txt").is_file()


def test_oom_squash_equivalence_rejects_newer_manifest_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "manifest-test@example.test"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Manifest Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()

    subprocess.run(["git", "switch", "-c", "candidate"], cwd=repo, check=True, capture_output=True)
    candidate_manifest = repo / "config/root-required/oom-containment.files"
    candidate_manifest.parent.mkdir(parents=True)
    candidate_manifest.write_text(
        "config/root-required/oom-containment.files\nscripts/install-p0-oom-containment\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "candidate"], cwd=repo, check=True, capture_output=True)
    candidate_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()

    subprocess.run(
        ["git", "switch", "-c", "desired", base_sha], cwd=repo, check=True, capture_output=True
    )
    desired_manifest = repo / "config/root-required/oom-containment.files"
    desired_manifest.parent.mkdir(parents=True)
    desired_manifest.write_text(
        "config/root-required/oom-containment.files\nscripts/install-p0-oom-containment\nconfig/earlyoom/new-policy\n",
        encoding="utf-8",
    )
    extra = repo / "config/earlyoom/new-policy"
    extra.parent.mkdir(parents=True)
    extra.write_text("new owned policy\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "desired adds owned file"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    desired_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()

    defer_root = tmp_path / "root-required"
    stage = defer_root / candidate_sha / "oom-containment"
    stage.mkdir(parents=True)
    (stage / "RUNBOOK.txt").write_text("candidate\n", encoding="utf-8")
    (stage / ".hapax-root-required-package-sha").write_text(f"{candidate_sha}\n", encoding="utf-8")
    installed_root = tmp_path / "root-state/installed-receipts"
    desired_root = tmp_path / "root-state/desired-receipts"
    installed_root.mkdir(parents=True)
    desired_root.mkdir(parents=True)
    (installed_root / "oom-containment.sha").write_text(f"{candidate_sha}\n", encoding="utf-8")
    desired_receipt = desired_root / "oom-containment.sha"
    desired_receipt.write_text(f"{desired_sha}\n", encoding="utf-8")

    result = subprocess.run(
        [str(INSTALLER), "--source", str(stage), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_INSTALL_SUDO": "",
            "HAPAX_POST_MERGE_ROOT_DEFER_DIR": str(defer_root),
            "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": candidate_sha,
            "HAPAX_ROOT_REQUIRED_INSTALLED_RECEIPT_ROOT": str(installed_root),
            "HAPAX_ROOT_REQUIRED_DESIRED_RECEIPT_ROOT": str(desired_root),
            "HAPAX_ROOT_REQUIRED_GIT_REPO": str(repo),
        },
    )

    assert result.returncode == 1
    assert "refusing divergent OOM package desired=" in result.stderr
    assert desired_receipt.read_text(encoding="utf-8").strip() == desired_sha
    assert (stage / "RUNBOOK.txt").is_file()


def test_p0_oom_containment_install_applies_live_scores_and_scrubs_inherited_user_protection(
    tmp_path: Path,
) -> None:
    system_dir = tmp_path / "systemd-system"
    user_dir = tmp_path / "systemd-user"
    user_control_dir = tmp_path / "systemd-user-control"
    earlyoom_dest = tmp_path / "earlyoom"
    enforcer_dest = tmp_path / "sbin" / "hapax-oom-score-enforce"
    root_failure_dest = tmp_path / "sbin" / "hapax-root-failure-intake"
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    unit_pids = {
        "apcupsd.service": 200,
        "systemd-logind.service": 201,
        "systemd-resolved.service": 202,
        "systemd-timesyncd.service": 203,
        "NetworkManager.service": 204,
        "dbus-broker.service": 205,
        "sshd.service": 206,
        "user@1000.service": 900,
        "pipewire.service": 910,
        "pipewire-pulse.service": 911,
        "wireplumber.service": 912,
        "hapax-daimonion.service": 913,
        "studio-compositor.service": 914,
        "hapax-imagination.service": 915,
    }
    for unit, pid in unit_pids.items():
        cgroup = (
            _unit_cgroup(unit) if unit in PROTECTED_USER_UNIT_SCORES else f"/system.slice/{unit}"
        )
        _write_proc(proc_root, pid, name=unit.split(".")[0], uid=0, oom_score=0, cgroup=cgroup)
    _write_proc(
        proc_root,
        900,
        name="systemd",
        uid=1000,
        oom_score=-900,
        cgroup="/user.slice/user-1000.slice/user@1000.service",
    )
    _write_proc(proc_root, 901, name="codex", uid=1000, oom_score=-900)
    _write_proc(proc_root, 902, name="wireplumber", uid=1000, oom_score=-900)

    systemctl_calls = tmp_path / "systemctl-calls.txt"
    systemctl_calls.write_text("", encoding="utf-8")
    systemctl_calls.chmod(0o666)
    fake_systemctl = tmp_path / "systemctl"
    cases = "\n".join(
        f'  *"show {unit} -p MainPID --value"*) printf "{pid}\\n" ;;'
        for unit, pid in unit_pids.items()
        if not unit.startswith(("pipewire", "wireplumber", "hapax-", "studio-"))
    )
    user_cases = _systemctl_user_unit_cases(
        {unit: pid for unit, pid in unit_pids.items() if unit in PROTECTED_USER_UNIT_SCORES}
    )
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {systemctl_calls!s}\n"
        'case "$*" in\n'
        f"{cases}\n"
        f"{user_cases}\n"
        f"{_systemctl_system_memory_cases(unit_pids)}\n"
        f"{_systemctl_app_slice_cases()}\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    install_env = {
        **os.environ,
        "HAPAX_OOM_SYSTEMD_SYSTEM_DIR": str(system_dir),
        "HAPAX_OOM_SYSTEMD_USER_DIR": str(user_dir),
        "HAPAX_OOM_SYSTEMD_USER_CONTROL_DIR": str(user_control_dir),
        "HAPAX_OOM_EARLYOOM_DEST": str(earlyoom_dest),
        "HAPAX_OOM_ENFORCER_DEST": str(enforcer_dest),
        "HAPAX_ROOT_FAILURE_INTAKE_DEST": str(root_failure_dest),
        "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
        "HAPAX_OOM_INSTALL_SUDO": "",
        "HAPAX_OOM_PROC_ROOT": str(proc_root),
        "HAPAX_OOM_TARGET_UID": "1000",
    }
    result = subprocess.run(
        [str(INSTALLER), "--install", "--verify-live"],
        text=True,
        capture_output=True,
        check=False,
        env=install_env,
    )

    assert result.returncode == 0, result.stderr
    expected_scores = {
        200: -900,
        201: -800,
        202: -800,
        203: -800,
        204: -800,
        205: -900,
        206: 0,
        900: 100,
        901: 100,
        902: -900,
        910: -900,
        911: -900,
        912: -900,
        913: -500,
        914: -800,
        915: -800,
    }
    for pid, score in expected_scores.items():
        assert (proc_root / str(pid) / "oom_score_adj").read_text(encoding="utf-8").strip() == str(
            score
        )
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "set-property --runtime system.slice MemoryHigh=infinity MemoryMax=infinity" in calls
    assert "set-property --runtime user.slice MemoryHigh=infinity MemoryMax=infinity" in calls
    assert "set-property --runtime user-1000.slice MemoryHigh=80G MemoryMax=96G" in calls
    assert "set-property --runtime user@1000.service MemoryHigh=80G MemoryMax=96G" in calls
    assert (
        "set-property --runtime app.slice MemoryHigh=72G MemoryMax=88G MemorySwapMax=8G MemoryLow=16G MemoryMin=8G"
        in calls
    )
    assert (
        "set-property --runtime session.slice MemoryHigh=infinity MemoryMax=infinity "
        "MemorySwapMax=infinity MemoryLow=2G MemoryMin=1G" in calls
    )

    inactive_pids = {**unit_pids, "apcupsd.service": 0}
    inactive_cases = "\n".join(
        f'  *"show {unit} -p MainPID --value"*) printf "{pid}\\n" ;;'
        for unit, pid in inactive_pids.items()
        if not unit.startswith(("pipewire", "wireplumber", "hapax-", "studio-"))
    )
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        f"{inactive_cases}\n"
        f"{user_cases}\n"
        f"{_systemctl_system_memory_cases(inactive_pids)}\n"
        f"{_systemctl_app_slice_cases()}\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    inactive_result = subprocess.run(
        [str(INSTALLER), "--install", "--verify-live"],
        text=True,
        capture_output=True,
        check=False,
        env=install_env,
    )

    assert inactive_result.returncode == 1
    assert "recovery daemon has no live MainPID: apcupsd.service" in inactive_result.stderr

    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        f"{cases}\n"
        f"{user_cases}\n"
        f"{_systemctl_system_memory_cases(unit_pids, user_manager_score=0)}\n"
        f"{_systemctl_app_slice_cases()}\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    configured_drift_result = subprocess.run(
        [str(INSTALLER), "--install", "--verify-live"],
        text=True,
        capture_output=True,
        check=False,
        env=install_env,
    )

    assert configured_drift_result.returncode == 1
    assert (
        "effective user@1000.service OOMScoreAdjust drift: actual=0 expected=100"
        in configured_drift_result.stderr
    )


def test_installer_falls_back_to_sudo_when_direct_oom_score_write_fails(
    tmp_path: Path,
) -> None:
    system_dir = tmp_path / "systemd-system"
    user_dir = tmp_path / "systemd-user"
    user_control_dir = tmp_path / "systemd-user-control"
    earlyoom_dest = tmp_path / "earlyoom"
    enforcer_dest = tmp_path / "sbin" / "hapax-oom-score-enforce"
    root_failure_dest = tmp_path / "sbin" / "hapax-root-failure-intake"
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _write_proc(
        proc_root,
        900,
        name="systemd",
        uid=1000,
        oom_score=100,
        cgroup="/user.slice/user-1000.slice/user@1000.service",
    )
    _write_proc(
        proc_root,
        910,
        name="pipewire",
        uid=1000,
        oom_score=100,
        cgroup=_unit_cgroup("pipewire.service"),
    )
    _write_recovery_procs(proc_root)

    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        '  "show user@1000.service -p ActiveState --value") printf "active\\n" ;;\n'
        '  *"show user@1000.service -p MainPID --value"*) printf "900\\n" ;;\n'
        f"{_systemctl_user_unit_cases({'pipewire.service': 910})}\n"
        f"{_systemctl_system_memory_cases(RECOVERY_SYSTEM_UNIT_PIDS)}\n"
        f"{_systemctl_app_slice_cases()}\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)
    sudo_calls = tmp_path / "sudo-calls"
    fake_sudo = tmp_path / "sudo"
    fake_sudo.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {sudo_calls!s}\n"
        'if [ "${1:-}" = "-n" ]; then shift; fi\n'
        'exec "$@"\n',
        encoding="utf-8",
    )
    fake_sudo.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_SYSTEMD_SYSTEM_DIR": str(system_dir),
            "HAPAX_OOM_SYSTEMD_USER_DIR": str(user_dir),
            "HAPAX_OOM_SYSTEMD_USER_CONTROL_DIR": str(user_control_dir),
            "HAPAX_OOM_EARLYOOM_DEST": str(earlyoom_dest),
            "HAPAX_OOM_ENFORCER_DEST": str(enforcer_dest),
            "HAPAX_ROOT_FAILURE_INTAKE_DEST": str(root_failure_dest),
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_INSTALL_SUDO": str(fake_sudo),
            "HAPAX_OOM_PROC_ROOT": str(proc_root),
            "HAPAX_OOM_TARGET_UID": "1000",
            "HAPAX_OOM_FORCE_DIRECT_WRITE_FAIL": "1",
        },
    )

    assert result.returncode == 0, result.stderr
    assert any(
        line.startswith("cmp -s ")
        and os.environ["HAPAX_OOM_SUDOERS_REFERENCE_DEST"] in line
        and os.environ["HAPAX_OOM_SUDOERS_DEST"] in line
        for line in sudo_calls.read_text(encoding="utf-8").splitlines()
    )
    assert (proc_root / "900" / "oom_score_adj").read_text(encoding="utf-8").strip() == "100"
    assert (proc_root / "910" / "oom_score_adj").read_text(encoding="utf-8").strip() == "-900"


def test_root_oom_score_enforcer_writes_live_user_manager_and_service_scores(
    tmp_path: Path,
) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    unit_pids = {
        "pipewire.service": 910,
        "pipewire-pulse.service": 911,
        "wireplumber.service": 912,
        "hapax-daimonion.service": 913,
        "studio-compositor.service": 914,
        "hapax-imagination.service": 915,
    }
    _write_proc(
        proc_root,
        900,
        name="systemd",
        uid=1000,
        oom_score=-900,
        cgroup="/user.slice/user-1000.slice/user@1000.service",
    )
    for unit, pid in unit_pids.items():
        _write_proc(
            proc_root,
            pid,
            name=unit.split(".")[0],
            uid=1000,
            oom_score=100,
            cgroup=_unit_cgroup(unit),
        )

    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        f"{_enforcer_system_manager_cases()}\n"
        '  *) echo "unexpected system args: $*" >&2; exit 9 ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    fake_user_systemctl = tmp_path / "systemctl-user"
    user_cases = _enforcer_user_unit_cases(unit_pids)
    fake_user_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        f"{user_cases}\n"
        '  *) echo "unexpected user args: $*" >&2; exit 9 ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    fake_user_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(OOM_ENFORCER), "--apply"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_PROC_ROOT": str(proc_root),
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_USER_SYSTEMCTL": str(fake_user_systemctl),
            "HAPAX_OOM_TARGET_UID": "1000",
        },
    )

    assert result.returncode == 0, result.stderr
    expected_scores = {900: 100}
    for unit, pid in unit_pids.items():
        expected_scores[pid] = PROTECTED_USER_UNIT_SCORES[unit]
    for pid, score in expected_scores.items():
        assert (proc_root / str(pid) / "oom_score_adj").read_text(encoding="utf-8").strip() == str(
            score
        )


def test_oom_score_trigger_uses_allowlisted_root_command(tmp_path: Path) -> None:
    calls = tmp_path / "enforcer-calls"
    fake_enforcer = tmp_path / "enforcer"
    fake_enforcer.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {calls!s}\n",
        encoding="utf-8",
    )
    fake_enforcer.chmod(0o755)
    fake_sudo = tmp_path / "sudo"
    fake_sudo.write_text(
        '#!/bin/sh\n[ "${1:-}" != "-n" ] || shift\nexec "$@"\n',
        encoding="utf-8",
    )
    fake_sudo.chmod(0o755)

    result = subprocess.run(
        [str(OOM_TRIGGER), "pipewire.service"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_TRIGGER_TEST_MODE": "1",
            "HAPAX_OOM_TRIGGER_SUDO": str(fake_sudo),
            "HAPAX_OOM_TRIGGER_ENFORCER": str(fake_enforcer),
        },
    )

    assert result.returncode == 0, result.stderr
    assert calls.read_text(encoding="utf-8").strip() == "--apply-unit pipewire.service"


def test_oom_score_trigger_deadlines_blocked_privilege_path(tmp_path: Path) -> None:
    blocked_sudo = tmp_path / "blocked-sudo"
    blocked_sudo.write_text("#!/bin/sh\nsleep 5\n", encoding="utf-8")
    blocked_sudo.chmod(0o755)

    started = time.monotonic()
    result = subprocess.run(
        [str(OOM_TRIGGER), "pipewire.service"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_TRIGGER_TEST_MODE": "1",
            "HAPAX_OOM_TRIGGER_SUDO": str(blocked_sudo),
            "HAPAX_OOM_TRIGGER_DEADLINE": "1s",
        },
    )
    elapsed = time.monotonic() - started

    assert result.returncode != 0
    assert elapsed < 2.5


def test_oom_score_trigger_rejects_non_allowlisted_unit() -> None:
    result = subprocess.run(
        [str(OOM_TRIGGER), "attacker.service"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "refusing non-allowlisted" in result.stderr
    assert "next action:" in result.stderr


def test_oom_score_sudoers_grant_is_narrow_and_valid() -> None:
    result = subprocess.run(
        ["visudo", "-cf", str(OOM_SUDOERS)],
        text=True,
        capture_output=True,
        check=False,
    )
    policy = OOM_SUDOERS.read_text(encoding="utf-8")

    assert result.returncode == 0, result.stderr
    for unit in PROTECTED_USER_UNIT_SCORES:
        assert f"--apply-unit {unit}" in policy
    assert (
        "/usr/bin/cmp -s /usr/local/share/hapax/root-required/"
        "hapax-oom-score-enforce.sudoers "
        "/etc/sudoers.d/hapax-oom-score-enforce"
    ) in policy
    assert "/usr/bin/visudo -cf /etc/sudoers.d/hapax-oom-score-enforce" in policy
    assert "NOPASSWD:NOSETENV:" in policy
    assert "NOPASSWD: ALL" not in policy


def test_root_entrypoints_pin_absolute_interpreters() -> None:
    assert OOM_ENFORCER.read_text(encoding="utf-8").splitlines()[0] == "#!/usr/bin/bash"
    assert OOM_TRIGGER.read_text(encoding="utf-8").splitlines()[0] == "#!/usr/bin/bash"
    assert ROOT_FAILURE_INTAKE.read_text(encoding="utf-8").splitlines()[0] == "#!/usr/bin/bash"
    helper = REPO_ROOT / "config" / "apcupsd" / "hapax-power-event.py"
    assert helper.read_text(encoding="utf-8").splitlines()[0] == "#!/usr/bin/python3"


def test_oom_enforcer_hostile_path_cannot_select_attacker_bash(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "attacker-bash-ran"
    fake_bash = fake_bin / "bash"
    fake_bash.write_text(f"#!/bin/sh\ntouch {marker!s}\nexit 99\n", encoding="utf-8")
    fake_bash.chmod(0o755)

    result = subprocess.run(
        [str(OOM_ENFORCER), "--invalid"],
        text=True,
        capture_output=True,
        check=False,
        env={
            "HOME": os.environ["HOME"],
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "HAPAX_OOM_ENFORCE_TEST_MODE": "1",
            "HAPAX_OOM_TARGET_USER": "ci-test-user",
            "HAPAX_OOM_TARGET_UID": str(os.getuid()),
        },
    )

    assert result.returncode == 2
    assert "usage: hapax-oom-score-enforce" in result.stderr
    assert not marker.exists()


def test_root_oom_score_enforcer_refuses_production_environment_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "unexpected-systemctl-call"
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(f"#!/bin/sh\ntouch {marker!s}\n", encoding="utf-8")
    fake_systemctl.chmod(0o755)
    monkeypatch.delenv("HAPAX_OOM_ENFORCE_TEST_MODE", raising=False)

    result = subprocess.run(
        [str(OOM_ENFORCER), "--apply-unit", "pipewire.service"],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl)},
    )

    assert result.returncode == 2
    assert "refusing production OOM enforcer override" in result.stderr
    assert "next action:" in result.stderr
    assert not marker.exists()


def test_root_oom_score_enforcer_refuses_test_mode_under_sudo() -> None:
    result = subprocess.run(
        [str(OOM_ENFORCER), "--apply-unit", "pipewire.service"],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "SUDO_USER": "hapax"},
    )

    assert result.returncode == 2
    assert "refusing OOM enforcer test overrides under root/sudo execution" in result.stderr
    assert "next action:" in result.stderr


def test_root_oom_score_enforcer_applies_one_allowlisted_unit_after_start(
    tmp_path: Path,
) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _write_proc(
        proc_root,
        910,
        name="pipewire",
        uid=1000,
        oom_score=100,
        cgroup=_unit_cgroup("pipewire.service"),
    )
    _write_proc(
        proc_root,
        916,
        name="systemctl",
        uid=1000,
        oom_score=100,
        cgroup="/user.slice/user-1000.slice/session-1.scope",
    )
    cgroup_root = tmp_path / "cgroup"
    cgroup_dir = cgroup_root / _unit_cgroup("pipewire.service").lstrip("/")
    cgroup_dir.mkdir(parents=True)
    (cgroup_dir / "cgroup.procs").write_text("910\n916\n", encoding="utf-8")
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        '[ "$*" = "show user@1000.service -p ActiveState --value" ] || exit 9\n'
        'printf "active\\n"\n',
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)
    fake_user_systemctl = tmp_path / "systemctl-user"
    fake_user_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        f"{_enforcer_user_unit_cases({'pipewire.service': 910})}\n"
        '  *) echo "unexpected user args: $*" >&2; exit 9 ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    fake_user_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(OOM_ENFORCER), "--apply-unit", "pipewire.service"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_PROC_ROOT": str(proc_root),
            "HAPAX_OOM_CGROUP_ROOT": str(cgroup_root),
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_USER_SYSTEMCTL": str(fake_user_systemctl),
            "HAPAX_OOM_TARGET_UID": "1000",
        },
    )

    assert result.returncode == 0, result.stderr
    assert (proc_root / "910" / "oom_score_adj").read_text(encoding="utf-8").strip() == "-900"
    assert (proc_root / "916" / "oom_score_adj").read_text(encoding="utf-8").strip() == "100"


def test_root_oom_score_enforcer_rejects_non_allowlisted_startup_unit(tmp_path: Path) -> None:
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(OOM_ENFORCER), "--apply-unit", "attacker.service"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_TARGET_UID": "1000",
        },
    )

    assert result.returncode == 2
    assert "refusing non-allowlisted" in result.stderr


def test_root_oom_score_enforcer_does_not_start_an_inactive_user_manager(
    tmp_path: Path,
) -> None:
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        '[ "$*" = "show user@1000.service -p ActiveState --value" ] || exit 9\n'
        'printf "inactive\\n"\n',
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(OOM_ENFORCER), "--apply"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_TARGET_UID": "1000",
        },
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.parametrize("active_state", ("failed", "unknown", "activating", ""))
def test_root_oom_score_enforcer_fails_for_noninactive_user_manager_state(
    tmp_path: Path,
    active_state: str,
) -> None:
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        '[ "$*" = "show user@1000.service -p ActiveState --value" ] || exit 9\n'
        f'printf "%s\\n" {active_state!r}\n',
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(OOM_ENFORCER), "--apply"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_TARGET_UID": "1000",
        },
    )

    assert result.returncode == 1
    assert "refusing to skip OOM score enforcement" in result.stderr
    assert f"ActiveState={active_state or 'empty'}" in result.stderr
    assert "next action:" in result.stderr


def test_root_oom_score_enforcer_fails_when_user_manager_query_errors(
    tmp_path: Path,
) -> None:
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text("#!/usr/bin/env bash\nexit 4\n", encoding="utf-8")
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(OOM_ENFORCER), "--apply"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_TARGET_UID": "1000",
        },
    )

    assert result.returncode == 1
    assert "unable to query user@1000.service ActiveState" in result.stderr
    assert "next action:" in result.stderr


def test_root_oom_score_enforcer_is_quiet_when_scores_already_match(
    tmp_path: Path,
) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    unit_pids = {
        "pipewire.service": 910,
        "pipewire-pulse.service": 911,
        "wireplumber.service": 912,
        "hapax-daimonion.service": 913,
        "studio-compositor.service": 914,
        "hapax-imagination.service": 915,
    }
    _write_proc(
        proc_root,
        900,
        name="systemd",
        uid=1000,
        oom_score=100,
        cgroup="/user.slice/user-1000.slice/user@1000.service",
    )
    for unit, pid in unit_pids.items():
        _write_proc(
            proc_root,
            pid,
            name=unit.split(".")[0],
            uid=1000,
            oom_score=PROTECTED_USER_UNIT_SCORES[unit],
            cgroup=_unit_cgroup(unit),
        )

    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        f"{_enforcer_system_manager_cases()}\n"
        '  *) echo "unexpected system args: $*" >&2; exit 9 ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)
    fake_user_systemctl = tmp_path / "systemctl-user"
    user_cases = _enforcer_user_unit_cases(unit_pids)
    fake_user_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        f"{user_cases}\n"
        '  *) echo "unexpected user args: $*" >&2; exit 9 ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    fake_user_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(OOM_ENFORCER), "--apply"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_PROC_ROOT": str(proc_root),
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_USER_SYSTEMCTL": str(fake_user_systemctl),
            "HAPAX_OOM_TARGET_UID": "1000",
        },
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_root_oom_score_enforcer_writes_all_user_unit_cgroup_pids(
    tmp_path: Path,
) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    cgroup_root = tmp_path / "cgroup"
    cgroup_dir = (
        cgroup_root / "user.slice/user-1000.slice/user@1000.service/app.slice/pipewire.service"
    )
    cgroup_dir.mkdir(parents=True)
    (cgroup_dir / "cgroup.procs").write_text("910\n916\n", encoding="utf-8")
    _write_proc(
        proc_root,
        900,
        name="systemd",
        uid=1000,
        oom_score=100,
        cgroup="/user.slice/user-1000.slice/user@1000.service",
    )
    _write_proc(
        proc_root,
        910,
        name="pipewire",
        uid=1000,
        oom_score=100,
        cgroup=_unit_cgroup("pipewire.service"),
    )
    _write_proc(
        proc_root,
        916,
        name="pipewire-worker",
        uid=1000,
        oom_score=100,
        cgroup=_unit_cgroup("pipewire.service"),
    )

    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        f"{_enforcer_system_manager_cases()}\n"
        '  *) printf "0\\n" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)
    fake_user_systemctl = tmp_path / "systemctl-user"
    fake_user_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        '  *"show pipewire.service -p ControlGroup --value"*) printf "/user.slice/user-1000.slice/user@1000.service/app.slice/pipewire.service\\n" ;;\n'
        '  *"show pipewire.service -p MainPID --value"*) printf "910\\n" ;;\n'
        '  *"show "*" -p ControlGroup --value"*) printf "\\n" ;;\n'
        '  *"show "*" -p MainPID --value"*) printf "0\\n" ;;\n'
        '  *) echo "unexpected user args: $*" >&2; exit 9 ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    fake_user_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(OOM_ENFORCER), "--apply"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_PROC_ROOT": str(proc_root),
            "HAPAX_OOM_CGROUP_ROOT": str(cgroup_root),
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_USER_SYSTEMCTL": str(fake_user_systemctl),
            "HAPAX_OOM_TARGET_UID": "1000",
        },
    )

    assert result.returncode == 0, result.stderr
    assert (proc_root / "910" / "oom_score_adj").read_text(encoding="utf-8").strip() == "-900"
    assert (proc_root / "916" / "oom_score_adj").read_text(encoding="utf-8").strip() == "-900"


def test_root_oom_score_enforcer_rejects_substring_only_unit_match(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _write_proc(
        proc_root,
        900,
        name="systemd",
        uid=1000,
        oom_score=100,
        cgroup="/user.slice/user-1000.slice/user@1000.service",
    )
    _write_proc(
        proc_root,
        910,
        name="pipewire-shadow",
        uid=1000,
        oom_score=100,
        cgroup=(
            "/user.slice/user-1000.slice/user@1000.service/"
            "app.slice/attacker.scope/pipewire.service"
        ),
    )
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        f"{_enforcer_system_manager_cases()}\n"
        '  *) printf "0\\n" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)
    fake_user_systemctl = tmp_path / "systemctl-user"
    fake_user_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        f"{_enforcer_user_unit_cases({'pipewire.service': 910})}\n"
        '  *" -p MainPID --value"*) printf "0\\n" ;;\n'
        '  *" -p ControlGroup --value"*) printf "\\n" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    fake_user_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(OOM_ENFORCER), "--apply"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_PROC_ROOT": str(proc_root),
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_USER_SYSTEMCTL": str(fake_user_systemctl),
            "HAPAX_OOM_TARGET_UID": "1000",
        },
    )

    assert result.returncode == 1
    assert "outside expected subtree" in result.stderr
    assert (proc_root / "910" / "oom_score_adj").read_text(encoding="utf-8").strip() == "100"


def test_root_oom_score_enforcer_continues_after_per_unit_write_failure(
    tmp_path: Path,
) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    unit_pids = {
        "pipewire.service": 910,
        "pipewire-pulse.service": 911,
        "wireplumber.service": 912,
    }
    _write_proc(
        proc_root,
        900,
        name="systemd",
        uid=1000,
        oom_score=-900,
        cgroup="/user.slice/user-1000.slice/user@1000.service",
    )
    for unit, pid in unit_pids.items():
        _write_proc(
            proc_root,
            pid,
            name=unit.split(".")[0],
            uid=1000,
            oom_score=100,
            cgroup=_unit_cgroup(unit),
        )
    (proc_root / "911" / "oom_score_adj").chmod(0o400)

    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        f"{_enforcer_system_manager_cases()}\n"
        '  *) printf "0\\n" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    fake_user_systemctl = tmp_path / "systemctl-user"
    user_cases = _enforcer_user_unit_cases(unit_pids)
    fake_user_systemctl.write_text(
        f'#!/usr/bin/env bash\ncase "$*" in\n{user_cases}\n  *) printf "0\\n" ;;\nesac\n',
        encoding="utf-8",
    )
    fake_user_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(OOM_ENFORCER), "--apply"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_PROC_ROOT": str(proc_root),
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_USER_SYSTEMCTL": str(fake_user_systemctl),
            "HAPAX_OOM_TARGET_UID": "1000",
        },
    )

    assert result.returncode == 1
    assert "failed to set oom_score_adj for pipewire-pulse.service" in result.stderr
    assert "next action: run scripts/hapax-oom-policy-audit --json" in result.stderr
    assert (proc_root / "912" / "oom_score_adj").read_text(encoding="utf-8").strip() == "-900"


def test_root_oom_score_enforcer_fails_when_user_manager_queries_fail(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _write_proc(
        proc_root,
        900,
        name="systemd",
        uid=1000,
        oom_score=100,
        cgroup="/user.slice/user-1000.slice/user@1000.service",
    )
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        f'#!/usr/bin/env bash\ncase "$*" in\n{_enforcer_system_manager_cases()}\nesac\nexit 0\n',
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)
    failing_user_systemctl = tmp_path / "systemctl-user"
    failing_user_systemctl.write_text("#!/usr/bin/env bash\nexit 9\n", encoding="utf-8")
    failing_user_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(OOM_ENFORCER), "--apply"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_PROC_ROOT": str(proc_root),
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_USER_SYSTEMCTL": str(failing_user_systemctl),
            "HAPAX_OOM_TARGET_UID": "1000",
        },
    )

    assert result.returncode == 1
    assert "unable to query user unit pipewire.service ControlGroup" in result.stderr
    assert "next action:" in result.stderr


def test_installer_preserves_python_child_inside_protected_user_unit_cgroup(
    tmp_path: Path,
) -> None:
    system_dir = tmp_path / "systemd-system"
    user_dir = tmp_path / "systemd-user"
    user_control_dir = tmp_path / "systemd-user-control"
    earlyoom_dest = tmp_path / "earlyoom"
    enforcer_dest = tmp_path / "sbin" / "hapax-oom-score-enforce"
    root_failure_dest = tmp_path / "sbin" / "hapax-root-failure-intake"
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    studio_cgroup = _unit_cgroup("studio-compositor.service")
    _write_proc(
        proc_root,
        900,
        name="systemd",
        uid=1000,
        oom_score=100,
        cgroup="/user.slice/user-1000.slice/user@1000.service",
    )
    _write_proc(proc_root, 914, name="python", uid=1000, oom_score=-800, cgroup=studio_cgroup)
    _write_proc(proc_root, 916, name="python", uid=1000, oom_score=-800, cgroup=studio_cgroup)
    _write_proc(
        proc_root,
        917,
        name="python",
        uid=1000,
        oom_score=-800,
        cgroup=f"{studio_cgroup}-shadow",
    )
    _write_proc(
        proc_root, 999, name="codex", uid=1000, oom_score=-900, cgroup="/user.slice/session.slice"
    )
    _write_recovery_procs(proc_root)

    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        '  *"show user@1000.service -p MainPID --value"*) printf "900\\n" ;;\n'
        f"{_systemctl_user_unit_cases({'studio-compositor.service': 914}, {'studio-compositor.service': studio_cgroup})}\n"
        f"{_systemctl_system_memory_cases(RECOVERY_SYSTEM_UNIT_PIDS)}\n"
        f"{_systemctl_app_slice_cases()}\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER), "--install", "--verify-live"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_SYSTEMD_SYSTEM_DIR": str(system_dir),
            "HAPAX_OOM_SYSTEMD_USER_DIR": str(user_dir),
            "HAPAX_OOM_SYSTEMD_USER_CONTROL_DIR": str(user_control_dir),
            "HAPAX_OOM_EARLYOOM_DEST": str(earlyoom_dest),
            "HAPAX_OOM_ENFORCER_DEST": str(enforcer_dest),
            "HAPAX_ROOT_FAILURE_INTAKE_DEST": str(root_failure_dest),
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_INSTALL_SUDO": "",
            "HAPAX_OOM_PROC_ROOT": str(proc_root),
            "HAPAX_OOM_TARGET_UID": "1000",
        },
    )

    assert result.returncode == 0, result.stderr
    assert (proc_root / "916" / "oom_score_adj").read_text(encoding="utf-8").strip() == "-800"
    assert (proc_root / "917" / "oom_score_adj").read_text(encoding="utf-8").strip() == "100"
    assert (proc_root / "999" / "oom_score_adj").read_text(encoding="utf-8").strip() == "100"


def test_installer_query_failure_cannot_scrub_protected_process_scores(tmp_path: Path) -> None:
    system_dir = tmp_path / "systemd-system"
    user_dir = tmp_path / "systemd-user"
    user_control_dir = tmp_path / "systemd-user-control"
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    studio_cgroup = _unit_cgroup("studio-compositor.service")
    _write_proc(
        proc_root,
        900,
        name="systemd",
        uid=1000,
        oom_score=100,
        cgroup="/user.slice/user-1000.slice/user@1000.service",
    )
    _write_proc(proc_root, 914, name="python", uid=1000, oom_score=-800, cgroup=studio_cgroup)
    _write_proc(
        proc_root,
        999,
        name="codex",
        uid=1000,
        oom_score=-900,
        cgroup="/user.slice/session.slice",
    )
    _write_recovery_procs(proc_root)

    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        '  *"--user show studio-compositor.service -p ControlGroup --value"*) exit 9 ;;\n'
        '  *"show user@1000.service -p MainPID --value"*) printf "900\\n" ;;\n'
        f"{_systemctl_user_unit_cases({'studio-compositor.service': 914}, {'studio-compositor.service': studio_cgroup})}\n"
        f"{_systemctl_system_memory_cases(RECOVERY_SYSTEM_UNIT_PIDS)}\n"
        f"{_systemctl_app_slice_cases()}\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_SYSTEMD_SYSTEM_DIR": str(system_dir),
            "HAPAX_OOM_SYSTEMD_USER_DIR": str(user_dir),
            "HAPAX_OOM_SYSTEMD_USER_CONTROL_DIR": str(user_control_dir),
            "HAPAX_OOM_EARLYOOM_DEST": str(tmp_path / "earlyoom"),
            "HAPAX_OOM_ENFORCER_DEST": str(tmp_path / "sbin/hapax-oom-score-enforce"),
            "HAPAX_ROOT_FAILURE_INTAKE_DEST": str(tmp_path / "sbin/hapax-root-failure-intake"),
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_INSTALL_SUDO": "",
            "HAPAX_OOM_PROC_ROOT": str(proc_root),
            "HAPAX_OOM_TARGET_UID": "1000",
        },
    )

    assert result.returncode == 1
    assert "unable to query user unit studio-compositor.service ControlGroup" in result.stderr
    assert (proc_root / "914" / "oom_score_adj").read_text(encoding="utf-8").strip() == "-800"
    assert (proc_root / "999" / "oom_score_adj").read_text(encoding="utf-8").strip() == "-900"


def test_installer_empty_control_group_with_live_pid_aborts_before_scrub(
    tmp_path: Path,
) -> None:
    system_dir = tmp_path / "systemd-system"
    user_dir = tmp_path / "systemd-user"
    user_control_dir = tmp_path / "systemd-user-control"
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    studio_cgroup = _unit_cgroup("studio-compositor.service")
    _write_proc(
        proc_root,
        900,
        name="systemd",
        uid=1000,
        oom_score=100,
        cgroup="/user.slice/user-1000.slice/user@1000.service",
    )
    _write_proc(proc_root, 914, name="python", uid=1000, oom_score=-800, cgroup=studio_cgroup)
    _write_proc(
        proc_root,
        999,
        name="codex",
        uid=1000,
        oom_score=-900,
        cgroup="/user.slice/session.slice",
    )
    _write_recovery_procs(proc_root)

    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        '  *"--user show studio-compositor.service -p ControlGroup --value"*) printf "\\n" ;;\n'
        '  *"show user@1000.service -p MainPID --value"*) printf "900\\n" ;;\n'
        f"{_systemctl_user_unit_cases({'studio-compositor.service': 914}, {'studio-compositor.service': studio_cgroup})}\n"
        f"{_systemctl_system_memory_cases(RECOVERY_SYSTEM_UNIT_PIDS)}\n"
        f"{_systemctl_app_slice_cases()}\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER), "--install"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_SYSTEMD_SYSTEM_DIR": str(system_dir),
            "HAPAX_OOM_SYSTEMD_USER_DIR": str(user_dir),
            "HAPAX_OOM_SYSTEMD_USER_CONTROL_DIR": str(user_control_dir),
            "HAPAX_OOM_EARLYOOM_DEST": str(tmp_path / "earlyoom"),
            "HAPAX_OOM_ENFORCER_DEST": str(tmp_path / "sbin/hapax-oom-score-enforce"),
            "HAPAX_ROOT_FAILURE_INTAKE_DEST": str(tmp_path / "sbin/hapax-root-failure-intake"),
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_INSTALL_SUDO": "",
            "HAPAX_OOM_PROC_ROOT": str(proc_root),
            "HAPAX_OOM_TARGET_UID": "1000",
        },
    )

    assert result.returncode == 1
    assert "live MainPID=914 but an empty ControlGroup" in result.stderr
    assert (proc_root / "914" / "oom_score_adj").read_text(encoding="utf-8").strip() == "-800"
    assert (proc_root / "999" / "oom_score_adj").read_text(encoding="utf-8").strip() == "-900"


def test_installer_revalidates_cached_main_pid_cgroup_before_write_and_exemption(
    tmp_path: Path,
) -> None:
    system_dir = tmp_path / "systemd-system"
    user_dir = tmp_path / "systemd-user"
    user_control_dir = tmp_path / "systemd-user-control"
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    studio_cgroup = _unit_cgroup("studio-compositor.service")
    moved_cgroup = "/user.slice/user-1000.slice/session.slice/app-niri-foot.scope"
    _write_proc(
        proc_root,
        900,
        name="systemd",
        uid=1000,
        oom_score=100,
        cgroup="/user.slice/user-1000.slice/user@1000.service",
    )
    _write_proc(proc_root, 914, name="python", uid=1000, oom_score=-800, cgroup=studio_cgroup)
    _write_recovery_procs(proc_root)

    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        '  *"--user show hapax-imagination.service -p ControlGroup --value"*) '
        f'printf "0::{moved_cgroup}\\n" > "{proc_root / "914" / "cgroup"}"; printf "\\n" ;;\n'
        '  *"show user@1000.service -p MainPID --value"*) printf "900\\n" ;;\n'
        f"{_systemctl_user_unit_cases({'studio-compositor.service': 914}, {'studio-compositor.service': studio_cgroup})}\n"
        f"{_systemctl_system_memory_cases(RECOVERY_SYSTEM_UNIT_PIDS)}\n"
        f"{_systemctl_app_slice_cases()}\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER), "--install", "--verify-live"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_SYSTEMD_SYSTEM_DIR": str(system_dir),
            "HAPAX_OOM_SYSTEMD_USER_DIR": str(user_dir),
            "HAPAX_OOM_SYSTEMD_USER_CONTROL_DIR": str(user_control_dir),
            "HAPAX_OOM_EARLYOOM_DEST": str(tmp_path / "earlyoom"),
            "HAPAX_OOM_ENFORCER_DEST": str(tmp_path / "sbin/hapax-oom-score-enforce"),
            "HAPAX_ROOT_FAILURE_INTAKE_DEST": str(tmp_path / "sbin/hapax-root-failure-intake"),
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_INSTALL_SUDO": "",
            "HAPAX_OOM_PROC_ROOT": str(proc_root),
            "HAPAX_OOM_TARGET_UID": "1000",
        },
    )

    assert result.returncode == 0, result.stderr
    assert (proc_root / "914" / "cgroup").read_text(encoding="utf-8").strip() == (
        f"0::{moved_cgroup}"
    )
    assert (proc_root / "914" / "oom_score_adj").read_text(encoding="utf-8").strip() == "100"


def test_root_failure_intake_uses_stable_recovery_bundle(tmp_path: Path) -> None:
    calls = tmp_path / "calls.txt"
    fake_intake = tmp_path / "hapax-p0-incident-intake"
    fake_intake.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" > {calls!s}\n",
        encoding="utf-8",
    )
    fake_intake.chmod(0o755)

    result = subprocess.run(
        [str(ROOT_FAILURE_INTAKE), "hapax-oom-score-enforce.service"],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "HAPAX_ROOT_FAILURE_INTAKE_CLI": str(fake_intake)},
    )

    assert result.returncode == 0, result.stderr
    assert calls.read_text(encoding="utf-8").strip() == (
        "service-failed hapax-oom-score-enforce.service"
    )


def test_root_failure_intake_requires_actionable_unit_argument() -> None:
    result = subprocess.run([str(ROOT_FAILURE_INTAKE)], text=True, capture_output=True, check=False)

    assert result.returncode == 64
    assert "usage: hapax-root-failure-intake UNIT" in result.stderr
    assert "next action:" in result.stderr


def test_root_failure_intake_default_is_independent_of_process_home() -> None:
    source = ROOT_FAILURE_INTAKE.read_text(encoding="utf-8")

    assert 'hapax_home="${HAPAX_ROOT_FAILURE_HOME:-/home/hapax}"' in source
    assert "${HOME" not in source


def test_root_failure_intake_records_emergency_ledger_when_bundle_missing(tmp_path: Path) -> None:
    ledger = tmp_path / "events.jsonl"
    marker = tmp_path / "user-python-was-used"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_python = bin_dir / "python3"
    fake_python.write_text(f"#!/bin/sh\ntouch {marker!s}\nexit 99\n", encoding="utf-8")
    fake_python.chmod(0o755)

    result = subprocess.run(
        [str(ROOT_FAILURE_INTAKE), "hapax-oom-score-enforce.service"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "HAPAX_ROOT_FAILURE_INTAKE_CLI": str(tmp_path / "missing-intake"),
            "HAPAX_ROOT_FAILURE_LEDGER": str(ledger),
        },
    )

    assert result.returncode == 0, result.stderr
    record = json.loads(ledger.read_text(encoding="utf-8"))
    assert record["kind"] == "root_failure_intake_cli_missing"
    assert record["unit"] == "hapax-oom-score-enforce.service"
    assert not marker.exists()


def test_root_failure_intake_reports_action_when_emergency_ledger_is_unwritable(
    tmp_path: Path,
) -> None:
    non_directory = tmp_path / "not-a-directory"
    non_directory.write_text("occupied\n", encoding="utf-8")

    result = subprocess.run(
        [str(ROOT_FAILURE_INTAKE), "hapax-oom-score-enforce.service"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_ROOT_FAILURE_INTAKE_CLI": str(tmp_path / "missing-intake"),
            "HAPAX_ROOT_FAILURE_LEDGER": str(non_directory / "events.jsonl"),
        },
    )

    assert result.returncode == 1
    assert "could not write emergency ledger" in result.stderr
    assert "unit=hapax-oom-score-enforce.service" in result.stderr
    assert f"missing_intake={tmp_path / 'missing-intake'}" in result.stderr
    assert "next action: repair the ledger parent ownership/capacity" in result.stderr


# What real systemd answers for a unit it has never heard of. VERIFIED on this host, 2026-08-04,
# against both a fabricated unit name and a genuinely-absent protected unit:
#
#   systemctl --user show <unknown>.service -p LoadState      --value  -> not-found
#   systemctl --user show <unknown>.service -p OOMScoreAdjust --value  -> 200
#   systemctl --user show <unknown>.service -p Slice          --value  -> (empty)
#   systemctl --user show <unknown>.service -p MemoryLow      --value  -> 0
#   systemctl --user show <unknown>.service -p MemoryMin      --value  -> 0
#
# Re-derive with:
#   for p in LoadState OOMScoreAdjust Slice MemoryLow MemoryMin; do \
#     systemctl --user show definitely-not-a-real-unit.service -p "$p" --value; done
#
# THIS is the 2026-07-11 mechanism, and it is why LoadState alone is not enough to reproduce it:
# systemctl does not error on an unknown unit, it ANSWERS WITH DEFAULTS, and those defaults are
# indistinguishable from drift to a verifier that does not check existence first. A stub that
# reported not-found while still returning the CORRECT policy values would exercise the skip branch
# without ever demonstrating what the skip prevents.
UNKNOWN_UNIT_SYSTEMD_DEFAULTS = {
    "OOMScoreAdjust": "200",
    "Slice": "",
    "MemoryLow": "0",
    "MemoryMin": "0",
}


def _load_state_cases(load_state: dict[str, str]) -> str:
    """systemctl stub cases for units whose LoadState is being forced.

    The pre-existing stub answers no LoadState query at all, so it returned empty, "not-found" never
    matched, and the host-fit branch was unreachable in tests — which is why the full
    install/verify-live test passed without ever executing the code it appeared to cover.

    For any unit forced to not-found, this ALSO emits systemd's real defaults-for-unknown-unit, so
    the drift checks downstream see exactly what they would see on a live host. Without the host-fit
    branch those defaults read as drift and verify-live fails; with it, the unit is skipped. That
    difference is what makes the assertions discriminating rather than decorative.
    """
    cases = []
    for unit, state in load_state.items():
        cases.append(
            f"  *--user\\ show\\ {unit}\\ -p\\ LoadState\\ --value*) printf '%s\\n' '{state}' ;;"
        )
        if state == "not-found":
            for prop, value in UNKNOWN_UNIT_SYSTEMD_DEFAULTS.items():
                cases.append(
                    f"  *--user\\ show\\ {unit}\\ -p\\ {prop}\\ --value*) printf '%s\\n' '{value}' ;;"
                )
    cases.append("  *-p\\ LoadState\\ --value*) printf '%s\\n' 'loaded' ;;")
    return "\n".join(cases)


def _drift_cases(drift: dict[str, dict[str, str]]) -> str:
    """systemctl stub cases that make a PRESENT unit report wrong policy values.

    Needed to prove the allow-list only tolerates ABSENCE. Without an injectable drift the suite can
    only show that an absent allow-listed unit is skipped; it cannot show that a LOADED allow-listed
    unit is still checked, which is the property that stops the list from becoming an exemption.
    """
    cases = []
    for unit, props in drift.items():
        for prop, value in props.items():
            cases.append(
                f"  *--user\\ show\\ {unit}\\ -p\\ {prop}\\ --value*) printf '%s\\n' '{value}' ;;"
            )
    return "\n".join(cases)


def _run_install_verify_live(
    tmp_path: Path,
    load_state: dict[str, str] | None = None,
    drift: dict[str, dict[str, str]] | None = None,
    unit_files: set[str] | None = None,
    no_unit_path_override: bool = False,
    systemd_analyze: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Drive the REAL installer through --install --verify-live against temp destinations.

    Mirrors test_p0_oom_containment_install_and_verify_live_against_temp_destinations, adding a
    LoadState-answering systemctl stub so the host-fit branch is actually reached, and an optional
    drift injector so a PRESENT unit can be made to report wrong policy values.

    `unit_files` places unit FILES on the fake host without making them load, which is the state
    that distinguishes "never installed here" from "installed here and broken".

    THE UNIT SEARCH PATH IS PINNED TO tmp_path. Left unset, the installer asks the real
    `systemd-analyze --user unit-paths` and finds the REAL machine's units — so a test asserting
    that pipewire.service is absent would silently be told it is present, and would assert against
    whatever the developer's laptop happens to have installed. Hermetic by construction.
    """
    load_state = load_state or {}
    drift = drift or {}
    unit_files = unit_files or set()
    system_dir = tmp_path / "systemd-system"
    target_home = tmp_path / "target-home"
    root_home = tmp_path / "root-home"
    user_dir = target_home / ".config" / "systemd" / "user"
    user_control_dir = target_home / ".config" / "systemd" / "user.control"
    earlyoom_dest = tmp_path / "earlyoom"
    enforcer_dest = tmp_path / "sbin" / "hapax-oom-score-enforce"
    root_failure_dest = tmp_path / "sbin" / "hapax-root-failure-intake"
    root_defer = tmp_path / "root-required"
    installed_source = tmp_path / "current-source"
    (installed_source / "scripts").mkdir(parents=True)
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _write_proc(proc_root, 900, name="systemd", uid=1000, oom_score=100)
    _write_recovery_procs(proc_root)

    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        '  *"show user@1000.service -p MainPID --value"*) printf "900\\n" ;;\n'
        f"{_drift_cases(drift)}\n"
        f"{_load_state_cases(load_state)}\n"
        f"{_systemctl_system_memory_cases(RECOVERY_SYSTEM_UNIT_PIDS)}\n"
        f"{_systemctl_user_unit_cases()}\n"
        f"{_systemctl_app_slice_cases()}\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)
    fake_runuser = tmp_path / "runuser"
    fake_runuser.write_text(
        '#!/usr/bin/env bash\nwhile [ "$1" != "--" ]; do shift; done\nshift\nexec "$@"\n',
        encoding="utf-8",
    )
    fake_runuser.chmod(0o755)

    unit_path_dir = tmp_path / "user-unit-path"
    unit_path_dir.mkdir()
    for unit in unit_files:
        if unit.startswith("dangling:"):
            # A BROKEN `systemctl --user enable` link. `-e` is FALSE here because it follows the
            # link, so this fixture is what distinguishes a correct presence check from one that
            # reports an enabled-but-broken unit as never-installed.
            (unit_path_dir / unit[len("dangling:") :]).symlink_to(
                tmp_path / "no-such-target.service"
            )
        else:
            (unit_path_dir / unit).write_text(
                "[Unit]\nDescription=placed by test\n", encoding="utf-8"
            )

    return subprocess.run(
        [str(INSTALLER), "--install", "--verify-live"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HOME": str(root_home),
            "HAPAX_OOM_SYSTEMD_SYSTEM_DIR": str(system_dir),
            "HAPAX_OOM_SYSTEMD_USER_DIR": str(user_dir),
            "HAPAX_OOM_SYSTEMD_USER_CONTROL_DIR": str(user_control_dir),
            "HAPAX_OOM_TARGET_UID": "1000",
            "HAPAX_OOM_TARGET_HOME": str(target_home),
            "HAPAX_OOM_EARLYOOM_DEST": str(earlyoom_dest),
            "HAPAX_OOM_ENFORCER_DEST": str(enforcer_dest),
            "HAPAX_ROOT_FAILURE_INTAKE_DEST": str(root_failure_dest),
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            **({} if no_unit_path_override else {"HAPAX_OOM_USER_UNIT_PATHS": str(unit_path_dir)}),
            **({"HAPAX_OOM_SYSTEMD_ANALYZE": systemd_analyze} if systemd_analyze else {}),
            "HAPAX_OOM_EFFECTIVE_UID": "0",
            "HAPAX_OOM_RUNUSER": str(fake_runuser),
            "HAPAX_OOM_INSTALL_SUDO": "",
            "HAPAX_OOM_PROC_ROOT": str(proc_root),
            "HAPAX_POST_MERGE_ROOT_DEFER_DIR": str(root_defer),
            "HAPAX_ROOT_REQUIRED_PACKAGE_SHA": REPO_HEAD,
            "HAPAX_ROOT_REQUIRED_GIT_REPO": str(REPO_ROOT),
            "HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT": str(installed_source),
        },
    )


def test_verify_live_skips_an_absent_host_optional_unit(tmp_path: Path) -> None:
    """EXECUTES THE BRANCH. A podium-shaped unit absent here must be skipped, not hard-failed.

    This is the 2026-07-11 regression: appendix has no hapax-daimonion/studio-compositor/
    hapax-imagination, systemctl answered `show` for them with DEFAULTS, the verifier read those
    defaults as drift, exited 1, rolled the deploy back, and repeated every two minutes for 2,176
    incident events.
    """
    result = _run_install_verify_live(tmp_path, load_state={"hapax-daimonion.service": "not-found"})
    assert result.returncode == 0, (
        "verify-live hard-failed on an absent HOST-OPTIONAL unit — the 2026-07-11 regression is "
        f"back.\nstderr: {result.stderr[-2000:]}"
    )
    assert "skipping hapax-daimonion.service" in result.stderr, (
        "the skip was not announced; a silent skip is indistinguishable from a unit that was "
        f"actually verified.\nstderr: {result.stderr[-2000:]}"
    )


def test_verify_live_fails_closed_on_an_absent_required_unit(tmp_path: Path) -> None:
    """EXECUTES THE BRANCH. A REQUIRED unit absent here must fail, never be skipped.

    Without this, --verify-live can report success having verified nothing: every protected unit
    absent, every one skipped, exit 0. That is a false green in the package whose job is to prevent
    one, and it is what the first version of this fix actually did.
    """
    result = _run_install_verify_live(tmp_path, load_state={"pipewire.service": "not-found"})
    assert result.returncode != 0, (
        "verify-live PASSED while a required protected unit was absent — it reported success "
        f"having verified nothing about it.\nstdout: {result.stdout[-1500:]}"
    )
    assert "required protected user unit pipewire.service is absent" in result.stderr, (
        f"the failure did not name the absent required unit.\nstderr: {result.stderr[-2000:]}"
    )
    assert "next action" in result.stderr and "host_optional_user_units" in result.stderr, (
        "per executive_function the failure must carry a next action and name both lawful exits "
        f"(install the unit, or justify the allow-list entry).\nstderr: {result.stderr[-2000:]}"
    )


def test_allow_list_membership_only_narrows_the_not_found_case(tmp_path: Path) -> None:
    """A host-optional unit that IS present must still be verified in full.

    The allow-list exists to make ABSENCE tolerable, not to make a unit exempt. If membership also
    suppressed checks on a unit that is loaded, then adding a name to that list would silently stop
    verifying it on the host where it actually runs — podium would stop verifying its own compositor
    stack while reporting success, which is the same false green the list was added to prevent, just
    aimed at a different host.

    This drives the real verifier with hapax-daimonion.service LOADED (not not-found) and with a
    deliberate OOMScoreAdjust drift. The allow-list must not save it.
    """
    result = _run_install_verify_live(
        tmp_path,
        load_state={"hapax-daimonion.service": "loaded"},
        drift={"hapax-daimonion.service": {"OOMScoreAdjust": "200"}},
    )
    assert result.returncode != 0, (
        "a PRESENT host-optional unit with real OOM policy drift passed verify-live — allow-list "
        "membership is exempting a loaded unit instead of only tolerating its absence.\n"
        f"stdout: {result.stdout[-1200:]}"
    )
    assert "hapax-daimonion.service" in result.stderr, (
        "the drift on the present host-optional unit was not reported by name.\n"
        f"stderr: {result.stderr[-1500:]}"
    )
    assert "skipping hapax-daimonion.service" not in result.stderr, (
        "verify-live SKIPPED a unit that is loaded. The skip branch must be reachable only via "
        f"LoadState=not-found.\nstderr: {result.stderr[-1500:]}"
    )


def test_allow_listed_unit_with_a_unit_file_on_disk_fails_closed(tmp_path: Path) -> None:
    """REVIEW'S CHARGE, EXECUTED. The allow-list is global; membership must not be sufficient.

    CodeRabbit on PR #4499: "This allowlist is global. `is_host_optional_user_unit` checks only the
    unit name. If an allowlisted unit is absent on podium, the skip fires and `--verify-live` can
    pass." That is correct, and the allow-list cannot fix it — a NAME cannot say which host it is on.

    Measured on both hosts 2026-08-04, which is where the discriminator came from:
        appendix  hapax-daimonion.service  LoadState=not-found  no unit file anywhere in the path
        podium    hapax-daimonion.service  LoadState=loaded     ~/.config/systemd/user/...

    So the unit FILE is what distinguishes never-installed-here from installed-here-and-broken, and
    it does so without the script ever asking its own hostname — hostname checks are precisely the
    thing that rots when a host is renamed, cloned, or replaced.

    NOTE ON FragmentPath: it was the first candidate and it does NOT work. systemd reports
    FragmentPath as EMPTY for every not-found unit, on both hosts, so it merely restates LoadState.
    Verified before writing this test rather than after.
    """
    result = _run_install_verify_live(
        tmp_path,
        load_state={"hapax-daimonion.service": "not-found"},
        unit_files={"hapax-daimonion.service"},
    )
    assert result.returncode != 0, (
        "an ALLOW-LISTED unit that is not-found while its unit file sits on disk was SKIPPED. That "
        "is a unit installed on this host which the manager cannot load (masked, dangling symlink, "
        "bad syntax), and skipping it makes --verify-live pass having verified nothing about it.\n"
        f"stderr: {result.stderr[-2000:]}"
    )
    assert "unit file for it EXISTS on this host" in result.stderr, (
        "the run failed, but not for this reason — the assertion would pass on an unrelated failure "
        f"and stop being a test of this branch.\nstderr: {result.stderr[-2000:]}"
    )


def test_absent_host_optional_unit_is_still_skipped_when_no_unit_file_exists(
    tmp_path: Path,
) -> None:
    """The other side of the same predicate: narrowing the skip must not delete it.

    Without this, a fix for the review comment could simply fail on everything absent and still look
    green in the test above — reinstating the 2026-07-11 rollback loop while appearing to be a
    hardening. Same LoadState as the test above, opposite file state, opposite required outcome.
    """
    result = _run_install_verify_live(
        tmp_path,
        load_state={"hapax-daimonion.service": "not-found"},
        unit_files=set(),
    )
    assert result.returncode == 0, (
        "a host-optional unit with NO unit file on this host was failed rather than skipped — this "
        f"is the 2026-07-11 rollback loop returning.\nstderr: {result.stderr[-2000:]}"
    )
    assert "skipping hapax-daimonion.service" in result.stderr


def test_verify_live_fails_when_it_verified_nothing_at_all(tmp_path: Path) -> None:
    """VACUOUS PASS. A check quantified over an empty set is TRUE, and says nothing.

    Every assertion in verify_protected_user_unit_oom_scores is of the form "for each surviving
    unit, ...". Skip them all and the loop body never runs, `failed` stays 0, and the exit code is
    identical to a run that verified all six units against a live manager. The allow-list is the
    mechanism that can empty the set — it is hand-edited, under deploy pressure, by whoever needs a
    host to go green.

    This test empties it deliberately: all six protected units report not-found with no unit files.
    A green exit here would mean the verifier reports success on a host where it examined nothing.
    """
    result = _run_install_verify_live(
        tmp_path,
        load_state={
            "pipewire.service": "not-found",
            "pipewire-pulse.service": "not-found",
            "wireplumber.service": "not-found",
            "hapax-daimonion.service": "not-found",
            "studio-compositor.service": "not-found",
            "hapax-imagination.service": "not-found",
        },
        unit_files=set(),
    )
    assert result.returncode != 0, (
        "--verify-live examined ZERO protected units and still exited 0. That exit code is "
        "indistinguishable from a full successful verification, which is the entire defect class "
        f"this package exists to remove.\nstderr: {result.stderr[-2000:]}"
    )
    assert "examined 0 of 6 protected user units" in result.stderr, (
        "it failed, but the vacuous-pass guard is not what caught it — the three REQUIRED units "
        "failing closed would produce a non-zero exit on their own and mask the guard's absence.\n"
        f"stderr: {result.stderr[-2000:]}"
    )


def test_a_dangling_unit_symlink_is_not_read_as_host_absence(tmp_path: Path) -> None:
    """MAJOR from blind review (codex-1) on PR #4499: `-e` follows symlinks.

    `systemctl --user enable` installs a SYMLINK into the unit path. If its target is removed the
    link dangles, `[ -e ]` on it is FALSE, and a presence check built only on `-e` reports "no unit
    file here" — so an allow-listed unit that is enabled-but-broken takes the host-absent skip and
    --verify-live passes having verified nothing about it.

    That is the exact case the presence check exists to catch, inverted. A dangling link is in fact
    the STRONGEST evidence the unit was installed on this host: something deliberately linked it.
    """
    result = _run_install_verify_live(
        tmp_path,
        load_state={"hapax-daimonion.service": "not-found"},
        unit_files={"dangling:hapax-daimonion.service"},
    )
    assert result.returncode != 0, (
        "an allow-listed unit whose unit file is a DANGLING SYMLINK was skipped as host-absent. "
        "The link proves the unit was enabled here; the broken target is a load failure and must "
        f"fail closed.\nstderr: {result.stderr[-2000:]}"
    )
    assert "unit file for it EXISTS on this host" in result.stderr, (
        "it failed, but not via the presence check — the assertion would pass on an unrelated "
        f"failure.\nstderr: {result.stderr[-2000:]}"
    )


def test_unit_search_path_falls_back_when_systemd_analyze_is_unusable(tmp_path: Path) -> None:
    """glm-2 minor on PR #4499: the SYSTEMD_ANALYZE branch was declared but never exercised.

    With no HAPAX_OOM_USER_UNIT_PATHS override the installer asks `systemd-analyze --user
    unit-paths`, and falls back to a static list only when that fails. Neither path had a test, so
    a fallback that produced no directories — making EVERY unit look absent and every allow-listed
    unit silently skippable — would not have been caught.

    Here systemd-analyze is pointed at a binary that always fails, forcing the fallback, and the
    unit file is placed in the fallback's own $TARGET_HOME location.
    """
    target_home = tmp_path / "target-home"
    fallback_dir = target_home / ".config" / "systemd" / "user"
    fallback_dir.mkdir(parents=True, exist_ok=True)
    (fallback_dir / "hapax-daimonion.service").write_text("[Unit]\n", encoding="utf-8")

    failing_analyze = tmp_path / "systemd-analyze-broken"
    failing_analyze.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    failing_analyze.chmod(0o755)

    result = _run_install_verify_live(
        tmp_path,
        load_state={"hapax-daimonion.service": "not-found"},
        unit_files=set(),
        no_unit_path_override=True,
        systemd_analyze=str(failing_analyze),
    )
    assert "unit file for it EXISTS on this host" in result.stderr, (
        "with systemd-analyze failing, the static fallback did not find a unit file that is "
        "present in ~/.config/systemd/user. A fallback that yields no directories makes every "
        f"unit look absent and every allow-listed unit skippable.\nstderr: {result.stderr[-2500:]}"
    )


def test_degraded_search_path_may_not_be_used_to_prove_absence(tmp_path: Path) -> None:
    """MAJOR from blind review (codex-1) on PR #4499, at its root rather than its symptom.

    The first fix answered "the fallback omits directories" by listing more directories. That is
    necessary but not sufficient: ANY reconstruction can omit a path this system actually uses, so
    "no unit file found" under a degraded enumeration means "I did not look everywhere", not "it is
    not installed". Skipping on that is a false host-absence.

    So a degraded path list may still PROVE PRESENCE — finding a file is positive evidence — but it
    may never prove ABSENCE. Here systemd-analyze fails and no unit file exists anywhere, which is
    exactly the state that must fail closed instead of skipping.
    """
    failing_analyze = tmp_path / "systemd-analyze-broken"
    failing_analyze.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    failing_analyze.chmod(0o755)

    result = _run_install_verify_live(
        tmp_path,
        load_state={"hapax-daimonion.service": "not-found"},
        unit_files=set(),
        no_unit_path_override=True,
        systemd_analyze=str(failing_analyze),
    )
    assert result.returncode != 0, (
        "an allow-listed unit was skipped as host-absent while the search path was a RECONSTRUCTION "
        "— absence was never proven, so this is a false green.\n"
        f"stderr: {result.stderr[-2000:]}"
    )
    assert "RECONSTRUCTION" in result.stderr, (
        "it failed, but not because absence was unprovable — the assertion would pass on an "
        f"unrelated failure.\nstderr: {result.stderr[-2000:]}"
    )


def test_authoritative_systemd_analyze_discovery_finds_a_unit_file(tmp_path: Path) -> None:
    """codex-1 on PR #4499: only the FAILING systemd-analyze branch was covered.

    The success branch is the one that runs on every real host, and it is the branch that decides
    whether the host-absent skip is even permitted. Untested, a change that made discovery return
    nothing on success would make every unit look absent, permit every allow-listed skip, and be
    invisible — while the failure-path test kept passing.

    Here systemd-analyze SUCCEEDS and prints a directory holding the unit file, so discovery is
    authoritative and must find it.
    """
    discovered = tmp_path / "analyze-reported-path"
    discovered.mkdir()
    (discovered / "hapax-daimonion.service").write_text("[Unit]\n", encoding="utf-8")

    ok_analyze = tmp_path / "systemd-analyze-ok"
    ok_analyze.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' {discovered}\nexit 0\n", encoding="utf-8"
    )
    ok_analyze.chmod(0o755)

    result = _run_install_verify_live(
        tmp_path,
        load_state={"hapax-daimonion.service": "not-found"},
        unit_files=set(),
        no_unit_path_override=True,
        systemd_analyze=str(ok_analyze),
    )
    assert "unit file for it EXISTS on this host" in result.stderr, (
        "authoritative systemd-analyze discovery did not find a unit file in the directory it "
        "itself reported. If discovery yields nothing on the success path, every unit looks absent "
        f"and every allow-listed skip is permitted.\nstderr: {result.stderr[-2500:]}"
    )
    assert result.returncode != 0, "an installed-but-unloadable unit must fail closed"
