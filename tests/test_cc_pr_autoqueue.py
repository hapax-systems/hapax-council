"""Tests for ``scripts/cc-pr-autoqueue.py``."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

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


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (vault / "active").mkdir(parents=True, exist_ok=True)
    (vault / "closed").mkdir(parents=True, exist_ok=True)
    return vault


def _write_task(
    vault: Path,
    *,
    task_id: str,
    folder: str = "closed",
    status: str = "done",
    pr: int | None = None,
    branch: str | None = None,
    authority_case: str | None = "CASE-TEST",
    parent_spec: str | None = "docs/spec.md",
    route_metadata_schema: int | None = 1,
    priority: str = "p2",
    kind: str = "implementation",
    tags: list[str] | None = None,
    queue_admission: str | None = None,
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
    tags_line = f"tags: [{', '.join(tags or [])}]"
    queue_admission_line = (
        f"queue_admission: {queue_admission}"
        if queue_admission is not None
        else "queue_admission: null"
    )
    path.write_text(
        f"""---
type: cc-task
task_id: {task_id}
title: "{task_id}"
status: {status}
assigned_to: alpha
priority: {priority}
kind: {kind}
{pr_line}
{branch_line}
{authority_line}
{parent_line}
{route_line}
{tags_line}
{queue_admission_line}
---

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
    body: str = "",
    draft: bool = False,
    merge_state: str = "CLEAN",
    checks: list[dict[str, Any]] | None = None,
    labels: list[str] | None = None,
    review_decision: str | None = None,
    auto_merge: bool = False,
) -> dict[str, Any]:
    return {
        "number": number,
        "id": f"PR_test_{number}",
        "title": title or f"PR {number}",
        "body": body,
        "headRefName": branch or f"feat/{number}",
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
        if cmd[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(cmd, 0, json.dumps(self.open_prs), "")
        if cmd[:3] == ["gh", "api", "graphql"] and any(
            "dequeuePullRequest" in part for part in cmd
        ):
            return subprocess.CompletedProcess(cmd, 0, '{"data":{"dequeuePullRequest":{}}}', "")
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
        if cmd[:3] == ["gh", "pr", "merge"]:
            return subprocess.CompletedProcess(cmd, 0, f"merged {cmd[3]}\n", "")
        return subprocess.CompletedProcess(cmd, 1, "", "unexpected command")


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
    assert ["gh", "pr", "merge", "42", "--repo", "owner/repo", "--merge"] in runner.calls


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
    assert ["gh", "pr", "merge", "43", "--repo", "owner/repo", "--auto", "--merge"] in runner.calls


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
    assert ["gh", "pr", "merge", "44", "--repo", "owner/repo", "--auto", "--merge"] in runner.calls


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
    assert ["gh", "pr", "merge", "74", "--repo", "owner/repo", "--merge"] in runner.calls


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
    assert ["gh", "pr", "merge", "90", "--repo", "owner/repo", "--merge"] in runner.calls
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
