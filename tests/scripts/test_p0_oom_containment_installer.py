from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "scripts" / "install-p0-oom-containment"
OOM_ENFORCER = REPO_ROOT / "scripts" / "hapax-oom-score-enforce"
ROOT_FAILURE_INTAKE = REPO_ROOT / "scripts" / "hapax-root-failure-intake"
PROTECTED_USER_UNIT_SCORES = {
    "pipewire.service": -900,
    "pipewire-pulse.service": -900,
    "wireplumber.service": -900,
    "hapax-daimonion.service": -500,
    "studio-compositor.service": -800,
    "hapax-imagination.service": -800,
}


@pytest.fixture(autouse=True)
def _isolate_installed_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT", str(tmp_path / "installed-source")
    )


def _unit_cgroup(unit: str) -> str:
    return f"/user.slice/user-1000.slice/user@1000.service/app.slice/{unit}"


def _systemctl_user_unit_cases(
    unit_pids: dict[str, int] | None = None,
    unit_cgroups: dict[str, str] | None = None,
) -> str:
    unit_pids = unit_pids or {}
    unit_cgroups = unit_cgroups or {
        unit: _unit_cgroup(unit) for unit in unit_pids if unit in PROTECTED_USER_UNIT_SCORES
    }
    cases = []
    for unit, score in PROTECTED_USER_UNIT_SCORES.items():
        cases.append(
            f"  *--user\\ show\\ {unit}\\ -p\\ OOMScoreAdjust\\ --value*) "
            f"printf '%s\\n' '{score}' ;;"
        )
        cases.append(
            f"  *--user\\ show\\ {unit}\\ -p\\ MainPID\\ --value*) "
            f"printf '%s\\n' '{unit_pids.get(unit, 0)}' ;;"
        )
        cases.append(
            f"  *--user\\ show\\ {unit}\\ -p\\ ControlGroup\\ --value*) "
            f"printf '%s\\n' '{unit_cgroups.get(unit, '')}' ;;"
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
        ]
    )


def _systemctl_system_memory_cases() -> str:
    return "\n".join(
        [
            '  *"show system.slice -p MemoryHigh --value"*) printf "infinity\\n" ;;',
            '  *"show system.slice -p MemoryMax --value"*) printf "infinity\\n" ;;',
            '  *"show system.slice -p MemorySwapMax --value"*) printf "infinity\\n" ;;',
            '  *"show system.slice -p MemoryLow --value"*) printf "25769803776\\n" ;;',
            '  *"show system.slice -p MemoryMin --value"*) printf "12884901888\\n" ;;',
            '  *"show user-1000.slice -p MemoryHigh --value"*) printf "85899345920\\n" ;;',
            '  *"show user-1000.slice -p MemoryMax --value"*) printf "103079215104\\n" ;;',
            '  *"show user-1000.slice -p MemorySwapMax --value"*) printf "8589934592\\n" ;;',
            '  *"show user-1000.slice -p MemoryLow --value"*) printf "17179869184\\n" ;;',
            '  *"show user-1000.slice -p MemoryMin --value"*) printf "8589934592\\n" ;;',
            '  *"show user@1000.service -p MemoryHigh --value"*) printf "85899345920\\n" ;;',
            '  *"show user@1000.service -p MemoryMax --value"*) printf "103079215104\\n" ;;',
            '  *"show user@1000.service -p MemorySwapMax --value"*) printf "8589934592\\n" ;;',
            '  *"show user@1000.service -p MemoryLow --value"*) printf "17179869184\\n" ;;',
            '  *"show user@1000.service -p MemoryMin --value"*) printf "8589934592\\n" ;;',
        ]
    )


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
    assert "hapax-imagination" not in earlyoom
    assert "studio-compositor" not in earlyoom
    assert "systemd-resolve" in earlyoom
    assert "systemd-timesyn" in earlyoom
    assert "hapax-imaginati" in earlyoom
    assert "studio-composit" in earlyoom


def test_p0_oom_containment_install_and_verify_live_against_temp_destinations(
    tmp_path: Path,
) -> None:
    system_dir = tmp_path / "systemd-system"
    target_home = tmp_path / "target-home"
    root_home = tmp_path / "root-home"
    user_dir = target_home / ".config" / "systemd" / "user"
    user_control_dir = target_home / ".config" / "systemd" / "user.control"
    stale_control = user_control_dir / "app.slice.d" / "50-MemoryHigh.conf"
    stale_control.parent.mkdir(parents=True)
    stale_control.write_text("[Slice]\nMemoryHigh=1G\n", encoding="utf-8")
    earlyoom_dest = tmp_path / "earlyoom"
    enforcer_dest = tmp_path / "sbin" / "hapax-oom-score-enforce"
    root_failure_dest = tmp_path / "sbin" / "hapax-root-failure-intake"
    root_defer = tmp_path / "root-required"
    drain_dir = root_defer / "sha" / "oom-containment"
    installed_source = tmp_path / "current-source"
    drain_dir.mkdir(parents=True)
    (drain_dir / "RUNBOOK.txt").write_text("run installer\n", encoding="utf-8")
    sibling_dir = root_defer / "other-sha" / "oom-containment"
    sibling_dir.mkdir(parents=True)
    (sibling_dir / "RUNBOOK.txt").write_text("run other installer\n", encoding="utf-8")
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _write_proc(proc_root, 900, name="systemd", uid=1000, oom_score=100)
    systemctl_calls = tmp_path / "systemctl-calls.txt"
    systemctl_calls.write_text("", encoding="utf-8")
    systemctl_calls.chmod(0o666)
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {systemctl_calls!s}\n"
        'case "$*" in\n'
        '  *"show user@1000.service -p MainPID --value"*) printf "900\\n" ;;\n'
        f"{_systemctl_system_memory_cases()}\n"
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
            "HAPAX_ROOT_REQUIRED_DRAIN_DIR": str(drain_dir),
            "HAPAX_ROOT_REQUIRED_INSTALLED_SOURCE_ROOT": str(installed_source),
        },
    )

    assert result.returncode == 0, result.stderr
    assert not drain_dir.exists()
    assert sibling_dir.exists()
    assert (installed_source / "scripts" / "install-p0-oom-containment").is_file()
    assert "root-required deferral drained" in result.stdout
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
    assert (system_dir / "user-1000.slice.d" / "oom-containment.conf").is_file()
    assert "MemoryLow=24G" in (system_dir / "system.slice.d" / "oom-containment.conf").read_text(
        encoding="utf-8"
    )
    assert earlyoom_dest.read_text(encoding="utf-8").startswith("EARLYOOM_ARGS=")
    assert enforcer_dest.is_file()
    assert root_failure_dest.is_file()
    assert not stale_control.exists()
    assert not (root_home / ".config" / "systemd").exists()
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "daemon-reload" in calls
    assert "enable --now earlyoom.service" in calls
    assert "restart earlyoom.service" in calls
    assert "is-enabled --quiet earlyoom.service" in calls
    assert "is-active --quiet earlyoom.service" in calls
    assert (
        f"-u hapax -- env XDG_RUNTIME_DIR=/run/user/1000 {fake_systemctl} --user daemon-reload"
        in runuser_calls.read_text(encoding="utf-8")
    )


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
        f"{_systemctl_system_memory_cases()}\n"
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
    expected_scores = {
        200: -900,
        201: -800,
        202: -800,
        203: -800,
        204: -800,
        205: -900,
        206: -1000,
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
    assert "set-property --runtime user-1000.slice MemoryHigh=80G MemoryMax=96G" in calls
    assert "set-property --runtime user@1000.service MemoryHigh=80G MemoryMax=96G" in calls
    assert (
        "set-property --runtime app.slice MemoryHigh=72G MemoryMax=88G MemorySwapMax=8G MemoryLow=16G MemoryMin=8G"
        in calls
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

    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        '  *"show user@1000.service -p MainPID --value"*) printf "900\\n" ;;\n'
        '  *"--user show pipewire.service -p OOMScoreAdjust --value"*) printf "-900\\n" ;;\n'
        '  *"--user show pipewire.service -p MainPID --value"*) printf "910\\n" ;;\n'
        f"{_systemctl_user_unit_cases()}\n"
        f"{_systemctl_system_memory_cases()}\n"
        f"{_systemctl_app_slice_cases()}\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)
    fake_sudo = tmp_path / "sudo"
    fake_sudo.write_text(
        '#!/usr/bin/env bash\nif [ "${1:-}" = "-n" ]; then shift; fi\nexec "$@"\n',
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
        '  *"show user@1000.service -p MainPID --value"*) printf "900\\n" ;;\n'
        '  *) echo "unexpected system args: $*" >&2; exit 9 ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    fake_user_systemctl = tmp_path / "systemctl-user"
    user_cases = "\n".join(
        f'  *"show {unit} -p MainPID --value"*) printf "{pid}\\n" ;;'
        for unit, pid in unit_pids.items()
    )
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
        '  *"show user@1000.service -p MainPID --value"*) printf "900\\n" ;;\n'
        '  *) echo "unexpected system args: $*" >&2; exit 9 ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)
    fake_user_systemctl = tmp_path / "systemctl-user"
    user_cases = "\n".join(
        f'  *"show {unit} -p MainPID --value"*) printf "{pid}\\n" ;;'
        for unit, pid in unit_pids.items()
    )
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
        '  *"show user@1000.service -p MainPID --value"*) printf "900\\n" ;;\n'
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
        '  *"show user@1000.service -p MainPID --value"*) printf "900\\n" ;;\n'
        '  *) printf "0\\n" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    fake_user_systemctl = tmp_path / "systemctl-user"
    user_cases = "\n".join(
        f'  *"show {unit} -p MainPID --value"*) printf "{pid}\\n" ;;'
        for unit, pid in unit_pids.items()
    )
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
        proc_root, 999, name="codex", uid=1000, oom_score=-900, cgroup="/user.slice/session.slice"
    )

    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        '  *"show user@1000.service -p MainPID --value"*) printf "900\\n" ;;\n'
        f"{_systemctl_user_unit_cases({'studio-compositor.service': 914}, {'studio-compositor.service': studio_cgroup})}\n"
        f"{_systemctl_system_memory_cases()}\n"
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
    assert (proc_root / "999" / "oom_score_adj").read_text(encoding="utf-8").strip() == "100"


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


def test_root_failure_intake_records_emergency_ledger_when_bundle_missing(tmp_path: Path) -> None:
    ledger = tmp_path / "events.jsonl"

    result = subprocess.run(
        [str(ROOT_FAILURE_INTAKE), "hapax-oom-score-enforce.service"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_ROOT_FAILURE_INTAKE_CLI": str(tmp_path / "missing-intake"),
            "HAPAX_ROOT_FAILURE_LEDGER": str(ledger),
        },
    )

    assert result.returncode == 0, result.stderr
    record = json.loads(ledger.read_text(encoding="utf-8"))
    assert record["kind"] == "root_failure_intake_cli_missing"
    assert record["unit"] == "hapax-oom-score-enforce.service"
