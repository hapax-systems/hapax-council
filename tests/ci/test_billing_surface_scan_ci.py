"""The billing evidence producer: YAML contract and execution in scratch git repos."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CHECK = "billing-surface-scan"
DUPLICATE = "needs.post_merge_duplicate_filter.outputs.duplicate_merge_group"


def _ci():
    return yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())


def _scan_step():
    return next(s for s in _ci()["jobs"][CHECK]["steps"] if s.get("env", {}).get("PR_BASE"))


def test_billing_ci_evidence_contract():
    ci = _ci()
    assert {"pull_request", "merge_group", "push"} <= set(ci.get("on", ci.get(True)))
    job = ci["jobs"][CHECK]
    assert "if" not in job and job.get("name", CHECK) == CHECK
    assert job["needs"] == ["post_merge_duplicate_filter"]
    assert CHECK not in ci["jobs"]["all-green"]["needs"]
    sentinel, *steps = job["steps"]
    assert sentinel["if"] == f"{DUPLICATE} == 'true'"
    assert "success" in sentinel["run"]
    result = subprocess.run(["bash", "-c", sentinel["run"]], capture_output=True, text=True)
    assert result.returncode == 0 and "success" in result.stdout
    assert all(s["if"] == f"{DUPLICATE} != 'true'" for s in steps)
    checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["fetch-depth"] == 0
    step = _scan_step()
    assert step["env"] == {
        "PR_BASE": "${{ github.event.pull_request.base.sha || github.event.merge_group.base_sha || github.event.before }}",
        "PR_HEAD": "${{ github.event.pull_request.head.sha || github.event.merge_group.head_sha || github.sha }}",
    }
    assert '--base "$base" --head "$PR_HEAD"' in step["run"]
    assert "--diff-file" not in step["run"]


def _git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def _commit(repo):
    _git(repo, "add", "app.py")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "fixture")
    return _git(repo, "rev-parse", "HEAD")


@pytest.mark.parametrize(
    "case", ["clean", "credential", "empty", "missing", "fallback", "zero", "root"]
)
def test_billing_ci_shell_executes_git_owned_scan(tmp_path, case):
    _git(tmp_path, "init", "-q")
    app = tmp_path / "app.py"
    app.write_text("value = 1\n")
    base = head = _commit(tmp_path)
    if case != "root":
        # Synthetic credential-read fixture, never a credential value.
        app.write_text(
            'key = os.environ["OPENAI_API_KEY"]\n'  # billing-scan:allow
            if case == "credential"
            else "value = 2\n"
        )
        head = _commit(tmp_path)
    if case == "empty":
        base = head
    elif case == "missing":
        base = "not-a-revision"
    elif case in {"fallback", "root"}:
        base = ""
    elif case == "zero":
        base = "0" * 40
    # Run the YAML shell unchanged, including uv and the actual scanner. Only the scratch
    # repo's untracked scripts binding points back to the candidate implementation.
    (tmp_path / "scripts").symlink_to(ROOT / "scripts", target_is_directory=True)
    env = {
        **os.environ,
        "PR_BASE": base,
        "PR_HEAD": head,
        "UV_OFFLINE": "1",
        "UV_PYTHON": sys.executable,
    }
    result = subprocess.run(
        ["bash", "-c", _scan_step()["run"]],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    expected = 1 if case == "credential" else 2 if case in {"empty", "missing", "root"} else 0
    assert result.returncode == expected, result.stdout + result.stderr
    if case == "credential":
        assert "credential-env-read" in result.stdout
    elif expected == 0:
        assert "billing-surface-scan: OK" in result.stdout
    else:
        assert "FAIL-CLOSED" in result.stderr and "Next action:" in result.stderr
