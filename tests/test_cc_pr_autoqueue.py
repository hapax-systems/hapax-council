"""Tests for ``scripts/cc-pr-autoqueue.py``."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

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
        "headRefOid": f"sha-{number}",
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
        if cmd[:4] == ["gh", "api", "-X", "POST"] and "/statuses/" in cmd[4]:
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
    assert any(
        call[:5] == ["gh", "api", "-X", "POST", "repos/owner/repo/statuses/sha-42"]
        and f"context={autoqueue.AUTOQUEUE_ADMISSION_CONTEXT}" in call
        and "state=success" in call
        for call in runner.calls
    )
    assert ["gh", "pr", "merge", "42", "--repo", "owner/repo", "--merge"] in runner.calls


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
    assert ["gh", "pr", "merge", "121", "--repo", "owner/repo", "--merge"] in runner.calls
    assert ["gh", "pr", "merge", "122", "--repo", "owner/repo", "--merge"] in runner.calls
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


def test_auto_arms_eligible_pr_open_task_then_merges(tmp_path: Path) -> None:
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

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=tmp_path / "ledger.jsonl",
    )

    # The note is armed in place: release authorized + advanced to S7.
    armed = note.read_text(encoding="utf-8")
    assert "release_authorized: true" in armed
    assert "release_authorized: false" not in armed
    assert "stage: S7_RELEASE" in armed
    # And the PR is admitted to the merge queue.
    assert ["gh", "pr", "merge", "701", "--repo", "owner/repo", "--merge"] in runner.calls
    decision = next(d for d in report["decisions"] if d["pr"] == 701)
    assert decision["auto_arm"] is True


def test_does_not_auto_arm_governance_sensitive_task(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _write_task(
        vault,
        task_id="stranded-governance",
        status="pr_open",
        pr=702,
        tags=["governance"],
        extra_frontmatter=_eligible_arm_extra(),
    )
    runner = _FakeRunner()
    runner.open_prs = [_pr(702)]

    report = autoqueue.run_reconciler(
        repo="owner/repo",
        repo_root=tmp_path,
        vault_root=vault,
        apply=True,
        runner=runner,
        auto_arm_ledger_path=tmp_path / "ledger.jsonl",
    )

    # Sensitive task stays manual: never armed, never merged.
    untouched = note.read_text(encoding="utf-8")
    assert "release_authorized: false" in untouched
    assert "stage: S7_RELEASE" not in untouched
    assert not any(call[:4] == ["gh", "pr", "merge", "702"] for call in runner.calls)
    decision = next(d for d in report["decisions"] if d["pr"] == 702)
    assert decision["action"] == "blocked"
    assert any("release_auto_arm_ineligible" in reason for reason in decision["reasons"])


def test_dry_run_reports_auto_arm_without_writing_note(tmp_path: Path) -> None:
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
    assert decision["auto_arm"] is True


def test_auto_arm_writes_authority_case_ledger_record(tmp_path: Path) -> None:
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

    records = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line]
    assert any(
        rec.get("kind") == "release_auto_arm" and rec.get("task_id") == "stranded-ledger"
        for rec in records
    )


def test_already_release_authorized_task_is_not_rearmed(tmp_path: Path) -> None:
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

    # Already armed → merges normally, no auto-arm audit line appended.
    assert "release auto-arm (system)" not in note.read_text(encoding="utf-8")
    assert ["gh", "pr", "merge", "705", "--repo", "owner/repo", "--merge"] in runner.calls
    decision = next(d for d in report["decisions"] if d["pr"] == 705)
    assert decision.get("auto_arm", False) is False


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
    assert ["gh", "pr", "merge", "330", "--repo", "owner/repo", "--merge"] in runner.calls
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
