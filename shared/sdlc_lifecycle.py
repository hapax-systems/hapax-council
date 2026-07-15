"""Shared SDLC lifecycle vocabulary and markdown closure helpers."""

from __future__ import annotations

import hashlib
import json
import math
import re
import stat as stat_module
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

TASK_ACTIVE_STATUSES = frozenset(
    {
        "offered",
        "claimed",
        "in_progress",
        "blocked",
        "pr_open",
        "ci_green",
        "merge_queue",
        "ready",
        "ready_for_review",
        "review_ready",
        "ready_for_merge",
    }
)

TASK_FULFILLING_CLOSED_STATUSES = frozenset(
    {"done", "completed", "complete", "closed", "fulfilled", "resolved"}
)
TASK_NON_FULFILLING_CLOSED_STATUSES = frozenset(
    {
        "withdrawn",
        "withdrawn_stale",
        "superseded",
        "closed_superseded",
        "rejected",
        "refused",
        "not_applicable",
        "deferred",
        "closed_poisoned",
    }
)
TASK_CLOSED_STATUSES = TASK_FULFILLING_CLOSED_STATUSES | TASK_NON_FULFILLING_CLOSED_STATUSES
TASK_TERMINAL_STATUSES = TASK_CLOSED_STATUSES | frozenset({"refused"})

# --- Canonical semantic status groups (coordination reform Phase 2: FM-5/G2) ---
# The single source of truth every status consumer references so the cc-task
# gate, the PR autoqueue, cc-claim/cc-close and the shape check AGREE. Before
# this, each hardcoded its own subset: the gate proceeded only on
# in_progress/claimed/pr_open/merge_queue while the autoqueue admitted the whole
# `ready` family — so ~88 active `ready` tasks were claimable-but-unmutatable
# (stranded). Spec: docs/superpowers/specs/2026-05-30-sdlc-frictionless-self-direction-design.md.

#: A fresh, unheld task may be claimed only from `offered`.
TASK_CLAIMABLE_STATUSES = frozenset({"offered"})

#: Statuses ``hapax-methodology-dispatch`` accepts for (re)dispatch: a fresh
#: claimable task plus the two actively-owned working states. Replaces the literal
#: ``{"offered", "claimed", "in_progress"}`` the dispatcher used to hardcode at its
#: dispatchability check (pinned by tests/shared/test_sdlc_lifecycle.py).
TASK_DISPATCHABLE_STATUSES = TASK_CLAIMABLE_STATUSES | frozenset({"claimed", "in_progress"})

#: Ready-family — implementation done / under review / awaiting merge. Distinct
#: labels accumulated historically; treated as one concept everywhere.
TASK_READY_FAMILY_STATUSES = frozenset(
    {"ci_green", "ready", "ready_for_review", "review_ready", "ready_for_merge"}
)

#: The owning lane may still mutate files in these states (CI fixes, review
#: feedback, merge-queue/closeout maintenance). This is the gate proceed-set —
#: the bash gate's section-9 case MUST match this set (pinned by
#: tests/hooks/test_cc_task_gate.py::TestStatusVocabularyDrift).
TASK_MUTABLE_STATUSES = (
    frozenset({"claimed", "in_progress", "pr_open", "merge_queue"}) | TASK_READY_FAMILY_STATUSES
)

#: PRs the autoqueue may consider for merge admission (the active, not-yet-closed
#: ready states). cc-pr-autoqueue adds the fulfilling-closed states separately.
TASK_MERGE_READY_STATUSES = frozenset({"pr_open", "merge_queue"}) | TASK_READY_FAMILY_STATUSES

#: A lane may RESUME (re-claim) an owned task in these states — not a fresh claim.
TASK_RESUMABLE_STATUSES = TASK_MERGE_READY_STATUSES

BLOCKED_DEPENDENCY_REASON_PREFIX = "waiting_for_closure_valid_dependencies:"
BLOCKED_WITNESS_FIELDS = ("blocked_witness", "blocked_witness_path")
_FRONTMATTER_NULL_SCALARS = frozenset({"", "null", "none", "~", "[]"})

# --- Dispatch-plane vocabulary: PR control actions (NOT statuses, NOT stages) -
#: The autoqueue's ``classify_pr`` (scripts/cc-pr-autoqueue.py) emits a small,
#: closed set of *control actions* deciding what to DO with a PR. This is a
#: third, distinct vocabulary from the task-plane status frozensets above and
#: the proof-plane ladder stages — naming it here gives the three planes one
#: import surface. Pinned total by tests/shared/test_sdlc_lifecycle.py: every
#: action ``classify_pr`` can emit is a member of this set.
PR_ACTIONS = frozenset(
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

REQUEST_TERMINAL_SKIP_STATUSES = frozenset(
    {"rejected", "deferred", "superseded", "withdrawn", "closed"}
)
REQUEST_CLOSEABLE_STATUSES = frozenset(
    {
        "",
        "captured",
        "triage",
        "clarification_needed",
        "clarification_answered",
        "normalized",
        "operator_confirmation",
        "accepted_for_planning",
        "accepted_for_execution",
        "planned",
        "active",
        "phase0_active",
    }
)

ACCEPTANCE_HEADING_RE = re.compile(r"^##\s+Acceptance\s+criteria\s*$", re.IGNORECASE | re.MULTILINE)
UNCHECKED_CHECKBOX_RE = re.compile(r"^\s*-\s+\[\s\]\s+(.*)$", re.MULTILINE)
CHECKED_CHECKBOX_RE = re.compile(r"^\s*-\s+\[[xX]\]\s+(.*)$", re.MULTILINE)
NEXT_HEADING_RE = re.compile(r"^##\s+", re.MULTILINE)


@dataclass(frozen=True)
class AcceptanceCriteriaState:
    section_present: bool
    checked_items: tuple[str, ...]
    unchecked_items: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.unchecked_items


@dataclass(frozen=True)
class TaskClosureValidity:
    """Result for whether a cc-task can satisfy downstream dependencies."""

    valid: bool
    blockers: tuple[str, ...]
    frontmatter: Mapping[str, Any]


PrStateLookup = Callable[[str], str | None]


def acceptance_criteria_section(text: str) -> str | None:
    match = ACCEPTANCE_HEADING_RE.search(text)
    if match is None:
        return None
    start = match.end()
    next_heading = NEXT_HEADING_RE.search(text, pos=start)
    end = next_heading.start() if next_heading else len(text)
    return text[start:end]


def acceptance_criteria_state(text: str) -> AcceptanceCriteriaState:
    section = acceptance_criteria_section(text)
    if section is None:
        return AcceptanceCriteriaState(
            section_present=False,
            checked_items=(),
            unchecked_items=(),
        )
    return AcceptanceCriteriaState(
        section_present=True,
        checked_items=tuple(
            match.group(1).strip() for match in CHECKED_CHECKBOX_RE.finditer(section)
        ),
        unchecked_items=tuple(
            match.group(1).strip() for match in UNCHECKED_CHECKBOX_RE.finditer(section)
        ),
    )


def frontmatter_from_text(text: str) -> dict[str, Any]:
    """Return YAML frontmatter from a markdown note, or an empty mapping."""

    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    raw = text[4:end].strip()
    if not raw:
        return {}
    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError:
        return {}
    if isinstance(loaded, dict):
        return loaded
    return {}


def _frontmatter_scalar(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().strip('"').strip("'")


def _frontmatter_non_null_scalar(value: object) -> str | None:
    scalar = _frontmatter_scalar(value)
    if scalar.lower() in _FRONTMATTER_NULL_SCALARS:
        return None
    return scalar


def blocked_reason_from_frontmatter(frontmatter: Mapping[str, Any]) -> str | None:
    """Return the machine blocker for an active blocked task, if one is present."""

    return _frontmatter_non_null_scalar(frontmatter.get("blocked_reason"))


def blocked_witness_from_frontmatter(frontmatter: Mapping[str, Any]) -> str | None:
    """Return the canonical witness path for an active blocked task, if present."""

    for field in BLOCKED_WITNESS_FIELDS:
        witness = _frontmatter_non_null_scalar(frontmatter.get(field))
        if witness:
            return witness
    return None


def is_dependency_blocked_reason(reason: str | None) -> bool:
    """Whether ``blocked_reason`` is the cascade-managed dependency wait reason."""

    return bool(reason and reason.strip().startswith(BLOCKED_DEPENDENCY_REASON_PREFIX))


def active_blocked_task_blockers(frontmatter: Mapping[str, Any]) -> tuple[str, ...]:
    """Return precise blockers for a task whose frontmatter status is ``blocked``."""

    status = _frontmatter_scalar(frontmatter.get("status")).lower()
    if status != "blocked":
        return ()

    reason = blocked_reason_from_frontmatter(frontmatter)
    witness = blocked_witness_from_frontmatter(frontmatter)
    blockers = [f"blocked_reason:{reason}" if reason else "blocked_reason:missing"]
    if witness:
        blockers.append(f"blocked_witness:{witness}")
    return tuple(blockers)


def is_active_blocked_with_evidence(frontmatter: Mapping[str, Any]) -> bool:
    """True for the stable active blocked-with-evidence lifecycle state."""

    status = _frontmatter_scalar(frontmatter.get("status")).lower()
    reason = blocked_reason_from_frontmatter(frontmatter)
    witness = blocked_witness_from_frontmatter(frontmatter)
    return bool(
        status == "blocked" and reason and witness and not is_dependency_blocked_reason(reason)
    )


# --- Acceptance-receipt enforcement (capacity routing Phase 0.2) -------------
# ``frontier_review_required`` is only honest if acceptance is enforced: a
# review-floor task may close (cc-close) or queue (cc-pr-autoqueue) only with a
# signed review receipt — acceptor identity, verdict, timestamp, artifact ref —
# stored beside the task note as ``<task_id>.acceptance.yaml``. Non-review-floor
# tasks are untouched. Spec: REQ-20260609 model-capability-cost-routing report.

#: The quality floor whose closure demands a signed acceptance receipt.
REVIEW_FLOOR_QUALITY_FLOOR = "frontier_review_required"

#: Receipt filename suffix; the receipt lives beside the task note.
ACCEPTANCE_RECEIPT_SUFFIX = ".acceptance.yaml"

#: Minimal receipt schema — every field must be present and non-null.
ACCEPTANCE_RECEIPT_REQUIRED_FIELDS = ("acceptor", "verdict", "timestamp", "artifact")

#: Verdicts that satisfy the gate. A present-but-rejected receipt still blocks.
ACCEPTANCE_RECEIPT_ACCEPTED_VERDICTS = frozenset({"accepted"})

REVIEW_TEAM_ACCEPTOR_PREFIX = "review-team:"
REVIEW_DOSSIER_SUFFIX = ".review-dossier.yaml"
REVIEW_TEAM_DOSSIER_SHA256_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
REVIEW_TEAM_DIGEST_MIGRATION_FILENAME = "_review-team-digest-migration.yaml"
REVIEW_TEAM_DIGEST_MIGRATION_SCHEMA = "hapax.review_team_digest_migration.v1"
REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION = "exact-hash-preserved"
REVIEW_TEAM_DIGEST_MIGRATION_LEGACY_ROUTE = "legacy_exact_hash_preserved"
REVIEW_TEAM_DIGEST_MIGRATION_SHA256_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
RAW_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
GIT_SHA_RE = re.compile(r"\A[0-9a-f]{40}\Z")
REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_CARRIER_LOCATOR_RE = re.compile(
    r"\Areview-team-digest-migration\.candidate-carrier\.[0-9a-f]{64}\.yaml\Z"
)
REVIEW_TEAM_DIGEST_MIGRATION_SOURCE_TRUST_ANCHOR: dict[str, str] = {
    "proposal_id": "PR4485-p0-sealed-cutover-boundary-final-remediation-20260714-v4",
    "proposal_sha256": "f89439a328e420c194183a772f81b08d2dc6a8cb860d8e3bf6456fb81305ec6e",
    "consumed_act_carrier_sha256": (
        "09d70fcb36485fc1e584243d081d3bf19b6a4d565b2e32bd684b2aa67c926987"
    ),
    "frozen_inventory_canonical_sha256": (
        "df0e9f2f2db610306b7186fe669f5f240f05c1e8b1161b9f2ea1684d5760c0c2"
    ),
    "legacy_unsealed_artifact_sha256": (
        "a87bc1867d07193e7e5d41e024c499d59f205f585b369c00b6da51cf6835dc5c"
    ),
    "authority_case": "CASE-SYSTEM-INTEGRITY-20260611",
}
REVIEW_TEAM_DIGEST_MIGRATION_RUNBOOK = "docs/runbooks/review-team-digest-migration.md"
REVIEW_TEAM_DIGEST_MIGRATION_PAUSE_BOUNDARY = (
    "Run only while hapax-pr-review-dispatch.timer, hapax-pr-review-dispatch.service, "
    "hapax-cc-pr-autoqueue.timer, and hapax-cc-pr-autoqueue.service are paused; "
    "replay-only must not dispatch reviewers or mutate GitHub."
)
REVIEW_TEAM_DIGEST_MIGRATION_INTEGRITY_RECHECK = (
    "Rerun `uv run python scripts/cc-pr-review-dispatch.py --all --replay-only "
    "--migration-recheck` with the same migration-authority flags and require unchanged "
    "sealed authority plus lifecycle validation."
)
REVIEW_TEAM_DIGEST_MIGRATION_CLASSIFICATIONS = frozenset(
    {
        "rebound",
        REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION,
        "stale-invalid",
        "unmatched",
        "not-subject",
    }
)
REVIEW_TEAM_DIGEST_MIGRATION_NEXT_ACTIONS = {
    "rebound": (
        "Receipt was rebound from a current admissible dossier; rerun lifecycle validation "
        "against the digest-bound active receipt."
    ),
    REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION: (
        "Receipt is preserved only while the active receipt bytes match this exact SHA-256; "
        "byte drift requires governed re-review or renewed reconciliation."
    ),
    "stale-invalid": (
        "Do not preserve this receipt; inspect the malformed/stale evidence and rerun a "
        "governed review if acceptance is still required."
    ),
    "unmatched": (
        "No matching active task note was found; restore the governed task identity or rerun "
        "review under a current task before relying on acceptance."
    ),
    "not-subject": (
        "No migration action is needed; the receipt is operator-signed, already digest-bound, "
        "or outside the review-floor gate."
    ),
}
REVIEW_TEAM_DIGEST_MIGRATION_TOP_LEVEL_KEYS = frozenset(
    {
        "schema",
        "generated_at",
        "authority",
        "authority_proposal_id",
        "sealed_generation",
        "frozen_prebinding_inventory",
        "active_dir",
        "pause_boundary",
        "integrity_recheck",
        "entries",
        "counts",
        "next_actions",
    }
)
REVIEW_TEAM_DIGEST_MIGRATION_OPTIONAL_TOP_LEVEL_KEYS = frozenset({"candidate_authority"})
REVIEW_TEAM_DIGEST_MIGRATION_AUTHORITY_KEYS = frozenset(
    {
        "proposal_path",
        "proposal_sha256",
        "proposal_id",
        "case_id",
        "consumed_act_carrier_path",
        "consumed_act_carrier_sha256",
        "consumed_act_carrier_schema",
        "consumed_act_carrier_status",
        "consumed_at",
        "operator_act_response",
        "frozen_inventory_canonical_sha256",
        "frozen_inventory_count",
        "legacy_unsealed_artifact_sha256",
        "source_trust_anchor",
    }
)
REVIEW_TEAM_DIGEST_MIGRATION_SOURCE_ANCHOR_KEYS = frozenset(
    REVIEW_TEAM_DIGEST_MIGRATION_SOURCE_TRUST_ANCHOR
)
REVIEW_TEAM_DIGEST_MIGRATION_GENERATION_KEYS = frozenset({"id", "sealed_at", "source_head_sha"})
REVIEW_TEAM_DIGEST_MIGRATION_FROZEN_INVENTORY_KEYS = frozenset(
    {"count", "canonical_sha256", "entries"}
)
REVIEW_TEAM_DIGEST_MIGRATION_FROZEN_ENTRY_KEYS = frozenset(
    {"task_id", "receipt_basename", "receipt_sha256"}
)
REVIEW_TEAM_DIGEST_MIGRATION_ENTRY_KEYS = frozenset(
    {
        "task_id",
        "task_note_basename",
        "receipt_basename",
        "receipt_relpath",
        "receipt_sha256",
        "classification",
        "reason",
        "legacy_admission",
    }
)
REVIEW_TEAM_DIGEST_MIGRATION_LEGACY_ADMISSION_KEYS = frozenset(
    {
        "route",
        "source_trust_anchor",
        "sealed_generation_id",
        "sealed_generation_source_head_sha",
        "receipt_sha256",
        "classification",
    }
)
REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_AUTHORITY_KEYS = frozenset(
    {
        "schema",
        "id",
        "candidate_authority_sha256",
        "migration_authority_proposal_sha256",
        "migration_authority_consumed_act_carrier_sha256",
        "frozen_inventory_canonical_sha256",
        "candidate_artifact_core_sha256",
        "disposition_manifest_sha256",
        "write_set_sha256",
        "evidence_manifest_sha256",
        "plan_sha256",
        "candidate_carrier_locator",
    }
)
REVIEW_TEAM_DIGEST_MIGRATION_OPTIONAL_CANDIDATE_AUTHORITY_KEYS = frozenset(
    {
        "carrier_path",
        "carrier_sha256",
        "prepared_plan_file_sha256",
        "prepared_plan_canonical_sha256",
    }
)
REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_AUTHORITY_SCHEMA = (
    "hapax.review_team_digest_migration.candidate_authority.v1"
)
REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_CARRIER_SCHEMA = (
    "hapax.review_team_digest_migration.candidate_authority_carrier.v1"
)
REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_CARRIER_KEYS = frozenset(
    {
        "schema",
        "id",
        "status",
        "consumed_at",
        "candidate_authority",
        "candidate_authority_sha256",
        "candidate_carrier_locator",
        "prepared_plan_file_sha256",
        "prepared_plan_canonical_sha256",
        "prepared_plan_raw_bytes_hex",
        "operator_act",
    }
)
REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_CARRIER_CANDIDATE_KEYS = (
    REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_AUTHORITY_KEYS
    - frozenset({"candidate_authority_sha256"})
)
REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_OPERATOR_ACT_KEYS = frozenset(
    {
        "exact_response_utf8_no_lf",
        "matched_id",
        "matched_candidate_authority_sha256",
        "authority_minted",
        "authority_limited_to_candidate",
    }
)
REVIEW_TEAM_DIGEST_MIGRATION_PREPARED_PLAN_SCHEMA = (
    "hapax.review_team_digest_migration.prepared_plan.v2"
)
REVIEW_TEAM_DIGEST_MIGRATION_PREPARED_PLAN_KEYS = frozenset(
    {
        "schema",
        "generated_at",
        "repo",
        "authority",
        "artifact_preflight",
        "snapshots",
        "open_pr_results",
        "migration",
        "receipt_writes",
        "evidence_manifest",
        "lock_transition",
        "plan_binding_core",
        "candidate_authority",
        "candidate_authority_sha256",
        "candidate_authority_response",
        "acceptance_admission_trace",
        "recovery_policy",
        "assertions",
    }
)
REVIEW_TEAM_DIGEST_MIGRATION_PREPARED_PLAN_BINDING_KEYS = (
    "candidate_artifact_core_sha256",
    "disposition_manifest_sha256",
    "write_set_sha256",
    "evidence_manifest_sha256",
    "plan_sha256",
    "migration_authority_proposal_sha256",
    "migration_authority_consumed_act_carrier_sha256",
    "frozen_inventory_canonical_sha256",
)
REVIEW_TEAM_DIGEST_MIGRATION_PREPARED_PLAN_BINDING_CORE_KEYS = frozenset(
    {
        "schema",
        "candidate_artifact_core_sha256",
        "candidate_artifact_sha256",
        "disposition_manifest_sha256",
        "write_set_sha256",
        "evidence_manifest_sha256",
        "snapshot_fingerprint",
        "snapshot_count",
        "plan_sha256",
        "disposition_manifest",
        "write_set",
        "evidence_manifest",
    }
)
REVIEW_TEAM_DIGEST_MIGRATION_PREPARED_PLAN_AUTHORITY_KEYS = frozenset(
    {
        "proposal_path",
        "proposal_sha256",
        "proposal_id",
        "case_id",
        "consumed_act_carrier_path",
        "consumed_act_carrier_sha256",
        "frozen_inventory_canonical_sha256",
        "frozen_inventory_count",
        "legacy_unsealed_artifact_sha256",
        "source_trust_anchor",
    }
)
REVIEW_TEAM_DIGEST_MIGRATION_PREPARED_PLAN_BINDING_CORE_SCHEMA = (
    "hapax.review_team_digest_migration.prepared_plan.v1"
)
REVIEW_TEAM_DIGEST_MIGRATION_DISPOSITION_MANIFEST_SCHEMA = (
    "hapax.review_team_digest_migration.disposition_manifest.v1"
)
REVIEW_TEAM_DIGEST_MIGRATION_WRITE_SET_SCHEMA = "hapax.review_team_digest_migration.write_set.v1"
# The transaction's recovery contract and apply-purity assertions are constants of the protocol,
# not per-plan data. Runtime and lifecycle both compare a decoded plan against these exact objects,
# so a plan cannot renegotiate its own recovery semantics or relax its own purity assertions.
REVIEW_TEAM_DIGEST_MIGRATION_RECOVERY_POLICY = {
    "initializing": "rollback",
    "prepared": "rollback",
    "applied": "rollback",
    "rollback_started": "rollback",
    "rollback_failed": "rollback",
    "complete": "roll_forward",
    "terminal_publishing": "roll_forward",
    "rolled_back": "rollback_verify",
}
REVIEW_TEAM_DIGEST_MIGRATION_APPLY_ASSERTIONS = {
    "provider_calls": "forbidden_during_apply",
    "github_calls": "forbidden_during_apply",
    "reviewer_calls": "forbidden_during_apply",
    "external_effects_before_journal": False,
    "outputs_are_exact_prepared_bytes": True,
}
REVIEW_TEAM_DIGEST_MIGRATION_SHA256_OR_NONE_KEYS = frozenset(
    {"candidate_artifact_core_sha256", "candidate_artifact_sha256"}
)

# ---------------------------------------------------------------------------------------------
# The one exact PreparedMigrationPlan decoder.
#
# Every nested exact-key set, scalar kind, enum, protocol constant, digest, byte representation and
# cross-field relation lives here EXACTLY ONCE, and both admission surfaces -- runtime apply and
# lifecycle artifact admission -- run this same total decoder over the same decoded object. Runtime
# adds FILESYSTEM evidence checks on top (vault-root path admission, on-disk digests); it must never
# add a second semantic/type decoder, because a check that only one surface runs is a check the
# other surface can be walked straight past. That asymmetry is exactly how a plan with a list-valued
# open-PR status, a list-valued migration.counts and a mapping-valued preflight blocker list reached
# lifecycle admission with no blockers while runtime rejected the identical bytes.
# ---------------------------------------------------------------------------------------------
PREPARED_MIGRATION_ALLOWED_KEYS = frozenset(
    {
        "status",
        "artifact_path",
        "artifact_written",
        "counts",
        "entries",
        "next_actions",
        "generated_at",
        "authority",
        "sealed_generation",
        "sealed_artifact_immutable",
        "current_receipt_drift",
        "before_artifact_sha256",
        "after_artifact_sha256",
        "candidate_artifact_sha256",
        "candidate_artifact_core_sha256",
        "candidate_authority_sha256",
        "candidate_raw_bytes_hex",
        "candidate_payload",
        "artifact_preflight",
        "target_preimage",
        "replaced_unsealed_artifact",
    }
)
PREPARED_MIGRATION_REQUIRED_KEYS = frozenset(
    {
        "status",
        "artifact_path",
        "artifact_written",
        "counts",
        "entries",
        "before_artifact_sha256",
        "after_artifact_sha256",
    }
)
PREPARED_RECEIPT_WRITE_KEYS = frozenset(
    {
        "kind",
        "path",
        "archive_path",
        "existing_sha256",
        "payload",
        "raw_bytes_hex",
        "sha256",
        "target_preimage",
    }
)
PREPARED_ARTIFACT_PREFLIGHT_KEYS = frozenset(
    {"status", "artifact_path", "artifact_sha256", "blockers", "sealed_generation"}
)
PREPARED_ARTIFACT_PREFLIGHT_REQUIRED_KEYS = frozenset(
    {"status", "artifact_path", "artifact_sha256", "blockers"}
)
PREPARED_EVIDENCE_MANIFEST_KEYS = frozenset(
    {
        "schema",
        "source_trust_anchor",
        "authority",
        "artifact_preflight",
        "lock_transition",
        "planned_writes",
        "paths",
    }
)
PREPARED_EVIDENCE_AUTHORITY_KEYS = frozenset(
    {
        "proposal_path",
        "proposal_sha256",
        "consumed_act_carrier_path",
        "consumed_act_carrier_sha256",
        "frozen_inventory_canonical_sha256",
    }
)
PREPARED_LOCK_TRANSITION_KEYS = frozenset(
    {
        "schema",
        "lock_path",
        "pre_claim_status",
        "required_pre_claim_status",
        "owned_lock_present",
        "owned_lock_schema",
        "required_owned_lock_schema",
    }
)
PREPARED_WRITE_SET_KEYS = frozenset({"schema", "writes"})
PREPARED_WRITE_SET_ITEM_KEYS = frozenset(
    {"kind", "path", "sha256", "before_sha256", "archive_path"}
)
PREPARED_TARGET_PREIMAGE_KEYS = frozenset({"evidence", "read_error", "raw_bytes_hex"})
PREPARED_FILE_EVIDENCE_KEYS = frozenset(
    {
        "path",
        "relpath",
        "exists",
        "error",
        "sha256",
        "sha256_error",
        "mode",
        "size",
        "mtime_ns",
        "ctime_ns",
        "dev",
        "ino",
        "is_file",
        "is_dir",
        "is_symlink",
        "symlink_target",
        "symlink_error",
        "entries",
        "entries_error",
        "read_error",
        "schema",
        "status",
    }
)
PREPARED_SNAPSHOT_KEYS = frozenset(
    {
        "task_id",
        "task_note_basename",
        "frontmatter",
        "receipt_path",
        "receipt_relpath",
        "receipt_basename",
        "receipt_sha256",
        "loaded",
    }
)
PREPARED_OPEN_PR_RESULT_KEYS = frozenset(
    {
        "status",
        "repo",
        "pr",
        "task_id",
        "head_sha",
        "dossier_path",
        "review_team_verdict",
        "prepared_side_effects",
        "side_effects",
        "blocked_reasons",
        "next_action",
        "reason",
        "results",
        "migration_claim",
    }
)
PREPARED_ACCEPTANCE_TRACE_KEYS = frozenset(
    {
        "task_note_basename",
        "task_id",
        "accepted",
        "route",
        "blockers",
        "receipt_path",
        "receipt_sha256",
        "dossier_sha256",
        "classification",
        "legacy_admission",
        "sealed_generation",
    }
)
PREPARED_PATH_ENTRY_KEYS = frozenset({"name", "is_dir", "is_file", "is_symlink"})
MIGRATION_CANDIDATE_AUTHORITY_KEYS = REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_CARRIER_CANDIDATE_KEYS
# The claim state a replay reports when it HOLDS because someone else owns the migration lock. It is
# authored by this protocol, so it gets a schema -- not a boundary declaration. Only ``holder`` is a
# boundary: it is the other process's lock document, observed and never authored here.
PREPARED_MIGRATION_CLAIM_KEYS = frozenset({"status", "lock_path", "holder", "lock_evidence"})
PREPARED_MIGRATION_CLAIM_STATUSES = frozenset(
    {
        "migration_in_progress",
        "migration_lock_absent",
        "migration_lock_malformed",
        "migration_lock_stale",
        "migration_lock_unavailable",
    }
)
PREPARED_MIGRATION_CLAIM_SHAPE = {
    "status": "str",
    "lock_path": "str",
    # AUTHORITY BOUNDARY -- see PREPARED_PLAN_AUTHORITY_BOUNDARIES["open_pr_result.migration_claim.holder"].
    "holder": "json_mapping",
    "lock_evidence": "mapping",
}
PREPARED_MIGRATION_CLAIM_EVIDENCE_KEYS = frozenset(
    {
        "path",
        "status",
        "stat",
        "holder_error",
        "stale_after_seconds",
        "lock_age_seconds",
        "next_action",
    }
)
PREPARED_MIGRATION_CLAIM_EVIDENCE_SHAPE = {
    "path": "str",
    "status": "str",
    "stat": "mapping",
    "holder_error": "str_or_none",
    "stale_after_seconds": "nonneg_number_or_none",
    "lock_age_seconds": "number_or_none",
    "next_action": "str_or_none",
}
PREPARED_MIGRATION_CLAIM_STAT_KEYS = frozenset({"exists", "size", "mode", "mtime", "stat_error"})
PREPARED_MIGRATION_CLAIM_STAT_SHAPE = {
    "exists": "bool",
    "size": "nonneg_int_or_none",
    "mode": "str_or_none",
    "mtime": "iso_instant_or_none",
    "stat_error": "str_or_none",
}

# Exact scalar/relation shape of every nested prepared-plan object. Each entry maps a key to a kind
# understood by ``scalar_kind_blocker``; a key absent from a shape is constrained only by the
# surrounding exact-key set.
PREPARED_SNAPSHOT_SHAPE = {
    "task_id": "str",
    "task_note_basename": "str_or_none",
    # AUTHORITY BOUNDARY -- see PREPARED_PLAN_AUTHORITY_BOUNDARIES["snapshot.frontmatter"].
    "frontmatter": "json_mapping_or_none",
    "receipt_path": "str",
    "receipt_relpath": "str_or_none",
    "receipt_basename": "str",
    "receipt_sha256": "sha256",
    # AUTHORITY BOUNDARY -- see PREPARED_PLAN_AUTHORITY_BOUNDARIES["snapshot.loaded"].
    "loaded": "json_mapping_or_none",
}
PREPARED_OPEN_PR_RESULT_SHAPE = {
    "status": "str",
    "repo": "str_or_none",
    "pr": "int_or_none",
    "task_id": "str_or_none",
    "head_sha": "str_or_none",
    "dossier_path": "str_or_none",
    "review_team_verdict": "str_or_none",
    # AUTHORITY BOUNDARY -- see PREPARED_PLAN_AUTHORITY_BOUNDARIES["open_pr_result.side_effects"].
    "prepared_side_effects": "json_mapping_or_none",
    "side_effects": "json_mapping_or_none",
    "blocked_reasons": "list_of_str_or_none",
    "next_action": "str_or_none",
    "reason": "str_or_none",
    # AUTHORITY BOUNDARY -- see PREPARED_PLAN_AUTHORITY_BOUNDARIES["open_pr_result.results"].
    "results": "list_of_json_mapping_or_none",
    # Exactly typed by _prepared_plan_migration_claim_blockers. Never an arbitrary mapping.
    "migration_claim": "mapping_or_none",
}
PREPARED_ACCEPTANCE_TRACE_SHAPE = {
    "task_note_basename": "str_or_none",
    "task_id": "str",
    "accepted": "bool",
    "route": "str",
    "blockers": "list_of_str",
    "receipt_path": "str_or_none",
    "receipt_sha256": "sha256_or_none",
    "dossier_sha256": "sha256_or_none",
    "classification": "str_or_none",
    # Exactly typed below by _prepared_acceptance_trace_relation_blockers: either the empty mapping
    # or a full legacy-admission / sealed-generation object. Never an arbitrary mapping.
    "legacy_admission": "mapping_or_none",
    "sealed_generation": "mapping_or_none",
}
PREPARED_ACCEPTANCE_TRACE_ROUTES = frozenset(
    {
        "blocked",
        "not_required",
        "operator_receipt",
        "review_team_dossier_sha256",
        REVIEW_TEAM_DIGEST_MIGRATION_LEGACY_ROUTE,
    }
)
# The only two statuses a migration can carry INTO a prepared plan. A blocked migration is returned
# before a plan is ever minted, and every other status in the system names a RESULT, not a plan.
PREPARED_MIGRATION_STATUSES = frozenset({"migration_ready", "migration_unchanged"})
PREPARED_MIGRATION_COUNTS_SHAPE = {
    classification: "nonneg_int" for classification in REVIEW_TEAM_DIGEST_MIGRATION_CLASSIFICATIONS
}
PREPARED_MIGRATION_NEXT_ACTIONS_SHAPE = {
    classification: "str" for classification in REVIEW_TEAM_DIGEST_MIGRATION_CLASSIFICATIONS
}
PREPARED_MIGRATION_ENTRY_SHAPE = {
    "task_id": "str",
    "task_note_basename": "str",
    "receipt_basename": "str",
    "receipt_relpath": "str",
    "receipt_sha256": "sha256",
    "classification": "str",
    "reason": "str",
    "legacy_admission": "mapping",
}
PREPARED_LEGACY_ADMISSION_SHAPE = {
    "route": "str",
    "source_trust_anchor": "mapping",
    "sealed_generation_id": "str",
    "sealed_generation_source_head_sha": "str",
    "receipt_sha256": "sha256",
    "classification": "str",
}
PREPARED_SEALED_GENERATION_SHAPE = {
    "id": "str",
    "sealed_at": "str",
    "source_head_sha": "str",
}
PREPARED_SOURCE_TRUST_ANCHOR_SHAPE = {
    key: "str" for key in REVIEW_TEAM_DIGEST_MIGRATION_SOURCE_ANCHOR_KEYS
}
PREPARED_MIGRATION_AUTHORITY_SHAPE = {
    "proposal_path": "str",
    "proposal_sha256": "raw_sha256",
    "proposal_id": "str",
    "case_id": "str",
    "consumed_act_carrier_path": "str",
    "consumed_act_carrier_sha256": "raw_sha256",
    "consumed_act_carrier_schema": "str",
    "consumed_act_carrier_status": "str",
    "consumed_at": "str",
    "operator_act_response": "str",
    "frozen_inventory_canonical_sha256": "raw_sha256",
    "frozen_inventory_count": "nonneg_int",
    "legacy_unsealed_artifact_sha256": "raw_sha256_or_none",
    "source_trust_anchor": "mapping",
}
PREPARED_RECEIPT_DRIFT_KEYS = frozenset(
    {
        "task_id",
        "receipt_basename",
        "status",
        "expected_receipt_sha256",
        "actual_receipt_sha256",
    }
)
PREPARED_RECEIPT_DRIFT_SHAPE = {
    "task_id": "str",
    "receipt_basename": "str",
    "status": "str",
    "expected_receipt_sha256": "sha256",
    "actual_receipt_sha256": "sha256",
}
PREPARED_RECEIPT_DRIFT_STATUSES = frozenset({"missing_from_active", "sha256_mismatch"})
PREPARED_FROZEN_INVENTORY_SHAPE = {
    "count": "nonneg_int",
    "canonical_sha256": "raw_sha256",
    "entries": "list_of_mapping",
}
PREPARED_FROZEN_ENTRY_SHAPE = {
    "task_id": "str",
    "receipt_basename": "str",
    "receipt_sha256": "sha256",
}
# How deep a declared AUTHORITY BOUNDARY document may nest before it is refused outright.
PLAN_JSON_DOCUMENT_MAX_DEPTH = 32
# Every plan field this decoder does NOT give an exact key set, and the reason each one is a typed
# authority boundary rather than an unexamined mapping. A field may appear here only when (a) the
# protocol does not author the document -- it OBSERVES a foreign one -- (b) apply never reads it to
# decide an effect, and (c) its bytes are digest-bound into something the operator ratified. Anything
# failing one of those three is a schema the decoder owes, not a boundary it may declare.
PREPARED_PLAN_AUTHORITY_BOUNDARIES: dict[str, str] = {
    "snapshot.frontmatter": (
        "Observed task-note frontmatter. Authored by the operator's vault, not by this protocol; "
        "typed as a total json_document and digest-bound through snapshot_fingerprint -> "
        "plan_sha256 -> candidate_authority -> the operator's RATIFY response. Apply never reads "
        "it: the artifact this plan writes is candidate_raw_bytes, which is separately byte-bound."
    ),
    "snapshot.loaded": (
        "Observed acceptance-receipt body of an EXISTING on-disk receipt. Same boundary as "
        "snapshot.frontmatter: foreign document, digest-bound, never consulted to decide an effect. "
        "Its semantic admission belongs to acceptance_receipt_blockers, not to the plan decoder."
    ),
    "open_pr_result.side_effects": (
        "Replay side-effect report echoed from review dispatch, for the audit trail only. Bound "
        "into the plan file digest the candidate carrier ratifies. No apply effect reads it."
    ),
    "open_pr_result.results": (
        "Nested per-PR replay results, same boundary and same binding as side_effects."
    ),
    "open_pr_result.migration_claim.holder": (
        "The lock-holder document of ANOTHER process's migration claim. A replay only carries a "
        "migration_claim when the lock is held by someone else -- our own claim is reported in "
        "lock_transition -- so this is an observed foreign document, typed as a total json_document "
        "and digest-bound through the plan. Apply never reads it: a plan that saw a foreign claim "
        "held before it was minted, and the claim this apply holds is proved live at effect time. "
        "The claim's own status, lock_path and lock_evidence ARE authored here and are exactly "
        "typed by _prepared_plan_migration_claim_blockers."
    ),
    "migration.candidate_payload": (
        "NOT opaque -- see _prepared_plan_candidate_payload_blockers. Listed here only to record "
        "that its exact schema is enforced by relation to the migration object plus a byte-exact "
        "binding to candidate_raw_bytes, rather than by a second independent key set."
    ),
}
PREPARED_FILE_EVIDENCE_SHAPE = {
    "path": "str",
    "relpath": "str_or_none",
    "exists": "bool_or_none",
    "error": "str_or_none",
    "sha256": "sha256_or_none",
    "sha256_error": "str_or_none",
    "mode": "int_or_none",
    "size": "int_or_none",
    "mtime_ns": "int_or_none",
    "ctime_ns": "int_or_none",
    "dev": "int_or_none",
    "ino": "int_or_none",
    "is_file": "bool_or_none",
    "is_dir": "bool_or_none",
    "is_symlink": "bool_or_none",
    "symlink_target": "str_or_none",
    "symlink_error": "str_or_none",
    "entries": "list_of_mapping_or_none",
    "entries_error": "str_or_none",
    "read_error": "str_or_none",
    "schema": "str_or_none",
    "status": "str_or_none",
}
PREPARED_PATH_ENTRY_SHAPE = {
    "name": "str",
    "is_dir": "bool",
    "is_file": "bool",
    "is_symlink": "bool",
}
PREPARED_WRITE_SET_ITEM_SHAPE = {
    "kind": "str",
    "path": "str",
    "sha256": "sha256",
    "before_sha256": "sha256_or_none",
    "archive_path": "str_or_none",
}
PREPARED_ARTIFACT_PREFLIGHT_SHAPE = {
    "status": "str",
    "artifact_path": "str",
    "artifact_sha256": "sha256_or_none",
    "blockers": "list_of_str",
    # Exactly typed by _prepared_plan_sealed_generation_blockers: the empty mapping, or a full
    # sealed-generation object. Never an arbitrary mapping.
    "sealed_generation": "mapping_or_none",
}
PREPARED_ARTIFACT_PREFLIGHT_STATUSES = frozenset(
    {
        "migration_artifact_absent",
        "migration_blocked",
        "sealed_migration_valid",
        "unsealed_migration_present",
    }
)
PREPARED_LOCK_TRANSITION_SHAPE = {
    "schema": "str",
    "lock_path": "str",
    "pre_claim_status": "str",
    "required_pre_claim_status": "str",
    "owned_lock_present": "bool",
    "owned_lock_schema": "str_or_none",
    "required_owned_lock_schema": "str",
}
PREPARED_EVIDENCE_AUTHORITY_SHAPE = {
    "proposal_path": "str",
    "proposal_sha256": "raw_sha256",
    "consumed_act_carrier_path": "str",
    "consumed_act_carrier_sha256": "raw_sha256",
    "frozen_inventory_canonical_sha256": "raw_sha256",
}
PREPARED_MIGRATION_PLAN_AUTHORITY_SHAPE = {
    "proposal_path": "str",
    "proposal_sha256": "raw_sha256",
    "proposal_id": "str",
    "case_id": "str",
    "consumed_act_carrier_path": "str",
    "consumed_act_carrier_sha256": "raw_sha256",
    "frozen_inventory_canonical_sha256": "raw_sha256",
    "frozen_inventory_count": "nonneg_int",
    "legacy_unsealed_artifact_sha256": "raw_sha256_or_none",
    "source_trust_anchor": "mapping",
}
PREPARED_MIGRATION_PLAN_BINDING_CORE_SHAPE = {
    "schema": "str",
    # Null exactly when no candidate payload is planned; the conditional relation is enforced by
    # _prepared_plan_candidate_relation_blockers, not by loosening the type.
    "candidate_artifact_core_sha256": "sha256_or_none",
    "candidate_artifact_sha256": "sha256_or_none",
    "disposition_manifest_sha256": "sha256",
    "write_set_sha256": "sha256",
    "evidence_manifest_sha256": "sha256",
    "snapshot_fingerprint": "raw_sha256",
    "snapshot_count": "nonneg_int",
    "plan_sha256": "sha256",
    "disposition_manifest": "mapping",
    "write_set": "mapping",
    "evidence_manifest": "mapping",
}
PREPARED_MIGRATION_SHAPE = {
    "status": "str",
    "artifact_path": "str",
    "artifact_written": "bool",
    # Each of the mappings/lists below carries an EXACT nested key set, scalar kinds, enums and
    # cross-field relations, enforced by _prepared_plan_migration_object_blockers. The kinds here
    # are only the outermost container check.
    "counts": "mapping",
    "entries": "list_of_mapping",
    "next_actions": "mapping_or_none",
    "generated_at": "str_or_none",
    "authority": "mapping_or_none",
    "candidate_raw_bytes_hex": "hex_or_none",
    "sealed_generation": "mapping_or_none",
    "sealed_artifact_immutable": "bool_or_none",
    "current_receipt_drift": "list_of_mapping_or_none",
    "before_artifact_sha256": "sha256_or_none",
    "after_artifact_sha256": "sha256_or_none",
    "candidate_artifact_sha256": "sha256_or_none",
    "candidate_artifact_core_sha256": "sha256_or_none",
    "candidate_authority_sha256": "sha256_or_none",
    "candidate_payload": "mapping_or_none",
    "artifact_preflight": "mapping_or_none",
    "target_preimage": "mapping_or_none",
    "replaced_unsealed_artifact": "bool_or_none",
}
PREPARED_RECEIPT_WRITE_SHAPE = {
    "kind": "str",
    "path": "str",
    "archive_path": "str_or_none",
    "existing_sha256": "sha256_or_none",
    # Exactly bound to raw_bytes_hex by _prepared_plan_receipt_payload_blockers: the payload must BE
    # the document those bytes decode to. It is therefore not an opaque mapping and not an
    # independent claim -- it is a view of the exact bytes this plan will write.
    "payload": "json_mapping",
    "sha256": "sha256",
    "target_preimage": "mapping",
}
PREPARED_TARGET_PREIMAGE_SHAPE = {
    "evidence": "mapping",
    # An absent read error is published as the empty string, so emptiness is legal here.
    "read_error": "any_str_or_none",
    "raw_bytes_hex": "hex_or_none",
}
MIGRATION_CANDIDATE_AUTHORITY_SHAPE = {
    "schema": "str",
    "id": "str",
    "migration_authority_proposal_sha256": "raw_sha256",
    "migration_authority_consumed_act_carrier_sha256": "raw_sha256",
    "frozen_inventory_canonical_sha256": "raw_sha256",
    "candidate_artifact_core_sha256": "sha256_or_none",
    "disposition_manifest_sha256": "sha256",
    "write_set_sha256": "sha256",
    "evidence_manifest_sha256": "sha256",
    "plan_sha256": "sha256",
    "candidate_carrier_locator": "str",
}


def review_team_digest_migration_source_trust_anchor() -> dict[str, str]:
    """Reviewed-source trust anchor for legacy review-team digest migration."""

    return dict(REVIEW_TEAM_DIGEST_MIGRATION_SOURCE_TRUST_ANCHOR)


def requires_acceptance_receipt(frontmatter: Mapping[str, Any]) -> bool:
    """True when the task declares the review floor (top-level or nested).

    Checks both the top-level ``quality_floor`` and the mirrored
    ``route_metadata.quality_floor`` — if either declares
    ``frontier_review_required`` the receipt gate applies (fail-closed on
    disagreement).
    """

    floors = {_frontmatter_scalar(frontmatter.get("quality_floor")).lower()}
    route_metadata = frontmatter.get("route_metadata")
    if isinstance(route_metadata, Mapping):
        floors.add(_frontmatter_scalar(route_metadata.get("quality_floor")).lower())
    return REVIEW_FLOOR_QUALITY_FLOOR in floors


def acceptance_receipt_path(note_path: Path, task_id: str) -> Path:
    """Canonical receipt location: ``<task_id>.acceptance.yaml`` beside the note."""

    return note_path.parent / f"{task_id}{ACCEPTANCE_RECEIPT_SUFFIX}"


def _task_artifact_path_beside_note(note_path: Path, task_id: str, suffix: str) -> Path | None:
    task_path = Path(task_id)
    if task_path.is_absolute() or task_path.name != task_id or task_id in {".", ".."}:
        return None
    candidate = note_path.parent / f"{task_id}{suffix}"
    try:
        candidate.resolve(strict=False).relative_to(note_path.parent.resolve(strict=False))
    except (OSError, ValueError):
        return None
    return candidate


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_active_dir_for_note(note_path: Path) -> Path | None:
    """Resolve the canonical active vault directory for review migration state."""

    note_dir = note_path.parent
    if note_dir.name == "active":
        return note_dir
    sibling_active = note_dir.parent / "active"
    if sibling_active.is_dir():
        return sibling_active
    if note_dir.name in {"closed", "done", "archive", "archived"}:
        return None
    return note_dir


def _valid_artifact_basename(value: str) -> bool:
    return bool(value) and Path(value).name == value and value not in {".", ".."}


def _raw_sha256_file(path: Path) -> str:
    try:
        stat = path.lstat()
    except OSError:
        raise
    if stat_module.S_ISLNK(stat.st_mode):
        raise OSError("symlink")
    if not stat_module.S_ISREG(stat.st_mode):
        raise OSError("wrong_kind")
    return _sha256_file(path)


def _canonical_frozen_inventory_sha256(entries: list[Any]) -> str:
    payload = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class _NoDuplicateSafeLoader(yaml.SafeLoader):
    pass


def _construct_no_duplicate_mapping(
    loader: _NoDuplicateSafeLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_NoDuplicateSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_no_duplicate_mapping,
)


def _load_yaml_mapping_for_migration(path: Path) -> tuple[Mapping[str, Any] | None, str | None]:
    try:
        stat = path.lstat()
        if stat_module.S_ISLNK(stat.st_mode):
            return None, "symlink"
        if not stat_module.S_ISREG(stat.st_mode):
            return None, "wrong_kind"
        loaded = yaml.load(path.read_text(encoding="utf-8"), Loader=_NoDuplicateSafeLoader)
    except (OSError, yaml.YAMLError) as exc:
        return None, type(exc).__name__
    if not isinstance(loaded, Mapping):
        return None, f"not_a_mapping:{type(loaded).__name__}"
    return loaded, None


def _source_anchor_blocker(
    *,
    actual: object,
    expected_key: str,
    reason_prefix: str,
) -> str | None:
    expected = review_team_digest_migration_source_trust_anchor()[expected_key]
    if _frontmatter_non_null_scalar(actual) != expected:
        return f"{reason_prefix}_{expected_key}_mismatch"
    return None


def _migration_source_anchor_blockers(authority: Mapping[str, Any]) -> tuple[str, ...]:
    source_anchor = authority.get("source_trust_anchor")
    if not isinstance(source_anchor, Mapping):
        return ("acceptance_receipt_digest_migration_authority_source_trust_anchor_missing",)
    reason_prefix = "acceptance_receipt_digest_migration_source_anchor"
    checks = (
        (source_anchor.get("proposal_id"), "proposal_id"),
        (source_anchor.get("proposal_sha256"), "proposal_sha256"),
        (source_anchor.get("consumed_act_carrier_sha256"), "consumed_act_carrier_sha256"),
        (
            source_anchor.get("frozen_inventory_canonical_sha256"),
            "frozen_inventory_canonical_sha256",
        ),
        (
            source_anchor.get("legacy_unsealed_artifact_sha256"),
            "legacy_unsealed_artifact_sha256",
        ),
        (source_anchor.get("authority_case"), "authority_case"),
        (authority.get("proposal_id"), "proposal_id"),
        (authority.get("proposal_sha256"), "proposal_sha256"),
        (authority.get("consumed_act_carrier_sha256"), "consumed_act_carrier_sha256"),
        (
            authority.get("frozen_inventory_canonical_sha256"),
            "frozen_inventory_canonical_sha256",
        ),
        (
            authority.get("legacy_unsealed_artifact_sha256"),
            "legacy_unsealed_artifact_sha256",
        ),
        (authority.get("case_id"), "authority_case"),
    )
    blockers = [
        blocker
        for actual, key in checks
        if (
            blocker := _source_anchor_blocker(
                actual=actual, expected_key=key, reason_prefix=reason_prefix
            )
        )
    ]
    return tuple(blockers)


def _migration_authority_blockers(loaded: Mapping[str, Any]) -> tuple[str, ...]:
    authority = loaded.get("authority")
    if not isinstance(authority, Mapping):
        return ("acceptance_receipt_digest_migration_authority_missing",)
    source_anchor_blockers = _migration_source_anchor_blockers(authority)
    if source_anchor_blockers:
        return source_anchor_blockers

    proposal_path_text = _frontmatter_non_null_scalar(authority.get("proposal_path"))
    proposal_sha = _frontmatter_non_null_scalar(authority.get("proposal_sha256"))
    carrier_path_text = _frontmatter_non_null_scalar(authority.get("consumed_act_carrier_path"))
    carrier_sha = _frontmatter_non_null_scalar(authority.get("consumed_act_carrier_sha256"))
    frozen_digest = _frontmatter_non_null_scalar(authority.get("frozen_inventory_canonical_sha256"))
    if not proposal_path_text or RAW_SHA256_RE.fullmatch(proposal_sha) is None:
        return ("acceptance_receipt_digest_migration_authority_proposal_invalid",)
    if not carrier_path_text or RAW_SHA256_RE.fullmatch(carrier_sha) is None:
        return ("acceptance_receipt_digest_migration_authority_carrier_invalid",)
    if RAW_SHA256_RE.fullmatch(frozen_digest) is None:
        return ("acceptance_receipt_digest_migration_authority_inventory_invalid",)

    proposal_path = Path(proposal_path_text)
    carrier_path = Path(carrier_path_text)
    try:
        if _raw_sha256_file(proposal_path) != proposal_sha:
            return ("acceptance_receipt_digest_migration_authority_proposal_sha256_mismatch",)
        if _raw_sha256_file(carrier_path) != carrier_sha:
            return ("acceptance_receipt_digest_migration_authority_carrier_sha256_mismatch",)
    except OSError as exc:
        return (f"acceptance_receipt_digest_migration_authority_unreadable:{type(exc).__name__}",)

    proposal, proposal_error = _load_yaml_mapping_for_migration(proposal_path)
    if proposal_error or proposal is None:
        return (
            f"acceptance_receipt_digest_migration_authority_proposal_malformed:{proposal_error}",
        )
    carrier, carrier_error = _load_yaml_mapping_for_migration(carrier_path)
    if carrier_error or carrier is None:
        return (f"acceptance_receipt_digest_migration_authority_carrier_malformed:{carrier_error}",)

    proposal_id = _frontmatter_non_null_scalar(proposal.get("id"))
    if proposal_id and _frontmatter_non_null_scalar(loaded.get("authority_proposal_id")) not in {
        "",
        proposal_id,
    }:
        return ("acceptance_receipt_digest_migration_authority_proposal_id_mismatch",)
    carrier_proposal = carrier.get("proposal")
    operator_act = carrier.get("operator_act")
    if not isinstance(carrier_proposal, Mapping) or not isinstance(operator_act, Mapping):
        return ("acceptance_receipt_digest_migration_authority_carrier_malformed:binding_missing",)
    expected_response = f"RATIFY {proposal_id} proposal_sha256={proposal_sha}"
    if _frontmatter_non_null_scalar(carrier.get("status")) != "consumed_active":
        return ("acceptance_receipt_digest_migration_authority_carrier_not_consumed",)
    if _frontmatter_non_null_scalar(carrier.get("id")) != proposal_id:
        return ("acceptance_receipt_digest_migration_authority_carrier_id_mismatch",)
    if _frontmatter_non_null_scalar(carrier_proposal.get("path")) != proposal_path_text:
        return ("acceptance_receipt_digest_migration_authority_carrier_proposal_path_mismatch",)
    if _frontmatter_non_null_scalar(carrier_proposal.get("sha256")) != proposal_sha:
        return ("acceptance_receipt_digest_migration_authority_carrier_proposal_sha_mismatch",)
    if (
        _frontmatter_non_null_scalar(operator_act.get("exact_response_utf8_no_lf"))
        != expected_response
    ):
        return ("acceptance_receipt_digest_migration_authority_carrier_response_mismatch",)
    if _frontmatter_non_null_scalar(authority.get("operator_act_response")) != expected_response:
        return ("acceptance_receipt_digest_migration_authority_operator_response_mismatch",)
    carrier_schema = _frontmatter_non_null_scalar(carrier.get("schema"))
    if not carrier_schema:
        return ("acceptance_receipt_digest_migration_authority_carrier_schema_missing",)
    if _frontmatter_non_null_scalar(authority.get("consumed_act_carrier_schema")) != carrier_schema:
        return ("acceptance_receipt_digest_migration_authority_carrier_schema_mismatch",)
    if _frontmatter_non_null_scalar(authority.get("consumed_act_carrier_status")) != (
        _frontmatter_non_null_scalar(carrier.get("status"))
    ):
        return ("acceptance_receipt_digest_migration_authority_carrier_status_mismatch",)
    consumed_at = _frontmatter_non_null_scalar(carrier.get("consumed_at"))
    if not consumed_at:
        return ("acceptance_receipt_digest_migration_authority_carrier_consumed_at_missing",)
    if _frontmatter_non_null_scalar(authority.get("consumed_at")) != consumed_at:
        return ("acceptance_receipt_digest_migration_authority_carrier_consumed_at_mismatch",)
    for key in (
        "matched_id",
        "matched_proposal_sha256",
        "authority_minted",
        "authority_limited_to_proposal",
    ):
        if operator_act.get(key) is not True:
            return (f"acceptance_receipt_digest_migration_authority_carrier_{key}_false",)

    frozen = proposal.get("frozen_prebinding_inventory")
    if not isinstance(frozen, Mapping):
        return ("acceptance_receipt_digest_migration_authority_inventory_missing",)
    frozen_entries = frozen.get("entries")
    if not isinstance(frozen_entries, list):
        return ("acceptance_receipt_digest_migration_authority_inventory_entries_invalid",)
    proposal_frozen_digest = _frontmatter_non_null_scalar(frozen.get("canonical_sha256"))
    actual_frozen_digest = _canonical_frozen_inventory_sha256(frozen_entries)
    if proposal_frozen_digest != actual_frozen_digest or frozen_digest != actual_frozen_digest:
        return ("acceptance_receipt_digest_migration_authority_inventory_sha256_mismatch",)
    if (
        _frontmatter_non_null_scalar(carrier.get("frozen_prebinding_inventory_canonical_sha256"))
        != actual_frozen_digest
    ):
        return ("acceptance_receipt_digest_migration_authority_carrier_inventory_sha_mismatch",)

    artifact_frozen = loaded.get("frozen_prebinding_inventory")
    if not isinstance(artifact_frozen, Mapping):
        return ("acceptance_receipt_digest_migration_authority_artifact_inventory_missing",)
    artifact_frozen_entries = artifact_frozen.get("entries")
    if not isinstance(artifact_frozen_entries, list):
        return ("acceptance_receipt_digest_migration_authority_artifact_inventory_invalid",)
    if _canonical_frozen_inventory_sha256(artifact_frozen_entries) != actual_frozen_digest:
        return ("acceptance_receipt_digest_migration_authority_artifact_inventory_expanded",)
    try:
        artifact_count = int(artifact_frozen.get("count"))
    except (TypeError, ValueError):
        return ("acceptance_receipt_digest_migration_authority_artifact_inventory_count_invalid",)
    if artifact_count != len(frozen_entries):
        return ("acceptance_receipt_digest_migration_authority_artifact_inventory_count_mismatch",)
    try:
        authority_count = int(authority.get("frozen_inventory_count"))
    except (TypeError, ValueError):
        return ("acceptance_receipt_digest_migration_authority_frozen_count_invalid",)
    if authority_count != len(frozen_entries):
        return ("acceptance_receipt_digest_migration_authority_frozen_count_mismatch",)
    return ()


def _expected_sealed_generation_id(authority: Mapping[str, Any]) -> str:
    proposal_id = _frontmatter_non_null_scalar(authority.get("proposal_id"))
    proposal_sha = _frontmatter_non_null_scalar(authority.get("proposal_sha256"))
    carrier_sha = _frontmatter_non_null_scalar(authority.get("consumed_act_carrier_sha256"))
    if not proposal_id or RAW_SHA256_RE.fullmatch(proposal_sha) is None:
        return ""
    if RAW_SHA256_RE.fullmatch(carrier_sha) is None:
        return ""
    return f"{proposal_id}.{proposal_sha[:12]}.{carrier_sha[:12]}"


def _migration_tuple_from_mapping(entry: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        _frontmatter_non_null_scalar(entry.get("task_id")),
        _frontmatter_non_null_scalar(entry.get("receipt_basename")),
        _frontmatter_non_null_scalar(entry.get("receipt_sha256")),
    )


def _migration_frozen_entry_tuples(entries: list[Any]) -> set[tuple[str, str, str]]:
    tuples: set[tuple[str, str, str]] = set()
    for entry in entries:
        if isinstance(entry, Mapping):
            tuples.add(_migration_tuple_from_mapping(entry))
    return tuples


def _migration_counts(entries: list[Mapping[str, Any]]) -> dict[str, int]:
    counts = {classification: 0 for classification in REVIEW_TEAM_DIGEST_MIGRATION_CLASSIFICATIONS}
    for entry in entries:
        classification = _frontmatter_non_null_scalar(entry.get("classification"))
        if classification in counts:
            counts[classification] += 1
    return counts


def _canonical_json_sha256(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _migration_disposition_manifest_from_entries(
    entries: list[Mapping[str, Any]],
) -> dict[str, Any]:
    disposition_entries = [
        {
            "task_id": _frontmatter_non_null_scalar(entry.get("task_id")),
            "receipt_basename": _frontmatter_non_null_scalar(entry.get("receipt_basename")),
            "receipt_sha256": _frontmatter_non_null_scalar(entry.get("receipt_sha256")),
            "classification": _frontmatter_non_null_scalar(entry.get("classification")),
            "reason": _frontmatter_non_null_scalar(entry.get("reason")),
        }
        for entry in entries
    ]
    disposition_entries.sort(
        key=lambda item: (item["task_id"], item["receipt_basename"], item["receipt_sha256"])
    )
    return {
        "schema": "hapax.review_team_digest_migration.disposition_manifest.v1",
        "entries": disposition_entries,
    }


def _candidate_artifact_core_sha256(loaded: Mapping[str, Any]) -> str:
    core = {key: value for key, value in loaded.items() if key != "candidate_authority"}
    return _canonical_json_sha256(core)


def review_team_digest_migration_disposition_manifest(entries: Any) -> dict[str, Any]:
    """Recompute the disposition manifest from plan entries.

    This is the single definition consumed by both the runtime planner and every decoder, so a
    plan's claimed ``disposition_manifest`` can never be believed on its own authority.
    """

    manifest_entries = [
        {
            "task_id": str(entry.get("task_id") or ""),
            "receipt_basename": str(entry.get("receipt_basename") or ""),
            "receipt_sha256": str(entry.get("receipt_sha256") or ""),
            "classification": str(entry.get("classification") or ""),
            "reason": str(entry.get("reason") or ""),
        }
        for entry in (entries or [])
        if isinstance(entry, Mapping)
    ]
    manifest_entries.sort(
        key=lambda item: (item["task_id"], item["receipt_basename"], item["receipt_sha256"])
    )
    return {
        "schema": REVIEW_TEAM_DIGEST_MIGRATION_DISPOSITION_MANIFEST_SCHEMA,
        "entries": manifest_entries,
    }


def review_team_digest_migration_write_set(
    *,
    migration: Mapping[str, Any],
    receipt_writes: list[Any],
) -> dict[str, Any]:
    """Recompute the planned write set from the decoded migration and receipt writes."""

    writes: list[dict[str, Any]] = []
    candidate_artifact_sha256 = migration.get("candidate_artifact_core_sha256") or migration.get(
        "candidate_artifact_sha256"
    )
    if migration.get("candidate_payload") and candidate_artifact_sha256:
        writes.append(
            {
                "kind": "migration_artifact",
                "path": str(migration.get("artifact_path") or ""),
                "sha256": str(candidate_artifact_sha256),
                "before_sha256": migration.get("before_artifact_sha256"),
            }
        )
    for write in receipt_writes:
        if not isinstance(write, Mapping):
            continue
        writes.append(
            {
                "kind": "acceptance_receipt",
                "path": str(write.get("path") or ""),
                "sha256": str(write.get("sha256") or ""),
                "before_sha256": write.get("existing_sha256"),
                "archive_path": write.get("archive_path"),
            }
        )
    writes.sort(key=lambda item: (item["kind"], item["path"]))
    return {"schema": REVIEW_TEAM_DIGEST_MIGRATION_WRITE_SET_SCHEMA, "writes": writes}


def _plan_sha256_field_blockers(
    mapping: Mapping[str, Any],
    *,
    keys: tuple[str, ...],
    reason_prefix: str,
) -> list[str]:
    blockers: list[str] = []
    for key in keys:
        value = mapping.get(key)
        if key in REVIEW_TEAM_DIGEST_MIGRATION_SHA256_OR_NONE_KEYS and value is None:
            continue
        if not isinstance(value, str) or (
            REVIEW_TEAM_DIGEST_MIGRATION_SHA256_RE.fullmatch(value) is None
        ):
            blockers.append(f"{reason_prefix}_{key}_invalid")
    return blockers


def exact_key_blockers(
    mapping: Mapping[str, Any],
    *,
    required: frozenset[str],
    allowed: frozenset[str],
    reason_prefix: str,
) -> list[str]:
    """Exact key-set admission: no missing required key, no unknown key."""

    actual = frozenset(str(key) for key in mapping)
    missing = sorted(required - actual)
    if missing:
        return [f"{reason_prefix}_missing_key:{missing[0]}"]
    unknown = sorted(actual - allowed)
    if unknown:
        return [f"{reason_prefix}_unknown_key:{unknown[0]}"]
    return []


def scalar_kind_blocker(value: Any, kind: str) -> str | None:
    """Return a suffix describing how ``value`` violates ``kind``, or None when it conforms."""

    optional = kind.endswith("_or_none")
    base = kind.removesuffix("_or_none")
    if value is None:
        return None if optional else "null"
    if base == "any":
        return None
    if base == "bool":
        return None if isinstance(value, bool) else "not_bool"
    if base in {"int", "nonneg_int"}:
        if isinstance(value, bool) or not isinstance(value, int):
            return "not_int"
        if base == "nonneg_int" and value < 0:
            return "negative"
        return None
    if base in {"number", "nonneg_number"}:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "not_number"
        if not math.isfinite(value):
            return "not_finite"
        if base == "nonneg_number" and value < 0:
            return "negative"
        return None
    if base == "iso_instant":
        if not isinstance(value, str):
            return "not_string"
        return None if _valid_iso_datetime(value) else "not_iso_instant"
    if base == "str":
        if not isinstance(value, str):
            return "not_string"
        return None if value else "empty"
    if base == "any_str":
        return None if isinstance(value, str) else "not_string"
    if base == "sha256":
        if not isinstance(value, str):
            return "not_string"
        return None if REVIEW_TEAM_DIGEST_MIGRATION_SHA256_RE.fullmatch(value) else "not_sha256"
    if base == "raw_sha256":
        if not isinstance(value, str):
            return "not_string"
        return None if RAW_SHA256_RE.fullmatch(value) else "not_raw_sha256"
    if base == "hex":
        if not isinstance(value, str):
            return "not_string"
        try:
            bytes.fromhex(value)
        except ValueError:
            return "not_hex"
        return None
    if base == "mapping":
        return None if isinstance(value, Mapping) else "not_mapping"
    if base == "list":
        return None if isinstance(value, list) else "not_list"
    if base == "list_of_str":
        if not isinstance(value, list):
            return "not_list"
        return None if all(isinstance(item, str) for item in value) else "item_not_string"
    if base == "list_of_mapping":
        if not isinstance(value, list):
            return "not_list"
        return None if all(isinstance(item, Mapping) for item in value) else "item_not_mapping"
    if base == "json_document":
        return _json_document_violation(value)
    if base == "json_mapping":
        if not isinstance(value, Mapping):
            return "not_mapping"
        return _json_document_violation(value)
    if base == "list_of_json_mapping":
        if not isinstance(value, list):
            return "not_list"
        for item in value:
            if not isinstance(item, Mapping):
                return "item_not_mapping"
            violation = _json_document_violation(item)
            if violation:
                return f"item_{violation}"
        return None
    raise RuntimeError(f"unknown_type_kind:{kind}")


def _json_document_violation(value: Any, *, depth: int = 0) -> str | None:
    """Total structural admission for a value inside a declared AUTHORITY BOUNDARY.

    ``json_document`` is NOT "any mapping". It is the exact type *JSON value tree*: a mapping with
    string keys, a list, or a JSON scalar, nested no deeper than ``PLAN_JSON_DOCUMENT_MAX_DEPTH``.
    Nothing else admits -- not a tuple, not a set, not a datetime, not a non-string mapping key.

    It exists because a handful of plan fields carry a document this protocol does not author and
    must not reinterpret (a foreign task-note frontmatter, a foreign receipt body). Their MEANING is
    ratified elsewhere -- see ``PREPARED_PLAN_AUTHORITY_BOUNDARIES`` -- and their BYTES are bound
    into the plan identity the operator signed. What the decoder still owes them is a total type, so
    an "opaque" field cannot smuggle an object of a kind the protocol never anticipated. Declaring a
    field opaque is a decision with a written reason; it is never the absence of one.

    NaN and the infinities are NOT in the JSON value domain. Python's ``json`` emits them anyway, as
    the bare tokens ``NaN``/``Infinity``, and reads them back by default -- so a boundary that
    claimed the JSON type while admitting them was declaring a domain it did not enforce, and the
    bytes it digest-bound were not parseable by a conforming JSON reader.
    """

    if depth > PLAN_JSON_DOCUMENT_MAX_DEPTH:
        return "too_deep"
    if isinstance(value, float) and not math.isfinite(value):
        return "not_finite"
    if value is None or isinstance(value, (str, int, float, bool)):
        return None
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                return "key_not_string"
            violation = _json_document_violation(item, depth=depth + 1)
            if violation:
                return violation
        return None
    if isinstance(value, list):
        for item in value:
            violation = _json_document_violation(item, depth=depth + 1)
            if violation:
                return violation
        return None
    return "not_json_value"


def typed_shape_blockers(
    mapping: Any,
    *,
    spec: dict[str, str],
    reason_prefix: str,
) -> list[str]:
    """Total scalar/relation admission for one mapping against a declarative type spec."""

    if not isinstance(mapping, Mapping):
        return [f"{reason_prefix}_not_mapping"]
    blockers: list[str] = []
    for key in sorted(spec):
        if key not in mapping:
            continue
        violation = scalar_kind_blocker(mapping[key], spec[key])
        if violation:
            blockers.append(f"{reason_prefix}_{key}_{violation}")
    return blockers


def _sha256_prefixed(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def review_team_digest_migration_snapshot_fingerprint(
    snapshots: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
) -> str:
    """Recompute the plan's snapshot fingerprint. Shared, so both admission surfaces recheck it."""

    payload = json.dumps(list(snapshots), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _prepared_plan_yaml_bytes(payload: Mapping[str, Any]) -> bytes:
    """The exact YAML serialization of a candidate artifact payload.

    This is the SAME function the planner uses to mint the candidate bytes, so a decoded payload can
    be re-serialized and compared against the plan's claimed bytes rather than trusted alongside
    them.
    """

    return yaml.safe_dump(dict(payload), sort_keys=False).encode("utf-8")


def _plan_bytes_from_hex(value: Any, *, field_name: str) -> tuple[bytes | None, str | None]:
    if value is None:
        return None, None
    if not isinstance(value, str):
        return None, f"{field_name}_not_string"
    try:
        return bytes.fromhex(value), None
    except ValueError:
        return None, f"{field_name}_not_hex"


def _prepared_file_evidence_blockers(value: Any, *, reason_prefix: str) -> list[str]:
    """One exact schema for a file-evidence object, INCLUDING its directory listing.

    ``entries`` was typed ``list_of_mapping``, so every directory listing in the plan -- in the
    evidence manifest and in every captured target preimage -- carried items of no declared shape.
    A listing is plan-authored observation, not a foreign document: it gets a schema.
    """

    if not isinstance(value, Mapping):
        return [f"{reason_prefix}_not_mapping"]
    blockers = exact_key_blockers(
        value,
        required=frozenset({"path", "exists"}),
        allowed=PREPARED_FILE_EVIDENCE_KEYS,
        reason_prefix=reason_prefix,
    )
    blockers.extend(
        typed_shape_blockers(
            value,
            spec=PREPARED_FILE_EVIDENCE_SHAPE,
            reason_prefix=reason_prefix,
        )
    )
    entries = value.get("entries")
    if isinstance(entries, list):
        for index, entry in enumerate(entries):
            entry_prefix = f"{reason_prefix}_entry:{index}"
            if not isinstance(entry, Mapping):
                blockers.append(f"{entry_prefix}_not_mapping")
                continue
            blockers.extend(
                exact_key_blockers(
                    entry,
                    required=PREPARED_PATH_ENTRY_KEYS,
                    allowed=PREPARED_PATH_ENTRY_KEYS,
                    reason_prefix=entry_prefix,
                )
            )
            blockers.extend(
                typed_shape_blockers(
                    entry,
                    spec=PREPARED_PATH_ENTRY_SHAPE,
                    reason_prefix=entry_prefix,
                )
            )
    return blockers


def _prepared_target_preimage_blockers(value: Any, *, reason_prefix: str) -> list[str]:
    if not isinstance(value, Mapping):
        return [f"{reason_prefix}_not_mapping"]
    blockers = exact_key_blockers(
        value,
        required=frozenset({"evidence", "read_error"}),
        allowed=PREPARED_TARGET_PREIMAGE_KEYS,
        reason_prefix=reason_prefix,
    )
    blockers.extend(
        typed_shape_blockers(
            value,
            spec=PREPARED_TARGET_PREIMAGE_SHAPE,
            reason_prefix=reason_prefix,
        )
    )
    blockers.extend(
        _prepared_file_evidence_blockers(
            value.get("evidence"), reason_prefix=f"{reason_prefix}_evidence"
        )
    )
    raw_hex = value.get("raw_bytes_hex")
    if raw_hex is not None:
        _raw, error = _plan_bytes_from_hex(raw_hex, field_name=f"{reason_prefix}_raw_bytes_hex")
        if error:
            blockers.append(error)
    return blockers


def _prepared_plan_mapping_list_blockers(
    value: Any,
    *,
    item_allowed_keys: frozenset[str],
    item_required_keys: frozenset[str] | None = None,
    item_shape: dict[str, str] | None = None,
    reason_prefix: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(value, list):
        return [], [f"{reason_prefix}_not_list"]
    items: list[dict[str, Any]] = []
    blockers: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            blockers.append(f"{reason_prefix}_item_not_mapping:{index}")
            continue
        blockers.extend(
            exact_key_blockers(
                item,
                required=item_required_keys or frozenset(),
                allowed=item_allowed_keys,
                reason_prefix=f"{reason_prefix}_item:{index}",
            )
        )
        if item_shape is not None:
            blockers.extend(
                typed_shape_blockers(
                    item,
                    spec=item_shape,
                    reason_prefix=f"{reason_prefix}_item:{index}",
                )
            )
        items.append(dict(item))
    return items, blockers


def _prepared_evidence_manifest_blockers(value: Any) -> list[str]:
    """Every object the manifest is REQUIRED to carry, decoded under its exact schema.

    ``source_trust_anchor`` and ``artifact_preflight`` were listed in the manifest's required key
    set and then read by nothing: the exact-key check proved only that the keys were PRESENT. So
    ``source_trust_anchor={"arbitrary": []}`` and ``artifact_preflight=[]`` decoded with blockers=[]
    inside a manifest whose digest is bound into plan_sha256 and ratified by the operator. A
    required key with no decoder is not a schema; it is a key set.
    """

    prefix = "migration_prepared_plan_evidence_manifest"
    if not isinstance(value, Mapping):
        return [f"{prefix}_missing"]
    blockers = exact_key_blockers(
        value,
        required=PREPARED_EVIDENCE_MANIFEST_KEYS,
        allowed=PREPARED_EVIDENCE_MANIFEST_KEYS,
        reason_prefix=prefix,
    )
    blockers.extend(
        _prepared_plan_source_trust_anchor_blockers(
            value.get("source_trust_anchor"),
            reason_prefix=f"{prefix}_source_trust_anchor",
        )
    )
    blockers.extend(
        _prepared_plan_artifact_preflight_blockers(
            value.get("artifact_preflight"),
            reason_prefix=f"{prefix}_artifact_preflight",
        )
    )
    authority = value.get("authority")
    if not isinstance(authority, Mapping):
        blockers.append(f"{prefix}_authority_not_mapping")
    else:
        blockers.extend(
            exact_key_blockers(
                authority,
                required=PREPARED_EVIDENCE_AUTHORITY_KEYS,
                allowed=PREPARED_EVIDENCE_AUTHORITY_KEYS,
                reason_prefix=f"{prefix}_authority",
            )
        )
        blockers.extend(
            typed_shape_blockers(
                authority,
                spec=PREPARED_EVIDENCE_AUTHORITY_SHAPE,
                reason_prefix=f"{prefix}_authority",
            )
        )
    lock_transition = value.get("lock_transition")
    if lock_transition is not None:
        if not isinstance(lock_transition, Mapping):
            blockers.append(f"{prefix}_lock_transition_not_mapping")
        else:
            blockers.extend(
                exact_key_blockers(
                    lock_transition,
                    required=PREPARED_LOCK_TRANSITION_KEYS,
                    allowed=PREPARED_LOCK_TRANSITION_KEYS,
                    reason_prefix=f"{prefix}_lock_transition",
                )
            )
            blockers.extend(
                typed_shape_blockers(
                    lock_transition,
                    spec=PREPARED_LOCK_TRANSITION_SHAPE,
                    reason_prefix=f"{prefix}_lock_transition",
                )
            )
    planned_writes = value.get("planned_writes")
    if not isinstance(planned_writes, Mapping):
        blockers.append(f"{prefix}_planned_writes_not_mapping")
    else:
        blockers.extend(
            exact_key_blockers(
                planned_writes,
                required=PREPARED_WRITE_SET_KEYS,
                allowed=PREPARED_WRITE_SET_KEYS,
                reason_prefix=f"{prefix}_planned_writes",
            )
        )
        writes, write_blockers = _prepared_plan_mapping_list_blockers(
            planned_writes.get("writes"),
            item_allowed_keys=PREPARED_WRITE_SET_ITEM_KEYS,
            item_required_keys=frozenset({"kind", "path", "sha256"}),
            item_shape=PREPARED_WRITE_SET_ITEM_SHAPE,
            reason_prefix=f"{prefix}_planned_write",
        )
        blockers.extend(write_blockers)
        if len(writes) != len(planned_writes.get("writes") or []):
            blockers.append(f"{prefix}_planned_write_count_mismatch")
    raw_paths = value.get("paths")
    if not isinstance(raw_paths, list):
        blockers.append(f"{prefix}_paths_not_list")
    else:
        for index, path_evidence in enumerate(raw_paths):
            blockers.extend(
                _prepared_file_evidence_blockers(
                    path_evidence, reason_prefix=f"{prefix}_path_item:{index}"
                )
            )
    return blockers


def _enum_value_blockers(value: Any, *, allowed: frozenset[str], reason_prefix: str) -> list[str]:
    text = _frontmatter_non_null_scalar(value)
    if text not in allowed:
        return [f"{reason_prefix}_invalid:{text or 'missing'}"]
    return []


def _prepared_plan_source_trust_anchor_blockers(value: Any, *, reason_prefix: str) -> list[str]:
    """The source trust anchor is a CONSTANT of this protocol, not a field a plan gets to supply.

    ``{"arbitrary": []}`` decoded cleanly for as long as this was checked with ``isinstance(...,
    Mapping)``. The anchor names the exact reviewed proposal, act carrier and frozen inventory that
    the whole legacy-admission route rests on; a plan that carries a different one -- or a
    differently-shaped one -- is not describing this migration at all.
    """

    if not isinstance(value, Mapping):
        return [f"{reason_prefix}_not_mapping"]
    blockers = exact_key_blockers(
        value,
        required=REVIEW_TEAM_DIGEST_MIGRATION_SOURCE_ANCHOR_KEYS,
        allowed=REVIEW_TEAM_DIGEST_MIGRATION_SOURCE_ANCHOR_KEYS,
        reason_prefix=reason_prefix,
    )
    blockers.extend(
        typed_shape_blockers(
            value, spec=PREPARED_SOURCE_TRUST_ANCHOR_SHAPE, reason_prefix=reason_prefix
        )
    )
    if blockers:
        return blockers
    for key, expected in sorted(REVIEW_TEAM_DIGEST_MIGRATION_SOURCE_TRUST_ANCHOR.items()):
        if _frontmatter_non_null_scalar(value.get(key)) != expected:
            blockers.append(f"{reason_prefix}_{key}_mismatch")
    return blockers


def _prepared_plan_sealed_generation_blockers(
    value: Any,
    *,
    reason_prefix: str,
    allow_empty: bool = False,
) -> list[str]:
    """A sealed generation is an id, a sealed-at instant and the source head it was sealed from."""

    if not isinstance(value, Mapping):
        return [f"{reason_prefix}_not_mapping"]
    if allow_empty and not value:
        return []
    blockers = exact_key_blockers(
        value,
        required=REVIEW_TEAM_DIGEST_MIGRATION_GENERATION_KEYS,
        allowed=REVIEW_TEAM_DIGEST_MIGRATION_GENERATION_KEYS,
        reason_prefix=reason_prefix,
    )
    blockers.extend(
        typed_shape_blockers(
            value, spec=PREPARED_SEALED_GENERATION_SHAPE, reason_prefix=reason_prefix
        )
    )
    if blockers:
        return blockers
    if not _valid_iso_datetime(_frontmatter_non_null_scalar(value.get("sealed_at"))):
        blockers.append(f"{reason_prefix}_sealed_at_invalid")
    if GIT_SHA_RE.fullmatch(_frontmatter_non_null_scalar(value.get("source_head_sha"))) is None:
        blockers.append(f"{reason_prefix}_source_head_sha_invalid")
    return blockers


def _prepared_plan_legacy_admission_blockers(
    value: Any,
    *,
    reason_prefix: str,
    expected_receipt_sha256: str | None = None,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, Mapping):
        return [f"{reason_prefix}_not_mapping"]
    if allow_empty and not value:
        return []
    blockers = exact_key_blockers(
        value,
        required=REVIEW_TEAM_DIGEST_MIGRATION_LEGACY_ADMISSION_KEYS,
        allowed=REVIEW_TEAM_DIGEST_MIGRATION_LEGACY_ADMISSION_KEYS,
        reason_prefix=reason_prefix,
    )
    blockers.extend(
        typed_shape_blockers(
            value, spec=PREPARED_LEGACY_ADMISSION_SHAPE, reason_prefix=reason_prefix
        )
    )
    if blockers:
        return blockers
    if (
        _frontmatter_non_null_scalar(value.get("route"))
        != REVIEW_TEAM_DIGEST_MIGRATION_LEGACY_ROUTE
    ):
        blockers.append(f"{reason_prefix}_route_mismatch")
    if (
        _frontmatter_non_null_scalar(value.get("classification"))
        != REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION
    ):
        blockers.append(f"{reason_prefix}_classification_mismatch")
    if (
        GIT_SHA_RE.fullmatch(
            _frontmatter_non_null_scalar(value.get("sealed_generation_source_head_sha"))
        )
        is None
    ):
        blockers.append(f"{reason_prefix}_source_head_sha_invalid")
    if (
        expected_receipt_sha256 is not None
        and _frontmatter_non_null_scalar(value.get("receipt_sha256")) != expected_receipt_sha256
    ):
        blockers.append(f"{reason_prefix}_receipt_sha256_mismatch")
    blockers.extend(
        _prepared_plan_source_trust_anchor_blockers(
            value.get("source_trust_anchor"),
            reason_prefix=f"{reason_prefix}_source_trust_anchor",
        )
    )
    return blockers


def _prepared_plan_migration_entry_blockers(entry: Any, *, reason_prefix: str) -> list[str]:
    """One migration entry: exact keys, exact scalars, classification enum, and the reason relation.

    ``entries`` was admitted as a bare ``list`` and then, at most, checked for item-is-a-mapping.
    Every field that drives the disposition manifest -- and therefore the plan digest the operator
    ratified -- lives in here.
    """

    if not isinstance(entry, Mapping):
        return [f"{reason_prefix}_not_mapping"]
    required = REVIEW_TEAM_DIGEST_MIGRATION_ENTRY_KEYS - frozenset({"legacy_admission"})
    blockers = exact_key_blockers(
        entry,
        required=required,
        allowed=REVIEW_TEAM_DIGEST_MIGRATION_ENTRY_KEYS,
        reason_prefix=reason_prefix,
    )
    blockers.extend(
        typed_shape_blockers(
            entry, spec=PREPARED_MIGRATION_ENTRY_SHAPE, reason_prefix=reason_prefix
        )
    )
    if blockers:
        return blockers

    task_id = _frontmatter_non_null_scalar(entry.get("task_id"))
    basename = _frontmatter_non_null_scalar(entry.get("receipt_basename"))
    relpath = _frontmatter_non_null_scalar(entry.get("receipt_relpath"))
    if _frontmatter_non_null_scalar(entry.get("task_note_basename")) != f"{task_id}.md":
        blockers.append(f"{reason_prefix}_task_note_basename_mismatch")
    if not _valid_artifact_basename(basename):
        blockers.append(f"{reason_prefix}_receipt_basename_invalid")
    if relpath != basename or Path(relpath).name != relpath:
        blockers.append(f"{reason_prefix}_receipt_relpath_invalid")

    classification = _frontmatter_non_null_scalar(entry.get("classification"))
    blockers.extend(
        _enum_value_blockers(
            classification,
            allowed=REVIEW_TEAM_DIGEST_MIGRATION_CLASSIFICATIONS,
            reason_prefix=f"{reason_prefix}_classification",
        )
    )
    reason = _frontmatter_non_null_scalar(entry.get("reason"))
    if (
        classification in REVIEW_TEAM_DIGEST_MIGRATION_CLASSIFICATIONS
        and not _migration_entry_reason_valid(classification, reason)
    ):
        blockers.append(f"{reason_prefix}_reason_mismatch")

    # Legacy admission is present exactly when the entry is preserved on the legacy exact-hash route.
    preserved = classification == REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION
    if preserved and "legacy_admission" not in entry:
        blockers.append(f"{reason_prefix}_legacy_admission_missing")
    elif not preserved and "legacy_admission" in entry:
        blockers.append(f"{reason_prefix}_legacy_admission_unexpected")
    elif preserved:
        blockers.extend(
            _prepared_plan_legacy_admission_blockers(
                entry.get("legacy_admission"),
                reason_prefix=f"{reason_prefix}_legacy_admission",
                expected_receipt_sha256=_frontmatter_non_null_scalar(entry.get("receipt_sha256")),
            )
        )
    return blockers


def _prepared_plan_counts_blockers(
    counts: Any,
    *,
    entries: list[Any],
    reason_prefix: str,
) -> list[str]:
    """Counts are DERIVED, so they are recomputed, never believed.

    ``counts.rebound="wrong-type"`` survived because the only check was that ``counts`` is a mapping.
    """

    if not isinstance(counts, Mapping):
        return [f"{reason_prefix}_not_mapping"]
    blockers = exact_key_blockers(
        counts,
        required=REVIEW_TEAM_DIGEST_MIGRATION_CLASSIFICATIONS,
        allowed=REVIEW_TEAM_DIGEST_MIGRATION_CLASSIFICATIONS,
        reason_prefix=reason_prefix,
    )
    blockers.extend(
        typed_shape_blockers(
            counts, spec=PREPARED_MIGRATION_COUNTS_SHAPE, reason_prefix=reason_prefix
        )
    )
    if blockers:
        return blockers
    expected = _migration_counts([entry for entry in entries if isinstance(entry, Mapping)])
    for classification, actual in sorted(expected.items()):
        if counts.get(classification) != actual:
            blockers.append(f"{reason_prefix}_mismatch:{classification}")
    return blockers


def _prepared_plan_next_actions_blockers(value: Any, *, reason_prefix: str) -> list[str]:
    if not isinstance(value, Mapping):
        return [f"{reason_prefix}_not_mapping"]
    blockers = exact_key_blockers(
        value,
        required=REVIEW_TEAM_DIGEST_MIGRATION_CLASSIFICATIONS,
        allowed=REVIEW_TEAM_DIGEST_MIGRATION_CLASSIFICATIONS,
        reason_prefix=reason_prefix,
    )
    blockers.extend(
        typed_shape_blockers(
            value, spec=PREPARED_MIGRATION_NEXT_ACTIONS_SHAPE, reason_prefix=reason_prefix
        )
    )
    if blockers:
        return blockers
    for classification, expected in sorted(REVIEW_TEAM_DIGEST_MIGRATION_NEXT_ACTIONS.items()):
        if _frontmatter_non_null_scalar(value.get(classification)) != expected:
            blockers.append(f"{reason_prefix}_value_mismatch:{classification}")
    return blockers


def _prepared_plan_migration_authority_blockers(value: Any, *, reason_prefix: str) -> list[str]:
    if not isinstance(value, Mapping):
        return [f"{reason_prefix}_not_mapping"]
    blockers = exact_key_blockers(
        value,
        required=REVIEW_TEAM_DIGEST_MIGRATION_AUTHORITY_KEYS,
        allowed=REVIEW_TEAM_DIGEST_MIGRATION_AUTHORITY_KEYS,
        reason_prefix=reason_prefix,
    )
    blockers.extend(
        typed_shape_blockers(
            value, spec=PREPARED_MIGRATION_AUTHORITY_SHAPE, reason_prefix=reason_prefix
        )
    )
    blockers.extend(
        _prepared_plan_source_trust_anchor_blockers(
            value.get("source_trust_anchor"),
            reason_prefix=f"{reason_prefix}_source_trust_anchor",
        )
    )
    if not _valid_iso_datetime(_frontmatter_non_null_scalar(value.get("consumed_at"))):
        blockers.append(f"{reason_prefix}_consumed_at_invalid")
    return blockers


def _prepared_plan_receipt_drift_blockers(value: Any, *, reason_prefix: str) -> list[str]:
    if not isinstance(value, list):
        return [f"{reason_prefix}_not_list"]
    blockers: list[str] = []
    for index, item in enumerate(value):
        item_prefix = f"{reason_prefix}:{index}"
        if not isinstance(item, Mapping):
            blockers.append(f"{item_prefix}_not_mapping")
            continue
        status = _frontmatter_non_null_scalar(item.get("status"))
        # actual_receipt_sha256 exists exactly for the drifted-bytes status, never for the missing one.
        required = PREPARED_RECEIPT_DRIFT_KEYS - frozenset({"actual_receipt_sha256"})
        blockers.extend(
            exact_key_blockers(
                item,
                required=required,
                allowed=PREPARED_RECEIPT_DRIFT_KEYS,
                reason_prefix=item_prefix,
            )
        )
        blockers.extend(
            typed_shape_blockers(item, spec=PREPARED_RECEIPT_DRIFT_SHAPE, reason_prefix=item_prefix)
        )
        blockers.extend(
            _enum_value_blockers(
                status,
                allowed=PREPARED_RECEIPT_DRIFT_STATUSES,
                reason_prefix=f"{item_prefix}_status",
            )
        )
        if status == "sha256_mismatch" and "actual_receipt_sha256" not in item:
            blockers.append(f"{item_prefix}_actual_receipt_sha256_missing")
        if status == "missing_from_active" and "actual_receipt_sha256" in item:
            blockers.append(f"{item_prefix}_actual_receipt_sha256_unexpected")
    return blockers


def _prepared_plan_artifact_preflight_blockers(value: Any, *, reason_prefix: str) -> list[str]:
    if not isinstance(value, Mapping):
        return [f"{reason_prefix}_not_mapping"]
    blockers = exact_key_blockers(
        value,
        required=PREPARED_ARTIFACT_PREFLIGHT_REQUIRED_KEYS,
        allowed=PREPARED_ARTIFACT_PREFLIGHT_KEYS,
        reason_prefix=reason_prefix,
    )
    blockers.extend(
        typed_shape_blockers(
            value, spec=PREPARED_ARTIFACT_PREFLIGHT_SHAPE, reason_prefix=reason_prefix
        )
    )
    blockers.extend(
        _enum_value_blockers(
            value.get("status"),
            allowed=PREPARED_ARTIFACT_PREFLIGHT_STATUSES,
            reason_prefix=f"{reason_prefix}_status",
        )
    )
    if "sealed_generation" in value and value.get("sealed_generation") is not None:
        blockers.extend(
            _prepared_plan_sealed_generation_blockers(
                value.get("sealed_generation"),
                reason_prefix=f"{reason_prefix}_sealed_generation",
                allow_empty=True,
            )
        )
    return blockers


def _prepared_plan_frozen_inventory_blockers(
    value: Any,
    *,
    reason_prefix: str,
    expected_canonical_sha256: str | None,
) -> list[str]:
    if not isinstance(value, Mapping):
        return [f"{reason_prefix}_not_mapping"]
    blockers = exact_key_blockers(
        value,
        required=REVIEW_TEAM_DIGEST_MIGRATION_FROZEN_INVENTORY_KEYS,
        allowed=REVIEW_TEAM_DIGEST_MIGRATION_FROZEN_INVENTORY_KEYS,
        reason_prefix=reason_prefix,
    )
    blockers.extend(
        typed_shape_blockers(
            value, spec=PREPARED_FROZEN_INVENTORY_SHAPE, reason_prefix=reason_prefix
        )
    )
    if blockers:
        return blockers
    entries = value.get("entries")
    assert isinstance(entries, list)
    for index, entry in enumerate(entries):
        entry_prefix = f"{reason_prefix}_entry:{index}"
        blockers.extend(
            exact_key_blockers(
                entry,
                required=REVIEW_TEAM_DIGEST_MIGRATION_FROZEN_ENTRY_KEYS,
                allowed=REVIEW_TEAM_DIGEST_MIGRATION_FROZEN_ENTRY_KEYS,
                reason_prefix=entry_prefix,
            )
        )
        blockers.extend(
            typed_shape_blockers(
                entry, spec=PREPARED_FROZEN_ENTRY_SHAPE, reason_prefix=entry_prefix
            )
        )
    if value.get("count") != len(entries):
        blockers.append(f"{reason_prefix}_count_mismatch")
    actual = _canonical_frozen_inventory_sha256(entries)
    if _frontmatter_non_null_scalar(value.get("canonical_sha256")) != actual:
        blockers.append(f"{reason_prefix}_canonical_sha256_mismatch")
    if expected_canonical_sha256 is not None and actual != expected_canonical_sha256:
        blockers.append(f"{reason_prefix}_authority_sha256_mismatch")
    return blockers


def _prepared_plan_candidate_payload_blockers(migration: Mapping[str, Any]) -> list[str]:
    """The candidate payload IS the artifact this plan will write, so it gets the artifact's schema.

    Its exactness is established by relation rather than by a duplicated key set: every disposition-
    bearing object it carries (entries, counts, next_actions, authority, sealed_generation) must be
    the SAME object the migration carries -- and those are exactly typed above -- while the payload's
    own remaining keys are pinned here. Nothing is left as "some mapping".

    Deliberately environment-free: no ``resolve()``, no stat, no read. ``active_dir`` is admitted as
    a literal absolute path here and bound to the real vault root by the runtime's filesystem
    admission, so lifecycle and runtime keep running the identical decoder over the identical bytes.
    """

    prefix = "migration_prepared_plan_migration_candidate_payload"
    payload = migration.get("candidate_payload")
    if payload is None:
        return []
    if not isinstance(payload, Mapping):
        return [f"{prefix}_not_mapping"]
    blockers = exact_key_blockers(
        payload,
        required=REVIEW_TEAM_DIGEST_MIGRATION_TOP_LEVEL_KEYS,
        allowed=(
            REVIEW_TEAM_DIGEST_MIGRATION_TOP_LEVEL_KEYS
            | REVIEW_TEAM_DIGEST_MIGRATION_OPTIONAL_TOP_LEVEL_KEYS
        ),
        reason_prefix=prefix,
    )
    if blockers:
        return blockers
    if payload.get("schema") != REVIEW_TEAM_DIGEST_MIGRATION_SCHEMA:
        blockers.append(f"{prefix}_schema_mismatch")
    if payload.get("pause_boundary") != REVIEW_TEAM_DIGEST_MIGRATION_PAUSE_BOUNDARY:
        blockers.append(f"{prefix}_pause_boundary_mismatch")
    if payload.get("integrity_recheck") != REVIEW_TEAM_DIGEST_MIGRATION_INTEGRITY_RECHECK:
        blockers.append(f"{prefix}_integrity_recheck_mismatch")
    if not _valid_iso_datetime(_frontmatter_non_null_scalar(payload.get("generated_at"))):
        blockers.append(f"{prefix}_generated_at_invalid")
    active_dir = _frontmatter_non_null_scalar(payload.get("active_dir"))
    if not active_dir or not Path(active_dir).is_absolute() or ".." in Path(active_dir).parts:
        blockers.append(f"{prefix}_active_dir_invalid")

    authority = payload.get("authority")
    blockers.extend(
        _prepared_plan_migration_authority_blockers(authority, reason_prefix=f"{prefix}_authority")
    )
    expected_frozen = (
        _frontmatter_non_null_scalar(authority.get("frozen_inventory_canonical_sha256"))
        if isinstance(authority, Mapping)
        else None
    )
    if _frontmatter_non_null_scalar(payload.get("authority_proposal_id")) != (
        _frontmatter_non_null_scalar(authority.get("proposal_id"))
        if isinstance(authority, Mapping)
        else ""
    ):
        blockers.append(f"{prefix}_authority_proposal_id_mismatch")
    blockers.extend(
        _prepared_plan_frozen_inventory_blockers(
            payload.get("frozen_prebinding_inventory"),
            reason_prefix=f"{prefix}_frozen_prebinding_inventory",
            expected_canonical_sha256=expected_frozen or None,
        )
    )
    blockers.extend(
        _prepared_plan_sealed_generation_blockers(
            payload.get("sealed_generation"),
            reason_prefix=f"{prefix}_sealed_generation",
        )
    )

    # The payload's disposition-bearing objects and the migration's are ONE object, so the exact
    # typing already applied to the migration's is the exact typing of the payload's. A plan that
    # writes an artifact whose entries disagree with the entries it was ratified for dies here.
    for key in ("entries", "counts", "next_actions", "authority", "sealed_generation"):
        if key in migration and migration.get(key) != payload.get(key):
            blockers.append(f"{prefix}_{key}_diverges_from_migration")
    return blockers


def _prepared_plan_migration_claim_blockers(value: Any, *, reason_prefix: str) -> list[str]:
    """The held-claim report a replay echoes into the plan, closed to an exact schema.

    Every field here is authored by this protocol except ``holder``, which is the other process's
    lock document and is a declared authority boundary. An undeclared mapping in a digest-bound,
    operator-ratified plan is a schema the decoder owes, not a boundary it may assume.
    """

    if value is None:
        return []
    if not isinstance(value, Mapping):
        return [f"{reason_prefix}_not_mapping"]
    blockers = exact_key_blockers(
        value,
        required=PREPARED_MIGRATION_CLAIM_KEYS,
        allowed=PREPARED_MIGRATION_CLAIM_KEYS,
        reason_prefix=reason_prefix,
    )
    blockers.extend(
        typed_shape_blockers(
            value, spec=PREPARED_MIGRATION_CLAIM_SHAPE, reason_prefix=reason_prefix
        )
    )
    blockers.extend(
        _enum_value_blockers(
            value.get("status"),
            allowed=PREPARED_MIGRATION_CLAIM_STATUSES,
            reason_prefix=f"{reason_prefix}_status",
        )
    )
    evidence = value.get("lock_evidence")
    if not isinstance(evidence, Mapping):
        blockers.append(f"{reason_prefix}_lock_evidence_not_mapping")
        return blockers
    evidence_prefix = f"{reason_prefix}_lock_evidence"
    blockers.extend(
        exact_key_blockers(
            evidence,
            required=frozenset({"path", "status", "stat"}),
            allowed=PREPARED_MIGRATION_CLAIM_EVIDENCE_KEYS,
            reason_prefix=evidence_prefix,
        )
    )
    blockers.extend(
        typed_shape_blockers(
            evidence,
            spec=PREPARED_MIGRATION_CLAIM_EVIDENCE_SHAPE,
            reason_prefix=evidence_prefix,
        )
    )
    blockers.extend(
        _enum_value_blockers(
            evidence.get("status"),
            allowed=PREPARED_MIGRATION_CLAIM_STATUSES,
            reason_prefix=f"{evidence_prefix}_status",
        )
    )
    stat_evidence = evidence.get("stat")
    if not isinstance(stat_evidence, Mapping):
        blockers.append(f"{evidence_prefix}_stat_not_mapping")
        return blockers
    stat_prefix = f"{evidence_prefix}_stat"
    blockers.extend(
        exact_key_blockers(
            stat_evidence,
            required=frozenset({"exists"}),
            allowed=PREPARED_MIGRATION_CLAIM_STAT_KEYS,
            reason_prefix=stat_prefix,
        )
    )
    blockers.extend(
        typed_shape_blockers(
            stat_evidence,
            spec=PREPARED_MIGRATION_CLAIM_STAT_SHAPE,
            reason_prefix=stat_prefix,
        )
    )
    return blockers


def _prepared_plan_receipt_payload_blockers(
    payload: Any,
    *,
    raw: bytes | None,
    reason_prefix: str,
) -> list[str]:
    """The receipt payload must BE the document the receipt bytes decode to -- under its real schema.

    ``payload`` and ``raw_bytes_hex`` were two independently mutable descriptions of one write, with
    only ``raw_bytes_hex`` bound to a digest. The payload could therefore say one thing while the
    bytes that actually landed on disk said another, and every digest in the plan agreed. Binding
    the two closed that -- but it only proved they were the SAME document, never that the document
    was an acceptance receipt. These bytes are written to a receipt pathname by this protocol and
    admitted as a receipt afterwards, so the schema they must satisfy is the receipt's own, and it
    is owed at plan-decode time rather than discovered after the write lands.
    """

    if not isinstance(payload, Mapping):
        return [f"{reason_prefix}_not_mapping"]
    blockers = acceptance_receipt_document_blockers(payload, reason_prefix=reason_prefix)
    if raw is None:
        return blockers
    try:
        decoded = yaml.load(raw.decode("utf-8"), Loader=_NoDuplicateSafeLoader)
    except (UnicodeDecodeError, yaml.YAMLError):
        return [*blockers, f"{reason_prefix}_bytes_not_yaml"]
    if not isinstance(decoded, Mapping):
        return [*blockers, f"{reason_prefix}_bytes_not_mapping"]
    if dict(decoded) != dict(payload):
        blockers.append(f"{reason_prefix}_bytes_mismatch")
    return blockers


def _prepared_acceptance_trace_relation_blockers(
    trace: list[dict[str, Any]],
) -> list[str]:
    """Close the acceptance trace's own nested objects: route enum, legacy admission, sealed generation."""

    blockers: list[str] = []
    for index, item in enumerate(trace):
        prefix = f"migration_prepared_plan_acceptance_trace_item:{index}"
        route = _frontmatter_non_null_scalar(item.get("route"))
        blockers.extend(
            _enum_value_blockers(
                route,
                allowed=PREPARED_ACCEPTANCE_TRACE_ROUTES,
                reason_prefix=f"{prefix}_route",
            )
        )
        if item.get("legacy_admission") is not None:
            blockers.extend(
                _prepared_plan_legacy_admission_blockers(
                    item.get("legacy_admission"),
                    reason_prefix=f"{prefix}_legacy_admission",
                    allow_empty=True,
                )
            )
        if item.get("sealed_generation") is not None:
            blockers.extend(
                _prepared_plan_sealed_generation_blockers(
                    item.get("sealed_generation"),
                    reason_prefix=f"{prefix}_sealed_generation",
                    allow_empty=True,
                )
            )
    return blockers


def _prepared_plan_migration_object_blockers(migration: Mapping[str, Any]) -> list[str]:
    """Every plan-owned nested object inside ``migration``, closed to an exact schema."""

    prefix = "migration_prepared_plan_migration"
    entries = migration.get("entries")
    blockers: list[str] = []
    blockers.extend(
        _enum_value_blockers(
            migration.get("status"),
            allowed=PREPARED_MIGRATION_STATUSES,
            reason_prefix=f"{prefix}_status",
        )
    )
    if migration.get("generated_at") is not None and not _valid_iso_datetime(
        _frontmatter_non_null_scalar(migration.get("generated_at"))
    ):
        blockers.append(f"{prefix}_generated_at_invalid")
    if isinstance(entries, list):
        for index, entry in enumerate(entries):
            blockers.extend(
                _prepared_plan_migration_entry_blockers(
                    entry, reason_prefix=f"{prefix}_entry:{index}"
                )
            )
        blockers.extend(
            _prepared_plan_counts_blockers(
                migration.get("counts"),
                entries=entries,
                reason_prefix=f"{prefix}_counts",
            )
        )
    if migration.get("next_actions") is not None:
        blockers.extend(
            _prepared_plan_next_actions_blockers(
                migration.get("next_actions"), reason_prefix=f"{prefix}_next_actions"
            )
        )
    if migration.get("authority") is not None:
        blockers.extend(
            _prepared_plan_migration_authority_blockers(
                migration.get("authority"), reason_prefix=f"{prefix}_authority"
            )
        )
    if migration.get("sealed_generation") is not None:
        blockers.extend(
            _prepared_plan_sealed_generation_blockers(
                migration.get("sealed_generation"), reason_prefix=f"{prefix}_sealed_generation"
            )
        )
    if migration.get("current_receipt_drift") is not None:
        blockers.extend(
            _prepared_plan_receipt_drift_blockers(
                migration.get("current_receipt_drift"),
                reason_prefix=f"{prefix}_current_receipt_drift",
            )
        )
    if migration.get("artifact_preflight") is not None:
        blockers.extend(
            _prepared_plan_artifact_preflight_blockers(
                migration.get("artifact_preflight"), reason_prefix=f"{prefix}_artifact_preflight"
            )
        )
    blockers.extend(_prepared_plan_candidate_payload_blockers(migration))
    return blockers


def _decode_prepared_plan_migration(raw_migration: Any) -> tuple[dict[str, Any], list[str]]:
    prefix = "migration_prepared_plan_migration"
    if not isinstance(raw_migration, Mapping):
        return {}, [f"{prefix}_not_mapping"]
    blockers = exact_key_blockers(
        raw_migration,
        required=PREPARED_MIGRATION_REQUIRED_KEYS,
        allowed=PREPARED_MIGRATION_ALLOWED_KEYS,
        reason_prefix=prefix,
    )
    blockers.extend(
        typed_shape_blockers(
            raw_migration,
            spec=PREPARED_MIGRATION_SHAPE,
            reason_prefix=prefix,
        )
    )
    if not blockers:
        blockers.extend(_prepared_plan_migration_object_blockers(raw_migration))
    migration = dict(raw_migration)
    raw_hex = migration.pop("candidate_raw_bytes_hex", None)
    raw: bytes | None = None
    if raw_hex is not None:
        raw, error = _plan_bytes_from_hex(raw_hex, field_name="migration_candidate_raw_bytes_hex")
        if error:
            blockers.append(error)
        elif raw is not None:
            migration["candidate_raw_bytes"] = raw
    if migration.get("artifact_written") is not False:
        blockers.append(f"{prefix}_artifact_written_invalid")
    for key in (
        "candidate_artifact_sha256",
        "before_artifact_sha256",
        "after_artifact_sha256",
    ):
        value = migration.get(key)
        if (
            value is not None
            and REVIEW_TEAM_DIGEST_MIGRATION_SHA256_RE.fullmatch(str(value)) is None
        ):
            blockers.append(f"{prefix}_{key}_invalid")
    candidate_sha = migration.get("candidate_artifact_sha256")
    if (
        isinstance(raw, bytes)
        and candidate_sha is not None
        and _sha256_prefixed(raw) != candidate_sha
    ):
        blockers.append(f"{prefix}_candidate_raw_sha256_mismatch")
    target_preimage = migration.get("target_preimage")
    if target_preimage is not None:
        blockers.extend(
            _prepared_target_preimage_blockers(
                target_preimage,
                reason_prefix=f"{prefix}_target_preimage",
            )
        )
    return migration, blockers


def _decode_prepared_plan_receipt_writes(raw_writes: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(raw_writes, list):
        return [], ["migration_prepared_plan_receipt_writes_not_list"]
    writes: list[dict[str, Any]] = []
    blockers: list[str] = []
    for index, raw_write in enumerate(raw_writes):
        prefix = f"migration_prepared_plan_receipt_write:{index}"
        if not isinstance(raw_write, Mapping):
            blockers.append(f"migration_prepared_plan_receipt_write_not_mapping:{index}")
            continue
        blockers.extend(
            exact_key_blockers(
                raw_write,
                required=PREPARED_RECEIPT_WRITE_KEYS,
                allowed=PREPARED_RECEIPT_WRITE_KEYS,
                reason_prefix=prefix,
            )
        )
        blockers.extend(
            typed_shape_blockers(
                raw_write,
                spec=PREPARED_RECEIPT_WRITE_SHAPE,
                reason_prefix=prefix,
            )
        )
        write = dict(raw_write)
        if write.get("kind") != "acceptance_receipt":
            blockers.append(f"migration_prepared_plan_receipt_write_kind_invalid:{index}")
        raw_hex = write.pop("raw_bytes_hex", None)
        raw, error = _plan_bytes_from_hex(
            raw_hex, field_name=f"receipt_write_raw_bytes_hex:{index}"
        )
        if error:
            blockers.append(error)
        elif raw is not None:
            write["raw_bytes"] = raw
        if not isinstance(write.get("path"), str) or not write.get("path"):
            blockers.append(f"migration_prepared_plan_receipt_write_path_invalid:{index}")
        existing_sha = write.get("existing_sha256")
        if (
            existing_sha is not None
            and REVIEW_TEAM_DIGEST_MIGRATION_SHA256_RE.fullmatch(str(existing_sha)) is None
        ):
            blockers.append(
                f"migration_prepared_plan_receipt_write_existing_sha256_invalid:{index}"
            )
        write_sha = write.get("sha256")
        if REVIEW_TEAM_DIGEST_MIGRATION_SHA256_RE.fullmatch(str(write_sha or "")) is None:
            blockers.append(f"migration_prepared_plan_receipt_write_sha256_invalid:{index}")
        elif isinstance(raw, bytes) and write_sha != _sha256_prefixed(raw):
            blockers.append(f"migration_prepared_plan_receipt_write_raw_sha256_mismatch:{index}")
        blockers.extend(
            _prepared_plan_receipt_payload_blockers(
                write.get("payload"),
                raw=raw,
                reason_prefix=f"migration_prepared_plan_receipt_write_payload:{index}",
            )
        )
        blockers.extend(
            _prepared_target_preimage_blockers(
                write.get("target_preimage"),
                reason_prefix=f"migration_prepared_plan_receipt_write_target_preimage:{index}",
            )
        )
        writes.append(write)
    return writes, blockers


def _prepared_plan_candidate_relation_blockers(
    *,
    migration: Mapping[str, Any],
    plan_binding_core: Mapping[str, Any],
    candidate_authority: Mapping[str, Any],
) -> list[str]:
    """Phase-conditional totality: candidate digests are required exactly when effects are planned.

    A plan with no candidate payload is a legal no-op and carries null candidate digests. A plan
    that does write the artifact must carry them, so a null here cannot smuggle an unbound write.
    """

    if not isinstance(migration.get("candidate_payload"), Mapping):
        return []
    blockers: list[str] = []
    for label, mapping in (
        ("binding_core", plan_binding_core),
        ("candidate_authority", candidate_authority),
    ):
        value = mapping.get("candidate_artifact_core_sha256")
        if not isinstance(value, str) or (
            REVIEW_TEAM_DIGEST_MIGRATION_SHA256_RE.fullmatch(value) is None
        ):
            blockers.append(
                f"migration_prepared_plan_{label}_candidate_artifact_core_sha256_required"
            )
    candidate_sha = plan_binding_core.get("candidate_artifact_sha256")
    if not isinstance(candidate_sha, str) or (
        REVIEW_TEAM_DIGEST_MIGRATION_SHA256_RE.fullmatch(candidate_sha) is None
    ):
        blockers.append("migration_prepared_plan_binding_core_candidate_artifact_sha256_required")
    return blockers


def _prepared_plan_candidate_binding_blockers(
    *,
    migration: Mapping[str, Any],
    plan_binding_core: Mapping[str, Any],
    candidate_authority: Mapping[str, Any],
) -> list[str]:
    """Bind the candidate payload, its exact bytes, its file digest and its core digest to ONE object.

    ``candidate_payload`` and ``candidate_raw_bytes_hex`` used to be two independently mutable
    representations of "the artifact this plan will write", cross-checked against nothing: editing
    the payload while leaving the bytes and every digest claim untouched produced a plan that
    decoded, hashed and admitted cleanly, and the artifact that would actually be written was NOT
    the artifact the authority chain ratified.

    Everything is therefore re-derived from a single decoded object -- the payload parsed back out of
    the plan's own candidate bytes. The bytes must re-serialize to themselves, the payload must equal
    what those bytes actually say, and the file and core digests must be recomputed from that same
    object and agree in the migration, the binding core and the candidate authority. A semantic edit
    with unchanged byte and digest claims now dies here.
    """

    prefix = "migration_prepared_plan_migration"
    payload = migration.get("candidate_payload")
    if not isinstance(payload, Mapping):
        return []
    raw = migration.get("candidate_raw_bytes")
    if not isinstance(raw, bytes):
        return [f"{prefix}_candidate_raw_bytes_missing"]

    blockers: list[str] = []
    try:
        decoded = yaml.load(raw.decode("utf-8"), Loader=_NoDuplicateSafeLoader)
    except (UnicodeDecodeError, yaml.YAMLError):
        return [f"{prefix}_candidate_raw_bytes_not_yaml"]
    if not isinstance(decoded, Mapping):
        return [f"{prefix}_candidate_raw_bytes_not_mapping"]

    # The bytes are the artifact. The payload is only a claim ABOUT the bytes.
    if dict(decoded) != dict(payload):
        blockers.append(f"{prefix}_candidate_payload_bytes_mismatch")
    if _prepared_plan_yaml_bytes(decoded) != raw:
        blockers.append(f"{prefix}_candidate_raw_bytes_not_canonical")

    artifact_sha = _sha256_prefixed(raw)
    core_sha = _candidate_artifact_core_sha256(decoded)
    for label, mapping, key, expected in (
        ("migration", migration, "candidate_artifact_sha256", artifact_sha),
        ("migration", migration, "candidate_artifact_core_sha256", core_sha),
        ("binding_core", plan_binding_core, "candidate_artifact_sha256", artifact_sha),
        ("binding_core", plan_binding_core, "candidate_artifact_core_sha256", core_sha),
        (
            "candidate_authority",
            candidate_authority,
            "candidate_artifact_core_sha256",
            core_sha,
        ),
    ):
        if label == "migration" and key not in mapping:
            # The migration's own digest claims are optional keys; the binding core and candidate
            # authority carry the required ones and are checked unconditionally.
            continue
        if mapping.get(key) != expected:
            blockers.append(f"migration_prepared_plan_{label}_{key}_mismatch")
    return blockers


def candidate_authority_artifact_form(candidate_authority: Mapping[str, Any]) -> dict[str, Any]:
    """The candidate authority AS IT IS EMBEDDED IN THE ARTIFACT: the ratified object plus its digest.

    This is the single definition of that transform. The planner mints the artifact with it and the
    decoder re-derives it, so the authority the artifact carries can never be anything but the
    authority the operator ratified.
    """

    form = dict(candidate_authority)
    form["candidate_authority_sha256"] = _canonical_json_sha256(candidate_authority)
    return form


def _prepared_plan_candidate_authority_commitment_blockers(
    *,
    migration: Mapping[str, Any],
    candidate_authority: Mapping[str, Any],
    plan_candidate_authority_sha256: Any,
) -> list[str]:
    """The authority EMBEDDED in the artifact must be the authority the operator RATIFIED.

    The artifact's core digest deliberately excludes ``candidate_authority`` -- the authority is
    computed over the core, so it cannot also be inside it without a cycle. That exclusion was load
    bearing and unguarded: rewriting the embedded authority to ``{"forged": true, ...}``, then
    recomputing the candidate bytes and the candidate FILE digest, left the core digest and every
    ratified binding untouched. The plan decoded with blockers=[] and would have written an artifact
    whose self-declared authority was an object nobody ever ratified.

    The excluded field is therefore pinned by relation instead: the embedded authority must equal the
    ratified candidate authority in its artifact form -- byte for byte, including the exact self
    digest -- and the migration's own authority digest must equal the plan's claim.
    """

    prefix = "migration_prepared_plan_migration"
    payload = migration.get("candidate_payload")
    if not isinstance(payload, Mapping):
        return []

    blockers: list[str] = []
    expected = candidate_authority_artifact_form(candidate_authority)
    embedded = payload.get("candidate_authority")
    if embedded is None:
        blockers.append(f"{prefix}_candidate_payload_candidate_authority_missing")
    elif not isinstance(embedded, Mapping):
        blockers.append(f"{prefix}_candidate_payload_candidate_authority_not_mapping")
    elif dict(embedded) != expected:
        blockers.append(f"{prefix}_candidate_payload_candidate_authority_mismatch")

    declared = migration.get("candidate_authority_sha256")
    if declared is not None and declared != plan_candidate_authority_sha256:
        blockers.append(f"{prefix}_candidate_authority_sha256_diverges_from_plan")
    return blockers


def _prepared_plan_cross_object_blockers(
    *,
    payload: Mapping[str, Any],
    authority: Mapping[str, Any],
    migration: Mapping[str, Any],
    artifact_preflight: Mapping[str, Any],
    lock_transition: Mapping[str, Any],
    evidence_manifest: Mapping[str, Any],
    binding_core: Mapping[str, Any],
) -> list[str]:
    """The same object, carried in four places, must be the SAME OBJECT in all four.

    A prepared plan duplicates its authority, its preflight and its lock transition across the
    top level, the migration, the evidence manifest and the candidate artifact. Each copy was
    decoded against its own schema and none against the others, so a plan could be internally
    well-typed while its manifest described one authority, its migration a second and its artifact a
    third -- and only one of them is the one the ratified digests actually cover.

    Duplication is only safe when it is proved redundant. Where two objects overlap, they must
    agree; where one is a projection of the other (the manifest's authority carries a subset of the
    plan authority's keys), the projection must agree on every key it carries.
    """

    prefix = "migration_prepared_plan"
    blockers: list[str] = []

    manifest_anchor = evidence_manifest.get("source_trust_anchor")
    if manifest_anchor != authority.get("source_trust_anchor"):
        blockers.append(f"{prefix}_evidence_manifest_source_trust_anchor_diverges_from_authority")
    if evidence_manifest.get("artifact_preflight") != dict(artifact_preflight):
        blockers.append(f"{prefix}_evidence_manifest_artifact_preflight_diverges_from_plan")
    if evidence_manifest.get("lock_transition") != dict(lock_transition):
        blockers.append(f"{prefix}_evidence_manifest_lock_transition_diverges_from_plan")
    if evidence_manifest.get("planned_writes") != binding_core.get("write_set"):
        blockers.append(f"{prefix}_evidence_manifest_planned_writes_diverges_from_write_set")

    manifest_authority = evidence_manifest.get("authority")
    if isinstance(manifest_authority, Mapping):
        for key in sorted(PREPARED_EVIDENCE_AUTHORITY_KEYS):
            if manifest_authority.get(key) != authority.get(key):
                blockers.append(f"{prefix}_evidence_manifest_authority_{key}_diverges_from_plan")

    migration_authority = migration.get("authority")
    if isinstance(migration_authority, Mapping):
        # The migration's authority is a SUPERSET: it also carries the consumed-act provenance the
        # plan-level object leaves out. Every key they share must still be the same key.
        for key in sorted(authority):
            if migration_authority.get(key) != authority.get(key):
                blockers.append(f"{prefix}_migration_authority_{key}_diverges_from_plan")

    if migration.get("artifact_preflight") is not None and migration.get(
        "artifact_preflight"
    ) != dict(artifact_preflight):
        blockers.append(f"{prefix}_migration_artifact_preflight_diverges_from_plan")

    # migration.generated_at is deliberately NOT tied to the plan's. An unchanged migration carries
    # the timestamp of the artifact that was ALREADY sealed, which is older than the plan that
    # re-observed it -- so equality here would reject every idempotent re-run. Both are required to
    # be valid aware instants; neither is required to be the other.
    return blockers


@dataclass(frozen=True)
class DecodedPreparedMigrationPlan:
    """The typed result of the one shared plan decoder: decoded values, or the reasons there are none."""

    blockers: tuple[str, ...]
    payload: dict[str, Any] = dataclass_field(default_factory=dict)
    authority: dict[str, Any] = dataclass_field(default_factory=dict)
    artifact_preflight: dict[str, Any] = dataclass_field(default_factory=dict)
    snapshots: tuple[dict[str, Any], ...] = ()
    open_pr_results: list[dict[str, Any]] = dataclass_field(default_factory=list)
    migration: dict[str, Any] = dataclass_field(default_factory=dict)
    receipt_writes: list[dict[str, Any]] = dataclass_field(default_factory=list)
    evidence_manifest: dict[str, Any] = dataclass_field(default_factory=dict)
    lock_transition: dict[str, Any] = dataclass_field(default_factory=dict)
    plan_binding_core: dict[str, Any] = dataclass_field(default_factory=dict)
    candidate_authority: dict[str, Any] = dataclass_field(default_factory=dict)
    acceptance_admission_trace: list[dict[str, Any]] = dataclass_field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blockers


def decode_prepared_migration_plan(payload: Any) -> DecodedPreparedMigrationPlan:
    """The one exact PreparedMigrationPlan decoder shared by runtime apply and lifecycle admission.

    Structural only: it never touches the filesystem, so both callers run the identical key sets,
    scalar kinds, enums, protocol constants, digests, byte bindings and relations over the identical
    decoded object. Every derived value -- disposition manifest, write set, plan identity, candidate
    authority digest, candidate artifact bytes and ratification response -- is RECOMPUTED from the
    decoded inputs. A plan that merely agrees with its own claimed digests is rejected:
    self-consistency is not evidence.

    Callers add only environment-specific FILESYSTEM checks on top (the runtime binds vault-root
    paths and on-disk digests; lifecycle binds the artifact's candidate authority).
    """

    prefix = "migration_prepared_plan"
    if not isinstance(payload, Mapping):
        return DecodedPreparedMigrationPlan(blockers=(f"{prefix}_not_mapping",))
    if (
        _frontmatter_non_null_scalar(payload.get("schema"))
        != REVIEW_TEAM_DIGEST_MIGRATION_PREPARED_PLAN_SCHEMA
    ):
        return DecodedPreparedMigrationPlan(blockers=(f"{prefix}_schema_mismatch",))
    key_blockers = exact_key_blockers(
        payload,
        required=REVIEW_TEAM_DIGEST_MIGRATION_PREPARED_PLAN_KEYS,
        allowed=REVIEW_TEAM_DIGEST_MIGRATION_PREPARED_PLAN_KEYS,
        reason_prefix=prefix,
    )
    if key_blockers:
        return DecodedPreparedMigrationPlan(blockers=tuple(key_blockers))

    blockers: list[str] = []
    # Protocol constants are not negotiable per plan.
    if payload.get("recovery_policy") != REVIEW_TEAM_DIGEST_MIGRATION_RECOVERY_POLICY:
        blockers.append(f"{prefix}_recovery_policy_mismatch")
    if payload.get("assertions") != REVIEW_TEAM_DIGEST_MIGRATION_APPLY_ASSERTIONS:
        blockers.append(f"{prefix}_assertions_mismatch")
    if not isinstance(payload.get("repo"), str) or not payload.get("repo"):
        blockers.append(f"{prefix}_repo_invalid")
    # A plan's timestamp is an INSTANT, not a nonempty string. It was typed as the latter, so
    # generated_at="not-an-instant" re-canonicalized, re-digested and decoded with blockers=[] --
    # inside a decoder whose whole claim is that every field has an exact type.
    if not _valid_iso_datetime(_frontmatter_non_null_scalar(payload.get("generated_at"))):
        blockers.append(f"{prefix}_generated_at_invalid")
    blockers.extend(
        typed_shape_blockers(
            payload,
            spec={
                "schema": "str",
                # Instant-ness is asserted above, so the blocker names one reason, not two.
                "generated_at": "str",
                "repo": "str",
                "candidate_authority_sha256": "sha256",
                "candidate_authority_response": "str",
                "recovery_policy": "mapping",
                "assertions": "mapping",
            },
            reason_prefix=prefix,
        )
    )

    authority = payload.get("authority")
    if not isinstance(authority, Mapping):
        blockers.append(f"{prefix}_authority_not_mapping")
        authority = {}
    else:
        blockers.extend(
            exact_key_blockers(
                authority,
                required=REVIEW_TEAM_DIGEST_MIGRATION_PREPARED_PLAN_AUTHORITY_KEYS,
                allowed=REVIEW_TEAM_DIGEST_MIGRATION_PREPARED_PLAN_AUTHORITY_KEYS,
                reason_prefix=f"{prefix}_authority",
            )
        )
        blockers.extend(
            typed_shape_blockers(
                authority,
                spec=PREPARED_MIGRATION_PLAN_AUTHORITY_SHAPE,
                reason_prefix=f"{prefix}_authority",
            )
        )
        blockers.extend(
            _prepared_plan_source_trust_anchor_blockers(
                authority.get("source_trust_anchor"),
                reason_prefix=f"{prefix}_authority_source_trust_anchor",
            )
        )
        if not isinstance(authority.get("frozen_inventory_count"), int) or isinstance(
            authority.get("frozen_inventory_count"), bool
        ):
            blockers.append(f"{prefix}_authority_frozen_inventory_count_invalid")

    migration, migration_blockers = _decode_prepared_plan_migration(payload.get("migration"))
    blockers.extend(migration_blockers)
    receipt_writes, write_blockers = _decode_prepared_plan_receipt_writes(
        payload.get("receipt_writes")
    )
    blockers.extend(write_blockers)

    snapshots_list, snapshot_blockers = _prepared_plan_mapping_list_blockers(
        payload.get("snapshots"),
        item_allowed_keys=PREPARED_SNAPSHOT_KEYS,
        item_required_keys=frozenset(
            {"task_id", "receipt_path", "receipt_relpath", "receipt_basename", "receipt_sha256"}
        ),
        item_shape=PREPARED_SNAPSHOT_SHAPE,
        reason_prefix=f"{prefix}_snapshot",
    )
    blockers.extend(snapshot_blockers)
    open_pr_results, open_pr_blockers = _prepared_plan_mapping_list_blockers(
        payload.get("open_pr_results"),
        item_allowed_keys=PREPARED_OPEN_PR_RESULT_KEYS,
        item_required_keys=frozenset({"status"}),
        item_shape=PREPARED_OPEN_PR_RESULT_SHAPE,
        reason_prefix=f"{prefix}_open_pr_result",
    )
    blockers.extend(open_pr_blockers)
    if not open_pr_blockers:
        for index, open_pr_result in enumerate(open_pr_results):
            blockers.extend(
                _prepared_plan_migration_claim_blockers(
                    open_pr_result.get("migration_claim"),
                    reason_prefix=f"{prefix}_open_pr_result_item:{index}_migration_claim",
                )
            )
    acceptance_trace, trace_blockers = _prepared_plan_mapping_list_blockers(
        payload.get("acceptance_admission_trace"),
        item_allowed_keys=PREPARED_ACCEPTANCE_TRACE_KEYS,
        item_required_keys=frozenset({"task_id", "accepted", "route", "blockers"}),
        item_shape=PREPARED_ACCEPTANCE_TRACE_SHAPE,
        reason_prefix=f"{prefix}_acceptance_trace",
    )
    blockers.extend(trace_blockers)
    if not trace_blockers:
        blockers.extend(_prepared_acceptance_trace_relation_blockers(acceptance_trace))

    blockers.extend(_prepared_evidence_manifest_blockers(payload.get("evidence_manifest")))
    evidence_manifest = payload.get("evidence_manifest")
    if not isinstance(evidence_manifest, Mapping):
        evidence_manifest = {}

    artifact_preflight = payload.get("artifact_preflight")
    if not isinstance(artifact_preflight, Mapping):
        blockers.append(f"{prefix}_artifact_preflight_not_mapping")
        artifact_preflight = {}
    else:
        blockers.extend(
            _prepared_plan_artifact_preflight_blockers(
                artifact_preflight,
                reason_prefix=f"{prefix}_artifact_preflight",
            )
        )

    lock_transition = payload.get("lock_transition")
    if not isinstance(lock_transition, Mapping):
        blockers.append(f"{prefix}_lock_transition_not_mapping")
        lock_transition = {}
    else:
        blockers.extend(
            exact_key_blockers(
                lock_transition,
                required=PREPARED_LOCK_TRANSITION_KEYS,
                allowed=PREPARED_LOCK_TRANSITION_KEYS,
                reason_prefix=f"{prefix}_lock_transition",
            )
        )
        blockers.extend(
            typed_shape_blockers(
                lock_transition,
                spec=PREPARED_LOCK_TRANSITION_SHAPE,
                reason_prefix=f"{prefix}_lock_transition",
            )
        )

    binding_core = payload.get("plan_binding_core")
    if not isinstance(binding_core, Mapping):
        blockers.append(f"{prefix}_binding_core_not_mapping")
        binding_core = {}
    else:
        blockers.extend(
            exact_key_blockers(
                binding_core,
                required=REVIEW_TEAM_DIGEST_MIGRATION_PREPARED_PLAN_BINDING_CORE_KEYS,
                allowed=REVIEW_TEAM_DIGEST_MIGRATION_PREPARED_PLAN_BINDING_CORE_KEYS,
                reason_prefix=f"{prefix}_binding_core",
            )
        )
        blockers.extend(
            typed_shape_blockers(
                binding_core,
                spec=PREPARED_MIGRATION_PLAN_BINDING_CORE_SHAPE,
                reason_prefix=f"{prefix}_binding_core",
            )
        )

    candidate_authority = payload.get("candidate_authority")
    if not isinstance(candidate_authority, Mapping):
        blockers.append(f"{prefix}_candidate_authority_not_mapping")
        candidate_authority = {}
    else:
        blockers.extend(
            exact_key_blockers(
                candidate_authority,
                required=REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_CARRIER_CANDIDATE_KEYS,
                allowed=REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_CARRIER_CANDIDATE_KEYS,
                reason_prefix=f"{prefix}_candidate_authority",
            )
        )
        blockers.extend(
            typed_shape_blockers(
                candidate_authority,
                spec=MIGRATION_CANDIDATE_AUTHORITY_SHAPE,
                reason_prefix=f"{prefix}_candidate_authority",
            )
        )
    if blockers:
        return DecodedPreparedMigrationPlan(blockers=tuple(dict.fromkeys(blockers)))

    entries = migration.get("entries") or []
    snapshots = tuple(snapshots_list)
    blockers.extend(
        _prepared_plan_candidate_relation_blockers(
            migration=migration,
            plan_binding_core=binding_core,
            candidate_authority=candidate_authority,
        )
    )
    blockers.extend(
        _prepared_plan_candidate_binding_blockers(
            migration=migration,
            plan_binding_core=binding_core,
            candidate_authority=candidate_authority,
        )
    )
    blockers.extend(
        _prepared_plan_candidate_authority_commitment_blockers(
            migration=migration,
            candidate_authority=candidate_authority,
            plan_candidate_authority_sha256=payload.get("candidate_authority_sha256"),
        )
    )

    blockers.extend(
        _plan_sha256_field_blockers(
            binding_core,
            keys=(
                "candidate_artifact_core_sha256",
                "candidate_artifact_sha256",
                "disposition_manifest_sha256",
                "write_set_sha256",
                "evidence_manifest_sha256",
                "plan_sha256",
            ),
            reason_prefix=f"{prefix}_binding_core",
        )
    )
    if binding_core.get("schema") != REVIEW_TEAM_DIGEST_MIGRATION_PREPARED_PLAN_BINDING_CORE_SCHEMA:
        blockers.append(f"{prefix}_binding_core_schema_mismatch")
    snapshot_count = binding_core.get("snapshot_count")
    if isinstance(snapshot_count, bool) or not isinstance(snapshot_count, int):
        blockers.append(f"{prefix}_binding_core_snapshot_count_invalid")
    elif snapshot_count != len(snapshots):
        blockers.append(f"{prefix}_binding_core_snapshot_count_mismatch")
    if binding_core.get(
        "snapshot_fingerprint"
    ) != review_team_digest_migration_snapshot_fingerprint(snapshots):
        blockers.append(f"{prefix}_snapshot_fingerprint_mismatch")
    for key in ("disposition_manifest", "write_set", "evidence_manifest"):
        if not isinstance(binding_core.get(key), Mapping):
            blockers.append(f"{prefix}_binding_core_{key}_not_mapping")
    if blockers:
        return DecodedPreparedMigrationPlan(blockers=tuple(dict.fromkeys(blockers)))

    # Recompute, never trust. A forged manifest or write set that carries its old digest dies here.
    expected_disposition = review_team_digest_migration_disposition_manifest(entries)
    if binding_core.get("disposition_manifest") != expected_disposition:
        blockers.append(f"{prefix}_binding_core_disposition_manifest_mismatch")
    if binding_core.get("disposition_manifest_sha256") != _canonical_json_sha256(
        expected_disposition
    ):
        blockers.append(f"{prefix}_binding_core_disposition_manifest_sha256_mismatch")

    expected_write_set = review_team_digest_migration_write_set(
        migration=migration,
        receipt_writes=receipt_writes,
    )
    if binding_core.get("write_set") != expected_write_set:
        blockers.append(f"{prefix}_binding_core_write_set_mismatch")
    if binding_core.get("write_set_sha256") != _canonical_json_sha256(expected_write_set):
        blockers.append(f"{prefix}_binding_core_write_set_sha256_mismatch")

    if binding_core.get("evidence_manifest") != payload.get("evidence_manifest"):
        blockers.append(f"{prefix}_binding_core_evidence_manifest_mismatch")
    if binding_core.get("evidence_manifest_sha256") != _canonical_json_sha256(
        payload.get("evidence_manifest")
    ):
        blockers.append(f"{prefix}_binding_core_evidence_manifest_sha256_mismatch")

    # The duplicated-object relations belong in THIS phase, alongside the recomputations: they are
    # equalities, not preconditions, so reporting them must not pre-empt the deeper finding that a
    # derived object disagrees with what it was derived from.
    blockers.extend(
        _prepared_plan_cross_object_blockers(
            payload=payload,
            authority=authority,
            migration=migration,
            artifact_preflight=artifact_preflight,
            lock_transition=lock_transition,
            evidence_manifest=evidence_manifest,
            binding_core=binding_core,
        )
    )

    plan_identity = {
        "schema": binding_core.get("schema"),
        "candidate_artifact_core_sha256": binding_core.get("candidate_artifact_core_sha256"),
        "disposition_manifest_sha256": binding_core.get("disposition_manifest_sha256"),
        "write_set_sha256": binding_core.get("write_set_sha256"),
        "evidence_manifest_sha256": binding_core.get("evidence_manifest_sha256"),
    }
    if binding_core.get("plan_sha256") != _canonical_json_sha256(plan_identity):
        blockers.append(f"{prefix}_binding_core_plan_sha256_mismatch")

    # A planned artifact write must carry its candidate digests; a null cannot smuggle an unbound
    # write past the authority chain.
    if isinstance(migration.get("candidate_payload"), Mapping):
        for key in ("candidate_artifact_core_sha256", "candidate_artifact_sha256"):
            if binding_core.get(key) is None:
                blockers.append(f"{prefix}_binding_core_{key}_required")

    if candidate_authority.get("schema") != REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_AUTHORITY_SCHEMA:
        blockers.append(f"{prefix}_candidate_authority_schema_mismatch")
    candidate_sha = _canonical_json_sha256(candidate_authority)
    if _frontmatter_non_null_scalar(payload.get("candidate_authority_sha256")) != candidate_sha:
        blockers.append(f"{prefix}_candidate_authority_sha256_mismatch")
    expected_response = (
        f"RATIFY {_frontmatter_non_null_scalar(candidate_authority.get('id'))} "
        f"candidate_authority_sha256={candidate_sha}"
    )
    if payload.get("candidate_authority_response") != expected_response:
        blockers.append(f"{prefix}_candidate_authority_response_mismatch")

    expected_locator = (
        "review-team-digest-migration.candidate-carrier."
        f"{str(binding_core.get('plan_sha256') or '').removeprefix('sha256:')}.yaml"
    )
    if candidate_authority.get("candidate_carrier_locator") != expected_locator:
        blockers.append(f"{prefix}_candidate_authority_carrier_locator_mismatch")

    # Every candidate-authority digest is re-derived from the binding core or the plan's authority.
    for key, expected in (
        ("candidate_artifact_core_sha256", binding_core.get("candidate_artifact_core_sha256")),
        ("disposition_manifest_sha256", binding_core.get("disposition_manifest_sha256")),
        ("write_set_sha256", binding_core.get("write_set_sha256")),
        ("evidence_manifest_sha256", binding_core.get("evidence_manifest_sha256")),
        ("plan_sha256", binding_core.get("plan_sha256")),
        ("migration_authority_proposal_sha256", authority.get("proposal_sha256")),
        (
            "migration_authority_consumed_act_carrier_sha256",
            authority.get("consumed_act_carrier_sha256"),
        ),
        (
            "frozen_inventory_canonical_sha256",
            authority.get("frozen_inventory_canonical_sha256"),
        ),
    ):
        if candidate_authority.get(key) != expected:
            blockers.append(f"{prefix}_candidate_authority_{key}_mismatch")

    if blockers:
        return DecodedPreparedMigrationPlan(blockers=tuple(dict.fromkeys(blockers)))
    return DecodedPreparedMigrationPlan(
        blockers=(),
        payload=dict(payload),
        authority=dict(authority),
        artifact_preflight=dict(artifact_preflight),
        snapshots=snapshots,
        open_pr_results=open_pr_results,
        migration=migration,
        receipt_writes=receipt_writes,
        evidence_manifest=dict(evidence_manifest),
        lock_transition=dict(lock_transition),
        plan_binding_core=dict(binding_core),
        candidate_authority=dict(candidate_authority),
        acceptance_admission_trace=acceptance_trace,
    )


def prepared_migration_plan_blockers(payload: Any) -> tuple[str, ...]:
    """Blocker-only view of the one shared plan decoder, for callers that need no decoded values."""

    return decode_prepared_migration_plan(payload).blockers


def _embedded_prepared_plan_blockers(
    prepared_payload: Any,
    *,
    candidate: Mapping[str, Any],
    candidate_sha: str,
) -> tuple[str, ...]:
    """Decode the carrier's embedded prepared plan and bind it to the artifact's candidate authority.

    Hashing the embedded bytes only proves the carrier is self-consistent: a carrier that swaps in
    canonical ``{}`` and updates its own digest claims still passes. Lifecycle must therefore run
    the plan's own schema and re-derive the binding chain (plan identity, candidate authority,
    artifact core, disposition, write set, evidence manifest) from the exact embedded bytes.
    """

    prefix = "sealed_migration_candidate_authority_carrier_prepared_plan"
    # Lifecycle and the runtime apply path run the SAME exact decoder over the SAME decoded bytes.
    # A second, laxer lifecycle decoder is what let a grossly malformed embedded plan (non-list
    # receipt_writes, empty recovery_policy, forged manifests) reach admission while still hashing
    # self-consistently.
    plan_blockers = prepared_migration_plan_blockers(prepared_payload)
    if plan_blockers:
        # The shared decoder namespaces its blockers under "migration_prepared_plan"; re-root them
        # under the carrier prefix so the reason still says WHERE the bad plan was found.
        return tuple(
            f"{prefix}{blocker.removeprefix('migration_prepared_plan')}"
            for blocker in plan_blockers
        )

    plan_candidate = prepared_payload.get("candidate_authority")
    if not isinstance(plan_candidate, Mapping):
        return (f"{prefix}_candidate_authority_not_mapping",)
    if _canonical_json_sha256(plan_candidate) != candidate_sha:
        return (f"{prefix}_candidate_authority_sha256_mismatch",)
    if _frontmatter_non_null_scalar(prepared_payload.get("candidate_authority_sha256")) != (
        candidate_sha
    ):
        return (f"{prefix}_candidate_authority_sha256_claim_mismatch",)
    expected_response = (
        f"RATIFY {_frontmatter_non_null_scalar(candidate.get('id'))} "
        f"candidate_authority_sha256={candidate_sha}"
    )
    if _frontmatter_non_null_scalar(prepared_payload.get("candidate_authority_response")) != (
        expected_response
    ):
        return (f"{prefix}_candidate_authority_response_mismatch",)

    binding_core = prepared_payload.get("plan_binding_core")
    if not isinstance(binding_core, Mapping):
        return (f"{prefix}_binding_core_not_mapping",)
    for key in REVIEW_TEAM_DIGEST_MIGRATION_PREPARED_PLAN_BINDING_KEYS:
        artifact_value = _frontmatter_non_null_scalar(candidate.get(key))
        plan_value = _frontmatter_non_null_scalar(plan_candidate.get(key))
        if artifact_value != plan_value:
            return (f"{prefix}_binding_{key}_mismatch",)
        if key in binding_core and _frontmatter_non_null_scalar(binding_core.get(key)) != (
            artifact_value
        ):
            return (f"{prefix}_binding_core_{key}_mismatch",)

    migration = prepared_payload.get("migration")
    if not isinstance(migration, Mapping):
        return (f"{prefix}_migration_not_mapping",)
    if migration.get("artifact_written") is not False:
        return (f"{prefix}_migration_artifact_written_invalid",)
    return ()


def _candidate_authority_carrier_blockers(
    candidate: Mapping[str, Any],
    *,
    candidate_carrier_dir: Path | None,
    candidate_sha: str,
) -> tuple[str, ...]:
    locator = _frontmatter_non_null_scalar(candidate.get("candidate_carrier_locator"))
    if (
        not locator
        or Path(locator).name != locator
        or REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_CARRIER_LOCATOR_RE.fullmatch(locator) is None
    ):
        return ("sealed_migration_candidate_authority_carrier_locator_invalid",)
    plan_sha = _frontmatter_non_null_scalar(candidate.get("plan_sha256"))
    if REVIEW_TEAM_DIGEST_MIGRATION_SHA256_RE.fullmatch(plan_sha) is None:
        return ("sealed_migration_candidate_authority_plan_sha256_invalid",)
    expected_locator = (
        f"review-team-digest-migration.candidate-carrier.{plan_sha.removeprefix('sha256:')}.yaml"
    )
    if locator != expected_locator:
        return ("sealed_migration_candidate_authority_carrier_locator_mismatch",)
    if candidate_carrier_dir is None:
        return ("sealed_migration_candidate_authority_carrier_dir_missing",)

    carrier_path = candidate_carrier_dir / locator
    artifact_carrier_path = _frontmatter_non_null_scalar(candidate.get("carrier_path"))
    if artifact_carrier_path and Path(artifact_carrier_path).name != locator:
        return ("sealed_migration_candidate_authority_carrier_path_mismatch",)

    try:
        carrier_raw_sha = _raw_sha256_file(carrier_path)
    except OSError as exc:
        return (f"sealed_migration_candidate_authority_carrier_unreadable:{type(exc).__name__}",)
    artifact_carrier_sha = _frontmatter_non_null_scalar(candidate.get("carrier_sha256"))
    if artifact_carrier_sha and artifact_carrier_sha != f"sha256:{carrier_raw_sha}":
        return ("sealed_migration_candidate_authority_carrier_sha256_mismatch",)

    carrier, carrier_error = _load_yaml_mapping_for_migration(carrier_path)
    if carrier_error or carrier is None:
        return (f"sealed_migration_candidate_authority_carrier_malformed:{carrier_error}",)
    key_blockers = _key_set_blockers(
        carrier,
        required=REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_CARRIER_KEYS,
        allowed=REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_CARRIER_KEYS,
        reason_prefix="sealed_migration_candidate_authority_carrier",
    )
    if key_blockers:
        return tuple(key_blockers)
    if (
        _frontmatter_non_null_scalar(carrier.get("schema"))
        != REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_CARRIER_SCHEMA
    ):
        return ("sealed_migration_candidate_authority_carrier_schema_mismatch",)
    if _frontmatter_non_null_scalar(carrier.get("status")) != "consumed_active":
        return ("sealed_migration_candidate_authority_carrier_not_consumed",)
    consumed_at = _frontmatter_non_null_scalar(carrier.get("consumed_at"))
    if not _valid_iso_datetime(consumed_at):
        return ("sealed_migration_candidate_authority_carrier_consumed_at_invalid",)
    if _frontmatter_non_null_scalar(carrier.get("id")) != _frontmatter_non_null_scalar(
        candidate.get("id")
    ):
        return ("sealed_migration_candidate_authority_carrier_id_mismatch",)
    if _frontmatter_non_null_scalar(carrier.get("candidate_carrier_locator")) != locator:
        return ("sealed_migration_candidate_authority_carrier_locator_mismatch",)

    carrier_candidate = carrier.get("candidate_authority")
    if not isinstance(carrier_candidate, Mapping):
        return ("sealed_migration_candidate_authority_carrier_binding_missing",)
    carrier_candidate_blockers = _key_set_blockers(
        carrier_candidate,
        required=REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_CARRIER_CANDIDATE_KEYS,
        allowed=REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_CARRIER_CANDIDATE_KEYS,
        reason_prefix="sealed_migration_candidate_authority_carrier_candidate",
    )
    if carrier_candidate_blockers:
        return tuple(carrier_candidate_blockers)
    if _canonical_json_sha256(carrier_candidate) != candidate_sha:
        return ("sealed_migration_candidate_authority_sha256_mismatch",)
    if _frontmatter_non_null_scalar(carrier.get("candidate_authority_sha256")) != candidate_sha:
        return ("sealed_migration_candidate_authority_sha256_mismatch",)
    for key in REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_CARRIER_CANDIDATE_KEYS:
        if _frontmatter_non_null_scalar(carrier_candidate.get(key)) != (
            _frontmatter_non_null_scalar(candidate.get(key))
        ):
            return (f"sealed_migration_candidate_authority_{key}_mismatch",)

    for prepared_key in ("prepared_plan_file_sha256", "prepared_plan_canonical_sha256"):
        prepared_sha = _frontmatter_non_null_scalar(carrier.get(prepared_key))
        if REVIEW_TEAM_DIGEST_MIGRATION_SHA256_RE.fullmatch(prepared_sha) is None:
            return (f"sealed_migration_candidate_authority_carrier_{prepared_key}_invalid",)
        artifact_prepared_sha = _frontmatter_non_null_scalar(candidate.get(prepared_key))
        if artifact_prepared_sha and artifact_prepared_sha != prepared_sha:
            return (f"sealed_migration_candidate_authority_{prepared_key}_mismatch",)
    prepared_raw_hex = _frontmatter_non_null_scalar(carrier.get("prepared_plan_raw_bytes_hex"))
    try:
        prepared_raw = bytes.fromhex(prepared_raw_hex)
    except ValueError:
        return ("sealed_migration_candidate_authority_carrier_prepared_plan_raw_bytes_hex_invalid",)
    if "sha256:" + hashlib.sha256(prepared_raw).hexdigest() != _frontmatter_non_null_scalar(
        carrier.get("prepared_plan_file_sha256")
    ):
        return ("sealed_migration_candidate_authority_carrier_prepared_plan_file_sha256_mismatch",)
    try:
        prepared_payload = json.loads(prepared_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return (
            "sealed_migration_candidate_authority_carrier_prepared_plan_malformed:"
            f"{type(exc).__name__}",
        )
    if _canonical_json_sha256(prepared_payload) != _frontmatter_non_null_scalar(
        carrier.get("prepared_plan_canonical_sha256")
    ):
        return (
            "sealed_migration_candidate_authority_carrier_prepared_plan_canonical_sha256_mismatch",
        )
    prepared_plan_blockers = _embedded_prepared_plan_blockers(
        prepared_payload,
        candidate=candidate,
        candidate_sha=candidate_sha,
    )
    if prepared_plan_blockers:
        return prepared_plan_blockers

    operator_act = carrier.get("operator_act")
    if not isinstance(operator_act, Mapping):
        return ("sealed_migration_candidate_authority_carrier_operator_act_missing",)
    operator_key_blockers = _key_set_blockers(
        operator_act,
        required=REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_OPERATOR_ACT_KEYS,
        allowed=REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_OPERATOR_ACT_KEYS,
        reason_prefix="sealed_migration_candidate_authority_carrier_operator_act",
    )
    if operator_key_blockers:
        return tuple(operator_key_blockers)
    expected_response = (
        f"RATIFY {_frontmatter_non_null_scalar(candidate.get('id'))} "
        f"candidate_authority_sha256={candidate_sha}"
    )
    if _frontmatter_non_null_scalar(operator_act.get("exact_response_utf8_no_lf")) != (
        expected_response
    ):
        return ("sealed_migration_candidate_authority_carrier_response_mismatch",)
    for key in (
        "matched_id",
        "matched_candidate_authority_sha256",
        "authority_minted",
        "authority_limited_to_candidate",
    ):
        if operator_act.get(key) is not True:
            return (f"sealed_migration_candidate_authority_carrier_{key}_false",)
    return ()


def _candidate_authority_blockers(
    loaded: Mapping[str, Any],
    *,
    entries: list[Mapping[str, Any]],
    authority: Mapping[str, Any] | None,
    candidate_carrier_dir: Path | None,
    require_candidate_carrier: bool,
) -> tuple[str, ...]:
    candidate = loaded.get("candidate_authority")
    if not isinstance(candidate, Mapping):
        return ("sealed_migration_candidate_authority_missing",)
    key_blockers = _key_set_blockers(
        candidate,
        required=REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_AUTHORITY_KEYS,
        allowed=(
            REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_AUTHORITY_KEYS
            | REVIEW_TEAM_DIGEST_MIGRATION_OPTIONAL_CANDIDATE_AUTHORITY_KEYS
        ),
        reason_prefix="sealed_migration_candidate_authority",
    )
    if key_blockers:
        return tuple(key_blockers)
    if _frontmatter_non_null_scalar(candidate.get("schema")) != (
        REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_AUTHORITY_SCHEMA
    ):
        return ("sealed_migration_candidate_authority_schema_mismatch",)
    candidate_sha = _frontmatter_non_null_scalar(candidate.get("candidate_authority_sha256"))
    if REVIEW_TEAM_DIGEST_MIGRATION_SHA256_RE.fullmatch(candidate_sha) is None:
        return ("sealed_migration_candidate_authority_sha256_invalid",)
    for optional_sha_key in REVIEW_TEAM_DIGEST_MIGRATION_OPTIONAL_CANDIDATE_AUTHORITY_KEYS:
        if optional_sha_key == "carrier_path":
            continue
        optional_sha = _frontmatter_non_null_scalar(candidate.get(optional_sha_key))
        if optional_sha and REVIEW_TEAM_DIGEST_MIGRATION_SHA256_RE.fullmatch(optional_sha) is None:
            return (f"sealed_migration_candidate_authority_{optional_sha_key}_invalid",)
    commitment_body = {
        key: candidate.get(key)
        for key in sorted(
            REVIEW_TEAM_DIGEST_MIGRATION_CANDIDATE_AUTHORITY_KEYS
            - frozenset({"candidate_authority_sha256"})
        )
    }
    if _canonical_json_sha256(commitment_body) != candidate_sha:
        return ("sealed_migration_candidate_authority_sha256_mismatch",)
    if _frontmatter_non_null_scalar(candidate.get("candidate_artifact_core_sha256")) != (
        _candidate_artifact_core_sha256(loaded)
    ):
        return ("sealed_migration_candidate_artifact_core_sha256_mismatch",)
    if authority is not None:
        if _frontmatter_non_null_scalar(
            candidate.get("migration_authority_proposal_sha256")
        ) != _frontmatter_non_null_scalar(authority.get("proposal_sha256")):
            return ("sealed_migration_candidate_authority_proposal_sha256_mismatch",)
        if _frontmatter_non_null_scalar(
            candidate.get("migration_authority_consumed_act_carrier_sha256")
        ) != _frontmatter_non_null_scalar(authority.get("consumed_act_carrier_sha256")):
            return ("sealed_migration_candidate_authority_carrier_sha256_mismatch",)
        if _frontmatter_non_null_scalar(candidate.get("frozen_inventory_canonical_sha256")) != (
            _frontmatter_non_null_scalar(authority.get("frozen_inventory_canonical_sha256"))
        ):
            return ("sealed_migration_candidate_authority_frozen_sha256_mismatch",)

    disposition_manifest = _migration_disposition_manifest_from_entries(entries)
    if _frontmatter_non_null_scalar(candidate.get("disposition_manifest_sha256")) != (
        _canonical_json_sha256(disposition_manifest)
    ):
        return ("sealed_migration_authorized_disposition_manifest_mismatch",)

    if not require_candidate_carrier:
        return ()
    return _candidate_authority_carrier_blockers(
        candidate,
        candidate_carrier_dir=candidate_carrier_dir,
        candidate_sha=candidate_sha,
    )


def _valid_iso_datetime(value: str) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _key_set_blockers(
    mapping: Mapping[str, Any],
    *,
    required: frozenset[str],
    allowed: frozenset[str],
    reason_prefix: str,
) -> list[str]:
    keys = frozenset(str(key) for key in mapping)
    blockers = [f"{reason_prefix}_missing_key:{key}" for key in sorted(required - keys)]
    blockers.extend(f"{reason_prefix}_extra_key:{key}" for key in sorted(keys - allowed))
    return blockers


def _migration_entry_reason_valid(classification: str, reason: str) -> bool:
    if classification == "rebound":
        return reason == "current_open_pr_replay_rebound"
    if classification == REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION:
        return reason == "non_replayable_or_moved_head_exact_hash_preservation"
    if classification == "unmatched":
        return reason == "active_task_note_missing"
    if classification == "not-subject":
        return reason in {
            "acceptor_not_review_team",
            "already_digest_bound",
            "task_not_review_floor",
        }
    if classification == "stale-invalid":
        return reason in {
            "active_task_note_malformed",
            "task_note_id_mismatch",
            "post_cutover_unlisted_digest_unbound_receipt",
        } or reason.startswith(("receipt_malformed:", "verdict_not_accepted:"))
    return False


def review_team_digest_migration_artifact_blockers(
    loaded: Mapping[str, Any],
    *,
    expected_authority: Mapping[str, Any] | None = None,
    expected_frozen_inventory_entries: tuple[Mapping[str, Any], ...] | None = None,
    expected_active_dir: Path | None = None,
    require_candidate_authority_for_reclassified: bool = True,
    require_candidate_carrier: bool = True,
) -> tuple[str, ...]:
    """Validate the sealed review-team digest migration artifact.

    This is the canonical sealed-artifact contract for both lifecycle admission
    and dispatcher preflight. It validates identity, authority provenance,
    frozen tuple completeness, per-entry legacy provenance, and count coherence.
    """

    blockers: list[str] = []
    blockers.extend(
        _key_set_blockers(
            loaded,
            required=REVIEW_TEAM_DIGEST_MIGRATION_TOP_LEVEL_KEYS,
            allowed=(
                REVIEW_TEAM_DIGEST_MIGRATION_TOP_LEVEL_KEYS
                | REVIEW_TEAM_DIGEST_MIGRATION_OPTIONAL_TOP_LEVEL_KEYS
            ),
            reason_prefix="sealed_migration_top_level",
        )
    )
    if loaded.get("schema") != REVIEW_TEAM_DIGEST_MIGRATION_SCHEMA:
        blockers.append(f"sealed_migration_schema_mismatch:{loaded.get('schema') or 'missing'}")
    generated_at = _frontmatter_non_null_scalar(loaded.get("generated_at"))
    if not _valid_iso_datetime(generated_at):
        blockers.append("sealed_migration_generated_at_invalid")
    active_dir = _frontmatter_non_null_scalar(loaded.get("active_dir"))
    candidate_carrier_dir: Path | None = None
    if not active_dir or not Path(active_dir).is_absolute() or ".." in Path(active_dir).parts:
        blockers.append("sealed_migration_active_dir_invalid")
    elif expected_active_dir is not None:
        try:
            actual_active_dir = Path(active_dir).resolve(strict=False)
            expected_resolved = expected_active_dir.resolve(strict=False)
        except OSError:
            blockers.append("sealed_migration_active_dir_invalid")
        else:
            if actual_active_dir != expected_resolved:
                blockers.append("sealed_migration_active_dir_mismatch")
            else:
                candidate_carrier_dir = actual_active_dir
    else:
        try:
            candidate_carrier_dir = Path(active_dir).resolve(strict=False)
        except OSError:
            blockers.append("sealed_migration_active_dir_invalid")
    authority = loaded.get("authority")
    if not isinstance(authority, Mapping) or not authority:
        blockers.append("sealed_migration_authority_missing")
    else:
        blockers.extend(
            _key_set_blockers(
                authority,
                required=REVIEW_TEAM_DIGEST_MIGRATION_AUTHORITY_KEYS,
                allowed=REVIEW_TEAM_DIGEST_MIGRATION_AUTHORITY_KEYS,
                reason_prefix="sealed_migration_authority",
            )
        )
        source_anchor = authority.get("source_trust_anchor")
        if isinstance(source_anchor, Mapping):
            blockers.extend(
                _key_set_blockers(
                    source_anchor,
                    required=REVIEW_TEAM_DIGEST_MIGRATION_SOURCE_ANCHOR_KEYS,
                    allowed=REVIEW_TEAM_DIGEST_MIGRATION_SOURCE_ANCHOR_KEYS,
                    reason_prefix="sealed_migration_authority_source_anchor",
                )
            )
        blockers.extend(_migration_authority_blockers(loaded))
        if expected_authority is not None:
            for key, expected in expected_authority.items():
                if authority.get(key) != expected:
                    blockers.append(f"sealed_migration_authority_{key}_mismatch")
        if _frontmatter_non_null_scalar(loaded.get("authority_proposal_id")) != (
            _frontmatter_non_null_scalar(authority.get("proposal_id"))
        ):
            blockers.append("sealed_migration_authority_proposal_id_mismatch")

    if loaded.get("pause_boundary") != REVIEW_TEAM_DIGEST_MIGRATION_PAUSE_BOUNDARY:
        blockers.append("sealed_migration_pause_boundary_mismatch")
    if loaded.get("integrity_recheck") != REVIEW_TEAM_DIGEST_MIGRATION_INTEGRITY_RECHECK:
        blockers.append("sealed_migration_integrity_recheck_mismatch")

    sealed_generation = loaded.get("sealed_generation")
    if not isinstance(sealed_generation, Mapping) or not sealed_generation:
        blockers.append("sealed_migration_generation_missing")
    else:
        blockers.extend(
            _key_set_blockers(
                sealed_generation,
                required=REVIEW_TEAM_DIGEST_MIGRATION_GENERATION_KEYS,
                allowed=REVIEW_TEAM_DIGEST_MIGRATION_GENERATION_KEYS,
                reason_prefix="sealed_migration_generation",
            )
        )
        expected_generation_id = (
            _expected_sealed_generation_id(authority) if isinstance(authority, Mapping) else ""
        )
        if not expected_generation_id:
            blockers.append("sealed_migration_generation_expected_id_unavailable")
        elif _frontmatter_non_null_scalar(sealed_generation.get("id")) != expected_generation_id:
            blockers.append("sealed_migration_generation_id_mismatch")
        sealed_at = _frontmatter_non_null_scalar(sealed_generation.get("sealed_at"))
        if not sealed_at:
            blockers.append("sealed_migration_generation_sealed_at_missing")
        elif not _valid_iso_datetime(sealed_at):
            blockers.append("sealed_migration_generation_sealed_at_invalid")
        source_head = _frontmatter_non_null_scalar(sealed_generation.get("source_head_sha"))
        if GIT_SHA_RE.fullmatch(source_head) is None:
            blockers.append("sealed_migration_generation_source_head_invalid")

    frozen = loaded.get("frozen_prebinding_inventory")
    frozen_entries: list[Any] = []
    frozen_tuples: set[tuple[str, str, str]] = set()
    if not isinstance(frozen, Mapping) or not frozen:
        blockers.append("sealed_migration_frozen_inventory_missing")
    else:
        blockers.extend(
            _key_set_blockers(
                frozen,
                required=REVIEW_TEAM_DIGEST_MIGRATION_FROZEN_INVENTORY_KEYS,
                allowed=REVIEW_TEAM_DIGEST_MIGRATION_FROZEN_INVENTORY_KEYS,
                reason_prefix="sealed_migration_frozen_inventory",
            )
        )
        raw_entries = frozen.get("entries")
        if not isinstance(raw_entries, list):
            blockers.append("sealed_migration_frozen_inventory_entries_invalid")
        else:
            frozen_entries = raw_entries
            frozen_tuples = _migration_frozen_entry_tuples(raw_entries)
            if len(frozen_tuples) != len(raw_entries):
                blockers.append("sealed_migration_frozen_inventory_duplicate_tuple")
            for index, frozen_entry in enumerate(raw_entries):
                if not isinstance(frozen_entry, Mapping):
                    blockers.append(f"sealed_migration_frozen_inventory_entry_invalid:{index}")
                    continue
                blockers.extend(
                    _key_set_blockers(
                        frozen_entry,
                        required=REVIEW_TEAM_DIGEST_MIGRATION_FROZEN_ENTRY_KEYS,
                        allowed=REVIEW_TEAM_DIGEST_MIGRATION_FROZEN_ENTRY_KEYS,
                        reason_prefix=f"sealed_migration_frozen_inventory_entry:{index}",
                    )
                )
            expected_digest = (
                authority.get("frozen_inventory_canonical_sha256")
                if isinstance(authority, Mapping)
                else None
            )
            declared_digest = _frontmatter_non_null_scalar(frozen.get("canonical_sha256"))
            actual_digest = _canonical_frozen_inventory_sha256(raw_entries)
            if declared_digest != expected_digest or actual_digest != expected_digest:
                blockers.append("sealed_migration_frozen_inventory_sha256_mismatch")
        try:
            frozen_count = int(frozen.get("count"))
        except (TypeError, ValueError):
            blockers.append("sealed_migration_frozen_inventory_count_invalid")
        else:
            if frozen_count != len(frozen_entries):
                blockers.append("sealed_migration_frozen_inventory_count_mismatch")
        if expected_frozen_inventory_entries is not None:
            expected_tuples = {
                _migration_tuple_from_mapping(entry) for entry in expected_frozen_inventory_entries
            }
            if frozen_tuples != expected_tuples:
                blockers.append("sealed_migration_frozen_inventory_expected_tuple_mismatch")

    entries_raw = loaded.get("entries")
    entries: list[Mapping[str, Any]] = []
    represented_frozen_tuples: set[tuple[str, str, str]] = set()
    seen_identities: set[tuple[str, str]] = set()
    if not isinstance(entries_raw, list):
        blockers.append("sealed_migration_entries_invalid")
    else:
        for index, entry in enumerate(entries_raw):
            if not isinstance(entry, Mapping):
                blockers.append(f"sealed_migration_entry_invalid:{index}")
                continue
            blockers.extend(
                _key_set_blockers(
                    entry,
                    required=REVIEW_TEAM_DIGEST_MIGRATION_ENTRY_KEYS
                    - frozenset({"legacy_admission"}),
                    allowed=REVIEW_TEAM_DIGEST_MIGRATION_ENTRY_KEYS,
                    reason_prefix=f"sealed_migration_entry:{index}",
                )
            )
            entries.append(entry)
            task_id, basename, receipt_sha = _migration_tuple_from_mapping(entry)
            if not task_id:
                blockers.append(f"sealed_migration_entry_task_id_missing:{index}")
            expected_note_basename = f"{task_id}.md" if task_id else ""
            if (
                not expected_note_basename
                or _frontmatter_non_null_scalar(entry.get("task_note_basename"))
                != expected_note_basename
            ):
                blockers.append(
                    f"sealed_migration_entry_task_note_basename_mismatch:{task_id or index}"
                )
            if not _valid_artifact_basename(basename):
                blockers.append(f"sealed_migration_entry_path_invalid:{task_id or index}")
            relpath = _frontmatter_non_null_scalar(entry.get("receipt_relpath"))
            if not relpath or Path(relpath).name != relpath or relpath != basename:
                blockers.append(f"sealed_migration_entry_relpath_invalid:{task_id or index}")
            if REVIEW_TEAM_DIGEST_MIGRATION_SHA256_RE.fullmatch(receipt_sha) is None:
                blockers.append(f"sealed_migration_entry_receipt_sha_invalid:{task_id or index}")
            identity = (task_id, basename)
            if identity in seen_identities:
                blockers.append(f"sealed_migration_duplicate_identity:{task_id}:{basename}")
            seen_identities.add(identity)
            classification = _frontmatter_non_null_scalar(entry.get("classification"))
            if classification not in REVIEW_TEAM_DIGEST_MIGRATION_CLASSIFICATIONS:
                blockers.append(
                    "sealed_migration_entry_classification_invalid:"
                    f"{task_id or index}:{classification or 'missing'}"
                )
            reason = _frontmatter_non_null_scalar(entry.get("reason"))
            if not _migration_entry_reason_valid(classification, reason):
                blockers.append(f"sealed_migration_entry_reason_mismatch:{task_id or index}")
            entry_tuple = (task_id, basename, receipt_sha)
            if entry_tuple in frozen_tuples:
                represented_frozen_tuples.add(entry_tuple)
                if (
                    classification != REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION
                    and "candidate_authority" not in loaded
                    and require_candidate_authority_for_reclassified
                ):
                    blockers.append(
                        "sealed_migration_frozen_tuple_reclassified:"
                        f"{task_id}:{classification or 'missing'}"
                    )
            if classification == REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION:
                if entry_tuple not in frozen_tuples:
                    blockers.append(f"sealed_migration_preservation_not_frozen:{task_id}")
                blockers.extend(
                    f"{blocker}:{task_id}"
                    for blocker in _legacy_admission_blockers(
                        loaded,
                        entry,
                        expected_sha=receipt_sha,
                    )
                )
            elif "legacy_admission" in entry:
                blockers.append(f"sealed_migration_entry_unexpected_legacy_admission:{task_id}")

    missing_frozen = sorted(frozen_tuples - represented_frozen_tuples)
    blockers.extend(
        f"sealed_migration_frozen_tuple_missing:{task_id}:{basename}"
        for task_id, basename, _receipt_sha in missing_frozen
    )

    counts = loaded.get("counts")
    if not isinstance(counts, Mapping):
        blockers.append("sealed_migration_counts_missing")
    else:
        blockers.extend(
            _key_set_blockers(
                counts,
                required=REVIEW_TEAM_DIGEST_MIGRATION_CLASSIFICATIONS,
                allowed=REVIEW_TEAM_DIGEST_MIGRATION_CLASSIFICATIONS,
                reason_prefix="sealed_migration_counts",
            )
        )
        actual_counts = _migration_counts(entries)
        for classification, actual in sorted(actual_counts.items()):
            try:
                declared = int(counts.get(classification))
            except (TypeError, ValueError):
                blockers.append(f"sealed_migration_count_invalid:{classification}")
                continue
            if declared != actual:
                blockers.append(f"sealed_migration_count_mismatch:{classification}")
    next_actions = loaded.get("next_actions")
    if not isinstance(next_actions, Mapping):
        blockers.append("sealed_migration_next_actions_missing")
    else:
        blockers.extend(
            _key_set_blockers(
                next_actions,
                required=REVIEW_TEAM_DIGEST_MIGRATION_CLASSIFICATIONS,
                allowed=REVIEW_TEAM_DIGEST_MIGRATION_CLASSIFICATIONS,
                reason_prefix="sealed_migration_next_actions",
            )
        )
        for classification, expected_action in sorted(
            REVIEW_TEAM_DIGEST_MIGRATION_NEXT_ACTIONS.items()
        ):
            if _frontmatter_non_null_scalar(next_actions.get(classification)) != expected_action:
                blockers.append(f"sealed_migration_next_actions_value_mismatch:{classification}")
    frozen_reclassified = any(
        _migration_tuple_from_mapping(entry) in frozen_tuples
        and _frontmatter_non_null_scalar(entry.get("classification"))
        != REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION
        for entry in entries
    )
    if (
        frozen_reclassified and require_candidate_authority_for_reclassified
    ) or "candidate_authority" in loaded:
        blockers.extend(
            _candidate_authority_blockers(
                loaded,
                entries=entries,
                authority=authority if isinstance(authority, Mapping) else None,
                candidate_carrier_dir=candidate_carrier_dir,
                require_candidate_carrier=require_candidate_carrier and frozen_reclassified,
            )
        )
    return tuple(dict.fromkeys(blockers))


def _legacy_admission_blockers(
    loaded: Mapping[str, Any],
    entry: Mapping[str, Any],
    *,
    expected_sha: str,
) -> tuple[str, ...]:
    admission = entry.get("legacy_admission")
    if not isinstance(admission, Mapping):
        return ("acceptance_receipt_digest_migration_legacy_admission_missing",)
    key_blockers = _key_set_blockers(
        admission,
        required=REVIEW_TEAM_DIGEST_MIGRATION_LEGACY_ADMISSION_KEYS,
        allowed=REVIEW_TEAM_DIGEST_MIGRATION_LEGACY_ADMISSION_KEYS,
        reason_prefix="acceptance_receipt_digest_migration_legacy_admission",
    )
    if key_blockers:
        return tuple(key_blockers)
    if (
        _frontmatter_non_null_scalar(admission.get("route"))
        != REVIEW_TEAM_DIGEST_MIGRATION_LEGACY_ROUTE
    ):
        return ("acceptance_receipt_digest_migration_legacy_admission_route_mismatch",)
    if (
        _frontmatter_non_null_scalar(admission.get("classification"))
        != REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION
    ):
        return ("acceptance_receipt_digest_migration_legacy_admission_classification_mismatch",)
    if _frontmatter_non_null_scalar(admission.get("receipt_sha256")) != expected_sha:
        return ("acceptance_receipt_digest_migration_legacy_admission_receipt_sha_mismatch",)
    sealed = loaded.get("sealed_generation")
    if not isinstance(sealed, Mapping):
        return ("acceptance_receipt_digest_migration_legacy_admission_sealed_generation_missing",)
    if _frontmatter_non_null_scalar(
        admission.get("sealed_generation_id")
    ) != _frontmatter_non_null_scalar(sealed.get("id")):
        return ("acceptance_receipt_digest_migration_legacy_admission_sealed_generation_mismatch",)
    authority = loaded.get("authority")
    if not isinstance(authority, Mapping):
        return ("acceptance_receipt_digest_migration_legacy_admission_authority_missing",)
    expected_generation_id = _expected_sealed_generation_id(authority)
    if (
        not expected_generation_id
        or _frontmatter_non_null_scalar(sealed.get("id")) != expected_generation_id
    ):
        return (
            "acceptance_receipt_digest_migration_legacy_admission_sealed_generation_id_mismatch",
        )
    source_head = _frontmatter_non_null_scalar(sealed.get("source_head_sha"))
    if GIT_SHA_RE.fullmatch(source_head) is None:
        return ("acceptance_receipt_digest_migration_legacy_admission_source_head_invalid",)
    if _frontmatter_non_null_scalar(admission.get("sealed_generation_source_head_sha")) != (
        source_head
    ):
        return ("acceptance_receipt_digest_migration_legacy_admission_source_head_mismatch",)
    source_anchor = admission.get("source_trust_anchor")
    if not isinstance(source_anchor, Mapping):
        return ("acceptance_receipt_digest_migration_legacy_admission_source_anchor_missing",)
    key_blockers = _key_set_blockers(
        source_anchor,
        required=REVIEW_TEAM_DIGEST_MIGRATION_SOURCE_ANCHOR_KEYS,
        allowed=REVIEW_TEAM_DIGEST_MIGRATION_SOURCE_ANCHOR_KEYS,
        reason_prefix="acceptance_receipt_digest_migration_legacy_admission_source_anchor",
    )
    if key_blockers:
        return tuple(key_blockers)
    expected_anchor = review_team_digest_migration_source_trust_anchor()
    for key, expected in expected_anchor.items():
        if _frontmatter_non_null_scalar(source_anchor.get(key)) != expected:
            return (
                "acceptance_receipt_digest_migration_legacy_admission_source_anchor_"
                f"{key}_mismatch",
            )
    return ()


def _frozen_digest_tuples(loaded: Mapping[str, Any]) -> set[tuple[str, str, str]]:
    frozen = loaded.get("frozen_prebinding_inventory")
    if not isinstance(frozen, Mapping):
        return set()
    entries = frozen.get("entries")
    if not isinstance(entries, list):
        return set()
    tuples: set[tuple[str, str, str]] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        tuples.add(
            (
                _frontmatter_non_null_scalar(entry.get("task_id")),
                _frontmatter_non_null_scalar(entry.get("receipt_basename")),
                _frontmatter_non_null_scalar(entry.get("receipt_sha256")),
            )
        )
    return tuples


def _review_team_digest_migration_blockers(
    receipt_path: Path,
    *,
    note_path: Path | None,
    task_id: str | None,
) -> tuple[str, ...]:
    if note_path is None or not task_id:
        return ("acceptance_receipt_digest_migration_context_missing",)
    active_dir = _canonical_active_dir_for_note(note_path)
    if active_dir is None:
        return ("acceptance_receipt_digest_migration_unrecognized_vault_layout",)
    migration_path = active_dir / REVIEW_TEAM_DIGEST_MIGRATION_FILENAME
    if not migration_path.is_file():
        return ("acceptance_receipt_digest_migration_missing",)
    loaded, load_error = _load_yaml_mapping_for_migration(migration_path)
    if load_error or loaded is None:
        return (f"acceptance_receipt_digest_migration_malformed:{load_error}",)
    if loaded.get("schema") != REVIEW_TEAM_DIGEST_MIGRATION_SCHEMA:
        return (
            "acceptance_receipt_digest_migration_malformed:schema:"
            f"{loaded.get('schema') or 'missing'}",
        )
    artifact_blockers = review_team_digest_migration_artifact_blockers(
        loaded,
        expected_active_dir=active_dir,
    )
    authority_artifact_blockers = tuple(
        blocker
        for blocker in artifact_blockers
        if blocker.startswith("acceptance_receipt_digest_migration_")
        and "legacy_admission" not in blocker
    )
    if authority_artifact_blockers:
        return authority_artifact_blockers
    terminal_artifact_blockers = tuple(
        blocker
        for blocker in artifact_blockers
        if blocker.startswith(
            (
                "sealed_migration_authority",
                "sealed_migration_generation",
                "sealed_migration_frozen_inventory",
                "sealed_migration_frozen_tuple",
                "sealed_migration_counts",
                "sealed_migration_count_",
            )
        )
    )
    if terminal_artifact_blockers:
        return tuple(
            f"acceptance_receipt_digest_migration_{blocker}"
            for blocker in terminal_artifact_blockers
        )
    authority_blockers = _migration_authority_blockers(loaded)
    if authority_blockers:
        return authority_blockers
    entries = loaded.get("entries")
    if not isinstance(entries, list):
        return ("acceptance_receipt_digest_migration_malformed:entries_not_list",)

    matching_task_entries: list[Mapping[str, Any]] = []
    task_entry_count = 0
    for entry in entries:
        if not isinstance(entry, Mapping):
            return ("acceptance_receipt_digest_migration_malformed:entry_not_mapping",)
        entry_task_id = _frontmatter_non_null_scalar(entry.get("task_id"))
        if entry_task_id == task_id:
            task_entry_count += 1
            matching_task_entries.append(entry)

    if task_entry_count > 1:
        return (f"acceptance_receipt_digest_migration_duplicate_task:{task_id}",)
    if not matching_task_entries:
        return ("acceptance_receipt_digest_migration_unlisted",)

    entry = matching_task_entries[0]
    basename = _frontmatter_non_null_scalar(entry.get("receipt_basename"))
    if not _valid_artifact_basename(basename):
        return ("acceptance_receipt_digest_migration_path_invalid",)
    if basename != receipt_path.name:
        return ("acceptance_receipt_digest_migration_unlisted",)
    relpath = _frontmatter_non_null_scalar(entry.get("receipt_relpath"))
    if relpath and (Path(relpath).name != relpath or relpath != receipt_path.name):
        return ("acceptance_receipt_digest_migration_path_invalid",)

    classification = _frontmatter_non_null_scalar(entry.get("classification"))
    if classification != REVIEW_TEAM_DIGEST_MIGRATION_PRESERVE_CLASSIFICATION:
        if _frontmatter_non_null_scalar(entry.get("reason")) == (
            "post_cutover_unlisted_digest_unbound_receipt"
        ):
            return ("acceptance_receipt_digest_migration_post_cutover_unlisted",)
        return (
            "acceptance_receipt_digest_migration_classification_not_preserving:"
            f"{classification or 'missing'}",
        )
    expected_sha = _frontmatter_non_null_scalar(entry.get("receipt_sha256"))
    if REVIEW_TEAM_DIGEST_MIGRATION_SHA256_RE.fullmatch(expected_sha) is None:
        return ("acceptance_receipt_digest_migration_malformed:receipt_sha256",)
    if (task_id, basename, expected_sha) not in _frozen_digest_tuples(loaded):
        return ("acceptance_receipt_digest_migration_post_cutover_unlisted",)
    legacy_blockers = _legacy_admission_blockers(loaded, entry, expected_sha=expected_sha)
    if legacy_blockers:
        return legacy_blockers
    try:
        actual_sha = _sha256_file(receipt_path)
    except OSError as exc:
        return (f"acceptance_receipt_unreadable:{type(exc).__name__}",)
    if expected_sha.removeprefix("sha256:") != actual_sha:
        return ("acceptance_receipt_digest_migration_sha256_mismatch",)
    return ()


def acceptance_receipt_document_blockers(
    loaded: Any,
    *,
    reason_prefix: str = "acceptance_receipt",
) -> list[str]:
    """Structural admission of an acceptance-receipt DOCUMENT, with no filesystem in it.

    Split out of ``_acceptance_receipt_validity_blockers`` so the one receipt schema can be applied
    to a receipt that is about to be WRITTEN as well as to one already on disk. A prepared plan
    carries the exact bytes of each receipt write; those bytes are admitted as a receipt the moment
    they land, so their schema is owed while the plan is being decoded -- not discovered afterwards
    by the surface that reads the file back.

    The environment-dependent half of receipt admission (does the dossier exist, does it hash to
    what the receipt claims) stays with the path-based caller, which is the only one that has a
    filesystem to ask.
    """

    if not isinstance(loaded, Mapping):
        return [f"{reason_prefix}_malformed:not_a_mapping:{type(loaded).__name__}"]
    blockers = [
        f"{reason_prefix}_missing_field:{field}"
        for field in ACCEPTANCE_RECEIPT_REQUIRED_FIELDS
        if not _frontmatter_non_null_scalar(loaded.get(field))
    ]
    verdict = _frontmatter_non_null_scalar(loaded.get("verdict"))
    if verdict and verdict.lower() not in ACCEPTANCE_RECEIPT_ACCEPTED_VERDICTS:
        blockers.append(f"{reason_prefix}_verdict_not_accepted:{verdict.lower()}")
    acceptor = _frontmatter_non_null_scalar(loaded.get("acceptor")) or ""
    if acceptor.startswith(REVIEW_TEAM_ACCEPTOR_PREFIX):
        dossier_sha256 = _frontmatter_non_null_scalar(loaded.get("dossier_sha256"))
        if dossier_sha256 and REVIEW_TEAM_DOSSIER_SHA256_RE.fullmatch(dossier_sha256) is None:
            blockers.append(f"{reason_prefix}_dossier_sha256_malformed")
    return blockers


def _acceptance_receipt_validity_blockers(
    receipt_path: Path,
    *,
    note_path: Path | None = None,
    task_id: str | None = None,
) -> tuple[str, ...]:
    if not receipt_path.is_file():
        return ("missing_acceptance_receipt",)
    try:
        loaded = yaml.safe_load(receipt_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return (f"acceptance_receipt_malformed:{type(exc).__name__}",)
    if not isinstance(loaded, Mapping):
        return (f"acceptance_receipt_malformed:not_a_mapping:{type(loaded).__name__}",)

    blockers = acceptance_receipt_document_blockers(loaded)
    acceptor = _frontmatter_non_null_scalar(loaded.get("acceptor")) or ""
    if acceptor.startswith(REVIEW_TEAM_ACCEPTOR_PREFIX):
        dossier_sha256 = _frontmatter_non_null_scalar(loaded.get("dossier_sha256"))
        if not dossier_sha256:
            migration_blockers = _review_team_digest_migration_blockers(
                receipt_path,
                note_path=note_path,
                task_id=task_id,
            )
            if migration_blockers:
                blockers.extend(migration_blockers)
                blockers.append("acceptance_receipt_review_team_dossier_sha256_missing")
        elif REVIEW_TEAM_DOSSIER_SHA256_RE.fullmatch(dossier_sha256) is not None:
            # A malformed digest is already reported by the document decoder above.
            if note_path is None or not task_id:
                blockers.append("acceptance_receipt_dossier_context_missing")
            else:
                dossier_path = _task_artifact_path_beside_note(
                    note_path, task_id, REVIEW_DOSSIER_SUFFIX
                )
                if dossier_path is None:
                    blockers.append("acceptance_receipt_dossier_context_invalid")
                elif not dossier_path.is_file():
                    blockers.append("acceptance_receipt_dossier_missing")
                else:
                    try:
                        actual = _sha256_file(dossier_path)
                    except OSError as exc:
                        blockers.append(
                            f"acceptance_receipt_dossier_unreadable:{type(exc).__name__}"
                        )
                    else:
                        expected = dossier_sha256.removeprefix("sha256:")
                        if actual != expected:
                            blockers.append("acceptance_receipt_dossier_sha256_mismatch")
    return tuple(blockers)


def acceptance_receipt_blockers(frontmatter: Mapping[str, Any], note_path: Path) -> tuple[str, ...]:
    """Receipt blockers for a review-floor task; empty for non-review-floor tasks.

    A review-floor note without a safe, resolvable ``task_id`` fails closed with
    a task-identity blocker — the receipt is keyed by task_id, so an unsafe
    identity must not be hidden behind a generic missing-receipt reason.
    """

    if not requires_acceptance_receipt(frontmatter):
        return ()
    task_id = _frontmatter_non_null_scalar(frontmatter.get("task_id"))
    if not task_id:
        return ("acceptance_receipt_task_id_missing",)
    receipt_path = _task_artifact_path_beside_note(note_path, task_id, ACCEPTANCE_RECEIPT_SUFFIX)
    if receipt_path is None:
        return ("acceptance_receipt_task_id_invalid",)
    return _acceptance_receipt_validity_blockers(
        receipt_path,
        note_path=note_path,
        task_id=task_id,
    )


def acceptance_receipt_admission_route(
    frontmatter: Mapping[str, Any], note_path: Path
) -> dict[str, Any]:
    """Return the accepted receipt route for audit diagnostics.

    This is intentionally separate from ``acceptance_receipt_blockers`` so gate
    callers keep a simple fail-closed reason tuple while audit callers can tell
    normal dossier-bound review-team receipts from legacy exact-hash admission.
    """

    blockers = acceptance_receipt_blockers(frontmatter, note_path)
    if blockers:
        return {"accepted": False, "route": "blocked", "blockers": blockers}
    if not requires_acceptance_receipt(frontmatter):
        return {"accepted": True, "route": "not_required", "blockers": ()}
    task_id = _frontmatter_non_null_scalar(frontmatter.get("task_id"))
    receipt_path = _task_artifact_path_beside_note(note_path, task_id, ACCEPTANCE_RECEIPT_SUFFIX)
    if receipt_path is None:
        return {
            "accepted": False,
            "route": "blocked",
            "blockers": ("acceptance_receipt_task_id_invalid",),
        }
    loaded, load_error = _load_yaml_mapping_for_migration(receipt_path)
    if load_error or loaded is None:
        return {
            "accepted": False,
            "route": "blocked",
            "blockers": (f"acceptance_receipt_malformed:{load_error}",),
        }
    acceptor = _frontmatter_non_null_scalar(loaded.get("acceptor")) or ""
    if not acceptor.startswith(REVIEW_TEAM_ACCEPTOR_PREFIX):
        return {"accepted": True, "route": "operator_receipt", "blockers": ()}
    dossier_sha256 = _frontmatter_non_null_scalar(loaded.get("dossier_sha256"))
    if dossier_sha256:
        return {
            "accepted": True,
            "route": "review_team_dossier_sha256",
            "blockers": (),
            "dossier_sha256": dossier_sha256,
        }

    active_dir = _canonical_active_dir_for_note(note_path)
    if active_dir is None:
        return {
            "accepted": False,
            "route": "blocked",
            "blockers": ("acceptance_receipt_digest_migration_unrecognized_vault_layout",),
        }
    migration, migration_error = _load_yaml_mapping_for_migration(
        active_dir / REVIEW_TEAM_DIGEST_MIGRATION_FILENAME
    )
    if migration_error or migration is None:
        return {
            "accepted": False,
            "route": "blocked",
            "blockers": (f"acceptance_receipt_digest_migration_malformed:{migration_error}",),
        }
    entries = migration.get("entries")
    matching = []
    if isinstance(entries, list):
        matching = [
            entry
            for entry in entries
            if isinstance(entry, Mapping)
            and _frontmatter_non_null_scalar(entry.get("task_id")) == task_id
        ]
    entry = matching[0] if matching else {}
    admission = entry.get("legacy_admission") if isinstance(entry, Mapping) else None
    sealed = migration.get("sealed_generation")
    return {
        "accepted": True,
        "route": REVIEW_TEAM_DIGEST_MIGRATION_LEGACY_ROUTE,
        "blockers": (),
        "receipt_sha256": _frontmatter_non_null_scalar(entry.get("receipt_sha256")),
        "classification": _frontmatter_non_null_scalar(entry.get("classification")),
        "sealed_generation": dict(sealed) if isinstance(sealed, Mapping) else {},
        "legacy_admission": dict(admission) if isinstance(admission, Mapping) else {},
    }


def _frontmatter_pr_number(frontmatter: Mapping[str, Any]) -> str | None:
    value = _frontmatter_scalar(frontmatter.get("pr"))
    if value.lower() in {"", "null", "none", "~"}:
        return None
    return value.lstrip("#")


def _route_metadata_blockers(frontmatter: Mapping[str, Any]) -> tuple[str, ...]:
    from shared.route_metadata_schema import assess_route_metadata

    assessment = assess_route_metadata(frontmatter)
    if assessment.dispatchable:
        return ()
    reasons = [
        *assessment.hold_reasons,
        *assessment.missing_fields,
        *assessment.validation_errors,
    ]
    return tuple(f"route_metadata:{reason}" for reason in reasons or ("invalid",))


def _route_metadata_validation_blockers(frontmatter: Mapping[str, Any]) -> tuple[str, ...]:
    """Governance-only route-metadata blockers: validation_errors only (e.g. a
    frontier_review_required task marked authoritative), NOT a merely absent
    envelope. Dependency-closure callers (cc-claim, cc-cascade-unblock) use this
    to block on a broken/governance-invalid dependency task while allowing an
    external-repo dependency that simply carries no dispatch envelope."""
    from shared.route_metadata_schema import assess_route_metadata

    assessment = assess_route_metadata(frontmatter)
    return tuple(f"route_metadata:{reason}" for reason in assessment.validation_errors)


def task_closure_validity(
    text: str,
    *,
    pr_state_lookup: PrStateLookup | None = None,
    require_route_metadata: bool = False,
    require_route_metadata_validity: bool = False,
) -> TaskClosureValidity:
    """Validate that a cc-task closure may satisfy downstream work.

    This predicate is stricter than "status is done": it requires a fulfilling
    terminal status, no unchecked Acceptance criteria boxes, a merged declared
    PR when a PR can be checked, and valid route metadata when that surface is
    required by the caller.
    """

    frontmatter = frontmatter_from_text(text)
    status = _frontmatter_scalar(frontmatter.get("status")).lower()
    blockers: list[str] = []

    if status == "blocked":
        blockers.extend(active_blocked_task_blockers(frontmatter))
    elif status not in TASK_FULFILLING_CLOSED_STATUSES:
        blockers.append(f"status_not_fulfilling:{status or 'missing'}")

    ac_state = acceptance_criteria_state(text)
    blockers.extend(f"unchecked_acceptance_criteria:{item}" for item in ac_state.unchecked_items)

    pr_number = _frontmatter_pr_number(frontmatter)
    if pr_number and pr_state_lookup is not None:
        state = (pr_state_lookup(pr_number) or "unknown").strip().lower()
        if state == "merged":
            pass
        elif state == "open":
            blockers.append(f"pr_open:{pr_number}")
        elif state in {"closed_unmerged", "closed"}:
            blockers.append(f"pr_closed_unmerged:{pr_number}")
        else:
            blockers.append(f"pr_unknown:{pr_number}")

    if require_route_metadata:
        blockers.extend(_route_metadata_blockers(frontmatter))
    if require_route_metadata_validity:
        blockers.extend(_route_metadata_validation_blockers(frontmatter))

    return TaskClosureValidity(
        valid=not blockers,
        blockers=tuple(blockers),
        frontmatter=frontmatter,
    )


# --- System release auto-arm (dispatch resilience to lane-death) -------------
# CASE-CAPACITY-ROUTING-001. A headless lane exits after creating its PR. If it
# dies after `gh pr create` but before flipping `release_authorized: true`, a
# CLEAN, green, mergeable PR strands at `pr_open` forever and needs manual
# re-dispatch. The autoqueue runs as the system (unclaimed — master design
# FM-20: "auto-queue is the merge path (runs as system, unclaimed)"), so it can
# authorize release on behalf of a dead lane — but ONLY for tasks whose release
# was already authorized-in-principle by their ISAP (`implementation_authorized`)
# and whose risk profile carries verified mitigation evidence for each applicable
# sensitivity class.

#: Risk flags whose presence (explicit or keyword-derived) requires mitigation
#: evidence before auto-arming (see RELEASE_MITIGATION_CHECKS). Historically a
#: hard veto; per operator directive 2026-06-22 each is an evidence GATE, not a
#: human-arm trigger.
SENSITIVE_RISK_FLAGS = (
    "governance_sensitive",
    "public_claim_sensitive",
    "audio_or_live_egress_sensitive",
    "privacy_or_secret_sensitive",
    "provider_billing_sensitive",
)

#: Per-sensitivity-class mitigation evidence: the CI check name(s) whose PASS
#: state is sufficient, machine-verified mitigation for that class. When the
#: release assessment is supplied the PR's verified (passing) checks, a sensitive
#: class is satisfied (no veto) iff its required checks all passed — so the SDLC
#: AUTO-arms on evidence rather than holding for a manual arm (operator directive
#: 2026-06-22: "sensitive changes [are] risk-mitigated sufficiently so as to not
#: require manual arming"). A class ABSENT from this map has no defined mitigation
#: gate yet → it fails CLOSED (held) until its gate is defined; it is NEVER
#: released by a manual override. Extend this map (never add a manual-arm path) to
#: bring a new sensitivity class under automated, evidence-gated release.
#: Emergency recovery for miswired evidence producers is the autoqueue killswitch
#: (`HAPAX_CC_PR_AUTOQUEUE_OFF=1` or `HAPAX_CC_HYGIENE_OFF=1`) while the check
#: wiring is repaired; the killswitch pauses admission and is not a manual release
#: arm. Recheck the pause before retrying autoqueue with that environment check
#: and the executable reader in `scripts/cc-pr-autoqueue.py` (`KILLSWITCH_ENVS`;
#: `run_reconciler` returns a killed report before any admission mutation).
#: One-off shell check:
#: `env | grep -E '^(HAPAX_CC_PR_AUTOQUEUE_OFF|HAPAX_CC_HYGIENE_OFF)=1$'`.
REVIEW_TEAM_QUORUM_EVIDENCE = "review-team-quorum"

RELEASE_MITIGATION_CHECKS: dict[str, tuple[str, ...]] = {
    # A governance-sensitive change auto-arms only after the local review dossier
    # gate has already accepted the PR and the GitHub-side authority check passes.
    # The review-team quorum marker is virtual evidence produced only by
    # ``cc-pr-autoqueue`` after it validates the source-pinned dossier for the
    # current PR head and scope; it is not satisfied by a bare GitHub check named
    # ``review``. ``cc-pr-autoqueue`` writes its own fresh admission proof only
    # after the task note is armed and the release-head boundary is revalidated,
    # so that proof is not release-arm evidence.
    "governance_sensitive": (
        "authority-case-check",
        REVIEW_TEAM_QUORUM_EVIDENCE,
    ),
    # A public-claim-sensitive source change auto-arms only when the current
    # PR head has passed authority-case validation and the source-pinned review
    # dossier has quorum-accepted the public-claim posture. This does not grant
    # public egress or provider spend: those still fail closed through mutation
    # surface, public_current, and provider-spend gates.
    "public_claim_sensitive": (
        "authority-case-check",
        REVIEW_TEAM_QUORUM_EVIDENCE,
    ),
    # A privacy/secret-sensitive change auto-arms when the dedicated secret
    # scanner passes on its diff (no committed credential). The redaction
    # CORRECTNESS of such a change is separately gated by the general test/review
    # checks every PR already carries.
    "privacy_or_secret_sensitive": ("secrets-scan",),
}

#: Mutation surfaces too high-stakes for the system to auto-authorize release.
AUTO_ARM_INELIGIBLE_MUTATION_SURFACES = frozenset({"public", "provider_spend"})

#: Governance-protected / off-limits path fragments (mirrors the workspace
#: off-limits set + CODEOWNERS-governed surfaces). A task whose mutation scope
#: touches any of these must be released by a human, never the system.
SENSITIVE_PATH_MARKERS = (
    "axioms/",
    "shared/governance/",
    "agents/hapax_daimonion/",
    "config/pipewire/",
    "codeowners",
    "claude.md",
    "hapax-constitution",
    # Operator-coupled broadcast/visual surfaces (operator directive 2026-06-10):
    # correctness depends on continuous operator aesthetic/directorial judgment,
    # so release is ALWAYS human-armed — never system auto-arm.
    "agents/studio_compositor/",
    "screwm",
    "darkplaces",
)

_AUTO_ARM_TRUTHY = {"1", "true", "yes", "y", "required"}
_STAGE_PREFIX_RE = re.compile(r"^s(\d{1,2})", re.IGNORECASE)

# --- Canonical stage-shape vocabulary (proof-plane: the S0..S11 ladder) -------
# Three matchers with deliberately different jobs (do NOT collapse into one):
#  * STAGE_RE — strict full-shape validator "S<n>[_LABEL]"; cc-stage-advance pins
#    its local _STAGE_RE to this (case-sensitive, <=2 digits, uppercase label).
#  * stage_token — normalizes a labeled/branch stage to its ladder token
#    ("S6_IMPLEMENTATION"->"S6", "S3.5"->"S3_5"); the naming-drift bridge the
#    invariants monitor reuses (shared.sdlc_invariants._stage_token).
#  * _STAGE_PREFIX_RE (above) — lenient case-insensitive numeric *prefix* used
#    only by the release-arm _stage_below_s7 check; intentionally distinct from
#    STAGE_RE (it must tolerate stray case/suffixes on a release-gate read).
STAGE_RE = re.compile(r"^S(\d{1,2})(?:_[A-Z][A-Z0-9_]*)?$")


def stage_token(raw: str) -> str:
    """Normalize 'S6_IMPLEMENTATION' / 'S3.5' to the ladder token (S6 / S3_5)."""
    token = raw.strip().replace(".", "_")
    return token.split("_")[0] if (token[:1] == "S" and "_" in token and token != "S3_5") else token


@dataclass(frozen=True)
class ReleaseAutoArmAssessment:
    """Whether a stranded ``pr_open`` task may be auto-armed by the system.

    ``subject``      task participates in the release-authorization model
                     (carries a ``release_authorized`` field).
    ``armed``        ``release_authorized`` is already true.
    ``needs_arming`` subject and not yet armed.
    ``eligible``     needs arming and carries no governance/sensitivity veto.
    ``blockers``     the reasons it is ineligible (empty iff eligible).
    """

    subject: bool
    armed: bool
    needs_arming: bool
    eligible: bool
    blockers: tuple[str, ...]


def _auto_arm_truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in _AUTO_ARM_TRUTHY


def _explicit_risk_flag_true(frontmatter: Mapping[str, Any], name: str) -> bool:
    """Whether a route-metadata risk flag was explicitly set true.

    Top-level ``route_metadata_schema`` makes many task notes explicit route
    metadata subjects. That should not by itself block the subscription-secret
    carve-out below; only an actual explicit ``risk_flags.<name>: true`` does.
    """

    from shared.route_metadata_schema import route_metadata_payload_from_frontmatter

    risk_flags = route_metadata_payload_from_frontmatter(frontmatter).get("risk_flags")
    if not isinstance(risk_flags, Mapping):
        return False
    return _auto_arm_truthy(risk_flags.get(name))


def _pass_backed_runtime_secret_auto_arm_ok(frontmatter: Mapping[str, Any]) -> bool:
    """True for narrow pass-backed runtime-only secret tooling.

    A task title containing "secret" is often privacy-sensitive and should stay
    system-held. The exception is explicitly declared provider tooling that reads
    an existing pass entry only at runtime, stores no secret value, uses only
    already-purchased subscription quota, and is constrained to supported tools.
    This waives only the derived privacy/secret keyword flag; explicit
    route-metadata privacy flags, governance/public/audio/provider-spend flags,
    sensitive paths, and public/runtime gates still apply normally.
    """

    if not _auto_arm_truthy(frontmatter.get("pass_backed_secret_only")):
        return False
    if not _auto_arm_truthy(frontmatter.get("no_secret_value_storage")):
        return False
    if not _auto_arm_truthy(frontmatter.get("subscription_quota_only")):
        return False
    if not _auto_arm_truthy(frontmatter.get("supported_tools_only")):
        return False
    secret_entry = _frontmatter_non_null_scalar(frontmatter.get("secret_entry"))
    if not secret_entry:
        return False
    # Intentionally scoped to the GLM Coding Plan pass namespace.
    if not secret_entry.startswith("glmcp/"):
        return False
    if any(ch.isspace() for ch in secret_entry):
        return False
    parts = secret_entry.split("/")
    return not any(part in {"", ".", ".."} for part in parts) and not secret_entry.startswith(
        ("/", "~")
    )


def release_auto_arm_waivers(frontmatter: Mapping[str, Any]) -> tuple[str, ...]:
    """Auto-arm waiver names used by the lifecycle assessment for audit receipts."""

    waivers: list[str] = []
    if _pass_backed_runtime_secret_auto_arm_ok(frontmatter):
        waivers.append("pass_backed_runtime_secret_waiver")
    return tuple(waivers)


def _effective_sensitive_flags(frontmatter: Mapping[str, Any]) -> list[str]:
    """Sensitive risk flags from explicit route metadata OR keyword derivation.

    The derived (keyword) pass matters because an explicit-route-metadata task
    can omit ``risk_flags`` entirely yet still be governance/audio/public by its
    title or tags — those must not be auto-armed.
    """

    from shared.route_metadata_schema import _derive_risk_flags, assess_route_metadata

    flags: set[str] = set()
    derived = _derive_risk_flags(frontmatter)
    for name in SENSITIVE_RISK_FLAGS:
        if (
            name == "privacy_or_secret_sensitive"
            and derived.get(name)
            and _pass_backed_runtime_secret_auto_arm_ok(frontmatter)
            and not _explicit_risk_flag_true(frontmatter, name)
        ):
            continue
        if derived.get(name):
            flags.add(name)
    metadata = assess_route_metadata(frontmatter).metadata
    if metadata is not None:
        for name in SENSITIVE_RISK_FLAGS:
            if getattr(metadata.risk_flags, name, False):
                flags.add(name)
    return sorted(flags)


def _path_matches_sensitive_marker(ref: str, marker: str) -> bool:
    """Path-segment match of a governance-sensitive marker against a ref.

    Directory markers (e.g. ``axioms/``, ``shared/governance/``) match a
    consecutive run of path segments; bare-file markers (``codeowners``,
    ``claude.md``, ``hapax-constitution``) match a whole path segment. This
    replaces a raw substring test that false-vetoed refs which merely contain a
    marker as a substring — e.g. ``scripts/sync-codeowners.py`` (not the
    CODEOWNERS file) or ``research/meta-axioms/notes.md`` (not axioms/).
    """

    segments = [seg for seg in ref.strip().lower().replace("\\", "/").split("/") if seg]
    marker_segments = [seg for seg in marker.strip().lower().strip("/").split("/") if seg]
    if not segments or not marker_segments:
        return False
    window = len(marker_segments)
    return any(
        segments[start : start + window] == marker_segments
        for start in range(len(segments) - window + 1)
    )


def _sensitive_paths_in_scope(frontmatter: Mapping[str, Any]) -> list[str]:
    refs = frontmatter.get("mutation_scope_refs")
    if isinstance(refs, (list, tuple)):
        values = [str(ref) for ref in refs]
    elif refs:
        values = [str(refs)]
    else:
        values = []
    hits: list[str] = []
    for ref in values:
        text = ref.strip()
        if any(_path_matches_sensitive_marker(text, marker) for marker in SENSITIVE_PATH_MARKERS):
            hits.append(text)
    return hits


def _route_metadata_assessable(frontmatter: Mapping[str, Any]) -> bool:
    from shared.route_metadata_schema import assess_route_metadata

    return assess_route_metadata(frontmatter).metadata is not None


def _release_auto_arm_blockers(
    frontmatter: Mapping[str, Any],
    *,
    now: float | datetime | None,
    verified_checks: set[str] | None = None,
) -> list[str]:
    from shared.release_gate import evaluate_avsdlc_release_gate

    blockers: list[str] = []
    # ISAP authorization-in-principle precondition.
    if not _auto_arm_truthy(frontmatter.get("implementation_authorized")):
        blockers.append("not_implementation_authorized")
    # Governance / sensitivity gate. Historically a hard veto (the manual-arm
    # limbo). Per operator directive 2026-06-22, when the caller supplies the PR's
    # verified (passing) checks each sensitive class is gated on its mitigation
    # EVIDENCE: present+verified → no veto (the SDLC auto-arms); missing → held
    # until the mitigation is produced; no gate defined for the class → fail
    # CLOSED. With no verified checks supplied (pure-frontmatter assessment) the
    # historical hard veto is preserved for backward compatibility.
    # Blocker reason-code contract: `risk_flag:` is the no-evidence legacy veto,
    # `needs_mitigation:` is emitted once per missing check (not grouped), and
    # `unmitigable_risk_flag:` means no automated mitigation gate is defined.
    for name in _effective_sensitive_flags(frontmatter):
        if verified_checks is None:
            blockers.append(f"risk_flag:{name}")
            continue
        required = RELEASE_MITIGATION_CHECKS.get(name)
        if not required:
            blockers.append(f"unmitigable_risk_flag:{name}")
            continue
        for check in required:
            if check not in verified_checks:
                blockers.append(f"needs_mitigation:{name}:{check}")
    # High-stakes mutation surfaces.
    surface = str(frontmatter.get("mutation_surface") or "").strip().lower()
    if surface in AUTO_ARM_INELIGIBLE_MUTATION_SURFACES:
        blockers.append(f"mutation_surface:{surface}")
    # Governance-protected / off-limits paths.
    blockers.extend(f"sensitive_path:{path}" for path in _sensitive_paths_in_scope(frontmatter))
    # Already a live public surface → human releases it.
    if _auto_arm_truthy(frontmatter.get("public_current")):
        blockers.append("public_current")
    # Highest risk tier → human releases it.
    if str(frontmatter.get("risk_tier") or "").strip().lower() == "t3":
        blockers.append("risk_tier:t3")
    # AVSDLC aesthetic/quality axes must permit (evidence present, or no axes).
    gate = evaluate_avsdlc_release_gate(frontmatter, now=now)
    blockers.extend(f"avsdlc:{blocker}" for blocker in gate.blockers)
    # Fail-closed when the route metadata cannot be assessed at all.
    if not _route_metadata_assessable(frontmatter):
        blockers.append("route_metadata_unassessable")
    return blockers


def assess_release_auto_arm(
    frontmatter: Mapping[str, Any],
    *,
    now: float | datetime | None = None,
    verified_checks: set[str] | None = None,
) -> ReleaseAutoArmAssessment:
    """Assess whether the system may auto-arm (authorize release for) a task.

    Only tasks that carry a ``release_authorized`` field participate (the
    reform-era model marker); legacy tasks without it are not subject and keep
    their prior autoqueue behavior. A subject task that is not yet armed
    ``needs_arming``; it is ``eligible`` only when it carries no governance,
    public, audio/live-egress, privacy, or provider-billing veto, its release
    was authorized-in-principle (``implementation_authorized``), and its AVSDLC
    quality axes permit.

    ``verified_checks`` (the PR's passing CI check names) switches the sensitivity
    classes from a hard veto to evidence-gating: a class is satisfied when its
    ``RELEASE_MITIGATION_CHECKS`` all passed. Omitted (the default) preserves the
    historical pure-frontmatter hard veto for backward compatibility.
    """

    subject = "release_authorized" in frontmatter
    armed = _auto_arm_truthy(frontmatter.get("release_authorized"))
    needs_arming = subject and not armed
    if not needs_arming:
        return ReleaseAutoArmAssessment(
            subject=subject,
            armed=armed,
            needs_arming=False,
            eligible=False,
            blockers=(),
        )
    blockers = _release_auto_arm_blockers(frontmatter, now=now, verified_checks=verified_checks)
    return ReleaseAutoArmAssessment(
        subject=True,
        armed=False,
        needs_arming=True,
        eligible=not blockers,
        blockers=tuple(blockers),
    )


def _stage_below_s7(stage_value: str) -> bool:
    match = _STAGE_PREFIX_RE.match(stage_value.strip().strip('"').strip("'"))
    if not match:
        return True
    return int(match.group(1)) < 7


def apply_release_auto_arm(
    note_text: str,
    *,
    now_iso: str,
    role: str = "autoqueue-system",
    head_sha: str | None = None,
    head_ref: str | None = None,
) -> str:
    """Return ``note_text`` with the system release-arming applied to frontmatter.

    Sets ``release_authorized: true``, advances ``stage`` to ``S7_RELEASE`` when
    it is below S7 or absent, records the authorized PR head when supplied,
    refreshes ``updated_at``, and appends a single audit line to the body. Pure
    text transform — file IO and the authority-case ledger append are the
    caller's responsibility.
    """

    if not note_text.startswith("---"):
        return note_text
    end = note_text.find("\n---", 4)
    if end < 0:
        return note_text
    front, body = note_text[: end + 1], note_text[end + 1 :]

    if re.search(r"(?m)^release_authorized:", front):
        front = re.sub(
            r"(?m)^release_authorized:\s*.*$", "release_authorized: true", front, count=1
        )
    else:
        front = front.rstrip("\n") + "\nrelease_authorized: true\n"

    for key, value in (
        ("release_authorized_head_sha", head_sha),
        ("release_authorized_head_ref", head_ref),
    ):
        if not value:
            continue
        line = yaml.safe_dump({key: value}, sort_keys=False).strip()
        if re.search(rf"(?m)^{re.escape(key)}:", front):
            front = re.sub(rf"(?m)^{re.escape(key)}:\s*.*$", line, front, count=1)
        else:
            front = front.rstrip("\n") + f"\n{line}\n"

    stage_match = re.search(r"(?m)^stage:\s*(.*)$", front)
    if stage_match:
        if _stage_below_s7(stage_match.group(1)):
            front = re.sub(r"(?m)^stage:\s*.*$", "stage: S7_RELEASE", front, count=1)
    else:
        front = front.rstrip("\n") + "\nstage: S7_RELEASE\n"

    if re.search(r"(?m)^updated_at:", front):
        front = re.sub(r"(?m)^updated_at:\s*.*$", f"updated_at: {now_iso}", front, count=1)
    else:
        front = front.rstrip("\n") + f"\nupdated_at: {now_iso}\n"

    log_line = (
        f"- {now_iso} {role}: release auto-arm (system) — "
        "release_authorized -> true, stage -> S7_RELEASE."
    )
    body = body.rstrip("\n") + "\n" + log_line + "\n"
    return front + body
