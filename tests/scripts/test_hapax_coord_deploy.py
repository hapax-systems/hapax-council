from __future__ import annotations

import fcntl
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
    service_state = tmp_path / "systemctl-service-state.txt"
    service_state.write_text("inactive\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "systemctl"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf \'%s\\n\' "$*" >> "$HAPAX_SYSTEMCTL_CALLS"\n'
        'state_file="${HAPAX_SYSTEMCTL_SERVICE_STATE:?}"\n'
        'case "$*" in\n'
        '    "--user is-active --quiet hapax-coord.service")\n'
        '        [ "$(cat "$state_file" 2>/dev/null || true)" = "active" ] && exit 0\n'
        "        exit 3\n"
        "        ;;\n"
        '    "--user stop hapax-coord.service")\n'
        '        stop_count_file="${HAPAX_SYSTEMCTL_STOP_COUNT:?}"\n'
        '        stop_count="$(cat "$stop_count_file" 2>/dev/null || printf "0")"\n'
        '        stop_count="$((stop_count + 1))"\n'
        '        printf "%s\\n" "$stop_count" > "$stop_count_file"\n'
        '        if [ "${HAPAX_SYSTEMCTL_FAIL_STOP_NUMBER:-}" = "$stop_count" ]; then exit 1; fi\n'
        '        printf "inactive\\n" > "$state_file"\n'
        "        exit 0\n"
        "        ;;\n"
        '    "--user restart hapax-coord.service")\n'
        '        if [ "${HAPAX_SYSTEMCTL_FAIL_RESTART:-0}" = "1" ]; then exit 1; fi\n'
        '        printf "active\\n" > "$state_file"\n'
        "        exit 0\n"
        "        ;;\n"
        "esac\n"
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
    fake_git = bin_dir / "git"
    fake_git.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [ "${HAPAX_FAIL_CHECKOUT_ON_SHA:-}" != "" ] '
        '&& [ "${1:-}" = "-C" ] && [ "${3:-}" = "checkout" ] '
        '&& [ "${6:-}" = "$HAPAX_FAIL_CHECKOUT_ON_SHA" ]; then\n'
        "    exit 1\n"
        "fi\n"
        'if [ "${HAPAX_FAIL_MUTATE_WHILE_ACTIVE:-0}" = "1" ] '
        '&& [ "${1:-}" = "-C" ] '
        '&& { [ "${3:-}" = "checkout" ] || [ "${3:-}" = "clean" ]; } '
        '&& [ "$(cat "$HAPAX_SYSTEMCTL_SERVICE_STATE" 2>/dev/null || true)" = "active" ]; then\n'
        "    exit 66\n"
        "fi\n"
        'if [ "${HAPAX_FAIL_CLEAN_ON_SHA:-}" != "" ] '
        '&& [ "${1:-}" = "-C" ] && [ "${3:-}" = "clean" ]; then\n'
        '    head="$(/usr/bin/git -C "$2" rev-parse HEAD 2>/dev/null || true)"\n'
        '    if [ "$head" = "$HAPAX_FAIL_CLEAN_ON_SHA" ]; then\n'
        "        exit 1\n"
        "    fi\n"
        "fi\n"
        'exec /usr/bin/git "$@"\n',
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    return bin_dir, calls


def _deploy(
    repo: Path,
    act_root: Path,
    bin_dir: Path,
    calls: Path,
    *,
    fail_restart: bool = False,
    fail_receipt_promote: bool = False,
    fail_checkout_on_sha: str | None = None,
    fail_clean_on_sha: str | None = None,
    fail_stop_number: int | None = None,
    restart_if_up_to_date: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HAPAX_COORD_DEPLOY_REPO": str(repo),
        "HAPAX_COORD_DEPLOY_ACT_ROOT": str(act_root),
        "HAPAX_SYSTEMCTL_CALLS": str(calls),
        "HAPAX_SYSTEMCTL_SERVICE_STATE": str(calls.with_name("systemctl-service-state.txt")),
        "HAPAX_SYSTEMCTL_STOP_COUNT": str(calls.with_name("systemctl-stop-count.txt")),
        "HAPAX_FAIL_MUTATE_WHILE_ACTIVE": "1",
    }
    if fail_restart:
        env["HAPAX_SYSTEMCTL_FAIL_RESTART"] = "1"
    if fail_receipt_promote:
        env["HAPAX_FAIL_RECEIPT_PROMOTE"] = "1"
    if fail_checkout_on_sha is not None:
        env["HAPAX_FAIL_CHECKOUT_ON_SHA"] = fail_checkout_on_sha
    if fail_clean_on_sha is not None:
        env["HAPAX_FAIL_CLEAN_ON_SHA"] = fail_clean_on_sha
    if fail_stop_number is not None:
        env["HAPAX_SYSTEMCTL_FAIL_STOP_NUMBER"] = str(fail_stop_number)
    if restart_if_up_to_date:
        env["HAPAX_COORD_DEPLOY_RESTART_IF_UP_TO_DATE"] = "1"
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
    return [
        line for line in _systemctl_calls(calls) if line == "--user restart hapax-coord.service"
    ]


def _systemctl_calls(calls: Path) -> list[str]:
    if not calls.exists():
        return []
    return calls.read_text(encoding="utf-8").splitlines()


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
    assert contract["single_writer_lock"] == str(act_root / "deploy.lock")
    assert contract["restart_if_up_to_date_env"] == "HAPAX_COORD_DEPLOY_RESTART_IF_UP_TO_DATE"
    assert contract["stops_service_before_worktree_mutation"] is True
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

    third = _deploy(repo, act_root, bin_dir, calls, restart_if_up_to_date=True)

    assert third.returncode == 0, third.stderr
    assert f"coord-deploy: up to date at {sha}; restarting hapax-coord" in third.stdout
    assert f"coord-deploy: reactivated {sha}" in third.stdout
    assert _restart_calls(calls) == [
        "--user restart hapax-coord.service",
        "--user restart hapax-coord.service",
    ]


def test_coord_deploy_reports_up_to_date_restart_failure(tmp_path: Path) -> None:
    repo, _sha = _init_coord_repo(tmp_path)
    act_root = tmp_path / "activation"
    bin_dir, calls = _fake_systemctl(tmp_path)
    first = _deploy(repo, act_root, bin_dir, calls)
    assert first.returncode == 0, first.stderr

    result = _deploy(
        repo,
        act_root,
        bin_dir,
        calls,
        restart_if_up_to_date=True,
        fail_restart=True,
    )

    assert result.returncode == 1
    assert "coord-deploy: up-to-date restart failed (rc=1)" in result.stderr
    assert "coord-deploy: reactivated" not in result.stdout
    assert _restart_calls(calls) == [
        "--user restart hapax-coord.service",
        "--user restart hapax-coord.service",
    ]


def test_coord_deploy_refuses_when_single_writer_lock_is_held(tmp_path: Path) -> None:
    repo, _sha = _init_coord_repo(tmp_path)
    act_root = tmp_path / "activation"
    act_root.mkdir()
    lock_path = act_root / "deploy.lock"
    bin_dir, calls = _fake_systemctl(tmp_path)

    with lock_path.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "HAPAX_COORD_DEPLOY_REPO": str(repo),
            "HAPAX_COORD_DEPLOY_ACT_ROOT": str(act_root),
            "HAPAX_COORD_DEPLOY_LOCK_WAIT_S": "0",
            "HAPAX_SYSTEMCTL_CALLS": str(calls),
        }
        result = subprocess.run(
            [str(SCRIPT)],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    assert result.returncode == 75
    assert "deploy lock unavailable" in result.stderr
    assert _restart_calls(calls) == []


def test_coord_deploy_refuses_invalid_deployed_sha_receipt_path(tmp_path: Path) -> None:
    repo, _sha = _init_coord_repo(tmp_path)
    act_root = tmp_path / "activation"
    bin_dir, calls = _fake_systemctl(tmp_path)
    first = _deploy(repo, act_root, bin_dir, calls)
    assert first.returncode == 0, first.stderr
    receipt = act_root / "worktree" / ".deployed-sha"
    receipt.unlink()
    receipt.mkdir()

    result = _deploy(repo, act_root, bin_dir, calls)

    assert result.returncode == 1
    assert "deployed sha receipt path invalid" in result.stderr
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
    calls_after_second_deploy = _systemctl_calls(calls)[2:]
    assert calls_after_second_deploy[:2] == [
        "--user is-active --quiet hapax-coord.service",
        "--user stop hapax-coord.service",
    ]
    assert _restart_calls(calls) == [
        "--user restart hapax-coord.service",
        "--user restart hapax-coord.service",
    ]


def test_coord_deploy_refuses_target_mutation_when_initial_stop_fails(
    tmp_path: Path,
) -> None:
    repo, sha_a = _init_coord_repo(tmp_path)
    act_root = tmp_path / "activation"
    bin_dir, calls = _fake_systemctl(tmp_path)
    first = _deploy(repo, act_root, bin_dir, calls)
    assert first.returncode == 0, first.stderr
    worktree = act_root / "worktree"

    _commit_and_push(repo, "update with stop failure\n")
    result = _deploy(repo, act_root, bin_dir, calls, fail_stop_number=1)

    assert result.returncode == 1
    assert "stop hapax-coord.service before activation worktree mutation failed" in result.stderr
    assert _activation_head(worktree) == sha_a
    assert (worktree / ".deployed-sha").read_text(encoding="utf-8").strip() == sha_a


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
    assert "restart failed; stopped hapax-coord.service before rollback" in result.stderr
    assert "rolled activation worktree back" in result.stderr
    assert _activation_head(worktree) == sha_a
    assert (worktree / ".deployed-sha").read_text(encoding="utf-8").strip() == sha_a
    assert len(_restart_calls(calls)) == 3


def test_coord_deploy_stops_before_rollback_and_refuses_failed_rollback_checkout(
    tmp_path: Path,
) -> None:
    repo, sha_a = _init_coord_repo(tmp_path)
    act_root = tmp_path / "activation"
    bin_dir, calls = _fake_systemctl(tmp_path)
    first = _deploy(repo, act_root, bin_dir, calls)
    assert first.returncode == 0, first.stderr
    worktree = act_root / "worktree"

    sha_b = _commit_and_push(repo, "rollback checkout failure update\n")
    result = _deploy(
        repo,
        act_root,
        bin_dir,
        calls,
        fail_restart=True,
        fail_checkout_on_sha=sha_a,
    )

    assert result.returncode == 1
    assert "restart failed; stopped hapax-coord.service before rollback" in result.stderr
    assert "rollback checkout" in result.stderr
    assert _activation_head(worktree) == sha_b
    assert (worktree / ".deployed-sha").read_text(encoding="utf-8").strip() == sha_a


def test_coord_deploy_reports_failed_rollback_clean_after_restart_failure(
    tmp_path: Path,
) -> None:
    repo, sha_a = _init_coord_repo(tmp_path)
    act_root = tmp_path / "activation"
    bin_dir, calls = _fake_systemctl(tmp_path)
    first = _deploy(repo, act_root, bin_dir, calls)
    assert first.returncode == 0, first.stderr
    worktree = act_root / "worktree"

    _commit_and_push(repo, "rollback clean failure update\n")
    result = _deploy(
        repo,
        act_root,
        bin_dir,
        calls,
        fail_restart=True,
        fail_clean_on_sha=sha_a,
    )

    assert result.returncode == 1
    assert "rollback clean failed" in result.stderr
    assert _activation_head(worktree) == sha_a
    assert (worktree / ".deployed-sha").read_text(encoding="utf-8").strip() == sha_a


def test_coord_deploy_rolls_activation_back_when_target_checkout_fails(
    tmp_path: Path,
) -> None:
    repo, sha_a = _init_coord_repo(tmp_path)
    act_root = tmp_path / "activation"
    bin_dir, calls = _fake_systemctl(tmp_path)
    first = _deploy(repo, act_root, bin_dir, calls)
    assert first.returncode == 0, first.stderr
    worktree = act_root / "worktree"

    sha_b = _commit_and_push(repo, "checkout failure update\n")
    result = _deploy(repo, act_root, bin_dir, calls, fail_checkout_on_sha=sha_b)

    assert result.returncode == 1
    assert "checkout activation worktree" in result.stderr
    assert "failed before restart; rolled activation worktree back" in result.stderr
    assert "restarted hapax-coord.service on rollback sha" in result.stderr
    assert _activation_head(worktree) == sha_a
    assert (worktree / ".deployed-sha").read_text(encoding="utf-8").strip() == sha_a
    assert _restart_calls(calls) == [
        "--user restart hapax-coord.service",
        "--user restart hapax-coord.service",
    ]


def test_coord_deploy_rolls_activation_back_when_target_clean_fails(
    tmp_path: Path,
) -> None:
    repo, sha_a = _init_coord_repo(tmp_path)
    act_root = tmp_path / "activation"
    bin_dir, calls = _fake_systemctl(tmp_path)
    first = _deploy(repo, act_root, bin_dir, calls)
    assert first.returncode == 0, first.stderr
    worktree = act_root / "worktree"

    sha_b = _commit_and_push(repo, "clean failure update\n")
    result = _deploy(repo, act_root, bin_dir, calls, fail_clean_on_sha=sha_b)

    assert result.returncode == 1
    assert "clean untracked/ignored activation worktree" in result.stderr
    assert "failed before restart; rolled activation worktree back" in result.stderr
    assert "restarted hapax-coord.service on rollback sha" in result.stderr
    assert _activation_head(worktree) == sha_a
    assert (worktree / ".deployed-sha").read_text(encoding="utf-8").strip() == sha_a
    assert _restart_calls(calls) == [
        "--user restart hapax-coord.service",
        "--user restart hapax-coord.service",
    ]


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
    assert (
        "receipt write failed after restart; stopped hapax-coord.service before rollback"
        in result.stderr
    )
    assert "rolled activation worktree back" in result.stderr
    assert _activation_head(worktree) == sha_a
    assert (worktree / ".deployed-sha").read_text(encoding="utf-8").strip() == sha_a
    assert not (worktree / ".deployed-sha.tmp").exists()
    assert len(_restart_calls(calls)) == 3


def test_coord_deploy_refuses_rollback_mutation_when_stop_fails(tmp_path: Path) -> None:
    repo, sha_a = _init_coord_repo(tmp_path)
    act_root = tmp_path / "activation"
    bin_dir, calls = _fake_systemctl(tmp_path)
    first = _deploy(repo, act_root, bin_dir, calls)
    assert first.returncode == 0, first.stderr
    worktree = act_root / "worktree"

    sha_b = _commit_and_push(repo, "unreceipted update with stop failure\n")
    result = _deploy(
        repo,
        act_root,
        bin_dir,
        calls,
        fail_receipt_promote=True,
        fail_stop_number=2,
    )

    assert result.returncode == 1
    assert "failed to stop hapax-coord.service before rollback worktree mutation" in result.stderr
    assert "not mutating live activation worktree" in result.stderr
    assert _activation_head(worktree) == sha_b
    assert (worktree / ".deployed-sha").read_text(encoding="utf-8").strip() == sha_a
