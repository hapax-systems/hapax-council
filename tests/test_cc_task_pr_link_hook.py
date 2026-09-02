"""Tests for hooks/scripts/cc-task-pr-link.sh (H8 — PR3 of cc-hygiene).

Invokes the shell hook via subprocess against synthetic vault fixtures
so the operator's real ~/Documents/Personal vault is never touched.

Per project convention, no shared conftest fixtures — each test builds
its own vault + claim file under ``tmp_path``.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "cc-task-pr-link.sh"


def _make_vault(
    tmp_path: Path,
    *,
    task_id: str = "test-001",
    pr: str | None = None,
    status: str = "in_progress",
    branch: str | None = None,
) -> tuple[Path, Path]:
    """Build a fixture vault under ``tmp_path/Documents/Personal/...``.

    Returns ``(vault_root, note_path)``.
    """
    vault_root = tmp_path / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    note_dir = vault_root / "active"
    note_dir.mkdir(parents=True, exist_ok=True)
    pr_line = f"pr: {pr if pr is not None else 'null'}"
    branch_line = f"branch: {branch if branch is not None else 'null'}"
    note = note_dir / f"{task_id}-test-task.md"
    note.write_text(
        f"""---
type: cc-task
task_id: {task_id}
title: "Fixture task"
status: {status}
assigned_to: beta
priority: normal
{branch_line}
{pr_line}
created_at: 2026-04-26T00:00:00Z
updated_at: 2026-04-26T00:00:00Z
---

# Fixture task

## Session log

- 2026-04-26T00:00:00Z fixture
"""
    )
    return vault_root, note


def _write_claim(home: Path, role: str, task_id: str) -> None:
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"cc-active-task-{role}").write_text(task_id + "\n")


def _run_hook(
    *,
    bash_cmd: str,
    bash_output: str,
    role: str = "beta",
    home: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Invoke the hook with PostToolUse-shaped JSON on stdin."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": bash_cmd},
        "tool_response": {"output": bash_output},
        "session_id": "test-session",
    }
    env = os.environ.copy()
    if home is not None:
        env["HOME"] = str(home)
    env["CLAUDE_ROLE"] = role
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


def _run_payload(
    payload: dict,
    *,
    home: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("CLAUDE_ROLE", None)
    env.pop("CODEX_ROLE", None)
    env.pop("CODEX_THREAD_NAME", None)
    env.pop("CODEX_SESSION", None)
    env.pop("CODEX_SESSION_NAME", None)
    env.pop("HAPAX_AGENT_NAME", None)
    env.pop("HAPAX_AGENT_ROLE", None)
    env.pop("HAPAX_AGENT_SLOT", None)
    env.pop("HAPAX_WORKTREE_ROLE", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


class TestHappyPath:
    def test_links_pr_when_active_claim_exists(self, tmp_path: Path) -> None:
        _vault, note = _make_vault(tmp_path, task_id="test-001", pr=None)
        _write_claim(tmp_path, "beta", "test-001")
        result = _run_hook(
            bash_cmd='gh pr create --title "feat: x" --body "y"',
            bash_output="https://github.com/ryanklee/hapax-council/pull/4242\n",
            home=tmp_path,
        )
        assert result.returncode == 0, result.stderr
        text = note.read_text(encoding="utf-8")
        assert "pr: 4242" in text
        assert "status: pr_open" in text
        assert "auto-linked PR #4242" in text

    def test_writes_pr_repo_from_the_pr_url(self, tmp_path: Path) -> None:
        """A BARE PR NUMBER IS NOT A LINK, so the repository is recorded at birth.

        The merge watcher scans ONE repository and would otherwise match any task carrying that
        number -- which closed a task meaning reins#6 against a merged council#6 while the real PR
        was still open. Both closure gates now REQUIRE pr_repo, so a task written without it can
        never close.

        This hook already parsed the PR URL, so it always knew the repository; it simply was not
        writing it down. With several sessions creating tasks in parallel, "the author will
        remember to add it" is not a mechanism.
        """
        _vault, note = _make_vault(tmp_path, task_id="repo-001", pr=None)
        _write_claim(tmp_path, "beta", "repo-001")
        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/hapax-systems/reins/pull/6\n",
            home=tmp_path,
        )
        assert result.returncode == 0, result.stderr
        text = note.read_text(encoding="utf-8")
        assert "pr_repo: hapax-systems/reins" in text, (
            "the task was linked to PR #6 with no repository; both closure gates will refuse it"
        )
        assert "pr: 6" in text

    def test_pr_repo_follows_the_url_not_a_default(self, tmp_path: Path) -> None:
        """Two repositories, same hook. The value must come from the URL, not a constant."""
        _vault, note = _make_vault(tmp_path, task_id="repo-002", pr=None)
        _write_claim(tmp_path, "beta", "repo-002")
        _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/ryanklee/hapax-council/pull/4242\n",
            home=tmp_path,
        )
        assert "pr_repo: ryanklee/hapax-council" in note.read_text(encoding="utf-8")

    def test_writes_branch_field(self, tmp_path: Path) -> None:
        _vault, note = _make_vault(tmp_path, task_id="ef7-020", pr=None, branch=None)
        _write_claim(tmp_path, "beta", "ef7-020")
        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/ryanklee/hapax-council/pull/9001",
            home=tmp_path,
        )
        assert result.returncode == 0
        text = note.read_text(encoding="utf-8")
        assert "branch: " in text

    def test_mcp_github_pr_create_links_pr(self, tmp_path: Path) -> None:
        _vault, note = _make_vault(tmp_path, task_id="mcp-task", pr=None)
        _write_claim(tmp_path, "beta", "mcp-task")

        result = _run_payload(
            {
                "tool_name": "mcp__github__create_pull_request",
                "tool_response": {"output": "https://github.com/ryanklee/hapax-council/pull/5151"},
            },
            home=tmp_path,
            extra_env={"CLAUDE_ROLE": "beta"},
        )

        assert result.returncode == 0, result.stderr
        text = note.read_text(encoding="utf-8")
        assert "pr: 5151" in text
        assert "status: pr_open" in text


class TestIdempotency:
    def test_existing_pr_not_overwritten(self, tmp_path: Path) -> None:
        _vault, note = _make_vault(tmp_path, task_id="test-001", pr="100", status="claimed")
        _write_claim(tmp_path, "beta", "test-001")
        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/ryanklee/hapax-council/pull/200",
            home=tmp_path,
        )
        assert result.returncode == 0
        text = note.read_text(encoding="utf-8")
        # Original PR retained.
        assert "pr: 100" in text
        assert "pr: 200" not in text
        assert "status: claimed" in text
        assert "status: pr_open" not in text
        # The refusal is not silent: it names the row, both PRs, and the next action (the
        # exit predicate requires BOTH refusal paths to name the conflicting task).
        assert "REFUSING to overwrite 'test-001-test-task'" in result.stderr
        assert "already declares PR #100" in result.stderr
        assert "PR #200 is a different PR" in result.stderr
        assert "Next action:" in result.stderr

    def test_same_number_in_another_repository_is_not_the_same_pr(self, tmp_path: Path) -> None:
        """PR numbers are per repository (review finding on #4613, round 3).

        A row bound to #100 in hapax-spine must not be rebound to #100 in hapax-council: the
        number-only guard let the link fall through and then replaced ``pr_repo`` silently, which
        is the same-numbered cross-repository confusion that closed the wrong task twice in August.
        """
        _vault, note = _make_vault(tmp_path, task_id="test-001", pr="100", status="claimed")
        note.write_text(
            note.read_text(encoding="utf-8").replace(
                "pr: 100\n", "pr: 100\npr_repo: ryanklee/hapax-spine\n", 1
            ),
            encoding="utf-8",
        )
        _write_claim(tmp_path, "beta", "test-001")
        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/ryanklee/hapax-council/pull/100",
            home=tmp_path,
        )
        assert result.returncode == 0
        text = note.read_text(encoding="utf-8")
        assert "pr: 100" in text
        assert "pr_repo: ryanklee/hapax-spine" in text
        assert "hapax-council" not in text
        assert "status: claimed" in text
        assert "REFUSING to overwrite 'test-001-test-task'" in result.stderr
        assert "PR #100 in ryanklee/hapax-spine" in result.stderr
        assert "PR #100 in ryanklee/hapax-council" in result.stderr
        assert "same number" in result.stderr
        assert "Next action:" in result.stderr

    def test_same_number_in_the_same_repository_completes_the_link(self, tmp_path: Path) -> None:
        """The control for the guard above: the same PR in the same repository is not a conflict."""
        _vault, note = _make_vault(tmp_path, task_id="test-001", pr="100", status="claimed")
        note.write_text(
            note.read_text(encoding="utf-8").replace(
                "pr: 100\n", "pr: 100\npr_repo: RyanKlee/Hapax-Council\n", 1
            ),
            encoding="utf-8",
        )
        _write_claim(tmp_path, "beta", "test-001")
        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/ryanklee/hapax-council/pull/100",
            home=tmp_path,
        )
        assert result.returncode == 0
        assert "REFUSING" not in result.stderr
        assert "status: pr_open" in note.read_text(encoding="utf-8")

    @pytest.mark.parametrize("scalar", ['"4605"', "'4605'", "4605 # owns it", '"4605" # owner'])
    def test_quoted_or_commented_pr_scalars_are_the_same_link(
        self, tmp_path: Path, scalar: str
    ) -> None:
        """`pr: "4605"` and `pr: 4605 # owner` declare #4605 (review finding on #4613, round 4):
        comparing the raw text let valid YAML forms bypass the duplicate-link refusal."""
        _vault, note = _make_vault(tmp_path, task_id="research-row", pr=None, status="in_progress")
        owner = note.parent / "velocity-fix-test-task.md"
        owner.write_text(
            '---\ntype: cc-task\ntask_id: velocity-fix\ntitle: "Owns the PR"\n'
            "status: pr_open\nassigned_to: beta\npriority: normal\n"
            f"branch: fix/velocity\npr: {scalar}\npr_repo: ryanklee/hapax-council\n"
            "created_at: 2026-04-26T00:00:00Z\nupdated_at: 2026-04-26T00:00:00Z\n---\n\n"
            "# Owns the PR\n\n## Session log\n",
            encoding="utf-8",
        )
        _write_claim(tmp_path, "beta", "research-row")
        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/ryanklee/hapax-council/pull/4605",
            home=tmp_path,
        )
        assert result.returncode == 0
        assert "pr: 4605" not in note.read_text(encoding="utf-8")
        assert "REFUSING" in result.stderr
        assert "velocity-fix" in result.stderr

    def test_refuses_a_pr_another_active_task_already_declares(self, tmp_path: Path) -> None:
        """A PR must not be bound to two tasks. Measured defect, three occurrences on one row.

        The hook links the PR just created to whatever task the role holds, and nothing tested that
        the two were related. On a long-lived `kind: research` row held for days, every PR opened in
        that window is a candidate. 2026-08-24 it attached #4605 — a one-line velocity fix with its
        own correctly-formed row — and every blocker autoqueue then reported on #4605 was that
        research programme's unmet acceptance criteria. Cleared 2026-09-01; within hours it attached
        #4612, which also had its own row.

        Note WHY clearing did not help: the idempotency guard protects a row from being OVERWRITTEN,
        never from wrongly ACQUIRING, so nulling `pr:` to repair a bad link makes that row the next
        eligible target. Repairing the instance re-armed the mechanism.
        """
        _vault, note = _make_vault(tmp_path, task_id="research-row", pr=None, status="in_progress")
        owner = note.parent / "velocity-fix-test-task.md"
        owner.write_text(
            '---\ntype: cc-task\ntask_id: velocity-fix\ntitle: "Owns the PR"\n'
            "status: pr_open\nassigned_to: beta\npriority: normal\n"
            "branch: fix/velocity\npr: 4605\npr_repo: ryanklee/hapax-council\n"
            "created_at: 2026-04-26T00:00:00Z\nupdated_at: 2026-04-26T00:00:00Z\n---\n\n"
            "# Owns the PR\n\n## Session log\n",
            encoding="utf-8",
        )
        _write_claim(tmp_path, "beta", "research-row")

        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/ryanklee/hapax-council/pull/4605",
            home=tmp_path,
        )

        assert result.returncode == 0, "a refusal is not an error; the hook must not fail the turn"
        text = note.read_text(encoding="utf-8")
        assert "pr: 4605" not in text, (
            "the research row must NOT acquire a PR another task already declares"
        )
        assert "pr: null" in text
        assert "status: in_progress" in text, "and must not advance status on a refused link"
        assert "pr: 4605" in owner.read_text(encoding="utf-8"), "a refusal moves nothing"
        # The refusal names both tasks and the next action (exit predicate: BOTH refusals do).
        assert "REFUSING to link PR #4605 to 'research-row-test-task'" in result.stderr
        assert "'velocity-fix-test-task' already declares it" in result.stderr
        assert "Next action:" in result.stderr

    def test_still_links_when_no_other_task_declares_the_pr(self, tmp_path: Path) -> None:
        """The guard must not break the ordinary case it sits in front of.

        A same-numbered PR in a DIFFERENT repository is not the same PR — this estate has closed the
        wrong task twice that way — so `pr_repo` participates in the comparison.
        """
        _vault, note = _make_vault(tmp_path, task_id="test-001", pr=None, status="claimed")
        foreign = note.parent / "foreign-repo-task.md"
        foreign.write_text(
            '---\ntype: cc-task\ntask_id: foreign\ntitle: "Same number, other repo"\n'
            "status: pr_open\nassigned_to: beta\npriority: normal\n"
            "branch: x\npr: 4242\npr_repo: hapax-systems/reins\n"
            "created_at: 2026-04-26T00:00:00Z\nupdated_at: 2026-04-26T00:00:00Z\n---\n\n"
            "# Foreign\n\n## Session log\n",
            encoding="utf-8",
        )
        _write_claim(tmp_path, "beta", "test-001")

        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/ryanklee/hapax-council/pull/4242",
            home=tmp_path,
        )

        assert result.returncode == 0
        assert "pr: 4242" in note.read_text(encoding="utf-8"), (
            "a same-numbered PR in another repository must not block a legitimate link"
        )

    def test_a_bare_number_on_another_row_is_not_a_link_and_does_not_block(
        self, tmp_path: Path
    ) -> None:
        """Repository contract: `pr:` without `pr_repo:` is not a link. A row carrying only the
        number therefore declares no PR, so it cannot be the conflicting task (review finding on
        #4613: the first version treated a missing pr_repo as "same repository" and refused)."""
        _vault, note = _make_vault(tmp_path, task_id="test-001", pr=None, status="claimed")
        bare = note.parent / "bare-number-task.md"
        bare.write_text(
            '---\ntype: cc-task\ntask_id: bare\ntitle: "Number only, no repository"\n'
            "status: pr_open\nassigned_to: beta\npriority: normal\n"
            "branch: x\npr: 4242\n"
            "created_at: 2026-04-26T00:00:00Z\nupdated_at: 2026-04-26T00:00:00Z\n---\n\n"
            "# Bare\n\n## Session log\n",
            encoding="utf-8",
        )
        _write_claim(tmp_path, "beta", "test-001")

        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/ryanklee/hapax-council/pull/4242",
            home=tmp_path,
        )

        assert result.returncode == 0
        assert "pr: 4242" in note.read_text(encoding="utf-8")
        assert "REFUSING" not in result.stderr

    def test_repository_names_compare_case_insensitively(self, tmp_path: Path) -> None:
        """GitHub owner/name are case-insensitive: `RyanKlee/Hapax-Council` is the same repository
        as `ryanklee/hapax-council`, so a differently capitalised declaration still conflicts."""
        _vault, note = _make_vault(tmp_path, task_id="research-row", pr=None, status="in_progress")
        owner = note.parent / "capitalised-owner-task.md"
        owner.write_text(
            '---\ntype: cc-task\ntask_id: capitalised\ntitle: "Owns the PR"\n'
            "status: pr_open\nassigned_to: beta\npriority: normal\n"
            'branch: x\npr: 4605\npr_repo: "RyanKlee/Hapax-Council"\n'
            "created_at: 2026-04-26T00:00:00Z\nupdated_at: 2026-04-26T00:00:00Z\n---\n\n"
            "# Owner\n\n## Session log\n",
            encoding="utf-8",
        )
        _write_claim(tmp_path, "beta", "research-row")

        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/ryanklee/hapax-council/pull/4605",
            home=tmp_path,
        )

        assert result.returncode == 0
        assert "pr: 4605" not in note.read_text(encoding="utf-8")
        assert "'capitalised-owner-task' already declares it" in result.stderr

    def test_matching_existing_pr_still_advances_status(self, tmp_path: Path) -> None:
        _vault, note = _make_vault(
            tmp_path,
            task_id="test-001",
            pr="4242",
            status="claimed",
            branch=None,
        )
        _write_claim(tmp_path, "beta", "test-001")
        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/ryanklee/hapax-council/pull/4242\n",
            home=tmp_path,
        )
        assert result.returncode == 0, result.stderr
        text = note.read_text(encoding="utf-8")
        assert "pr: 4242" in text
        assert "pr: 200" not in text
        assert "status: pr_open" in text
        assert "branch: null" not in text
        assert "auto-linked PR #4242" in text


class TestGracefulSkips:
    def test_no_active_claim_exits_zero(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, task_id="test-001", pr=None)
        # NO claim file written.
        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/ryanklee/hapax-council/pull/4242",
            home=tmp_path,
        )
        assert result.returncode == 0
        assert "no active claim" in result.stderr

    def test_no_pr_url_in_output_exits_zero(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, task_id="test-001", pr=None)
        _write_claim(tmp_path, "beta", "test-001")
        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="some other output\nno url here",
            home=tmp_path,
        )
        assert result.returncode == 0
        assert "no PR URL" in result.stderr

    def test_non_gh_pr_create_passes_through(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, task_id="test-001", pr=None)
        _write_claim(tmp_path, "beta", "test-001")
        result = _run_hook(
            bash_cmd="ls -la",
            bash_output="file1\nfile2",
            home=tmp_path,
        )
        assert result.returncode == 0
        # No URL present and command doesn't match — silent exit.

    def test_non_bash_tool_passes_through(self, tmp_path: Path) -> None:
        _make_vault(tmp_path, task_id="test-001", pr=None)
        _write_claim(tmp_path, "beta", "test-001")
        payload = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/x"},
            "tool_response": {"output": "https://github.com/x/y/pull/1"},
        }
        env = os.environ.copy()
        env["HOME"] = str(tmp_path)
        env["CLAUDE_ROLE"] = "beta"
        result = subprocess.run(
            [str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0

    def test_vault_note_missing_exits_zero(self, tmp_path: Path) -> None:
        # No vault note created.
        _write_claim(tmp_path, "beta", "test-001")
        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/ryanklee/hapax-council/pull/4242",
            home=tmp_path,
        )
        assert result.returncode == 0
        assert "vault note" in result.stderr

    def test_empty_stdin_exits_zero(self, tmp_path: Path) -> None:
        env = os.environ.copy()
        env["HOME"] = str(tmp_path)
        env["CLAUDE_ROLE"] = "beta"
        result = subprocess.run(
            [str(HOOK)],
            input="",
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0


class TestKillswitch:
    def test_killswitch_skips_link(self, tmp_path: Path) -> None:
        _vault, note = _make_vault(tmp_path, task_id="test-001", pr=None)
        _write_claim(tmp_path, "beta", "test-001")
        result = _run_hook(
            bash_cmd="gh pr create",
            bash_output="https://github.com/ryanklee/hapax-council/pull/4242",
            home=tmp_path,
            extra_env={"HAPAX_CC_HYGIENE_OFF": "1"},
        )
        assert result.returncode == 0
        text = note.read_text(encoding="utf-8")
        assert "pr: 4242" not in text
        assert "pr: null" in text


class TestRoleResolution:
    def test_codex_claim_precedes_inherited_claude_role(self, tmp_path: Path) -> None:
        _vault, codex_note = _make_vault(tmp_path, task_id="codex-task", pr=None)
        _vault, alpha_note = _make_vault(tmp_path, task_id="alpha-task", pr=None)
        _write_claim(tmp_path, "cx-red", "codex-task")
        _write_claim(tmp_path, "alpha", "alpha-task")

        result = _run_payload(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "gh --repo ryanklee/hapax-council pr create --title test"
                },
                "tool_response": {"output": "https://github.com/ryanklee/hapax-council/pull/6060"},
            },
            home=tmp_path,
            extra_env={
                "CLAUDE_ROLE": "alpha",
                "HAPAX_AGENT_ROLE": "cx-red",
                "CODEX_THREAD_NAME": "cx-red",
                "CODEX_ROLE": "cx-red",
            },
        )

        assert result.returncode == 0, result.stderr
        assert "pr: 6060" in codex_note.read_text(encoding="utf-8")
        assert "pr: 6060" not in alpha_note.read_text(encoding="utf-8")

    def test_relay_yaml_fallback_when_role_unset(self, tmp_path: Path) -> None:
        _vault, note = _make_vault(tmp_path, task_id="test-001", pr=None)
        # Write a single relay yaml so the hook can infer role=beta.
        relay = tmp_path / ".cache" / "hapax" / "relay"
        relay.mkdir(parents=True, exist_ok=True)
        (relay / "beta.yaml").write_text("session_status: alive\n")
        _write_claim(tmp_path, "beta", "test-001")

        env = os.environ.copy()
        env["HOME"] = str(tmp_path)
        env.pop("CLAUDE_ROLE", None)
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr create"},
            "tool_response": {"output": "https://github.com/x/y/pull/777"},
        }
        result = subprocess.run(
            [str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        text = note.read_text(encoding="utf-8")
        assert "pr: 777" in text


class TestPrUrlParsing:
    def test_extracts_first_pr_url_from_multiline_output(self, tmp_path: Path) -> None:
        _vault, note = _make_vault(tmp_path, task_id="test-001", pr=None)
        _write_claim(tmp_path, "beta", "test-001")
        # Real `gh pr create` output: a status banner, then the URL.
        bash_output = (
            "Creating pull request for beta/foo into main in ryanklee/hapax-council\n"
            "\n"
            "https://github.com/ryanklee/hapax-council/pull/1234\n"
        )
        result = _run_hook(bash_cmd="gh pr create", bash_output=bash_output, home=tmp_path)
        assert result.returncode == 0, result.stderr
        text = note.read_text(encoding="utf-8")
        assert "pr: 1234" in text

    def test_ignores_non_pull_github_urls(self, tmp_path: Path) -> None:
        _vault, note = _make_vault(tmp_path, task_id="test-001", pr=None)
        _write_claim(tmp_path, "beta", "test-001")
        bash_output = "https://github.com/ryanklee/hapax-council/issues/42\n"
        result = _run_hook(bash_cmd="gh pr create", bash_output=bash_output, home=tmp_path)
        assert result.returncode == 0
        text = note.read_text(encoding="utf-8")
        # No PR URL pattern matched, so no rewrite.
        assert "pr: null" in text
