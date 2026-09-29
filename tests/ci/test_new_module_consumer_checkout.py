"""Regression tests for the consumer gate's Git history and entrypoint boundary."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import yaml

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check-new-module-consumers.py"
WORKFLOW = SCRIPT.parents[1] / ".github" / "workflows" / "ci.yml"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()


def test_unfetched_base_in_depth_one_clone_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-q")
    _git(source, "config", "user.name", "test")
    _git(source, "config", "user.email", "test@example.invalid")
    (source / "README.md").write_text("base\n")
    _git(source, "add", ".")
    _git(source, "commit", "-qm", "base")
    base = _git(source, "rev-parse", "HEAD")
    (source / "shared").mkdir()
    (source / "shared" / "new_module.py").write_text("VALUE = 1\n")
    _git(source, "add", ".")
    _git(source, "commit", "-qm", "feature")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--depth", "1", source.as_uri(), str(clone)], check=True)
    assert _git(clone, "rev-parse", "--is-shallow-repository") == "true"
    assert (
        subprocess.run(["git", "-C", str(clone), "cat-file", "-e", base], check=False).returncode
        != 0
    )

    result = subprocess.run(
        ["python", str(SCRIPT), "--base-ref", base], cwd=clone, capture_output=True, text=True
    )

    assert result.returncode == 2
    assert "Git diff failed" in result.stderr
    assert "No new module files to check" not in result.stdout

    _git(clone, "fetch", "--unshallow", "origin")
    with_history = subprocess.run(
        ["python", str(SCRIPT), "--base-ref", base], cwd=clone, capture_output=True, text=True
    )
    assert with_history.returncode == 1
    assert "shared/new_module.py" in with_history.stdout


def test_script_entrypoint_needs_declared_execution_or_allowlist(
    tmp_path: Path, monkeypatch
) -> None:
    spec = importlib.util.spec_from_file_location("consumer_gate_checkout_test", SCRIPT)
    assert spec and spec.loader
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "scripts" / "demo_entry.py"
    script.parent.mkdir()
    script.write_text('if __name__ == "__main__":\n    print("demo")\n')
    monkeypatch.setattr(gate, "git_diff_added_files", lambda args: [Path("scripts/demo_entry.py")])

    assert gate.main([]) == 1
    workflow = tmp_path / ".github" / "workflows" / "demo.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("steps:\n  - run: python scripts/demo_entry.py\n")
    assert gate.main([]) == 0


def test_lint_checkout_supplies_history_and_does_not_ignore_fetch_failure() -> None:
    lint_steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["lint"]["steps"]
    checkout = next(step for step in lint_steps if "actions/checkout@" in step.get("uses", ""))
    gate = next(step for step in lint_steps if step.get("name") == "new-module-consumer-check")

    assert checkout["with"]["fetch-depth"] == 0
    assert gate["env"]["MERGE_GROUP_BASE_SHA"] == "${{ github.event.merge_group.base_sha }}"
    assert "git fetch" in gate["run"]
    assert '"$MERGE_GROUP_BASE_SHA..HEAD"' in gate["run"]
    assert "|| true" not in gate["run"]
    assert "skipping new-module-consumer-check" not in gate["run"]
