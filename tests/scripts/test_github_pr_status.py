from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import github_pr_status


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(
        self,
        cmd: list[str],
        *,
        cwd: str | None = None,
        capture_output: bool = False,
        text: bool = False,
        check: bool = False,
        timeout: int | None = None,
        **_: Any,
    ) -> subprocess.CompletedProcess:
        self.calls.append(list(cmd))
        if cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6].endswith("/check-runs"):
            payload = {
                "check_runs": [
                    {
                        "name": "lint",
                        "status": "completed",
                        "conclusion": "success",
                        "completed_at": "2026-07-05T15:00:00Z",
                    }
                ]
            }
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        if cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6].endswith("/status"):
            payload = {
                "statuses": [
                    {
                        "context": "legacy-ci",
                        "state": "success",
                        "created_at": "2026-07-05T15:01:00Z",
                    }
                ]
            }
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        if cmd[:3] == ["gh", "api", "rate_limit"]:
            payload = {"resources": {"graphql": {"remaining": 0, "reset": 1893456000}}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        if cmd[:3] == ["gh", "api", "graphql"]:
            return subprocess.CompletedProcess(cmd, 0, '{"data":{}}', "")
        return subprocess.CompletedProcess(cmd, 1, "", "unexpected command")


def test_rest_status_rollup_uses_check_runs_and_statuses(tmp_path: Path) -> None:
    runner = FakeRunner()

    rollup = github_pr_status.fetch_status_check_rollup_rest(
        "abc123",
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
        use_cache=False,
    )

    assert {item.get("name") or item.get("context") for item in rollup} == {
        "lint",
        "legacy-ci",
    }
    assert rollup[0]["status"] == "COMPLETED"
    assert rollup[0]["conclusion"] == "SUCCESS"
    assert rollup[1]["state"] == "SUCCESS"
    assert not any(call[:2] == ["gh", "pr"] for call in runner.calls)


def test_rest_status_rollup_fails_closed_when_status_source_fails(tmp_path: Path) -> None:
    class PartialRunner(FakeRunner):
        def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            if cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6].endswith("/status"):
                self.calls.append(list(cmd))
                return subprocess.CompletedProcess(cmd, 1, "", "status unavailable")
            return super().__call__(cmd, **kwargs)

    runner = PartialRunner()
    old_cache_dir = github_pr_status.DEFAULT_CACHE_DIR
    github_pr_status.DEFAULT_CACHE_DIR = tmp_path / "cache"

    try:
        rollup = github_pr_status.fetch_status_check_rollup_rest(
            "abc123",
            repo="owner/repo",
            repo_root=tmp_path,
            runner=runner,
            use_cache=True,
        )
    finally:
        github_pr_status.DEFAULT_CACHE_DIR = old_cache_dir

    assert rollup == []
    assert not list((tmp_path / "cache").glob("**/*.json"))


def test_rest_status_rollup_fails_closed_when_check_run_source_fails(tmp_path: Path) -> None:
    class PartialRunner(FakeRunner):
        def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            if cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6].endswith("/check-runs"):
                self.calls.append(list(cmd))
                return subprocess.CompletedProcess(cmd, 1, "", "check runs unavailable")
            return super().__call__(cmd, **kwargs)

    runner = PartialRunner()

    rollup = github_pr_status.fetch_status_check_rollup_rest(
        "abc123",
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
        use_cache=False,
    )

    assert rollup == []


def test_review_decision_rest_fails_closed_when_no_reviews(tmp_path: Path) -> None:
    class ReviewRunner(FakeRunner):
        def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            self.calls.append(list(cmd))
            if cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6].endswith("/reviews"):
                return subprocess.CompletedProcess(cmd, 0, json.dumps([]), "")
            return super().__call__(cmd, **kwargs)

    assert (
        github_pr_status.review_decision_rest(
            9,
            repo="owner/repo",
            repo_root=tmp_path,
            runner=ReviewRunner(),
        )
        == "REVIEW_REQUIRED"
    )


def test_review_decision_rest_fails_closed_on_lookup_failure(tmp_path: Path) -> None:
    class ReviewRunner(FakeRunner):
        def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            self.calls.append(list(cmd))
            if cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6].endswith("/reviews"):
                return subprocess.CompletedProcess(cmd, 1, "", "reviews unavailable")
            return super().__call__(cmd, **kwargs)

    assert (
        github_pr_status.review_decision_rest(
            9,
            repo="owner/repo",
            repo_root=tmp_path,
            runner=ReviewRunner(),
        )
        == "REVIEW_REQUIRED"
    )


def test_review_decision_rest_preserves_changes_requested(tmp_path: Path) -> None:
    class ReviewRunner(FakeRunner):
        def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            self.calls.append(list(cmd))
            if cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6].endswith("/reviews"):
                payload = [{"state": "changes_requested", "user": {"login": "reviewer"}}]
                return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
            return super().__call__(cmd, **kwargs)

    assert (
        github_pr_status.review_decision_rest(
            9,
            repo="owner/repo",
            repo_root=tmp_path,
            runner=ReviewRunner(),
        )
        == "CHANGES_REQUESTED"
    )


def test_graphql_backoff_skips_graphql_when_remaining_is_low(tmp_path: Path) -> None:
    runner = FakeRunner()

    proc = github_pr_status.run_graphql_rate_aware(
        ["-f", "query=query { viewer { login } }"],
        repo_root=tmp_path,
        runner=runner,
        min_remaining=10,
    )

    assert proc.returncode == 75
    assert "github_graphql_remaining_below_threshold" in proc.stderr
    assert not any(call[:3] == ["gh", "api", "graphql"] for call in runner.calls)


def test_open_pr_status_snapshot_uses_single_pull_for_merge_state(tmp_path: Path) -> None:
    class SnapshotRunner(FakeRunner):
        def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            self.calls.append(list(cmd))
            if cmd[:5] == ["gh", "api", "--method", "GET", "-H"]:
                path = cmd[6]
                if path == "repos/owner/repo/pulls":
                    return subprocess.CompletedProcess(
                        cmd,
                        0,
                        json.dumps(
                            [
                                {
                                    "number": 9,
                                    "title": "REST PR",
                                    "head": {"ref": "feat/rest", "sha": "abc123"},
                                    "draft": False,
                                    "auto_merge": {"enabled_by": {"login": "bot"}},
                                }
                            ]
                        ),
                        "",
                    )
                if path == "repos/owner/repo/pulls/9":
                    return subprocess.CompletedProcess(
                        cmd,
                        0,
                        json.dumps(
                            {
                                "number": 9,
                                "node_id": "PR_node",
                                "title": "REST PR",
                                "body": "body",
                                "head": {"ref": "feat/rest", "sha": "abc123"},
                                "draft": False,
                                "auto_merge": {"enabled_by": {"login": "bot"}},
                                "mergeable_state": "clean",
                                "changed_files": 1,
                            }
                        ),
                        "",
                    )
                if path == "repos/owner/repo/pulls/9/files":
                    return subprocess.CompletedProcess(
                        cmd, 0, json.dumps([{"filename": "scripts/example.py"}]), ""
                    )
                if path == "repos/owner/repo/pulls/9/reviews":
                    return subprocess.CompletedProcess(
                        cmd,
                        0,
                        json.dumps([{"state": "approved", "user": {"login": "reviewer"}}]),
                        "",
                    )
            return super().__call__(cmd, **kwargs)

    runner = SnapshotRunner()

    rows = github_pr_status.list_open_pr_statuses_rest(
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
        include_files=True,
        include_review_decision=True,
    )

    assert rows[0]["mergeStateStatus"] == "CLEAN"
    assert rows[0]["changedFiles"] == 1
    assert rows[0]["files"] == [{"path": "scripts/example.py"}]
    assert rows[0]["reviewDecision"] == "APPROVED"
    assert not any(call[:2] == ["gh", "pr"] for call in runner.calls)
