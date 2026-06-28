from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime

from shared import worktree_registry as wr


def _init_repo(path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    (path / "f.txt").write_text("hi")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True)


_NOW = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)
_CANON = "/p/hapax-council"


# --- classify(): explicit status from signals (the "layer of indication") ---------------------------


def test_classify_infra_wins() -> None:
    assert (
        wr.classify(
            is_infra=True,
            live=True,
            clean=True,
            merged=True,
            heartbeat_age_s=0.0,
            abandoned_after_s=3600,
            has_open_pr=True,
        )
        == "infra"
    )


def test_classify_merged_is_done() -> None:
    assert (
        wr.classify(
            is_infra=False,
            live=False,
            clean=True,
            merged=True,
            heartbeat_age_s=None,
            abandoned_after_s=3600,
            has_open_pr=False,
        )
        == "done"
    )


def test_classify_live_owner_is_active() -> None:
    assert (
        wr.classify(
            is_infra=False,
            live=True,
            clean=False,
            merged=False,
            heartbeat_age_s=None,
            abandoned_after_s=3600,
            has_open_pr=False,
        )
        == "active"
    )


def test_classify_fresh_heartbeat_is_active() -> None:
    assert (
        wr.classify(
            is_infra=False,
            live=False,
            clean=True,
            merged=False,
            heartbeat_age_s=10.0,
            abandoned_after_s=3600,
            has_open_pr=False,
        )
        == "active"
    )


def test_classify_open_pr_idle_is_merging() -> None:
    # PR exists (follow-through) but owner is idle + heartbeat stale -> merging, not abandoned.
    assert (
        wr.classify(
            is_infra=False,
            live=False,
            clean=True,
            merged=False,
            heartbeat_age_s=99999.0,
            abandoned_after_s=3600,
            has_open_pr=True,
        )
        == "merging"
    )


def test_classify_no_pr_dead_owner_stale_is_abandoned() -> None:
    # The disease made knowable: no live owner, stale/no heartbeat, no PR, not merged -> abandoned.
    assert (
        wr.classify(
            is_infra=False,
            live=False,
            clean=True,
            merged=False,
            heartbeat_age_s=None,
            abandoned_after_s=3600,
            has_open_pr=False,
        )
        == "abandoned"
    )


# --- is_reapable(): reap ONLY by explicit status, never inference -----------------------------------


def test_is_reapable_abandoned() -> None:
    assert wr.is_reapable("abandoned", clean=True) is True


def test_is_reapable_done() -> None:
    assert wr.is_reapable("done", clean=True) is True


def test_not_reapable_active() -> None:
    assert wr.is_reapable("active", clean=True) is False


def test_not_reapable_merging_open_pr_is_kept() -> None:
    # THE critical regression: a clean, non-live, open-PR (merging) lane must NOT be reaped.
    assert wr.is_reapable("merging", clean=True) is False


def test_not_reapable_infra() -> None:
    assert wr.is_reapable("infra", clean=True) is False


def test_not_reapable_dirty_even_if_abandoned() -> None:
    assert wr.is_reapable("abandoned", clean=False) is False


def test_not_reapable_live_even_if_done() -> None:
    # CRITICAL: classify() returns `done` for a merged worktree BEFORE checking liveness, so a merged
    # worktree with a live process must still be protected from removal by the live gate.
    assert wr.is_reapable("done", clean=True, live=True) is False


def test_not_reapable_live_even_if_abandoned() -> None:
    assert wr.is_reapable("abandoned", clean=True, live=True) is False


# --- record CRUD round-trips (registry keyed by path) ------------------------------------------------


def test_register_and_load_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path))
    wr.register(
        "/p/hapax-council--foo",
        role="dev2",
        branch="dev2/foo",
        session_id="sess-1",
        task_id="cc-task-foo",
        now=_NOW,
    )
    rec = wr.load("/p/hapax-council--foo")
    assert rec is not None
    assert rec.role == "dev2"
    assert rec.branch == "dev2/foo"
    assert rec.task_id == "cc-task-foo"
    assert rec.created_at == _NOW
    assert rec.last_heartbeat == _NOW
    assert wr.load("/p/hapax-council--missing") is None


def test_heartbeat_updates_only_heartbeat(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path))
    t1 = datetime(2026, 6, 28, 13, 0, tzinfo=UTC)
    wr.register("/p/wt", role="dev2", now=_NOW)
    wr.heartbeat("/p/wt", now=t1)
    rec = wr.load("/p/wt")
    assert rec is not None
    assert rec.created_at == _NOW
    assert rec.last_heartbeat == t1


def test_set_status_and_list(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path))
    wr.register("/p/a", role="dev2", now=_NOW)
    wr.register("/p/b", role="cx-red", now=_NOW)
    wr.set_status("/p/a", "abandoned")
    by_path = {r.path: r for r in wr.list_records()}
    assert by_path["/p/a"].status == "abandoned"
    assert by_path["/p/b"].status == "active"


def test_deregister_removes_record(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path))
    wr.register("/p/gone", role="dev2", now=_NOW)
    assert wr.load("/p/gone") is not None
    wr.deregister("/p/gone")
    assert wr.load("/p/gone") is None


def test_is_infra_path_patterns() -> None:
    assert wr.is_infra_path(_CANON, canonical=_CANON) is True
    assert wr.is_infra_path("/x/source-activation/releases/abc123", canonical=_CANON) is True
    assert wr.is_infra_path("/x/rebuild/worktree", canonical=_CANON) is True
    assert wr.is_infra_path("/x/runtime/health-monitor-source", canonical=_CANON) is True
    assert wr.is_infra_path("/p/hapax-council--cx-red", canonical=_CANON) is False


def test_mtime_age_seconds_uses_freshest_signal(tmp_path) -> None:
    d = tmp_path / "wt"
    d.mkdir()
    os.utime(d, (1000.0, 1000.0))
    assert wr.mtime_age_seconds(str(d), now_epoch=5000.0) == 4000.0


def test_mtime_age_seconds_missing_path_is_inf() -> None:
    assert wr.mtime_age_seconds("/no/such/worktree", now_epoch=5000.0) == float("inf")


# --- probes against a real git repo + linked worktree -----------------------------------------------


def test_is_clean_true_then_false(tmp_path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    assert wr.is_clean(str(repo)) is True
    (repo / "f.txt").write_text("changed")
    assert wr.is_clean(str(repo)) is False


def test_is_merged_distinguishes_ancestor_from_unmerged(tmp_path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    base = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert wr.is_merged(str(repo), base, base_ref=base) is True
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feature"], check=True)
    (repo / "g.txt").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "feat"], check=True)
    assert wr.is_merged(str(repo), "feature", base_ref=base) is False


def test_mtime_age_resolves_linked_worktree_gitdir(tmp_path) -> None:
    # In a LINKED worktree, .git is a FILE; _resolve_git_dir must find the real git dir so mtime
    # reads index/HEAD rather than NotADirectoryError-ing and silently using only the bare dir mtime.
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", str(wt)], check=True)
    assert (wt / ".git").is_file()
    git_dir = wr._resolve_git_dir(str(wt))
    assert git_dir is not None and os.path.isdir(git_dir)
    assert wr.mtime_age_seconds(str(wt)) < 3600


# --- probe_worktree(): the real reap derivation path, through actual worktrees -----------------------

# A fixed "now" far past every test-created mtime (system clock is well before 2040) but a valid
# datetime — so an idle worktree reads stale without depending on wall-clock timing.
_FUTURE = datetime(2040, 1, 1, tzinfo=UTC)
_FUTURE_EPOCH = _FUTURE.timestamp()


def _add_worktree(repo, name):
    wt = repo.parent / name
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "-b", f"feat/{name}", str(wt)],
        check=True,
    )
    return wt, f"feat/{name}"


def test_probe_abandoned_when_idle_no_pr_nonlive(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    wt, branch = _add_worktree(repo, "wt")
    p = wr.probe_worktree(
        path=str(wt),
        branch=branch,
        canonical=str(repo),
        open_pr_branches=set(),
        abandoned_after_s=3600,
        live_count_fn=lambda _p: 0,
        now_epoch=_FUTURE_EPOCH,
    )
    assert p is not None
    assert p["status"] == "abandoned"
    assert wr.is_reapable(p["status"], p["clean"], live=p["live"]) is True


def test_probe_merging_open_pr_is_kept(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    wt, branch = _add_worktree(repo, "wt")
    p = wr.probe_worktree(
        path=str(wt),
        branch=branch,
        canonical=str(repo),
        open_pr_branches={branch},
        abandoned_after_s=3600,
        live_count_fn=lambda _p: 0,
        now_epoch=_FUTURE_EPOCH,
    )
    assert p is not None
    assert p["status"] == "merging"
    assert wr.is_reapable(p["status"], p["clean"], live=p["live"]) is False


def test_probe_live_is_active_kept(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    wt, branch = _add_worktree(repo, "wt")
    p = wr.probe_worktree(
        path=str(wt),
        branch=branch,
        canonical=str(repo),
        open_pr_branches=set(),
        abandoned_after_s=3600,
        live_count_fn=lambda _p: 1,
        now_epoch=_FUTURE_EPOCH,
    )
    assert p is not None
    assert p["status"] == "active"
    assert wr.is_reapable(p["status"], p["clean"], live=p["live"]) is False


def test_probe_fresh_heartbeat_protects_idle_lane(tmp_path, monkeypatch) -> None:
    # CRITICAL: a heartbeated session reads `active` even with an old mtime — paused != abandoned.
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    wt, branch = _add_worktree(repo, "wt")
    wr.register(os.path.realpath(str(wt)), branch=branch, last_heartbeat=_FUTURE)
    p = wr.probe_worktree(
        path=str(wt),
        branch=branch,
        canonical=str(repo),
        open_pr_branches=set(),
        abandoned_after_s=3600,
        live_count_fn=lambda _p: 0,
        now_epoch=_FUTURE_EPOCH,
    )
    assert p is not None
    assert p["status"] == "active"
    assert wr.is_reapable(p["status"], p["clean"], live=p["live"]) is False
