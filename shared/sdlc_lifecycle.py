"""Shared SDLC lifecycle vocabulary and markdown closure helpers."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
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
REVIEW_TEAM_DIGEST_MIGRATION_SHA256_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")


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


def _review_team_digest_migration_path(note_path: Path) -> Path:
    return note_path.parent / REVIEW_TEAM_DIGEST_MIGRATION_FILENAME


def _valid_artifact_basename(value: str) -> bool:
    return bool(value) and Path(value).name == value and value not in {".", ".."}


def _review_team_digest_migration_blockers(
    receipt_path: Path,
    *,
    note_path: Path | None,
    task_id: str | None,
) -> tuple[str, ...]:
    if note_path is None or not task_id:
        return ("acceptance_receipt_digest_migration_context_missing",)
    migration_path = _review_team_digest_migration_path(note_path)
    if not migration_path.is_file():
        return ("acceptance_receipt_digest_migration_missing",)
    try:
        loaded = yaml.safe_load(migration_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return (f"acceptance_receipt_digest_migration_malformed:{type(exc).__name__}",)
    if not isinstance(loaded, Mapping):
        return (
            f"acceptance_receipt_digest_migration_malformed:not_a_mapping:{type(loaded).__name__}",
        )
    if loaded.get("schema") != REVIEW_TEAM_DIGEST_MIGRATION_SCHEMA:
        return (
            "acceptance_receipt_digest_migration_malformed:schema:"
            f"{loaded.get('schema') or 'missing'}",
        )
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
        return (
            "acceptance_receipt_digest_migration_classification_not_preserving:"
            f"{classification or 'missing'}",
        )
    expected_sha = _frontmatter_non_null_scalar(entry.get("receipt_sha256"))
    if REVIEW_TEAM_DIGEST_MIGRATION_SHA256_RE.fullmatch(expected_sha) is None:
        return ("acceptance_receipt_digest_migration_malformed:receipt_sha256",)
    try:
        actual_sha = _sha256_file(receipt_path)
    except OSError as exc:
        return (f"acceptance_receipt_unreadable:{type(exc).__name__}",)
    if expected_sha.removeprefix("sha256:") != actual_sha:
        return ("acceptance_receipt_digest_migration_sha256_mismatch",)
    return ()


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

    blockers = [
        f"acceptance_receipt_missing_field:{field}"
        for field in ACCEPTANCE_RECEIPT_REQUIRED_FIELDS
        if not _frontmatter_non_null_scalar(loaded.get(field))
    ]
    verdict = _frontmatter_non_null_scalar(loaded.get("verdict"))
    if verdict and verdict.lower() not in ACCEPTANCE_RECEIPT_ACCEPTED_VERDICTS:
        blockers.append(f"acceptance_receipt_verdict_not_accepted:{verdict.lower()}")
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
                blockers.append("acceptance_receipt_review_team_dossier_sha256_missing")
                blockers.extend(migration_blockers)
        elif REVIEW_TEAM_DOSSIER_SHA256_RE.fullmatch(dossier_sha256) is None:
            blockers.append("acceptance_receipt_dossier_sha256_malformed")
        elif note_path is None or not task_id:
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
                    blockers.append(f"acceptance_receipt_dossier_unreadable:{type(exc).__name__}")
                else:
                    expected = dossier_sha256.removeprefix("sha256:")
                    if actual != expected:
                        blockers.append("acceptance_receipt_dossier_sha256_mismatch")
    return tuple(blockers)


def acceptance_receipt_blockers(frontmatter: Mapping[str, Any], note_path: Path) -> tuple[str, ...]:
    """Receipt blockers for a review-floor task; empty for non-review-floor tasks.

    A review-floor note without a resolvable ``task_id`` fails closed with
    ``missing_acceptance_receipt`` — the receipt is keyed by task_id, so an
    anonymous note can never present one.
    """

    if not requires_acceptance_receipt(frontmatter):
        return ()
    task_id = _frontmatter_non_null_scalar(frontmatter.get("task_id"))
    if not task_id:
        return ("missing_acceptance_receipt",)
    receipt_path = _task_artifact_path_beside_note(note_path, task_id, ACCEPTANCE_RECEIPT_SUFFIX)
    if receipt_path is None:
        return ("missing_acceptance_receipt",)
    return _acceptance_receipt_validity_blockers(
        receipt_path,
        note_path=note_path,
        task_id=task_id,
    )


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
