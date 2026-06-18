from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-coord-deploy"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _init_coord_repo(tmp_path: Path) -> tuple[Path, str]:
    origin = tmp_path / "coord-origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)

    repo = tmp_path / "hapax-coord"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "coord-deploy-test@example.test")
    _git(repo, "config", "user.name", "Coord Deploy Test")
    (repo / "coord.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "coord.txt")
    _git(repo, "commit", "-m", "base")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-u", "origin", "main")
    return repo, _git(repo, "rev-parse", "HEAD")


def _commit_and_push(repo: Path, body: str) -> str:
    (repo / "coord.txt").write_text(body, encoding="utf-8")
    _git(repo, "add", "coord.txt")
    _git(repo, "commit", "-m", "update coord")
    _git(repo, "push", "origin", "main")
    return _git(repo, "rev-parse", "HEAD")


def _fake_systemctl(tmp_path: Path) -> tuple[Path, Path]:
    calls = tmp_path / "systemctl-calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "systemctl"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf \'%s\\n\' "$*" >> "$HAPAX_SYSTEMCTL_CALLS"\n'
        'if [ "${HAPAX_SYSTEMCTL_FAIL_RESTART:-0}" = "1" ] '
        '&& [ "$*" = "--user restart hapax-coord.service" ]; then\n'
        "    exit 1\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    fake_mv = bin_dir / "mv"
    fake_mv.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [ "${HAPAX_FAIL_RECEIPT_PROMOTE:-0}" = "1" ] '
        '&& [ "${1:-}" = "-T" ] && [[ "${2:-}" == *.deployed-sha.tmp ]]; then\n'
        "    exit 1\n"
        "fi\n"
        'exec /usr/bin/mv "$@"\n',
        encoding="utf-8",
    )
    fake_mv.chmod(0o755)
    return bin_dir, calls


def _deploy(
    repo: Path,
    act_root: Path,
    bin_dir: Path,
    calls: Path,
    *,
    fail_restart: bool = False,
    fail_receipt_promote: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HAPAX_COORD_DEPLOY_REPO": str(repo),
        "HAPAX_COORD_DEPLOY_ACT_ROOT": str(act_root),
        "HAPAX_SYSTEMCTL_CALLS": str(calls),
    }
    if fail_restart:
        env["HAPAX_SYSTEMCTL_FAIL_RESTART"] = "1"
    if fail_receipt_promote:
        env["HAPAX_FAIL_RECEIPT_PROMOTE"] = "1"
    return subprocess.run(
        [str(SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _activation_head(worktree: Path) -> str:
    return _git(worktree, "rev-parse", "HEAD")


def _restart_calls(calls: Path) -> list[str]:
    if not calls.exists():
        return []
    return [
        line
        for line in calls.read_text(encoding="utf-8").splitlines()
        if line == "--user restart hapax-coord.service"
    ]


def test_coord_deploy_contract_names_stable_activation_surfaces(tmp_path: Path) -> None:
    repo, _sha = _init_coord_repo(tmp_path)
    act_root = tmp_path / "activation"
    env = {
        **os.environ,
        "HAPAX_COORD_DEPLOY_REPO": str(repo),
        "HAPAX_COORD_DEPLOY_ACT_ROOT": str(act_root),
    }

    result = subprocess.run(
        [str(SCRIPT), "--contract-json"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    contract = json.loads(result.stdout)
    assert contract["source_repo"] == str(repo)
    assert contract["activation_worktree"] == str(act_root / "worktree")
    assert contract["writes_deployed_sha_after_restart"] is True
    assert contract["rolls_back_worktree_on_restart_failure"] is True
    assert contract["restarts_service"] == "hapax-coord.service"


def test_coord_deploy_materializes_activation_and_skips_up_to_date(
    tmp_path: Path,
) -> None:
    repo, sha = _init_coord_repo(tmp_path)
    act_root = tmp_path / "activation"
    bin_dir, calls = _fake_systemctl(tmp_path)

    result = _deploy(repo, act_root, bin_dir, calls)

    worktree = act_root / "worktree"
    assert result.returncode == 0, result.stderr
    assert f"coord-deploy: activated {sha}" in result.stdout
    assert _activation_head(worktree) == sha
    assert (worktree / ".deployed-sha").read_text(encoding="utf-8").strip() == sha
    assert _restart_calls(calls) == ["--user restart hapax-coord.service"]

    second = _deploy(repo, act_root, bin_dir, calls)

    assert second.returncode == 0, second.stderr
    assert f"coord-deploy: up to date at {sha}" in second.stdout
    assert _restart_calls(calls) == ["--user restart hapax-coord.service"]


def test_coord_deploy_cleans_activation_worktree_before_new_restart(
    tmp_path: Path,
) -> None:
    repo, sha_a = _init_coord_repo(tmp_path)
    act_root = tmp_path / "activation"
    bin_dir, calls = _fake_systemctl(tmp_path)
    first = _deploy(repo, act_root, bin_dir, calls)
    assert first.returncode == 0, first.stderr
    worktree = act_root / "worktree"
    stale = worktree / "stale-runtime-copy.py"
    stale.write_text("stale\n", encoding="utf-8")
    assert _activation_head(worktree) == sha_a

    sha_b = _commit_and_push(repo, "updated\n")
    result = _deploy(repo, act_root, bin_dir, calls)

    assert result.returncode == 0, result.stderr
    assert _activation_head(worktree) == sha_b
    assert not stale.exists()
    assert (worktree / ".deployed-sha").read_text(encoding="utf-8").strip() == sha_b
    assert _restart_calls(calls) == [
        "--user restart hapax-coord.service",
        "--user restart hapax-coord.service",
    ]


def test_coord_deploy_rolls_activation_back_when_restart_fails(tmp_path: Path) -> None:
    repo, sha_a = _init_coord_repo(tmp_path)
    act_root = tmp_path / "activation"
    bin_dir, calls = _fake_systemctl(tmp_path)
    first = _deploy(repo, act_root, bin_dir, calls)
    assert first.returncode == 0, first.stderr
    worktree = act_root / "worktree"

    _commit_and_push(repo, "broken update\n")
    result = _deploy(repo, act_root, bin_dir, calls, fail_restart=True)

    assert result.returncode == 1
    assert "restart failed; rolled activation worktree back" in result.stderr
    assert _activation_head(worktree) == sha_a
    assert (worktree / ".deployed-sha").read_text(encoding="utf-8").strip() == sha_a
    assert len(_restart_calls(calls)) == 3


def test_coord_deploy_rolls_service_back_when_receipt_promote_fails(
    tmp_path: Path,
) -> None:
    repo, sha_a = _init_coord_repo(tmp_path)
    act_root = tmp_path / "activation"
    bin_dir, calls = _fake_systemctl(tmp_path)
    first = _deploy(repo, act_root, bin_dir, calls)
    assert first.returncode == 0, first.stderr
    worktree = act_root / "worktree"

    _commit_and_push(repo, "unreceipted update\n")
    result = _deploy(repo, act_root, bin_dir, calls, fail_receipt_promote=True)

    assert result.returncode == 1
    assert "receipt write failed after restart; rolled activation worktree back" in result.stderr
    assert _activation_head(worktree) == sha_a
    assert (worktree / ".deployed-sha").read_text(encoding="utf-8").strip() == sha_a
    assert not (worktree / ".deployed-sha.tmp").exists()
    assert len(_restart_calls(calls)) == 3
