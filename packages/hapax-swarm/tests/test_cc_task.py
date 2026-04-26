"""Tests for cc_task.py — markdown-with-frontmatter SSOT."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from hapax_swarm import CcTask, CcTaskStatus
from hapax_swarm.cc_task import CcTaskStateError

if TYPE_CHECKING:
    from pathlib import Path

SAMPLE = """\
---
type: cc-task
task_id: leverage-workflow-hapax-swarm-pypi
title: "hapax-swarm PyPI"
status: offered
assigned_to: unassigned
priority: high
wsjf: 6.0
created_at: 2026-04-25T22:45:00Z
updated_at: 2026-04-25T22:45:00Z
claimed_at: null
completed_at: null
---

# hapax-swarm PyPI

Body.
"""


def _write(path: Path, text: str = SAMPLE) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_load_parses_frontmatter_and_body(tmp_path: Path) -> None:
    task = CcTask.load(_write(tmp_path / "x.md"))
    assert task.task_id == "leverage-workflow-hapax-swarm-pypi"
    assert task.status is CcTaskStatus.OFFERED
    assert task.assigned_to is None
    assert task.body.startswith("\n# hapax-swarm PyPI\n")


def test_claim_transitions_offered_to_claimed(tmp_path: Path) -> None:
    task = CcTask.load(_write(tmp_path / "x.md"))
    task.claim(role="beta")
    assert task.status is CcTaskStatus.CLAIMED
    assert task.assigned_to == "beta"
    assert task.frontmatter["claimed_at"].endswith("Z")
    assert task.frontmatter["claimed_at"] != "null"


def test_claim_rejects_non_offered(tmp_path: Path) -> None:
    task = CcTask.load(_write(tmp_path / "x.md"))
    task.claim(role="beta")
    task.start()
    with pytest.raises(CcTaskStateError):
        task.claim(role="alpha")


def test_claim_rejects_already_assigned(tmp_path: Path) -> None:
    text = SAMPLE.replace("assigned_to: unassigned", "assigned_to: alpha")
    task = CcTask.load(_write(tmp_path / "x.md", text))
    with pytest.raises(CcTaskStateError):
        task.claim(role="beta")


def test_start_transitions_claimed_to_in_progress(tmp_path: Path) -> None:
    task = CcTask.load(_write(tmp_path / "x.md"))
    task.claim(role="beta")
    task.start()
    assert task.status is CcTaskStatus.IN_PROGRESS


def test_start_rejects_offered(tmp_path: Path) -> None:
    task = CcTask.load(_write(tmp_path / "x.md"))
    with pytest.raises(CcTaskStateError):
        task.start()


def test_open_pr_records_pr_and_branch(tmp_path: Path) -> None:
    task = CcTask.load(_write(tmp_path / "x.md"))
    task.claim(role="beta")
    task.start()
    task.open_pr(pr_url="https://github.com/x/y/pull/1", branch="beta/foo")
    assert task.status is CcTaskStatus.PR_OPEN
    assert task.frontmatter["pr"] == "https://github.com/x/y/pull/1"
    assert task.frontmatter["branch"] == "beta/foo"


def test_mark_done_stamps_completed_at(tmp_path: Path) -> None:
    task = CcTask.load(_write(tmp_path / "x.md"))
    task.claim(role="beta")
    task.start()
    task.mark_done()
    assert task.status is CcTaskStatus.DONE
    assert task.frontmatter["completed_at"].endswith("Z")


def test_save_roundtrip_preserves_body(tmp_path: Path) -> None:
    target = _write(tmp_path / "x.md")
    task = CcTask.load(target)
    task.claim(role="beta")
    task.save()

    reloaded = CcTask.load(target)
    assert reloaded.status is CcTaskStatus.CLAIMED
    assert reloaded.assigned_to == "beta"
    assert reloaded.body == task.body


def test_load_rejects_non_frontmatter(tmp_path: Path) -> None:
    target = tmp_path / "x.md"
    target.write_text("no frontmatter here\n")
    with pytest.raises(ValueError):
        CcTask.load(target)
