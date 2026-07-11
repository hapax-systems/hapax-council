from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared import worktree_registry as wr


def _init_repo(path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    (path / "f.txt").write_text("hi")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True)


def _load_cli():
    """Import the extensionless CLI script as a module so its cmd_* handlers can be driven directly."""
    src = Path(__file__).resolve().parents[2] / "scripts" / "hapax-worktree-register"
    loader = importlib.machinery.SourceFileLoader("hwr_cli_under_test", str(src))
    spec = importlib.util.spec_from_loader("hwr_cli_under_test", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


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


def test_classify_open_pr_idle_but_fresh_is_merging() -> None:
    # PR exists (follow-through) + owner idle (no live process) but heartbeat FRESH -> merging, kept.
    assert (
        wr.classify(
            is_infra=False,
            live=False,
            clean=True,
            merged=False,
            heartbeat_age_s=600.0,  # < abandoned_after_s: recent owner activity
            abandoned_after_s=3600,
            has_open_pr=True,
        )
        == "merging"
    )


def test_classify_open_pr_but_stale_is_abandoned() -> None:
    # The round-11 fix / the operator's model ("stale PR -> abandoned"): a STALE open-PR lane with a dead
    # owner is abandoned, NOT kept as merging — the checkout reap is non-destructive (branch + PR survive).
    assert (
        wr.classify(
            is_infra=False,
            live=False,
            clean=True,
            merged=False,
            heartbeat_age_s=99999.0,  # >> abandoned_after_s: session stopped
            abandoned_after_s=3600,
            has_open_pr=True,
        )
        == "abandoned"
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


# --- lane-standardization S4: canonical Lane instance fields + union liveness ------------------------


def test_register_load_roundtrip_canonical_lane_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path))
    wr.register(
        "/p/hapax-council--agy",
        role="agy",
        lane_id="agy",
        route_id="agy.interactive.full",
        dispatch_host="appendix",
        supervisor="agy.launcher.pid",
        now=_NOW,
    )
    rec = wr.load("/p/hapax-council--agy")
    assert rec is not None
    assert rec.lane_id == "agy"
    assert rec.route_id == "agy.interactive.full"
    assert rec.dispatch_host == "appendix"
    assert rec.supervisor == "agy.launcher.pid"
    # `host` is deleted from the model (grep-clean of readers) — replaced by `dispatch_host`.
    assert not hasattr(rec, "host")


def test_legacy_record_with_host_key_still_deserializes(tmp_path, monkeypatch) -> None:
    """A pre-S4 record on disk carrying the now-removed `host` key must load, not raise."""
    import json

    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path))
    wr.register("/p/hapax-council--old", role="dev2", now=_NOW)
    rp = wr.record_path("/p/hapax-council--old")
    d = json.loads(rp.read_text(encoding="utf-8"))
    d["host"] = "podium"  # legacy key no longer in the model
    rp.write_text(json.dumps(d), encoding="utf-8")
    rec = wr.load("/p/hapax-council--old")  # unknown key is ignored by d.get(...)
    assert rec is not None
    assert rec.role == "dev2"


def test_probe_union_liveness_supervisor_keeps_no_cwd_lane_live(tmp_path, monkeypatch) -> None:
    """A live SUPERVISOR launcher keeps a lane live even when no process resolves in the worktree —
    the false-kill-under-live-supervisor class the path-scan alone cannot see."""
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
        live_count_fn=lambda _p: 0,  # nothing resolves inside the worktree
        launcher_live_fn=lambda _rec: True,  # but the supervisor launcher is alive
        now_epoch=_FUTURE_EPOCH,
    )
    assert p is not None
    assert p["live"] is True
    assert p["liveness_evidence"] == "pidfile"
    assert p["status"] == "active"
    assert wr.is_reapable(p["status"], p["clean"], live=p["live"]) is False


def test_probe_path_process_evidence_is_proc(tmp_path, monkeypatch) -> None:
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
        live_count_fn=lambda _p: 1,  # a process resolves inside the worktree
        launcher_live_fn=lambda _rec: False,
        now_epoch=_FUTURE_EPOCH,
    )
    assert p["live"] is True
    assert p["liveness_evidence"] == "proc"


def test_probe_default_no_launcher_fn_is_path_only_unchanged(tmp_path, monkeypatch) -> None:
    """Default (no launcher_live_fn) preserves pre-S4 behavior: path-scan only, abandoned when idle."""
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
        live_count_fn=lambda _p: 0,  # no launcher_live_fn -> default off
        now_epoch=_FUTURE_EPOCH,
    )
    assert p["live"] is False
    assert p["liveness_evidence"] is None
    assert p["status"] == "abandoned"


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
    # FRESH lane (just created -> recent mtime) with an open PR -> merging (idle owner mid-flight, kept).
    p = wr.probe_worktree(
        path=str(wt),
        branch=branch,
        canonical=str(repo),
        open_pr_branches={branch},
        abandoned_after_s=3600,
        live_count_fn=lambda _p: 0,
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


# --- cmd_reap / cmd_heartbeat through the real CLI module (the destructive path, end-to-end) ---------


def test_cli_reap_reaps_abandoned_keeps_merging_and_live(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    abandoned, _ab = _add_worktree(repo, "ab")
    merging, mg_branch = _add_worktree(repo, "mg")
    live_wt, _lv = _add_worktree(repo, "lv")
    live_real = os.path.realpath(str(live_wt))

    # Age ONLY the abandoned lane's activity signals into the past; mg + lv stay fresh (just created).
    # With the heartbeat-driven model a fresh open-PR lane is `merging`, a stale one would be abandoned —
    # so the merging lane MUST stay fresh, and we use the real (non-zero) threshold rather than 0.
    ab_real = os.path.realpath(str(abandoned))
    ab_gd = wr._resolve_git_dir(ab_real)
    old = 1_000_000_000.0  # 2001
    for p in (ab_real, os.path.join(ab_gd, "index"), os.path.join(ab_gd, "HEAD")):
        if os.path.exists(p):
            os.utime(p, (old, old))

    cli = _load_cli()
    monkeypatch.setattr(cli, "CANONICAL", str(repo))
    monkeypatch.setattr(cli, "SELF", "")
    monkeypatch.setattr(cli, "_open_pr_branches", lambda: {mg_branch})
    monkeypatch.setattr(cli.wr, "live_process_count", lambda p: 1 if p == live_real else 0)

    cli.cmd_backfill(
        argparse.Namespace()
    )  # govern all worktrees first (cleanup needs a registry record)

    # dry-run: only the abandoned lane is reap-eligible; merging + live are silently kept.
    assert cli.cmd_reap(argparse.Namespace(apply=False, min_idle_hours=0.0)) == 0
    out = capsys.readouterr().out
    assert "abandoned" in out and str(abandoned) in out
    assert str(merging) not in out
    assert str(live_wt) not in out

    # apply: the abandoned checkout is removed + deregistered; merging + live survive.
    assert cli.cmd_reap(argparse.Namespace(apply=True, min_idle_hours=0.0)) == 0
    assert not os.path.isdir(str(abandoned))
    assert wr.load(os.path.realpath(str(abandoned))) is None  # record deregistered after removal
    assert os.path.isdir(str(merging))
    assert os.path.isdir(str(live_wt))


def test_cli_reap_self_is_protected(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    self_wt, _b = _add_worktree(repo, "self")
    cli = _load_cli()
    monkeypatch.setattr(cli, "CANONICAL", str(repo))
    monkeypatch.setattr(cli, "_open_pr_branches", lambda: set())
    monkeypatch.setattr(cli.wr, "live_process_count", lambda _p: 0)
    monkeypatch.setattr(cli.wr, "DEFAULT_ABANDONED_AFTER_S", 0)
    monkeypatch.setattr(cli, "SELF", os.path.realpath(str(self_wt)))
    cli.cmd_backfill(argparse.Namespace())  # registered + abandoned, but SELF-protected
    cli.cmd_reap(argparse.Namespace(apply=True, min_idle_hours=0.0))
    assert os.path.isdir(str(self_wt))


def test_cli_heartbeat_missing_registration_returns_1(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    cli = _load_cli()
    rc = cli.cmd_heartbeat(argparse.Namespace(path=str(tmp_path / "nope")))
    assert rc == 1
    err = capsys.readouterr().err
    assert "no registration" in err
    assert "register" in err  # carries a next-action


def test_cli_reap_skips_unregistered_worktree(tmp_path, monkeypatch, capsys) -> None:
    # CRITICAL: an UNREGISTERED worktree is never reaped by inference (cleanup is registry-governed).
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    wt, _b = _add_worktree(repo, "wt")  # deliberately NOT registered
    cli = _load_cli()
    monkeypatch.setattr(cli, "CANONICAL", str(repo))
    monkeypatch.setattr(cli, "_open_pr_branches", lambda: set())
    monkeypatch.setattr(cli.wr, "live_process_count", lambda _p: 0)
    monkeypatch.setattr(cli.wr, "DEFAULT_ABANDONED_AFTER_S", 0)
    cli.cmd_reap(argparse.Namespace(apply=True, min_idle_hours=0.0))
    assert "unregistered" in capsys.readouterr().out
    assert os.path.isdir(str(wt))  # kept despite being idle/abandoned-by-inference


def test_cli_reap_abandons_stale_lane_without_gh(tmp_path, monkeypatch) -> None:
    # ROUND-11 CRITICAL: the production timer runs WITHOUT a GH_TOKEN (open_pr_branches=None). A stopped,
    # non-merged, non-live lane MUST still flip to abandoned and be reaped — abandonment is heartbeat-
    # driven, NOT gated on the unavailable PR signal. (Reaping the checkout keeps the branch + any PR.)
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    wt, _b = _add_worktree(repo, "wt")
    cli = _load_cli()
    monkeypatch.setattr(cli, "CANONICAL", str(repo))
    monkeypatch.setattr(cli, "SELF", "")
    monkeypatch.setattr(
        cli, "_open_pr_branches", lambda: None
    )  # gh DOWN — the production timer mode
    monkeypatch.setattr(cli.wr, "live_process_count", lambda _p: 0)
    monkeypatch.setattr(cli.wr, "DEFAULT_ABANDONED_AFTER_S", 0)  # any idle age counts as stale
    cli.cmd_backfill(argparse.Namespace())
    cli.cmd_reap(argparse.Namespace(apply=True, min_idle_hours=0.0))
    assert not os.path.isdir(str(wt))  # stale non-merged lane reaped even with gh unavailable


def test_cli_reap_apply_failure_keeps_record(tmp_path, monkeypatch, capsys) -> None:
    # When `git worktree remove` fails, the worktree + its registry record are kept; the loop continues.
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    wt, _b = _add_worktree(repo, "wt")
    real = os.path.realpath(str(wt))
    cli = _load_cli()
    monkeypatch.setattr(cli, "CANONICAL", str(repo))
    monkeypatch.setattr(cli, "_open_pr_branches", lambda: set())
    monkeypatch.setattr(cli.wr, "live_process_count", lambda _p: 0)
    monkeypatch.setattr(cli.wr, "DEFAULT_ABANDONED_AFTER_S", 0)
    cli.cmd_backfill(argparse.Namespace())
    real_run = cli.subprocess.run

    def fake_run(cmd, *a, **k):
        if "remove" in cmd:
            return cli.subprocess.CompletedProcess(cmd, 1, "", "fatal: cannot remove")
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    cli.cmd_reap(argparse.Namespace(apply=True, min_idle_hours=0.0))
    assert "FAIL remove" in capsys.readouterr().err
    assert os.path.isdir(str(wt))  # not removed
    assert wr.load(real) is not None  # record NOT deregistered on failure


def test_classify_stale_without_pr_signal_is_abandoned() -> None:
    # gh down -> has_open_pr can't be confirmed (False at the probe). A STALE non-live lane is abandoned
    # regardless (round-11 fix): abandonment is heartbeat-driven, not gated on the PR signal.
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


def test_probe_pr_signal_unavailable_abandons_stale_idle_lane(tmp_path, monkeypatch) -> None:
    # ROUND-11: when _open_pr_branches is None (gh down — the production timer mode), a STALE, non-live
    # lane is abandoned (reapable). Abandonment is heartbeat-driven, not gated on the unknowable PR set.
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    wt, branch = _add_worktree(repo, "wt")
    p = wr.probe_worktree(
        path=str(wt),
        branch=branch,
        canonical=str(repo),
        open_pr_branches=None,
        abandoned_after_s=3600,
        live_count_fn=lambda _p: 0,
        now_epoch=_FUTURE_EPOCH,
    )
    assert p is not None
    assert p["status"] == "abandoned"
    assert wr.is_reapable(p["status"], p["clean"], live=p["live"]) is True


def test_probe_respects_pinned_infra_for_custom_path(tmp_path, monkeypatch) -> None:
    # CRITICAL: an explicit set_status pin is AUTHORITATIVE — not re-derived from signals.
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    wt, branch = _add_worktree(repo, "wt")
    real = os.path.realpath(str(wt))
    wr.register(real, branch=branch)
    wr.set_status(real, "infra")  # custom infra pin; path does not match the infra patterns
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
    assert p["pinned"] is True
    assert p["status"] == "infra"
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


def test_cli_list_prints_status_format(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    wt, branch = _add_worktree(repo, "wt")
    cli = _load_cli()
    monkeypatch.setattr(cli, "CANONICAL", str(repo))
    monkeypatch.setattr(cli, "_open_pr_branches", lambda: set())
    monkeypatch.setattr(cli.wr, "live_process_count", lambda _p: 0)
    assert cli.cmd_list(argparse.Namespace()) == 0
    out = capsys.readouterr().out
    assert str(wt) in out and branch in out
    assert "live=" in out and "clean=" in out and "merged=" in out


def test_cli_register_persists_loadable_record(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    cli = _load_cli()
    target = tmp_path / "wt"
    target.mkdir()
    cli.cmd_register(
        argparse.Namespace(
            path=str(target), role="dev2", branch="dev2/x", session="s1", task="cc-task-x", pr=42
        )
    )
    rec = wr.load(os.path.realpath(str(target)))
    assert rec is not None
    assert rec.role == "dev2"
    assert rec.branch == "dev2/x"
    assert rec.task_id == "cc-task-x"
    assert rec.pr == 42


def test_cli_reap_done_merged_is_reaped(tmp_path, monkeypatch) -> None:
    # A merged (done) worktree IS reaped through the CLI (is_merged stubbed True; the docstring's
    # done-reap claim, evidenced end-to-end).
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    done_wt, _b = _add_worktree(repo, "done")
    cli = _load_cli()
    monkeypatch.setattr(cli, "CANONICAL", str(repo))
    monkeypatch.setattr(cli, "_open_pr_branches", lambda: set())
    monkeypatch.setattr(cli.wr, "live_process_count", lambda _p: 0)
    monkeypatch.setattr(cli.wr, "is_merged", lambda *a, **k: True)  # treat the branch as merged
    cli.cmd_backfill(argparse.Namespace())
    cli.cmd_reap(argparse.Namespace(apply=True, min_idle_hours=0.0))
    assert not os.path.isdir(str(done_wt))  # done/merged -> reaped


# --- is_inference_protected(): what the legacy GC sweep must NOT reap (review round 6) ----------------


def test_is_inference_protected() -> None:
    # In-use / infra statuses are protected from the legacy age+clean+merged inference sweep...
    assert wr.is_inference_protected("active", pinned=False) is True
    assert wr.is_inference_protected("merging", pinned=False) is True
    assert wr.is_inference_protected("infra", pinned=False) is True
    # ...done/abandoned are NOT (the sweep may reap a merged checkout + delete its merged branch)...
    assert wr.is_inference_protected("done", pinned=False) is False
    assert wr.is_inference_protected("abandoned", pinned=False) is False
    # ...but an explicit PIN protects even a status the sweep would otherwise reap.
    assert wr.is_inference_protected("done", pinned=True) is True
    assert wr.is_inference_protected("abandoned", pinned=True) is True


def test_cli_protected_paths_lists_only_protected(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    wt_act, b_act = _add_worktree(repo, "act")
    wt_done, b_done = _add_worktree(repo, "done")
    wt_unreg, _b_unreg = _add_worktree(repo, "unreg")
    # active+pinned -> protected; done (registered, unpinned) -> NOT protected; unregistered -> omitted.
    wr.register(os.path.realpath(str(wt_act)), branch=b_act, status="active", pinned=True)
    wr.register(os.path.realpath(str(wt_done)), branch=b_done, status="done")
    cli = _load_cli()
    monkeypatch.setattr(cli, "CANONICAL", str(repo))
    monkeypatch.setattr(cli, "_open_pr_branches", lambda: set())
    monkeypatch.setattr(cli.wr, "live_process_count", lambda _p: 0)
    monkeypatch.setattr(cli.wr, "is_merged", lambda _c, br, *a, **k: br == b_done)
    assert cli.cmd_protected_paths(argparse.Namespace()) == 0
    out = capsys.readouterr().out
    assert os.path.realpath(str(wt_act)) in out  # pinned active -> protected
    assert os.path.realpath(str(wt_done)) not in out  # done -> reapable, not protected
    assert os.path.realpath(str(wt_unreg)) not in out  # unregistered -> legacy inference applies


def test_cli_backfill_preserves_task_keying(tmp_path, monkeypatch) -> None:
    # A lane registered by the creation contract carries cc-task keying; a later backfill (which probes
    # git, not the contract) must PRESERVE it, not wipe it to None (glm minor: coverage for the gap).
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    wt, b = _add_worktree(repo, "wt")
    rp = os.path.realpath(str(wt))
    wr.register(rp, branch=b, role="dev2", session_id="s1", task_id="cc-task-x", pr=99)
    cli = _load_cli()
    monkeypatch.setattr(cli, "CANONICAL", str(repo))
    monkeypatch.setattr(cli, "_open_pr_branches", lambda: set())
    monkeypatch.setattr(cli.wr, "live_process_count", lambda _p: 0)
    assert cli.cmd_backfill(argparse.Namespace()) == 0
    rec = wr.load(rp)
    assert rec is not None
    assert rec.task_id == "cc-task-x"  # backfill must not drop cc-task keying
    assert rec.role == "dev2"
    assert rec.session_id == "s1"
    assert rec.pr == 99


def test_canonical_resolves_linked_worktree_to_main(tmp_path) -> None:
    # Given a LINKED worktree path, _resolve_canonical resolves to the MAIN checkout (glm minor: so
    # is_infra_path / gh cwd are correct even if HAPAX_WORKTREE_GC_REPO points at a worktree).
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
    wt = tmp_path / "wt"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "-b", "lane", str(wt), "main"], check=True
    )
    cli = _load_cli()
    assert os.path.realpath(cli._resolve_canonical(str(wt))) == os.path.realpath(str(repo))


# --- gc.sh integration: the REAL production script is governed by lifecycle status (review round 6) ---


def _run_gc(repo, registry_dir, *, apply=False, now="9999999999", clean_age="0"):
    """Run the real hapax-worktree-gc.sh against a throwaway repo; return combined output. Orphan-reaper
    + fetch + ntfy disabled to keep it hermetic. `apply=False` runs --dry-run; `apply=True` actually
    removes. `now`/`clean_age` tune the legacy age gate (default: far-future now + 0 clean-age so every
    clean merged worktree reaches the legacy removable gate, leaving the registry gate to decide)."""
    gc = Path(__file__).resolve().parents[2] / "scripts" / "hapax-worktree-gc.sh"
    env = {
        **os.environ,
        "HAPAX_WORKTREE_REGISTRY_DIR": str(registry_dir),
        "HAPAX_WORKTREE_GC_REAP_ORPHANS": "0",
        "HAPAX_WORKTREE_GC_NTFY_URL": "",
    }
    argv = [
        "bash",
        str(gc),
        "--repo",
        str(repo),
        "--base-ref",
        "origin/main",
        "--clean-age-seconds",
        clean_age,
        "--now",
        now,
        "--no-fetch",
    ]
    if not apply:
        argv.append("--dry-run")
    res = subprocess.run(argv, capture_output=True, text=True, env=env, check=False)
    return res.stdout + res.stderr


def test_gc_legacy_respects_registry_pin(tmp_path, monkeypatch) -> None:
    # The CRITICAL: the durable timer's legacy age+clean+merged sweep must NOT reap a pinned active lane
    # by inference, but must still reap an unpinned merged (done) lane. Exercises the REAL gc.sh end to
    # end (backfill -> protected-paths -> reap -> legacy gate), not just the module/CLI handlers.
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
    # origin/main is the base both the registry (is_merged) AND gc.sh default to; in production they
    # agree, so the test must too — otherwise the registry can't see the lanes as merged.
    subprocess.run(
        ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", "main"], check=True
    )
    wt_a, b_a = _add_worktree(repo, "actlane")  # feat/actlane at main -> merged, clean
    _wt_b, _b_b = _add_worktree(repo, "doomedlane")  # feat/doomedlane at main -> merged, clean
    wr.register(os.path.realpath(str(wt_a)), branch=b_a, status="active", pinned=True)
    lines = _run_gc(repo, tmp_path / "reg").splitlines()
    # pinned active lane: kept by the registry gate, never marked removable by inference
    assert any("registry-protected" in ln and "actlane" in ln for ln in lines), lines
    assert not any("would remove" in ln and "actlane" in ln for ln in lines), lines
    # unpinned merged lane: still reaped by the legacy sweep (selective gate, not a blanket disable)
    assert any("would remove" in ln and "doomedlane" in ln for ln in lines), lines


def test_gc_fail_closed_on_registry_pre_pass_error(tmp_path) -> None:
    # If the registry pre-pass ERRORS (here: registry dir under a regular file, so backfill raises), the
    # legacy sweep must fail CLOSED — reap nothing by inference + alert — never silently degrade to the
    # inference behavior the lifecycle predicate forbids.
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", "main"], check=True
    )
    _wt_b, _b_b = _add_worktree(repo, "doomedlane")  # merged, clean -> reapable by inference
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir")  # a FILE where the registry dir should be -> mkdir fails
    lines = _run_gc(repo, blocker / "reg").splitlines()
    assert any("registry pre-pass FAILED" in ln for ln in lines), lines
    assert any("fail-closed" in ln and "doomedlane" in ln for ln in lines), lines
    assert not any("would remove" in ln and "doomedlane" in ln for ln in lines), lines


# --- corrupt records fail CLOSED, never lose a pin (review round 7 critical) -------------------------


def _corrupt_record(path: str) -> Path:
    """Write an unparseable record file at a worktree's registry slot; return its path."""
    rp = wr.record_path(path)
    rp.write_text("{ this is not valid json :::", encoding="utf-8")
    return rp


def test_read_record_distinguishes_absent_from_corrupt(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    # absent -> (None, False); corrupt -> (None, True). Conflating them is the fail-open hole.
    assert wr._read_record("/nope/absent") == (None, False)
    _corrupt_record("/some/wt")
    rec, corrupt = wr._read_record("/some/wt")
    assert rec is None and corrupt is True


def test_probe_corrupt_record_is_protected(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    wt, branch = _add_worktree(repo, "wt")
    _corrupt_record(os.path.realpath(str(wt)))
    p = wr.probe_worktree(
        path=str(wt),
        branch=branch,
        canonical=str(repo),
        open_pr_branches=set(),
        live_count_fn=lambda _p: 0,
    )
    assert p is not None
    assert p["corrupt"] is True
    assert p["registered"] is True  # a corrupt record is PRESENT, not absent
    assert p["pinned"] is True  # fail closed -> protected
    assert wr.is_reapable(p["status"], p["clean"], live=p["live"]) is False  # never reaped


def test_register_refuses_to_overwrite_corrupt(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    rp = _corrupt_record("/some/wt")
    before = rp.read_text(encoding="utf-8")
    with pytest.raises(wr.CorruptRecordError):
        wr.register(
            "/some/wt", branch="x", status="done"
        )  # backfill would pass a derived status here
    assert (
        rp.read_text(encoding="utf-8") == before
    )  # the pin-bearing file is left intact, not clobbered


def test_cli_protected_paths_emits_corrupt(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    wt, _b = _add_worktree(repo, "wt")
    _corrupt_record(os.path.realpath(str(wt)))
    cli = _load_cli()
    monkeypatch.setattr(cli, "CANONICAL", str(repo))
    monkeypatch.setattr(cli, "_open_pr_branches", lambda: set())
    monkeypatch.setattr(cli.wr, "live_process_count", lambda _p: 0)
    assert cli.cmd_protected_paths(argparse.Namespace()) == 0
    assert (
        os.path.realpath(str(wt)) in capsys.readouterr().out
    )  # corrupt -> protected from inference


def test_cli_reap_keeps_corrupt(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    wt, _b = _add_worktree(repo, "wt")
    _corrupt_record(os.path.realpath(str(wt)))
    cli = _load_cli()
    monkeypatch.setattr(cli, "CANONICAL", str(repo))
    monkeypatch.setattr(cli, "_open_pr_branches", lambda: set())
    monkeypatch.setattr(cli.wr, "live_process_count", lambda _p: 0)
    cli.cmd_reap(argparse.Namespace(apply=True, min_idle_hours=0.0))
    assert os.path.isdir(str(wt))  # corrupt record -> fail closed -> never reaped
    assert "KEEP corrupt" in capsys.readouterr().out


def test_cli_backfill_leaves_corrupt_untouched(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    wt, _b = _add_worktree(repo, "wt")
    rp = _corrupt_record(os.path.realpath(str(wt)))
    before = rp.read_text(encoding="utf-8")
    cli = _load_cli()
    monkeypatch.setattr(cli, "CANONICAL", str(repo))
    monkeypatch.setattr(cli, "_open_pr_branches", lambda: set())
    monkeypatch.setattr(cli.wr, "live_process_count", lambda _p: 0)
    assert (
        cli.cmd_backfill(argparse.Namespace()) == 0
    )  # backfill succeeds, does not crash on corrupt
    assert (
        rp.read_text(encoding="utf-8") == before
    )  # corrupt record NOT overwritten with derived status


def test_cli_protected_paths_propagates_runtime_error(tmp_path, monkeypatch) -> None:
    # glm minor: if protected-paths itself raises (after a successful backfill), the error must propagate
    # so the GC sees a non-zero exit and fails CLOSED — it must not silently return an empty set.
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    cli = _load_cli()

    def _boom(_canonical):
        raise RuntimeError("git worktree list blew up")

    monkeypatch.setattr(cli, "_worktrees", _boom)
    monkeypatch.setattr(cli, "_open_pr_branches", lambda: set())
    with pytest.raises(RuntimeError):
        cli.cmd_protected_paths(argparse.Namespace())


def test_gc_keeps_corrupt_record_lane(tmp_path, monkeypatch) -> None:
    # End-to-end via the REAL gc.sh: a merged+clean+old lane that WOULD be reaped by inference is kept
    # when its registry record is corrupt — the legacy sweep never reaps a record it cannot read.
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", "main"], check=True
    )
    wt, _b = _add_worktree(repo, "corruptlane")  # merged, clean -> reapable by inference
    _corrupt_record(os.path.realpath(str(wt)))
    lines = _run_gc(repo, tmp_path / "reg").splitlines()
    assert any("registry-protected" in ln and "corruptlane" in ln for ln in lines), lines
    assert not any("would remove" in ln and "corruptlane" in ln for ln in lines), lines


# --- idle signal is not self-refreshed by the probe (review round 8 critical 1) ----------------------


def test_is_clean_uses_no_optional_locks(tmp_path, monkeypatch) -> None:
    # is_clean must use --no-optional-locks: a plain `git status` refreshes the index on disk, bumping
    # the mtime the reap path reads as activity, so an abandoned lane would never age out.
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    captured: list = []
    real_run = subprocess.run

    def spy(args, **kw):
        captured.append(args)
        return real_run(args, **kw)

    monkeypatch.setattr(wr.subprocess, "run", spy)
    wr.is_clean(str(repo))
    status_cmds = [a for a in captured if isinstance(a, list) and "status" in a]
    assert status_cmds, captured
    assert all("--no-optional-locks" in a for a in status_cmds)


def test_is_clean_does_not_refresh_index_mtime(tmp_path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    wt, _b = _add_worktree(repo, "wt")
    git_dir = wr._resolve_git_dir(os.path.realpath(str(wt)))
    assert git_dir is not None
    index = os.path.join(git_dir, "index")
    if not os.path.exists(index):
        return  # nothing to refresh
    old = 1_000_000_000.0  # 2001-09-09
    os.utime(index, (old, old))
    os.utime(str(Path(wt) / "f.txt"), None)  # stat-change a tracked file -> git wants to refresh
    assert wr.is_clean(str(wt)) is True  # still clean (content identical)
    assert os.path.getmtime(index) == old  # index NOT rewritten -> idle clock preserved


# --- registry merge detection matches the legacy GC (squash merges) (round 8 critical 2) -------------


def _squash_setup(repo, *, content_in_main: bool) -> None:
    """Branch `feat` modifies f.txt; main lands the SAME content as a different commit iff
    content_in_main (a squash merge). feat tracks origin/feat, which is gone (auto-deleted on merge)."""
    subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feat"], check=True)
    (repo / "f.txt").write_text("feat content")
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-am", "feat work"], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "main"], check=True)
    if content_in_main:
        (repo / "f.txt").write_text("feat content")  # same bytes -> squash landed
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-am", "squash-merge feat"], check=True
        )
    subprocess.run(
        ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", "main"], check=True
    )
    subprocess.run(["git", "-C", str(repo), "config", "branch.feat.remote", "origin"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "branch.feat.merge", "refs/heads/feat"], check=True
    )


def test_is_merged_detects_squash_merge(tmp_path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    _squash_setup(repo, content_in_main=True)
    # feat is NOT an ancestor of main, but its content IS present -> squash-merge -> reapable as done.
    assert wr._git(str(repo), "merge-base", "--is-ancestor", "feat", "origin/main").returncode != 0
    assert wr.is_merged(str(repo), "feat", "origin/main") is True


def test_is_merged_keeps_unmerged_remote_deleted_branch(tmp_path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    _squash_setup(repo, content_in_main=False)  # remote-deleted, but content NOT in base
    # Data-loss guard: a closed-without-merge / manually-deleted branch with real commits is NOT merged.
    assert wr.is_merged(str(repo), "feat", "origin/main") is False


# --- corrupt-record surfacing in list_records + heartbeat (round 8 minors) ---------------------------


def test_list_records_warns_on_corrupt(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    wr.register("/a/wt", branch="x")  # one valid record
    _corrupt_record("/b/wt")  # one corrupt record
    recs = wr.list_records()
    assert len(recs) == 1  # only the parseable record returned
    assert "corrupt" in capsys.readouterr().err.lower()  # corruption surfaced, not silent


def test_cli_heartbeat_corrupt_message(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    _corrupt_record("/some/wt")
    cli = _load_cli()
    assert cli.cmd_heartbeat(argparse.Namespace(path="/some/wt")) == 1
    err = capsys.readouterr().err.lower()
    assert (
        "corrupt" in err
    )  # distinguishes corrupt from "absent" -> sends operator to repair, not register


# --- exit-predicate proofs through the real GC path (review round 9) ---------------------------------


def test_gc_cycle_flips_idle_lane_to_abandoned_and_reaps(tmp_path, monkeypatch) -> None:
    # CORE EXIT PREDICATE (acceptance #3): a non-live, no-PR, idle, clean lane flips to abandoned across
    # the real backfill->reap path and is reaped. Guards the is_clean()-refreshes-the-idle-clock bug: we
    # build the racy condition (a tracked file whose stat differs from the index's cached stat) that
    # makes a plain `git status` REWRITE the index mtime; --no-optional-locks must prevent that, else the
    # backfill probe would reset the idle clock and the lane would stay `active` forever.
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    wt, branch = _add_worktree(repo, "idle")
    real = os.path.realpath(str(wt))
    git_dir = wr._resolve_git_dir(real)
    assert git_dir is not None
    index = os.path.join(git_dir, "index")
    old = datetime.now(UTC).timestamp() - 100 * 3600  # 100h idle (> 48h)
    # Age the activity signals AND the tracked file (its stat now differs from the index's cached stat,
    # so a plain `git status` would refresh+rewrite the index — the bug this proves is prevented).
    for p in (str(Path(wt) / "f.txt"), index, os.path.join(git_dir, "HEAD"), real):
        if os.path.exists(p):
            os.utime(p, (old, old))
    cli = _load_cli()
    monkeypatch.setattr(cli, "CANONICAL", str(repo))
    monkeypatch.setattr(cli, "SELF", "")
    monkeypatch.setattr(cli, "_open_pr_branches", lambda: set())  # gh available, empty -> no PR
    monkeypatch.setattr(cli.wr, "live_process_count", lambda _p: 0)  # not live
    cli.cmd_backfill(
        argparse.Namespace()
    )  # runs is_clean() inside the probe; must not refresh the clock
    p = wr.probe_worktree(
        path=real,
        branch=branch,
        canonical=str(repo),
        open_pr_branches=set(),
        abandoned_after_s=48 * 3600,
        live_count_fn=lambda _p: 0,
    )
    assert p["status"] == "abandoned"  # idle clock survived backfill's is_clean()
    assert wr.is_reapable(p["status"], p["clean"], live=p["live"]) is True
    cli.cmd_reap(argparse.Namespace(apply=True, min_idle_hours=48.0))
    assert not os.path.isdir(real)  # the idle lane was actually reaped through the real GC path


def test_classify_squash_merged_lane_is_done_without_gh(tmp_path, monkeypatch) -> None:
    # Critical 2 end-to-end: a squash-merged lane classifies `done` (reapable) even with gh UNAVAILABLE
    # (open_pr_branches=None) — so the legacy sweep is NOT blocked from cleaning the council's default
    # merge style. is_merged detects the squash (remote-deleted + content-merged); classify: merged->done.
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    _squash_setup(repo, content_in_main=True)
    wt = tmp_path / "feat-wt"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", str(wt), "feat"], check=True)
    p = wr.probe_worktree(
        path=str(wt),
        branch="feat",
        canonical=str(repo),
        open_pr_branches=None,  # gh UNAVAILABLE (the no-gh timer mode the critical is about)
        live_count_fn=lambda _p: 0,
    )
    assert p is not None
    assert p["merged"] is True  # squash detected git-only
    assert p["status"] == "done"  # NOT "merging" -> reapable
    assert wr.is_inference_protected(p["status"], pinned=p["pinned"]) is False  # not protected


# --- review round 10: the REAL gc.sh path must not refresh the idle clock; squash reaps; reap-fail ---


def test_gc_real_path_does_not_refresh_idle_index(tmp_path, monkeypatch) -> None:
    # Critical: NEITHER the registry pre-pass (is_clean) NOR the legacy sweep's OWN `git status` (gc.sh
    # process_worktree) may refresh the index mtime — else a sub-48h idle lane looks fresh every 6h cycle
    # and never abandons. Run the REAL gc.sh --dry-run on a racy idle lane; assert its index mtime is
    # unchanged (both git-status reads use --no-optional-locks).
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", "main"], check=True
    )
    wt, _b = _add_worktree(repo, "idlelane")
    real = os.path.realpath(str(wt))
    git_dir = wr._resolve_git_dir(real)
    assert git_dir is not None
    index = os.path.join(git_dir, "index")
    old = 1_000_000_000.0  # 2001
    # racy: a tracked file whose stat differs from the index's cached stat makes a plain `git status`
    # want to rewrite the index; --no-optional-locks must prevent that on BOTH status reads.
    os.utime(str(Path(wt) / "f.txt"), (old, old))
    os.utime(index, (old, old))
    before = os.path.getmtime(index)
    _run_gc(repo, tmp_path / "reg")  # dry-run: backfill is_clean + legacy `git status` both run
    assert os.path.getmtime(index) == before  # idle clock survived the whole real GC run


def test_gc_real_path_reaps_squash_merged_without_gh(tmp_path, monkeypatch) -> None:
    # Critical 4 end-to-end through the REAL gc.sh with gh UNAVAILABLE (throwaway repo has no remote, so
    # _open_pr_branches degrades to None): a squash-merged lane is detected `done` and actually reaped.
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _squash_setup(repo, content_in_main=True)
    wt = tmp_path / "feat-wt"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", str(wt), "feat"], check=True)
    _run_gc(repo, tmp_path / "reg", apply=True)
    assert not os.path.isdir(str(wt))  # squash-merged lane reaped through the real GC path, no gh


def test_cli_reap_handles_remove_failure_gracefully(tmp_path, monkeypatch, capsys) -> None:
    # Critical: a failing `git worktree remove` must print the FAIL + Next guidance and let the loop
    # continue (not crash on the first removal failure, halting cleanup of remaining lanes).
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    wt, branch = _add_worktree(repo, "doomed")
    wr.register(os.path.realpath(str(wt)), branch=branch, status="done")
    cli = _load_cli()
    monkeypatch.setattr(cli, "CANONICAL", str(repo))
    monkeypatch.setattr(cli, "SELF", "")
    monkeypatch.setattr(cli, "_open_pr_branches", lambda: set())
    monkeypatch.setattr(cli.wr, "live_process_count", lambda _p: 0)
    monkeypatch.setattr(cli.wr, "is_merged", lambda *a, **k: True)  # -> done -> reap is attempted
    real_run = subprocess.run

    def failing_run(args, **kw):
        if isinstance(args, list) and "worktree" in args and "remove" in args:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="fatal: is locked")
        return real_run(args, **kw)

    monkeypatch.setattr(cli.subprocess, "run", failing_run)
    cli.cmd_reap(argparse.Namespace(apply=True, min_idle_hours=0.0))  # must not raise
    err = capsys.readouterr().err
    assert "FAIL remove" in err
    assert "Next:" in err
    assert os.path.isdir(str(wt))  # not removed (remove failed) — loop survived the failure


def test_cli_backfill_preserves_fresh_heartbeat(tmp_path, monkeypatch) -> None:
    # Codex major: an already-registered lane with a FRESH heartbeat but OLD file mtime must NOT be
    # clobbered to the stale mtime by backfill (else an active lane looks abandoned and gets reaped).
    monkeypatch.setenv("HAPAX_WORKTREE_REGISTRY_DIR", str(tmp_path / "reg"))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)
    wt, branch = _add_worktree(repo, "wt")
    real = os.path.realpath(str(wt))
    git_dir = wr._resolve_git_dir(real)
    old = 1_000_000_000.0  # 2001 — old FILE activity
    for p in (real, os.path.join(git_dir, "index"), os.path.join(git_dir, "HEAD")):
        if os.path.exists(p):
            os.utime(p, (old, old))
    fresh = datetime.now(UTC)  # but a fresh session heartbeat
    wr.register(real, branch=branch, status="active", last_heartbeat=fresh)
    cli = _load_cli()
    monkeypatch.setattr(cli, "CANONICAL", str(repo))
    monkeypatch.setattr(cli, "_open_pr_branches", lambda: set())
    monkeypatch.setattr(cli.wr, "live_process_count", lambda _p: 0)
    cli.cmd_backfill(argparse.Namespace())
    rec = wr.load(real)
    assert rec is not None
    assert (
        rec.last_heartbeat == fresh
    )  # fresh heartbeat preserved, NOT moved back to the stale mtime
