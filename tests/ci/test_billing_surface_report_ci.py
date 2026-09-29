"""Pin the report-only PR consumer of the billing surface scanner."""

import os
import shutil
import subprocess
from pathlib import Path

import yaml

CI = Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"


def test_billing_scan_reports_every_pr_without_blocking_all_green() -> None:
    jobs = yaml.safe_load(CI.read_text())["jobs"]
    lint = jobs["lint"]
    assert "lint" in jobs["all-green"]["needs"]

    checkout = next(step for step in lint["steps"] if "actions/checkout" in step.get("uses", ""))
    assert "github.event_name == 'pull_request'" in checkout["if"]
    assert checkout["with"]["fetch-depth"] == 0
    scan = next(step for step in lint["steps"] if step.get("name") == "Report billing surface scan")
    assert scan["if"] == "github.event_name == 'pull_request'"
    assert scan["continue-on-error"] is True
    assert scan["env"]["PR_BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"
    assert scan["env"]["PR_HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"
    body = scan["run"]
    assert (
        'python3 scripts/check-billing-surface-diff.py --report-only --base "$PR_BASE_SHA" --head "$PR_HEAD_SHA"'
        in body
    )
    assert 'cat "$report"' in body
    assert "GITHUB_STEP_SUMMARY" in body
    assert "exit 0" in body


def test_report_step_records_a_finding_and_succeeds(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    for name in (
        "__init__.py",
        "check-billing-surface-diff.py",
        "billing_surface_detector.py",
        "billing_surface_input.py",
    ):
        shutil.copy2(CI.parents[2] / "scripts" / name, scripts / name)

    def git(*args: str) -> str:
        done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
        return done.stdout.strip()

    git("init", "-q")
    (repo / "app.py").write_text("value = 1\n")
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (repo / "app.py").write_text('client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])\n')
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "head")
    head = git("rev-parse", "HEAD")

    steps = yaml.safe_load(CI.read_text())["jobs"]["lint"]["steps"]
    body = next(step["run"] for step in steps if step.get("name") == "Report billing surface scan")
    summary = tmp_path / "summary.md"
    env = {
        **os.environ,
        "PR_BASE_SHA": base,
        "PR_HEAD_SHA": head,
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    run = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", body],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    for output in (run.stdout, summary.read_text()):
        assert "REPORT-ONLY: findings" in output
        assert "api-key-route" in output
        assert "OPENAI_API_KEY" not in output
