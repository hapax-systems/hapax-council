"""Tests for ``scripts/rebuild-service.sh``'s dedicated-worktree behaviour.

The 2026-05-03 refactor (cc-task ``deploy-pipeline-canonical-worktree-isolation``)
moves council deploys off the operator's interactive worktree
(``~/projects/hapax-council``) and onto a dedicated rebuild worktree
(``~/.cache/hapax/rebuild/worktree``) that the script auto-creates and
fast-forwards to ``origin/main`` at the start of every invocation.

This module pins three load-bearing invariants:

1. **Bootstrap** — when the rebuild worktree does not exist, the script
   creates it via ``git worktree add --detach origin/main`` against the
   canonical source repo.
2. **Fast-forward** — when the rebuild worktree exists but is at an older
   SHA, the script resets it to ``origin/main`` before doing any other work.
3. **No branch-check** — when the canonical (operator) repo is on a feature
   branch, the deploy proceeds anyway. This is the original bug class
   (``alpha off main blocks deploys for the rest of the system``) and the
   primary forever-fix the refactor exists to ship.

Plus one regression pin:

4. **Dropped code is gone** — ``rebuild-service.sh`` no longer contains the
   ``repo not on main (on $CURRENT_BRANCH)`` skip path.

A real ``git`` is used; ``systemctl`` / ``curl`` / ``logger`` are shimmed via
PATH-prepended fakes so the tests don't require systemd or network.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "rebuild-service.sh"


# ----------------------------------------------------------------------
# Harness
# ----------------------------------------------------------------------


@pytest.fixture
def harness(tmp_path: Path) -> dict[str, Path]:
    """Build a sandbox with a real git remote + canonical worktree.

    Layout produced::

        tmp_path/
          remote.git/                     -- bare remote
          canonical/                      -- the "operator's interactive worktree"
            file.txt                      -- one tracked file
            agents/voice/voice.py         -- one watched file
          rebuild_worktree/                -- target slot for the dedicated
                                            rebuild worktree (initially empty;
                                            the script must create it)
          state/                          -- script state dir
          shimbin/
            systemctl, curl, logger,
            timeout                       -- PATH-shadowing fakes that record
                                            their calls into log.txt
          log.txt
    """
    remote = tmp_path / "remote.git"
    canonical = tmp_path / "canonical"
    rebuild_worktree = tmp_path / "rebuild_worktree"
    state_dir = tmp_path / "state"
    shimbin = tmp_path / "shimbin"
    log_file = tmp_path / "log.txt"

    state_dir.mkdir()
    shimbin.mkdir()

    # Bare remote.
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)

    # Canonical worktree — clone of the bare remote, with a seed commit on main.
    subprocess.run(
        ["git", "clone", str(remote), str(canonical)],
        check=True,
        capture_output=True,
    )
    git_env = {
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }

    def gitc(*args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(git_env)
        return subprocess.run(
            ["git", "-C", str(canonical), *args],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )

    # The default branch from a fresh `git clone` of an empty bare repo
    # depends on init.defaultBranch. Force "main" explicitly.
    gitc("checkout", "-b", "main")
    (canonical / "file.txt").write_text("seed\n")
    voice_dir = canonical / "agents" / "voice"
    voice_dir.mkdir(parents=True)
    (voice_dir / "voice.py").write_text("# v1\n")
    gitc("add", ".")
    gitc("commit", "-m", "seed")
    gitc("push", "origin", "main")

    # ------------------------------------------------------------------
    # Shims: systemctl, curl, logger
    # ------------------------------------------------------------------
    systemctl_shim = shimbin / "systemctl"
    systemctl_shim.write_text(
        f"""#!/usr/bin/env bash
printf '%s' "systemctl" >> {log_file}
for a in "$@"; do printf ' %s' "$a" >> {log_file}; done
printf '\\n' >> {log_file}
if [ "${{1:-}}" = "--user" ] && [ "${{2:-}}" = "show" ]; then
  printf 'LoadState=%s\\n' "${{HAPAX_TEST_LOAD_STATE:-loaded}}"
  printf 'UnitFileState=%s\\n' "${{HAPAX_TEST_UNIT_FILE_STATE:-enabled}}"
  printf 'ActiveState=%s\\n' "${{HAPAX_TEST_ACTIVE_STATE:-active}}"
  printf 'SubState=%s\\n' "${{HAPAX_TEST_SUB_STATE:-running}}"
  printf 'Result=%s\\n' "${{HAPAX_TEST_RESULT:-success}}"
  printf 'ExecMainStatus=%s\\n' "${{HAPAX_TEST_EXEC_MAIN_STATUS:-0}}"
  printf 'ActiveEnterTimestampMonotonic=%s\\n' "${{HAPAX_TEST_ACTIVE_ENTER_MONO:-999999999999999999}}"
  exit 0
fi
exit 0
"""
    )
    systemctl_shim.chmod(systemctl_shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    for name in ("curl", "logger"):
        shim = shimbin / name
        # Quote literally — log to the file, succeed cleanly. Use printf to
        # keep argv reproducible across shells.
        shim.write_text(
            f"""#!/usr/bin/env bash
printf '%s' "{name}" >> {log_file}
for a in "$@"; do printf ' %s' "$a" >> {log_file}; done
printf '\\n' >> {log_file}
exit 0
"""
        )
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    timeout_shim = shimbin / "timeout"
    timeout_shim.write_text(
        f"""#!/usr/bin/env bash
printf '%s' "timeout" >> {log_file}
for a in "$@"; do printf ' %s' "$a" >> {log_file}; done
printf '\\n' >> {log_file}
if [ -n "${{HAPAX_TEST_TIMEOUT_RC:-}}" ]; then
  exit "$HAPAX_TEST_TIMEOUT_RC"
fi
while [ "$#" -gt 0 ] && [ "${{1#--}}" != "$1" ]; do shift; done
if [ "$#" -gt 0 ]; then shift; fi
exec "$@"
"""
    )
    timeout_shim.chmod(timeout_shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    return {
        "tmp_path": tmp_path,
        "remote": remote,
        "canonical": canonical,
        "rebuild_worktree": rebuild_worktree,
        "state_dir": state_dir,
        "shimbin": shimbin,
        "log_file": log_file,
    }


def _add_remote_commit(harness: dict[str, Path], path: str, content: str, message: str) -> str:
    """Commit + push a change to ``origin/main`` from the canonical repo."""
    canonical = harness["canonical"]
    target = canonical / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
    )
    for cmd in (
        ["git", "-C", str(canonical), "add", path],
        ["git", "-C", str(canonical), "commit", "-m", message],
        ["git", "-C", str(canonical), "push", "origin", "HEAD:main"],
    ):
        subprocess.run(cmd, check=True, capture_output=True, env=env)
    sha = subprocess.run(
        ["git", "-C", str(canonical), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return sha


def _switch_canonical_to_feature_branch(harness: dict[str, Path]) -> None:
    """Put the canonical operator worktree on a feature branch with a dirty edit.

    This is the failure mode the refactor exists to make irrelevant: pre-fix,
    the rebuild script saw the canonical worktree was off main and skipped the
    deploy for every council service.
    """
    canonical = harness["canonical"]
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
    )
    subprocess.run(
        ["git", "-C", str(canonical), "checkout", "-b", "alpha/wip"],
        check=True,
        capture_output=True,
        env=env,
    )
    (canonical / "agents" / "voice" / "voice.py").write_text("# WIP — uncommitted edit\n")


def _run(
    harness: dict[str, Path],
    *,
    sha_key: str = "voice",
    watch: str | None = "agents/voice/",
    service: str | None = None,
    pull_only: bool = False,
    repo_override: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        "bash",
        str(SCRIPT_PATH),
        "--repo",
        repo_override or str(harness["rebuild_worktree"]),
        "--sha-key",
        sha_key,
    ]
    if watch is not None:
        cmd += ["--watch", watch]
    if service is not None:
        cmd += ["--service", service]
    if pull_only:
        cmd += ["--pull-only"]

    env = os.environ.copy()
    env.update(
        {
            # Critical: PATH-prepend the shim dir so the script's bare
            # `systemctl` / `curl` / `logger` calls hit the fakes.
            "PATH": f"{harness['shimbin']}:{env.get('PATH', '')}",
            "HAPAX_REBUILD_STATE_DIR": str(harness["state_dir"]),
            "HAPAX_REBUILD_CANONICAL_REPO": str(harness["canonical"]),
            "HAPAX_REBUILD_WORKTREE": str(harness["rebuild_worktree"]),
            # Defang the pressure guard — load can spike on CI.
            "HAPAX_REBUILD_SKIP_GUARD": "1",
            "HAPAX_REBUILD_RESTART_OBSERVATION_SEC": "0",
            # Don't actually try to hit ntfy.
            "NTFY_BASE_URL": "http://127.0.0.1:0",
        }
    )
    if extra_env:
        env.update(extra_env)
    return subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)


def _last_outcome(harness: dict[str, Path], sha_key: str = "voice") -> dict:
    return json.loads((harness["state_dir"] / f"last-{sha_key}-outcome.json").read_text())


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------


def test_rebuild_worktree_is_created_on_first_run(harness: dict[str, Path]) -> None:
    """When the rebuild worktree slot is empty, the script creates it."""
    rebuild_worktree = harness["rebuild_worktree"]
    assert not rebuild_worktree.exists()

    # Force a deploy-eligible diff: advance origin/main with a watched-path change.
    _add_remote_commit(harness, "agents/voice/voice.py", "# v2\n", "v2")

    result = _run(harness, service="hapax-daimonion.service")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (rebuild_worktree / ".git").exists(), (
        "rebuild worktree must be created by the script on first run"
    )

    # The worktree must be at origin/main HEAD.
    head = subprocess.run(
        ["git", "-C", str(rebuild_worktree), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    origin_main = subprocess.run(
        ["git", "-C", str(harness["canonical"]), "rev-parse", "origin/main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head == origin_main, (
        f"rebuild worktree should be at origin/main ({origin_main}); got {head}"
    )


def test_rebuild_worktree_is_fast_forwarded_each_run(harness: dict[str, Path]) -> None:
    """Existing rebuild worktree is reset to origin/main at start of run."""
    rebuild_worktree = harness["rebuild_worktree"]

    # Bootstrap the rebuild worktree at the seed SHA.
    seed_sha = subprocess.run(
        ["git", "-C", str(harness["canonical"]), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "-C",
            str(harness["canonical"]),
            "worktree",
            "add",
            "--detach",
            str(rebuild_worktree),
            seed_sha,
        ],
        check=True,
        capture_output=True,
    )

    # Advance origin/main past the seed.
    new_sha = _add_remote_commit(harness, "agents/voice/voice.py", "# v3\n", "v3")
    assert new_sha != seed_sha

    result = _run(harness, service="hapax-daimonion.service")
    assert result.returncode == 0, result.stdout + result.stderr

    head = subprocess.run(
        ["git", "-C", str(rebuild_worktree), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head == new_sha, (
        f"rebuild worktree must be fast-forwarded to origin/main ({new_sha}); still at {head}"
    )


def test_canonical_on_feature_branch_does_not_block_deploy(
    harness: dict[str, Path],
) -> None:
    """Original-bug-class regression pin.

    Pre-fix: when ``~/projects/hapax-council`` was on ``alpha/<wip>`` with
    uncommitted edits, ``rebuild-service.sh`` skipped the deploy with
    ``repo not on main`` and emitted a throttled ntfy. That meant a feature
    branch on the operator's interactive worktree blocked deploys for the
    rest of the system.

    Post-fix: deploys run from the dedicated rebuild worktree, which is
    structurally on main. The canonical worktree's branch state is
    irrelevant to deploys.
    """
    # Origin advances first.
    _add_remote_commit(harness, "agents/voice/voice.py", "# v4\n", "v4")
    new_sha = subprocess.run(
        ["git", "-C", str(harness["canonical"]), "rev-parse", "origin/main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    # Then the operator switches the canonical worktree to a feature branch
    # with a local dirty edit (the exact failure mode the refactor obsoletes).
    _switch_canonical_to_feature_branch(harness)

    result = _run(harness, service="hapax-daimonion.service")
    assert result.returncode == 0, result.stdout + result.stderr

    # Service restart must have fired.
    log = harness["log_file"].read_text() if harness["log_file"].exists() else ""
    assert "systemctl --user restart hapax-daimonion.service" in log, (
        "service restart must fire even though the canonical repo is on a "
        f"feature branch; log:\n{log}"
    )

    # SHA_FILE must have been advanced (no silent skip).
    sha_file = harness["state_dir"] / "last-voice-sha"
    assert sha_file.exists(), "SHA_FILE must be written after a successful deploy"
    assert sha_file.read_text().strip() == new_sha, (
        f"SHA_FILE should be {new_sha}; got {sha_file.read_text().strip()}"
    )


def test_service_restart_is_wrapped_with_timeout(harness: dict[str, Path]) -> None:
    """A single service restart must not be able to hang the whole chain."""
    new_sha = _add_remote_commit(
        harness, "agents/voice/voice.py", "# restart-timeout\n", "restart timeout"
    )

    result = _run(harness, service="hapax-daimonion.service")
    assert result.returncode == 0, result.stdout + result.stderr

    log = harness["log_file"].read_text() if harness["log_file"].exists() else ""
    assert "timeout --kill-after=10s 60s systemctl --user restart hapax-daimonion.service" in log, (
        f"restart must be wrapped by the timeout guard; log:\n{log}"
    )
    outcome = _last_outcome(harness)
    assert outcome["outcome"] == "restart_success"
    assert outcome["current_sha"] == new_sha
    assert outcome["sha_file_written"] is True


def test_timed_out_restart_unknown_writes_sha_and_exits_nonzero(
    harness: dict[str, Path],
) -> None:
    """Unknown timeout failures preserve failed-restart behavior and advance SHA state."""
    new_sha = _add_remote_commit(
        harness,
        "agents/voice/voice.py",
        "# restart-timeout-failure\n",
        "restart timeout failure",
    )

    result = _run(
        harness,
        service="hapax-daimonion.service",
        extra_env={"HAPAX_TEST_TIMEOUT_RC": "124", "HAPAX_TEST_ACTIVE_ENTER_MONO": "1"},
    )
    assert result.returncode == 1, result.stdout + result.stderr

    log = harness["log_file"].read_text() if harness["log_file"].exists() else ""
    assert "timeout --kill-after=10s 60s systemctl --user restart hapax-daimonion.service" in log, (
        f"timeout wrapper should have been invoked; log:\n{log}"
    )
    assert "logger -t hapax-rebuild-voice hapax-daimonion.service restart failed" in log

    sha_file = harness["state_dir"] / "last-voice-sha"
    assert sha_file.exists(), "failed restart path should still record the attempted SHA"
    assert sha_file.read_text().strip() == new_sha
    outcome = _last_outcome(harness)
    assert outcome["outcome"] == "restart_timeout_unknown"
    assert outcome["exit_code"] == 1
    assert outcome["sha_file_written"] is True


def test_timed_out_restart_late_active_is_not_false_red(harness: dict[str, Path]) -> None:
    """A timed-out restart can clear only with fresh active evidence."""
    new_sha = _add_remote_commit(
        harness,
        "agents/voice/voice.py",
        "# restart-timeout-late-active\n",
        "restart timeout late active",
    )

    result = _run(
        harness,
        service="hapax-daimonion.service",
        extra_env={
            "HAPAX_TEST_TIMEOUT_RC": "124",
            "HAPAX_TEST_ACTIVE_ENTER_MONO": "999999999999999999",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr

    sha_file = harness["state_dir"] / "last-voice-sha"
    assert sha_file.read_text().strip() == new_sha
    outcome = _last_outcome(harness)
    assert outcome["outcome"] == "restart_timeout_late_active"
    assert outcome["exit_code"] == 0
    assert outcome["sha_file_written"] is True


def test_missing_unit_is_fail_closed_and_does_not_write_sha(harness: dict[str, Path]) -> None:
    """A not-found target unit must not be treated as a successful activation."""
    _add_remote_commit(
        harness,
        "agents/voice/voice.py",
        "# restart-missing-unit\n",
        "restart missing unit",
    )

    result = _run(
        harness,
        service="hapax-daimonion.service",
        extra_env={"HAPAX_TEST_LOAD_STATE": "not-found"},
    )
    assert result.returncode == 1, result.stdout + result.stderr

    log = harness["log_file"].read_text() if harness["log_file"].exists() else ""
    assert "systemctl --user restart hapax-daimonion.service" not in log
    assert not (harness["state_dir"] / "last-voice-sha").exists()
    outcome = _last_outcome(harness)
    assert outcome["outcome"] == "missing_unit"
    assert outcome["sha_file_written"] is False


def test_restart_timeout_accepts_coreutils_duration_override(harness: dict[str, Path]) -> None:
    """The env override accepts an explicit duration, not only bare seconds."""
    _add_remote_commit(
        harness, "agents/voice/voice.py", "# restart-timeout-override\n", "timeout override"
    )

    result = _run(
        harness,
        service="hapax-daimonion.service",
        extra_env={"HAPAX_REBUILD_RESTART_TIMEOUT_SEC": "2m"},
    )
    assert result.returncode == 0, result.stdout + result.stderr

    log = harness["log_file"].read_text() if harness["log_file"].exists() else ""
    assert "timeout --kill-after=10s 2m systemctl --user restart hapax-daimonion.service" in log, (
        f"duration override should be passed through without appending seconds; log:\n{log}"
    )


def test_no_op_when_main_unchanged(harness: dict[str, Path]) -> None:
    """No deploy fires when origin/main has not advanced past SHA_FILE.

    Sanity check: the bootstrap path must not falsely trigger a restart on
    a steady-state run.
    """
    # Bootstrap rebuild worktree at HEAD.
    seed_sha = subprocess.run(
        ["git", "-C", str(harness["canonical"]), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    # Pre-write SHA_FILE so the script believes we already deployed this SHA.
    (harness["state_dir"] / "last-voice-sha").write_text(seed_sha)

    result = _run(harness, service="hapax-daimonion.service")
    assert result.returncode == 0, result.stdout + result.stderr

    log = harness["log_file"].read_text() if harness["log_file"].exists() else ""
    assert "systemctl --user restart" not in log, (
        f"no service restart should fire when origin/main is unchanged; log:\n{log}"
    )


def test_branch_check_is_removed_from_script() -> None:
    """Static regression pin: the script no longer contains the branch-check.

    Pre-fix string fragments that must not reappear:
      - ``repo not on main (on``
      - ``Operator: rebase``
    """
    script_text = SCRIPT_PATH.read_text()
    assert "repo not on main (on" not in script_text, (
        "rebuild-service.sh must not refuse deploys based on canonical branch"
    )
    assert "Operator: rebase" not in script_text, (
        "rebuild-service.sh must not emit the legacy 'rebase to deploy' ntfy"
    )
    assert "rebuild-service.sh refuses to auto-advance a feature branch" not in script_text, (
        "rebuild-service.sh no longer refuses based on canonical branch"
    )


def test_foreign_repo_path_skips_worktree_bootstrap(harness: dict[str, Path]) -> None:
    """Foreign repos (officium, mcp) bypass the rebuild-worktree machinery.

    When ``--repo`` does not equal ``HAPAX_REBUILD_WORKTREE``, the script must
    not try to ``git worktree add`` it. The foreign repo manages its own
    branch state.
    """
    # Build a small foreign repo at a third path.
    foreign = harness["tmp_path"] / "foreign"
    subprocess.run(
        ["git", "clone", str(harness["remote"]), str(foreign)],
        check=True,
        capture_output=True,
    )
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
    )
    subprocess.run(
        ["git", "-C", str(foreign), "checkout", "main"],
        check=True,
        capture_output=True,
        env=env,
    )

    # Advance origin/main with a change.
    _add_remote_commit(harness, "agents/voice/voice.py", "# v5\n", "v5")

    # Run the script against the foreign repo. Critical assertion: the
    # rebuild worktree slot must remain absent (not bootstrapped for foreign
    # repos).
    rebuild_worktree = harness["rebuild_worktree"]
    assert not rebuild_worktree.exists()

    result = _run(
        harness,
        sha_key="officium",
        watch=None,
        service="officium-api.service",
        repo_override=str(foreign),
    )
    assert result.returncode == 0, result.stdout + result.stderr

    assert not rebuild_worktree.exists(), (
        "rebuild worktree must NOT be bootstrapped when --repo points at a foreign repo"
    )

    # And the foreign repo should have ff-merged onto main.
    head = subprocess.run(
        ["git", "-C", str(foreign), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    origin_main = subprocess.run(
        ["git", "-C", str(foreign), "rev-parse", "origin/main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head == origin_main, (
        f"foreign repo should ff-merge to origin/main ({origin_main}); got {head}"
    )


# ----------------------------------------------------------------------
# reform-deploy-chain-repair-20260601: post-merge-deploy trigger restore,
# consecutive-pressure-skip force, and deploy-staleness alarm.
# ----------------------------------------------------------------------


def _advance_origin_externally(
    harness: dict[str, Path], path: str, content: str, message: str
) -> str:
    """Advance origin/main from a THROWAWAY clone, leaving the canonical
    worktree's local refs/heads/main frozen (production shape: the operator
    worktree sits on a feature branch, so nothing advances its local main)."""
    ext = harness["tmp_path"] / f"ext-{message.replace(' ', '-')}"
    # Clone main EXPLICITLY: the harness remote is `git init --bare` (no
    # `-b main`), so its HEAD may point at an init-default branch (master) that
    # doesn't exist. A bare `git clone` then leaves an unborn default branch and
    # the subsequent `push HEAD:main` is a non-fast-forward root commit (green
    # locally on git that defaults to main, red in CI that defaults to master).
    subprocess.run(
        ["git", "clone", "--branch", "main", str(harness["remote"]), str(ext)],
        check=True,
        capture_output=True,
    )
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
    )
    target = ext / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    for cmd in (
        ["git", "-C", str(ext), "add", path],
        ["git", "-C", str(ext), "commit", "-m", message],
        ["git", "-C", str(ext), "push", "origin", "HEAD:main"],
    ):
        subprocess.run(cmd, check=True, capture_output=True, env=env)
    return subprocess.run(
        ["git", "-C", str(ext), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _rev_parse(repo: Path, ref: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", ref],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_rebuild_advances_canonical_main_ref_for_path_trigger(harness: dict[str, Path]) -> None:
    """The post-merge-deploy .path watches refs/heads/main; rebuild-service must
    advance that SHARED ref to origin/main. Without it the ref is frozen (the
    operator worktree is on a feature branch) and the deploy trigger is dead —
    the reform-deploy-chain-repair root cause."""
    canonical = harness["canonical"]
    seed_main = _rev_parse(canonical, "refs/heads/main")
    # Put canonical on a feature branch so its local main can only move via our
    # explicit update-ref, never as a side effect of a commit-on-main.
    _switch_canonical_to_feature_branch(harness)
    new_sha = _advance_origin_externally(harness, "agents/voice/voice.py", "# advance\n", "advance")
    assert new_sha != seed_main
    assert _rev_parse(canonical, "refs/heads/main") == seed_main, "precondition: local main frozen"

    result = _run(harness, service="hapax-daimonion.service")
    assert result.returncode == 0, result.stdout + result.stderr

    assert _rev_parse(canonical, "refs/heads/main") == new_sha, (
        "rebuild-service must update-ref the shared refs/heads/main to origin/main "
        "so the .path trigger fires"
    )
    loose_ref = canonical / ".git" / "refs" / "heads" / "main"
    assert loose_ref.is_file(), "a loose refs/heads/main file must exist for PathChanged to watch"
    log = harness["log_file"].read_text() if harness["log_file"].exists() else ""
    assert f"advanced refs/heads/main → {new_sha[:8]}" in log


def test_rebuild_does_not_rewrite_main_ref_when_already_current(harness: dict[str, Path]) -> None:
    """Loop-safety: when refs/heads/main already equals origin/main the script
    must NOT update-ref (no mtime churn → no spurious per-tick .path re-fires)."""
    canonical = harness["canonical"]
    # Bootstrap rebuild worktree + leave canonical on main at origin/main HEAD.
    _add_remote_commit(harness, "agents/voice/voice.py", "# v\n", "v")
    # canonical is on main and just committed+pushed, so refs/heads/main == origin/main.
    assert _rev_parse(canonical, "refs/heads/main") == _rev_parse(canonical, "origin/main")

    result = _run(harness, service="hapax-daimonion.service")
    assert result.returncode == 0, result.stdout + result.stderr

    log = harness["log_file"].read_text() if harness["log_file"].exists() else ""
    assert "advanced refs/heads/main" not in log, (
        "must not advance the ref when it already matches origin/main"
    )


def test_pressure_skip_counter_progresses_then_forces_restart(harness: dict[str, Path]) -> None:
    """A permanently-loaded host would skip forever; after N consecutive
    pressure-skips the restart is FORCED through and the counter resets."""
    new_sha = _add_remote_commit(harness, "agents/voice/voice.py", "# pressure\n", "pressure")
    count_file = harness["state_dir"] / "pressure-skip-count-voice"
    sha_file = harness["state_dir"] / "last-voice-sha"
    # Defeat the guard's defang and force a pressure condition every run.
    extra = {
        "HAPAX_REBUILD_SKIP_GUARD": "0",
        "HAPAX_REBUILD_LOAD_MAX": "-1",
        "HAPAX_REBUILD_PRESSURE_SKIP_MAX": "3",
    }

    for expected in ("1", "2"):
        result = _run(harness, service="hapax-daimonion.service", extra_env=extra)
        assert result.returncode == 0, result.stdout + result.stderr
        assert count_file.read_text().strip() == expected
        assert not sha_file.exists(), "a pressure-skip must not advance the deploy SHA"
        assert _last_outcome(harness)["outcome"] == "deferred_pressure"

    # Third run hits the cap → force the restart through, reset the counter.
    result = _run(harness, service="hapax-daimonion.service", extra_env=extra)
    assert result.returncode == 0, result.stdout + result.stderr
    log = harness["log_file"].read_text()
    assert "systemctl --user restart hapax-daimonion.service" in log, "forced restart must fire"
    assert not count_file.exists(), "counter must reset after a forced restart"
    assert sha_file.read_text().strip() == new_sha


def test_high_swap_pct_env_no_longer_pressure_skips_restart(harness: dict[str, Path]) -> None:
    """High zram/swap fullness alone must not block rebuild restarts."""
    new_sha = _add_remote_commit(harness, "agents/voice/voice.py", "# swap\n", "swap")
    fake_meminfo = harness["state_dir"] / "meminfo"
    fake_memory_psi = harness["state_dir"] / "memory-psi"
    fake_meminfo.write_text(
        "MemTotal: 134217728 kB\n"
        "MemAvailable: 70254592 kB\n"
        "SwapTotal: 33554432 kB\n"
        "SwapFree: 0 kB\n"
    )
    fake_memory_psi.write_text(
        "some avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
        "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
    )

    result = _run(
        harness,
        service="hapax-daimonion.service",
        extra_env={
            "HAPAX_REBUILD_SKIP_GUARD": "0",
            "HAPAX_REBUILD_LOAD_MAX": "999",
            "HAPAX_REBUILD_SWAP_PCT_MAX": "0",
            "HAPAX_REBUILD_MEMINFO_PATH": str(fake_meminfo),
            "HAPAX_REBUILD_MEMORY_PSI_PATH": str(fake_memory_psi),
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    log = harness["log_file"].read_text()
    assert "systemctl --user restart hapax-daimonion.service" in log
    assert (harness["state_dir"] / "last-voice-sha").read_text().strip() == new_sha


def test_memory_psi_pressure_skips_restart(harness: dict[str, Path]) -> None:
    _add_remote_commit(harness, "agents/voice/voice.py", "# psi\n", "psi")
    fake_meminfo = harness["state_dir"] / "meminfo"
    fake_memory_psi = harness["state_dir"] / "memory-psi"
    fake_meminfo.write_text(
        "MemTotal: 134217728 kB\n"
        "MemAvailable: 70254592 kB\n"
        "SwapTotal: 33554432 kB\n"
        "SwapFree: 0 kB\n"
    )
    fake_memory_psi.write_text(
        "some avg10=42.00 avg60=0.00 avg300=0.00 total=0\n"
        "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
    )

    result = _run(
        harness,
        service="hapax-daimonion.service",
        extra_env={
            "HAPAX_REBUILD_SKIP_GUARD": "0",
            "HAPAX_REBUILD_LOAD_MAX": "999",
            "HAPAX_REBUILD_MEMINFO_PATH": str(fake_meminfo),
            "HAPAX_REBUILD_MEMORY_PSI_PATH": str(fake_memory_psi),
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert _last_outcome(harness)["outcome"] == "deferred_pressure"
    assert "memory-psi-some-avg10=42.00%" in result.stderr


def test_pressure_skip_counter_resets_on_normal_restart(harness: dict[str, Path]) -> None:
    """A successful non-pressure restart clears any stale consecutive-skip count
    so the cap only ever measures *consecutive* skips."""
    _add_remote_commit(harness, "agents/voice/voice.py", "# normal\n", "normal")
    count_file = harness["state_dir"] / "pressure-skip-count-voice"
    count_file.write_text("2")

    # Harness default _run sets HAPAX_REBUILD_SKIP_GUARD=1 → no pressure → restart.
    result = _run(harness, service="hapax-daimonion.service")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "systemctl --user restart hapax-daimonion.service" in harness["log_file"].read_text()
    assert not count_file.exists(), "a successful non-pressure restart must reset the counter"


def test_deploy_staleness_alarm_fires_when_receipt_lags(harness: dict[str, Path]) -> None:
    """When the post-merge-deploy receipt lags origin/main beyond the threshold,
    rebuild-service ntfys a high-priority staleness alarm."""
    seed = _rev_parse(harness["canonical"], "HEAD")
    new_sha = _add_remote_commit(harness, "logos/api.py", "# advance\n", "advance")
    assert new_sha != seed
    receipt = harness["tmp_path"] / "last-deployed-sha"
    receipt.write_text(seed + "\n")
    extra = {
        "HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH": str(receipt),
        "HAPAX_REBUILD_DEPLOY_STALENESS_SEC": "0",
    }

    result = _run(harness, service="hapax-daimonion.service", extra_env=extra)
    assert result.returncode == 0, result.stdout + result.stderr

    log = harness["log_file"].read_text()
    assert "post-merge-deploy STALE" in log, "staleness alarm must fire when the receipt lags"
    # The alarm is throttled per stalled SHA — a notified-state file is written.
    assert (harness["state_dir"] / "post-merge-deploy-lag-notified-sha").exists()


def test_deploy_staleness_alarm_silent_when_caught_up(harness: dict[str, Path]) -> None:
    """No alarm when the receipt equals origin/main, and the lag state clears."""
    new_sha = _add_remote_commit(harness, "logos/api.py", "# advance\n", "advance")
    receipt = harness["tmp_path"] / "last-deployed-sha"
    receipt.write_text(new_sha + "\n")
    lag_since = harness["state_dir"] / "post-merge-deploy-lag-since"
    lag_since.write_text("1")  # stale lag state that a caught-up run must clear
    extra = {
        "HAPAX_POST_MERGE_LAST_DEPLOYED_SHA_PATH": str(receipt),
        "HAPAX_REBUILD_DEPLOY_STALENESS_SEC": "0",
    }

    result = _run(harness, service="hapax-daimonion.service", extra_env=extra)
    assert result.returncode == 0, result.stdout + result.stderr

    log = harness["log_file"].read_text()
    assert "post-merge-deploy STALE" not in log
    assert not lag_since.exists(), "a caught-up run must clear the lag-since state"
