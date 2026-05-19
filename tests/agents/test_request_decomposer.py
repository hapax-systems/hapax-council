"""End-to-end tests for the request decomposer pipeline."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agents.request_decomposer.models import RequestDecomposition, TaskSpec
from agents.request_decomposer.writer import write_decomposition


class TestTaskSpec:
    def test_valid_task(self):
        t = TaskSpec(
            task_id="test-task",
            title="Test task",
            parent_request="REQ-test.md",
            authority_case="CASE-TEST",
            acceptance_criteria=["It works"],
        )
        assert t.task_id == "test-task"
        assert t.status == "offered"

    def test_blocked_requires_reason(self):
        with pytest.raises(ValueError, match="blocked_reason"):
            TaskSpec(
                task_id="test-blocked",
                title="Blocked task",
                status="blocked",
                parent_request="REQ-test.md",
                authority_case="CASE-TEST",
                acceptance_criteria=["It works"],
            )

    def test_blocked_with_reason_ok(self):
        t = TaskSpec(
            task_id="test-blocked",
            title="Blocked task",
            status="blocked",
            blocked_reason="Phase 1 not done",
            parent_request="REQ-test.md",
            authority_case="CASE-TEST",
            acceptance_criteria=["It works"],
        )
        assert t.blocked_reason == "Phase 1 not done"

    def test_empty_ac_rejected(self):
        with pytest.raises(ValueError, match="acceptance criteria"):
            TaskSpec(
                task_id="test-no-ac",
                title="No AC",
                parent_request="REQ-test.md",
                authority_case="CASE-TEST",
                acceptance_criteria=[],
            )


class TestRequestDecomposition:
    def _make_task(self, task_id: str, **kw) -> TaskSpec:
        defaults = {
            "title": f"Task {task_id}",
            "parent_request": "REQ-test.md",
            "authority_case": "CASE-TEST",
            "acceptance_criteria": ["Done"],
        }
        defaults.update(kw)
        return TaskSpec(task_id=task_id, **defaults)

    def test_valid_decomposition(self):
        d = RequestDecomposition(
            request_id="test",
            request_path="/tmp/test.md",
            tasks=[self._make_task("a"), self._make_task("b")],
        )
        assert len(d.tasks) == 2

    def test_duplicate_ids_rejected(self):
        with pytest.raises(ValueError, match="duplicate"):
            RequestDecomposition(
                request_id="test",
                request_path="/tmp/test.md",
                tasks=[self._make_task("a"), self._make_task("a")],
            )

    def test_unknown_dependency_rejected(self):
        with pytest.raises(ValueError, match="depends_on unknown"):
            RequestDecomposition(
                request_id="test",
                request_path="/tmp/test.md",
                tasks=[self._make_task("a", depends_on=["nonexistent"])],
            )

    def test_cycle_rejected(self):
        with pytest.raises(ValueError, match="cycle"):
            RequestDecomposition(
                request_id="test",
                request_path="/tmp/test.md",
                tasks=[
                    self._make_task("a", depends_on=["b"]),
                    self._make_task("b", depends_on=["a"]),
                ],
            )

    def test_valid_dependency_chain(self):
        d = RequestDecomposition(
            request_id="test",
            request_path="/tmp/test.md",
            tasks=[
                self._make_task("a"),
                self._make_task("b", depends_on=["a"]),
                self._make_task("c", depends_on=["b"]),
            ],
        )
        assert len(d.tasks) == 3

    def test_missing_parent_request_rejected(self):
        with pytest.raises(ValueError, match="parent_request"):
            RequestDecomposition(
                request_id="test",
                request_path="/tmp/test.md",
                tasks=[
                    TaskSpec(
                        task_id="orphan",
                        title="Orphan",
                        parent_request="",
                        authority_case="CASE-TEST",
                        acceptance_criteria=["Done"],
                    )
                ],
            )


class TestWriter:
    def _make_decomp(self) -> RequestDecomposition:
        return RequestDecomposition(
            request_id="test-write",
            request_path="/tmp/test.md",
            tasks=[
                TaskSpec(
                    task_id="write-phase1",
                    title="Phase 1",
                    parent_request="REQ-test.md",
                    authority_case="CASE-TEST",
                    acceptance_criteria=["Schema exists", "Tests pass"],
                    intent="Create the schema.",
                ),
                TaskSpec(
                    task_id="write-phase2",
                    title="Phase 2",
                    depends_on=["write-phase1"],
                    status="blocked",
                    blocked_reason="Phase 1 not done",
                    parent_request="REQ-test.md",
                    authority_case="CASE-TEST",
                    acceptance_criteria=["API works"],
                    intent="Wire the API.",
                ),
            ],
        )

    def test_dry_run_returns_paths(self):
        with tempfile.TemporaryDirectory() as td:
            paths = write_decomposition(self._make_decomp(), Path(td), dry_run=True)
            assert len(paths) == 2
            assert not any(p.exists() for p in paths)

    def test_real_write_creates_files(self):
        with tempfile.TemporaryDirectory() as td:
            paths = write_decomposition(self._make_decomp(), Path(td))
            assert len(paths) == 2
            assert all(p.exists() for p in paths)
            for p in paths:
                content = p.read_text()
                assert "type: cc-task" in content
                assert "parent_request: REQ-test.md" in content

    def test_blocks_computed(self):
        with tempfile.TemporaryDirectory() as td:
            paths = write_decomposition(self._make_decomp(), Path(td))
            phase1 = [p for p in paths if "phase1" in p.name][0]
            content = phase1.read_text()
            assert "write-phase2" in content

    def test_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            write_decomposition(self._make_decomp(), Path(td))
            with pytest.raises(FileExistsError):
                write_decomposition(self._make_decomp(), Path(td))
