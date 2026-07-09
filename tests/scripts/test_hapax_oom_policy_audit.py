from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-oom-policy-audit"


def _fake_systemctl(tmp_path: Path, *, user_oom: int = 100, app_bounded: bool = True) -> Path:
    path = tmp_path / "systemctl"
    app_values = (
        "MemoryHigh=85899345920\nMemoryMax=111669149696\nMemorySwapMax=8589934592\n"
        if app_bounded
        else "MemoryHigh=infinity\nMemoryMax=infinity\nMemorySwapMax=infinity\n"
    )
    path.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
case "$*" in
  *"show user@1000.service"*) printf 'OOMScoreAdjust={user_oom}\\nDropInPaths=/etc/systemd/system/user@1000.service.d/oom.conf\\n' ;;
  *"show app.slice"*) printf '{app_values}' ;;
  *"list-units --type=scope"*) printf 'tmux-spawn-a.scope loaded active running tmux child pane\\n' ;;
  *"show tmux-spawn-a.scope"*) printf 'MemoryHigh=12884901888\\nMemoryMax=19327352832\\nMemorySwapMax=3221225472\\n' ;;
  *) echo "unexpected args: $*" >&2; exit 9 ;;
esac
""",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _run(
    tmp_path: Path, *, user_oom: int = 100, app_bounded: bool = True
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "HAPAX_SYSTEMCTL": str(
            _fake_systemctl(tmp_path, user_oom=user_oom, app_bounded=app_bounded)
        ),
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
