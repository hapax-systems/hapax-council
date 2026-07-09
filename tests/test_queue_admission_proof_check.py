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

import pytest

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
    def __init__(
        self,
        statuses: list[dict[str, Any]],
        *,
        graphql_fails: bool = False,
        graphql_semantic_error: bool = False,
    ) -> None:
        self.statuses = statuses
        self.graphql_fails = graphql_fails
        self.graphql_semantic_error = graphql_semantic_error
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **_: Any) -> subprocess.CompletedProcess:
        self.calls.append(list(cmd))
        if cmd[:3] == ["gh", "api", "graphql"]:
            if self.graphql_fails:
                return subprocess.CompletedProcess(cmd, 1, "", "graphql unavailable")
            if self.graphql_semantic_error:
                payload = {
                    "data": {"repository": None},
                    "errors": [{"message": "repository unavailable"}],
                }
                return subprocess.CompletedProcess(cmd, 1, json.dumps(payload), "GraphQL error")
            contexts = [
                {
                    "context": item.get("context"),
                    "state": str(item.get("state") or "").upper(),
                    "createdAt": item.get("created_at") or item.get("createdAt"),
                    "description": item.get("description", ""),
                }
                for item in self.statuses
            ]
            payload = {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "headRefOid": "abc123",
                            "commits": {
                                "nodes": [
                                    {
                                        "commit": {
                                            "oid": "abc123",
                                            "status": {"contexts": contexts},
                                        }
                                    }
                                ]
                            },
                        }
                    }
                }
            }
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
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
    assert runner.calls[0][:3] == ["gh", "api", "graphql"]
    assert not any("repos/owner/repo/pulls/42" in call for cmd in runner.calls for call in cmd)


def test_graphql_failure_falls_back_to_rest() -> None:
    now = datetime(2026, 5, 21, 2, 0, tzinfo=UTC)
    runner = _FakeRunner(
        [
            {
                "context": proof.AUTOQUEUE_ADMISSION_CONTEXT,
                "state": "success",
                "created_at": "2026-05-21T01:55:00Z",
                "description": "cc-pr-autoqueue admitted: already_queued",
            }
        ],
        graphql_fails=True,
    )

    failures = proof.validate_proofs(
        repo="owner/repo",
        prs=[42],
        ttl_seconds=600,
        now=now,
        runner=runner,
    )

    assert failures == []
    assert any(cmd[:3] == ["gh", "api", "repos/owner/repo/pulls/42"] for cmd in runner.calls)


def test_graphql_semantic_error_does_not_fall_back_to_rest() -> None:
    runner = _FakeRunner([], graphql_semantic_error=True)

    with pytest.raises(RuntimeError, match="GraphQL response contained errors"):
        proof.fetch_latest_proof("owner/repo", 42, runner=runner)

    assert runner.calls == [
        [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={proof._GRAPHQL_PROOF_QUERY}",
            "-f",
            "owner=owner",
            "-f",
            "name=repo",
            "-F",
            "number=42",
        ]
    ]


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
