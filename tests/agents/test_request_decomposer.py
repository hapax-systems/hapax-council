"""End-to-end tests for the request decomposer pipeline."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import re
import sys
import tempfile
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import yaml

import agents.request_decomposer.writer as decomposition_writer
from agents.request_decomposer.models import (
    REQUIREMENT_VECTOR_DIMENSIONS,
    RequestDecomposition,
    RequestDecompositionPlan,
    TaskSpec,
)
from agents.request_decomposer.writer import (
    decomposition_commit_state,
    request_admission_sha256,
    write_decomposition,
)
from shared.frontmatter import parse_frontmatter
from shared.route_metadata_schema import RouteMetadataStatus, assess_route_metadata
from shared.sdlc_task_store import TaskStoreError

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


def _task_demand() -> dict[str, object]:
    return {
        "authority_class": "source_mutation",
        "grounding_criticality": 5,
        "governance_claim_risk": 5,
        "codebase_locality": "cross_module",
        "implementation_complexity": 4,
        "architectural_novelty": 3,
        "requirement_ambiguity": 2,
        "estimated_context_tokens": 32000,
        "context_breadth": "vault_plus_repo",
        "source_grounding_need": "local_docs",
        "required_tools": [],
        "execution_environment": {"required": False, "surfaces": []},
        "verification_demand": {
            "deterministic_tests": ["tests/agents/test_request_decomposer.py"],
            "static_checks": ["ruff"],
            "runtime_observation": [],
        },
        "security_privacy_sensitivity": 4,
        "release_publication_impact": 0,
        "coordination_load": 4,
        "branch_worktree_conflict_risk": 3,
        "operator_insight_dependency": 4,
        "failure_cost": 5,
        "fixed_route_overhead_sensitivity": 2,
    }


def _decomposition_holds(task_root: Path) -> list[dict[str, object]]:
    return [
        yaml.safe_load(path.read_bytes())
        for path in sorted((task_root / "_decomposition_holds").glob("*.yaml"))
    ]


def _rewrite_decomposition_journal_as_v1(task_root: Path) -> Path:
    [transaction_path] = list((task_root / ".request-decompose-transactions").iterdir())
    manifest_path = transaction_path / "manifest.yaml"
    staged_receipt_path = transaction_path / "receipt.yaml"
    manifest = yaml.safe_load(manifest_path.read_bytes())
    receipt = yaml.safe_load(staged_receipt_path.read_bytes())
    receipt.pop("task_identity_guard", None)
    receipt["tasks"] = [
        {"path": entry["path"], "sha256": entry["content_sha256"]} for entry in receipt["tasks"]
    ]
    receipt["schema"] = "hapax.request-decomposition-commit.v1"
    receipt_bytes = yaml.safe_dump(
        receipt,
        sort_keys=False,
        allow_unicode=False,
    ).encode("utf-8")
    staged_receipt_path.write_bytes(receipt_bytes)
    final_receipt = Path(manifest["receipt"]["final"])
    if final_receipt.exists():
        final_receipt.write_bytes(receipt_bytes)
    manifest["schema"] = "hapax.request-decomposition-transaction.v1"
    manifest["receipt"]["sha256"] = hashlib.sha256(receipt_bytes).hexdigest()
    manifest.pop("task_identity_guard", None)
    manifest["tasks"] = [
        {
            "stage": entry["stage"],
            "final": entry["final"],
            "sha256": entry["content_sha256"],
        }
        for entry in manifest["tasks"]
    ]
    manifest_without_hash = dict(manifest)
    manifest_without_hash.pop("manifest_sha256", None)
    manifest["manifest_sha256"] = decomposition_writer._canonical_hash(manifest_without_hash)
    manifest_path.write_bytes(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=False).encode("utf-8")
    )
    return transaction_path


def _rewrite_decomposition_journal_as_v2(task_root: Path) -> Path:
    transaction = _rewrite_decomposition_journal_as_v1(task_root)
    manifest_path = transaction / "manifest.yaml"
    receipt_path = transaction / "receipt.yaml"
    manifest = yaml.safe_load(manifest_path.read_bytes())
    receipt = yaml.safe_load(receipt_path.read_bytes())
    receipt["schema"] = "hapax.request-decomposition-commit.v2"
    receipt_bytes = yaml.safe_dump(receipt, sort_keys=False, allow_unicode=False).encode("utf-8")
    receipt_path.write_bytes(receipt_bytes)
    final_receipt = Path(manifest["receipt"]["final"])
    if final_receipt.exists():
        final_receipt.write_bytes(receipt_bytes)
    manifest["schema"] = "hapax.request-decomposition-transaction.v2"
    manifest["receipt"]["sha256"] = hashlib.sha256(receipt_bytes).hexdigest()
    manifest_without_hash = dict(manifest)
    manifest_without_hash.pop("manifest_sha256", None)
    manifest["manifest_sha256"] = decomposition_writer._canonical_hash(manifest_without_hash)
    manifest_path.write_bytes(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=False).encode("utf-8")
    )
    return transaction


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
        with pytest.raises(
            ValueError,
            match=(
                "routing taxonomy requires requirement_vector_validity_mask; next action: add "
                "true/false validity"
            ),
        ):
            TaskSpec(
                task_id="taxonomy-no-mask",
                title="No mask",
                parent_request="REQ-test.md",
                authority_case="CASE-TEST",
                acceptance_criteria=["It works"],
                routing_class="source_python",
                requirement_vector=_requirement_vector(),
            )

    def test_taxonomy_without_requirement_vector_rejected_with_next_action(self):
        with pytest.raises(
            ValueError,
            match=("routing taxonomy requires requirement_vector; next action: add one 0-5 score"),
        ):
            TaskSpec(
                task_id="taxonomy-no-vector",
                title="No vector",
                parent_request="REQ-test.md",
                authority_case="CASE-TEST",
                acceptance_criteria=["It works"],
                routing_class="source_python",
                requirement_vector_validity_mask=_validity_mask(),
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


class TestPrecomputedDecompositionPlan:
    def _fixture(
        self,
        tmp_path: Path,
    ) -> tuple[RequestDecompositionPlan, Path, Path, Path]:
        request_dir = tmp_path / "requests" / "active"
        request_dir.mkdir(parents=True)
        request_path = request_dir / "REQ-plan.md"
        request_source = tmp_path / "REQ-plan.captured.md"
        source_bytes = b"""---
type: hapax-request
request_id: REQ-plan
status: captured
authority_level: support_non_authoritative
---

# Exact source request
"""
        request_source.write_bytes(source_bytes)
        source_hash = hashlib.sha256(source_bytes).hexdigest()

        external_task = tmp_path / "external-task.md"
        external_task.write_text(
            """---
type: cc-task
task_id: external-task
status: in_progress
---

# External task
""",
            encoding="utf-8",
        )
        external_hash = hashlib.sha256(external_task.read_bytes()).hexdigest()
        request_admission = {
            "request_id": "REQ-plan",
            "status": "accepted_for_planning",
            "authority_level": "support_non_authoritative",
            "planning_case": "CASE-CAPACITY-ROUTING-001",
            "parent_spec": "/specs/convergence.md",
            "cctv_intake_receipt": "receipt://REQ-plan",
            "cctv_intake_verdict": "ready_to_plan",
            "cctv_route_resource_admission": "admitted",
            "cctv_capability_receipts": ["receipt://capability/plan"],
        }
        plan_payload: dict[str, object] = {
            "schema": "hapax.request-decomposition-plan.v2",
            "plan_id": "plan-req-plan-v1",
            "created_at": "2026-07-12T06:00:00Z",
            "request_id": "REQ-plan",
            "request_path": str(request_path),
            "request_admission_sha256": request_admission_sha256(request_admission),
            "request_source_path": str(request_source),
            "request_source_sha256": source_hash,
            "decomposition_model": "precomputed:test",
            "generator_refs": ["test:deterministic"],
            "policy_refs": ["policy:request-decomposition-plan-v1"],
            "source_bindings": [
                {
                    "path": str(request_source),
                    "sha256": source_hash,
                    "authority_level": "support_non_authoritative",
                    "may_authorize": False,
                }
            ],
            "external_dependencies": [
                {
                    "dependency_id": "external-task",
                    "kind": "cc_task",
                    "path": str(external_task),
                    "sha256": external_hash,
                    "authority_level": "support_non_authoritative",
                    "may_authorize": False,
                }
            ],
            "expected_existing_downstream_tasks": [],
            "tasks": [
                {
                    "task_id": "planned-task",
                    "title": "Perform the planned task",
                    "kind": "build",
                    "priority": "p0",
                    "wsjf": 0.0,
                    "priority_basis": "ratified_dependency_order",
                    "priority_window": "after_gate0a",
                    "phase_index": 0,
                    "local_dependencies": [],
                    "external_dependency_ids": ["external-task"],
                    "intent": "Preserve this task without granting execution authority.",
                    "acceptance_criteria": ["The exact hold is inspectable."],
                    "effort_class": "high",
                    "mutation_surface": "source",
                    "scope_state": "exact",
                    "mutation_scope_refs": ["shared/coord_event_log.py"],
                    "target_paths": ["shared/coord_event_log.py"],
                    "quality_floor": "frontier_required",
                    "routing_class": "source_python",
                    "requirement_vector": _requirement_vector(
                        quality_floor=5,
                        information_scope=5,
                        context_length=4,
                        mutation_risk=5,
                        verification_demand=5,
                        ambiguity_novelty=3,
                        composition_coupling=5,
                        governance_sensitivity=5,
                    ),
                    "composition_tolerance": "sequential_required",
                    "requirement_vector_validity_mask": _validity_mask(),
                    "task_demand": _task_demand(),
                    "parent_request": request_path.name,
                    "parent_spec": "/specs/convergence.md",
                    "authority_case": "CASE-CAPACITY-ROUTING-001",
                    "authority_level": "support_non_authoritative",
                    "requested_authority_level": "authoritative",
                    "initial_projection": {
                        "stage": "S0",
                        "status": "blocked",
                        "claimable": False,
                        "assigned_to": "unassigned",
                        "hold_refs": ["external-task", "authority_transition_required"],
                        "authorization": {
                            "may_authorize": False,
                            "implementation_authorized": False,
                            "source_mutation_authorized": False,
                            "docs_mutation_authorized": False,
                            "runtime_mutation_authorized": False,
                            "release_authorized": False,
                            "public_mutation_authorized": False,
                            "provider_spend_authorized": False,
                        },
                        "may_authorize": False,
                    },
                    "losses": [],
                    "unresolveds": [],
                    "may_authorize": False,
                }
            ],
            "authority_level": "support_non_authoritative",
            "losses": [],
            "unresolveds": [],
            "may_authorize": False,
        }
        plan = RequestDecompositionPlan.model_validate(plan_payload)
        plan_path = tmp_path / "decomposition-plan.yaml"
        plan_path.write_text(
            yaml.safe_dump(plan_payload, sort_keys=False),
            encoding="utf-8",
        )
        plan_hash = hashlib.sha256(plan_path.read_bytes()).hexdigest()
        request_path.write_text(
            f"""---
type: hapax-request
request_id: REQ-plan
status: accepted_for_planning
authority_level: support_non_authoritative
planning_case: CASE-CAPACITY-ROUTING-001
parent_spec: /specs/convergence.md
cctv_intake_receipt: receipt://REQ-plan
cctv_intake_verdict: ready_to_plan
cctv_route_resource_admission: admitted
cctv_capability_receipts:
  - receipt://capability/plan
decomposition_plan_ref: {plan_path}
decomposition_plan_sha256: {plan_hash}
custom_field: preserve-exactly
# preserve-this-comment
---

# Current request
""",
            encoding="utf-8",
        )
        return plan, request_path, plan_path, external_task

    def test_bound_plan_bypasses_llm_and_dry_run_is_zero_write(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        plan, request_path, _plan_path, _external_task = self._fixture(tmp_path)
        request_data = script._read_request(request_path)

        def fail_if_called(_request_data):
            raise AssertionError("bound plans must not invoke the LLM")

        monkeypatch.setattr(script, "_decompose_with_llm", fail_if_called)
        loaded = script._decompose_request(request_data)

        assert loaded == plan
        task_root = tmp_path / "tasks"
        paths = write_decomposition(plan, task_root, dry_run=True)
        assert paths == [task_root / "active" / "planned-task.md"]
        assert not task_root.exists()

    def test_bound_v1_plan_creates_typed_zero_authority_hold(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        plan, request_path, plan_path, _external_task = self._fixture(tmp_path)
        payload = plan.model_dump(mode="json", by_alias=True)
        payload["schema"] = "hapax.request-decomposition-plan.v1"
        payload["tasks"][0]["initial_projection"]["stage"] = "S1_INTAKE"
        plan_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        request_path.write_text(
            re.sub(
                r"(?m)^decomposition_plan_sha256: [0-9a-f]{64}$",
                f"decomposition_plan_sha256: {hashlib.sha256(plan_path.read_bytes()).hexdigest()}",
                request_path.read_text(encoding="utf-8"),
            ),
            encoding="utf-8",
        )
        task_root = tmp_path / "tasks"
        monkeypatch.setattr(script, "TASKS_DIR", task_root)
        monkeypatch.setattr(sys, "argv", ["request-decompose", str(request_path)])

        assert script.main() == 1
        [hold] = _decomposition_holds(task_root)
        assert hold["failure_class"] == ("historical_decomposition_genesis_correction_required")
        assert hold["reason_codes"] == [
            "historical_decomposition_plan_v1_requires_explicit_s0_correction"
        ]
        assert hold["may_authorize"] is False
        assert not (task_root / "active").exists()

    def test_plan_commit_is_blocked_receipted_and_idempotent(self, tmp_path):
        plan, request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        request_before = request_path.read_bytes()

        [task_path] = write_decomposition(plan, task_root)
        task_fields, _body = parse_frontmatter(task_path)
        assert task_fields["status"] == "blocked"
        assert task_fields["stage"] == "S0"
        assert task_fields["claimable"] is False
        assert task_fields["may_authorize"] is False
        assert task_fields["implementation_authorized"] is False
        assert task_fields["source_mutation_authorized"] is False
        assert task_fields["mutation_scope_refs"] == ["shared/coord_event_log.py"]
        assert task_fields["depends_on"] == ["external-task"]
        receipt_path = Path(task_fields["decomposition_commit_receipt"])
        assert receipt_path.is_file()
        receipt = yaml.safe_load(receipt_path.read_bytes())
        assert receipt["schema"] == "hapax.request-decomposition-commit.v3"
        [transaction] = list((task_root / ".request-decompose-transactions").iterdir())
        manifest = yaml.safe_load((transaction / "manifest.yaml").read_bytes())
        guard = receipt["task_identity_guard"]
        assert manifest["schema"] == "hapax.request-decomposition-transaction.v3"
        assert manifest["task_identity_guard"] == guard
        assert guard["schema"] == "hapax.task-identity-write-guard.v2"
        assert guard["base_content_frontier_hash"] != guard["expected_content_frontier_hash"]
        assert receipt["tasks"] == [
            {
                "content_sha256": guard["intents"][0]["content_sha256"],
                "path": str(task_path),
                "relative_path": "active/planned-task.md",
                "state": "active",
                "task_id": "planned-task",
            }
        ]
        assert receipt["identity"]["genesis_stage"] == "S0"
        assert request_path.read_bytes() == request_before
        assert (task_root / ".request-decompose-transactions").is_dir()
        assert write_decomposition(plan, task_root) == [task_path]

    def test_direct_api_resolves_current_path_after_governed_state_move(self, tmp_path):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        [task_path] = write_decomposition(plan, task_root)
        closed_path = task_root / "closed" / task_path.name
        closed_path.parent.mkdir()
        task_path.rename(closed_path)
        replacement = closed_path.with_suffix(".progress")
        replacement.write_text(
            closed_path.read_text(encoding="utf-8").replace(
                "status: blocked",
                "status: completed",
            ),
            encoding="utf-8",
        )
        replacement.replace(closed_path)

        assert write_decomposition(plan, task_root) == [closed_path.resolve()]
        assert decomposition_commit_state(plan, task_root) == "committed"

    def test_direct_api_refuses_committed_missing_live_projection(self, tmp_path):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        [task_path] = write_decomposition(plan, task_root)
        task_path.unlink()

        [inspection] = decomposition_writer.inspect_decomposition_journals(task_root)
        assert inspection.state == "committed"
        assert inspection.system_atomic is False
        assert inspection.gate0b_hold_reason == "single_committer_generation_fence_required"
        assert inspection.residue_policy == "preserve_for_reconciliation"
        assert inspection.cleanup_authorized is False
        assert inspection.gate0b_cleanup_hold_reason == (
            "single_committer_residue_cleanup_required"
        )
        assert inspection.projection_update_requirement == "replace_only_no_in_place_mutation"
        with pytest.raises(TaskStoreError, match="task_identity_projection_missing"):
            write_decomposition(plan, task_root)
        with pytest.raises(TaskStoreError, match="task_identity_projection_missing"):
            decomposition_commit_state(plan, task_root)

    def test_direct_api_refuses_committed_duplicate_live_projection(self, tmp_path):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        [task_path] = write_decomposition(plan, task_root)
        duplicate = task_root / "closed" / task_path.name
        duplicate.parent.mkdir()
        duplicate.write_bytes(task_path.read_bytes())

        with pytest.raises(TaskStoreError, match="task_identity_projection_ambiguous"):
            write_decomposition(plan, task_root)
        with pytest.raises(TaskStoreError, match="task_identity_projection_ambiguous"):
            decomposition_commit_state(plan, task_root)

    def test_receipt_install_projection_race_never_returns_success(
        self,
        tmp_path,
        monkeypatch,
    ):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        original_install = decomposition_writer._install_no_replace

        def install_receipt_then_remove_projection(stage, final, expected_hash):
            result = original_install(stage, final, expected_hash)
            if final.suffix == ".yaml":
                (task_root / "active" / "planned-task.md").unlink()
            return result

        monkeypatch.setattr(
            decomposition_writer,
            "_install_no_replace",
            install_receipt_then_remove_projection,
        )

        with pytest.raises(ValueError, match="receipt lacks the exact guarded task post-frontier"):
            write_decomposition(plan, task_root)

        assert list((task_root / "_decomposition_receipts").glob("*.yaml"))
        with pytest.raises(TaskStoreError, match="task_identity_projection_missing"):
            write_decomposition(plan, task_root)

    @pytest.mark.parametrize(
        ("parent_name", "final_suffix"),
        [
            ("active", ".md"),
            ("_decomposition_receipts", ".yaml"),
        ],
    )
    def test_parent_swap_during_install_refuses_and_preserves_linked_artifact(
        self,
        tmp_path,
        monkeypatch,
        parent_name: str,
        final_suffix: str,
    ):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        outside = tmp_path / "outside"
        displaced = tmp_path / f"displaced-{parent_name}"
        outside.mkdir()
        original_link = decomposition_writer.os.link
        swapped = False

        def swap_parent_then_link(src, dst, **kwargs):
            nonlocal swapped
            if not swapped and str(dst).endswith(final_suffix):
                parent = task_root / parent_name
                parent.rename(displaced)
                parent.symlink_to(outside, target_is_directory=True)
                swapped = True
            return original_link(src, dst, **kwargs)

        monkeypatch.setattr(decomposition_writer.os, "link", swap_parent_then_link)

        with pytest.raises((OSError, TaskStoreError, FileExistsError)):
            write_decomposition(plan, task_root)

        assert swapped is True
        assert list(outside.iterdir()) == []
        preserved = list(displaced.glob(f"*{final_suffix}"))
        assert len(preserved) == 1
        assert preserved[0].stat().st_nlink >= 2

    def test_transaction_parent_swap_during_publish_refuses_without_escape(
        self,
        tmp_path,
        monkeypatch,
    ):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        transaction_root = task_root / ".request-decompose-transactions"
        displaced = tmp_path / "displaced-transactions"
        outside = tmp_path / "outside-transactions"
        outside.mkdir()
        original_rename = decomposition_writer.os.rename
        original_publish = decomposition_writer.rename_task_store_no_replace
        swapped = False

        def swap_transaction_parent_then_publish(src_fd, src, dst_fd, dst):
            nonlocal swapped
            if not swapped and str(src).startswith(".") and len(str(dst)) == 64:
                original_rename(transaction_root, displaced)
                transaction_root.symlink_to(outside, target_is_directory=True)
                swapped = True
            return original_publish(src_fd, src, dst_fd, dst)

        monkeypatch.setattr(
            decomposition_writer,
            "rename_task_store_no_replace",
            swap_transaction_parent_then_publish,
        )

        with pytest.raises((OSError, TaskStoreError, FileExistsError)):
            write_decomposition(plan, task_root)

        assert swapped is True
        assert list(outside.iterdir()) == []
        published = [
            path
            for path in displaced.iterdir()
            if re.fullmatch(r"[0-9a-f]{64}", path.name)
        ]
        assert len(published) == 1
        assert (published[0] / "manifest.yaml").is_file()
        assert not (task_root / "active" / "planned-task.md").exists()

    def test_transaction_publish_collision_preserves_unowned_destination(
        self,
        tmp_path,
        monkeypatch,
    ):
        plan, _request_path, plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        transaction_root = task_root / ".request-decompose-transactions"
        commit_id = decomposition_writer._planned_commit_id(
            plan,
            hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        )
        raced_destination = transaction_root / commit_id
        marker = raced_destination / "unowned-marker"
        original_write = decomposition_writer._write_bytes

        def write_manifest_then_race_destination(path, content):
            result = original_write(path, content)
            if path.name == "manifest.yaml":
                raced_destination.mkdir()
                marker.write_bytes(b"must survive")
            return result

        monkeypatch.setattr(
            decomposition_writer,
            "_write_bytes",
            write_manifest_then_race_destination,
        )

        with pytest.raises(FileExistsError):
            write_decomposition(plan, task_root)

        assert marker.read_bytes() == b"must survive"
        staging_residue = list(transaction_root.glob(f".{commit_id}.staging-*"))
        assert len(staging_residue) == 1
        assert (staging_residue[0] / "manifest.yaml").is_file()
        assert not (task_root / "active" / "planned-task.md").exists()
        assert not (task_root / "_decomposition_receipts").exists()

    def test_post_install_cross_state_duplicate_refuses_receipt(self, tmp_path, monkeypatch):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        original_install = decomposition_writer._install_no_replace

        def install_then_duplicate(stage, final, expected_hash):
            result = original_install(stage, final, expected_hash)
            if final.suffix == ".md":
                duplicate = task_root / "closed" / "raced-descriptor.md"
                duplicate.parent.mkdir(parents=True, exist_ok=True)
                duplicate.write_bytes(stage.read_bytes())
            return result

        monkeypatch.setattr(
            decomposition_writer,
            "_install_no_replace",
            install_then_duplicate,
        )

        with pytest.raises(RuntimeError, match="store_ambiguous"):
            write_decomposition(plan, task_root)

        assert not list((task_root / "_decomposition_receipts").glob("*.yaml"))

    def test_unrelated_task_drift_after_journal_stage_refuses_all_intents(
        self,
        tmp_path,
        monkeypatch,
    ):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        original_stage = decomposition_writer._stage_transaction

        def stage_then_drift(prepared):
            manifest = original_stage(prepared)
            unrelated = task_root / "active" / "unrelated.md"
            unrelated.parent.mkdir(parents=True, exist_ok=True)
            unrelated.write_text(
                "---\ntype: cc-task\ntask_id: unrelated\nstatus: blocked\n---\n",
                encoding="utf-8",
            )
            return manifest

        monkeypatch.setattr(decomposition_writer, "_stage_transaction", stage_then_drift)

        with pytest.raises(RuntimeError, match="residual_content_frontier_mismatch"):
            write_decomposition(plan, task_root)

        assert not (task_root / "active" / "planned-task.md").exists()
        assert not list((task_root / "_decomposition_receipts").glob("*.yaml"))

    def test_external_binding_hash_drift_refuses_before_write(self, tmp_path):
        plan, _request_path, _plan_path, external_task = self._fixture(tmp_path)
        external_task.write_text("drifted", encoding="utf-8")
        task_root = tmp_path / "tasks"

        with pytest.raises(ValueError, match="binding hash drift"):
            write_decomposition(plan, task_root, dry_run=True)
        assert not task_root.exists()

    def test_interrupted_commit_rolls_forward_exact_staged_bytes(self, tmp_path, monkeypatch):
        plan, request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        request_before = request_path.read_bytes()
        original_install = decomposition_writer._install_no_replace

        def interrupt_before_receipt(stage, final, expected_hash):
            if final.suffix == ".yaml":
                raise RuntimeError("simulated power cut")
            return original_install(stage, final, expected_hash)

        monkeypatch.setattr(decomposition_writer, "_install_no_replace", interrupt_before_receipt)
        with pytest.raises(RuntimeError, match="simulated power cut"):
            write_decomposition(plan, task_root)
        task_path = task_root / "active" / "planned-task.md"
        assert task_path.is_file()
        assert request_path.read_bytes() == request_before

        monkeypatch.setattr(decomposition_writer, "_install_no_replace", original_install)
        assert write_decomposition(plan, task_root) == [task_path]
        task_fields, _body = parse_frontmatter(task_path)
        assert Path(task_fields["decomposition_commit_receipt"]).is_file()
        assert request_path.read_bytes() == request_before

    @pytest.mark.parametrize(
        "internal_parent",
        ["active", "_decomposition_receipts", ".request-decompose-transactions"],
    )
    def test_internal_parent_symlink_escape_is_rejected(
        self,
        tmp_path,
        internal_parent: str,
    ):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        outside = tmp_path / "outside"
        task_root.mkdir()
        outside.mkdir()
        (task_root / internal_parent).symlink_to(outside, target_is_directory=True)

        with pytest.raises(ValueError, match="escapes task root"):
            write_decomposition(plan, task_root)

        assert list(outside.iterdir()) == []

    def test_task_id_path_escape_is_rejected_by_the_plan_model(self, tmp_path):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        payload = plan.model_dump(mode="json", by_alias=True)
        payload["tasks"][0]["task_id"] = "../../escaped"

        with pytest.raises(ValueError, match="task_id"):
            RequestDecompositionPlan.model_validate(payload)

    def test_partial_pre_manifest_staging_is_preserved_and_does_not_poison_retry(
        self,
        tmp_path,
        monkeypatch,
    ):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        original_write = decomposition_writer._write_bytes
        calls = 0

        def interrupt_second_write(path, content):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("simulated staging cut")
            return original_write(path, content)

        monkeypatch.setattr(decomposition_writer, "_write_bytes", interrupt_second_write)
        with pytest.raises(RuntimeError, match="simulated staging cut"):
            write_decomposition(plan, task_root)
        transaction_root = task_root / ".request-decompose-transactions"
        assert not (
            transaction_root
            / decomposition_writer._planned_commit_id(
                plan,
                hashlib.sha256((tmp_path / "decomposition-plan.yaml").read_bytes()).hexdigest(),
            )
        ).exists()
        staging_residue = list(transaction_root.glob(".*.staging-*"))
        assert len(staging_residue) == 1
        assert (staging_residue[0] / "tasks" / "0.md").is_file()

        monkeypatch.setattr(decomposition_writer, "_write_bytes", original_write)
        assert write_decomposition(plan, task_root) == [task_root / "active" / "planned-task.md"]
        assert staging_residue[0].is_dir()

    def test_recovery_rejects_staged_authority_forgery(self, tmp_path, monkeypatch):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        original_install = decomposition_writer._install_no_replace

        def interrupt_before_receipt(stage, final, expected_hash):
            if final.suffix == ".yaml":
                raise RuntimeError("simulated power cut")
            return original_install(stage, final, expected_hash)

        monkeypatch.setattr(decomposition_writer, "_install_no_replace", interrupt_before_receipt)
        with pytest.raises(RuntimeError):
            write_decomposition(plan, task_root)
        task = task_root / "active" / "planned-task.md"
        replacement = task.with_suffix(".forged")
        replacement.write_text(
            task.read_text(encoding="utf-8").replace(
                "implementation_authorized: false",
                "implementation_authorized: true",
            ),
            encoding="utf-8",
        )
        replacement.replace(task)
        monkeypatch.setattr(decomposition_writer, "_install_no_replace", original_install)

        with pytest.raises(RuntimeError, match="installed_postimage_mismatch"):
            write_decomposition(plan, task_root)

    def test_inspection_contains_tampered_v3_guard_as_invalid(self, tmp_path):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        write_decomposition(plan, task_root)
        [transaction] = list((task_root / ".request-decompose-transactions").iterdir())
        manifest_path = transaction / "manifest.yaml"
        manifest = yaml.safe_load(manifest_path.read_bytes())
        manifest["task_identity_guard"]["guard_hash"] = "f" * 64
        manifest_without_hash = dict(manifest)
        manifest_without_hash.pop("manifest_sha256", None)
        manifest["manifest_sha256"] = decomposition_writer._canonical_hash(manifest_without_hash)
        manifest_path.write_bytes(
            yaml.safe_dump(manifest, sort_keys=False, allow_unicode=False).encode("utf-8")
        )

        [inspection] = decomposition_writer.inspect_decomposition_journals(task_root)

        assert inspection.state == "invalid"
        assert "task_identity_write_guard_hash_mismatch" in inspection.reason_code

    def test_recovery_revalidates_external_bindings(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        plan, request_path, _plan_path, external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        original_install = decomposition_writer._install_no_replace

        def interrupt_before_receipt(stage, final, expected_hash):
            if final.suffix == ".yaml":
                raise RuntimeError("simulated power cut")
            return original_install(stage, final, expected_hash)

        monkeypatch.setattr(decomposition_writer, "_install_no_replace", interrupt_before_receipt)
        with pytest.raises(RuntimeError, match="simulated power cut"):
            write_decomposition(plan, task_root)
        monkeypatch.setattr(decomposition_writer, "_install_no_replace", original_install)
        external_task.write_text("dependency drift", encoding="utf-8")

        with pytest.raises(ValueError, match="binding hash drift"):
            write_decomposition(plan, task_root, dry_run=True)
        with pytest.raises(ValueError, match="binding hash drift"):
            write_decomposition(plan, task_root)

        assert not list((task_root / "_decomposition_receipts").glob("*.yaml"))

        def fail_if_called(_request_data):
            raise AssertionError("bound-plan recovery must not call a provider")

        monkeypatch.setattr(script, "REQUESTS_DIR", request_path.parent)
        monkeypatch.setattr(script, "TASKS_DIR", task_root)
        monkeypatch.setattr(script, "_decompose_with_llm", fail_if_called)
        monkeypatch.setattr(sys, "argv", ["request-decompose", "--scan"])
        assert script.main() == 0
        [hold] = _decomposition_holds(task_root)
        assert hold["failure_class"] == "write_validation_refused"
        assert any(
            str(reason).startswith(
                "decomposition_validation_refused:decomposition binding hash drift"
            )
            for reason in hold["reason_codes"]
        )
        assert not list((task_root / "_decomposition_receipts").glob("*.yaml"))

    def test_prepared_plan_dry_run_reconciles_live_task_frontier(self, tmp_path, monkeypatch):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        original_install = decomposition_writer._install_no_replace

        def interrupt_before_receipt(stage, final, expected_hash):
            if final.suffix == ".yaml":
                raise RuntimeError("simulated power cut")
            return original_install(stage, final, expected_hash)

        monkeypatch.setattr(decomposition_writer, "_install_no_replace", interrupt_before_receipt)
        with pytest.raises(RuntimeError, match="simulated power cut"):
            write_decomposition(plan, task_root)
        monkeypatch.setattr(decomposition_writer, "_install_no_replace", original_install)
        unrelated = task_root / "active" / "unrelated-after-prepare.md"
        unrelated.write_text(
            "---\ntype: cc-task\ntask_id: unrelated-after-prepare\nstatus: blocked\n---\n",
            encoding="utf-8",
        )

        with pytest.raises(RuntimeError, match="residual_content_frontier_mismatch"):
            write_decomposition(plan, task_root, dry_run=True)

        assert not list((task_root / "_decomposition_receipts").glob("*.yaml"))

    def test_recovery_rejects_non_private_transaction_tasks_parent(
        self,
        tmp_path,
        monkeypatch,
    ):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        original_install = decomposition_writer._install_no_replace

        def interrupt_before_receipt(stage, final, expected_hash):
            if final.suffix == ".yaml":
                raise RuntimeError("simulated power cut")
            return original_install(stage, final, expected_hash)

        monkeypatch.setattr(decomposition_writer, "_install_no_replace", interrupt_before_receipt)
        with pytest.raises(RuntimeError, match="simulated power cut"):
            write_decomposition(plan, task_root)
        monkeypatch.setattr(decomposition_writer, "_install_no_replace", original_install)
        [transaction] = list((task_root / ".request-decompose-transactions").iterdir())
        staged_tasks = transaction / "tasks"
        displaced = tmp_path / "displaced-transaction-tasks"
        staged_tasks.rename(displaced)
        staged_tasks.symlink_to(displaced, target_is_directory=True)

        with pytest.raises(ValueError, match="tasks path is not a private directory"):
            write_decomposition(plan, task_root)

    def test_receipt_tamper_is_not_self_ratifying(self, tmp_path):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        [task] = write_decomposition(plan, task_root)
        fields, _body = parse_frontmatter(task)
        receipt = Path(fields["decomposition_commit_receipt"])
        receipt.write_text(receipt.read_text(encoding="utf-8") + "tampered: true\n")

        with pytest.raises(ValueError, match="postimage mismatch"):
            write_decomposition(plan, task_root)

    def test_replay_survives_later_task_request_and_dependency_progress(self, tmp_path):
        plan, request_path, _plan_path, external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        [task] = write_decomposition(plan, task_root)
        task_fields, _body = parse_frontmatter(task)
        staged_task = (
            task_root
            / ".request-decompose-transactions"
            / task_fields["decomposition_commit_id"]
            / "tasks"
            / "0.md"
        )
        staged_before = staged_task.read_bytes()
        assert task.stat().st_ino == staged_task.stat().st_ino

        replacement = task.with_suffix(".progress")
        replacement.write_text(
            task.read_text(encoding="utf-8").replace("status: blocked", "status: in_progress"),
            encoding="utf-8",
        )
        replacement.replace(task)
        assert task.stat().st_ino != staged_task.stat().st_ino
        assert staged_task.read_bytes() == staged_before
        request_path.write_text(
            request_path.read_text(encoding="utf-8") + "\n# later operator note\n",
            encoding="utf-8",
        )
        external_task.write_text("later dependency state", encoding="utf-8")

        assert write_decomposition(plan, task_root) == [task]

    def test_request_frontier_change_after_staging_refuses_visible_commit(
        self,
        tmp_path,
        monkeypatch,
    ):
        plan, request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        original_stage = decomposition_writer._stage_transaction

        def stage_then_change_request(prepared):
            manifest = original_stage(prepared)
            request_path.write_text(
                request_path.read_text(encoding="utf-8").replace(
                    "status: accepted_for_planning",
                    "status: rejected",
                ),
                encoding="utf-8",
            )
            return manifest

        monkeypatch.setattr(
            decomposition_writer,
            "_stage_transaction",
            stage_then_change_request,
        )

        with pytest.raises(FileExistsError, match="source bytes changed"):
            write_decomposition(plan, task_root)

        assert not (task_root / "active" / "planned-task.md").exists()
        assert not list((task_root / "_decomposition_receipts").glob("*.yaml"))
        assert list((task_root / ".request-decompose-transactions").iterdir())

    def test_scan_recovers_task_before_receipt_partial_commit(
        self,
        tmp_path,
        monkeypatch,
    ):
        script = _load_request_decompose_module()
        plan, request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        original_install = decomposition_writer._install_no_replace

        def interrupt_before_receipt(stage, final, expected_hash):
            if final.suffix == ".yaml":
                raise RuntimeError("simulated power cut")
            return original_install(stage, final, expected_hash)

        monkeypatch.setattr(decomposition_writer, "_install_no_replace", interrupt_before_receipt)
        with pytest.raises(RuntimeError, match="simulated power cut"):
            write_decomposition(plan, task_root)
        monkeypatch.setattr(decomposition_writer, "_install_no_replace", original_install)
        monkeypatch.setattr(script, "REQUESTS_DIR", request_path.parent)
        monkeypatch.setattr(script, "TASKS_DIR", task_root)

        assert script._find_undecomposed_requests() == [request_path]

        monkeypatch.setattr(sys, "argv", ["request-decompose", "--scan"])
        assert script.main() == 0
        [task_path] = list((task_root / "active").glob("planned-task.md"))
        task_fields, _body = parse_frontmatter(task_path)
        assert Path(task_fields["decomposition_commit_receipt"]).is_file()
        assert script._find_undecomposed_requests() == []

    def test_scan_surfaces_prepared_commit_after_request_status_changes(
        self,
        tmp_path,
        monkeypatch,
    ):
        script = _load_request_decompose_module()
        plan, request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        original_install = decomposition_writer._install_no_replace

        def interrupt_before_receipt(stage, final, expected_hash):
            if final.suffix == ".yaml":
                raise RuntimeError("simulated power cut")
            return original_install(stage, final, expected_hash)

        monkeypatch.setattr(decomposition_writer, "_install_no_replace", interrupt_before_receipt)
        with pytest.raises(RuntimeError, match="simulated power cut"):
            write_decomposition(plan, task_root)
        monkeypatch.setattr(decomposition_writer, "_install_no_replace", original_install)
        request_path.write_text(
            request_path.read_text(encoding="utf-8").replace(
                "status: accepted_for_planning",
                "status: rejected",
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(script, "REQUESTS_DIR", request_path.parent)
        monkeypatch.setattr(script, "TASKS_DIR", task_root)

        def fail_if_called(_request_data):
            raise AssertionError("rejected prepared input must not call a provider")

        monkeypatch.setattr(script, "_decompose_with_llm", fail_if_called)
        assert script._find_undecomposed_requests() == [request_path]

        monkeypatch.setattr(sys, "argv", ["request-decompose", "--scan"])
        assert script.main() == 0
        [hold] = _decomposition_holds(task_root)
        assert "request_status_not_accepted_for_planning:rejected" in hold["reason_codes"]
        assert not list((task_root / "_decomposition_receipts").glob("*.yaml"))

    @pytest.mark.parametrize(
        ("pointer_state", "expected_reason"),
        [
            ("removed", "prepared_decomposition_binding_missing"),
            ("superseded", "prepared_decomposition_binding_superseded"),
        ],
    )
    def test_scan_surfaces_prepared_journal_independently_of_live_plan_pointer(
        self,
        tmp_path,
        monkeypatch,
        pointer_state: str,
        expected_reason: str,
    ):
        script = _load_request_decompose_module()
        plan, request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        original_install = decomposition_writer._install_no_replace

        def interrupt_before_first_task(stage, final, expected_hash):
            if final.suffix == ".md":
                raise RuntimeError("simulated power cut")
            return original_install(stage, final, expected_hash)

        monkeypatch.setattr(
            decomposition_writer,
            "_install_no_replace",
            interrupt_before_first_task,
        )
        with pytest.raises(RuntimeError, match="simulated power cut"):
            write_decomposition(plan, task_root)
        monkeypatch.setattr(decomposition_writer, "_install_no_replace", original_install)
        request_text = request_path.read_text(encoding="utf-8")
        if pointer_state == "removed":
            request_text = re.sub(
                r"(?m)^decomposition_plan_(?:ref|sha256):.*\n",
                "",
                request_text,
            )
        else:
            request_text = re.sub(
                r"(?m)^decomposition_plan_sha256: [0-9a-f]{64}$",
                f"decomposition_plan_sha256: {'b' * 64}",
                request_text,
            )
        request_path.write_text(request_text, encoding="utf-8")
        monkeypatch.setattr(script, "REQUESTS_DIR", request_path.parent)
        monkeypatch.setattr(script, "TASKS_DIR", task_root)

        def fail_if_called(_request_data):
            raise AssertionError("an unbound prepared journal must not call a provider")

        monkeypatch.setattr(script, "_decompose_with_llm", fail_if_called)
        assert not (task_root / "active" / "planned-task.md").exists()
        assert script._find_undecomposed_requests() == [request_path]

        monkeypatch.setattr(sys, "argv", ["request-decompose", "--scan"])
        assert script.main() == 0
        [hold] = _decomposition_holds(task_root)
        assert any(str(reason).startswith(f"{expected_reason}:") for reason in hold["reason_codes"])
        assert not list((task_root / "_decomposition_receipts").glob("*.yaml"))

    def test_single_request_complete_replay_is_idempotent(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        plan, request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        [task_path] = write_decomposition(plan, task_root)
        task_before = task_path.read_bytes()
        request_before = request_path.read_bytes()
        monkeypatch.setattr(script, "TASKS_DIR", task_root)

        def fail_if_called(_request_data):
            raise AssertionError("bound complete replay must not call a provider")

        monkeypatch.setattr(script, "_decompose_with_llm", fail_if_called)
        monkeypatch.setattr(sys, "argv", ["request-decompose", str(request_path)])

        assert script.main() == 0
        assert task_path.read_bytes() == task_before
        assert request_path.read_bytes() == request_before
        assert not (task_root / "_decomposition_holds").exists()

    def test_completed_journal_does_not_reopen_when_live_plan_pointer_is_removed(
        self,
        tmp_path,
        monkeypatch,
    ):
        script = _load_request_decompose_module()
        plan, request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        write_decomposition(plan, task_root)
        request_path.write_text(
            re.sub(
                r"(?m)^decomposition_plan_(?:ref|sha256):.*\n",
                "",
                request_path.read_text(encoding="utf-8"),
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(script, "REQUESTS_DIR", request_path.parent)
        monkeypatch.setattr(script, "TASKS_DIR", task_root)

        assert script._find_undecomposed_requests() == []

    def test_committed_v1_journal_is_exact_history_only(self, tmp_path):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        write_decomposition(plan, task_root)
        transaction = _rewrite_decomposition_journal_as_v1(task_root)
        before = {
            path.relative_to(transaction): path.read_bytes()
            for path in transaction.rglob("*")
            if path.is_file()
        }

        [inspection] = decomposition_writer.inspect_decomposition_journals(task_root)

        assert inspection.state == "committed"
        assert inspection.history_only is True
        assert inspection.schema == "hapax.request-decomposition-transaction.v1"
        assert inspection.reason_code == "historical_v1_commit_receipt_valid"
        assert before == {
            path.relative_to(transaction): path.read_bytes()
            for path in transaction.rglob("*")
            if path.is_file()
        }

    def test_prepared_v1_journal_is_history_only_and_never_recovered(
        self,
        tmp_path,
        monkeypatch,
    ):
        plan, request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        original_install = decomposition_writer._install_no_replace

        def interrupt_before_first_task(stage, final, expected_hash):
            if final.suffix == ".md":
                raise RuntimeError("simulated power cut")
            return original_install(stage, final, expected_hash)

        monkeypatch.setattr(
            decomposition_writer,
            "_install_no_replace",
            interrupt_before_first_task,
        )
        with pytest.raises(RuntimeError, match="simulated power cut"):
            write_decomposition(plan, task_root)
        monkeypatch.setattr(decomposition_writer, "_install_no_replace", original_install)
        transaction = _rewrite_decomposition_journal_as_v1(task_root)
        before = {
            path.relative_to(transaction): path.read_bytes()
            for path in transaction.rglob("*")
            if path.is_file()
        }

        [inspection] = decomposition_writer.inspect_decomposition_journals(task_root)

        assert inspection.state == "invalid"
        assert inspection.history_only is True
        assert inspection.reason_code == "historical_v1_prepared_no_recovery"
        assert not (task_root / "active" / "planned-task.md").exists()
        assert before == {
            path.relative_to(transaction): path.read_bytes()
            for path in transaction.rglob("*")
            if path.is_file()
        }
        assert request_path.is_file()

    def test_committed_v2_journal_is_history_only_and_idempotent(self, tmp_path):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        [task_path] = write_decomposition(plan, task_root)
        transaction = _rewrite_decomposition_journal_as_v2(task_root)
        before = {
            path.relative_to(transaction): path.read_bytes()
            for path in transaction.rglob("*")
            if path.is_file()
        }

        [inspection] = decomposition_writer.inspect_decomposition_journals(task_root)

        assert inspection.state == "committed"
        assert inspection.history_only is True
        assert inspection.schema == "hapax.request-decomposition-transaction.v2"
        assert inspection.reason_code == "historical_v2_commit_receipt_valid"
        assert write_decomposition(plan, task_root) == [task_path]
        assert before == {
            path.relative_to(transaction): path.read_bytes()
            for path in transaction.rglob("*")
            if path.is_file()
        }

    def test_prepared_v2_journal_is_history_only_and_never_recovered(
        self,
        tmp_path,
        monkeypatch,
    ):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        original_install = decomposition_writer._install_no_replace

        def interrupt_before_first_task(stage, final, expected_hash):
            if final.suffix == ".md":
                raise RuntimeError("simulated power cut")
            return original_install(stage, final, expected_hash)

        monkeypatch.setattr(
            decomposition_writer,
            "_install_no_replace",
            interrupt_before_first_task,
        )
        with pytest.raises(RuntimeError, match="simulated power cut"):
            write_decomposition(plan, task_root)
        monkeypatch.setattr(decomposition_writer, "_install_no_replace", original_install)
        _rewrite_decomposition_journal_as_v2(task_root)

        [inspection] = decomposition_writer.inspect_decomposition_journals(task_root)
        assert inspection.state == "invalid"
        assert inspection.history_only is True
        assert inspection.reason_code == "historical_v2_prepared_no_recovery"
        with pytest.raises(ValueError, match="historical_v2_prepared_no_recovery"):
            write_decomposition(plan, task_root)
        assert not list((task_root / "_decomposition_receipts").glob("*.yaml"))

    def test_committed_journal_with_missing_projection_holds_instead_of_redecomposing(
        self,
        tmp_path,
        monkeypatch,
    ):
        script = _load_request_decompose_module()
        plan, request_path, _plan_path, _external_task = self._fixture(tmp_path)
        task_root = tmp_path / "tasks"
        [task_path] = write_decomposition(plan, task_root)
        task_path.unlink()
        request_text = re.sub(
            r"(?m)^decomposition_plan_(?:ref|sha256):.*\n",
            "",
            request_path.read_text(encoding="utf-8"),
        )
        request_path.write_text(
            request_text.replace(
                "custom_field: preserve-exactly",
                "custom_field: preserve-exactly\nprovider_spend_authorized: true",
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(script, "REQUESTS_DIR", request_path.parent)
        monkeypatch.setattr(script, "TASKS_DIR", task_root)

        def fail_if_called(_request_data):
            raise AssertionError("a committed journal cannot be decomposed again")

        monkeypatch.setattr(script, "_decompose_with_llm", fail_if_called)
        assert script._find_undecomposed_requests() == [request_path]
        blockers = script._decomposition_admission_blockers(script._read_request(request_path))
        assert any(
            blocker.startswith("committed_decomposition_projection_missing:")
            for blocker in blockers
        )

        monkeypatch.setattr(sys, "argv", ["request-decompose", "--scan"])
        assert script.main() == 0
        [hold] = _decomposition_holds(task_root)
        assert any(
            str(reason).startswith("committed_decomposition_projection_missing:")
            for reason in hold["reason_codes"]
        )

    def test_unassociated_invalid_journal_creates_global_hold_and_blocks_provider(
        self,
        tmp_path,
        monkeypatch,
    ):
        script = _load_request_decompose_module()
        requests = tmp_path / "requests" / "active"
        task_root = tmp_path / "tasks"
        requests.mkdir(parents=True)
        transaction = task_root / ".request-decompose-transactions" / ("a" * 64)
        transaction.mkdir(parents=True)
        request = requests / "REQ-global-journal-hold.md"
        request.write_text(
            """---
type: hapax-request
request_id: REQ-global-journal-hold
status: accepted_for_planning
planning_case: CASE-TEST-001
parent_spec: /specs/test.md
authority_level: authoritative
cctv_intake_receipt: receipt://REQ-global-journal-hold
cctv_intake_verdict: ready_to_plan
cctv_route_resource_admission: admitted
cctv_capability_receipts:
  - cctv-capability-admission:REQ-global-journal-hold
provider_spend_authorized: true
---

# Request
""",
            encoding="utf-8",
        )
        monkeypatch.setattr(script, "REQUESTS_DIR", requests)
        monkeypatch.setattr(script, "TASKS_DIR", task_root)

        def fail_if_called(_request_data):
            raise AssertionError("an unassociated invalid journal must block provider use")

        monkeypatch.setattr(script, "_decompose_with_llm", fail_if_called)
        blockers = script._decomposition_admission_blockers(script._read_request(request))
        assert any(
            blocker.startswith("unassociated_decomposition_journal_invalid:")
            for blocker in blockers
        )

        monkeypatch.setattr(sys, "argv", ["request-decompose", "--scan"])
        assert script.main() == 0
        holds = _decomposition_holds(task_root)
        assert {hold["failure_class"] for hold in holds} == {
            "admission_blocked",
            "journal_reconciliation_required",
        }

    def test_plan_lineage_must_match_admitted_request(self, tmp_path):
        plan, request_path, plan_path, _external_task = self._fixture(tmp_path)
        payload = plan.model_dump(mode="json", by_alias=True)
        payload["tasks"][0]["authority_case"] = "CASE-UNRELATED-999"
        mismatched = RequestDecompositionPlan.model_validate(payload)
        plan_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        plan_hash = hashlib.sha256(plan_path.read_bytes()).hexdigest()
        request_path.write_text(
            re.sub(
                r"(?m)^decomposition_plan_sha256: [0-9a-f]{64}$",
                f"decomposition_plan_sha256: {plan_hash}",
                request_path.read_text(encoding="utf-8"),
            ),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="authority case differs"):
            write_decomposition(mismatched, tmp_path / "tasks", dry_run=True)

    def test_symbolic_scope_plan_remains_nonmaterializable(self, tmp_path):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        payload = plan.model_dump(mode="json", by_alias=True)
        payload["tasks"][0]["scope_state"] = "withheld"
        payload["tasks"][0]["mutation_scope_refs"] = []
        payload["tasks"][0]["unresolveds"] = ["exact_scope_missing"]

        unresolved = RequestDecompositionPlan.model_validate(payload)
        assert unresolved.materializable is False

    @pytest.mark.parametrize(
        "stage",
        ("S0_INTAKE", "S1_INTAKE", "S1", "S1_RESEARCH", "S2_READY"),
    )
    def test_planned_initial_stage_must_be_canonical_s0(self, tmp_path, stage):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        payload = plan.model_dump(mode="json", by_alias=True)
        payload["tasks"][0]["initial_projection"]["stage"] = stage

        with pytest.raises(ValueError, match="S0"):
            RequestDecompositionPlan.model_validate(payload)

    def test_governance_protected_planned_scope_requires_frontier(self, tmp_path):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        payload = plan.model_dump(mode="json", by_alias=True)
        payload["tasks"][0]["mutation_scope_refs"] = ["shared/governance/policy.py"]
        payload["tasks"][0]["target_paths"] = ["shared/governance/policy.py"]
        payload["tasks"][0]["quality_floor"] = "frontier_review_required"

        with pytest.raises(ValueError, match="governance-protected planned source scope"):
            RequestDecompositionPlan.model_validate(payload)

    @pytest.mark.parametrize(
        "path",
        [
            "./shared/governance/policy.py",
            "x/../shared/governance/policy.py",
            "/shared/governance/policy.py",
            "shared\\governance\\policy.py",
            ".",
            "*",
        ],
    )
    def test_planned_source_paths_must_be_normalized_repo_relative(self, tmp_path, path: str):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        payload = plan.model_dump(mode="json", by_alias=True)
        payload["tasks"][0]["mutation_scope_refs"] = [path]
        payload["tasks"][0]["target_paths"] = [path]

        with pytest.raises(ValueError, match="normalized repo-relative paths"):
            RequestDecompositionPlan.model_validate(payload)

    def test_exact_planned_source_scope_requires_concrete_targets(self, tmp_path):
        plan, _request_path, _plan_path, _external_task = self._fixture(tmp_path)
        payload = plan.model_dump(mode="json", by_alias=True)
        payload["tasks"][0]["target_paths"] = []

        with pytest.raises(ValueError, match="requires concrete target_paths"):
            RequestDecompositionPlan.model_validate(payload)


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

    @staticmethod
    def _bind_request(decomposition: RequestDecomposition, request: Path) -> None:
        decomposition.request_path = str(request)
        decomposition.request_source_sha256 = hashlib.sha256(request.read_bytes()).hexdigest()

    def _write_bound(
        self,
        decomposition: RequestDecomposition,
        task_root: Path,
        *,
        dry_run: bool = False,
    ) -> list[Path]:
        task_root.mkdir(parents=True, exist_ok=True)
        request = task_root / "_test_request_source.md"
        if not request.exists():
            request.write_text(
                """---
type: hapax-request
request_id: test-writer-source
status: accepted_for_planning
---

# Test request source
""",
                encoding="utf-8",
            )
        self._bind_request(decomposition, request)
        return write_decomposition(decomposition, task_root, dry_run=dry_run)

    def test_writer_requires_existing_request_source(self, tmp_path):
        decomposition = self._make_decomp()
        decomposition.request_path = str(tmp_path / "missing-request.md")

        with pytest.raises(ValueError, match="existing request source file"):
            write_decomposition(decomposition, tmp_path / "tasks", dry_run=True)

        assert not (tmp_path / "tasks").exists()

    def test_writer_requires_exact_request_source_binding(self, tmp_path):
        request = tmp_path / "REQ-unbound.md"
        request.write_text(
            """---
type: hapax-request
request_id: REQ-unbound
status: accepted_for_planning
---

# Request
""",
            encoding="utf-8",
        )
        decomposition = self._make_decomp()
        decomposition.request_path = str(request)

        with pytest.raises(ValueError, match="exact request source binding"):
            write_decomposition(decomposition, tmp_path / "tasks", dry_run=True)

        assert not (tmp_path / "tasks").exists()

    def test_dry_run_returns_paths(self):
        with tempfile.TemporaryDirectory() as td:
            paths = self._write_bound(self._make_decomp(), Path(td), dry_run=True)
            assert len(paths) == 2
            assert not any(p.exists() for p in paths)

    def test_prepared_legacy_dry_run_reconciles_live_task_frontier(
        self,
        tmp_path,
        monkeypatch,
    ):
        task_root = tmp_path / "tasks"
        decomposition = self._make_decomp()
        request = tmp_path / "request.md"
        request.write_text("---\nrequest_id: test-write\nstatus: accepted_for_planning\n---\n")
        self._bind_request(decomposition, request)
        original_install = decomposition_writer._install_no_replace

        def interrupt_before_receipt(stage, final, expected_hash):
            if final.suffix == ".yaml":
                raise RuntimeError("simulated power cut")
            return original_install(stage, final, expected_hash)

        monkeypatch.setattr(decomposition_writer, "_install_no_replace", interrupt_before_receipt)
        with pytest.raises(RuntimeError, match="simulated power cut"):
            write_decomposition(decomposition, task_root)
        monkeypatch.setattr(decomposition_writer, "_install_no_replace", original_install)
        unrelated = task_root / "active" / "unrelated-after-prepare.md"
        unrelated.write_text(
            "---\ntype: cc-task\ntask_id: unrelated-after-prepare\nstatus: blocked\n---\n"
        )

        with pytest.raises(RuntimeError, match="residual_content_frontier_mismatch"):
            write_decomposition(decomposition, task_root, dry_run=True)

    def test_legacy_commit_identity_changes_at_s0_genesis_boundary(self):
        decomposition = self._make_decomp()
        request_preimage = b"historical request bytes\n"
        decomposition.request_source_sha256 = hashlib.sha256(request_preimage).hexdigest()
        historical_v1 = decomposition_writer._canonical_hash(
            {
                "schema": "hapax.request-decomposition-commit.v1",
                "request_id": decomposition.request_id,
                "request_path": decomposition.request_path,
                "request_sha256": decomposition.request_source_sha256,
                "task_ids": [task.task_id for task in decomposition.tasks],
                "model": decomposition.decomposition_model,
            }
        )

        current_v2 = decomposition_writer._legacy_commit_id(
            decomposition,
            request_preimage,
        )

        assert current_v2 != historical_v1

    def test_real_write_creates_files(self):
        with tempfile.TemporaryDirectory() as td:
            paths = self._write_bound(self._make_decomp(), Path(td))
            assert len(paths) == 2
            assert all(p.exists() for p in paths)
            for p in paths:
                content = p.read_text()
                assert "type: cc-task" in content
                assert "stage: S0" in content
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
            paths = self._write_bound(decomp, Path(td))
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

            [path] = self._write_bound(decomp, Path(td))
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

            [path] = self._write_bound(decomp, Path(td))
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

            paths = self._write_bound(decomp, Path(td))
            phase2 = [p for p in paths if "phase2" in p.name][0]

            frontmatter, _body = parse_frontmatter(phase2.read_text(encoding="utf-8"))
            assert frontmatter["blocked_reason"] == "Depends on: write-phase1"

    def test_blocks_computed(self):
        with tempfile.TemporaryDirectory() as td:
            paths = self._write_bound(self._make_decomp(), Path(td))
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
                    route_envelope=_route_envelope(),
                ),
            ],
        )
        with tempfile.TemporaryDirectory() as td:
            [path] = self._write_bound(decomp, Path(td))

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
                    route_envelope=_route_envelope(),
                ),
            ],
        )
        with tempfile.TemporaryDirectory() as td:
            [path] = self._write_bound(decomp, Path(td))

            fields, _body = parse_frontmatter(path)
            assessment = assess_route_metadata(fields)

        assert assessment.status != RouteMetadataStatus.MALFORMED
        assert assessment.dispatchable
        assert assessment.metadata is not None
        assert assessment.metadata.review_requirement.support_artifact_allowed is True

    def test_exact_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            first = self._write_bound(self._make_decomp(), Path(td))
            assert self._write_bound(self._make_decomp(), Path(td)) == first

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
            self._bind_request(decomp, request)

            with pytest.raises(FileExistsError, match="already has downstream_tasks"):
                write_decomposition(decomp, root / "tasks")

            assert not list((root / "tasks" / "active").glob("*.md"))

    def test_real_write_preserves_parent_request_and_links_through_receipt(self):
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
            self._bind_request(decomp, request)
            request_before = request.read_bytes()

            paths = write_decomposition(decomp, root / "tasks")

            assert request.read_bytes() == request_before
            task_fields, _body = parse_frontmatter(paths[0])
            receipt = Path(task_fields["decomposition_commit_receipt"])
            assert receipt.is_file()
            receipt_payload = yaml.safe_load(receipt.read_bytes())
            assert [Path(item["path"]).name for item in receipt_payload["tasks"]] == [
                "write-phase1.md",
                "write-phase2.md",
            ]

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
            self._bind_request(decomp, request)

            write_decomposition(decomp, root / "tasks", dry_run=True)

            assert request.read_text(encoding="utf-8") == original


class TestRequestDecomposeScan:
    def _admitted_cctv_frontmatter(self, receipt: str = "receipt://REQ-test") -> dict[str, object]:
        return {
            "cctv_intake_receipt": receipt,
            "cctv_intake_verdict": "ready_to_plan",
            "cctv_route_resource_admission": "admitted",
            "cctv_capability_receipts": ["cctv-capability-admission:test-member"],
            "provider_spend_authorized": True,
        }

    def _request_data(self, tmp_path: Path, frontmatter: dict[str, object]) -> dict[str, object]:
        request_path = tmp_path / "REQ-test.md"
        return {
            "path": str(request_path),
            "filename": request_path.name,
            "frontmatter": {"authority_level": "authoritative", **frontmatter},
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
                **self._admitted_cctv_frontmatter(),
                "planning_case": "CASE-TEST-001",
            },
        )

        assert script._decomposition_admission_blockers(request_data) == []

    def test_decomposition_admission_blocks_non_planning_status(self, tmp_path):
        script = _load_request_decompose_module()
        request_data = self._request_data(
            tmp_path,
            {
                "status": "rejected",
                **self._admitted_cctv_frontmatter(),
                "planning_case": "CASE-TEST-001",
            },
        )

        assert "request_status_not_accepted_for_planning:rejected" in (
            script._decomposition_admission_blockers(request_data)
        )

    def test_unbound_decomposition_is_bound_to_bytes_read_before_provider(
        self,
        tmp_path,
        monkeypatch,
    ):
        script = _load_request_decompose_module()
        request = tmp_path / "REQ-source-bound.md"
        request.write_text(
            """---
type: hapax-request
request_id: REQ-source-bound
status: accepted_for_planning
---

# Original request
""",
            encoding="utf-8",
        )
        request_data = script._read_request(request)
        expected_sha256 = hashlib.sha256(request.read_bytes()).hexdigest()

        def fake_decompose(_request_data):
            return RequestDecomposition(
                request_id="REQ-source-bound",
                request_path=str(request),
                tasks=[
                    TaskSpec(
                        task_id="source-bound-task",
                        title="Source-bound task",
                        parent_request=request.name,
                        authority_case="CASE-TEST-001",
                        acceptance_criteria=["Done"],
                    )
                ],
            )

        monkeypatch.setattr(script, "_decompose_with_llm", fake_decompose)
        decomposition = script._decompose_request(request_data)
        assert decomposition is not None
        assert decomposition.request_source_sha256 == expected_sha256

        request.write_text(
            request.read_text(encoding="utf-8") + "\n# Changed after provider derivation\n",
            encoding="utf-8",
        )
        task_root = tmp_path / "tasks"
        with pytest.raises(FileExistsError, match="request source changed after decomposition"):
            write_decomposition(decomposition, task_root)
        assert not task_root.exists()

    @pytest.mark.parametrize("provider_spend", [False, None])
    def test_decomposition_admission_blocks_unbound_provider_without_spend_authority(
        self,
        tmp_path,
        provider_spend: bool | None,
    ):
        script = _load_request_decompose_module()
        frontmatter = {
            "status": "accepted_for_planning",
            **self._admitted_cctv_frontmatter(),
            "planning_case": "CASE-TEST-001",
        }
        if provider_spend is None:
            frontmatter.pop("provider_spend_authorized")
        else:
            frontmatter["provider_spend_authorized"] = provider_spend
        request_data = self._request_data(tmp_path, frontmatter)

        assert "provider_spend_not_authorized" in (
            script._decomposition_admission_blockers(request_data)
        )

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

    def test_decomposition_admission_blocks_missing_route_resource_state(self, tmp_path):
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

        assert "missing_cctv_route_resource_admission" in (
            script._decomposition_admission_blockers(request_data)
        )

    @pytest.mark.parametrize("route_state", ["refused", "partial_admitted"])
    def test_decomposition_admission_blocks_non_admitted_route_resource_state(
        self, tmp_path, route_state: str
    ):
        script = _load_request_decompose_module()
        request_data = self._request_data(
            tmp_path,
            {
                "status": "accepted_for_planning",
                **self._admitted_cctv_frontmatter(),
                "cctv_route_resource_admission": route_state,
                "planning_case": "CASE-TEST-001",
            },
        )

        assert f"cctv_route_resource_not_admitted:{route_state}" in (
            script._decomposition_admission_blockers(request_data)
        )

    @pytest.mark.parametrize(
        "empty_receipts",
        [[], "[]", '"[]"', "[null]", "[unassigned]", "['null']", '["unassigned"]'],
    )
    def test_decomposition_admission_blocks_admitted_route_without_receipts(
        self, tmp_path, empty_receipts: object
    ):
        script = _load_request_decompose_module()
        request_data = self._request_data(
            tmp_path,
            {
                "status": "accepted_for_planning",
                **self._admitted_cctv_frontmatter(),
                "cctv_capability_receipts": empty_receipts,
                "planning_case": "CASE-TEST-001",
            },
        )

        assert "missing_cctv_capability_receipts" in (
            script._decomposition_admission_blockers(request_data)
        )

    def test_decomposition_admission_blocks_missing_authority_case(self, tmp_path):
        script = _load_request_decompose_module()
        request_data = self._request_data(
            tmp_path,
            {
                "status": "accepted_for_planning",
                **self._admitted_cctv_frontmatter(),
            },
        )

        assert "missing_authority_case" in script._decomposition_admission_blockers(request_data)

    def test_decomposition_admission_blocks_missing_authority_level(self, tmp_path):
        script = _load_request_decompose_module()
        request_data = self._request_data(
            tmp_path,
            {
                "status": "accepted_for_planning",
                **self._admitted_cctv_frontmatter(),
                "planning_case": "CASE-TEST-001",
                "authority_level": "",
            },
        )

        assert "missing_authority_level" in script._decomposition_admission_blockers(request_data)

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
authority_level: authoritative
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
        assert "governed non-dry intake transition" in caplog.text
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
authority_level: authoritative
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

    def test_admitted_unbound_dry_run_is_provider_free_and_zero_write(
        self,
        tmp_path,
        monkeypatch,
    ):
        script = _load_request_decompose_module()
        tasks = tmp_path / "tasks"
        request = tmp_path / "REQ-provider-free.md"
        request.write_text(
            """---
type: hapax-request
request_id: REQ-provider-free
status: accepted_for_planning
planning_case: CASE-TEST-001
parent_spec: /specs/test.md
authority_level: authoritative
cctv_intake_receipt: receipt://REQ-provider-free
cctv_intake_verdict: ready_to_plan
cctv_route_resource_admission: admitted
cctv_capability_receipts:
  - cctv-capability-admission:REQ-provider-free
provider_spend_authorized: true
---

# Request
""",
            encoding="utf-8",
        )

        def fail_if_called(_request_data):
            raise AssertionError("dry-run must not call a provider")

        monkeypatch.setattr(script, "TASKS_DIR", tasks)
        monkeypatch.setattr(script, "_decompose_with_llm", fail_if_called)
        monkeypatch.setattr(sys, "argv", ["request-decompose", str(request), "--dry-run"])

        assert script.main() == 1
        assert not tasks.exists()

    def test_unbound_provider_spend_refuses_before_llm(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        tasks = tmp_path / "tasks"
        (tasks / "active").mkdir(parents=True)
        (tasks / "closed").mkdir(parents=True)
        request = tmp_path / "REQ-no-spend.md"
        request.write_text(
            """---
type: hapax-request
request_id: REQ-no-spend
status: accepted_for_planning
planning_case: CASE-TEST-001
parent_spec: /specs/test.md
authority_level: authoritative
cctv_intake_receipt: receipt://REQ-no-spend
cctv_intake_verdict: ready_to_plan
cctv_route_resource_admission: admitted
cctv_capability_receipts:
  - cctv-capability-admission:REQ-no-spend
provider_spend_authorized: false
---

# Request
""",
            encoding="utf-8",
        )

        def fail_if_called(_request_data):
            raise AssertionError("LLM must not run without provider-spend authority")

        monkeypatch.setattr(script, "TASKS_DIR", tasks)
        monkeypatch.setattr(script, "_decompose_with_llm", fail_if_called)
        monkeypatch.setattr(sys, "argv", ["request-decompose", str(request)])

        assert script.main() == 1
        [hold] = _decomposition_holds(tasks)
        assert "provider_spend_not_authorized" in hold["reason_codes"]
        assert not list((tasks / "active").glob("*.md"))

    def test_hold_parent_symlink_escape_is_rejected(self, tmp_path, monkeypatch):
        script = _load_request_decompose_module()
        tasks = tmp_path / "tasks"
        outside = tmp_path / "outside"
        tasks.mkdir()
        outside.mkdir()
        (tasks / "_decomposition_holds").symlink_to(outside, target_is_directory=True)
        request = tmp_path / "REQ-hold-escape.md"
        request.write_text(
            """---
type: hapax-request
request_id: REQ-hold-escape
status: accepted_for_planning
---

# Request
""",
            encoding="utf-8",
        )
        request_data = script._read_request(request)
        monkeypatch.setattr(script, "TASKS_DIR", tasks)

        with pytest.raises(ValueError, match="HOLD directory escapes task root"):
            script._record_decomposition_remediation(
                request_data,
                "admission_blocked",
                ["test_hold"],
                dry_run=False,
            )

        assert list(outside.iterdir()) == []

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
authority_level: authoritative
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
authority_level: authoritative
cctv_intake_receipt: receipt://REQ-002-admitted
cctv_intake_verdict: ready_to_plan
cctv_route_resource_admission: admitted
cctv_capability_receipts:
  - cctv-capability-admission:REQ-002-admitted
provider_spend_authorized: true
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
authority_level: authoritative
cctv_intake_receipt: receipt://REQ-003-admitted
cctv_intake_verdict: ready_to_plan
cctv_route_resource_admission: admitted
cctv_capability_receipts:
  - cctv-capability-admission:REQ-003-admitted
provider_spend_authorized: true
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
        [hold] = _decomposition_holds(tasks)
        assert hold["request_id"] == "REQ-001-blocked"
        assert hold["may_authorize"] is False

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
authority_level: authoritative
cctv_intake_receipt: receipt://REQ-001-admitted
cctv_intake_verdict: ready_to_plan
cctv_route_resource_admission: admitted
cctv_capability_receipts:
  - cctv-capability-admission:REQ-001-admitted
provider_spend_authorized: true
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
authority_level: authoritative
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
authority_level: authoritative
cctv_intake_receipt: receipt://REQ-003-admitted
cctv_intake_verdict: ready_to_plan
cctv_route_resource_admission: admitted
cctv_capability_receipts:
  - cctv-capability-admission:REQ-003-admitted
provider_spend_authorized: true
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
        [hold] = _decomposition_holds(tasks)
        assert hold["request_id"] == "REQ-002-blocked"

    def test_scan_writes_idempotent_non_authorizing_admission_hold(self, tmp_path, monkeypatch):
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
authority_level: authoritative
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

        hold_paths = list((tasks / "_decomposition_holds").glob("*.yaml"))
        assert len(hold_paths) == 1
        original_bytes = hold_paths[0].read_bytes()

        assert script.main() == 0
        assert hold_paths[0].read_bytes() == original_bytes

        [hold] = _decomposition_holds(tasks)
        assert hold["schema"] == "hapax.request-decomposition-hold.v1"
        assert hold["state"] == "hold"
        assert hold["claimable"] is False
        assert hold["authority_level"] == "support_non_authoritative"
        for field in (
            "may_authorize",
            "implementation_authorized",
            "source_mutation_authorized",
            "docs_mutation_authorized",
            "runtime_mutation_authorized",
            "release_authorized",
            "public_mutation_authorized",
            "provider_spend_authorized",
        ):
            assert hold[field] is False
        assert hold["request_id"] == "REQ-blocked"
        assert hold["failure_class"] == "admission_blocked"
        assert "missing_cctv_intake_receipt" in hold["reason_codes"]
        assert not list((tasks / "active").glob("request-decompose-*.md"))
        assert script._find_undecomposed_requests() == [request]

    def test_hold_cannot_receive_authority_from_legacy_environment(self, tmp_path, monkeypatch):
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
authority_level: authoritative
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

        [hold] = _decomposition_holds(tasks)
        assert hold["authority_level"] == "support_non_authoritative"
        assert hold["may_authorize"] is False
        assert "authority_case" not in hold
        assert "parent_spec" not in hold

    def test_missing_hold_is_rehydrated_without_creating_a_task(self, tmp_path, monkeypatch):
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
authority_level: authoritative
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
        [hold_path] = list((tasks / "_decomposition_holds").glob("*.yaml"))
        hold_path.unlink()

        assert script.main() == 0

        assert hold_path.exists()
        assert not list((tasks / "active").glob("request-decompose-*.md"))

    def test_tampered_hold_is_refused_instead_of_reopened(self, tmp_path, monkeypatch):
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
authority_level: authoritative
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
        [hold_path] = list((tasks / "_decomposition_holds").glob("*.yaml"))
        hold_path.write_text(hold_path.read_text(encoding="utf-8") + "tampered: true\n")

        with pytest.raises(FileExistsError, match="HOLD identity collision"):
            script.main()
        assert not list((tasks / "active").glob("request-decompose-*.md"))

    def test_scan_writes_non_authorizing_llm_failure_hold(self, tmp_path, monkeypatch):
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
authority_level: authoritative
cctv_intake_receipt: receipt://REQ-llm
cctv_intake_verdict: ready_to_plan
cctv_route_resource_admission: admitted
cctv_capability_receipts:
  - cctv-capability-admission:REQ-llm
provider_spend_authorized: true
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

        [hold] = _decomposition_holds(tasks)
        assert hold["failure_class"] == "llm_failed"
        assert hold["implementation_authorized"] is False
        assert hold["source_mutation_authorized"] is False
        assert hold["docs_mutation_authorized"] is False
        assert hold["runtime_mutation_authorized"] is False
        assert hold["request_id"] == "REQ-llm"

    def test_scan_writes_non_authorizing_write_conflict_hold(self, tmp_path, monkeypatch):
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
authority_level: authoritative
cctv_intake_receipt: receipt://REQ-conflict
cctv_intake_verdict: ready_to_plan
cctv_route_resource_admission: admitted
cctv_capability_receipts:
  - cctv-capability-admission:REQ-conflict
provider_spend_authorized: true
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

        def fail_write(_decomp, _tasks_dir, **_kwargs):
            raise decomposition_writer.TaskStoreError(
                "task_identity_write_identity_exists",
                "do not create an existing identity",
                "conflicting-task",
            )

        monkeypatch.setattr(script, "REQUESTS_DIR", requests)
        monkeypatch.setattr(script, "TASKS_DIR", tasks)
        monkeypatch.setattr(script, "_decompose_with_llm", fake_decompose)
        monkeypatch.setattr(script, "write_decomposition", fail_write)
        monkeypatch.setattr(sys, "argv", ["request-decompose", "--scan"])

        assert script.main() == 0

        [hold] = _decomposition_holds(tasks)
        assert hold["failure_class"] == "write_conflict"
        assert hold["implementation_authorized"] is False
        assert hold["source_mutation_authorized"] is False
        assert hold["docs_mutation_authorized"] is False
        assert hold["runtime_mutation_authorized"] is False
        assert hold["request_id"] == "REQ-conflict"
        assert any(
            str(reason).startswith("task_write_conflict:") for reason in hold["reason_codes"]
        )
        monkeypatch.setattr(sys, "argv", ["request-decompose", "--scan", "--dry-run"])
        assert script.main() == 0
        assert len(_decomposition_holds(tasks)) == 1

    def test_single_request_writes_admission_hold_not_task(self, tmp_path, monkeypatch):
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
authority_level: authoritative
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

        [hold] = _decomposition_holds(tasks)
        assert hold["request_id"] == "REQ-single-blocked"
        assert hold["failure_class"] == "admission_blocked"
        assert not list((tasks / "active").glob("request-decompose-*.md"))

    def test_single_request_writes_llm_failure_hold_not_task(self, tmp_path, monkeypatch):
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
authority_level: authoritative
cctv_intake_receipt: receipt://REQ-single-llm
cctv_intake_verdict: ready_to_plan
cctv_route_resource_admission: admitted
cctv_capability_receipts:
  - cctv-capability-admission:REQ-single-llm
provider_spend_authorized: true
---

# Request
""",
            encoding="utf-8",
        )

        monkeypatch.setattr(script, "TASKS_DIR", tasks)
        monkeypatch.setattr(script, "_decompose_with_llm", lambda _request_data: None)
        monkeypatch.setattr(sys, "argv", ["request-decompose", str(request)])

        assert script.main() == 1

        [hold] = _decomposition_holds(tasks)
        assert hold["request_id"] == "REQ-single-llm"
        assert hold["failure_class"] == "llm_failed"

    def test_single_request_writes_write_conflict_hold_not_task(self, tmp_path, monkeypatch):
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
authority_level: authoritative
cctv_intake_receipt: receipt://REQ-single-conflict
cctv_intake_verdict: ready_to_plan
cctv_route_resource_admission: admitted
cctv_capability_receipts:
  - cctv-capability-admission:REQ-single-conflict
provider_spend_authorized: true
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

        [hold] = _decomposition_holds(tasks)
        assert hold["request_id"] == "REQ-single-conflict"
        assert hold["failure_class"] == "write_conflict"
        assert not list((tasks / "active").glob("request-decompose-write-conflict-*.md"))

    def test_known_task_ids_use_parsed_identity_and_include_refused(
        self,
        tmp_path,
        monkeypatch,
    ):
        script = _load_request_decompose_module()
        tasks = tmp_path / "tasks"
        active = tasks / "active" / "filename-is-not-identity.md"
        refused = tasks / "refused" / "refused-descriptor.md"
        active.parent.mkdir(parents=True)
        refused.parent.mkdir(parents=True)
        active.write_text(
            "---\ntype: cc-task\ntask_id: parsed-active\nstatus: blocked\n---\n",
            encoding="utf-8",
        )
        refused.write_text(
            "---\ntype: cc-task\ntask_id: parsed-refused\nstatus: refused\n---\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(script, "TASKS_DIR", tasks)

        assert script._known_task_ids() == {"parsed-active", "parsed-refused"}

    def test_refused_task_parent_reference_closes_request_loop(
        self,
        tmp_path,
        monkeypatch,
    ):
        script = _load_request_decompose_module()
        requests = tmp_path / "requests" / "active"
        tasks = tmp_path / "tasks"
        requests.mkdir(parents=True)
        refused = tasks / "refused" / "refused-task.md"
        refused.parent.mkdir(parents=True)
        request = requests / "REQ-refused-parent.md"
        request.write_text(
            "---\nrequest_id: REQ-refused-parent\nstatus: accepted_for_planning\n---\n",
            encoding="utf-8",
        )
        refused.write_text(
            "---\ntype: cc-task\ntask_id: refused-task\nstatus: refused\n"
            "parent_request: REQ-refused-parent.md\n---\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(script, "REQUESTS_DIR", requests)
        monkeypatch.setattr(script, "TASKS_DIR", tasks)

        assert script._find_undecomposed_requests() == []
