"""Tests for scripts/hapax-oom-score-enforce (bash) — the logind-storm fix.

The 2026-08-10 appendix SSH wedge: the enforcer made ~14 runuser calls per
run (full PAM/logind session each) on a 30s timer — 1,678 sessions/hour, an
I/O storm that wedged sshd session setup. The fix resolves user-unit cgroups
from /sys/fs/cgroup directly. These tests pin: fs-based resolution (app.slice
and direct-child placements), all-pid writes on --apply-unit, idempotence,
missing-cgroup refusal, and that NO runuser/systemctl --user path executes.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENFORCER = REPO_ROOT / "scripts" / "hapax-oom-score-enforce"


def _write(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)


def _fixture_tree(tmp_path: Path, *, unit_in_app_slice: bool = True) -> tuple[Path, Path, Path]:
    """Build a fake /proc and cgroup tree with one protected unit carrying two pids."""
    proc = tmp_path / "proc"
    cgroup = tmp_path / "cgroup"
    base = cgroup / "user.slice" / "user-1000.slice" / "user@1000.service"
    unit_dir = (
        (base / "app.slice" / "pipewire.service")
        if unit_in_app_slice
        else (base / "pipewire.service")
    )
    _write(unit_dir / "cgroup.procs", "4242\n4343\n")
    rel_unit = unit_dir.relative_to(cgroup)
    for pid in ("4242", "4343"):
        _write(proc / pid / "oom_score_adj", "200\n")
        _write(proc / pid / "cgroup", f"0::/{rel_unit}\n")
    # the user manager itself (queried via the systemctl stub)
    _write(proc / "1000" / "oom_score_adj", "0\n")
    _write(proc / "1000" / "cgroup", "0::/user.slice/user-1000.slice/user@1000.service\n")
    return proc, cgroup, unit_dir


def _systemctl_stub(tmp_path: Path) -> Path:
    """System-level queries only; explodes if asked for a --user call."""
    stub = tmp_path / "bin" / "systemctl"
    _write(
        stub,
        """#!/usr/bin/bash
if [[ "$*" == *--user* ]]; then
  echo "systemctl --user must never be called (PAM/logind storm)" >&2
  exit 99
fi
if [[ "$*" == *"show user@1000.service -p ActiveState"* ]]; then printf 'active\\n'; exit 0; fi
if [[ "$*" == *"show user@1000.service -p MainPID"* ]]; then printf '1000\\n'; exit 0; fi
if [[ "$*" == *"show user@1000.service -p ControlGroup"* ]]; then
  printf '/user.slice/user-1000.slice/user@1000.service\\n'; exit 0
fi
exit 0
""",
        stat.S_IRWXU,
    )
    return stub


def _run(tmp_path: Path, *args: str, unit_in_app_slice: bool = True) -> subprocess.CompletedProcess:
    proc, cgroup, _unit_dir = _fixture_tree(tmp_path, unit_in_app_slice=unit_in_app_slice)
    return _run_against(tmp_path, proc, cgroup, *args)


def _run_against(
    tmp_path: Path, proc: Path, cgroup: Path, *args: str
) -> subprocess.CompletedProcess:
    stub = _systemctl_stub(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            # pin both: without these the TEST_MODE path probes id -u hapax,
            # which fails on CI runners where the account does not exist
            "HAPAX_OOM_TARGET_USER": "hapax",
            "HAPAX_OOM_TARGET_UID": "1000",
            "HAPAX_OOM_ENFORCE_TEST_MODE": "1",
            "HAPAX_OOM_PROC_ROOT": str(proc),
            "HAPAX_OOM_CGROUP_ROOT": str(cgroup),
            "HAPAX_OOM_SYSTEMCTL": str(stub),
            # a runuser that explodes, FIRST on PATH — any PAM attempt is a hard failure
            "PATH": f"{tmp_path / 'bin'}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        }
    )
    _write(
        tmp_path / "bin" / "runuser",
        "#!/usr/bin/bash\necho 'runuser must never be called (PAM/logind storm)' >&2\nexit 99\n",
        stat.S_IRWXU,
    )
    return subprocess.run(
        ["/usr/bin/bash", str(ENFORCER), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_apply_writes_scores_via_filesystem_resolution(tmp_path):
    proc = tmp_path / "proc"
    result = _run(tmp_path, "--apply")
    assert result.returncode == 0, result.stderr
    assert "systemctl --user must never be called" not in result.stderr
    for pid in ("4242", "4343"):
        assert (proc / pid / "oom_score_adj").read_text().strip() == "-900"
    # the manager itself is made killable via the system path
    assert (proc / "1000" / "oom_score_adj").read_text().strip() == "100"


def test_apply_resolves_direct_child_placement(tmp_path):
    proc = tmp_path / "proc"
    result = _run(tmp_path, "--apply", unit_in_app_slice=False)
    assert result.returncode == 0, result.stderr
    assert (proc / "4242" / "oom_score_adj").read_text().strip() == "-900"


def test_apply_is_idempotent(tmp_path):
    proc, cgroup, _unit_dir = _fixture_tree(tmp_path)
    first = _run_against(tmp_path, proc, cgroup, "--apply")
    assert first.returncode == 0, first.stderr
    # second run against the SAME tree must write nothing
    second = _run_against(tmp_path, proc, cgroup, "--apply")
    assert second.returncode == 0, second.stderr
    assert "oom_score_adj=" not in second.stdout  # no 'changed' lines at all
    assert (proc / "4242" / "oom_score_adj").read_text().strip() == "-900"


def test_apply_fails_loud_when_manager_subtree_absent(tmp_path):
    # a missing manager cgroup subtree is not host topology — it is a wrong
    # cgroup layout, and the run must fail rather than skip everything
    proc, cgroup, _unit_dir = _fixture_tree(tmp_path)
    import shutil

    shutil.rmtree(cgroup / "user.slice")
    result = _run_against(tmp_path, proc, cgroup, "--apply")
    assert result.returncode == 1
    assert "cgroup subtree absent" in result.stderr


def test_apply_unit_writes_all_unit_pids(tmp_path):
    proc = tmp_path / "proc"
    result = _run(tmp_path, "--apply-unit", "pipewire.service")
    assert result.returncode == 0, result.stderr
    for pid in ("4242", "4343"):
        assert (proc / pid / "oom_score_adj").read_text().strip() == "-900"


def test_apply_unit_refuses_non_allowlisted_unit(tmp_path):
    result = _run(tmp_path, "--apply-unit", "evil.service")
    assert result.returncode == 2
    assert "refusing non-allowlisted" in result.stderr


def test_apply_skips_absent_units_quietly(tmp_path):
    # appendix topology: daimonion/compositor/imagination are not-found here.
    # Skips must be quiet and the run must still succeed for present units.
    proc = tmp_path / "proc"
    result = _run(tmp_path, "--apply")
    assert result.returncode == 0, result.stderr
    assert "not present on this host; skipping" in result.stdout
    assert (proc / "4242" / "oom_score_adj").read_text().strip() == "-900"
