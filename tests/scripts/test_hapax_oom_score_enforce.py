"""Executable coverage for the privileged OOM enforcer and startup trigger."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENFORCER = REPO_ROOT / "scripts" / "hapax-oom-score-enforce"
TRIGGER = REPO_ROOT / "scripts" / "hapax-oom-score-trigger"
MANAGER_CGROUP = "/user.slice/user-1000.slice/user@1000.service"
TEST_SELECTORS = {
    "HAPAX_OOM_ENFORCE_TEST_MODE",
    "HAPAX_OOM_TARGET_USER",
    "HAPAX_OOM_TARGET_UID",
    "HAPAX_OOM_SYSTEMCTL",
    "HAPAX_OOM_PROC_ROOT",
    "HAPAX_OOM_CGROUP_ROOT",
}


def _write(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)


def _manager_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    proc_root = tmp_path / "proc"
    cgroup_root = tmp_path / "cgroup"
    manager_dir = cgroup_root / MANAGER_CGROUP.removeprefix("/")
    _write(manager_dir / "cgroup.procs", "1000\n")
    _write(proc_root / "1000" / "oom_score_adj", "0\n")
    _write(proc_root / "1000" / "cgroup", f"0::{MANAGER_CGROUP}\n")
    return proc_root, cgroup_root, manager_dir


def _add_unit(
    proc_root: Path,
    cgroup_root: Path,
    manager_dir: Path,
    unit: str,
    placement: str,
    pids: tuple[int, ...] = (4242, 4343),
) -> Path:
    unit_dir = manager_dir / placement / unit if placement else manager_dir / unit
    _write(unit_dir / "cgroup.procs", "".join(f"{pid}\n" for pid in pids))
    unit_cgroup = "/" + unit_dir.relative_to(cgroup_root).as_posix()
    for pid in pids:
        _write(proc_root / str(pid) / "oom_score_adj", "200\n")
        _write(proc_root / str(pid) / "cgroup", f"0::{unit_cgroup}\n")
    return unit_dir


def _systemctl_stub(
    tmp_path: Path,
    *,
    active_state: str = "active",
    active_query_rc: int = 0,
    manager_cgroup: str = MANAGER_CGROUP,
) -> tuple[Path, Path]:
    calls = tmp_path / "systemctl.calls"
    stub = tmp_path / "bin" / "systemctl"
    _write(
        stub,
        f"""#!/usr/bin/bash
printf '%s\n' "$*" >> {calls}
case "$*" in
  *--user*) echo 'systemctl --user is forbidden' >&2; exit 99 ;;
  'show user@1000.service -p ActiveState --value')
    printf '%s\n' '{active_state}'
    exit {active_query_rc}
    ;;
  'show user@1000.service -p MainPID --value') printf '%s\n' 1000 ;;
  'show user@1000.service -p ControlGroup --value') printf '%s\n' '{manager_cgroup}' ;;
  *) echo "unexpected systemctl call: $*" >&2; exit 98 ;;
esac
""",
        stat.S_IRWXU,
    )
    return stub, calls


def _test_env(
    tmp_path: Path, proc_root: Path, cgroup_root: Path, systemctl: Path
) -> dict[str, str]:
    env = os.environ.copy()
    for key in TEST_SELECTORS | {"SUDO_USER", "ENV", "BASH_ENV", "CDPATH"}:
        env.pop(key, None)
    env.update(
        {
            "HAPAX_OOM_ENFORCE_TEST_MODE": "1",
            "HAPAX_OOM_TARGET_USER": "hapax",
            "HAPAX_OOM_TARGET_UID": "1000",
            "HAPAX_OOM_SYSTEMCTL": str(systemctl),
            "HAPAX_OOM_PROC_ROOT": str(proc_root),
            "HAPAX_OOM_CGROUP_ROOT": str(cgroup_root),
            "PATH": f"{tmp_path / 'bin'}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        }
    )
    _write(
        tmp_path / "bin" / "runuser",
        "#!/usr/bin/bash\necho 'runuser is forbidden' >&2\nexit 99\n",
        stat.S_IRWXU,
    )
    return env


def _run_enforcer(
    tmp_path: Path,
    proc_root: Path,
    cgroup_root: Path,
    *args: str,
    active_state: str = "active",
    active_query_rc: int = 0,
    manager_cgroup: str = MANAGER_CGROUP,
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    systemctl, calls = _systemctl_stub(
        tmp_path,
        active_state=active_state,
        active_query_rc=active_query_rc,
        manager_cgroup=manager_cgroup,
    )
    env = _test_env(tmp_path, proc_root, cgroup_root, systemctl)
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [str(ENFORCER), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return result, calls


@pytest.mark.skipif(os.geteuid() == 0, reason="test selectors intentionally refuse root")
@pytest.mark.parametrize(
    ("unit", "placement", "score"),
    [
        ("pipewire.service", "session.slice", "-900"),
        ("hapax-daimonion.service", "app.slice", "-500"),
        ("studio-compositor.service", "", "-800"),
    ],
)
def test_apply_unit_uses_canonical_placement_and_writes_every_pid(
    tmp_path: Path, unit: str, placement: str, score: str
) -> None:
    proc_root, cgroup_root, manager_dir = _manager_tree(tmp_path)
    _add_unit(proc_root, cgroup_root, manager_dir, unit, placement)

    result, calls = _run_enforcer(tmp_path, proc_root, cgroup_root, "--apply-unit", unit)

    assert result.returncode == 0, result.stderr
    assert "runuser is forbidden" not in result.stderr
    assert all("--user" not in call for call in calls.read_text().splitlines())
    for pid in (4242, 4343):
        assert (proc_root / str(pid) / "oom_score_adj").read_text().strip() == score


@pytest.mark.skipif(os.geteuid() == 0, reason="test selectors intentionally refuse root")
def test_apply_unit_refuses_wrong_slice_and_nested_name_impostors(tmp_path: Path) -> None:
    proc_root, cgroup_root, manager_dir = _manager_tree(tmp_path)
    wrong_slice = _add_unit(
        proc_root, cgroup_root, manager_dir, "pipewire.service", "app.slice", (4242,)
    )
    nested = manager_dir / "session.slice" / "attacker.scope" / "pipewire.service"
    _write(nested / "cgroup.procs", "4343\n")
    nested_cgroup = "/" + nested.relative_to(cgroup_root).as_posix()
    _write(proc_root / "4343" / "oom_score_adj", "200\n")
    _write(proc_root / "4343" / "cgroup", f"0::{nested_cgroup}\n")

    result, _ = _run_enforcer(tmp_path, proc_root, cgroup_root, "--apply-unit", "pipewire.service")

    assert result.returncode == 1
    assert "no canonical cgroup" in result.stderr
    assert wrong_slice.is_dir()
    assert (proc_root / "4242" / "oom_score_adj").read_text().strip() == "200"
    assert (proc_root / "4343" / "oom_score_adj").read_text().strip() == "200"


@pytest.mark.skipif(os.geteuid() == 0, reason="test selectors intentionally refuse root")
def test_apply_unit_rechecks_proc_cgroup_before_writing(tmp_path: Path) -> None:
    proc_root, cgroup_root, manager_dir = _manager_tree(tmp_path)
    _add_unit(proc_root, cgroup_root, manager_dir, "pipewire.service", "session.slice", (4242,))
    _write(proc_root / "4242" / "cgroup", "0::/attacker.scope/pipewire.service\n")

    result, _ = _run_enforcer(tmp_path, proc_root, cgroup_root, "--apply-unit", "pipewire.service")

    assert result.returncode == 1
    assert "no live PID in its canonical cgroup" in result.stderr
    assert (proc_root / "4242" / "oom_score_adj").read_text().strip() == "200"


@pytest.mark.skipif(os.geteuid() == 0, reason="test selectors intentionally refuse root")
def test_periodic_apply_scores_manager_and_skips_absent_host_units(tmp_path: Path) -> None:
    proc_root, cgroup_root, manager_dir = _manager_tree(tmp_path)
    _add_unit(proc_root, cgroup_root, manager_dir, "pipewire.service", "session.slice", (4242,))

    result, _ = _run_enforcer(tmp_path, proc_root, cgroup_root, "--apply")

    assert result.returncode == 0, result.stderr
    assert "not present on this host; skipping" in result.stdout
    assert (proc_root / "1000" / "oom_score_adj").read_text().strip() == "100"
    assert (proc_root / "4242" / "oom_score_adj").read_text().strip() == "-900"


@pytest.mark.skipif(os.geteuid() == 0, reason="test selectors intentionally refuse root")
def test_inactive_manager_exits_without_writes(tmp_path: Path) -> None:
    proc_root, cgroup_root, manager_dir = _manager_tree(tmp_path)
    _add_unit(proc_root, cgroup_root, manager_dir, "pipewire.service", "session.slice", (4242,))

    result, _ = _run_enforcer(tmp_path, proc_root, cgroup_root, "--apply", active_state="inactive")

    assert result.returncode == 0
    assert (proc_root / "1000" / "oom_score_adj").read_text().strip() == "0"
    assert (proc_root / "4242" / "oom_score_adj").read_text().strip() == "200"


@pytest.mark.skipif(os.geteuid() == 0, reason="test selectors intentionally refuse root")
@pytest.mark.parametrize(("active_state", "active_query_rc"), [("failed", 0), ("", 9)])
def test_manager_failure_or_query_error_is_not_treated_as_inactive(
    tmp_path: Path, active_state: str, active_query_rc: int
) -> None:
    proc_root, cgroup_root, _ = _manager_tree(tmp_path)

    result, _ = _run_enforcer(
        tmp_path,
        proc_root,
        cgroup_root,
        "--apply",
        active_state=active_state,
        active_query_rc=active_query_rc,
    )

    assert result.returncode == 1
    assert (proc_root / "1000" / "oom_score_adj").read_text().strip() == "0"


@pytest.mark.skipif(os.geteuid() == 0, reason="test selectors intentionally refuse root")
def test_active_manager_requires_canonical_subtree_and_control_group(tmp_path: Path) -> None:
    proc_root, cgroup_root, manager_dir = _manager_tree(tmp_path)
    manager_dir.rename(tmp_path / "manager-moved")

    missing, _ = _run_enforcer(tmp_path, proc_root, cgroup_root, "--apply")
    assert missing.returncode == 1
    assert "cgroup subtree absent" in missing.stderr

    proc_root, cgroup_root, _ = _manager_tree(tmp_path)
    wrong_group, _ = _run_enforcer(
        tmp_path,
        proc_root,
        cgroup_root,
        "--apply",
        manager_cgroup="/attacker.scope/user@1000.service",
    )
    assert wrong_group.returncode == 1
    assert "refusing non-canonical ControlGroup" in wrong_group.stderr
    assert (proc_root / "1000" / "oom_score_adj").read_text().strip() == "0"


@pytest.mark.parametrize(
    ("selector", "value"),
    [
        ("HAPAX_OOM_ENFORCE_TEST_MODE", "0"),
        ("HAPAX_OOM_PROC_ROOT", "/tmp/attacker-proc"),
        ("HAPAX_OOM_SYSTEMCTL", "/tmp/attacker-systemctl"),
    ],
)
def test_production_enforcer_refuses_every_test_selector(selector: str, value: str) -> None:
    env = os.environ.copy()
    for key in TEST_SELECTORS | {"SUDO_USER", "ENV", "BASH_ENV", "CDPATH"}:
        env.pop(key, None)
    env[selector] = value

    result = subprocess.run(
        [str(ENFORCER), "--apply"],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 2
    assert f"refusing production OOM enforcer override {selector}" in result.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="test selectors intentionally refuse root")
def test_enforcer_test_mode_refuses_sudo_and_ignores_bash_env(tmp_path: Path) -> None:
    proc_root, cgroup_root, manager_dir = _manager_tree(tmp_path)
    _add_unit(proc_root, cgroup_root, manager_dir, "pipewire.service", "session.slice", (4242,))
    poison_marker = tmp_path / "bash-env-ran"
    poison = tmp_path / "poison.sh"
    _write(poison, f"printf poison > {poison_marker}\n")

    safe, _ = _run_enforcer(
        tmp_path,
        proc_root,
        cgroup_root,
        "--apply-unit",
        "pipewire.service",
        extra_env={"BASH_ENV": str(poison)},
    )
    assert safe.returncode == 0, safe.stderr
    assert not poison_marker.exists()

    refused, _ = _run_enforcer(
        tmp_path,
        proc_root,
        cgroup_root,
        "--apply-unit",
        "pipewire.service",
        extra_env={"SUDO_USER": "hapax"},
    )
    assert refused.returncode == 2
    assert "under root/sudo execution" in refused.stderr


def _trigger_test_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    calls = tmp_path / "timeout.calls"
    fake_timeout = tmp_path / "timeout"
    _write(
        fake_timeout,
        f"#!/usr/bin/bash\nprintf '%s\\n' \"$@\" > {calls}\n",
        stat.S_IRWXU,
    )
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("HAPAX_OOM_TRIGGER_") or key in {
            "SUDO_USER",
            "ENV",
            "BASH_ENV",
            "CDPATH",
        }:
            env.pop(key, None)
    env.update(
        {
            "HAPAX_OOM_TRIGGER_TEST_MODE": "1",
            "HAPAX_OOM_TRIGGER_TIMEOUT": str(fake_timeout),
            "HAPAX_OOM_TRIGGER_SUDO": "/test/sudo",
            "HAPAX_OOM_TRIGGER_ENFORCER": "/test/enforcer",
            "HAPAX_OOM_TRIGGER_DEADLINE": "7s",
        }
    )
    return env, calls


@pytest.mark.skipif(os.geteuid() == 0, reason="test selectors intentionally refuse root")
def test_trigger_executes_only_the_bounded_allowlisted_command(tmp_path: Path) -> None:
    env, calls = _trigger_test_env(tmp_path)

    result = subprocess.run(
        [str(TRIGGER), "hapax-daimonion.service"],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert calls.read_text().splitlines() == [
        "--signal=KILL",
        "7s",
        "/test/sudo",
        "-n",
        "/test/enforcer",
        "--apply-unit",
        "hapax-daimonion.service",
    ]


@pytest.mark.skipif(os.geteuid() == 0, reason="test selectors intentionally refuse root")
def test_trigger_refuses_nonallowlist_sudo_test_mode_and_bash_env(tmp_path: Path) -> None:
    env, calls = _trigger_test_env(tmp_path)
    poison_marker = tmp_path / "trigger-bash-env-ran"
    poison = tmp_path / "trigger-poison.sh"
    _write(poison, f"printf poison > {poison_marker}\n")
    env["BASH_ENV"] = str(poison)

    safe = subprocess.run(
        [str(TRIGGER), "studio-compositor.service"],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert safe.returncode == 0, safe.stderr
    assert calls.exists()
    assert not poison_marker.exists()

    rejected = subprocess.run(
        [str(TRIGGER), "attacker.service"],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert rejected.returncode == 2
    assert "refusing non-allowlisted" in rejected.stderr

    sudo_env = env | {"SUDO_USER": "hapax"}
    sudo_refused = subprocess.run(
        [str(TRIGGER), "studio-compositor.service"],
        env=sudo_env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert sudo_refused.returncode == 2
    assert "under root/sudo execution" in sudo_refused.stderr


def test_production_trigger_refuses_test_selectors() -> None:
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("HAPAX_OOM_TRIGGER_") or key in {
            "SUDO_USER",
            "ENV",
            "BASH_ENV",
            "CDPATH",
        }:
            env.pop(key, None)
    env["HAPAX_OOM_TRIGGER_TEST_MODE"] = "0"

    result = subprocess.run(
        [str(TRIGGER), "studio-compositor.service"],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 2
    assert "refusing production OOM trigger override" in result.stderr


def test_privileged_oom_shells_parse_and_exclude_session_spawning_paths() -> None:
    for script in (ENFORCER, TRIGGER):
        result = subprocess.run(
            ["/usr/bin/bash", "-n", str(script)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert script.read_text(encoding="utf-8").startswith("#!/usr/bin/bash -p\n")

    enforcer = ENFORCER.read_text(encoding="utf-8")
    assert "runuser" not in enforcer
    assert "systemctl --user" not in enforcer
    assert "HAPAX_OOM_USER_SYSTEMCTL" not in enforcer
