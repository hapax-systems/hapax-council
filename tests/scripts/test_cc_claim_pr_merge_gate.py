"""Tests for cc-claim PR merge dependency gate.

Validates that cc-claim blocks dependent task claims when upstream
tasks have unmerged PRs, per REQ-20260509191922.
"""

import pathlib
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cc-claim"


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
    assert "require_route_metadata=True" in py_code


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


def test_pr_gate_uses_current_gh_merge_field():
    """GitHub CLI exposes mergedAt for PR view; merged is not available."""
    py_code = _extract_python(SCRIPT)
    assert '"state,mergedAt"' in py_code
    assert '"state,merged"' not in py_code
    assert ".mergedAt != null" in py_code
