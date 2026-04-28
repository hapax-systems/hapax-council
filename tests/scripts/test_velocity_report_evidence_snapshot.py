from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from scripts.velocity_report_evidence_snapshot import (
    _frontmatter_value,
    count_refusal_tasks,
    measure_repo_window,
)


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env)


def test_frontmatter_value_reads_simple_scalar() -> None:
    text = "---\nstatus: refused\nautomation_status: REFUSED\n---\nBody\n"
    assert _frontmatter_value(text, "status") == "refused"
    assert _frontmatter_value(text, "automation_status") == "REFUSED"


def test_measure_repo_window_counts_commits_and_churn(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.org")
    _git(repo, "config", "user.name", "Test")

    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2026-04-25T12:00:00-05:00",
        "GIT_COMMITTER_DATE": "2026-04-25T12:00:00-05:00",
    }
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    _git(repo, "add", ".", env=env)
    _git(repo, "commit", "-q", "-m", "first", env=env)
    (repo / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "second", env=env)

    result = measure_repo_window(
        repo,
        since="2026-04-25T00:00:00-05:00",
        until="2026-04-25T18:00:00-05:00",
        all_refs=False,
    )

    assert result.commits == 2
    assert result.additions >= 2
    assert result.churn >= result.additions
    assert len(result.commit_shas) == 2


def test_count_refusal_tasks_reports_multiple_refusal_shapes(tmp_path: Path) -> None:
    closed = tmp_path / "closed"
    refused = tmp_path / "refused"
    closed.mkdir()
    refused.mkdir()
    (closed / "a.md").write_text("---\nstatus: done\n---\nBody\n", encoding="utf-8")
    (closed / "b.md").write_text(
        "---\nstatus: done\nautomation_status: REFUSED\n---\nBody\n",
        encoding="utf-8",
    )
    (refused / "c.md").write_text("---\nstatus: refused\n---\nBody\n", encoding="utf-8")

    result = count_refusal_tasks(tmp_path)

    assert result["total_task_files"] == 3
    assert result["status_refused"] == 1
    assert result["automation_status_refused"] == 1
    assert result["refusal_like_unique"] == 2


def test_snapshot_output_is_json_serializable(tmp_path: Path) -> None:
    output = tmp_path / "snapshot.json"
    payload = {"schema_version": 1, "windows": {}}
    output.write_text(json.dumps(payload), encoding="utf-8")
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == 1
