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
    env["HOME"] = str(home)
    env["HAPAX_AGENT_ROLE"] = "cx-test"
    env["HAPAX_SESSION_ID"] = "0f9f9f9f-1111-2222-3333-444455556666"
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["GH_ARGS_LOG"] = str(log_path)
    return subprocess.run(
        [
            "bash",
            str(SCRIPT),
            task_id,
            "--dispatch-message-id",
            "message-a",
            "--dispatch-binding-hash",
            "a" * 64,
            "--dispatch-platform",
            "codex",
            "--dispatch-mode",
            "headless",
            "--dispatch-profile",
            "full",
            "--dispatch-authority-case",
            "CASE-TEST-001",
        ],
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

    assert result.returncode == 8, result.stderr
    assert "unadmitted_claim_publication_forbidden" in result.stderr
    assert "status: offered" in note.read_text(encoding="utf-8")
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

    assert result.returncode == 8, result.stderr
    assert "unadmitted_claim_publication_forbidden" in result.stderr
    assert "status: offered" in note.read_text(encoding="utf-8")
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
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["GH_ARGS_LOG"] = str(log_path)
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


def test_close_check_pr_flag_defaults_to_council_repo(tmp_path: pathlib.Path) -> None:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "gh-args.log"
    _fake_gh(bin_dir, CLOSE_FAKE_GH)
    note = _write_task(home, "active", "council-task", status="pr_open", pr="null")

    result = _close_check_with_fake_gh(note, bin_dir, log_path, "--pr", "12")

    assert result.returncode == 0, result.stderr
    assert log_path.read_text(encoding="utf-8").strip() == "hapax-systems/hapax-council#12"
