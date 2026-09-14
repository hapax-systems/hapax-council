"""Run the emitted remediation through real cc-close, and see what survives.

Every earlier test of this remediation checked the STRING: that it parses under
`bash -n`, that it names the right identity variable, that it carries the observed
roots. None executed it. So each round found a new way for a syntactically valid,
correctly-parameterised command to act on the wrong thing — a prefix-matched
neighbour, a note whose id disagreed, a duplicate identity inside one directory.
The string was fine every time.

These build an isolated vault and cache, ask the check what to run, run it, and
assert which notes and markers are left. That is the only shape that can catch
"the command was well-formed and did the wrong thing".
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from cc_hygiene.checks import check_stale_claim_marker, parse_task_note  # noqa: E402

CC_CLOSE = REPO_ROOT / "scripts" / "cc-close"

_IDENTITY_ENV = (
    "HAPAX_AGENT_NAME",
    "HAPAX_AGENT_ROLE",
    "HAPAX_AGENT_INTERFACE",
    "HAPAX_SESSION_ID",
    "CLAUDE_ROLE",
    "CLAUDECODE",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_THREAD_NAME",
    "CODEX_SESSION_NAME",
    "CODEX_SESSION",
    "CODEX_ROLE",
    "CODEX_HOME",
    "HAPAX_CC_TASKS_ROOT",
)


def _write_note(vault: Path, filename: str, task_id: str, status: str) -> Path:
    path = vault / "active" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    (vault / "closed").mkdir(parents=True, exist_ok=True)
    path.write_text(
        textwrap.dedent(
            f"""\
            ---
            type: cc-task
            task_id: {task_id}
            title: "{task_id}"
            status: {status}
            assigned_to: eta
            completed_at:
            updated_at:
            pr:
            ---

            # {task_id}

            ## Session log
            """
        ),
        encoding="utf-8",
    )
    return path


def _sweep(vault: Path, cache: Path, marker_key: str, task_id: str):
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"cc-active-task-{marker_key}").write_text(f"{task_id}\n", encoding="utf-8")
    active = [n for n in (parse_task_note(p) for p in (vault / "active").glob("*.md")) if n]
    closed = [n for n in (parse_task_note(p) for p in (vault / "closed").glob("*.md")) if n]
    return check_stale_claim_marker({marker_key: task_id}, active, closed, cache_dir=cache)


def _run(command: str, home: Path) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_ENV}
    env["HOME"] = str(home)
    bash = shutil.which("bash")
    assert bash is not None
    # cc-close is invoked by absolute path; the emitted command says `cc-close`.
    return subprocess.run(
        [bash, "-c", command.replace("cc-close ", f"{CC_CLOSE} ", 1)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_emitted_remediation_closes_the_reported_task_and_retires_its_marker(
    tmp_path: Path,
) -> None:
    """The happy path, executed rather than parsed."""
    home = tmp_path / "home"
    vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    cache = home / ".cache" / "hapax"
    _write_note(vault, "t1.md", "t1", "withdrawn")

    events = _sweep(vault, cache, "eta", "t1")
    assert len(events) == 1 and events[0].metadata["next_action"] == "re-emit-close"

    result = _run(events[0].metadata["remediation"], home)

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert not (vault / "active" / "t1.md").exists(), "the reported task was not closed"
    assert not (cache / "cc-active-task-eta").exists(), "the reported marker survived"


def test_duplicate_active_identities_emit_no_command_at_all(tmp_path: Path) -> None:
    """The round-9 critical, caught where a string check could not see it.

    active/t1-a.md (in_progress) and active/t1-z.md (withdrawn) both declare
    task_id t1. Collapsing them by id kept the withdrawn one, so the check emitted
    `cc-close t1 --status withdrawn` — and cc-close selects t1-a.md as its first
    prefix match, which passes the identity guard because it really does declare
    t1, and withdraws the LIVE note. Every string assertion about that command was
    satisfied.
    """
    home = tmp_path / "home"
    vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    cache = home / ".cache" / "hapax"
    _write_note(vault, "t1-a.md", "t1", "in_progress")
    _write_note(vault, "t1-z.md", "t1", "withdrawn")

    events = _sweep(vault, cache, "eta", "t1")

    assert len(events) == 1
    assert events[0].metadata["reason"] == "duplicate_task_id_within_collection"
    assert events[0].metadata["next_action"] == "operator-adjudication"
    assert "remediation" not in events[0].metadata, (
        "a command was emitted for an ambiguous identity; running it would have "
        "withdrawn the live note"
    )
    # And the live note is still there, because nothing was recommended.
    assert (vault / "active" / "t1-a.md").exists()


def test_a_note_the_checker_could_not_parse_still_blocks_closure(tmp_path: Path) -> None:
    """The checker sees a FILTERED vault; cc-close mutates the real one.

    `parse_task_note` drops a note missing `type: cc-task`, so with active/t1-a.md
    (in_progress, no type) and active/t1-z.md (withdrawn, valid) both declaring
    task_id t1, the checker sees only the withdrawn one — no duplicate to detect —
    and emits `cc-close t1 --status withdrawn`. cc-close then selects t1-a.md, its
    identity guard passes because it really declares t1, and `withdrawn` skips the
    completion gates: the live note is withdrawn.

    No caller can prevent this, because the caller's view is the filtered one.
    cc-close revalidates at the point of mutation, where the whole truth is.
    """
    home = tmp_path / "home"
    vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    cache = home / ".cache" / "hapax"
    _write_note(vault, "t1-z.md", "t1", "withdrawn")
    # Declares t1 but has no `type: cc-task`, so the checker never sees it.
    unparsed = vault / "active" / "t1-a.md"
    unparsed.write_text(
        "---\ntask_id: t1\nstatus: in_progress\nassigned_to: eta\n---\n\n# t1\n",
        encoding="utf-8",
    )

    events = _sweep(vault, cache, "eta", "t1")
    remediation = next(
        (e.metadata["remediation"] for e in events if "remediation" in e.metadata), None
    )
    if remediation is None:
        return  # the checker refused outright; nothing to execute

    result = _run(remediation, home)

    assert result.returncode != 0, (
        f"the emitted command ran against an ambiguous identity\n{result.stdout}"
    )
    assert unparsed.exists(), "the LIVE note the checker could not see was mutated"
    assert "declare task_id" in result.stderr or "declares task_id" in result.stderr, result.stderr


def test_an_unparseable_note_blocks_destructive_advice(tmp_path: Path) -> None:
    """The blind-deletion path: retire-orphan-marker is a manual `rm`.

    active/t1-a.md declares t1/in_progress but lacks `type`, so the parser drops
    it; a valid closed/t1-z.md declares t1 withdrawn. The checker saw only the
    closed record and recommended deleting a LIVE lane's marker — and no cc-close
    guard can intercept that, because the remedy is `rm`.
    """
    home = tmp_path / "home"
    vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    cache = home / ".cache" / "hapax"
    (vault / "closed").mkdir(parents=True, exist_ok=True)
    (vault / "active").mkdir(parents=True, exist_ok=True)
    (vault / "closed" / "t1-z.md").write_text(
        "---\ntype: cc-task\ntask_id: t1\nstatus: withdrawn\nassigned_to: eta\n---\n",
        encoding="utf-8",
    )
    live = vault / "active" / "t1-a.md"
    live.write_text(
        "---\ntask_id: t1\nstatus: in_progress\nassigned_to: eta\n---\n",
        encoding="utf-8",
    )

    cache.mkdir(parents=True, exist_ok=True)
    (cache / "cc-active-task-eta").write_text("t1\n", encoding="utf-8")
    active = [n for n in (parse_task_note(p) for p in (vault / "active").glob("*.md")) if n]
    closed = [n for n in (parse_task_note(p) for p in (vault / "closed").glob("*.md")) if n]
    events = check_stale_claim_marker(
        {"eta": "t1"},
        active,
        closed,
        cache_dir=cache,
        unparsed_notes=[str(live)],
    )

    assert len(events) == 1
    assert events[0].metadata["reason"] == "vault_view_incomplete"
    assert events[0].metadata["next_action"] == "operator-adjudication"
    assert "remediation" not in events[0].metadata, (
        "deletion of a live lane's marker was recommended from an incomplete view"
    )


def test_a_descriptor_named_note_is_closed_by_its_own_id(tmp_path: Path) -> None:
    """Most notes carry a descriptor suffix; the command must still work."""
    home = tmp_path / "home"
    vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    cache = home / ".cache" / "hapax"
    _write_note(vault, "t1-with-descriptor.md", "t1", "withdrawn")

    events = _sweep(vault, cache, "eta", "t1")
    result = _run(events[0].metadata["remediation"], home)

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert not (vault / "active" / "t1-with-descriptor.md").exists()


def test_a_saved_command_refuses_after_the_task_resumes(tmp_path: Path) -> None:
    """Remediation is generated by a sweep and run later by a person.

    A sweep observing t1 as withdrawn emits the close command. If the task then
    RESUMES, the saved command still passed every identity check — and `withdrawn`
    skips the completion gates, so the live note was moved to closed/. The command
    now carries the observed state as a precondition, revalidated by cc-close
    immediately before it writes anything.
    """
    home = tmp_path / "home"
    vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    cache = home / ".cache" / "hapax"
    note = _write_note(vault, "t1.md", "t1", "withdrawn")

    events = _sweep(vault, cache, "eta", "t1")
    remediation = events[0].metadata["remediation"]
    assert "--expect-status withdrawn" in remediation, remediation

    # The world moves on between generation and execution.
    note.write_text(
        note.read_text(encoding="utf-8").replace("status: withdrawn", "status: in_progress"),
        encoding="utf-8",
    )

    result = _run(remediation, home)

    assert result.returncode != 0, (
        f"the saved command withdrew a task that had resumed\n{result.stdout}"
    )
    assert "--expect-status" in result.stderr, result.stderr
    assert note.exists(), "the resumed note was moved to closed/"
    assert "status: in_progress" in note.read_text(encoding="utf-8")


def test_the_precondition_holds_against_the_bytes_actually_rewritten(
    tmp_path: Path,
) -> None:
    """The refusal must be the EXPECTED-STATUS refusal, named exactly.

    An earlier version of this test asserted only "nonzero exit, note unchanged".
    Review round 13 pointed out that a cc-close with no `--expect-status` at all
    satisfies both — it rejects the unknown argument before touching the task — so
    the test passed against a build without the feature. Asserting the specific
    message is what makes it a test of the precondition rather than of argument
    parsing.
    """
    home = tmp_path / "home"
    vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    note = _write_note(vault, "t1.md", "t1", "in_progress")

    # Ask cc-close to act as though it had observed `withdrawn`.
    env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_ENV}
    env["HOME"] = str(home)
    env["HAPAX_AGENT_NAME"] = "eta"
    result = subprocess.run(
        [
            "bash",
            str(CC_CLOSE),
            "t1",
            "--status",
            "withdrawn",
            "--expect-status",
            "withdrawn",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2, f"expected the precondition refusal\n{result.stderr}"
    assert "is status 'in_progress' at write time" in result.stderr, (
        "cc-close exited nonzero for some other reason — an unrecognised argument "
        f"would also do that, and would prove nothing\n{result.stderr}"
    )
    assert "--expect-status 'withdrawn' was required" in result.stderr, result.stderr
    assert note.exists(), "a task that had resumed was moved to closed/"
    assert "status: in_progress" in note.read_text(encoding="utf-8")


def test_the_precondition_is_evaluated_after_the_lock_is_taken(tmp_path: Path) -> None:
    """Placement, proved by a controlled interleaving rather than by reading.

    The previous test cannot tell an early guard from a late one: it sets the
    status before cc-close starts, so any guard anywhere catches it. This one
    starts cc-close while the task still matches its expectation, holds the
    per-task lock so cc-close cannot proceed, changes the status underneath it, and
    only then releases. A guard that ran before the lock was taken saw `withdrawn`
    and would close a task that is now `in_progress`; the shipped one re-reads
    under the lock and refuses.

    The competing writer here takes the lock with plain `fcntl.flock` on the path
    `shared.cc_task_lock` names, not through the helper — so the test proves the
    lock FILE is the rendezvous, rather than trusting our own helper on both sides.
    """
    import fcntl
    import time

    from shared.cc_task_lock import lock_path

    home = tmp_path / "home"
    vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    note = _write_note(vault, "t1.md", "t1", "withdrawn")

    env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_ENV}
    env["HOME"] = str(home)
    env["XDG_CACHE_HOME"] = str(home / ".cache")
    env["HAPAX_AGENT_NAME"] = "eta"

    held = lock_path("t1", Path(env["XDG_CACHE_HOME"]) / "hapax" / "cc-task-locks")
    handle = os.open(held, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(handle, fcntl.LOCK_EX)
    try:
        proc = subprocess.Popen(
            [
                "bash",
                str(CC_CLOSE),
                "t1",
                "--status",
                "withdrawn",
                "--expect-status",
                "withdrawn",
            ],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Give cc-close time to run its read-only gates and reach the lock. If it
        # does NOT block there, it finishes here and the assertion catches it —
        # which is precisely the unserialized build this test exists to reject.
        settle = time.monotonic() + 3.0
        while proc.poll() is None and time.monotonic() < settle:
            time.sleep(0.05)
        assert proc.poll() is None, (
            "cc-close ran to completion while another process held the task lock — "
            "the mutating tail is not serialized"
        )
        # The world moves on while cc-close waits.
        note.write_text(
            note.read_text(encoding="utf-8").replace("status: withdrawn", "status: in_progress"),
            encoding="utf-8",
        )
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        os.close(handle)

    stdout, stderr = proc.communicate(timeout=60)

    assert proc.returncode == 2, f"expected the precondition refusal\n{stdout}\n{stderr}"
    assert "is status 'in_progress' at write time" in stderr, (
        "cc-close validated before acquiring the lock, so it decided on a view of "
        f"the note that was already stale\n{stderr}"
    )
    assert note.exists(), "the resumed note was moved to closed/"
    assert "status: in_progress" in note.read_text(encoding="utf-8")


class TestOnlyTheFrontmatterCounts:
    """A note's BODY must not decide, or receive, a governed field mutation.

    The writer validated and rewrote with regexes over the whole note for one
    round. Review round 13->14 reproduced three consequences, and all three are
    pinned here. Selection had used the canonical parser the whole time; the split
    between the two is where the defect lived.
    """

    def _close(self, home: Path, note_text: str, *args: str):
        vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
        (vault / "active").mkdir(parents=True, exist_ok=True)
        (vault / "closed").mkdir(parents=True, exist_ok=True)
        note = vault / "active" / "t1.md"
        note.write_text(note_text, encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k not in _IDENTITY_ENV}
        env["HOME"] = str(home)
        env["XDG_CACHE_HOME"] = str(home / ".cache")
        env["HAPAX_AGENT_NAME"] = "eta"
        result = subprocess.run(
            ["bash", str(CC_CLOSE), "t1", *args],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
        return result, note

    def test_a_body_line_cannot_satisfy_expect_status(self, tmp_path: Path) -> None:
        """The reported reproduction: live task, body example, stale precondition.

        Frontmatter says in_progress; a body line says `status: withdrawn`. The
        whole-note regex found the body line, so `--expect-status withdrawn`
        passed, the live note was unlinked, and the archived copy still read
        in_progress.

        The frontmatter key is QUOTED, as reported, and that detail is the whole
        reproduction: `^status:` does not match `"status":`, so the regex skipped
        the real field and matched the body. With an unquoted key the regex finds
        the frontmatter line first and refuses correctly — which is why a test
        written with one passes against the defect and proves nothing. YAML treats
        both spellings as the same key; the regex does not.
        """
        result, note = self._close(
            tmp_path / "home",
            textwrap.dedent(
                """\
                ---
                type: cc-task
                task_id: t1
                title: "t1"
                "status": in_progress
                assigned_to: eta
                completed_at:
                updated_at:
                pr:
                ---

                # t1

                An example of what a withdrawn note looks like:

                status: withdrawn

                ## Session log
                """
            ),
            "--status",
            "withdrawn",
            "--expect-status",
            "withdrawn",
        )
        assert result.returncode == 2, f"a body line satisfied the precondition\n{result.stdout}"
        assert "is status 'in_progress' at write time" in result.stderr, result.stderr
        assert note.exists(), "the live note was unlinked"

    def test_duplicate_governed_keys_are_refused_not_guessed(self, tmp_path: Path) -> None:
        """YAML takes the last silently; `re.sub(count=1)` rewrites the first.

        So the field validated and the field rewritten could be different lines.
        There is no safe pick, and picking is what produces a closure that reports
        one status and archives another.
        """
        result, note = self._close(
            tmp_path / "home",
            textwrap.dedent(
                """\
                ---
                type: cc-task
                task_id: t1
                title: "t1"
                status: withdrawn
                status: in_progress
                assigned_to: eta
                completed_at:
                updated_at:
                pr:
                ---

                # t1

                ## Session log
                """
            ),
            "--status",
            "withdrawn",
        )
        assert result.returncode == 2, f"a duplicated key was silently resolved\n{result.stdout}"
        assert "more than once" in result.stderr, result.stderr
        assert note.exists()

    def test_an_inline_comment_on_task_id_is_not_an_identity_change(self, tmp_path: Path) -> None:
        """`task_id: t1  # note` is valid YAML and was read as the id `t1  # note`.

        The regex took everything after the colon, so a legitimate close refused
        with "declares task_id ... not ...". The canonical parser reads `t1`.
        """
        result, note = self._close(
            tmp_path / "home",
            textwrap.dedent(
                """\
                ---
                type: cc-task
                task_id: t1  # the ontology row
                title: "t1"
                status: withdrawn
                assigned_to: eta
                completed_at:
                updated_at:
                pr:
                ---

                # t1

                ## Session log
                """
            ),
            "--status",
            "withdrawn",
        )
        assert result.returncode == 0, (
            f"a valid inline comment was read as an identity change\n{result.stderr}"
        )
        assert not note.exists(), "the note was not closed"

    def test_a_body_line_is_not_rewritten_by_the_status_mutation(self, tmp_path: Path) -> None:
        """The write-side half, with a note whose frontmatter LACKS the key.

        `re.sub(count=1)` over the whole note rewrites the first match. When the
        frontmatter carries the field that is the frontmatter line, which is why a
        naive version of this test passes against the defect. When it does not —
        `completed_at` is optional scaffolding and plenty of notes omit it — the
        first match is in the body, and the close silently edits prose. Confining
        the substitution to the frontmatter block makes that unrepresentable: with
        no key to rewrite, nothing is rewritten.
        """
        home = tmp_path / "home"
        result, _note = self._close(
            home,
            textwrap.dedent(
                """\
                ---
                type: cc-task
                task_id: t1
                title: "t1"
                status: withdrawn
                assigned_to: eta
                updated_at:
                pr:
                ---

                # t1

                Prior art quoted verbatim from the superseded row:

                completed_at: 2020-01-01T00:00:00Z

                ## Session log
                """
            ),
            "--status",
            "withdrawn",
        )
        assert result.returncode == 0, result.stderr
        closed = (
            home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "closed" / "t1.md"
        )
        assert closed.is_file(), "the note was not archived"
        archived = closed.read_text(encoding="utf-8")
        assert "completed_at: 2020-01-01T00:00:00Z" in archived, (
            f"the quoted body line was rewritten by a frontmatter field mutation:\n{archived}"
        )


def test_a_prefix_neighbour_is_left_alone(tmp_path: Path) -> None:
    """`cc-close t1` must not reach t1-next, which is different, live work."""
    home = tmp_path / "home"
    vault = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    cache = home / ".cache" / "hapax"
    _write_note(vault, "t1.md", "t1", "withdrawn")
    _write_note(vault, "t1-next.md", "t1-next", "in_progress")

    events = _sweep(vault, cache, "eta", "t1")
    remediation = next(e.metadata["remediation"] for e in events if "remediation" in e.metadata)
    result = _run(remediation, home)

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert not (vault / "active" / "t1.md").exists(), "the reported task was not closed"
    assert (vault / "active" / "t1-next.md").exists(), (
        "the remediation reached a prefix neighbour — different, live work"
    )
