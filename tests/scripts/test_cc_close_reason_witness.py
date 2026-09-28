"""cc-close writes its reason or witness in the close's own locked write (M179, M182).

``cc-close-reason-and-awaiting-witness-path-20260927``:

- A withdrawn or superseded close states why, with ``--reason``, in the same write that closes
  the row (M179). Before this, the gate refused any later edit of a closed row, so reasons lived
  only in mail.
- An awaiting row (``merged_awaiting_runtime_witness``, #4828) has one exit:
  ``cc-close <task> --pr N --witness "<observation>"``. It writes the witness and closes done
  in one locked write, with no claim needed (M182). A done close without the witness refuses.
  The awaiting check reads every ``status`` key line, in any quoting. The rewrite changes the
  one plain line the release-grade read found, by position.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from shared.sdlc_lifecycle import TASK_MERGED_AWAITING_WITNESS_STATUS

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cc-close"
AWAITING = TASK_MERGED_AWAITING_WITNESS_STATUS
TASK = "awaiting-row"
OBSERVATION = "a real claim at 00:29Z emitted claim_publication_phase_observed (seq 3464-3465)"

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
)


def _vault(home: Path) -> Path:
    root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (root / "active").mkdir(parents=True, exist_ok=True)
    (root / "closed").mkdir(parents=True, exist_ok=True)
    return root


def _row(home: Path, *, status_lines: str = f"status: {AWAITING}", body: str = "") -> Path:
    note = _vault(home) / "active" / f"{TASK}.md"
    frontmatter = "\n".join(
        [
            "---",
            "type: cc-task",
            f"task_id: {TASK}",
            f'title: "{TASK}"',
            status_lines,
            "assigned_to: dev42",
            "completed_at: null",
            "updated_at: 2026-09-27T00:00:00Z",
            "pr: 4830",
            "---",
        ]
    )
    note.write_text(
        frontmatter
        + textwrap.dedent(
            f"""

            # {TASK}
            {body}
            ## Session log
            - 2026-09-27T00:00:00Z merge-watcher: PR #4830 merged; runtime witnesses unmet
            """
        ),
        encoding="utf-8",
    )
    return note


def _close(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key not in _IDENTITY_ENV}
    env.update(
        HOME=str(home),
        HAPAX_CC_TASKS_ROOT=str(_vault(home)),
        HAPAX_COORD_DIR=str(home / "coord"),
        HAPAX_AGENT_ROLE="dev42",
        # The done-only gates each have their own suites; these tests pin the locked write.
        HAPAX_CC_TASK_CLOSURE_GATE_OFF="1",
        HAPAX_ACCEPTANCE_RECEIPT_GATE_OFF="1",
        HAPAX_PR_MERGE_GATE_OFF="1",
        HAPAX_REQUEST_RECONCILER_OFF="1",
    )
    return subprocess.run(
        ["bash", str(SCRIPT), TASK, *args],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )


def _closed(home: Path) -> Path:
    return _vault(home) / "closed" / f"{TASK}.md"


def _new_log_lines(before: str, after: str) -> list[str]:
    old = set(before.splitlines())
    tail = after.split("## Session log\n", 1)[1]
    return [line for line in tail.splitlines() if line.startswith("- ") and line not in old]


def _frontmatter_status_lines(text: str) -> list[str]:
    block = text[3 : text.find("\n---", 3)]
    return [line for line in block.splitlines() if "status" in line.split(":", 1)[0]]


@pytest.mark.parametrize("final_status", ["withdrawn", "superseded"])
def test_a_disposition_close_records_its_reason_in_the_same_write(
    tmp_path: Path, final_status: str
) -> None:
    note = _row(tmp_path, status_lines="status: claimed")
    before = note.read_text(encoding="utf-8")

    closed = _close(tmp_path, "--status", final_status, "--reason", "superseded by #4830 (M179)")

    assert closed.returncode == 0, closed.stderr
    after = _closed(tmp_path).read_text(encoding="utf-8")
    [line] = _new_log_lines(before, after)
    assert line.endswith(f"dev42 closed as {final_status}: superseded by #4830 (M179) (cc-close)")
    assert _frontmatter_status_lines(after) == [f"status: {final_status}"]


@pytest.mark.parametrize("final_status", ["withdrawn", "superseded"])
def test_a_disposition_close_without_a_reason_changes_nothing(
    tmp_path: Path, final_status: str
) -> None:
    note = _row(tmp_path, status_lines="status: claimed")
    before = note.read_bytes()

    refused = _close(tmp_path, "--status", final_status)

    assert refused.returncode == 1
    assert "--reason" in refused.stderr and "Next action" in refused.stderr
    assert note.read_bytes() == before and not _closed(tmp_path).exists()


@pytest.mark.parametrize(
    ("args", "flag"),
    [
        (("--status", "withdrawn", "--reason", "two\nlines"), "--reason"),
        (("--status", "withdrawn", "--reason", "   "), "--reason"),
        (("--pr", "4830", "--witness", "two\rlines"), "--witness"),
        (("--pr", "4830", "--witness", ""), "--witness"),
    ],
    ids=["reason_newline", "reason_blank", "witness_carriage_return", "witness_empty"],
)
def test_a_reason_or_witness_is_one_non_empty_line(
    tmp_path: Path, args: tuple[str, ...], flag: str
) -> None:
    note = _row(tmp_path)
    before = note.read_bytes()

    refused = _close(tmp_path, *args, "--retroactive")

    assert refused.returncode == 1
    assert flag in refused.stderr and "one non-empty line" in refused.stderr
    assert note.read_bytes() == before and not _closed(tmp_path).exists()


def test_done_on_an_awaiting_row_without_a_witness_changes_nothing(tmp_path: Path) -> None:
    note = _row(tmp_path)
    before = note.read_bytes()

    refused = _close(tmp_path, "--pr", "4830", "--retroactive")

    assert refused.returncode == 5, refused.stderr
    assert f'cc-close {TASK} --pr 4830 --witness "<observation>"' in refused.stderr
    assert note.read_bytes() == before and not _closed(tmp_path).exists()


def test_a_witness_closes_an_awaiting_row_done_in_one_write(tmp_path: Path) -> None:
    note = _row(tmp_path)
    before = note.read_text(encoding="utf-8")

    closed = _close(tmp_path, "--pr", "4830", "--witness", OBSERVATION, "--retroactive")

    assert closed.returncode == 0, closed.stderr
    assert not note.exists()
    after = _closed(tmp_path).read_text(encoding="utf-8")
    [line] = _new_log_lines(before, after)
    assert line.endswith(
        f"dev42 closed as done (PR #4830); runtime witness: {OBSERVATION} (cc-close)"
    )
    assert _frontmatter_status_lines(after) == ["status: done"]


def test_the_witness_rewrite_changes_the_line_it_read_and_never_a_body_line(
    tmp_path: Path,
) -> None:
    # A space before the colon is the same key line to the reader and the rewrite; the old
    # first-match `^status:` would have rewritten the body's line instead.
    note = _row(
        tmp_path,
        status_lines=f"status : {AWAITING}",
        body="\nstatus: this body line is prose, never frontmatter\n",
    )

    closed = _close(tmp_path, "--pr", "4830", "--witness", OBSERVATION, "--retroactive")

    assert closed.returncode == 0, closed.stderr
    assert not note.exists()
    after = _closed(tmp_path).read_text(encoding="utf-8")
    assert _frontmatter_status_lines(after) == ["status: done"]
    assert "\nstatus: this body line is prose, never frontmatter\n" in after


@pytest.mark.parametrize(
    "status_lines",
    [
        f'"status": {AWAITING}',
        f"status: pr_open\n'status': {AWAITING}",
        f"status: {AWAITING}\nstatus: pr_open",
    ],
    ids=["quoted_only", "quoted_duplicate_after_plain", "plain_duplicate"],
)
def test_every_status_key_line_is_read_so_an_awaiting_row_is_never_closed_done_blind(
    tmp_path: Path, status_lines: str
) -> None:
    note = _row(tmp_path, status_lines=status_lines)
    before = note.read_bytes()

    refused = _close(tmp_path, "--pr", "4830", "--retroactive")

    assert refused.returncode == 5, refused.stderr
    assert note.read_bytes() == before and not _closed(tmp_path).exists()


@pytest.mark.parametrize(
    "status_lines",
    [f'"status": {AWAITING}', f"status: {AWAITING}\n'status': pr_open"],
    ids=["quoted_only", "duplicate"],
)
def test_a_witness_on_an_unreadable_awaiting_row_holds_and_names_the_repair(
    tmp_path: Path, status_lines: str
) -> None:
    note = _row(tmp_path, status_lines=status_lines)
    before = note.read_bytes()

    held = _close(tmp_path, "--pr", "4830", "--witness", OBSERVATION, "--retroactive")

    assert held.returncode == 5, held.stderr
    assert "one plain status line" in held.stderr and "Next action" in held.stderr
    assert note.read_bytes() == before and not _closed(tmp_path).exists()


def test_a_witness_is_refused_on_a_row_that_is_not_awaiting(tmp_path: Path) -> None:
    note = _row(tmp_path, status_lines="status: pr_open")
    before = note.read_bytes()

    refused = _close(tmp_path, "--pr", "4830", "--witness", OBSERVATION, "--retroactive")

    assert refused.returncode == 5, refused.stderr
    assert AWAITING in refused.stderr
    assert note.read_bytes() == before and not _closed(tmp_path).exists()


def test_a_witness_never_closes_a_row_other_than_done(tmp_path: Path) -> None:
    note = _row(tmp_path)
    before = note.read_bytes()

    refused = _close(
        tmp_path, "--status", "withdrawn", "--reason", "reverted", "--witness", OBSERVATION
    )

    assert refused.returncode == 1
    assert "--witness" in refused.stderr
    assert note.read_bytes() == before and not _closed(tmp_path).exists()


def test_an_awaiting_row_withdrawn_with_a_reason_rewrites_its_one_status_line(
    tmp_path: Path,
) -> None:
    note = _row(tmp_path, body="\nstatus: body prose\n")

    closed = _close(tmp_path, "--status", "withdrawn", "--reason", "the feature was reverted")

    assert closed.returncode == 0, closed.stderr
    assert not note.exists()
    after = _closed(tmp_path).read_text(encoding="utf-8")
    assert _frontmatter_status_lines(after) == ["status: withdrawn"]
    assert "\nstatus: body prose\n" in after


def test_a_row_without_a_session_log_gains_one_rather_than_losing_the_reason(
    tmp_path: Path,
) -> None:
    note = _row(tmp_path, status_lines="status: claimed")
    note.write_text(note.read_text(encoding="utf-8").split("## Session log\n")[0], "utf-8")

    closed = _close(tmp_path, "--status", "superseded", "--reason", "folded into #4830")

    assert closed.returncode == 0, closed.stderr
    after = _closed(tmp_path).read_text(encoding="utf-8")
    log = after.split("\n## Session log\n", 1)[1].splitlines()
    assert len(log) == 1 and log[0].endswith("closed as superseded: folded into #4830 (cc-close)")


def test_a_checkout_without_the_project_runtime_refuses_and_changes_nothing(
    tmp_path: Path,
) -> None:
    # The locked write imports shared.sdlc_claim, which a bare python3 cannot; cc-close needs
    # the project interpreter, as cc-claim does, and refuses before any gate or write without it.
    checkout = tmp_path / "checkout"
    (checkout / "scripts").mkdir(parents=True)
    (checkout / "hooks" / "scripts").mkdir(parents=True)
    (checkout / "scripts" / "cc-close").write_bytes(SCRIPT.read_bytes())
    for helper in ("agent-role.sh", "cc-task-root.sh"):
        source = REPO_ROOT / "hooks" / "scripts" / helper
        (checkout / "hooks" / "scripts" / helper).write_bytes(source.read_bytes())
    note = _row(tmp_path, status_lines="status: claimed")
    before = note.read_bytes()
    env = {key: value for key, value in os.environ.items() if key not in _IDENTITY_ENV}
    env.update(HOME=str(tmp_path), HAPAX_CC_TASKS_ROOT=str(_vault(tmp_path)))

    refused = subprocess.run(
        ["bash", str(checkout / "scripts" / "cc-close"), TASK, "--status", "withdrawn"]
        + ["--reason", "no runtime"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )

    assert refused.returncode == 3, refused.stderr
    assert "project_runtime_unprovisioned" in refused.stderr and "uv sync" in refused.stderr
    assert note.read_bytes() == before and not _closed(tmp_path).exists()
