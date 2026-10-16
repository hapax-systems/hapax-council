"""Pin the scanner's report-only mode: it changes the exit, never the verdict.

The every-PR CI step that consumes it lands in the follow-up PR (#4844b).
"""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check-billing-surface-diff.py"


def _scan(repo: Path, base: str, *extra: str) -> subprocess.CompletedProcess[str]:
    argv = [sys.executable, str(SCRIPT), "--repo", str(repo), "--base", base, "--head", "HEAD"]
    return subprocess.run([*argv, *extra], capture_output=True, text=True, check=False)


def test_report_only_keeps_the_strict_findings_and_only_changes_the_exit(tmp_path: Path) -> None:
    def git(*args: str) -> str:
        done = subprocess.run(
            ["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True
        )
        return done.stdout.strip()

    git("init", "-q")
    (tmp_path / "app.py").write_text("value = 1\n")
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (tmp_path / "app.py").write_text('client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])\n')
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "head")

    strict = _scan(tmp_path, base)
    report = _scan(tmp_path, base, "--report-only")
    assert strict.returncode == 1 and report.returncode == 0
    assert "REPORT-ONLY: findings" in report.stdout
    for kind in ("api-key-route", "credential-env-read"):
        assert kind in strict.stdout and kind in report.stdout
    assert "OPENAI_API_KEY" not in report.stdout
