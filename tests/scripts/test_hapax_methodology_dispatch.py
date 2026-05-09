import json
import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-methodology-dispatch"


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _task(
    root: Path,
    task_id: str,
    frontmatter: str,
    *,
    status: str = "offered",
    assigned_to: str = "unassigned",
) -> Path:
    return _write(
        root / "active" / f"{task_id}.md",
        "\n".join(
            [
                "---",
                "type: cc-task",
                f"task_id: {task_id}",
                f'title: "{task_id}"',
                f"status: {status}",
                f"assigned_to: {assigned_to}",
                textwrap.dedent(frontmatter).strip(),
                "---",
                "",
                f"# {task_id}",
                "",
            ]
        ),
    )


def _spec(path: Path, case_id: str = "CASE-TEST-001") -> Path:
    return _write(
        path,
        textwrap.dedent(
            f"""\
            ---
            status: implementation_slice_authorization_packet
            case_id: {case_id}
            slice_id: SLICE-TEST
            ---

            # Test ISAP
            """
        ),
    )


def _worktree(path: Path, *, guarded: bool = True, close_guarded: bool = True) -> Path:
    guard = (
        "missing required AuthorityCase/ISAP fields authority_case parent_spec"
        if guarded
        else "legacy cc-claim"
    )
    close_guard = (
        "frontmatter_task_id closed_duplicate closed task duplicate has task_id"
        if close_guarded
        else "legacy cc-close"
    )
    _write(path / "scripts" / "cc-claim", f"#!/usr/bin/env bash\n# {guard}\n")
    _write(path / "scripts" / "cc-close", f"#!/usr/bin/env bash\n# {close_guard}\n")
    return path


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["HAPAX_CC_TASK_ROOT"] = str(tmp_path / "tasks")
    env["HAPAX_DISPATCH_WORKTREE"] = str(tmp_path / "worktree")
    env["HAPAX_ORCHESTRATION_LEDGER_DIR"] = str(tmp_path / "ledger")
    return subprocess.run(
        [str(SCRIPT), *args],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_blocks_mutation_task_with_null_parent_spec(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    _task(
        tmp_path / "tasks",
        "bad-build",
        """
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: null
        """,
    )

    result = _run(tmp_path, "--task", "bad-build", "--lane", "beta")

    assert result.returncode == 10
    assert "missing required AuthorityCase/ISAP fields" in result.stderr
    assert "parent_spec" in result.stderr
    ledger = (tmp_path / "ledger" / "methodology-dispatch.jsonl").read_text(encoding="utf-8")
    assert '"ok": false' in ledger


def test_allows_explicit_read_only_intake_without_authority(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    _task(
        tmp_path / "tasks",
        "intake-only",
        """
        kind: intake
        task_type: read-only
        parent_spec: null
        tags:
          - intake
          - read-only
        """,
    )

    result = _run(tmp_path, "--task", "intake-only", "--lane", "beta", "--print-prompt")

    assert result.returncode == 0, result.stderr
    assert "eligible: intake-only -> claude/beta" in result.stdout
    assert "AuthorityCase: read-only-exempt" in result.stdout


def test_governed_prompt_is_specific_and_not_work_pool_prompt(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )

    result = _run(tmp_path, "--task", "governed-build", "--lane", "beta", "--print-prompt")

    assert result.returncode == 0, result.stderr
    assert "Task: governed-build" in result.stdout
    assert "AuthorityCase: CASE-TEST-001" in result.stdout
    assert str(spec) in result.stdout
    assert "claim the next" not in result.stdout
    assert "highest-WSJF" not in result.stdout
    assert "Never stop" not in result.stdout


def test_blocks_offered_task_preassigned_to_target_lane(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "preassigned-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
        assigned_to="beta",
    )

    result = _run(tmp_path, "--task", "preassigned-build", "--lane", "beta")

    assert result.returncode == 10
    assert "offered task assigned_to 'beta' is not claimable" in result.stderr
    assert "target-lane routing belongs in dispatch" in result.stderr
    assert "must remain unassigned until cc-claim" in result.stderr


def test_allows_claimed_task_assigned_to_target_lane(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "claimed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
        status="claimed",
        assigned_to="beta",
    )

    result = _run(tmp_path, "--task", "claimed-build", "--lane", "beta")

    assert result.returncode == 0, result.stderr
    assert "eligible: claimed-build -> claude/beta" in result.stdout


def test_blocks_claimed_task_assigned_to_unassigned(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "bad-claimed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
        status="claimed",
        assigned_to="unassigned",
    )

    result = _run(tmp_path, "--task", "bad-claimed-build", "--lane", "beta")

    assert result.returncode == 10
    assert "claimed/in_progress tasks may only be dispatched" in result.stderr


def test_blocks_stale_worktree_cc_claim_before_launch(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree", guarded=False)
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )

    result = _run(tmp_path, "--task", "governed-build", "--lane", "beta")

    assert result.returncode == 10
    assert "stale cc-claim" in result.stderr


def test_blocks_stale_worktree_cc_close_before_launch(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree", guarded=True, close_guarded=False)
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )

    result = _run(tmp_path, "--task", "governed-build", "--lane", "beta")

    assert result.returncode == 10
    assert "stale cc-close" in result.stderr


def test_prompt_contains_worktree_local_cc_claim_path(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )

    result = _run(tmp_path, "--task", "governed-build", "--lane", "beta", "--print-prompt")

    assert result.returncode == 0, result.stderr
    prompt = result.stdout
    assert "scripts/cc-claim governed-build" in prompt
    assert "/scripts/cc-claim governed-build" in prompt
    assert "scripts/cc-close" in prompt
    assert "/scripts/cc-close" in prompt
    lines = [l for l in prompt.splitlines() if "cc-claim" in l.lower()]
    for line in lines:
        assert "Run cc-claim governed-build" not in line or "/scripts/cc-claim" in line, (
            f"bare cc-claim without absolute path found: {line!r}"
        )
    close_lines = [l for l in prompt.splitlines() if "cc-close" in l.lower()]
    for line in close_lines:
        assert "bare cc-close" in line or "/scripts/cc-close" in line, (
            f"bare cc-close without absolute path found: {line!r}"
        )


def test_prompt_does_not_use_canonical_checkout_cc_claim(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )

    result = _run(tmp_path, "--task", "governed-build", "--lane", "beta", "--print-prompt")

    assert result.returncode == 0, result.stderr
    prompt = result.stdout
    assert "hapax-council/scripts/cc-claim" not in prompt or "hapax-council--beta" in prompt, (
        "prompt must not reference the canonical checkout cc-claim for a non-alpha lane"
    )


def test_receipt_contains_task_and_authority(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )

    result = _run(tmp_path, "--task", "governed-build", "--lane", "beta")

    assert result.returncode == 0, result.stderr
    line = (
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    receipt = json.loads(line)
    assert receipt["ok"] is True
    assert receipt["task_id"] == "governed-build"
    assert receipt["parent_spec_path"] == str(spec)
