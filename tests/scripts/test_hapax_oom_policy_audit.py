from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-oom-policy-audit"
PROTECTED_USER_UNIT_SCORES = {
    "pipewire.service": -900,
    "pipewire-pulse.service": -900,
    "wireplumber.service": -900,
    "hapax-daimonion.service": -500,
    "studio-compositor.service": -800,
    "hapax-imagination.service": -800,
}


def _protected_user_unit_cases(*, wrong_unit_score: bool = False) -> str:
    cases = []
    for unit, score in PROTECTED_USER_UNIT_SCORES.items():
        actual = 100 if wrong_unit_score and unit == "studio-compositor.service" else score
        cases.append(
            f'  *"--user show {unit} --no-pager -p OOMScoreAdjust -p MainPID"*) '
            f"printf 'OOMScoreAdjust={actual}\\nMainPID=0\\n' ;;"
        )
    return "\n".join(cases)


def _fake_systemctl(
    tmp_path: Path,
    *,
    user_oom: int = 100,
    app_bounded: bool = True,
    tmux_bounded: bool = True,
    tmux_slice: str = "app.slice",
    wrong_unit_score: bool = False,
) -> Path:
    path = tmp_path / "systemctl"
    app_values = (
        "MemoryHigh=85899345920\nMemoryMax=111669149696\nMemorySwapMax=8589934592\n"
        if app_bounded
        else "MemoryHigh=infinity\nMemoryMax=infinity\nMemorySwapMax=infinity\n"
    )
    tmux_values = (
        f"MemoryHigh=12884901888\nMemoryMax=19327352832\nMemorySwapMax=3221225472\nSlice={tmux_slice}\n"
        if tmux_bounded
        else f"MemoryHigh=infinity\nMemoryMax=infinity\nMemorySwapMax=infinity\nSlice={tmux_slice}\n"
    )
    path.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
case "$*" in
  *"show user@1000.service"*) printf 'OOMScoreAdjust={user_oom}\\nDropInPaths=/etc/systemd/system/user@1000.service.d/oom.conf\\nMainPID=900\\n' ;;
  *"show app.slice"*) printf '{app_values}' ;;
{_protected_user_unit_cases(wrong_unit_score=wrong_unit_score)}
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


def _run(
    tmp_path: Path,
    *,
    user_oom: int = 100,
    app_bounded: bool = True,
    tmux_bounded: bool = True,
    tmux_slice: str = "app.slice",
    wrong_unit_score: bool = False,
    proc_root: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    if proc_root is None:
        proc_root = tmp_path / "proc"
        proc_root.mkdir(exist_ok=True)
    if not (proc_root / "900").exists():
        _write_proc(proc_root, 900, name="systemd", uid=1000, oom_score=100)
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
            )
        ),
        "HAPAX_OOM_AUDIT_PROC_ROOT": str(proc_root),
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


def test_audit_fails_when_app_slice_backstop_is_unbounded(tmp_path: Path) -> None:
    result = _run(tmp_path, app_bounded=False)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    app_checks = [item for item in payload["checks"] if item["name"].startswith("app_slice_")]
    assert app_checks
    assert all(item["status"] == "gap" for item in app_checks)


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


def test_audit_passes_when_unbounded_tmux_scope_is_app_slice_backed(tmp_path: Path) -> None:
    result = _run(tmp_path, tmux_bounded=False, tmux_slice="app.slice")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    check = next(
        item for item in payload["checks"] if item["name"] == "tmux_scope_tmux-spawn-a.scope"
    )
    assert check["status"] == "pass"
    assert "Slice=app.slice" in check["actual"]


def test_audit_warns_when_unbounded_tmux_scope_is_outside_app_slice(tmp_path: Path) -> None:
    result = _run(tmp_path, tmux_bounded=False, tmux_slice="session.slice")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    check = next(
        item for item in payload["checks"] if item["name"] == "tmux_scope_tmux-spawn-a.scope"
    )
    assert check["status"] == "warn"
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
