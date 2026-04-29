"""Path-coverage tests for ``scripts/hapax-post-merge-deploy``."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-post-merge-deploy"


def _coverage(paths: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), "--report-coverage-stdin"],
        input="\n".join(paths) + "\n",
        text=True,
        capture_output=True,
        check=False,
    )


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _repo_with_merge_commit(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "trace-test@example.test")
    _git(repo, "config", "user.name", "Trace Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    _git(repo, "switch", "-c", "trace-branch")
    script_path = repo / "scripts" / "hapax-demo"
    script_path.parent.mkdir()
    script_path.write_text("#!/bin/sh\necho demo\n", encoding="utf-8")
    _git(repo, "add", "scripts/hapax-demo")
    _git(repo, "commit", "-m", "add deployable script")
    _git(repo, "switch", "main")
    main_script_path = repo / "scripts" / "hapax-main-only"
    main_script_path.parent.mkdir(exist_ok=True)
    main_script_path.write_text("#!/bin/sh\necho main\n", encoding="utf-8")
    _git(repo, "add", "scripts/hapax-main-only")
    _git(repo, "commit", "-m", "add main-only deployable script")
    _git(repo, "merge", "--no-ff", "trace-branch", "-m", "merge trace branch")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_dry_run_writes_bounded_post_merge_trace(tmp_path: Path) -> None:
    repo, sha = _repo_with_merge_commit(tmp_path)
    trace_path = tmp_path / "traces" / "post-merge-traces.jsonl"
    env = {
        **os.environ,
        "REPO": str(repo),
        "HAPAX_POST_MERGE_TRACE_PATH": str(trace_path),
        "HAPAX_POST_MERGE_TRACE_MAX_RECORDS": "2",
    }

    for _ in range(3):
        result = subprocess.run(
            [str(SCRIPT), "--dry-run", sha],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        assert result.returncode == 0, result.stderr
        assert "dry-run: post-merge deploy trace written" in result.stdout

    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]

    assert len(records) == 2
    assert records[-1]["event"] == "post_merge_deploy"
    assert records[-1]["sha"] == sha
    assert records[-1]["mode"] == "dry_run"
    assert records[-1]["status"] == "dry_run"
    assert records[-1]["changed_files"] == ["scripts/hapax-demo"]
    assert records[-1]["deploy_groups"]["hapax_scripts"] == ["scripts/hapax-demo"]
    assert records[-1]["manual_deploy_needed"] is True
    assert records[-1]["manual_deploy_executed"] is False


def test_systemd_coverage_includes_dropins_presets_and_source_overrides() -> None:
    result = _coverage(
        [
            "systemd/units/hapax-datacite-mirror.service",
            "systemd/units/hapax-datacite-mirror.timer",
            "systemd/units/pipewire.service.d/cpu-affinity.conf",
            "systemd/user-preset.d/hapax.preset",
            "systemd/overrides/audio-stability/README.md",
            "systemd/overrides/audio-stability/pipewire-cpu-affinity.conf",
            "systemd/watchdogs/scout-watchdog",
            "systemd/README.md",
            "systemd/expected-timers.yaml",
        ]
    )

    assert result.returncode == 0, result.stderr
    assert "ok: all systemd/** paths" in result.stdout


def test_systemd_coverage_still_flags_unknown_systemd_paths() -> None:
    result = _coverage(["systemd/uncovered/example.conf"])

    assert result.returncode == 1
    assert "systemd/uncovered/example.conf" in result.stderr


def test_deploy_rejects_commit_ranges_before_touching_targets() -> None:
    result = subprocess.run(
        [str(SCRIPT), "HEAD..HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "expected a single commit SHA/ref" in result.stderr


def test_coverage_rejects_commit_ranges_before_touching_targets() -> None:
    result = subprocess.run(
        [str(SCRIPT), "--report-coverage", "HEAD..HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "expected a single commit SHA/ref" in result.stderr
