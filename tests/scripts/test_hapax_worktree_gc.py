"""Tests for stale Hapax worktree garbage collection."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-worktree-gc.sh"
SERVICE = REPO_ROOT / "systemd" / "units" / "hapax-worktree-gc.service"
TIMER = REPO_ROOT / "systemd" / "units" / "hapax-worktree-gc.timer"
PRESET = REPO_ROOT / "systemd" / "user-preset.d" / "hapax.preset"


@pytest.fixture(autouse=True)
def _force_legacy_inference_sweep(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Force gc.sh's LEGACY pure-inference sweep (the explicit opt-out) for every case here.

    In production the registry-governed pre-pass is AUTHORITATIVE over the age+clean+merged
    inference -- it registers every worktree, protects active/registered ones, and reaps
    abandoned ones by explicit lifecycle status, so with it enabled (the default) it would
    shadow the inference these cases assert on (a fresh test worktree classifies ``active`` and
    is protected from the legacy reap). That registry+legacy interaction has its own coverage in
    tests/shared/test_worktree_registry.py (the real-gc.sh integration tests). Setting this in
    os.environ means every ``env = os.environ.copy()`` below inherits it, regardless of how each
    case invokes gc.sh.
    """
    monkeypatch.setenv("HAPAX_WORKTREE_GC_REGISTRY", "0")
    monkeypatch.setenv("HAPAX_WORKTREE_GC_REAP_ORPHANS", "0")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    private_home = tmp_path / "home"
    private_home.mkdir()
    monkeypatch.setenv("HOME", str(private_home))
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(private_home / "registry"))
    monkeypatch.setenv("HAPAX_WORKTREE_GC_UNIT_DIRS", str(private_home / "units"))
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    monkeypatch.setenv("HAPAX_WORKTREE_GC_PROC_ROOT", str(proc_root))
    monkeypatch.setenv(
        "HAPAX_WORKTREE_GC_RELEASE_ROOTS", str(tmp_path / "cache/source-activation/releases")
    )
    # Actual source bytes; fake incident/reaper/registry peers.
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    monkeypatch.setenv("PATH", f"{scripts}:{os.environ['PATH']}")
    copy = scripts / SCRIPT.name
    shutil.copyfile(SCRIPT, copy)
    for name in (
        "curl",
        "systemctl",
        "hapax-alert",
        "hapax-orphan-spawn-reaper.py",
        "hapax-worktree-register",
    ):
        peer = scripts / name
        peer.write_text(
            "#!/bin/sh\nexit 0\n"
            if name in ("curl", "systemctl", "hapax-alert")
            else "#!/bin/sh\necho unexpected-peer >&2\nexit 99\n"
        )
        peer.chmod(0o755)
    monkeypatch.setattr(sys.modules[__name__], "SCRIPT", copy)


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
            "--release-keep",
            "0",
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
            "--release-keep",
            "0",
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
    link = Path(os.environ["HAPAX_WORKTREE_GC_PROC_ROOT"]) / str(proc.pid)
    link.symlink_to(Path("/proc") / str(proc.pid))
    try:
        yield proc
    finally:
        proc.kill()
        proc.wait(timeout=10)
        link.unlink()


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


def _curl_env(tmp_path: Path) -> dict[str, str]:
    """A PATH with a no-op ``curl`` so the ntfy alert path does not hit the network.
    (No ``gh`` stub — squash detection is GIT-ONLY; the deploy unit has no GH_TOKEN.)"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "curl").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (bin_dir / "curl").chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return env


def _make_repo_with_remote(tmp_path: Path) -> tuple[Path, Path]:
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True)
    repo = _make_repo(tmp_path)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "origin", "main")
    _git(repo, "fetch", "origin")
    return repo, bare


def _add_remote_deleted_branch(
    repo: Path,
    bare: Path,
    tmp_path: Path,
    now: int,
    name: str = "squashed",
    *,
    land_on_main: bool = True,
) -> Path:
    """A REAL squash-merge signature: a branch pushed to origin (so it tracks), with a
    commit NOT an ancestor of main (ancestry MISSES it), whose remote ref GitHub
    auto-deleted on merge — simulated by deleting it from the bare remote + pruning.

    ``land_on_main`` controls whether the branch's CONTENT actually reaches main (the
    squash commit). True = a genuine squash-merge: main carries the same net change,
    so content-equivalence holds and the branch is reapable. False = the data-loss
    trap: the remote vanished (closed-without-merge / manual delete) but the unique
    work is NOT in main, so it must be PRESERVED, never force-deleted."""
    wt = tmp_path / f"hapax-council--{name}"
    _git(repo, "branch", name, "main")
    _git(repo, "worktree", "add", str(wt), name)
    _commit(wt, "feature.txt", "squashed away\n", "work that was squash-merged")
    _git(wt, "push", "-u", "origin", name)  # real tracking + real origin/<name>
    if land_on_main:
        # The squash commit lands the SAME net content on main, so the branch's work
        # is provably present in base (content-equivalence) — a true merge.
        _commit(repo, "feature.txt", "squashed away\n", f"squash-merge of {name}")
        _git(repo, "push", "origin", "main")
    subprocess.run(["git", "-C", str(bare), "branch", "-D", name], check=True)  # auto-delete
    _git(repo, "fetch", "--prune", "origin")  # origin/<name> pruned; tracking config remains
    _age_path(wt, now=now, seconds_old=49 * 3600)
    return wt


def test_squash_merged_branch_is_reaped_via_remote_delete_signal(tmp_path: Path) -> None:
    """The council squash-merges, so ancestry-detection + ``git branch -d`` silently
    miss every merged branch. A branch whose remote was auto-deleted on merge (tracked
    origin + origin ref pruned) is detected git-only and reaped with ``-D``."""
    repo, bare = _make_repo_with_remote(tmp_path)
    now = int(time.time())
    wt = _add_remote_deleted_branch(repo, bare, tmp_path, now)
    # sanity: ancestry MUST miss it (else we'd not be exercising the remote-delete arm)
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", "squashed", "main"],
            capture_output=True,
        ).returncode
        != 0
    )

    result = _run_gc(repo, now, _curl_env(tmp_path))

    assert result.returncode == 0, result.stderr
    assert not wt.exists()  # squash-merged worktree reaped
    assert _git(repo, "branch", "--list", "squashed") == ""  # local branch ref reaped
    assert "deleted merged local branch squashed" in result.stdout


def test_remote_deleted_but_unmerged_content_is_preserved(tmp_path: Path) -> None:
    """DATA-LOSS guard (4/4 review block, #4142): a branch that was pushed and then had
    its remote deleted WITHOUT the work landing in main — a closed-without-merge PR or a
    manual ``git push origin --delete`` — has byte-identical local state to a real
    squash-merge (tracks origin, origin/<name> gone), but its commits are REAL unmerged
    work. The remote-delete signal alone would force-delete it with ``-D``. The required
    content-equivalence guard (branch_content_merged) sees the work is NOT in base and
    PRESERVES the branch."""
    repo, bare = _make_repo_with_remote(tmp_path)
    now = int(time.time())
    wt = _add_remote_deleted_branch(repo, bare, tmp_path, now, name="orphaned", land_on_main=False)
    # sanity: ancestry misses it AND its content is genuinely absent from main
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", "orphaned", "main"],
            capture_output=True,
        ).returncode
        != 0
    )

    result = _run_gc(repo, now, _curl_env(tmp_path))

    assert result.returncode == 0, result.stderr
    assert wt.exists()  # PRESERVED — remote vanished but the work is not in base
    assert _git(repo, "branch", "--list", "orphaned").strip().endswith("orphaned")
    assert "deleted merged local branch orphaned" not in result.stdout


def test_branch_with_live_remote_not_reaped(tmp_path: Path) -> None:
    """Safety: a non-ancestor branch whose origin ref STILL EXISTS (not merged/deleted)
    is NOT reaped — the remote-delete signal requires the origin ref to be gone."""
    repo, _bare = _make_repo_with_remote(tmp_path)
    now = int(time.time())
    wt = tmp_path / "hapax-council--live"
    _git(repo, "branch", "live", "main")
    _git(repo, "worktree", "add", str(wt), "live")
    _commit(wt, "f.txt", "wip\n", "unmerged wip")
    _git(wt, "push", "-u", "origin", "live")  # origin/live EXISTS (not deleted)
    _age_path(wt, now=now, seconds_old=49 * 3600)

    result = _run_gc(repo, now, _curl_env(tmp_path))

    assert result.returncode == 0, result.stderr
    assert wt.exists()  # NOT reaped — remote still present
    assert _git(repo, "branch", "--list", "live").strip().endswith("live")


def test_local_only_branch_not_reaped(tmp_path: Path) -> None:
    """Safety: a never-pushed local branch has no tracking config, so the remote-delete
    signal can never match — it is judged by ancestry alone and survives."""
    repo, _bare = _make_repo_with_remote(tmp_path)
    now = int(time.time())
    wt = tmp_path / "hapax-council--localonly"
    _git(repo, "branch", "localonly", "main")
    _git(repo, "worktree", "add", str(wt), "localonly")
    _commit(wt, "f.txt", "local\n", "never pushed")
    _age_path(wt, now=now, seconds_old=49 * 3600)

    result = _run_gc(repo, now, _curl_env(tmp_path))

    assert result.returncode == 0, result.stderr
    assert wt.exists()  # NOT reaped — no tracking config, not an ancestor
    assert _git(repo, "branch", "--list", "localonly").strip().endswith("localonly")


def test_branch_tracking_other_ref_not_reaped(tmp_path: Path) -> None:
    """DATA-LOSS guard (gemini-2): a branch that tracks origin/main (e.g.
    `git checkout -b x origin/main`) has remote=origin but merge=refs/heads/main and
    NO origin/x ref. Without the merge-ref guard the absent origin/x would be read as
    "deleted" and the branch force-deleted with `-D`, destroying live unmerged work.
    It must NOT be reaped."""
    repo, _bare = _make_repo_with_remote(tmp_path)
    now = int(time.time())
    wt = tmp_path / "hapax-council--tracksmain"
    _git(repo, "branch", "tracksmain", "main")
    _git(repo, "worktree", "add", str(wt), "tracksmain")
    _commit(wt, "f.txt", "real unmerged work\n", "tracks origin/main, never pushed as itself")
    # the dangerous config: tracks origin/main, not origin/tracksmain
    _git(repo, "config", "branch.tracksmain.remote", "origin")
    _git(repo, "config", "branch.tracksmain.merge", "refs/heads/main")
    _age_path(wt, now=now, seconds_old=49 * 3600)

    result = _run_gc(repo, now, _curl_env(tmp_path))

    assert result.returncode == 0, result.stderr
    assert wt.exists()  # NOT reaped — its upstream is origin/main, not its own ref
    assert _git(repo, "branch", "--list", "tracksmain").strip().endswith("tracksmain")


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

    env = _curl_env(tmp_path)
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


# --- Release retention: count cap, no --force, stray-mode class, maps/unit guards ---
#
# The 2026-09-25 appendix reap found 103 releases (998 GiB logical) because the timer was never
# enabled there. It also found that the release pass used `worktree remove --force` (which would
# silently discard a real diff), and that its live guard read only cwd/exe (a daemon importing
# from a release .venv is visible only in /proc/<pid>/maps: the venv's python symlinks outside it).


def _run_gc_args(
    repo: Path, now: int, env: dict[str, str], *extra: str
) -> subprocess.CompletedProcess[str]:
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
            "--clean-age-seconds",
            "0",
            # empty URL: send_ntfy_alert returns before curl AND before hapax-alert
            # --record-only, so refusal paths post nothing and record no incident
            "--ntfy-url",
            "",
            *extra,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def _release_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HAPAX_SOURCE_ACTIVATION_CURRENT"] = str(_write_unrelated_current_json(tmp_path))
    units = tmp_path / "units"
    units.mkdir(exist_ok=True)
    env["HAPAX_WORKTREE_GC_UNIT_DIRS"] = str(units)
    # The orphan spawn-tree pre-pass acts on the REAL host's tmux/proc, not the test repo.
    env["HAPAX_WORKTREE_GC_REAP_ORPHANS"] = "0"
    return env


def _young_releases(tmp_path: Path, repo: Path, now: int, count: int) -> list[Path]:
    """`count` releases, all younger than the 48 h rule; index 0 is the OLDEST."""
    releases = []
    for i in range(count):
        release = _make_release_worktree(tmp_path, repo, f"cafe{i:08d}")
        _age_path(release, now=now, seconds_old=(count - i) * 600)
        releases.append(release)
    return releases


def test_release_count_cap_reaps_young_releases_beyond_keep(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    now = int(time.time())
    releases = _young_releases(tmp_path, repo, now, 7)

    result = _run_gc_args(repo, now, _release_env(tmp_path), "--release-keep", "5")

    assert result.returncode == 0, result.stderr
    assert not releases[0].exists()
    assert not releases[1].exists()
    for kept in releases[2:]:
        assert kept.exists(), kept
    assert "removed=2" in result.stdout


def test_release_count_cap_default_keeps_five(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    now = int(time.time())
    releases = _young_releases(tmp_path, repo, now, 6)

    result = _run_gc_args(repo, now, _release_env(tmp_path))

    assert result.returncode == 0, result.stderr
    assert not releases[0].exists()
    assert all(r.exists() for r in releases[1:])


def test_release_count_cap_never_removes_live_or_locked_over_cap(tmp_path: Path) -> None:
    """The unsafe case of the cap: a release ranked over the cap is still refused when it
    is locked or live."""
    repo = _make_repo(tmp_path)
    now = int(time.time())
    releases = _young_releases(tmp_path, repo, now, 8)
    _git(repo, "worktree", "lock", "--reason", "hook substrate pin", str(releases[0]))

    with _live_process(["sleep", "300"], cwd=releases[1]):
        result = _run_gc_args(repo, now, _release_env(tmp_path), "--release-keep", "5")

    assert result.returncode == 0, result.stderr
    assert releases[0].exists(), "locked release over the cap must survive"
    assert releases[1].exists(), "live release over the cap must survive"
    assert not releases[2].exists()
    assert all(r.exists() for r in releases[3:])
    assert "skip locked release" in result.stdout
    assert "refuse live release" in result.stdout


def test_release_retained_sha_is_neither_counted_nor_removed(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    now = int(time.time())
    releases = _young_releases(tmp_path, repo, now, 5)
    active = _make_release_worktree(tmp_path, repo, "aaaaaaaa")
    # NEWEST of all: if the retained release consumed a cap slot it would rank first and
    # push the oldest of the five over the cap.
    _age_path(active, now=now, seconds_old=60)

    result = _run_gc_args(repo, now, _release_env(tmp_path), "--release-keep", "5")

    assert result.returncode == 0, result.stderr
    assert active.exists(), "active release (current.json) must never be reaped"
    assert all(r.exists() for r in releases), "retained release must not consume a cap slot"
    assert "removed=0" in result.stdout


def test_release_mode_only_diff_is_restored_then_removed_without_force(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _commit(repo, "scripts/tool", "#!/bin/sh\necho hi\n", "tool, committed 644")
    now = int(time.time())
    release = _make_release_worktree(tmp_path, repo, "deadbeefmode")
    (release / "scripts" / "tool").chmod(0o755)
    _age_path(release, now=now, seconds_old=49 * 3600)

    result = _run_gc_args(repo, now, _release_env(tmp_path), "--release-keep", "0")

    assert result.returncode == 0, result.stderr
    assert not release.exists()
    assert "restored stray mode" in result.stdout
    assert "scripts/tool" in result.stdout
    assert "removed release" in result.stdout


def test_release_content_diff_is_refused_never_forced(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _commit(repo, "scripts/tool", "#!/bin/sh\necho hi\n", "tool")
    now = int(time.time())
    release = _make_release_worktree(tmp_path, repo, "deadbeefedit")
    tool = release / "scripts" / "tool"
    tool.write_text("#!/bin/sh\necho edited\n", encoding="utf-8")
    tool.chmod(0o755)  # mode AND content: not the stray-mode class
    _age_path(release, now=now, seconds_old=49 * 3600)

    result = _run_gc_args(repo, now, _release_env(tmp_path), "--release-keep", "0")

    assert result.returncode == 0, result.stderr
    assert release.exists()
    assert tool.read_text(encoding="utf-8") == "#!/bin/sh\necho edited\n"
    assert "refuse dirty release" in result.stdout
    assert "removed=0" in result.stdout


def test_release_untracked_file_is_refused(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    now = int(time.time())
    release = _make_release_worktree(tmp_path, repo, "deadbeefuntr")
    (release / "notes.txt").write_text("someone's scratch\n", encoding="utf-8")
    _age_path(release, now=now, seconds_old=49 * 3600)

    result = _run_gc_args(repo, now, _release_env(tmp_path), "--release-keep", "0")

    assert result.returncode == 0, result.stderr
    assert release.exists()
    assert (release / "notes.txt").exists()
    assert "refuse dirty release" in result.stdout


def test_release_mode_only_dry_run_changes_nothing(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _commit(repo, "scripts/tool", "#!/bin/sh\necho hi\n", "tool")
    now = int(time.time())
    release = _make_release_worktree(tmp_path, repo, "deadbeefdry0")
    (release / "scripts" / "tool").chmod(0o755)
    _age_path(release, now=now, seconds_old=49 * 3600)

    result = _run_gc_args(repo, now, _release_env(tmp_path), "--dry-run", "--release-keep", "0")

    assert result.returncode == 0, result.stderr
    assert release.exists()
    assert os.access(release / "scripts" / "tool", os.X_OK), "dry-run must not restore modes"
    assert "dry-run would restore stray mode" in result.stdout


def test_refuses_release_mapped_by_live_process(tmp_path: Path) -> None:
    """cwd and exe are both outside the release; only /proc/<pid>/maps references it
    (the shape of a daemon importing .so files from a release .venv)."""
    repo = _make_repo(tmp_path)
    now = int(time.time())
    release = _make_release_worktree(tmp_path, repo, "deadbeefmaps")
    common = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    (common / "info").mkdir(parents=True, exist_ok=True)
    with (common / "info" / "exclude").open("a", encoding="utf-8") as fh:
        fh.write("lib.so\n")  # ignored, like a .venv file: the release stays clean
    blob = release / "lib.so"
    blob.write_bytes(b"\0" * 4096)
    _age_path(release, now=now, seconds_old=49 * 3600)

    mapper = (
        "import mmap, sys, time\n"
        "f = open(sys.argv[1], 'rb')\n"
        "m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)\n"
        "f.close()\n"
        "print('mapped', flush=True)\n"
        "time.sleep(300)\n"
    )
    proc = subprocess.Popen(
        ["python3", "-c", mapper, str(blob)], cwd=tmp_path, stdout=subprocess.PIPE
    )
    (Path(os.environ["HAPAX_WORKTREE_GC_PROC_ROOT"]) / str(proc.pid)).symlink_to(
        Path("/proc") / str(proc.pid)
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == b"mapped"
        result = _run_gc_args(repo, now, _release_env(tmp_path), "--release-keep", "0")
    finally:
        proc.kill()
        proc.wait(timeout=10)

    assert result.returncode == 0, result.stderr
    assert release.exists()
    assert "refuse live release" in result.stdout
    assert "(maps)" in result.stdout


def test_releases_only_mode_touches_nothing_but_releases(tmp_path: Path) -> None:
    """--releases-only runs the release pass alone: a merged, clean, stale branch worktree
    that the legacy sweep WOULD remove survives, the orphan and registry pre-passes do not
    run, and a stale release is still reaped."""
    repo = _make_repo(tmp_path)
    now = int(time.time())
    merged = tmp_path / "hapax-council--merged-clean"
    _git(repo, "branch", "merged-clean", "main")
    _git(repo, "worktree", "add", str(merged), "merged-clean")
    _age_path(merged, now=now, seconds_old=49 * 3600)
    release = _make_release_worktree(tmp_path, repo, "deadbeefonly")
    _age_path(release, now=now, seconds_old=49 * 3600)
    env = _release_env(tmp_path)
    env["HAPAX_WORKTREE_GC_REAP_ORPHANS"] = "1"  # would run, were the mode not honoured
    env["HAPAX_WORKTREE_GC_REGISTRY"] = "1"
    registry_dir = tmp_path / "registry"
    env["HAPAX_WORKTREE_REGISTRY_DIR"] = str(registry_dir)

    result = _run_gc_args(repo, now, env, "--releases-only", "--release-keep", "0")

    assert result.returncode == 0, result.stderr
    assert merged.exists(), "releases-only must not run the merged-worktree sweep"
    assert _git(repo, "branch", "--list", "merged-clean") != ""
    assert not release.exists()
    assert "orphan-reaper" not in result.stdout
    # the registry pre-pass's backfill would have written one record per worktree
    assert not registry_dir.exists() or not any(registry_dir.iterdir())
    assert "releases-only" in result.stdout


def test_releases_only_mode_via_environment(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    now = int(time.time())
    merged = tmp_path / "hapax-council--merged-env"
    _git(repo, "branch", "merged-env", "main")
    _git(repo, "worktree", "add", str(merged), "merged-env")
    _age_path(merged, now=now, seconds_old=49 * 3600)
    env = _release_env(tmp_path)
    env["HAPAX_WORKTREE_GC_RELEASES_ONLY"] = "1"

    result = _run_gc_args(repo, now, env)

    assert result.returncode == 0, result.stderr
    assert merged.exists()
    assert "releases-only" in result.stdout


def test_refuses_release_referenced_by_a_unit(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    now = int(time.time())
    release = _make_release_worktree(tmp_path, repo, "deadbeefunit")
    _age_path(release, now=now, seconds_old=49 * 3600)
    env = _release_env(tmp_path)
    unit = Path(env["HAPAX_WORKTREE_GC_UNIT_DIRS"]) / "hapax-example.service"
    unit.write_text(f"[Service]\nExecStart={release}/scripts/run\n", encoding="utf-8")

    result = _run_gc_args(repo, now, env, "--release-keep", "0")

    assert result.returncode == 0, result.stderr
    assert release.exists()
    assert "refuse unit-referenced release" in result.stdout
    assert "hapax-example.service" in result.stdout


@pytest.mark.parametrize("count", [3, 7])
def test_old_releases_keep_rollback_floor(tmp_path: Path, count: int) -> None:
    repo = _make_repo(tmp_path)
    now = int(time.time())
    releases = _young_releases(tmp_path, repo, now, count)
    for i, release in enumerate(releases):
        _age_path(release, now=now, seconds_old=(count - i + 3) * 86400)
    result = _run_gc_args(repo, now, _release_env(tmp_path), "--releases-only")
    assert result.returncode == 0, result.stderr
    assert [r.exists() for r in releases] == [False] * max(0, count - 5) + [True] * min(count, 5)


def test_release_only_preserves_unrelated_prunable_admin(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    other = tmp_path / "missing-lane"
    _git(repo, "worktree", "add", "--detach", str(other), "main")
    shutil.rmtree(other)
    admin = repo / ".git/worktrees/missing-lane"
    before = {p.name: p.read_bytes() for p in admin.iterdir() if p.is_file()}
    result = _run_gc_args(repo, int(time.time()), _release_env(tmp_path), "--releases-only")
    assert result.returncode == 0, result.stderr
    assert admin.exists()
    assert before == {p.name: p.read_bytes() for p in admin.iterdir() if p.is_file()}


def _fake_proc(pid: str = "999999") -> Path:
    proc = Path(os.environ["HAPAX_WORKTREE_GC_PROC_ROOT"]) / pid
    proc.mkdir()
    (proc / "fd").mkdir()
    (proc / "cwd").symlink_to("/elsewhere")
    (proc / "exe").symlink_to("/bin/sleep")
    (proc / "maps").write_text("")
    return proc


@pytest.mark.parametrize(
    "kind", ["fd", "deleted-fd", "alias-fd", "permission", "exit", "fd-exit", "sibling"]
)
def test_release_process_visibility(tmp_path: Path, kind: str) -> None:
    repo = _make_repo(tmp_path)
    release = _make_release_worktree(tmp_path, repo, "deadbeefproc")
    env = _release_env(tmp_path)
    proc = _fake_proc()
    target = release / "README.md"
    if kind == "alias-fd":
        alias = tmp_path / "alias"
        alias.symlink_to(release)
        target = alias / "README.md"
    if kind == "sibling":
        target = release.with_name(release.name + "-other") / "file"
    (proc / "fd/5").symlink_to(str(target) + (" (deleted)" if kind == "deleted-fd" else ""))
    if kind == "permission":
        (proc / "fd").chmod(0)
    elif kind == "exit":
        shutil.rmtree(proc)
        proc.symlink_to(tmp_path / "exited")  # listed PID disappears before stat
    elif kind == "fd-exit":
        wrapper = SCRIPT.parent / "python3"
        wrapper.write_text(
            f"#!{sys.executable}\nimport os,sys\noriginal=os.listdir\n"
            "def listing(path):\n r=original(path)\n"
            f" if str(path)=={str(proc / 'fd')!r}: os.unlink(str(path)+'/5')\n"
            " return r\nos.listdir=listing\nsys.argv=sys.argv[1:]\n"
            "exec(compile(sys.stdin.read(), '<stdin>', 'exec'))\n"
        )
        wrapper.chmod(0o755)
    try:
        result = _run_gc_args(repo, int(time.time()), env, "--releases-only", "--release-keep", "0")
    finally:
        if kind == "permission":
            (proc / "fd").chmod(0o700)
    assert result.returncode == 0, result.stderr
    keep = kind not in {"exit", "fd-exit", "sibling"}
    assert release.exists() == keep, result.stdout
    assert (
        "DETECTION-FAILED" if kind == "permission" else "(fd)" if keep else "removed release"
    ) in result.stdout


@pytest.mark.parametrize("registered", [True, False])
def test_partial_release_is_reported_and_never_ranked(tmp_path: Path, registered: bool) -> None:
    repo = _make_repo(tmp_path)
    now = int(time.time())
    healthy = _young_releases(tmp_path, repo, now, 5)
    name = (
        "8c0aaa53d436c2a973d745b1f767a27db2cb0b62"  # pragma: allowlist secret
        if registered
        else "3a2664d48fefce563e595e3eac0354988dfc0979"  # pragma: allowlist secret
    )
    partial = healthy[0].parent / name
    if registered:
        _git(repo, "worktree", "add", "--detach", str(partial), "main")
        (partial / ".git").unlink()
    else:
        partial.mkdir()
    payload = partial / "sole-data"
    payload.write_bytes(b"preserve me")
    _age_path(partial, now=now, seconds_old=0)
    result = _run_gc_args(repo, now, _release_env(tmp_path), "--releases-only")
    assert result.returncode == 0, result.stderr
    assert all(r.exists() for r in healthy)
    assert payload.read_bytes() == b"preserve me"
    assert str(partial.resolve()) in result.stdout
    assert ("partial" if registered else "unregistered") in result.stdout
    assert "hold release" in result.stdout


@pytest.mark.parametrize(
    "kind",
    [
        "pin",
        "claim",
        "publication",
        "unknown",
        "ignored",
        "unmerged",
        "active",
        "candidate",
        "current-unknown",
        "dropin",
        "unit-unknown",
    ],
)
def test_release_custody_holds(tmp_path: Path, kind: str) -> None:
    repo = _make_repo(tmp_path)
    release = _make_release_worktree(tmp_path, repo, "deadbeefhold")
    env = _release_env(tmp_path)
    cache = Path(env["HOME"]) / ".cache/hapax"
    cache.mkdir(parents=True)
    if kind == "pin":
        registry = Path(env["HAPAX_WORKTREE_REGISTRY_DIR"])
        registry.mkdir()
        (registry / "pin.json").write_text(json.dumps({"path": str(release), "pinned": True}))
    elif kind in {"claim", "publication", "unknown"}:
        parent = cache
        if kind == "publication":
            parent = (
                Path(env["HOME"])
                / ".local/share/hapax/claim-publications/gate0b-claim-publish-v1/example"
            )
            parent.mkdir(parents=True)
        (parent / "cc-claim-dispatch-example.json").write_text(
            "{"
            if kind == "unknown"
            else json.dumps({"source_path": str(release), "state": "applied"})
        )
    elif kind == "ignored":
        with (repo / ".git/info/exclude").open("a") as fh:
            fh.write("sole-data\n")
        (release / "sole-data").write_bytes(b"not regenerable")
    elif kind == "unmerged":
        _commit(release, "unmerged", "sole source\n", "unmerged source")
    elif kind in {"active", "candidate", "current-unknown"}:
        Path(env["HAPAX_SOURCE_ACTIVATION_CURRENT"]).write_text(
            "{" if kind == "current-unknown" else json.dumps({kind + "_source_path": str(release)})
        )
    else:
        unit = Path(env["HAPAX_WORKTREE_GC_UNIT_DIRS"]) / "example.service.d/override.conf"
        unit.parent.mkdir()
        unit.write_text(f"[Service]\nWorkingDirectory={release}\n")
        if kind == "unit-unknown":
            unit.chmod(0)
    try:
        result = _run_gc_args(repo, int(time.time()), env, "--releases-only", "--release-keep", "0")
    finally:
        if kind == "unit-unknown":
            unit.chmod(0o600)
    assert result.returncode == 0, result.stderr
    assert release.exists(), result.stdout
    assert "removed=0" in result.stdout
    assert any(word in result.stdout for word in ("hold", "refuse", "retain")), result.stdout


def test_scheduler_exact_release_only_argv() -> None:
    import configparser
    import shlex

    unit = configparser.ConfigParser(interpolation=None, strict=False)
    unit.read(SERVICE)
    root = "%h/.cache/hapax/source-activation/worktree"
    assert shlex.split(unit["Service"]["ExecStart"]) == [
        root + "/scripts/hapax-worktree-gc.sh",
        "--repo",
        root,
        "--releases-only",
        "--no-fetch",
        "--release-keep",
        "5",
    ]
    assert unit["Service"]["WorkingDirectory"] == root


def test_young_over_cap_releases_wait_for_age_threshold(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    now = int(time.time())
    releases = _young_releases(tmp_path, repo, now, 7)
    result = _run_gc_args(
        repo, now, _release_env(tmp_path), "--releases-only", "--clean-age-seconds", "172800"
    )
    assert result.returncode == 0, result.stderr
    assert all(p.exists() for p in releases), result.stdout
