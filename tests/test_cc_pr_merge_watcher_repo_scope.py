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
    assert [t.task_id for t in watcher.find_linked_tasks(6, repo=REINS, vault_root=tmp_path)] == [
        "reins-6"
    ]


def test_find_linked_task_singular_carries_the_same_scope(tmp_path) -> None:
    """The legacy single-result entry point must not be a way around the check."""
    _note(tmp_path, "task-in-reins", 6, REINS)

    assert watcher.find_linked_task(6, repo=COUNCIL, vault_root=tmp_path) is None
    assert watcher.find_linked_task(6, repo=REINS, vault_root=tmp_path).task_id == "task-in-reins"


# --- the orchestration path, not just the matcher -----------------------------------------
def test_run_watcher_does_not_close_a_cross_repo_task(tmp_path, monkeypatch) -> None:
    """THROUGH run_watcher, not find_linked_tasks.

    The tests above prove the matcher. A reviewer pointed out that they do not prove the WIRING --
    that run_watcher actually threads its repo into the matcher rather than letting a default leak
    back in. A parameter that is not passed is the same defect wearing a signature, and this file
    had already found one of those (`fetch_merged_prs` took `repo` and used DEFAULT_REPO inside).

    So this drives the real entry point with a merged council PR #6 and a task meaning reins#6, and
    asserts cc-close is never invoked.
    """
    # SCANNED REPO IS *NOT* THE DEFAULT, deliberately.
    #
    # An earlier version scanned COUNCIL, which is also DEFAULT_REPO -- so a mutant that DROPPED
    # the `repo=` argument entirely fell back to the same value and the test could not see it. It
    # survived. Scanning reins while the task declares council means a dropped argument defaults to
    # council, matches, and closes: exactly what must not happen, and now visible.
    _note(tmp_path, "task-in-council", 6, COUNCIL)
    cursor = tmp_path / "cursor.txt"

    # ASSERT WHAT run_watcher HANDED TO fetch_merged_prs, not merely that it called it. Patching a
    # function and ignoring its arguments proves the call happened and nothing about the scope --
    # and this file has already caught a `repo` parameter that was accepted and then ignored.
    fetched: list[str] = []

    def _fake_fetch(cursor_arg, *, repo, repo_root, runner=None, limit=300):
        fetched.append(repo)
        return [
            watcher.MergedPR(
                number=6,
                merged_at=watcher.datetime.now(watcher.UTC),
                head_branch="whatever",
            )
        ]

    monkeypatch.setattr(watcher, "fetch_merged_prs", _fake_fetch)
    closed: list[str] = []
    monkeypatch.setattr(watcher, "close_linked_task", lambda task, **k: closed.append(task.task_id))

    counters = watcher.run_watcher(
        cursor_path=cursor, vault_root=tmp_path, repo=REINS, repo_root=tmp_path, dry_run=False
    )

    assert fetched == [REINS], f"run_watcher fetched merged PRs from {fetched}, not {REINS}"
    assert closed == [], (
        f"cc-close was invoked for a task in another repository: {closed}. If this fails with "
        f"repo= threaded correctly, the watcher is falling back to DEFAULT_REPO somewhere."
    )
    assert counters["closed"] == 0


def test_run_watcher_still_closes_a_same_repo_task(tmp_path, monkeypatch) -> None:
    """The complement: refusing everything is an outage, not a gate."""
    _note(tmp_path, "task-in-reins", 6, REINS)
    cursor = tmp_path / "cursor.txt"

    monkeypatch.setattr(
        watcher,
        "fetch_merged_prs",
        lambda *a, **k: [
            watcher.MergedPR(
                number=6,
                merged_at=watcher.datetime.now(watcher.UTC),
                head_branch="whatever",
            )
        ],
    )
    closed: list[str] = []
    monkeypatch.setattr(watcher, "close_linked_task", lambda task, **k: closed.append(task.task_id))

    watcher.run_watcher(
        cursor_path=cursor, vault_root=tmp_path, repo=REINS, repo_root=tmp_path, dry_run=False
    )

    assert closed == ["task-in-reins"], "scoping to a non-default repo closed nothing at all"


# --- the SECOND closure path, which the first fix left behind ------------------------------
def test_stale_reconciliation_skips_tasks_belonging_to_another_repo(tmp_path, monkeypatch) -> None:
    """THE CRITICAL FOUND IN REVIEW.

    `reconcile_stale_pr_states` is cursor-window independent: it scans EVERY active task and
    queries each number against one repository. Scoping the cursor loop and leaving this one meant
    the defect stayed fully alive through the second door -- and `main` invokes both, so fixing one
    fixed nothing. A control whose scope of effect nobody declared, which is the shape of the very
    thing being fixed.
    """
    _note(tmp_path, "task-in-reins", 6, REINS)
    queried: list[str] = []

    def _fake_state(pr_num, *, repo=COUNCIL, repo_root=None, runner=None):
        queried.append(f"{repo}#{pr_num}")
        return "MERGED"

    monkeypatch.setattr(watcher, "_query_pr_state", _fake_state)
    closed: list[str] = []
    monkeypatch.setattr(
        watcher, "_close_merged_note", lambda *a, **k: closed.append("closed") or True
    )

    watcher.reconcile_stale_pr_states(
        vault_root=tmp_path, repo=COUNCIL, repo_root=tmp_path, dry_run=False
    )

    assert queried == [], f"a reins task's PR number was queried against council: {queried}"
    assert closed == []


# --- one definition of "absent" ------------------------------------------------------------
def test_both_gates_share_one_definition_of_absent() -> None:
    """Three copies existed and had ALREADY diverged on "nil".

    One gate treating a value as undeclared while the other treats it as declared reintroduces the
    silent mismatch this change removes, so the definition lives in shared.cc_task_pr_link and both
    resolve through it. Asserted by identity, not by comparing two literals -- comparing literals
    is what drifts.
    """
    from shared.cc_task_pr_link import NULLISH, is_nullish

    assert watcher._PR_NULL_NULLISH is NULLISH

    check = importlib.util.spec_from_file_location(
        "cc_close_pr_merge_check",
        Path(__file__).resolve().parent.parent / "scripts" / "cc-close-pr-merge-check.py",
    )
    assert check and check.loader
    mod = importlib.util.module_from_spec(check)
    check.loader.exec_module(mod)
    for spelling in ("null", "NONE", "~", "", "nil"):
        assert mod._nullish(spelling) is is_nullish(spelling), (
            f"the two gates disagree about {spelling!r}: one would treat it as a repository name"
        )


def test_stale_reconciliation_skips_a_task_with_no_declared_repo(
    tmp_path, monkeypatch, caplog
) -> None:
    """THE SAME OMISSION, IN THE SECOND PATH.

    The cursor loop skips an undeclared task; the reconcile path originally read
    `if note_repo and note_repo != repo`, so an ABSENT pr_repo fell through and the task was
    reconciled against whatever repo the pass was scanning -- the original defect, reintroduced
    inside its own fix, in the door that had just been fixed.

    The previous test only covered a task declaring ANOTHER repo, so it passed over this. Both
    branches are asserted now: declared-elsewhere and undeclared.
    """
    _note(tmp_path, "task-undeclared", 4499, None)
    queried: list[str] = []

    def _fake_state(pr_num, *, repo=COUNCIL, repo_root=None, runner=None):
        queried.append(f"{repo}#{pr_num}")
        return "MERGED"

    monkeypatch.setattr(watcher, "_query_pr_state", _fake_state)
    closed: list[str] = []
    monkeypatch.setattr(
        watcher, "_close_merged_note", lambda *a, **k: closed.append("closed") or True
    )

    with caplog.at_level("WARNING"):
        watcher.reconcile_stale_pr_states(
            vault_root=tmp_path, repo=COUNCIL, repo_root=tmp_path, dry_run=False
        )

    assert queried == [], f"an undeclared task's PR was queried anyway: {queried}"
    assert closed == [], "an undeclared task was closed by the reconcile path"
    assert "no pr_repo" in caplog.text, "the undeclared task was skipped silently"
    assert "task-undeclared" in caplog.text, "the operator must be told WHICH note to fix"


def test_stale_reconciliation_still_reconciles_a_matching_task(tmp_path, monkeypatch) -> None:
    """The complement: skipping everything is an outage, not a scope."""
    _note(tmp_path, "task-in-council", 4499, COUNCIL)
    queried: list[str] = []

    def _fake_state(pr_num, *, repo=COUNCIL, repo_root=None, runner=None):
        queried.append(f"{repo}#{pr_num}")
        return "MERGED"

    monkeypatch.setattr(watcher, "_query_pr_state", _fake_state)
    closed: list[str] = []
    monkeypatch.setattr(
        watcher, "_close_merged_note", lambda *a, **k: closed.append("closed") or True
    )

    watcher.reconcile_stale_pr_states(
        vault_root=tmp_path, repo=COUNCIL, repo_root=tmp_path, dry_run=False
    )

    assert queried == [f"{COUNCIL}#4499"]
    assert closed == ["closed"]


# --- the parameter must reach the REST layer, not just the signature ----------------------
def test_fetch_merged_prs_queries_the_repo_it_was_given(monkeypatch, tmp_path) -> None:
    """A PARAMETER THAT IS NOT USED IS THE SAME DEFECT WEARING A SIGNATURE.

    `fetch_merged_prs` took `repo` and then hardcoded DEFAULT_REPO in its body, in both the search
    call and the closed-pulls fallback. The orchestration tests monkeypatch this function, so they
    could never have seen that -- they prove run_watcher passes the value, not that anything
    downstream reads it. This drives the real function and asserts the value reaches the REST call.
    """
    seen: list[str] = []

    def _fake_search(cursor, *, repo, repo_root, runner, limit):
        seen.append(repo)
        return []

    monkeypatch.setattr(watcher, "_search_merged_pull_details_rest", _fake_search)
    watcher.fetch_merged_prs(
        watcher.datetime.now(watcher.UTC),
        repo=REINS,
        repo_root=tmp_path,
        runner=lambda *a, **k: None,
    )

    assert seen == [REINS], f"fetch_merged_prs queried {seen} after being told {REINS}"


def test_fetch_merged_prs_fallback_also_honours_the_repo(monkeypatch, tmp_path) -> None:
    """The fallback path hardcoded it too, and a fallback is exactly where nobody looks."""
    seen: list[str] = []
    monkeypatch.setattr(watcher, "_search_merged_pull_details_rest", lambda *a, **k: None)

    def _fake_list(*, repo, repo_root, runner, state, sort, direction, limit):
        seen.append(repo)
        return []

    monkeypatch.setattr(watcher, "list_pulls_rest", _fake_list)
    watcher.fetch_merged_prs(
        watcher.datetime.now(watcher.UTC),
        repo=REINS,
        repo_root=tmp_path,
        runner=lambda *a, **k: None,
    )

    assert seen == [REINS], f"the fallback queried {seen} after being told {REINS}"


def test_the_pr_null_repair_path_queries_the_repo_it_was_given(monkeypatch, tmp_path) -> None:
    """The pr:null repair re-derives a PR from a branch, and hardcoded the repo doing it."""
    _note(tmp_path, "task-null", 0, REINS)
    (tmp_path / "active" / "task-null.md").write_text(
        "---\ntype: cc-task\ntask_id: task-null\nstatus: pr_open\n"
        f"pr_repo: {REINS}\nbranch: feat/x\npr: null\n---\nbody\n",
        encoding="utf-8",
    )
    seen: list[str] = []

    def _fake_branch_lookup(branch, *, repo, repo_root, runner):
        seen.append(repo)
        return []

    monkeypatch.setattr(watcher, "_list_prs_for_branch", _fake_branch_lookup)
    monkeypatch.setattr(watcher, "_block_stale_note", lambda *a, **k: True)

    watcher.reconcile_stale_pr_states(
        vault_root=tmp_path, repo=REINS, repo_root=tmp_path, dry_run=True
    )

    assert seen == [REINS], f"the repair path queried {seen} after being told {REINS}"


def test_main_threads_the_repo_flag_into_both_closure_paths(tmp_path, monkeypatch) -> None:
    """THROUGH main(), the way the systemd unit actually runs it.

    Everything else drives the functions directly. A reviewer noted that leaves the CLI wiring
    itself unproven -- and this change added a --repo flag whose whole purpose is to make the
    scope declarable, so a flag parsed and then dropped would be the defect restated. Both closure
    paths must receive it, because `main` invokes both and scoping one is scoping neither.
    """
    seen: dict[str, str] = {}
    monkeypatch.setattr(
        watcher,
        "run_watcher",
        lambda **k: (
            seen.setdefault("cursor", k["repo"])
            and None
            or {"merged": 0, "linked": 0, "closed": 0, "failed": 0}
        ),
    )
    monkeypatch.setattr(
        watcher,
        "reconcile_stale_pr_states",
        lambda **k: (
            seen.setdefault("stale", k["repo"])
            and None
            or {"scanned": 0, "stale": 0, "closed": 0, "repaired": 0}
        ),
    )
    monkeypatch.setattr(watcher, "trigger_reform_dispatch", lambda **k: False)

    watcher.main(
        ["--repo", REINS, "--vault-root", str(tmp_path), "--repo-root", str(tmp_path), "--dry-run"]
    )

    assert seen.get("cursor") == REINS, "the cursor loop did not receive --repo"
    assert seen.get("stale") == REINS, "the stale-reconciliation path did not receive --repo"


def test_a_repo_named_only_in_the_body_does_not_qualify_a_task(tmp_path) -> None:
    """BODY TEXT IS PROSE, NOT A DECLARATION.

    `declared_pr_repo` searched the whole note, so a line in the body -- prose, an example, a fenced
    block -- could qualify a task whose FRONTMATTER never did. This change's own task note contains
    "Add `pr_repo: <owner>/<name>`" in three places, so the vector was live, not theoretical.

    And cc-close-pr-merge-check reads frontmatter only. The two gates would therefore disagree
    about the same note: the watcher considering it qualified and trying to close it, the check
    considering it undeclared and refusing. Gates disagreeing about one note is the precise failure
    this change removes, so reintroducing it through a parsing shortcut would have undone the point.
    """
    (tmp_path / "active").mkdir(parents=True, exist_ok=True)
    (tmp_path / "active" / "forged.md").write_text(
        "---\ntype: cc-task\ntask_id: forged\nstatus: pr_open\npr: 6\n---\n\n"
        "# Notes\n\nTo fix this, add `pr_repo: hapax-systems/hapax-council` to the frontmatter.\n"
        f"pr_repo: {COUNCIL}\n",
        encoding="utf-8",
    )

    assert watcher.find_linked_tasks(6, repo=COUNCIL, vault_root=tmp_path) == [], (
        "a pr_repo written in the note BODY qualified a task whose frontmatter declares none"
    )


def test_frontmatter_declaration_still_qualifies(tmp_path) -> None:
    """The complement: reading only frontmatter must still read frontmatter."""
    _note(tmp_path, "properly-declared", 6, COUNCIL)
    assert [t.task_id for t in watcher.find_linked_tasks(6, repo=COUNCIL, vault_root=tmp_path)] == [
        "properly-declared"
    ]


def test_main_refuses_a_malformed_repo_flag(tmp_path, monkeypatch) -> None:
    """A TYPO MUST NOT LOOK LIKE A QUIET SUCCESS.

    An unvalidated --repo scans a repository that does not exist, matches no task, closes nothing,
    and exits 0. A run reporting health while doing nothing is the fail-quiet shape this whole
    change is about, arriving through the flag added to prevent it.
    """
    called: list[str] = []
    monkeypatch.setattr(watcher, "run_watcher", lambda **k: called.append("ran") or {})
    monkeypatch.setattr(
        watcher, "reconcile_stale_pr_states", lambda **k: called.append("ran") or {}
    )

    rc = watcher.main(
        ["--repo", "garbage", "--vault-root", str(tmp_path), "--repo-root", str(tmp_path)]
    )

    assert rc == 2, "a malformed --repo exited successfully"
    assert called == [], "a closure path ran with an invalid repository"


def test_a_pr_number_in_the_body_cannot_forge_a_link(tmp_path) -> None:
    """THE SAME VECTOR, THE OTHER FIELD.

    pr_repo was scoped to frontmatter first and `pr:` was left matching the whole note, so a body
    line "pr: 6" could forge the very link the scoping was added to protect. Fixing one half of a
    pair and leaving the other is the third appearance of that shape in this change: the two
    closure paths, then pr_repo and pr.

    This note's frontmatter declares a DIFFERENT number; only the body mentions 6.
    """
    (tmp_path / "active").mkdir(parents=True, exist_ok=True)
    (tmp_path / "active" / "forged-number.md").write_text(
        f"---\ntype: cc-task\ntask_id: forged-number\nstatus: pr_open\n"
        f"pr_repo: {COUNCIL}\npr: 999\n---\n\n"
        "# Notes\n\nThis supersedes the earlier attempt:\npr: 6\n",
        encoding="utf-8",
    )

    assert watcher.find_linked_tasks(6, repo=COUNCIL, vault_root=tmp_path) == [], (
        "a pr number written in the note BODY forged a link"
    )
    assert [
        t.task_id for t in watcher.find_linked_tasks(999, repo=COUNCIL, vault_root=tmp_path)
    ] == ["forged-number"], "the real frontmatter link stopped working"


def test_reconciliation_reads_status_and_pr_from_frontmatter_only(tmp_path, monkeypatch) -> None:
    """The reconcile path read status, pr and branch from the whole note as well.

    A closed task whose BODY happens to contain "status: pr_open" would be re-opened for
    reconciliation, and a body "pr: N" would decide which PR it was reconciled against.
    """
    (tmp_path / "active").mkdir(parents=True, exist_ok=True)
    (tmp_path / "active" / "body-status.md").write_text(
        "---\ntype: cc-task\ntask_id: body-status\nstatus: done\n"
        f"pr_repo: {COUNCIL}\npr: 999\n---\n\n"
        "# Notes\n\nWhile it was open the frontmatter read:\nstatus: pr_open\npr: 6\n",
        encoding="utf-8",
    )
    queried: list[str] = []
    monkeypatch.setattr(
        watcher,
        "_query_pr_state",
        lambda pr_num, *, repo=COUNCIL, repo_root=None, runner=None: (
            queried.append(pr_num) or "MERGED"
        ),
    )
    monkeypatch.setattr(watcher, "_close_merged_note", lambda *a, **k: True)

    watcher.reconcile_stale_pr_states(
        vault_root=tmp_path, repo=COUNCIL, repo_root=tmp_path, dry_run=True
    )

    assert queried == [], (
        f"a DONE task was reconciled because its body contains 'status: pr_open': queried {queried}"
    )


def test_a_malformed_task_repo_is_reported_by_both_paths(tmp_path, monkeypatch, caplog) -> None:
    """ASSERT THE REPORT, NOT THE SKIP.

    A malformed pr_repo is skipped either way -- "garbage" is not the scanned repo, so the plain
    comparison rejects it and the outcome is identical with the check deleted. A test asserting
    only "nothing closed" therefore passes over the whole thing, and the first version of this one
    did: the mutant survived.

    What differs is whether the operator is TOLD. A task stranded forever by a typo, in silence, is
    the fail-quiet family this change exists to remove -- so both closure paths report it, and both
    reports are what is asserted here.
    """
    _note(tmp_path, "typo-cursor", 4499, "garbage")
    with caplog.at_level("WARNING"):
        assert watcher.find_linked_tasks(4499, repo=COUNCIL, vault_root=tmp_path) == []
    assert "malformed pr_repo" in caplog.text, "the cursor loop skipped a typo'd repo in silence"
    assert "typo-cursor" in caplog.text, "the operator must be told WHICH task"

    caplog.clear()
    monkeypatch.setattr(
        watcher, "_query_pr_state", lambda *a, **k: pytest.fail("a malformed repo was queried")
    )
    with caplog.at_level("WARNING"):
        watcher.reconcile_stale_pr_states(
            vault_root=tmp_path, repo=COUNCIL, repo_root=tmp_path, dry_run=True
        )
    assert "malformed pr_repo" in caplog.text, (
        "the reconcile path skipped a typo'd repo in silence; the cursor loop reports it and the "
        "two paths must not disagree about what they tell the operator"
    )


# --- the parser's own guarantees ----------------------------------------------------------
@pytest.mark.parametrize(
    ("label", "text", "expected"),
    [
        ("plain", "---\npr_repo: a/b\n---\nbody\n", "a/b"),
        ("double-quoted", '---\npr_repo: "a/b"\n---\nbody\n', "a/b"),
        ("single-quoted", "---\npr_repo: 'a/b'\n---\nbody\n", "a/b"),
        ("crlf", "---\r\npr_repo: a/b\r\n---\r\nbody\r\n", "a/b"),
        # value on the NEXT line: the field is empty. `\s*` matched the newline and captured it.
        ("value on next line", "---\npr_repo:\na/b\n---\n", ""),
        # neither line is a real fence; body text between them is not frontmatter.
        ("fake fences", "---not-a-fence\npr_repo: a/b\n---also-not\n", ""),
        ("body only", "---\npr: 6\n---\n\npr_repo: a/b\n", ""),
        ("no frontmatter", "pr_repo: a/b\n", ""),
        ("unterminated", "---\npr_repo: a/b\nno close\n", ""),
    ],
)
def test_declared_pr_repo_parses_exactly_and_fails_closed(label, text, expected) -> None:
    """Every degenerate shape resolves to UNDECLARED, which both gates refuse.

    Three separate defects lived in this one function, each found in review:

      `startswith("---")` + first `\n---`   `---not-a-fence` opened a block and `---also-not`
                                            closed one, so body text became frontmatter.
      `\s*` in the field pattern            `\s` matches newlines, so a value on the NEXT line was
                                            captured for a field that was empty.
      no scalar normalization               `pr_repo: "a/b"` failed equality against `a/b`, so one
                                            gate saw a declaration and the other saw a mismatch.

    All three turn "malformed" into "declared", which is the forgery this module exists to stop.
    """
    from shared.cc_task_pr_link import declared_pr_repo

    assert declared_pr_repo(text) == expected, label


def test_both_gates_share_one_frontmatter_extractor() -> None:
    """The close-check had its OWN parser, with different block boundaries.

    Two gates disagreeing about where a note's frontmatter ends is the same class of failure as
    two gates disagreeing about "absent": the same note is declared to one and undeclared to the
    other. Asserted by identity so the two cannot drift apart again.
    """
    from shared.cc_task_pr_link import frontmatter as shared_frontmatter

    check = importlib.util.spec_from_file_location(
        "cc_close_pr_merge_check2",
        Path(__file__).resolve().parent.parent / "scripts" / "cc-close-pr-merge-check.py",
    )
    assert check and check.loader
    mod = importlib.util.module_from_spec(check)
    check.loader.exec_module(mod)

    assert mod.frontmatter is shared_frontmatter
    forged = "---not-a-fence\npr_repo: a/b\npr: 6\n---also-not\n"
    assert mod._extract_frontmatter(forged) == {}, (
        "the close-check still parses a forged fence the watcher rejects"
    )


def test_the_killswitch_stops_the_reconcile_path_too(tmp_path, monkeypatch) -> None:
    """A KILLSWITCH THAT STOPS HALF THE AUTOMATION IS WORSE THAN NONE.

    run_watcher honoured HAPAX_CC_HYGIENE_OFF and reconcile_stale_pr_states did not, so with the
    switch armed this path still queried PRs, rewrote `pr: null` notes, and invoked cc-close. The
    operator would believe the estate was quiet while it was closing tasks.

    Guarded inside the function, not only at the call site, so a direct caller cannot route around
    it. Found in review.
    """
    _note(tmp_path, "would-close", 4499, COUNCIL)
    monkeypatch.setenv(watcher.KILLSWITCH_ENV, "1")
    monkeypatch.setattr(
        watcher,
        "_query_pr_state",
        lambda *a, **k: pytest.fail("a PR was queried with the switch armed"),
    )
    monkeypatch.setattr(
        watcher,
        "_close_merged_note",
        lambda *a, **k: pytest.fail("a task was closed with the switch armed"),
    )

    counts = watcher.reconcile_stale_pr_states(
        vault_root=tmp_path, repo=COUNCIL, repo_root=tmp_path, dry_run=False
    )

    assert counts["skipped"] == 1
    assert counts["closed"] == 0


@pytest.mark.parametrize(
    "declared",
    [
        "hapax-systems/hapax-council",
        "Hapax-Systems/Hapax-Council",
        "HAPAX-SYSTEMS/HAPAX-COUNCIL",
    ],
)
def test_repository_matching_ignores_case_because_github_does(tmp_path, declared) -> None:
    """A TASK STRANDED BY CAPITALIZATION.

    GitHub repository names are case-insensitive, and a plain `!=` treated
    `Hapax-Systems/Reins` and `hapax-systems/reins` as different repositories. A note whose pr_repo
    differed only in capitalization was therefore read as belonging elsewhere and never closed --
    silently, forever. That is the fail-quiet family this change removes, arriving through a
    comparison operator. Found in review.
    """
    _note(tmp_path, "cased", 4499, declared)

    found = watcher.find_linked_tasks(4499, repo=COUNCIL, vault_root=tmp_path)
    assert [x.task_id for x in found] == ["cased"], f"{declared!r} did not match {COUNCIL!r}"


def test_repository_matching_still_rejects_a_genuinely_different_repo(tmp_path) -> None:
    """Case-insensitivity must not quietly become match-everything."""
    _note(tmp_path, "elsewhere", 4499, REINS)

    assert watcher.find_linked_tasks(4499, repo=COUNCIL, vault_root=tmp_path) == []
