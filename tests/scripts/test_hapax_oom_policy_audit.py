from __future__ import annotations

import csv
import fcntl
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
ROOT_REQUIRED_AUDIT = REPO_ROOT / "scripts" / "hapax-root-required-deploy-audit"
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
JUDGE_CONTAINER_ID = "a" * 64
MCP_CONTAINER_ID = "b" * 64
REPLACEMENT_CONTAINER_ID = "d" * 64
INSTALLED_TEST_SELECTORS = {
    "HAPAX_OOM_AUDIT_TEST_MODE",
    "HAPAX_OOM_AUDIT_PROC_ROOT",
    "HAPAX_OOM_AUDIT_CGROUP_ROOT",
    "HAPAX_OOM_AUDIT_SYS_ROOT",
    "HAPAX_OOM_AUDIT_MEMTOTAL_KIB",
    "HAPAX_OOM_AUDIT_HOSTNAME",
    "HAPAX_OOM_AUDIT_PROFILE_TABLE",
    "HAPAX_OOM_AUDIT_SEALED_PACKAGE_SOURCE",
    "HAPAX_OOM_AUDIT_SYSTEMD_SYSTEM_DIR",
    "HAPAX_OOM_AUDIT_SYSTEMD_USER_DIR",
    "HAPAX_OOM_AUDIT_USER_UNIT_PATHS",
    "HAPAX_OOM_AUDIT_DOCKER",
    "HAPAX_SYSTEMCTL",
    "HAPAX_SYSTEMD_ANALYZE",
}


@pytest.fixture(autouse=True)
def _host_policy_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sys_root = tmp_path / "sys"
    zram = sys_root / "block" / "zram0"
    zram.mkdir(parents=True)
    (zram / "disksize").write_text(f"{32 * 1024**3}\n", encoding="utf-8")
    (zram / "comp_algorithm").write_text("lzo-rle lzo lz4 lz4hc [zstd] deflate\n", encoding="utf-8")
    unit_paths = tmp_path / "user-unit-path"
    unit_paths.mkdir()
    system_dir = tmp_path / "systemd-system"
    user_dir = tmp_path / "systemd-user"
    for path in (
        system_dir / "system.slice.d/oom-containment.conf",
        system_dir / "user.slice.d/oom-containment.conf",
        system_dir / "user-1000.slice.d/oom-containment.conf",
        system_dir / "user@1000.service.d/oom.conf",
        user_dir / "app.slice.d/oom-containment.conf",
        user_dir / "session.slice.d/oom-containment.conf",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[Slice]\nMemoryHigh=infinity\n", encoding="utf-8")
    monkeypatch.setenv("HAPAX_OOM_AUDIT_TEST_MODE", "1")
    monkeypatch.setenv("HAPAX_OOM_AUDIT_MEMTOTAL_KIB", "131007744")
    monkeypatch.setenv("HAPAX_OOM_AUDIT_HOSTNAME", "hapax-podium")
    monkeypatch.setenv("HAPAX_OOM_AUDIT_SYS_ROOT", str(sys_root))
    monkeypatch.setenv("HAPAX_OOM_AUDIT_USER_UNIT_PATHS", str(unit_paths))
    monkeypatch.setenv("HAPAX_OOM_AUDIT_SYSTEMD_SYSTEM_DIR", str(system_dir))
    monkeypatch.setenv("HAPAX_OOM_AUDIT_SYSTEMD_USER_DIR", str(user_dir))
    monkeypatch.setenv("HAPAX_OOM_AUDIT_DOCKER", str(_fake_docker(tmp_path)))


def test_audit_resets_hostile_path_before_command_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "/tmp/hapax-hostile-path")
    monkeypatch.delenv("HAPAX_SYSTEMCTL", raising=False)

    namespace = runpy.run_path(str(SCRIPT))

    assert os.environ["PATH"] == "/usr/local/sbin:/usr/local/bin:/usr/bin:/bin"
    assert namespace["_systemctl"]() == "/usr/bin/systemctl"


@pytest.mark.parametrize(
    ("selector", "value"),
    [
        ("HAPAX_OOM_AUDIT_TEST_MODE", "1"),
        ("HAPAX_OOM_AUDIT_PROC_ROOT", "/tmp/proc"),
        ("HAPAX_OOM_AUDIT_CGROUP_ROOT", "/tmp/cgroup"),
        ("HAPAX_OOM_AUDIT_SYS_ROOT", "/tmp/sys"),
        ("HAPAX_OOM_AUDIT_MEMTOTAL_KIB", "131007744"),
        ("HAPAX_OOM_AUDIT_HOSTNAME", "hapax-podium"),
        ("HAPAX_OOM_AUDIT_PROFILE_TABLE", "/tmp/profiles.tsv"),
        ("HAPAX_OOM_AUDIT_SEALED_PACKAGE_SOURCE", "1"),
        ("HAPAX_OOM_AUDIT_SYSTEMD_SYSTEM_DIR", "/tmp/systemd-system"),
        ("HAPAX_OOM_AUDIT_SYSTEMD_USER_DIR", "/tmp/systemd-user"),
        ("HAPAX_OOM_AUDIT_USER_UNIT_PATHS", "/tmp/unit-paths"),
        ("HAPAX_OOM_AUDIT_DOCKER", "/bin/true"),
        ("HAPAX_SYSTEMCTL", "/bin/true"),
        ("HAPAX_SYSTEMD_ANALYZE", "/bin/true"),
    ],
)
def test_installed_audit_refuses_every_test_selector(
    tmp_path: Path, selector: str, value: str
) -> None:
    installed = tmp_path / "usr" / "local" / "sbin" / "hapax-oom-policy-audit"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(SCRIPT.read_bytes())
    installed.chmod(0o755)
    env = {key: item for key, item in os.environ.items() if key not in INSTALLED_TEST_SELECTORS}
    env[selector] = value

    result = subprocess.run(
        [str(installed), "--host-policy-lines"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "refused by an installed audit" in result.stdout


def test_symlinked_installed_audit_cannot_look_like_source(tmp_path: Path) -> None:
    installed = tmp_path / "usr" / "local" / "sbin" / "hapax-oom-policy-audit"
    installed.parent.mkdir(parents=True)
    installed.symlink_to(SCRIPT)
    env = {key: item for key, item in os.environ.items() if key not in INSTALLED_TEST_SELECTORS}
    env.update(
        {
            "HAPAX_OOM_AUDIT_TEST_MODE": "1",
            "HAPAX_OOM_AUDIT_HOSTNAME": "hapax-podium",
            "HAPAX_OOM_AUDIT_MEMTOTAL_KIB": "131007744",
        }
    )

    result = subprocess.run(
        [str(installed), "--host-policy-lines"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "refused by an installed audit" in result.stdout


def test_arbitrary_scripts_directory_without_git_marker_is_installed_mode(
    tmp_path: Path,
) -> None:
    copied = tmp_path / "arbitrary" / "scripts" / "hapax-oom-policy-audit"
    copied.parent.mkdir(parents=True)
    copied.write_bytes(SCRIPT.read_bytes())
    copied.chmod(0o755)
    env = {key: item for key, item in os.environ.items() if key not in INSTALLED_TEST_SELECTORS}
    env.update(
        {
            "HAPAX_OOM_AUDIT_TEST_MODE": "1",
            "HAPAX_OOM_AUDIT_HOSTNAME": "hapax-podium",
            "HAPAX_OOM_AUDIT_MEMTOTAL_KIB": "131007744",
        }
    )

    result = subprocess.run(
        [str(copied), "--host-policy-lines"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "refused by an installed audit" in result.stdout


def test_arbitrary_scripts_directory_with_fake_git_marker_is_installed_mode(
    tmp_path: Path,
) -> None:
    copied = tmp_path / "arbitrary" / "scripts" / "hapax-oom-policy-audit"
    copied.parent.mkdir(parents=True)
    copied.write_bytes(SCRIPT.read_bytes())
    copied.chmod(0o755)
    (tmp_path / "arbitrary" / ".git").write_text("not a Git checkout\n", encoding="utf-8")
    env = {key: item for key, item in os.environ.items() if key not in INSTALLED_TEST_SELECTORS}
    env.update(
        {
            "HAPAX_OOM_AUDIT_TEST_MODE": "1",
            "HAPAX_OOM_AUDIT_HOSTNAME": "hapax-podium",
            "HAPAX_OOM_AUDIT_MEMTOTAL_KIB": "131007744",
        }
    )

    result = subprocess.run(
        [str(copied), "--host-policy-lines"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "refused by an installed audit" in result.stdout


def test_source_checkout_probe_failure_is_a_structured_fail_closed_result(tmp_path: Path) -> None:
    copied = tmp_path / "arbitrary" / "scripts" / "hapax-oom-policy-audit"
    copied.parent.mkdir(parents=True)
    copied.write_bytes(SCRIPT.read_bytes())
    copied.chmod(0o755)
    (tmp_path / "arbitrary" / ".git").write_text("not a Git checkout\n", encoding="utf-8")
    env = {key: item for key, item in os.environ.items() if key not in INSTALLED_TEST_SELECTORS}

    result = subprocess.run(
        [str(copied), "--json"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    payload = json.loads(result.stdout)
    check = next(item for item in payload["checks"] if item["name"] == "source_checkout_authority")
    assert result.returncode == 1
    assert check["status"] == "fail"
    assert check["actual"] == "unverified source checkout; installed-mode diagnostics only"
    assert "next action:" in check["detail"]
    assert check["detail"] in result.stderr
    assert "WARNING hapax-oom-policy-audit source checkout verification failed" in result.stderr
    assert "continuing installed-mode diagnostics with a fail-closed result" in result.stderr
    assert "fatal:" in result.stderr


def _root_required_profile_parser_source() -> str:
    source = ROOT_REQUIRED_AUDIT.read_text(encoding="utf-8")
    section = source.split("load_host_profile() {", 1)[1]
    return section.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]


@pytest.mark.parametrize(
    ("row", "hostname", "memtotal_kib", "accepted"),
    (
        (
            "hapax-appendix\t59\t61\tappendix\t46G\t54G\t48G\t56G\t16384",
            "hapax-appendix",
            "63310228",
            True,
        ),
        (
            "hapax-appendix\t59\t61\tappendix\t46G\t54G\t48G\t56G\t4096",
            "hapax-appendix",
            "63310228",
            False,
        ),
        (
            "hapax-appendix\t59\t61\tappendix\t46G\t54G\t48G\t56G\t30720",
            "hapax-appendix",
            "63310228",
            False,
        ),
        (
            "hapax-podium\t123\t125\tpodium\t72G\t88G\t80G\t96G\t32768",
            "hapax-podium",
            "131007744",
            True,
        ),
        (
            "hapax-podium\t123\t125\tpodium\t72G\t88G\t80G\t96G\t65536",
            "hapax-podium",
            "131007744",
            False,
        ),
        (
            "hapax-podium\t123\t125\tpodium\t72G\t88G\t80G\t96G\ttrue",
            "hapax-podium",
            "131007744",
            False,
        ),
    ),
    ids=(
        "appendix-valid",
        "appendix-below-eight-gib",
        "appendix-above-half-floor",
        "podium-valid",
        "podium-above-half-floor",
        "non-integer-zram",
    ),
)
def test_host_profile_parsers_share_zram_admission_corpus(
    tmp_path: Path,
    row: str,
    hostname: str,
    memtotal_kib: str,
    accepted: bool,
) -> None:
    table = tmp_path / "oom-host-profiles.tsv"
    table.write_text(f"{row}\n", encoding="utf-8")
    source_env = {
        **os.environ,
        "HAPAX_OOM_AUDIT_TEST_MODE": "1",
        "HAPAX_OOM_AUDIT_PROFILE_TABLE": str(table),
        "HAPAX_OOM_AUDIT_HOSTNAME": hostname,
        "HAPAX_OOM_AUDIT_MEMTOTAL_KIB": memtotal_kib,
    }
    root_env = {
        **os.environ,
        "HAPAX_ROOT_AUDIT_TEST_MODE": "1",
        "HAPAX_ROOT_AUDIT_HOSTNAME": hostname,
        "HAPAX_ROOT_AUDIT_MEMTOTAL_KIB": memtotal_kib,
    }

    source_result = subprocess.run(
        [str(SCRIPT), "--host-policy-lines"],
        text=True,
        capture_output=True,
        check=False,
        env=source_env,
    )
    root_result = subprocess.run(
        ["/usr/bin/python3", "-", str(table)],
        input=_root_required_profile_parser_source(),
        text=True,
        capture_output=True,
        check=False,
        env=root_env,
    )

    assert (source_result.returncode == 0) is accepted, source_result.stdout
    assert (root_result.returncode == 0) is accepted, root_result.stderr
    assert (source_result.returncode == 0) == (root_result.returncode == 0)
    if accepted:
        source_policy = dict(
            line.split("=", 1) for line in source_result.stdout.splitlines() if "=" in line
        )
        root_policy = dict(line.split("=", 1) for line in root_result.stdout.splitlines())
        assert root_policy == {
            "PROFILE": source_policy["PROFILE"],
            "ZRAM_SIZE_MIB": source_policy["ZRAM_SIZE_MIB"],
        }


def test_unrecognized_executable_cannot_claim_installed_receipt_authority(
    tmp_path: Path,
) -> None:
    namespace = runpy.run_path(str(SCRIPT))
    copied = tmp_path / "opt" / "hapax-oom-policy-audit"
    namespace["SCRIPT_INVOKED_PATH"] = copied
    namespace["SCRIPT_PATH"] = copied

    label = namespace["_policy_authority_label"](namespace["INSTALLED_PROFILE_TABLE"])

    assert label == "non-authoritative-unrecognized-executable"


def test_linked_worktree_git_file_is_a_positive_source_checkout_marker(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=primary, check=True)
    subprocess.run(["git", "config", "user.email", "tests@hapax.local"], cwd=primary, check=True)
    subprocess.run(["git", "config", "user.name", "Hapax Tests"], cwd=primary, check=True)
    copied = primary / "scripts" / "hapax-oom-policy-audit"
    copied.parent.mkdir(parents=True)
    copied.write_bytes(SCRIPT.read_bytes())
    copied.chmod(0o755)
    profile = primary / "config/root-required/oom-host-profiles.tsv"
    profile.parent.mkdir(parents=True)
    profile.write_bytes((REPO_ROOT / "config/root-required/oom-host-profiles.tsv").read_bytes())
    subprocess.run(["git", "add", "."], cwd=primary, check=True)
    subprocess.run(["git", "commit", "-qm", "audit checkout"], cwd=primary, check=True)
    checkout = tmp_path / "checkout"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "audit-linked", str(checkout)],
        cwd=primary,
        check=True,
    )
    copied = checkout / "scripts" / "hapax-oom-policy-audit"
    env = {key: item for key, item in os.environ.items() if key not in INSTALLED_TEST_SELECTORS}
    env.update(
        {
            "HAPAX_OOM_AUDIT_TEST_MODE": "1",
            "HAPAX_OOM_AUDIT_HOSTNAME": "hapax-podium",
            "HAPAX_OOM_AUDIT_MEMTOTAL_KIB": "131007744",
        }
    )

    result = subprocess.run(
        [str(copied), "--host-policy-lines"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stdout
    assert "PROFILE=podium" in result.stdout


def _run_sealed_audit_driver(body: str) -> subprocess.CompletedProcess[str]:
    driver = (
        r"""
import fcntl
import os
import runpy
import sys

def sealed(name, data, mode):
    fd = os.memfd_create(name, os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short memfd write")
        view = view[written:]
    os.fchmod(fd, mode)
    os.lseek(fd, 0, os.SEEK_SET)
    seals = fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE
    fcntl.fcntl(fd, fcntl.F_ADD_SEALS, seals)
    return fd

audit_fd = sealed("hapax-audit", open(sys.argv[1], "rb").read(), 0o755)
profile_fd = sealed("hapax-profile", open(sys.argv[2], "rb").read(), 0o644)
audit_path = f"/proc/{os.getpid()}/fd/{audit_fd}"
profile_path = f"/proc/{os.getpid()}/fd/{profile_fd}"
for name in tuple(os.environ):
    if name.startswith("HAPAX_OOM_AUDIT_") or name in {"HAPAX_SYSTEMCTL", "HAPAX_SYSTEMD_ANALYZE"}:
        os.environ.pop(name, None)
os.environ["HAPAX_OOM_AUDIT_SEALED_PACKAGE_SOURCE"] = "1"
os.environ["HAPAX_OOM_AUDIT_PROFILE_TABLE"] = profile_path
namespace = runpy.run_path(audit_path, run_name="sealed_package_policy")
"""
        + body
    )
    return subprocess.run(
        [
            "/usr/bin/python3",
            "-I",
            "-c",
            driver,
            str(SCRIPT),
            str(REPO_ROOT / "config/root-required/oom-host-profiles.tsv"),
        ],
        text=True,
        capture_output=True,
        check=False,
        env=os.environ.copy(),
    )


def test_sealed_package_profile_derives_without_production_test_selectors() -> None:
    result = _run_sealed_audit_driver(
        r"""
policy = namespace["derive_host_policy"](
    memtotal_kib=60 * 1024**2, hostname="hapax-appendix"
)
print(f"profile={policy.profile}")
print(f"zram={policy.zram_size}")
print(f"path={namespace['_profile_table_path']()}")
print(namespace["_profile_table_context"](namespace["_profile_table_path"]()))
"""
    )

    assert result.returncode == 0, result.stderr
    assert "profile=appendix" in result.stdout
    assert f"zram={16 * 1024**3}" in result.stdout
    assert "path=/proc/" in result.stdout and "/fd/" in result.stdout
    assert "sealed package-source" in result.stdout


def test_sealed_package_source_cannot_run_the_recurring_audit() -> None:
    result = _run_sealed_audit_driver(
        r"""
raise SystemExit(namespace["main"](["--json"]))
"""
    )

    assert result.returncode == 1
    assert "limited to internal host-policy derivation" in result.stdout


def test_installed_audit_ignores_adjacent_unowned_profile_table(tmp_path: Path) -> None:
    installed = tmp_path / "usr" / "local" / "sbin" / "hapax-oom-policy-audit"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(SCRIPT.read_bytes())
    shadow = tmp_path / "usr" / "local" / "config" / "root-required"
    shadow.mkdir(parents=True)
    (shadow / "oom-host-profiles.tsv").write_text("malicious\n", encoding="utf-8")

    namespace = runpy.run_path(str(installed))

    assert namespace["_profile_table_path"]() == Path(
        "/usr/local/share/hapax/root-required/oom-host-profiles.tsv"
    )


def _protected_user_unit_cases(
    *,
    wrong_unit_score: bool = False,
    wrong_unit_memory: bool = False,
    wrong_unit_slice: bool = False,
    wrong_audio_no_new_privileges: bool = False,
    unit_pids: dict[str, int] | None = None,
    unit_cgroups: dict[str, str] | None = None,
    unit_load_states: dict[str, str] | None = None,
) -> str:
    unit_pids = unit_pids or {}
    unit_cgroups = unit_cgroups or {}
    unit_load_states = unit_load_states or {}
    cases = []
    for unit in PROTECTED_USER_UNIT_SCORES:
        load_state = unit_load_states.get(unit, "loaded")
        actual = (
            200
            if load_state == "not-found"
            else 0
            if wrong_unit_score and unit == "studio-compositor.service"
            else 100
        )
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
            f'  *"--user show {unit} --no-pager -p LoadState -p OOMScoreAdjust -p MainPID"*) '
            f"printf 'LoadState={load_state}\\nOOMScoreAdjust={actual}\\nMainPID={pid}\\n"
            f"ControlGroup={cgroup}\\n"
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
    protected_unit_load_states: dict[str, str] | None = None,
    sshd_score: int = 0,
    sshd_policy: str = "continue",
    wrong_recovery_unit_score: bool = False,
    inactive_recovery_unit: str | None = None,
    host_profile: str = "podium",
    memory_dropin_state: str = "clean",
    memory_fragment_scope: str = "",
    memory_fragment_key: str = "MemoryHigh",
    memory_need_reload_scope: str = "",
) -> Path:
    path = tmp_path / "systemctl"
    app_high = 49392123904 if host_profile == "appendix" else 77309411328
    app_max = 57982058496 if host_profile == "appendix" else 94489280512
    uid_high = 51539607552 if host_profile == "appendix" else 85899345920
    uid_max = 60129542144 if host_profile == "appendix" else 103079215104
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
    system_dir = Path(os.environ["HAPAX_OOM_AUDIT_SYSTEMD_SYSTEM_DIR"])
    user_dir = Path(os.environ["HAPAX_OOM_AUDIT_SYSTEMD_USER_DIR"])
    vendor_system_dir = tmp_path / "vendor-systemd-system"
    vendor_user_dir = tmp_path / "vendor-systemd-user"
    vendor_fragments = (
        vendor_system_dir / "user.slice",
        vendor_system_dir / "user@.service",
        vendor_user_dir / "app.slice",
        vendor_user_dir / "session.slice",
    )
    for fragment in vendor_fragments:
        fragment.parent.mkdir(parents=True, exist_ok=True)
        fragment.write_text("[Unit]\nDescription=vendor aggregate\n", encoding="utf-8")
    uid_fragment = ""
    app_fragment = str(vendor_user_dir / "app.slice")
    uid_need_reload = "yes" if memory_need_reload_scope == "system" else "no"
    app_need_reload = "yes" if memory_need_reload_scope == "user" else "no"
    if memory_need_reload_scope not in {"", "system", "user"}:
        raise ValueError(f"unknown memory reload scope: {memory_need_reload_scope}")
    if memory_fragment_scope:
        fragment = tmp_path / "manager-only-root" / f"{memory_fragment_scope}.slice"
        fragment.parent.mkdir(parents=True, exist_ok=True)
        fragment.write_text(f"[Slice]\n{memory_fragment_key}=77309411328\n", encoding="utf-8")
        if memory_fragment_scope == "system":
            uid_fragment = str(fragment)
        elif memory_fragment_scope == "user":
            app_fragment = str(fragment)
        else:
            raise ValueError(f"unknown memory fragment scope: {memory_fragment_scope}")
    app_dropin_paths = str(user_dir / "app.slice.d/oom-containment.conf")
    if memory_dropin_state == "unowned":
        extra = tmp_path / "manager-only-root" / "app.slice.d" / "50-MemoryHigh.conf"
        extra.parent.mkdir(parents=True)
        extra.write_text("[Slice]\nMemoryHigh=77309411328\n", encoding="utf-8")
        app_dropin_paths += f" {extra}"
    elif memory_dropin_state == "missing-canonical":
        app_dropin_paths = ""
    elif memory_dropin_state == "unreadable":
        app_dropin_paths += f" {tmp_path / 'manager-only-root/missing.conf'}"
    app_show = (
        "exit 72"
        if memory_dropin_state == "query-failure"
        else (
            f"printf '{app_values}ControlGroup=/user.slice/user-1000.slice/"
            f"user@1000.service/app.slice\\nNeedDaemonReload={app_need_reload}\\n"
            f"FragmentPath={app_fragment}\\n"
            f"DropInPaths={app_dropin_paths}\\n'"
        )
    )
    path.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
case "$*" in
  *"show system.slice"*) printf '{system_slice_values}NeedDaemonReload=no\nFragmentPath=\nDropInPaths={system_dir / "system.slice.d/oom-containment.conf"}\n' ;;
  *"show user.slice"*) printf '{user_slice_values}ControlGroup=/user.slice\nNeedDaemonReload=no\nFragmentPath={vendor_system_dir / "user.slice"}\nDropInPaths={system_dir / "user.slice.d/oom-containment.conf"}\n' ;;
  *"show user-1000.slice"*) printf '{uid_memory_values}ControlGroup=/user.slice/user-1000.slice\nNeedDaemonReload={uid_need_reload}\nFragmentPath={uid_fragment}\nDropInPaths={system_dir / "user-1000.slice.d/oom-containment.conf"}\n' ;;
  *"show user@1000.service --no-pager -p MemoryHigh"*) printf '{uid_memory_values}' ;;
  *"show user@1000.service --no-pager -p MemoryLow"*) printf '{uid_memory_values}ControlGroup=/user.slice/user-1000.slice/user@1000.service\n' ;;
  *"show user@1000.service"*) printf 'OOMScoreAdjust={user_oom}\\nOOMPolicy={user_oom_policy}\\nNeedDaemonReload=no\\nFragmentPath={vendor_system_dir / "user@.service"}\\nDropInPaths={system_dir / "user@1000.service.d/oom.conf"}\\nMainPID=900\\n' ;;
  *"show sshd.service"*) printf 'OOMScoreAdjust={sshd_score}\\nOOMPolicy={sshd_policy}\\nMainPID=920\\n' ;;
{_recovery_system_unit_cases(wrong_score=wrong_recovery_unit_score, inactive_unit=inactive_recovery_unit)}
  *"show app.slice"*) {app_show} ;;
  *"show session.slice"*) printf '{session_slice_values}ControlGroup=/user.slice/user-1000.slice/user@1000.service/session.slice\nNeedDaemonReload=no\nFragmentPath={vendor_user_dir / "session.slice"}\nDropInPaths={user_dir / "session.slice.d/oom-containment.conf"}\n' ;;
{_protected_user_unit_cases(wrong_unit_score=wrong_unit_score, wrong_unit_memory=wrong_unit_memory, wrong_unit_slice=wrong_unit_slice, wrong_audio_no_new_privileges=wrong_audio_no_new_privileges, unit_pids=protected_unit_pids, unit_cgroups=protected_unit_cgroups, unit_load_states=protected_unit_load_states)}
  *"list-units --type=scope"*) printf 'tmux-spawn-a.scope loaded active running tmux child pane\\n' ;;
  *"show tmux-spawn-a.scope"*) printf '{tmux_values}' ;;
  *) echo "unexpected args: $*" >&2; exit 9 ;;
esac
""",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _fake_docker(tmp_path: Path, *, state: str = "bounded") -> Path:
    path = tmp_path / "docker"
    if state == "query-failure":
        body = "echo 'docker unavailable' >&2\nexit 1\n"
    else:
        judge_memory = 4 * 1024**3
        judge_swap = 6 * 1024**3
        mcp_memory = 512 * 1024**2
        mcp_swap = 768 * 1024**2
        if state == "oom-kill-disabled":
            oom_kill_disable = "true"
        elif state == "oom-kill-invalid":
            oom_kill_disable = "FALSE"
        else:
            oom_kill_disable = "false"
        judge_state = "exited" if state == "judge-exited" else "running"
        if state == "unlimited":
            judge_memory = judge_swap = mcp_memory = mcp_swap = 0
        elif state == "wrong-swap":
            mcp_swap = -1
        disappearance_state = tmp_path / "docker-disappearance-observed"
        if state in {"disappear", "rename", "replace"}:
            if state == "replace":
                second_enumeration = (
                    f"printf '%s\\t%s\\n' {REPLACEMENT_CONTAINER_ID} "
                    "hapax-github-mcp-hapax-123; exit 0"
                )
            elif state == "rename":
                second_enumeration = f"printf '%s\\t%s\\n' {MCP_CONTAINER_ID} renamed-away; exit 0"
            else:
                second_enumeration = "exit 0"
            ps_body = (
                f"if [ -e {disappearance_state!s} ]; then {second_enumeration}; fi\n"
                f"touch {disappearance_state!s}\n"
                f"printf '%s\\t%s\\n' {MCP_CONTAINER_ID} hapax-github-mcp-hapax-123\n"
            )
            inspect_body = "exit 1"
        else:
            ps_body = (
                f"printf '%s\\t%s\\n' {JUDGE_CONTAINER_ID} hapax-local-judge\n"
                f"printf '%s\\t%s\\n' {MCP_CONTAINER_ID} hapax-github-mcp-hapax-123\n"
                f"printf '%s\\t%s\\n' {'c' * 64} unrelated-container\n"
            )
            inspect_body = (
                f'case "$id" in\n'
                f"  {JUDGE_CONTAINER_ID}) printf '%s\\t/%s\\t%s\\t%s\\t%s\\t%s\\n' \"$id\" hapax-local-judge {judge_memory} {judge_swap} null {judge_state} ;;\n"
                f"  {MCP_CONTAINER_ID}) printf '%s\\t/%s\\t%s\\t%s\\t%s\\t%s\\n' \"$id\" hapax-github-mcp-hapax-123 {mcp_memory} {mcp_swap} {oom_kill_disable} running ;;\n"
                "  *) exit 1 ;;\n"
                "esac"
                if state != "inspect-failure-present"
                else "exit 1"
            )
        body = f"""case "$1" in
  ps)
    {ps_body}
    ;;
  inspect)
    id="${{@: -1}}"
    {inspect_body}
    ;;
  *) exit 9 ;;
esac
"""
    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [ -n "${HAPAX_TEST_DOCKER_BOUNDARY_CALLS:-}" ]; then\n'
        "  printf 'host=%s context=%s config=%s cert=%s tls_verify=%s tls=%s api=%s args=%s\\n' \\\n"
        '    "${DOCKER_HOST-unset}" "${DOCKER_CONTEXT-unset}" "${DOCKER_CONFIG-unset}" \\\n'
        '    "${DOCKER_CERT_PATH-unset}" "${DOCKER_TLS_VERIFY-unset}" "${DOCKER_TLS-unset}" \\\n'
        '    "${DOCKER_API_VERSION-unset}" "$*" >> "$HAPAX_TEST_DOCKER_BOUNDARY_CALLS"\n'
        "fi\n"
        'if [ "${1:-}" = --config ]; then\n'
        '  [ "${2:-}" = /nonexistent/hapax-local-docker-config ] || exit 97\n'
        "  shift 2\n"
        "fi\n"
        'if [ "${1:-}" = --host ]; then\n'
        '  [ "${2:-}" = unix:///var/run/docker.sock ] || exit 98\n'
        "  shift 2\n"
        "fi\n"
        f"{body}",
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
    protected_unit_load_states: dict[str, str] | None = None,
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
    host_profile: str = "podium",
    docker_state: str = "bounded",
    zram_size_bytes: int | None = None,
    zram_priority: int = 100,
    zram_compression: str = "lzo-rle lzo lz4 lz4hc [zstd] deflate",
    memory_dropin_state: str = "clean",
    memory_fragment_scope: str = "",
    memory_fragment_key: str = "MemoryHigh",
    memory_need_reload_scope: str = "",
) -> subprocess.CompletedProcess[str]:
    if proc_root is None:
        proc_root = tmp_path / "proc"
        proc_root.mkdir(exist_ok=True)
    if not (proc_root / "900").exists():
        _write_proc(proc_root, 900, name="systemd", uid=1000, oom_score=100)
    if not (proc_root / "920").exists():
        _write_proc(proc_root, 920, name="sshd", uid=0, oom_score=0)
    (proc_root / "swaps").write_text(
        f"Filename Type Size Used Priority\n/dev/zram0 partition 33554428 0 {zram_priority}\n",
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
    lock = tmp_path / "root-state" / ".lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    if not lock.exists():
        lock.write_text("", encoding="utf-8")
        lock.chmod(0o600)
    env = {
        **os.environ,
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
                protected_unit_load_states=protected_unit_load_states,
                sshd_score=sshd_score,
                sshd_policy=sshd_policy,
                wrong_recovery_unit_score=wrong_recovery_unit_score,
                inactive_recovery_unit=inactive_recovery_unit,
                host_profile=host_profile,
                memory_dropin_state=memory_dropin_state,
                memory_fragment_scope=memory_fragment_scope,
                memory_fragment_key=memory_fragment_key,
                memory_need_reload_scope=memory_need_reload_scope,
            )
        ),
        "HAPAX_OOM_AUDIT_PROC_ROOT": str(proc_root),
        "HAPAX_OOM_AUDIT_CGROUP_ROOT": str(cgroup_root),
        "HAPAX_ROOT_REQUIRED_LOCK_FILE": str(lock),
        "HAPAX_OOM_AUDIT_DOCKER": str(_fake_docker(tmp_path, state=docker_state)),
        "HAPAX_OOM_AUDIT_MEMTOTAL_KIB": ("63310228" if host_profile == "appendix" else "131007744"),
        "HAPAX_OOM_AUDIT_HOSTNAME": (
            "hapax-appendix" if host_profile == "appendix" else "hapax-podium"
        ),
    }
    zram_size = zram_size_bytes
    if zram_size is None:
        zram_size = 16 * 1024**3 if host_profile == "appendix" else 32 * 1024**3
    Path(os.environ["HAPAX_OOM_AUDIT_SYS_ROOT"]).joinpath("block", "zram0", "disksize").write_text(
        f"{zram_size}\n", encoding="utf-8"
    )
    Path(os.environ["HAPAX_OOM_AUDIT_SYS_ROOT"]).joinpath(
        "block", "zram0", "comp_algorithm"
    ).write_text(f"{zram_compression}\n", encoding="utf-8")
    return subprocess.run(
        [str(SCRIPT), "--json", "--uid", "1000"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


@pytest.mark.parametrize("host_profile", ["podium", "appendix"])
def test_audit_passes_when_user_manager_is_killable_and_app_slice_bounded(
    tmp_path: Path, host_profile: str
) -> None:
    result = _run(tmp_path, host_profile=host_profile)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["policy_authority"] == "non-authoritative-source-tree"
    statuses = {check["name"]: check["status"] for check in payload["checks"]}
    assert statuses["root_required_package_lock"] == "pass"
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
    assert statuses["zram0_active_swap"] == "pass"
    assert statuses["zram0_compression"] == "pass"
    assert statuses["docker_hapax_local_judge_Memory"] == "pass"
    assert statuses["docker_hapax_local_judge_OomKillDisable"] == "pass"
    assert statuses["docker_hapax_github_mcp_hapax_123_MemorySwap"] == "pass"
    assert statuses["user_unit_pipewire.service_Slice"] == "pass"
    assert statuses["user_unit_pipewire.service_NoNewPrivileges"] == "pass"
    assert statuses["user_unit_studio-compositor.service_Slice"] == "pass"
    assert statuses["app.slice_memory_dropin_ownership"] == "pass"


def test_audit_rejects_value_correct_unowned_manager_dropin_outside_known_roots(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path, memory_dropin_state="unowned")

    assert result.returncode == 1
    checks = {check["name"]: check for check in json.loads(result.stdout)["checks"]}
    check = checks["app.slice_memory_dropin_ownership"]
    assert check["status"] == "gap"
    assert "manager-only-root" in check["actual"]
    assert "authoritative DropInPaths" in check["detail"]


@pytest.mark.parametrize("scope", ["system", "user"])
@pytest.mark.parametrize(
    "key", ["MemoryHigh", "MemoryMax", "MemorySwapMax", "MemoryLow", "MemoryMin"]
)
def test_audit_rejects_manager_reported_fragment_governed_assignment(
    tmp_path: Path, scope: str, key: str
) -> None:
    result = _run(
        tmp_path,
        memory_fragment_scope=scope,
        memory_fragment_key=key,
    )

    assert result.returncode == 1
    checks = {check["name"]: check for check in json.loads(result.stdout)["checks"]}
    check_name = (
        "user_1000.slice_memory_dropin_ownership"
        if scope == "system"
        else "app.slice_memory_dropin_ownership"
    )
    check = checks[check_name]
    assert check["status"] == "gap"
    assert "manager-only-root" in check["actual"]
    assert "authoritative FragmentPath" in check["detail"]


@pytest.mark.parametrize("scope", ["system", "user"])
def test_audit_rejects_stale_loaded_memory_manager_state(tmp_path: Path, scope: str) -> None:
    result = _run(tmp_path, memory_need_reload_scope=scope)

    assert result.returncode == 1
    checks = {check["name"]: check for check in json.loads(result.stdout)["checks"]}
    check_name = (
        "user_1000.slice_memory_dropin_ownership"
        if scope == "system"
        else "app.slice_memory_dropin_ownership"
    )
    check = checks[check_name]
    assert check["status"] == "gap"
    assert check["target"] == "NeedDaemonReload=no"
    assert check["actual"] == "yes"
    assert "manager state is stale" in check["detail"]


@pytest.mark.parametrize(
    ("state", "status", "detail"),
    [
        ("missing-canonical", "gap", "exactly one receipt-owned"),
        ("unreadable", "error", "cannot inspect authoritative DropInPath"),
        ("query-failure", "error", "cannot query authoritative"),
    ],
)
def test_audit_fails_closed_when_dropin_ownership_is_unprovable(
    tmp_path: Path, state: str, status: str, detail: str
) -> None:
    result = _run(tmp_path, memory_dropin_state=state)

    assert result.returncode == 1
    checks = {check["name"]: check for check in json.loads(result.stdout)["checks"]}
    check = checks["app.slice_memory_dropin_ownership"]
    assert check["status"] == status
    assert detail in check["detail"]


def test_host_policy_lines_derive_both_known_profiles(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "HAPAX_OOM_AUDIT_TEST_MODE": "1",
        "HAPAX_OOM_AUDIT_MEMTOTAL_KIB": "63310228",
        "HAPAX_OOM_AUDIT_HOSTNAME": "hapax-appendix",
    }
    appendix = subprocess.run(
        [str(SCRIPT), "--host-policy-lines"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert appendix.returncode == 0, appendix.stderr
    assert "HOSTNAME=hapax-appendix" in appendix.stdout
    assert "PROFILE=appendix" in appendix.stdout
    assert "APP_MEMORY_HIGH=46G" in appendix.stdout
    assert "APP_MEMORY_MAX=54G" in appendix.stdout
    assert "UID_MEMORY_HIGH=48G" in appendix.stdout
    assert "UID_MEMORY_MAX=56G" in appendix.stdout
    assert "ZRAM_SIZE_MIB=16384" in appendix.stdout
    assert "POLICY_AUTHORITY=non-authoritative-source-tree" in appendix.stdout

    env["HAPAX_OOM_AUDIT_MEMTOTAL_KIB"] = "131007744"
    env["HAPAX_OOM_AUDIT_HOSTNAME"] = "hapax-podium"
    podium = subprocess.run(
        [str(SCRIPT), "--host-policy-lines"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert podium.returncode == 0, podium.stderr
    assert "HOSTNAME=hapax-podium" in podium.stdout
    assert "PROFILE=podium" in podium.stdout
    assert "APP_MEMORY_HIGH=72G" in podium.stdout
    assert "APP_MEMORY_MAX=88G" in podium.stdout
    assert "UID_MEMORY_HIGH=80G" in podium.stdout
    assert "UID_MEMORY_MAX=96G" in podium.stdout
    assert "ZRAM_SIZE_MIB=32768" in podium.stdout
    assert "POLICY_AUTHORITY=non-authoritative-source-tree" in podium.stdout


@pytest.mark.parametrize(
    ("hostname", "floor_gib"),
    [
        ("hapax-appendix", 59),
        ("hapax-appendix", 61),
        ("hapax-podium", 123),
        ("hapax-podium", 125),
    ],
)
def test_host_policy_accepts_a_reviewed_physical_memory_interval_edge(
    hostname: str, floor_gib: int
) -> None:
    result = subprocess.run(
        [str(SCRIPT), "--host-policy-lines"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_AUDIT_TEST_MODE": "1",
            "HAPAX_OOM_AUDIT_MEMTOTAL_KIB": str(floor_gib * 1024**2),
            "HAPAX_OOM_AUDIT_HOSTNAME": hostname,
        },
    )
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    ("hostname", "floor_gib"),
    [
        ("hapax-appendix", 58),
        ("hapax-appendix", 62),
        ("hapax-podium", 122),
        ("hapax-podium", 126),
    ],
)
def test_host_policy_refuses_an_unreviewed_physical_memory_floor(
    hostname: str, floor_gib: int
) -> None:
    result = subprocess.run(
        [str(SCRIPT), "--host-policy-lines"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_AUDIT_TEST_MODE": "1",
            "HAPAX_OOM_AUDIT_MEMTOTAL_KIB": str(floor_gib * 1024**2),
            "HAPAX_OOM_AUDIT_HOSTNAME": hostname,
        },
    )
    assert result.returncode == 1
    assert "unlisted MemTotal floor" in result.stdout
    assert "source-tree host profile table" in result.stdout
    assert str(REPO_ROOT / "config/root-required/oom-host-profiles.tsv") in result.stdout


@pytest.mark.parametrize(
    "rows",
    [
        "hapax-appendix\t61\t59\tappendix\t46G\t54G\t48G\t56G\t16384\n",
        (
            "hapax-appendix\t59\t61\tappendix\t46G\t54G\t48G\t56G\t16384\n"
            "hapax-appendix\t60\t62\tappendix\t46G\t54G\t48G\t56G\t16384\n"
        ),
    ],
)
def test_host_policy_refuses_invalid_or_overlapping_memory_intervals(
    tmp_path: Path, rows: str
) -> None:
    table = tmp_path / "oom-host-profiles.tsv"
    table.write_text(rows, encoding="utf-8")
    result = subprocess.run(
        [str(SCRIPT), "--host-policy-lines"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_AUDIT_TEST_MODE": "1",
            "HAPAX_OOM_AUDIT_PROFILE_TABLE": str(table),
            "HAPAX_OOM_AUDIT_MEMTOTAL_KIB": str(60 * 1024**2),
            "HAPAX_OOM_AUDIT_HOSTNAME": "hapax-appendix",
        },
    )
    assert result.returncode == 1
    assert "MemTotal GiB interval" in result.stdout
    assert "test-override host profile table" in result.stdout


@pytest.mark.parametrize(
    ("hostname", "floor_gib", "row"),
    [
        (
            "hapax-appendix",
            60,
            "hapax-appendix\t59\t61\tpodium\t46G\t54G\t48G\t56G\t16384\n",
        ),
        (
            "hapax-podium",
            124,
            "hapax-podium\t123\t125\tappendix\t72G\t88G\t80G\t96G\t32768\n",
        ),
    ],
)
def test_host_policy_refuses_swapped_hostname_profile_semantics(
    tmp_path: Path, hostname: str, floor_gib: int, row: str
) -> None:
    table = tmp_path / "oom-host-profiles.tsv"
    table.write_text(row, encoding="utf-8")
    result = subprocess.run(
        [str(SCRIPT), "--host-policy-lines"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_AUDIT_TEST_MODE": "1",
            "HAPAX_OOM_AUDIT_PROFILE_TABLE": str(table),
            "HAPAX_OOM_AUDIT_MEMTOTAL_KIB": str(floor_gib * 1024**2),
            "HAPAX_OOM_AUDIT_HOSTNAME": hostname,
        },
    )

    assert result.returncode == 1
    assert "hostname/profile mismatch" in result.stdout
    assert f"{hostname} requires profile {hostname.removeprefix('hapax-')}" in result.stdout


def test_host_policy_requires_ceiling_below_the_interval_minimum(tmp_path: Path) -> None:
    table = tmp_path / "oom-host-profiles.tsv"
    table.write_text(
        "hapax-appendix\t59\t61\tappendix\t46G\t54G\t58G\t60G\t16384\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(SCRIPT), "--host-policy-lines"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_AUDIT_TEST_MODE": "1",
            "HAPAX_OOM_AUDIT_PROFILE_TABLE": str(table),
            "HAPAX_OOM_AUDIT_MEMTOTAL_KIB": str(61 * 1024**2),
            "HAPAX_OOM_AUDIT_HOSTNAME": "hapax-appendix",
        },
    )
    assert result.returncode == 1
    assert "below the reviewed 59 GiB interval floor" in result.stdout


@pytest.mark.parametrize("zram_mib", [4096, 30720])
def test_host_policy_bounds_zram_against_swap_and_physical_floor(
    tmp_path: Path, zram_mib: int
) -> None:
    table = tmp_path / "oom-host-profiles.tsv"
    table.write_text(
        f"hapax-appendix\t59\t61\tappendix\t46G\t54G\t48G\t56G\t{zram_mib}\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(SCRIPT), "--host-policy-lines"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_AUDIT_TEST_MODE": "1",
            "HAPAX_OOM_AUDIT_PROFILE_TABLE": str(table),
            "HAPAX_OOM_AUDIT_MEMTOTAL_KIB": str(60 * 1024**2),
            "HAPAX_OOM_AUDIT_HOSTNAME": "hapax-appendix",
        },
    )

    assert result.returncode == 1
    assert "8 GiB slice swap ceiling" in result.stdout
    assert "half the physical floor as recovery headroom" in result.stdout


def test_shipped_host_profile_rows_satisfy_the_declared_zram_invariant() -> None:
    table = REPO_ROOT / "config" / "root-required" / "oom-host-profiles.tsv"
    table_text = table.read_text(encoding="utf-8")
    rows = [
        row
        for row in csv.reader(table_text.splitlines(), delimiter="\t")
        if row and not row[0].lstrip().startswith("#")
    ]

    assert "-k shipped_host_profile_rows_satisfy_the_declared_zram_invariant" in table_text
    assert "exact zram contract: appendix=16384 MiB, podium=32768 MiB" in table_text
    assert "appendix=config/root-required/oom-host-policy/appendix/" in table_text
    assert "podium=systemd/units/app.slice.d/oom-containment.conf" in table_text
    assert {row[0] for row in rows} == {"hapax-appendix", "hapax-podium"}
    for row in rows:
        assert len(row) == 9
        min_memtotal_gib = int(row[1])
        zram_mib = int(row[8])
        assert zram_mib >= 8192
        assert zram_mib * 2 <= min_memtotal_gib * 1024


def test_host_policy_validates_unselected_rows_against_their_interval_minimum(
    tmp_path: Path,
) -> None:
    table = tmp_path / "oom-host-profiles.tsv"
    table.write_text(
        "hapax-appendix\t59\t61\tappendix\t46G\t54G\t48G\t56G\t16384\n"
        "hapax-podium\t123\t125\tpodium\t72G\t88G\t120G\t124G\t32768\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(SCRIPT), "--host-policy-lines"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_AUDIT_TEST_MODE": "1",
            "HAPAX_OOM_AUDIT_PROFILE_TABLE": str(table),
            "HAPAX_OOM_AUDIT_MEMTOTAL_KIB": str(60 * 1024**2),
            "HAPAX_OOM_AUDIT_HOSTNAME": "hapax-appendix",
        },
    )
    assert result.returncode == 1
    assert "below the reviewed 123 GiB interval floor" in result.stdout


def test_host_policy_refuses_cross_host_memory_profile() -> None:
    result = subprocess.run(
        [str(SCRIPT), "--host-policy-lines"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_AUDIT_TEST_MODE": "1",
            "HAPAX_OOM_AUDIT_MEMTOTAL_KIB": "63310228",
            "HAPAX_OOM_AUDIT_HOSTNAME": "hapax-podium",
        },
    )
    assert result.returncode == 1
    assert "host/profile memory mismatch" in result.stdout
    assert "source-tree host profile table" in result.stdout


def test_host_policy_refuses_a_hostname_suffix() -> None:
    result = subprocess.run(
        [str(SCRIPT), "--host-policy-lines"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_AUDIT_TEST_MODE": "1",
            "HAPAX_OOM_AUDIT_MEMTOTAL_KIB": "63310228",
            "HAPAX_OOM_AUDIT_HOSTNAME": "hapax-appendix.staging",
        },
    )

    assert result.returncode == 1
    assert "unsupported host identity" in result.stdout
    assert "hapax-appendix.staging" in result.stdout


def test_appendix_skips_only_its_explicitly_optional_absent_units(tmp_path: Path) -> None:
    absent = {
        "hapax-daimonion.service": "not-found",
        "studio-compositor.service": "not-found",
        "hapax-imagination.service": "not-found",
    }
    result = _run(
        tmp_path,
        host_profile="appendix",
        protected_unit_load_states=absent,
    )
    assert result.returncode == 0, result.stderr
    checks = {check["name"]: check for check in json.loads(result.stdout)["checks"]}
    for unit in absent:
        load_check = checks[f"user_unit_{unit}_LoadState"]
        assert load_check["status"] == "pass"
        assert load_check["target"] == "host-optional-absent"
        assert f"user_unit_{unit}_OOMScoreAdjust" not in checks


def test_podium_treats_the_same_absent_protected_unit_as_drift(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        protected_unit_load_states={"hapax-daimonion.service": "not-found"},
    )
    assert result.returncode == 1
    checks = {check["name"]: check for check in json.loads(result.stdout)["checks"]}
    load_check = checks["user_unit_hapax-daimonion.service_LoadState"]
    assert load_check["status"] == "gap"
    assert load_check["target"] == "loaded"
    assert "user_unit_hapax-daimonion.service_OOMScoreAdjust" not in checks


@pytest.mark.parametrize("link_kind", ["regular", "dangling-symlink"])
def test_appendix_optional_absence_fails_when_a_unit_file_exists(
    tmp_path: Path, link_kind: str
) -> None:
    unit_dir = Path(os.environ["HAPAX_OOM_AUDIT_USER_UNIT_PATHS"])
    unit_file = unit_dir / "studio-compositor.service"
    if link_kind == "regular":
        unit_file.write_text("[Service]\nExecStart=/bin/true\n", encoding="utf-8")
    else:
        unit_file.symlink_to(unit_dir / "missing-target.service")
    result = _run(
        tmp_path,
        host_profile="appendix",
        protected_unit_load_states={
            "hapax-daimonion.service": "not-found",
            "studio-compositor.service": "not-found",
            "hapax-imagination.service": "not-found",
        },
    )
    assert result.returncode == 1
    checks = {check["name"]: check for check in json.loads(result.stdout)["checks"]}
    check = checks["user_unit_studio-compositor.service_LoadState"]
    assert check["status"] == "gap"
    assert check["actual"] == str(unit_file)


def test_appendix_optional_absence_fails_without_authoritative_search_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    analyzer = tmp_path / "systemd-analyze"
    analyzer.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    analyzer.chmod(0o755)
    monkeypatch.delenv("HAPAX_OOM_AUDIT_USER_UNIT_PATHS")
    monkeypatch.setenv("HAPAX_SYSTEMD_ANALYZE", str(analyzer))
    result = _run(
        tmp_path,
        host_profile="appendix",
        protected_unit_load_states={
            "hapax-daimonion.service": "not-found",
            "studio-compositor.service": "not-found",
            "hapax-imagination.service": "not-found",
        },
    )
    assert result.returncode == 1
    checks = {check["name"]: check for check in json.loads(result.stdout)["checks"]}
    assert checks["user_unit_studio-compositor.service_LoadState"]["status"] == "error"
    assert (
        "cannot prove absence" in checks["user_unit_studio-compositor.service_LoadState"]["detail"]
    )


@pytest.mark.parametrize(
    "docker_state", ["unlimited", "wrong-swap", "oom-kill-disabled", "oom-kill-invalid"]
)
def test_audit_fails_for_unbounded_or_wrong_docker_limits(
    tmp_path: Path, docker_state: str
) -> None:
    result = _run(tmp_path, docker_state=docker_state)
    assert result.returncode == 1
    checks = {check["name"]: check for check in json.loads(result.stdout)["checks"]}
    check = checks["docker_hapax_github_mcp_hapax_123_OomKillDisable"]
    if docker_state == "oom-kill-invalid":
        assert check["status"] == "error"
        assert check["actual"] == "FALSE"
        assert "unparseable Docker OOM-kill-disable state" in check["detail"]
    else:
        assert any(
            item["status"] == "gap" and name.startswith("docker_") for name, item in checks.items()
        )
    if docker_state == "unlimited":
        assert checks["docker_hapax_local_judge_Memory"]["status"] == "gap"
        assert checks["docker_hapax_local_judge_MemorySwap"]["status"] == "gap"
    if docker_state == "oom-kill-disabled":
        assert check["target"] == "false"
        assert check["actual"] == "true"
        assert "recreate the container" in check["detail"]


def test_audit_fails_when_docker_cannot_be_queried(tmp_path: Path) -> None:
    result = _run(tmp_path, docker_state="query-failure")
    assert result.returncode == 1
    check = next(
        check
        for check in json.loads(result.stdout)["checks"]
        if check["name"] == "docker_container_limits"
    )
    assert check["status"] == "error"


def test_audit_pins_local_docker_daemon_against_hostile_selectors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    boundary_calls = tmp_path / "docker-boundary-calls"
    monkeypatch.setenv("HAPAX_TEST_DOCKER_BOUNDARY_CALLS", str(boundary_calls))
    monkeypatch.setenv("DOCKER_HOST", "tcp://attacker.invalid:2376")
    monkeypatch.setenv("DOCKER_CONTEXT", "remote-production")
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / "hostile-docker-config"))
    monkeypatch.setenv("DOCKER_CERT_PATH", str(tmp_path / "hostile-certs"))
    monkeypatch.setenv("DOCKER_TLS_VERIFY", "1")
    monkeypatch.setenv("DOCKER_TLS", "1")
    monkeypatch.setenv("DOCKER_API_VERSION", "1.24")

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    calls = boundary_calls.read_text(encoding="utf-8")
    assert calls
    for call in calls.splitlines():
        assert "host=unix:///var/run/docker.sock" in call
        assert "context=unset" in call
        assert "config=/nonexistent/hapax-local-docker-config" in call
        assert "cert=unset" in call
        assert "tls_verify=unset" in call
        assert "tls=unset" in call
        assert "api=unset" in call
        assert "--config /nonexistent/hapax-local-docker-config" in call
        assert "--host unix:///var/run/docker.sock" in call


def test_audit_rejects_exited_same_name_local_judge_container(tmp_path: Path) -> None:
    result = _run(tmp_path, docker_state="judge-exited")

    assert result.returncode == 1
    checks = {check["name"]: check for check in json.loads(result.stdout)["checks"]}
    check = checks["docker_hapax_local_judge_State"]
    assert check["status"] == "gap"
    assert check["target"] == "running"
    assert check["actual"] == "exited"
    assert JUDGE_CONTAINER_ID in check["detail"]
    assert "without -f" in check["detail"]


def test_audit_accepts_ephemeral_docker_disappearance_only_after_id_reenumeration(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path, docker_state="disappear")
    assert result.returncode == 0, result.stderr
    check = next(
        check for check in json.loads(result.stdout)["checks"] if check["name"].endswith("_inspect")
    )
    assert check["status"] == "pass"
    assert MCP_CONTAINER_ID in check["actual"]


def test_audit_refuses_inspect_error_while_same_docker_id_remains(tmp_path: Path) -> None:
    result = _run(tmp_path, docker_state="inspect-failure-present")
    assert result.returncode == 1
    check = next(
        check for check in json.loads(result.stdout)["checks"] if check["name"].endswith("_inspect")
    )
    assert check["status"] == "error"
    assert "Docker inspect failed" in check["detail"]


def test_audit_refuses_same_name_docker_replacement_after_original_id_disappears(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path, docker_state="replace")
    assert result.returncode == 1
    check = next(
        check for check in json.loads(result.stdout)["checks"] if check["name"].endswith("_inspect")
    )
    assert check["status"] == "error"
    assert "same-name target remains" in check["detail"]


def test_audit_refuses_same_id_docker_rename_after_inspect_failure(tmp_path: Path) -> None:
    result = _run(tmp_path, docker_state="rename")

    assert result.returncode == 1
    checks = {check["name"]: check for check in json.loads(result.stdout)["checks"]}
    check = checks["docker_hapax_github_mcp_hapax_123_inspect"]
    assert check["status"] == "error"
    assert "original identity or same-name target remains" in check["detail"]


@pytest.mark.parametrize(
    ("kwargs", "check_name"),
    [
        ({"zram_size_bytes": 8 * 1024**3}, "zram0_disksize"),
        ({"zram_priority": 5}, "zram0_active_swap"),
        ({"zram_compression": "[lzo] lz4 zstd"}, "zram0_compression"),
    ],
)
def test_audit_rejects_zram_runtime_drift(
    tmp_path: Path, kwargs: dict[str, object], check_name: str
) -> None:
    result = _run(tmp_path, **kwargs)
    assert result.returncode == 1
    checks = {check["name"]: check for check in json.loads(result.stdout)["checks"]}
    assert checks[check_name]["status"] == "gap"


def test_audit_uses_existing_lock_without_mutating_it(tmp_path: Path) -> None:
    lock = tmp_path / "root-state" / ".lock"
    result = _run(tmp_path)
    before = lock.stat()

    result = _run(tmp_path)

    after = lock.stat()
    assert result.returncode == 0, result.stderr
    assert after.st_mode == before.st_mode
    assert after.st_mtime_ns == before.st_mtime_ns


def test_audit_waits_for_exclusive_package_install_lock(tmp_path: Path) -> None:
    lock = tmp_path / "root-state" / ".lock"
    lock.parent.mkdir(parents=True)
    calls = tmp_path / "systemctl-calls"
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {calls!s}\nexit 1\n", encoding="utf-8"
    )
    fake_systemctl.chmod(0o755)

    with lock.open("w", encoding="utf-8") as lock_file:
        lock.chmod(0o600)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        proc = subprocess.Popen(
            [str(SCRIPT), "--json", "--uid", "1000"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                **os.environ,
                "HAPAX_SYSTEMCTL": str(fake_systemctl),
                "HAPAX_ROOT_REQUIRED_LOCK_FILE": str(lock),
            },
        )
        time.sleep(0.25)
        assert proc.poll() is None
        assert not calls.exists()
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    stdout, stderr = proc.communicate(timeout=5)
    assert proc.returncode == 1, stderr
    assert calls.is_file()
    payload = json.loads(stdout)
    lock_check = next(
        check for check in payload["checks"] if check["name"] == "root_required_package_lock"
    )
    assert lock_check["status"] == "pass"


@pytest.mark.parametrize("lock_kind", ["symlink", "hardlink"])
def test_audit_refuses_unsafe_package_lock_without_system_reads(
    tmp_path: Path, lock_kind: str
) -> None:
    state_root = tmp_path / "root-state"
    state_root.mkdir()
    protected = tmp_path / "protected"
    protected.write_text("sentinel\n", encoding="utf-8")
    lock = state_root / ".lock"
    if lock_kind == "symlink":
        lock.symlink_to(protected)
    else:
        os.link(protected, lock)
    calls = tmp_path / "systemctl-calls"
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {calls!s}\nexit 1\n", encoding="utf-8"
    )
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(SCRIPT), "--json", "--uid", "1000"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_ROOT_REQUIRED_LOCK_FILE": str(lock),
        },
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert len(payload["checks"]) == 1
    check = payload["checks"][0]
    assert check["actual"] == str(lock)
    assert check["name"] == "root_required_package_lock"
    assert check["status"] == "error"
    assert check["target"] == "shared package lock held during readback"
    assert "package lock" in check["detail"]
    assert not calls.exists()
    assert protected.read_text(encoding="utf-8") == "sentinel\n"


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
    pipewire_cgroup = "/user.slice/user-1000.slice/user@1000.service/app.slice/pipewire.service"
    _write_proc_cgroup(proc_root, 910, pipewire_cgroup)
    _write_proc_cgroup(proc_root, 916, pipewire_cgroup)

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
    _write_proc(proc_root, 914, name="python", uid=1000, oom_score=-800)
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
    assert "914:python=-800" in residual["actual"]


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
