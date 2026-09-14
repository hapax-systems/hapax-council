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
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.blocked_witness import evaluate_blocked_witness
from shared.sdlc_lifecycle import (
    FRONTMATTER_ABSENT,
    FRONTMATTER_INVALID_OPENING_FENCE,
    FRONTMATTER_NOT_A_MAPPING,
    FRONTMATTER_OK,
    FRONTMATTER_PARSE_ERROR,
    FRONTMATTER_UNREADABLE_STATES,
    FRONTMATTER_UNTERMINATED,
    PR_ACTIONS,
    RECEIPT_TRIGGER_INDEPENDENT_REVIEW,
    RECEIPT_TRIGGER_MALFORMED_CONTAINER,
    RECEIPT_TRIGGER_MALFORMED_REVIEW,
    RECEIPT_TRIGGER_REVIEW_FLOOR,
    SDLC_STAGE_METADATA,
    SDLC_STAGE_METADATA_PATH,
    STAGE_RE,
    TASK_CLAIMABLE_STATUSES,
    TASK_DISPATCHABLE_STATUSES,
    StageMetadataError,
    acceptance_receipt_blockers,
    acceptance_receipt_path,
    acceptance_receipt_triggers,
    active_blocked_task_blockers,
    frontmatter_from_text,
    frontmatter_state_from_text,
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

    def test_typed_witness_unknown_kind_refuses(self) -> None:
        fm = frontmatter_from_text(
            """---
status: blocked
blocked_reason: waiting
blocked_witness:
  kind: existence_implies_resolved
  ref: /tmp/anything
---
"""
        )
        assert evaluate_blocked_witness(fm) == "refuse"
        assert is_active_blocked_with_evidence(fm) is True

    def test_typed_path_exists_witness_evaluates_the_named_path(self, tmp_path: Path) -> None:
        present = tmp_path / "here"
        present.write_text("ok", encoding="utf-8")
        missing = tmp_path / "gone"
        sat = frontmatter_from_text(
            f"""---
status: blocked
blocked_reason: waiting
blocked_witness:
  kind: path_exists
  ref: {present}
---
"""
        )
        uns = frontmatter_from_text(
            f"""---
status: blocked
blocked_reason: waiting
blocked_witness:
  kind: path_exists
  ref: {missing}
---
"""
        )
        assert evaluate_blocked_witness(sat) == "satisfied"
        assert is_active_blocked_with_evidence(sat) is True
        assert evaluate_blocked_witness(uns) == "unsatisfied"
        assert is_active_blocked_with_evidence(uns) is True

    def test_string_witness_is_untyped_and_refuses(self) -> None:
        fm = frontmatter_from_text(
            """---
status: blocked
blocked_reason: waiting
blocked_witness: /tmp/does-not-need-to-exist
---
"""
        )
        assert evaluate_blocked_witness(fm) == "refuse"

    def test_future_receipt_timestamp_refuses(self, tmp_path: Path) -> None:
        receipt = tmp_path / "receipt.yaml"
        receipt.write_text(
            "observed_at: 2099-01-01T00:00:00Z\nstale_after_seconds: 3600\n",
            encoding="utf-8",
        )
        fm = frontmatter_from_text(
            f"""---
status: blocked
blocked_reason: waiting
blocked_witness:
  kind: receipt_fresh
  ref: {receipt}
---
"""
        )
        now = datetime(2026, 8, 18, tzinfo=UTC)
        assert evaluate_blocked_witness(fm, now=now) == "refuse"
        assert is_active_blocked_with_evidence(fm) is True

    def test_non_string_kind_or_ref_refuses(self) -> None:
        fm = frontmatter_from_text(
            """---
status: blocked
blocked_reason: waiting
blocked_witness:
  kind: 123
  ref: 456
---
"""
        )
        assert evaluate_blocked_witness(fm) == "refuse"

    def test_receipt_fresh_satisfied_and_stale(self, tmp_path: Path) -> None:
        receipt = tmp_path / "receipt.yaml"
        receipt.write_text(
            "observed_at: 2026-08-18T00:00:00Z\nstale_after_seconds: 3600\n",
            encoding="utf-8",
        )
        fm = frontmatter_from_text(
            f"""---
status: blocked
blocked_reason: waiting
blocked_witness:
  kind: receipt_fresh
  ref: {receipt}
---
"""
        )
        fresh_now = datetime(2026, 8, 18, 0, 10, tzinfo=UTC)
        stale_now = datetime(2026, 8, 18, 2, 0, tzinfo=UTC)
        assert evaluate_blocked_witness(fm, now=fresh_now) == "satisfied"
        assert evaluate_blocked_witness(fm, now=stale_now) == "unsatisfied"

    def test_ancestor_of_main_evaluates_returncodes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fm = frontmatter_from_text(
            """---
status: blocked
blocked_reason: waiting
blocked_witness:
  kind: ancestor_of_main
  ref: abcdef1
---
"""
        )

        class _Result:
            def __init__(self, returncode: int) -> None:
                self.returncode = returncode

        box = {"rc": 0}

        def _run(*_args: object, **_kwargs: object) -> _Result:
            return _Result(box["rc"])

        monkeypatch.setattr("shared.blocked_witness.subprocess.run", _run)
        box["rc"] = 0
        assert evaluate_blocked_witness(fm) == "satisfied"
        box["rc"] = 1
        assert evaluate_blocked_witness(fm) == "unsatisfied"
        box["rc"] = 128
        assert evaluate_blocked_witness(fm) == "refuse"

        bad = frontmatter_from_text(
            """---
status: blocked
blocked_reason: waiting
blocked_witness:
  kind: ancestor_of_main
  ref: not-a-sha
---
"""
        )
        assert evaluate_blocked_witness(bad) == "refuse"

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

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("S6", "S6"),
            ("S6_IMPLEMENTATION", "S6"),
            ("S6_UNKNOWN", "S6"),
            (" S6 ", "S6"),
            ("s6", "s6"),
            ("S12", "S12"),
            ("S3.5", "S3_5"),
            ("BLOCKED", "BLOCKED"),
        ],
    )
    def test_live_invariants_monitor_still_emits_mains_stage_value(
        self, raw: str, expected: str
    ) -> None:
        """The strict resolver must not change what the LIVE monitor emits.

        ``stage_token`` is deliberately strict, but ``shared/sdlc_invariants.py``
        calls it on every observed transition and main normalized every shaped
        alias there (``S6_UNKNOWN`` -> ``S6``). Falling back to the raw string on
        refusal would change the monitor's trace records, which a Gate-0A
        source-only landing must not do. This pins the fallback to main's exact
        normalization for both the accepted and the refused inputs, so tightening
        the resolver stays invisible to the running monitor. Caught by blind
        review (codex-1) on PR #4483.
        """
        from shared.sdlc_lifecycle import StageMetadataError as _Err

        try:
            resolved = stage_token(raw)
        except _Err:
            token = raw.strip().replace(".", "_")
            resolved = (
                token.split("_")[0]
                if (token[:1] == "S" and "_" in token and token != "S3_5")
                else token
            )
        assert resolved == expected

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


def _rr(value: object) -> dict[str, object]:
    return {"review_requirement": {"independent_review_required": value}}


class TestIndependentReviewTriggerNormalization:
    """The flag is read from raw frontmatter but written against a coercing schema.

    ``route_metadata_schema.ReviewRequirement.independent_review_required`` is a
    pydantic ``bool``, so ``"true"``, ``"yes"``, ``"y"``, ``"on"``, ``"t"``,
    ``"1"`` and ``1`` all validate as *demanding* independent review. The close
    gate reads the same frontmatter as raw text. An identity test against Python
    ``True`` therefore disagreed with the schema and let a schema-valid demand
    spelled ``"true"`` disarm the gate — the exact fail-open the trigger exists
    to close, reintroduced at the parser boundary.
    """

    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "yes", "y", "on", "t", "1", 1, True])
    def test_schema_truthy_spellings_arm_the_gate(self, value: object) -> None:
        assert acceptance_receipt_triggers(_rr(value)) == (RECEIPT_TRIGGER_INDEPENDENT_REVIEW,)

    @pytest.mark.parametrize("value", ["false", "False", "no", "n", "off", "f", "0", 0, False])
    def test_schema_falsy_spellings_do_not_arm(self, value: object) -> None:
        assert acceptance_receipt_triggers(_rr(value)) == ()

    @pytest.mark.parametrize("value", [None, "maybe", "", 2, [], {}])
    def test_unrecognized_values_arm_as_malformed(self, value: object) -> None:
        """The schema rejects these outright, so their intent is unknown.

        An unknown review requirement must not read as *no* requirement: that is
        how a malformed declaration would silently disable enforcement.
        """
        assert acceptance_receipt_triggers(_rr(value)) == (RECEIPT_TRIGGER_MALFORMED_REVIEW,)

    def test_absent_block_does_not_arm(self) -> None:
        assert acceptance_receipt_triggers({"quality_floor": "verification_receipt"}) == ()

    def test_absent_flag_within_present_block_does_not_arm(self) -> None:
        frontmatter = {"review_requirement": {"support_artifact_allowed": True}}
        assert acceptance_receipt_triggers(frontmatter) == ()


class TestSchemaParity:
    """The classifier must agree with ``ReviewRequirement`` on every value.

    ``shared.sdlc_lifecycle`` reimplements the schema's boolean coercion instead
    of importing it, because ``scripts/cc-close`` runs the close gate under a
    bare ``python3`` and pydantic must not become a runtime dependency of a gate.
    That duplication is only safe while it is *pinned*: this test round-trips
    each value through the real model, so a pydantic upgrade that changes the
    accepted spellings fails here rather than silently reopening the
    parser-boundary fail-open.

    Asserted against the model, never against the local frozensets — restating
    the table would prove nothing.
    """

    @staticmethod
    def _schema_verdict(value: object) -> bool | None:
        from shared.route_metadata_schema import ReviewRequirement

        try:
            return bool(
                ReviewRequirement(independent_review_required=value).independent_review_required
            )
        except Exception:  # noqa: BLE001 - any validation failure means "rejected"
            return None

    @pytest.mark.parametrize(
        "value",
        [
            True,
            False,
            "true",
            "True",
            "TRUE",
            "TrUe",
            "yes",
            "Yes",
            "y",
            "on",
            "t",
            "1",
            "false",
            "False",
            "no",
            "n",
            "off",
            "OFF",
            "f",
            "0",
            0,
            1,
            2,
            -1,
            0.0,
            1.0,
            2.0,
            0.5,
            -1.0,
            '"true"',
            '"false"',
            "'true'",
            "  true  ",
            "  ",
            "",
            "maybe",
            "null",
            "none",
            None,
            [],
            {},
            # bytes: the model accepts them, so the classifier's decode branch —
            # including its UnicodeDecodeError path (b"\xff") — must agree rather
            # than be incidentally correct.
            b"true",
            b"false",
            b"maybe",
            b"\xff",
            b"",
        ],
    )
    def test_classifier_matches_schema_for_every_value(self, value: object) -> None:
        schema_verdict = self._schema_verdict(value)
        triggers = acceptance_receipt_triggers(_rr(value))

        if schema_verdict is True:
            assert triggers == (RECEIPT_TRIGGER_INDEPENDENT_REVIEW,), (
                f"{value!r} is a schema-valid DEMAND but did not arm the gate"
            )
        elif schema_verdict is False:
            assert triggers == (), f"{value!r} is a schema-valid DECLINE but armed the gate"
        else:
            assert triggers == (RECEIPT_TRIGGER_MALFORMED_REVIEW,), (
                f"{value!r} is REJECTED by the schema but was not classified malformed"
            )


class TestMalformedBlockShape:
    """A ``review_requirement`` that is present but not a mapping is malformed.

    ``review_requirement: [{independent_review_required: true}]`` is rejected by
    ``assess_route_metadata`` yet was classified *absent*, so the gate permitted
    closure on a row the schema considered invalid. Present-but-unreadable may
    never collapse into "nothing was claimed".
    """

    @pytest.mark.parametrize(
        "block", [[{"independent_review_required": True}], "true", 1, [], None]
    )
    def test_non_mapping_block_is_malformed_top_level(self, block: object) -> None:
        assert acceptance_receipt_triggers({"review_requirement": block}) == (
            RECEIPT_TRIGGER_MALFORMED_CONTAINER,
        )

    @pytest.mark.parametrize(
        "block", [[{"independent_review_required": True}], "true", 1, [], None]
    )
    def test_non_mapping_block_is_malformed_in_mirror(self, block: object) -> None:
        frontmatter = {"route_metadata": {"review_requirement": block}}
        assert acceptance_receipt_triggers(frontmatter) == (RECEIPT_TRIGGER_MALFORMED_CONTAINER,)

    def test_missing_block_is_still_absent(self) -> None:
        """The distinction that matters: absent is not malformed."""
        assert acceptance_receipt_triggers({"quality_floor": "verification_receipt"}) == ()


class TestFrontmatterParseState:
    """The document is the outermost container, and it gets the same rule.

    ``frontmatter_from_text`` collapses every failure to ``{}``, so a note whose
    YAML does not parse is indistinguishable from one that declares nothing. For
    a gate that arms on declarations those are opposite meanings, and the gate
    was reporting the first as the second.
    """

    def test_well_formed_frontmatter_is_ok(self) -> None:
        loaded, state = frontmatter_state_from_text("---\ntask_id: x\n---\nbody\n")
        assert state == FRONTMATTER_OK
        assert loaded == {"task_id": "x"}

    def test_no_frontmatter_is_absent_not_unreadable(self) -> None:
        """A plain markdown file declares nothing; that is not a failure."""
        _, state = frontmatter_state_from_text("just a body\n")
        assert state == FRONTMATTER_ABSENT
        assert state not in FRONTMATTER_UNREADABLE_STATES

    def test_empty_frontmatter_is_absent(self) -> None:
        _, state = frontmatter_state_from_text("---\n\n---\nbody\n")
        assert state == FRONTMATTER_ABSENT
        assert state not in FRONTMATTER_UNREADABLE_STATES

    def test_unterminated_frontmatter_is_unreadable(self) -> None:
        _, state = frontmatter_state_from_text("---\ntask_id: x\nbody without close\n")
        assert state == FRONTMATTER_UNTERMINATED
        assert state in FRONTMATTER_UNREADABLE_STATES

    def test_invalid_yaml_is_unreadable(self) -> None:
        text = "---\nverification_surface: [\nreview_requirement:\n  a: b\n---\nbody\n"
        _, state = frontmatter_state_from_text(text)
        assert state == FRONTMATTER_PARSE_ERROR
        assert state in FRONTMATTER_UNREADABLE_STATES

    def test_sequence_document_is_unreadable(self) -> None:
        _, state = frontmatter_state_from_text("---\n- a\n- b\n---\nbody\n")
        assert state == FRONTMATTER_NOT_A_MAPPING
        assert state in FRONTMATTER_UNREADABLE_STATES

    def test_a_yaml_key_starting_with_dashes_is_not_a_closing_fence(self) -> None:
        """``---extra: abc`` is a legal key, not a fence.

        Matching the fence as a prefix truncated the block there and returned
        the preceding fields with state ``ok`` — hiding whatever followed behind
        a confident success rather than declaring itself unreadable.
        """
        text = (
            "---\ntask_id: x\n---extra: abc\n"
            "review_requirement:\n  independent_review_required: true\n---\nbody\n"
        )

        loaded, state = frontmatter_state_from_text(text)

        assert state == FRONTMATTER_OK
        assert loaded["---extra"] == "abc"
        assert acceptance_receipt_triggers(loaded) == (RECEIPT_TRIGGER_INDEPENDENT_REVIEW,)

    def test_adjacent_and_blank_separated_empty_fences_agree(self) -> None:
        """Both are empty frontmatter; the offset scan disagreed about them."""
        adjacent = frontmatter_state_from_text("---\n---\nbody\n")
        blank_separated = frontmatter_state_from_text("---\n\n---\nbody\n")

        assert adjacent == blank_separated == ({}, FRONTMATTER_ABSENT)

    def test_a_commented_opening_fence_still_arms_the_gate(self) -> None:
        """``--- # task metadata`` is a supported header and a legal YAML marker.

        Tightening the opening-fence check to an exact ``---`` rejected it, so a
        note carrying BOTH the frontier floor and an independent-review demand
        reported ``absent`` and the gate returned 0 — a previously enforced note
        silently disarmed. Base blocked it; that head did not.
        """
        text = (
            "--- # task metadata\n"
            "quality_floor: frontier_review_required\n"
            "review_requirement:\n  independent_review_required: true\n---\nbody\n"
        )

        loaded, state = frontmatter_state_from_text(text)

        assert state == FRONTMATTER_OK
        assert acceptance_receipt_triggers(loaded) == (
            RECEIPT_TRIGGER_REVIEW_FLOOR,
            RECEIPT_TRIGGER_INDEPENDENT_REVIEW,
        )

    def test_indented_dashes_inside_a_literal_scalar_are_not_a_fence(self) -> None:
        """A fence sits at column 0; an indented ``---`` is scalar content.

        ``strip()`` accepted it, truncating the block and dropping every field
        below — including the review demand. It also regressed frontier
        enforcement: a ``quality_floor`` placed after such a scalar vanished.
        """
        text = (
            "---\ntask_id: x\ndescription: |\n  ---\n"
            "review_requirement:\n  independent_review_required: true\n---\nbody\n"
        )

        loaded, state = frontmatter_state_from_text(text)

        assert state == FRONTMATTER_OK
        assert acceptance_receipt_triggers(loaded) == (RECEIPT_TRIGGER_INDEPENDENT_REVIEW,)

    def test_indented_dashes_do_not_hide_the_quality_floor(self) -> None:
        """The frontier-enforcement regression, pinned in its own right."""
        text = (
            "---\ntask_id: x\ndescription: >\n  ---\n"
            "quality_floor: frontier_review_required\n---\nbody\n"
        )

        loaded, _ = frontmatter_state_from_text(text)

        assert acceptance_receipt_triggers(loaded) == (RECEIPT_TRIGGER_REVIEW_FLOOR,)

    def test_fence_with_trailing_whitespace_still_closes(self) -> None:
        loaded, state = frontmatter_state_from_text("---\ntask_id: x\n--- \nbody\n")
        assert state == FRONTMATTER_OK
        assert loaded == {"task_id": "x"}

    @pytest.mark.parametrize(
        "text",
        [
            "---nope: 1\ntask_id: x\n---\nbody\n",
            "---extra: [\ntask_id: x\n---\nbody\n",
            "----\ntask_id: x\n---\nbody\n",
        ],
    )
    def test_an_attempted_but_invalid_opening_marker_is_unreadable(self, text: str) -> None:
        """Not ABSENT: the note visibly tried to declare frontmatter.

        Classing it absent let the close gate report "no receipt-arming
        declaration" and pass, while admission — which was given this
        distinction first — blocked. The two surfaces disagreed on the same
        input, which is the split this PR exists to remove.
        """
        _, state = frontmatter_state_from_text(text)

        assert state == FRONTMATTER_INVALID_OPENING_FENCE
        assert state in FRONTMATTER_UNREADABLE_STATES

    def test_a_document_with_no_marker_at_all_is_still_absent(self) -> None:
        """The control: absent and invalid must stay distinguishable."""
        _, state = frontmatter_state_from_text("plain body\n")
        assert state == FRONTMATTER_ABSENT
        assert state not in FRONTMATTER_UNREADABLE_STATES

    def test_opening_line_yaml_content_is_preserved(self) -> None:
        """``--- {a: 1}`` is a document whose mapping sits on the marker line.

        The fence predicate accepted the line and extraction then took only the
        lines *after* it, so the declarations on it vanished while the parse
        reported success — a clean-looking result that had dropped half the
        document.
        """
        text = "--- {task_id: inline, quality_floor: frontier_review_required}\n\n---\nbody\n"

        loaded, state = frontmatter_state_from_text(text)

        assert state == FRONTMATTER_OK
        assert loaded["task_id"] == "inline"
        assert acceptance_receipt_triggers(loaded) == (RECEIPT_TRIGGER_REVIEW_FLOOR,)

    def test_crlf_notes_parse_identically_to_lf(self) -> None:
        """The snapshot path decodes raw bytes; the gate uses newline-normalizing reads.

        Without CR tolerance those two surfaces disagree about the same file:
        terminal close raised task_note_frontmatter_malformed on a CRLF note the
        standalone checker accepted.
        """
        crlf = "---\r\ntask_id: x\r\nquality_floor: frontier_review_required\r\n---\r\nbody\r\n"
        lf = crlf.replace("\r\n", "\n")

        assert frontmatter_state_from_text(crlf) == frontmatter_state_from_text(lf)
        loaded, state = frontmatter_state_from_text(crlf)
        assert state == FRONTMATTER_OK
        assert acceptance_receipt_triggers(loaded) == (RECEIPT_TRIGGER_REVIEW_FLOOR,)

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("---\ntask_id: x\n---\nbody\n", {"task_id": "x"}),
            ("no frontmatter\n", {}),
            ("---\nverification_surface: [\n---\nbody\n", {}),
            ("---\n- a\n---\nbody\n", {}),
            ("---\ntask_id: x\nbody without close\n", {}),
            ("---\n---\nbody\n", {}),
            ("---\n\n---\nbody\n", {}),
            # Fence boundaries: a line that merely STARTS with --- is a YAML key,
            # not a closing fence, and must not truncate the block.
            (
                "---\ntask_id: x\n---extra: abc\nkeep: yes\n---\nbody\n",
                {"task_id": "x", "---extra": "abc", "keep": True},
            ),
            ("---\ntask_id: x\n--- \nbody\n", {"task_id": "x"}),
        ],
    )
    def test_lossy_helper_returns_the_expected_mapping(
        self, text: str, expected: dict[str, object]
    ) -> None:
        """Explicit expectations, not a comparison with the implementation.

        The previous version asserted ``frontmatter_from_text(text) ==
        frontmatter_state_from_text(text)[0]``, which is how the wrapper is
        *defined* — it stayed green even when both returned a wrong mapping, so
        it established nothing about the preserved parser contract.
        """
        assert frontmatter_from_text(text) == expected


class TestMalformedContainerAtEveryLevel:
    """Shape is checked at every level of the lookup chain, not just the innermost.

    Skipping a present-but-wrong-shaped container discards whatever it holds.
    That bit twice: a non-mapping ``review_requirement`` classified as absent,
    then a non-mapping ``route_metadata`` skipped outright — which silently
    discarded a review demand nested inside it while ``assess_route_metadata``
    rejected the same note. Same error, different depth.
    """

    @pytest.mark.parametrize(
        "route_metadata",
        [
            [{"review_requirement": {"independent_review_required": True}}],
            "oops",
            1,
            [],
        ],
    )
    def test_non_mapping_route_metadata_arms(self, route_metadata: object) -> None:
        frontmatter = {
            "quality_floor": "verification_receipt",
            "route_metadata": route_metadata,
        }
        assert acceptance_receipt_triggers(frontmatter) == (RECEIPT_TRIGGER_MALFORMED_CONTAINER,)

    def test_demand_nested_in_a_malformed_route_metadata_is_not_discarded(self) -> None:
        """The reported critical: the demand is invisible, so the gate must arm anyway."""
        frontmatter = {
            "quality_floor": "verification_receipt",
            "route_metadata": [{"review_requirement": {"independent_review_required": True}}],
        }
        assert acceptance_receipt_triggers(frontmatter) != ()

    def test_top_level_decline_does_not_excuse_a_malformed_route_metadata(self) -> None:
        """An explicit false cannot vouch for a mirror nobody can read."""
        frontmatter = {
            "review_requirement": {"independent_review_required": False},
            "route_metadata": [{"review_requirement": {"independent_review_required": True}}],
        }
        assert acceptance_receipt_triggers(frontmatter) == (RECEIPT_TRIGGER_MALFORMED_CONTAINER,)

    def test_container_and_value_malformations_are_distinct(self) -> None:
        """The refusal must not tell an operator to fix an already-valid flag."""
        container = acceptance_receipt_triggers({"review_requirement": [{"x": 1}]})
        value = acceptance_receipt_triggers(
            {"review_requirement": {"independent_review_required": "maybe"}}
        )
        assert container == (RECEIPT_TRIGGER_MALFORMED_CONTAINER,)
        assert value == (RECEIPT_TRIGGER_MALFORMED_REVIEW,)
        assert container != value

    def test_absent_route_metadata_is_not_malformed(self) -> None:
        assert acceptance_receipt_triggers({"quality_floor": "verification_receipt"}) == ()

    def test_valid_mapping_route_metadata_is_not_malformed(self) -> None:
        frontmatter = {"route_metadata": {"quality_floor": "verification_receipt"}}
        assert acceptance_receipt_triggers(frontmatter) == ()


class TestIndependentReviewMirror:
    """The ``route_metadata`` mirror is consulted, fail-closed on disagreement."""

    def test_mirror_only_declaration_arms(self) -> None:
        frontmatter = {
            "quality_floor": "verification_receipt",
            "route_metadata": {"review_requirement": {"independent_review_required": True}},
        }
        assert acceptance_receipt_triggers(frontmatter) == (RECEIPT_TRIGGER_INDEPENDENT_REVIEW,)

    def test_mirror_demand_overrides_benign_top_level(self) -> None:
        """Disagreement fails closed: a demand anywhere arms."""
        frontmatter = {
            "quality_floor": "verification_receipt",
            "review_requirement": {"independent_review_required": False},
            "route_metadata": {"review_requirement": {"independent_review_required": True}},
        }
        assert acceptance_receipt_triggers(frontmatter) == (RECEIPT_TRIGGER_INDEPENDENT_REVIEW,)

    def test_top_level_demand_overrides_benign_mirror(self) -> None:
        frontmatter = {
            "quality_floor": "verification_receipt",
            "review_requirement": {"independent_review_required": True},
            "route_metadata": {"review_requirement": {"independent_review_required": False}},
        }
        assert acceptance_receipt_triggers(frontmatter) == (RECEIPT_TRIGGER_INDEPENDENT_REVIEW,)

    def test_both_declining_does_not_arm(self) -> None:
        frontmatter = {
            "quality_floor": "verification_receipt",
            "review_requirement": {"independent_review_required": False},
            "route_metadata": {"review_requirement": {"independent_review_required": False}},
        }
        assert acceptance_receipt_triggers(frontmatter) == ()

    def test_malformed_mirror_arms_even_when_top_level_declines(self) -> None:
        frontmatter = {
            "review_requirement": {"independent_review_required": False},
            "route_metadata": {"review_requirement": {"independent_review_required": "maybe"}},
        }
        assert acceptance_receipt_triggers(frontmatter) == (RECEIPT_TRIGGER_MALFORMED_REVIEW,)

    def test_demand_plus_malformed_reports_both(self) -> None:
        """A demand elsewhere must not suppress an unreadable declaration.

        The gate arms either way, so this is not a fail-open — but reporting only
        the demand loses which location is unreadable, which is precisely the
        reconstructability the malformed trigger exists to provide, and hides
        mirror drift ``assess_route_metadata`` would reject.
        """
        frontmatter = {
            "review_requirement": {"independent_review_required": True},
            "route_metadata": {"review_requirement": {"independent_review_required": "maybe"}},
        }
        assert acceptance_receipt_triggers(frontmatter) == (
            RECEIPT_TRIGGER_INDEPENDENT_REVIEW,
            RECEIPT_TRIGGER_MALFORMED_REVIEW,
        )

    def test_malformed_plus_demand_reports_both_in_the_reverse_arrangement(self) -> None:
        frontmatter = {
            "review_requirement": {"independent_review_required": "maybe"},
            "route_metadata": {"review_requirement": {"independent_review_required": True}},
        }
        assert acceptance_receipt_triggers(frontmatter) == (
            RECEIPT_TRIGGER_INDEPENDENT_REVIEW,
            RECEIPT_TRIGGER_MALFORMED_REVIEW,
        )


class TestBothTriggersTogether:
    def test_both_declarations_are_reported(self) -> None:
        frontmatter = {
            "quality_floor": "frontier_review_required",
            "review_requirement": {"independent_review_required": True},
        }
        assert acceptance_receipt_triggers(frontmatter) == (
            RECEIPT_TRIGGER_REVIEW_FLOOR,
            RECEIPT_TRIGGER_INDEPENDENT_REVIEW,
        )

    def test_floor_alone_reports_only_the_floor(self) -> None:
        assert acceptance_receipt_triggers({"quality_floor": "frontier_review_required"}) == (
            RECEIPT_TRIGGER_REVIEW_FLOOR,
        )

    def test_boolean_predicate_derives_from_triggers(self) -> None:
        """One definition of "armed" — the boolean may never disagree."""
        for frontmatter in (
            {"quality_floor": "frontier_review_required"},
            {"quality_floor": "verification_receipt"},
            _rr(True),
            _rr("true"),
            _rr(False),
            _rr("maybe"),
            {},
        ):
            assert requires_acceptance_receipt(frontmatter) is bool(
                acceptance_receipt_triggers(frontmatter)
            )
