"""Tests for ``scripts/queue-admission-proof-check.py``."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _load_module() -> ModuleType:
    if "queue_admission_proof_check" in sys.modules:
        return sys.modules["queue_admission_proof_check"]
    path = _SCRIPTS / "queue-admission-proof-check.py"
    spec = importlib.util.spec_from_file_location("queue_admission_proof_check", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["queue_admission_proof_check"] = module
    spec.loader.exec_module(module)
    return module


proof = _load_module()


class _FakeRunner:
    def __init__(self, statuses: list[dict[str, Any]]) -> None:
        self.statuses = statuses
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **_: Any) -> subprocess.CompletedProcess:
        self.calls.append(list(cmd))
        if cmd[:3] == ["gh", "api", "repos/owner/repo/pulls/42"]:
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"head": {"sha": "abc123"}}), "")
        if cmd[:3] == ["gh", "api", "repos/owner/repo/commits/abc123/statuses?per_page=100"]:
            return subprocess.CompletedProcess(cmd, 0, json.dumps(self.statuses), "")
        return subprocess.CompletedProcess(cmd, 1, "", "unexpected command")


def test_merge_group_ref_extracts_pr_numbers() -> None:
    assert proof.pr_numbers_from_ref("gh-readonly-queue/main/pr-3628-pr-3632-abcdef") == [
        3628,
        3632,
    ]


def test_pull_request_non_queue_action_is_not_enforced(tmp_path: Path) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps({"action": "synchronize", "pull_request": {"number": 42}}))

    prs, reason = proof.pr_numbers_from_event(
        event_name="pull_request",
        event_path=event_path,
        ref_name="feature",
        ref="refs/pull/42/merge",
    )

    assert prs == []
    assert reason == "pull_request action synchronize is not queue admission"


def test_fresh_success_status_passes() -> None:
    now = datetime(2026, 5, 21, 2, 0, tzinfo=UTC)
    runner = _FakeRunner(
        [
            {
                "context": proof.AUTOQUEUE_ADMISSION_CONTEXT,
                "state": "success",
                "created_at": "2026-05-21T01:55:00Z",
                "description": "cc-pr-autoqueue admitted: already_queued",
            }
        ]
    )

    failures = proof.validate_proofs(
        repo="owner/repo",
        prs=[42],
        ttl_seconds=600,
        now=now,
        runner=runner,
    )

    assert failures == []


def test_fetch_head_sha_falls_back_to_graphql_when_rest_pull_is_blocked() -> None:
    now = datetime(2026, 5, 21, 2, 0, tzinfo=UTC)
    calls: list[list[str]] = []

    def runner(cmd: list[str], **_: Any) -> subprocess.CompletedProcess:
        calls.append(list(cmd))
        if cmd[:3] == ["gh", "api", "repos/owner/repo/pulls/42"]:
            return subprocess.CompletedProcess(cmd, 1, "", "HTTP 403 secondary rate limit")
        if cmd[:3] == ["gh", "api", "rate_limit"]:
            payload = {"resources": {"graphql": {"remaining": 1000, "reset": 1893456000}}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        if cmd[:3] == ["gh", "api", "graphql"]:
            payload = {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "headRefOid": "abc123",
                        }
                    }
                }
            }
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        if cmd[:3] == ["gh", "api", "repos/owner/repo/commits/abc123/statuses?per_page=100"]:
            statuses = [
                {
                    "context": proof.AUTOQUEUE_ADMISSION_CONTEXT,
                    "state": "success",
                    "created_at": "2026-05-21T01:55:00Z",
                    "description": "cc-pr-autoqueue admitted: already_queued",
                }
            ]
            return subprocess.CompletedProcess(cmd, 0, json.dumps(statuses), "")
        return subprocess.CompletedProcess(cmd, 1, "", "unexpected command")

    failures = proof.validate_proofs(
        repo="owner/repo",
        prs=[42],
        ttl_seconds=600,
        now=now,
        runner=runner,
    )

    assert failures == []
    assert any(call[:3] == ["gh", "api", "graphql"] for call in calls)


def test_fetch_head_sha_fails_when_rest_and_graphql_are_blocked() -> None:
    def runner(cmd: list[str], **_: Any) -> subprocess.CompletedProcess:
        if cmd[:3] == ["gh", "api", "repos/owner/repo/pulls/42"]:
            return subprocess.CompletedProcess(cmd, 1, "", "HTTP 403 secondary rate limit")
        if cmd[:3] == ["gh", "api", "rate_limit"]:
            payload = {"resources": {"graphql": {"remaining": 1000, "reset": 1893456000}}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        if cmd[:3] == ["gh", "api", "graphql"]:
            return subprocess.CompletedProcess(cmd, 1, "", "graphql unavailable")
        return subprocess.CompletedProcess(cmd, 1, "", "unexpected command")

    try:
        proof.fetch_head_sha("owner/repo", 42, runner=runner)
    except RuntimeError as exc:
        assert "REST pull fetch failed" in str(exc)
        assert "GraphQL head fallback failed" in str(exc)
    else:
        raise AssertionError("fetch_head_sha should fail when both REST and GraphQL are blocked")


def test_missing_status_fails() -> None:
    failures = proof.validate_proofs(
        repo="owner/repo",
        prs=[42],
        ttl_seconds=600,
        now=datetime(2026, 5, 21, 2, 0, tzinfo=UTC),
        runner=_FakeRunner([]),
    )

    assert failures == ["PR #42: admission status is missing"]


def test_stale_status_fails() -> None:
    failures = proof.validate_proofs(
        repo="owner/repo",
        prs=[42],
        ttl_seconds=60,
        now=datetime(2026, 5, 21, 2, 0, tzinfo=UTC),
        runner=_FakeRunner(
            [
                {
                    "context": proof.AUTOQUEUE_ADMISSION_CONTEXT,
                    "state": "success",
                    "created_at": "2026-05-21T01:55:00Z",
                }
            ]
        ),
    )

    assert failures and failures[0].startswith("PR #42: admission status is stale")
