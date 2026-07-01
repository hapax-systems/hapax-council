"""review_team — PR review-team constitution, dossier synthesis, admission gate.

Pure logic for the PR review-team system (spec:
``~/Documents/Personal/30-areas/hapax/pr-review-team-design-2026-06-11.md``,
CASE-ROUTING-OPERATIONALIZATION-20260609):

- lens selection: changed files -> mandatory lens charters (registry §1)
- tactical sizing: task risk x touched surfaces -> team class (registry §2)
- strategic constitution: cross model-family seats, the writer's family never
  holds the majority alone (registry §3)
- dossier synthesis: blind reviewer verdicts -> quorum verdict + escalations
- admission gate: ``review_team_verdict_blockers`` consumed by
  ``scripts/cc-pr-autoqueue.py`` (no quorum, no merge)

Registry: ``config/review-lenses/registry.yaml``. Dossiers live beside the
cc-task note as ``<task_id>.review-dossier.yaml`` (same pattern as acceptance
receipts). Emergency bypass: ``HAPAX_REVIEW_TEAM_GATE_OFF=1`` disables only
post-dossier admission blockers; it does not authorize dispatcher/provider
invocation when route, quota, resource, or authority admission is missing. The
dispatcher killswitch is ``HAPAX_REVIEW_TEAM_DISPATCH_OFF=1``.
"""

from __future__ import annotations

import ast
import fnmatch
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.dispatcher_policy import ROUTE_DECISION_LEDGER  # noqa: E402
from shared.failure_classification import (  # noqa: E402
    STRUCTURED_PROVIDER_OUTAGE_ACTIONS,
    STRUCTURED_PROVIDER_OUTAGE_ERROR_CLASSES,
    STRUCTURED_QUOTA_ACTIONS,
    STRUCTURED_QUOTA_ERROR_CLASSES,
    FailureCode,
    FailureReceipt,
)

DEFAULT_REGISTRY_PATH = REPO_ROOT / "config" / "review-lenses" / "registry.yaml"
LENS_DIR = REPO_ROOT / "config" / "review-lenses"
DEFAULT_ROUTE_DECISION_LEDGER_PATH = (
    Path.home() / ".cache" / "hapax" / "orchestration" / ROUTE_DECISION_LEDGER
)
ROUTE_DECISION_LEDGER_PATH = DEFAULT_ROUTE_DECISION_LEDGER_PATH

#: Dossier filename suffix; the dossier lives beside the task note.
REVIEW_DOSSIER_SUFFIX = ".review-dossier.yaml"

#: The only dossier verdict that admits a PR.
QUORUM_ACCEPT = "quorum-accept"

#: Reviewer verdicts that count toward the accept quorum.
ACCEPT_VERDICTS = frozenset({"accept", "accept-with-findings"})

#: Reviewer verdicts the dispatcher may record. ``invalid-output`` is what an
#: unparseable reviewer reply becomes — it never counts as an accept.
#: ``quota-wall``, ``provider-outage``, and ``reviewer-route-unavailable`` are
#: FAMILY-AVAILABILITY signals:
#: on 2026-06-12 the claude weekly wall surfaced as invalid-output for 13
#: hours and t1's require_all_families sealed the merge gate fleet-wide
#: (postmortem failure class #1). Availability failures must be named so the
#: constitution can degrade instead of seal, while preserving the true cause.
REVIEWER_VERDICTS = frozenset(
    {
        "accept",
        "accept-with-findings",
        "block",
        "invalid-output",
        "quota-wall",
        "provider-outage",
        "reviewer-route-unavailable",
    }
)
FAMILY_OUTAGE_VERDICTS = frozenset({"quota-wall", "provider-outage", "reviewer-route-unavailable"})
TEAM_CLASS_RANK = {"t3_docs": 0, "t2_standard": 1, "t1_critical": 2}

#: Provider usage-wall shapes (the 2026-06-12 claude weekly-wall text is the
#: canonical fixture; the rest cover the codex/gemini/glm families' phrasings).
_RESET_TIME_SHAPE = (
    r"(?:(?:[A-Z][a-z]{2}\s+\d{1,2},\s+)?"
    r"\d{1,2}(?::\d{2})?\s*(?:am|pm)"
    r"(?:\s+(?:\([A-Z][A-Za-z0-9._+-]*(?:/[A-Z][A-Za-z0-9._+-]*)+\)"
    r"|[A-Z][A-Za-z0-9._+-]*(?:/[A-Z][A-Za-z0-9._+-]*)+|[A-Z]{2,5}))?)"
)
_QUOTA_WALL_SHAPE_RE = re.compile(
    r"\A("
    r"You('ve| have) hit your (weekly|usage|session|5-hour) limit"
    rf"(?:\s+·\s+resets\s+{_RESET_TIME_SHAPE})?"
    r"|HTTP 429 Too Many Requests"
    r"|Too Many Requests"
    r"|RESOURCE_EXHAUSTED(?::\s+Quota (?:exceeded|exhausted))?"
    r"|rate.?limit\s+(?:reached|exceeded|hit)(?:\s+for\s+\w+)?"
    r"|usage limit\s+(?:reached|exceeded|hit)"
    r"|quota\s+(?:reached|exceeded|exhausted|hit)"
    r")\Z",
    re.IGNORECASE,
)

#: Real provider walls are terse one-liners. A long unparseable reply that
#: merely MENTIONS quota-ish words (a half-written review of rate-limit code,
#: or attacker-influenced diff text echoed back) must never classify as a
#: wall — that would forge a family outage and degrade the next constitution
#: (round-4 review finding).
_QUOTA_WALL_MAX_CHARS = 600

#: Extended line-by-line wall pattern for CLIs that wrap the wall phrase in
#: diagnostic chrome (codex v0.139.0 emits ~704 chars of "ERROR: You've hit
#: your usage limit. Visit <URL> … purchase more credits … try again at …").
#: Applied ONLY when model_stdout is empty (the anti-forge anchor: a real
#: wall produces NO review output).
_QUOTA_WALL_LINE_RE = re.compile(
    r"\A(?:ERROR:\s*)?"
    r"You(?:'ve| have) hit your (?:weekly|usage|session|5-hour) (?:limit|cap)"
    rf"(?:(?:\s+·\s+resets\s+{_RESET_TIME_SHAPE})"
    r"|(?:\.\s+Visit\s+\S+.*(?:purchase more credits|upgrade your plan|try again).*))?"
    r"\Z",
    re.IGNORECASE,
)
_QUOTA_WALL_HTTP_RE = re.compile(
    r"\A(?:[-\w.]+:\s+api error:\s+)?HTTP\s+429\b.*"
    r"(?:quota|usage limit|rate.?limit|too many requests|insufficient balance|"
    r"RESOURCE_EXHAUSTED)",
    re.IGNORECASE | re.DOTALL,
)
_STRUCTURED_ZAI_ENVELOPE_RE = re.compile(
    r"\A\s*hapax-glmcp-reviewer:\s+api error:\s+HTTP\s+\d{3}\b",
    re.IGNORECASE,
)
_STRUCTURED_FIELD_VALUE_RE = re.compile(r"\A[A-Za-z0-9_:-]+\Z")
# The structured-envelope allowlists now live in shared/failure_classification.py (single source
# across the review + worker planes). Aliased here byte-identically; the classifier logic below is
# unchanged. NEVER move a class between QUOTA and PROVIDER_OUTAGE — verdicts would drift.
_STRUCTURED_QUOTA_ERROR_CLASSES = STRUCTURED_QUOTA_ERROR_CLASSES
_STRUCTURED_QUOTA_ACTIONS = STRUCTURED_QUOTA_ACTIONS

_PROVIDER_OUTAGE_SHAPE_RE = re.compile(
    r"\bHTTP\s+(?:429|5\d\d)\b",
    re.IGNORECASE,
)

_PROVIDER_OUTAGE_LINE_RE = re.compile(
    r"(?:temporarily overloaded|server-side issue|try again later|retry later|"
    r"check the Z\.ai Coding Plan endpoint|bad gateway|service unavailable|"
    r"gateway timeout|network error|timed out)",
    re.IGNORECASE,
)
_PROVIDER_OUTAGE_MAX_CHARS = 4_000
_REVIEWER_ROUTE_UNAVAILABLE_MAX_CHARS = 4_000
_UNSUPPORTED_REVIEWER_CLIENT_RE = re.compile(
    r"(?:IneligibleTierError|UNSUPPORTED_CLIENT|failed to launch .*?\bagy\b.*?install agy)",
    re.IGNORECASE,
)
_STRUCTURED_PROVIDER_OUTAGE_ERROR_CLASSES = STRUCTURED_PROVIDER_OUTAGE_ERROR_CLASSES
_STRUCTURED_PROVIDER_OUTAGE_ACTIONS = STRUCTURED_PROVIDER_OUTAGE_ACTIONS

#: The dispatcher's family-outage witness state (canonical path; the
#: dispatcher aliases this). Admission consults it so a forged dossier
#: cannot self-certify a degradation (round-4 review finding).
FAMILY_OUTAGE_STATE = Path.home() / ".cache" / "hapax" / "review-team" / "family-outage.json"
FAMILY_OUTAGE_TTL_S = 2 * 3600


def _structured_zai_error_match_state(
    text: str,
    *,
    error_classes: frozenset[str],
    actions: frozenset[str],
) -> bool | None:
    """Return None when no structured controls exist, else trusted match state."""

    envelope = _STRUCTURED_ZAI_ENVELOPE_RE.search(text)
    if envelope is None:
        return None
    control_text = re.split(
        r";\s*(?:message|detail)=",
        text[envelope.start() :],
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    tokens: dict[str, str] = {}
    saw_control = False
    for raw_field in control_text.split(";")[1:]:
        field = raw_field.strip()
        if "=" not in field:
            continue
        key, value = [part.strip() for part in field.split("=", 1)]
        if key not in {"error_class", "action"}:
            continue
        saw_control = True
        if key in tokens or _STRUCTURED_FIELD_VALUE_RE.fullmatch(value) is None:
            return False
        tokens[key] = value
    if not saw_control:
        return None
    return tokens.get("error_class") in error_classes or tokens.get("action") in actions


def is_quota_wall(
    text: str,
    *,
    process_failed: bool = False,
    model_stdout: str = "",
) -> bool:
    """True when reviewer output/error text is a provider usage wall.

    Deliberately strict — forging an outage must be harder than hitting one:
    only process-failure diagnostics are trusted as provider evidence, short
    text only, and the whole output must match a known provider wall shape.
    This rejects model-controlled review stdout that merely mentions quota text.

    The ``model_stdout`` anti-forge anchor: a real wall produces NO review
    output. If the process emitted non-empty stdout (= model-produced prose),
    the stderr content cannot be trusted as sole wall evidence because the
    model was active enough to write something.
    """

    if not process_failed or not (text or model_stdout):
        return False
    stripped = text.strip()
    stdout_stripped = model_stdout.strip()
    # Anti-forge anchor (postmortem 2026-06-15): if the reviewer process
    # emitted review content on stdout, it was running — stderr text is
    # supplementary, not sole wall evidence. Narrow exception: Claude Code
    # can emit its own non-model quota wall on stdout with empty stderr and a
    # nonzero exit. Accept only a short exact provider wall phrase.
    if stdout_stripped:
        return bool(
            not stripped
            and len(stdout_stripped) <= _QUOTA_WALL_MAX_CHARS
            and _QUOTA_WALL_SHAPE_RE.fullmatch(stdout_stripped)
        )
    # Fast path: short, bare wall phrase (the 2026-06-12 claude shape)
    if len(stripped) <= _QUOTA_WALL_MAX_CHARS and _QUOTA_WALL_SHAPE_RE.fullmatch(stripped):
        return True
    if len(stripped) <= _PROVIDER_OUTAGE_MAX_CHARS:
        structured_match = _structured_zai_error_match_state(
            stripped,
            error_classes=_STRUCTURED_QUOTA_ERROR_CLASSES,
            actions=_STRUCTURED_QUOTA_ACTIONS,
        )
        if structured_match is not None:
            return structured_match
    if len(stripped) <= _PROVIDER_OUTAGE_MAX_CHARS and _QUOTA_WALL_HTTP_RE.search(stripped):
        return True
    # Slow path: CLI chrome wraps the wall phrase (codex v0.139.0 emits
    # ~704 chars including "ERROR: You've hit your usage limit. Visit …
    # purchase more credits … try again at <date>"). Scan each line for
    # a wall-shaped line.  The empty-stdout anchor above prevents a diff-
    # echoed stderr from forging this.
    for line in stripped.splitlines():
        line = line.strip()
        if line and _QUOTA_WALL_LINE_RE.fullmatch(line):
            return True
    return False


def is_provider_outage(
    text: str,
    *,
    process_failed: bool = False,
    model_stdout: str = "",
) -> bool:
    """True when process-failure diagnostics show provider unavailability.

    This deliberately uses the same channel-trust constraints as quota-wall
    classification: no model stdout may be present, and the diagnostic must be
    terse and match known provider outage phrasing.
    """

    if not process_failed or not text:
        return False
    stripped = text.strip()
    if model_stdout.strip():
        return False
    if len(stripped) > _PROVIDER_OUTAGE_MAX_CHARS:
        return False
    normalized = re.sub(r"\A[-\w.]+:\s+api error:\s*", "", stripped, flags=re.I)
    structured_match = _structured_zai_error_match_state(
        stripped,
        error_classes=_STRUCTURED_PROVIDER_OUTAGE_ERROR_CLASSES,
        actions=_STRUCTURED_PROVIDER_OUTAGE_ACTIONS,
    )
    if structured_match is not None:
        return structured_match
    http_429 = bool(re.match(r"\AHTTP\s+429\b", normalized, flags=re.IGNORECASE))
    http_5xx = bool(re.match(r"\AHTTP\s+5\d\d\b", normalized, flags=re.IGNORECASE))
    outage_terms = bool(_PROVIDER_OUTAGE_LINE_RE.search(stripped))
    provider_detail = re.split(r";\s*retry later\b", normalized, maxsplit=1, flags=re.IGNORECASE)[0]
    provider_detail_outage_terms = bool(_PROVIDER_OUTAGE_LINE_RE.search(provider_detail))
    direct_outage = normalized.lower().startswith(("network error:", "request timed out after"))
    return (
        (http_5xx and outage_terms)
        or (http_429 and provider_detail_outage_terms)
        or (direct_outage and outage_terms)
    )


def is_reviewer_route_unavailable(
    text: str,
    *,
    process_failed: bool = False,
    model_stdout: str = "",
) -> bool:
    """True when the configured reviewer route itself is unavailable.

    This covers process-level auth/client/tier failures such as an unsupported
    reviewer client. It is a family-availability signal like a quota wall, but
    it is not mislabeled as a transient provider outage.
    """

    if not process_failed or not text:
        return False
    stripped = text.strip()
    if model_stdout.strip():
        return False
    if len(stripped) > _REVIEWER_ROUTE_UNAVAILABLE_MAX_CHARS:
        return False
    return bool(_UNSUPPORTED_REVIEWER_CLIENT_RE.search(stripped))


def classify_failure(
    text: str,
    *,
    process_failed: bool = False,
    model_stdout: str = "",
    platform: str | None = None,
    route_id: str | None = None,
) -> FailureReceipt:
    """Map the channel-trust classifiers to a structured FailureReceipt (the shared taxonomy across
    the review + worker planes). ADDITIVE: the dispatch verdict path (cc-pr-review-dispatch.py) still
    calls the three booleans directly and OWNS the canonical verdict; this helper applies the SAME
    priority order (quota > route > provider > UNKNOWN) for telemetry and does NOT change any verdict.
    No production consumer calls this helper yet, so there is no live parity to enforce; behavioral
    parity against the dispatch path is pinned by the worker-path slice that makes dispatch consume
    this helper (capability-adapter-worker-path-classify-failure). Defaults to UNKNOWN (no
    auto-degrade) when no classifier fires."""

    if is_quota_wall(text, process_failed=process_failed, model_stdout=model_stdout):
        code = FailureCode.QUOTA_EXHAUSTION
    elif is_reviewer_route_unavailable(
        text, process_failed=process_failed, model_stdout=model_stdout
    ):
        code = FailureCode.ROUTE_UNAVAILABLE
    elif is_provider_outage(text, process_failed=process_failed, model_stdout=model_stdout):
        code = FailureCode.PROVIDER_OUTAGE
    else:
        code = FailureCode.UNKNOWN
    return FailureReceipt(code=code, raw_signal=text, platform=platform, route_id=route_id)


def _parse_iso_datetime(value: Any) -> datetime:
    return datetime.fromisoformat(str(value))


def _coerce_datetime(value: datetime | str | None, *, reference: datetime) -> datetime:
    if value is None:
        return datetime.now(reference.tzinfo) if reference.tzinfo else datetime.now()
    parsed = value if isinstance(value, datetime) else _parse_iso_datetime(value)
    if reference.tzinfo and parsed.tzinfo is None:
        return parsed.replace(tzinfo=reference.tzinfo)
    if parsed.tzinfo and reference.tzinfo is None:
        return parsed.replace(tzinfo=None)
    return parsed


def _seconds_between(later: datetime, earlier: datetime) -> float:
    if later.tzinfo and earlier.tzinfo is None:
        earlier = earlier.replace(tzinfo=later.tzinfo)
    elif earlier.tzinfo and later.tzinfo is None:
        later = later.replace(tzinfo=earlier.tzinfo)
    return (later - earlier).total_seconds()


def _witness_window(entry: Any) -> tuple[datetime | None, datetime | None]:
    """The ``(outage_started_at, observed_at)`` window for a family-outage witness entry.

    Dict entries (current format) carry a stable ``outage_started_at`` (set when the
    sustained outage began, never advanced) alongside the moving ``observed_at`` (latest
    observation, pushed forward each run). Legacy str entries (the old single-timestamp
    format) yield ``(ts, ts)`` — start == observed — so they preserve the prior
    one-directional behaviour (constituted must be ``>=`` the timestamp). Either value may
    be ``None`` (malformed/absent), which the caller treats as unwitnessed.
    """
    if isinstance(entry, dict):
        started_raw = entry.get("outage_started_at")
        observed_raw = entry.get("observed_at", started_raw)
        return _parse_iso_datetime(started_raw), _parse_iso_datetime(observed_raw)
    if isinstance(entry, str):
        dt = _parse_iso_datetime(entry)
        return dt, dt
    return None, None


GATE_KILLSWITCH_ENV = "HAPAX_REVIEW_TEAM_GATE_OFF"
CHECKLIST_ITEM_RE = re.compile(r"^- \[ \] (?P<slug>[a-z0-9-]+):", re.MULTILINE)
CHECKLIST_VALUES = frozenset({"pass", "finding", "na"})
TRUTHY_ENV_VALUES = frozenset({"1", "true", "yes", "on"})


def gate_disabled() -> bool:
    """True when the operator killswitch disables the review-team gate."""

    return os.environ.get(GATE_KILLSWITCH_ENV, "").strip().lower() in TRUTHY_ENV_VALUES


def load_lens_registry(path: Path | None = None) -> dict[str, Any]:
    registry_path = path or DEFAULT_REGISTRY_PATH
    loaded = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or loaded.get("registry_schema") != 1:
        raise ValueError(f"lens registry at {registry_path} is not a registry_schema:1 mapping")
    return loaded


def _matches(path: str, pattern: str) -> bool:
    """Glob match per registry semantics: ``dir/**`` is a prefix, else fnmatch."""

    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return path == prefix or path.startswith(prefix + "/")
    return fnmatch.fnmatch(path, pattern)


def lenses_for_files(changed_files: Sequence[str], registry: Mapping[str, Any]) -> tuple[str, ...]:
    """Mandatory lenses for a diff: always-on + matched surfaces (+ tests-only)."""

    files = [f.strip() for f in changed_files if f and f.strip()]
    ordered: list[str] = list(registry["always_on_lenses"])
    for row in registry["surface_lenses"]:
        if any(_matches(f, glob) for f in files for glob in row["globs"]):
            ordered.extend(row["lenses"])
    if files and all(_matches(f, "tests/**") for f in files):
        ordered.extend(registry["tests_only_lenses"])
    seen: set[str] = set()
    out: list[str] = []
    for lens in ordered:
        if lens not in seen:
            seen.add(lens)
            out.append(lens)
    return tuple(out)


def team_class_for(
    frontmatter: Mapping[str, Any],
    changed_files: Sequence[str],
    registry: Mapping[str, Any],
) -> str:
    """Tactical sizing class. T1 surfaces beat docs-only (fail toward more review)."""

    files = [f.strip() for f in changed_files if f and f.strip()]
    risk = str(frontmatter.get("risk_tier") or "").strip().upper()
    if risk == "T1" or any(
        _matches(f, glob) for f in files for glob in registry["t1_surface_globs"]
    ):
        return "t1_critical"
    docs_globs = registry["docs_only_globs"]
    docs_only = bool(files) and all(any(_matches(f, g) for g in docs_globs) for f in files)
    if risk == "T3" or docs_only:
        return "t3_docs"
    return "t2_standard"


def strongest_team_class(classes: Sequence[str]) -> str:
    """Return the strongest known team class from a non-empty sequence."""

    if not classes:
        raise ValueError("at least one team class is required")
    return max(classes, key=lambda item: TEAM_CLASS_RANK.get(item, -1))


def writer_family_for_lane(lane: str | None, registry: Mapping[str, Any]) -> str:
    """Model family of the authoring lane (exact map, then prefixes, then default)."""

    lane_families = registry["lane_families"]
    lane_norm = (lane or "").strip().lower()
    if not lane_norm:
        return lane_families["default"]
    if lane_norm in set(lane_families.get("retired") or []):
        raise ValueError(f"retired authoring lane is not admissible: {lane_norm}")
    exact = lane_families.get("exact") or {}
    if lane_norm in exact:
        return exact[lane_norm]
    for prefix, family in (lane_families.get("prefixes") or {}).items():
        if lane_norm.startswith(prefix):
            return family
    return lane_families["default"]


@dataclass(frozen=True)
class Seat:
    id: str
    family: str


@dataclass(frozen=True)
class Constitution:
    team_class: str
    quorum_required: int
    seats: tuple[Seat, ...]
    notes: tuple[str, ...]


def constitute_team(
    team_class: str,
    writer_family: str,
    registry: Mapping[str, Any],
    *,
    pr_number: int,
    available_families: Sequence[str] | None = None,
    outage_families: frozenset[str] | set[str] = frozenset(),
) -> Constitution:
    """Constitute the review team for a class — deterministic, fail-closed.

    Rules (spec §2/§3): t3 = 2 seats / 2 families; t2 = 3 seats, >=2 families;
    t1 = 4-5 seats, ALL roster families or :class:`ValueError`. The writer's
    family never holds the majority alone (cap = ``size // 2``); non-writer
    families seat first, rotated by ``pr_number`` for fairness.

    DEGRADATION RULE (n-tier symmetry principal; postmortem 2026-06-12,
    failure class #1): when a roster family is out on an OBSERVED quota wall
    (``outage_families``), t1's require_all_families does not seal the gate —
    the team degrades to t2 composition from the available families, and the
    constitution notes carry ``degraded_family_outage:<family>`` +
    ``post_recovery_rereview_required`` so the dossier, admission, and the
    degraded-merges ledger all see the degradation. A family missing for any
    OTHER reason (config error) still raises — only evidenced outages degrade.
    """

    sizing = registry["sizing"][team_class]
    roster = [entry["family"] for entry in registry["families"]]
    if available_families is None:
        available = list(roster)
    else:
        wanted = {f for f in available_families}
        available = [f for f in roster if f in wanted]
    out = [f for f in available if f in outage_families]
    available = [f for f in available if f not in outage_families]
    notes = [f"family_unavailable:{f}" for f in roster if f not in available and f not in out]
    degraded: list[str] = []

    if team_class == "t1_critical":
        size = int(sizing["team_size_min"])
        if sizing.get("require_all_families"):
            missing = [f for f in roster if f not in available]
            if missing and all(f in outage_families for f in missing):
                degraded = sorted(missing)
                sizing = registry["sizing"]["t2_standard"]
                size = int(sizing["team_size"])
                notes.extend(f"degraded_family_outage:{f}" for f in degraded)
                notes.append("degraded_to:t2_standard")
                notes.append("post_recovery_rereview_required")
            elif missing:
                raise ValueError(
                    "t1_critical requires every model family on the team; "
                    f"unavailable family: {','.join(missing)}"
                )
    else:
        size = int(sizing["team_size"])
        if out:
            # t2/t3 keep their own sizing — the walled family simply is not
            # seated; the markers still ride so synthesis/admission validate
            # by the shrunken roster and the re-review obligation is recorded
            notes.extend(f"degraded_family_outage:{f}" for f in sorted(out))
            notes.append("post_recovery_rereview_required")
    min_families = int(sizing.get("min_families", 1))
    if not available:
        raise ValueError("no reviewer families available")
    if len(available) < min_families:
        raise ValueError(
            f"{team_class} requires >={min_families} model families; "
            f"only available: {','.join(available)}"
        )

    rot = pr_number % len(available)
    rotated = available[rot:] + available[:rot]
    non_writer = [f for f in rotated if f != writer_family]
    writer_cap = size // 2  # strict-majority guard: writer seats can never reach size//2 + 1

    seat_families: list[str] = []
    for family in non_writer:  # one seat per non-writer family first
        if len(seat_families) < size:
            seat_families.append(family)
    writer_seats = 0
    if writer_family in rotated and len(seat_families) < size and writer_seats < writer_cap:
        seat_families.append(writer_family)
        writer_seats += 1
    fill = 0
    while len(seat_families) < size:
        if non_writer:
            seat_families.append(non_writer[fill % len(non_writer)])
            fill += 1
        elif writer_seats < writer_cap:
            seat_families.append(writer_family)
            writer_seats += 1
        else:
            raise ValueError(
                "cannot constitute team: only the writer's own family is available "
                "and it would hold the majority alone"
            )
    if len(set(seat_families)) < min_families:
        raise ValueError(
            f"constituted team spans {len(set(seat_families))} families; "
            f"{team_class} requires >={min_families}"
        )

    counts: dict[str, int] = {}
    seats: list[Seat] = []
    for family in seat_families:
        counts[family] = counts.get(family, 0) + 1
        seats.append(Seat(id=f"{family}-{counts[family]}", family=family))
    return Constitution(
        team_class=team_class,
        quorum_required=int(sizing["quorum_accept"]),
        seats=tuple(seats),
        notes=tuple(notes),
    )


# --- Task-note + charter lookup ----------------------------------------------


def _note_frontmatter(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    try:
        parsed = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None
    return parsed if isinstance(parsed, dict) else None


def find_task_notes(
    vault_root: Path,
    *,
    pr_number: int | None = None,
    head_ref: str | None = None,
) -> tuple[tuple[Path, dict[str, Any]], ...]:
    """All cc-task notes linked to a PR: by ``pr`` field first, else by branch."""

    pr_matches: list[tuple[Path, dict[str, Any]]] = []
    branch_matches: list[tuple[Path, dict[str, Any]]] = []
    for folder in ("active", "closed"):
        root = vault_root / folder
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.md")):
            fm = _note_frontmatter(path)
            if not fm or fm.get("type") != "cc-task":
                continue
            try:
                note_pr = int(fm.get("pr")) if fm.get("pr") is not None else None
            except (TypeError, ValueError):
                note_pr = None
            if pr_number is not None and note_pr == pr_number:
                pr_matches.append((path, fm))
            elif head_ref and str(fm.get("branch") or "") == head_ref:
                branch_matches.append((path, fm))
    return tuple(pr_matches or branch_matches)


def charter_text(lens: str, lens_dir: Path | None = None) -> str:
    """Full charter markdown for a lens (raises if the charter is missing)."""

    return ((lens_dir or LENS_DIR) / f"{lens}.md").read_text(encoding="utf-8")


def charter_checklist_items(lens: str, lens_dir: Path | None = None) -> tuple[str, ...]:
    """Checklist item slugs declared by a lens charter."""

    return tuple(CHECKLIST_ITEM_RE.findall(charter_text(lens, lens_dir)))


# --- Dossier synthesis --------------------------------------------------------


def _unresolved_criticals(reviews: Sequence[Mapping[str, Any]]) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for review in reviews:
        for finding in review.get("findings") or []:
            if not isinstance(finding, Mapping):
                continue
            if str(finding.get("severity", "")).lower() == "critical":
                out.append((str(review.get("id")), dict(finding)))
    return out


# --- The go-gate: fail-closed literal-defect verifier -------------------------
# A reviewer's "syntax error / compile failure / corruption at line N" critical is INVALIDATED
# (does not block quorum) when the actual file at head refutes it — verified deterministically,
# out-of-model (ast.parse for Python; file/line existence otherwise). This fail-closes against
# reviewer confabulation (e.g. a phantom "corrupted decorators at line 690" on a 267-line file that
# parses clean) while never touching non-literal-defect criticals. Scoped exactly as the prior
# prompt-only evidence rule (#4132) tried, but enforced by code, not in-model suasion.

# Only the NARROW syntax/compile claim class is verifiable (ast.parse can refute it). Semantic
# claims ('corrupt state', 'malformed request', off-by-one) are NEVER matched and never invalidated
# — the go-gate must not suppress a real finding (claude-1, #4136 review v2).
_SYNTAX_COMPILE_RE = re.compile(
    r"syntax\s*error|syntaxerror|invalid\s+syntax|fails?\s+to\s+(?:compile|parse)|"
    r"won'?t\s+(?:compile|parse)|will\s+not\s+(?:compile|parse)|"
    r"does\s*n'?t\s+(?:compile|parse)|cannot\s+be\s+parsed|"
    r"un(?:parse|parseable|parsable)|compile\s+(?:error|failure)|unterminated|"
    r"indentation\s+error|missing\s+(?:colon|paren|parenthes|brace|bracket)",
    re.IGNORECASE,
)
_NEGATED_SYNTAX_COMPILE_RE = re.compile(
    r"\b(?:not|isn'?t|is\s+not)\s+(?:a\s+)?"
    r"(?:syntax\s*error|parse\s+(?:failure|error)|compile\s+(?:failure|error))",
    re.IGNORECASE,
)
_NAMESPACE_CORRUPTION_RE = re.compile(
    r"(?:namespace|prefix|@prefix).*(?:corrupt|replac|invalid|violat)|"
    r"(?:corrupt|replac|invalid|violat).*(?:namespace|prefix|@prefix)",
    re.IGNORECASE,
)
_BACKTICK_LITERAL_RE = re.compile(r"`([^`\n]{3,200})`")

#: Killswitch — set to "1" to disable the go-gate (every critical blocks; the pre-go-gate behaviour).
_GO_GATE_OFF_ENV = "HAPAX_REVIEW_GO_GATE_OFF"


def _is_syntax_compile_claim(finding: Mapping[str, Any]) -> bool:
    """True iff the critical asserts a SYNTAX/COMPILE defect — the ONLY class the verifier may
    refute. Semantic claims ('corrupt state', off-by-one) are never matched, so never invalidated."""
    text = f"{finding.get('title', '')}\n{finding.get('detail', '')}"
    if _NEGATED_SYNTAX_COMPILE_RE.search(text):
        return False
    return bool(_SYNTAX_COMPILE_RE.search(text))


def _is_namespace_corruption_claim(finding: Mapping[str, Any]) -> bool:
    text = f"{finding.get('title', '')} {finding.get('detail', '')}"
    return bool(_NAMESPACE_CORRUPTION_RE.search(text))


def _is_path_like_at_literal(literal: str) -> bool:
    token = (literal.strip().split() or [""])[0]
    return token.startswith("@") and "/" in token and token != "@prefix"


def _line_literal_claim_refuted(finding: Mapping[str, Any], source: str) -> bool:
    try:
        line = int(finding.get("line") or 0)
    except (TypeError, ValueError):
        return False
    lines = source.splitlines()
    if line <= 0 or line > len(lines):
        return False
    current_line = lines[line - 1]
    text = f"{finding.get('title', '')}\n{finding.get('detail', '')}"
    suspect_literals = [
        literal.strip()
        for literal in _BACKTICK_LITERAL_RE.findall(text)
        if _is_path_like_at_literal(literal)
    ]
    return bool(suspect_literals) and all(
        literal not in current_line for literal in suspect_literals
    )


def _rdf_parse_format(path: Path) -> str | None:
    if path.suffix == ".trig":
        return "trig"
    if path.suffix == ".ttl":
        return "turtle"
    return None


def _rdf_parses_clean(path: Path, parse_format: str) -> bool:
    try:
        from rdflib import Dataset, Graph

        graph = Dataset() if parse_format == "trig" else Graph()
        graph.parse(path, format=parse_format)
    except Exception:  # noqa: BLE001 - rdflib raises parser-specific exception types.
        return False
    return True


def _discover_repo_root() -> Path | None:
    cur = Path.cwd()
    for d in (cur, *cur.parents):
        if (d / ".git").exists():
            return d
    return None


def _repo_root_for_path(path: Path) -> Path | None:
    cur = path if path.is_dir() else path.parent
    for d in (cur, *cur.parents):
        if (d / ".git").exists():
            return d
    return None


def _frontmatter_repo_root(frontmatter: Mapping[str, Any] | None, head_sha: str) -> Path | None:
    if frontmatter is None:
        return None
    raw_refs = frontmatter.get("mutation_scope_refs") or frontmatter.get("paths") or ()
    if not isinstance(raw_refs, Sequence) or isinstance(raw_refs, str):
        raw_refs = (raw_refs,)
    seen: set[Path] = set()
    for raw in raw_refs:
        text = str(raw or "").strip()
        if not text or not (text.startswith("/") or text.startswith("~")):
            continue
        root = _repo_root_for_path(Path(text).expanduser())
        if root is None or root in seen:
            continue
        seen.add(root)
        if _repo_head_matches(root, head_sha):
            return root
    return None


def _repo_head_matches(repo_root: Path, head_sha: str) -> bool:
    """True iff ``repo_root``'s git HEAD is ``head_sha`` — i.e. the local checkout IS the reviewed PR
    at the reviewed commit. Guards against binding the verifier to the wrong checkout (claude-1)."""
    want = str(head_sha or "").strip().lower()
    if not want:
        return False
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    got = out.stdout.strip().lower()
    return bool(got) and (got == want or got.startswith(want) or want.startswith(got))


def verify_literal_defect_critical(finding: Mapping[str, Any], repo_root: Path) -> bool:
    """Return True if the critical STANDS; False ONLY for a DEFINITIVELY-refuted syntax/compile
    phantom. A critical is invalidated only when it is a SYNTAX/COMPILE claim AND the cited Python
    file ``ast.parse``-s clean. Every other case — not a syntax/compile claim (ALL semantic
    criticals), a missing/unreadable/non-Python file — KEEPS the critical. Uncertainty never
    suppresses."""
    syntax_claim = _is_syntax_compile_claim(finding)
    namespace_claim = _is_namespace_corruption_claim(finding)
    if not syntax_claim and not namespace_claim:
        return (
            True  # not a syntax/compile claim — never invalidate (every semantic critical is safe)
        )
    rel = str(finding.get("file") or "").strip()
    if not rel:
        return True  # ungrounded — cannot DISPROVE, keep
    path = repo_root / rel
    if not path.is_file():
        return True  # cites a file not in the tree — cannot verify, keep
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return True  # unreadable — cannot verify, keep
    rdf_format = _rdf_parse_format(path)
    if rdf_format is not None:
        parses_clean = _rdf_parses_clean(path, rdf_format)
        if syntax_claim:
            return not parses_clean
        return not (
            namespace_claim and parses_clean and _line_literal_claim_refuted(finding, source)
        )
    if namespace_claim and _line_literal_claim_refuted(finding, source):
        return False
    if path.suffix != ".py":
        return True  # cannot verify this syntax claim class — keep (conservative)
    if not syntax_claim:
        return True
    try:
        ast.parse(source)
    except SyntaxError:
        return True  # really does not parse — the claim stands
    return False  # parses clean — the syntax/compile claim is a phantom


def _blocking_criticals(
    reviews: Sequence[Mapping[str, Any]],
    repo_root: Path | None,
    head_sha: str | None = None,
) -> tuple[list[tuple[str, dict]], list[tuple[str, dict]]]:
    """Partition unresolved criticals into (blocking, phantom). ``repo_root=None`` discovers the repo
    from cwd. The verifier runs ONLY when the checkout is confirmed to be the reviewed commit
    (``head_sha`` matches local HEAD, when given); otherwise — no repo, killswitch, or a wrong/unknown
    checkout — every critical blocks (the safe, pre-go-gate behaviour)."""
    criticals = _unresolved_criticals(reviews)
    if os.environ.get(_GO_GATE_OFF_ENV) == "1":
        return criticals, []  # killswitch: every critical blocks (pre-go-gate behaviour)
    root = repo_root if repo_root is not None else _discover_repo_root()
    if root is None:
        return criticals, []
    if not head_sha or not _repo_head_matches(root, head_sha):
        return criticals, []  # no commit to bind to, or wrong checkout -> do not verify (keep all)
    blocking: list[tuple[str, dict]] = []
    phantom: list[tuple[str, dict]] = []
    for reviewer_id, finding in criticals:
        target = blocking if verify_literal_defect_critical(finding, root) else phantom
        target.append((reviewer_id, finding))
    return blocking, phantom


def _finding_key(reviewer_id: str, finding: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        reviewer_id,
        str(finding.get("file") or ""),
        str(finding.get("line") or ""),
        str(finding.get("title") or ""),
        str(finding.get("lens") or ""),
    )


def _reviews_with_phantom_resolutions(
    reviews: Sequence[Mapping[str, Any]], phantom_criticals: Sequence[tuple[str, dict]]
) -> list[dict[str, Any]]:
    phantom_keys = {
        _finding_key(reviewer_id, finding) for reviewer_id, finding in phantom_criticals
    }
    out: list[dict[str, Any]] = []
    for review in reviews:
        reviewer_id = str(review.get("id"))
        record = dict(review)
        findings: list[Any] = []
        for finding in review.get("findings") or []:
            if not isinstance(finding, Mapping):
                findings.append(finding)
                continue
            finding_record = dict(finding)
            if _finding_key(reviewer_id, finding_record) in phantom_keys:
                finding_record["resolved"] = True
                finding_record["resolution_source"] = "review-go-gate"
                finding_record["resolution_detail"] = (
                    "literal-defect critical refuted by the file at head"
                )
            findings.append(finding_record)
        record["findings"] = findings
        out.append(record)
    return out


def _reviews_for_quorum(
    reviews: Sequence[Mapping[str, Any]],
    blocking_criticals: Sequence[tuple[str, dict]],
    phantom_criticals: Sequence[tuple[str, dict]],
) -> list[dict[str, Any]]:
    blocking_keys = {
        _finding_key(reviewer_id, finding) for reviewer_id, finding in blocking_criticals
    }
    phantom_keys = {
        _finding_key(reviewer_id, finding) for reviewer_id, finding in phantom_criticals
    }
    out: list[dict[str, Any]] = []
    for review in reviews:
        record = dict(review)
        if str(review.get("verdict", "")).lower() == "block":
            reviewer_id = str(review.get("id"))
            critical_keys = {
                _finding_key(reviewer_id, finding)
                for finding in review.get("findings") or []
                if isinstance(finding, Mapping)
                and str(finding.get("severity", "")).lower() == "critical"
            }
            if (
                critical_keys
                and not (critical_keys & blocking_keys)
                and critical_keys <= phantom_keys
            ):
                record["verdict"] = "accept-with-findings"
                record["raw_verdict"] = "block"
                record["verdict_effective_reason"] = "all named criticals invalidated by go-gate"
        out.append(record)
    return out


def _accepting(reviews: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [r for r in reviews if str(r.get("verdict", "")).lower() in ACCEPT_VERDICTS]


def _review_checklist_blockers(
    review: Mapping[str, Any],
    lenses: Sequence[str],
    *,
    lens_dir: Path | None = None,
) -> tuple[str, ...]:
    verdict = str(review.get("verdict", "")).lower()
    if verdict not in ACCEPT_VERDICTS and verdict != "block":
        return ()

    checklist = review.get("checklist")
    reviewer = str(review.get("id") or "unknown")
    if not isinstance(checklist, Mapping):
        return (f"review_dossier_checklist_missing:{reviewer}",)

    blockers: list[str] = []
    for lens in lenses:
        lens_checklist = checklist.get(lens)
        if not isinstance(lens_checklist, Mapping):
            blockers.append(f"review_dossier_checklist_missing:{reviewer}:{lens}")
            continue
        try:
            expected = charter_checklist_items(str(lens), lens_dir=lens_dir)
        except OSError:
            blockers.append(f"review_dossier_checklist_lens_unreadable:{lens}")
            continue
        for item in expected:
            value = str(lens_checklist.get(item) or "").strip().lower()
            if value not in CHECKLIST_VALUES:
                blockers.append(f"review_dossier_checklist_item_missing:{reviewer}:{lens}:{item}")
    return tuple(blockers)


def _checklist_complete_accepts(
    reviews: Sequence[Mapping[str, Any]],
    lenses: Sequence[str],
) -> list[Mapping[str, Any]]:
    return [r for r in _accepting(reviews) if not _review_checklist_blockers(r, lenses)]


def _required_team_size(sizing: Mapping[str, Any]) -> int:
    return int(sizing.get("team_size") or sizing.get("team_size_min") or 1)


def _int_field(value: Any, field: str, blockers: list[str]) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        blockers.append(
            f"review_dossier_malformed:{field}:{value if value is not None else 'missing'}"
        )
        return None


def _task_class_floor(frontmatter: Mapping[str, Any] | None) -> str | None:
    if frontmatter is None:
        return None
    risk = str(frontmatter.get("risk_tier") or "").strip().upper()
    if risk == "T1":
        return "t1_critical"
    return None


def synthesize_dossier(
    *,
    task_id: str,
    pr_number: int,
    head_sha: str,
    team_class: str,
    registry: Mapping[str, Any],
    reviews: Sequence[Mapping[str, Any]],
    lenses: Sequence[str],
    constituted_at: str,
    constitution_notes: Sequence[str] = (),
    writer_family: str | None = None,
    constitution_writer_family: str | None = None,
    changed_files: Sequence[str] | None = None,
    changed_file_count: int | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Reconcile blind reviews into a dossier (the synthesizer, spec §3/§5).

    Verdict ladder: any unresolved named critical -> ``blocked`` (criticals are
    resolved, not outvoted); else accepts >= quorum (t1 additionally needs >=1
    accept from EVERY roster family) -> ``quorum-accept``; else ``no-quorum``.
    Cross-family verdict splits and blocks without a named critical are
    escalated to the top of the dossier — family disagreement is signal.
    """

    sizing = registry["sizing"][team_class]
    roster = [entry["family"] for entry in registry["families"]]
    # an outage-degraded constitution judges itself by the DEGRADED rules:
    # t2 sizing, roster minus the walled families (postmortem 2026-06-12 —
    # otherwise require_all_families would seal the verdict it already
    # degraded the constitution for)
    degraded_outage = sorted(
        n.split(":", 1)[1]
        for n in constitution_notes
        if str(n).startswith("degraded_family_outage:")
    )
    if degraded_outage:
        # roster shrinks for ANY outage-degraded class; the t1->t2 sizing
        # swap applies only when the constitution actually degraded sizing
        # (round-3 review finding: t2/t3 outage dossiers must not be judged
        # by rules their class never had)
        roster = [f for f in roster if f not in degraded_outage]
        if any(str(n) == "degraded_to:t2_standard" for n in constitution_notes):
            sizing = registry["sizing"]["t2_standard"]
    block_reviews = [r for r in reviews if str(r.get("verdict", "")).lower() == "block"]
    criticals, phantom_criticals = _blocking_criticals(reviews, repo_root, head_sha=head_sha)
    quorum_reviews = _reviews_for_quorum(reviews, criticals, phantom_criticals)
    accepts = _checklist_complete_accepts(quorum_reviews, lenses)
    accept_families = {str(r.get("family")) for r in accepts}
    scoped_files = None if changed_files is None else [str(f) for f in changed_files]
    if changed_files is not None and changed_file_count is None:
        changed_file_count = len(scoped_files)

    escalations: list[dict[str, Any]] = []
    for reviewer_id, finding in criticals:
        escalations.append(
            {
                "kind": "unresolved-critical",
                "reviewer": reviewer_id,
                "title": finding.get("title"),
                "file": finding.get("file"),
                "line": finding.get("line"),
                "lens": finding.get("lens"),
            }
        )
    for reviewer_id, finding in phantom_criticals:
        escalations.append(
            {
                "kind": "invalidated-phantom-critical",
                "reviewer": reviewer_id,
                "title": finding.get("title"),
                "file": finding.get("file"),
                "line": finding.get("line"),
                "lens": finding.get("lens"),
                "detail": "literal-defect critical refuted by the file at head (fail-closed go-gate)",
            }
        )
    if accepts and block_reviews:
        blocking_families = {str(r.get("family")) for r in block_reviews}
        if blocking_families - accept_families or accept_families - blocking_families:
            for review in block_reviews:
                escalations.append(
                    {
                        "kind": "cross-family-split",
                        "reviewer": str(review.get("id")),
                        "family": str(review.get("family")),
                        "detail": "family verdicts split — disagreement is signal, reconcile first",
                    }
                )
    for review in block_reviews:
        named = [
            f
            for f in review.get("findings") or []
            if isinstance(f, Mapping) and str(f.get("severity", "")).lower() == "critical"
        ]
        if not named:
            escalations.append(
                {
                    "kind": "block-without-named-critical",
                    "reviewer": str(review.get("id")),
                    "family": str(review.get("family")),
                    "detail": "BLOCK verdict without a named critical finding does not block on its own",
                }
            )
    for review in reviews:
        for blocker in _review_checklist_blockers(review, lenses):
            escalations.append(
                {
                    "kind": "checklist-incomplete",
                    "reviewer": str(review.get("id")),
                    "family": str(review.get("family")),
                    "detail": blocker,
                }
            )

    if criticals and sizing.get("block_on_named_critical", True):
        verdict = "blocked"
    else:
        quorum_met = len(accepts) >= int(sizing["quorum_accept"])
        min_families = int(sizing.get("min_families", 1))
        if quorum_met and len(accept_families) < min_families:
            quorum_met = False
        if quorum_met and sizing.get("require_all_families"):
            quorum_met = set(roster) <= accept_families
        verdict = QUORUM_ACCEPT if quorum_met else "no-quorum"

    return {
        "dossier_schema": 1,
        "task_id": task_id,
        "pr": pr_number,
        "head_sha": head_sha,
        "team_class": team_class,
        "quorum_required": int(sizing["quorum_accept"]),
        "constituted_at": constituted_at,
        "registry_id": registry.get("registry_id"),
        "registry_declared_at": registry.get("declared_at"),
        "writer_family": writer_family,
        "constitution_writer_family": constitution_writer_family or writer_family,
        "changed_file_count": changed_file_count,
        "changed_files": scoped_files,
        "constitution_notes": list(constitution_notes),
        "route_admission_required": any("route_admissions" in r for r in reviews),
        "degraded_family_outage": degraded_outage,
        "post_recovery_rereview_required": bool(degraded_outage),
        "lenses": list(lenses),
        "reviewers": _reviews_with_phantom_resolutions(reviews, phantom_criticals),
        "escalations": escalations,
        "accept_count": len(accepts),
        "review_team_verdict": verdict,
    }


# --- Admission gate (consumed by scripts/cc-pr-autoqueue.py) ------------------


def review_dossier_path(note_path: Path, task_id: str) -> Path:
    """Canonical dossier location: ``<task_id>.review-dossier.yaml`` beside the note."""

    return note_path.parent / f"{task_id}{REVIEW_DOSSIER_SUFFIX}"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _route_decision_ledger_record(
    ledger_path: Any,
    decision_id: str,
) -> tuple[Mapping[str, Any] | None, str | None]:
    ledger_ref = str(ledger_path or "").strip()
    if not ledger_ref:
        return None, "ledger_missing"
    path = Path(ledger_ref).expanduser()
    try:
        resolved_path = path.resolve(strict=False)
        trusted_path = ROUTE_DECISION_LEDGER_PATH.expanduser().resolve(strict=False)
    except OSError:
        return None, "ledger_unreadable"
    if resolved_path != trusted_path:
        return None, "ledger_untrusted"
    if not path.is_file():
        return None, "ledger_unreadable"
    try:
        with path.open("r", encoding="utf-8") as ledger:
            for line in ledger:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    return None, "ledger_malformed"
                if (
                    isinstance(record, Mapping)
                    and str(record.get("decision_id") or "") == decision_id
                ):
                    return record, None
    except OSError:
        return None, "ledger_unreadable"
    return None, "decision_missing"


def _route_decision_ledger_blockers(
    admission: Mapping[str, Any],
    *,
    reviewer_id: str,
    prefix: str,
) -> list[str]:
    decision_id = str(admission.get("route_decision_id") or "").strip()
    if not decision_id:
        return []
    record, error = _route_decision_ledger_record(
        admission.get("route_decision_ledger"),
        decision_id,
    )
    if record is None:
        return [f"review_dossier_route_decision_{error}:{prefix}:{decision_id}"]

    expected = {
        "task_id": str(admission.get("task_id") or ""),
        "lane": f"review-seat-{reviewer_id}",
        "route_id": str(admission.get("route_id") or ""),
        "action": str(admission.get("route_policy_action") or ""),
        "authority_case": str(admission.get("authority_case") or ""),
    }
    blockers: list[str] = []
    for field, expected_value in expected.items():
        if str(record.get(field) or "") != expected_value:
            blockers.append(f"review_dossier_route_decision_mismatch:{prefix}:{field}")

    admission_authority_case = str(admission.get("route_policy_authority_case") or "")
    if (
        admission_authority_case
        and str(record.get("authority_case") or "") != admission_authority_case
    ):
        blockers.append(
            f"review_dossier_route_decision_mismatch:{prefix}:route_policy_authority_case"
        )

    bool_fields = {
        "launch_allowed": admission.get("route_policy_launch_allowed"),
        "route_policy_green": admission.get("route_policy_green"),
        "registry_freshness_green": admission.get("route_policy_registry_freshness_green"),
        "quota_freshness_green": admission.get("route_policy_quota_freshness_green"),
        "resource_freshness_green": admission.get("route_policy_resource_freshness_green"),
    }
    for field, expected_value in bool_fields.items():
        if record.get(field) is not expected_value:
            blockers.append(f"review_dossier_route_decision_mismatch:{prefix}:{field}")

    list_fields = {
        "quota_evidence_refs": admission.get("route_policy_quota_evidence_refs"),
        "resource_state_refs": admission.get("route_policy_resource_state_refs"),
    }
    for field, expected_value in list_fields.items():
        if _string_list(record.get(field)) != _string_list(expected_value):
            blockers.append(f"review_dossier_route_decision_mismatch:{prefix}:{field}")
    admission_demand_ref = _string_mapping(admission.get("route_policy_demand_vector_ref"))
    record_demand_ref = _string_mapping(record.get("demand_vector_ref"))
    if not admission_demand_ref or record_demand_ref != admission_demand_ref:
        blockers.append(f"review_dossier_route_decision_mismatch:{prefix}:demand_vector_ref")
    return blockers


def _route_admission_blockers(
    review: Mapping[str, Any],
    *,
    task_id: str,
    registry: Mapping[str, Any],
    frontmatter: Mapping[str, Any] | None = None,
) -> list[str]:
    reviewer_id = str(review.get("id") or "missing")
    reviewer_family = str(review.get("family") or "missing")
    expected_authority_case = ""
    expected_parent_spec = ""
    if isinstance(frontmatter, Mapping):
        expected_authority_case = str(frontmatter.get("authority_case") or "").strip()
        expected_parent_spec = str(frontmatter.get("parent_spec") or "").strip()
    expected_route_ids = {
        str(entry.get("family")): str(entry.get("route_id") or "")
        for entry in (registry.get("families") or [])
        if isinstance(entry, Mapping)
    }
    expected_route_id = expected_route_ids.get(reviewer_family, "")
    admissions = review.get("route_admissions")
    if not isinstance(admissions, list) or not admissions:
        return [f"review_dossier_route_admission_missing:{reviewer_id}"]

    matching = [
        admission
        for admission in admissions
        if isinstance(admission, Mapping) and str(admission.get("task_id") or "") == task_id
    ]
    if not matching:
        return [f"review_dossier_route_admission_task_missing:{reviewer_id}:{task_id}"]

    blockers: list[str] = []
    if not expected_route_id:
        blockers.append(f"review_dossier_route_registry_missing:{reviewer_id}:{reviewer_family}")
    for admission in matching:
        route_id = str(admission.get("route_id") or "missing")
        prefix = f"{reviewer_id}:{route_id}"
        admission_seat_id = str(admission.get("seat_id") or "missing")
        if admission_seat_id != reviewer_id:
            blockers.append(
                f"review_dossier_route_admission_seat_mismatch:{reviewer_id}:{admission_seat_id}"
            )
        admission_family = str(admission.get("family") or "missing")
        if admission_family != reviewer_family:
            blockers.append(
                f"review_dossier_route_admission_family_mismatch:{reviewer_id}:"
                f"{admission_family}!={reviewer_family}"
            )
        admission_authority_case = str(admission.get("authority_case") or "").strip()
        if not expected_authority_case:
            blockers.append(f"review_dossier_route_admission_authority_case_missing:{prefix}")
        elif admission_authority_case != expected_authority_case:
            blockers.append(
                "review_dossier_route_admission_authority_case_mismatch:"
                f"{prefix}:{admission_authority_case or 'missing'}!={expected_authority_case}"
            )
        admission_parent_spec = str(admission.get("parent_spec") or "").strip()
        if not expected_parent_spec:
            blockers.append(f"review_dossier_route_admission_parent_spec_missing:{prefix}")
        elif admission_parent_spec != expected_parent_spec:
            blockers.append(
                "review_dossier_route_admission_parent_spec_mismatch:"
                f"{prefix}:{admission_parent_spec or 'missing'}!={expected_parent_spec}"
            )
        if expected_route_id and route_id != expected_route_id:
            blockers.append(
                f"review_dossier_route_id_mismatch:{reviewer_id}:{route_id}!={expected_route_id}"
            )
        if admission.get("admitted") is not True:
            reasons = [
                str(reason)
                for reason in (admission.get("blocked_reasons") or [])
                if str(reason).strip()
            ]
            detail = ",".join(reasons) if reasons else "unknown"
            blockers.append(f"review_dossier_route_admission_not_admitted:{prefix}:{detail}")
        if admission.get("route_policy_action") != "launch":
            blockers.append(f"review_dossier_route_policy_not_launch:{prefix}")
        if admission.get("route_policy_green") is not True:
            blockers.append(f"review_dossier_route_policy_not_green:{prefix}")
        if admission.get("route_policy_registry_freshness_green") is not True:
            blockers.append(f"review_dossier_route_registry_not_fresh:{prefix}")
        quota_refs = admission.get("route_policy_quota_evidence_refs")
        if admission.get("route_policy_quota_freshness_green") is not True:
            blockers.append(f"review_dossier_route_quota_not_fresh:{prefix}")
        if not isinstance(quota_refs, list) or not quota_refs:
            blockers.append(f"review_dossier_route_quota_evidence_missing:{prefix}")
        resource_refs = admission.get("route_policy_resource_state_refs")
        if admission.get("route_policy_resource_freshness_green") is not True:
            blockers.append(f"review_dossier_route_resource_not_fresh:{prefix}")
        if not isinstance(resource_refs, list) or not resource_refs:
            blockers.append(f"review_dossier_route_resource_evidence_missing:{prefix}")
        if not str(admission.get("route_decision_id") or "").strip():
            blockers.append(f"review_dossier_route_decision_missing:{prefix}")
        blockers.extend(
            _route_decision_ledger_blockers(admission, reviewer_id=reviewer_id, prefix=prefix)
        )
    return blockers


def _frontmatter_requires_route_admissions(frontmatter: Mapping[str, Any] | None) -> bool:
    if not isinstance(frontmatter, Mapping):
        return False
    nested = frontmatter.get("route_metadata")
    nested_metadata = nested if isinstance(nested, Mapping) else {}
    return bool(
        frontmatter.get("route_metadata_schema")
        or nested_metadata.get("route_metadata_schema")
        or (frontmatter.get("authority_case") and frontmatter.get("parent_spec"))
    )


def _dossier_requires_route_admissions(
    dossier: Mapping[str, Any],
    frontmatter: Mapping[str, Any] | None,
) -> bool:
    return dossier.get(
        "route_admission_required"
    ) is True or _frontmatter_requires_route_admissions(frontmatter)


def _dossier_validity_blockers(
    dossier: Mapping[str, Any],
    *,
    pr_head_sha: str | None,
    registry: Mapping[str, Any],
    frontmatter: Mapping[str, Any] | None = None,
    expected_task_id: str | None = None,
    pr_number: int | None = None,
    changed_files: Sequence[str] | None = None,
    changed_file_count: int | None = None,
    outage_state_path: Path | None = None,
    admission_time: datetime | str | None = None,
) -> tuple[str, ...]:
    blockers: list[str] = []
    scoped_files = (
        tuple(f.strip() for f in changed_files if f and f.strip())
        if changed_files is not None
        else None
    )

    if expected_task_id is not None:
        dossier_task_id = str(dossier.get("task_id") or "").strip()
        if dossier_task_id != expected_task_id:
            blockers.append(
                f"review_dossier_task_id_mismatch:{dossier_task_id or 'missing'}!={expected_task_id}"
            )
    if pr_number is not None:
        dossier_pr = _int_field(dossier.get("pr"), "pr", blockers)
        if dossier_pr is not None and dossier_pr != pr_number:
            blockers.append(f"review_dossier_pr_mismatch:{dossier_pr}!={pr_number}")

    dossier_sha = str(dossier.get("head_sha") or "")
    if not dossier_sha:
        blockers.append("review_dossier_malformed:missing_head_sha")
    elif not pr_head_sha:
        blockers.append("review_dossier_current_head_unknown")
    elif dossier_sha != pr_head_sha:
        blockers.append(f"review_dossier_stale_head:dossier={dossier_sha[:8]},pr={pr_head_sha[:8]}")

    team_class = str(dossier.get("team_class") or "")
    sizing = (registry.get("sizing") or {}).get(team_class)
    if not isinstance(sizing, Mapping):
        blockers.append(f"review_dossier_malformed:unknown_team_class:{team_class or 'missing'}")
        return tuple(blockers)

    # DEGRADATION (PR #4110 round-2 finding: the admission gate re-sealed
    # what the constitution degraded): a dossier whose constitution recorded
    # an evidenced family outage is validated by the DEGRADED rules — t2
    # sizing, roster minus the walled families. Integrity here: the notes and
    # the explicit fields must agree and the walled family must have seated
    # no reviewers; the post-recovery re-review obligation rides the
    # degraded-merges ledger, not this gate.
    _notes = [str(n) for n in (dossier.get("constitution_notes") or [])]
    _note_out = sorted(
        n.split(":", 1)[1] for n in _notes if n.startswith("degraded_family_outage:")
    )
    _field_out = sorted(str(f) for f in (dossier.get("degraded_family_outage") or []))
    degraded_outage: list[str] = []
    if _note_out or _field_out:
        # consistency: notes and fields agree + the re-review flag is set.
        # The t1->t2 sizing marker is only demanded where the class actually
        # degraded sizing — t2/t3 outage dossiers keep their own sizing
        # (round-3 review finding: the first cut of this check sealed every
        # t2/t3 review conducted during an outage).
        sizing_degraded = "degraded_to:t2_standard" in _notes
        if (
            _note_out != _field_out
            or not dossier.get("post_recovery_rereview_required")
            or (sizing_degraded and team_class != "t1_critical")
            or (team_class == "t1_critical" and not sizing_degraded)
        ):
            blockers.append("review_dossier_degradation_flags_inconsistent")
            return tuple(blockers)
        degraded_outage = _note_out
        # a degraded family must be a REAL roster family (round-5 finding:
        # a nonsense family name in the markers + witness state would buy a
        # t1->t2 downgrade while leaving the actual roster untouched)
        _full_roster = {str(entry["family"]) for entry in registry["families"]}
        _unknown_degraded = sorted(set(degraded_outage) - _full_roster)
        if _unknown_degraded:
            blockers.append(
                "review_dossier_degradation_unknown_family:" + ",".join(_unknown_degraded)
            )
            return tuple(blockers)
        # external witness (round-4 finding: dossier-internal consistency can
        # be forged wholesale): each degraded family must appear in the
        # dispatcher's outage state with observed_at within TTL BEFORE this
        # dossier's constituted_at. Recovery clears the state entry, which
        # mechanically enforces post_recovery_rereview_required — degraded
        # dossiers stop admitting the moment the family answers again.
        witness_path = outage_state_path or FAMILY_OUTAGE_STATE
        unwitnessed = list(degraded_outage)
        try:
            witness_state = json.loads(Path(witness_path).read_text(encoding="utf-8"))
            if not isinstance(witness_state, Mapping):
                raise TypeError("family outage witness is not a mapping")
            constituted = _parse_iso_datetime(dossier.get("constituted_at"))
            admitted_at = _coerce_datetime(admission_time, reference=constituted)
            unwitnessed = []
            for fam in degraded_outage:
                try:
                    started, observed = _witness_window(witness_state.get(fam))
                    if started is None or observed is None:
                        unwitnessed.append(fam)
                        continue
                    # Window model (#4246 re-design): the dossier is valid iff it was
                    # constituted AND admitted DURING the sustained outage. The STABLE
                    # outage_started_at anchors the lower bound (anti-forge: a back-dated
                    # constituted_at < outage_started_at blocks — the abs() symmetric
                    # relaxation is NOT used, per the #4246 review finding). The MOVING
                    # observed_at bounds freshness on the upper side (constituted/admitted
                    # within TTL of the latest observation) — re-stamping observed_at
                    # forward only extends the window, so a later run never un-witnesses a
                    # valid dossier (the clobber fix). Recovery clears the family entirely
                    # in update_family_outage (-> entry absent -> None -> unwitnessed),
                    # which mechanically enforces post_recovery_rereview_required.
                    if not (
                        _seconds_between(constituted, started) >= 0
                        and _seconds_between(constituted, observed) <= FAMILY_OUTAGE_TTL_S
                        and _seconds_between(admitted_at, started) >= 0
                        and _seconds_between(admitted_at, observed) <= FAMILY_OUTAGE_TTL_S
                    ):
                        unwitnessed.append(fam)
                except (TypeError, ValueError):
                    unwitnessed.append(fam)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass  # unreadable witness state -> every family stays unwitnessed
        if unwitnessed:
            blockers.append(
                "review_dossier_degradation_unwitnessed:" + ",".join(sorted(unwitnessed))
            )
            return tuple(blockers)
        if sizing_degraded:
            sizing = (registry.get("sizing") or {}).get("t2_standard")
            if not isinstance(sizing, Mapping):
                blockers.append("review_dossier_malformed:no_t2_sizing_for_degradation")
                return tuple(blockers)
    if changed_files is not None:
        if not scoped_files:
            blockers.append("review_dossier_changed_files_unknown")
        elif changed_file_count is None:
            blockers.append("review_dossier_changed_files_count_unknown")
        elif changed_file_count is not None and len(scoped_files) < changed_file_count:
            blockers.append(
                f"review_dossier_changed_files_truncated:{len(scoped_files)}/{changed_file_count}"
            )
        else:
            expected_team_class = team_class_for(frontmatter or {}, scoped_files, registry)
            if TEAM_CLASS_RANK.get(team_class, -1) < TEAM_CLASS_RANK.get(expected_team_class, -1):
                blockers.append(
                    f"review_dossier_team_class_scope_mismatch:{team_class}!={expected_team_class}"
                )
    else:
        class_floor = _task_class_floor(frontmatter)
        if class_floor is not None and team_class != class_floor:
            blockers.append(
                f"review_dossier_team_class_below_task_floor:{team_class}!={class_floor}"
            )

    reviews = dossier.get("reviewers")
    if not isinstance(reviews, list) or not all(isinstance(r, Mapping) for r in reviews):
        blockers.append("review_dossier_malformed:reviewers_not_a_list")
        return tuple(blockers)
    reviewer_ids = [str(r.get("id") or "missing") for r in reviews]
    duplicate_reviewer_ids = sorted(
        {reviewer_id for reviewer_id in reviewer_ids if reviewer_ids.count(reviewer_id) > 1}
    )
    if duplicate_reviewer_ids:
        blockers.append("review_dossier_duplicate_reviewer_id:" + ",".join(duplicate_reviewer_ids))
    roster = {entry["family"] for entry in registry["families"]}
    unknown_reviewer_families = {str(r.get("family") or "missing") for r in reviews} - roster
    if unknown_reviewer_families:
        blockers.append(
            "review_dossier_unknown_reviewer_family:" + ",".join(sorted(unknown_reviewer_families))
        )
    if degraded_outage:
        seated_walled = sorted({str(r.get("family")) for r in reviews} & set(degraded_outage))
        if seated_walled:
            blockers.append("review_dossier_degraded_family_was_seated:" + ",".join(seated_walled))
        roster = roster - set(degraded_outage)
    unknown_verdicts = {
        str(r.get("verdict") or "missing").lower()
        for r in reviews
        if str(r.get("verdict") or "missing").lower() not in REVIEWER_VERDICTS
    }
    if unknown_verdicts:
        blockers.append(
            "review_dossier_unknown_reviewer_verdict:" + ",".join(sorted(unknown_verdicts))
        )
    if _dossier_requires_route_admissions(dossier, frontmatter):
        task_id = str(dossier.get("task_id") or "")
        for review in reviews:
            blockers.extend(
                _route_admission_blockers(
                    review,
                    task_id=task_id,
                    registry=registry,
                    frontmatter=frontmatter,
                )
            )

    required_size = _required_team_size(sizing)
    if len(reviews) < required_size:
        blockers.append(f"review_dossier_team_undersized:{len(reviews)}/{required_size}")

    # go-gate: drop literal-defect phantoms only against a checkout proven to be
    # the reviewed head. Local autoqueue often runs outside the PR checkout, so
    # prefer a declared task worktree when one is available and head-bound.
    dossier_head_sha = str(dossier.get("head_sha") or "")
    verification_root = _frontmatter_repo_root(frontmatter, dossier_head_sha)
    criticals, phantoms = _blocking_criticals(reviews, verification_root, head_sha=dossier_head_sha)
    if phantoms:  # receipt: phantom invalidations are auditable in the CI log, never silent
        print(
            f"go-gate: invalidated {len(phantoms)} phantom literal-defect critical(s): "
            + "; ".join(str(f.get("title")) for _, f in phantoms),
            file=sys.stderr,
        )
    if criticals and sizing.get("block_on_named_critical", True):
        blockers.append(f"review_dossier_unresolved_critical:{len(criticals)}")

    lenses = dossier.get("lenses") or []
    if not isinstance(lenses, list) or not all(isinstance(l, str) for l in lenses):
        blockers.append("review_dossier_malformed:lenses")
        lenses = []
    required_lenses = set(
        lenses_for_files(scoped_files, registry)
        if scoped_files is not None
        else registry.get("always_on_lenses") or []
    )
    missing_required_lenses = required_lenses - set(lenses)
    if missing_required_lenses:
        blockers.append(
            "review_dossier_missing_required_lenses:" + ",".join(sorted(missing_required_lenses))
        )
    for review in reviews:
        blockers.extend(_review_checklist_blockers(review, lenses))

    quorum_reviews = _reviews_for_quorum(reviews, criticals, phantoms)
    accepts = _checklist_complete_accepts(quorum_reviews, lenses)
    unknown_accept_families = {str(r.get("family")) for r in accepts} - roster
    if unknown_accept_families:
        blockers.append(
            "review_dossier_unknown_accept_family:" + ",".join(sorted(unknown_accept_families))
        )
    required_quorum = _int_field(sizing.get("quorum_accept"), "sizing.quorum_accept", blockers)
    if required_quorum is None:
        return tuple(blockers)
    recorded_quorum = dossier.get("quorum_required")
    parsed_recorded_quorum = (
        _int_field(recorded_quorum, "quorum_required", blockers)
        if recorded_quorum is not None
        else None
    )
    if parsed_recorded_quorum is not None and parsed_recorded_quorum != required_quorum:
        blockers.append(f"review_dossier_quorum_mismatch:{recorded_quorum}!={required_quorum}")
    if len(accepts) < required_quorum:
        blockers.append(f"review_dossier_quorum_not_met:{len(accepts)}/{required_quorum}")
    accept_families = {str(r.get("family")) for r in accepts}
    min_families = _int_field(sizing.get("min_families", 1), "sizing.min_families", blockers)
    if min_families is not None and len(accept_families) < min_families:
        blockers.append(
            f"review_dossier_family_diversity:accept_families={len(accept_families)}/{min_families}"
        )
    if sizing.get("require_all_families"):
        missing_families = roster - {str(r.get("family")) for r in accepts}
        if missing_families:
            blockers.append(
                "review_dossier_family_diversity:missing_accept_from="
                + ",".join(sorted(missing_families))
            )
    if frontmatter is not None and accepts:
        writer_family = writer_family_for_lane(str(frontmatter.get("assigned_to") or ""), registry)
        writer_accepts = sum(1 for r in accepts if str(r.get("family")) == writer_family)
        if writer_accepts > len(accepts) // 2:
            blockers.append(
                f"review_dossier_writer_family_majority:{writer_family}:{writer_accepts}/{len(accepts)}"
            )

    verdict = str(dossier.get("review_team_verdict") or "missing").lower()
    if verdict != QUORUM_ACCEPT:
        blockers.append(f"review_team_verdict_not_quorum_accept:{verdict}")
    return tuple(blockers)


def review_dossier_validity_blockers(
    frontmatter: Mapping[str, Any],
    note_path: Path,
    *,
    pr_head_sha: str | None = None,
    pr_number: int | None = None,
    changed_files: Sequence[str] | None = None,
    changed_file_count: int | None = None,
    registry: Mapping[str, Any] | None = None,
    outage_state_path: Path | None = None,
    admission_time: datetime | str | None = None,
) -> tuple[str, ...]:
    """Validate a recorded review dossier without honoring any gate killswitch."""

    task_id = str(frontmatter.get("task_id") or "").strip()
    if not task_id:
        return ("review_dossier_unkeyable:missing_task_id",)
    dossier_file = review_dossier_path(note_path, task_id)
    if not dossier_file.is_file():
        return ("missing_review_dossier",)
    try:
        loaded = yaml.safe_load(dossier_file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return (f"review_dossier_malformed:{type(exc).__name__}",)
    if not isinstance(loaded, Mapping):
        return (f"review_dossier_malformed:not_a_mapping:{type(loaded).__name__}",)
    if loaded.get("dossier_schema") != 1:
        return (f"review_dossier_malformed:dossier_schema:{loaded.get('dossier_schema')}",)
    if registry is None:
        try:
            registry = load_lens_registry()
        except (OSError, ValueError, yaml.YAMLError) as exc:
            return (f"review_lens_registry_unreadable:{type(exc).__name__}",)
    return _dossier_validity_blockers(
        loaded,
        pr_head_sha=pr_head_sha,
        registry=registry,
        frontmatter=frontmatter,
        expected_task_id=task_id,
        pr_number=pr_number,
        changed_files=changed_files,
        changed_file_count=changed_file_count,
        outage_state_path=outage_state_path,
        admission_time=admission_time,
    )


def review_team_verdict_blockers(
    frontmatter: Mapping[str, Any],
    note_path: Path,
    *,
    pr_head_sha: str | None = None,
    pr_number: int | None = None,
    changed_files: Sequence[str] | None = None,
    changed_file_count: int | None = None,
    registry: Mapping[str, Any] | None = None,
    outage_state_path: Path | None = None,
    admission_time: datetime | str | None = None,
) -> tuple[str, ...]:
    """Admission blockers from the review-team quorum gate (no quorum, no merge).

    Fail-closed: a missing/malformed/stale dossier blocks; the verdict field is
    never trusted alone — quorum, criticals, team size, mandatory lenses, and
    family diversity are recomputed from the recorded reviews. When changed
    files are supplied, the recorded team class and lens set must match the
    same surface-derived scope used by the dispatcher.
    ``HAPAX_REVIEW_TEAM_GATE_OFF=1`` is the documented emergency bypass for
    post-dossier admission only; it is not a dispatch-time/provider-use bypass.
    Durable receipt minting must use
    :func:`review_dossier_validity_blockers` instead.
    """

    if gate_disabled():
        return ()
    return review_dossier_validity_blockers(
        frontmatter,
        note_path,
        pr_head_sha=pr_head_sha,
        pr_number=pr_number,
        changed_files=changed_files,
        changed_file_count=changed_file_count,
        registry=registry,
        outage_state_path=outage_state_path,
        admission_time=admission_time,
    )
