"""Unit tests for the SDLC lifecycle vocabulary SSOT (shared/sdlc_lifecycle.py).

Pins the three coordination-plane vocabularies so the gate, dispatch, and
autoqueue provably consume ONE source: the status frozensets, the named
dispatch-plane PR-action vocabulary, and the dispatchable-status set. This is
the additive, behavior-preserving slice of bb-status-ssot — the canonical
status->stage projection is intentionally NOT shipped here (a pre-flight over
the live vault showed status->stage is not a function; see
~/Documents/Personal/30-areas/hapax/bb-status-ssot-preflight-stop-2026-06-02.md).
"""

from __future__ import annotations

import ast
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest

from shared.sdlc_lifecycle import (
    PR_ACTIONS,
    SDLC_STAGE_METADATA,
    SDLC_STAGE_METADATA_PATH,
    STAGE_RE,
    TASK_CLAIMABLE_STATUSES,
    TASK_DISPATCHABLE_STATUSES,
    StageMetadataError,
    acceptance_receipt_blockers,
    acceptance_receipt_path,
    active_blocked_task_blockers,
    frontmatter_from_text,
    is_active_blocked_with_evidence,
    is_dependency_blocked_reason,
    is_legal_stage_edge,
    load_sdlc_stage_metadata,
    requires_acceptance_receipt,
    stage_edges,
    stage_token,
    task_closure_validity,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_STAGE_ALIASES = {
    "S0": "S0",
    "S0_INTAKE": "S0",
    "S1": "S1",
    "S1_RESEARCH": "S1",
    "S2": "S2",
    "S2_DESIGN": "S2",
    "S3": "S3",
    "S3_REVIEW": "S3",
    "S3_5": "S3_5",
    "S3.5": "S3_5",
    "S4": "S4",
    "S4_ACCEPTANCE": "S4",
    "S5": "S5",
    "S5_IMPLEMENTATION_AUTHORIZATION": "S5",
    "S6": "S6",
    "S6_IMPLEMENTATION": "S6",
    "S7": "S7",
    "S7_RUNTIME_VERIFICATION": "S7",
    "S7_RELEASE": "S7",
    "S8": "S8",
    "S8_RELEASE": "S8",
    "S9": "S9",
    "S9_POST_MERGE": "S9",
    "S10": "S10",
    "S10_CLOSURE": "S10",
    "S11": "S11",
    "S11_CLOSED": "S11",
    "BLOCKED": "BLOCKED",
}


class TestPrActions:
    def test_pr_actions_names_the_seven_dispatch_plane_actions(self) -> None:
        assert (
            frozenset(
                {
                    "queue",
                    "enable_auto_merge",
                    "disable_auto_merge",
                    "dequeue",
                    "already_queued",
                    "already_auto_merge_enabled",
                    "blocked",
                }
            )
            == PR_ACTIONS
        )

    def test_classify_pr_emits_only_pr_actions(self) -> None:
        """Totality: every action string classify_pr can emit is in PR_ACTIONS.

        Source-introspection (no import of the heavy autoqueue module): parse the
        ``classify_pr`` function body for ``action=<literal>`` and assert the set
        is covered. A new action added without updating PR_ACTIONS fails here.
        """

        src = (REPO_ROOT / "scripts" / "cc-pr-autoqueue.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        classify = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == "classify_pr"
            ),
            None,
        )
        assert classify is not None, "classify_pr not found (autoqueue source drift)"
        emitted = {
            kw.value.value
            for sub in ast.walk(classify)
            if isinstance(sub, ast.Call)
            for kw in sub.keywords
            if kw.arg == "action"
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, str)
        }
        assert emitted, "no action= literals found in classify_pr (parser drift)"
        assert emitted <= PR_ACTIONS, (
            f"classify_pr emits actions outside PR_ACTIONS: {emitted - PR_ACTIONS}"
        )


class TestTaskDispatchableStatuses:
    def test_dispatchable_statuses_is_offered_claimed_in_progress(self) -> None:
        assert frozenset({"offered", "claimed", "in_progress"}) == TASK_DISPATCHABLE_STATUSES

    def test_dispatchable_statuses_derives_from_claimable_plus_active_work(self) -> None:
        # The dispatch admit-set is exactly the claimable set plus the two
        # actively-owned working states — the identity hapax-methodology-dispatch
        # used to hardcode at the dispatchability check.
        assert TASK_CLAIMABLE_STATUSES | {"claimed", "in_progress"} == TASK_DISPATCHABLE_STATUSES

    def test_dispatch_consumes_the_ssot_not_a_hardcoded_literal(self) -> None:
        """Pin the de-hardcode: hapax-methodology-dispatch references the SSOT set
        and no longer carries the literal {"offered","claimed","in_progress"}."""

        src = (REPO_ROOT / "scripts" / "hapax-methodology-dispatch").read_text(encoding="utf-8")
        assert "TASK_DISPATCHABLE_STATUSES" in src, "dispatch must reference the SSOT set"
        set_literals = [
            frozenset(
                el.value
                for el in node.elts
                if isinstance(el, ast.Constant) and isinstance(el.value, str)
            )
            for node in ast.walk(ast.parse(src))
            if isinstance(node, ast.Set)
        ]
        assert frozenset({"offered", "claimed", "in_progress"}) not in set_literals, (
            "dispatch still hardcodes the dispatchable-status set literal"
        )


class TestBlockedEvidenceLifecycle:
    def test_blocked_with_evidence_has_precise_dependency_blockers(self) -> None:
        text = """---
status: blocked
blocked_reason: minio_mirror_still_d_state
blocked_witness: ~/.cache/hapax/witness/minio-d-state.json
---

# blocked
"""

        validity = task_closure_validity(text)

        assert validity.valid is False
        assert validity.blockers == (
            "blocked_reason:minio_mirror_still_d_state",
            "blocked_witness:~/.cache/hapax/witness/minio-d-state.json",
        )

    def test_blocked_evidence_requires_non_dependency_reason_and_witness(self) -> None:
        evidence = frontmatter_from_text(
            """---
status: blocked
blocked_reason: minio_mirror_still_d_state
blocked_witness: ~/.cache/hapax/witness/minio-d-state.json
---
"""
        )
        dependency_wait = frontmatter_from_text(
            """---
status: blocked
blocked_reason: 'waiting_for_closure_valid_dependencies: dep (pr_open:123)'
blocked_witness: ~/.cache/hapax/witness/dependency.json
---
"""
        )
        no_witness = frontmatter_from_text(
            """---
status: blocked
blocked_reason: minio_mirror_still_d_state
---
"""
        )

        assert is_active_blocked_with_evidence(evidence) is True
        assert active_blocked_task_blockers(evidence) == (
            "blocked_reason:minio_mirror_still_d_state",
            "blocked_witness:~/.cache/hapax/witness/minio-d-state.json",
        )
        assert is_dependency_blocked_reason(
            "waiting_for_closure_valid_dependencies: dep (pr_open:123)"
        )
        assert is_active_blocked_with_evidence(dependency_wait) is False
        assert is_active_blocked_with_evidence(no_witness) is False

    def test_malformed_frontmatter_is_non_fulfilling_not_exception(self) -> None:
        text = """---
status: blocked
blocked_reason: waiting_for_closure_valid_dependencies: dep (pr_open:123)
---

# malformed
"""

        validity = task_closure_validity(text)

        assert validity.valid is False
        assert "status_not_fulfilling:missing" in validity.blockers


class TestStageVocabulary:
    def test_stage_token_normalizes_labeled_and_branch_stages(self) -> None:
        assert stage_token("S6_IMPLEMENTATION") == "S6"
        assert stage_token("S7_RELEASE") == "S7"
        assert stage_token("S0_INTAKE") == "S0"
        assert stage_token("S3.5") == "S3_5"
        assert stage_token("S3_5") == "S3_5"
        assert stage_token("S11") == "S11"
        assert stage_token("BLOCKED") == "BLOCKED"

    def test_stage_catalog_has_exact_ordered_token_set(self) -> None:
        assert SDLC_STAGE_METADATA.tokens == (
            "S0",
            "S1",
            "S2",
            "S3",
            "S3_5",
            "S4",
            "S5",
            "S6",
            "S7",
            "S8",
            "S9",
            "S10",
            "S11",
            "BLOCKED",
        )

    def test_stage_catalog_has_exact_alias_contract(self) -> None:
        assert dict(SDLC_STAGE_METADATA.alias_to_token) == EXPECTED_STAGE_ALIASES
        assert SDLC_STAGE_METADATA.by_token["S7"].deprecated_aliases == ("S7_RELEASE",)

    def test_stage_catalog_carries_ratified_guard_and_deliverable_contract(self) -> None:
        s6 = SDLC_STAGE_METADATA.by_token["S6"]
        assert len(s6.operation_admissions) == 1
        mutation = s6.operation_admissions[0]
        assert mutation.operation == "source_mutation"
        assert mutation.authority_capability == "system.mutation.admit"
        assert mutation.guards == (
            "stage_at_least_s6",
            "implementation_authorized",
            "source_mutation_authorized",
            "mutation_in_mutation_scope_refs",
        )
        assert mutation.actions == ("admit_scoped_mutation",)
        assert mutation.enforcement == "enforced"
        assert mutation.enforcement_ref == "hooks/scripts/cc-task-gate.impl.sh"
        assert all(
            stage.operation_admissions == (mutation,)
            for stage in SDLC_STAGE_METADATA.stages
            if stage.token in {"S6", "S7", "S8", "S9", "S10"}
        )
        assert all(
            not stage.operation_admissions
            for stage in SDLC_STAGE_METADATA.stages
            if stage.token not in {"S6", "S7", "S8", "S9", "S10"}
        )

        s9_to_s10 = SDLC_STAGE_METADATA.by_token["S9"].next_edges[0]
        assert "acceptance_receipt_valid" in s9_to_s10.guards
        projection_roles = {
            (stage.token, edge.to): edge.projection_role
            for stage in SDLC_STAGE_METADATA.stages
            for edge in stage.next_edges
        }
        assert projection_roles[("S3", "S3_5")] == "branch"
        assert projection_roles[("S3_5", "S0")] == "repair"
        assert projection_roles[("BLOCKED", "S6")] == "repair"
        assert projection_roles[("S8", "S9")] == "advance"
        assert all(
            edge.projection_role == "repair"
            for stage in SDLC_STAGE_METADATA.stages
            for edge in stage.fall_edges
        )
        assert SDLC_STAGE_METADATA.by_token["BLOCKED"].deliverable.required_fields == (
            "blocked_reason",
            "blocked_witness",
            "relay_receipt",
        )

    @pytest.mark.parametrize(
        ("raw", "reason"),
        [
            ("", "stage_blank"),
            ("s6", "stage_case_drift"),
            ("S6_implementation", "stage_case_drift"),
            ("S1_INTAKE", "stage_alias_unknown"),
            ("S6_UNKNOWN", "stage_alias_unknown"),
            ("S12", "stage_alias_unknown"),
            (" S6 ", "stage_whitespace_drift"),
        ],
    )
    def test_stage_resolution_refuses_undeclared_or_drifted_aliases(
        self, raw: str, reason: str
    ) -> None:
        with pytest.raises(StageMetadataError) as caught:
            stage_token(raw)
        assert caught.value.reason_code == reason
        assert caught.value.repair_action

    def test_legal_edges_keep_next_and_fall_distinct(self) -> None:
        assert is_legal_stage_edge("S3", "S3_5", edge_class="next")
        assert is_legal_stage_edge("S3_5", "S0", edge_class="next")
        assert is_legal_stage_edge("BLOCKED", "S6", edge_class="next")
        assert is_legal_stage_edge("BLOCKED", "S0", edge_class="next")
        assert not is_legal_stage_edge("S0", "S11")
        assert not is_legal_stage_edge("S0", "BLOCKED", edge_class="next")
        assert is_legal_stage_edge("S0", "BLOCKED", edge_class="fall")
        assert is_legal_stage_edge("S6", "BLOCKED", edge_class="next")
        assert is_legal_stage_edge("S6", "BLOCKED", edge_class="fall")
        assert is_legal_stage_edge("S7", "BLOCKED", edge_class="next")
        assert is_legal_stage_edge("S7", "BLOCKED", edge_class="fall")
        assert stage_edges("S6") == frozenset({"S7", "BLOCKED"})
        assert stage_edges("S6", include_fall=True) == frozenset({"S7", "BLOCKED"})
        assert not is_legal_stage_edge("S11", "BLOCKED", edge_class="fall")
        assert not is_legal_stage_edge("BLOCKED", "BLOCKED", edge_class="fall")

    def test_invalid_edge_class_is_a_programmer_error(self) -> None:
        with pytest.raises(ValueError, match="edge_class must be"):
            is_legal_stage_edge("S0", "S1", edge_class="skip")

    def test_default_metadata_path_is_cwd_independent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert load_sdlc_stage_metadata().tokens == SDLC_STAGE_METADATA.tokens

    def test_loaded_metadata_indexes_are_immutable(self) -> None:
        with pytest.raises(TypeError):
            SDLC_STAGE_METADATA.by_token["S0"] = SDLC_STAGE_METADATA.by_token["S1"]  # type: ignore[index]
        with pytest.raises(TypeError):
            SDLC_STAGE_METADATA.alias_to_token["S0_FAKE"] = "S0"  # type: ignore[index]

    @pytest.mark.parametrize(
        ("mutation", "reason"),
        [
            (
                lambda text: text.replace(
                    "schema: hapax.sdlc-stage-metadata.v2\n",
                    "schema: hapax.sdlc-stage-metadata.v2\nschema: duplicate\n",
                    1,
                ),
                "stage_metadata_duplicate_yaml_key",
            ),
            (
                lambda text: text.replace("  - token: S5\n", "  - token: S4\n", 1),
                "stage_metadata_duplicate_token",
            ),
            (
                lambda text: text.replace("      - to: S11\n", "      - to: S12\n", 1),
                "stage_metadata_unknown_edge_target",
            ),
            (
                lambda text: text.replace(
                    "        guards: [gate_refused]\n", "        guards: invalid\n", 1
                ),
                "stage_metadata_invalid_field",
            ),
            (
                lambda text: text.replace(
                    "guards: [cc_task_shape_valid, parent_spec_present, authority_case_present]",
                    "guards: []",
                    1,
                ),
                "stage_metadata_semantic_field_empty",
            ),
            (
                lambda text: text.replace("    operation_admissions: []\n", "", 1),
                "stage_metadata_missing_field",
            ),
            (
                lambda text: text.replace(
                    "        enforcement_ref: hooks/scripts/cc-task-gate.impl.sh\n",
                    "",
                    1,
                ),
                "stage_metadata_enforcement_witness_missing",
            ),
            (
                lambda text: text.replace(
                    "actions: [append_stage_transition, begin_research]",
                    "actions: []",
                    1,
                ),
                "stage_metadata_semantic_field_empty",
            ),
            (
                lambda text: text.replace(
                    "required_fields: [task_id, parent_spec, authority_case]",
                    "required_fields: []",
                    1,
                ),
                "stage_metadata_semantic_field_empty",
            ),
            (
                lambda text: text.replace(
                    "schema: hapax.sdlc-stage-metadata.v2\n",
                    "schema: hapax.sdlc-stage-metadata.v1\n",
                    1,
                ),
                "stage_metadata_schema_unknown",
            ),
            (
                lambda text: text.replace(
                    "formal_model: docs/formal/sdlc-ladder.tla\n",
                    "formal_model: docs/formal/other.tla\n",
                    1,
                ),
                "stage_metadata_formal_model_invalid",
            ),
            (
                lambda text: text.replace(
                    "formal_model: docs/formal/sdlc-ladder.tla\n",
                    "formal_model: docs/formal/sdlc-ladder.tla\nunknown_root: true\n",
                    1,
                ),
                "stage_metadata_unknown_field",
            ),
            (
                lambda text: text.replace(
                    "edge_classes:\n"
                    "  next: TLA Next(s), including BLOCKED escape edges\n"
                    "  fall: TLA Fall(t), distinct from Next even when the destination "
                    "duplicates a Next edge\n",
                    "edge_classes: []\n",
                    1,
                ),
                "stage_metadata_edge_classes_invalid",
            ),
            (
                lambda text: text.replace(
                    "  - token: S0\n",
                    "  - token: S0\n    unexpected: true\n",
                    1,
                ),
                "stage_metadata_unknown_field",
            ),
            (
                lambda text: text.replace("  - token: S5\n", "  - token: S12\n", 1),
                "stage_metadata_token_sequence_invalid",
            ),
            (
                lambda text: text.replace(
                    "    display_alias: S1_RESEARCH\n",
                    "    display_alias: S0_INTAKE\n",
                    1,
                ),
                "stage_metadata_alias_token_mismatch",
            ),
            (
                lambda text: text.replace("    aliases: []\n", "    aliases: [S0]\n", 1),
                "stage_metadata_duplicate_alias",
            ),
            (
                lambda text: text.replace(
                    "    display_alias: S1_RESEARCH\n",
                    "    display_alias: S99_RESEARCH\n",
                    1,
                ),
                "stage_metadata_alias_token_mismatch",
            ),
            (
                lambda text: text.replace(
                    "    terminal: true\n",
                    "    terminal: false\n",
                    1,
                ),
                "stage_metadata_terminal_blocked_cardinality",
            ),
            (
                lambda text: text.replace(
                    "        enforcement: declared\n",
                    "        enforcement: enforced\n",
                    1,
                ),
                "stage_metadata_enforcement_witness_missing",
            ),
            (
                lambda text: text.replace(
                    "        enforcement: declared\n",
                    "        enforcement: optional\n",
                    1,
                ),
                "stage_metadata_invalid_enforcement",
            ),
            (
                lambda text: text.replace("projection_role: advance", "projection_role: skip", 1),
                "stage_metadata_invalid_projection_role",
            ),
            (
                lambda text: text.replace(
                    "      - to: S0\n        projection_role: repair\n"
                    "        authority_capability: coord.case.advance\n",
                    "      - to: S0\n        projection_role: advance\n"
                    "        authority_capability: coord.case.advance\n",
                    1,
                ),
                "stage_metadata_projection_role_action_mismatch",
            ),
            (
                lambda text: text.replace(
                    "      - to: S10\n        projection_role: advance\n",
                    "      - to: S10\n        projection_role: repair\n",
                    1,
                ),
                "stage_metadata_projection_role_action_mismatch",
            ),
            (
                lambda text: text.replace(
                    "      - to: S0\n        projection_role: repair\n"
                    "        authority_capability: coord.case.advance\n"
                    "        guards: [disconfirmation_requires_restart]\n"
                    "        actions: [append_stage_transition, restart_intake]\n",
                    "      - to: S0\n        projection_role: advance\n"
                    "        authority_capability: coord.case.advance\n"
                    "        guards: [disconfirmation_requires_restart]\n"
                    "        actions: [append_stage_transition, begin_research]\n",
                    1,
                ),
                "stage_metadata_projection_cycle",
            ),
            (
                lambda text: text.replace(
                    "    fall:\n"
                    "      - to: BLOCKED\n"
                    "        projection_role: repair\n"
                    "        authority_capability: system.gate.refusal\n"
                    "        guards: [gate_refused]\n"
                    "        actions: [record_blocker_report, append_stage_transition]\n"
                    "        enforcement: declared\n",
                    "    fall: []\n",
                    1,
                ),
                "stage_metadata_fall_contract_invalid",
            ),
        ],
    )
    def test_stage_metadata_mutations_fail_closed(
        self,
        tmp_path: Path,
        mutation: Callable[[str], str],
        reason: str,
    ) -> None:
        target = tmp_path / "stages.yaml"
        source = SDLC_STAGE_METADATA_PATH.read_text(encoding="utf-8")
        target.write_text(mutation(source), encoding="utf-8")
        with pytest.raises(StageMetadataError) as caught:
            load_sdlc_stage_metadata(target)
        assert caught.value.reason_code == reason

    def test_missing_stage_metadata_has_typed_repair(self, tmp_path: Path) -> None:
        with pytest.raises(StageMetadataError) as caught:
            load_sdlc_stage_metadata(tmp_path / "missing.yaml")
        assert caught.value.reason_code == "stage_metadata_source_missing"
        assert "restore" in caught.value.repair_action

    def test_stage_metadata_is_in_wheel_and_container_build_contexts(self) -> None:
        config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        force_include = config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
        assert (
            force_include["docs/formal/sdlc-stage-metadata.yaml"]
            == "shared/_data/sdlc-stage-metadata.yaml"
        )
        assert force_include["docs/formal/sdlc-ladder.tla"] == "shared/_data/sdlc-ladder.tla"
        assert (
            force_include["config/compression-surface-registry.yaml"]
            == "shared/_data/compression-surface-registry.yaml"
        )
        assert (
            force_include["config/coordination-canon/source.yaml"]
            == "shared/_data/coordination-canon-source.yaml"
        )
        assert (
            force_include["config/coordination-canon/runtime-dependency-release-set.json"]
            == "shared/_data/runtime-dependency-release-set.json"
        )
        assert (
            force_include["schemas/coordination-canon.schema.json"]
            == "shared/_data/coordination-canon.schema.json"
        )
        dockerfile = (REPO_ROOT / "docker" / "Dockerfile.logos-api").read_text(encoding="utf-8")
        assert "uv sync --frozen --no-dev --extra logos-api --no-install-project" in dockerfile
        assert (
            "COPY docs/formal/sdlc-stage-metadata.yaml "
            "docs/formal/sdlc-stage-metadata.yaml" in dockerfile
        )
        assert "COPY docs/formal/sdlc-ladder.tla docs/formal/sdlc-ladder.tla" in dockerfile
        assert (
            "COPY config/coordination-canon/source.yaml "
            "config/coordination-canon/source.yaml" in dockerfile
        )
        assert (
            "COPY config/coordination-canon/runtime-dependency-release-set.json "
            "config/coordination-canon/runtime-dependency-release-set.json" in dockerfile
        )
        dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        docs_rule = dockerignore.index("docs/")
        assert dockerignore[docs_rule : docs_rule + 7] == [
            "docs/",
            "!docs/",
            "docs/*",
            "!docs/formal/",
            "docs/formal/*",
            "!docs/formal/sdlc-stage-metadata.yaml",
            "!docs/formal/sdlc-ladder.tla",
        ]

    def test_stage_re_accepts_canonical_shapes_rejects_malformed(self) -> None:
        for good in ("S0", "S6", "S11", "S6_IMPLEMENTATION", "S7_RELEASE", "S0_INTAKE"):
            assert STAGE_RE.match(good), f"should accept {good!r}"
        for bad in ("", "S", "s6", "S6_lower", "X6", "S123", "S6-IMPL", "BLOCKED"):
            assert not STAGE_RE.match(bad), f"should reject {bad!r}"

    def test_sdlc_invariants_reuses_canonical_stage_token(self) -> None:
        # The invariants monitor's _stage_token is the canonical one, not a
        # hand-kept duplicate (the naming-drift bridge collapses to one source).
        from shared import sdlc_invariants

        assert sdlc_invariants._stage_token is stage_token

    def test_cc_stage_advance_delegates_stage_grammar_and_edges_to_canonical(self) -> None:
        # The command must not maintain a second stage grammar or infer legal
        # edges numerically. LifecycleTransitionIntent owns both decisions.
        src = (REPO_ROOT / "scripts" / "cc-stage-advance").read_text(encoding="utf-8")
        assert "LifecycleTransitionIntent.create(" in src
        assert "_STAGE_RE" not in src
        assert "_stage_num" not in src
        assert "--allow-backward was removed" in src


class TestAcceptanceReceiptEnforcement:
    """Acceptance-receipt vocabulary for review-floor tasks (routing Phase 0.2).

    frontier_review_required is only honest if acceptance is enforced: closing
    or queueing a review-floor task demands a signed receipt
    (``<task_id>.acceptance.yaml`` beside the note) carrying acceptor identity,
    verdict, timestamp, and an artifact ref.
    """

    def _note(self, tmp_path: Path, task_id: str, frontmatter: dict[str, object]) -> Path:
        path = tmp_path / f"{task_id}.md"
        lines = [f"{key}: {value}" for key, value in frontmatter.items()]
        path.write_text(
            "---\ntype: cc-task\ntask_id: " + task_id + "\n" + "\n".join(lines) + "\n---\n",
            encoding="utf-8",
        )
        return path

    def _receipt(self, tmp_path: Path, task_id: str, body: str) -> Path:
        path = tmp_path / f"{task_id}.acceptance.yaml"
        path.write_text(body, encoding="utf-8")
        return path

    VALID_RECEIPT = (
        "acceptor: operator\n"
        "verdict: accepted\n"
        "timestamp: 2026-06-10T17:00:00Z\n"
        "artifact: https://github.com/hapax-systems/hapax-council/pull/4100\n"
    )

    def test_review_floor_declared_top_level_requires_receipt(self) -> None:
        assert requires_acceptance_receipt({"quality_floor": "frontier_review_required"})

    def test_review_floor_declared_in_nested_route_metadata_requires_receipt(self) -> None:
        frontmatter = {
            "quality_floor": None,
            "route_metadata": {"quality_floor": "frontier_review_required"},
        }
        assert requires_acceptance_receipt(frontmatter)

    def test_non_review_floor_task_requires_no_receipt(self) -> None:
        assert not requires_acceptance_receipt({"quality_floor": "frontier_required"})
        assert not requires_acceptance_receipt({"quality_floor": "deterministic_ok"})
        assert not requires_acceptance_receipt({})

    def test_receipt_path_is_task_id_acceptance_yaml_beside_note(self, tmp_path: Path) -> None:
        note = self._note(tmp_path, "task-r", {"quality_floor": "frontier_review_required"})
        assert acceptance_receipt_path(note, "task-r") == tmp_path / "task-r.acceptance.yaml"

    def test_missing_receipt_blocks_review_floor_task(self, tmp_path: Path) -> None:
        note = self._note(tmp_path, "task-r", {"quality_floor": "frontier_review_required"})
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))
        assert acceptance_receipt_blockers(frontmatter, note) == ("missing_acceptance_receipt",)

    def test_non_review_floor_task_has_no_receipt_blockers(self, tmp_path: Path) -> None:
        note = self._note(tmp_path, "task-n", {"quality_floor": "frontier_required"})
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))
        assert acceptance_receipt_blockers(frontmatter, note) == ()

    def test_valid_receipt_clears_blockers(self, tmp_path: Path) -> None:
        note = self._note(tmp_path, "task-r", {"quality_floor": "frontier_review_required"})
        self._receipt(tmp_path, "task-r", self.VALID_RECEIPT)
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))
        assert acceptance_receipt_blockers(frontmatter, note) == ()

    def test_receipt_missing_fields_block(self, tmp_path: Path) -> None:
        note = self._note(tmp_path, "task-r", {"quality_floor": "frontier_review_required"})
        self._receipt(tmp_path, "task-r", "acceptor: operator\nverdict: accepted\n")
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))
        blockers = acceptance_receipt_blockers(frontmatter, note)
        assert "acceptance_receipt_missing_field:timestamp" in blockers
        assert "acceptance_receipt_missing_field:artifact" in blockers

    def test_rejected_verdict_blocks(self, tmp_path: Path) -> None:
        note = self._note(tmp_path, "task-r", {"quality_floor": "frontier_review_required"})
        self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("verdict: accepted", "verdict: rejected"),
        )
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))
        assert acceptance_receipt_blockers(frontmatter, note) == (
            "acceptance_receipt_verdict_not_accepted:rejected",
        )

    def test_malformed_receipt_blocks(self, tmp_path: Path) -> None:
        note = self._note(tmp_path, "task-r", {"quality_floor": "frontier_review_required"})
        self._receipt(tmp_path, "task-r", "- just\n- a\n- list\n")
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))
        blockers = acceptance_receipt_blockers(frontmatter, note)
        assert len(blockers) == 1
        assert blockers[0].startswith("acceptance_receipt_malformed:")

    def test_review_floor_task_without_task_id_fails_closed(self, tmp_path: Path) -> None:
        note = tmp_path / "anonymous.md"
        note.write_text(
            "---\ntype: cc-task\nquality_floor: frontier_review_required\n---\n",
            encoding="utf-8",
        )
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))
        assert acceptance_receipt_blockers(frontmatter, note) == ("missing_acceptance_receipt",)
