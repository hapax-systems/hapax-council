"""Tests for ``scripts/cc-pr-autoqueue.py``."""

from __future__ import annotations

import fcntl
import importlib.util
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
import yaml

from shared.merge_queue_lineage import MergeQueueLineageRecord, write_jsonl_records

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _load_module() -> ModuleType:
    if "cc_pr_autoqueue" in sys.modules:
        return sys.modules["cc_pr_autoqueue"]
    path = _SCRIPTS / "cc-pr-autoqueue.py"
    spec = importlib.util.spec_from_file_location("cc_pr_autoqueue", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["cc_pr_autoqueue"] = module
    spec.loader.exec_module(module)
    return module


autoqueue = _load_module()


def test_task_lane_unwraps_platform_qualified_owner() -> None:
    task = SimpleNamespace(assigned_to="codex/cx-red", lane_affinity=None)
    assert autoqueue._task_lane(task) == "cx-red"


COMPLETE_ALWAYS_ON_CHECKLIST = {
    "tests-cover-the-diff": {
        "diff-behavior-coverage": "pass",
        "red-before-green": "na",
        "new-paths-tested": "pass",
        "no-coverage-theater": "pass",
    },
    "exit-predicate-adequacy": {
        "predicate-testable": "pass",
        "predicate-evidenced": "pass",
        "diff-matches-predicate": "pass",
        "witness-durability": "pass",
    },
    "doc-claims-recheck": {
        "recheck-cmds-present": "pass",
        "claims-match-code": "pass",
        "stale-docs-updated": "pass",
        "next-actions-on-error": "pass",
    },
}


@pytest.fixture(autouse=True)
def _review_team_gate_off(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Pre-gate admission tests run with the review-team gate off.

    The review-team quorum gate (review_team.review_team_verdict_blockers) is
    exercised explicitly by TestReviewTeamGate, which re-enables it per test.
    Route-receipt behavior is covered in tests/test_review_team.py; these
    generic autoqueue fixtures must not depend on live capability receipts.
    """

    monkeypatch.setenv("HAPAX_REVIEW_TEAM_GATE_OFF", "1")
    monkeypatch.setattr(
        autoqueue.review_team, "review_route_blocked_families", lambda *_a, **_k: {}
    )
    monkeypatch.setattr(
        autoqueue,
        "DEFAULT_OWNERSHIP_TRANSACTION_JOURNAL",
        tmp_path / ".cache" / "hapax" / "cc-ownership-txn.json",
    )


def _write_review_dossier(
    vault: Path,
    task_id: str,
    *,
    head_sha: str,
    pr: int = 42,
    verdict: str = "quorum-accept",
    reviewers: list[dict[str, Any]] | None = None,
    folder: str = "active",
) -> Path:
    if reviewers is None:
        reviewers = [
            {
                "id": "codex-1",
                "family": "codex",
                "verdict": "accept",
                "findings": [],
                "checklist": COMPLETE_ALWAYS_ON_CHECKLIST,
            },
            {
                "id": "claude-1",
                "family": "claude",
                "verdict": "accept",
                "findings": [],
                "checklist": COMPLETE_ALWAYS_ON_CHECKLIST,
            },
            {
                "id": "claude-2",
                "family": "claude",
                "verdict": "invalid-output",
                "findings": [],
                "checklist": {},
            },
        ]
    accepts = sum(1 for r in reviewers if r["verdict"] in ("accept", "accept-with-findings"))
    dossier = {
        "dossier_schema": 1,
        "task_id": task_id,
        "pr": pr,
        "head_sha": head_sha,
        "team_class": "t2_standard",
        "quorum_required": 2,
        "constituted_at": "2026-06-11T00:00:00+00:00",
        "constitution_notes": [],
        "lenses": list(COMPLETE_ALWAYS_ON_CHECKLIST),
        "reviewers": reviewers,
        "escalations": [],
        "accept_count": accepts,
        "review_team_verdict": verdict,
    }
    path = vault / folder / f"{task_id}.review-dossier.yaml"
    path.write_text(yaml.safe_dump(dossier, sort_keys=False), encoding="utf-8")
    return path


def _write_governance_review_dossier(vault: Path, task_id: str, pr: int) -> Path:
    return _write_review_dossier(vault, task_id, head_sha=f"sha-{pr}", pr=pr)


class TestReviewTeamGate:
    """Spec §5: a quorum-accept review dossier is an admission requirement."""

    def _classify(self, vault: Path, pr_payload: dict[str, Any]):
        pr = autoqueue._parse_pr(pr_payload)
        assert pr is not None
        tasks = autoqueue.load_task_notes(vault)
        return autoqueue.classify_pr(pr, tasks=tasks, queued_prs=set())

    def test_green_pr_without_dossier_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HAPAX_REVIEW_TEAM_GATE_OFF", raising=False)
        vault = _make_vault(tmp_path)
        _write_task(vault, task_id="task-a", pr=42)
        decision = self._classify(vault, _pr(42))
        assert decision.action == "blocked"
        assert "missing_review_dossier" in decision.reasons

    def test_green_pr_with_quorum_dossier_queues(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HAPAX_REVIEW_TEAM_GATE_OFF", raising=False)
        vault = _make_vault(tmp_path)
        _write_task(vault, task_id="task-a", pr=42)
        _write_review_dossier(vault, "task-a", head_sha="sha-42")
        decision = self._classify(vault, _pr(42))
        assert decision.action == "queue", decision.reasons

    def test_changed_file_scope_mismatch_blocks(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv("HAPAX_REVIEW_TEAM_GATE_OFF", raising=False)
        vault = _make_vault(tmp_path)
        _write_task(vault, task_id="task-a", pr=42)
        _write_review_dossier(vault, "task-a", head_sha="sha-42")
        decision = self._classify(vault, _pr(42, files=["scripts/review_team.py"]))
        assert decision.action == "blocked"
        assert (
            "review_dossier_team_class_scope_mismatch:t2_standard!=t1_critical" in decision.reasons
        )
        assert any(
            r.startswith("review_dossier_missing_required_lenses:") and "sdlc-gate-compose" in r
            for r in decision.reasons
        )

    def test_empty_changed_file_scope_blocks(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv("HAPAX_REVIEW_TEAM_GATE_OFF", raising=False)
        vault = _make_vault(tmp_path)
        _write_task(vault, task_id="task-a", pr=42)
        _write_review_dossier(vault, "task-a", head_sha="sha-42")
        decision = self._classify(vault, _pr(42, files=[]))
        assert decision.action == "blocked"
        assert "review_dossier_changed_files_unknown" in decision.reasons

    def test_truncated_changed_file_scope_blocks(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv("HAPAX_REVIEW_TEAM_GATE_OFF", raising=False)
        vault = _make_vault(tmp_path)
        _write_task(vault, task_id="task-a", pr=42)
        _write_review_dossier(vault, "task-a", head_sha="sha-42")
        decision = self._classify(
            vault,
            _pr(42, files=["shared/foo.py"], changed_files_count=101),
        )
        assert decision.action == "blocked"
        assert "review_dossier_changed_files_truncated:1/101" in decision.reasons

    def test_stale_dossier_blocks_after_push(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HAPAX_REVIEW_TEAM_GATE_OFF", raising=False)
        vault = _make_vault(tmp_path)
        _write_task(vault, task_id="task-a", pr=42)
        _write_review_dossier(vault, "task-a", head_sha="sha-OLD")
        decision = self._classify(vault, _pr(42))
        assert decision.action == "blocked"
        assert any(r.startswith("review_dossier_stale_head:") for r in decision.reasons)

    def test_no_quorum_dossier_blocks(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HAPAX_REVIEW_TEAM_GATE_OFF", raising=False)
        vault = _make_vault(tmp_path)
        _write_task(vault, task_id="task-a", pr=42)
        _write_review_dossier(
            vault,
            "task-a",
            head_sha="sha-42",
            verdict="no-quorum",
            reviewers=[
                {
                    "id": "codex-1",
                    "family": "codex",
                    "verdict": "accept",
                    "findings": [],
                    "checklist": COMPLETE_ALWAYS_ON_CHECKLIST,
                },
                {
                    "id": "codex-2",
                    "family": "codex",
                    "verdict": "invalid-output",
                    "findings": [],
                    "checklist": {},
                },
                {
                    "id": "claude-1",
                    "family": "claude",
                    "verdict": "invalid-output",
                    "findings": [],
                    "checklist": {},
                },
            ],
        )
        decision = self._classify(vault, _pr(42))
        assert decision.action == "blocked"
        assert "review_dossier_quorum_not_met:1/2" in decision.reasons

    def test_killswitch_admits_without_dossier(self, tmp_path: Path) -> None:
        # autouse fixture sets HAPAX_REVIEW_TEAM_GATE_OFF=1
        vault = _make_vault(tmp_path)
        _write_task(vault, task_id="task-a", pr=42)
        decision = self._classify(vault, _pr(42))
        assert decision.action == "queue", decision.reasons


def _recent_observed_at(index: int, *, total: int = 4) -> datetime:
    return datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=total - index)


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (vault / "active").mkdir(parents=True, exist_ok=True)
    (vault / "closed").mkdir(parents=True, exist_ok=True)
    return vault


def _write_task(
    vault: Path,
    *,
    task_id: str,
    folder: str = "active",
    status: str = "ready",
    pr: int | None = None,
    branch: str | None = None,
    authority_case: str | None = "CASE-TEST",
    parent_spec: str | None = "docs/spec.md",
    route_metadata_schema: int | None = 1,
    quality_floor: str | None = "frontier_required",
    mutation_surface: str | None = "source",
    authority_level: str | None = "authoritative",
    priority: str = "p2",
    kind: str = "implementation",
    assigned_to: str = "alpha",
    tags: list[str] | None = None,
    queue_admission: str | None = None,
    extra_frontmatter: dict[str, object] | None = None,
) -> Path:
    path = vault / folder / f"{task_id}.md"
    pr_line = f"pr: {pr}" if pr is not None else "pr: null"
    branch_line = f"branch: {branch}" if branch is not None else "branch: null"
    authority_line = (
        f"authority_case: {authority_case}"
        if authority_case is not None
        else "authority_case: null"
    )
    parent_line = f"parent_spec: {parent_spec}" if parent_spec is not None else "parent_spec: null"
    route_line = (
        f"route_metadata_schema: {route_metadata_schema}"
        if route_metadata_schema is not None
        else "route_metadata_schema: null"
    )
    quality_line = (
        f"quality_floor: {quality_floor}" if quality_floor is not None else "quality_floor: null"
    )
    mutation_line = (
        f"mutation_surface: {mutation_surface}"
        if mutation_surface is not None
        else "mutation_surface: null"
    )
    authority_level_line = (
        f"authority_level: {authority_level}"
        if authority_level is not None
        else "authority_level: null"
    )
    tags_line = f"tags: [{', '.join(tags or [])}]"
    queue_admission_line = (
        f"queue_admission: {queue_admission}"
        if queue_admission is not None
        else "queue_admission: null"
    )
    extra_lines = ""
    if extra_frontmatter:
        extra_lines = yaml.safe_dump(extra_frontmatter, sort_keys=False).strip() + "\n"
    path.write_text(
        f"""---
type: cc-task
task_id: {task_id}
title: "{task_id}"
status: {status}
assigned_to: {assigned_to}
priority: {priority}
kind: {kind}
{pr_line}
{branch_line}
{authority_line}
{parent_line}
{route_line}
{quality_line}
{mutation_line}
{authority_level_line}
{tags_line}
{queue_admission_line}
{extra_lines}---

# {task_id}

## Session log
""",
        encoding="utf-8",
    )
    return path


def _check(name: str, state: str = "SUCCESS") -> dict[str, Any]:
    return {"__typename": "CheckRun", "name": name, "conclusion": state}


def _pr(
    number: int,
    *,
    branch: str | None = None,
    title: str | None = None,
    files: list[str] | None = None,
    changed_files_count: int | None = None,
    body: str = "",
    draft: bool = False,
    merge_state: str = "CLEAN",
    checks: list[dict[str, Any]] | None = None,
    labels: list[str] | None = None,
    review_decision: str | None = None,
    auto_merge: bool = False,
) -> dict[str, Any]:
    file_list = ["shared/foo.py"] if files is None else files
    return {
        "number": number,
        "id": f"PR_test_{number}",
        "title": title or f"PR {number}",
        "body": body,
        "headRefName": branch or f"feat/{number}",
        "headRefOid": f"sha-{number}",
        "changedFiles": len(file_list) if changed_files_count is None else changed_files_count,
        "files": [{"path": path} for path in file_list],
        "isDraft": draft,
        "mergeStateStatus": merge_state,
        "labels": [{"name": label} for label in labels or []],
        "reviewDecision": review_decision,
        "autoMergeRequest": {"enabledAt": "now"} if auto_merge else None,
        "statusCheckRollup": checks
        if checks is not None
        else [
            _check("lint"),
            _check("test"),
            _check("typecheck"),
            _check("web-build"),
            _check("vscode-build"),
        ],
    }


class _FakeRunner:
    def __init__(self) -> None:
        self.open_prs: list[dict[str, Any]] = []
        self.queued_prs: set[int] = set()
        self.queue_refs: list[str] = []
        self.fail_queue_refs = False
        self.calls: list[list[str]] = []
        self.fail_status_posts = False
        # head_sha -> existing commit statuses (most-recent-first), for the G3
        # read-before-write idempotency check in set_autoqueue_admission_status.
        self.head_statuses: dict[str, list[dict[str, Any]]] = {}

    @staticmethod
    def _fields(cmd: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        index = 0
        while index < len(cmd):
            if cmd[index] == "-f" and index + 1 < len(cmd) and "=" in cmd[index + 1]:
                key, value = cmd[index + 1].split("=", 1)
                out[key] = value
                index += 2
                continue
            index += 1
        return out

    @staticmethod
    def _rest_pr(pr: dict[str, Any]) -> dict[str, Any]:
        labels = pr.get("labels") if isinstance(pr.get("labels"), list) else []
        merge_state = str(pr.get("mergeStateStatus") or "CLEAN").lower()
        return {
            "number": pr.get("number"),
            "node_id": pr.get("id"),
            "title": pr.get("title") or "",
            "body": pr.get("body") or "",
            "head": {"ref": pr.get("headRefName") or "", "sha": pr.get("headRefOid") or ""},
            "draft": bool(pr.get("isDraft")),
            "labels": labels,
            "auto_merge": pr.get("autoMergeRequest"),
            "mergeable_state": merge_state,
            "mergeable": merge_state in {"clean", "has_hooks", "unstable"},
            "changed_files": pr.get("changedFiles"),
            "state": "open",
            "merged": False,
            "merged_at": None,
        }

    @staticmethod
    def _rest_check_run(check: dict[str, Any]) -> dict[str, Any]:
        conclusion = check.get("conclusion")
        status = check.get("status")
        if status is None:
            status = "completed" if conclusion is not None else "in_progress"
        return {
            "name": check.get("name") or check.get("context") or "unnamed-check",
            "status": str(status).lower(),
            "conclusion": str(conclusion).lower() if conclusion is not None else None,
            "completed_at": check.get("completedAt")
            or check.get("completed_at")
            or "2026-07-05T00:00:00Z",
        }

    def _rest_pull_for_number(self, number: int) -> dict[str, Any] | None:
        pr = next((item for item in self.open_prs if item.get("number") == number), None)
        return self._rest_pr(pr) if pr is not None else None

    def _rest_response(self, cmd: list[str]) -> subprocess.CompletedProcess | None:
        if cmd[:5] != ["gh", "api", "--method", "GET", "-H"]:
            return None
        path = cmd[6]
        fields = self._fields(cmd)
        if path == "repos/owner/repo/pulls":
            rows = [self._rest_pr(pr) for pr in self.open_prs]
            head = fields.get("head")
            if head:
                branch = head.split(":", 1)[-1]
                rows = [row for row in rows if (row.get("head") or {}).get("ref") == branch]
            return subprocess.CompletedProcess(cmd, 0, json.dumps(rows), "")
        pull_match = re.fullmatch(r"repos/owner/repo/pulls/(\d+)", path)
        if pull_match:
            payload = self._rest_pull_for_number(int(pull_match.group(1)))
            if payload is None:
                return subprocess.CompletedProcess(cmd, 1, "", "PR not found")
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        files_match = re.fullmatch(r"repos/owner/repo/pulls/(\d+)/files", path)
        if files_match:
            pr = next(
                (item for item in self.open_prs if item.get("number") == int(files_match.group(1))),
                None,
            )
            files = pr.get("files") if isinstance(pr, dict) else []
            payload = [
                {"filename": entry.get("path")}
                for entry in files or []
                if isinstance(entry, dict) and entry.get("path")
            ]
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        reviews_match = re.fullmatch(r"repos/owner/repo/pulls/(\d+)/reviews", path)
        if reviews_match:
            pr = next(
                (
                    item
                    for item in self.open_prs
                    if item.get("number") == int(reviews_match.group(1))
                ),
                None,
            )
            decision = pr.get("reviewDecision") if isinstance(pr, dict) else None
            if decision is None:
                decision = "APPROVED"
            payload = [{"state": str(decision).lower(), "user": {"login": "reviewer"}}]
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        check_match = re.fullmatch(r"repos/owner/repo/commits/(.+)/check-runs", path)
        if check_match:
            ref = check_match.group(1)
            pr = next(
                (
                    item
                    for item in self.open_prs
                    if item.get("headRefOid") == ref or item.get("headRefName") == ref
                ),
                None,
            )
            checks = pr.get("statusCheckRollup") if isinstance(pr, dict) else []
            payload = {
                "check_runs": [
                    self._rest_check_run(check)
                    for check in checks or []
                    if isinstance(check, dict) and (check.get("name") or check.get("context"))
                ]
            }
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        status_match = re.fullmatch(r"repos/owner/repo/commits/(.+)/status", path)
        if status_match:
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"statuses": []}), "")
        return None

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
        rest = self._rest_response(cmd)
        if rest is not None:
            return rest
        if cmd[:3] == ["gh", "api", "graphql"] and any(
            "dequeuePullRequest" in part for part in cmd
        ):
            return subprocess.CompletedProcess(cmd, 0, '{"data":{"dequeuePullRequest":{}}}', "")
        if cmd[:4] == ["gh", "api", "-X", "POST"] and "/statuses/" in cmd[4]:
            if self.fail_status_posts:
                return subprocess.CompletedProcess(cmd, 1, "", "status post failed")
            return subprocess.CompletedProcess(cmd, 0, '{"state":"ok"}', "")
        if cmd[:3] == ["gh", "api", "graphql"]:
            nodes = [{"pullRequest": {"number": number}} for number in sorted(self.queued_prs)]
            payload = {
                "data": {
                    "repository": {
                        "mergeQueue": {
                            "entries": {
                                "nodes": nodes,
                            },
                        },
                    },
                },
            }
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        if (
            cmd[:2] == ["gh", "api"]
            and len(cmd) >= 3
            and cmd[2].endswith("/git/matching-refs/heads/gh-readonly-queue")
        ):
            if self.fail_queue_refs:
                return subprocess.CompletedProcess(cmd, 1, "", "queue refs unavailable")
            return subprocess.CompletedProcess(cmd, 0, "\n".join(self.queue_refs), "")
        if cmd[:3] == ["gh", "pr", "merge"]:
            return subprocess.CompletedProcess(cmd, 0, f"merged {cmd[3]}\n", "")
        if (
            cmd[:2] == ["gh", "api"]
            and len(cmd) == 3
            and "/commits/" in cmd[2]
            and cmd[2].endswith("/statuses")
        ):
            sha = cmd[2].split("/commits/", 1)[1].rsplit("/statuses", 1)[0]
            return subprocess.CompletedProcess(
                cmd, 0, json.dumps(self.head_statuses.get(sha, [])), ""
            )
        return subprocess.CompletedProcess(cmd, 1, "", "unexpected command")


class _GraphQLRollupOnRestIndeterminateRunner(_FakeRunner):
    def __init__(
        self,
        *,
        graphql_head_sha: str | None = None,
        graphql_rollup: list[dict[str, Any]] | None = None,
        graphql_error: bool = False,
    ) -> None:
        super().__init__()
        self.graphql_head_sha = graphql_head_sha
        self.graphql_rollup = graphql_rollup
        self.graphql_error = graphql_error

    def _rest_response(self, cmd: list[str]) -> subprocess.CompletedProcess | None:
        if cmd[:5] == ["gh", "api", "--method", "GET", "-H"]:
            path = cmd[6]
            if re.fullmatch(r"repos/owner/repo/commits/(.+)/(check-runs|status)", path):
                return subprocess.CompletedProcess(cmd, 1, "", "secondary rate limit")
        return super()._rest_response(cmd)

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:3] == ["gh", "api", "graphql"] and any("statusCheckRollup" in part for part in cmd):
            self.calls.append(list(cmd))
            if self.graphql_error:
                return subprocess.CompletedProcess(cmd, 1, "", "graphql unavailable")
            pr = self.open_prs[0] if self.open_prs else _pr(0)
            head_sha = self.graphql_head_sha or str(pr.get("headRefOid") or "")
            rollup = (
                self.graphql_rollup
                if self.graphql_rollup is not None
                else pr.get("statusCheckRollup") or []
            )
            payload = {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "headRefOid": head_sha,
                            "commits": {
                                "nodes": [
                                    {
                                        "commit": {
                                            "oid": head_sha,
                                            "statusCheckRollup": {
                                                "contexts": {"nodes": rollup},
                                            },
                                        }
                                    }
                                ]
                            },
                        }
                    }
                }
            }
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        return super().__call__(cmd, **kwargs)


def test_fetch_pr_release_evidence_rejects_non_json_success(tmp_path: Path) -> None:
    def runner(cmd: list[str], **_: Any) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(cmd, 0, "not json", "")

    ok, message, checks = autoqueue.fetch_pr_release_evidence(
        42,
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
    )

    assert ok is False
    assert message == "invalid_pr_release_evidence_payload"
    assert checks == set()


def test_fetch_pr_release_evidence_falls_back_to_graphql_when_rest_pull_indeterminate(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def runner(cmd: list[str], **_: Any) -> subprocess.CompletedProcess:
        calls.append(list(cmd))
        if cmd[:5] == ["gh", "api", "--method", "GET", "-H"]:
            return subprocess.CompletedProcess(cmd, 1, "", "secondary rate limit")
        if cmd[:3] == ["gh", "api", "rate_limit"]:
            payload = {"resources": {"graphql": {"remaining": 1000, "reset": 1893456000}}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        if cmd[:3] == ["gh", "api", "graphql"]:
            payload = {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "headRefOid": "sha-42",
                            "commits": {
                                "nodes": [
                                    {
                                        "commit": {
                                            "oid": "sha-42",
                                            "statusCheckRollup": {
                                                "contexts": {
                                                    "nodes": [
                                                        {
                                                            "__typename": "CheckRun",
                                                            "name": "authority-case-check",
                                                            "status": "COMPLETED",
                                                            "conclusion": "SUCCESS",
                                                        }
                                                    ]
                                                }
                                            },
                                        }
                                    }
                                ]
                            },
                        }
                    }
                }
            }
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        return subprocess.CompletedProcess(cmd, 1, "", "unexpected command")

    ok, sha, checks = autoqueue.fetch_pr_release_evidence(
        42,
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
    )

    assert ok is True
    assert sha == "sha-42"
    assert checks == {"authority-case-check"}
    assert any(call[:3] == ["gh", "api", "graphql"] for call in calls)


def test_fetch_status_rollup_falls_back_to_graphql_when_rest_indeterminate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_rest_rollup(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "name": autoqueue.REST_INDETERMINATE_CHECK_NAME,
                "status": "PENDING",
                "conclusion": None,
            }
        ]

    monkeypatch.setattr(autoqueue, "fetch_status_check_rollup_rest", fake_rest_rollup)

    def runner(cmd: list[str], **_: Any) -> subprocess.CompletedProcess:
        calls.append(list(cmd))
        if cmd[:3] == ["gh", "api", "rate_limit"]:
            payload = {"resources": {"graphql": {"remaining": 1000, "reset": 1893456000}}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        if cmd[:3] == ["gh", "api", "graphql"]:
            payload = {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "headRefOid": "sha-graph",
                            "commits": {
                                "nodes": [
                                    {
                                        "commit": {
                                            "oid": "sha-graph",
                                            "statusCheckRollup": {
                                                "contexts": {
                                                    "nodes": [
                                                        {
                                                            "__typename": "CheckRun",
                                                            "name": "lint",
                                                            "status": "COMPLETED",
                                                            "conclusion": "SUCCESS",
                                                            "completedAt": "2026-07-07T21:45:00Z",
                                                        },
                                                        {
                                                            "__typename": "CheckRun",
                                                            "name": "test",
                                                            "status": "COMPLETED",
                                                            "conclusion": "SUCCESS",
                                                            "completedAt": "2026-07-07T21:46:00Z",
                                                        },
                                                    ]
                                                }
                                            },
                                        }
                                    }
                                ]
                            },
                        }
                    }
                }
            }
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        return subprocess.CompletedProcess(cmd, 1, "", "unexpected command")

    rollup = autoqueue._fetch_status_check_rollup(
        701,
        head_sha="sha-graph",
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
    )
    summary = autoqueue.summarize_checks(rollup)

    assert {"lint", "test"} <= summary.observed
    assert autoqueue.REST_INDETERMINATE_CHECK_NAME not in summary.observed
    assert any(call[:3] == ["gh", "api", "graphql"] for call in calls)


def test_fetch_status_rollup_keeps_rest_indeterminate_when_graphql_head_mismatches(
    tmp_path: Path,
) -> None:
    runner = _GraphQLRollupOnRestIndeterminateRunner(graphql_head_sha="sha-other")
    runner.open_prs = [_pr(701)]

    rollup = autoqueue._fetch_status_check_rollup(
        701,
        head_sha="sha-701",
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
    )
    summary = autoqueue.summarize_checks(rollup)

    assert summary.observed == {autoqueue.REST_INDETERMINATE_CHECK_NAME}
    assert any(call[:3] == ["gh", "api", "graphql"] for call in runner.calls)


def test_fetch_pr_release_evidence_fails_closed_when_rest_and_graphql_unreadable(
    tmp_path: Path,
) -> None:
    runner = _GraphQLRollupOnRestIndeterminateRunner(graphql_error=True)
    runner.open_prs = [_pr(702)]

    ok, message, checks = autoqueue.fetch_pr_release_evidence(
        702,
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
    )

    assert ok is False
    assert message == "invalid_status_check_rollup"
    assert checks == set()
    assert any(call[:3] == ["gh", "api", "graphql"] for call in runner.calls)


def test_fetch_pr_release_evidence_rejects_missing_head_oid(tmp_path: Path) -> None:
    def runner(cmd: list[str], **_: Any) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(
            cmd,
            0,
            json.dumps({"headRefOid": None, "statusCheckRollup": []}),
            "",
        )

    ok, message, checks = autoqueue.fetch_pr_release_evidence(
        42,
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
    )

    assert ok is False
    assert message == "missing_head_sha"
    assert checks == set()


def test_fetch_pr_release_evidence_bypasses_status_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _FakeRunner()
    runner.open_prs = [_pr(42)]
    observed: dict[str, object] = {}

    def fake_rollup(
        ref: str,
        *,
        repo: str,
        repo_root: Path,
        runner: Any,
        use_cache: bool | None = None,
    ) -> list[dict[str, Any]]:
        observed["ref"] = ref
        observed["use_cache"] = use_cache
        return [_check("authority-case-check")]

    monkeypatch.setattr(autoqueue, "fetch_status_check_rollup_rest", fake_rollup)

    ok, sha, checks = autoqueue.fetch_pr_release_evidence(
        42,
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
    )

    assert ok is True
    assert sha == "sha-42"
    assert checks == {"authority-case-check"}
    assert observed == {"ref": "sha-42", "use_cache": False}


def test_fetch_open_prs_uses_rest_core_not_gh_pr_list(tmp_path: Path) -> None:
    runner = _FakeRunner()
    runner.open_prs = [_pr(42)]

    prs = autoqueue.fetch_open_prs(repo="owner/repo", repo_root=tmp_path, runner=runner)

    assert [pr.number for pr in prs] == [42]
    assert any(
        call[:5] == ["gh", "api", "--method", "GET", "-H"] and call[6] == "repos/owner/repo/pulls"
        for call in runner.calls
    )
    assert not any(call[:3] == ["gh", "pr", "list"] for call in runner.calls)
    assert not any(call[:3] == ["gh", "pr", "view"] for call in runner.calls)


def test_empty_rest_reviews_do_not_synthesize_review_required(tmp_path: Path) -> None:
    class EmptyReviewsRunner(_FakeRunner):
        def _rest_response(self, cmd: list[str]) -> subprocess.CompletedProcess | None:
            if cmd[:5] == ["gh", "api", "--method", "GET", "-H"]:
                path = cmd[6]
                if re.fullmatch(r"repos/owner/repo/pulls/\d+/reviews", path):
                    return subprocess.CompletedProcess(cmd, 0, json.dumps([]), "")
            return super()._rest_response(cmd)

    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="task-a", pr=42)
    runner = EmptyReviewsRunner()
    runner.open_prs = [_pr(42)]

    prs = autoqueue.fetch_open_prs(repo="owner/repo", repo_root=tmp_path, runner=runner)
    assert prs[0].review_decision is None

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=False,
        runner=runner,
    )

    assert report["counts"]["queue"] == 1
    assert "review_decision:REVIEW_REQUIRED" not in report["decisions"][0].get("reasons", [])


def test_graphql_backoff_skips_autoqueue_reconciler(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="task-a", pr=42)

    class _LowGraphQLRunner(_FakeRunner):
        def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            if cmd[:3] == ["gh", "api", "rate_limit"]:
                self.calls.append(list(cmd))
                payload = {"resources": {"graphql": {"remaining": 0, "reset": 1893456000}}}
                return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
            return super().__call__(cmd, **kwargs)

    runner = _LowGraphQLRunner()
    runner.open_prs = [_pr(42)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["skipped"] is True
    assert report["reason"] == "merge_queue_state_indeterminate"
    assert not any(call[:3] == ["gh", "api", "graphql"] for call in runner.calls)


def test_review_required_rest_decision_blocks_autoqueue(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="task-a", pr=42)
    runner = _FakeRunner()
    runner.open_prs = [_pr(42, review_decision="REVIEW_REQUIRED")]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["blocked"] == 1
    assert "review_decision:REVIEW_REQUIRED" in report["decisions"][0]["reasons"]
    assert not any(call[:3] == ["gh", "pr", "merge"] for call in runner.calls)


def test_queue_green_governed_pr(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="task-a", pr=42)
    runner = _FakeRunner()
    runner.open_prs = [_pr(42)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["queue"] == 1
    assert report["mutations"][0]["ok"] is True
    assert any(
        call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-42"]
        and f"context={autoqueue.AUTOQUEUE_ADMISSION_CONTEXT}" in call
        and "state=success" in call
        for call in runner.calls
    )
    assert ["gh", "pr", "merge", "42", "--repo", "owner/repo", "--auto", "--squash"] in runner.calls


def test_reconciler_falls_back_to_graphql_when_rest_rollup_indeterminate(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="task-a", pr=4455)
    runner = _GraphQLRollupOnRestIndeterminateRunner()
    runner.open_prs = [_pr(4455)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        required_checks=("lint", "test", "typecheck", "web-build", "vscode-build"),
        runner=runner,
    )

    decision = report["decisions"][0]
    assert report["counts"]["queue"] == 1
    assert not any(
        reason.startswith("missing_required_checks:") for reason in decision.get("reasons", [])
    )
    assert [
        "gh",
        "pr",
        "merge",
        "4455",
        "--repo",
        "owner/repo",
        "--auto",
        "--squash",
    ] in runner.calls
    assert any(
        call[:3] == ["gh", "api", "graphql"] and any("statusCheckRollup" in part for part in call)
        for call in runner.calls
    )


def test_does_not_queue_when_admission_status_write_fails(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="task-a", pr=142)
    runner = _FakeRunner()
    runner.open_prs = [_pr(142)]

    def failing_runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        if cmd[:4] == ["gh", "api", "-X", "POST"] and "/statuses/" in cmd[4]:
            return subprocess.CompletedProcess(cmd, 1, "", "status denied")
        return runner(cmd, **kwargs)

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=failing_runner,
    )

    assert report["mutations"][0]["ok"] is False
    assert report["mutations"][0]["admission_status"]["ok"] is False
    assert not any(call[:4] == ["gh", "pr", "merge", "142"] for call in runner.calls)


def test_enable_auto_merge_for_pending_governed_pr(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="task-a", pr=43)
    runner = _FakeRunner()
    runner.open_prs = [
        _pr(
            43,
            checks=[
                _check("lint"),
                {"name": "test", "status": "IN_PROGRESS"},
                _check("typecheck"),
                _check("web-build"),
                _check("vscode-build"),
            ],
        )
    ]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["enable_auto_merge"] == 1
    assert ["gh", "pr", "merge", "43", "--repo", "owner/repo", "--auto", "--squash"] in runner.calls


def test_enable_auto_merge_for_unknown_pending_governed_pr(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="task-a", pr=44)
    runner = _FakeRunner()
    runner.open_prs = [
        _pr(
            44,
            merge_state="UNKNOWN",
            checks=[
                _check("lint"),
                {"name": "test", "status": "IN_PROGRESS"},
                _check("typecheck"),
                _check("web-build"),
                _check("vscode-build"),
            ],
        )
    ]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["enable_auto_merge"] == 1
    assert ["gh", "pr", "merge", "44", "--repo", "owner/repo", "--auto", "--squash"] in runner.calls


def test_blocks_unknown_merge_state_without_pending_checks(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="task-a", pr=45)
    runner = _FakeRunner()
    runner.open_prs = [_pr(45, merge_state="UNKNOWN")]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["blocked"] == 1
    assert "merge_state:UNKNOWN" in report["decisions"][0]["reasons"]
    assert not any(call[:4] == ["gh", "pr", "merge", "45"] for call in runner.calls)


def test_blocks_failed_dirty_draft_and_hold_prs(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    for number in (1, 2, 3, 4):
        _write_task(vault, task_id=f"task-{number}", pr=number)
    runner = _FakeRunner()
    runner.open_prs = [
        _pr(1, checks=[_check("lint", "FAILURE")]),
        _pr(2, merge_state="DIRTY"),
        _pr(3, draft=True),
        _pr(4, labels=["do-not-merge"]),
    ]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["blocked"] == 4
    assert not any(call[:4] == ["gh", "pr", "merge", "1"] for call in runner.calls)
    reasons = {item["pr"]: item["reasons"] for item in report["decisions"]}
    assert any(reason.startswith("failed_checks:") for reason in reasons[1])
    assert "merge_state:DIRTY" in reasons[2]
    assert "draft" in reasons[3]
    assert "hold_labels:do-not-merge" in reasons[4]


def test_ignores_failed_non_required_advisory_check(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="task-a", pr=47)
    runner = _FakeRunner()
    runner.open_prs = [
        _pr(
            47,
            checks=[
                _check("lint"),
                _check("test"),
                _check("typecheck"),
                _check("web-build"),
                _check("vscode-build"),
                _check("hkp-advisory", "FAILURE"),
            ],
        )
    ]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["queue"] == 1
    assert not report["decisions"][0].get("reasons")
    assert any(call[:4] == ["gh", "pr", "merge", "47"] for call in runner.calls)


def test_ignores_prior_autoqueue_admission_checks_when_classifying_checks(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="task-a", pr=49)
    runner = _FakeRunner()
    runner.open_prs = [
        _pr(
            49,
            checks=[
                _check("lint"),
                _check("test"),
                _check("typecheck"),
                _check("web-build"),
                _check("vscode-build"),
                {
                    "__typename": "StatusContext",
                    "context": autoqueue.AUTOQUEUE_ADMISSION_CONTEXT,
                    "state": "FAILURE",
                },
                {
                    "__typename": "CheckRun",
                    "name": "pr-admission",
                    "conclusion": "FAILURE",
                },
            ],
        )
    ]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["queue"] == 1
    assert not report["decisions"][0].get("reasons")
    assert any(
        call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-49"]
        and f"context={autoqueue.AUTOQUEUE_ADMISSION_CONTEXT}" in call
        and "state=success" in call
        for call in runner.calls
    )


def test_ignores_governance_gate_admission_mirror_failure(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="task-a", pr=48)
    runner = _FakeRunner()
    runner.open_prs = [
        _pr(
            48,
            checks=[
                _check("lint"),
                _check("test"),
                _check("typecheck"),
                _check("web-build"),
                _check("vscode-build"),
                {
                    "__typename": "CheckRun",
                    "name": "governance-gate",
                    "conclusion": "FAILURE",
                    "completedAt": "2026-06-04T12:53:21Z",
                },
            ],
        )
    ]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["queue"] == 1
    assert not report["decisions"][0].get("reasons")
    assert any(
        call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-48"]
        and f"context={autoqueue.AUTOQUEUE_ADMISSION_CONTEXT}" in call
        and "state=success" in call
        for call in runner.calls
    )


def test_uses_latest_duplicate_check_context_when_classifying_checks(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="task-a", pr=50)
    runner = _FakeRunner()
    runner.open_prs = [
        _pr(
            50,
            checks=[
                {
                    "__typename": "CheckRun",
                    "name": "governance-gate",
                    "conclusion": "FAILURE",
                    "completedAt": "2026-06-04T12:03:43Z",
                },
                {
                    "__typename": "CheckRun",
                    "name": "pr-admission",
                    "conclusion": "FAILURE",
                    "completedAt": "2026-06-04T12:03:41Z",
                },
                {
                    "__typename": "CheckRun",
                    "name": "governance-gate",
                    "conclusion": "SUCCESS",
                    "completedAt": "2026-06-04T12:05:18Z",
                },
                {
                    "__typename": "CheckRun",
                    "name": "pr-admission",
                    "conclusion": "SUCCESS",
                    "completedAt": "2026-06-04T12:05:17Z",
                },
                _check("lint"),
                _check("test"),
                _check("typecheck"),
                _check("web-build"),
                _check("vscode-build"),
            ],
        )
    ]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["queue"] == 1
    assert not report["decisions"][0].get("reasons")


def test_blocks_missing_or_legacy_task_metadata(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="legacy", pr=50, route_metadata_schema=None)
    runner = _FakeRunner()
    runner.open_prs = [_pr(50), _pr(51)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        runner=runner,
    )

    reasons = {item["pr"]: item["reasons"] for item in report["decisions"]}
    assert "task_missing_route_metadata_schema_1" in reasons[50]
    assert "missing_cc_task_link" in reasons[51]


def test_blocks_closed_task_linked_to_open_pr(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="false-closed", folder="closed", status="done", pr=54)
    runner = _FakeRunner()
    runner.open_prs = [_pr(54)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        runner=runner,
    )

    assert report["counts"]["blocked"] == 1
    assert "closed_task_closure_invalid:pr_open:54" in report["decisions"][0]["reasons"]


def test_blocks_closed_task_with_unchecked_acceptance_criteria_and_open_pr(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    task_path = _write_task(
        vault,
        task_id="unchecked-closed",
        folder="closed",
        status="done",
        pr=None,
        branch="feat/unchecked",
    )
    task_path.write_text(
        task_path.read_text(encoding="utf-8")
        + "\n## Acceptance criteria\n\n- [ ] Closure evidence exists\n",
        encoding="utf-8",
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(57, branch="feat/unchecked")]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        runner=runner,
    )

    assert report["counts"]["blocked"] == 1
    reasons = report["decisions"][0]["reasons"]
    assert (
        "closed_task_closure_invalid:unchecked_acceptance_criteria:Closure evidence exists"
        in reasons
    )
    assert "closed_task_linked_to_open_pr_without_pr_field:57" in reasons


def test_blocks_avsdlc_impacted_task_without_release_evidence(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="audio-task",
        pr=52,
        extra_frontmatter={"avsdlc_axes": ["audio"]},
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(52)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        runner=runner,
    )

    assert report["counts"]["blocked"] == 1
    reasons = report["decisions"][0]["reasons"]
    assert "avsdlc_release_gate:missing:avsdlc_dossier" in reasons
    assert "avsdlc_release_gate:missing:audio_witness" in reasons


def test_queues_avsdlc_impacted_task_with_fresh_release_evidence(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="audio-task",
        pr=53,
        extra_frontmatter={
            "avsdlc_axes": ["audio"],
            "avsdlc_dossier": "docs/evidence/audio.md",
            "audio_witness": "artifacts/lufs.json",
            "avsdlc_evidence_collected_at": 4102444800,
        },
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(53)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        runner=runner,
    )

    assert report["counts"]["queue"] == 1
    assert "reasons" not in report["decisions"][0]


def test_blocks_unchecked_pr_checklist_items(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="costed-validation", pr=55)
    runner = _FakeRunner()
    runner.open_prs = [
        _pr(
            55,
            body="- [x] CI green\n- [ ] Full validation run (operator-triggered, ~$3 cost)\n",
        )
    ]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        runner=runner,
    )

    assert report["counts"]["blocked"] == 1
    assert any(
        reason.startswith("unchecked_pr_checklist:") for reason in report["decisions"][0]["reasons"]
    )


def test_blocks_closed_task_linked_to_still_open_pr(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="premature-close", folder="closed", status="done", pr=57)
    runner = _FakeRunner()
    runner.open_prs = [_pr(57)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        runner=runner,
    )

    assert report["counts"]["blocked"] == 1
    assert "closed_task_closure_invalid:pr_open:57" in report["decisions"][0]["reasons"]


def test_blocks_closed_task_linked_by_branch_without_pr_field(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    task = _write_task(vault, task_id="unchecked-close", folder="closed", status="done", pr=58)
    task.write_text(
        task.read_text(encoding="utf-8")
        + "\n## Acceptance criteria\n\n- [x] Deterministic tests pass\n- [ ] Runtime witness accepted\n",
        encoding="utf-8",
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(58)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        runner=runner,
    )

    assert report["counts"]["blocked"] == 1
    reasons = report["decisions"][0]["reasons"]
    assert (
        "closed_task_closure_invalid:unchecked_acceptance_criteria:Runtime witness accepted"
        in reasons
    )
    assert "closed_task_closure_invalid:pr_open:58" in reasons


def test_blocks_closed_task_with_malformed_route_metadata(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="bad-route-close",
        folder="closed",
        status="done",
        pr=59,
        quality_floor="frontier_review_required",
        authority_level="authoritative",
        mutation_surface="source",
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(59)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        runner=runner,
    )

    assert report["counts"]["blocked"] == 1
    assert any(
        reason.startswith("closed_task_closure_invalid:route_metadata:")
        for reason in report["decisions"][0]["reasons"]
    )


def test_allows_optional_unchecked_pr_checklist_items(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="optional-validation", pr=56)
    runner = _FakeRunner()
    runner.open_prs = [_pr(56, body="- [ ] Optional benchmark rerun\n")]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        runner=runner,
    )

    assert report["counts"]["queue"] == 1


def test_branch_link_can_identify_task_when_pr_frontmatter_missing(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="branch-task", branch="alpha/branch-task")
    runner = _FakeRunner()
    runner.open_prs = [_pr(60, branch="alpha/branch-task")]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        runner=runner,
    )

    assert report["counts"]["queue"] == 1
    assert report["decisions"][0]["task_id"] == "branch-task"


def test_skips_prs_already_in_queue_or_auto_merge_enabled(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="queued", pr=70)
    _write_task(vault, task_id="armed", pr=71)
    runner = _FakeRunner()
    runner.queued_prs = {70}
    runner.open_prs = [_pr(70), _pr(71, auto_merge=True)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["already_queued"] == 1
    assert report["counts"]["already_auto_merge_enabled"] == 1
    assert not any(call[:3] == ["gh", "pr", "merge"] for call in runner.calls)


def test_gh_readonly_queue_ref_marks_pr_already_queued_when_graphql_empty(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="queue-ref", pr=4296)
    runner = _FakeRunner()
    runner.queue_refs = ["refs/heads/gh-readonly-queue/main/pr-4296-deadbeef"]
    runner.open_prs = [_pr(4296)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["already_queued"] == 1
    assert report["decisions"][0]["action"] == "already_queued"
    assert any(
        call[:2] == ["gh", "api"]
        and len(call) >= 3
        and call[2] == "repos/owner/repo/git/matching-refs/heads/gh-readonly-queue"
        for call in runner.calls
    )
    assert not any(call[:3] == ["gh", "pr", "merge"] for call in runner.calls)


def test_merge_queue_ref_numbers_returns_empty_set_when_matching_refs_fails(
    tmp_path: Path,
) -> None:
    runner = _FakeRunner()
    runner.fail_queue_refs = True
    runner.queue_refs = ["refs/heads/gh-readonly-queue/main/pr-4296-deadbeef"]

    queued = autoqueue._merge_queue_ref_pr_numbers(
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
    )

    assert queued == set()
    assert any(
        call[:2] == ["gh", "api"]
        and len(call) >= 3
        and call[2] == "repos/owner/repo/git/matching-refs/heads/gh-readonly-queue"
        for call in runner.calls
    )


def test_merge_queue_status_is_ready_for_already_queued_pr(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="queued-status", folder="active", status="merge_queue", pr=72)
    runner = _FakeRunner()
    runner.queued_prs = {72}
    runner.open_prs = [_pr(72)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["already_queued"] == 1
    assert not any(
        call[:3] == ["gh", "api", "graphql"] and any("dequeuePullRequest" in part for part in call)
        for call in runner.calls
    )


def test_allows_already_queued_pr_with_multiple_ready_task_links(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="queued-primary", folder="active", status="merge_queue", pr=73)
    _write_task(vault, task_id="queued-fix", folder="active", status="ready", pr=73)
    runner = _FakeRunner()
    runner.queued_prs = {73}
    runner.open_prs = [_pr(73)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["already_queued"] == 1
    assert report["decisions"][0]["task_ids"] == ["queued-fix", "queued-primary"]
    assert "reasons" not in report["decisions"][0]
    assert not any(
        call[:3] == ["gh", "api", "graphql"] and any("dequeuePullRequest" in part for part in call)
        for call in runner.calls
    )


def test_queues_pr_with_multiple_ready_task_links(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="primary", folder="active", status="merge_queue", pr=74)
    _write_task(vault, task_id="followup", folder="active", status="ready", pr=74)
    runner = _FakeRunner()
    runner.open_prs = [_pr(74)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["queue"] == 1
    assert report["decisions"][0]["task_ids"] == ["followup", "primary"]
    assert ["gh", "pr", "merge", "74", "--repo", "owner/repo", "--auto", "--squash"] in runner.calls


def test_dequeues_multiple_task_links_when_any_task_missing_metadata(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="valid", folder="active", status="merge_queue", pr=75)
    _write_task(
        vault,
        task_id="missing-route",
        folder="active",
        status="ready",
        pr=75,
        route_metadata_schema=None,
    )
    runner = _FakeRunner()
    runner.queued_prs = {75}
    runner.open_prs = [_pr(75)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["dequeue"] == 1
    assert (
        "task_blocker:missing-route:task_missing_route_metadata_schema_1"
        in report["decisions"][0]["reasons"]
    )
    assert any(
        call[:3] == ["gh", "api", "graphql"] and any("dequeuePullRequest" in part for part in call)
        for call in runner.calls
    )


def test_blocks_multiple_task_links_when_any_task_not_ready(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="valid", folder="active", status="merge_queue", pr=76)
    _write_task(vault, task_id="not-ready", folder="active", status="claimed", pr=76)
    runner = _FakeRunner()
    runner.open_prs = [_pr(76)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["blocked"] == 1
    assert (
        "task_blocker:not-ready:active_task_status_not_ready:claimed"
        in report["decisions"][0]["reasons"]
    )
    assert not any(call[:4] == ["gh", "pr", "merge", "76"] for call in runner.calls)


def test_dequeues_queued_pr_that_loses_governance_gate(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="queued", pr=77, authority_case=None)
    runner = _FakeRunner()
    runner.queued_prs = {77}
    runner.open_prs = [_pr(77, merge_state="UNKNOWN", checks=[_check("lint")])]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["dequeue"] == 1
    assert report["mutations"][0]["ok"] is True
    assert any(
        call[:3] == ["gh", "api", "graphql"] and any("dequeuePullRequest" in part for part in call)
        for call in runner.calls
    )


def test_disables_auto_merge_when_armed_pr_is_now_blocked(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="blocked-armed", pr=80)
    runner = _FakeRunner()
    runner.open_prs = [_pr(80, auto_merge=True, checks=[_check("lint", "FAILURE")])]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["disable_auto_merge"] == 1
    assert report["mutations"][0]["admission_status"]["state"] == "failure"
    assert ["gh", "pr", "merge", "80", "--repo", "owner/repo", "--disable-auto"] in runner.calls


def test_disables_auto_merge_when_required_checks_are_absent(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="missing-required", pr=81)
    runner = _FakeRunner()
    runner.open_prs = [_pr(81, auto_merge=True, checks=[_check("CodeQL")])]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        required_checks=("lint", "test"),
        runner=runner,
    )

    assert report["counts"]["disable_auto_merge"] == 1
    assert "missing_required_checks:lint,test" in report["decisions"][0]["reasons"]
    assert ["gh", "pr", "merge", "81", "--repo", "owner/repo", "--disable-auto"] in runner.calls


def test_dequeues_queued_pr_when_required_checks_are_absent(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="queued-missing-required", pr=82)
    runner = _FakeRunner()
    runner.queued_prs = {82}
    runner.open_prs = [_pr(82, checks=[_check("CodeQL")])]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        required_checks=("lint", "test"),
        runner=runner,
    )

    assert report["counts"]["dequeue"] == 1
    assert "missing_required_checks:lint,test" in report["decisions"][0]["reasons"]
    assert any(
        call[:3] == ["gh", "api", "graphql"] and any("dequeuePullRequest" in part for part in call)
        for call in runner.calls
    )


def test_writes_stable_report_with_verbatim_governor_and_blockers(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="blocked-task", pr=84, status="claimed")
    runner = _FakeRunner()
    runner.open_prs = [_pr(84)]
    governor_path = tmp_path / "pr-admission-governor.yaml"
    governor_raw = {
        "mode": "frozen",
        "updated": "2026-06-12T00:00:00Z",
        "set_by": "auto",
        "reason": "auto-freeze: fixture reason",
        "entry_open_pr_count": 12,
        "exit_below_count": 5,
        "exit_stable_ticks_required": 3,
        "stable_ticks_observed": 2,
        "allowed_existing_branches": ["feat/84"],
    }
    governor_path.write_text(yaml.safe_dump(governor_raw, sort_keys=False), encoding="utf-8")
    report_path = tmp_path / "orchestration" / "cc-pr-autoqueue-report.json"

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        runner=runner,
        report_path=report_path,
        admission_governor_path=governor_path,
    )

    assert report["stable_report"]["written"] is True
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == autoqueue.AUTOQUEUE_REPORT_SCHEMA_VERSION
    assert payload["source_definition"] == {
        "source_id": "cc-pr-autoqueue",
        "authority_class": "per-pr-admission-verdicts",
        "path": str(report_path),
        "staleness_budget_seconds": autoqueue.AUTOQUEUE_REPORT_STALENESS_SECONDS,
        "watch": True,
    }
    assert payload["admission_governor"]["raw"] == governor_raw
    assert payload["admission_governor"]["mode"] == "frozen"
    assert payload["admission_governor"]["reason"] == "auto-freeze: fixture reason"
    assert payload["admission_governor"]["set_by"] == "auto"
    assert payload["admission_governor"]["hysteresis"] == {
        "entry_open_pr_count": 12,
        "exit_below_count": 5,
        "exit_stable_ticks_required": 3,
        "stable_ticks_observed": 2,
    }
    assert payload["per_pr_admission"] == [
        {
            "pr": 84,
            "title": "PR 84",
            "head_ref": "feat/84",
            "task_id": "blocked-task",
            "task_ids": None,
            "task_status": "claimed",
            "action": "blocked",
            "verdict": "blocked",
            "blockers": ["active_task_status_not_ready:claimed"],
            "auto_arm": False,
        }
    ]


def test_stable_report_marks_missing_governor_without_defaulting_normal(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="ready-task", pr=85)
    runner = _FakeRunner()
    runner.open_prs = [_pr(85)]
    report_path = tmp_path / "orchestration" / "cc-pr-autoqueue-report.json"

    autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        runner=runner,
        report_path=report_path,
        admission_governor_path=tmp_path / "missing-governor.yaml",
    )

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    governor = payload["admission_governor"]
    assert governor["present"] is False
    assert governor["read_error"] == "missing"
    assert governor["raw"] is None
    assert governor["mode"] is None
    assert governor["hysteresis"]["exit_below_count"] is None


def test_stable_report_jsonifies_governor_yaml_scalars(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="ready-task", pr=86)
    runner = _FakeRunner()
    runner.open_prs = [_pr(86)]
    governor_path = tmp_path / "pr-admission-governor.yaml"
    governor_path.write_text(
        "\n".join(
            [
                "mode: frozen",
                "updated: 2026-06-12",
                "entry_open_pr_count: 10",
                "exit_below_count: 6",
                "exit_stable_ticks_required: 2",
                "stable_ticks_observed: 1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "orchestration" / "cc-pr-autoqueue-report.json"

    autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        runner=runner,
        report_path=report_path,
        admission_governor_path=governor_path,
    )

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["admission_governor"]["raw"]["updated"] == "2026-06-12"


def test_stabilization_holds_downstream_prs_while_ci_repair_is_active(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="ci-repair",
        folder="active",
        status="ready",
        pr=90,
        priority="p0",
        kind="cicd-speedup",
        tags=["cicd", "merge-queue"],
    )
    _write_task(vault, task_id="downstream", folder="active", status="ready", pr=91)
    runner = _FakeRunner()
    runner.open_prs = [_pr(90), _pr(91)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    decisions = {item["pr"]: item for item in report["decisions"]}
    assert decisions[90]["action"] == "queue"
    assert decisions[91]["action"] == "blocked"
    assert "admission_stabilization_hold:active_ci_repair:ci-repair" in decisions[91]["reasons"]
    assert ["gh", "pr", "merge", "90", "--repo", "owner/repo", "--auto", "--squash"] in runner.calls
    assert not any(call[:4] == ["gh", "pr", "merge", "91"] for call in runner.calls)


def test_stabilization_allows_governed_independent_route(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="ci-repair",
        folder="active",
        status="ready",
        pr=92,
        priority="p0",
        kind="cicd-speedup",
        tags=["cicd"],
    )
    _write_task(
        vault,
        task_id="independent",
        folder="active",
        status="ready",
        pr=93,
        queue_admission="independent",
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(92), _pr(93)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    decisions = {item["pr"]: item for item in report["decisions"]}
    assert decisions[92]["action"] == "queue"
    assert decisions[93]["action"] == "queue"
    assert not any(
        reason.startswith("admission_stabilization_hold:")
        for reason in decisions[93].get("reasons", [])
    )


def test_open_pr_count_is_advisory_and_does_not_freeze_admission(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    for number in range(100, 108):
        _write_task(vault, task_id=f"task-{number}", pr=number)
    runner = _FakeRunner()
    runner.queued_prs = {100, 101}
    runner.open_prs = [
        _pr(100),
        _pr(101, checks=[_check("lint", "FAILURE")]),
        *[_pr(number) for number in range(102, 108)],
    ]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        runner=runner,
    )

    decisions = {item["pr"]: item for item in report["decisions"]}
    assert report["storm_mode"]["active"] is False
    assert report["storm_mode"]["mode"] == "busy"
    assert report["storm_mode"]["queued_pr_count"] == 2
    assert report["storm_mode"]["blocked_queued_pr_count"] == 1
    assert report["storm_mode"]["recommended_throttle"]["max_entries_to_build"] == 6
    assert decisions[100]["action"] == "already_queued"
    assert decisions[101]["action"] == "dequeue"
    assert any(reason.startswith("failed_checks:") for reason in decisions[101]["reasons"])
    assert decisions[102]["action"] == "queue"
    assert not any(
        reason.startswith("storm_admission_hold:") for reason in decisions[102].get("reasons", [])
    )


def test_storm_apply_dequeues_only_non_ready_queued_prs(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="ready-queued", folder="active", status="merge_queue", pr=110)
    _write_task(vault, task_id="blocked-queued", pr=111, route_metadata_schema=None)
    _write_task(
        vault,
        task_id="repair-queued",
        folder="active",
        status="merge_queue",
        pr=112,
        priority="p0",
        kind="cicd-speedup",
        tags=["cicd"],
    )
    for number in range(113, 118):
        _write_task(vault, task_id=f"task-{number}", pr=number)
    runner = _FakeRunner()
    runner.queued_prs = {110, 111, 112}
    runner.open_prs = [_pr(number) for number in range(110, 118)]
    ledger = tmp_path / "merge-queue-lineage.jsonl"
    write_jsonl_records(
        ledger,
        [
            MergeQueueLineageRecord(
                observed_at=_recent_observed_at(i),
                pr_number=113 + i,
                merge_group_run_id=9100 + i,
                run_conclusion="failure",
                run_outcome="failure",
            )
            for i in range(4)
        ],
    )

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        lineage_ledger_path=ledger,
        runner=runner,
    )

    decisions = {item["pr"]: item for item in report["decisions"]}
    assert decisions[110]["action"] == "already_queued"
    assert decisions[111]["action"] == "dequeue"
    assert decisions[112]["action"] == "already_queued"
    assert report["counts"]["dequeue"] == 1
    assert (
        sum(
            1
            for call in runner.calls
            if call[:3] == ["gh", "api", "graphql"]
            and any("dequeuePullRequest" in part for part in call)
        )
        == 1
    )
    assert not any(call[:3] == ["gh", "pr", "merge"] for call in runner.calls)


def test_storm_allows_ci_repair_and_independent_admissions(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="normal-ready", folder="active", status="ready", pr=120)
    _write_task(
        vault,
        task_id="ci-repair",
        folder="active",
        status="ready",
        pr=121,
        priority="p0",
        kind="cicd-speedup",
        tags=["cicd"],
    )
    _write_task(
        vault,
        task_id="independent",
        folder="active",
        status="ready",
        pr=122,
        queue_admission="independent",
    )
    for number in range(123, 128):
        _write_task(vault, task_id=f"task-{number}", pr=number)
    runner = _FakeRunner()
    runner.open_prs = [_pr(number) for number in range(120, 128)]
    ledger = tmp_path / "merge-queue-lineage.jsonl"
    write_jsonl_records(
        ledger,
        [
            MergeQueueLineageRecord(
                observed_at=_recent_observed_at(i),
                pr_number=120 + i,
                merge_group_run_id=9200 + i,
                run_conclusion="failure",
                run_outcome="failure",
            )
            for i in range(4)
        ],
    )

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        lineage_ledger_path=ledger,
        runner=runner,
    )

    decisions = {item["pr"]: item for item in report["decisions"]}
    assert report["storm_mode"]["active"] is True
    assert decisions[120]["action"] == "blocked"
    assert decisions[121]["action"] == "queue"
    assert decisions[122]["action"] == "queue"
    assert [
        "gh",
        "pr",
        "merge",
        "121",
        "--repo",
        "owner/repo",
        "--auto",
        "--squash",
    ] in runner.calls
    assert [
        "gh",
        "pr",
        "merge",
        "122",
        "--repo",
        "owner/repo",
        "--auto",
        "--squash",
    ] in runner.calls
    assert not any(call[:4] == ["gh", "pr", "merge", "120"] for call in runner.calls)


def test_failed_recent_non_ready_merge_group_run_activates_storm_mode(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="missing-route", pr=130, route_metadata_schema=None)
    ledger = tmp_path / "merge-queue-lineage.jsonl"
    write_jsonl_records(
        ledger,
        [
            MergeQueueLineageRecord(
                observed_at=_recent_observed_at(i),
                pr_number=130,
                merge_group_run_id=9001 + i,
                run_conclusion="failure",
                run_outcome="failure",
            )
            for i in range(4)
        ],
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(130)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        lineage_ledger_path=ledger,
        runner=runner,
    )

    failed = report["storm_mode"]["failed_recent_merge_group_runs"]
    assert report["storm_mode"]["active"] is True
    assert report["storm_mode"]["rate_frozen"] is True
    assert failed[0]["run_id"] == 9001
    assert failed[0]["pr"] == 130
    assert "task_missing_route_metadata_schema_1" in failed[0]["reasons"]


# ── release auto-arm: dispatch resilience to lane-death (CASE-CAPACITY-ROUTING-001) ──


def _eligible_arm_extra() -> dict[str, object]:
    return {
        "implementation_authorized": True,
        "release_authorized": False,
        "risk_tier": "T2",
        "stage": "S6_IMPLEMENTATION",
    }


def _governance_mitigation_checks() -> list[dict[str, Any]]:
    return [
        _check("lint"),
        _check("test"),
        _check("typecheck"),
        _check("web-build"),
        _check("vscode-build"),
        _check("authority-case-check"),
        # These admission mirror checks may be present and green, but governance
        # release mitigation must not rely on them; they can pass vacuously.
        _check("governance-gate"),
        _check("pr-admission"),
        _check("review"),
    ]


def _public_claim_mitigation_checks() -> list[dict[str, Any]]:
    return _governance_mitigation_checks()


def test_summarize_checks_keeps_admission_context_ignored_until_written_by_autoqueue() -> None:
    summary = autoqueue.summarize_checks(
        [
            _check(autoqueue.AUTOQUEUE_ADMISSION_CONTEXT),
            _check("governance-gate"),
            _check("hkp-advisory", "CANCELLED"),
            _check("pr-admission"),
            _check("review"),
            _check(autoqueue.REVIEW_TEAM_QUORUM_EVIDENCE),
        ]
    )

    assert autoqueue.AUTOQUEUE_ADMISSION_CONTEXT not in summary.verified_passed
    assert "review" in summary.verified_passed
    assert autoqueue.REVIEW_TEAM_QUORUM_EVIDENCE not in summary.verified_passed
    assert "governance-gate" not in summary.verified_passed
    assert "hkp-advisory" not in summary.verified_passed
    assert "pr-admission" not in summary.verified_passed
    assert autoqueue.AUTOQUEUE_ADMISSION_CONTEXT not in summary.passed
    assert autoqueue.REVIEW_TEAM_QUORUM_EVIDENCE not in summary.passed
    assert "hkp-advisory" not in summary.failed


def test_auto_arms_release_unauthorized_pr_open_task(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-eligible",
        status="pr_open",
        pr=701,
        extra_frontmatter=_eligible_arm_extra(),
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(701)]
    ledger = tmp_path / "ledger.jsonl"

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=ledger,
    )

    armed = note.read_text(encoding="utf-8")
    assert "release_authorized: true" in armed
    assert "release_authorized: false" not in armed
    assert "stage: S7_RELEASE" in armed
    assert "release_authorized_head_sha: sha-701" in armed
    assert "release_authorized_head_ref: feat/701" in armed
    assert "release auto-arm (system)" in armed
    assert [
        "gh",
        "pr",
        "merge",
        "701",
        "--repo",
        "owner/repo",
        "--auto",
        "--squash",
        "--match-head-commit",
        "sha-701",
    ] in runner.calls
    decision = next(d for d in report["decisions"] if d["pr"] == 701)
    assert decision["action"] == "queue"
    assert decision["auto_arm"] is True
    record = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert record["kind"] == "release_auto_arm"
    assert record["task_id"] == "stranded-eligible"
    assert record["pr_head_sha"] == "sha-701"
    assert record["pr_head_ref"] == "feat/701"
    assert record["verified_checks_head_sha"] == "sha-701"
    assert record["planned_autoqueue_admission_head_sha"] == "sha-701"
    assert record["autoqueue_admission_proof_state"] == "pending_status_write"
    assert "autoqueue_admission_head_sha" not in record


def test_holds_governance_sensitive_task_without_mitigation_evidence(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-governance",
        status="pr_open",
        pr=702,
        tags=["governance"],
        extra_frontmatter=_eligible_arm_extra(),
    )
    pr_payload = _pr(
        702,
        checks=[
            _check("lint"),
            _check("test"),
            _check("typecheck"),
            _check("web-build"),
            _check("vscode-build"),
            _check("governance-gate", "SKIPPED"),
            _check("pr-admission", "NEUTRAL"),
        ],
    )
    parsed = autoqueue._parse_pr(pr_payload)
    assert parsed is not None
    assert "governance-gate" not in parsed.check_summary.verified_passed
    assert "pr-admission" not in parsed.check_summary.verified_passed

    runner = _FakeRunner()
    runner.open_prs = [pr_payload]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=tmp_path / "ledger.jsonl",
    )

    # Missing evidence holds the task; the release path stays evidence-gated.
    untouched = note.read_text(encoding="utf-8")
    assert "release_authorized: false" in untouched
    assert "stage: S7_RELEASE" not in untouched
    assert not any(call[:4] == ["gh", "pr", "merge", "702"] for call in runner.calls)
    decision = next(d for d in report["decisions"] if d["pr"] == 702)
    assert decision["action"] == "blocked"
    assert decision["reasons"] == [
        "release_auto_arm_ineligible:"
        "needs_mitigation:governance_sensitive:authority-case-check,"
        "needs_mitigation:governance_sensitive:review-team-quorum"
    ]


def test_governance_mitigation_ignores_bare_review_check_without_dossier(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-governance-bare-review",
        status="pr_open",
        pr=751,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "risk_flags": {
                "governance_sensitive": True,
            },
        },
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(751, checks=_governance_mitigation_checks())]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=tmp_path / "ledger.jsonl",
    )

    current = note.read_text(encoding="utf-8")
    assert "release_authorized: false" in current
    assert "stage: S7_RELEASE" not in current
    decision = next(d for d in report["decisions"] if d["pr"] == 751)
    assert decision["action"] == "blocked"
    assert decision["reasons"] == [
        "release_auto_arm_ineligible:needs_mitigation:governance_sensitive:review-team-quorum"
    ]
    assert not any(call[:4] == ["gh", "pr", "merge", "751"] for call in runner.calls)


def test_governance_mitigation_ignores_forged_quorum_check_without_dossier(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-governance-forged-quorum",
        status="pr_open",
        pr=755,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "risk_flags": {
                "governance_sensitive": True,
            },
        },
    )
    checks = [*_governance_mitigation_checks(), _check(autoqueue.REVIEW_TEAM_QUORUM_EVIDENCE)]
    runner = _FakeRunner()
    runner.open_prs = [_pr(755, checks=checks)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=tmp_path / "ledger.jsonl",
    )

    current = note.read_text(encoding="utf-8")
    assert "release_authorized: false" in current
    assert "stage: S7_RELEASE" not in current
    parsed = autoqueue._parse_pr(_pr(755, checks=checks))
    assert parsed is not None
    assert autoqueue.REVIEW_TEAM_QUORUM_EVIDENCE not in parsed.check_summary.verified_passed
    decision = next(d for d in report["decisions"] if d["pr"] == 755)
    assert decision["action"] == "blocked"
    assert decision["reasons"] == [
        "release_auto_arm_ineligible:needs_mitigation:governance_sensitive:review-team-quorum"
    ]
    assert not any(call[:4] == ["gh", "pr", "merge", "755"] for call in runner.calls)


def test_public_claim_mitigation_ignores_bare_review_check_without_dossier(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-public-claim-bare-review",
        status="pr_open",
        pr=756,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "risk_flags": {
                "public_claim_sensitive": True,
            },
        },
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(756, checks=_public_claim_mitigation_checks())]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=tmp_path / "ledger.jsonl",
    )

    current = note.read_text(encoding="utf-8")
    assert "release_authorized: false" in current
    assert "stage: S7_RELEASE" not in current
    decision = next(d for d in report["decisions"] if d["pr"] == 756)
    assert decision["action"] == "blocked"
    assert decision["reasons"] == [
        "release_auto_arm_ineligible:needs_mitigation:public_claim_sensitive:review-team-quorum"
    ]
    assert not any(call[:4] == ["gh", "pr", "merge", "756"] for call in runner.calls)


def test_public_claim_mitigation_ignores_forged_quorum_check_without_dossier(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-public-claim-forged-quorum",
        status="pr_open",
        pr=757,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "risk_flags": {
                "public_claim_sensitive": True,
            },
        },
    )
    checks = [*_public_claim_mitigation_checks(), _check(autoqueue.REVIEW_TEAM_QUORUM_EVIDENCE)]
    runner = _FakeRunner()
    runner.open_prs = [_pr(757, checks=checks)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=tmp_path / "ledger.jsonl",
    )

    current = note.read_text(encoding="utf-8")
    assert "release_authorized: false" in current
    assert "stage: S7_RELEASE" not in current
    parsed = autoqueue._parse_pr(_pr(757, checks=checks))
    assert parsed is not None
    assert autoqueue.REVIEW_TEAM_QUORUM_EVIDENCE not in parsed.check_summary.verified_passed
    decision = next(d for d in report["decisions"] if d["pr"] == 757)
    assert decision["action"] == "blocked"
    assert decision["reasons"] == [
        "release_auto_arm_ineligible:needs_mitigation:public_claim_sensitive:review-team-quorum"
    ]
    assert not any(call[:4] == ["gh", "pr", "merge", "757"] for call in runner.calls)


def test_auto_arms_public_claim_sensitive_source_task_with_verified_mitigation_evidence(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-public-claim-evidenced",
        status="pr_open",
        pr=758,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "risk_flags": {
                "public_claim_sensitive": True,
            },
        },
    )
    _write_governance_review_dossier(vault, "stranded-public-claim-evidenced", 758)
    runner = _FakeRunner()
    runner.open_prs = [_pr(758, checks=_public_claim_mitigation_checks())]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=tmp_path / "ledger.jsonl",
    )

    armed = note.read_text(encoding="utf-8")
    assert "release_authorized: true" in armed
    assert "release_authorized_head_sha: sha-758" in armed
    assert "release_authorized_head_ref: feat/758" in armed
    assert "stage: S7_RELEASE" in armed
    assert [
        "gh",
        "pr",
        "merge",
        "758",
        "--repo",
        "owner/repo",
        "--auto",
        "--squash",
        "--match-head-commit",
        "sha-758",
    ] in runner.calls
    decision = next(d for d in report["decisions"] if d["pr"] == 758)
    assert decision["action"] == "queue"
    assert decision["auto_arm"] is True


def test_public_claim_mitigation_does_not_auto_arm_public_mutation_surface(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-public-surface",
        status="pr_open",
        pr=759,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "mutation_surface": "public",
            "risk_flags": {
                "public_claim_sensitive": True,
            },
        },
    )
    _write_governance_review_dossier(vault, "stranded-public-surface", 759)
    runner = _FakeRunner()
    runner.open_prs = [_pr(759, checks=_public_claim_mitigation_checks())]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=tmp_path / "ledger.jsonl",
    )

    current = note.read_text(encoding="utf-8")
    assert "release_authorized: false" in current
    decision = next(d for d in report["decisions"] if d["pr"] == 759)
    assert decision["action"] == "blocked"
    assert decision["reasons"] == ["release_auto_arm_ineligible:mutation_surface:public"]
    assert not any(call[:4] == ["gh", "pr", "merge", "759"] for call in runner.calls)


def test_head_locked_public_current_release_passes_revalidation(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="already-armed-public-current-surface",
        status="pr_open",
        pr=769,
        branch="feat/769",
        mutation_surface="public",
        extra_frontmatter={
            **_eligible_arm_extra(),
            "public_current": True,
            "release_authorized": True,
            "release_authorized_head_sha": "sha-769",
            "release_authorized_head_ref": "feat/769",
            "stage": "S7_RELEASE",
            "risk_flags": {
                "public_claim_sensitive": True,
            },
        },
    )
    _write_governance_review_dossier(vault, "already-armed-public-current-surface", 769)
    runner = _FakeRunner()
    runner.open_prs = [
        _pr(
            769,
            branch="feat/769",
            files=["agents/omg_web_builder/static/index.html"],
            checks=_public_claim_mitigation_checks(),
        )
    ]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["queue"] == 1
    assert not any(
        item["pr"] == 769 and item["action"] == "release_head_revalidation"
        for item in report["mutations"]
    )
    assert any(
        item["pr"] == 769
        and item["action"] == "release_authorization_waiver"
        and item["ok"] is True
        and item["waivers"]
        == [
            "mutation_surface_waived_by_release_authorization:public",
            "public_current_waived_by_release_authorization",
        ]
        for item in report["mutations"]
    )
    assert [
        "gh",
        "pr",
        "merge",
        "769",
        "--repo",
        "owner/repo",
        "--auto",
        "--squash",
        "--match-head-commit",
        "sha-769",
    ] in runner.calls


def test_head_locked_provider_spend_release_still_blocks_revalidation(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="already-armed-provider-spend-surface",
        status="pr_open",
        pr=770,
        branch="feat/770",
        mutation_surface="provider_spend",
        extra_frontmatter={
            **_eligible_arm_extra(),
            "release_authorized": True,
            "release_authorized_head_sha": "sha-770",
            "release_authorized_head_ref": "feat/770",
            "stage": "S7_RELEASE",
        },
    )
    _write_governance_review_dossier(vault, "already-armed-provider-spend-surface", 770)
    runner = _FakeRunner()
    runner.open_prs = [_pr(770, branch="feat/770")]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert any(
        item["pr"] == 770
        and item["action"] == "release_head_revalidation"
        and item["ok"] is False
        and item["message"].startswith("current_release_auto_arm_blocked:")
        and "mutation_surface:provider_spend" in item["message"]
        for item in report["mutations"]
    )
    assert not any(call[:4] == ["gh", "pr", "merge", "770"] for call in runner.calls)


def test_auto_arms_governance_sensitive_task_with_verified_mitigation_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-governance-evidenced",
        status="pr_open",
        pr=708,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "risk_flags": {
                "governance_sensitive": True,
            },
        },
    )
    _write_governance_review_dossier(vault, "stranded-governance-evidenced", 708)
    pr_payload = _pr(708, checks=_governance_mitigation_checks())
    parsed = autoqueue._parse_pr(pr_payload)
    assert parsed is not None
    assert "governance-gate" not in parsed.check_summary.passed
    assert "pr-admission" not in parsed.check_summary.passed
    assert "governance-gate" not in parsed.check_summary.verified_passed
    assert "pr-admission" not in parsed.check_summary.verified_passed

    runner = _FakeRunner()
    runner.open_prs = [pr_payload]
    ledger = tmp_path / "ledger.jsonl"
    original_set_status = autoqueue.set_autoqueue_admission_status

    def assert_note_armed_before_success_proof(
        *args: Any, **kwargs: Any
    ) -> tuple[bool, str] | None:
        decision = args[0] if args else kwargs["decision"]
        if decision.action == "queue":
            assert "release_authorized: true" in note.read_text(encoding="utf-8")
        return original_set_status(*args, **kwargs)

    monkeypatch.setattr(
        autoqueue,
        "set_autoqueue_admission_status",
        assert_note_armed_before_success_proof,
    )

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=ledger,
    )

    armed = note.read_text(encoding="utf-8")
    assert "release_authorized: true" in armed
    assert "release_authorized_head_sha: sha-708" in armed
    assert "release_authorized_head_ref: feat/708" in armed
    assert "stage: S7_RELEASE" in armed
    assert [
        "gh",
        "pr",
        "merge",
        "708",
        "--repo",
        "owner/repo",
        "--auto",
        "--squash",
        "--match-head-commit",
        "sha-708",
    ] in runner.calls
    decision = next(d for d in report["decisions"] if d["pr"] == 708)
    assert decision["action"] == "queue"
    assert decision["auto_arm"] is True
    record = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert record["pr_head_sha"] == "sha-708"
    assert record["pr_head_ref"] == "feat/708"
    assert record["verified_checks_head_sha"] == "sha-708"
    assert record["planned_autoqueue_admission_head_sha"] == "sha-708"
    assert record["autoqueue_admission_proof_state"] == "pending_status_write"
    assert "autoqueue_admission_head_sha" not in record
    assert set(record["verified_checks"]) >= {
        "authority-case-check",
        autoqueue.REVIEW_TEAM_QUORUM_EVIDENCE,
    }
    assert "governance-gate" not in record["verified_checks"]
    assert "pr-admission" not in record["verified_checks"]
    assert record["release_auto_arm_pre_arm_assessment"] == {
        "subject": True,
        "armed": False,
        "needs_arming": True,
        "eligible": True,
        "blockers": [],
    }
    assert record["release_auto_arm_assessment"] == {
        "subject": True,
        "armed": True,
        "needs_arming": False,
        "eligible": False,
        "blockers": [],
    }
    assert record["release_auto_arm_result"]["armed"] is True
    assert record["release_auto_arm_result"]["note_mutated"] is True


def test_governance_auto_arm_refetches_live_mitigation_evidence_before_write(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-governance-stale-checks",
        status="pr_open",
        pr=749,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "risk_flags": {
                "governance_sensitive": True,
            },
        },
    )
    _write_governance_review_dossier(vault, "stranded-governance-stale-checks", 749)

    class _StaleMitigationRunner(_FakeRunner):
        def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            result = super().__call__(cmd, **kwargs)
            # The INITIAL per-PR REST check-runs fetch returns the
            # PASSING checks (result was built before this mutation); the mutation then leaves
            # open_prs FAILING so the refetch-before-write
            # (`fetch_pr_release_evidence`) observes the fresh authority-case-check failure.
            if cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6].endswith("/check-runs"):
                self.open_prs[0]["statusCheckRollup"] = [
                    _check("lint"),
                    _check("test"),
                    _check("typecheck"),
                    _check("web-build"),
                    _check("vscode-build"),
                    _check("authority-case-check", "FAILURE"),
                    _check("review"),
                ]
            return result

    runner = _StaleMitigationRunner()
    runner.open_prs = [_pr(749, checks=_governance_mitigation_checks())]
    ledger = tmp_path / "ledger.jsonl"

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=ledger,
    )

    current = note.read_text(encoding="utf-8")
    assert "release_authorized: false" in current
    assert "release_authorized_head_sha:" not in current
    assert "stage: S7_RELEASE" not in current
    assert not ledger.exists()
    assert not any(call[:4] == ["gh", "pr", "merge", "749"] for call in runner.calls)
    assert not any(
        call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-749"]
        and "state=success" in call
        for call in runner.calls
    )
    assert any(
        item["pr"] == 749
        and item["action"] == "release_auto_arm"
        and item["ok"] is False
        and item["message"]
        == "release auto-arm failed: "
        "release_auto_arm_ineligible:needs_mitigation:governance_sensitive:authority-case-check"
        for item in report["mutations"]
    )
    assert any(
        item["pr"] == 749
        and item["action"] == "set_admission_status"
        and item["status_state"] == "failure"
        and item["reasons"]
        == [
            "release_auto_arm_failed:"
            "release_auto_arm_ineligible:"
            "needs_mitigation:governance_sensitive:authority-case-check"
        ]
        for item in report["mutations"]
    )


def test_auto_arms_already_queued_governance_sensitive_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-governance-already-queued",
        status="pr_open",
        pr=711,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "risk_flags": {
                "governance_sensitive": True,
            },
        },
    )
    _write_governance_review_dossier(vault, "stranded-governance-already-queued", 711)
    runner = _FakeRunner()
    runner.queued_prs = {711}
    runner.open_prs = [_pr(711, checks=_governance_mitigation_checks())]
    ledger = tmp_path / "ledger.jsonl"
    original_set_status = autoqueue.set_autoqueue_admission_status

    def assert_note_armed_before_success_proof(
        *args: Any, **kwargs: Any
    ) -> tuple[bool, str] | None:
        decision = args[0] if args else kwargs["decision"]
        if decision.action == "already_queued":
            assert "release_authorized: true" in note.read_text(encoding="utf-8")
        return original_set_status(*args, **kwargs)

    monkeypatch.setattr(
        autoqueue,
        "set_autoqueue_admission_status",
        assert_note_armed_before_success_proof,
    )

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=ledger,
    )

    armed = note.read_text(encoding="utf-8")
    assert "release_authorized: true" in armed
    assert "stage: S7_RELEASE" in armed
    assert not any(call[:4] == ["gh", "pr", "merge", "711"] for call in runner.calls)
    decision = next(d for d in report["decisions"] if d["pr"] == 711)
    assert decision["action"] == "already_queued"
    assert decision["auto_arm"] is True
    assert any(
        item["pr"] == 711 and item["action"] == "release_auto_arm" and item["ok"] is True
        for item in report["mutations"]
    )
    release_index = next(
        index
        for index, item in enumerate(report["mutations"])
        if item["pr"] == 711 and item["action"] == "release_auto_arm"
    )
    status_index = next(
        index
        for index, item in enumerate(report["mutations"])
        if item["pr"] == 711
        and item["action"] == "set_admission_status"
        and item["status_state"] == "success"
    )
    assert release_index < status_index
    record = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert record["task_id"] == "stranded-governance-already-queued"


def test_already_queued_refetches_mitigation_checks_before_success_proof(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="already-armed-governance-stale-checks",
        status="pr_open",
        pr=750,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "release_authorized": True,
            "release_authorized_head_sha": "sha-750",
            "release_authorized_head_ref": "feat/750",
            "risk_flags": {
                "governance_sensitive": True,
            },
        },
    )
    _write_governance_review_dossier(vault, "already-armed-governance-stale-checks", 750)

    class _StaleMitigationRunner(_FakeRunner):
        def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
            result = super().__call__(cmd, **kwargs)
            # The INITIAL per-PR REST check-runs fetch returns the
            # PASSING checks (result was built before this mutation); the mutation then leaves
            # open_prs FAILING so the refetch-before-write
            # (`fetch_pr_release_evidence`) observes the fresh authority-case-check failure.
            if cmd[:5] == ["gh", "api", "--method", "GET", "-H"] and cmd[6].endswith("/check-runs"):
                self.open_prs[0]["statusCheckRollup"] = [
                    _check("lint"),
                    _check("test"),
                    _check("typecheck"),
                    _check("web-build"),
                    _check("vscode-build"),
                    _check("authority-case-check", "FAILURE"),
                    _check("review"),
                ]
            return result

    runner = _StaleMitigationRunner()
    runner.queued_prs = {750}
    runner.open_prs = [_pr(750, checks=_governance_mitigation_checks())]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=tmp_path / "ledger.jsonl",
    )

    assert not any(
        call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-750"]
        and "state=success" in call
        for call in runner.calls
    )
    assert any(
        item["pr"] == 750
        and item["action"] == "release_head_revalidation"
        and item["ok"] is False
        and item["message"]
        == "current_release_auto_arm_blocked:"
        "needs_mitigation:governance_sensitive:authority-case-check"
        for item in report["mutations"]
    )
    assert any(
        item["pr"] == 750
        and item["action"] == "set_admission_status"
        and item["status_state"] == "failure"
        and item["reasons"]
        == [
            "release_head_revalidation_failed:"
            "current_release_auto_arm_blocked:"
            "needs_mitigation:governance_sensitive:authority-case-check"
        ]
        for item in report["mutations"]
    )
    assert any(
        call[:3] == ["gh", "api", "graphql"] and any("dequeuePullRequest" in part for part in call)
        for call in runner.calls
    )


def test_head_locked_sensitive_path_release_passes_revalidation(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="already-armed-sensitive-doc",
        status="pr_open",
        pr=760,
        branch="feat/760",
        extra_frontmatter={
            **_eligible_arm_extra(),
            "release_authorized": True,
            "release_authorized_head_sha": "sha-760",
            "release_authorized_head_ref": "feat/760",
            "stage": "S7_RELEASE",
            "mutation_scope_refs": ["hapax-council/CLAUDE.md"],
        },
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(760, branch="feat/760", files=["CLAUDE.md"])]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["queue"] == 1
    assert not any(
        item["pr"] == 760 and item["action"] == "release_head_revalidation"
        for item in report["mutations"]
    )
    assert any(
        item["pr"] == 760
        and item["action"] == "release_authorization_waiver"
        and item["ok"] is True
        and item["waivers"]
        == ["sensitive_path_waived_by_release_authorization:hapax-council/CLAUDE.md"]
        for item in report["mutations"]
    )
    success_status_index = next(
        index
        for index, call in enumerate(runner.calls)
        if call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-760"]
        and "state=success" in call
    )
    evidence_indices = [
        index
        for index, call in enumerate(runner.calls)
        if call[:5] == ["gh", "api", "--method", "GET", "-H"]
        and call[6] == "repos/owner/repo/commits/sha-760/check-runs"
    ]
    assert len([index for index in evidence_indices if index < success_status_index]) >= 2
    assert any(
        call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-760"]
        and "state=success" in call
        for call in runner.calls
    )
    assert [
        "gh",
        "pr",
        "merge",
        "760",
        "--repo",
        "owner/repo",
        "--auto",
        "--squash",
        "--match-head-commit",
        "sha-760",
    ] in runner.calls


def test_unarmed_sensitive_path_still_blocks_auto_arm(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="unarmed-sensitive-doc",
        status="pr_open",
        pr=761,
        branch="feat/761",
        extra_frontmatter={
            **_eligible_arm_extra(),
            "mutation_scope_refs": ["hapax-council/CLAUDE.md"],
        },
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(761, branch="feat/761", files=["CLAUDE.md"])]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=tmp_path / "ledger.jsonl",
    )

    assert report["counts"]["blocked"] == 1
    decision = next(item for item in report["decisions"] if item["pr"] == 761)
    assert decision["reasons"] == [
        "release_auto_arm_ineligible:sensitive_path:hapax-council/CLAUDE.md"
    ]
    assert not any(call[:4] == ["gh", "pr", "merge", "761"] for call in runner.calls)


def test_sensitive_path_waiver_uses_current_note_at_revalidation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="already-armed-current-sensitive-doc",
        status="pr_open",
        pr=762,
        branch="feat/762",
        extra_frontmatter={
            **_eligible_arm_extra(),
            "release_authorized": True,
            "release_authorized_head_sha": "sha-762",
            "release_authorized_head_ref": "feat/762",
            "stage": "S7_RELEASE",
            "mutation_scope_refs": ["hapax-council/docs/example.md"],
        },
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(762, branch="feat/762", files=["CLAUDE.md"])]
    original_boundary = autoqueue._release_head_boundary_blocker
    changed_scope = False

    def add_sensitive_path_before_boundary(decision: Any, **kwargs: Any) -> str | None:
        nonlocal changed_scope
        if decision.pr.number == 762 and not changed_scope:
            note.write_text(
                note.read_text(encoding="utf-8").replace(
                    "- hapax-council/docs/example.md",
                    "- hapax-council/CLAUDE.md",
                ),
                encoding="utf-8",
            )
            changed_scope = True
        return original_boundary(decision, **kwargs)

    monkeypatch.setattr(
        autoqueue, "_release_head_boundary_blocker", add_sensitive_path_before_boundary
    )

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["queue"] == 1
    assert any(
        item["pr"] == 762
        and item["action"] == "release_authorization_waiver"
        and item["waivers"]
        == ["sensitive_path_waived_by_release_authorization:hapax-council/CLAUDE.md"]
        for item in report["mutations"]
    )


def test_head_locked_sensitive_path_stale_head_still_blocks_admission(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="already-armed-sensitive-doc-stale-head",
        status="pr_open",
        pr=763,
        branch="feat/763",
        extra_frontmatter={
            **_eligible_arm_extra(),
            "release_authorized": True,
            "release_authorized_head_sha": "sha-before-force-push",
            "release_authorized_head_ref": "feat/763",
            "stage": "S7_RELEASE",
            "mutation_scope_refs": ["hapax-council/CLAUDE.md"],
        },
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(763, branch="feat/763", files=["CLAUDE.md"])]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    decision = next(item for item in report["decisions"] if item["pr"] == 763)
    assert decision["action"] == "blocked"
    assert decision["reasons"] == [
        "release_authorized_head_mismatch:authorized=sha-before-force-push:current=sha-763"
    ]
    assert not any(
        item["pr"] == 763 and item["action"] == "release_authorization_waiver"
        for item in report["mutations"]
    )
    assert not any(call[:4] == ["gh", "pr", "merge", "763"] for call in runner.calls)


def test_sensitive_path_stale_head_during_revalidation_blocks_before_waiver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="already-armed-sensitive-doc-stale-during-boundary",
        status="pr_open",
        pr=764,
        branch="feat/764",
        extra_frontmatter={
            **_eligible_arm_extra(),
            "release_authorized": True,
            "release_authorized_head_sha": "sha-764",
            "release_authorized_head_ref": "feat/764",
            "stage": "S7_RELEASE",
            "mutation_scope_refs": ["hapax-council/CLAUDE.md"],
        },
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(764, branch="feat/764", files=["CLAUDE.md"])]
    original_boundary = autoqueue._release_head_boundary_blocker
    repointed = False

    def repoint_before_boundary(decision: Any, **kwargs: Any) -> str | None:
        nonlocal repointed
        if decision.pr.number == 764 and not repointed:
            note.write_text(
                note.read_text(encoding="utf-8").replace(
                    "release_authorized_head_sha: sha-764",
                    "release_authorized_head_sha: sha-old",
                ),
                encoding="utf-8",
            )
            repointed = True
        return original_boundary(decision, **kwargs)

    monkeypatch.setattr(autoqueue, "_release_head_boundary_blocker", repoint_before_boundary)

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert not any(
        item["pr"] == 764 and item["action"] == "release_authorization_waiver"
        for item in report["mutations"]
    )
    assert not any(
        call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-764"]
        and "state=success" in call
        for call in runner.calls
    )
    assert any(
        item["pr"] == 764
        and item["action"] == "release_head_revalidation"
        and item["ok"] is False
        and item["message"]
        == "current_task_gate_blocked:release_authorized_head_mismatch:"
        "authorized=sha-old:current=sha-764"
        for item in report["mutations"]
    )


def test_already_queued_replays_full_current_auto_arm_blockers_before_success_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="already-armed-current-auto-arm-drift",
        status="pr_open",
        pr=754,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "release_authorized": True,
            "release_authorized_head_sha": "sha-754",
            "release_authorized_head_ref": "feat/754",
            "stage": "S7_RELEASE",
        },
    )
    runner = _FakeRunner()
    runner.queued_prs = {754}
    runner.open_prs = [_pr(754)]
    original_boundary = autoqueue._release_head_boundary_blocker

    def revoke_implementation_before_boundary(decision: Any, **kwargs: Any) -> str | None:
        if decision.pr.number == 754:
            note.write_text(
                note.read_text(encoding="utf-8").replace(
                    "implementation_authorized: true",
                    "implementation_authorized: false",
                ),
                encoding="utf-8",
            )
        return original_boundary(decision, **kwargs)

    monkeypatch.setattr(
        autoqueue, "_release_head_boundary_blocker", revoke_implementation_before_boundary
    )

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert not any(
        call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-754"]
        and "state=success" in call
        for call in runner.calls
    )
    assert any(
        item["pr"] == 754
        and item["action"] == "release_head_revalidation"
        and item["ok"] is False
        and item["message"] == "current_release_auto_arm_blocked:not_implementation_authorized"
        for item in report["mutations"]
    )
    assert any(
        item["pr"] == 754
        and item["action"] == "set_admission_status"
        and item["status_state"] == "failure"
        and item["reasons"]
        == [
            "release_head_revalidation_failed:"
            "current_release_auto_arm_blocked:not_implementation_authorized"
        ]
        for item in report["mutations"]
    )
    assert any(
        call[:3] == ["gh", "api", "graphql"] and any("dequeuePullRequest" in part for part in call)
        for call in runner.calls
    )


def test_auto_arms_already_auto_merge_enabled_governance_sensitive_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-governance-already-auto",
        status="pr_open",
        pr=712,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "risk_flags": {
                "governance_sensitive": True,
            },
        },
    )
    _write_governance_review_dossier(vault, "stranded-governance-already-auto", 712)
    runner = _FakeRunner()
    runner.open_prs = [_pr(712, auto_merge=True, checks=_governance_mitigation_checks())]
    ledger = tmp_path / "ledger.jsonl"
    original_set_status = autoqueue.set_autoqueue_admission_status

    def assert_note_armed_before_success_proof(
        *args: Any, **kwargs: Any
    ) -> tuple[bool, str] | None:
        decision = args[0] if args else kwargs["decision"]
        if decision.action == "already_auto_merge_enabled":
            assert "release_authorized: true" in note.read_text(encoding="utf-8")
        return original_set_status(*args, **kwargs)

    monkeypatch.setattr(
        autoqueue,
        "set_autoqueue_admission_status",
        assert_note_armed_before_success_proof,
    )

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=ledger,
    )

    armed = note.read_text(encoding="utf-8")
    assert "release_authorized: true" in armed
    assert "stage: S7_RELEASE" in armed
    assert not any(call[:4] == ["gh", "pr", "merge", "712"] for call in runner.calls)
    decision = next(d for d in report["decisions"] if d["pr"] == 712)
    assert decision["action"] == "already_auto_merge_enabled"
    assert decision["auto_arm"] is True
    assert any(
        item["pr"] == 712 and item["action"] == "release_auto_arm" and item["ok"] is True
        for item in report["mutations"]
    )
    record = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert record["task_id"] == "stranded-governance-already-auto"


def test_auto_arms_enable_auto_merge_governance_sensitive_task_after_arming_before_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-governance-new-auto",
        status="pr_open",
        pr=739,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "risk_flags": {
                "governance_sensitive": True,
            },
        },
    )
    _write_governance_review_dossier(vault, "stranded-governance-new-auto", 739)
    checks = [
        {**check, "conclusion": "PENDING"} if check.get("name") == "vscode-build" else check
        for check in _governance_mitigation_checks()
    ]
    runner = _FakeRunner()
    runner.open_prs = [_pr(739, checks=checks)]
    ledger = tmp_path / "ledger.jsonl"
    original_set_status = autoqueue.set_autoqueue_admission_status

    def assert_note_armed_before_success_proof(
        *args: Any, **kwargs: Any
    ) -> tuple[bool, str] | None:
        decision = args[0] if args else kwargs["decision"]
        if decision.action == "enable_auto_merge":
            assert "release_authorized: true" in note.read_text(encoding="utf-8")
        return original_set_status(*args, **kwargs)

    monkeypatch.setattr(
        autoqueue,
        "set_autoqueue_admission_status",
        assert_note_armed_before_success_proof,
    )

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=ledger,
    )

    armed = note.read_text(encoding="utf-8")
    assert "release_authorized: true" in armed
    assert "release_authorized_head_sha: sha-739" in armed
    assert "stage: S7_RELEASE" in armed
    decision = next(d for d in report["decisions"] if d["pr"] == 739)
    assert decision["action"] == "enable_auto_merge"
    assert decision["auto_arm"] is True
    assert [
        "gh",
        "pr",
        "merge",
        "739",
        "--repo",
        "owner/repo",
        "--auto",
        "--squash",
        "--match-head-commit",
        "sha-739",
    ] in runner.calls
    assert any(
        item["pr"] == 739 and item["action"] == "release_auto_arm" and item["ok"] is True
        for item in report["mutations"]
    )
    record = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert record["task_id"] == "stranded-governance-new-auto"


def test_already_queued_auto_arm_failure_dequeues_and_overwrites_admission_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-governance-queued-arm-fails",
        status="pr_open",
        pr=713,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "risk_flags": {
                "governance_sensitive": True,
            },
        },
    )
    _write_governance_review_dossier(vault, "stranded-governance-queued-arm-fails", 713)
    runner = _FakeRunner()
    runner.queued_prs = {713}
    runner.open_prs = [_pr(713, checks=_governance_mitigation_checks())]

    def fail_arm(*_: Any, **__: Any) -> tuple[bool, str]:
        return False, "task note write failed"

    monkeypatch.setattr(autoqueue, "arm_release_for_task", fail_arm)

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=tmp_path / "ledger.jsonl",
    )

    assert "release_authorized: false" in note.read_text(encoding="utf-8")
    assert any(
        item["pr"] == 713 and item["action"] == "release_auto_arm" and item["ok"] is False
        for item in report["mutations"]
    )
    assert any(
        call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-713"]
        and "state=failure" in call
        for call in runner.calls
    )
    assert not any(
        call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-713"]
        and "state=success" in call
        for call in runner.calls
    )
    assert any(
        item["pr"] == 713
        and item["action"] == "set_admission_status"
        and item["status_state"] == "failure"
        and item["ok"] is True
        for item in report["mutations"]
    )
    assert any(
        call[:3] == ["gh", "api", "graphql"] and any("dequeuePullRequest" in part for part in call)
        for call in runner.calls
    )


def test_arm_release_for_task_note_unchanged_is_idempotent_with_matching_head(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-governance-arm-idempotent",
        status="pr_open",
        pr=732,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "risk_flags": {
                "governance_sensitive": True,
            },
        },
    )
    task = next(task for task in autoqueue.load_task_notes(vault) if task.task_id == note.stem)
    note.write_text(
        note.read_text(encoding="utf-8")
        .replace(
            "release_authorized: false",
            "release_authorized: true\n"
            "release_authorized_head_sha: sha-732\n"
            "release_authorized_head_ref: feat/732",
        )
        .replace("stage: S6_IMPLEMENTATION", "stage: S7_RELEASE"),
        encoding="utf-8",
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(732, checks=_governance_mitigation_checks())]
    ledger = tmp_path / "ledger.jsonl"

    ok, message = autoqueue.arm_release_for_task(
        task,
        ledger_path=ledger,
        verified_checks=set(autoqueue.RELEASE_MITIGATION_CHECKS["governance_sensitive"]),
        pr_number=732,
        head_ref="feat/732",
        expected_head_sha="sha-732",
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
    )

    assert ok is True
    assert message == "note_unchanged"
    assert "release_authorized: true" in note.read_text(encoding="utf-8")
    assert not ledger.exists()


def test_already_auto_merge_auto_arm_failure_disables_auto_merge_and_overwrites_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-governance-auto-arm-fails",
        status="pr_open",
        pr=714,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "risk_flags": {
                "governance_sensitive": True,
            },
        },
    )
    _write_governance_review_dossier(vault, "stranded-governance-auto-arm-fails", 714)
    runner = _FakeRunner()
    runner.open_prs = [_pr(714, auto_merge=True, checks=_governance_mitigation_checks())]

    def fail_arm(*_: Any, **__: Any) -> tuple[bool, str]:
        return False, "task note write failed"

    monkeypatch.setattr(autoqueue, "arm_release_for_task", fail_arm)

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=tmp_path / "ledger.jsonl",
    )

    assert "release_authorized: false" in note.read_text(encoding="utf-8")
    assert any(
        item["pr"] == 714 and item["action"] == "release_auto_arm" and item["ok"] is False
        for item in report["mutations"]
    )
    assert any(
        call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-714"]
        and "state=failure" in call
        for call in runner.calls
    )
    assert not any(
        call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-714"]
        and "state=success" in call
        for call in runner.calls
    )
    assert any(
        item["pr"] == 714
        and item["action"] == "set_admission_status"
        and item["status_state"] == "failure"
        and item["ok"] is True
        for item in report["mutations"]
    )
    assert ["gh", "pr", "merge", "714", "--repo", "owner/repo", "--disable-auto"] in runner.calls


def test_already_queued_status_write_failure_still_dequeues(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-governance-queued-status-fails",
        status="pr_open",
        pr=717,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "risk_flags": {
                "governance_sensitive": True,
            },
        },
    )
    _write_governance_review_dossier(vault, "stranded-governance-queued-status-fails", 717)
    runner = _FakeRunner()
    runner.queued_prs = {717}
    runner.open_prs = [_pr(717, checks=_governance_mitigation_checks())]
    runner.fail_status_posts = True

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=tmp_path / "ledger.jsonl",
    )

    assert "release_authorized: true" in note.read_text(encoding="utf-8")
    assert any(
        item["pr"] == 717 and item["action"] == "release_auto_arm" and item["ok"] is True
        for item in report["mutations"]
    )
    assert any(
        item["pr"] == 717
        and item["action"] == "set_admission_status"
        and item["status_state"] == "success"
        and item["ok"] is False
        for item in report["mutations"]
    )
    failure_status = next(
        item
        for item in report["mutations"]
        if item["pr"] == 717
        and item["action"] == "set_admission_status"
        and item["status_state"] == "failure"
    )
    assert failure_status["ok"] is False
    assert failure_status["reasons"] == ["admission_status_write_failed:status post failed"]
    assert any(
        call[:3] == ["gh", "api", "graphql"] and any("dequeuePullRequest" in part for part in call)
        for call in runner.calls
    )


def test_already_auto_merge_status_write_failure_still_disables_auto_merge(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-governance-auto-status-fails",
        status="pr_open",
        pr=718,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "risk_flags": {
                "governance_sensitive": True,
            },
        },
    )
    _write_governance_review_dossier(vault, "stranded-governance-auto-status-fails", 718)
    runner = _FakeRunner()
    runner.open_prs = [_pr(718, auto_merge=True, checks=_governance_mitigation_checks())]
    runner.fail_status_posts = True

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=tmp_path / "ledger.jsonl",
    )

    assert "release_authorized: true" in note.read_text(encoding="utf-8")
    assert any(
        item["pr"] == 718 and item["action"] == "release_auto_arm" and item["ok"] is True
        for item in report["mutations"]
    )
    assert any(
        item["pr"] == 718
        and item["action"] == "set_admission_status"
        and item["status_state"] == "success"
        and item["ok"] is False
        for item in report["mutations"]
    )
    failure_status = next(
        item
        for item in report["mutations"]
        if item["pr"] == 718
        and item["action"] == "set_admission_status"
        and item["status_state"] == "failure"
    )
    assert failure_status["ok"] is False
    assert failure_status["reasons"] == ["admission_status_write_failed:status post failed"]
    assert ["gh", "pr", "merge", "718", "--repo", "owner/repo", "--disable-auto"] in runner.calls


def test_new_queue_auto_arm_failure_overwrites_admission_status_without_queueing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-governance-new-queue-arm-fails",
        status="pr_open",
        pr=715,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "risk_flags": {
                "governance_sensitive": True,
            },
        },
    )
    _write_governance_review_dossier(vault, "stranded-governance-new-queue-arm-fails", 715)
    runner = _FakeRunner()
    runner.open_prs = [_pr(715, checks=_governance_mitigation_checks())]

    def fail_arm(*_: Any, **__: Any) -> tuple[bool, str]:
        return False, "task note write failed"

    monkeypatch.setattr(autoqueue, "arm_release_for_task", fail_arm)

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=tmp_path / "ledger.jsonl",
    )

    assert "release_authorized: false" in note.read_text(encoding="utf-8")
    assert not any(call[:4] == ["gh", "pr", "merge", "715"] for call in runner.calls)
    assert any(
        item["pr"] == 715 and item["action"] == "release_auto_arm" and item["ok"] is False
        for item in report["mutations"]
    )
    assert any(
        item["pr"] == 715
        and item["action"] == "set_admission_status"
        and item["status_state"] == "failure"
        and item["ok"] is True
        for item in report["mutations"]
    )


def test_new_enable_auto_merge_auto_arm_failure_overwrites_admission_status_without_arming(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-governance-new-auto-arm-fails",
        status="pr_open",
        pr=716,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "risk_flags": {
                "governance_sensitive": True,
            },
        },
    )
    _write_governance_review_dossier(vault, "stranded-governance-new-auto-arm-fails", 716)
    checks = [
        {**check, "conclusion": "PENDING"} if check.get("name") == "vscode-build" else check
        for check in _governance_mitigation_checks()
    ]
    runner = _FakeRunner()
    runner.open_prs = [_pr(716, checks=checks)]

    def fail_arm(*_: Any, **__: Any) -> tuple[bool, str]:
        return False, "task note write failed"

    monkeypatch.setattr(autoqueue, "arm_release_for_task", fail_arm)

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=tmp_path / "ledger.jsonl",
    )

    assert "release_authorized: false" in note.read_text(encoding="utf-8")
    assert not any(call[:4] == ["gh", "pr", "merge", "716"] for call in runner.calls)
    decision = next(item for item in report["decisions"] if item["pr"] == 716)
    assert decision["action"] == "enable_auto_merge"
    assert any(
        item["pr"] == 716 and item["action"] == "release_auto_arm" and item["ok"] is False
        for item in report["mutations"]
    )
    assert any(
        item["pr"] == 716
        and item["action"] == "set_admission_status"
        and item["status_state"] == "failure"
        and item["ok"] is True
        for item in report["mutations"]
    )


@pytest.mark.parametrize(
    ("context", "state"),
    [
        ("authority-case-check", "SKIPPED"),
        ("authority-case-check", "NEUTRAL"),
    ],
)
def test_governance_mitigation_requires_successful_evidence(
    tmp_path: Path,
    context: str,
    state: str,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id=f"stranded-governance-{context}-{state.lower()}",
        status="pr_open",
        pr=709,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "risk_flags": {
                "governance_sensitive": True,
            },
        },
    )
    _write_governance_review_dossier(
        vault,
        f"stranded-governance-{context}-{state.lower()}",
        709,
    )
    checks = _governance_mitigation_checks()
    checks = [
        {**check, "conclusion": state} if check.get("name") == context else check
        for check in checks
    ]
    pr_payload = _pr(709, checks=checks)
    parsed = autoqueue._parse_pr(pr_payload)
    assert parsed is not None
    assert context not in parsed.check_summary.verified_passed

    runner = _FakeRunner()
    runner.open_prs = [pr_payload]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=tmp_path / "ledger.jsonl",
    )

    untouched = note.read_text(encoding="utf-8")
    assert "release_authorized: false" in untouched
    assert "stage: S7_RELEASE" not in untouched
    assert not any(call[:4] == ["gh", "pr", "merge", "709"] for call in runner.calls)
    decision = next(d for d in report["decisions"] if d["pr"] == 709)
    assert decision["action"] == "blocked"
    assert decision["reasons"] == [
        f"release_auto_arm_ineligible:needs_mitigation:governance_sensitive:{context}"
    ]


def test_governance_auto_arm_status_write_failure_blocks_queue_after_arm(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-governance-status-failed",
        status="pr_open",
        pr=710,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "risk_flags": {
                "governance_sensitive": True,
            },
        },
    )
    _write_governance_review_dossier(vault, "stranded-governance-status-failed", 710)
    runner = _FakeRunner()
    runner.open_prs = [_pr(710, checks=_governance_mitigation_checks())]
    runner.fail_status_posts = True
    ledger = tmp_path / "ledger.jsonl"

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=ledger,
    )

    armed = note.read_text(encoding="utf-8")
    assert "release_authorized: true" in armed
    assert "release_authorized_head_sha: sha-710" in armed
    assert "stage: S7_RELEASE" in armed
    assert ledger.exists()
    assert not any(call[:4] == ["gh", "pr", "merge", "710"] for call in runner.calls)
    assert any(
        item["pr"] == 710 and item["action"] == "release_auto_arm" and item["ok"] is True
        for item in report["mutations"]
    )
    mutation = next(
        item
        for item in report["mutations"]
        if item["pr"] == 710 and item["action"] == "set_admission_status"
    )
    assert mutation["action"] == "set_admission_status"
    assert mutation["status_state"] == "success"
    assert mutation["ok"] is False
    assert mutation["message"] == "admission status write failed; queue mutation skipped"


def test_governance_auto_arm_reposts_existing_success_before_queue(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-governance-existing-success",
        status="pr_open",
        pr=744,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "risk_flags": {
                "governance_sensitive": True,
            },
        },
    )
    _write_governance_review_dossier(vault, "stranded-governance-existing-success", 744)
    runner = _FakeRunner()
    runner.open_prs = [_pr(744, checks=_governance_mitigation_checks())]
    runner.head_statuses["sha-744"] = [
        _existing_status(
            "success",
            "cc-pr-autoqueue admitted: queue",
            "2999-06-02T00:00:00Z",
        )
    ]
    ledger = tmp_path / "ledger.jsonl"

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=ledger,
    )

    armed = note.read_text(encoding="utf-8")
    assert "release_authorized: true" in armed
    assert "release_authorized_head_sha: sha-744" in armed
    posts = [
        call
        for call in runner.calls
        if call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-744"]
    ]
    assert len(posts) == 1
    assert "state=success" in posts[0]
    post_index = runner.calls.index(posts[0])
    merge_index = next(
        index for index, call in enumerate(runner.calls) if call[:4] == ["gh", "pr", "merge", "744"]
    )
    assert post_index < merge_index
    result = next(
        item for item in report["mutations"] if item.get("pr") == 744 and "admission_status" in item
    )
    assert result["ok"] is True
    assert result["admission_status"]["ok"] is True
    assert result["admission_status"]["message"] == '{"state":"ok"}'


def test_governance_auto_arm_missing_head_sha_blocks_before_note_write(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-missing-head",
        status="pr_open",
        pr=745,
        extra_frontmatter=_eligible_arm_extra(),
    )
    _write_governance_review_dossier(vault, "stranded-missing-head", 745)
    runner = _FakeRunner()
    pr = _pr(745, checks=_governance_mitigation_checks())
    pr["headRefOid"] = None
    runner.open_prs = [pr]
    ledger = tmp_path / "ledger.jsonl"

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=ledger,
    )

    current = note.read_text(encoding="utf-8")
    assert "release_authorized: false" in current
    assert "release_authorized_head_sha:" not in current
    assert "stage: S7_RELEASE" not in current
    assert not ledger.exists()
    assert not any(call[:4] == ["gh", "pr", "merge", "745"] for call in runner.calls)
    assert any(
        item["pr"] == 745
        and item["action"] == "release_auto_arm"
        and item["ok"] is False
        and item["message"]
        == "release auto-arm failed: current_pr_head_unverifiable:missing_expected_head_sha"
        for item in report["mutations"]
    )


def test_enable_auto_merge_status_write_failure_blocks_queue_after_arm(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-governance-enable-status-failed",
        status="pr_open",
        pr=721,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "risk_flags": {
                "governance_sensitive": True,
            },
        },
    )
    _write_governance_review_dossier(vault, "stranded-governance-enable-status-failed", 721)
    checks = [
        {**check, "conclusion": "PENDING"} if check.get("name") == "vscode-build" else check
        for check in _governance_mitigation_checks()
    ]
    runner = _FakeRunner()
    runner.open_prs = [_pr(721, checks=checks)]
    runner.fail_status_posts = True
    ledger = tmp_path / "ledger.jsonl"

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=ledger,
    )

    armed = note.read_text(encoding="utf-8")
    assert "release_authorized: true" in armed
    assert "release_authorized_head_sha: sha-721" in armed
    assert "stage: S7_RELEASE" in armed
    assert ledger.exists()
    assert not any(call[:4] == ["gh", "pr", "merge", "721"] for call in runner.calls)
    decision = next(item for item in report["decisions"] if item["pr"] == 721)
    assert decision["action"] == "enable_auto_merge"
    assert any(
        item["pr"] == 721 and item["action"] == "release_auto_arm" and item["ok"] is True
        for item in report["mutations"]
    )
    mutation = next(
        item
        for item in report["mutations"]
        if item["pr"] == 721 and item["action"] == "set_admission_status"
    )
    assert mutation["action"] == "set_admission_status"
    assert mutation["status_state"] == "success"
    assert mutation["ok"] is False
    assert mutation["message"] == "admission status write failed; queue mutation skipped"


def test_arm_release_for_task_fails_closed_when_assessment_ineligible(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-governance-helper-ineligible",
        status="pr_open",
        pr=731,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "risk_flags": {
                "governance_sensitive": True,
            },
        },
    )
    task = next(task for task in autoqueue.load_task_notes(vault) if task.task_id == note.stem)
    ledger = tmp_path / "ledger.jsonl"

    ok, message = autoqueue.arm_release_for_task(
        task,
        ledger_path=ledger,
        verified_checks={"authority-case-check", autoqueue.REVIEW_TEAM_QUORUM_EVIDENCE},
    )

    assert ok is False
    assert (
        message == "release_auto_arm_ineligible:"
        "needs_mitigation:governance_sensitive:review-team-quorum"
    )
    untouched = note.read_text(encoding="utf-8")
    assert "release_authorized: false" in untouched
    assert "stage: S7_RELEASE" not in untouched
    assert not ledger.exists()


def test_arm_release_for_task_revalidates_current_note_frontmatter(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-stale-snapshot",
        status="pr_open",
        pr=722,
        extra_frontmatter=_eligible_arm_extra(),
    )
    task = next(task for task in autoqueue.load_task_notes(vault) if task.task_id == note.stem)
    note.write_text(
        note.read_text(encoding="utf-8").replace(
            "implementation_authorized: true", "implementation_authorized: false"
        ),
        encoding="utf-8",
    )
    ledger = tmp_path / "ledger.jsonl"

    ok, message = autoqueue.arm_release_for_task(
        task,
        ledger_path=ledger,
    )

    assert ok is False
    assert message == "release_auto_arm_ineligible:not_implementation_authorized"
    current = note.read_text(encoding="utf-8")
    assert "release_authorized: false" in current
    assert "stage: S7_RELEASE" not in current
    assert not ledger.exists()


def test_arm_release_for_task_revalidates_current_full_task_gate(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-stale-governance-metadata",
        status="pr_open",
        pr=737,
        branch="feat/737",
        extra_frontmatter=_eligible_arm_extra(),
    )
    task = next(task for task in autoqueue.load_task_notes(vault) if task.task_id == note.stem)
    note.write_text(
        note.read_text(encoding="utf-8").replace(
            "authority_case: CASE-TEST", "authority_case: null"
        ),
        encoding="utf-8",
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(737, branch="feat/737")]
    ledger = tmp_path / "ledger.jsonl"

    ok, message = autoqueue.arm_release_for_task(
        task,
        ledger_path=ledger,
        verified_checks=set(autoqueue.RELEASE_MITIGATION_CHECKS["governance_sensitive"]),
        pr_number=737,
        head_ref="feat/737",
        expected_head_sha="sha-737",
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
    )

    assert ok is False
    assert message == "current_task_gate_blocked:task_missing_authority_case"
    current = note.read_text(encoding="utf-8")
    assert "release_authorized: false" in current
    assert "stage: S7_RELEASE" not in current
    assert not ledger.exists()


def test_arm_release_for_task_rereads_parent_spec_before_write(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-stale-parent-spec",
        status="pr_open",
        pr=741,
        branch="feat/741",
        extra_frontmatter=_eligible_arm_extra(),
    )
    task = next(task for task in autoqueue.load_task_notes(vault) if task.task_id == note.stem)
    note.write_text(
        note.read_text(encoding="utf-8").replace("parent_spec: docs/spec.md", "parent_spec: null"),
        encoding="utf-8",
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(741, branch="feat/741")]
    ledger = tmp_path / "ledger.jsonl"

    ok, message = autoqueue.arm_release_for_task(
        task,
        ledger_path=ledger,
        pr_number=741,
        head_ref="feat/741",
        expected_head_sha="sha-741",
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
    )

    assert ok is False
    assert message == "current_task_gate_blocked:task_missing_parent_spec"
    current = note.read_text(encoding="utf-8")
    assert "release_authorized: false" in current
    assert "stage: S7_RELEASE" not in current
    assert not ledger.exists()


def test_arm_release_for_task_rejects_note_no_longer_cc_task(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-retyped-note",
        status="pr_open",
        pr=739,
        branch="feat/739",
        extra_frontmatter=_eligible_arm_extra(),
    )
    task = next(task for task in autoqueue.load_task_notes(vault) if task.task_id == note.stem)
    note.write_text(
        note.read_text(encoding="utf-8").replace("type: cc-task", "type: note"),
        encoding="utf-8",
    )
    ledger = tmp_path / "ledger.jsonl"

    ok, message = autoqueue.arm_release_for_task(
        task,
        ledger_path=ledger,
        pr_number=739,
        head_ref="feat/739",
        expected_head_sha="sha-739",
    )

    assert ok is False
    assert message == "current_task_gate_blocked:current_task_not_cc_task"
    current = note.read_text(encoding="utf-8")
    assert "release_authorized: false" in current
    assert "stage: S7_RELEASE" not in current
    assert not ledger.exists()


def test_arm_release_for_task_revalidates_current_task_status(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-stale-status",
        status="pr_open",
        pr=723,
        branch="feat/723",
        extra_frontmatter=_eligible_arm_extra(),
    )
    task = next(task for task in autoqueue.load_task_notes(vault) if task.task_id == note.stem)
    note.write_text(
        note.read_text(encoding="utf-8").replace("status: pr_open", "status: claimed"),
        encoding="utf-8",
    )
    ledger = tmp_path / "ledger.jsonl"

    ok, message = autoqueue.arm_release_for_task(
        task,
        ledger_path=ledger,
        pr_number=723,
        head_ref="feat/723",
    )

    assert ok is False
    assert message == "current_task_not_admissible:current_task_status_not_ready:claimed"
    current = note.read_text(encoding="utf-8")
    assert "release_authorized: false" in current
    assert "stage: S7_RELEASE" not in current
    assert not ledger.exists()


def test_arm_release_for_task_revalidates_current_task_identity(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-stale-identity",
        status="pr_open",
        pr=724,
        branch="feat/724",
        extra_frontmatter=_eligible_arm_extra(),
    )
    task = next(task for task in autoqueue.load_task_notes(vault) if task.task_id == note.stem)
    note.write_text(
        note.read_text(encoding="utf-8")
        .replace("pr: 724", "pr: 999")
        .replace("branch: feat/724", "branch: feat/999"),
        encoding="utf-8",
    )
    ledger = tmp_path / "ledger.jsonl"

    ok, message = autoqueue.arm_release_for_task(
        task,
        ledger_path=ledger,
        pr_number=724,
        head_ref="feat/724",
    )

    assert ok is False
    assert (
        message == "current_task_not_admissible:"
        "current_task_pr_mismatch:current=999:expected=724,"
        "current_task_branch_mismatch:current=feat/999:expected=feat/724"
    )
    current = note.read_text(encoding="utf-8")
    assert "release_authorized: false" in current
    assert "stage: S7_RELEASE" not in current
    assert not ledger.exists()


def test_arm_release_for_task_revalidates_current_note_identity(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-repointed-snapshot",
        status="pr_open",
        pr=725,
        branch="feature/current",
        extra_frontmatter=_eligible_arm_extra(),
    )
    task = next(task for task in autoqueue.load_task_notes(vault) if task.task_id == note.stem)
    note.write_text(
        note.read_text(encoding="utf-8").replace("pr: 725", "pr: 999"),
        encoding="utf-8",
    )
    ledger = tmp_path / "ledger.jsonl"

    ok, message = autoqueue.arm_release_for_task(
        task,
        ledger_path=ledger,
        pr_number=725,
        head_ref="feature/current",
    )

    assert ok is False
    assert (
        message == "current_task_not_admissible:current_task_pr_mismatch:current=999:expected=725"
    )
    current = note.read_text(encoding="utf-8")
    assert "release_authorized: false" in current
    assert "stage: S7_RELEASE" not in current
    assert not ledger.exists()


def test_arm_release_for_task_allows_branch_match_when_pr_field_missing(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-branch-only",
        status="pr_open",
        pr=None,
        branch="feature/branch-only",
        extra_frontmatter=_eligible_arm_extra(),
    )
    task = next(task for task in autoqueue.load_task_notes(vault) if task.task_id == note.stem)
    ledger = tmp_path / "ledger.jsonl"

    ok, message = autoqueue.arm_release_for_task(
        task,
        ledger_path=ledger,
        pr_number=None,
        head_ref="feature/branch-only",
    )

    assert ok is True
    assert message == "release auto-armed stranded-branch-only"
    current = note.read_text(encoding="utf-8")
    assert "release_authorized: true" in current
    assert "release_authorized_head_ref: feature/branch-only" in current
    assert ledger.exists()


def test_arm_release_for_task_revalidates_current_pr_head_sha(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-repointed-head",
        status="pr_open",
        pr=726,
        branch="feat/726",
        extra_frontmatter=_eligible_arm_extra(),
    )
    task = next(task for task in autoqueue.load_task_notes(vault) if task.task_id == note.stem)
    runner = _FakeRunner()
    runner.open_prs = [_pr(726, branch="feat/726")]
    ledger = tmp_path / "ledger.jsonl"

    ok, message = autoqueue.arm_release_for_task(
        task,
        ledger_path=ledger,
        pr_number=726,
        head_ref="feat/726",
        expected_head_sha="sha-before-force-push",
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
    )

    assert ok is False
    assert message == "current_pr_head_mismatch:current=sha-726:expected=sha-before-force-push"
    current = note.read_text(encoding="utf-8")
    assert "release_authorized: false" in current
    assert "stage: S7_RELEASE" not in current
    assert not ledger.exists()


def test_arm_release_for_task_requires_head_sha_for_pr_linked_write(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-missing-expected-head",
        status="pr_open",
        pr=727,
        branch="feat/727",
        extra_frontmatter=_eligible_arm_extra(),
    )
    task = next(task for task in autoqueue.load_task_notes(vault) if task.task_id == note.stem)
    ledger = tmp_path / "ledger.jsonl"

    ok, message = autoqueue.arm_release_for_task(
        task,
        ledger_path=ledger,
        pr_number=727,
        head_ref="feat/727",
    )

    assert ok is False
    assert message == "current_pr_head_unverifiable:missing_expected_head_sha"
    current = note.read_text(encoding="utf-8")
    assert "release_authorized: false" in current
    assert "release_authorized_head_sha:" not in current
    assert "stage: S7_RELEASE" not in current
    assert not ledger.exists()


def test_arm_release_for_task_rejects_stale_already_armed_note_head(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-stale-armed-head",
        status="pr_open",
        pr=728,
        branch="feat/728",
        extra_frontmatter={
            **_eligible_arm_extra(),
            "release_authorized": True,
            "release_authorized_head_sha": "sha-old",
            "stage": "S7_RELEASE",
        },
    )
    task = next(task for task in autoqueue.load_task_notes(vault) if task.task_id == note.stem)
    runner = _FakeRunner()
    runner.open_prs = [_pr(728, branch="feat/728")]
    ledger = tmp_path / "ledger.jsonl"

    ok, message = autoqueue.arm_release_for_task(
        task,
        ledger_path=ledger,
        pr_number=728,
        head_ref="feat/728",
        expected_head_sha="sha-728",
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
    )

    assert ok is False
    assert (
        message == "current_task_gate_blocked:release_authorized_head_mismatch:"
        "authorized=sha-old:current=sha-728"
    )
    assert not ledger.exists()


def test_arm_release_for_task_rejects_headless_already_armed_note(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-headless-armed",
        status="pr_open",
        pr=729,
        branch="feat/729",
        extra_frontmatter={
            **_eligible_arm_extra(),
            "release_authorized": True,
            "stage": "S7_RELEASE",
        },
    )
    task = next(task for task in autoqueue.load_task_notes(vault) if task.task_id == note.stem)
    runner = _FakeRunner()
    runner.open_prs = [_pr(729, branch="feat/729")]
    ledger = tmp_path / "ledger.jsonl"

    ok, message = autoqueue.arm_release_for_task(
        task,
        ledger_path=ledger,
        pr_number=729,
        head_ref="feat/729",
        expected_head_sha="sha-729",
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
    )

    assert ok is False
    assert message == "current_task_gate_blocked:release_authorized_head_missing:current=sha-729"
    assert not ledger.exists()


def test_release_authorized_head_mismatch_blocks_later_admission(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="already-armed-stale-head",
        status="pr_open",
        pr=727,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "release_authorized": True,
            "release_authorized_head_sha": "sha-before-force-push",
            "stage": "S7_RELEASE",
        },
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(727)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    decision = next(item for item in report["decisions"] if item["pr"] == 727)
    assert decision["action"] == "blocked"
    assert (
        "release_authorized_head_mismatch:authorized=sha-before-force-push:current=sha-727"
        in decision["reasons"]
    )
    assert not any(call[:4] == ["gh", "pr", "merge", "727"] for call in runner.calls)


def test_release_head_boundary_reports_unreadable_current_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="already-armed-unreadable-boundary",
        status="pr_open",
        pr=738,
        branch="feat/738",
        extra_frontmatter={
            **_eligible_arm_extra(),
            "release_authorized": True,
            "release_authorized_head_sha": "sha-738",
            "stage": "S7_RELEASE",
        },
    )
    task = next(task for task in autoqueue.load_task_notes(vault) if task.task_id == note.stem)
    pr = autoqueue._parse_pr(_pr(738, branch="feat/738"))
    assert pr is not None
    original_read_text = Path.read_text

    def fail_current_note_read(path: Path, *args: Any, **kwargs: Any) -> str:
        if path == note:
            raise OSError("read failed")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_current_note_read)

    message = autoqueue._release_head_boundary_blocker(
        autoqueue.Decision(pr=pr, task=task, tasks=(task,), action="queue")
    )

    assert message == "release_authorized_note_unreadable:read failed"


def test_release_head_boundary_revalidates_current_task_gate_before_queue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="already-armed-governance-revoked-before-boundary",
        status="pr_open",
        pr=740,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "release_authorized": True,
            "release_authorized_head_sha": "sha-740",
            "stage": "S7_RELEASE",
        },
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(740)]
    original_boundary = autoqueue._release_head_boundary_blocker

    def remove_authority_before_boundary(decision: Any, **kwargs: Any) -> str | None:
        if decision.pr.number == 740:
            note.write_text(
                note.read_text(encoding="utf-8").replace(
                    "authority_case: CASE-TEST", "authority_case: null"
                ),
                encoding="utf-8",
            )
        return original_boundary(decision, **kwargs)

    monkeypatch.setattr(
        autoqueue, "_release_head_boundary_blocker", remove_authority_before_boundary
    )

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert not any(call[:4] == ["gh", "pr", "merge", "740"] for call in runner.calls)
    assert not any(
        call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-740"]
        and "state=success" in call
        for call in runner.calls
    )
    assert any(
        item["pr"] == 740
        and item["action"] == "release_head_revalidation"
        and item["ok"] is False
        and item["message"] == "current_task_gate_blocked:task_missing_authority_case"
        for item in report["mutations"]
    )
    assert any(
        item["pr"] == 740
        and item["action"] == "set_admission_status"
        and item["status_state"] == "failure"
        and item["reasons"]
        == [
            "release_head_revalidation_failed:current_task_gate_blocked:task_missing_authority_case"
        ]
        for item in report["mutations"]
    )


def test_release_head_boundary_rejects_note_no_longer_cc_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="already-armed-retyped-before-boundary",
        status="pr_open",
        pr=742,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "release_authorized": True,
            "release_authorized_head_sha": "sha-742",
            "stage": "S7_RELEASE",
        },
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(742)]
    original_boundary = autoqueue._release_head_boundary_blocker

    def retype_before_boundary(decision: Any, **kwargs: Any) -> str | None:
        if decision.pr.number == 742:
            note.write_text(
                note.read_text(encoding="utf-8").replace("type: cc-task", "type: note"),
                encoding="utf-8",
            )
        return original_boundary(decision, **kwargs)

    monkeypatch.setattr(autoqueue, "_release_head_boundary_blocker", retype_before_boundary)

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert not any(call[:4] == ["gh", "pr", "merge", "742"] for call in runner.calls)
    assert not any(
        call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-742"]
        and "state=success" in call
        for call in runner.calls
    )
    assert any(
        item["pr"] == 742
        and item["action"] == "release_head_revalidation"
        and item["ok"] is False
        and item["message"] == "current_task_gate_blocked:current_task_not_cc_task"
        for item in report["mutations"]
    )
    assert any(
        item["pr"] == 742
        and item["action"] == "set_admission_status"
        and item["status_state"] == "failure"
        and item["reasons"]
        == ["release_head_revalidation_failed:current_task_gate_blocked:current_task_not_cc_task"]
        for item in report["mutations"]
    )


def test_release_head_boundary_rejects_current_note_missing_cc_task_type(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="already-armed-missing-type-before-boundary",
        status="pr_open",
        pr=743,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "release_authorized": True,
            "release_authorized_head_sha": "sha-743",
            "stage": "S7_RELEASE",
        },
    )
    task = next(task for task in autoqueue.load_task_notes(vault) if task.task_id == note.stem)
    note.write_text(
        note.read_text(encoding="utf-8").replace("type: cc-task\n", ""),
        encoding="utf-8",
    )
    pr = autoqueue._parse_pr(_pr(743))
    assert pr is not None
    runner = _FakeRunner()
    runner.open_prs = [_pr(743)]

    message = autoqueue._release_head_boundary_blocker(
        autoqueue.Decision(pr=pr, task=task, tasks=(task,), action="queue"),
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
    )

    assert message == "current_task_gate_blocked:current_task_not_cc_task"


def test_release_head_boundary_revalidates_current_note_before_queue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="already-armed-revoked-before-queue",
        status="pr_open",
        pr=735,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "release_authorized": True,
            "release_authorized_head_sha": "sha-735",
            "stage": "S7_RELEASE",
        },
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(735)]
    original_boundary = autoqueue._release_head_boundary_blocker

    def revoke_before_boundary(decision: Any, **kwargs: Any) -> str | None:
        if decision.pr.number == 735:
            current = note.read_text(encoding="utf-8")
            note.write_text(
                current.replace("release_authorized: true", "release_authorized: false"),
                encoding="utf-8",
            )
        return original_boundary(decision, **kwargs)

    monkeypatch.setattr(autoqueue, "_release_head_boundary_blocker", revoke_before_boundary)

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert not any(call[:4] == ["gh", "pr", "merge", "735"] for call in runner.calls)
    assert not any(
        call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-735"]
        and "state=success" in call
        for call in runner.calls
    )
    assert any(
        item["pr"] == 735
        and item["action"] == "release_head_revalidation"
        and item["ok"] is False
        and item["message"] == "release_authorized_not_current"
        for item in report["mutations"]
    )
    assert any(
        item["pr"] == 735
        and item["action"] == "set_admission_status"
        and item["status_state"] == "failure"
        and item["reasons"] == ["release_head_revalidation_failed:release_authorized_not_current"]
        for item in report["mutations"]
    )


def test_release_head_boundary_fetches_live_head_before_queue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="already-armed-force-pushed-before-queue",
        status="pr_open",
        pr=748,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "release_authorized": True,
            "release_authorized_head_sha": "sha-748",
            "stage": "S7_RELEASE",
        },
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(748)]
    original_boundary = autoqueue._release_head_boundary_blocker
    repointed = False

    def force_push_before_boundary(decision: Any, **kwargs: Any) -> str | None:
        nonlocal repointed
        if decision.pr.number == 748 and not repointed:
            runner.open_prs[0]["headRefOid"] = "sha-force-pushed"
            repointed = True
        return original_boundary(decision, **kwargs)

    monkeypatch.setattr(autoqueue, "_release_head_boundary_blocker", force_push_before_boundary)

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert not any(call[:4] == ["gh", "pr", "merge", "748"] for call in runner.calls)
    assert not any(
        call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-748"]
        and "state=success" in call
        for call in runner.calls
    )
    assert any(
        item["pr"] == 748
        and item["action"] == "release_head_revalidation"
        and item["ok"] is False
        and item["message"] == "current_pr_head_mismatch:current=sha-force-pushed:expected=sha-748"
        for item in report["mutations"]
    )
    assert any(
        item["pr"] == 748
        and item["action"] == "set_admission_status"
        and item["status_state"] == "failure"
        and item["reasons"]
        == [
            "release_head_revalidation_failed:"
            "current_pr_head_mismatch:current=sha-force-pushed:expected=sha-748"
        ]
        for item in report["mutations"]
    )


def test_queue_failure_after_success_admission_rewrites_failure_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="already-armed-revoked-after-success-status",
        status="pr_open",
        pr=750,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "release_authorized": True,
            "release_authorized_head_sha": "sha-750",
            "stage": "S7_RELEASE",
        },
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(750)]
    original_set_status = autoqueue.set_autoqueue_admission_status
    revoked = False

    def revoke_after_success_status(*args: Any, **kwargs: Any) -> tuple[bool, str] | None:
        nonlocal revoked
        result = original_set_status(*args, **kwargs)
        decision = args[0] if args else kwargs["decision"]
        if decision.pr.number == 750 and result is not None and result[0] and not revoked:
            note.write_text(
                note.read_text(encoding="utf-8").replace(
                    "release_authorized: true", "release_authorized: false"
                ),
                encoding="utf-8",
            )
            revoked = True
        return result

    monkeypatch.setattr(autoqueue, "set_autoqueue_admission_status", revoke_after_success_status)

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    posts = [
        call
        for call in runner.calls
        if call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-750"]
    ]
    assert any("state=success" in call for call in posts)
    assert any("state=failure" in call for call in posts)
    success_index = next(index for index, call in enumerate(posts) if "state=success" in call)
    failure_index = next(index for index, call in enumerate(posts) if "state=failure" in call)
    assert success_index < failure_index
    assert any(
        item["pr"] == 750
        and item["action"] == "queue"
        and item["ok"] is False
        and item["message"] == "release_authorized_not_current"
        for item in report["mutations"]
    )
    assert any(
        item["pr"] == 750
        and item["action"] == "set_admission_status"
        and item["status_state"] == "failure"
        and item["reasons"] == ["queue_mutation_failed:release_authorized_not_current"]
        for item in report["mutations"]
    )


def test_release_head_boundary_revalidates_current_note_before_already_queued(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="already-queued-repointed-before-boundary",
        status="pr_open",
        pr=736,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "release_authorized": True,
            "release_authorized_head_sha": "sha-736",
            "stage": "S7_RELEASE",
        },
    )
    runner = _FakeRunner()
    runner.queued_prs = {736}
    runner.open_prs = [_pr(736)]
    original_boundary = autoqueue._release_head_boundary_blocker
    repointed = False

    def repoint_before_boundary(decision: Any, **kwargs: Any) -> str | None:
        nonlocal repointed
        if decision.pr.number == 736 and not repointed:
            note.write_text(
                note.read_text(encoding="utf-8").replace(
                    "release_authorized_head_sha: sha-736",
                    "release_authorized_head_sha: sha-old",
                ),
                encoding="utf-8",
            )
            repointed = True
        return original_boundary(decision, **kwargs)

    monkeypatch.setattr(autoqueue, "_release_head_boundary_blocker", repoint_before_boundary)

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert not any(
        call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-736"]
        and "state=success" in call
        for call in runner.calls
    )
    assert any(
        item["pr"] == 736
        and item["action"] == "release_head_revalidation"
        and item["ok"] is False
        and item["message"]
        == "current_task_gate_blocked:release_authorized_head_mismatch:"
        "authorized=sha-old:current=sha-736"
        for item in report["mutations"]
    )
    assert any(
        call[:3] == ["gh", "api", "graphql"] and any("dequeuePullRequest" in part for part in call)
        for call in runner.calls
    )


def test_release_head_boundary_fetches_live_head_before_already_queued_retention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="already-queued-force-pushed-before-boundary",
        status="pr_open",
        pr=746,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "release_authorized": True,
            "release_authorized_head_sha": "sha-746",
            "stage": "S7_RELEASE",
        },
    )
    runner = _FakeRunner()
    runner.queued_prs = {746}
    runner.open_prs = [_pr(746)]
    original_boundary = autoqueue._release_head_boundary_blocker
    repointed = False

    def force_push_before_boundary(decision: Any, **kwargs: Any) -> str | None:
        nonlocal repointed
        if decision.pr.number == 746 and not repointed:
            runner.open_prs[0]["headRefOid"] = "sha-force-pushed"
            repointed = True
        return original_boundary(decision, **kwargs)

    monkeypatch.setattr(autoqueue, "_release_head_boundary_blocker", force_push_before_boundary)

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert not any(
        call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-746"]
        and "state=success" in call
        for call in runner.calls
    )
    assert any(
        item["pr"] == 746
        and item["action"] == "release_head_revalidation"
        and item["ok"] is False
        and item["message"] == "current_pr_head_mismatch:current=sha-force-pushed:expected=sha-746"
        for item in report["mutations"]
    )
    assert any(
        call[:3] == ["gh", "api", "graphql"] and any("dequeuePullRequest" in part for part in call)
        for call in runner.calls
    )


def test_release_head_boundary_fetches_live_head_before_auto_merge_retention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="already-auto-force-pushed-before-boundary",
        status="pr_open",
        pr=747,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "release_authorized": True,
            "release_authorized_head_sha": "sha-747",
            "stage": "S7_RELEASE",
        },
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(747, auto_merge=True)]
    original_boundary = autoqueue._release_head_boundary_blocker
    repointed = False

    def force_push_before_boundary(decision: Any, **kwargs: Any) -> str | None:
        nonlocal repointed
        if decision.pr.number == 747 and not repointed:
            runner.open_prs[0]["headRefOid"] = "sha-force-pushed"
            repointed = True
        return original_boundary(decision, **kwargs)

    monkeypatch.setattr(autoqueue, "_release_head_boundary_blocker", force_push_before_boundary)

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert not any(
        call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-747"]
        and "state=success" in call
        for call in runner.calls
    )
    assert any(
        item["pr"] == 747
        and item["action"] == "release_head_revalidation"
        and item["ok"] is False
        and item["message"] == "current_pr_head_mismatch:current=sha-force-pushed:expected=sha-747"
        for item in report["mutations"]
    )
    assert [
        "gh",
        "pr",
        "merge",
        "747",
        "--repo",
        "owner/repo",
        "--disable-auto",
    ] in runner.calls


def test_arm_release_for_task_reports_note_read_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-read-failure",
        status="pr_open",
        pr=719,
        extra_frontmatter=_eligible_arm_extra(),
    )
    task = next(task for task in autoqueue.load_task_notes(vault) if task.task_id == note.stem)
    original_read_bytes = Path.read_bytes

    def fail_note_read(path: Path, *args: Any, **kwargs: Any) -> bytes:
        if path == note:
            raise OSError("read failed")
        return original_read_bytes(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", fail_note_read)

    ok, message = autoqueue.arm_release_for_task(
        task,
        ledger_path=tmp_path / "ledger.jsonl",
    )

    assert ok is False
    assert message == "note_unreadable:read failed"


def test_arm_release_for_task_reports_note_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-write-failure",
        status="pr_open",
        pr=720,
        extra_frontmatter=_eligible_arm_extra(),
    )
    task = next(task for task in autoqueue.load_task_notes(vault) if task.task_id == note.stem)

    def fail_note_write(*args: Any, **kwargs: Any) -> None:
        raise autoqueue.FilesystemTransactionError("write failed")

    monkeypatch.setattr(autoqueue, "execute_filesystem_transaction", fail_note_write)

    ok, message = autoqueue.arm_release_for_task(
        task,
        ledger_path=tmp_path / "ledger.jsonl",
    )

    assert ok is False
    assert message == "note_write_failed:write failed"
    assert "release_authorized: false" in note.read_text(encoding="utf-8")
    assert not (tmp_path / "ledger.jsonl").exists()


def test_arm_release_for_task_cannot_recreate_note_moved_by_concurrent_close(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-concurrent-close",
        status="pr_open",
        pr=None,
        branch="feature/concurrent-close",
        extra_frontmatter=_eligible_arm_extra(),
    )
    task = next(task for task in autoqueue.load_task_notes(vault) if task.task_id == note.stem)
    stage = note.parent / ".hapax-transactions"
    stage.mkdir(mode=0o700)
    lock_path = stage / ".hapax-transaction.lock"
    lock_path.touch(mode=0o600)

    with ThreadPoolExecutor(max_workers=1) as executor, lock_path.open("r+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        future = executor.submit(
            autoqueue.arm_release_for_task,
            task,
            ledger_path=tmp_path / "ledger.jsonl",
            pr_number=None,
            head_ref="feature/concurrent-close",
        )
        time.sleep(0.25)
        assert not future.done(), "autoqueue writer did not wait on the target lock"

        closed = vault / "closed" / note.name
        closed.parent.mkdir(parents=True, exist_ok=True)
        note.rename(closed)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        ok, message = future.result(timeout=10)

    assert ok is False
    assert message.startswith("note_write_failed:transaction preimage changed:")
    assert not note.exists()
    assert "release_authorized: false" in closed.read_text(encoding="utf-8")
    assert not (tmp_path / "ledger.jsonl").exists()


def test_auto_arms_pass_backed_runtime_secret_subscription_task(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-glmcp-secret",
        status="pr_open",
        pr=706,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "title": "Activate GLMCP lane with pass-backed secret",
            "pass_backed_secret_only": True,
            "no_secret_value_storage": True,
            "secret_entry": "glmcp/api-key",
            "subscription_quota_only": True,
            "supported_tools_only": True,
        },
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(706)]
    ledger = tmp_path / "ledger.jsonl"

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=ledger,
    )

    armed = note.read_text(encoding="utf-8")
    assert "release_authorized: true" in armed
    assert "stage: S7_RELEASE" in armed
    assert [
        "gh",
        "pr",
        "merge",
        "706",
        "--repo",
        "owner/repo",
        "--auto",
        "--squash",
        "--match-head-commit",
        "sha-706",
    ] in runner.calls
    decision = next(d for d in report["decisions"] if d["pr"] == 706)
    assert decision["action"] == "queue"
    assert decision["auto_arm"] is True
    record = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert record["kind"] == "release_auto_arm"
    assert record["task_id"] == "stranded-glmcp-secret"
    assert record["auto_arm_waivers"] == ["pass_backed_runtime_secret_waiver"]


def test_auto_arm_ledger_uses_lifecycle_waiver_predicate(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-glmcp-string-truthy",
        status="pr_open",
        pr=707,
        extra_frontmatter={
            **_eligible_arm_extra(),
            "title": "Activate GLMCP lane with pass-backed secret",
            "pass_backed_secret_only": "true",
            "no_secret_value_storage": "true",
            "secret_entry": "glmcp/alt-key",
            "subscription_quota_only": "true",
            "supported_tools_only": "true",
        },
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(707)]
    ledger = tmp_path / "ledger.jsonl"

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=ledger,
    )

    assert "release_authorized: true" in note.read_text(encoding="utf-8")
    decision = next(d for d in report["decisions"] if d["pr"] == 707)
    assert decision["action"] == "queue"
    assert decision["auto_arm"] is True
    record = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert record["auto_arm_waivers"] == ["pass_backed_runtime_secret_waiver"]


def test_dry_run_reports_release_auto_arm_without_writing_note(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-dry",
        status="pr_open",
        pr=703,
        extra_frontmatter=_eligible_arm_extra(),
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(703)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=False,
        runner=runner,
        auto_arm_ledger_path=tmp_path / "ledger.jsonl",
    )

    assert "release_authorized: false" in note.read_text(encoding="utf-8")  # untouched
    decision = next(d for d in report["decisions"] if d["pr"] == 703)
    assert decision["action"] == "queue"
    assert decision["auto_arm"] is True
    assert not any(call[:4] == ["gh", "pr", "merge", "703"] for call in runner.calls)


def test_multiple_release_unauthorized_tasks_still_block_auto_arm(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    first = _write_task(
        vault,
        task_id="stranded-one",
        status="pr_open",
        pr=704,
        extra_frontmatter=_eligible_arm_extra(),
    )
    second = _write_task(
        vault,
        task_id="stranded-two",
        status="pr_open",
        pr=704,
        extra_frontmatter=_eligible_arm_extra(),
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(704)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=tmp_path / "ledger.jsonl",
    )

    assert "release_authorized: false" in first.read_text(encoding="utf-8")
    assert "release_authorized: false" in second.read_text(encoding="utf-8")
    assert not any(call[:4] == ["gh", "pr", "merge", "704"] for call in runner.calls)
    decision = next(d for d in report["decisions"] if d["pr"] == 704)
    assert decision["action"] == "blocked"
    assert "auto_arm" not in decision
    assert any("release_authorized_false" in reason for reason in decision["reasons"])


def test_auto_armed_task_writes_auto_arm_ledger_record(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="stranded-ledger",
        status="pr_open",
        pr=704,
        extra_frontmatter=_eligible_arm_extra(),
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(704)]
    ledger = tmp_path / "ledger.jsonl"

    autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=ledger,
    )

    assert ledger.exists()
    record = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert record["kind"] == "release_auto_arm"
    assert record["task_id"] == "stranded-ledger"
    assert record["release_auto_arm_pre_arm_assessment"]["eligible"] is True
    assert record["release_auto_arm_pre_arm_assessment"]["blockers"] == []
    assert record["release_auto_arm_assessment"]["armed"] is True
    assert record["release_auto_arm_result"]["armed"] is True
    assert set(record["verified_checks"]) >= {"lint", "test", "typecheck"}


def test_already_release_authorized_task_without_head_stamp_is_blocked(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="already-armed",
        status="pr_open",
        pr=705,
        extra_frontmatter={
            "implementation_authorized": True,
            "release_authorized": True,
            "risk_tier": "T2",
            "stage": "S7_RELEASE",
        },
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(705)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=tmp_path / "ledger.jsonl",
    )

    # Already armed without a stamped head cannot prove which commit was authorized.
    assert "release auto-arm (system)" not in note.read_text(encoding="utf-8")
    assert not any(call[:4] == ["gh", "pr", "merge", "705"] for call in runner.calls)
    decision = next(d for d in report["decisions"] if d["pr"] == 705)
    assert decision["action"] == "blocked"
    assert "release_authorized_head_missing:current=sha-705" in decision["reasons"]
    assert decision.get("auto_arm", False) is False


def test_already_release_authorized_head_locked_task_matches_head_on_merge(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="already-armed-head-locked",
        status="pr_open",
        pr=733,
        extra_frontmatter={
            "implementation_authorized": True,
            "release_authorized": True,
            "release_authorized_head_sha": "sha-733",
            "risk_tier": "T2",
            "stage": "S7_RELEASE",
        },
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(733)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert [
        "gh",
        "pr",
        "merge",
        "733",
        "--repo",
        "owner/repo",
        "--auto",
        "--squash",
        "--match-head-commit",
        "sha-733",
    ] in runner.calls
    decision = next(d for d in report["decisions"] if d["pr"] == 733)
    assert decision["action"] == "queue"
    assert decision.get("auto_arm", False) is False


def test_merge_pr_revalidates_current_release_authorization_before_head_locked_merge(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="already-armed-revoked",
        status="pr_open",
        pr=735,
        branch="feat/735",
        extra_frontmatter={
            "implementation_authorized": True,
            "release_authorized": True,
            "release_authorized_head_sha": "sha-735",
            "risk_tier": "T2",
            "stage": "S7_RELEASE",
        },
    )
    task = next(task for task in autoqueue.load_task_notes(vault) if task.task_id == note.stem)
    note.write_text(
        note.read_text(encoding="utf-8").replace(
            "release_authorized: true", "release_authorized: false"
        ),
        encoding="utf-8",
    )
    pr = autoqueue._parse_pr(_pr(735))
    assert pr is not None
    runner = _FakeRunner()
    runner.open_prs = [_pr(735)]

    ok, message = autoqueue.merge_pr(
        autoqueue.Decision(pr=pr, task=task, tasks=(task,), action="queue"),
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
    )

    assert ok is False
    assert message == "release_authorized_not_current"
    assert not any(call[:3] == ["gh", "pr", "merge"] for call in runner.calls)


def test_merge_pr_revalidates_current_release_authorized_head_before_merge(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="already-armed-repointed",
        status="pr_open",
        pr=736,
        branch="feat/736",
        extra_frontmatter={
            "implementation_authorized": True,
            "release_authorized": True,
            "release_authorized_head_sha": "sha-736",
            "risk_tier": "T2",
            "stage": "S7_RELEASE",
        },
    )
    task = next(task for task in autoqueue.load_task_notes(vault) if task.task_id == note.stem)
    note.write_text(
        note.read_text(encoding="utf-8").replace(
            "release_authorized_head_sha: sha-736",
            "release_authorized_head_sha: sha-old",
        ),
        encoding="utf-8",
    )
    pr = autoqueue._parse_pr(_pr(736))
    assert pr is not None
    runner = _FakeRunner()
    runner.open_prs = [_pr(736)]

    ok, message = autoqueue.merge_pr(
        autoqueue.Decision(pr=pr, task=task, tasks=(task,), action="queue"),
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
    )

    assert ok is False
    assert (
        message == "current_task_gate_blocked:release_authorized_head_mismatch:"
        "authorized=sha-old:current=sha-736"
    )
    assert not any(call[:3] == ["gh", "pr", "merge"] for call in runner.calls)


def test_head_guard_required_merge_fails_when_head_sha_missing(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="already-armed-missing-head",
        status="pr_open",
        pr=734,
        extra_frontmatter={
            "implementation_authorized": True,
            "release_authorized": True,
            "release_authorized_head_sha": "sha-734",
            "risk_tier": "T2",
            "stage": "S7_RELEASE",
        },
    )
    task = next(
        task
        for task in autoqueue.load_task_notes(vault)
        if task.task_id == "already-armed-missing-head"
    )
    payload = _pr(734)
    payload["headRefOid"] = None
    pr = autoqueue._parse_pr(payload)
    assert pr is not None
    runner = _FakeRunner()

    ok, message = autoqueue.merge_pr(
        autoqueue.Decision(pr=pr, task=task, tasks=(task,), action="queue"),
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
    )

    assert ok is False
    assert message == "missing_head_sha_for_head_guard"
    assert runner.calls == []


def test_flake_quarantine_write_side_persists_and_excludes_next_tick(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    _write_task(vault, task_id="flaky-pr", pr=140, route_metadata_schema=None)
    ledger = tmp_path / "merge-queue-lineage.jsonl"
    write_jsonl_records(
        ledger,
        [
            MergeQueueLineageRecord(
                observed_at=_recent_observed_at(i),
                pr_number=140,
                merge_group_run_id=8000 + i,
                run_conclusion="failure",
                run_outcome="failure",
            )
            # 4 genuine failures: over the quarantine threshold (2) AND enough
            # samples (min_samples 4) to also trip the failure-rate freeze.
            for i in range(4)
        ],
    )
    quarantine_path = tmp_path / "merge-queue-quarantine.jsonl"
    runner = _FakeRunner()
    runner.open_prs = [_pr(140)]

    # First apply: PR 140 is over the failure threshold → quarantine opened and
    # persisted. The freshly-detected PR still counts toward THIS tick's rate.
    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        lineage_ledger_path=ledger,
        quarantine_path=quarantine_path,
        runner=runner,
    )
    assert report["flake_quarantine"]["newly_quarantined"] == [140]
    assert report["flake_quarantine"]["written"] is True
    assert quarantine_path.exists()
    assert report["storm_mode"]["rate_frozen"] is True

    # Second apply: the persisted quarantine is now active → PR 140 is excluded
    # from the failure-rate signal, so the isolated flaky PR no longer freezes the
    # fleet, and it is not re-opened.
    report2 = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        lineage_ledger_path=ledger,
        quarantine_path=quarantine_path,
        runner=runner,
    )
    assert 140 in report2["flake_quarantine"]["active"]
    assert report2["flake_quarantine"]["newly_quarantined"] == []
    assert report2["storm_mode"]["rate_frozen"] is False


# ── shared-file epic serialization: single-lane affinity (CASE-SBCL-CLOG-COORD-001) ──
# The CLOG/Trainyard cockpit epic is a parallel DAG whose branches all mutate one
# shared file (src/dashboard.lisp). Two lanes editing it concurrently merge-conflict
# by construction. The autoqueue holds admission of an epic PR while a sibling epic
# task is concurrently in flight in a DIFFERENT lane (the real hazard); same-lane
# serial work is never held, and a deterministic lowest-PR tiebreak prevents two
# different-lane epic PRs from dead-holding each other.

_CLOG_SPEC = "clog-frontend-elevation-design-2026-06-01.md"
# The CLOG epic was removed from SHARED_FILE_EPIC_PARENT_SPECS (task
# reform-native-merge-queue) — the native merge queue now serializes shared-file
# contention. The mechanism still works via the explicit ``epic_serialize`` field,
# so these mechanism tests opt in via that field instead of the (now empty)
# parent_spec registry. See test_clog_parent_spec_alone_no_longer_holds.
_CLOG_EPIC = "clog-dashboard-lisp"


def test_clog_parent_spec_alone_no_longer_holds(tmp_path: Path) -> None:
    # Regression for task reform-native-merge-queue: the CLOG epic was removed from
    # SHARED_FILE_EPIC_PARENT_SPECS, so a parent_spec match ALONE (no explicit
    # epic_serialize field) must NOT trigger a pre-admission affinity hold — the
    # native merge queue's speculative branches now serialize shared-file contention.
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="clog-c",
        status="ready",
        pr=350,
        assigned_to="eta",
        parent_spec=_CLOG_SPEC,
    )
    _write_task(
        vault,
        task_id="clog-b",
        status="in_progress",
        assigned_to="zeta",
        parent_spec=_CLOG_SPEC,
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(350)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert not any(
        reason.startswith("shared_file_epic_affinity_hold:")
        for reason in report["decisions"][0].get("reasons", [])
    )
    assert report["counts"]["queue"] == 1


def test_shared_file_epic_holds_pr_when_sibling_in_progress_in_other_lane(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="clog-c",
        status="ready",
        pr=300,
        assigned_to="eta",
        parent_spec=_CLOG_SPEC,
        extra_frontmatter={"epic_serialize": _CLOG_EPIC},
    )
    # Sibling mid-edit in a different lane: in flight, no PR yet.
    _write_task(
        vault,
        task_id="clog-b",
        status="in_progress",
        assigned_to="zeta",
        parent_spec=_CLOG_SPEC,
        extra_frontmatter={"epic_serialize": _CLOG_EPIC},
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(300)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["blocked"] == 1
    reasons = report["decisions"][0]["reasons"]
    assert any(
        reason.startswith("shared_file_epic_affinity_hold:clog-dashboard-lisp:clog-b@zeta")
        for reason in reasons
    )
    assert not any(call[:4] == ["gh", "pr", "merge", "300"] for call in runner.calls)


def test_shared_file_epic_allows_pr_when_sibling_same_lane(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="clog-c",
        status="ready",
        pr=310,
        assigned_to="eta",
        parent_spec=_CLOG_SPEC,
        extra_frontmatter={"epic_serialize": _CLOG_EPIC},
    )
    _write_task(
        vault,
        task_id="clog-d",
        status="in_progress",
        assigned_to="eta",  # same lane: serial work, no hazard
        parent_spec=_CLOG_SPEC,
        extra_frontmatter={"epic_serialize": _CLOG_EPIC},
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(310)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["queue"] == 1
    assert not any(
        reason.startswith("shared_file_epic_affinity_hold:")
        for reason in report["decisions"][0].get("reasons", [])
    )


def test_shared_file_epic_allows_pr_when_only_terminal_sibling(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="clog-c",
        status="ready",
        pr=320,
        assigned_to="eta",
        parent_spec=_CLOG_SPEC,
        extra_frontmatter={"epic_serialize": _CLOG_EPIC},
    )
    # Predecessor merged+closed in another lane: not in flight, must not hold.
    _write_task(
        vault,
        task_id="clog-a",
        folder="closed",
        status="done",
        assigned_to="zeta",
        parent_spec=_CLOG_SPEC,
        extra_frontmatter={"epic_serialize": _CLOG_EPIC},
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(320)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["queue"] == 1


def test_shared_file_epic_lowest_pr_proceeds_across_lanes(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="clog-c",
        status="ready",
        pr=330,
        assigned_to="eta",
        parent_spec=_CLOG_SPEC,
        extra_frontmatter={"epic_serialize": _CLOG_EPIC},
    )
    _write_task(
        vault,
        task_id="clog-e",
        status="ready",
        pr=331,
        assigned_to="zeta",
        parent_spec=_CLOG_SPEC,
        extra_frontmatter={"epic_serialize": _CLOG_EPIC},
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(330), _pr(331)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    decisions = {item["pr"]: item for item in report["decisions"]}
    # Lower PR (opened first) proceeds; higher PR holds — deterministic, no deadlock.
    assert decisions[330]["action"] == "queue"
    assert decisions[331]["action"] == "blocked"
    assert any(
        reason.startswith("shared_file_epic_affinity_hold:clog-dashboard-lisp:clog-c@eta")
        for reason in decisions[331]["reasons"]
    )
    assert [
        "gh",
        "pr",
        "merge",
        "330",
        "--repo",
        "owner/repo",
        "--auto",
        "--squash",
    ] in runner.calls
    assert not any(call[:4] == ["gh", "pr", "merge", "331"] for call in runner.calls)


def test_shared_file_epic_detected_via_explicit_epic_serialize_field(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    # parent_spec NOT in the registry — membership comes from the explicit field.
    _write_task(
        vault,
        task_id="x-consumer",
        status="ready",
        pr=340,
        assigned_to="eta",
        parent_spec="docs/other.md",
        extra_frontmatter={"epic_serialize": "my-shared-file-epic"},
    )
    _write_task(
        vault,
        task_id="x-producer",
        status="in_progress",
        assigned_to="zeta",
        parent_spec="docs/other.md",
        extra_frontmatter={"epic_serialize": "my-shared-file-epic"},
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(340)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["blocked"] == 1
    assert any(
        reason.startswith("shared_file_epic_affinity_hold:my-shared-file-epic:x-producer@zeta")
        for reason in report["decisions"][0]["reasons"]
    )


def test_non_epic_pr_not_held_by_unrelated_in_progress_task(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="plain",
        status="ready",
        pr=350,
        assigned_to="eta",
        parent_spec="docs/spec.md",
    )
    _write_task(
        vault,
        task_id="other",
        status="in_progress",
        assigned_to="zeta",
        parent_spec="docs/spec.md",
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(350)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    # No shared-file epic → no affinity hold; ordinary PR queues.
    assert report["counts"]["queue"] == 1
    assert not any(
        reason.startswith("shared_file_epic_affinity_hold:")
        for reason in report["decisions"][0].get("reasons", [])
    )


# --- G3: idempotent admission writes (kill the 422 self-DoS) -----------------


def _admission_decision(number: int = 50, action: str = "queue") -> Any:
    pr = autoqueue._parse_pr(_pr(number))
    assert pr is not None
    return autoqueue.Decision(pr=pr, action=action)


def _admission_posts(runner: _FakeRunner) -> list[list[str]]:
    return [call for call in runner.calls if call[:4] == ["gh", "api", "-X", "POST"]]


def _existing_status(state: str, description: str, created_at: str) -> dict[str, Any]:
    return {
        "context": autoqueue.AUTOQUEUE_ADMISSION_CONTEXT,
        "state": state,
        "description": description,
        "created_at": created_at,
    }


def test_admission_status_posts_when_no_current_status(tmp_path: Path) -> None:
    decision = _admission_decision()
    runner = _FakeRunner()  # no existing status on the head SHA
    result = autoqueue.set_autoqueue_admission_status(
        decision, repo="owner/repo", repo_root=tmp_path, runner=runner
    )
    assert result is not None and result[0]
    assert len(_admission_posts(runner)) == 1


def test_admission_status_idempotent_when_unchanged_and_fresh(tmp_path: Path) -> None:
    decision = _admission_decision()
    state, description = autoqueue._admission_status_for(decision)
    runner = _FakeRunner()
    runner.head_statuses["sha-50"] = [_existing_status(state, description, "2026-06-02T00:00:00Z")]
    # 5 minutes later: well within TTL/2 (15 min) -> skip the redundant POST.
    now = datetime(2026, 6, 2, 0, 5, tzinfo=UTC)
    result = autoqueue.set_autoqueue_admission_status(
        decision, repo="owner/repo", repo_root=tmp_path, runner=runner, now=now
    )
    assert result == (True, "unchanged")
    assert _admission_posts(runner) == []


def test_admission_status_force_fresh_success_posts_when_unchanged(
    tmp_path: Path,
) -> None:
    decision = _admission_decision()
    state, description = autoqueue._admission_status_for(decision)
    runner = _FakeRunner()
    runner.head_statuses["sha-50"] = [_existing_status(state, description, "2026-06-02T00:00:00Z")]
    now = datetime(2026, 6, 2, 0, 5, tzinfo=UTC)

    result = autoqueue.set_autoqueue_admission_status(
        decision,
        repo="owner/repo",
        repo_root=tmp_path,
        runner=runner,
        now=now,
        force_fresh_success=True,
    )

    assert result is not None and result[0]
    posts = _admission_posts(runner)
    assert len(posts) == 1
    assert "state=success" in posts[0]


def test_admission_status_reposts_when_stale(tmp_path: Path) -> None:
    decision = _admission_decision()
    state, description = autoqueue._admission_status_for(decision)
    runner = _FakeRunner()
    runner.head_statuses["sha-50"] = [_existing_status(state, description, "2026-06-02T00:00:00Z")]
    # 20 minutes later: older than TTL/2 (15 min) -> re-post to stay fresh.
    now = datetime(2026, 6, 2, 0, 20, tzinfo=UTC)
    result = autoqueue.set_autoqueue_admission_status(
        decision, repo="owner/repo", repo_root=tmp_path, runner=runner, now=now
    )
    assert result is not None and result[0]
    assert len(_admission_posts(runner)) == 1


def test_admission_status_defers_fresh_failure_description_change(
    tmp_path: Path,
) -> None:
    decision = _admission_decision(action="blocked")
    runner = _FakeRunner()
    runner.head_statuses["sha-50"] = [
        _existing_status(
            "failure",
            "cc-pr-autoqueue blocked: old reason",
            "2026-06-02T00:00:00Z",
        )
    ]
    now = datetime(2026, 6, 2, 0, 1, tzinfo=UTC)

    result = autoqueue.set_autoqueue_admission_status(
        decision, repo="owner/repo", repo_root=tmp_path, runner=runner, now=now
    )

    assert result == (True, "deferred_failure_description_update")
    assert _admission_posts(runner) == []


def test_admission_status_does_not_repost_unchanged_failure_status(
    tmp_path: Path,
) -> None:
    decision = _admission_decision(action="blocked")
    state, description = autoqueue._admission_status_for(decision)
    runner = _FakeRunner()
    runner.head_statuses["sha-50"] = [_existing_status(state, description, "2026-06-02T00:00:00Z")]
    now = datetime(2026, 6, 2, 1, 0, tzinfo=UTC)

    result = autoqueue.set_autoqueue_admission_status(
        decision, repo="owner/repo", repo_root=tmp_path, runner=runner, now=now
    )

    assert result == (True, "unchanged_failure_state")
    assert _admission_posts(runner) == []


def test_admission_status_refreshes_stale_failure_description_change(
    tmp_path: Path,
) -> None:
    decision = _admission_decision(action="blocked")
    runner = _FakeRunner()
    runner.head_statuses["sha-50"] = [
        _existing_status(
            "failure",
            "cc-pr-autoqueue blocked: old reason",
            "2026-06-02T00:00:00Z",
        )
    ]
    now = datetime(2026, 6, 2, 1, 0, tzinfo=UTC)

    result = autoqueue.set_autoqueue_admission_status(
        decision, repo="owner/repo", repo_root=tmp_path, runner=runner, now=now
    )

    assert result is not None and result[0]
    posts = _admission_posts(runner)
    assert len(posts) == 1
    assert "state=failure" in posts[0]


def test_admission_status_posts_when_verdict_changed(tmp_path: Path) -> None:
    decision = _admission_decision()  # success verdict
    runner = _FakeRunner()
    runner.head_statuses["sha-50"] = [
        _existing_status("failure", "cc-pr-autoqueue blocked: stale", "2026-06-02T00:00:00Z")
    ]
    # Fresh, but the verdict flipped failure -> success: must POST.
    now = datetime(2026, 6, 2, 0, 1, tzinfo=UTC)
    result = autoqueue.set_autoqueue_admission_status(
        decision, repo="owner/repo", repo_root=tmp_path, runner=runner, now=now
    )
    assert result is not None and result[0]
    assert len(_admission_posts(runner)) == 1


def test_admission_status_posts_when_success_flips_to_failure(tmp_path: Path) -> None:
    decision = _admission_decision(action="blocked")
    runner = _FakeRunner()
    runner.head_statuses["sha-50"] = [
        _existing_status("success", "cc-pr-autoqueue admitted: queue", "2026-06-02T00:00:00Z")
    ]
    now = datetime(2026, 6, 2, 0, 1, tzinfo=UTC)

    result = autoqueue.set_autoqueue_admission_status(
        decision, repo="owner/repo", repo_root=tmp_path, runner=runner, now=now
    )

    assert result is not None and result[0]
    posts = _admission_posts(runner)
    assert len(posts) == 1
    assert "state=failure" in posts[0]


def test_blocks_review_floor_pr_without_acceptance_receipt(tmp_path: Path) -> None:
    """Routing Phase 0.2: review-floor admission demands a signed receipt."""
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="review-floor-task",
        pr=88,
        quality_floor="frontier_review_required",
        authority_level="support_non_authoritative",
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(88)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        runner=runner,
    )

    assert report["counts"]["blocked"] == 1
    assert "missing_acceptance_receipt" in report["decisions"][0]["reasons"]


def test_queues_review_floor_pr_with_acceptance_receipt(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="review-floor-task",
        pr=89,
        quality_floor="frontier_review_required",
        authority_level="support_non_authoritative",
    )
    (vault / "active" / "review-floor-task.acceptance.yaml").write_text(
        "acceptor: operator\n"
        "verdict: accepted\n"
        "timestamp: 2026-06-10T17:00:00Z\n"
        "artifact: https://github.com/owner/repo/pull/89\n",
        encoding="utf-8",
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(89)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
    )

    assert report["counts"]["queue"] == 1


def test_blocks_review_floor_pr_with_rejected_receipt(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="review-floor-task",
        pr=90,
        quality_floor="frontier_review_required",
        authority_level="support_non_authoritative",
    )
    (vault / "active" / "review-floor-task.acceptance.yaml").write_text(
        "acceptor: operator\n"
        "verdict: rejected\n"
        "timestamp: 2026-06-10T17:00:00Z\n"
        "artifact: https://github.com/owner/repo/pull/90\n",
        encoding="utf-8",
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(90)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        runner=runner,
    )

    assert report["counts"]["blocked"] == 1
    assert "acceptance_receipt_verdict_not_accepted:rejected" in report["decisions"][0]["reasons"]


def test_review_floor_receipt_detected_from_nested_route_metadata(tmp_path: Path) -> None:
    """The mirrored route_metadata block alone is enough to arm the gate."""
    vault = _make_vault(tmp_path)
    _write_task(
        vault,
        task_id="nested-floor-task",
        pr=91,
        quality_floor="frontier_required",
        extra_frontmatter={
            "route_metadata": {
                "route_metadata_schema": 1,
                "quality_floor": "frontier_review_required",
            }
        },
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(91)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        runner=runner,
    )

    assert report["counts"]["blocked"] == 1
    assert "missing_acceptance_receipt" in report["decisions"][0]["reasons"]
