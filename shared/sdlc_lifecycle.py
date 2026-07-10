"""Shared SDLC lifecycle vocabulary and markdown closure helpers."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path
from types import MappingProxyType
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


def _acceptance_receipt_validity_blockers(receipt_path: Path) -> tuple[str, ...]:
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
    return _acceptance_receipt_validity_blockers(acceptance_receipt_path(note_path, task_id))


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
# STAGE_RE remains a legacy shape grammar until transition writers move to the
# exact metadata catalog. It is not an alias registry: matching this regex does
# not make a stage canonical. _STAGE_PREFIX_RE remains the deliberately lenient
# release-arm reader and must not be used for lifecycle admission.
STAGE_RE = re.compile(r"^S(\d{1,2})(?:_[A-Z][A-Z0-9_]*)?$")
SDLC_STAGE_METADATA_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "formal" / "sdlc-stage-metadata.yaml"
)
_CANONICAL_STAGE_TOKENS = (
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


class StageMetadataError(ValueError):
    """Typed fail-closed stage metadata or resolution failure."""

    def __init__(self, reason_code: str, *, raw_stage: str = "", repair_action: str) -> None:
        self.reason_code = reason_code
        self.raw_stage = raw_stage
        self.repair_action = repair_action
        detail = f":{raw_stage}" if raw_stage else ""
        super().__init__(f"{reason_code}{detail}; repair={repair_action}")


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects last-wins duplicate mappings."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[object, object]:
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise StageMetadataError(
                "stage_metadata_invalid_yaml_key",
                repair_action="use scalar mapping keys in the stage metadata SSOT",
            ) from exc
        if duplicate:
            raise StageMetadataError(
                "stage_metadata_duplicate_yaml_key",
                raw_stage=str(key),
                repair_action="remove the duplicate key; last-wins YAML is forbidden",
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


@dataclass(frozen=True)
class StageEdgeMetadata:
    """One typed normal, escape, or fall edge from the stage SSOT."""

    to: str
    authority_capability: str
    guards: tuple[str, ...]
    actions: tuple[str, ...]
    enforcement: str
    enforcement_ref: str | None


@dataclass(frozen=True)
class StageDeliverableMetadata:
    """The artifact shape due at one lifecycle stage."""

    id: str
    required_fields: tuple[str, ...]


@dataclass(frozen=True)
class StageOperationAdmissionMetadata:
    """One governed operation that may occur while a task remains in a stage."""

    operation: str
    authority_capability: str
    guards: tuple[str, ...]
    actions: tuple[str, ...]
    enforcement: str
    enforcement_ref: str | None


@dataclass(frozen=True)
class StageMetadata:
    """One immutable row in the canonical SDLC stage table."""

    token: str
    display_alias: str
    aliases: tuple[str, ...]
    deprecated_aliases: tuple[str, ...]
    label: str
    terminal: bool
    blocked: bool
    deliverable: StageDeliverableMetadata
    operation_admissions: tuple[StageOperationAdmissionMetadata, ...]
    next_edges: tuple[StageEdgeMetadata, ...]
    fall_edges: tuple[StageEdgeMetadata, ...]


@dataclass(frozen=True)
class StageMetadataCatalog:
    """Immutable indexed view of the stage metadata SSOT."""

    schema: str
    stages: tuple[StageMetadata, ...]
    by_token: Mapping[str, StageMetadata]
    alias_to_token: Mapping[str, str]

    @property
    def tokens(self) -> tuple[str, ...]:
        return tuple(stage.token for stage in self.stages)


def _metadata_error(reason: str, repair: str, raw_stage: str = "") -> StageMetadataError:
    return StageMetadataError(reason, raw_stage=raw_stage, repair_action=repair)


def _assert_exact_keys(
    payload: Mapping[str, Any], expected: set[str], *, row: str, optional: set[str] | None = None
) -> None:
    optional = optional or set()
    keys = {str(key) for key in payload}
    unknown = keys - expected - optional
    missing = expected - keys
    if unknown:
        raise _metadata_error(
            "stage_metadata_unknown_field",
            f"remove unknown fields: {', '.join(sorted(unknown))}",
            row,
        )
    if missing:
        raise _metadata_error(
            "stage_metadata_missing_field",
            f"add required fields: {', '.join(sorted(missing))}",
            row,
        )


def _required_string(payload: Mapping[str, Any], key: str, *, row: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _metadata_error(
            "stage_metadata_invalid_field",
            f"set {key} to a non-empty string",
            f"{row}.{key}",
        )
    if value != value.strip():
        raise _metadata_error(
            "stage_metadata_whitespace_drift",
            f"remove leading or trailing whitespace from {key}",
            f"{row}.{key}",
        )
    return value


def _string_tuple(
    value: object, *, row: str, field_name: str, allow_empty: bool = True
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _metadata_error(
            "stage_metadata_invalid_field", f"set {field_name} to a list", f"{row}.{field_name}"
        )
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise _metadata_error(
                "stage_metadata_invalid_field",
                f"use non-empty string entries in {field_name}",
                f"{row}.{field_name}",
            )
        if item != item.strip():
            raise _metadata_error(
                "stage_metadata_whitespace_drift",
                f"remove leading or trailing whitespace from {field_name}",
                f"{row}.{field_name}",
            )
        result.append(item)
    if not result and not allow_empty:
        raise _metadata_error(
            "stage_metadata_semantic_field_empty",
            f"declare at least one value in {field_name}",
            f"{row}.{field_name}",
        )
    if len(result) != len(set(result)):
        raise _metadata_error(
            "stage_metadata_duplicate_value",
            f"remove duplicate entries from {field_name}",
            f"{row}.{field_name}",
        )
    return tuple(result)


def _edge_tuple(value: object, *, row: str, edge_class: str) -> tuple[StageEdgeMetadata, ...]:
    if not isinstance(value, list):
        raise _metadata_error(
            "stage_metadata_invalid_edge_list",
            f"set {edge_class} to a list of typed edges",
            row,
        )
    edges: list[StageEdgeMetadata] = []
    destinations: set[str] = set()
    for index, item in enumerate(value):
        edge_row = f"{row}.{edge_class}[{index}]"
        if not isinstance(item, Mapping):
            raise _metadata_error(
                "stage_metadata_invalid_edge", "replace the edge with a mapping", edge_row
            )
        _assert_exact_keys(
            item,
            {"to", "authority_capability", "guards", "actions", "enforcement"},
            optional={"enforcement_ref"},
            row=edge_row,
        )
        destination = _required_string(item, "to", row=edge_row)
        if destination in destinations:
            raise _metadata_error(
                "stage_metadata_duplicate_edge",
                f"keep one {edge_class} edge to {destination}",
                edge_row,
            )
        destinations.add(destination)
        enforcement = _required_string(item, "enforcement", row=edge_row)
        if enforcement not in {"declared", "enforced"}:
            raise _metadata_error(
                "stage_metadata_invalid_enforcement",
                "use declared or enforced",
                edge_row,
            )
        enforcement_ref_raw = item.get("enforcement_ref")
        enforcement_ref = None
        if enforcement_ref_raw is not None:
            enforcement_ref = _required_string(item, "enforcement_ref", row=edge_row)
        if enforcement == "enforced" and enforcement_ref is None:
            raise _metadata_error(
                "stage_metadata_enforcement_witness_missing",
                "add enforcement_ref or mark the edge declared",
                edge_row,
            )
        edges.append(
            StageEdgeMetadata(
                to=destination,
                authority_capability=_required_string(
                    item, "authority_capability", row=edge_row
                ),
                guards=_string_tuple(
                    item.get("guards"), row=edge_row, field_name="guards", allow_empty=False
                ),
                actions=_string_tuple(
                    item.get("actions"), row=edge_row, field_name="actions", allow_empty=False
                ),
                enforcement=enforcement,
                enforcement_ref=enforcement_ref,
            )
        )
    return tuple(edges)


def _operation_admission_tuple(
    value: object, *, row: str
) -> tuple[StageOperationAdmissionMetadata, ...]:
    if not isinstance(value, list):
        raise _metadata_error(
            "stage_metadata_invalid_operation_admission_list",
            "set operation_admissions to a list of typed admissions",
            row,
        )
    admissions: list[StageOperationAdmissionMetadata] = []
    operations: set[str] = set()
    for index, item in enumerate(value):
        admission_row = f"{row}.operation_admissions[{index}]"
        if not isinstance(item, Mapping):
            raise _metadata_error(
                "stage_metadata_invalid_operation_admission",
                "replace the operation admission with a mapping",
                admission_row,
            )
        _assert_exact_keys(
            item,
            {"operation", "authority_capability", "guards", "actions", "enforcement"},
            optional={"enforcement_ref"},
            row=admission_row,
        )
        operation = _required_string(item, "operation", row=admission_row)
        if operation in operations:
            raise _metadata_error(
                "stage_metadata_duplicate_operation_admission",
                f"keep one admission for {operation}",
                admission_row,
            )
        operations.add(operation)
        enforcement = _required_string(item, "enforcement", row=admission_row)
        if enforcement not in {"declared", "enforced"}:
            raise _metadata_error(
                "stage_metadata_invalid_enforcement",
                "use declared or enforced",
                admission_row,
            )
        enforcement_ref = None
        if item.get("enforcement_ref") is not None:
            enforcement_ref = _required_string(item, "enforcement_ref", row=admission_row)
        if enforcement == "enforced" and enforcement_ref is None:
            raise _metadata_error(
                "stage_metadata_enforcement_witness_missing",
                "add enforcement_ref or mark the operation admission declared",
                admission_row,
            )
        admissions.append(
            StageOperationAdmissionMetadata(
                operation=operation,
                authority_capability=_required_string(
                    item, "authority_capability", row=admission_row
                ),
                guards=_string_tuple(
                    item.get("guards"),
                    row=admission_row,
                    field_name="guards",
                    allow_empty=False,
                ),
                actions=_string_tuple(
                    item.get("actions"),
                    row=admission_row,
                    field_name="actions",
                    allow_empty=False,
                ),
                enforcement=enforcement,
                enforcement_ref=enforcement_ref,
            )
        )
    return tuple(admissions)


def _parse_stage_row(payload: object, *, index: int) -> StageMetadata:
    row = f"stages[{index}]"
    if not isinstance(payload, Mapping):
        raise _metadata_error("stage_metadata_invalid_row", "replace the row with a mapping", row)
    _assert_exact_keys(
        payload,
        {
            "token",
            "display_alias",
            "aliases",
            "label",
            "terminal",
            "blocked",
            "deliverable",
            "operation_admissions",
            "next",
            "fall",
        },
        optional={"deprecated_aliases"},
        row=row,
    )
    token = _required_string(payload, "token", row=row)
    deliverable_payload = payload.get("deliverable")
    if not isinstance(deliverable_payload, Mapping):
        raise _metadata_error(
            "stage_metadata_invalid_deliverable", "set deliverable to a mapping", token
        )
    _assert_exact_keys(
        deliverable_payload, {"id", "required_fields"}, row=f"{token}.deliverable"
    )
    terminal = payload.get("terminal")
    blocked = payload.get("blocked")
    if not isinstance(terminal, bool) or not isinstance(blocked, bool):
        raise _metadata_error(
            "stage_metadata_invalid_flags",
            "set terminal and blocked to explicit booleans",
            token,
        )
    return StageMetadata(
        token=token,
        display_alias=_required_string(payload, "display_alias", row=token),
        aliases=_string_tuple(payload.get("aliases"), row=token, field_name="aliases"),
        deprecated_aliases=_string_tuple(
            payload.get("deprecated_aliases", []), row=token, field_name="deprecated_aliases"
        ),
        label=_required_string(payload, "label", row=token),
        terminal=terminal,
        blocked=blocked,
        deliverable=StageDeliverableMetadata(
            id=_required_string(deliverable_payload, "id", row=f"{token}.deliverable"),
            required_fields=_string_tuple(
                deliverable_payload.get("required_fields"),
                row=f"{token}.deliverable",
                field_name="required_fields",
                allow_empty=False,
            ),
        ),
        operation_admissions=_operation_admission_tuple(
            payload.get("operation_admissions"), row=token
        ),
        next_edges=_edge_tuple(payload.get("next"), row=token, edge_class="next"),
        fall_edges=_edge_tuple(payload.get("fall"), row=token, edge_class="fall"),
    )


def _read_stage_metadata(path: Path | None) -> tuple[str, str]:
    if path is not None:
        source_label = str(path)
        try:
            return path.read_text(encoding="utf-8"), source_label
        except FileNotFoundError as exc:
            raise _metadata_error(
                "stage_metadata_source_missing",
                "restore the packaged or repository stage metadata SSOT",
                source_label,
            ) from exc
        except UnicodeError as exc:
            raise _metadata_error(
                "stage_metadata_source_encoding_invalid",
                "encode the stage metadata SSOT as UTF-8",
                source_label,
            ) from exc
        except OSError as exc:
            raise _metadata_error(
                "stage_metadata_source_unreadable",
                "restore readable permissions for the stage metadata SSOT",
                source_label,
            ) from exc
    if SDLC_STAGE_METADATA_PATH.is_file():
        return _read_stage_metadata(SDLC_STAGE_METADATA_PATH)
    packaged = resources.files("shared").joinpath("_data").joinpath("sdlc-stage-metadata.yaml")
    source_label = "shared/_data/sdlc-stage-metadata.yaml"
    try:
        return packaged.read_text(encoding="utf-8"), source_label
    except FileNotFoundError as exc:
        raise _metadata_error(
            "stage_metadata_source_missing",
            "restore the packaged or repository stage metadata SSOT",
            source_label,
        ) from exc
    except UnicodeError as exc:
        raise _metadata_error(
            "stage_metadata_source_encoding_invalid",
            "encode the packaged stage metadata SSOT as UTF-8",
            source_label,
        ) from exc
    except OSError as exc:
        raise _metadata_error(
            "stage_metadata_source_unreadable",
            "restore readable permissions for the packaged stage metadata SSOT",
            source_label,
        ) from exc


def load_sdlc_stage_metadata(path: Path | None = None) -> StageMetadataCatalog:
    """Load and strictly validate the canonical stage table without fallback."""

    raw, source_label = _read_stage_metadata(path)
    try:
        payload = yaml.load(raw, Loader=_UniqueKeyLoader)
    except StageMetadataError:
        raise
    except yaml.YAMLError as exc:
        raise _metadata_error(
            "stage_metadata_yaml_invalid", "repair the YAML syntax", source_label
        ) from exc
    if not isinstance(payload, Mapping):
        raise _metadata_error(
            "stage_metadata_root_invalid", "make the YAML root a mapping", source_label
        )
    _assert_exact_keys(
        payload, {"schema", "formal_model", "edge_classes", "stages"}, row="root"
    )
    schema = payload.get("schema")
    if schema != "hapax.sdlc-stage-metadata.v1":
        raise _metadata_error(
            "stage_metadata_schema_unknown",
            "set schema to hapax.sdlc-stage-metadata.v1",
            str(schema or "<missing>"),
        )
    if payload.get("formal_model") != "docs/formal/sdlc-ladder.tla":
        raise _metadata_error(
            "stage_metadata_formal_model_invalid",
            "set formal_model to docs/formal/sdlc-ladder.tla",
            str(payload.get("formal_model") or "<missing>"),
        )
    edge_classes = payload.get("edge_classes")
    if not isinstance(edge_classes, Mapping):
        raise _metadata_error(
            "stage_metadata_edge_classes_invalid",
            "declare next and fall edge classes as a mapping",
            source_label,
        )
    _assert_exact_keys(edge_classes, {"next", "fall"}, row="edge_classes")
    for name in ("next", "fall"):
        _required_string(edge_classes, name, row="edge_classes")
    rows = payload.get("stages")
    if not isinstance(rows, list) or not rows:
        raise _metadata_error(
            "stage_metadata_stages_missing", "provide a non-empty stages list", source_label
        )
    stages = tuple(_parse_stage_row(row, index=index) for index, row in enumerate(rows))
    tokens = [stage.token for stage in stages]
    if len(tokens) != len(set(tokens)):
        raise _metadata_error(
            "stage_metadata_duplicate_token", "keep exactly one row per stage token"
        )
    if tuple(tokens) != _CANONICAL_STAGE_TOKENS:
        raise _metadata_error(
            "stage_metadata_token_sequence_invalid",
            "restore the exact ordered S0..S11, S3_5, BLOCKED token sequence",
        )
    by_token = {stage.token: stage for stage in stages}
    alias_to_token: dict[str, str] = {token: token for token in tokens}
    casefolded: dict[str, str] = {token.casefold(): token for token in tokens}
    for stage in stages:
        declared_aliases = (stage.display_alias, *stage.aliases)
        if stage.display_alias in stage.aliases or stage.token in stage.aliases:
            raise _metadata_error(
                "stage_metadata_duplicate_alias",
                "do not repeat display_alias or the canonical token in aliases",
                stage.token,
            )
        if not set(stage.deprecated_aliases).issubset(set(stage.aliases)):
            raise _metadata_error(
                "stage_metadata_deprecated_alias_not_declared",
                "list every deprecated alias in aliases too",
                stage.token,
            )
        for alias in declared_aliases:
            alias_match = STAGE_RE.fullmatch(alias)
            special_owner = {"S3.5": "S3_5", "S3_5": "S3_5", "BLOCKED": "BLOCKED"}.get(
                alias
            )
            if alias_match is None and special_owner is None:
                raise _metadata_error(
                    "stage_metadata_alias_shape_invalid",
                    "use an exact uppercase stage alias or the declared S3.5 compatibility form",
                    alias,
                )
            alias_owner = f"S{alias_match.group(1)}" if alias_match is not None else special_owner
            if alias_owner != stage.token:
                raise _metadata_error(
                    "stage_metadata_alias_token_mismatch",
                    f"use an alias whose stage prefix resolves to {stage.token}",
                    alias,
                )
            if alias == stage.token:
                continue
            owner = alias_to_token.get(alias)
            if owner is not None and owner != stage.token:
                raise _metadata_error(
                    "stage_metadata_duplicate_alias",
                    f"assign {alias} to only one stage",
                    alias,
                )
            folded_owner = casefolded.get(alias.casefold())
            if folded_owner is not None and folded_owner != alias:
                raise _metadata_error(
                    "stage_metadata_casefold_collision",
                    f"remove alias {alias}; it collides by case with {folded_owner}",
                    alias,
                )
            alias_to_token[alias] = stage.token
            casefolded[alias.casefold()] = alias
    target_tokens = set(tokens)
    terminal = [stage for stage in stages if stage.terminal]
    blocked = [stage for stage in stages if stage.blocked]
    if len(terminal) != 1 or len(blocked) != 1:
        raise _metadata_error(
            "stage_metadata_terminal_blocked_cardinality",
            "declare exactly one terminal and one blocked stage",
        )
    blocked_token = blocked[0].token
    for stage in stages:
        if stage.terminal and (stage.next_edges or stage.fall_edges):
            raise _metadata_error(
                "stage_metadata_terminal_has_edges",
                "remove all next and fall edges from the terminal stage",
                stage.token,
            )
        if stage.blocked and (not stage.next_edges or stage.fall_edges):
            raise _metadata_error(
                "stage_metadata_blocked_edge_invalid",
                "give BLOCKED escape next edges and no fall edges",
                stage.token,
            )
        if not stage.terminal and not stage.blocked and not stage.next_edges:
            raise _metadata_error(
                "stage_metadata_nonterminal_dead_end",
                "add at least one normal successor",
                stage.token,
            )
        for edge in (*stage.next_edges, *stage.fall_edges):
            if edge.to not in target_tokens:
                raise _metadata_error(
                    "stage_metadata_unknown_edge_target",
                    f"declare target {edge.to} or correct the edge",
                    stage.token,
                )
        if not stage.terminal and not stage.blocked:
            if tuple(edge.to for edge in stage.fall_edges) != (blocked_token,):
                raise _metadata_error(
                    "stage_metadata_fall_contract_invalid",
                    f"give {stage.token} exactly one fall edge to {blocked_token}",
                    stage.token,
                )
    return StageMetadataCatalog(
        schema=str(schema),
        stages=stages,
        by_token=MappingProxyType(by_token),
        alias_to_token=MappingProxyType(alias_to_token),
    )


SDLC_STAGE_METADATA = load_sdlc_stage_metadata()


def stage_token(raw: str) -> str:
    """Resolve one exact canonical token or declared alias, case-sensitively."""

    if not raw.strip():
        raise _metadata_error("stage_blank", "provide a canonical stage token or declared alias")
    if raw != raw.strip():
        raise _metadata_error(
            "stage_whitespace_drift", "remove leading or trailing whitespace", raw
        )
    candidate = raw
    resolved = SDLC_STAGE_METADATA.alias_to_token.get(candidate)
    if resolved is not None:
        return resolved
    folded = {alias.casefold(): alias for alias in SDLC_STAGE_METADATA.alias_to_token}
    if candidate.casefold() in folded:
        canonical = folded[candidate.casefold()]
        raise _metadata_error(
            "stage_case_drift", f"use exact case: {canonical}", candidate
        )
    if STAGE_RE.fullmatch(candidate):
        raise _metadata_error(
            "stage_alias_unknown",
            "use a token or alias declared in docs/formal/sdlc-stage-metadata.yaml",
            candidate,
        )
    raise _metadata_error(
        "stage_shape_invalid",
        "use a token or alias declared in docs/formal/sdlc-stage-metadata.yaml",
        candidate,
    )


def stage_edges(raw: str, *, include_fall: bool = False) -> frozenset[str]:
    """Return declared Next destinations, optionally unioned with Fall."""

    stage = SDLC_STAGE_METADATA.by_token[stage_token(raw)]
    destinations = {edge.to for edge in stage.next_edges}
    if include_fall:
        destinations.update(edge.to for edge in stage.fall_edges)
    return frozenset(destinations)


def is_legal_stage_edge(source: str, target: str, *, edge_class: str = "any") -> bool:
    """Pure edge lookup; transition writers begin enforcing it in slice 4."""

    if edge_class not in {"next", "fall", "any"}:
        raise ValueError("edge_class must be next, fall, or any")
    stage = SDLC_STAGE_METADATA.by_token[stage_token(source)]
    target_token = stage_token(target)
    next_targets = {edge.to for edge in stage.next_edges}
    fall_targets = {edge.to for edge in stage.fall_edges}
    if edge_class == "next":
        return target_token in next_targets
    if edge_class == "fall":
        return target_token in fall_targets
    return target_token in next_targets or target_token in fall_targets


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
