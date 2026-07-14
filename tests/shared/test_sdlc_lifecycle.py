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
import hashlib
from pathlib import Path

from shared.sdlc_lifecycle import (
    PR_ACTIONS,
    REVIEW_TEAM_DIGEST_MIGRATION_FILENAME,
    REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION,
    REVIEW_TEAM_DIGEST_MIGRATION_SCHEMA,
    STAGE_RE,
    TASK_CLAIMABLE_STATUSES,
    TASK_DISPATCHABLE_STATUSES,
    _acceptance_receipt_validity_blockers,
    acceptance_receipt_blockers,
    acceptance_receipt_path,
    active_blocked_task_blockers,
    frontmatter_from_text,
    is_active_blocked_with_evidence,
    is_dependency_blocked_reason,
    requires_acceptance_receipt,
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

    def _dossier(self, tmp_path: Path, task_id: str, body: str = "dossier-v1\n") -> str:
        path = tmp_path / f"{task_id}.review-dossier.yaml"
        path.write_text(body, encoding="utf-8")
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def _migration(
        self,
        tmp_path: Path,
        *,
        task_id: str = "task-r",
        receipt_basename: str = "task-r.acceptance.yaml",
        receipt_sha256: str,
        classification: str = REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION,
        extra_entry: str = "",
    ) -> Path:
        path = tmp_path / REVIEW_TEAM_DIGEST_MIGRATION_FILENAME
        path.write_text(
            f"""schema: {REVIEW_TEAM_DIGEST_MIGRATION_SCHEMA}
entries:
  - task_id: {task_id}
    receipt_basename: {receipt_basename}
    receipt_sha256: {receipt_sha256}
    classification: {classification}
{extra_entry}""",
            encoding="utf-8",
        )
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

    def test_review_team_receipt_bound_to_dossier_sha_clears_blockers(self, tmp_path: Path) -> None:
        note = self._note(tmp_path, "task-r", {"quality_floor": "frontier_review_required"})
        digest = self._dossier(tmp_path, "task-r")
        self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm")
            + f"dossier_sha256: sha256:{digest}\n",
        )
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))
        assert acceptance_receipt_blockers(frontmatter, note) == ()

    def test_direct_review_team_digest_validation_requires_dossier_context(
        self, tmp_path: Path
    ) -> None:
        digest = self._dossier(tmp_path, "task-r")
        receipt = self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm")
            + f"dossier_sha256: sha256:{digest}\n",
        )

        assert "acceptance_receipt_dossier_context_missing" in (
            _acceptance_receipt_validity_blockers(receipt)
        )

    def test_operator_receipt_does_not_retroactively_require_dossier_sha(
        self, tmp_path: Path
    ) -> None:
        note = self._note(tmp_path, "task-r", {"quality_floor": "frontier_review_required"})
        self._receipt(tmp_path, "task-r", self.VALID_RECEIPT)
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))
        assert acceptance_receipt_blockers(frontmatter, note) == ()

    def test_backdated_review_team_receipt_without_digest_still_blocks(
        self, tmp_path: Path
    ) -> None:
        note = self._note(tmp_path, "task-r", {"quality_floor": "frontier_review_required"})
        self._dossier(tmp_path, "task-r")
        self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm"),
        )
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))
        blockers = acceptance_receipt_blockers(frontmatter, note)
        assert "acceptance_receipt_review_team_dossier_sha256_missing" in blockers
        assert "acceptance_receipt_digest_migration_missing" in blockers

    def test_digest_unbound_review_team_receipt_exact_hash_migration_clears_blockers(
        self, tmp_path: Path
    ) -> None:
        note = self._note(tmp_path, "task-r", {"quality_floor": "frontier_review_required"})
        receipt = self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm"),
        )
        receipt_sha = "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest()
        self._migration(tmp_path, receipt_sha256=receipt_sha)
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))

        assert acceptance_receipt_blockers(frontmatter, note) == ()

        receipt.write_text(
            receipt.read_text(encoding="utf-8") + "tampered: true\n",
            encoding="utf-8",
        )
        assert "acceptance_receipt_digest_migration_sha256_mismatch" in (
            acceptance_receipt_blockers(frontmatter, note)
        )

    def test_new_review_team_receipt_missing_dossier_sha_blocks(self, tmp_path: Path) -> None:
        note = self._note(tmp_path, "task-r", {"quality_floor": "frontier_review_required"})
        self._dossier(tmp_path, "task-r")
        self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace(
                "acceptor: operator", "acceptor: review-team:codex,glm"
            ).replace("timestamp: 2026-06-10T17:00:00Z", "timestamp: 2026-07-14T00:00:00Z"),
        )
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))
        blockers = acceptance_receipt_blockers(frontmatter, note)
        assert "acceptance_receipt_review_team_dossier_sha256_missing" in blockers
        assert "acceptance_receipt_digest_migration_missing" in blockers

    def test_malformed_digest_migration_artifact_fails_closed(self, tmp_path: Path) -> None:
        note = self._note(tmp_path, "task-r", {"quality_floor": "frontier_review_required"})
        self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm"),
        )
        (tmp_path / REVIEW_TEAM_DIGEST_MIGRATION_FILENAME).write_text("[]\n", encoding="utf-8")
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))

        assert "acceptance_receipt_digest_migration_malformed:not_a_mapping:list" in (
            acceptance_receipt_blockers(frontmatter, note)
        )

    def test_path_escaping_digest_migration_entry_fails_closed(self, tmp_path: Path) -> None:
        note = self._note(tmp_path, "task-r", {"quality_floor": "frontier_review_required"})
        receipt = self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm"),
        )
        receipt_sha = "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest()
        self._migration(
            tmp_path,
            receipt_basename="../task-r.acceptance.yaml",
            receipt_sha256=receipt_sha,
        )
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))

        assert "acceptance_receipt_digest_migration_path_invalid" in (
            acceptance_receipt_blockers(frontmatter, note)
        )

    def test_unlisted_digest_migration_entry_fails_closed(self, tmp_path: Path) -> None:
        note = self._note(tmp_path, "task-r", {"quality_floor": "frontier_review_required"})
        receipt = self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm"),
        )
        receipt_sha = "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest()
        self._migration(
            tmp_path,
            task_id="other-task",
            receipt_basename="other-task.acceptance.yaml",
            receipt_sha256=receipt_sha,
        )
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))

        assert "acceptance_receipt_digest_migration_unlisted" in (
            acceptance_receipt_blockers(frontmatter, note)
        )

    def test_duplicate_task_digest_migration_entry_fails_closed(self, tmp_path: Path) -> None:
        note = self._note(tmp_path, "task-r", {"quality_floor": "frontier_review_required"})
        receipt = self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm"),
        )
        receipt_sha = "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest()
        self._migration(
            tmp_path,
            receipt_sha256=receipt_sha,
            extra_entry=(
                "  - task_id: task-r\n"
                "    receipt_basename: other.acceptance.yaml\n"
                f"    receipt_sha256: {receipt_sha}\n"
                f"    classification: {REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION}\n"
            ),
        )
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))

        assert "acceptance_receipt_digest_migration_duplicate_task:task-r" in (
            acceptance_receipt_blockers(frontmatter, note)
        )

    def test_non_basename_task_id_does_not_read_receipt_outside_note_dir(
        self, tmp_path: Path
    ) -> None:
        note_dir = tmp_path / "active"
        outside_dir = tmp_path / "outside"
        note_dir.mkdir()
        outside_dir.mkdir()
        note = note_dir / "task-r.md"
        note.write_text(
            "---\ntype: cc-task\ntask_id: ../outside/task-r\n"
            "quality_floor: frontier_review_required\n---\n",
            encoding="utf-8",
        )
        self._receipt(outside_dir, "task-r", self.VALID_RECEIPT)

        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))

        assert acceptance_receipt_blockers(frontmatter, note) == ("missing_acceptance_receipt",)

    def test_non_basename_task_id_does_not_read_dossier_outside_note_dir(
        self, tmp_path: Path
    ) -> None:
        note_dir = tmp_path / "active"
        outside_dir = tmp_path / "outside"
        note_dir.mkdir()
        outside_dir.mkdir()
        note = note_dir / "task-r.md"
        note.write_text("---\ntype: cc-task\ntask_id: task-r\n---\n", encoding="utf-8")
        digest = self._dossier(outside_dir, "task-r")
        receipt = note_dir / "task-r.acceptance.yaml"
        receipt.write_text(
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm")
            + f"dossier_sha256: sha256:{digest}\n",
            encoding="utf-8",
        )

        assert "acceptance_receipt_dossier_context_invalid" in (
            _acceptance_receipt_validity_blockers(
                receipt, note_path=note, task_id="../outside/task-r"
            )
        )

    def test_review_team_receipt_blocks_after_dossier_tamper(self, tmp_path: Path) -> None:
        note = self._note(tmp_path, "task-r", {"quality_floor": "frontier_review_required"})
        digest = self._dossier(tmp_path, "task-r")
        self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm")
            + f"dossier_sha256: sha256:{digest}\n",
        )
        (tmp_path / "task-r.review-dossier.yaml").write_text(
            "dossier-v1 tampered\n",
            encoding="utf-8",
        )
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))
        assert "acceptance_receipt_dossier_sha256_mismatch" in acceptance_receipt_blockers(
            frontmatter, note
        )

    def test_review_team_receipt_blocks_after_stale_same_head_replacement(
        self, tmp_path: Path
    ) -> None:
        note = self._note(tmp_path, "task-r", {"quality_floor": "frontier_review_required"})
        old_digest = self._dossier(tmp_path, "task-r", "head: cccccccc\ndossier: old\n")
        self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm")
            + "head_sha: cccccccccccccccccccccccccccccccccccccccc\n"
            + f"dossier_sha256: sha256:{old_digest}\n",
        )
        self._dossier(tmp_path, "task-r", "head: cccccccc\ndossier: replacement\n")
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))
        assert "acceptance_receipt_dossier_sha256_mismatch" in acceptance_receipt_blockers(
            frontmatter, note
        )

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
