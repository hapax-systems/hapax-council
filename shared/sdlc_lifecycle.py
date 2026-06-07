"""Shared SDLC lifecycle vocabulary and markdown closure helpers."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
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


def task_closure_validity(
    text: str,
    *,
    pr_state_lookup: PrStateLookup | None = None,
    require_route_metadata: bool = False,
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
# and whose risk profile carries no governance/public/audio-egress veto.
# Sensitive tasks stay manual.

#: Risk flags whose presence (explicit or keyword-derived) vetoes auto-arming.
SENSITIVE_RISK_FLAGS = (
    "governance_sensitive",
    "public_claim_sensitive",
    "audio_or_live_egress_sensitive",
    "privacy_or_secret_sensitive",
    "provider_billing_sensitive",
)

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
    frontmatter: Mapping[str, Any], *, now: float | datetime | None
) -> list[str]:
    from shared.release_gate import evaluate_avsdlc_release_gate

    blockers: list[str] = []
    # ISAP authorization-in-principle precondition.
    if not _auto_arm_truthy(frontmatter.get("implementation_authorized")):
        blockers.append("not_implementation_authorized")
    # Governance / sensitivity veto (explicit risk flags OR keyword-derived).
    blockers.extend(f"risk_flag:{name}" for name in _effective_sensitive_flags(frontmatter))
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
) -> ReleaseAutoArmAssessment:
    """Assess whether the system may auto-arm (authorize release for) a task.

    Only tasks that carry a ``release_authorized`` field participate (the
    reform-era model marker); legacy tasks without it are not subject and keep
    their prior autoqueue behavior. A subject task that is not yet armed
    ``needs_arming``; it is ``eligible`` only when it carries no governance,
    public, audio/live-egress, privacy, or provider-billing veto, its release
    was authorized-in-principle (``implementation_authorized``), and its AVSDLC
    quality axes permit.
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
    blockers = _release_auto_arm_blockers(frontmatter, now=now)
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
) -> str:
    """Return ``note_text`` with the system release-arming applied to frontmatter.

    Sets ``release_authorized: true``, advances ``stage`` to ``S7_RELEASE`` when
    it is below S7 or absent, refreshes ``updated_at``, and appends a single
    audit line to the body. Pure text transform — file IO and the authority-case
    ledger append are the caller's responsibility.
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
