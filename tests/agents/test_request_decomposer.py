"""End-to-end tests for the request decomposer pipeline."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

from agents.request_decomposer.models import RequestDecomposition, TaskSpec
from agents.request_decomposer.writer import write_decomposition
from shared.frontmatter import parse_frontmatter

_ROOT = Path(__file__).resolve().parents[2]


def _load_request_decompose_module() -> ModuleType:
    if "request_decompose_script" in sys.modules:
        return sys.modules["request_decompose_script"]
    path = _ROOT / "scripts" / "request-decompose"
    loader = SourceFileLoader("request_decompose_script", str(path))
    spec = importlib.util.spec_from_loader("request_decompose_script", loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["request_decompose_script"] = module
    spec.loader.exec_module(module)
    return module


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

    def test_missing_authority_case_rejected(self):
        with pytest.raises(ValueError, match="authority_case"):
            TaskSpec(
                task_id="test-no-auth",
                title="No auth case",
                parent_request="REQ-test.md",
                acceptance_criteria=["Done"],
            )

    def test_invalid_authority_case_rejected(self):
        with pytest.raises(ValueError, match="authority_case"):
            TaskSpec(
                task_id="test-bad-auth",
                title="Bad auth case",
                parent_request="REQ-test.md",
                authority_case="not-a-case",
                acceptance_criteria=["Done"],
            )

    def test_research_packet_exempt_from_authority_case(self):
        t = TaskSpec(
            task_id="test-research",
            title="Research task",
            kind="research_packet",
            acceptance_criteria=["Done"],
        )
        assert t.authority_case == ""

    def test_missing_parent_lineage_rejected(self):
        with pytest.raises(ValueError, match="no parent_spec or parent_request"):
            TaskSpec(
                task_id="test-no-parent",
                title="No parent",
                authority_case="CASE-TEST",
                acceptance_criteria=["Done"],
            )

    def test_parent_spec_satisfies_lineage(self):
        t = TaskSpec(
            task_id="test-spec",
            title="Has spec",
            authority_case="CASE-TEST",
            parent_spec="/some/spec.md",
            acceptance_criteria=["Done"],
        )
        assert t.parent_spec == "/some/spec.md"


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
                assert "route_metadata_schema: 1" in content
                assert "mutation_scope_refs:" in content

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

    def test_real_write_links_parent_request_downstream_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = root / "REQ-test.md"
            request.write_text(
                """---
type: hapax-request
request_id: REQ-test
status: accepted_for_planning
---

# Request

Body.
""",
                encoding="utf-8",
            )
            decomp = self._make_decomp()
            decomp.request_path = str(request)

            write_decomposition(decomp, root / "tasks")

            frontmatter, _body = parse_frontmatter(request)
            assert frontmatter["downstream_tasks"] == ["write-phase1", "write-phase2"]
            assert frontmatter["decomposition_model"] == "balanced"
            assert frontmatter["decomposition_task_count"] == 2

    def test_dry_run_does_not_link_parent_request(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = root / "REQ-test.md"
            original = """---
type: hapax-request
request_id: REQ-test
status: accepted_for_planning
---

# Request
"""
            request.write_text(original, encoding="utf-8")
            decomp = self._make_decomp()
            decomp.request_path = str(request)

            write_decomposition(decomp, root / "tasks", dry_run=True)

            assert request.read_text(encoding="utf-8") == original


class TestRequestDecomposeScan:
    def test_scan_limit_prefers_cli_then_env(self):
        script = _load_request_decompose_module()

        assert script._parse_scan_limit(2, "3") == 2
        assert script._parse_scan_limit(None, "3") == 3
        assert script._parse_scan_limit(None, None) is None
        assert script._parse_scan_limit(None, "") is None

    @pytest.mark.parametrize("value", [0, -1, "0", "not-a-number"])
    def test_scan_limit_rejects_non_positive_values(self, value):
        script = _load_request_decompose_module()

        with pytest.raises(ValueError, match="positive integer"):
            script._parse_scan_limit(None, value)

    def test_scan_limit_selects_prefix(self):
        script = _load_request_decompose_module()
        requests = [Path("a.md"), Path("b.md"), Path("c.md")]

        assert script._limit_scan_requests(requests, None) == requests
        assert script._limit_scan_requests(requests, 2) == requests[:2]
        assert script._limit_scan_requests(requests, 10) == requests

    def test_scan_uses_full_frontmatter_for_parent_request(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        requests = tmp_path / "requests" / "active"
        tasks = tmp_path / "tasks"
        requests.mkdir(parents=True)
        (tasks / "active").mkdir(parents=True)
        (tasks / "closed").mkdir(parents=True)

        request = requests / "REQ-long.md"
        request.write_text(
            """---
type: hapax-request
request_id: REQ-long
status: accepted_for_planning
owner: test
padding:
  - aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  - bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
  - ccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
  - ddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
---

# Request
""",
            encoding="utf-8",
        )
        task = tasks / "active" / "linked.md"
        task.write_text(
            """---
type: cc-task
task_id: linked
status: offered
padding:
  - aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  - bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
  - ccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
  - ddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
parent_request: REQ-long.md
---

# Task
""",
            encoding="utf-8",
        )
        monkeypatch.setattr(script, "REQUESTS_DIR", requests)
        monkeypatch.setattr(script, "TASKS_DIR", tasks)

        assert script._find_undecomposed_requests() == []

    def test_scan_skips_requests_with_downstream_tasks(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        requests = tmp_path / "requests" / "active"
        tasks = tmp_path / "tasks"
        requests.mkdir(parents=True)
        (tasks / "active").mkdir(parents=True)
        (tasks / "closed").mkdir(parents=True)

        request = requests / "REQ-linked.md"
        request.write_text(
            """---
type: hapax-request
request_id: REQ-linked
status: accepted_for_planning
downstream_tasks:
  - already-linked
---

# Request
""",
            encoding="utf-8",
        )
        monkeypatch.setattr(script, "REQUESTS_DIR", requests)
        monkeypatch.setattr(script, "TASKS_DIR", tasks)

        assert script._find_undecomposed_requests() == []
