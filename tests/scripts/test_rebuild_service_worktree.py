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
            systemctl, curl, logger       -- PATH-shadowing fakes that record
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
    for name in ("systemctl", "curl", "logger"):
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
            # Don't actually try to hit ntfy.
            "NTFY_BASE_URL": "http://127.0.0.1:0",
        }
    )
    return subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)


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
