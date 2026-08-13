from __future__ import annotations

import json
import os
import runpy
import stat
import subprocess
import time
from pathlib import Path

import pytest

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
    "pipewire.service": 100,
    "pipewire-pulse.service": 100,
    "wireplumber.service": 100,
    "hapax-daimonion.service": 100,
    "studio-compositor.service": 100,
    "hapax-imagination.service": 100,
}
PROTECTED_USER_UNIT_MEMORY = {
    "pipewire.service": (536870912, 268435456),
    "pipewire-pulse.service": (536870912, 268435456),
    "wireplumber.service": (536870912, 268435456),
    "hapax-daimonion.service": (2147483648, 1073741824),
    "studio-compositor.service": (6442450944, 3221225472),
    "hapax-imagination.service": (6442450944, 3221225472),
}
GITHUB_MCP_IMAGE_DIGEST = "sha256:30197479d8036c7811892bc07e06f9a05c9ef3cdd79bc59f256d50647f95788c"
GITHUB_MCP_IMAGE = f"ghcr.io/github/github-mcp-server@{GITHUB_MCP_IMAGE_DIGEST}"


def test_audit_resets_hostile_path_before_command_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "/tmp/hapax-hostile-path")
    monkeypatch.delenv("HAPAX_SYSTEMCTL", raising=False)

    namespace = runpy.run_path(str(SCRIPT))

    assert os.environ["PATH"] == "/usr/local/sbin:/usr/local/bin:/usr/bin:/bin"
    assert namespace["_systemctl"]() == "/usr/bin/systemctl"


def _protected_user_unit_cases(
    *,
    wrong_unit_score: bool = False,
    wrong_unit_memory: bool = False,
    wrong_unit_slice: bool = False,
    wrong_audio_no_new_privileges: bool = False,
    unit_pids: dict[str, int] | None = None,
    unit_cgroups: dict[str, str] | None = None,
    missing_units: frozenset[str] = frozenset(),
) -> str:
    unit_pids = unit_pids or {}
    unit_cgroups = unit_cgroups or {}
    cases = []
    for unit in PROTECTED_USER_UNIT_SCORES:
        if unit in missing_units:
            cases.append(
                f"  *\"--user show {unit} --no-pager\"*) printf 'LoadState=not-found\\n' ;;"
            )
            continue
        actual = 0 if wrong_unit_score and unit == "studio-compositor.service" else 100
        pid = unit_pids.get(unit, 0)
        cgroup = unit_cgroups.get(unit, "")
        memory_low, memory_min = PROTECTED_USER_UNIT_MEMORY[unit]
        if wrong_unit_memory and unit == "studio-compositor.service":
            memory_min = 0
        slice_name = (
            "session.slice" if unit.startswith(("pipewire", "wireplumber")) else "app.slice"
        )
        if wrong_unit_slice and unit == "studio-compositor.service":
            slice_name = "session.slice"
        no_new_privileges = (
            "no"
            if wrong_audio_no_new_privileges and unit == "pipewire.service"
            else "yes"
            if unit.startswith(("pipewire", "wireplumber"))
            else "no"
        )
        cases.append(
            f'  *"--user show {unit} --no-pager"*) '
            f"printf 'LoadState=loaded\\nOOMScoreAdjust={actual}\\nMainPID={pid}\\nControlGroup={cgroup}\\n"
            f"MemoryLow={memory_low}\\nMemoryMin={memory_min}\\nSlice={slice_name}\\n"
            f"NoNewPrivileges={no_new_privileges}\\n' ;;"
        )
    return "\n".join(cases)


def _recovery_system_unit_cases(
    *, wrong_score: bool = False, inactive_unit: str | None = None
) -> str:
    cases = []
    for unit, score in RECOVERY_SYSTEM_UNIT_SCORES.items():
        actual = -1000 if wrong_score and unit == "apcupsd.service" else score
        pid = 0 if unit == inactive_unit else RECOVERY_SYSTEM_UNIT_PIDS[unit]
        cases.append(f"  *\"show {unit}\"*) printf 'OOMScoreAdjust={actual}\\nMainPID={pid}\\n' ;;")
    return "\n".join(cases)


def _fake_systemctl(
    tmp_path: Path,
    *,
    user_oom: int = 100,
    user_oom_policy: str = "continue",
    app_bounded: bool = True,
    tmux_bounded: bool = True,
    tmux_slice: str = "app.slice",
    wrong_unit_score: bool = False,
    wrong_unit_memory: bool = False,
    wrong_unit_slice: bool = False,
    wrong_audio_no_new_privileges: bool = False,
    system_slice_finite_max: bool = False,
    user_slice_unprotected: bool = False,
    session_slice_unprotected: bool = False,
    user_floor_overcommitted: bool = False,
    protected_unit_pids: dict[str, int] | None = None,
    protected_unit_cgroups: dict[str, str] | None = None,
    sshd_score: int = 0,
    sshd_policy: str = "continue",
    wrong_recovery_unit_score: bool = False,
    inactive_recovery_unit: str | None = None,
    enforcer_timer_enabled: bool = False,
    enforcer_timer_active: bool = False,
    enforcer_service_active: bool = False,
    host_profile: str = "podium",
    missing_protected_units: frozenset[str] = frozenset(),
    judge_load_state: str = "masked",
    judge_unit_file_state: str = "masked",
    judge_active_state: str = "inactive",
    judge_fragment_path: str = "/dev/null",
) -> Path:
    path = tmp_path / "systemctl"
    calls = tmp_path / "systemctl.calls"
    if host_profile == "appendix":
        app_high = 46 * 1024**3
        app_max = 54 * 1024**3
        uid_high = 48 * 1024**3
        uid_max = 56 * 1024**3
    else:
        app_high = 72 * 1024**3
        app_max = 88 * 1024**3
        uid_high = 80 * 1024**3
        uid_max = 96 * 1024**3
    app_values = (
        f"MemoryHigh={app_high}\n"
        f"MemoryMax={app_max}\n"
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
        f"MemoryHigh={uid_high}\n"
        f"MemoryMax={uid_max}\n"
        "MemorySwapMax=8589934592\n"
        f"MemoryLow={'17179869184' if user_floor_overcommitted else '21474836480'}\n"
        f"MemoryMin={'8589934592' if user_floor_overcommitted else '10737418240'}\n"
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
        f"MemoryLow={'0' if user_slice_unprotected else '21474836480'}\n"
        f"MemoryMin={'0' if user_slice_unprotected else '10737418240'}\n"
    )
    session_slice_values = (
        "MemoryHigh=infinity\n"
        "MemoryMax=infinity\n"
        "MemorySwapMax=infinity\n"
        f"MemoryLow={'0' if session_slice_unprotected else '2147483648'}\n"
        f"MemoryMin={'0' if session_slice_unprotected else '1073741824'}\n"
    )
    path.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "{calls}"
case "$*" in
  *"--user show hapax-local-judge.service"*) printf 'LoadState={judge_load_state}\nUnitFileState={judge_unit_file_state}\nActiveState={judge_active_state}\nFragmentPath={judge_fragment_path}\n' ;;
  *"show hapax-oom-score-enforce.timer"*) printf 'LoadState=loaded\nUnitFileState={"enabled" if enforcer_timer_enabled else "static"}\nActiveState={"active" if enforcer_timer_active else "inactive"}\n' ;;
  *"show hapax-oom-score-enforce.service"*) printf 'LoadState=loaded\nActiveState={"active" if enforcer_service_active else "inactive"}\n' ;;
  *"show system.slice"*) printf '{system_slice_values}' ;;
  *"show user.slice"*) printf '{user_slice_values}ControlGroup=/user.slice\n' ;;
  *"show user-1000.slice"*) printf '{uid_memory_values}ControlGroup=/user.slice/user-1000.slice\n' ;;
  *"show user@1000.service --no-pager -p MemoryHigh"*) printf '{uid_memory_values}' ;;
  *"show user@1000.service --no-pager -p MemoryLow"*) printf '{uid_memory_values}ControlGroup=/user.slice/user-1000.slice/user@1000.service\n' ;;
  *"show user@1000.service"*) printf 'OOMScoreAdjust={user_oom}\\nOOMPolicy={user_oom_policy}\\nDropInPaths=/etc/systemd/system/user@1000.service.d/oom.conf\\nMainPID=900\\n' ;;
  *"show sshd.service"*) printf 'OOMScoreAdjust={sshd_score}\\nOOMPolicy={sshd_policy}\\nMainPID=920\\n' ;;
{_recovery_system_unit_cases(wrong_score=wrong_recovery_unit_score, inactive_unit=inactive_recovery_unit)}
  *"show app.slice"*) printf '{app_values}ControlGroup=/user.slice/user-1000.slice/user@1000.service/app.slice\n' ;;
  *"show session.slice"*) printf '{session_slice_values}ControlGroup=/user.slice/user-1000.slice/user@1000.service/session.slice\n' ;;
{_protected_user_unit_cases(wrong_unit_score=wrong_unit_score, wrong_unit_memory=wrong_unit_memory, wrong_unit_slice=wrong_unit_slice, wrong_audio_no_new_privileges=wrong_audio_no_new_privileges, unit_pids=protected_unit_pids, unit_cgroups=protected_unit_cgroups, missing_units=missing_protected_units)}
  *"list-units --type=scope"*) printf 'tmux-spawn-a.scope loaded active running tmux child pane\\n' ;;
  *"show tmux-spawn-a.scope"*) printf '{tmux_values}' ;;
  *) echo "unexpected args: $*" >&2; exit 9 ;;
esac
""",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _fake_docker(
    tmp_path: Path,
    *,
    mcp_count: int = 0,
    mcp_memory: int = 512 * 1024**2,
    mcp_memory_swap: int = 768 * 1024**2,
    mcp_oom_kill_disable: bool = False,
    include_judge: bool = False,
    inventory_override: str | None = None,
    inspect_override: str | None = None,
    mcp_image_id: str = GITHUB_MCP_IMAGE_DIGEST,
) -> Path:
    path = tmp_path / "docker"
    calls = tmp_path / "docker.calls"
    containers = [
        (f"{index + 1:064x}", f"hapax-github-mcp-{1000 + index}-{index + 1}")
        for index in range(mcp_count)
    ]
    if include_judge:
        containers.append(("f" * 64, "hapax-local-judge"))
    inventory = "".join(f"{container_id}\t{name}\n" for container_id, name in containers)
    inventory_file = tmp_path / "docker.inventory"
    inventory_file.write_text(
        inventory if inventory_override is None else inventory_override,
        encoding="utf-8",
    )
    inspect_cases = []
    inspect_file = tmp_path / "docker.inspect"
    if inspect_override is not None:
        inspect_file.write_text(inspect_override, encoding="utf-8")
    for container_id, name in containers:
        inspect_payload = "\t".join(
            json.dumps(value)
            for value in (
                container_id,
                f"/{name}",
                mcp_memory,
                mcp_memory_swap,
                mcp_oom_kill_disable,
                mcp_image_id,
                GITHUB_MCP_IMAGE,
                "/server/github-mcp-server",
                [
                    "stdio",
                    "--log-file",
                    "/tmp/github-mcp.log",
                    "--tools=pull_request_read",
                ],
            )
        )
        if inspect_override is None:
            inspect_cases.append(f"  *\" {container_id}\") printf '%s\\n' '{inspect_payload}' ;;")
    if inspect_override is not None:
        inspect_cases.append(f'  *" inspect --format "*) cat "{inspect_file}" ;;')
    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'printf \'%s\\n\' "$*" >> "{calls}"\n'
        'case "$*" in\n'
        f'  *" ps -a --no-trunc --format "*) cat "{inventory_file}" ;;\n'
        + "\n".join(inspect_cases)
        + "\n"
        '  *) echo "unexpected docker args: $*" >&2; exit 9 ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _write_proc(
    proc_root: Path,
    pid: int,
    *,
    name: str,
    uid: int,
    oom_score: int,
    ppid: int = 1,
) -> None:
    pid_dir = proc_root / str(pid)
    pid_dir.mkdir(parents=True)
    (pid_dir / "status").write_text(
        f"Name:\t{name}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\nPPid:\t{ppid}\n",
        encoding="utf-8",
    )
    (pid_dir / "oom_score_adj").write_text(f"{oom_score}\n", encoding="utf-8")


def _write_proc_cgroup(proc_root: Path, pid: int, cgroup: str) -> None:
    (proc_root / str(pid) / "cgroup").write_text(f"0::{cgroup}\n", encoding="utf-8")


def _run(
    tmp_path: Path,
    *,
    user_oom: int = 100,
    user_oom_policy: str = "continue",
    app_bounded: bool = True,
    tmux_bounded: bool = True,
    tmux_slice: str = "app.slice",
    wrong_unit_score: bool = False,
    wrong_unit_memory: bool = False,
    wrong_unit_slice: bool = False,
    wrong_audio_no_new_privileges: bool = False,
    system_slice_finite_max: bool = False,
    user_slice_unprotected: bool = False,
    session_slice_unprotected: bool = False,
    user_floor_overcommitted: bool = False,
    protected_unit_pids: dict[str, int] | None = None,
    protected_unit_cgroups: dict[str, str] | None = None,
    sshd_score: int = 0,
    sshd_policy: str = "continue",
    wrong_recovery_unit_score: bool = False,
    wrong_recovery_live_score: bool = False,
    inactive_recovery_unit: str | None = None,
    proc_root: Path | None = None,
    cgroup_root: Path | None = None,
    extra_direct_child_floor: bool = False,
    extra_uid_sibling_floor: bool = False,
    extra_user_sibling_floor: bool = False,
    extra_app_sibling_floor: bool = False,
    extra_session_sibling_floor: bool = False,
    enforcer_timer_enabled: bool = False,
    enforcer_timer_active: bool = False,
    enforcer_service_active: bool = False,
    host_profile: str = "podium",
    missing_protected_units: frozenset[str] = frozenset(),
    docker_mcp_count: int = 0,
    docker_mcp_memory: int = 512 * 1024**2,
    docker_mcp_memory_swap: int = 768 * 1024**2,
    docker_mcp_oom_kill_disable: bool = False,
    docker_include_judge: bool = False,
    docker_inventory_override: str | None = None,
    docker_inspect_override: str | None = None,
    docker_mcp_image_id: str = GITHUB_MCP_IMAGE_DIGEST,
    judge_load_state: str = "masked",
    judge_unit_file_state: str = "masked",
    judge_active_state: str = "inactive",
    judge_fragment_path: str = "/dev/null",
) -> subprocess.CompletedProcess[str]:
    if proc_root is None:
        proc_root = tmp_path / "proc"
        proc_root.mkdir(exist_ok=True)
    if not (proc_root / "900").exists():
        _write_proc(proc_root, 900, name="systemd", uid=1000, oom_score=100)
    if not (proc_root / "920").exists():
        _write_proc(proc_root, 920, name="sshd", uid=0, oom_score=0)
    memtotal_kib = 60 * 1024**2 if host_profile == "appendix" else 124 * 1024**2
    (proc_root / "meminfo").write_text(f"MemTotal:       {memtotal_kib} kB\n", encoding="utf-8")
    (proc_root / "swaps").write_text(
        "Filename\tType\tSize\tUsed\tPriority\n/dev/zram0\tpartition\t33554428\t0\t100\n",
        encoding="utf-8",
    )
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
    user_slice_cgroup = cgroup_root / "user.slice"
    uid_cgroup = user_slice_cgroup / "user-1000.slice"
    manager_cgroup = uid_cgroup / "user@1000.service"
    uid_cgroup.mkdir(parents=True, exist_ok=True)
    (uid_cgroup / "memory.low").write_text("21474836480\n", encoding="utf-8")
    (uid_cgroup / "memory.min").write_text("10737418240\n", encoding="utf-8")
    manager_cgroup.mkdir(parents=True, exist_ok=True)
    (manager_cgroup / "memory.low").write_text("21474836480\n", encoding="utf-8")
    (manager_cgroup / "memory.min").write_text("10737418240\n", encoding="utf-8")
    if extra_user_sibling_floor:
        sibling = user_slice_cgroup / "user-1001.slice"
        sibling.mkdir()
        (sibling / "memory.low").write_text("2147483648\n", encoding="utf-8")
        (sibling / "memory.min").write_text("1073741824\n", encoding="utf-8")
    if extra_uid_sibling_floor:
        sibling = uid_cgroup / "session-42.scope"
        sibling.mkdir()
        (sibling / "memory.low").write_text("2147483648\n", encoding="utf-8")
        (sibling / "memory.min").write_text("1073741824\n", encoding="utf-8")
    direct_child_floors = {
        "app.slice": (17179869184, 8589934592),
        "session.slice": (2147483648, 1073741824),
    }
    if extra_direct_child_floor:
        direct_child_floors["background.slice"] = (4294967296, 2147483648)
    for child, (memory_low, memory_min) in direct_child_floors.items():
        child_dir = manager_cgroup / child
        child_dir.mkdir(parents=True, exist_ok=True)
        (child_dir / "memory.low").write_text(f"{memory_low}\n", encoding="utf-8")
        (child_dir / "memory.min").write_text(f"{memory_min}\n", encoding="utf-8")
    app_cgroup = manager_cgroup / "app.slice"
    session_cgroup = manager_cgroup / "session.slice"
    leaf_floors = {
        app_cgroup: {
            "hapax-daimonion.service": (2147483648, 1073741824),
            "studio-compositor.service": (6442450944, 3221225472),
            "hapax-imagination.service": (6442450944, 3221225472),
        },
        session_cgroup: {
            "pipewire.service": (536870912, 268435456),
            "pipewire-pulse.service": (536870912, 268435456),
            "wireplumber.service": (536870912, 268435456),
        },
    }
    if extra_app_sibling_floor:
        leaf_floors[app_cgroup]["browser-batch.scope"] = (3221225472, 2147483648)
    if extra_session_sibling_floor:
        leaf_floors[session_cgroup]["session-99.scope"] = (1073741824, 536870912)
    for parent, children in leaf_floors.items():
        for child, (memory_low, memory_min) in children.items():
            child_dir = parent / child
            child_dir.mkdir(parents=True, exist_ok=True)
            (child_dir / "memory.low").write_text(f"{memory_low}\n", encoding="utf-8")
            (child_dir / "memory.min").write_text(f"{memory_min}\n", encoding="utf-8")
    sys_root = tmp_path / "sys"
    zram_root = sys_root / "block/zram0"
    zram_root.mkdir(parents=True, exist_ok=True)
    zram_gib = 16 if host_profile == "appendix" else 32
    (zram_root / "disksize").write_text(f"{zram_gib * 1024**3}\n", encoding="utf-8")
    (zram_root / "comp_algorithm").write_text("lzo [zstd] lz4\n", encoding="utf-8")
    env = {
        **os.environ,
        "HAPAX_OOM_AUDIT_TEST_MODE": "1",
        "HAPAX_OOM_AUDIT_HOSTNAME": f"hapax-{host_profile}",
        "HAPAX_OOM_AUDIT_MEMTOTAL_KIB": str(memtotal_kib),
        "HAPAX_SYSTEMCTL": str(
            _fake_systemctl(
                tmp_path,
                user_oom=user_oom,
                user_oom_policy=user_oom_policy,
                app_bounded=app_bounded,
                tmux_bounded=tmux_bounded,
                tmux_slice=tmux_slice,
                wrong_unit_score=wrong_unit_score,
                wrong_unit_memory=wrong_unit_memory,
                wrong_unit_slice=wrong_unit_slice,
                wrong_audio_no_new_privileges=wrong_audio_no_new_privileges,
                system_slice_finite_max=system_slice_finite_max,
                user_slice_unprotected=user_slice_unprotected,
                session_slice_unprotected=session_slice_unprotected,
                user_floor_overcommitted=user_floor_overcommitted,
                protected_unit_pids=protected_unit_pids,
                protected_unit_cgroups=protected_unit_cgroups,
                sshd_score=sshd_score,
                sshd_policy=sshd_policy,
                wrong_recovery_unit_score=wrong_recovery_unit_score,
                inactive_recovery_unit=inactive_recovery_unit,
                enforcer_timer_enabled=enforcer_timer_enabled,
                enforcer_timer_active=enforcer_timer_active,
                enforcer_service_active=enforcer_service_active,
                host_profile=host_profile,
                missing_protected_units=missing_protected_units,
                judge_load_state=judge_load_state,
                judge_unit_file_state=judge_unit_file_state,
                judge_active_state=judge_active_state,
                judge_fragment_path=judge_fragment_path,
            )
        ),
        "HAPAX_OOM_AUDIT_DOCKER": str(
            _fake_docker(
                tmp_path,
                mcp_count=docker_mcp_count,
                mcp_memory=docker_mcp_memory,
                mcp_memory_swap=docker_mcp_memory_swap,
                mcp_oom_kill_disable=docker_mcp_oom_kill_disable,
                include_judge=docker_include_judge,
                inventory_override=docker_inventory_override,
                inspect_override=docker_inspect_override,
                mcp_image_id=docker_mcp_image_id,
            )
        ),
        "HAPAX_OOM_AUDIT_PROC_ROOT": str(proc_root),
        "HAPAX_OOM_AUDIT_CGROUP_ROOT": str(cgroup_root),
        "HAPAX_OOM_AUDIT_SYS_ROOT": str(sys_root),
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
    assert payload["authoritative"] is False
    assert payload["scope"] == "observational-live-drift"
    assert statuses["audit_authority"] == "pass"
    assert statuses["host_memory_policy"] == "pass"
    assert statuses["zram_size"] == "pass"
    assert statuses["local_judge_unit_retired"] == "pass"
    assert statuses["docker_hapax-local-judge_retired"] == "pass"
    assert statuses["oom_enforcer_timer_UnitFileState"] == "pass"
    assert statuses["user_manager_oom_score_adjust"] == "pass"
    assert statuses["user_manager_OOMPolicy"] == "pass"
    assert statuses["system_slice_MemoryLow"] == "pass"
    assert statuses["user_slice_MemoryLow"] == "pass"
    assert statuses["app_slice_MemorySwapMax"] == "pass"
    assert statuses["session_slice_MemoryLow"] == "pass"
    assert statuses["user_slice_child_floor_MemoryLow"] == "pass"
    assert statuses["user_1000_slice_child_floor_MemoryLow"] == "pass"
    assert statuses["user_manager_child_floor_MemoryLow"] == "pass"
    assert statuses["user_manager_child_floor_MemoryMin"] == "pass"
    assert statuses["app_slice_child_floor_MemoryLow"] == "pass"
    assert statuses["session_slice_child_floor_MemoryMin"] == "pass"
    assert statuses["user_unit_pipewire.service_Slice"] == "pass"
    assert statuses["user_unit_pipewire.service_NoNewPrivileges"] == "pass"
    assert statuses["user_unit_studio-compositor.service_Slice"] == "pass"


def test_audit_fails_when_session_slice_audio_reservation_is_missing(tmp_path: Path) -> None:
    result = _run(tmp_path, session_slice_unprotected=True)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(item for item in payload["checks"] if item["name"] == "session_slice_MemoryLow")
    assert check["status"] == "gap"
    assert check["actual"] == "0"
    assert check["target"] == "2147483648"


def test_audit_fails_when_child_floors_exceed_user_manager_parent(tmp_path: Path) -> None:
    result = _run(tmp_path, user_floor_overcommitted=True)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = {item["name"]: item for item in payload["checks"]}
    assert checks["user_manager_child_floor_MemoryLow"]["status"] == "gap"
    assert checks["user_manager_child_floor_MemoryMin"]["status"] == "gap"
    assert "proportionally dilute" in checks["user_manager_child_floor_MemoryLow"]["detail"]


def test_audit_fails_when_additional_direct_child_dilutes_user_manager_floor(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path, extra_direct_child_floor=True)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = {item["name"]: item for item in payload["checks"]}
    low = checks["user_manager_child_floor_MemoryLow"]
    minimum = checks["user_manager_child_floor_MemoryMin"]
    assert low["status"] == "gap"
    assert minimum["status"] == "gap"
    assert "background.slice:4294967296" in low["actual"]
    assert low["target"] == "parent >= all direct children"


def test_audit_fails_when_session_scope_dilutes_uid_slice_floor(tmp_path: Path) -> None:
    result = _run(tmp_path, extra_uid_sibling_floor=True)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(
        item
        for item in payload["checks"]
        if item["name"] == "user_1000_slice_child_floor_MemoryLow"
    )
    assert check["status"] == "gap"
    assert "session-42.scope:2147483648" in check["actual"]


def test_audit_fails_when_another_uid_dilutes_user_slice_floor(tmp_path: Path) -> None:
    result = _run(tmp_path, extra_user_sibling_floor=True)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(
        item for item in payload["checks"] if item["name"] == "user_slice_child_floor_MemoryLow"
    )
    assert check["status"] == "gap"
    assert "user-1001.slice:2147483648" in check["actual"]


def test_audit_fails_when_app_sibling_dilutes_app_slice_floor(tmp_path: Path) -> None:
    result = _run(tmp_path, extra_app_sibling_floor=True)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = {item["name"]: item for item in payload["checks"]}
    assert checks["app_slice_child_floor_MemoryLow"]["status"] == "gap"
    assert checks["app_slice_child_floor_MemoryMin"]["status"] == "gap"
    assert "browser-batch.scope:3221225472" in checks["app_slice_child_floor_MemoryLow"]["actual"]


def test_audit_fails_when_session_sibling_dilutes_session_slice_floor(tmp_path: Path) -> None:
    result = _run(tmp_path, extra_session_sibling_floor=True)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = {item["name"]: item for item in payload["checks"]}
    assert checks["session_slice_child_floor_MemoryLow"]["status"] == "gap"
    assert checks["session_slice_child_floor_MemoryMin"]["status"] == "gap"
    assert "session-99.scope:1073741824" in checks["session_slice_child_floor_MemoryLow"]["actual"]


def test_audit_fails_when_protected_unit_leaves_checked_app_slice_chain(tmp_path: Path) -> None:
    result = _run(tmp_path, wrong_unit_slice=True)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(
        item
        for item in payload["checks"]
        if item["name"] == "user_unit_studio-compositor.service_Slice"
    )
    assert check["status"] == "gap"
    assert check["actual"] == "session.slice"
    assert check["target"] == "app.slice"


def test_audit_fails_when_audio_service_loses_no_new_privileges(tmp_path: Path) -> None:
    result = _run(tmp_path, wrong_audio_no_new_privileges=True)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(
        item
        for item in payload["checks"]
        if item["name"] == "user_unit_pipewire.service_NoNewPrivileges"
    )
    assert check["status"] == "gap"
    assert check["target"] == "yes"
    assert "privilege boundary" in check["detail"]


def test_audit_fails_when_user_manager_protects_all_descendants(tmp_path: Path) -> None:
    result = _run(tmp_path, user_oom=-900)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(
        item for item in payload["checks"] if item["name"] == "user_manager_oom_score_adjust"
    )
    assert check["status"] == "gap"
    assert check["target"] == "100"
    assert "packaged kill ordering exactly" in check["detail"]


def test_audit_fails_when_configured_user_manager_score_is_zero_but_live_score_is_100(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path, user_oom=0)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = {item["name"]: item for item in payload["checks"]}
    configured = checks["user_manager_oom_score_adjust"]
    assert configured["status"] == "gap"
    assert configured["actual"] == "0"
    assert configured["target"] == "100"
    assert checks["user_manager_live_oom_score_adj"]["status"] == "pass"


def test_audit_fails_when_user_manager_would_stop_after_descendant_oom(tmp_path: Path) -> None:
    result = _run(tmp_path, user_oom_policy="stop")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(item for item in payload["checks"] if item["name"] == "user_manager_OOMPolicy")
    assert check["status"] == "gap"
    assert "survive descendant OOM" in check["detail"]


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


def test_audit_fails_when_recovery_daemon_is_inactive(tmp_path: Path) -> None:
    result = _run(tmp_path, inactive_recovery_unit="apcupsd.service")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = {item["name"]: item for item in payload["checks"]}
    live = checks["system_unit_apcupsd.service_live_oom_score_adj"]
    assert live["status"] == "gap"
    assert live["actual"] == "inactive"
    assert "no live main process" in live["detail"]


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
    assert "separately runtime-authorized root-broker work" in check["detail"]
    assert "install-p0-oom-containment" not in check["detail"]


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


def test_audit_fails_when_protected_user_unit_process_has_any_negative_score(
    tmp_path: Path,
) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    cgroup_root = tmp_path / "cgroup"
    cgroup_dir = (
        cgroup_root / "user.slice/user-1000.slice/user@1000.service/session.slice/pipewire.service"
    )
    cgroup_dir.mkdir(parents=True)
    (cgroup_dir / "cgroup.procs").write_text("910\n916\n", encoding="utf-8")
    _write_proc(proc_root, 910, name="pipewire", uid=1000, oom_score=100)
    _write_proc(proc_root, 916, name="pipewire-worker", uid=1000, oom_score=-500, ppid=910)
    pipewire_cgroup = "/user.slice/user-1000.slice/user@1000.service/session.slice/pipewire.service"
    _write_proc_cgroup(proc_root, 910, pipewire_cgroup)
    _write_proc_cgroup(proc_root, 916, pipewire_cgroup)

    result = _run(
        tmp_path,
        proc_root=proc_root,
        cgroup_root=cgroup_root,
        protected_unit_pids={"pipewire.service": 910},
        protected_unit_cgroups={
            "pipewire.service": (
                "/user.slice/user-1000.slice/user@1000.service/session.slice/pipewire.service"
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
    assert check["target"] == "100"
    residual = next(
        item for item in payload["checks"] if item["name"] == "user_process_residual_oom_protection"
    )
    assert "916:pipewire-worker=-500" in residual["actual"]


def test_audit_revalidates_protected_pid_cgroup_before_score_and_exemption(
    tmp_path: Path,
) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    cgroup_root = tmp_path / "cgroup"
    studio_cgroup = (
        "/user.slice/user-1000.slice/user@1000.service/app.slice/studio-compositor.service"
    )
    moved_cgroup = "/user.slice/user-1000.slice/session.slice/app-niri-foot.scope"
    cgroup_dir = cgroup_root / studio_cgroup.lstrip("/")
    cgroup_dir.mkdir(parents=True)
    (cgroup_dir / "cgroup.procs").write_text("914\n", encoding="utf-8")
    _write_proc(proc_root, 914, name="python", uid=1000, oom_score=-500)
    _write_proc_cgroup(proc_root, 914, moved_cgroup)

    result = _run(
        tmp_path,
        proc_root=proc_root,
        cgroup_root=cgroup_root,
        protected_unit_pids={"studio-compositor.service": 914},
        protected_unit_cgroups={"studio-compositor.service": studio_cgroup},
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    membership = next(
        item
        for item in payload["checks"]
        if item["name"] == "user_unit_studio-compositor.service_pid_914_cgroup_membership"
    )
    assert membership["status"] == "gap"
    assert membership["actual"] == moved_cgroup
    residual = next(
        item for item in payload["checks"] if item["name"] == "user_process_residual_oom_protection"
    )
    assert residual["status"] == "gap"
    assert "914:python=-500" in residual["actual"]


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
    _write_proc(proc_root, 102, name="wireplumber", uid=1000, oom_score=-500)
    _write_proc(proc_root, 103, name="worker", uid=1000, oom_score=-1)
    _write_proc(proc_root, 900, name="systemd", uid=1000, oom_score=100)

    result = _run(tmp_path, proc_root=proc_root)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(
        item for item in payload["checks"] if item["name"] == "user_process_residual_oom_protection"
    )
    assert check["status"] == "gap"
    assert "101:codex=-900" in check["actual"]
    assert "102:wireplumber=-500" in check["actual"]
    assert "103:worker=-1" in check["actual"]


def test_audit_allows_neutral_python_child_inside_protected_unit_cgroup(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    cgroup_root = tmp_path / "cgroup"
    studio_cgroup = (
        "/user.slice/user-1000.slice/user@1000.service/app.slice/studio-compositor.service"
    )
    cgroup_dir = cgroup_root / studio_cgroup.lstrip("/")
    cgroup_dir.mkdir(parents=True)
    (cgroup_dir / "cgroup.procs").write_text("914\n916\n", encoding="utf-8")
    _write_proc(proc_root, 914, name="python", uid=1000, oom_score=100)
    _write_proc(proc_root, 916, name="python", uid=1000, oom_score=100, ppid=914)
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


def test_audit_rejects_same_uid_process_injected_below_protected_cgroup(
    tmp_path: Path,
) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    cgroup_root = tmp_path / "cgroup"
    pipewire_cgroup = "/user.slice/user-1000.slice/user@1000.service/session.slice/pipewire.service"
    cgroup_dir = cgroup_root / pipewire_cgroup.lstrip("/")
    attacker_dir = cgroup_dir / "evil.scope"
    attacker_dir.mkdir(parents=True)
    (cgroup_dir / "cgroup.procs").write_text("910\n", encoding="utf-8")
    (attacker_dir / "cgroup.procs").write_text("916\n", encoding="utf-8")
    _write_proc(proc_root, 910, name="pipewire", uid=1000, oom_score=100)
    _write_proc(proc_root, 916, name="wireplumber", uid=1000, oom_score=-500, ppid=1)
    _write_proc_cgroup(proc_root, 910, pipewire_cgroup)
    _write_proc_cgroup(proc_root, 916, f"{pipewire_cgroup}/evil.scope")

    result = _run(
        tmp_path,
        proc_root=proc_root,
        cgroup_root=cgroup_root,
        protected_unit_pids={"pipewire.service": 910},
        protected_unit_cgroups={"pipewire.service": pipewire_cgroup},
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    identity = next(
        item
        for item in payload["checks"]
        if item["name"] == "user_unit_pipewire.service_pid_916_process_tree_identity"
    )
    assert identity["status"] == "gap"
    residual = next(
        item for item in payload["checks"] if item["name"] == "user_process_residual_oom_protection"
    )
    assert residual["status"] == "gap"
    assert "916:wireplumber=-500" in residual["actual"]


@pytest.mark.parametrize("host_profile", ["appendix", "podium"])
def test_audit_passes_for_each_shipped_host_profile(tmp_path: Path, host_profile: str) -> None:
    result = _run(tmp_path, host_profile=host_profile)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    policy = next(item for item in payload["checks"] if item["name"] == "host_memory_policy")
    assert policy["status"] == "pass"
    assert f"hapax-{host_profile}:{host_profile}:" in policy["actual"]


def test_appendix_skips_only_its_declared_absent_user_units(tmp_path: Path) -> None:
    missing = frozenset(
        {
            "hapax-daimonion.service",
            "studio-compositor.service",
            "hapax-imagination.service",
        }
    )
    result = _run(
        tmp_path,
        host_profile="appendix",
        missing_protected_units=missing,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    checks = {item["name"]: item for item in payload["checks"]}
    for unit in missing:
        check = checks[f"user_unit_{unit}_availability"]
        assert check["status"] == "pass"
        assert check["actual"] == "not-found"


def test_podium_fails_when_an_appendix_optional_unit_is_absent(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        missing_protected_units=frozenset({"studio-compositor.service"}),
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(
        item
        for item in payload["checks"]
        if item["name"] == "user_unit_studio-compositor.service_availability"
    )
    assert check["status"] == "gap"
    assert check["target"] == "loaded"


@pytest.mark.parametrize(
    ("kwargs", "check_name"),
    (
        ({"enforcer_timer_enabled": True}, "oom_enforcer_timer_UnitFileState"),
        ({"enforcer_timer_active": True}, "oom_enforcer_timer_ActiveState"),
        ({"enforcer_service_active": True}, "oom_enforcer_service_ActiveState"),
    ),
)
def test_audit_fails_closed_when_retired_enforcer_surface_is_active(
    tmp_path: Path, kwargs: dict[str, object], check_name: str
) -> None:
    result = _run(tmp_path, **kwargs)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(item for item in payload["checks"] if item["name"] == check_name)
    assert check["status"] == "gap"


def test_audit_accepts_all_three_ephemeral_mcp_containers_with_exact_limits(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path, docker_mcp_count=3)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    checks = {item["name"]: item for item in payload["checks"]}
    assert checks["docker_github_mcp_count"]["actual"] == "3"
    limit_checks = [
        item for item in payload["checks"] if item["name"].startswith("docker_hapax-github-mcp-")
    ]
    assert len(limit_checks) == 3
    assert all(item["status"] == "pass" for item in limit_checks)


@pytest.mark.parametrize(
    "kwargs",
    (
        {"docker_mcp_memory": 0},
        {"docker_mcp_memory_swap": 0},
        {"docker_mcp_oom_kill_disable": True},
    ),
)
def test_audit_rejects_mcp_limit_or_oom_killer_drift(
    tmp_path: Path, kwargs: dict[str, object]
) -> None:
    result = _run(tmp_path, docker_mcp_count=1, **kwargs)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(
        item for item in payload["checks"] if item["name"].startswith("docker_hapax-github-mcp-")
    )
    assert check["status"] == "gap"


def test_audit_rejects_mcp_image_substitution(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        docker_mcp_count=1,
        docker_mcp_image_id=f"sha256:{'f' * 64}",
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(
        item for item in payload["checks"] if item["name"].startswith("docker_hapax-github-mcp-")
    )
    assert check["status"] == "gap"
    assert "image" in check["detail"]


def test_audit_requires_historical_local_judge_to_be_absent(tmp_path: Path) -> None:
    result = _run(tmp_path, docker_include_judge=True)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(
        item for item in payload["checks"] if item["name"] == "docker_hapax-local-judge_retired"
    )
    assert check["status"] == "gap"
    assert check["actual"] == "f" * 64


def test_audit_requires_historical_local_judge_unit_to_be_masked_and_inactive(
    tmp_path: Path,
) -> None:
    result = _run(
        tmp_path,
        judge_load_state="loaded",
        judge_unit_file_state="enabled",
        judge_active_state="active",
        judge_fragment_path="/home/hapax/.config/systemd/user/hapax-local-judge.service",
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = {item["name"]: item for item in payload["checks"]}
    assert checks["docker_hapax-local-judge_retired"]["status"] == "pass"
    assert checks["local_judge_unit_retired"]["status"] == "gap"
    assert "ActiveState=active" in checks["local_judge_unit_retired"]["actual"]


def test_audit_bounds_docker_output_before_parsing(tmp_path: Path) -> None:
    result = _run(tmp_path, docker_inventory_override="x" * (20 * 1024))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(item for item in payload["checks"] if item["name"] == "docker_oom_targets")
    assert check["status"] == "error"
    assert "output exceeded 16384 bytes" in check["detail"]


def test_command_deadline_survives_a_child_that_closes_both_pipes() -> None:
    namespace = runpy.run_path(str(SCRIPT))
    bounded_run = namespace["_run"]
    bounded_run.__globals__["COMMAND_TIMEOUT_SECONDS"] = 0.1

    started = time.monotonic()
    result = bounded_run(["/usr/bin/bash", "-c", "exec 1>&- 2>&-; /usr/bin/sleep 10"])
    elapsed = time.monotonic() - started

    assert result.returncode == 124
    assert "timed out" in result.stderr
    assert elapsed < 2


def test_audit_bounds_docker_inventory_rows(tmp_path: Path) -> None:
    result = _run(tmp_path, docker_inventory_override="x\n" * 513)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(item for item in payload["checks"] if item["name"] == "docker_oom_targets")
    assert check["status"] == "error"
    assert check["target"] == "at most 512 inventory rows"


def test_audit_rejects_malformed_formatted_docker_inspect(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        docker_mcp_count=1,
        docker_inspect_override="[]\n",
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    check = next(
        item for item in payload["checks"] if item["name"].startswith("docker_hapax-github-mcp-")
    )
    assert check["status"] == "error"
    assert "nine formatted Docker inspect fields" in check["detail"]


def test_audit_is_behaviorally_observational(tmp_path: Path) -> None:
    result = _run(tmp_path, docker_mcp_count=3)

    assert result.returncode == 0, result.stderr
    systemctl_calls = (tmp_path / "systemctl.calls").read_text(encoding="utf-8").splitlines()
    docker_calls = (tmp_path / "docker.calls").read_text(encoding="utf-8").splitlines()
    assert systemctl_calls
    assert docker_calls
    assert all(" show " in f" {call} " or " list-units " in f" {call} " for call in systemctl_calls)
    assert all(" ps " in f" {call} " or " inspect " in f" {call} " for call in docker_calls)
    assert not any(
        token in f" {call} "
        for call in systemctl_calls
        for token in (" start ", " stop ", " restart ", " enable ", " disable ")
    )
    assert not any(
        token in f" {call} "
        for call in docker_calls
        for token in (" rm ", " stop ", " update ", " run ")
    )


def test_source_test_selectors_require_explicit_test_mode(tmp_path: Path) -> None:
    marker = tmp_path / "systemctl-ran"
    fake = tmp_path / "systemctl"
    fake.write_text(f"#!/bin/sh\ntouch {marker!s}\n", encoding="utf-8")
    fake.chmod(0o755)
    env = os.environ.copy()
    env.pop("HAPAX_OOM_AUDIT_TEST_MODE", None)
    env["HAPAX_SYSTEMCTL"] = str(fake)

    result = subprocess.run(
        [str(SCRIPT), "--json"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["checks"][0]["name"] == "host_memory_policy"
    assert "test selectors require" in payload["checks"][0]["detail"]
    assert not marker.exists()


def test_canonical_installed_audit_rejects_test_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HAPAX_OOM_AUDIT_TEST_MODE", "1")
    namespace = runpy.run_path(str(SCRIPT))
    admission = namespace["_validate_test_mode_admission"]
    admission.__globals__["INSTALLED_AUDIT_PATH"] = namespace["SCRIPT_PATH"]

    with pytest.raises(namespace["HostPolicyError"], match="canonical installed audit"):
        admission()


@pytest.mark.parametrize("memtotal_gib", [59, 61])
def test_appendix_profile_interval_is_inclusive(
    monkeypatch: pytest.MonkeyPatch, memtotal_gib: int
) -> None:
    monkeypatch.setenv("HAPAX_OOM_AUDIT_TEST_MODE", "1")
    monkeypatch.setenv("HAPAX_OOM_AUDIT_HOSTNAME", "hapax-appendix")
    monkeypatch.setenv("HAPAX_OOM_AUDIT_MEMTOTAL_KIB", str(memtotal_gib * 1024**2))
    namespace = runpy.run_path(str(SCRIPT))

    namespace["_validate_test_mode_admission"]()
    policy = namespace["derive_host_policy"]()
    assert policy.profile == "appendix"


@pytest.mark.parametrize("memtotal_gib", [58, 62])
def test_appendix_profile_refuses_out_of_interval_memory(
    monkeypatch: pytest.MonkeyPatch, memtotal_gib: int
) -> None:
    monkeypatch.setenv("HAPAX_OOM_AUDIT_TEST_MODE", "1")
    monkeypatch.setenv("HAPAX_OOM_AUDIT_HOSTNAME", "hapax-appendix")
    monkeypatch.setenv("HAPAX_OOM_AUDIT_MEMTOTAL_KIB", str(memtotal_gib * 1024**2))
    namespace = runpy.run_path(str(SCRIPT))

    with pytest.raises(namespace["HostPolicyError"], match="outside admitted interval"):
        namespace["derive_host_policy"]()
