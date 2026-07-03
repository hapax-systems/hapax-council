"""Tests for the PR registry (Totality slice 1 — status_PR)."""

from __future__ import annotations

import typing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shared import pr_registry as pr
from shared.pr_registry import PrStatus, classify_pr, is_reapable_pr, is_terminal_pr

REPO = "hapax-systems/hapax-council"
T0 = datetime(2026, 7, 2, 12, 0, 0, tzinfo=UTC)
VALID_STATUSES = set(typing.get_args(PrStatus))


@pytest.fixture(autouse=True)
def _isolate_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_PR_REGISTRY_DIR", str(tmp_path / "pr-registry"))


# --- classify_pr (pure) -------------------------------------------------------------------------


def _classify(**over: object) -> PrStatus:
    base: dict[str, object] = dict(
        merged=False,
        closed=False,
        is_bot=False,
        checks_green=True,
        mergeable=True,
        owner_task_status="mutable",
        owner_live=False,
        seen_age_s=0.0,
    )
    base.update(over)
    return classify_pr(**base)  # type: ignore[arg-type]


def test_classify_merged_is_done() -> None:
    assert _classify(merged=True) == "done"


def test_classify_closed_is_closed() -> None:
    assert _classify(closed=True) == "closed"


def test_classify_bot_green_mergeable_is_mergeable_ownerless() -> None:
    assert _classify(is_bot=True, checks_green=True, mergeable=True) == "mergeable_ownerless"


def test_classify_bot_not_green_or_conflicting_is_bot_blocked() -> None:
    assert _classify(is_bot=True, checks_green=False) == "bot_blocked"
    assert _classify(is_bot=True, mergeable=False) == "bot_blocked"


def test_classify_live_owner_beats_dead_task() -> None:
    # a live owning worktree is KEEP (active) even if the task looks closed — join-independent.
    assert _classify(owner_live=True, owner_task_status="closed", seen_age_s=1e9) == "active"


def test_classify_unresolvable_owner_is_indeterminate_bottom() -> None:
    # join-failure is NOT owner-death: protect, never reap on a guess.
    assert _classify(owner_task_status="unresolvable", seen_age_s=1e9) == "indeterminate"


def test_classify_mutable_fresh_active_stale_abandoned() -> None:
    assert _classify(owner_task_status="mutable", seen_age_s=0.0) == "active"
    assert _classify(owner_task_status="mutable", seen_age_s=1e9) == "abandoned"


def test_classify_merge_ready() -> None:
    assert _classify(owner_task_status="merge_ready", mergeable=True, seen_age_s=0.0) == "merging"
    assert _classify(owner_task_status="merge_ready", mergeable=False, seen_age_s=0.0) == "active"
    assert _classify(owner_task_status="merge_ready", seen_age_s=1e9) == "abandoned"


def test_classify_closed_task_grace_then_abandoned() -> None:
    assert _classify(owner_task_status="closed", seen_age_s=0.0) == "active"
    assert _classify(owner_task_status="closed", seen_age_s=1e9) == "abandoned"


def test_classify_missing_task_fresh_protected_stale_orphaned() -> None:
    assert _classify(owner_task_status="missing", seen_age_s=0.0) == "indeterminate"
    assert _classify(owner_task_status="missing", seen_age_s=1e9) == "orphaned"


def test_classify_is_total_over_all_inputs() -> None:
    """status_PR is TOTAL — every input combination maps to a defined PrStatus, never raises."""
    for merged in (True, False):
        for closed in (True, False):
            for is_bot in (True, False):
                for green in (True, False):
                    for mergeable in (True, False):
                        for owner in (
                            "mutable",
                            "merge_ready",
                            "closed",
                            "missing",
                            "unresolvable",
                        ):
                            for live in (True, False):
                                for age in (0.0, 1e9, None):
                                    s = _classify(
                                        merged=merged,
                                        closed=closed,
                                        is_bot=is_bot,
                                        checks_green=green,
                                        mergeable=mergeable,
                                        owner_task_status=owner,
                                        owner_live=live,
                                        seen_age_s=age,
                                    )
                                    assert s in VALID_STATUSES


# --- reap / terminal predicates -----------------------------------------------------------------


def test_is_reapable_only_abandoned_orphaned() -> None:
    assert is_reapable_pr("abandoned")
    assert is_reapable_pr("orphaned")
    for s in (
        "active",
        "merging",
        "done",
        "closed",
        "mergeable_ownerless",
        "bot_blocked",
        "indeterminate",
    ):
        assert not is_reapable_pr(s)  # type: ignore[arg-type]


def test_is_reapable_respects_no_lossy_reap_veto() -> None:
    assert not is_reapable_pr("orphaned", has_unrecoverable_work=True)
    assert not is_reapable_pr("abandoned", has_unrecoverable_work=True)


def test_is_terminal() -> None:
    assert is_terminal_pr("done")
    assert is_terminal_pr("closed")
    for s in ("active", "merging", "abandoned", "orphaned", "indeterminate", "bot_blocked"):
        assert not is_terminal_pr(s)  # type: ignore[arg-type]


# --- registry I/O -------------------------------------------------------------------------------


def test_register_load_roundtrip() -> None:
    pr.register(
        REPO,
        4394,
        head_ref="spine/x",
        task_id="cc-task-x",
        author="dependabot[bot]",
        worktree_path="/w/x",
        now=T0,
    )
    loaded = pr.load(REPO, 4394)
    assert loaded is not None
    assert (loaded.repo, loaded.number) == (REPO, 4394)
    assert loaded.head_ref == "spine/x"
    assert loaded.task_id == "cc-task-x"
    assert loaded.author == "dependabot[bot]"
    assert loaded.worktree_path == "/w/x"
    assert loaded.created_at == T0
    assert loaded.last_seen == T0


def test_register_preserves_created_at_on_refresh() -> None:
    pr.register(REPO, 1, now=T0)
    later = T0 + timedelta(hours=3)
    rec = pr.register(REPO, 1, now=later)
    assert rec.created_at == T0
    assert rec.last_seen == later


def test_pin_is_authoritative_across_refresh() -> None:
    pr.register(REPO, 2, now=T0)
    pr.set_status(REPO, 2, "indeterminate", pinned=True)
    # a plain refresh (no explicit pinned) must NOT clobber the pinned status.
    rec = pr.register(REPO, 2, status="active", now=T0 + timedelta(hours=1))
    assert rec.pinned is True
    assert rec.status == "indeterminate"


def test_heartbeat_updates_last_seen() -> None:
    pr.register(REPO, 3, now=T0)
    later = T0 + timedelta(hours=5)
    rec = pr.heartbeat(REPO, 3, now=later)
    assert rec is not None
    assert rec.last_seen == later


def test_heartbeat_and_set_status_noop_on_absent() -> None:
    assert pr.heartbeat(REPO, 999, now=T0) is None
    assert pr.set_status(REPO, 999, "abandoned") is None
    assert pr.load(REPO, 999) is None


def test_deregister_is_idempotent() -> None:
    pr.register(REPO, 5, now=T0)
    pr.deregister(REPO, 5)
    assert pr.load(REPO, 5) is None
    pr.deregister(REPO, 5)  # no raise on already-gone


def test_absent_vs_corrupt_distinguished() -> None:
    assert pr._read_record(REPO, 42) == (None, False)  # absent
    pr.register(REPO, 42, now=T0)
    pr.record_path(REPO, 42).write_text("{ not json", encoding="utf-8")
    rec, corrupt = pr._read_record(REPO, 42)
    assert rec is None
    assert corrupt is True
    assert pr.load(REPO, 42) is None  # best-effort read returns None on corrupt


def test_register_refuses_to_overwrite_corrupt() -> None:
    pr.register(REPO, 43, now=T0)
    pr.record_path(REPO, 43).write_text("{ not json", encoding="utf-8")
    with pytest.raises(pr.CorruptRecordError):
        pr.register(REPO, 43, now=T0)


def test_list_records_skips_corrupt() -> None:
    pr.register(REPO, 6, now=T0)
    pr.register(REPO, 7, now=T0)
    pr.record_path(REPO, 7).write_text("{ bad", encoding="utf-8")
    nums = {r.number for r in pr.list_records()}
    assert 6 in nums
    assert 7 not in nums


def test_multi_repo_identity_no_collision() -> None:
    pr.register("owner/a", 100, task_id="a-task", now=T0)
    pr.register("owner/b", 100, task_id="b-task", now=T0)
    a = pr.load("owner/a", 100)
    b = pr.load("owner/b", 100)
    assert a is not None and a.task_id == "a-task"
    assert b is not None and b.task_id == "b-task"
