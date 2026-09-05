from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import github_pr_status


def _api_fields(cmd: list[str]) -> dict[str, str]:
    return {
        cmd[index + 1].split("=", 1)[0]: cmd[index + 1].split("=", 1)[1]
        for index, token in enumerate(cmd[:-1])
        if token == "-f" and "=" in cmd[index + 1]
    }


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
        if cmd[:4] == ["gh", "api", "-i", "rate_limit"]:
            # `-i` so the rate probe reads RESPONSE HEADERS, which are what the API
            # actually enforces. Measured 2026-08-29: the body reported
            # `core: 4996/5000 remaining` while a real call returned 403 with
            # `X-Ratelimit-Remaining: 0` for that same bucket.
            payload = {
                "resources": {
                    "core": {"remaining": 4000, "limit": 5000, "reset": 1893456000},
                    "graphql": {"remaining": 0, "limit": 5000, "reset": 1893456000},
                }
            }
            head = (
                "HTTP/2.0 200 OK\r\n"
                "X-Ratelimit-Limit: 5000\r\n"
                "X-Ratelimit-Remaining: 4000\r\n"
                "X-Ratelimit-Reset: 1893456000\r\n"
                "X-Ratelimit-Resource: core\r\n"
            )
            return subprocess.CompletedProcess(cmd, 0, f"{head}\r\n{json.dumps(payload)}", "")
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


def test_rest_status_rollup_paginates_check_runs(tmp_path: Path) -> None:
    class PaginatedRunner(FakeRunner):
        def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            self.calls.append(list(cmd))
            if cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6].endswith("/check-runs"):
                fields = _api_fields(cmd)
                page = int(fields.get("page", "1"))
                if page == 1:
                    payload = {
                        "total_count": 101,
                        "check_runs": [
                            {
                                "name": f"check-{index}",
                                "status": "completed",
                                "conclusion": "success",
                            }
                            for index in range(100)
                        ],
                    }
                    return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
                payload = {
                    "total_count": 101,
                    "check_runs": [
                        {
                            "name": "late-failure",
                            "status": "completed",
                            "conclusion": "failure",
                        }
                    ],
                }
                return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
            if cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6].endswith("/status"):
                return subprocess.CompletedProcess(cmd, 0, json.dumps({"statuses": []}), "")
            return subprocess.CompletedProcess(cmd, 1, "", "unexpected command")

    runner = PaginatedRunner()

    rollup = github_pr_status.fetch_status_check_rollup_rest(
        "abc123",
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
        use_cache=False,
    )

    assert len(rollup) == 101
    assert any(item.get("name") == "late-failure" for item in rollup)
    assert any("page=2" in call for call in runner.calls for call in call)


def test_rest_status_rollup_paginates_combined_statuses(tmp_path: Path) -> None:
    class PaginatedStatusRunner(FakeRunner):
        def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            self.calls.append(list(cmd))
            if cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6].endswith("/check-runs"):
                return subprocess.CompletedProcess(
                    cmd, 0, json.dumps({"total_count": 0, "check_runs": []}), ""
                )
            if cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6].endswith("/status"):
                page = int(_api_fields(cmd).get("page", "1"))
                if page == 1:
                    payload = {
                        "total_count": 101,
                        "statuses": [
                            {
                                "context": f"legacy-{index}",
                                "state": "success",
                            }
                            for index in range(100)
                        ],
                    }
                    return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
                payload = {
                    "total_count": 101,
                    "statuses": [
                        {
                            "context": "late-legacy-failure",
                            "state": "failure",
                        }
                    ],
                }
                return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
            return subprocess.CompletedProcess(cmd, 1, "", "unexpected command")

    runner = PaginatedStatusRunner()

    rollup = github_pr_status.fetch_status_check_rollup_rest(
        "abc123",
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
        use_cache=False,
    )

    assert len(rollup) == 101
    assert any(
        item.get("context") == "late-legacy-failure" and item.get("state") == "FAILURE"
        for item in rollup
    )
    assert any("page=2" in call for call in runner.calls for call in call)


def test_rest_status_rollup_cache_round_trips(tmp_path: Path, monkeypatch: Any) -> None:
    runner = FakeRunner()
    old_cache_dir = github_pr_status.DEFAULT_CACHE_DIR
    github_pr_status.DEFAULT_CACHE_DIR = tmp_path / "cache"
    monkeypatch.setenv("HAPAX_GITHUB_PR_STATUS_CACHE_TTL_SECONDS", "60")

    try:
        rollup = github_pr_status.fetch_status_check_rollup_rest(
            "abc123",
            repo="owner/repo",
            repo_root=tmp_path,
            runner=runner,
            use_cache=True,
        )

        class FailingRunner(FakeRunner):
            def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
                self.calls.append(list(cmd))
                return subprocess.CompletedProcess(cmd, 1, "", "cache was missed")

        cached_runner = FailingRunner()
        cached = github_pr_status.fetch_status_check_rollup_rest(
            "abc123",
            repo="owner/repo",
            repo_root=tmp_path,
            runner=cached_runner,
            use_cache=True,
        )
    finally:
        github_pr_status.DEFAULT_CACHE_DIR = old_cache_dir

    assert cached == rollup
    assert cached_runner.calls == []


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

    assert rollup == [
        {
            "name": github_pr_status.REST_INDETERMINATE_CHECK_NAME,
            "status": "PENDING",
            "conclusion": None,
            "details": "combined_status_rest_indeterminate",
        }
    ]
    assert not list((tmp_path / "cache").glob("**/*.json"))


def test_rest_status_rollup_fails_closed_when_status_pagination_fails(tmp_path: Path) -> None:
    class PartialStatusRunner(FakeRunner):
        def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            self.calls.append(list(cmd))
            if cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6].endswith("/check-runs"):
                return subprocess.CompletedProcess(
                    cmd, 0, json.dumps({"total_count": 0, "check_runs": []}), ""
                )
            if cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6].endswith("/status"):
                page = int(_api_fields(cmd).get("page", "1"))
                if page == 1:
                    payload = {
                        "total_count": 101,
                        "statuses": [
                            {
                                "context": f"legacy-{index}",
                                "state": "success",
                            }
                            for index in range(100)
                        ],
                    }
                    return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
                return subprocess.CompletedProcess(cmd, 1, "", "status page unavailable")
            return subprocess.CompletedProcess(cmd, 1, "", "unexpected command")

    runner = PartialStatusRunner()

    rollup = github_pr_status.fetch_status_check_rollup_rest(
        "abc123",
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
        use_cache=False,
    )

    assert rollup == [
        {
            "name": github_pr_status.REST_INDETERMINATE_CHECK_NAME,
            "status": "PENDING",
            "conclusion": None,
            "details": "combined_status_rest_indeterminate",
        }
    ]
    assert any("page=2" in call for call in runner.calls for call in call)


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

    assert rollup == [
        {
            "name": github_pr_status.REST_INDETERMINATE_CHECK_NAME,
            "status": "PENDING",
            "conclusion": None,
            "details": "check_runs_rest_indeterminate",
        }
    ]


def test_review_decision_rest_returns_unknown_when_no_reviews(tmp_path: Path) -> None:
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
        is None
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


def test_review_decision_rest_dismissed_review_revokes_approval(tmp_path: Path) -> None:
    class ReviewRunner(FakeRunner):
        def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            self.calls.append(list(cmd))
            if cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6].endswith("/reviews"):
                payload = [
                    {"state": "approved", "user": {"login": "reviewer"}},
                    {"state": "dismissed", "user": {"login": "reviewer"}},
                ]
                return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
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


def test_review_decision_rest_paginates_late_dismissed_review(tmp_path: Path) -> None:
    class ReviewRunner(FakeRunner):
        def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            self.calls.append(list(cmd))
            if cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6].endswith("/reviews"):
                fields = {
                    cmd[index + 1].split("=", 1)[0]: cmd[index + 1].split("=", 1)[1]
                    for index, token in enumerate(cmd[:-1])
                    if token == "-f" and "=" in cmd[index + 1]
                }
                page = int(fields.get("page", "1"))
                if page == 1:
                    payload = [
                        {"state": "commented", "user": {"login": f"reviewer-{index}"}}
                        for index in range(99)
                    ]
                    payload.append({"state": "approved", "user": {"login": "reviewer"}})
                    return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
                if page == 2:
                    payload = [{"state": "dismissed", "user": {"login": "reviewer"}}]
                    return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
            return super().__call__(cmd, **kwargs)

    runner = ReviewRunner()

    assert (
        github_pr_status.review_decision_rest(
            9,
            repo="owner/repo",
            repo_root=tmp_path,
            runner=runner,
        )
        == "REVIEW_REQUIRED"
    )
    assert any("page=2" in call for call in runner.calls for call in call)


def test_review_decision_rest_fails_closed_at_review_page_boundary(tmp_path: Path) -> None:
    class ReviewRunner(FakeRunner):
        def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            self.calls.append(list(cmd))
            if cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6].endswith("/reviews"):
                payload = [
                    {"state": "approved", "user": {"login": f"reviewer-{index}"}}
                    for index in range(100)
                ]
                return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
            return super().__call__(cmd, **kwargs)

    assert (
        github_pr_status.review_decision_rest(
            9,
            repo="owner/repo",
            repo_root=tmp_path,
            runner=ReviewRunner(),
            limit=100,
        )
        == "REVIEW_REQUIRED"
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
                                    "state": "open",
                                    "merged_at": None,
                                    "updated_at": "2026-07-05T15:00:00Z",
                                    "html_url": "https://github.example/owner/repo/pull/9",
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
                                "state": "open",
                                "merged_at": None,
                                "updated_at": "2026-07-05T15:00:00Z",
                                "html_url": "https://github.example/owner/repo/pull/9",
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
    assert rows[0]["state"] == "OPEN"
    assert rows[0]["mergedAt"] is None
    assert rows[0]["updatedAt"] == "2026-07-05T15:00:00Z"
    assert rows[0]["url"] == "https://github.example/owner/repo/pull/9"
    assert rows[0]["changedFiles"] == 1
    assert rows[0]["files"] == [{"path": "scripts/example.py"}]
    assert rows[0]["reviewDecision"] == "APPROVED"
    assert not any(call[:2] == ["gh", "pr"] for call in runner.calls)


def test_open_pr_status_snapshot_does_not_hydrate_list_rows_by_default(tmp_path: Path) -> None:
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
                                    "node_id": "PR_node",
                                    "title": "REST PR",
                                    "body": "body",
                                    "head": {"ref": "feat/rest", "sha": "abc123"},
                                    "draft": True,
                                    "state": "open",
                                    "merged_at": None,
                                    "updated_at": "2026-07-05T15:00:00Z",
                                    "html_url": "https://github.example/owner/repo/pull/9",
                                    "auto_merge": None,
                                    "changed_files": 1,
                                }
                            ]
                        ),
                        "",
                    )
            return super().__call__(cmd, **kwargs)

    runner = SnapshotRunner()

    rows = github_pr_status.list_open_pr_statuses_rest(
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
        include_status=False,
    )

    assert rows[0]["state"] == "OPEN"
    assert rows[0]["isDraft"] is True
    assert rows[0]["mergedAt"] is None
    assert rows[0]["updatedAt"] == "2026-07-05T15:00:00Z"
    assert rows[0]["url"] == "https://github.example/owner/repo/pull/9"
    # Length-guarded: the rate probe (`gh api -i rate_limit`) is a 4-element call, so an
    # unguarded call[6] raises IndexError rather than reporting the property under test.
    assert not any(len(call) > 6 and call[6] == "repos/owner/repo/pulls/9" for call in runner.calls)


def test_open_pr_status_snapshot_hydrates_list_rows_when_requested(tmp_path: Path) -> None:
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
                                    "state": "open",
                                    "updated_at": "2026-07-05T15:00:00Z",
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
                                "title": "REST PR",
                                "head": {"ref": "feat/rest", "sha": "abc123"},
                                "draft": False,
                                "state": "open",
                                "updated_at": "2026-07-05T15:00:00Z",
                                "mergeable_state": "behind",
                            }
                        ),
                        "",
                    )
            return super().__call__(cmd, **kwargs)

    runner = SnapshotRunner()

    rows = github_pr_status.list_open_pr_statuses_rest(
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
        include_status=False,
        hydrate_pull=True,
    )

    assert rows[0]["mergeStateStatus"] == "BEHIND"
    assert any(len(call) > 6 and call[6] == "repos/owner/repo/pulls/9" for call in runner.calls)


# --------------------------------------------------------------- rate pool balancing
#
# Context: PR #4436 moved PR status polling from GraphQL onto REST to escape a GraphQL rate
# limit, but the guard stayed on GraphQL. Measured 2026-08-29: core 0/5000 exhausted while
# graphql held 4660/5000 — the estate protected the pool it had stopped using.


def _rate_runner(
    *,
    header_remaining: int | None,
    body_core: int,
    body_graphql: int,
    limit: int = 5000,
) -> Any:
    """A runner whose header and body figures can be made to disagree on purpose."""

    def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:4] == ["gh", "api", "-i", "rate_limit"]:
            payload = {
                "resources": {
                    "core": {"remaining": body_core, "limit": limit, "reset": 1893456000},
                    "graphql": {
                        "remaining": body_graphql,
                        "limit": limit,
                        "reset": 1893456000,
                    },
                }
            }
            head = "HTTP/2.0 200 OK\r\n"
            if header_remaining is not None:
                head += (
                    f"X-Ratelimit-Limit: {limit}\r\n"
                    f"X-Ratelimit-Remaining: {header_remaining}\r\n"
                    "X-Ratelimit-Reset: 1893456000\r\n"
                    "X-Ratelimit-Resource: core\r\n"
                )
            return subprocess.CompletedProcess(cmd, 0, f"{head}\r\n{json.dumps(payload)}", "")
        return subprocess.CompletedProcess(cmd, 1, "", "unexpected command")

    return run


def test_core_headroom_prefers_headers_over_the_body(tmp_path: Path) -> None:
    """The measured disagreement, pinned.

    The endpoint body reported core 4996/5000 remaining at the same moment a real call
    returned 403 with X-Ratelimit-Remaining: 0. A guard trusting the body would have
    concluded there was headroom and spent a call straight into a 403.
    """
    snapshot = github_pr_status.rate_snapshot(
        repo_root=tmp_path,
        runner=_rate_runner(header_remaining=0, body_core=4996, body_graphql=4660),
    )

    assert snapshot.core is not None
    assert snapshot.core.remaining == 0
    assert snapshot.core.source == "header"


def test_disagreement_resolves_pessimistically(tmp_path: Path) -> None:
    """Over-reporting exhaustion costs a reroute; under-reporting spends into a 403."""
    snapshot = github_pr_status.rate_snapshot(
        repo_root=tmp_path,
        runner=_rate_runner(header_remaining=4500, body_core=10, body_graphql=4660),
    )

    assert snapshot.core is not None
    assert snapshot.core.remaining == 10, "the stricter of the two sources must win"
    assert snapshot.core.source == "body", (
        "provenance must follow the winning figure — labelling this 'header' would "
        "claim authoritative evidence for a body-derived number, in the exact case "
        "the two sources disagree"
    )


def test_header_wins_and_keeps_its_authoritative_label(tmp_path: Path) -> None:
    """The converse of the pessimistic merge: when the header is stricter, it is also the label.

    Pinned separately because a fix that always said "body" would satisfy the
    disagreement test above while destroying the provenance distinction entirely.
    """
    snapshot = github_pr_status.rate_snapshot(
        repo_root=tmp_path,
        runner=_rate_runner(header_remaining=7, body_core=4000, body_graphql=4660),
    )

    assert snapshot.core is not None
    assert snapshot.core.remaining == 7, "the stricter of the two sources must win"
    assert snapshot.core.source == "header"


def test_rest_floor_is_enforced_by_the_single_decision_point(tmp_path: Path) -> None:
    """REST exhaustion is guarded once, inside choose_transport.

    An earlier draft added a `rest_backoff()` twin of `graphql_backoff`. That would have been
    a second mitigation for the same hazard — two guards that can disagree about one pool —
    so it was removed rather than given a caller. This pins the floor at the one place it
    lives, using the default rather than an explicit override.
    """
    transport, reason = github_pr_status.choose_transport(
        repo_root=tmp_path,
        runner=_rate_runner(header_remaining=3, body_core=3, body_graphql=4660),
    )

    assert transport == "graphql"
    assert f"<{github_pr_status.DEFAULT_REST_MIN_REMAINING}" in reason


def test_exhausted_rest_routes_to_graphql(tmp_path: Path) -> None:
    """The whole point: divert BEFORE spending, not after failing."""
    transport, reason = github_pr_status.choose_transport(
        repo_root=tmp_path,
        runner=_rate_runner(header_remaining=0, body_core=0, body_graphql=4660),
    )

    assert transport == "graphql"
    assert "github_rest_below_floor" in reason


def test_both_pools_exhausted_returns_no_transport(tmp_path: Path) -> None:
    """Neither pool is spendable; callers must refuse rather than pick a doomed one."""
    transport, reason = github_pr_status.choose_transport(
        repo_root=tmp_path,
        runner=_rate_runner(header_remaining=0, body_core=0, body_graphql=0),
    )

    assert transport is None
    assert "github_both_pools_below_floor" in reason


def test_healthy_pools_send_work_to_the_roomier_one(tmp_path: Path) -> None:
    """Balancing, not merely failover: the pools should drain together."""
    transport, _ = github_pr_status.choose_transport(
        repo_root=tmp_path,
        runner=_rate_runner(header_remaining=1000, body_core=1000, body_graphql=4900),
    )

    assert transport == "graphql"


def test_rest_wins_ties_preserving_post_4436_behaviour(tmp_path: Path) -> None:
    """This change only ever diverts away from a pool measured to be in trouble."""
    transport, _ = github_pr_status.choose_transport(
        repo_root=tmp_path,
        runner=_rate_runner(header_remaining=4000, body_core=4000, body_graphql=4000),
    )

    assert transport == "rest"


def test_lookup_failure_fails_open_to_rest(tmp_path: Path) -> None:
    """A network or auth hiccup must not be mistaken for confirmed exhaustion.

    Preserves the contract graphql_backoff already documented, now applied to routing:
    unknown headroom is not evidence of an empty pool.
    """

    def failing(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(cmd, 1, "", "network down")

    snapshot = github_pr_status.rate_snapshot(repo_root=tmp_path, runner=failing)
    assert snapshot.core is None and snapshot.graphql is None

    transport, _ = github_pr_status.choose_transport(repo_root=tmp_path, runner=failing)
    assert transport == "rest"

    assert github_pr_status.graphql_backoff(repo_root=tmp_path, runner=failing) is None


def test_rate_subcommand_reports_pools_and_exits_nonzero_when_both_are_empty(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    """The diagnostic that would have made the 2026-08-29 diagnosis instant.

    `gh auth status` claimed the token was invalid (it was not — the pool was empty) and
    `gh api rate_limit` reported core headroom a real call contradicted. This subcommand
    prints what actually governs, per pool, with provenance — and is `choose_transport`'s
    static call path, so the routing primitive does not ship as whitelisted dead code.
    """
    monkeypatch.setattr(
        github_pr_status.subprocess,
        "run",
        _rate_runner(header_remaining=0, body_core=0, body_graphql=0),
    )

    rc = github_pr_status.main(["rate", "--repo-root", str(tmp_path)])
    payload = json.loads(capsys.readouterr().out)

    assert rc == github_pr_status.GRAPHQL_BACKOFF_RC, "both pools empty must exit non-zero"
    assert payload["transport"] is None
    assert "github_both_pools_below_floor" in payload["reason"]
    assert payload["core"]["source"] == "header"
    assert payload["graphql"]["source"] == "body", "body-sourced figures say so"


def test_a_403_with_rate_headers_is_a_measurement_of_exhaustion(tmp_path: Path) -> None:
    """Authoritative headers survive a nonzero exit; the body does not.

    Replaces an earlier test that asserted the opposite and **codified a regression**
    (review finding codex-1, major). A 403 carrying `X-Ratelimit-Resource: core` and
    `X-Ratelimit-Remaining: 0` is GitHub stating the pool is spent — the most direct
    evidence of exhaustion available. Discarding it and failing open meant the guard
    proceeded into the exact condition it exists to detect.

    The distinction that matters: transport-level rate headers are authoritative whatever
    the status code, while a 403's *body* is an error payload rather than a rate document.
    """

    def forbidden_with_headers(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        head = (
            "HTTP/2.0 403 Forbidden\r\n"
            "X-Ratelimit-Limit: 5000\r\n"
            "X-Ratelimit-Remaining: 0\r\n"
            "X-Ratelimit-Used: 5000\r\n"
            "X-Ratelimit-Reset: 1893456000\r\n"
            "X-Ratelimit-Resource: core\r\n"
        )
        body = json.dumps({"message": "API rate limit exceeded for user ID 418460."})
        return subprocess.CompletedProcess(cmd, 1, f"{head}\r\n{body}", "")

    snapshot = github_pr_status.rate_snapshot(repo_root=tmp_path, runner=forbidden_with_headers)
    assert snapshot.core is not None, "a 403's rate headers are evidence, not noise"
    assert snapshot.core.remaining == 0
    assert snapshot.core.source == "header"
    # The error body must not be mistaken for rate data.
    assert snapshot.graphql is None

    assert "github_rest_below_floor" in (github_pr_status.rest_pool_blocked(snapshot) or "")


def test_unknown_graphql_is_not_reported_as_a_measured_empty_pool(tmp_path: Path) -> None:
    """A reason code must not record an inference as a measurement (codex-1, major)."""

    def rest_empty_graphql_absent(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        head = (
            "HTTP/2.0 200 OK\r\n"
            "X-Ratelimit-Limit: 5000\r\n"
            "X-Ratelimit-Remaining: 0\r\n"
            "X-Ratelimit-Resource: core\r\n"
        )
        payload = {"resources": {"core": {"remaining": 0, "limit": 5000, "reset": 1}}}
        return subprocess.CompletedProcess(cmd, 0, f"{head}\r\n{json.dumps(payload)}", "")

    transport, reason = github_pr_status.choose_transport(
        repo_root=tmp_path, runner=rest_empty_graphql_absent
    )
    # The invariant this test was written for stands: the reason must not record an inference
    # as a measurement. What changed is the ROUTING — all three review families found that
    # refusing here deadlocked every fleet cycle, because unmeasurable is not the same as
    # measured-empty and there was no evidence GraphQL could not serve the scan.
    assert transport == "graphql", "unknown is not blocked; refusing needs a measurement"
    assert "graphql_unknown" in reason
    assert "both_pools_below_floor" not in reason


def _healthy_rest_graphql(graphql_remaining: int | None) -> Any:
    """REST healthy; GraphQL either measured at `graphql_remaining` or absent entirely."""

    def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        resources: dict[str, Any] = {"core": {"remaining": 4000, "limit": 5000, "reset": 1}}
        if graphql_remaining is not None:
            resources["graphql"] = {"remaining": graphql_remaining, "limit": 5000, "reset": 1}
        head = (
            "HTTP/2.0 200 OK\r\n"
            "X-Ratelimit-Limit: 5000\r\n"
            "X-Ratelimit-Remaining: 4000\r\n"
            "X-Ratelimit-Resource: core\r\n"
        )
        payload = {"resources": resources}
        return subprocess.CompletedProcess(cmd, 0, f"{head}\r\n{json.dumps(payload)}", "")

    return run


def test_graphql_low_and_graphql_unknown_get_different_reason_codes(tmp_path: Path) -> None:
    """The same discipline as the both-blocked branch, which this branch was missing.

    `github_graphql_below_floor_or_unknown` spelled two materially different states the same
    way, so a later reader could not reconstruct whether GraphQL was measured low or never
    measured at all (codex-1, minor). The routing outcome is REST either way; the record is
    not. Both directions are asserted because a fix that emitted one code for both would
    satisfy either assertion alone.
    """
    _, low_reason = github_pr_status.choose_transport(
        repo_root=tmp_path, runner=_healthy_rest_graphql(3)
    )
    _, unknown_reason = github_pr_status.choose_transport(
        repo_root=tmp_path, runner=_healthy_rest_graphql(None)
    )

    assert low_reason != unknown_reason, (
        f"measured-low and never-measured must not share a reason code: {low_reason!r}"
    )
    assert "below_floor" in low_reason and "3<" in low_reason, low_reason
    assert "unknown" in unknown_reason and "below_floor" not in unknown_reason, unknown_reason


def test_rest_floor_has_exactly_one_decision_point(tmp_path: Path) -> None:
    """choose_transport delegates its REST test rather than re-deriving the floor.

    An earlier revision applied DEFAULT_REST_MIN_REMAINING in both places, so they could
    disagree — the two-mitigations-per-hazard smell this change removed `rest_backoff` for,
    reintroduced in another shape (codex-1, major).
    """
    snapshot = github_pr_status.rate_snapshot(
        repo_root=tmp_path,
        runner=_rate_runner(header_remaining=400, body_core=400, body_graphql=4900),
    )
    # One floor, passed through: at 400 a floor of 300 permits REST and 500 blocks it, and
    # the guard and the chooser must agree at both settings.
    assert github_pr_status.rest_pool_blocked(snapshot, min_remaining=300) is None
    assert github_pr_status.rest_pool_blocked(snapshot, min_remaining=500) is not None

    permissive, _ = github_pr_status.choose_transport(
        repo_root=tmp_path, snapshot=snapshot, rest_min_remaining=300
    )
    strict, strict_reason = github_pr_status.choose_transport(
        repo_root=tmp_path, snapshot=snapshot, rest_min_remaining=500
    )
    assert permissive == "graphql", "300 permits REST, so the roomier pool wins on preference"
    assert strict == "graphql" and "below_floor" in strict_reason


def test_failed_lookup_without_rate_headers_is_unknown_not_exhausted(tmp_path: Path) -> None:
    """A failure carrying no rate headers is unknown headroom, and fails open.

    **This replaces a test that asserted the opposite for a 403 WITH headers**, which
    codified the discard of authoritative evidence (codex-1, major; see
    `test_a_403_with_rate_headers_is_a_measurement_of_exhaustion`). The distinction is the
    presence of transport-level rate headers, not the exit status:

    - failure **with** `X-Ratelimit-*`  → measured exhaustion, refuse
    - failure **without** them           → unknown, proceed

    A gh crash, a network drop, or an old binary yields no headers and must never be
    mistaken for an empty pool, since that would stop the fleet timers on a hiccup.
    """

    def failing_without_headers(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        # An error body but no HTTP header block at all — what a transport failure looks like.
        return subprocess.CompletedProcess(cmd, 1, '{"message":"could not resolve host"}', "")

    snapshot = github_pr_status.rate_snapshot(repo_root=tmp_path, runner=failing_without_headers)
    assert snapshot.core is None, "no headers means unknown, not measured"
    assert snapshot.graphql is None
    assert github_pr_status.rest_pool_blocked(snapshot) is None

    transport, _ = github_pr_status.choose_transport(
        repo_root=tmp_path, runner=failing_without_headers
    )
    assert transport == "rest", "unknown headroom fails open; it does not divert traffic"


def test_crlf_wire_format_parses_without_relying_on_newline_translation() -> None:
    """The header/body split must not depend on `text=True`'s universal newlines.

    HTTP puts CRLF CRLF on the wire. Measured 2026-08-29: `subprocess.run(text=True)`
    rewrites that to LF LF before this module sees it, so a bare `partition` on the LF
    form worked -- but only via a decoding side effect nothing stated or tested. A caller
    reading bytes would have broken it silently: no separator, empty body, both pools
    None, the balancer degenerating to "rest" unconditionally, and graphql_backoff
    becoming a permanent no-op. Review finding (claude-1, critical); the described
    production failure does not occur on the `text=True` path, but the unstated
    dependency was real. This pins the raw shape directly.
    """
    payload = {
        "resources": {
            "core": {"remaining": 10, "limit": 5000, "reset": 1893456000},
            "graphql": {"remaining": 4660, "limit": 5000, "reset": 1893456000},
        }
    }
    raw = (
        "HTTP/2.0 200 OK\r\n"
        "X-Ratelimit-Limit: 5000\r\n"
        "X-Ratelimit-Remaining: 10\r\n"
        "X-Ratelimit-Resource: core\r\n"
        "\r\n" + json.dumps(payload)
    )

    headers = github_pr_status._parse_rate_headers(raw)
    assert headers["x-ratelimit-remaining"] == "10"
    assert headers["x-ratelimit-resource"] == "core"

    head, body = github_pr_status._split_head_body(raw)
    assert "X-Ratelimit-Remaining" in head
    assert json.loads(body)["resources"]["graphql"]["remaining"] == 4660

    # The translated shape still works, so the fix is additive, not a swap.
    _, body_lf = github_pr_status._split_head_body(raw.replace("\r\n", "\n"))
    assert json.loads(body_lf)["resources"]["core"]["remaining"] == 10


def test_exhausted_rest_refuses_before_spending_calls(tmp_path: Path) -> None:
    """The operational guard: a request path consults the routing decision before calling.

    `list_open_pr_statuses_rest` is what cc-pr-autoqueue, cc-pr-merge-watcher and
    cc-pr-review-dispatch all use, and one call fans out into a listing plus per-PR
    hydration. When core is measurably empty those requests are guaranteed 403s, so
    refusing early is strictly better than spending them to fail slower. Review finding
    (codex-1, critical): before this, the only caller of choose_transport was the
    read-only diagnostic, so the operational path remained unguarded.
    """
    runner = _rate_runner(header_remaining=0, body_core=0, body_graphql=4660)
    calls: list[list[str]] = []

    def recording(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        calls.append(list(cmd))
        return runner(cmd, **kwargs)

    with pytest.raises(github_pr_status.RestPoolExhausted) as excinfo:
        github_pr_status.list_open_pr_statuses_rest(
            repo="owner/repo", repo_root=tmp_path, runner=recording
        )

    assert "github_rest_below_floor" in excinfo.value.reason
    assert excinfo.value.reset_epoch == 1893456000
    assert not any(call[:4] == ["gh", "api", "--method", "GET"] for call in calls), (
        "the listing must not be attempted once the pool is measured empty"
    )


def test_healthy_or_unknown_pool_never_blocks_polling(tmp_path: Path) -> None:
    """Fail open. Only a MEASURED empty pool refuses; everything else proceeds."""

    def healthy(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:4] == ["gh", "api", "-i", "rate_limit"]:
            return _rate_runner(header_remaining=4000, body_core=4000, body_graphql=4000)(
                cmd, **kwargs
            )
        return subprocess.CompletedProcess(cmd, 0, json.dumps([]), "")

    assert (
        github_pr_status.list_open_pr_statuses_rest(
            repo="owner/repo", repo_root=tmp_path, runner=healthy
        )
        == []
    )

    def probe_fails(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:4] == ["gh", "api", "-i", "rate_limit"]:
            return subprocess.CompletedProcess(cmd, 1, "", "network down")
        return subprocess.CompletedProcess(cmd, 0, json.dumps([]), "")

    assert (
        github_pr_status.list_open_pr_statuses_rest(
            repo="owner/repo", repo_root=tmp_path, runner=probe_fails
        )
        == []
    ), "an unreachable probe must not stop the fleet timers"


def test_healthy_rest_never_refuses_even_when_graphql_is_roomier(tmp_path: Path) -> None:
    """A balancing *preference* must not halt a REST-only path.

    Regression pinned: an earlier revision refused whenever `choose_transport` did not
    answer "rest", but that function answers "graphql" whenever GraphQL has proportionally
    more headroom — including with REST entirely healthy. All three reviewers caught it
    independently: the guard would have stopped cc-pr-autoqueue, cc-pr-merge-watcher and
    cc-pr-review-dispatch on a healthy pool.

    A REST-only caller has no GraphQL alternative to route to, so only REST's own
    spendability matters to it.
    """
    # REST healthy at 1000/5000; GraphQL roomier at 4900/5000 — choose_transport prefers
    # graphql, and the REST path must proceed anyway.
    runner = _rate_runner(header_remaining=1000, body_core=1000, body_graphql=4900)
    transport, _ = github_pr_status.choose_transport(repo_root=tmp_path, runner=runner)
    assert transport == "graphql", "fixture must actually exercise the preference case"

    def healthy(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:4] == ["gh", "api", "-i", "rate_limit"]:
            return runner(cmd, **kwargs)
        return subprocess.CompletedProcess(cmd, 0, json.dumps([]), "")

    assert (
        github_pr_status.list_open_pr_statuses_rest(
            repo="owner/repo", repo_root=tmp_path, runner=healthy
        )
        == []
    ), "a roomier GraphQL pool is a preference, not a reason to stop REST work"


def test_rest_pool_blocked_only_reports_rest_exhaustion(tmp_path: Path) -> None:
    """The predicate itself, independent of any caller."""
    healthy = github_pr_status.rate_snapshot(
        repo_root=tmp_path,
        runner=_rate_runner(header_remaining=1000, body_core=1000, body_graphql=4900),
    )
    assert github_pr_status.rest_pool_blocked(healthy) is None

    empty = github_pr_status.rate_snapshot(
        repo_root=tmp_path,
        runner=_rate_runner(header_remaining=0, body_core=0, body_graphql=4900),
    )
    assert "github_rest_below_floor" in (github_pr_status.rest_pool_blocked(empty) or "")

    unknown = github_pr_status.RateSnapshot(core=None, graphql=None)
    assert github_pr_status.rest_pool_blocked(unknown) is None, "unknown is not exhaustion"


def test_rate_pool_guard_can_be_disabled_for_callers_that_manage_their_own(
    tmp_path: Path,
) -> None:
    """`respect_rate_pools=False` preserves the pre-change contract exactly."""

    def empty_pool(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:4] == ["gh", "api", "-i", "rate_limit"]:
            return _rate_runner(header_remaining=0, body_core=0, body_graphql=0)(cmd, **kwargs)
        return subprocess.CompletedProcess(cmd, 0, json.dumps([]), "")

    assert (
        github_pr_status.list_open_pr_statuses_rest(
            repo="owner/repo",
            repo_root=tmp_path,
            runner=empty_pool,
            respect_rate_pools=False,
        )
        == []
    )


# --------------------------------------------------- the operational half: actually routing
#
# Review finding at 4dd82a97, raised independently by all three seated families (gemini
# critical, codex critical, claude major): `choose_transport` was reachable only from the
# diagnostic CLI, so REST-below-floor with healthy GraphQL made all three fleet timers sit
# out their cycles rather than selecting GraphQL. The exit predicate says "transport is
# chosen before the call"; a tested helper with no operational caller does not satisfy it.


class _BothTransportsRunner(FakeRunner):
    """Serves the same PR over REST and over `gh pr list --json` (GraphQL-backed)."""

    def __init__(self, *, rest_remaining: int, graphql_remaining: int) -> None:
        super().__init__()
        self.rest_remaining = rest_remaining
        self.graphql_remaining = graphql_remaining

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        self.calls.append(list(cmd))
        if cmd[:4] == ["gh", "api", "-i", "rate_limit"]:
            payload = {
                "resources": {
                    "core": {"remaining": self.rest_remaining, "limit": 5000, "reset": 1},
                    "graphql": {"remaining": self.graphql_remaining, "limit": 5000, "reset": 1},
                }
            }
            head = (
                "HTTP/2.0 200 OK\r\n"
                f"X-Ratelimit-Remaining: {self.rest_remaining}\r\n"
                "X-Ratelimit-Limit: 5000\r\n"
                "X-Ratelimit-Resource: core\r\n"
            )
            return subprocess.CompletedProcess(cmd, 0, f"{head}\r\n{json.dumps(payload)}", "")
        if cmd[:3] == ["gh", "pr", "list"]:
            assert "author" in cmd[cmd.index("--json") + 1].split(",")
            return subprocess.CompletedProcess(
                cmd,
                0,
                json.dumps(
                    [
                        {
                            "number": 9,
                            "id": "PR_node",
                            "author": {"login": "app/dependabot"},
                            "state": "OPEN",
                            "title": "REST PR",
                            "body": "body",
                            "url": "https://github.example/owner/repo/pull/9",
                            "updatedAt": "2026-07-05T15:00:00Z",
                            "mergedAt": None,
                            "headRefName": "feat/rest",
                            "headRefOid": "abc123",
                            "changedFiles": 1,
                            "files": [{"path": "scripts/example.py"}],
                            "isDraft": False,
                            "labels": [],
                            "reviewDecision": "APPROVED",
                            "autoMergeRequest": {"enabledBy": {"login": "bot"}},
                            "mergeStateStatus": "CLEAN",
                        }
                    ]
                ),
                "",
            )
        if cmd[:3] == ["gh", "pr", "view"]:
            return subprocess.CompletedProcess(
                cmd, 0, json.dumps({"headRefOid": "abc123", "statusCheckRollup": []}), ""
            )
        if cmd[:5] == ["gh", "api", "--method", "GET", "-H"]:
            path = cmd[6]
            pull = {
                "number": 9,
                "node_id": "PR_node",
                "user": {"login": "app/dependabot"},
                "title": "REST PR",
                "body": "body",
                "head": {"ref": "feat/rest", "sha": "abc123"},
                "draft": False,
                "state": "open",
                "merged_at": None,
                "updated_at": "2026-07-05T15:00:00Z",
                "html_url": "https://github.example/owner/repo/pull/9",
                "auto_merge": {"enabled_by": {"login": "bot"}},
                "mergeable_state": "clean",
                "changed_files": 1,
            }
            if path == "repos/owner/repo/pulls":
                return subprocess.CompletedProcess(cmd, 0, json.dumps([pull]), "")
            if path == "repos/owner/repo/pulls/9":
                return subprocess.CompletedProcess(cmd, 0, json.dumps(pull), "")
            if path == "repos/owner/repo/pulls/9/files":
                return subprocess.CompletedProcess(
                    cmd, 0, json.dumps([{"filename": "scripts/example.py"}]), ""
                )
            if path == "repos/owner/repo/pulls/9/reviews":
                return subprocess.CompletedProcess(
                    cmd, 0, json.dumps([{"state": "approved", "user": {"login": "reviewer"}}]), ""
                )
        return super().__call__(cmd, **kwargs)


def test_the_two_transports_agree_on_row_shape(tmp_path: Path) -> None:
    """The guard that makes a divergence loud instead of silent.

    Consumers read these rows by key; the autoqueue makes merge decisions from them. A field
    present on one transport and missing on the other would not raise — it would read `None`
    and quietly change a merge decision depending on which rate pool happened to be roomier.
    That is the failure mode that made this work look expensive, and it is the one thing a
    test can actually foreclose.
    """
    kwargs: dict[str, Any] = {
        "repo": "owner/repo",
        "repo_root": tmp_path,
        "include_files": True,
        "include_review_decision": True,
    }
    rest_rows = github_pr_status.list_open_pr_statuses_rest(
        runner=_BothTransportsRunner(rest_remaining=4000, graphql_remaining=4000), **kwargs
    )
    graphql_rows = github_pr_status.list_open_pr_statuses_graphql(
        runner=_BothTransportsRunner(rest_remaining=4000, graphql_remaining=4000), **kwargs
    )

    assert rest_rows and graphql_rows
    assert set(rest_rows[0]) == set(graphql_rows[0]), (
        "the two transports must produce the same keys; a consumer reads them by name.\n"
        f"rest-only: {set(rest_rows[0]) - set(graphql_rows[0])}\n"
        f"graphql-only: {set(graphql_rows[0]) - set(rest_rows[0])}"
    )
    # Not just the keys — the values a merge decision actually turns on.
    for field in (
        "number",
        "state",
        "headRefOid",
        "mergeStateStatus",
        "reviewDecision",
        "isDraft",
        "author",
    ):
        assert rest_rows[0][field] == graphql_rows[0][field], field


def test_exhausted_rest_routes_the_fleet_listing_to_graphql(tmp_path: Path) -> None:
    """The predicate, at the operational call: chosen before the call, not after a failure."""
    runner = _BothTransportsRunner(rest_remaining=0, graphql_remaining=4660)

    rows, route = github_pr_status.list_open_pr_statuses(
        repo="owner/repo", repo_root=tmp_path, runner=runner
    )

    assert rows and rows[0]["number"] == 9
    assert any(call[:3] == ["gh", "pr", "list"] for call in runner.calls), (
        "an exhausted REST pool with healthy GraphQL must SELECT GraphQL, not skip the cycle"
    )
    assert not any(
        len(call) > 6 and call[6].startswith("repos/owner/repo/pulls") for call in runner.calls
    ), "nothing may be spent on the measured-empty pool"


def test_healthy_rest_keeps_the_fleet_listing_on_rest(tmp_path: Path) -> None:
    """Diversion happens only away from a pool measured to be in trouble."""
    runner = _BothTransportsRunner(rest_remaining=4900, graphql_remaining=600)

    rows, route = github_pr_status.list_open_pr_statuses(
        repo="owner/repo", repo_root=tmp_path, runner=runner
    )

    assert rows and rows[0]["number"] == 9
    assert any(len(call) > 6 and call[6] == "repos/owner/repo/pulls" for call in runner.calls), (
        "healthy REST must stay on REST"
    )
    assert not any(call[:3] == ["gh", "pr", "list"] for call in runner.calls)


def test_both_pools_blocked_still_refuses_the_cycle(tmp_path: Path) -> None:
    """Routing must not become a way to spend a pool that is also measurably empty."""
    runner = _BothTransportsRunner(rest_remaining=0, graphql_remaining=0)

    with pytest.raises(github_pr_status.RestPoolExhausted):
        github_pr_status.list_open_pr_statuses(repo="owner/repo", repo_root=tmp_path, runner=runner)


def test_a_failed_graphql_listing_refuses_instead_of_reading_as_an_empty_estate(
    tmp_path: Path,
) -> None:
    """ "We did not look" and "nothing found" are the same value and different facts.

    This is the precise way the pre-#4436 implementation failed: it swallowed GitHub's 504 as
    an empty list, and an empty list reads downstream as "no PRs need attention" — silently
    deadlocking the merge pipeline. The first version of this function documented that hazard
    in a comment and then reproduced it three lines later, which is what codex caught.
    """

    def failing_list(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(cmd, 1, "", "HTTP 504 Gateway Timeout")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with pytest.raises(github_pr_status.GraphQLListingFailed) as excinfo:
        github_pr_status.list_open_pr_statuses_graphql(
            repo="owner/repo", repo_root=tmp_path, runner=failing_list
        )
    assert "504" in str(excinfo.value)

    def malformed_list(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"message": "nope"}), "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with pytest.raises(github_pr_status.GraphQLListingFailed):
        github_pr_status.list_open_pr_statuses_graphql(
            repo="owner/repo", repo_root=tmp_path, runner=malformed_list
        )


@pytest.mark.parametrize(
    ("payload", "why"),
    [
        ("[null]", "a null row parses fine and would silently vanish"),
        ('[{"title": "no number"}]', "a row with no identity cannot be safely omitted"),
        ('[{"number": ""}]', "an empty identity is not a PR number"),
        ('[{"number": 0}]', "zero is not a GitHub PR number"),
        ('[{"number": true}]', "a boolean is an integer subclass but not a PR number"),
    ],
)
def test_a_malformed_row_refuses_rather_than_shrinking_the_estate(
    tmp_path: Path, payload: str, why: str
) -> None:
    """Skipping a bad row rebuilds the silent-empty failure one level down.

    Rejecting only the top-level payload was not enough: `[null]` is a valid JSON list, yields
    no rows, and reads downstream as "no open PRs" — the exact deadlock `GraphQLListingFailed`
    was introduced to prevent. A row we cannot identify is not a PR we can drop from a merge
    decision.
    """

    def rows(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(cmd, 0, payload, "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with pytest.raises(github_pr_status.GraphQLListingFailed):
        (
            github_pr_status.list_open_pr_statuses_graphql(
                repo="owner/repo", repo_root=tmp_path, runner=rows, include_status=False
            ),
            why,
        )


def test_a_failed_listing_is_caught_by_the_same_handler_as_exhaustion(tmp_path: Path) -> None:
    """Both mean "skip the cycle", so both must be reachable by one `except`.

    The three fleet callers each catch `PrListingUnavailable`. If a failed GraphQL listing were
    outside that hierarchy it would escape and crash the timer service — mint a P0 "service
    failed" incident to report a listing that did not come back.
    """
    assert issubclass(github_pr_status.GraphQLListingFailed, github_pr_status.PrListingUnavailable)
    assert issubclass(github_pr_status.RestPoolExhausted, github_pr_status.PrListingUnavailable)


def test_both_pools_blocked_reports_when_not_merely_that(tmp_path: Path) -> None:
    """A refusal without a reset time tells an operator nothing they can act on."""
    runner = _BothTransportsRunner(rest_remaining=0, graphql_remaining=0)

    with pytest.raises(github_pr_status.RestPoolExhausted) as excinfo:
        github_pr_status.list_open_pr_statuses(repo="owner/repo", repo_root=tmp_path, runner=runner)
    assert excinfo.value.reset_epoch is not None, (
        "the refusal must carry a reset time; both pools measured empty is not actionable "
        "without a when"
    )


def test_the_chooser_returns_its_decision_rather_than_leaving_it_to_be_inferred(
    tmp_path: Path,
) -> None:
    """The decision must survive an EMPTY listing, which is where inference broke.

    An earlier revision let callers recover the cycle's transport by scanning rows for a
    `transport` stamp. With zero open PRs there are no rows, so a GraphQL-routed cycle read as
    "rest" — the predicate holding by coincidence of data rather than by construction.
    """

    def empty_listing(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(cmd, 0, "[]", "")
        return _BothTransportsRunner(rest_remaining=0, graphql_remaining=4660)(cmd, **kwargs)

    rows, route = github_pr_status.list_open_pr_statuses(
        repo="owner/repo", repo_root=tmp_path, runner=empty_listing
    )

    assert rows == []
    assert route.transport == "graphql", (
        "an empty listing has no rows to infer from; the decision must come from the chooser"
    )
    assert route.rest_blocked is True


def test_a_measured_empty_rest_pool_is_not_an_eligible_fallback(tmp_path: Path) -> None:
    """Failure paths narrow. Falling back to a pool measured empty attempts more, not less.

    `rest_blocked` exists to make that decidable at the point of fallback rather than
    re-derived — the route carries it, so a GraphQL failure on a blocked-REST cycle refuses
    instead of recreating the failure-triggered routing this change replaced.
    """
    blocked = github_pr_status.ListingRoute(
        transport="graphql", rest_blocked=True, reason="core=0<500"
    )
    open_pool = github_pr_status.ListingRoute(
        transport="graphql", rest_blocked=False, reason="github_graphql_has_more_headroom"
    )

    assert blocked.rest_blocked is True
    assert open_pool.rest_blocked is False


def test_the_rest_floor_has_an_operational_killswitch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gate on every fleet scan needs a way off that is not a deploy.

    `HAPAX_GITHUB_REST_MIN_REMAINING=0` restores exactly the pre-change behaviour: nothing is
    refused for measured exhaustion. An operator at 3am cannot edit and redeploy source.
    """
    empty_core = _BothTransportsRunner(rest_remaining=0, graphql_remaining=0)
    snapshot = github_pr_status.rate_snapshot(repo_root=tmp_path, runner=empty_core)

    assert github_pr_status.rest_pool_blocked(snapshot) is not None, "guarded by default"

    monkeypatch.setenv(github_pr_status.REST_MIN_REMAINING_ENV, "0")
    assert github_pr_status.rest_pool_blocked(snapshot) is None, (
        "the documented killswitch must actually disable the floor"
    )


def test_a_failed_rest_listing_refuses_like_the_graphql_one(tmp_path: Path) -> None:
    """The two transports must fail the same way for the same event.

    GraphQL raised while REST quietly returned [] — so the identical failure produced a
    refusal on one pool and a silent "no open PRs" on the other, depending only on which pool
    happened to be roomier that minute.
    """

    def rest_listing_fails(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:4] == ["gh", "api", "-i", "rate_limit"]:
            return _BothTransportsRunner(rest_remaining=4000, graphql_remaining=10)(cmd, **kwargs)
        return subprocess.CompletedProcess(cmd, 1, "", "boom")

    with pytest.raises(github_pr_status.PrListingUnavailable):
        github_pr_status.list_open_pr_statuses(
            repo="owner/repo", repo_root=tmp_path, runner=rest_listing_fails
        )


def test_an_unrunnable_gh_refuses_instead_of_escaping_as_an_os_error(tmp_path: Path) -> None:
    """A `gh` that cannot be executed must refuse, not kill the caller.

    Found by two review families. The REST listing handlers catch `subprocess.SubprocessError`;
    `TimeoutExpired` subclasses it, so timeouts were routed correctly — but **`OSError` subclasses
    neither**, so a missing or unexecutable `gh` sailed past both handlers, past
    `PrListingUnavailable`, and past the GraphQL fallback, crashing fleet consumers that catch only
    the declared failure mode. Three earlier passes over this exact boundary missed it because the
    structural test exempted `_rest_get_json` on the premise that wrapping already covered it.

    The distinction being pinned is refusal versus crash, NOT refusal versus empty: returning
    `None` here would have collapsed "transport unavailable" into "no open PRs", which is the
    silent-empty defect this module refuses everywhere else.
    """

    def gh_is_not_installed(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:4] == ["gh", "api", "-i", "rate_limit"]:
            return _BothTransportsRunner(rest_remaining=4000, graphql_remaining=10)(cmd, **kwargs)
        raise FileNotFoundError(2, "No such file or directory: 'gh'")

    with pytest.raises(github_pr_status.PrListingUnavailable):
        github_pr_status.list_open_pr_statuses(
            repo="owner/repo", repo_root=tmp_path, runner=gh_is_not_installed
        )

    # The normalised type stays catchable by the handlers that already existed, which is the whole
    # reason it subclasses SubprocessError rather than introducing a parallel hierarchy.
    assert issubclass(github_pr_status.RestTransportUnavailable, subprocess.SubprocessError)


def test_every_fleet_consumer_routes_its_open_pr_listing() -> None:
    """The enumeration, pinned — because estimating this tail is what took ten review rounds.

    Five consumers poll open PRs. Five review rounds each found the next one still on
    `list_open_pr_statuses_rest`, and each time I fixed the one named and left its siblings,
    because I priced the remainder instead of listing it. This asserts the list.

    A new fleet consumer that reaches for the REST-only helper fails here rather than in a
    review round — or, if it genuinely needs the unrouted helper, has to say so by name.
    """
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    fleet = [
        "cc-pr-autoqueue.py",
        "cc-pr-merge-watcher.py",
        "cc-pr-review-dispatch.py",
        "hapax-pr-admission",
        "hapax-merge-queue-lineage",
    ]
    unrouted = [
        name
        for name in fleet
        if "list_open_pr_statuses(" not in (scripts / name).read_text(encoding="utf-8")
    ]
    assert unrouted == [], (
        "these fleet consumers poll open PRs without choosing a transport, so they drain one "
        f"pool while the other idles: {unrouted}"
    )


def test_every_subprocess_boundary_is_normalised_or_named() -> None:
    """The third axis, added after normalising the same boundary three times one site at a time.

    `_run` can raise (TimeoutExpired, OSError). Every caller reachable from a fleet scan must
    convert that into its own declared failure mode — a refusal, or the `None` its docstring
    promises — because callers catch `PrListingUnavailable`, not arbitrary OS errors, and an
    escaping exception kills the timer instead of skipping a cycle.

    I fixed this in the listing, then in the per-PR rollup, then in `get_pr_status_graphql`,
    each time only where the review pointed. Enumerating the callers takes one AST walk; the
    list is short and it is now asserted.
    """
    source = (Path(__file__).resolve().parents[2] / "scripts" / "github_pr_status.py").read_text(
        encoding="utf-8"
    )
    # Callers deliberately left raw, each with the reason it is safe.
    raw_by_design = {
        # The primitive itself: normalising here would hide the error from every caller.
        "_run",
        # `_rest_get_json` WAS exempted here, on the premise that "the fleet path wraps it —
        # `list_open_pr_statuses` catches SubprocessError, and TimeoutExpired subclasses it". That
        # is true of timeouts and FALSE of OSError, which subclasses neither: a missing or
        # unexecutable `gh` escaped both REST listing handlers, bypassed PrListingUnavailable and
        # the GraphQL fallback, and killed fleet consumers. Two review families found it, and this
        # exemption is what let it survive three earlier passes over the same boundary — the test
        # asserting the invariant carried the false premise that hid its violation.
        # It now normalises to RestTransportUnavailable and is no longer exempt.
        # Pre-existing GraphQL runner with its own rc-based protocol (GRAPHQL_BACKOFF_RC); its
        # callers check returncode rather than catching, and changing that is not this change.
        "run_graphql_rate_aware",
    }
    # Structural, not textual. A first version grepped the function body for "TimeoutExpired"
    # and passed under mutation — because the word appears in the COMMENT explaining why the
    # guard is there. A test that greps for a word passes for any function that merely mentions
    # it; this one asks the AST whether a handler actually catches the exception.
    guards = {"TimeoutExpired", "OSError", "SubprocessError"}

    def _handler_names(handler: ast.ExceptHandler) -> set[str]:
        if handler.type is None:
            return {"BareExcept"}
        parts = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
        names = set()
        for part in parts:
            while isinstance(part, ast.Attribute):
                part = part.value if not isinstance(part.value, ast.Name) else part
                if isinstance(part, ast.Attribute):
                    names.add(part.attr)
                    break
            if isinstance(part, ast.Attribute):
                names.add(part.attr)
            elif isinstance(part, ast.Name):
                names.add(part.id)
        return names

    def _calls_run(node: ast.AST) -> bool:
        return any(
            isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "_run"
            for sub in ast.walk(node)
        )

    unnormalised: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name in raw_by_design or not _calls_run(node):
            continue
        caught: set[str] = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Try):
                for handler in sub.handlers:
                    caught |= _handler_names(handler)
        if not (caught & guards):
            unnormalised.append(node.name)

    assert unnormalised == [], (
        "these functions call `_run` without an except handler that catches a raised OS error, "
        f"so one slow call kills the cycle instead of skipping it: {unnormalised}"
    )


def test_every_per_pr_rest_call_in_the_fleet_is_routed_or_named() -> None:
    """The axis the first enumeration missed, which is why round 11 found three more siblings.

    Listing the consumers that call the routed listing is one axis. The other is every REST call
    *inside* each consumer — the per-PR work, which is N calls to the listing's one. Routing the
    listing and leaving the loop spares almost nothing, and that is the mistake this workstream
    made five times.

    Every site below is either routed (guarded by the cycle's `route`) or **named here with a
    reason**. A new unrouted REST call fails this test; a deliberately excluded one has to be
    argued for in this list rather than left silent.
    """
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    rest_callers = re.compile(
        r"\b(get_pull_rest|list_pull_files_rest|review_decision_rest|"
        r"fetch_status_check_rollup_rest|get_pr_status_rest|list_pulls_rest|"
        r"list_pulls_for_branch_rest)\("
    )
    # Sites excluded on purpose, each with why. These are NOT open-PR polling.
    excluded = {
        # The merge watcher's *close* path: it scans MERGED PRs since a durable cursor to close
        # their cc-tasks. Different surface, different cadence, different failure mode from the
        # open-PR poll — routing it is separate work, not an omission from this one.
        ("cc-pr-merge-watcher.py", "_search_merged_pull_details_rest"),
        ("cc-pr-merge-watcher.py", "fetch_merged_prs"),
        ("cc-pr-merge-watcher.py", "_query_pr_state"),
        ("cc-pr-merge-watcher.py", "_list_prs_for_branch"),
        # Reached only on the REST path: `fetch_pr` returns early via `gh pr view` when the cycle
        # chose GraphQL, so these never run on a GraphQL-routed cycle.
        ("cc-pr-review-dispatch.py", "fetch_pr"),
        # Reached only for REST-sourced rows; the caller skips re-hydration for GraphQL rows.
        ("cc-pr-autoqueue.py", "_fetch_status_check_rollup"),
    }
    routed_by_route_param = {
        ("cc-pr-autoqueue.py", "fetch_open_prs"),
        ("cc-pr-autoqueue.py", "fetch_pr_release_evidence"),
        ("hapax-merge-queue-lineage", "fetch_prs"),
    }

    unaccounted: list[str] = []
    for name in (
        "cc-pr-autoqueue.py",
        "cc-pr-merge-watcher.py",
        "cc-pr-review-dispatch.py",
        "hapax-pr-admission",
        "hapax-merge-queue-lineage",
    ):
        source = (scripts / name).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = ast.get_source_segment(source, node) or ""
            if not rest_callers.search(body):
                continue
            key = (name, node.name)
            if key in excluded or key in routed_by_route_param:
                continue
            unaccounted.append(f"{name}:{node.name}")

    assert unaccounted == [], (
        "these functions spend REST without consulting the cycle's transport, and are not on the "
        f"named-exclusion list: {unaccounted}"
    )


def test_a_failing_graphql_listing_falls_back_to_a_HEALTHY_rest_pool(tmp_path: Path) -> None:
    """Eligibility turns on `rest_blocked`, never on "we already tried something".

    Without this, a persistently failing GraphQL listing deadlocked every fleet scan while REST
    sat at full headroom: `choose_transport` kept picking the roomier pool, the pool kept
    failing, and the refusal was permanent. That is a deadlock, not caution — and it was mine,
    from applying the fallback rule per-PR and not at the listing.
    """

    def graphql_broken(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(cmd, 1, "", "HTTP 504")
        # REST healthy and roomier-losing: graphql wins the choice, then fails.
        return _BothTransportsRunner(rest_remaining=3000, graphql_remaining=4900)(cmd, **kwargs)

    rows, route = github_pr_status.list_open_pr_statuses(
        repo="owner/repo", repo_root=tmp_path, runner=graphql_broken
    )

    assert rows and rows[0]["number"] == 9, "a healthy REST pool must still serve the scan"
    assert route.transport == "rest"
    assert "graphql_listing_failed" in route.reason


def test_a_failing_graphql_listing_still_refuses_when_rest_is_measured_empty(
    tmp_path: Path,
) -> None:
    """The converse, and the reason the fallback is conditional rather than unconditional."""

    def both_bad(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(cmd, 1, "", "HTTP 504")
        return _BothTransportsRunner(rest_remaining=0, graphql_remaining=4900)(cmd, **kwargs)

    with pytest.raises(github_pr_status.GraphQLListingFailed):
        github_pr_status.list_open_pr_statuses(
            repo="owner/repo", repo_root=tmp_path, runner=both_bad
        )


def test_a_failing_rest_fallback_refuses_instead_of_reading_as_empty(tmp_path: Path) -> None:
    """The fallback needed the same determinacy as the path it falls back from.

    I wrote the GraphQL→REST fallback without `fail_on_indeterminate`, so a fallback that also
    failed returned `[]` — the silent-empty defect, reproduced inside the fix for the deadlock.
    """

    def both_listings_fail(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(cmd, 1, "", "HTTP 504")
        if cmd[:4] == ["gh", "api", "-i", "rate_limit"]:
            return _BothTransportsRunner(rest_remaining=3000, graphql_remaining=4900)(cmd, **kwargs)
        return subprocess.CompletedProcess(cmd, 1, "", "rest boom")

    with pytest.raises(github_pr_status.PrListingUnavailable):
        github_pr_status.list_open_pr_statuses(
            repo="owner/repo", repo_root=tmp_path, runner=both_listings_fail
        )


@pytest.mark.parametrize("route", ["primary", "fallback"])
@pytest.mark.parametrize(
    "payload",
    [
        [None],
        [{"title": "missing number"}],
        [{"number": ""}],
        [{"number": 0}],
        [{"number": True}],
    ],
)
def test_malformed_rest_rows_refuse_the_fleet_listing(
    tmp_path: Path, route: str, payload: list[Any]
) -> None:
    """A parsed REST list is determinate only when every row identifies a real PR.

    Filtering ``[null]`` to ``[]`` reports a quiet estate, while passing a dict with no
    usable ``number`` onward fabricates a status row that no consumer can act on. Both the
    REST primary and GraphQL-to-REST fallback request strict listing semantics, so both must
    refuse these payloads rather than shrinking the observed estate.
    """
    if route == "primary":
        rest_remaining, graphql_remaining = 4900, 0
    else:
        rest_remaining, graphql_remaining = 3000, 4900

    def malformed_rest(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(cmd, 1, "", "HTTP 504")
        if cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6] == "repos/owner/repo/pulls":
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        return _BothTransportsRunner(
            rest_remaining=rest_remaining, graphql_remaining=graphql_remaining
        )(cmd, **kwargs)

    with pytest.raises(github_pr_status.RestListingFailed) as excinfo:
        github_pr_status.list_open_pr_statuses(
            repo="owner/repo", repo_root=tmp_path, runner=malformed_rest
        )

    assert "row 0" in excinfo.value.reason


def test_the_fallback_is_symmetric_when_rest_is_chosen_and_fails(tmp_path: Path) -> None:
    """Whichever pool the chooser prefers must not be the only one able to fail the scan.

    The GraphQL→REST direction was implemented and the REST→GraphQL one was not, which made the
    asymmetry arbitrary: identical failures produced a refusal or a served scan depending only
    on which pool happened to be roomier that minute.
    """

    def rest_broken(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:5] == ["gh", "api", "--method", "GET", "-H"]:
            return subprocess.CompletedProcess(cmd, 1, "", "rest boom")
        # REST roomier, so it is chosen; then it fails, and GraphQL is healthy.
        return _BothTransportsRunner(rest_remaining=4900, graphql_remaining=3000)(cmd, **kwargs)

    rows, route = github_pr_status.list_open_pr_statuses(
        repo="owner/repo", repo_root=tmp_path, runner=rest_broken
    )

    assert rows and rows[0]["number"] == 9
    assert route.transport == "graphql"
    assert "rest_listing_failed" in route.reason


@pytest.mark.parametrize("failure", ["timeout", "nonzero", "malformed_json", "malformed_shape"])
def test_an_indeterminate_graphql_rollup_falls_back_to_a_healthy_rest_pool(
    tmp_path: Path, failure: str
) -> None:
    """A rollup transport failure is not the same fact as a PR with no checks.

    Returning ``[]`` for either one leaves the routed GraphQL listing looking successful, so
    the fleet never invokes its healthy-REST fallback. Autoqueue then blocks every PR on absent
    evidence while REST sits idle, and lineage can record the incomplete rows as hydrated.

    The four failure shapes are deliberately one contract: timeout, nonzero exit, invalid JSON,
    and a payload whose rollup is not a list must all make the GraphQL scan indeterminate. The
    fleet-level router can then retry the complete scan on REST, which was measured healthy.
    """
    seen: list[list[str]] = []

    def rollup_is_indeterminate(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        seen.append(list(cmd))
        if cmd[:3] == ["gh", "pr", "view"]:
            if failure == "timeout":
                raise subprocess.TimeoutExpired(cmd, 60)
            if failure == "nonzero":
                return subprocess.CompletedProcess(cmd, 1, "", "HTTP 504")
            if failure == "malformed_json":
                return subprocess.CompletedProcess(cmd, 0, "not-json", "")
            return subprocess.CompletedProcess(
                cmd, 0, json.dumps({"statusCheckRollup": {"not": "a list"}}), ""
            )
        return _BothTransportsRunner(rest_remaining=3000, graphql_remaining=4900)(cmd, **kwargs)

    rows, route = github_pr_status.list_open_pr_statuses(
        repo="owner/repo", repo_root=tmp_path, runner=rollup_is_indeterminate
    )

    assert rows and rows[0]["transport"] == "rest"
    assert rows[0]["statusCheckRollup"], "the eligible REST retry must hydrate the real rollup"
    assert route.transport == "rest"
    assert route.reason == "graphql_listing_failed_rest_healthy"
    assert any(call[:3] == ["gh", "pr", "view"] for call in seen)


def test_an_indeterminate_graphql_rollup_refuses_when_rest_is_measured_empty(
    tmp_path: Path,
) -> None:
    """When no alternate pool is eligible, expose the gap instead of fabricating ``[]``."""

    def rollup_times_out(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:3] == ["gh", "pr", "view"]:
            raise subprocess.TimeoutExpired(cmd, 60)
        return _BothTransportsRunner(rest_remaining=0, graphql_remaining=4900)(cmd, **kwargs)

    with pytest.raises(github_pr_status.GraphQLRollupFailed):
        github_pr_status.list_open_pr_statuses(
            repo="owner/repo", repo_root=tmp_path, runner=rollup_times_out
        )


def test_a_real_empty_graphql_rollup_remains_a_determinate_result(tmp_path: Path) -> None:
    """The new indeterminate state must not erase the legitimate "no checks" state."""
    seen: list[list[str]] = []

    def no_checks(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        seen.append(list(cmd))
        if cmd[:3] == ["gh", "pr", "view"]:
            return subprocess.CompletedProcess(
                cmd, 0, json.dumps({"headRefOid": "abc123", "statusCheckRollup": []}), ""
            )
        return _BothTransportsRunner(rest_remaining=3000, graphql_remaining=4900)(cmd, **kwargs)

    rows, route = github_pr_status.list_open_pr_statuses(
        repo="owner/repo", repo_root=tmp_path, runner=no_checks
    )

    assert rows and rows[0]["transport"] == "graphql"
    assert rows[0]["statusCheckRollup"] == []
    assert route.transport == "graphql"
    assert not any(len(call) > 6 and call[6] == "repos/owner/repo/pulls" for call in seen), (
        "a genuine empty rollup must not spend the fallback pool"
    )


@pytest.mark.parametrize("hydrated_head", ["abc123", "head-B", "", None])
@pytest.mark.parametrize("rest_remaining", [0, 3000])
@pytest.mark.parametrize("with_checks", [True, False])
def test_bulk_graphql_rollup_is_bound_to_the_listed_head(
    tmp_path: Path, hydrated_head: str | None, rest_remaining: int, with_checks: bool
) -> None:
    fake = _BothTransportsRunner(rest_remaining=rest_remaining, graphql_remaining=4900)
    check = {"name": "head-B-check", "status": "COMPLETED", "conclusion": "SUCCESS"}
    checks = [check] if with_checks else []

    def runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:3] == ["gh", "pr", "view"]:
            fake.calls.append(cmd)
            payload = {"headRefOid": hydrated_head, "statusCheckRollup": checks}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        return fake(cmd, **kwargs)

    if hydrated_head != "abc123" and rest_remaining == 0:
        with pytest.raises(github_pr_status.GraphQLRollupFailed, match="head_sha_mismatch"):
            github_pr_status.list_open_pr_statuses(
                repo="owner/repo", repo_root=tmp_path, runner=runner
            )
        assert not any(cmd[:5] == ["gh", "api", "--method", "GET", "-H"] for cmd in fake.calls)
    else:
        rows, route = github_pr_status.list_open_pr_statuses(
            repo="owner/repo", repo_root=tmp_path, runner=runner
        )
        if hydrated_head == "abc123":
            assert route.transport == "graphql"
            assert rows[0]["headRefOid"] == hydrated_head
            assert rows[0]["statusCheckRollup"] == checks
        else:
            assert route.transport == "rest"
            assert check not in rows[0]["statusCheckRollup"]
    view = next(cmd for cmd in fake.calls if cmd[:3] == ["gh", "pr", "view"])
    assert {"headRefOid", "statusCheckRollup"} <= set(view[-1].split(","))


def test_single_pr_graphql_hydration_does_not_return_an_incomplete_row(tmp_path: Path) -> None:
    """Lineage must receive ``None`` so it can retry or record an unhydrated gap."""
    seen: list[list[str]] = []

    def rollup_missing(cmd: list[str], **_: Any) -> subprocess.CompletedProcess:
        seen.append(list(cmd))
        if cmd[:3] != ["gh", "pr", "view"]:
            return subprocess.CompletedProcess(cmd, 1, "", "unexpected")
        return subprocess.CompletedProcess(
            cmd,
            0,
            json.dumps(
                {
                    "number": 9,
                    "url": "https://github.com/owner/repo/pull/9",
                    "state": "OPEN",
                    "title": "PR",
                    "headRefName": "feat/graphql",
                    "headRefOid": "abc123",
                    "mergeStateStatus": "CLEAN",
                }
            ),
            "",
        )

    row = github_pr_status.get_pr_status_graphql(
        9, repo="owner/repo", repo_root=tmp_path, runner=rollup_missing
    )

    assert row is None, "an incomplete row would make lineage report hydration_complete=true"
    assert len([call for call in seen if call[:3] == ["gh", "pr", "view"]]) == 1


def test_the_rest_fallback_distinguishes_empty_from_failed(tmp_path: Path) -> None:
    """Answers a review finding that did not reproduce, and guards it anyway.

    The claim was that the REST fallback "may still collapse to an empty estate". It does not:
    `fail_on_indeterminate=True` raises, and `TimeoutExpired` subclasses `SubprocessError` so it
    is caught too. But an empty result and a failed one are one keystroke apart here, so both
    directions are pinned rather than argued.
    """

    def graphql_fails_rest_empty(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(cmd, 1, "", "HTTP 504")
        if cmd[:5] == ["gh", "api", "--method", "GET", "-H"]:
            return subprocess.CompletedProcess(cmd, 0, "[]", "")
        return _BothTransportsRunner(rest_remaining=3000, graphql_remaining=4900)(cmd, **kwargs)

    rows, route = github_pr_status.list_open_pr_statuses(
        repo="owner/repo", repo_root=tmp_path, runner=graphql_fails_rest_empty
    )
    assert rows == [] and route.transport == "rest", (
        "a genuinely empty REST fallback is a measurement, not a failure"
    )

    def graphql_fails_rest_times_out(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(cmd, 1, "", "HTTP 504")
        if cmd[:5] == ["gh", "api", "--method", "GET", "-H"]:
            raise subprocess.TimeoutExpired(cmd, 60)
        return _BothTransportsRunner(rest_remaining=3000, graphql_remaining=4900)(cmd, **kwargs)

    with pytest.raises(github_pr_status.PrListingUnavailable):
        github_pr_status.list_open_pr_statuses(
            repo="owner/repo", repo_root=tmp_path, runner=graphql_fails_rest_times_out
        )


def test_a_probe_timeout_fails_open_rather_than_crashing_the_timer(tmp_path: Path) -> None:
    """The fail-open promise is in `rate_snapshot`'s own docstring, and a raised exception broke it.

    The probe now runs on every fleet scan, so a 30-second hang would take down the timer
    service rather than proceed on unknown headroom. Unknown routes to REST, exactly as before
    this change — the documented behaviour, reached by a path the tests did not cover because
    they only ever exercised nonzero return codes.
    """

    def times_out(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        raise subprocess.TimeoutExpired(cmd, 30)

    snapshot = github_pr_status.rate_snapshot(repo_root=tmp_path, runner=times_out)
    assert snapshot.core is None and snapshot.graphql is None

    transport, reason = github_pr_status.choose_transport(repo_root=tmp_path, runner=times_out)
    assert transport == "rest", f"unknown headroom must fail open to REST, got {transport}"
    assert "unknown" in reason


def test_listing_failure_and_exhaustion_get_different_operator_text(tmp_path: Path) -> None:
    """All three fleet handlers said "quota, not auth" for every case.

    That is true of exhaustion and false of a failed listing, which can be auth, malformed
    output, or a 504 — and it printed a null reset with no recovery action. One shared
    formatter, so the three cannot drift apart again.
    """
    exhausted = github_pr_status.listing_unavailable_detail(
        github_pr_status.RestPoolExhausted("core=0", None)
    )
    failed = github_pr_status.listing_unavailable_detail(
        github_pr_status.GraphQLListingFailed("rc=1")
    )

    assert "quota, not auth" in exhausted
    assert "quota" not in failed.replace("NOT a quota condition", "")
    assert "gh auth status" in failed, "a failed listing must name a next action"
    assert exhausted != failed


def test_bulk_graphql_query_never_requests_status_check_rollup(tmp_path: Path) -> None:
    """Pins the constraint the pre-#4436 implementation paid for.

    `statusCheckRollup` in the bulk query makes the aggregate response large enough that
    GitHub returns 504 — deterministic at ~30 open PRs — which the old code swallowed as an
    empty list, silently deadlocking the merge pipeline. It is fetched per-PR instead.
    """
    assert "statusCheckRollup" not in github_pr_status._GRAPHQL_PR_LIST_FIELDS

    runner = _BothTransportsRunner(rest_remaining=0, graphql_remaining=4660)
    github_pr_status.list_open_pr_statuses_graphql(
        repo="owner/repo", repo_root=tmp_path, runner=runner
    )

    bulk = [call for call in runner.calls if call[:3] == ["gh", "pr", "list"]]
    assert bulk, "expected a bulk listing call"
    assert all("statusCheckRollup" not in " ".join(call) for call in bulk)
    assert any(call[:3] == ["gh", "pr", "view"] for call in runner.calls), (
        "the rollup must still be fetched, just per-PR"
    )


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        *[({"number": number}, "number") for number in (None, "", "9", 0, -1, True, 9.0, 10)],
        ({"url": "https://github.com/other/repo/pull/9"}, "repository_mismatch"),
        ({"url": "https://github.com/owner/other/pull/9"}, "repository_mismatch"),
        ({"url": "https://github.com/owner/repo/pull/10"}, "number_mismatch"),
        ({"url": None}, "repository_identity_unusable"),
        *[({"headRefOid": sha}, "head_sha_unusable") for sha in (None, "", " ", 123)],
    ],
)
def test_single_pr_hydration_refuses_wrong_identity(
    tmp_path: Path, capsys: Any, change: dict[str, Any], reason: str
) -> None:
    payload = {
        "number": 9,
        "url": "https://github.com/owner/repo/pull/9",
        "headRefOid": "a" * 40,
        "statusCheckRollup": [],
        **change,
    }
    row = github_pr_status.get_pr_status_graphql(
        9,
        repo="owner/repo",
        repo_root=tmp_path,
        runner=lambda cmd, **_: subprocess.CompletedProcess(cmd, 0, json.dumps(payload), ""),
    )
    assert row is None
    diagnostic = capsys.readouterr().err
    assert reason in diagnostic
    assert "Next action:" in diagnostic


def test_single_pr_hydration_returns_head_and_checks_from_one_read(tmp_path: Path) -> None:
    calls = []
    sha = "b" * 40

    def runner(cmd: list[str], **_: Any) -> subprocess.CompletedProcess:
        calls.append(cmd)
        payload = {
            "number": 9,
            "url": "https://github.com/Owner/Repo/pull/9",
            "headRefOid": sha if len(calls) == 1 else "c" * 40,
            "statusCheckRollup": [{"name": "test", "conclusion": "FAILURE"}],
        }
        return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")

    row = github_pr_status.get_pr_status_graphql(
        "9", repo="owner/repo", repo_root=tmp_path, runner=runner
    )
    assert row is not None and row["headRefOid"] == sha
    assert row["statusCheckRollup"] == [{"name": "test", "conclusion": "FAILURE"}]
    assert len(calls) == 1, "a second read could attach a moved head's checks to the first head"
    assert {"headRefOid", "statusCheckRollup", "url", "number"} <= set(calls[0][-1].split(","))


@pytest.mark.parametrize("moved", [False, True])
def test_single_pr_hydration_compares_expected_head(
    tmp_path: Path, capsys: Any, moved: bool
) -> None:
    row = github_pr_status.get_pr_status_graphql(
        9,
        repo="owner/repo",
        repo_root=tmp_path,
        expected_head_sha="a" * 40,
        runner=lambda cmd, **_: subprocess.CompletedProcess(
            cmd,
            0,
            json.dumps(
                {
                    "number": 9,
                    "url": "https://github.com/owner/repo/pull/9",
                    "headRefOid": ("b" if moved else "a") * 40,
                    "statusCheckRollup": [],
                }
            ),
            "",
        ),
    )
    if moved:
        assert row is None
        diagnostic = capsys.readouterr().err
        assert "head_sha_mismatch" in diagnostic and "Next action:" in diagnostic
    else:
        assert row is not None and row["headRefOid"] == "a" * 40


@pytest.mark.parametrize("reset", [None, 1893456000])
@pytest.mark.parametrize("head", [None, "feature/diagnostic"])
def test_open_prs_quota_refusal_is_actionable(
    tmp_path: Path, monkeypatch: Any, capsys: Any, reset: int | None, head: str | None
) -> None:
    def refused(*_: Any, **__: Any) -> Any:
        raise github_pr_status.RestPoolExhausted("github_rest_below_floor:0<500", reset)

    monkeypatch.setattr(github_pr_status, "list_open_pr_statuses_rest", refused)
    monkeypatch.setattr(github_pr_status, "list_pr_statuses_for_branch_rest", refused)
    args = ["open-prs", "--repo", "owner/repo", "--repo-root", str(tmp_path)]
    if head:
        args += ["--head", head]
    assert github_pr_status.main(args) == github_pr_status.GRAPHQL_BACKOFF_RC
    captured = capsys.readouterr()
    assert captured.out == "", "refusal must not emit a successful empty PR list"
    assert "github_rest_below_floor:0<500" in captured.err
    assert "Next action:" in captured.err and "GraphQL" in captured.err
    assert "gh pr view" in captured.err and "headRefOid,statusCheckRollup" in captured.err
    assert "wait" in captured.err
    assert ("2030-01-01T00:00:00+00:00" if reset else "reset time unknown") in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize("count", [None, True, -1, 1.5, "bad"])
def test_bulk_graphql_never_synthesizes_a_changed_file_count(tmp_path: Path, count: Any) -> None:
    base = _BothTransportsRunner(rest_remaining=0, graphql_remaining=4000)

    def runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        proc = base(cmd, **kwargs)
        if cmd[:3] == ["gh", "pr", "list"]:
            rows = json.loads(proc.stdout)
            rows[0]["changedFiles"] = count
            proc.stdout = json.dumps(rows)
        return proc

    rows = github_pr_status.list_open_pr_statuses_graphql(
        repo="owner/repo", repo_root=tmp_path, runner=runner, include_files=True
    )
    assert rows[0]["files"] == [{"path": "scripts/example.py"}]
    assert rows[0]["changedFiles"] is None


@pytest.mark.parametrize(
    "recovery, expected_count",
    [
        ({}, 2),
        ({"number": 10}, None),
        ({"url": "https://github.com/other/repo/pull/9"}, None),
        ({"headRefOid": "head-B"}, None),
        ({"changedFiles": None}, None),
        ({"changedFiles": True}, None),
        ({"changedFiles": -1}, None),
        ({"changedFiles": 1.5}, None),
        ({"changedFiles": "bad"}, None),
    ],
)
def test_rest_count_recovery_requires_independent_count_and_matching_identity(
    tmp_path: Path, recovery: dict[str, Any], expected_count: int | None
) -> None:
    base = _BothTransportsRunner(rest_remaining=4000, graphql_remaining=4000)

    def runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        proc = base(cmd, **kwargs)
        if cmd[:3] == ["gh", "pr", "view"]:
            assert "changedFiles" in cmd[-1].split(",")
            proc.stdout = json.dumps(
                {
                    "number": 9,
                    "url": "https://github.com/owner/repo/pull/9",
                    "headRefOid": "abc123",
                    "changedFiles": 2,
                    **recovery,
                }
            )
        elif cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6].endswith("/pulls/9"):
            pull = json.loads(proc.stdout)
            del pull["changed_files"]
            proc.stdout = json.dumps(pull)
        return proc

    rows = github_pr_status.list_open_pr_statuses_rest(
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
        include_files=True,
    )
    row = rows[0]
    assert row is not None and row["changedFiles"] == expected_count
    assert row["headRefOid"] == "abc123"
    assert row["files"] == [{"path": "scripts/example.py"}]


def test_missing_rest_count_stays_absent_when_graphql_pool_is_blocked(tmp_path: Path) -> None:
    base = _BothTransportsRunner(rest_remaining=4000, graphql_remaining=0)

    def runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        assert cmd[:3] != ["gh", "pr", "view"], "do not spend the exhausted GraphQL pool"
        proc = base(cmd, **kwargs)
        if cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6].endswith("/pulls/9"):
            pull = json.loads(proc.stdout)
            del pull["changed_files"]
            proc.stdout = json.dumps(pull)
        return proc

    rows = github_pr_status.list_open_pr_statuses_rest(
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
        include_files=True,
    )
    row = rows[0]
    assert row is not None and row["changedFiles"] is None
