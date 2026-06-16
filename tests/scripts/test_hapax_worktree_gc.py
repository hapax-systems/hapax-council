"""Tests for stale Hapax worktree garbage collection."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-worktree-gc.sh"
SERVICE = REPO_ROOT / "systemd" / "units" / "hapax-worktree-gc.service"
TIMER = REPO_ROOT / "systemd" / "units" / "hapax-worktree-gc.timer"
PRESET = REPO_ROOT / "systemd" / "user-preset.d" / "hapax.preset"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, path: str, body: str, message: str) -> None:
    file_path = repo / path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(body, encoding="utf-8")
    _git(repo, "add", path)
    _git(repo, "commit", "-m", message)


def _age_path(path: Path, *, now: int, seconds_old: int) -> None:
    timestamp = now - seconds_old
    os.utime(path, (timestamp, timestamp))


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "hapax-council"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-b", "main"], check=True)
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test User")
    _commit(repo, "README.md", "# test\n", "seed")
    return repo


def test_removes_old_clean_merged_worktrees_and_alerts_unmerged(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    now = int(time.time())

    merged = tmp_path / "hapax-council--merged-clean"
    dirty = tmp_path / "hapax-council--merged-dirty"
    unmerged = tmp_path / "hapax-council--unmerged"

    _git(repo, "branch", "merged-clean", "main")
    _git(repo, "worktree", "add", str(merged), "merged-clean")

    _git(repo, "branch", "merged-dirty", "main")
    _git(repo, "worktree", "add", str(dirty), "merged-dirty")
    (dirty / "local.txt").write_text("not committed\n", encoding="utf-8")

    _git(repo, "branch", "unmerged", "main")
    _git(repo, "worktree", "add", str(unmerged), "unmerged")
    _commit(unmerged, "feature.txt", "not merged\n", "unmerged change")

    _age_path(merged, now=now, seconds_old=49 * 3600)
    _age_path(dirty, now=now, seconds_old=49 * 3600)
    _age_path(unmerged, now=now, seconds_old=8 * 24 * 3600)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl_log = tmp_path / "curl.log"
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(
        f"""#!/usr/bin/env bash
for arg in "$@"; do
  printf '%s\\n' "$arg" >> {curl_log}
done
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--repo",
            str(repo),
            "--base-ref",
            "main",
            "--no-fetch",
            "--now",
            str(now),
            "--ntfy-url",
            "http://ntfy.test/hapax-worktree-gc",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert not merged.exists()
    assert dirty.exists()
    assert unmerged.exists()
    assert "removable" in result.stdout
    assert "merged-clean" in result.stdout
    assert "removed" in result.stdout
    assert "stale_unmerged=1" in result.stdout

    alert = curl_log.read_text(encoding="utf-8")
    assert "Hapax stale unmerged worktrees" in alert
    assert "hapax-council--unmerged" in alert
    assert "not merged into main" in alert


def _make_release_worktree(tmp_path: Path, repo: Path, sha_name: str) -> Path:
    """Add a detached release worktree under a source-activation releases dir."""
    release_dir = tmp_path / "cache" / "source-activation" / "releases" / sha_name
    release_dir.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "--detach", str(release_dir), "main")
    return release_dir


def _write_unrelated_current_json(tmp_path: Path) -> Path:
    """current.json retaining SHAs unrelated to the test release."""
    current = tmp_path / "current.json"
    current.write_text(
        '{"active_source_path": "/x/releases/aaaaaaaa", '
        '"active_source_head": "bbbbbbbb", '
        '"candidate_source_path": "/x/releases/cccccccc"}\n',
        encoding="utf-8",
    )
    return current


def _run_gc(repo: Path, now: int, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--repo",
            str(repo),
            "--base-ref",
            "main",
            "--no-fetch",
            "--now",
            str(now),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


@contextmanager
def _live_process(argv: list[str], cwd: Path) -> Iterator[subprocess.Popen[bytes]]:
    proc = subprocess.Popen(argv, cwd=cwd)
    try:
        yield proc
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_refuses_release_dir_with_live_pid_cwd(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    now = int(time.time())
    release = _make_release_worktree(tmp_path, repo, "deadbeef1234")
    _age_path(release, now=now, seconds_old=49 * 3600)

    env = os.environ.copy()
    env["HAPAX_SOURCE_ACTIVATION_CURRENT"] = str(_write_unrelated_current_json(tmp_path))

    with _live_process(["sleep", "300"], cwd=release):
        result = _run_gc(repo, now, env)

    assert result.returncode == 0, result.stderr
    assert release.exists()
    assert "refuse live release" in result.stdout
    assert "(cwd)" in result.stdout
    assert "live_refused=1" in result.stdout


def test_refuses_release_dir_with_live_pid_exe(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    now = int(time.time())
    release = _make_release_worktree(tmp_path, repo, "deadbeef5678")

    sleep_bin = shutil.which("sleep")
    assert sleep_bin is not None
    release_sleep = release / "hapax-test-sleep"
    shutil.copy(sleep_bin, release_sleep)
    release_sleep.chmod(0o755)
    _age_path(release, now=now, seconds_old=49 * 3600)

    env = os.environ.copy()
    env["HAPAX_SOURCE_ACTIVATION_CURRENT"] = str(_write_unrelated_current_json(tmp_path))

    # cwd outside the release: only /proc/<pid>/exe references it.
    with _live_process([str(release_sleep), "300"], cwd=tmp_path):
        result = _run_gc(repo, now, env)

    assert result.returncode == 0, result.stderr
    assert release.exists()
    assert "refuse live release" in result.stdout
    assert "(exe)" in result.stdout
    assert "live_refused=1" in result.stdout


def test_removes_stale_release_dir_without_live_pids(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    now = int(time.time())
    release = _make_release_worktree(tmp_path, repo, "deadbeef9abc")
    _age_path(release, now=now, seconds_old=49 * 3600)

    env = os.environ.copy()
    env["HAPAX_SOURCE_ACTIVATION_CURRENT"] = str(_write_unrelated_current_json(tmp_path))

    result = _run_gc(repo, now, env)

    assert result.returncode == 0, result.stderr
    assert not release.exists()
    assert "removed release" in result.stdout
    assert "live_refused=0" in result.stdout


def test_refuses_merged_branch_worktree_with_live_pid_cwd(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    now = int(time.time())

    merged = tmp_path / "hapax-council--merged-live"
    _git(repo, "branch", "merged-live", "main")
    _git(repo, "worktree", "add", str(merged), "merged-live")
    _age_path(merged, now=now, seconds_old=49 * 3600)

    env = os.environ.copy()

    with _live_process(["sleep", "300"], cwd=merged):
        result = _run_gc(repo, now, env)

    assert result.returncode == 0, result.stderr
    assert merged.exists()
    assert "refuse live worktree" in result.stdout
    assert "live_refused=1" in result.stdout


def test_worktree_gc_systemd_timer_is_installable_and_six_hourly() -> None:
    service = SERVICE.read_text(encoding="utf-8")
    timer = TIMER.read_text(encoding="utf-8")
    preset = PRESET.read_text(encoding="utf-8")

    assert "Type=oneshot" in service
    assert (
        "scripts/hapax-worktree-gc.sh --repo %h/.cache/hapax/source-activation/worktree" in service
    )
    assert "WorkingDirectory=%h/.cache/hapax/source-activation/worktree" in service
    assert "OnUnitActiveSec=6h" in timer
    assert "Persistent=true" in timer
    assert "WantedBy=timers.target" in timer
    assert "enable hapax-worktree-gc.timer" in preset


def test_detection_failure_preserves_release_dir(tmp_path: Path) -> None:
    """Review #4094-1/2: when /proc scanning itself FAILS, the guard must
    fail CLOSED — the stale release dir survives, witnessed as a refusal."""
    repo = _make_repo(tmp_path)
    now = int(time.time())
    release = _make_release_worktree(tmp_path, repo, "deadbeefcafe")
    _age_path(release, now=now, seconds_old=49 * 3600)

    env = os.environ.copy()
    env["HAPAX_SOURCE_ACTIVATION_CURRENT"] = str(_write_unrelated_current_json(tmp_path))
    env["HAPAX_WORKTREE_GC_PROC_ROOT"] = str(tmp_path / "nonexistent-proc")

    result = _run_gc(repo, now, env)

    assert result.returncode == 0, result.stderr
    assert release.exists(), "detection failure must NEVER free a dir"
    assert "DETECTION-FAILED" in result.stdout
    assert "live_refused=1" in result.stdout


def test_deletes_merged_local_branch_ref_after_worktree_removal(tmp_path: Path) -> None:
    """Regression for the refs/heads/ prefix bug (codex-1, #4142): ``git branch -d`` was passed the full
    ``refs/heads/<name>`` ref (from ``worktree list --porcelain``) instead of the bare branch name, so the
    delete silently failed and the merged LOCAL BRANCH REF was never reaped even after its worktree was
    removed. Asserts the ref is actually gone."""
    repo = _make_repo(tmp_path)
    now = int(time.time())

    wt = tmp_path / "hapax-council--merged-feature"
    _git(repo, "branch", "merged-feature", "main")
    _git(repo, "worktree", "add", str(wt), "merged-feature")
    _age_path(wt, now=now, seconds_old=49 * 3600)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_curl = bin_dir / "curl"
    fake_curl.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_curl.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--repo",
            str(repo),
            "--base-ref",
            "main",
            "--no-fetch",
            "--now",
            str(now),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert not wt.exists()  # the merged worktree is removed
    # ...and the orphaned LOCAL BRANCH REF is actually reaped (the bug: it survived the removal).
    assert _git(repo, "branch", "--list", "merged-feature") == ""
    assert "deleted merged local branch merged-feature" in result.stdout


def _stub_bin(tmp_path: Path, *, gh_merged_pr: str | None) -> dict[str, str]:
    """A PATH with stub ``curl`` (ntfy) and ``gh``. ``gh pr list ... --state merged``
    echoes ``gh_merged_pr`` (empty/None ⇒ no merged PR)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "curl").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (bin_dir / "curl").chmod(0o755)
    merged = gh_merged_pr or ""
    (bin_dir / "gh").write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        f'  *"pr list"*"--state merged"*) printf "%s" "{merged}" ;;\n'
        "  *) ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (bin_dir / "gh").chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return env


def _add_squash_merged_branch(repo: Path, tmp_path: Path, now: int) -> Path:
    """A worktree whose branch has a commit NOT in main (so ancestry MISSES it) and
    looks squash-merged: it tracked origin but its origin ref is gone (pruned)."""
    wt = tmp_path / "hapax-council--squashed"
    _git(repo, "branch", "squashed", "main")
    _git(repo, "worktree", "add", str(wt), "squashed")
    _commit(wt, "feature.txt", "squashed away\n", "work that was squash-merged")
    # tracked origin, but no refs/remotes/origin/squashed (auto-deleted + pruned on merge)
    _git(repo, "config", "branch.squashed.remote", "origin")
    _git(repo, "config", "branch.squashed.merge", "refs/heads/squashed")
    _age_path(wt, now=now, seconds_old=49 * 3600)
    return wt


def test_squash_merged_branch_is_reaped_when_gh_confirms_merge(tmp_path: Path) -> None:
    """The council squash-merges, so ancestry-detection + ``git branch -d`` silently
    miss every merged branch. A branch that tracked origin, lost its remote ref, and
    has an authoritative merged PR is reaped with ``-D``."""
    repo = _make_repo(tmp_path)
    now = int(time.time())
    wt = _add_squash_merged_branch(repo, tmp_path, now)
    # sanity: ancestry MUST miss it (else we'd not be exercising the squash arm)
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", "squashed", "main"],
            capture_output=True,
        ).returncode
        != 0
    )

    result = _run_gc(repo, now, _stub_bin(tmp_path, gh_merged_pr="999"))

    assert result.returncode == 0, result.stderr
    assert not wt.exists()  # squash-merged worktree reaped
    assert _git(repo, "branch", "--list", "squashed") == ""  # local branch ref reaped
    assert "deleted merged local branch squashed (-D)" in result.stdout


def test_squash_branch_not_reaped_when_gh_reports_no_merge(tmp_path: Path) -> None:
    """Safety: a branch that lost its remote ref but has NO merged PR (e.g. a closed
    PR whose remote was deleted by hand) is NOT force-deleted — it is treated as
    unmerged and alerted, never reaped."""
    repo = _make_repo(tmp_path)
    now = int(time.time())
    wt = _add_squash_merged_branch(repo, tmp_path, now)

    result = _run_gc(repo, now, _stub_bin(tmp_path, gh_merged_pr=None))

    assert result.returncode == 0, result.stderr
    assert wt.exists()  # NOT reaped (unconfirmed)
    assert _git(repo, "branch", "--list", "squashed").strip().endswith("squashed")
    assert "deleted merged local branch squashed" not in result.stdout


def test_fetch_prune_drops_stale_remote_tracking_ref(tmp_path: Path) -> None:
    """The fetch was widened to ``git fetch --prune`` so a branch GitHub auto-deleted
    on merge clears its stale ``origin/<branch>`` mirror each cycle. Verifies the
    prune actually happens (the prior fetch left stale mirrors to accumulate)."""
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True)
    repo = _make_repo(tmp_path)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "origin", "main")
    _git(repo, "push", "origin", "main:refs/heads/feature")  # a remote branch
    _git(repo, "fetch", "origin")
    assert _git(repo, "rev-parse", "--verify", "refs/remotes/origin/feature") != ""

    # GitHub "auto-deletes on merge": drop the branch from the remote.
    subprocess.run(["git", "-C", str(bare), "branch", "-D", "feature"], check=True)

    env = _stub_bin(tmp_path, gh_merged_pr=None)
    # run GC WITHOUT --no-fetch so the fetch --prune path executes
    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--repo",
            str(repo),
            "--base-ref",
            "main",
            "--now",
            str(int(time.time())),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    # the stale remote-tracking ref is pruned
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "refs/remotes/origin/feature"],
            capture_output=True,
        ).returncode
        != 0
    )
