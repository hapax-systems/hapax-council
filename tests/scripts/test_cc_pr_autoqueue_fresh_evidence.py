"""Fresh-evidence admission: a receipt or dossier that lands after a PR's last
examination earns that PR a one-shot full exam on the next tick.

Spec: autoqueue-admits-fresh-receipt-or-dossier-next-tick-20260924. Evidence:
#4729 was examined at 22:07:20Z, its acceptance receipt was written 21 s later,
and the fair rotation put its next examination ~17 ticks away. The mechanism
extends the #4716 must-include seats; it does not raise MUST_INCLUDE_CAP,
MUST_INCLUDE_RESERVE, the refresh-POST cap or bypass storm mode.
"""

from __future__ import annotations

import dataclasses
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shared.merge_queue_lineage import MergeQueueLineageRecord, write_jsonl_records
from tests.scripts.test_cc_pr_autoqueue_rotation import RotationRunner, _admission_status
from tests.test_cc_pr_autoqueue import (
    _make_vault,
    _recent_observed_at,
    _write_task,
    autoqueue,
)


def tick(
    tmp_path: Path,
    runner: RotationRunner,
    vault: Path,
    *,
    limit: int = 5,
    apply: bool = True,
    lineage_ledger_path: Path | None = None,
) -> dict:
    return autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        runner=runner,
        apply=apply,
        limit=limit,
        rotation_state_path=tmp_path / "examined.json",
        lineage_ledger_path=lineage_ledger_path,
        quarantine_path=tmp_path / "quarantine.json",
        admission_governor_path=tmp_path / "governor.yaml",
    )


def examined(report: dict) -> list[int]:
    assert not report.get("skipped"), report
    return [decision["pr"] for decision in report["decisions"]]


def _state(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "examined.json").read_text())


def _examined_at(tmp_path: Path, number: int) -> datetime:
    return datetime.fromisoformat(_state(tmp_path)["repositories"]["owner/repo"][str(number)])


def _age_rotation_state(tmp_path: Path, seconds: int) -> None:
    """Shift every examination stamp into the past, preserving rotation order.

    Tests then land evidence at "examination + N s" without writing files
    dated in the future.
    """
    path = tmp_path / "examined.json"
    state = json.loads(path.read_text())
    stamps = state["repositories"]["owner/repo"]
    for number, stamp in stamps.items():
        stamps[number] = (datetime.fromisoformat(stamp) - timedelta(seconds=seconds)).isoformat()
    path.write_text(json.dumps(state))


def _set_mtime(path: Path, at: datetime) -> None:
    os.utime(path, (at.timestamp(), at.timestamp()))


def _land_receipt(
    vault: Path, task_id: str, *, mtime: datetime, timestamp: datetime | None = None
) -> Path:
    path = vault / "active" / f"{task_id}.acceptance.yaml"
    path.write_text(
        "acceptor: review-team:claude,gemini\n"
        "verdict: accepted\n"
        f"timestamp: '{(timestamp or mtime).isoformat()}'\n"
        "artifact: dossier\n",
        encoding="utf-8",
    )
    _set_mtime(path, mtime)
    return path


def _land_dossier(vault: Path, task_id: str, *, mtime: datetime) -> Path:
    path = vault / "active" / f"{task_id}.review-dossier.yaml"
    path.write_text(
        f"dossier_schema: 1\ntask_id: {task_id}\nconstituted_at: '{mtime.isoformat()}'\n",
        encoding="utf-8",
    )
    _set_mtime(path, mtime)
    return path


def _estate(
    tmp_path: Path, *, count: int, linked: range | list[int]
) -> tuple[RotationRunner, Path]:
    vault = _make_vault(tmp_path)
    for number in linked:
        _write_task(vault, task_id=f"task-{number}", pr=number)
    return RotationRunner(count), vault


def _examine_all(tmp_path: Path, runner: RotationRunner, vault: Path, *, count: int) -> None:
    for _ in range(-(-count // 5)):
        tick(tmp_path, runner, vault)
    _age_rotation_state(tmp_path, 120)


# ── unsafe cases first ─────────────────────────────────────────────────────


def test_fresh_evidence_seat_is_one_shot_when_hydration_keeps_failing(tmp_path: Path) -> None:
    # A PR whose full exam fails must not hold a must-include seat every tick:
    # the failed attempt counts as the examination the evidence is compared to.
    runner, vault = _estate(tmp_path, count=25, linked=[13])
    for _ in range(3):
        tick(tmp_path, runner, vault)
    _age_rotation_state(tmp_path, 120)
    _land_receipt(vault, "task-13", mtime=_examined_at(tmp_path, 13) + timedelta(seconds=21))
    runner.fail_hydration = {13}
    runner.calls.clear()
    report = tick(tmp_path, runner, vault)
    assert 13 in runner.hydrated_numbers()  # The one-shot was attempted...
    assert report["must_include"]["fresh_evidence"] == [13]
    runner.calls.clear()
    report = tick(tmp_path, runner, vault)
    assert 13 not in runner.hydrated_numbers()  # ...and not re-seated after failing.
    assert report["must_include"]["fresh_evidence"] == []


def test_future_dated_evidence_never_jumps_the_rotation(tmp_path: Path) -> None:
    # Clock skew or a bogus timestamp would otherwise keep the PR "fresh"
    # after every exam until real time caught up: future times are discarded.
    runner, vault = _estate(tmp_path, count=25, linked=[13])
    for _ in range(3):
        tick(tmp_path, runner, vault)
    future = datetime.now(UTC) + timedelta(days=365)
    _land_receipt(vault, "task-13", mtime=future)
    _land_dossier(vault, "task-13", mtime=future)
    for expected in ([16, 17, 18, 19, 20], [21, 22, 23, 24, 25]):
        report = tick(tmp_path, runner, vault)
        assert examined(report) == expected
        assert report["must_include"]["fresh_evidence"] == []


def test_never_examined_pr_with_receipt_takes_no_fresh_seat(tmp_path: Path) -> None:
    # A PR with no examination stamp already heads the rotation; a lost
    # rotation state must not turn every receipt-bearing PR into a seat.
    runner, vault = _estate(tmp_path, count=25, linked=[20])
    _land_receipt(vault, "task-20", mtime=datetime.now(UTC) - timedelta(minutes=5))
    report = tick(tmp_path, runner, vault)
    assert examined(report) == [1, 2, 3, 4, 5]
    assert report["must_include"]["fresh_evidence"] == []


def test_malformed_receipt_falls_back_to_mtime_without_failing_the_tick(tmp_path: Path) -> None:
    runner, vault = _estate(tmp_path, count=25, linked=[13])
    for _ in range(3):
        tick(tmp_path, runner, vault)
    _age_rotation_state(tmp_path, 120)
    path = vault / "active" / "task-13.acceptance.yaml"
    path.write_text("timestamp: [unterminated\n", encoding="utf-8")
    last_exam = _examined_at(tmp_path, 13)
    # An old mtime forces the parse; the malformed file must not fail the tick.
    _set_mtime(path, last_exam - timedelta(seconds=21))
    report = tick(tmp_path, runner, vault, apply=False)
    assert examined(report) == [16, 17, 18, 19, 20]
    # Its mtime alone still counts.
    _set_mtime(path, last_exam + timedelta(seconds=21))
    report = tick(tmp_path, runner, vault)
    assert 13 in examined(report)


def test_must_include_killswitch_also_disables_fresh_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, vault = _estate(tmp_path, count=25, linked=[13])
    for _ in range(3):
        tick(tmp_path, runner, vault)
    _age_rotation_state(tmp_path, 120)
    _land_receipt(vault, "task-13", mtime=_examined_at(tmp_path, 13) + timedelta(seconds=21))
    monkeypatch.setenv("HAPAX_AUTOQUEUE_MUST_INCLUDE_OFF", "1")
    report = tick(tmp_path, runner, vault)
    assert examined(report) == [16, 17, 18, 19, 20]
    assert report["must_include"]["fresh_evidence"] == []


# ── (a) and (b): the exit predicate ────────────────────────────────────────


@pytest.mark.parametrize("source", ["receipt_mtime", "receipt_timestamp", "dossier_mtime"])
def test_evidence_21s_after_examination_is_examined_next_tick(tmp_path: Path, source: str) -> None:
    # (a) #4729's shape: evidence lands 21 s after the PR's examination; the
    # next tick examines it ahead of the rotation, and only once.
    runner, vault = _estate(tmp_path, count=25, linked=[13])
    for _ in range(3):
        tick(tmp_path, runner, vault)
    _age_rotation_state(tmp_path, 120)
    last_exam = _examined_at(tmp_path, 13)
    after, before = last_exam + timedelta(seconds=21), last_exam - timedelta(seconds=21)
    if source == "receipt_mtime":
        _land_receipt(vault, "task-13", mtime=after, timestamp=before)
    elif source == "receipt_timestamp":
        # An mtime preserved by a copy or sync, but the recorded verdict is new.
        _land_receipt(vault, "task-13", mtime=before, timestamp=after)
    else:
        _land_dossier(vault, "task-13", mtime=after)
    runner.calls.clear()
    report = tick(tmp_path, runner, vault)
    window = examined(report)
    assert 13 in window
    assert 13 in runner.hydrated_numbers()  # A full exam, not the refresh path.
    assert sorted(window) == [13, 16, 17, 18, 19]  # The window stays 5 wide.
    assert report["must_include"]["fresh_evidence"] == [13]
    assert _examined_at(tmp_path, 13) > after
    report = tick(tmp_path, runner, vault)
    assert 13 not in examined(report)
    assert report["must_include"]["fresh_evidence"] == []


def test_evidence_older_than_examination_does_not_jump_the_rotation(tmp_path: Path) -> None:
    # (b) A receipt and dossier that predate the last examination were already
    # seen by it; the PR keeps its rotation place.
    runner, vault = _estate(tmp_path, count=25, linked=[13])
    for _ in range(3):
        tick(tmp_path, runner, vault)
    _age_rotation_state(tmp_path, 120)
    before = _examined_at(tmp_path, 13) - timedelta(seconds=21)
    _land_receipt(vault, "task-13", mtime=before)
    _land_dossier(vault, "task-13", mtime=before)
    report = tick(tmp_path, runner, vault)
    assert examined(report) == [16, 17, 18, 19, 20]
    assert report["must_include"]["fresh_evidence"] == []


@pytest.mark.parametrize("transport", ["rest", "graphql"])
def test_branch_linked_task_evidence_counts(tmp_path: Path, transport: str) -> None:
    # A task linked by branch (no pr field yet) is matched the way
    # classify_pr matches it, from either listing shape (REST head.ref,
    # GraphQL headRefName).
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="task-by-branch", branch="feat/13")
    runner = RotationRunner(25, transport)
    for _ in range(3):
        tick(tmp_path, runner, vault)
    _age_rotation_state(tmp_path, 120)
    _land_receipt(vault, "task-by-branch", mtime=_examined_at(tmp_path, 13) + timedelta(seconds=21))
    report = tick(tmp_path, runner, vault)
    assert 13 in examined(report)


# ── (c) caps, reserve and overflow ─────────────────────────────────────────


def test_fresh_overflow_beyond_cap_carries_to_next_tick_with_reserve_kept(
    tmp_path: Path,
) -> None:
    # (c) Twelve fresh PRs at limit 5: MUST_INCLUDE_CAP (8) are served, oldest
    # examination first; MUST_INCLUDE_RESERVE (2) rotation slots survive; the
    # other four are reported and served next tick, not dropped.
    assert (autoqueue.MUST_INCLUDE_CAP, autoqueue.MUST_INCLUDE_RESERVE) == (8, 2)
    runner, vault = _estate(tmp_path, count=30, linked=range(13, 25))
    _examine_all(tmp_path, runner, vault, count=30)
    for number in range(13, 25):
        _land_receipt(
            vault,
            f"task-{number}",
            mtime=_examined_at(tmp_path, number) + timedelta(seconds=21),
        )
    report = tick(tmp_path, runner, vault)
    window = examined(report)
    assert sorted(window) == [1, 2, *range(13, 21)]
    assert report["must_include"]["fresh_evidence"] == list(range(13, 21))
    assert report["must_include"]["fresh_evidence_overflow"] == [21, 22, 23, 24]
    report = tick(tmp_path, runner, vault)
    assert sorted(examined(report)) == [3, 4, 21, 22, 23, 24]
    assert report["must_include"]["fresh_evidence"] == [21, 22, 23, 24]
    assert report["must_include"]["fresh_evidence_overflow"] == []


def test_queued_and_armed_seats_are_served_before_fresh_evidence(tmp_path: Path) -> None:
    # (c) The #4716 guarantee is not weakened: with the cap filled by queued
    # PRs, a fresh-evidence PR overflows and the queued refreshes all happen.
    runner, vault = _estate(tmp_path, count=30, linked=[25])
    _examine_all(tmp_path, runner, vault, count=30)
    _land_receipt(vault, "task-25", mtime=_examined_at(tmp_path, 25) + timedelta(seconds=21))
    runner.queued_prs = set(range(1, 9))
    report = tick(tmp_path, runner, vault)
    assert report["must_include"]["fresh_evidence"] == []
    assert report["must_include"]["fresh_evidence_overflow"] == [25]
    assert report["must_include"]["overflow"] == []
    assert 25 not in examined(report)
    # The queue drains: its eight PRs become R6 dequeued follow-ups, which also
    # rank ahead, so #25 is carried again rather than dropped...
    runner.queued_prs = set()
    report = tick(tmp_path, runner, vault)
    assert report["must_include"]["dequeued_followup"] == list(range(1, 9))
    assert report["must_include"]["fresh_evidence_overflow"] == [25]
    assert 25 not in examined(report)
    # ...and served on the first tick the cap has room.
    report = tick(tmp_path, runner, vault)
    assert 25 in examined(report)
    assert report["must_include"]["fresh_evidence"] == [25]


def test_fresh_evidence_spends_no_refresh_post_budget(tmp_path: Path) -> None:
    # (c) Fresh rows take the full-exam path; the must-include refresh-POST
    # cap (4 per tick) stays with the queued/armed refresh rows.
    runner, vault = _estate(tmp_path, count=30, linked=[25])
    _examine_all(tmp_path, runner, vault, count=30)
    _land_receipt(vault, "task-25", mtime=_examined_at(tmp_path, 25) + timedelta(seconds=21))
    runner.queued_prs = {1, 2, 3, 4, 5}
    for number in range(1, 6):
        runner.head_statuses[f"sha-{number}"] = [_admission_status("success", age_minutes=16)]
    report = tick(tmp_path, runner, vault)
    assert report["must_include"]["refreshed"] == [1, 2, 3, 4]
    assert report["must_include"]["deferred"]["5"] == "deferred_post_cap"
    assert report["must_include"]["fresh_evidence"] == [25]


# ── (d) storm mode still limits the tick ───────────────────────────────────


def test_storm_mode_still_holds_a_fresh_evidence_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # (d) A fresh-evidence exam is an ordinary classify_pr pass: under a rate
    # freeze an otherwise admissible PR is held, not queued, and the window
    # does not grow past the requested limit for one fresh PR.
    monkeypatch.setenv("HAPAX_REVIEW_TEAM_GATE_OFF", "1")
    monkeypatch.setattr(
        autoqueue.review_team, "review_route_blocked_families", lambda *_a, **_k: {}
    )
    runner, vault = _estate(tmp_path, count=25, linked=[13])
    ledger = tmp_path / "merge-queue-lineage.jsonl"
    write_jsonl_records(
        ledger,
        [
            MergeQueueLineageRecord(
                observed_at=_recent_observed_at(i),
                pr_number=90 + i,
                merge_group_run_id=9300 + i,
                run_conclusion="failure",
                run_outcome="failure",
            )
            for i in range(4)
        ],
    )
    for _ in range(3):
        tick(tmp_path, runner, vault, lineage_ledger_path=ledger)
    _age_rotation_state(tmp_path, 120)
    _land_receipt(vault, "task-13", mtime=_examined_at(tmp_path, 13) + timedelta(seconds=21))
    runner.calls.clear()
    report = tick(tmp_path, runner, vault, lineage_ledger_path=ledger)
    assert report["storm_mode"]["active"] is True
    decisions = {item["pr"]: item for item in report["decisions"]}
    assert len(decisions) == 5
    assert report["must_include"]["fresh_evidence"] == [13]
    assert decisions[13]["action"] != "queue"
    assert any(
        reason.startswith("storm_admission_hold:") for reason in decisions[13].get("reasons", [])
    )
    assert not any(call[:4] == ["gh", "pr", "merge", "13"] for call in runner.calls)


# ── (e) a seat release stamp is fresh evidence ─────────────────────────────
# admission-encode-seat-t2-release-rule-20260925: #4759 was stamped at 08:07Z, 32 min after its
# 07:35Z examination, and sat at rotation rank 62/130 (~3 h) because a stamp is a note edit,
# not a receipt or dossier.


def _stamp(
    vault: Path, number: int, *, mtime: datetime, head: str | None = None, authorized: bool = True
) -> Path:
    extra: dict[str, object] = {"release_authorized": authorized}
    if head is not None:
        extra["release_authorized_head_sha"] = head
    path = _write_task(vault, task_id=f"task-{number}", pr=number, extra_frontmatter=extra)
    _set_mtime(path, mtime)
    return path


def _examined_estate(tmp_path: Path) -> tuple[RotationRunner, Path, datetime]:
    runner, vault = _estate(tmp_path, count=25, linked=[13])
    _set_mtime(vault / "active" / "task-13.md", datetime.now(UTC) - timedelta(hours=1))
    for _ in range(3):
        tick(tmp_path, runner, vault)
    _age_rotation_state(tmp_path, 120)
    return runner, vault, _examined_at(tmp_path, 13)


@pytest.mark.parametrize(
    ("head", "authorized", "offset_s"),
    [
        (None, True, 21),  # a note edit that stamps no head
        ("sha-old", True, 21),  # a stamp for a head the PR no longer has
        ("sha-13", False, 21),  # the head is named, but release is not authorized
        ("sha-13", True, -21),  # a stamp the last examination already saw
    ],
)
def test_a_note_edit_that_is_not_a_current_head_stamp_keeps_the_rotation(
    tmp_path: Path, head: str | None, authorized: bool, offset_s: int
) -> None:
    runner, vault, last_exam = _examined_estate(tmp_path)
    _stamp(
        vault, 13, head=head, authorized=authorized, mtime=last_exam + timedelta(seconds=offset_s)
    )
    report = tick(tmp_path, runner, vault)
    assert examined(report) == [16, 17, 18, 19, 20]
    assert report["must_include"]["fresh_evidence"] == []


def test_an_unreadable_stamped_note_is_not_evidence(tmp_path: Path) -> None:
    # The stamp probe's fallback narrows: a note that cannot be stat'ed is not fresh.
    vault = _make_vault(tmp_path)
    path = _stamp(vault, 13, head="sha-13", mtime=datetime.now(UTC) - timedelta(minutes=1))
    task = autoqueue.load_task_notes(vault)[0]
    since = datetime.now(UTC) - timedelta(hours=1)
    assert autoqueue._release_stamp_newer_than(task, "sha-13", since, now=datetime.now(UTC))
    path.unlink()
    assert not autoqueue._release_stamp_newer_than(task, "sha-13", since, now=datetime.now(UTC))


def test_a_future_dated_stamp_never_jumps_the_rotation(tmp_path: Path) -> None:
    runner, vault, _ = _examined_estate(tmp_path)
    _stamp(vault, 13, head="sha-13", mtime=datetime.now(UTC) + timedelta(days=365))
    report = tick(tmp_path, runner, vault)
    assert examined(report) == [16, 17, 18, 19, 20]
    assert report["must_include"]["fresh_evidence"] == []


def test_a_seat_release_stamp_at_the_current_head_is_examined_next_tick(tmp_path: Path) -> None:
    runner, vault, last_exam = _examined_estate(tmp_path)
    after = last_exam + timedelta(seconds=21)
    _stamp(vault, 13, head="sha-13", mtime=after)
    runner.calls.clear()
    report = tick(tmp_path, runner, vault)
    assert 13 in examined(report)
    assert 13 in runner.hydrated_numbers()  # a full exam, not the refresh path
    assert report["must_include"]["fresh_evidence"] == [13]
    assert _examined_at(tmp_path, 13) > after
    report = tick(tmp_path, runner, vault)
    assert 13 not in examined(report)  # one-shot
    assert report["must_include"]["fresh_evidence"] == []


# ── a route flap, or a row turning ready, after the exam ───────────────────
# Row cc-pr-autoqueue-fresh-evidence-counts-a-row-turning-ready-20261011. A PR
# blocked only by a review-route flap passes only when the live route state at
# its exam matches the state at constitution; a row that turns pr_open is
# neither a receipt nor a dossier. Both waited for the rotation (~4 h).

SEATED_GLM = "review_dossier_blocked_route_family_seated:glm"
UNWITNESSED_CLAUDE = "review_dossier_route_block_degradation_unwitnessed:claude"
_EXAM = datetime(2026, 10, 11, 7, 46, 4, tzinfo=UTC)


def _entry(
    *,
    blockers: tuple[str, ...] = (SEATED_GLM,),
    route_blocked: list[str] | None = None,
    task_status: str | None = "pr_open",
) -> dict:
    return {
        "head_sha": "sha-13",
        "blockers": list(blockers),
        "route_blocked": ["glm"] if route_blocked is None else route_blocked,
        "task_status": task_status,
        "examined_at": _EXAM.isoformat(),
    }


def _due(
    entry: dict,
    *,
    head: str = "sha-13",
    status: str | None = "pr_open",
    live: frozenset[str] | None = frozenset(),
    since: datetime = _EXAM,
) -> str | None:
    return autoqueue._exam_ledger_reexam_due(
        entry, head_sha=head, task_status=status, live_route_blocked=live, since=since
    )


def test_flap_blocker_families_reads_only_flap_only_blocker_sets() -> None:
    families = autoqueue._flap_blocker_families
    assert families([SEATED_GLM, UNWITNESSED_CLAUDE]) == {
        "seated": frozenset({"glm"}),
        "unwitnessed": frozenset({"claude"}),
    }
    both = families(["review_dossier_blocked_route_family_seated:glm,gemini"])
    assert both is not None and both["seated"] == frozenset({"glm", "gemini"})
    assert families([SEATED_GLM, "failed_checks:lint"]) is None  # any other blocker
    assert families([]) is None
    assert families(["review_dossier_blocked_route_family_seated:"]) is None  # no family


def test_a_seated_flap_is_due_once_its_family_is_admitted_again() -> None:
    # #5048 at 07:46:04Z: GLM's 900 s receipt went stale one second after constitution.
    entry = _entry(blockers=(SEATED_GLM,), route_blocked=["glm"])
    assert _due(entry, live=frozenset()) == "route_flap_satisfied"
    assert _due(entry, live=frozenset({"glm"})) is None  # unchanged: the same verdict
    assert _due(entry, live=frozenset({"glm", "codex"})) is None  # changed, glm still blocked


def test_an_unwitnessed_degradation_is_due_once_its_family_is_blocked_again() -> None:
    # #5104 and #5111 at 08:49:59Z: claude blocked at constitution, live at the exam.
    entry = _entry(blockers=(UNWITNESSED_CLAUDE,), route_blocked=[])
    assert _due(entry, live=frozenset({"claude"})) == "route_flap_satisfied"
    assert _due(entry, live=frozenset()) is None
    assert _due(entry, live=frozenset({"glm"})) is None


def test_no_flap_reexam_for_a_moved_head_another_blocker_or_an_unknown_state() -> None:
    assert _due(_entry(), head="sha-new") is None
    assert _due(_entry(blockers=(SEATED_GLM, "hold_labels:hold"))) is None
    assert _due(_entry(), live=None) is None
    assert _due({**_entry(), "route_blocked": None}) is None


def test_a_row_turning_ready_after_its_exam_is_due_and_only_then() -> None:
    not_ready = _entry(
        blockers=("active_task_status_not_ready:in_progress",), task_status="in_progress"
    )
    assert _due(not_ready, status="pr_open", live=frozenset({"glm"})) == "row_turned_ready"
    assert _due(not_ready, status="in_progress", live=frozenset({"glm"})) is None
    ready = _entry(blockers=(), task_status="pr_open")
    assert _due(ready, status="pr_open", live=frozenset({"glm"})) is None
    assert _due(ready, status="in_progress", live=frozenset({"glm"})) is None


def test_the_reexam_is_one_shot_after_a_later_failed_attempt() -> None:
    # A failed hydration after the recorded exam advances the attempt stamp.
    assert _due(_entry(), since=_EXAM + timedelta(minutes=6)) is None


def test_a_flap_blocked_pr_is_examined_on_the_first_tick_its_route_state_flips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = {"blocked": frozenset({"glm"})}
    monkeypatch.setattr(autoqueue, "_live_review_route_blocked_families", lambda: live["blocked"])
    real_classify = autoqueue.classify_pr

    def classify(pr, **kwargs):  # type: ignore[no-untyped-def]
        decision = real_classify(pr, **kwargs)
        if pr.number != 13:
            return decision
        return dataclasses.replace(decision, action="blocked", reasons=(SEATED_GLM,))

    monkeypatch.setattr(autoqueue, "classify_pr", classify)
    runner, vault = _estate(tmp_path, count=25, linked=[13])
    for _ in range(3):
        tick(tmp_path, runner, vault)
    _age_rotation_state(tmp_path, 120)
    report = tick(tmp_path, runner, vault)  # glm is still blocked: the rotation goes on
    assert examined(report) == [16, 17, 18, 19, 20]
    assert report["must_include"]["fresh_evidence"] == []
    live["blocked"] = frozenset()  # GLM's receipt is fresh again
    report = tick(tmp_path, runner, vault)
    assert 13 in examined(report)
    assert report["must_include"]["fresh_evidence"] == [13]
    report = tick(tmp_path, runner, vault)  # one-shot: that exam recorded the new state
    assert 13 not in examined(report)
    assert report["must_include"]["fresh_evidence"] == []


def test_a_row_turning_pr_open_after_its_exam_is_examined_next_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # #5047: examined at 06:04:46Z while its row read in_progress; the row turned
    # pr_open at 07:15Z, and the rotation put its next exam hours away.
    monkeypatch.setattr(autoqueue, "_live_review_route_blocked_families", lambda: frozenset())
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="task-13", pr=13, status="in_progress")
    runner = RotationRunner(25)
    for _ in range(3):
        tick(tmp_path, runner, vault)
    _age_rotation_state(tmp_path, 120)
    report = tick(tmp_path, runner, vault)  # still in_progress: no seat
    assert 13 not in examined(report)
    _write_task(vault, task_id="task-13", pr=13, status="pr_open")
    report = tick(tmp_path, runner, vault)
    assert 13 in examined(report)
    assert report["must_include"]["fresh_evidence"] == [13]
    report = tick(tmp_path, runner, vault)  # one-shot
    assert 13 not in examined(report)


# ── the ledger fails open: a failure only removes seats, never crashes a tick ──


def test_a_naive_examined_at_grants_nothing_and_does_not_raise() -> None:
    naive = {**_entry(), "examined_at": "2026-10-11T07:46:04"}  # no timezone
    assert _due(naive) is None
    assert _due({**_entry(), "examined_at": "not-a-time"}) is None


def test_the_ledger_loader_skips_what_it_cannot_ground(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    path = tmp_path / "examined.json.exam-ledger.json"
    load = autoqueue._load_exam_ledger
    path.write_text("{not json", encoding="utf-8")
    assert load(path, repo="owner/repo", now=now) == {}
    path.write_text(json.dumps({"schema_version": 2, "repositories": {}}), encoding="utf-8")
    assert load(path, repo="owner/repo", now=now) == {}
    good = {**_entry(), "examined_at": (now - timedelta(minutes=5)).isoformat()}
    entries = {
        "13": good,
        "14": {**good, "examined_at": "2026-10-11T07:46:04"},  # naive: skipped, no raise
        "15": {**good, "examined_at": (now - timedelta(days=8)).isoformat()},  # aged out
        "16": "not a mapping",
        "nan": good,
    }
    path.write_text(
        json.dumps({"schema_version": 1, "repositories": {"owner/repo": entries}}),
        encoding="utf-8",
    )
    assert list(load(path, repo="owner/repo", now=now)) == [13]


def test_a_ledger_write_failure_is_logged_not_raised(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("", encoding="utf-8")
    # The parent is a file, so every write under it fails with OSError.
    autoqueue._save_exam_ledger(blocker / "ledger.json", "owner/repo", {13: _entry()})
    assert not (blocker / "ledger.json").exists()


def test_an_unreadable_route_state_grants_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_registry):  # type: ignore[no-untyped-def]
        raise RuntimeError("registry unreadable")

    monkeypatch.setattr(autoqueue.review_team, "review_route_blocked_families", boom)
    assert autoqueue._live_review_route_blocked_families() is None


def test_a_row_turning_ready_is_due_even_across_a_moved_head() -> None:
    # By design: readiness is the row's, not the head's, and the exam reruns every check.
    not_ready = _entry(blockers=("active_task_status_not_ready:claimed",), task_status="claimed")
    assert _due(not_ready, head="sha-new", status="pr_open") == "row_turned_ready"
