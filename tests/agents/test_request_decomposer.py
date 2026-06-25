"""End-to-end tests for the request decomposer pipeline."""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
import tempfile
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from agents.request_decomposer.models import (
    REQUIREMENT_VECTOR_DIMENSIONS,
    RequestDecomposition,
    TaskSpec,
)
from agents.request_decomposer.writer import write_decomposition
from shared.frontmatter import parse_frontmatter
from shared.route_metadata_schema import RouteMetadataStatus, assess_route_metadata

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


def _requirement_vector(**overrides: int) -> dict[str, int]:
    values = {dimension: 1 for dimension in REQUIREMENT_VECTOR_DIMENSIONS}
    values.update(overrides)
    return values


def _validity_mask(**overrides: bool) -> dict[str, bool]:
    values = {dimension: True for dimension in REQUIREMENT_VECTOR_DIMENSIONS}
    values.update(overrides)
    return values


def _route_envelope(**classification_overrides: object) -> dict[str, object]:
    classification: dict[str, object] = {
        "label": "source_python",
        "classifier": "test.deterministic",
        "source_kind": "deterministic",
        "confidence": 0.91,
        "evidence_refs": ["test:classification-evidence"],
        "freshness": "fresh",
        "authority_ceiling": "authoritative",
        "validity_mask": {
            "label": True,
            "source": True,
            "confidence": True,
            "freshness": True,
            "authority_ceiling": True,
        },
        "deterministic_facts_used": ["target_paths:agents/foo/helper.py"],
        "consumer_floor": "frontier_required",
    }
    classification.update(classification_overrides)
    return {
        "classification_envelope": classification,
        "eligibility": {
            "authority_allowed": True,
            "privacy_allowed": True,
            "freshness_ok": True,
            "quality_floor_satisfied": True,
            "required_tools_available": True,
            "budget_allowed": True,
            "reason_codes": ["eligibility_witnessed"],
        },
        "admission": {"admission_action": "route", "reason_codes": ["fresh"]},
    }


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

    def test_taxonomy_fields_are_additive_defaults(self):
        t = TaskSpec(
            task_id="taxonomy-defaults",
            title="No taxonomy yet",
            parent_request="REQ-test.md",
            authority_case="CASE-TEST",
            acceptance_criteria=["It works"],
        )

        assert t.routing_class == "unknown"
        assert t.requirement_vector == {}
        assert t.composition_tolerance == "unknown"
        assert t.requirement_vector_validity_mask == {}

    def test_complete_taxonomy_payload_is_validated(self):
        t = TaskSpec(
            task_id="taxonomy-full",
            title="Classified task",
            parent_request="REQ-test.md",
            authority_case="CASE-TEST",
            acceptance_criteria=["It works"],
            routing_class="source-python",
            requirement_vector=_requirement_vector(
                information_scope=3,
                context_length=2,
                governance_sensitivity=0,
            ),
            composition_tolerance="parallel",
            requirement_vector_validity_mask=_validity_mask(context_length=False),
        )

        assert t.routing_class == "source_python"
        assert t.requirement_vector["information_scope"] == 3
        assert t.composition_tolerance == "parallel_ok"
        assert t.requirement_vector_validity_mask["context_length"] is False

    def test_taxonomy_vector_accepts_ordered_eight_value_sequence(self):
        t = TaskSpec(
            task_id="taxonomy-sequence",
            title="Classified task",
            parent_request="REQ-test.md",
            authority_case="CASE-TEST",
            acceptance_criteria=["It works"],
            routing_class="verification",
            requirement_vector=[0, 1, 2, 3, 4, 5, 4, 3],
            composition_tolerance="atomic",
            requirement_vector_validity_mask=[True] * 8,
        )

        assert t.requirement_vector == dict(
            zip(REQUIREMENT_VECTOR_DIMENSIONS, [0, 1, 2, 3, 4, 5, 4, 3], strict=True)
        )

    def test_partial_taxonomy_vector_rejected(self):
        with pytest.raises(ValueError, match="exactly 8 dimensions"):
            TaskSpec(
                task_id="taxonomy-partial",
                title="Partial taxonomy",
                parent_request="REQ-test.md",
                authority_case="CASE-TEST",
                acceptance_criteria=["It works"],
                routing_class="source_python",
                requirement_vector={"quality_floor": 1},
                requirement_vector_validity_mask={"quality_floor": True},
            )

    def test_taxonomy_without_validity_mask_rejected(self):
        with pytest.raises(ValueError, match="requirement_vector_validity_mask"):
            TaskSpec(
                task_id="taxonomy-no-mask",
                title="No mask",
                parent_request="REQ-test.md",
                authority_case="CASE-TEST",
                acceptance_criteria=["It works"],
                routing_class="source_python",
                requirement_vector=_requirement_vector(),
            )

    def test_invalid_taxonomy_score_rejected(self):
        with pytest.raises(ValueError, match="next action: set each requirement vector score"):
            TaskSpec(
                task_id="taxonomy-bad-score",
                title="Bad score",
                parent_request="REQ-test.md",
                authority_case="CASE-TEST",
                acceptance_criteria=["It works"],
                routing_class="source_python",
                requirement_vector=_requirement_vector(context_length=6),
                requirement_vector_validity_mask=_validity_mask(),
            )

    def test_invalid_taxonomy_mask_error_includes_next_action(self):
        validity_mask: dict[str, object] = _validity_mask()
        validity_mask["context_length"] = "maybe"

        with pytest.raises(
            ValueError,
            match="next action: set each requirement_vector_validity_mask value",
        ):
            TaskSpec(
                task_id="taxonomy-bad-mask",
                title="Bad mask",
                parent_request="REQ-test.md",
                authority_case="CASE-TEST",
                acceptance_criteria=["It works"],
                routing_class="source_python",
                requirement_vector=_requirement_vector(),
                requirement_vector_validity_mask=validity_mask,
            )

    def test_unknown_taxonomy_dimension_error_includes_next_action(self):
        with pytest.raises(ValueError, match="next action: provide one value"):
            TaskSpec(
                task_id="taxonomy-unknown-dimension",
                title="Unknown taxonomy dimension",
                parent_request="REQ-test.md",
                authority_case="CASE-TEST",
                acceptance_criteria=["It works"],
                routing_class="source_python",
                requirement_vector={**_requirement_vector(), "unknown_dimension": 1},
                requirement_vector_validity_mask=_validity_mask(),
            )

    def test_route_envelope_is_carried_when_high_confidence_is_justified(self):
        t = TaskSpec(
            task_id="route-envelope",
            title="Route envelope",
            parent_request="REQ-test.md",
            authority_case="CASE-TEST",
            acceptance_criteria=["It works"],
            route_envelope=_route_envelope(),
        )

        assert t.route_envelope is not None
        assert t.route_envelope.classification_envelope.label == "source_python"

    def test_high_confidence_route_envelope_without_evidence_is_rejected(self):
        with pytest.raises(ValueError, match="high-confidence classification"):
            TaskSpec(
                task_id="route-envelope-bad",
                title="Route envelope bad",
                parent_request="REQ-test.md",
                authority_case="CASE-TEST",
                acceptance_criteria=["It works"],
                route_envelope=_route_envelope(evidence_refs=[], deterministic_facts_used=[]),
            )

    def test_d8_rust_source_forces_frontier(self):
        t = TaskSpec(
            task_id="d8-rs",
            title="touch a rust file",
            mutation_surface="source",
            target_paths=["agents/foo/render.rs"],
            parent_request="REQ-test.md",
            authority_case="CASE-TEST",
            acceptance_criteria=["x"],
        )
        assert t.quality_floor == "frontier_required"

    def test_d8_wgsl_source_forces_frontier(self):
        t = TaskSpec(
            task_id="d8-wgsl",
            title="touch a shader",
            mutation_surface="source",
            target_paths=["agents/foo/cymatic.wgsl"],
            parent_request="REQ-test.md",
            authority_case="CASE-TEST",
            acceptance_criteria=["x"],
        )
        assert t.quality_floor == "frontier_required"

    def test_d8_codeowners_path_forces_frontier(self):
        # axioms/ is CODEOWNERS-protected (.github/CODEOWNERS), sourced live.
        t = TaskSpec(
            task_id="d8-co",
            title="touch a governed path",
            mutation_surface="source",
            target_paths=["axioms/registry.yaml"],
            parent_request="REQ-test.md",
            authority_case="CASE-TEST",
            acceptance_criteria=["x"],
        )
        assert t.quality_floor == "frontier_required"

    def test_d8_pure_python_non_governed_unchanged(self):
        t = TaskSpec(
            task_id="d8-py",
            title="touch a plain python file",
            mutation_surface="source",
            target_paths=["agents/foo/bar.py"],
            parent_request="REQ-test.md",
            authority_case="CASE-TEST",
            acceptance_criteria=["x"],
        )
        assert t.quality_floor == "deterministic_ok"

    def test_d8_no_target_paths_unchanged(self):
        t = TaskSpec(
            task_id="d8-none",
            title="no touch set",
            mutation_surface="source",
            parent_request="REQ-test.md",
            authority_case="CASE-TEST",
            acceptance_criteria=["x"],
        )
        assert t.quality_floor == "deterministic_ok"

    def test_d8_only_fires_on_source_surface(self):
        # A non-source surface touching a .rs path must NOT be forced to frontier.
        t = TaskSpec(
            task_id="d8-notsrc",
            title="docs surface, rs path",
            mutation_surface="vault_docs",
            target_paths=["notes/example.rs"],
            parent_request="REQ-test.md",
            authority_case="CASE-TEST",
            acceptance_criteria=["x"],
        )
        assert t.quality_floor == "deterministic_ok"

    def test_codeowners_matcher_handles_dir_anydepth_glob_exact(self):
        from agents.request_decomposer.models import _path_matches_codeowners

        # directory prefix (/axioms/)
        assert _path_matches_codeowners("axioms/registry.yaml", ("/axioms/",))
        assert not _path_matches_codeowners("agents/foo.py", ("/axioms/",))
        # any-depth basename (**/CLAUDE.md)
        assert _path_matches_codeowners("agents/x/CLAUDE.md", ("**/CLAUDE.md",))
        # fnmatch globs (the codex/claude '*' finding)
        assert _path_matches_codeowners("agents/x/foo.rs", ("*.rs",))
        assert _path_matches_codeowners("build/out.js", ("build/*",))
        assert not _path_matches_codeowners("src/out.js", ("build/*",))
        # exact + basename
        assert _path_matches_codeowners(".github/CODEOWNERS", ("/.github/CODEOWNERS",))
        assert not _path_matches_codeowners("docs/readme.md", ("/axioms/",))

    def test_codeowners_matcher_respects_root_anchoring(self):
        from agents.request_decomposer.models import _path_matches_codeowners

        # root-anchored pattern (leading /) matches ONLY at repo root
        assert _path_matches_codeowners(".github/CODEOWNERS", ("/.github/CODEOWNERS",))
        assert not _path_matches_codeowners("tmp/.github/CODEOWNERS", ("/.github/CODEOWNERS",))
        # non-anchored pattern matches at any depth
        assert _path_matches_codeowners("agents/x/CLAUDE.md", ("CLAUDE.md",))
        assert _path_matches_codeowners("CLAUDE.md", ("CLAUDE.md",))

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

    def test_authoritative_frontier_review_tasks_normalize_to_frontier_required(self):
        t = TaskSpec(
            task_id="test-authoritative-route",
            title="Authoritative route",
            parent_request="REQ-test.md",
            authority_case="CASE-TEST",
            quality_floor="frontier_review_required",
            authority_level="authoritative",
            mutation_surface="source",
            acceptance_criteria=["Done"],
        )

        assert t.quality_floor == "frontier_required"

    def test_route_metadata_synonyms_normalize_before_write(self):
        t = TaskSpec(
            task_id="test-route-synonyms",
            title="Route synonyms",
            parent_request="REQ-test.md",
            authority_case="CASE-TEST",
            quality_floor="production",
            mutation_surface="vault",
            authority_level="session",
            acceptance_criteria=["Done"],
        )

        assert t.quality_floor == "frontier_required"
        assert t.mutation_surface == "vault_docs"
        assert t.authority_level == "authoritative"

    def test_path_like_mutation_surface_normalizes_to_source(self):
        t = TaskSpec(
            task_id="test-path-surface",
            title="Path surface",
            parent_request="REQ-test.md",
            authority_case="CASE-TEST",
            mutation_surface="agents/request_decomposer",
            acceptance_criteria=["Done"],
        )

        assert t.mutation_surface == "source"

    def test_invalid_route_metadata_values_rejected(self):
        with pytest.raises(ValueError):
            TaskSpec(
                task_id="test-bad-route",
                title="Bad route",
                parent_request="REQ-test.md",
                authority_case="CASE-TEST",
                mutation_surface="filesystem",
                acceptance_criteria=["Done"],
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

    def test_ready_status_allowed_for_dependency_gated_tasks(self):
        task = self._make_task("ready-task", status="ready", depends_on=["a"])
        d = RequestDecomposition(
            request_id="test",
            request_path="/tmp/test.md",
            tasks=[self._make_task("a"), task],
        )

        assert d.tasks[1].status == "ready"

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

    def test_real_write_renders_target_paths(self):
        with tempfile.TemporaryDirectory() as td:
            decomp = RequestDecomposition(
                request_id="test-tp",
                request_path="/tmp/test.md",
                tasks=[
                    TaskSpec(
                        task_id="tp-task",
                        title="touch rust",
                        parent_request="REQ-test.md",
                        authority_case="CASE-TEST",
                        acceptance_criteria=["x"],
                        target_paths=["agents/foo/bar.rs"],
                    )
                ],
            )
            paths = write_decomposition(decomp, Path(td))
            content = paths[0].read_text()
            assert "target_paths:" in content
            assert "agents/foo/bar.rs" in content

    def test_real_write_renders_taxonomy_fields(self):
        with tempfile.TemporaryDirectory() as td:
            decomp = RequestDecomposition(
                request_id="test-taxonomy-write",
                request_path="/tmp/test.md",
                tasks=[
                    TaskSpec(
                        task_id="taxonomy-write",
                        title="taxonomy fields",
                        parent_request="REQ-test.md",
                        authority_case="CASE-TEST",
                        acceptance_criteria=["x"],
                        routing_class="source_python",
                        requirement_vector=_requirement_vector(),
                        composition_tolerance="atomic",
                        requirement_vector_validity_mask=_validity_mask(),
                    )
                ],
            )

            [path] = write_decomposition(decomp, Path(td))
            frontmatter, _body = parse_frontmatter(path.read_text(encoding="utf-8"))

        assert frontmatter["routing_class"] == "source_python"
        assert frontmatter["requirement_vector"]["context_length"] == 1
        assert frontmatter["composition_tolerance"] == "atomic"
        assert frontmatter["requirement_vector_validity_mask"]["context_length"] is True

    def test_real_write_renders_route_envelope_and_task_demand_when_present(self):
        with tempfile.TemporaryDirectory() as td:
            decomp = RequestDecomposition(
                request_id="test-envelope-write",
                request_path="/tmp/test.md",
                tasks=[
                    TaskSpec(
                        task_id="envelope-write",
                        title="envelope fields",
                        parent_request="REQ-test.md",
                        authority_case="CASE-TEST",
                        acceptance_criteria=["x"],
                        route_envelope=_route_envelope(),
                        task_demand={"fixed_route_overhead_sensitivity": 5},
                    )
                ],
            )

            [path] = write_decomposition(decomp, Path(td))
            frontmatter, _body = parse_frontmatter(path.read_text(encoding="utf-8"))

        assert frontmatter["route_envelope"]["classification_envelope"]["label"] == "source_python"
        assert frontmatter["task_demand"]["fixed_route_overhead_sensitivity"] == 5

    def test_real_write_frontmatter_is_yaml_safe(self):
        with tempfile.TemporaryDirectory() as td:
            decomp = RequestDecomposition(
                request_id="test-write",
                request_path="/tmp/test.md",
                tasks=[
                    TaskSpec(
                        task_id="write-phase1",
                        title="Phase 1",
                        parent_request="REQ-test.md",
                        authority_case="CASE-TEST",
                        acceptance_criteria=["Schema exists"],
                    ),
                    TaskSpec(
                        task_id="write-phase2",
                        title="Phase 2",
                        depends_on=["write-phase1"],
                        status="blocked",
                        blocked_reason="Depends on: write-phase1",
                        parent_request="REQ-test.md",
                        authority_case="CASE-TEST",
                        acceptance_criteria=["API works"],
                    ),
                ],
            )

            paths = write_decomposition(decomp, Path(td))
            phase2 = [p for p in paths if "phase2" in p.name][0]

            frontmatter, _body = parse_frontmatter(phase2.read_text(encoding="utf-8"))
            assert frontmatter["blocked_reason"] == "Depends on: write-phase1"

    def test_blocks_computed(self):
        with tempfile.TemporaryDirectory() as td:
            paths = write_decomposition(self._make_decomp(), Path(td))
            phase1 = [p for p in paths if "phase1" in p.name][0]
            content = phase1.read_text()
            assert "write-phase2" in content

    def test_writer_emits_dispatchable_route_metadata(self):
        decomp = RequestDecomposition(
            request_id="test-route-write",
            request_path="/tmp/test.md",
            tasks=[
                TaskSpec(
                    task_id="write-route",
                    title="Route metadata",
                    parent_request="REQ-test.md",
                    authority_case="CASE-TEST",
                    parent_spec="/tmp/spec.md",
                    quality_floor="frontier_review_required",
                    authority_level="authoritative",
                    mutation_surface="source",
                    acceptance_criteria=["Route validates"],
                    intent="Write dispatchable metadata.",
                ),
            ],
        )
        with tempfile.TemporaryDirectory() as td:
            [path] = write_decomposition(decomp, Path(td))

            fields, _body = parse_frontmatter(path)
            assessment = assess_route_metadata(fields)

        assert assessment.status != RouteMetadataStatus.MALFORMED
        assert assessment.dispatchable
        assert assessment.metadata is not None
        assert assessment.metadata.quality_floor == "frontier_required"

    def test_writer_emits_support_review_requirement_when_needed(self):
        decomp = RequestDecomposition(
            request_id="test-review-write",
            request_path="/tmp/test.md",
            tasks=[
                TaskSpec(
                    task_id="write-review",
                    title="Review metadata",
                    kind="research_packet",
                    parent_request="REQ-test.md",
                    quality_floor="frontier_review_required",
                    authority_level="support_non_authoritative",
                    mutation_surface="vault_docs",
                    acceptance_criteria=["Route validates"],
                    intent="Write support metadata.",
                ),
            ],
        )
        with tempfile.TemporaryDirectory() as td:
            [path] = write_decomposition(decomp, Path(td))

            fields, _body = parse_frontmatter(path)
            assessment = assess_route_metadata(fields)

        assert assessment.status != RouteMetadataStatus.MALFORMED
        assert assessment.dispatchable
        assert assessment.metadata is not None
        assert assessment.metadata.review_requirement.support_artifact_allowed is True

    def test_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            write_decomposition(self._make_decomp(), Path(td))
            with pytest.raises(FileExistsError):
                write_decomposition(self._make_decomp(), Path(td))

    def test_refuses_parent_request_with_existing_downstream_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = root / "REQ-test.md"
            request.write_text(
                """---
type: hapax-request
request_id: REQ-test
status: accepted_for_planning
downstream_tasks:
- existing-task
---

# Request
""",
                encoding="utf-8",
            )
            decomp = self._make_decomp()
            decomp.request_path = str(request)

            with pytest.raises(FileExistsError, match="already has downstream_tasks"):
                write_decomposition(decomp, root / "tasks")

            assert not list((root / "tasks" / "active").glob("*.md"))

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
    def _request_data(self, tmp_path: Path, frontmatter: dict[str, object]) -> dict[str, object]:
        request_path = tmp_path / "REQ-test.md"
        return {
            "path": str(request_path),
            "filename": request_path.name,
            "frontmatter": frontmatter,
            "body": "# Request\n",
        }

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

    def test_scan_matches_task_parent_request_absolute_path(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        requests = tmp_path / "requests" / "active"
        tasks = tmp_path / "tasks"
        requests.mkdir(parents=True)
        (tasks / "active").mkdir(parents=True)
        (tasks / "closed").mkdir(parents=True)

        request = requests / "REQ-path-parent.md"
        request.write_text(
            """---
type: hapax-request
request_id: REQ-path-parent
status: accepted_for_planning
---

# Request
""",
            encoding="utf-8",
        )
        (tasks / "active" / "linked-by-path.md").write_text(
            f"""---
type: cc-task
task_id: linked-by-path
status: offered
parent_request: {request}
---

# Task
""",
            encoding="utf-8",
        )
        monkeypatch.setattr(script, "REQUESTS_DIR", requests)
        monkeypatch.setattr(script, "TASKS_DIR", tasks)

        assert script._find_undecomposed_requests() == []

    def test_decomposition_admission_allows_ready_cctv_request(self, tmp_path):
        script = _load_request_decompose_module()
        request_data = self._request_data(
            tmp_path,
            {
                "status": "accepted_for_planning",
                "cctv_intake_receipt": "receipt://REQ-test",
                "cctv_intake_verdict": "ready_to_plan",
                "planning_case": "CASE-TEST-001",
            },
        )

        assert script._decomposition_admission_blockers(request_data) == []

    def test_decomposition_admission_blocks_missing_cctv_receipt(self, tmp_path):
        script = _load_request_decompose_module()
        request_data = self._request_data(
            tmp_path,
            {
                "status": "accepted_for_planning",
                "cctv_intake_verdict": "ready_to_plan",
                "planning_case": "CASE-TEST-001",
            },
        )

        assert "missing_cctv_intake_receipt" in script._decomposition_admission_blockers(
            request_data
        )

    def test_decomposition_admission_blocks_non_ready_cctv_verdict(self, tmp_path):
        script = _load_request_decompose_module()
        request_data = self._request_data(
            tmp_path,
            {
                "status": "accepted_for_planning",
                "cctv_intake_receipt": "receipt://REQ-test",
                "cctv_intake_verdict": "needs_hardening",
                "planning_case": "CASE-TEST-001",
            },
        )

        assert "cctv_intake_not_ready:needs_hardening" in (
            script._decomposition_admission_blockers(request_data)
        )

    def test_decomposition_admission_blocks_missing_authority_case(self, tmp_path):
        script = _load_request_decompose_module()
        request_data = self._request_data(
            tmp_path,
            {
                "status": "accepted_for_planning",
                "cctv_intake_receipt": "receipt://REQ-test",
                "cctv_intake_verdict": "ready_to_plan",
            },
        )

        assert "missing_authority_case" in script._decomposition_admission_blockers(request_data)

    def test_single_request_blocks_before_llm_without_cctv(self, tmp_path, monkeypatch, caplog):
        script = _load_request_decompose_module()
        tasks = tmp_path / "tasks"
        (tasks / "active").mkdir(parents=True)
        (tasks / "closed").mkdir(parents=True)
        request = tmp_path / "REQ-blocked.md"
        request.write_text(
            """---
type: hapax-request
request_id: REQ-blocked
status: accepted_for_planning
planning_case: CASE-TEST-001
---

# Request
""",
            encoding="utf-8",
        )

        def fail_if_called(_request_data):
            raise AssertionError("LLM should not run before CCTV admission")

        caplog.set_level(logging.ERROR, logger="request_decompose_script")
        monkeypatch.setattr(script, "TASKS_DIR", tasks)
        monkeypatch.setattr(script, "_decompose_with_llm", fail_if_called)
        monkeypatch.setattr(sys, "argv", ["request-decompose", str(request), "--dry-run"])

        assert script.main() == 1
        assert not list((tasks / "active").glob("request-decompose-*.md"))
        assert "rerun without --dry-run" in caplog.text
        assert "cc-claim" not in caplog.text

    def test_scan_blocks_before_llm_without_cctv(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        requests = tmp_path / "requests" / "active"
        tasks = tmp_path / "tasks"
        requests.mkdir(parents=True)
        (tasks / "active").mkdir(parents=True)
        (tasks / "closed").mkdir(parents=True)
        (requests / "REQ-001-blocked.md").write_text(
            """---
type: hapax-request
request_id: REQ-001-blocked
status: accepted_for_planning
planning_case: CASE-TEST-001
---

# Request
""",
            encoding="utf-8",
        )

        def fail_if_called(_request_data):
            raise AssertionError("LLM should not run before CCTV admission")

        monkeypatch.setattr(script, "REQUESTS_DIR", requests)
        monkeypatch.setattr(script, "TASKS_DIR", tasks)
        monkeypatch.setattr(script, "_decompose_with_llm", fail_if_called)
        monkeypatch.setattr(sys, "argv", ["request-decompose", "--scan", "--dry-run"])

        assert script.main() == 0
        assert not list((tasks / "active").glob("request-decompose-*.md"))

    def test_decomposition_uses_real_authority_case_without_fallback(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()

        def completion(**_kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(
                                {
                                    "tasks": [
                                        {
                                            "task_id": "req-test-build",
                                            "title": "Build it",
                                            "kind": "build",
                                            "acceptance_criteria": ["Done"],
                                        }
                                    ]
                                }
                            )
                        )
                    )
                ]
            )

        monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=completion))

        request_data = self._request_data(
            tmp_path,
            {
                "status": "accepted_for_planning",
                "planning_case": "CASE-REAL-001",
            },
        )

        decomp = script._decompose_with_llm(request_data)

        assert decomp is not None
        assert decomp.tasks[0].authority_case == "CASE-REAL-001"

    def test_decomposition_marks_dependency_tasks_ready_for_offer_sweeper(
        self, tmp_path, monkeypatch
    ):
        script = _load_request_decompose_module()

        def completion(**_kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(
                                {
                                    "tasks": [
                                        {
                                            "task_id": "req-test-a",
                                            "title": "Build A",
                                            "kind": "build",
                                            "acceptance_criteria": ["A done"],
                                        },
                                        {
                                            "task_id": "req-test-b",
                                            "title": "Build B",
                                            "kind": "build",
                                            "depends_on": ["req-test-a"],
                                            "acceptance_criteria": ["B done"],
                                        },
                                    ]
                                }
                            )
                        )
                    )
                ]
            )

        monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=completion))

        request_data = self._request_data(
            tmp_path,
            {
                "filename": "REQ-test.md",
                "status": "accepted_for_planning",
                "planning_case": "CASE-REAL-001",
            },
        )

        decomp = script._decompose_with_llm(request_data)

        assert decomp is not None
        assert decomp.tasks[0].status == "offered"
        assert decomp.tasks[1].status == "ready"
        assert decomp.tasks[1].blocked_reason == "Depends on: req-test-a"

    def test_decomposition_fails_without_authority_instead_of_fabricating_case(
        self, tmp_path, monkeypatch
    ):
        script = _load_request_decompose_module()

        def completion(**_kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(
                                {
                                    "tasks": [
                                        {
                                            "task_id": "req-test-build",
                                            "title": "Build it",
                                            "kind": "build",
                                            "acceptance_criteria": ["Done"],
                                        }
                                    ]
                                }
                            )
                        )
                    )
                ]
            )

        monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=completion))

        assert script._decompose_with_llm(self._request_data(tmp_path, {})) is None

    def test_decomposition_tolerates_synonym_enum_fields(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()

        def completion(**_kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(
                                {
                                    "tasks": [
                                        {
                                            "task_id": "Req Test Implement!",
                                            "title": "Build the thing",
                                            "kind": "implementation",
                                            "priority": "high",
                                            "effort_class": "large",
                                            "quality_floor": "review",
                                            "acceptance_criteria": ["It works"],
                                        }
                                    ]
                                }
                            )
                        )
                    )
                ]
            )

        monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=completion))

        request_data = self._request_data(
            tmp_path,
            {"status": "accepted_for_planning", "planning_case": "CASE-REAL-001"},
        )
        decomp = script._decompose_with_llm(request_data)

        assert decomp is not None
        task = decomp.tasks[0]
        assert task.kind == "build"
        assert task.priority == "p1"
        assert task.effort_class == "high"
        # frontier_review_required + authoritative collapses to frontier_required per model rules
        assert task.quality_floor == "frontier_required"
        assert task.task_id == "req-test-implement"

    def test_prompt_requests_taxonomy_fields(self):
        script = _load_request_decompose_module()

        assert "routing_class" in script.DECOMPOSITION_PROMPT
        assert "requirement_vector" in script.DECOMPOSITION_PROMPT
        assert "requirement_vector_validity_mask" in script.DECOMPOSITION_PROMPT

    def test_decomposition_carries_llm_route_envelope_and_task_demand(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()

        def completion(**_kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(
                                {
                                    "tasks": [
                                        {
                                            "task_id": "req-test-route-aware",
                                            "title": "Build route-aware task",
                                            "kind": "build",
                                            "routing_class": "source_python",
                                            "requirement_vector": _requirement_vector(),
                                            "requirement_vector_validity_mask": _validity_mask(),
                                            "route_envelope": _route_envelope(),
                                            "task_demand": {"fixed_route_overhead_sensitivity": 5},
                                            "acceptance_criteria": [
                                                "Route envelope and demand survive normalization."
                                            ],
                                        }
                                    ]
                                }
                            )
                        )
                    )
                ]
            )

        monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=completion))

        request_data = self._request_data(
            tmp_path,
            {"status": "accepted_for_planning", "planning_case": "CASE-REAL-001"},
        )
        decomp = script._decompose_with_llm(request_data)

        assert decomp is not None
        task = decomp.tasks[0]
        assert task.route_envelope is not None
        assert task.route_envelope.classification_envelope.label == "source_python"
        assert task.task_demand["fixed_route_overhead_sensitivity"] == 5

    def test_decomposition_parses_taxonomy_held_set(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()

        tasks = [
            {
                "task_id": "req-test-python",
                "title": "Patch Python helper",
                "kind": "build",
                "mutation_surface": "source",
                "quality_floor": "deterministic_ok",
                "target_paths": ["agents/foo/helper.py"],
                "routing_class": "source_python",
                "requirement_vector": _requirement_vector(
                    quality_floor=1,
                    information_scope=2,
                    context_length=2,
                    mutation_risk=2,
                    verification_demand=1,
                    ambiguity_novelty=1,
                    composition_coupling=1,
                    governance_sensitivity=0,
                ),
                "composition_tolerance": "parallel_ok",
                "requirement_vector_validity_mask": _validity_mask(),
                "acceptance_criteria": ["Helper behavior is tested"],
            },
            {
                "task_id": "req-test-shader",
                "title": "Patch governed shader",
                "kind": "build",
                "mutation_surface": "source",
                "quality_floor": "deterministic_ok",
                "target_paths": ["agents/shaders/nodes/example.wgsl"],
                "routing_class": "source_governance",
                "requirement_vector": _requirement_vector(
                    quality_floor=5,
                    information_scope=3,
                    context_length=3,
                    mutation_risk=4,
                    verification_demand=4,
                    ambiguity_novelty=3,
                    composition_coupling=2,
                    governance_sensitivity=5,
                ),
                "composition_tolerance": "atomic",
                "requirement_vector_validity_mask": _validity_mask(),
                "acceptance_criteria": ["Shader behavior remains covered"],
            },
            {
                "task_id": "req-test-docs",
                "title": "Draft support note",
                "kind": "research_packet",
                "mutation_surface": "vault_docs",
                "quality_floor": "frontier_review_required",
                "authority_level": "support_non_authoritative",
                "routing_class": "research_support",
                "requirement_vector": _requirement_vector(
                    quality_floor=3,
                    information_scope=4,
                    context_length=4,
                    mutation_risk=1,
                    verification_demand=3,
                    ambiguity_novelty=4,
                    composition_coupling=2,
                    governance_sensitivity=2,
                ),
                "composition_tolerance": "sequential_required",
                "requirement_vector_validity_mask": _validity_mask(context_length=False),
                "acceptance_criteria": ["Support note cites source paths"],
            },
        ]

        def completion(**_kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content=json.dumps({"tasks": tasks})))
                ]
            )

        monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=completion))

        request_data = self._request_data(
            tmp_path,
            {"status": "accepted_for_planning", "planning_case": "CASE-REAL-001"},
        )
        decomp = script._decompose_with_llm(request_data)

        assert decomp is not None
        python_task, shader_task, docs_task = decomp.tasks
        assert python_task.routing_class == "source_python"
        assert python_task.requirement_vector["information_scope"] == 2
        assert python_task.composition_tolerance == "parallel_ok"
        assert shader_task.routing_class == "source_governance"
        assert shader_task.quality_floor == "frontier_required"
        assert docs_task.routing_class == "research_support"
        assert docs_task.requirement_vector_validity_mask["context_length"] is False

    def test_decomposition_fails_closed_on_partial_taxonomy(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()

        def completion(**_kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(
                                {
                                    "tasks": [
                                        {
                                            "task_id": "req-test-partial-taxonomy",
                                            "title": "Partial taxonomy",
                                            "routing_class": "source_python",
                                            "acceptance_criteria": ["done"],
                                        }
                                    ]
                                }
                            )
                        )
                    )
                ]
            )

        monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=completion))

        request_data = self._request_data(
            tmp_path,
            {"status": "accepted_for_planning", "planning_case": "CASE-REAL-001"},
        )
        assert script._decompose_with_llm(request_data) is None

    def test_decomposition_parses_fenced_json_with_preamble(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()

        def completion(**_kwargs):
            payload = json.dumps({"tasks": [{"title": "Do it"}]})
            wrapped = f"Sure, here is the decomposition:\n```json\n{payload}\n```\n"
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=wrapped))]
            )

        monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=completion))

        request_data = self._request_data(
            tmp_path,
            {"status": "accepted_for_planning", "planning_case": "CASE-REAL-001"},
        )
        decomp = script._decompose_with_llm(request_data)

        assert decomp is not None
        assert len(decomp.tasks) == 1
        # title-only task still gets a derived slug and a default acceptance criterion
        assert decomp.tasks[0].task_id
        assert decomp.tasks[0].acceptance_criteria

    def test_decomposition_handles_dict_style_response(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()

        def completion(**_kwargs):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "tasks": [
                                        {
                                            "task_id": "req-dict-task",
                                            "title": "Dict task",
                                            "acceptance_criteria": ["done"],
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            }

        monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=completion))

        request_data = self._request_data(
            tmp_path,
            {"status": "accepted_for_planning", "planning_case": "CASE-REAL-001"},
        )
        decomp = script._decompose_with_llm(request_data)

        assert decomp is not None
        assert decomp.tasks[0].task_id == "req-dict-task"

    def test_decomposition_fails_closed_on_empty_tasks(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()

        def completion(**_kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content=json.dumps({"tasks": []})))
                ]
            )

        monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=completion))

        request_data = self._request_data(
            tmp_path,
            {"status": "accepted_for_planning", "planning_case": "CASE-REAL-001"},
        )
        assert script._decompose_with_llm(request_data) is None

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
        (tasks / "active" / "already-linked.md").write_text(
            """---
type: cc-task
task_id: already-linked
status: offered
---

# Task
""",
            encoding="utf-8",
        )
        monkeypatch.setattr(script, "REQUESTS_DIR", requests)
        monkeypatch.setattr(script, "TASKS_DIR", tasks)

        assert script._find_undecomposed_requests() == []

    def test_scan_does_not_skip_stale_downstream_tasks(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        requests = tmp_path / "requests" / "active"
        tasks = tmp_path / "tasks"
        requests.mkdir(parents=True)
        (tasks / "active").mkdir(parents=True)
        (tasks / "closed").mkdir(parents=True)

        request = requests / "REQ-stale-link.md"
        request.write_text(
            """---
type: hapax-request
request_id: REQ-stale-link
status: accepted_for_planning
downstream_tasks:
  - missing-task
---

# Request
""",
            encoding="utf-8",
        )
        monkeypatch.setattr(script, "REQUESTS_DIR", requests)
        monkeypatch.setattr(script, "TASKS_DIR", tasks)

        assert script._find_undecomposed_requests() == [request]

    def test_task_parent_reference_keys_include_md_stem(self):
        script = _load_request_decompose_module()

        assert "REQ-parent" in script._task_parent_reference_keys("REQ-parent.md")

    def test_scan_does_not_treat_remediation_task_as_downstream_task(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        requests = tmp_path / "requests" / "active"
        tasks = tmp_path / "tasks"
        requests.mkdir(parents=True)
        (tasks / "active").mkdir(parents=True)
        (tasks / "closed").mkdir(parents=True)

        request = requests / "REQ-remediation-link.md"
        request.write_text(
            """---
type: hapax-request
request_id: REQ-remediation-link
status: accepted_for_planning
downstream_tasks:
  - request-decompose-admission-blocked-REQ-remediation-link
---

# Request
""",
            encoding="utf-8",
        )
        (
            tasks / "active" / "request-decompose-admission-blocked-REQ-remediation-link.md"
        ).write_text(
            """---
type: cc-task
task_id: request-decompose-admission-blocked-REQ-remediation-link
status: offered
remediates_request_id: REQ-remediation-link
---

# Task
""",
            encoding="utf-8",
        )
        monkeypatch.setattr(script, "REQUESTS_DIR", requests)
        monkeypatch.setattr(script, "TASKS_DIR", tasks)

        assert script._find_undecomposed_requests() == [request]

    def test_scan_limit_counts_admitted_attempts_not_blocked_prefix(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        requests = tmp_path / "requests" / "active"
        tasks = tmp_path / "tasks"
        requests.mkdir(parents=True)
        (tasks / "active").mkdir(parents=True)
        (tasks / "closed").mkdir(parents=True)
        (requests / "REQ-001-blocked.md").write_text(
            """---
type: hapax-request
request_id: REQ-001-blocked
status: accepted_for_planning
planning_case: CASE-TEST-001
---

# Request
""",
            encoding="utf-8",
        )
        (requests / "REQ-002-admitted.md").write_text(
            """---
type: hapax-request
request_id: REQ-002-admitted
status: accepted_for_planning
planning_case: CASE-TEST-001
cctv_intake_receipt: receipt://REQ-002-admitted
cctv_intake_verdict: ready_to_plan
---

# Request
""",
            encoding="utf-8",
        )
        (requests / "REQ-003-admitted.md").write_text(
            """---
type: hapax-request
request_id: REQ-003-admitted
status: accepted_for_planning
planning_case: CASE-TEST-001
cctv_intake_receipt: receipt://REQ-003-admitted
cctv_intake_verdict: ready_to_plan
---

# Request
""",
            encoding="utf-8",
        )
        calls: list[str] = []

        def fake_decompose(request_data):
            calls.append(request_data["filename"])
            return RequestDecomposition(
                request_id="REQ-002-admitted",
                request_path=request_data["path"],
                tasks=[
                    TaskSpec(
                        task_id="admitted-task",
                        title="Admitted task",
                        parent_request=request_data["filename"],
                        authority_case="CASE-TEST-001",
                        acceptance_criteria=["Done"],
                    )
                ],
            )

        monkeypatch.setattr(script, "REQUESTS_DIR", requests)
        monkeypatch.setattr(script, "TASKS_DIR", tasks)
        monkeypatch.setattr(script, "_decompose_with_llm", fake_decompose)
        monkeypatch.setattr(
            sys,
            "argv",
            ["request-decompose", "--scan", "--limit", "1"],
        )

        assert script.main() == 0
        assert calls == ["REQ-002-admitted.md"]
        assert "REQ-003-admitted.md" not in calls
        [remediation_task] = list(
            (tasks / "active").glob("request-decompose-admission-blocked-*.md")
        )
        frontmatter, _body = parse_frontmatter(remediation_task)
        assert frontmatter["remediates_request_id"] == "REQ-001-blocked"

    def test_scan_limit_still_remediates_blocked_after_cap_filled(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        requests = tmp_path / "requests" / "active"
        tasks = tmp_path / "tasks"
        requests.mkdir(parents=True)
        (tasks / "active").mkdir(parents=True)
        (tasks / "closed").mkdir(parents=True)
        (requests / "REQ-001-admitted.md").write_text(
            """---
type: hapax-request
request_id: REQ-001-admitted
status: accepted_for_planning
planning_case: CASE-TEST-001
cctv_intake_receipt: receipt://REQ-001-admitted
cctv_intake_verdict: ready_to_plan
---

# Request
""",
            encoding="utf-8",
        )
        (requests / "REQ-002-blocked.md").write_text(
            """---
type: hapax-request
request_id: REQ-002-blocked
status: accepted_for_planning
planning_case: CASE-TEST-001
---

# Request
""",
            encoding="utf-8",
        )
        (requests / "REQ-003-admitted.md").write_text(
            """---
type: hapax-request
request_id: REQ-003-admitted
status: accepted_for_planning
planning_case: CASE-TEST-001
cctv_intake_receipt: receipt://REQ-003-admitted
cctv_intake_verdict: ready_to_plan
---

# Request
""",
            encoding="utf-8",
        )
        calls: list[str] = []

        def fake_decompose(request_data):
            calls.append(request_data["filename"])
            request_id = request_data["frontmatter"]["request_id"]
            return RequestDecomposition(
                request_id=request_id,
                request_path=request_data["path"],
                tasks=[
                    TaskSpec(
                        task_id=f"{request_id}-task",
                        title="Admitted task",
                        parent_request=request_data["filename"],
                        authority_case="CASE-TEST-001",
                        acceptance_criteria=["Done"],
                    )
                ],
            )

        monkeypatch.setattr(script, "REQUESTS_DIR", requests)
        monkeypatch.setattr(script, "TASKS_DIR", tasks)
        monkeypatch.setattr(script, "_decompose_with_llm", fake_decompose)
        monkeypatch.setattr(sys, "argv", ["request-decompose", "--scan", "--limit", "1"])

        assert script.main() == 0

        assert calls == ["REQ-001-admitted.md"]
        [remediation_task] = list(
            (tasks / "active").glob("request-decompose-admission-blocked-*.md")
        )
        frontmatter, _body = parse_frontmatter(remediation_task)
        assert frontmatter["remediates_request_id"] == "REQ-002-blocked"

    def test_scan_writes_idempotent_admission_remediation_task(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        requests = tmp_path / "requests" / "active"
        tasks = tmp_path / "tasks"
        requests.mkdir(parents=True)
        (tasks / "active").mkdir(parents=True)
        (tasks / "closed").mkdir(parents=True)
        request = requests / "REQ-blocked.md"
        request.write_text(
            """---
type: hapax-request
request_id: REQ-blocked
status: accepted_for_planning
planning_case: CASE-TEST-001
priority_hint: p0
---

# Request
""",
            encoding="utf-8",
        )

        def fail_if_called(_request_data):
            raise AssertionError("LLM should not run before admission")

        monkeypatch.setattr(script, "REQUESTS_DIR", requests)
        monkeypatch.setattr(script, "TASKS_DIR", tasks)
        monkeypatch.setattr(script, "_decompose_with_llm", fail_if_called)
        monkeypatch.setattr(sys, "argv", ["request-decompose", "--scan"])

        assert script.main() == 0

        remediation_tasks = list(
            (tasks / "active").glob("request-decompose-admission-blocked-*.md")
        )
        assert len(remediation_tasks) == 1
        original_text = remediation_tasks[0].read_text(encoding="utf-8")

        assert script.main() == 0
        assert remediation_tasks[0].read_text(encoding="utf-8") == original_text

        frontmatter, body = parse_frontmatter(remediation_tasks[0])
        assert frontmatter["status"] == "offered"
        assert frontmatter["priority"] == "p0"
        assert frontmatter["implementation_authorized"] is True
        assert frontmatter["source_mutation_authorized"] is False
        assert frontmatter["docs_mutation_authorized"] is True
        assert frontmatter["runtime_mutation_authorized"] is False
        assert frontmatter["parent_request"] == "REQ-blocked.md"
        assert frontmatter["remediates_request_id"] == "REQ-blocked"
        assert frontmatter["decompose_failure_class"] == "admission_blocked"
        assert "missing_cctv_intake_receipt" in frontmatter["decompose_failure_reasons"]
        assert "not treated as fulfillment" in body
        assert script._find_undecomposed_requests() == [request]

    def test_remediation_task_uses_lineage_env_overrides(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        requests = tmp_path / "requests" / "active"
        tasks = tmp_path / "tasks"
        requests.mkdir(parents=True)
        (tasks / "active").mkdir(parents=True)
        (tasks / "closed").mkdir(parents=True)
        (requests / "REQ-env.md").write_text(
            """---
type: hapax-request
request_id: REQ-env
status: accepted_for_planning
planning_case: CASE-TEST-001
---

# Request
""",
            encoding="utf-8",
        )

        monkeypatch.setattr(script, "REQUESTS_DIR", requests)
        monkeypatch.setattr(script, "TASKS_DIR", tasks)
        monkeypatch.setattr(script, "_decompose_with_llm", lambda _request_data: None)
        monkeypatch.setenv("HAPAX_REQUEST_DECOMPOSE_REMEDIATION_PARENT_REQUEST", "REQ-parent")
        monkeypatch.setenv("HAPAX_REQUEST_DECOMPOSE_REMEDIATION_PARENT_SPEC", "SPEC-parent")
        monkeypatch.setenv("HAPAX_REQUEST_DECOMPOSE_REMEDIATION_AUTHORITY_CASE", "CASE-ENV-001")
        monkeypatch.setattr(sys, "argv", ["request-decompose", "--scan"])

        assert script.main() == 0

        [remediation_task] = list(
            (tasks / "active").glob("request-decompose-admission-blocked-*.md")
        )
        frontmatter, _body = parse_frontmatter(remediation_task)
        assert frontmatter["parent_request"] == "REQ-parent"
        assert frontmatter["parent_spec"] == "SPEC-parent"
        assert frontmatter["authority_case"] == "CASE-ENV-001"

    def test_closed_remediation_does_not_suppress_active_remediation(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        requests = tmp_path / "requests" / "active"
        tasks = tmp_path / "tasks"
        requests.mkdir(parents=True)
        (tasks / "active").mkdir(parents=True)
        (tasks / "closed").mkdir(parents=True)
        (requests / "REQ-blocked.md").write_text(
            """---
type: hapax-request
request_id: REQ-blocked
status: accepted_for_planning
planning_case: CASE-TEST-001
---

# Request
""",
            encoding="utf-8",
        )

        monkeypatch.setattr(script, "REQUESTS_DIR", requests)
        monkeypatch.setattr(script, "TASKS_DIR", tasks)
        monkeypatch.setattr(script, "_decompose_with_llm", lambda _request_data: None)
        monkeypatch.setattr(sys, "argv", ["request-decompose", "--scan"])

        assert script.main() == 0
        [active_remediation] = list(
            (tasks / "active").glob("request-decompose-admission-blocked-*.md")
        )
        closed_remediation = tasks / "closed" / active_remediation.name
        active_remediation.rename(closed_remediation)

        assert script.main() == 0

        assert closed_remediation.exists()
        assert (tasks / "active" / closed_remediation.name).exists()

    def test_terminal_active_remediation_is_reopened(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        requests = tmp_path / "requests" / "active"
        tasks = tmp_path / "tasks"
        requests.mkdir(parents=True)
        (tasks / "active").mkdir(parents=True)
        (tasks / "closed").mkdir(parents=True)
        (requests / "REQ-blocked.md").write_text(
            """---
type: hapax-request
request_id: REQ-blocked
status: accepted_for_planning
planning_case: CASE-TEST-001
---

# Request
""",
            encoding="utf-8",
        )

        monkeypatch.setattr(script, "REQUESTS_DIR", requests)
        monkeypatch.setattr(script, "TASKS_DIR", tasks)
        monkeypatch.setattr(script, "_decompose_with_llm", lambda _request_data: None)
        monkeypatch.setattr(sys, "argv", ["request-decompose", "--scan"])

        assert script.main() == 0
        [active_remediation] = list(
            (tasks / "active").glob("request-decompose-admission-blocked-*.md")
        )
        text = active_remediation.read_text(encoding="utf-8")
        active_remediation.write_text(
            text.replace("status: offered\n", "status: done\n"),
            encoding="utf-8",
        )

        assert script.main() == 0

        frontmatter, _body = parse_frontmatter(active_remediation)
        assert frontmatter["status"] == "offered"
        assert frontmatter["remediates_request_id"] == "REQ-blocked"

    def test_scan_writes_llm_failure_remediation_task(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        requests = tmp_path / "requests" / "active"
        tasks = tmp_path / "tasks"
        requests.mkdir(parents=True)
        (tasks / "active").mkdir(parents=True)
        (tasks / "closed").mkdir(parents=True)
        (requests / "REQ-llm.md").write_text(
            """---
type: hapax-request
request_id: REQ-llm
status: accepted_for_planning
planning_case: CASE-TEST-001
cctv_intake_receipt: receipt://REQ-llm
cctv_intake_verdict: ready_to_plan
---

# Request
""",
            encoding="utf-8",
        )

        monkeypatch.setattr(script, "REQUESTS_DIR", requests)
        monkeypatch.setattr(script, "TASKS_DIR", tasks)
        monkeypatch.setattr(script, "_decompose_with_llm", lambda _request_data: None)
        monkeypatch.setattr(sys, "argv", ["request-decompose", "--scan"])

        assert script.main() == 0

        [remediation_task] = list((tasks / "active").glob("request-decompose-llm-failed-*.md"))
        frontmatter, _body = parse_frontmatter(remediation_task)
        assert frontmatter["decompose_failure_class"] == "llm_failed"
        assert frontmatter["mutation_surface"] == "source"
        assert frontmatter["implementation_authorized"] is True
        assert frontmatter["source_mutation_authorized"] is True
        assert frontmatter["docs_mutation_authorized"] is True
        assert frontmatter["runtime_mutation_authorized"] is False
        assert frontmatter["remediates_request_id"] == "REQ-llm"

    def test_scan_writes_write_conflict_remediation_task(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        requests = tmp_path / "requests" / "active"
        tasks = tmp_path / "tasks"
        requests.mkdir(parents=True)
        (tasks / "active").mkdir(parents=True)
        (tasks / "closed").mkdir(parents=True)
        (requests / "REQ-conflict.md").write_text(
            """---
type: hapax-request
request_id: REQ-conflict
status: accepted_for_planning
planning_case: CASE-TEST-001
cctv_intake_receipt: receipt://REQ-conflict
cctv_intake_verdict: ready_to_plan
---

# Request
""",
            encoding="utf-8",
        )

        def fake_decompose(request_data):
            return RequestDecomposition(
                request_id="REQ-conflict",
                request_path=request_data["path"],
                tasks=[
                    TaskSpec(
                        task_id="conflicting-task",
                        title="Conflicting task",
                        parent_request=request_data["filename"],
                        authority_case="CASE-TEST-001",
                        acceptance_criteria=["Done"],
                    )
                ],
            )

        def fail_write(_decomp, _tasks_dir):
            raise FileExistsError("task already exists: conflicting-task")

        monkeypatch.setattr(script, "REQUESTS_DIR", requests)
        monkeypatch.setattr(script, "TASKS_DIR", tasks)
        monkeypatch.setattr(script, "_decompose_with_llm", fake_decompose)
        monkeypatch.setattr(script, "write_decomposition", fail_write)
        monkeypatch.setattr(sys, "argv", ["request-decompose", "--scan"])

        assert script.main() == 0

        [remediation_task] = list((tasks / "active").glob("request-decompose-write-conflict-*.md"))
        frontmatter, _body = parse_frontmatter(remediation_task)
        assert (
            frontmatter["title"] == "Repair request decomposition write conflict for REQ-conflict"
        )
        assert frontmatter["decompose_failure_class"] == "write_conflict"
        assert frontmatter["mutation_surface"] == "vault_docs"
        assert frontmatter["implementation_authorized"] is True
        assert frontmatter["source_mutation_authorized"] is False
        assert frontmatter["docs_mutation_authorized"] is True
        assert frontmatter["runtime_mutation_authorized"] is False
        assert frontmatter["remediates_request_id"] == "REQ-conflict"
        assert any(
            str(reason).startswith("task_write_conflict:")
            for reason in frontmatter["decompose_failure_reasons"]
        )

    def test_single_request_writes_admission_remediation_task(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        tasks = tmp_path / "tasks"
        (tasks / "active").mkdir(parents=True)
        (tasks / "closed").mkdir(parents=True)
        request = tmp_path / "REQ-single-blocked.md"
        request.write_text(
            """---
type: hapax-request
request_id: REQ-single-blocked
status: accepted_for_planning
planning_case: CASE-TEST-001
---

# Request
""",
            encoding="utf-8",
        )

        def fail_if_called(_request_data):
            raise AssertionError("LLM should not run before admission")

        monkeypatch.setattr(script, "TASKS_DIR", tasks)
        monkeypatch.setattr(script, "_decompose_with_llm", fail_if_called)
        monkeypatch.setattr(sys, "argv", ["request-decompose", str(request)])

        assert script.main() == 1

        [remediation_task] = list(
            (tasks / "active").glob("request-decompose-admission-blocked-*.md")
        )
        frontmatter, _body = parse_frontmatter(remediation_task)
        assert frontmatter["remediates_request_id"] == "REQ-single-blocked"
        assert frontmatter["decompose_failure_class"] == "admission_blocked"

    def test_single_request_writes_llm_failure_remediation_task(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        tasks = tmp_path / "tasks"
        (tasks / "active").mkdir(parents=True)
        (tasks / "closed").mkdir(parents=True)
        request = tmp_path / "REQ-single-llm.md"
        request.write_text(
            """---
type: hapax-request
request_id: REQ-single-llm
status: accepted_for_planning
planning_case: CASE-TEST-001
cctv_intake_receipt: receipt://REQ-single-llm
cctv_intake_verdict: ready_to_plan
---

# Request
""",
            encoding="utf-8",
        )

        monkeypatch.setattr(script, "TASKS_DIR", tasks)
        monkeypatch.setattr(script, "_decompose_with_llm", lambda _request_data: None)
        monkeypatch.setattr(sys, "argv", ["request-decompose", str(request)])

        assert script.main() == 1

        [remediation_task] = list((tasks / "active").glob("request-decompose-llm-failed-*.md"))
        frontmatter, _body = parse_frontmatter(remediation_task)
        assert frontmatter["remediates_request_id"] == "REQ-single-llm"
        assert frontmatter["decompose_failure_class"] == "llm_failed"

    def test_single_request_writes_write_conflict_remediation_task(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        tasks = tmp_path / "tasks"
        (tasks / "active").mkdir(parents=True)
        (tasks / "closed").mkdir(parents=True)
        request = tmp_path / "REQ-single-conflict.md"
        request.write_text(
            """---
type: hapax-request
request_id: REQ-single-conflict
status: accepted_for_planning
planning_case: CASE-TEST-001
cctv_intake_receipt: receipt://REQ-single-conflict
cctv_intake_verdict: ready_to_plan
---

# Request
""",
            encoding="utf-8",
        )
        (tasks / "active" / "conflicting-task.md").write_text(
            """---
type: cc-task
task_id: conflicting-task
status: offered
---

# Task
""",
            encoding="utf-8",
        )

        def fake_decompose(request_data):
            return RequestDecomposition(
                request_id="REQ-single-conflict",
                request_path=request_data["path"],
                tasks=[
                    TaskSpec(
                        task_id="conflicting-task",
                        title="Conflicting task",
                        parent_request=request_data["filename"],
                        authority_case="CASE-TEST-001",
                        acceptance_criteria=["Done"],
                    )
                ],
            )

        monkeypatch.setattr(script, "TASKS_DIR", tasks)
        monkeypatch.setattr(script, "_decompose_with_llm", fake_decompose)
        monkeypatch.setattr(sys, "argv", ["request-decompose", str(request)])

        assert script.main() == 1

        [remediation_task] = list((tasks / "active").glob("request-decompose-write-conflict-*.md"))
        frontmatter, _body = parse_frontmatter(remediation_task)
        assert frontmatter["remediates_request_id"] == "REQ-single-conflict"
        assert frontmatter["decompose_failure_class"] == "write_conflict"
