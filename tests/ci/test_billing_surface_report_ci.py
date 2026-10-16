"""Pin the gate invocation a CI consumer runs: strict, on the diff git generates itself.

The every-PR CI step (and the advisory report-only mode) land in the follow-up PR (#4844b).
"""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check-billing-surface-diff.py"


def test_the_strict_gate_fails_a_billing_surface_from_base_and_head(tmp_path: Path) -> None:
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

    argv = [sys.executable, str(SCRIPT), "--repo", str(tmp_path), "--base", base, "--head", "HEAD"]
    strict = subprocess.run(argv, capture_output=True, text=True, check=False)
    assert strict.returncode == 1, strict.stdout + strict.stderr
    for kind in ("api-key-route", "credential-env-read"):
        assert kind in strict.stdout
