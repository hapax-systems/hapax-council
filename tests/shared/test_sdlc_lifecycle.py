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
from pathlib import Path

from shared.sdlc_lifecycle import (
    PR_ACTIONS,
    STAGE_RE,
    TASK_CLAIMABLE_STATUSES,
    TASK_DISPATCHABLE_STATUSES,
    active_blocked_task_blockers,
    frontmatter_from_text,
    is_active_blocked_with_evidence,
    is_dependency_blocked_reason,
    stage_token,
    task_closure_validity,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


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

    def test_cc_stage_advance_stage_re_pinned_to_canonical(self) -> None:
        # cc-stage-advance defines _STAGE_RE at module scope (before its
        # in-function sys.path insert), so it cannot import the canonical pattern
        # at load time. Pin the two equal by test instead, so they cannot drift.
        src = (REPO_ROOT / "scripts" / "cc-stage-advance").read_text(encoding="utf-8")
        patterns = {
            node.targets[0].id: node.value.args[0].value
            for node in ast.walk(ast.parse(src))
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "compile"
            and node.value.args
            and isinstance(node.value.args[0], ast.Constant)
        }
        assert "_STAGE_RE" in patterns, "cc-stage-advance _STAGE_RE = re.compile(...) not found"
        assert patterns["_STAGE_RE"] == STAGE_RE.pattern
