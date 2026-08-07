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
import json
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

from shared import sdlc_lifecycle
from shared.sdlc_lifecycle import (
    PR_ACTIONS,
    REVIEW_TEAM_DIGEST_MIGRATION_FILENAME,
    REVIEW_TEAM_DIGEST_MIGRATION_INTEGRITY_RECHECK,
    REVIEW_TEAM_DIGEST_MIGRATION_LEGACY_ROUTE,
    REVIEW_TEAM_DIGEST_MIGRATION_NEXT_ACTIONS,
    REVIEW_TEAM_DIGEST_MIGRATION_PAUSE_BOUNDARY,
    REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION,
    REVIEW_TEAM_DIGEST_MIGRATION_SCHEMA,
    STAGE_RE,
    TASK_CLAIMABLE_STATUSES,
    TASK_DISPATCHABLE_STATUSES,
    _acceptance_receipt_validity_blockers,
    acceptance_receipt_admission_route,
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


def _plan_authority_for(authority: Mapping[str, object]) -> dict[str, object]:
    return {
        key: authority.get(key)
        for key in sdlc_lifecycle.REVIEW_TEAM_DIGEST_MIGRATION_PREPARED_PLAN_AUTHORITY_KEYS
    }


def _coherent_prepared_plan_chain(
    *,
    artifact: Mapping[str, Any],
    entries: list[dict[str, Any]],
) -> tuple[dict[str, Any], str, dict[str, Any], str]:
    """Build a prepared plan whose binding chain is DERIVED, not asserted.

    Lifecycle now runs the exact shared plan decoder, which recomputes the disposition manifest,
    write set, plan identity and candidate authority from the plan's own decoded contents. A fixture
    can therefore no longer hand-wave those digests: a plan that merely agrees with itself is now
    rejected, which is the whole point of the decoder. Everything below is computed in dependency
    order -- content, then digests, then plan identity, then candidate authority.
    """

    plan_authority = _plan_authority_for(artifact["authority"])
    plan_migration = {
        # "migration_prepared" is not a status the runtime can produce; the total decoder now says
        # so. A plan carries the status the planner actually stamped on it.
        "status": "migration_ready",
        "artifact_path": "review-team-digest-migration.yaml",
        "artifact_written": False,
        "counts": sdlc_lifecycle._migration_counts(entries),
        "entries": entries,
        "before_artifact_sha256": None,
        "after_artifact_sha256": None,
    }
    receipt_writes: list[dict[str, Any]] = []
    lock_transition = {
        "schema": "hapax.review_team_digest_migration.lock_transition.v1",
        "lock_path": "_locks/review-team-digest-migration.lock",
        "pre_claim_status": "unclaimed",
        "required_pre_claim_status": "unclaimed",
        "owned_lock_present": True,
        "owned_lock_schema": "hapax.review_team_digest_migration.lock.v1",
        "required_owned_lock_schema": "hapax.review_team_digest_migration.lock.v1",
    }
    # The evidence manifest is a TOTAL object in the shared decoder: exact keys at every level, raw
    # digests in the authority block, an exact write-set shape and typed path evidence. A fixture may
    # no longer hand-wave it as {} -- that is precisely the shape the seventh audit walked past.
    evidence_manifest: dict[str, Any] = {
        "schema": "hapax.review_team_digest_migration.evidence_manifest.v1",
        "source_trust_anchor": dict(
            sdlc_lifecycle.review_team_digest_migration_source_trust_anchor()
        ),
        "authority": {
            "proposal_path": str(plan_authority["proposal_path"]),
            "proposal_sha256": str(plan_authority["proposal_sha256"]),
            "consumed_act_carrier_path": str(plan_authority["consumed_act_carrier_path"]),
            "consumed_act_carrier_sha256": str(plan_authority["consumed_act_carrier_sha256"]),
            "frozen_inventory_canonical_sha256": str(
                plan_authority["frozen_inventory_canonical_sha256"]
            ),
        },
        "artifact_preflight": {
            "status": "migration_artifact_absent",
            "artifact_path": "review-team-digest-migration.yaml",
            "artifact_sha256": None,
            "blockers": [],
        },
        "lock_transition": lock_transition,
        "planned_writes": {
            "schema": sdlc_lifecycle.REVIEW_TEAM_DIGEST_MIGRATION_WRITE_SET_SCHEMA,
            "writes": [],
        },
        "paths": [],
    }

    disposition_manifest = sdlc_lifecycle.review_team_digest_migration_disposition_manifest(entries)
    write_set = sdlc_lifecycle.review_team_digest_migration_write_set(
        migration=plan_migration,
        receipt_writes=receipt_writes,
    )
    binding_core: dict[str, Any] = {
        "schema": sdlc_lifecycle.REVIEW_TEAM_DIGEST_MIGRATION_PREPARED_PLAN_BINDING_CORE_SCHEMA,
        "candidate_artifact_core_sha256": sdlc_lifecycle._candidate_artifact_core_sha256(artifact),
        "candidate_artifact_sha256": None,
        "disposition_manifest_sha256": sdlc_lifecycle._canonical_json_sha256(disposition_manifest),
        "write_set_sha256": sdlc_lifecycle._canonical_json_sha256(write_set),
        "evidence_manifest_sha256": sdlc_lifecycle._canonical_json_sha256(evidence_manifest),
        "snapshot_fingerprint": sdlc_lifecycle.review_team_digest_migration_snapshot_fingerprint(
            []
        ),
        "snapshot_count": 0,
        "disposition_manifest": disposition_manifest,
        "write_set": write_set,
        "evidence_manifest": evidence_manifest,
    }
    binding_core["plan_sha256"] = sdlc_lifecycle._canonical_json_sha256(
        {
            "schema": binding_core["schema"],
            "candidate_artifact_core_sha256": binding_core["candidate_artifact_core_sha256"],
            "disposition_manifest_sha256": binding_core["disposition_manifest_sha256"],
            "write_set_sha256": binding_core["write_set_sha256"],
            "evidence_manifest_sha256": binding_core["evidence_manifest_sha256"],
        }
    )
    plan_sha = binding_core["plan_sha256"]
    locator = (
        f"review-team-digest-migration.candidate-carrier.{plan_sha.removeprefix('sha256:')}.yaml"
    )
    candidate = {
        "schema": sdlc_lifecycle.REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_AUTHORITY_SCHEMA,
        "id": "review-team-digest-migration-candidate.test",
        "migration_authority_proposal_sha256": plan_authority["proposal_sha256"],
        "migration_authority_consumed_act_carrier_sha256": plan_authority[
            "consumed_act_carrier_sha256"
        ],
        "frozen_inventory_canonical_sha256": plan_authority["frozen_inventory_canonical_sha256"],
        "candidate_artifact_core_sha256": binding_core["candidate_artifact_core_sha256"],
        "disposition_manifest_sha256": binding_core["disposition_manifest_sha256"],
        "write_set_sha256": binding_core["write_set_sha256"],
        "evidence_manifest_sha256": binding_core["evidence_manifest_sha256"],
        "plan_sha256": plan_sha,
        "candidate_carrier_locator": locator,
    }
    candidate_sha = sdlc_lifecycle._canonical_json_sha256(candidate)
    payload = {
        "schema": sdlc_lifecycle.REVIEW_TEAM_DIGEST_MIGRATION_PREPARED_PLAN_SCHEMA,
        "generated_at": "2026-07-14T03:00:30+00:00",
        "repo": "owner/repo",
        "authority": plan_authority,
        "artifact_preflight": {
            "status": "migration_artifact_absent",
            "artifact_path": "review-team-digest-migration.yaml",
            "artifact_sha256": None,
            "blockers": [],
        },
        "snapshots": [],
        "open_pr_results": [],
        "migration": plan_migration,
        "receipt_writes": receipt_writes,
        "evidence_manifest": evidence_manifest,
        "lock_transition": lock_transition,
        "plan_binding_core": binding_core,
        "candidate_authority": candidate,
        "candidate_authority_sha256": candidate_sha,
        "candidate_authority_response": (
            f"RATIFY {candidate['id']} candidate_authority_sha256={candidate_sha}"
        ),
        "acceptance_admission_trace": [],
        "recovery_policy": dict(sdlc_lifecycle.REVIEW_TEAM_DIGEST_MIGRATION_RECOVERY_POLICY),
        "assertions": dict(sdlc_lifecycle.REVIEW_TEAM_DIGEST_MIGRATION_APPLY_ASSERTIONS),
    }
    return candidate, candidate_sha, payload, locator


@pytest.fixture(autouse=True)
def _restore_review_team_digest_migration_source_anchor() -> Iterator[None]:
    source_anchor = dict(sdlc_lifecycle.REVIEW_TEAM_DIGEST_MIGRATION_SOURCE_TRUST_ANCHOR)
    yield
    sdlc_lifecycle.REVIEW_TEAM_DIGEST_MIGRATION_SOURCE_TRUST_ANCHOR.clear()
    sdlc_lifecycle.REVIEW_TEAM_DIGEST_MIGRATION_SOURCE_TRUST_ANCHOR.update(source_anchor)


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
        extra_entries: list[dict[str, object]] | None = None,
        frozen_entries: list[dict[str, object]] | None = None,
    ) -> Path:
        if frozen_entries is None:
            frozen_entries = [
                {
                    "task_id": task_id,
                    "receipt_basename": receipt_basename,
                    "receipt_sha256": receipt_sha256,
                }
            ]
        frozen_digest = hashlib.sha256(
            json.dumps(frozen_entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        proposal = tmp_path / "ratified-proposal.yaml"
        proposal_id = "test-digest-migration-v4"
        proposal.write_text(
            yaml.safe_dump(
                {
                    "id": proposal_id,
                    "case_id": "CASE-TEST",
                    "frozen_prebinding_inventory": {
                        "count": len(frozen_entries),
                        "canonical_sha256": frozen_digest,
                        "entries": frozen_entries,
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        proposal_sha = hashlib.sha256(proposal.read_bytes()).hexdigest()
        carrier = tmp_path / "consumed-carrier.yaml"
        carrier.write_text(
            yaml.safe_dump(
                {
                    "schema": "hapax.test-carrier.v1",
                    "id": proposal_id,
                    "status": "consumed_active",
                    "consumed_at": "2026-07-14T03:00:00+00:00",
                    "proposal": {"path": str(proposal), "sha256": proposal_sha},
                    "operator_act": {
                        "exact_response_utf8_no_lf": (
                            f"RATIFY {proposal_id} proposal_sha256={proposal_sha}"
                        ),
                        "matched_id": True,
                        "matched_proposal_sha256": True,
                        "authority_minted": True,
                        "authority_limited_to_proposal": True,
                    },
                    "frozen_prebinding_inventory_canonical_sha256": frozen_digest,
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        carrier_sha = hashlib.sha256(carrier.read_bytes()).hexdigest()
        source_anchor = {
            "proposal_id": proposal_id,
            "proposal_sha256": proposal_sha,
            "consumed_act_carrier_sha256": carrier_sha,
            "frozen_inventory_canonical_sha256": frozen_digest,
            "legacy_unsealed_artifact_sha256": "a" * 64,
            "authority_case": "CASE-TEST",
        }
        sdlc_lifecycle.REVIEW_TEAM_DIGEST_MIGRATION_SOURCE_TRUST_ANCHOR.clear()
        sdlc_lifecycle.REVIEW_TEAM_DIGEST_MIGRATION_SOURCE_TRUST_ANCHOR.update(source_anchor)
        entries = [
            {
                "task_id": task_id,
                "task_note_basename": f"{task_id}.md",
                "receipt_basename": receipt_basename,
                "receipt_relpath": receipt_basename,
                "receipt_sha256": receipt_sha256,
                "classification": classification,
                "reason": "non_replayable_or_moved_head_exact_hash_preservation"
                if classification == REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION
                else "current_open_pr_replay_rebound",
            }
        ]
        if classification == REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION:
            entries[0]["legacy_admission"] = {
                "route": REVIEW_TEAM_DIGEST_MIGRATION_LEGACY_ROUTE,
                "source_trust_anchor": source_anchor,
                "sealed_generation_id": f"{proposal_id}.{proposal_sha[:12]}.{carrier_sha[:12]}",
                "sealed_generation_source_head_sha": "a" * 40,
                "receipt_sha256": receipt_sha256,
                "classification": classification,
            }
        entries.extend(extra_entries or [])
        path = tmp_path / REVIEW_TEAM_DIGEST_MIGRATION_FILENAME
        path.write_text(
            yaml.safe_dump(
                {
                    "schema": REVIEW_TEAM_DIGEST_MIGRATION_SCHEMA,
                    "generated_at": "2026-07-14T03:00:00+00:00",
                    "authority": {
                        "proposal_path": str(proposal),
                        "proposal_sha256": proposal_sha,
                        "proposal_id": proposal_id,
                        "case_id": "CASE-TEST",
                        "consumed_act_carrier_path": str(carrier),
                        "consumed_act_carrier_sha256": carrier_sha,
                        "consumed_act_carrier_schema": "hapax.test-carrier.v1",
                        "consumed_act_carrier_status": "consumed_active",
                        "consumed_at": "2026-07-14T03:00:00+00:00",
                        "operator_act_response": (
                            f"RATIFY {proposal_id} proposal_sha256={proposal_sha}"
                        ),
                        "frozen_inventory_canonical_sha256": frozen_digest,
                        "frozen_inventory_count": len(frozen_entries),
                        "legacy_unsealed_artifact_sha256": "a" * 64,
                        "source_trust_anchor": source_anchor,
                    },
                    "authority_proposal_id": proposal_id,
                    "sealed_generation": {
                        "id": f"{proposal_id}.{proposal_sha[:12]}.{carrier_sha[:12]}",
                        "sealed_at": "2026-07-14T03:00:00+00:00",
                        "source_head_sha": "a" * 40,
                    },
                    "frozen_prebinding_inventory": {
                        "count": len(frozen_entries),
                        "canonical_sha256": frozen_digest,
                        "entries": frozen_entries,
                    },
                    "active_dir": str(tmp_path.resolve()),
                    "pause_boundary": REVIEW_TEAM_DIGEST_MIGRATION_PAUSE_BOUNDARY,
                    "integrity_recheck": REVIEW_TEAM_DIGEST_MIGRATION_INTEGRITY_RECHECK,
                    "entries": entries,
                    "counts": {
                        "rebound": 0,
                        REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION: sum(
                            1
                            for entry in entries
                            if entry.get("classification")
                            == REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION
                        ),
                        "stale-invalid": sum(
                            1 for entry in entries if entry.get("classification") == "stale-invalid"
                        ),
                        "unmatched": 0,
                        "not-subject": 0,
                    },
                    "next_actions": dict(REVIEW_TEAM_DIGEST_MIGRATION_NEXT_ACTIONS),
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return path

    def _candidate_authorized_reclassification(
        self,
        migration: Path,
        *,
        write_carrier: bool = True,
        carrier_mutator: Callable[[dict[str, object]], None] | None = None,
        prepared_plan_mutator: Callable[[dict[str, object]], None] | None = None,
    ) -> dict[str, object]:
        loaded = yaml.safe_load(migration.read_text(encoding="utf-8"))
        entry = loaded["entries"][0]
        entry["classification"] = "rebound"
        entry["reason"] = "current_open_pr_replay_rebound"
        entry.pop("legacy_admission", None)
        loaded["counts"] = {
            "rebound": 1,
            REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION: 0,
            "stale-invalid": 0,
            "unmatched": 0,
            "not-subject": 0,
        }

        candidate, candidate_sha, prepared_plan_payload, locator = _coherent_prepared_plan_chain(
            artifact=loaded,
            entries=loaded["entries"],
        )
        loaded["candidate_authority"] = {
            **candidate,
            "candidate_authority_sha256": candidate_sha,
        }
        migration.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")

        if write_carrier:
            if prepared_plan_mutator is not None:
                prepared_plan_mutator(prepared_plan_payload)
            prepared_plan_raw = json.dumps(
                prepared_plan_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            carrier = {
                "schema": sdlc_lifecycle.REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_CARRIER_SCHEMA,
                "id": candidate["id"],
                "status": "consumed_active",
                "consumed_at": "2026-07-14T03:00:30+00:00",
                "candidate_authority": candidate,
                "candidate_authority_sha256": candidate_sha,
                "candidate_carrier_locator": locator,
                "prepared_plan_file_sha256": "sha256:"
                + hashlib.sha256(prepared_plan_raw).hexdigest(),
                "prepared_plan_canonical_sha256": sdlc_lifecycle._canonical_json_sha256(
                    prepared_plan_payload
                ),
                "prepared_plan_raw_bytes_hex": prepared_plan_raw.hex(),
                "operator_act": {
                    "exact_response_utf8_no_lf": (
                        f"RATIFY {candidate['id']} candidate_authority_sha256={candidate_sha}"
                    ),
                    "matched_id": True,
                    "matched_candidate_authority_sha256": True,
                    "authority_minted": True,
                    "authority_limited_to_candidate": True,
                },
            }
            if carrier_mutator is not None:
                carrier_mutator(carrier)
            (migration.parent / locator).write_text(
                yaml.safe_dump(carrier, sort_keys=False),
                encoding="utf-8",
            )
        return loaded

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
        admission = acceptance_receipt_admission_route(frontmatter, note)
        assert admission["route"] == REVIEW_TEAM_DIGEST_MIGRATION_LEGACY_ROUTE
        assert admission["receipt_sha256"] == receipt_sha
        assert admission["legacy_admission"]["classification"] == (
            REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION
        )

        receipt.write_text(
            receipt.read_text(encoding="utf-8") + "tampered: true\n",
            encoding="utf-8",
        )
        assert "acceptance_receipt_digest_migration_sha256_mismatch" in (
            acceptance_receipt_blockers(frontmatter, note)
        )

    def test_post_freeze_review_team_receipt_remains_rejected_when_manually_listed(
        self, tmp_path: Path
    ) -> None:
        note = self._note(tmp_path, "task-r", {"quality_floor": "frontier_review_required"})
        receipt = self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace(
                "acceptor: operator", "acceptor: review-team:codex,glm"
            ).replace("timestamp: 2026-06-10T17:00:00Z", "timestamp: 2026-05-01T00:00:00Z"),
        )
        receipt_sha = "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest()
        self._migration(tmp_path, receipt_sha256=receipt_sha, frozen_entries=[])
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))

        blockers = acceptance_receipt_blockers(frontmatter, note)

        assert "acceptance_receipt_review_team_dossier_sha256_missing" in blockers
        assert "acceptance_receipt_digest_migration_post_cutover_unlisted" in blockers

    def test_digest_migration_authority_tamper_fails_closed(self, tmp_path: Path) -> None:
        note = self._note(tmp_path, "task-r", {"quality_floor": "frontier_review_required"})
        receipt = self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm"),
        )
        receipt_sha = "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest()
        migration = self._migration(tmp_path, receipt_sha256=receipt_sha)
        loaded = yaml.safe_load(migration.read_text(encoding="utf-8"))
        loaded["authority"]["proposal_sha256"] = "0" * 64
        migration.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))

        blockers = acceptance_receipt_blockers(frontmatter, note)

        assert "acceptance_receipt_review_team_dossier_sha256_missing" in blockers
        assert "acceptance_receipt_digest_migration_source_anchor_proposal_sha256_mismatch" in (
            blockers
        )

    def test_digest_migration_missing_legacy_admission_fails_closed(self, tmp_path: Path) -> None:
        note = self._note(tmp_path, "task-r", {"quality_floor": "frontier_review_required"})
        receipt = self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm"),
        )
        receipt_sha = "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest()
        migration = self._migration(tmp_path, receipt_sha256=receipt_sha)
        loaded = yaml.safe_load(migration.read_text(encoding="utf-8"))
        loaded["entries"][0].pop("legacy_admission")
        migration.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))

        blockers = acceptance_receipt_blockers(frontmatter, note)

        assert "acceptance_receipt_digest_migration_legacy_admission_missing" in blockers

    def test_digest_migration_empty_seal_maps_fail_closed(self, tmp_path: Path) -> None:
        note = self._note(tmp_path, "task-r", {"quality_floor": "frontier_review_required"})
        receipt = self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm"),
        )
        receipt_sha = "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest()
        migration = self._migration(tmp_path, receipt_sha256=receipt_sha)
        loaded = yaml.safe_load(migration.read_text(encoding="utf-8"))
        loaded["authority"] = {}
        loaded["sealed_generation"] = {}
        loaded["frozen_prebinding_inventory"] = {}
        migration.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))

        blockers = acceptance_receipt_blockers(frontmatter, note)

        assert "acceptance_receipt_digest_migration_sealed_migration_authority_missing" in blockers
        assert "acceptance_receipt_digest_migration_sealed_migration_generation_missing" in blockers
        assert (
            "acceptance_receipt_digest_migration_sealed_migration_frozen_inventory_missing"
            in blockers
        )

    def test_digest_migration_self_consistent_forged_generation_fails_closed(
        self, tmp_path: Path
    ) -> None:
        note = self._note(tmp_path, "task-r", {"quality_floor": "frontier_review_required"})
        receipt = self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm"),
        )
        receipt_sha = "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest()
        migration = self._migration(tmp_path, receipt_sha256=receipt_sha)
        loaded = yaml.safe_load(migration.read_text(encoding="utf-8"))
        forged_id = "forged-generation.000000000000.111111111111"
        loaded["sealed_generation"]["id"] = forged_id
        loaded["entries"][0]["legacy_admission"]["sealed_generation_id"] = forged_id
        migration.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))

        blockers = acceptance_receipt_blockers(frontmatter, note)

        assert (
            "acceptance_receipt_digest_migration_sealed_migration_generation_id_mismatch"
            in blockers
        )

    @pytest.mark.parametrize(
        ("mutation", "expected_blocker"),
        (
            (
                "declared_frozen_digest",
                "sealed_migration_frozen_inventory_sha256_mismatch",
            ),
            ("entry_reason", "sealed_migration_entry_reason_mismatch:task-r"),
            (
                "task_note_basename",
                "sealed_migration_entry_task_note_basename_mismatch:task-r",
            ),
            ("sealed_at", "sealed_migration_generation_sealed_at_invalid"),
            ("generated_at_naive", "sealed_migration_generated_at_invalid"),
            ("top_level_extra_key", "sealed_migration_top_level_extra_key:unexpected"),
            ("authority_extra_key", "sealed_migration_authority_extra_key:unexpected"),
            (
                "self_consistent_reclassification",
                "sealed_migration_frozen_tuple_reclassified:task-r:rebound",
            ),
            ("active_dir_other_absolute", "sealed_migration_active_dir_mismatch"),
            (
                "next_actions_bad_value",
                "sealed_migration_next_actions_value_mismatch:rebound",
            ),
        ),
    )
    def test_digest_migration_total_contract_rejects_forged_coherent_fields(
        self,
        tmp_path: Path,
        mutation: str,
        expected_blocker: str,
    ) -> None:
        receipt = self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm"),
        )
        receipt_sha = "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest()
        migration = self._migration(tmp_path, receipt_sha256=receipt_sha)
        loaded = yaml.safe_load(migration.read_text(encoding="utf-8"))

        if mutation == "declared_frozen_digest":
            loaded["frozen_prebinding_inventory"]["canonical_sha256"] = "0" * 64
        elif mutation == "entry_reason":
            loaded["entries"][0]["reason"] = "acceptor_not_review_team"
        elif mutation == "task_note_basename":
            loaded["entries"][0]["task_note_basename"] = "other-task.md"
        elif mutation == "sealed_at":
            loaded["sealed_generation"]["sealed_at"] = "not-a-real-timestamp"
        elif mutation == "generated_at_naive":
            loaded["generated_at"] = "2026-07-14T03:00:00"
        elif mutation == "top_level_extra_key":
            loaded["unexpected"] = True
        elif mutation == "authority_extra_key":
            loaded["authority"]["unexpected"] = True
        elif mutation == "self_consistent_reclassification":
            loaded["entries"][0]["classification"] = "rebound"
            loaded["entries"][0]["reason"] = "current_open_pr_replay_rebound"
            loaded["entries"][0].pop("legacy_admission")
            loaded["counts"][REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION] = 0
            loaded["counts"]["rebound"] = 1
        elif mutation == "active_dir_other_absolute":
            other_active = tmp_path / "other-active"
            other_active.mkdir()
            loaded["active_dir"] = str(other_active.resolve())
        elif mutation == "next_actions_bad_value":
            loaded["next_actions"]["rebound"] = "arbitrary text"
        else:
            raise AssertionError(mutation)

        blockers = sdlc_lifecycle.review_team_digest_migration_artifact_blockers(
            loaded,
            expected_active_dir=tmp_path,
        )

        assert expected_blocker in blockers

    def test_digest_migration_reclassified_candidate_requires_consumed_carrier(
        self, tmp_path: Path
    ) -> None:
        receipt = self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm"),
        )
        receipt_sha = "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest()
        migration = self._migration(tmp_path, receipt_sha256=receipt_sha)
        loaded = self._candidate_authorized_reclassification(migration, write_carrier=False)

        blockers = sdlc_lifecycle.review_team_digest_migration_artifact_blockers(
            loaded,
            expected_active_dir=tmp_path,
        )

        assert "sealed_migration_candidate_authority_carrier_unreadable:FileNotFoundError" in (
            blockers
        )

    def test_digest_migration_reclassified_candidate_proves_consumed_carrier(
        self, tmp_path: Path
    ) -> None:
        receipt = self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm"),
        )
        receipt_sha = "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest()
        migration = self._migration(tmp_path, receipt_sha256=receipt_sha)
        loaded = self._candidate_authorized_reclassification(migration)

        blockers = sdlc_lifecycle.review_team_digest_migration_artifact_blockers(
            loaded,
            expected_active_dir=tmp_path,
        )

        assert blockers == ()

    def test_digest_migration_reclassified_candidate_requires_embedded_plan_bytes(
        self, tmp_path: Path
    ) -> None:
        receipt = self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm"),
        )
        receipt_sha = "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest()
        migration = self._migration(tmp_path, receipt_sha256=receipt_sha)

        def remove_prepared_plan_bytes(carrier: dict[str, object]) -> None:
            carrier.pop("prepared_plan_raw_bytes_hex", None)

        loaded = self._candidate_authorized_reclassification(
            migration,
            carrier_mutator=remove_prepared_plan_bytes,
        )

        blockers = sdlc_lifecycle.review_team_digest_migration_artifact_blockers(
            loaded,
            expected_active_dir=tmp_path,
        )

        assert (
            "sealed_migration_candidate_authority_carrier_missing_key:prepared_plan_raw_bytes_hex"
        ) in blockers

    def test_v12_probe_20_carrier_cannot_embed_semantically_empty_prepared_plan(
        self, tmp_path: Path
    ) -> None:
        """A self-consistently re-hashed empty plan must not pass as prepared-plan authority.

        V12-PROBE-20 replaced the embedded plan with canonical ``{}`` and updated only the
        carrier's own digest claims. Hashing alone cannot catch that: lifecycle must decode the
        plan and re-derive its binding chain.
        """

        receipt = self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm"),
        )
        receipt_sha = "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest()
        migration = self._migration(tmp_path, receipt_sha256=receipt_sha)

        def empty_the_plan(carrier: dict[str, object]) -> None:
            empty_raw = json.dumps({}, sort_keys=True, separators=(",", ":")).encode("utf-8")
            carrier["prepared_plan_raw_bytes_hex"] = empty_raw.hex()
            # Keep the carrier internally self-consistent, exactly as the probe did.
            carrier["prepared_plan_file_sha256"] = "sha256:" + hashlib.sha256(empty_raw).hexdigest()
            carrier["prepared_plan_canonical_sha256"] = sdlc_lifecycle._canonical_json_sha256({})

        loaded = self._candidate_authorized_reclassification(
            migration,
            carrier_mutator=empty_the_plan,
        )

        blockers = sdlc_lifecycle.review_team_digest_migration_artifact_blockers(
            loaded,
            expected_active_dir=tmp_path,
        )

        assert (
            "sealed_migration_candidate_authority_carrier_prepared_plan_schema_mismatch"
        ) in blockers

    @staticmethod
    def _retitle_candidate(plan: dict[str, Any]) -> None:
        """Change a value inside the plan's candidate authority, keeping its key set exact.

        The tamper has to be shape-valid to reach the digest relation: a candidate authority with
        the wrong KEYS dies at the key check, which proves nothing about whether the decoder
        actually re-derives the candidate digest.
        """

        plan["candidate_authority"] = {
            **plan["candidate_authority"],
            "id": "review-team-digest-migration-candidate.someone-else",
        }

    @staticmethod
    def _forge_disposition_manifest(plan: dict[str, Any]) -> None:
        plan["plan_binding_core"] = {
            **plan["plan_binding_core"],
            "disposition_manifest": {
                "schema": sdlc_lifecycle.REVIEW_TEAM_DIGEST_MIGRATION_DISPOSITION_MANIFEST_SCHEMA,
                "entries": [],
            },
        }

    @staticmethod
    def _forge_write_set(plan: dict[str, Any]) -> None:
        plan["plan_binding_core"] = {
            **plan["plan_binding_core"],
            "write_set": {
                "schema": sdlc_lifecycle.REVIEW_TEAM_DIGEST_MIGRATION_WRITE_SET_SCHEMA,
                "writes": [{"kind": "acceptance_receipt", "path": "/etc/passwd", "sha256": "x"}],
            },
        }

    @staticmethod
    def _break_recovery_policy(plan: dict[str, Any]) -> None:
        plan["recovery_policy"] = {}

    @staticmethod
    def _break_receipt_writes(plan: dict[str, Any]) -> None:
        plan["receipt_writes"] = "not-a-list"

    @pytest.mark.parametrize(
        ("mutate", "expected"),
        [
            (
                lambda plan: plan.update(
                    {"schema": "hapax.review_team_digest_migration.prepared_plan.v1"}
                ),
                "sealed_migration_candidate_authority_carrier_prepared_plan_schema_mismatch",
            ),
            (
                _retitle_candidate,
                "sealed_migration_candidate_authority_carrier_prepared_plan"
                "_candidate_authority_sha256_mismatch",
            ),
            (
                lambda plan: plan.update({"candidate_authority_response": "RATIFY someone-else"}),
                "sealed_migration_candidate_authority_carrier_prepared_plan"
                "_candidate_authority_response_mismatch",
            ),
            (
                lambda plan: plan.update({"migration": {"artifact_written": True}}),
                "sealed_migration_candidate_authority_carrier_prepared_plan"
                "_migration_artifact_written_invalid",
            ),
            (
                lambda plan: plan.update(
                    {
                        "plan_binding_core": {
                            **plan["plan_binding_core"],
                            "plan_sha256": "sha256:" + "9" * 64,
                        }
                    }
                ),
                "sealed_migration_candidate_authority_carrier_prepared_plan"
                "_binding_core_plan_sha256_mismatch",
            ),
            # V12-PROBE-34, at the lifecycle boundary: a forged manifest or write set that keeps its
            # old claimed digest is recomputed and caught, not believed.
            (
                _forge_disposition_manifest,
                "sealed_migration_candidate_authority_carrier_prepared_plan"
                "_binding_core_disposition_manifest_mismatch",
            ),
            (
                _forge_write_set,
                "sealed_migration_candidate_authority_carrier_prepared_plan"
                "_binding_core_write_set_mismatch",
            ),
            # V12-PROBE-29: protocol constants and nested container types are total.
            (
                _break_recovery_policy,
                "sealed_migration_candidate_authority_carrier_prepared_plan"
                "_recovery_policy_mismatch",
            ),
            (
                _break_receipt_writes,
                "sealed_migration_candidate_authority_carrier_prepared_plan"
                "_receipt_writes_not_list",
            ),
        ],
    )
    def test_v12_embedded_prepared_plan_decoder_matrix(
        self, tmp_path: Path, mutate: Callable[[dict[str, Any]], None], expected: str
    ) -> None:
        receipt = self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm"),
        )
        receipt_sha = "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest()
        migration = self._migration(tmp_path, receipt_sha256=receipt_sha)

        loaded = self._candidate_authorized_reclassification(
            migration,
            prepared_plan_mutator=mutate,
        )

        blockers = sdlc_lifecycle.review_team_digest_migration_artifact_blockers(
            loaded,
            expected_active_dir=tmp_path,
        )

        assert expected in blockers

    def test_v12_probe_29_lifecycle_uses_the_exact_runtime_plan_decoder(
        self, tmp_path: Path
    ) -> None:
        """V12-PROBE-29: the grossly malformed nested plan that lifecycle used to admit.

        The probe embedded snapshots=7, open_pr_results="not-a-list", receipt_writes={not: a-list},
        recovery_policy={} and assertions={}, re-hashed the carrier so it was self-consistent, and
        lifecycle returned no blockers. Lifecycle now runs the same exact decoder as the runtime, so
        every one of those is named.
        """

        receipt = self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm"),
        )
        receipt_sha = "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest()
        migration = self._migration(tmp_path, receipt_sha256=receipt_sha)

        def malform(plan: dict[str, Any]) -> None:
            plan["snapshots"] = 7
            plan["open_pr_results"] = "not-a-list"
            plan["receipt_writes"] = {"not": "a-list"}
            plan["recovery_policy"] = {}
            plan["assertions"] = {}

        loaded = self._candidate_authorized_reclassification(
            migration,
            prepared_plan_mutator=malform,
        )

        blockers = sdlc_lifecycle.review_team_digest_migration_artifact_blockers(
            loaded,
            expected_active_dir=tmp_path,
        )
        prefix = "sealed_migration_candidate_authority_carrier_prepared_plan"
        # The reason vocabulary is the RUNTIME's, because there is only one decoder now: lifecycle
        # does not merely reject the same plans, it rejects them for the same named reasons.
        for reason in (
            f"{prefix}_snapshot_not_list",
            f"{prefix}_open_pr_result_not_list",
            f"{prefix}_receipt_writes_not_list",
            f"{prefix}_recovery_policy_mismatch",
            f"{prefix}_assertions_mismatch",
        ):
            assert reason in blockers, f"lifecycle admitted a malformed plan: {reason} not named"

    @staticmethod
    def _receipt_write(payload: object, raw: bytes) -> list[dict[str, object]]:
        return [
            {
                "kind": "acceptance_receipt",
                "path": "/vault/active/task-a.acceptance.yaml",
                "archive_path": None,
                "existing_sha256": None,
                "payload": payload,
                "raw_bytes_hex": raw.hex(),
                "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "target_preimage": {
                    "evidence": {"path": "/vault/active/x", "exists": False},
                    "read_error": "",
                },
            }
        ]

    def test_v12_probe_45_receipt_payload_is_bound_to_the_bytes_that_will_be_written(self) -> None:
        """V12-PROBE-45 / V12-STATIC-07: a receipt payload is not a claim BESIDE its bytes.

        ``payload`` and ``raw_bytes_hex`` were two independently mutable descriptions of one write,
        and only the bytes were digest-bound. So the payload could say one thing while the bytes that
        actually landed on disk said another, and every digest in the plan still agreed.
        """

        receipt = {
            "acceptor": "review-team:codex",
            "verdict": "accepted",
            "timestamp": "2026-07-14T04:00:00+00:00",
            "artifact": "https://github.com/owner/repo/pull/1",
            "dossier_sha256": "sha256:" + "a" * 64,
        }
        raw = yaml.safe_dump(receipt, sort_keys=False).encode("utf-8")

        _writes, clean = sdlc_lifecycle._decode_prepared_plan_receipt_writes(
            self._receipt_write(dict(receipt), raw)
        )
        assert clean == [], f"a faithful receipt write must decode: {clean}"

        # Same bytes, same digest -- a payload that lies about what those bytes say.
        forged = dict(receipt, acceptor="operator:someone-else")
        _writes, blockers = sdlc_lifecycle._decode_prepared_plan_receipt_writes(
            self._receipt_write(forged, raw)
        )
        assert "migration_prepared_plan_receipt_write_payload:0_bytes_mismatch" in blockers

        # And an outright non-mapping payload is still refused by kind.
        _writes, blockers = sdlc_lifecycle._decode_prepared_plan_receipt_writes(
            self._receipt_write([], raw)
        )
        assert "migration_prepared_plan_receipt_write_payload:0_not_mapping" in blockers

    @pytest.mark.parametrize(
        ("mutate", "expected"),
        [
            # A receipt with no verdict is not an acceptance receipt, however well its bytes bind.
            (
                lambda r: r.pop("verdict"),
                "migration_prepared_plan_receipt_write_payload:0_missing_field:verdict",
            ),
            # A REJECTED receipt would be written to a receipt path and then refused by the gate
            # that reads it back. The plan that plans to write it must die first.
            (
                lambda r: r.__setitem__("verdict", "rejected"),
                "migration_prepared_plan_receipt_write_payload:0_verdict_not_accepted:rejected",
            ),
            (
                lambda r: r.pop("timestamp"),
                "migration_prepared_plan_receipt_write_payload:0_missing_field:timestamp",
            ),
            # A review-team receipt whose dossier digest is not a digest.
            (
                lambda r: r.__setitem__("dossier_sha256", "not-a-digest"),
                "migration_prepared_plan_receipt_write_payload:0_dossier_sha256_malformed",
            ),
        ],
    )
    def test_v12_probe_57_receipt_write_payload_is_decoded_as_a_receipt(
        self, mutate: Any, expected: str
    ) -> None:
        """The bytes a plan will write to a RECEIPT path must decode under the RECEIPT schema.

        Binding the payload to its bytes proved only that the two agreed. It never proved the
        document was an acceptance receipt at all, so a plan could carry -- fully digest-bound,
        byte-exact and operator-ratified -- a write of a document that the very next surface to read
        it back would refuse. The schema is owed at plan-decode time.
        """

        receipt: dict[str, Any] = {
            "acceptor": "review-team:codex",
            "verdict": "accepted",
            "timestamp": "2026-07-14T04:00:00+00:00",
            "artifact": "https://github.com/owner/repo/pull/1",
            "dossier_sha256": "sha256:" + "a" * 64,
        }
        mutate(receipt)
        raw = yaml.safe_dump(receipt, sort_keys=False).encode("utf-8")

        _writes, blockers = sdlc_lifecycle._decode_prepared_plan_receipt_writes(
            self._receipt_write(dict(receipt), raw)
        )

        assert expected in blockers, f"expected {expected!r}, got {blockers}"

    def test_v12_embedded_prepared_plan_binds_candidate_authority_chain(
        self, tmp_path: Path
    ) -> None:
        receipt = self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm"),
        )
        receipt_sha = "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest()
        migration = self._migration(tmp_path, receipt_sha256=receipt_sha)

        loaded = self._candidate_authorized_reclassification(migration)

        assert (
            sdlc_lifecycle.review_team_digest_migration_artifact_blockers(
                loaded,
                expected_active_dir=tmp_path,
            )
            == ()
        )

    def test_digest_migration_reclassified_candidate_rejects_forged_carrier_act(
        self, tmp_path: Path
    ) -> None:
        receipt = self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm"),
        )
        receipt_sha = "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest()
        migration = self._migration(tmp_path, receipt_sha256=receipt_sha)

        def forge_operator_act(carrier: dict[str, object]) -> None:
            operator_act = carrier["operator_act"]
            assert isinstance(operator_act, dict)
            operator_act["exact_response_utf8_no_lf"] = "RATIFY forged"

        loaded = self._candidate_authorized_reclassification(
            migration,
            carrier_mutator=forge_operator_act,
        )

        blockers = sdlc_lifecycle.review_team_digest_migration_artifact_blockers(
            loaded,
            expected_active_dir=tmp_path,
        )

        assert "sealed_migration_candidate_authority_carrier_response_mismatch" in blockers

    # ---- V12-PROBE-37: lifecycle runs the NESTED decoder, not just the relation subset --------

    @pytest.mark.parametrize(
        ("mutate", "expected"),
        [
            (
                lambda plan: plan.__setitem__("open_pr_results", [{"status": []}]),
                "open_pr_result_item:0_status_not_string",
            ),
            (
                lambda plan: plan["migration"].__setitem__("counts", []),
                "migration_counts_not_mapping",
            ),
            (
                lambda plan: plan["artifact_preflight"].__setitem__("blockers", {}),
                "artifact_preflight_blockers_not_list",
            ),
        ],
        ids=["open_pr_status_list", "migration_counts_list", "preflight_blockers_mapping"],
    )
    def test_v12_probe_37_lifecycle_decodes_every_nested_field(
        self,
        tmp_path: Path,
        mutate: Callable[[dict[str, Any]], None],
        expected: str,
    ) -> None:
        """V12-PROBE-37: lifecycle ran only the RELATION subset of the plan decoder.

        The runtime rejected these three shapes -- a list-valued open-PR status, a list-valued
        migration.counts, a mapping-valued preflight blocker list -- while lifecycle admitted the
        identical canonicalized bytes with no blockers at all. Two surfaces that reject different
        plans are two decoders, however much the relation checks they share happen to agree.
        """

        receipt = self._receipt(
            tmp_path,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm"),
        )
        receipt_sha = "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest()
        migration = self._migration(tmp_path, receipt_sha256=receipt_sha)

        loaded = self._candidate_authorized_reclassification(
            migration,
            prepared_plan_mutator=mutate,
        )

        blockers = sdlc_lifecycle.review_team_digest_migration_artifact_blockers(
            loaded,
            expected_active_dir=tmp_path,
        )

        # The reason is the RUNTIME's, re-rooted at the carrier: one decoder, one vocabulary.
        assert (
            f"sealed_migration_candidate_authority_carrier_prepared_plan_{expected}" in blockers
        ), f"lifecycle admitted a plan the runtime rejects: {blockers}"

    def test_closed_note_without_active_sibling_reports_unrecognized_layout(
        self, tmp_path: Path
    ) -> None:
        closed = tmp_path / "closed"
        closed.mkdir()
        note = self._note(closed, "task-r", {"quality_floor": "frontier_review_required"})
        self._receipt(
            closed,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm"),
        )
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))

        blockers = acceptance_receipt_blockers(frontmatter, note)

        assert "acceptance_receipt_digest_migration_unrecognized_vault_layout" in blockers
        assert blockers[-1] == "acceptance_receipt_review_team_dossier_sha256_missing"

    def test_moved_task_note_resolves_canonical_active_migration_artifact(
        self, tmp_path: Path
    ) -> None:
        active = tmp_path / "active"
        closed = tmp_path / "closed"
        active.mkdir()
        closed.mkdir()
        note = self._note(closed, "task-r", {"quality_floor": "frontier_review_required"})
        receipt = self._receipt(
            closed,
            "task-r",
            self.VALID_RECEIPT.replace("acceptor: operator", "acceptor: review-team:codex,glm"),
        )
        receipt_sha = "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest()
        self._migration(active, receipt_sha256=receipt_sha)
        frontmatter = frontmatter_from_text(note.read_text(encoding="utf-8"))

        assert acceptance_receipt_blockers(frontmatter, note) == ()

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
            extra_entries=[
                {
                    "task_id": "task-r",
                    "receipt_basename": "other.acceptance.yaml",
                    "receipt_sha256": receipt_sha,
                    "classification": REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION,
                }
            ],
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

        assert acceptance_receipt_blockers(frontmatter, note) == (
            "acceptance_receipt_task_id_invalid",
        )

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
        assert acceptance_receipt_blockers(frontmatter, note) == (
            "acceptance_receipt_task_id_missing",
        )
