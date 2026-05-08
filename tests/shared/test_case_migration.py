"""Tests for shared.case_migration — cc-task to AuthorityCase migration logic.

ISAP: SLICE-007-MIGRATION-CLOSURE (CASE-SDLC-REFORM-001)
"""

from __future__ import annotations

from pathlib import Path

from shared.case_migration import (
    CcTask,
    annotate_task_file,
    classify_risk_tier,
    generate_case_id,
    generate_stub,
    map_decision,
    map_stage,
    parse_cc_task,
    scan_tasks,
)


def _write_task(tmp_path: Path, task_id: str, **overrides: object) -> Path:
    fields = {
        "type": "cc-task",
        "task_id": task_id,
        "title": f"Test task {task_id}",
        "status": "offered",
        "assigned_to": "unassigned",
        "priority": "p2",
        "wsjf": 3.0,
        "depends_on": [],
        "blocks": [],
        "branch": None,
        "pr": None,
        "blocked_reason": None,
        "train": None,
        "tags": ["cc-task"],
    }
    fields.update(overrides)
    import yaml

    fm = yaml.dump(fields, default_flow_style=False, sort_keys=False, allow_unicode=True)
    p = tmp_path / f"{task_id}.md"
    p.write_text(f"---\n{fm}---\n\n# {task_id}\n\nBody text.\n", encoding="utf-8")
    return p


class TestParseTask:
    def test_parses_valid_task(self, tmp_path: Path) -> None:
        p = _write_task(tmp_path, "test-parse")
        task = parse_cc_task(p)
        assert task is not None
        assert task.task_id == "test-parse"
        assert task.status == "offered"

    def test_returns_none_for_non_cc_task(self, tmp_path: Path) -> None:
        p = tmp_path / "not-a-task.md"
        p.write_text("---\ntype: note\ntask_id: x\n---\n\nNope.\n")
        assert parse_cc_task(p) is None

    def test_returns_none_for_no_frontmatter(self, tmp_path: Path) -> None:
        p = tmp_path / "no-fm.md"
        p.write_text("Just plain text.\n")
        assert parse_cc_task(p) is None

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        assert parse_cc_task(tmp_path / "nonexistent.md") is None


class TestClassifyRiskTier:
    def test_governance_tag_is_t3(self) -> None:
        t = CcTask(task_id="x", tags=["governance", "cc-task"])
        assert classify_risk_tier(t) == "T3"

    def test_public_tag_is_t3(self) -> None:
        t = CcTask(task_id="x", tags=["public", "cc-task"])
        assert classify_risk_tier(t) == "T3"

    def test_compositor_tag_is_t2(self) -> None:
        t = CcTask(task_id="x", tags=["compositor", "cc-task"])
        assert classify_risk_tier(t) == "T2"

    def test_audio_tag_is_t2(self) -> None:
        t = CcTask(task_id="x", tags=["audio", "cc-task"])
        assert classify_risk_tier(t) == "T2"

    def test_service_tag_is_t1(self) -> None:
        t = CcTask(task_id="x", tags=["service", "cc-task"])
        assert classify_risk_tier(t) == "T1"

    def test_p0_priority_defaults_to_t2(self) -> None:
        t = CcTask(task_id="x", priority="p0", tags=["cc-task"])
        assert classify_risk_tier(t) == "T2"

    def test_critical_priority_defaults_to_t2(self) -> None:
        t = CcTask(task_id="x", priority="critical", tags=["cc-task"])
        assert classify_risk_tier(t) == "T2"

    def test_plain_task_is_t0(self) -> None:
        t = CcTask(task_id="x", priority="p3", tags=["cc-task"])
        assert classify_risk_tier(t) == "T0"

    def test_t3_beats_t2(self) -> None:
        t = CcTask(task_id="x", tags=["governance", "compositor"])
        assert classify_risk_tier(t) == "T3"


class TestMapStage:
    def test_offered_is_s0(self) -> None:
        assert map_stage(CcTask(task_id="x", status="offered")) == "S0"

    def test_blocked_is_s0(self) -> None:
        assert map_stage(CcTask(task_id="x", status="blocked")) == "S0"

    def test_claimed_no_branch_is_s1(self) -> None:
        assert map_stage(CcTask(task_id="x", status="claimed")) == "S1"

    def test_claimed_with_branch_is_s6(self) -> None:
        assert map_stage(CcTask(task_id="x", status="claimed", branch="feat/x")) == "S6"

    def test_in_progress_is_s6(self) -> None:
        assert map_stage(CcTask(task_id="x", status="in_progress")) == "S6"

    def test_pr_open_is_s7(self) -> None:
        assert map_stage(CcTask(task_id="x", status="pr_open")) == "S7"

    def test_completed_is_s11(self) -> None:
        assert map_stage(CcTask(task_id="x", status="completed")) == "S11"

    def test_withdrawn_is_s11(self) -> None:
        assert map_stage(CcTask(task_id="x", status="withdrawn")) == "S11"


class TestMapDecision:
    def test_offered_is_unresolved(self) -> None:
        assert map_decision(CcTask(task_id="x", status="offered")) == "unresolved"

    def test_blocked_is_quarantined(self) -> None:
        assert map_decision(CcTask(task_id="x", status="blocked")) == "quarantined"

    def test_completed_is_adopted(self) -> None:
        assert map_decision(CcTask(task_id="x", status="completed")) == "adopted"

    def test_withdrawn_is_retired(self) -> None:
        assert map_decision(CcTask(task_id="x", status="withdrawn")) == "retired"

    def test_in_progress_with_branch_is_adopted_with_limits(self) -> None:
        t = CcTask(task_id="x", status="in_progress", branch="feat/x")
        assert map_decision(t) == "adopted_with_limits"

    def test_in_progress_no_branch_is_unresolved(self) -> None:
        t = CcTask(task_id="x", status="in_progress")
        assert map_decision(t) == "unresolved"


class TestGenerateStub:
    def test_offered_task_stub(self) -> None:
        t = CcTask(task_id="my-task", status="offered", tags=["cc-task"])
        stub = generate_stub(t)
        assert stub.case_id == "CASE-LEGACY-my-task"
        assert stub.authority_case_stage == "S0"
        assert stub.migration_decision == "unresolved"
        assert stub.implementation_authorized is False

    def test_active_task_with_branch(self) -> None:
        t = CcTask(
            task_id="active-work",
            status="in_progress",
            branch="beta/active-work",
            tags=["compositor", "cc-task"],
        )
        stub = generate_stub(t)
        assert stub.authority_case_stage == "S6"
        assert stub.risk_tier == "T2"
        assert stub.migration_decision == "adopted_with_limits"


class TestCaseId:
    def test_deterministic(self) -> None:
        t = CcTask(task_id="foo-bar-baz")
        assert generate_case_id(t) == "CASE-LEGACY-foo-bar-baz"

    def test_underscores_replaced(self) -> None:
        t = CcTask(task_id="foo_bar")
        assert generate_case_id(t) == "CASE-LEGACY-foo-bar"


class TestAnnotateTaskFile:
    def test_injects_case_fields(self, tmp_path: Path) -> None:
        p = _write_task(tmp_path, "annotate-me")
        task = parse_cc_task(p)
        assert task is not None
        stub = generate_stub(task)
        new_content = annotate_task_file(p, stub)

        assert "case_id: CASE-LEGACY-annotate-me" in new_content
        assert "authority_case_stage: S0" in new_content
        assert "risk_tier: T0" in new_content
        assert "migration_decision: unresolved" in new_content
        assert "# annotate-me" in new_content

    def test_preserves_body(self, tmp_path: Path) -> None:
        p = _write_task(tmp_path, "body-test")
        task = parse_cc_task(p)
        assert task is not None
        stub = generate_stub(task)
        new_content = annotate_task_file(p, stub)
        assert "Body text." in new_content


class TestScanTasks:
    def test_scans_directory(self, tmp_path: Path) -> None:
        _write_task(tmp_path, "task-a")
        _write_task(tmp_path, "task-b", status="blocked", blocked_reason="depends on X")
        _write_task(tmp_path, "task-c", status="completed")
        (tmp_path / "not-a-task.txt").write_text("ignored")

        tasks = scan_tasks(tmp_path)
        assert len(tasks) == 3
        ids = {t.task_id for t in tasks}
        assert ids == {"task-a", "task-b", "task-c"}

    def test_empty_dir(self, tmp_path: Path) -> None:
        assert scan_tasks(tmp_path) == []
