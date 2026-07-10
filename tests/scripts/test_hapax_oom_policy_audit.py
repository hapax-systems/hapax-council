from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-oom-policy-audit"
RECOVERY_SYSTEM_UNIT_SCORES = {
    "apcupsd.service": -900,
    "systemd-logind.service": -800,
    "systemd-resolved.service": -800,
    "systemd-timesyncd.service": -800,
    "NetworkManager.service": -800,
    "dbus-broker.service": -900,
}
RECOVERY_SYSTEM_UNIT_PIDS = {
    unit: 930 + index for index, unit in enumerate(RECOVERY_SYSTEM_UNIT_SCORES)
}
PROTECTED_USER_UNIT_SCORES = {
    "pipewire.service": -900,
    "pipewire-pulse.service": -900,
    "wireplumber.service": -900,
    "hapax-daimonion.service": -500,
    "studio-compositor.service": -800,
    "hapax-imagination.service": -800,
}
PROTECTED_USER_UNIT_MEMORY = {
    "pipewire.service": (536870912, 268435456),
    "pipewire-pulse.service": (536870912, 268435456),
    "wireplumber.service": (536870912, 268435456),
    "hapax-daimonion.service": (2147483648, 1073741824),
    "studio-compositor.service": (6442450944, 3221225472),
    "hapax-imagination.service": (6442450944, 3221225472),
}


def _protected_user_unit_cases(
    *,
    wrong_unit_score: bool = False,
    wrong_unit_memory: bool = False,
    unit_pids: dict[str, int] | None = None,
    unit_cgroups: dict[str, str] | None = None,
) -> str:
    unit_pids = unit_pids or {}
    unit_cgroups = unit_cgroups or {}
    cases = []
    for unit, score in PROTECTED_USER_UNIT_SCORES.items():
        actual = 100 if wrong_unit_score and unit == "studio-compositor.service" else score
        pid = unit_pids.get(unit, 0)
        cgroup = unit_cgroups.get(unit, "")
        memory_low, memory_min = PROTECTED_USER_UNIT_MEMORY[unit]
        if wrong_unit_memory and unit == "studio-compositor.service":
            memory_min = 0
        cases.append(
            f'  *"--user show {unit} --no-pager -p OOMScoreAdjust -p MainPID"*) '
            f"printf 'OOMScoreAdjust={actual}\\nMainPID={pid}\\nControlGroup={cgroup}\\n"
            f"MemoryLow={memory_low}\\nMemoryMin={memory_min}\\n' ;;"
        )
    return "\n".join(cases)


def _recovery_system_unit_cases(*, wrong_score: bool = False) -> str:
    cases = []
    for unit, score in RECOVERY_SYSTEM_UNIT_SCORES.items():
        actual = -1000 if wrong_score and unit == "apcupsd.service" else score
        pid = RECOVERY_SYSTEM_UNIT_PIDS[unit]
        cases.append(f"  *\"show {unit}\"*) printf 'OOMScoreAdjust={actual}\\nMainPID={pid}\\n' ;;")
    return "\n".join(cases)


def _fake_systemctl(
    tmp_path: Path,
    *,
    user_oom: int = 100,
    app_bounded: bool = True,
    tmux_bounded: bool = True,
    tmux_slice: str = "app.slice",
    wrong_unit_score: bool = False,
    wrong_unit_memory: bool = False,
    system_slice_finite_max: bool = False,
    user_slice_unprotected: bool = False,
    protected_unit_pids: dict[str, int] | None = None,
    protected_unit_cgroups: dict[str, str] | None = None,
    sshd_score: int = 0,
    sshd_policy: str = "continue",
    wrong_recovery_unit_score: bool = False,
) -> Path:
    path = tmp_path / "systemctl"
    app_values = (
        "MemoryHigh=77309411328\n"
        "MemoryMax=94489280512\n"
        "MemorySwapMax=8589934592\n"
        "MemoryLow=17179869184\n"
        "MemoryMin=8589934592\n"
        if app_bounded
        else (
            "MemoryHigh=infinity\n"
            "MemoryMax=infinity\n"
            "MemorySwapMax=infinity\n"
            "MemoryLow=infinity\n"
            "MemoryMin=infinity\n"
        )
    )
    uid_memory_values = (
        "MemoryHigh=85899345920\n"
        "MemoryMax=103079215104\n"
        "MemorySwapMax=8589934592\n"
        "MemoryLow=17179869184\n"
        "MemoryMin=8589934592\n"
    )
    tmux_values = (
        f"MemoryHigh=12884901888\nMemoryMax=19327352832\nMemorySwapMax=3221225472\nSlice={tmux_slice}\n"
        if tmux_bounded
        else f"MemoryHigh=infinity\nMemoryMax=infinity\nMemorySwapMax=infinity\nSlice={tmux_slice}\n"
    )
    system_slice_values = (
        "MemoryHigh=infinity\n"
        f"MemoryMax={'68719476736' if system_slice_finite_max else 'infinity'}\n"
        "MemorySwapMax=infinity\n"
        "MemoryLow=25769803776\n"
        "MemoryMin=12884901888\n"
    )
    user_slice_values = (
        "MemoryHigh=infinity\n"
        "MemoryMax=infinity\n"
        "MemorySwapMax=infinity\n"
        f"MemoryLow={'0' if user_slice_unprotected else '17179869184'}\n"
        f"MemoryMin={'0' if user_slice_unprotected else '8589934592'}\n"
    )
    path.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
case "$*" in
  *"show system.slice"*) printf '{system_slice_values}' ;;
  *"show user.slice"*) printf '{user_slice_values}' ;;
  *"show user-1000.slice"*) printf '{uid_memory_values}' ;;
  *"show user@1000.service --no-pager -p MemoryHigh"*) printf '{uid_memory_values}' ;;
  *"show user@1000.service"*) printf 'OOMScoreAdjust={user_oom}\\nDropInPaths=/etc/systemd/system/user@1000.service.d/oom.conf\\nMainPID=900\\n' ;;
  *"show sshd.service"*) printf 'OOMScoreAdjust={sshd_score}\\nOOMPolicy={sshd_policy}\\nMainPID=920\\n' ;;
{_recovery_system_unit_cases(wrong_score=wrong_recovery_unit_score)}
  *"show app.slice"*) printf '{app_values}' ;;
{_protected_user_unit_cases(wrong_unit_score=wrong_unit_score, wrong_unit_memory=wrong_unit_memory, unit_pids=protected_unit_pids, unit_cgroups=protected_unit_cgroups)}
  *"list-units --type=scope"*) printf 'tmux-spawn-a.scope loaded active running tmux child pane\\n' ;;
  *"show tmux-spawn-a.scope"*) printf '{tmux_values}' ;;
  *) echo "unexpected args: $*" >&2; exit 9 ;;
esac
""",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _write_proc(proc_root: Path, pid: int, *, name: str, uid: int, oom_score: int) -> None:
    pid_dir = proc_root / str(pid)
    pid_dir.mkdir(parents=True)
    (pid_dir / "status").write_text(
        f"Name:\t{name}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n", encoding="utf-8"
    )
    (pid_dir / "oom_score_adj").write_text(f"{oom_score}\n", encoding="utf-8")


def _write_proc_cgroup(proc_root: Path, pid: int, cgroup: str) -> None:
    (proc_root / str(pid) / "cgroup").write_text(f"0::{cgroup}\n", encoding="utf-8")


def _run(
    tmp_path: Path,
    *,
    user_oom: int = 100,
    app_bounded: bool = True,
    tmux_bounded: bool = True,
    tmux_slice: str = "app.slice",
    wrong_unit_score: bool = False,
    wrong_unit_memory: bool = False,
    system_slice_finite_max: bool = False,
    user_slice_unprotected: bool = False,
    protected_unit_pids: dict[str, int] | None = None,
    protected_unit_cgroups: dict[str, str] | None = None,
    sshd_score: int = 0,
    sshd_policy: str = "continue",
    wrong_recovery_unit_score: bool = False,
    wrong_recovery_live_score: bool = False,
    proc_root: Path | None = None,
    cgroup_root: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    if proc_root is None:
        proc_root = tmp_path / "proc"
        proc_root.mkdir(exist_ok=True)
    if not (proc_root / "900").exists():
        _write_proc(proc_root, 900, name="systemd", uid=1000, oom_score=100)
    if not (proc_root / "920").exists():
        _write_proc(proc_root, 920, name="sshd", uid=0, oom_score=0)
    for unit, pid in RECOVERY_SYSTEM_UNIT_PIDS.items():
        if not (proc_root / str(pid)).exists():
            live_score = (
                100
                if wrong_recovery_live_score and unit == "apcupsd.service"
                else RECOVERY_SYSTEM_UNIT_SCORES[unit]
            )
            _write_proc(
                proc_root,
                pid,
                name=unit.removesuffix(".service"),
                uid=0,
                oom_score=live_score,
            )
    if cgroup_root is None:
        cgroup_root = tmp_path / "cgroup"
        cgroup_root.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "HAPAX_SYSTEMCTL": str(
            _fake_systemctl(
                tmp_path,
                user_oom=user_oom,
                app_bounded=app_bounded,
                tmux_bounded=tmux_bounded,
                tmux_slice=tmux_slice,
                wrong_unit_score=wrong_unit_score,
                wrong_unit_memory=wrong_unit_memory,
                system_slice_finite_max=system_slice_finite_max,
                user_slice_unprotected=user_slice_unprotected,
                protected_unit_pids=protected_unit_pids,
                protected_unit_cgroups=protected_unit_cgroups,
                sshd_score=sshd_score,
                sshd_policy=sshd_policy,
                wrong_recovery_unit_score=wrong_recovery_unit_score,
            )
        ),
        "HAPAX_OOM_AUDIT_PROC_ROOT": str(proc_root),
        "HAPAX_OOM_AUDIT_CGROUP_ROOT": str(cgroup_root),
    }
    return subprocess.run(
        [str(SCRIPT), "--json", "--uid", "1000"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_audit_passes_when_user_manager_is_killable_and_app_slice_bounded(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    statuses = {check["name"]: check["status"] for check in payload["checks"]}
    assert statuses["user_manager_oom_score_adjust"] == "pass"
    assert statuses["system_slice_MemoryLow"] == "pass"
    assert statuses["user_slice_MemoryLow"] == "pass"
    assert statuses["app_slice_MemorySwapMax"] == "pass"


def test_audit_fails_when_user_manager_protects_all_descendants(tmp_path: Path) -> None:
    result = _run(tmp_path, user_oom=-900)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(
        item for item in payload["checks"] if item["name"] == "user_manager_oom_score_adjust"
    )
    assert check["status"] == "gap"
    assert "descendant workload" in check["detail"]


def test_audit_fails_when_effective_sshd_policy_is_overridden(tmp_path: Path) -> None:
    result = _run(tmp_path, sshd_score=-1000, sshd_policy="stop")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = {item["name"]: item for item in payload["checks"]}
    assert checks["sshd_effective_OOMScoreAdjust"]["status"] == "gap"
    assert "future sessions" in checks["sshd_effective_OOMScoreAdjust"]["detail"]
    assert checks["sshd_effective_OOMPolicy"]["status"] == "gap"
    assert checks["sshd_live_oom_score_adj"]["status"] == "pass"


def test_audit_fails_when_effective_recovery_daemon_policy_is_overridden(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path, wrong_recovery_unit_score=True)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = {item["name"]: item for item in payload["checks"]}
    effective = checks["system_unit_apcupsd.service_OOMScoreAdjust"]
    assert effective["status"] == "gap"
    assert effective["actual"] == "-1000"
    assert "effective recovery-daemon OOM policy drifted" in effective["detail"]
    assert checks["system_unit_apcupsd.service_live_oom_score_adj"]["status"] == "pass"


def test_audit_fails_when_live_recovery_daemon_score_drifts(tmp_path: Path) -> None:
    result = _run(tmp_path, wrong_recovery_live_score=True)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = {item["name"]: item for item in payload["checks"]}
    assert checks["system_unit_apcupsd.service_OOMScoreAdjust"]["status"] == "pass"
    live = checks["system_unit_apcupsd.service_live_oom_score_adj"]
    assert live["status"] == "gap"
    assert live["actual"] == "100"
    assert "live recovery-daemon OOM score drifted" in live["detail"]


def test_audit_fails_when_app_slice_backstop_is_unbounded(tmp_path: Path) -> None:
    result = _run(tmp_path, app_bounded=False)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    app_checks = [item for item in payload["checks"] if item["name"].startswith("app_slice_")]
    assert app_checks
    assert all(item["status"] == "gap" for item in app_checks)


def test_audit_fails_when_system_slice_has_finite_hard_ceiling(tmp_path: Path) -> None:
    result = _run(tmp_path, system_slice_finite_max=True)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(item for item in payload["checks"] if item["name"] == "system_slice_MemoryMax")
    assert check["status"] == "gap"
    assert check["target"] == "infinity"


def test_audit_fails_when_user_slice_ancestor_has_no_reservation(tmp_path: Path) -> None:
    result = _run(tmp_path, user_slice_unprotected=True)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(item for item in payload["checks"] if item["name"] == "user_slice_MemoryMin")
    assert check["status"] == "gap"
    assert "ancestor reservation" in check["detail"]


def test_audit_fails_when_protected_user_unit_loses_oom_score(tmp_path: Path) -> None:
    result = _run(tmp_path, wrong_unit_score=True)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(
        item
        for item in payload["checks"]
        if item["name"] == "user_unit_studio-compositor.service_OOMScoreAdjust"
    )
    assert check["status"] == "gap"
    assert "install-p0-oom-containment" in check["detail"]


def test_audit_fails_when_protected_user_unit_loses_memory_reservation(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path, wrong_unit_memory=True)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(
        item
        for item in payload["checks"]
        if item["name"] == "user_unit_studio-compositor.service_MemoryMin"
    )
    assert check["status"] == "gap"
    assert check["target"] == "3221225472"
    assert "memory reservation drifted" in check["detail"]


def test_audit_fails_when_protected_user_unit_cgroup_pid_loses_oom_score(
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
    _write_proc(proc_root, 910, name="pipewire", uid=1000, oom_score=-900)
    _write_proc(proc_root, 916, name="pipewire-worker", uid=1000, oom_score=100)

    result = _run(
        tmp_path,
        proc_root=proc_root,
        cgroup_root=cgroup_root,
        protected_unit_pids={"pipewire.service": 910},
        protected_unit_cgroups={
            "pipewire.service": (
                "/user.slice/user-1000.slice/user@1000.service/app.slice/pipewire.service"
            )
        },
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(
        item
        for item in payload["checks"]
        if item["name"] == "user_unit_pipewire.service_pid_916_live_oom_score_adj"
    )
    assert check["status"] == "gap"


def test_audit_passes_when_unbounded_tmux_scope_is_app_slice_backed(tmp_path: Path) -> None:
    result = _run(tmp_path, tmux_bounded=False, tmux_slice="app.slice")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    check = next(item for item in payload["checks"] if item["name"].startswith("tmux_scope_tmux"))
    assert check["detail"] == ""
    payload = json.loads(result.stdout)
    check = next(
        item for item in payload["checks"] if item["name"] == "tmux_scope_tmux-spawn-a.scope"
    )
    assert check["status"] == "pass"
    assert "Slice=app.slice" in check["actual"]


def test_audit_fails_when_unbounded_tmux_scope_is_outside_app_slice(tmp_path: Path) -> None:
    result = _run(tmp_path, tmux_bounded=False, tmux_slice="session.slice")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(
        item for item in payload["checks"] if item["name"] == "tmux_scope_tmux-spawn-a.scope"
    )
    assert check["status"] == "gap"
    assert "MemoryMax" in check["detail"]
    assert "Slice=session.slice" in check["detail"]


def test_audit_fails_when_user_process_retains_inherited_protection(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _write_proc(proc_root, 101, name="codex", uid=1000, oom_score=-900)
    _write_proc(proc_root, 102, name="wireplumber", uid=1000, oom_score=-900)
    _write_proc(proc_root, 900, name="systemd", uid=1000, oom_score=100)

    result = _run(tmp_path, proc_root=proc_root)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(
        item for item in payload["checks"] if item["name"] == "user_process_residual_oom_protection"
    )
    assert check["status"] == "gap"
    assert "101:codex=-900" in check["actual"]
    assert "102:wireplumber=-900" not in check["actual"]


def test_audit_allows_python_child_inside_protected_unit_cgroup(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    cgroup_root = tmp_path / "cgroup"
    studio_cgroup = (
        "/user.slice/user-1000.slice/user@1000.service/app.slice/studio-compositor.service"
    )
    cgroup_dir = cgroup_root / studio_cgroup.lstrip("/")
    cgroup_dir.mkdir(parents=True)
    (cgroup_dir / "cgroup.procs").write_text("914\n916\n", encoding="utf-8")
    _write_proc(proc_root, 914, name="python", uid=1000, oom_score=-800)
    _write_proc(proc_root, 916, name="python", uid=1000, oom_score=-800)
    _write_proc_cgroup(proc_root, 914, studio_cgroup)
    _write_proc_cgroup(proc_root, 916, studio_cgroup)

    result = _run(
        tmp_path,
        proc_root=proc_root,
        cgroup_root=cgroup_root,
        protected_unit_pids={"studio-compositor.service": 914},
        protected_unit_cgroups={"studio-compositor.service": studio_cgroup},
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    check = next(
        item for item in payload["checks"] if item["name"] == "user_process_residual_oom_protection"
    )
    assert check["status"] == "pass"
