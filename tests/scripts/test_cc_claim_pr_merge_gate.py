"""Tests for cc-claim PR merge dependency gate.

Validates that cc-claim blocks dependent task claims when upstream
tasks have unmerged PRs, per REQ-20260509191922.
"""

import os
import pathlib
import subprocess
import textwrap

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cc-claim"
CLOSE_CHECK = REPO_ROOT / "scripts" / "cc-close-pr-merge-check.py"
_SESSION_ID = "12345678-1234-4321-8765-123456789abc"
_BINDING_HASH = "c" * 64
_IDENTITY_ENV = (
    "HAPAX_AGENT_NAME",
    "CODEX_THREAD_NAME",
    "CODEX_SESSION_NAME",
    "CODEX_SESSION",
    "CODEX_ROLE",
    "CLAUDE_ROLE",
    "HAPAX_SESSION_ID",
    "CLAUDE_CODE_SESSION_ID",
    "HAPAX_GATE0B_CLAIM_PUBLICATION_OFF",
    "HAPAX_CLAIM_DISPATCH_MESSAGE_ID",
    "HAPAX_CLAIM_DISPATCH_BINDING_HASH",
    "HAPAX_CLAIM_DISPATCH_PLATFORM",
    "HAPAX_CLAIM_DISPATCH_MODE",
    "HAPAX_CLAIM_DISPATCH_PROFILE",
    "HAPAX_CLAIM_DISPATCH_AUTHORITY_CASE",
    "HAPAX_CLAIM_DISPATCH_IDEMPOTENCY_KEY",
)


def _extract_python(script_path: pathlib.Path) -> str:
    """Extract the embedded Python from the bash heredoc."""
    text = script_path.read_text()
    start = text.index("<<'PYEOF'") + len("<<'PYEOF'") + 1
    end = text.index("\nPYEOF", start)
    return text[start:end]


def test_script_exists_and_executable():
    assert SCRIPT.exists()
    assert SCRIPT.stat().st_mode & 0o111


def test_bash_syntax_valid():
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"Syntax error: {result.stderr}"


def test_python_syntax_valid():
    py_code = _extract_python(SCRIPT)
    compile(py_code, "cc-claim-embedded", "exec")


def test_parse_pr_number_function_exists():
    py_code = _extract_python(SCRIPT)
    assert "def _parse_pr_number(" in py_code


def test_check_pr_merged_function_exists():
    py_code = _extract_python(SCRIPT)
    assert "def _check_pr_merged(" in py_code


def test_parse_pr_repo_function_exists():
    py_code = _extract_python(SCRIPT)
    assert "def _parse_pr_repo(" in py_code
    assert 'DEFAULT_PR_REPO = "hapax-systems/hapax-council"' in py_code


def test_pr_gate_blocks_open_pr():
    """The code must block when a PR is 'open'."""
    py_code = _extract_python(SCRIPT)
    assert "task_closure_validity(" in py_code
    assert 'return "open"' in py_code


def test_pr_gate_blocks_closed_unmerged():
    """The code must block when a PR was closed without merge."""
    py_code = _extract_python(SCRIPT)
    assert 'return "closed_unmerged"' in py_code


def test_pr_gate_fails_closed_on_unknown():
    """Unknown PR state must fail closed (block), not pass."""
    py_code = _extract_python(SCRIPT)
    assert 'return "unknown"' in py_code
    assert "require_route_metadata_validity=True" in py_code


def test_pr_gate_allows_merged():
    """Merged PRs should NOT produce an unmet entry."""
    py_code = _extract_python(SCRIPT)
    # The code should only append to unmet for open/closed_unmerged/unknown
    # There should be no unmet.append for "merged"
    assert '"merged"' in py_code
    # The merged branch returns the state, the calling code only blocks non-merged
    lines = py_code.splitlines()
    merged_handling = [l for l in lines if "merged" in l and "unmet" in l]
    # Should be zero — merged should not produce unmet entries
    assert len(merged_handling) == 0, "Merged PR state should not block dispatch"


def test_dependency_gate_checks_status_first():
    """The dependency gate uses the shared closure-validity predicate."""
    py_code = _extract_python(SCRIPT)
    dep_pos = py_code.index("for dep_id in _parse_depends_on")
    predicate_pos = py_code.index("task_closure_validity(")
    assert dep_pos < predicate_pos, "Dependency checks must call the shared predicate"


def test_uses_gh_cli():
    """PR merge check should use the gh CLI tool."""
    py_code = _extract_python(SCRIPT)
    assert '"gh"' in py_code
    assert '"pr"' in py_code
    assert '"view"' in py_code
    assert '"--repo"' in py_code


def test_pr_gate_uses_current_gh_merge_field():
    """GitHub CLI exposes mergedAt for PR view; merged is not available."""
    py_code = _extract_python(SCRIPT)
    assert '"state,mergedAt"' in py_code
    assert '"state,merged"' not in py_code
    assert ".mergedAt != null" in py_code


def _task_root(home: pathlib.Path) -> pathlib.Path:
    root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (root / "active").mkdir(parents=True, exist_ok=True)
    (root / "closed").mkdir(parents=True, exist_ok=True)
    return root


def _write_task(
    home: pathlib.Path,
    subdir: str,
    task_id: str,
    *,
    status: str = "offered",
    depends_on: str = "[]",
    pr: str = "null",
    pr_repo: str | None = None,
) -> pathlib.Path:
    path = _task_root(home) / subdir / f"{task_id}.md"
    frontmatter = [
        "---",
        "type: cc-task",
        f"task_id: {task_id}",
        f'title: "{task_id}"',
        f"status: {status}",
        "assigned_to: unassigned",
        "claimable: true",
        "kind: build",
        "authority_case: CASE-TEST-001",
        "parent_spec: /tmp/isap-test.md",
        "quality_floor: frontier_required",
        "mutation_surface: source",
        "authority_level: authoritative",
        "route_metadata_schema: 1",
        f"pr: {pr}",
    ]
    if pr_repo is not None:
        frontmatter.append(f"pr_repo: {pr_repo}")
    if depends_on.startswith("\n"):
        frontmatter.append(f"depends_on:{depends_on}")
    else:
        frontmatter.append(f"depends_on: {depends_on}")
    frontmatter.extend(
        [
            "created_at: 2026-06-04T00:00:00Z",
            "updated_at: 2026-06-04T00:00:00Z",
            "claimed_at: null",
            "---",
            "",
            f"# {task_id}",
            "",
            "## Acceptance criteria",
            "- [x] Done",
            "",
            "## Session log",
        ]
    )
    path.write_text("\n".join(frontmatter), encoding="utf-8")
    return path


def _fake_gh(bin_dir: pathlib.Path, body: str) -> pathlib.Path:
    gh = bin_dir / "gh"
    gh.write_text(body, encoding="utf-8")
    gh.chmod(0o755)
    return gh


def _claim_with_fake_gh(
    home: pathlib.Path,
    task_id: str,
    bin_dir: pathlib.Path,
    log_path: pathlib.Path,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for var in _IDENTITY_ENV:
        env.pop(var, None)
    env["HOME"] = str(home)
    env["HAPAX_AGENT_ROLE"] = "cx-test"
    env["HAPAX_AGENT_NAME"] = "cx-test"
    env["HAPAX_SESSION_ID"] = _SESSION_ID
    env["HAPAX_CLAIM_DISPATCH_MESSAGE_ID"] = f"dispatch-{task_id}"
    env["HAPAX_CLAIM_DISPATCH_BINDING_HASH"] = _BINDING_HASH
    env["HAPAX_CLAIM_DISPATCH_PLATFORM"] = "codex"
    env["HAPAX_CLAIM_DISPATCH_MODE"] = "headless"
    env["HAPAX_CLAIM_DISPATCH_PROFILE"] = "ultra"
    env["HAPAX_CLAIM_DISPATCH_AUTHORITY_CASE"] = "CASE-TEST-001"
    env["HAPAX_CLAIM_DISPATCH_IDEMPOTENCY_KEY"] = f"coord-{task_id}"
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["GH_ARGS_LOG"] = str(log_path)
    return subprocess.run(
        ["bash", str(SCRIPT), task_id],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


CLAIM_FAKE_GH = textwrap.dedent(
    """\
    #!/usr/bin/env bash
    set -euo pipefail
    repo=""
    pr=""
    if [[ "${1:-}" == "pr" && "${2:-}" == "view" ]]; then
      pr="${3:-}"
      shift 3
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --repo) repo="$2"; shift 2 ;;
          *) shift ;;
        esac
      done
    fi
    printf '%s#%s\\n' "$repo" "$pr" >> "${GH_ARGS_LOG:?}"
    case "$repo#$pr" in
      ryanklee/hapax-coord#35) echo "MERGED,true" ;;
      ryanklee/hapax-coord#36) echo "CLOSED,false" ;;
      hapax-systems/hapax-council#12) echo "MERGED,true" ;;
      *) echo "OPEN,false" ;;
    esac
    """
)


def test_claim_allows_merged_external_repo_dependency(tmp_path: pathlib.Path) -> None:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "gh-args.log"
    _fake_gh(bin_dir, CLAIM_FAKE_GH)
    _write_task(
        home,
        "closed",
        "external-dep",
        status="done",
        pr="35",
        pr_repo="ryanklee/hapax-coord",
    )
    note = _write_task(home, "active", "target", depends_on="\n  - external-dep")

    result = _claim_with_fake_gh(home, "target", bin_dir, log_path)

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")
    assert log_path.read_text(encoding="utf-8").strip() == "ryanklee/hapax-coord#35"


def test_claim_blocks_closed_unmerged_external_repo_dependency(
    tmp_path: pathlib.Path,
) -> None:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "gh-args.log"
    _fake_gh(bin_dir, CLAIM_FAKE_GH)
    _write_task(
        home,
        "closed",
        "external-dep",
        status="done",
        pr="36",
        pr_repo="ryanklee/hapax-coord",
    )
    _write_task(home, "active", "target", depends_on="\n  - external-dep")

    result = _claim_with_fake_gh(home, "target", bin_dir, log_path)

    assert result.returncode == 5
    assert "external-dep (pr_closed_unmerged:36)" in result.stderr
    assert log_path.read_text(encoding="utf-8").strip() == "ryanklee/hapax-coord#36"


def test_claim_defaults_dependency_pr_lookup_to_council_repo(
    tmp_path: pathlib.Path,
) -> None:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "gh-args.log"
    _fake_gh(bin_dir, CLAIM_FAKE_GH)
    _write_task(home, "closed", "council-dep", status="done", pr="12")
    note = _write_task(home, "active", "target", depends_on="\n  - council-dep")

    result = _claim_with_fake_gh(home, "target", bin_dir, log_path)

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")
    assert log_path.read_text(encoding="utf-8").strip() == "hapax-systems/hapax-council#12"


CLOSE_FAKE_GH = textwrap.dedent(
    """\
    #!/usr/bin/env bash
    set -euo pipefail
    repo=""
    pr=""
    if [[ "${1:-}" == "pr" && "${2:-}" == "view" ]]; then
      pr="${3:-}"
      shift 3
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --repo) repo="$2"; shift 2 ;;
          *) shift ;;
        esac
      done
    fi
    printf '%s#%s\\n' "$repo" "$pr" >> "${GH_ARGS_LOG:?}"
    case "$repo#$pr" in
      ryanklee/hapax-coord#35) echo "MERGED" ;;
      hapax-systems/hapax-council#12) echo "MERGED" ;;
      *) echo "CLOSED" ;;
    esac
    """
)


def _close_check_with_fake_gh(
    note: pathlib.Path,
    bin_dir: pathlib.Path,
    log_path: pathlib.Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """`env` adds variables for the run — used to exercise documented bypasses."""
    extra = env or {}
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["GH_ARGS_LOG"] = str(log_path)
    env.update(extra)
    return subprocess.run(
        ["python3", str(CLOSE_CHECK), str(note), *args],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_close_check_uses_task_pr_repo(tmp_path: pathlib.Path) -> None:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "gh-args.log"
    _fake_gh(bin_dir, CLOSE_FAKE_GH)
    note = _write_task(
        home,
        "active",
        "external-task",
        status="pr_open",
        pr="35",
        pr_repo="ryanklee/hapax-coord",
    )

    result = _close_check_with_fake_gh(note, bin_dir, log_path)

    assert result.returncode == 0, result.stderr
    assert log_path.read_text(encoding="utf-8").strip() == "ryanklee/hapax-coord#35"


def test_close_check_pr_flag_refuses_without_a_repository(tmp_path: pathlib.Path) -> None:
    """WAS `..._defaults_to_council_repo`. The default it asserted is the defect.

    Resolving an absent repository to the council one closed a task meaning reins#6 against a
    merged hapax-council#6 while that PR was still open (2026-08-04, twice). This test named that
    behaviour as the contract, so it changes with the contract rather than being deleted: the same
    invocation must now REFUSE, and say what to add.
    """
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "gh-args.log"
    _fake_gh(bin_dir, CLOSE_FAKE_GH)
    note = _write_task(home, "active", "council-task", status="pr_open", pr="null")

    result = _close_check_with_fake_gh(note, bin_dir, log_path, "--pr", "12")

    assert result.returncode == 2, result.stdout + result.stderr
    assert "no 'pr_repo'" in result.stderr
    assert "--repo" in result.stderr, "a refusal must carry its legal next move"
    assert not log_path.exists() or not log_path.read_text(encoding="utf-8").strip(), (
        "the repository was guessed and gh was queried anyway"
    )


def test_close_check_repo_refusal_has_a_working_bypass(tmp_path: pathlib.Path) -> None:
    """A GATE WITH NO ESCAPE IS A TRAP, and the escape has to be exercised, not just documented.

    Two reviewers noted the new refusal advertises HAPAX_PR_MERGE_GATE_OFF=1 with nothing proving
    it works. An advertised bypass that does not is worse than none: the operator follows the
    instruction, stays blocked, and now distrusts the message as well as the gate.

    The bypass DECLINES TO VERIFY. It does not pick a repository and check against that: guessing
    is the defect this gate exists to prevent, and an escape hatch that reintroduces it is worse
    than none, because the run still looks verified.

    This paragraph described the opposite until a reviewer read it against the code -- it was
    written for an earlier version that fell back to the council repo, and survived the change that
    removed it. Stale prose beside correct code is the same hazard as correct prose beside broken
    code: one of them is lying and the reader cannot tell which.
    """
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "gh-args.log"
    _fake_gh(bin_dir, CLOSE_FAKE_GH)
    note = _write_task(home, "active", "council-task", status="pr_open", pr="null")

    result = _close_check_with_fake_gh(
        note, bin_dir, log_path, "--pr", "12", env={"HAPAX_PR_MERGE_GATE_OFF": "1"}
    )

    assert result.returncode == 0, result.stdout + result.stderr
    # AND IT DOES NOT GUESS A REPOSITORY. An earlier version fell back to the council repo and
    # queried THAT, which is the exact defect this gate exists to prevent, reintroduced inside its
    # own escape hatch — and worse than no bypass, because the run still looked verified. A
    # reviewer caught it. The bypass declines to verify, and says so.
    assert not log_path.exists() or not log_path.read_text(encoding="utf-8").strip(), (
        "the bypass guessed a repository and queried it instead of declining to verify"
    )
    assert "NOT VERIFIED" in result.stderr
    assert "no merge evidence" in result.stderr, (
        "a closure with no verification must say that it has none"
    )


def test_close_check_pr_flag_resolves_when_the_repository_is_named(tmp_path: pathlib.Path) -> None:
    """The other half: naming the repository explicitly still works, via --repo.

    Without this the change above could be satisfied by refusing everything, which is not a gate
    but an outage.
    """
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "gh-args.log"
    _fake_gh(bin_dir, CLOSE_FAKE_GH)
    note = _write_task(home, "active", "council-task", status="pr_open", pr="null")

    result = _close_check_with_fake_gh(
        note, bin_dir, log_path, "--pr", "12", "--repo", "hapax-systems/hapax-council"
    )

    assert result.returncode == 0, result.stderr
    assert log_path.read_text(encoding="utf-8").strip() == "hapax-systems/hapax-council#12"


def test_close_check_refuses_a_malformed_repository_before_touching_the_network(
    tmp_path: pathlib.Path,
) -> None:
    """A TYPO WAS AN UNVERIFIED CLOSURE.

    The gate rejected only nullish values, so "garbage" reached gh; the lookup failed; and the
    failure path read that as "could not verify, allowing". Found in review. Shape is checkable
    without the network, so it is checked before the network — and the lookup-failure path no
    longer allows either.
    """
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "gh-args.log"
    _fake_gh(bin_dir, CLOSE_FAKE_GH)
    note = _write_task(home, "active", "council-task", status="pr_open", pr="null")

    result = _close_check_with_fake_gh(note, bin_dir, log_path, "--pr", "12", "--repo", "garbage")

    assert result.returncode == 2, result.stdout + result.stderr
    assert "malformed" in result.stderr
    assert "owner/name" in result.stderr, "the refusal must show the expected shape"
    assert not log_path.exists() or not log_path.read_text(encoding="utf-8").strip(), (
        "a malformed repository was sent to gh instead of being refused on shape"
    )


def test_close_check_blocks_when_the_pr_cannot_be_verified(tmp_path: pathlib.Path) -> None:
    """`could not verify` IS NOT `verified`.

    This path returned 0 — the same absence-into-zero shape as the repository default, and
    reachable from any transient gh failure. It blocks now, and names the bypass for an operator
    who is genuinely offline.
    """
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "gh-args.log"
    _fake_gh(bin_dir, "#!/usr/bin/env bash\nexit 1\n")
    note = _write_task(home, "active", "council-task", status="pr_open", pr="null")

    result = _close_check_with_fake_gh(
        note, bin_dir, log_path, "--pr", "12", "--repo", "hapax-systems/hapax-council"
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "could not verify" in result.stderr.lower()
    assert "HAPAX_PR_MERGE_GATE_OFF" in result.stderr, "a refusal must carry its legal next move"

    allowed = _close_check_with_fake_gh(
        note,
        bin_dir,
        log_path,
        "--pr",
        "12",
        "--repo",
        "hapax-systems/hapax-council",
        env={"HAPAX_PR_MERGE_GATE_OFF": "1"},
    )
    # rc=0 is the bypass's whole meaning -- "do not gate this" -- so a wrapper reading only the
    # exit code sees a pass. A reviewer flagged that as a hazard and it is one, but encoding
    # "allowed, unverified" as a distinct code would break every existing caller of this gate. The
    # honest mitigation is that stderr says NOT VERIFIED and names the missing evidence, and that
    # an operator had to set the variable deliberately to reach it.
    assert allowed.returncode == 0
    assert "no merge evidence" in allowed.stderr


def test_close_check_no_pr_path_runs_before_the_repository_requirement(
    tmp_path: pathlib.Path,
) -> None:
    """ORDER IS PART OF A GATE'S CORRECTNESS.

    The repository refusal originally ran FIRST, so a task with `pr: null` was blocked for lacking
    a field that has no meaning without a PR -- wedging the legitimate branch/commit evidence flow
    that owns that case. Reordering fixed it and nothing held the order in place; a reviewer asked
    for the regression test, and they were right that a hand-run probe is not one.

    A build task with source mutation, no PR, and a branch must be ALLOWED by this gate, with the
    repository never consulted.
    """
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "gh-args.log"
    _fake_gh(bin_dir, CLOSE_FAKE_GH)
    note = home / "active" / "no-pr-task.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\ntype: cc-task\ntask_id: no-pr-task\nstatus: pr_open\nkind: build\n"
        "mutation_surface: source\nbranch: feat/x\npr: null\n---\n\nbody\n",
        encoding="utf-8",
    )

    result = _close_check_with_fake_gh(note, bin_dir, log_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "pr_repo" not in result.stderr, (
        "the repository requirement ran before the no-PR path and blocked a task that has no PR"
    )
    assert not log_path.exists() or not log_path.read_text(encoding="utf-8").strip()


def test_close_check_no_pr_and_no_evidence_still_blocks(tmp_path: pathlib.Path) -> None:
    """The complement: reordering must not have opened the no-evidence hole it sits beside."""
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "gh-args.log"
    _fake_gh(bin_dir, CLOSE_FAKE_GH)
    note = home / "active" / "no-eviden.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\ntype: cc-task\ntask_id: no-eviden\nstatus: pr_open\nkind: build\n"
        "mutation_surface: source\nbranch: null\npr: null\n---\n\nnothing here\n",
        encoding="utf-8",
    )

    result = _close_check_with_fake_gh(note, bin_dir, log_path)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "no PR, no branch, and no commit" in result.stderr
