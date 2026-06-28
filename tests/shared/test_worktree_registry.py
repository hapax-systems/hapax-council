from __future__ import annotations

from datetime import UTC, datetime

from shared import worktree_registry as wr

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


# --- should_reap_worktree(): a checkout is disposable when nobody is editing it ----------------------


def test_reap_nonlive_clean() -> None:
    assert wr.should_reap_worktree(is_infra=False, live=False, clean=True) is True


def test_no_reap_live() -> None:
    assert wr.should_reap_worktree(is_infra=False, live=True, clean=True) is False


def test_no_reap_dirty() -> None:
    assert wr.should_reap_worktree(is_infra=False, live=False, clean=False) is False


def test_no_reap_infra() -> None:
    assert wr.should_reap_worktree(is_infra=True, live=False, clean=True) is False


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
