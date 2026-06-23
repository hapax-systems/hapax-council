from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.continuity_ground_truth import (
    CcTaskState,
    CoordState,
    GitState,
    GroundTruthSnapshot,
    PrState,
    read_ground_truth,
)


def test_read_ground_truth_assembles_dependency_injected_readers() -> None:
    repo = Path(".").resolve()
    captured_at = datetime(2026, 6, 23, 19, 30, tzinfo=UTC)
    calls: list[tuple[str, Path]] = []

    def fake_git_reader(path: Path) -> dict[str, object]:
        calls.append(("git", path))
        return {
            "head": "a" * 40,
            "branch": "codex/cs-p1-f2-d10-ground-truth-20260622",
            "dirty": False,
            "recent_commits": ["a" * 40 + " seed"],
        }

    def fake_pr_reader(path: Path) -> PrState:
        calls.append(("pr", path))
        return PrState(number=4269, state="OPEN", head="feature", merge_state="CLEAN")

    def fake_coord_reader(path: Path) -> CoordState:
        calls.append(("coord", path))
        return CoordState(active_claims=("cx-fugultra=cs-p1-f2-d10-ground-truth-20260622",))

    def fake_cc_task_reader(path: Path, coord: CoordState) -> CcTaskState:
        calls.append(("cc_task", path))
        assert coord.active_claims == ("cx-fugultra=cs-p1-f2-d10-ground-truth-20260622",)
        return CcTaskState(task_id="cs-p1-f2-d10-ground-truth-20260622", status="claimed")

    snapshot = read_ground_truth(
        repo=repo,
        now=lambda: captured_at,
        git_reader=fake_git_reader,
        pr_reader=fake_pr_reader,
        coord_reader=fake_coord_reader,
        cc_task_reader=fake_cc_task_reader,
    )

    assert calls == [("git", repo), ("pr", repo), ("coord", repo), ("cc_task", repo)]
    assert snapshot.captured_at == captured_at
    assert snapshot.provenance == "SOURCE"
    assert snapshot.git.head == "a" * 40
    assert snapshot.pr.number == 4269
    assert snapshot.cc_task.task_id == "cs-p1-f2-d10-ground-truth-20260622"


def test_model_invariants_reject_non_source_and_naive_capture_time() -> None:
    kwargs = {
        "captured_at": datetime(2026, 6, 23, 19, 30, tzinfo=UTC),
        "git": GitState(head="a" * 40, branch="main", dirty=False),
        "pr": PrState(),
        "coord": CoordState(),
        "cc_task": CcTaskState(),
    }

    GroundTruthSnapshot(**kwargs)

    with pytest.raises(ValidationError):
        GroundTruthSnapshot(**kwargs, provenance="SUPPORT")

    with pytest.raises(ValidationError):
        GroundTruthSnapshot(**{**kwargs, "captured_at": datetime(2026, 6, 23, 19, 30)})


def test_model_invariants_reject_blank_and_inconsistent_state() -> None:
    with pytest.raises(ValidationError):
        GitState(head="", branch="main", dirty=False)

    with pytest.raises(ValidationError):
        GitState(head="a" * 40, branch="main", dirty=False, recent_commits=("",))

    with pytest.raises(ValidationError):
        PrState(state="OPEN")

    with pytest.raises(ValidationError):
        CoordState(active_claims=("cx-fugultra=task", " "))

    with pytest.raises(ValidationError):
        CcTaskState(status="claimed")


def test_default_integration_git_head_matches_repo() -> None:
    repo = Path(__file__).resolve().parents[2]
    expected_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    snapshot = read_ground_truth(repo=repo, now=datetime(2026, 6, 23, 19, 30, tzinfo=UTC))

    assert snapshot.git.head == expected_head
    assert snapshot.git.branch
    assert isinstance(snapshot.git.dirty, bool)
    assert snapshot.git.recent_commits
    assert snapshot.pr.number is None or snapshot.pr.number > 0
    assert snapshot.provenance == "SOURCE"
