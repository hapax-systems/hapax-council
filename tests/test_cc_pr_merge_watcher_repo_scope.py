"""A bare PR number is not a link: the watcher must match on (repo, number).

MEASURED 2026-08-04. `cc-pr-merge-watcher` queries merged PRs in hapax-council only, then matched
vault tasks with `^pr:\\s*N\\s*$` -- the number alone. A task meaning `reins#6` was closed twice
while that PR was still open, because `hapax-council#6` is merged. Two sibling tasks meaning
`reins-dev#11` and `reins-dev#8` survived the SAME watcher run, because they declared `pr_repo`.
Three tasks, one mechanism, two outcomes, and the discriminator was an optional field.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_WATCHER = Path(__file__).resolve().parent.parent / "scripts" / "cc-pr-merge-watcher.py"
_spec = importlib.util.spec_from_file_location("cc_pr_merge_watcher", _WATCHER)
assert _spec and _spec.loader
watcher = importlib.util.module_from_spec(_spec)
sys.modules["cc_pr_merge_watcher"] = watcher
_spec.loader.exec_module(watcher)

COUNCIL = "hapax-systems/hapax-council"
REINS = "hapax-systems/reins"


def _note(vault: Path, task_id: str, pr: int, pr_repo: str | None) -> Path:
    active = vault / "active"
    active.mkdir(parents=True, exist_ok=True)
    repo_line = f"pr_repo: {pr_repo}\n" if pr_repo is not None else ""
    path = active / f"{task_id}.md"
    path.write_text(
        f"---\ntype: cc-task\ntask_id: {task_id}\nstatus: pr_open\n{repo_line}pr: {pr}\n---\n\nbody\n",
        encoding="utf-8",
    )
    return path


def test_a_merged_council_pr_does_not_close_a_task_whose_pr_is_in_another_repo(tmp_path) -> None:
    """THE INCIDENT. Same number, different repository, and the watcher only sees council."""
    _note(tmp_path, "task-in-reins", 6, REINS)

    assert watcher.find_linked_tasks(6, repo=COUNCIL, vault_root=tmp_path) == [], (
        "a merged council PR #6 matched a task whose PR #6 is in reins. The number is not the link."
    )


def test_the_same_number_in_the_matching_repo_does_close(tmp_path) -> None:
    """The fix must not simply stop closing things."""
    _note(tmp_path, "task-in-council", 6, COUNCIL)

    found = watcher.find_linked_tasks(6, repo=COUNCIL, vault_root=tmp_path)
    assert [t.task_id for t in found] == ["task-in-council"]


def test_a_task_with_no_pr_repo_is_not_matched_and_is_reported(tmp_path, caplog) -> None:
    """UNDECLARED IS NOT COUNCIL.

    Defaulting an absent field to a wrong non-empty value is the estate's absence-into-zero
    pattern, and here it fails in the direction that marks work DONE. Not matching is the safe
    direction -- a task stays open until someone declares where its PR lives -- and it is reported
    so an undeclared link is visible rather than silent.
    """
    _note(tmp_path, "task-undeclared", 4499, None)

    with caplog.at_level("WARNING"):
        found = watcher.find_linked_tasks(4499, repo=COUNCIL, vault_root=tmp_path)

    assert found == [], "an undeclared pr_repo was treated as the council repo"
    assert "no pr_repo" in caplog.text, "the undeclared link was skipped silently"
    assert "task-undeclared" in caplog.text, "the operator must be told WHICH task to fix"


@pytest.mark.parametrize("nullish", ["null", "none", "~", "", "  ", "NULL", "None"])
def test_yaml_spellings_of_absent_are_all_treated_as_absent(tmp_path, caplog, nullish) -> None:
    """`pr_repo: null` is not a repository named "null".

    THE ASSERTION IS ON THE WARNING, not on the empty result. Not-matching is the same outcome
    either way -- "null" is not the council repo, so the comparison rejects it regardless -- which
    means a test asserting only `== []` passes with the nullish handling deleted. It did: that
    mutant survived until this test moved to the property that actually differs.

    What differs is whether the operator is TOLD. Undeclared must be reported as undeclared, so the
    link gets fixed; silently failing a string comparison leaves a task that will never close and
    no indication why.
    """
    _note(tmp_path, "task-nullish", 4499, nullish)

    with caplog.at_level("WARNING"):
        assert watcher.find_linked_tasks(4499, repo=COUNCIL, vault_root=tmp_path) == []

    assert "no pr_repo" in caplog.text, (
        f"pr_repo: {nullish!r} was treated as a repository NAME rather than as absent, so the task "
        f"silently fails a string comparison forever with nothing reported"
    )


def test_the_three_tasks_from_the_incident_resolve_as_they_should_have(tmp_path) -> None:
    """The exact configuration of the run that mis-closed one of them.

    All three carry a PR number that also exists as a merged council PR. Only the council one may
    be closed by a council merge.
    """
    _note(tmp_path, "reins-6", 6, REINS)
    _note(tmp_path, "reins-dev-11", 11, "hapax-systems/reins-dev")
    _note(tmp_path, "council-6", 6, COUNCIL)

    assert [t.task_id for t in watcher.find_linked_tasks(6, repo=COUNCIL, vault_root=tmp_path)] == [
        "council-6"
    ]
    assert watcher.find_linked_tasks(11, repo=COUNCIL, vault_root=tmp_path) == []
    assert [
        t.task_id for t in watcher.find_linked_tasks(6, repo=REINS, vault_root=tmp_path)
    ] == ["reins-6"]


def test_find_linked_task_singular_carries_the_same_scope(tmp_path) -> None:
    """The legacy single-result entry point must not be a way around the check."""
    _note(tmp_path, "task-in-reins", 6, REINS)

    assert watcher.find_linked_task(6, repo=COUNCIL, vault_root=tmp_path) is None
    assert watcher.find_linked_task(6, repo=REINS, vault_root=tmp_path).task_id == "task-in-reins"
