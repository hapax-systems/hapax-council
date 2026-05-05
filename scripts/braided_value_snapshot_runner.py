#!/usr/bin/env python3
"""Build a read-only braided-value snapshot and operator dashboard.

The runner is intentionally descriptive. It reads cc-task frontmatter,
cc-hygiene state, and live witness files, then writes an append-only JSONL
snapshot ledger plus a Markdown dashboard. It never mutates task state and it
does not make braid scores authoritative for public, monetary, or research
truth claims.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from shared.braid_v2_config import (
    BRAID_V2_BETA,
    BRAID_V2_FORCING_GATE_THRESHOLD,
    BRAID_V2_MAX_PUBLIC_CLAIM_ORDER,
    BRAID_V2_RHO,
    BRAID_V2_STRAIN_GATE_THRESHOLD,
    BRAID_V2_W_ENGAGEMENT,
    BRAID_V2_W_FORCING,
    BRAID_V2_W_MONETARY,
    BRAID_V2_W_POLYSEMIC,
    BRAID_V2_W_RESEARCH,
    BRAID_V2_W_TREE_EFFECT,
    BRAID_V2_W_UNBLOCK,
)
from shared.github_publication_log import classify_publication_log_payload

DEFAULT_TASK_ROOT = Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks"
DEFAULT_HYGIENE_STATE = Path.home() / ".cache/hapax/cc-hygiene-state.json"
DEFAULT_DASHBOARD = DEFAULT_TASK_ROOT / "_dashboard/cc-braided-value.md"
DEFAULT_LEDGER = (
    Path.home()
    / "Documents/Personal/20-projects/hapax-research/ledgers/braided-value-snapshots.jsonl"
)

SCORE_DRIFT_THRESHOLD = 1.0
HIGH_BRAID_THRESHOLD = 7.0
DEFAULT_STALE_SECONDS = 24 * 60 * 60
STALE_BLOCKER_DAYS = 7

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---[ \t]*(?:\n|$)", re.DOTALL)

VALUE_FAMILIES = ("engagement", "monetary", "research", "tree_effect")
NEGATIVE_REASON_ORDER = (
    "visible_claim_without_live_witness",
    "selected_not_successful_recruitment",
    "rights_blocked_money_claim",
    "private_audio_route_public_claim",
    "tauri_decommission_overclaim",
    "usb_bandwidth_reliability_overclaim",
    "missing_telemetry_for_audience_or_revenue_claim",
)
BAD_WITNESS_STATUSES = {
    "missing",
    "stale",
    "malformed",
    "degraded",
    "unsafe",
    "private_only",
    "rights_blocked",
    "selected_not_witnessed",
    "unavailable",
}


type JsonDict = dict[str, Any]


@dataclass(frozen=True)
class TaskNote:
    path: Path
    source_class: str
    frontmatter: JsonDict
    body: str
    parse_error: str | None = None

    @property
    def task_id(self) -> str:
        value = self.frontmatter.get("task_id")
        return str(value) if value else self.path.stem

    @property
    def status(self) -> str:
        value = self.frontmatter.get("status")
        return str(value).lower() if value is not None else "parse_error"


@dataclass(frozen=True)
class BraidVector:
    engagement: float | None
    monetary: float | None
    research: float | None
    tree_effect: float | None
    evidence_confidence: float | None
    risk_penalty: float
    declared_score: float | None
    schema: str = "1"
    # v1.1 optional dimensions. None when the task is v1 or when v1.1 has not
    # populated the field. Validated lazily by ``recompute_braid_score``.
    forcing_function_window: str | None = None
    unblock_breadth: float | None = None
    polysemic_channels: tuple[int, ...] | None = None
    funnel_role: str | None = None
    compounding_curve: str | None = None
    axiomatic_strain: float | None = None
    # v2.0 optional dimensions and gate flags.
    # Witness-derived in production; for the spike, operator-set or
    # test-fixture populated. None / default values mean "do not gate":
    # ``deny_wins`` defaults False; ``mode_ceiling`` /
    # ``max_public_claim`` / ``target_deposit_tier`` default None
    # (no comparison made); ``witness_freshness`` defaults 1.0.
    deny_wins: bool = False
    mode_ceiling: str | None = None
    max_public_claim: str | None = None
    target_deposit_tier: str | None = None
    grounding_class: str | None = None
    witness_freshness: float = 1.0

    @property
    def complete(self) -> bool:
        return all(
            value is not None
            for value in (
                self.engagement,
                self.monetary,
                self.research,
                self.tree_effect,
                self.evidence_confidence,
            )
        )

    @property
    def is_v11(self) -> bool:
        """True when the braid_schema discriminator selects v1.1.

        Per the schema contract in ``cc-readme.md`` braid-overlay section,
        only ``braid_schema: 1.1`` selects the v1.1 formula. Anything else
        (``1``, ``2``, missing, parse error) does NOT route here.
        """

        return self.schema == "1.1"

    @property
    def is_v2(self) -> bool:
        """True when the braid_schema discriminator selects v2.0.

        Per the v2.0 design spec, ``braid_schema: 2`` (or ``2.0``) selects
        the 5-layer composition pipeline. Anything else (``1``, ``1.1``,
        missing, parse error) routes to its own formula.
        """

        return self.schema == "2"

    def as_dict(self) -> JsonDict:
        return {
            "engagement": self.engagement,
            "monetary": self.monetary,
            "research": self.research,
            "tree_effect": self.tree_effect,
            "evidence_confidence": self.evidence_confidence,
            "risk_penalty": self.risk_penalty,
            "declared_score": self.declared_score,
            "schema": self.schema,
            "forcing_function_window": self.forcing_function_window,
            "unblock_breadth": self.unblock_breadth,
            "polysemic_channels": list(self.polysemic_channels)
            if self.polysemic_channels is not None
            else None,
            "funnel_role": self.funnel_role,
            "compounding_curve": self.compounding_curve,
            "axiomatic_strain": self.axiomatic_strain,
            "deny_wins": self.deny_wins,
            "mode_ceiling": self.mode_ceiling,
            "max_public_claim": self.max_public_claim,
            "target_deposit_tier": self.target_deposit_tier,
            "grounding_class": self.grounding_class,
            "witness_freshness": self.witness_freshness,
        }


@dataclass(frozen=True)
class HygieneRead:
    status: str
    path: Path
    payload: JsonDict | None
    error: str | None = None

    def as_dict(self) -> JsonDict:
        return {
            "status": self.status,
            "path": str(self.path),
            "error": self.error,
        }


@dataclass(frozen=True)
class WitnessSpec:
    witness_id: str
    label: str
    path: Path
    family: str
    source_class: str = "live_runtime"
    stale_seconds: int = DEFAULT_STALE_SECONDS
    public_when_ok: bool = False


@dataclass(frozen=True)
class WitnessRead:
    witness_id: str
    label: str
    path: str
    family: str
    source_class: str
    status: str
    reasons: tuple[str, ...]
    observed_at: str | None
    mode_ceiling: str
    max_public_claim: str

    def as_dict(self) -> JsonDict:
        return {
            "witness_id": self.witness_id,
            "label": self.label,
            "path": self.path,
            "family": self.family,
            "source_class": self.source_class,
            "status": self.status,
            "reasons": list(self.reasons),
            "observed_at": self.observed_at,
            "mode_ceiling": self.mode_ceiling,
            "max_public_claim": self.max_public_claim,
        }


@dataclass(frozen=True)
class SystemdSpec:
    unit: str
    family: str


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def isoformat_z(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if isinstance(value, tuple | set):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def parse_frontmatter(path: Path) -> TaskNote:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return TaskNote(
            path=path,
            source_class=source_class_for_path(path),
            frontmatter={},
            body="",
            parse_error=f"read_error:{exc}",
        )
    match = FRONTMATTER_RE.match(text)
    if not match:
        return TaskNote(
            path=path,
            source_class=source_class_for_path(path),
            frontmatter={},
            body=text,
            parse_error="missing_frontmatter",
        )
    try:
        parsed = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        return TaskNote(
            path=path,
            source_class=source_class_for_path(path),
            frontmatter={},
            body=text[match.end() :],
            parse_error=f"malformed_frontmatter:{exc.__class__.__name__}",
        )
    if not isinstance(parsed, dict):
        return TaskNote(
            path=path,
            source_class=source_class_for_path(path),
            frontmatter={},
            body=text[match.end() :],
            parse_error="frontmatter_not_mapping",
        )
    return TaskNote(
        path=path,
        source_class=source_class_for_path(path),
        frontmatter=dict(parsed),
        body=text[match.end() :],
    )


def source_class_for_path(path: Path) -> str:
    parts = {part.lower() for part in path.parts}
    if "closed" in parts:
        return "closed_artifact"
    if "active" in parts:
        return "planning_task"
    return "repo_implementation"


def load_task_notes(task_root: Path) -> list[TaskNote]:
    notes: list[TaskNote] = []
    for directory_name in ("active", "closed"):
        directory = task_root / directory_name
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.md")):
            notes.append(parse_frontmatter(path))
    return notes


_FUNNEL_ROLES: frozenset[str] = frozenset(
    {"none", "inbound", "conversion", "amplifier", "compounder"}
)
_COMPOUNDING_CURVES: frozenset[str] = frozenset(
    {"linear", "log_saturating", "step_function", "preferential_attachment", "mixed"}
)
# braid_forcing_function_window kinds per the v1.1 schema. ``none`` is a
# bare token; the other three carry an ``:<YYYY-MM-DD>`` suffix.
_FORCING_WINDOW_RE: re.Pattern[str] = re.compile(
    r"^(?:none|(regulatory|deadline|amplifier_window):(\d{4}-\d{2}-\d{2}))$"
)


def _normalize_schema(value: Any) -> str:
    """Canonicalise braid_schema into '1', '1.1', or '2'.

    YAML may produce numeric (1, 1.1, 2, 2.0), string ('1', '1.1', '2',
    '2.0'), or absent — all collapse to a string discriminator. Anything
    else (parse error, unknown version) routes to v1 to preserve
    backward compatibility.
    """

    if value is None:
        return "1"
    if isinstance(value, bool):
        return "1"
    if isinstance(value, int):
        if value == 2:
            return "2"
        return "1"
    if isinstance(value, float):
        if abs(value - 1.1) < 1e-6:
            return "1.1"
        if abs(value - 2.0) < 1e-6:
            return "2"
        return "1"
    text = str(value).strip()
    if text in {"1", "1.0"}:
        return "1"
    if text == "1.1":
        return "1.1"
    if text in {"2", "2.0"}:
        return "2"
    return "1"


def _parse_polysemic_channels(value: Any) -> tuple[int, ...] | None:
    """Validate ``braid_polysemic_channels`` per the seven-channel taxonomy.

    Permitted: list of distinct ints in ``{1..7}``. Out-of-range integers,
    duplicates, and non-integer entries warn-and-skip — the contract in
    cc-readme.md says runner should never crash on malformed input.
    Returns the validated tuple or ``None`` when the field is absent or
    every entry was rejected.
    """

    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        return None
    seen: set[int] = set()
    out: list[int] = []
    for item in value:
        if isinstance(item, bool):
            continue
        if not isinstance(item, int):
            continue
        if not 1 <= item <= 7:
            continue
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return tuple(out) if out else None


def _parse_forcing_window(value: Any) -> str | None:
    """Validate ``braid_forcing_function_window`` regex.

    Permitted: ``none`` or one of ``regulatory|deadline|amplifier_window:<YYYY-MM-DD>``.
    Anything else returns ``None`` so the score path treats it as missing.
    """

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if _FORCING_WINDOW_RE.match(text):
        return text
    return None


def compute_forcing_function_urgency(
    window: str | None,
    *,
    now: datetime | None = None,
) -> float:
    """Translate a forcing-function window into the v1.1 urgency score.

    Per the cc-readme.md table:
        ``none`` / closed / null     → 0
        > 365 days out               → 2
        90 - 365 days out            → 5
        30 - 90 days out             → 8
        < 30 days (incl. past)       → 10

    The "closed" case (date already in the past) is the most operator-
    facing failure mode — the spec is explicit that closed windows score
    0, not 10. This function follows the spec.
    """

    if not window or window == "none":
        return 0.0
    match = _FORCING_WINDOW_RE.match(window)
    if not match or match.group(1) is None:
        return 0.0
    try:
        target = datetime.strptime(match.group(2), "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return 0.0
    reference = now if now is not None else utc_now()
    days = (target - reference).total_seconds() / 86400.0
    if days < 0:
        # Closed window: explicit zero per spec.
        return 0.0
    if days < 30:
        return 10.0
    if days < 90:
        return 8.0
    if days <= 365:
        return 5.0
    return 2.0


def _parse_string_enum(value: Any, allowed: tuple[str, ...]) -> str | None:
    """Validate ``value`` against an allowed string enum tuple.

    Used for v2.0 ``mode_ceiling``, ``max_public_claim``,
    ``target_deposit_tier`` fields where unknown values must not enter
    the gate computation.
    """

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text in allowed:
        return text
    return None


def braid_vector_from_frontmatter(frontmatter: JsonDict) -> BraidVector:
    schema = _normalize_schema(frontmatter.get("braid_schema"))
    raw_freshness = as_float(frontmatter.get("braid_witness_freshness"))
    witness_freshness = 1.0 if raw_freshness is None else max(0.0, min(raw_freshness, 1.0))
    return BraidVector(
        engagement=as_float(frontmatter.get("braid_engagement")),
        monetary=as_float(frontmatter.get("braid_monetary")),
        research=as_float(frontmatter.get("braid_research")),
        tree_effect=as_float(frontmatter.get("braid_tree_effect")),
        evidence_confidence=as_float(frontmatter.get("braid_evidence_confidence")),
        risk_penalty=as_float(frontmatter.get("braid_risk_penalty")) or 0.0,
        declared_score=as_float(frontmatter.get("braid_score")),
        schema=schema,
        forcing_function_window=_parse_forcing_window(
            frontmatter.get("braid_forcing_function_window")
        ),
        unblock_breadth=as_float(frontmatter.get("braid_unblock_breadth")),
        polysemic_channels=_parse_polysemic_channels(frontmatter.get("braid_polysemic_channels")),
        funnel_role=(
            str(frontmatter["braid_funnel_role"]).strip()
            if frontmatter.get("braid_funnel_role")
            and str(frontmatter["braid_funnel_role"]).strip() in _FUNNEL_ROLES
            else None
        ),
        compounding_curve=(
            str(frontmatter["braid_compounding_curve"]).strip()
            if frontmatter.get("braid_compounding_curve")
            and str(frontmatter["braid_compounding_curve"]).strip() in _COMPOUNDING_CURVES
            else None
        ),
        axiomatic_strain=as_float(frontmatter.get("braid_axiomatic_strain")),
        deny_wins=bool(frontmatter.get("braid_deny_wins", False)),
        mode_ceiling=_parse_string_enum(
            frontmatter.get("braid_mode_ceiling"),
            ("private", "dry_run", "public_archive", "public_live", "public_monetizable"),
        ),
        max_public_claim=_parse_string_enum(
            frontmatter.get("braid_max_public_claim"),
            BRAID_V2_MAX_PUBLIC_CLAIM_ORDER,
        ),
        target_deposit_tier=_parse_string_enum(
            frontmatter.get("braid_target_deposit_tier"),
            BRAID_V2_MAX_PUBLIC_CLAIM_ORDER,
        ),
        grounding_class=_parse_string_enum(
            frontmatter.get("braid_grounding_class"),
            ("grounding-act", "delegable-work"),
        ),
        witness_freshness=witness_freshness,
    )


def _recompute_v1(vector: BraidVector) -> float:
    engagement = float(vector.engagement)
    monetary = float(vector.monetary)
    research = float(vector.research)
    tree_effect = float(vector.tree_effect)
    evidence_confidence = float(vector.evidence_confidence)
    return (
        0.35 * min(engagement, monetary, research)
        + 0.30 * ((engagement + monetary + research) / 3.0)
        + 0.25 * tree_effect
        + 0.10 * evidence_confidence
        - vector.risk_penalty
    )


def _recompute_v11(vector: BraidVector, *, now: datetime | None = None) -> float:
    """Compute v1.1 score per cc-readme.md formula.

    The three new positive terms (``unblock_breadth``, ``polysemic_channels``,
    ``forcing_function_urgency``) and the new subtractive ``axiomatic_strain``
    default to 0 when their fields are absent — per the
    backward-compatibility invariant, a v1.1 task with no new fields
    populated computes to (close to) the v1 score, modulated only by the
    rebalanced base weights.
    """

    engagement = float(vector.engagement)
    monetary = float(vector.monetary)
    research = float(vector.research)
    tree_effect = float(vector.tree_effect)
    evidence_confidence = float(vector.evidence_confidence)

    unblock = vector.unblock_breadth or 0.0
    channels = vector.polysemic_channels or ()
    urgency = compute_forcing_function_urgency(vector.forcing_function_window, now=now)
    strain = vector.axiomatic_strain or 0.0

    return (
        0.30 * min(engagement, monetary, research)
        + 0.25 * ((engagement + monetary + research) / 3.0)
        + 0.20 * tree_effect
        + 0.10 * (unblock / 1.5)
        + 0.10 * float(len(channels))
        + 0.05 * urgency
        + 0.10 * evidence_confidence
        - vector.risk_penalty
        - strain
    )


def _ces_aggregate(values: list[float], weights: list[float], rho: float) -> float:
    """Constant Elasticity of Substitution aggregator.

    Per spec §3.2: ``core = (Σ w_i · x_i^ρ)^(1/ρ)``. Three limit cases:
        ρ → -∞   reproduces ``min`` (Leontief, perfect complements)
        ρ = 0    reproduces Cobb-Douglas via L'Hopital limit
        ρ = 1    reproduces weighted average (perfect substitutes)

    Defensive against zero-valued inputs under negative rho: if any
    value <= 0 and rho < 0, returns 0 (matches the Leontief limit's
    treatment of "any zero zeroes the aggregate"). The spec's intent
    for rho = -2 is "we want all three reasonable" — a literal zero
    trips this gate.
    """

    if not values or not weights or len(values) != len(weights):
        raise ValueError("CES aggregate requires matched values/weights")
    if math.isinf(rho) and rho < 0:
        return min(values)
    if rho < 0 and any(v <= 0 for v in values):
        return 0.0
    if rho == 0:
        if any(v <= 0 for v in values):
            return 0.0
        return math.exp(sum(w * math.log(v) for w, v in zip(weights, values, strict=True)))
    inner = sum(w * (v**rho) for w, v in zip(weights, values, strict=True))
    if inner <= 0:
        return 0.0
    return inner ** (1.0 / rho)


def _compute_v2_layer_1_gate(
    vector: BraidVector,
    *,
    forcing_urgency: float,
) -> str | None:
    """Evaluate v2 Layer 1 lexicographic gates per spec §3.1.

    Returns a gate-cause string if any hard-cut gate fires; returns
    ``None`` when the score path is clear. The score-recompute path
    short-circuits to ``None`` (sentinel for GATED) on any firing
    cause.

    Mode-ceiling violation criterion (spec §2.6): public-tier ceiling
    with ``axiomatic_strain >= 1`` OR with stale consent. The spike
    encodes only the strain-coupled half — the consent-staleness half
    is a Phase A witness-wiring concern out of scope for the formula
    spike.

    max_public_claim mismatch (spec §2.6): the artifact's claim must
    dominate (be >= ladder index of) its declared deposit target.
    """

    if vector.deny_wins:
        return "deny_wins"

    strain = vector.axiomatic_strain or 0.0
    if strain >= BRAID_V2_STRAIN_GATE_THRESHOLD:
        return "strain_gate"

    if forcing_urgency >= BRAID_V2_FORCING_GATE_THRESHOLD:
        return "forcing_zero_deadline"

    ceiling = vector.mode_ceiling
    if ceiling and ceiling.startswith("public") and strain >= 1.0:
        return "mode_ceiling_strain"

    claim = vector.max_public_claim
    target = vector.target_deposit_tier
    if claim and target:
        try:
            claim_idx = BRAID_V2_MAX_PUBLIC_CLAIM_ORDER.index(claim)
            target_idx = BRAID_V2_MAX_PUBLIC_CLAIM_ORDER.index(target)
        except ValueError:
            return None
        if claim_idx < target_idx:
            return "max_public_claim_below_target"

    return None


def _recompute_v2(
    vector: BraidVector,
    *,
    now: datetime | None = None,
    rho: float = BRAID_V2_RHO,
    beta: float = BRAID_V2_BETA,
) -> float | None:
    """Compute v2.0 score per spec §3 (5-layer composition).

    Returns ``None`` when any Layer 1 gate fires. Returns a
    floating-point score otherwise. Caller responsibility to interpret
    the ``None`` sentinel — the dashboard surfaces it as
    ``GATED:<cause>`` rather than as a low priority.

    Layers, in order:
      1. Lexicographic gates → None
      2. CES core over (E, M, R)
      3. Additive bonuses (T, U/1.5, |channels|^β, forcing_urgency)
      4. Subtractive penalties (P, strain ∈ {0,1,2})
      5. Multiplicative envelope (C/10) × witness_freshness
    """

    engagement = float(vector.engagement)
    monetary = float(vector.monetary)
    research = float(vector.research)
    tree_effect = float(vector.tree_effect)
    evidence_confidence = float(vector.evidence_confidence)

    unblock = vector.unblock_breadth or 0.0
    channels = vector.polysemic_channels or ()
    urgency = compute_forcing_function_urgency(vector.forcing_function_window, now=now)
    strain = vector.axiomatic_strain or 0.0

    gate_cause = _compute_v2_layer_1_gate(vector, forcing_urgency=urgency)
    if gate_cause is not None:
        return None

    core = _ces_aggregate(
        values=[engagement, monetary, research],
        weights=[
            BRAID_V2_W_ENGAGEMENT,
            BRAID_V2_W_MONETARY,
            BRAID_V2_W_RESEARCH,
        ],
        rho=rho,
    )

    polysemic_count = float(len(channels))
    polysemic_term = polysemic_count**beta if polysemic_count > 0 else 0.0
    bonuses = (
        BRAID_V2_W_TREE_EFFECT * tree_effect
        + BRAID_V2_W_UNBLOCK * (unblock / 1.5)
        + BRAID_V2_W_POLYSEMIC * polysemic_term
        + BRAID_V2_W_FORCING * urgency
    )

    penalties = vector.risk_penalty + max(0.0, min(strain, 2.0))

    raw_score = core + bonuses - penalties

    c_envelope = max(0.0, min(evidence_confidence / 10.0, 1.0))
    freshness = max(0.0, min(vector.witness_freshness, 1.0))
    return raw_score * c_envelope * freshness


def recompute_braid_score(vector: BraidVector, *, now: datetime | None = None) -> float | None:
    """Compute the braid score, dispatching by schema discriminator.

    v1 tasks (``braid_schema: 1`` or missing) use the original 5-term
    formula. v1.1 tasks use the rebalanced 9-term formula with the
    three new positive terms and the subtractive axiomatic_strain.
    v2 tasks use the 5-layer composition (CES core + additive bonuses
    + subtractive penalties + confidence/witness multipliers, with
    Layer 1 lexicographic gates short-circuiting to None).

    Returns ``None`` when the base 5 dimensions aren't fully populated,
    or when a v2 Layer 1 gate fires (deny_wins, strain >= 3,
    forcing-zero deadline, mode_ceiling violation, max_public_claim
    mismatch).
    """

    if not vector.complete:
        return None
    if vector.is_v2:
        result = _recompute_v2(vector, now=now)
        return None if result is None else round(result, 2)
    if vector.is_v11:
        return round(_recompute_v11(vector, now=now), 2)
    return round(_recompute_v1(vector), 2)


def load_hygiene_state(path: Path) -> HygieneRead:
    if not path.exists():
        return HygieneRead(status="missing", path=path, payload=None, error="hygiene_state_missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return HygieneRead(
            status="malformed",
            path=path,
            payload=None,
            error=f"hygiene_state_unreadable:{exc.__class__.__name__}",
        )
    if not isinstance(payload, dict):
        return HygieneRead(
            status="malformed",
            path=path,
            payload=None,
            error="hygiene_state_not_mapping",
        )
    return HygieneRead(status="present", path=path, payload=payload)


def default_witness_specs() -> list[WitnessSpec]:
    return [
        WitnessSpec(
            "voice_output_witness",
            "Voice output witness",
            Path("/dev/shm/hapax-daimonion/voice-output-witness.json"),
            "voice_grounding_research",
        ),
        WitnessSpec(
            "narration_triads",
            "Narration triads",
            Path.home() / "hapax-state/outcomes/narration-triads.jsonl",
            "voice_grounding_research",
        ),
        WitnessSpec(
            "broadcast_audio_safety",
            "Broadcast audio safety",
            Path("/dev/shm/hapax-broadcast/audio-safe-for-broadcast.json"),
            "livestream_studio_stack",
            public_when_ok=True,
        ),
        WitnessSpec(
            "audio_router_state",
            "Audio router state",
            Path("/dev/shm/hapax-audio-router/state.json"),
            "livestream_studio_stack",
        ),
        WitnessSpec(
            "audio_ducker_state",
            "Audio ducker state",
            Path("/dev/shm/hapax-audio-ducker/state.json"),
            "livestream_studio_stack",
        ),
        WitnessSpec(
            "audio_safety_state",
            "Audio safety state",
            Path("/dev/shm/hapax-audio-safety/state.json"),
            "livestream_studio_stack",
        ),
        WitnessSpec(
            "affordance_dispatch_trace",
            "Affordance dispatch trace",
            Path.home() / "hapax-state/affordance/dispatch-trace.jsonl",
            "semantic_affordance_economy",
        ),
        WitnessSpec(
            "affordance_recruitment_log",
            "Affordance recruitment log",
            Path.home() / "hapax-state/affordance/recruitment-log.jsonl",
            "semantic_affordance_economy",
        ),
        WitnessSpec(
            "daimonion_recruitment_log",
            "Daimonion recruitment log",
            Path("/dev/shm/hapax-daimonion/recruitment-log.jsonl"),
            "semantic_affordance_economy",
        ),
        WitnessSpec(
            "compositor_recent_recruitment",
            "Compositor recent recruitment",
            Path("/dev/shm/hapax-compositor/recent-recruitment.json"),
            "semantic_affordance_economy",
        ),
        WitnessSpec(
            "demonet_egress_audit",
            "Demonet egress audit",
            Path.home() / "hapax-state/demonet-egress-audit.jsonl",
            "monetary_safety_rail",
        ),
        WitnessSpec(
            "imagination_current",
            "Imagination current",
            Path("/dev/shm/hapax-imagination/current.json"),
            "visual_reverie_path",
        ),
        WitnessSpec(
            "imagination_health",
            "Imagination health",
            Path("/dev/shm/hapax-imagination/health.json"),
            "visual_reverie_path",
        ),
        WitnessSpec(
            "imagination_uniforms",
            "Imagination uniforms",
            Path("/dev/shm/hapax-imagination/uniforms.json"),
            "visual_reverie_path",
        ),
        WitnessSpec(
            "imagination_pool_metrics",
            "Imagination pool metrics",
            Path("/dev/shm/hapax-imagination/pool_metrics.json"),
            "visual_reverie_path",
        ),
        WitnessSpec(
            "reverie_predictions",
            "Reverie predictions",
            Path("/dev/shm/hapax-reverie/predictions.json"),
            "visual_reverie_path",
        ),
        WitnessSpec(
            "compositor_health",
            "Compositor health",
            Path("/dev/shm/hapax-compositor/health.json"),
            "visual_reverie_path",
        ),
        WitnessSpec(
            "compositor_degraded",
            "Compositor degraded",
            Path("/dev/shm/hapax-compositor/degraded.json"),
            "visual_reverie_path",
        ),
        WitnessSpec(
            "compositor_recent_impingements",
            "Compositor recent impingements",
            Path("/dev/shm/hapax-compositor/recent-impingements.json"),
            "visual_reverie_path",
        ),
        WitnessSpec(
            "dmn_status",
            "DMN status",
            Path("/dev/shm/hapax-dmn/status.json"),
            "visual_reverie_path",
        ),
        WitnessSpec(
            "dmn_impingements",
            "DMN impingements",
            Path("/dev/shm/hapax-dmn/impingements.jsonl"),
            "visual_reverie_path",
        ),
        WitnessSpec(
            "stimmung_state",
            "Stimmung state",
            Path("/dev/shm/hapax-stimmung/state.json"),
            "visual_reverie_path",
        ),
        WitnessSpec(
            "sensors_snapshot",
            "Sensor snapshot",
            Path("/dev/shm/hapax-sensors/snapshot.json"),
            "livestream_studio_stack",
        ),
        WitnessSpec(
            "usb_topology_status",
            "USB topology status",
            Path("/dev/shm/hapax-usb/topology-status.json"),
            "executive_function_os",
        ),
        WitnessSpec(
            "publication_log",
            "Publication log",
            Path.home() / "hapax-state/publication/publication-log.jsonl",
            "publication_tree_effect",
        ),
        WitnessSpec(
            "logos_health",
            "Logos health witness",
            Path("/dev/shm/hapax-logos/health.json"),
            "executive_function_os",
        ),
        WitnessSpec(
            "logos_openapi",
            "Logos OpenAPI witness",
            Path("/dev/shm/hapax-logos/openapi.json"),
            "executive_function_os",
        ),
        WitnessSpec(
            "research_registry",
            "Research registry",
            Path.home() / "hapax-state/research/registry.jsonl",
            "research_instrument_mesh",
            source_class="closed_artifact",
            stale_seconds=7 * DEFAULT_STALE_SECONDS,
        ),
    ]


def default_systemd_specs() -> list[SystemdSpec]:
    return [
        SystemdSpec("hapax-logos-api.service", "executive_function_os"),
        SystemdSpec("hapax-daimonion.service", "voice_grounding_research"),
        SystemdSpec("hapax-imagination.service", "visual_reverie_path"),
        SystemdSpec("hapax-compositor.service", "visual_reverie_path"),
    ]


def load_jsonish(path: Path) -> tuple[Any | None, str | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"read_error:{exc.__class__.__name__}"
    if path.suffix == ".jsonl":
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            return {}, None
        text = lines[-1]
    if not text.strip():
        return {}, None
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, f"json_error:{exc.__class__.__name__}"


def walk_json(value: Any) -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            items.append((str(key).lower(), child))
            items.extend(walk_json(child))
    elif isinstance(value, list):
        for child in value:
            items.extend(walk_json(child))
    return items


def any_truthy_key(payload: Any, names: set[str]) -> bool:
    return any(key in names and truthy(value) for key, value in walk_json(payload))


def any_falsy_key(payload: Any, names: set[str]) -> bool:
    return any(key in names and falsy(value) for key, value in walk_json(payload))


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "ok", "safe", "active"}
    return False


def falsy(value: Any) -> bool:
    if isinstance(value, bool):
        return not value
    if isinstance(value, int | float):
        return value == 0
    if isinstance(value, str):
        return value.strip().lower() in {
            "0",
            "false",
            "no",
            "unsafe",
            "blocked",
            "denied",
            "inactive",
        }
    return False


def payload_text(payload: Any) -> str:
    try:
        return json.dumps(payload, sort_keys=True, default=str).lower()
    except TypeError:
        return str(payload).lower()


def classify_payload(spec: WitnessSpec, payload: Any) -> tuple[str, tuple[str, ...]]:
    if spec.witness_id == "publication_log":
        return classify_publication_log_payload(payload)

    text = payload_text(payload)
    reasons: list[str] = []
    status = "ok"

    if "rights" in text and any(word in text for word in ("blocked", "denied", "failed")):
        status = "rights_blocked"
        reasons.append("rights_or_privacy_blocked")

    if any(word in text for word in ("unsafe", "leak", "not_safe_for_broadcast")):
        status = "unsafe"
        reasons.append("unsafe_marker")

    if any_falsy_key(payload, {"safe_for_broadcast", "broadcast_safe", "safe"}):
        status = "unsafe"
        reasons.append("safe_for_broadcast_false")

    if "private" in text and any(word in text for word in ("broadcast", "public", "egress")):
        status = "unsafe"
        reasons.append("private_route_public_claim")

    if any(word in text for word in ("degraded", "failed", "error")):
        if status == "ok":
            status = "degraded"
        reasons.append("degraded_marker")

    if "private_only" in text or any_truthy_key(payload, {"private_only"}):
        if status == "ok":
            status = "private_only"
        reasons.append("private_only_marker")

    if "recruit" in spec.witness_id:
        has_selection = any_truthy_key(payload, {"selected", "recruited", "commanded"})
        has_success = any_truthy_key(
            payload,
            {"success", "succeeded", "witnessed", "completed", "delivered"},
        )
        if has_selection and not has_success:
            if status == "ok":
                status = "selected_not_witnessed"
            reasons.append("selected_or_recruited_without_success_witness")

    if not reasons:
        reasons.append("witness_present")
    return status, tuple(dict.fromkeys(reasons))


def witness_mode_and_claim(spec: WitnessSpec, status: str) -> tuple[str, str]:
    if status == "ok" and spec.public_when_ok:
        return "public_live", "runtime_marker_present_not_quality_or_truth_claim"
    if status == "ok":
        return "dry_run", "witnessed_presence_only"
    if status in {"stale", "degraded", "selected_not_witnessed"}:
        return "private", "none_until_fresh_success_witness"
    return "private", "none"


def probe_witness(spec: WitnessSpec, now: datetime) -> WitnessRead:
    if not spec.path.exists():
        return WitnessRead(
            witness_id=spec.witness_id,
            label=spec.label,
            path=str(spec.path),
            family=spec.family,
            source_class=spec.source_class,
            status="missing",
            reasons=("missing_live_witness",),
            observed_at=None,
            mode_ceiling="private",
            max_public_claim="none",
        )

    observed_at = datetime.fromtimestamp(spec.path.stat().st_mtime, tz=UTC)
    stale = now - observed_at > timedelta(seconds=spec.stale_seconds)
    payload, error = load_jsonish(spec.path)
    if error is not None:
        mode, claim = witness_mode_and_claim(spec, "malformed")
        return WitnessRead(
            witness_id=spec.witness_id,
            label=spec.label,
            path=str(spec.path),
            family=spec.family,
            source_class=spec.source_class,
            status="malformed",
            reasons=(error,),
            observed_at=isoformat_z(observed_at),
            mode_ceiling=mode,
            max_public_claim=claim,
        )

    status, reasons = classify_payload(spec, payload)
    if stale and status == "ok":
        status = "stale"
        reasons = ("stale_live_witness",)
    elif stale:
        reasons = tuple(dict.fromkeys((*reasons, "stale_live_witness")))
    mode, claim = witness_mode_and_claim(spec, status)
    return WitnessRead(
        witness_id=spec.witness_id,
        label=spec.label,
        path=str(spec.path),
        family=spec.family,
        source_class=spec.source_class,
        status=status,
        reasons=reasons,
        observed_at=isoformat_z(observed_at),
        mode_ceiling=mode,
        max_public_claim=claim,
    )


def probe_systemd(spec: SystemdSpec) -> WitnessRead:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", spec.unit],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return WitnessRead(
            witness_id=f"systemd_{spec.unit}",
            label=f"systemd {spec.unit}",
            path=f"systemd://user/{spec.unit}",
            family=spec.family,
            source_class="live_runtime",
            status="unavailable",
            reasons=(f"systemd_unavailable:{exc.__class__.__name__}",),
            observed_at=None,
            mode_ceiling="private",
            max_public_claim="none",
        )
    active = result.stdout.strip() == "active"
    status = "ok" if active else "degraded"
    mode, claim = witness_mode_and_claim(
        WitnessSpec(
            witness_id=f"systemd_{spec.unit}",
            label=f"systemd {spec.unit}",
            path=Path(spec.unit),
            family=spec.family,
        ),
        status,
    )
    return WitnessRead(
        witness_id=f"systemd_{spec.unit}",
        label=f"systemd {spec.unit}",
        path=f"systemd://user/{spec.unit}",
        family=spec.family,
        source_class="live_runtime",
        status=status,
        reasons=("systemd_active" if active else f"systemd_state:{result.stdout.strip()}",),
        observed_at=isoformat_z(utc_now()),
        mode_ceiling=mode,
        max_public_claim=claim,
    )


def collect_witnesses(
    now: datetime,
    *,
    witness_specs: list[WitnessSpec] | None = None,
    include_systemd: bool = True,
) -> list[WitnessRead]:
    specs = default_witness_specs() if witness_specs is None else witness_specs
    witnesses = [probe_witness(spec, now) for spec in specs]
    if include_systemd:
        witnesses.extend(probe_systemd(spec) for spec in default_systemd_specs())
    return witnesses


def summarize_witnesses(witnesses: list[WitnessRead]) -> JsonDict:
    bad = [witness for witness in witnesses if witness.status in BAD_WITNESS_STATUSES]
    by_family: dict[str, list[str]] = {}
    for witness in witnesses:
        by_family.setdefault(witness.family, []).append(witness.status)
    return {
        "total": len(witnesses),
        "downgraded": len(bad),
        "downgrade_ids": [witness.witness_id for witness in bad],
        "families": by_family,
    }


def note_text_for_detection(note: TaskNote) -> str:
    return (
        json.dumps(note.frontmatter, sort_keys=True, default=str)
        + "\n"
        + note.body
        + "\n"
        + note.task_id
    ).lower()


def negative_claim_reasons(note: TaskNote, witnesses: list[WitnessRead]) -> list[str]:
    frontmatter_text = json.dumps(note.frontmatter, sort_keys=True, default=str).lower()
    body_text = note.body.lower()
    text = f"{frontmatter_text}\n{body_text}\n{note.task_id.lower()}"
    reasons: list[str] = []
    has_good_live_witness = any(witness.status == "ok" for witness in witnesses)
    public_claim = explicit_public_claim(note, body_text)
    money_claim = explicit_money_claim(note, body_text)
    audience_claim = explicit_audience_claim(note, body_text)
    if public_claim and not has_good_live_witness:
        reasons.append("visible_claim_without_live_witness")
    if explicit_selected_without_success(note, body_text):
        reasons.append("selected_not_successful_recruitment")
    if money_claim and explicit_rights_block(note, body_text):
        reasons.append("rights_blocked_money_claim")
    if explicit_private_audio_public_claim(note, body_text):
        reasons.append("private_audio_route_public_claim")
    if "tauri" in text and "decommission" in text and public_claim:
        reasons.append("tauri_decommission_overclaim")
    if explicit_usb_semantic_claim(note, body_text):
        reasons.append("usb_bandwidth_reliability_overclaim")
    if (audience_claim or money_claim) and explicit_missing_telemetry(note, body_text):
        reasons.append("missing_telemetry_for_audience_or_revenue_claim")
    return [reason for reason in NEGATIVE_REASON_ORDER if reason in set(reasons)]


def explicit_public_claim(note: TaskNote, body_text: str) -> bool:
    frontmatter = note.frontmatter
    claim_keys = {
        "public_claim",
        "public_claims",
        "public_mode",
        "public_behavior",
        "broadcast_claim",
        "public_broadcast_claim",
        "publication_claim",
        "livestream_claim",
        "monetizable_claim",
    }
    if any(
        key in frontmatter and frontmatter[key] not in (None, False, "false") for key in claim_keys
    ):
        return True
    return bool(
        re.search(
            r"\b(public|broadcast|publication|livestream|monetizable)[_-]?claim\s*(?::|=)\s*(true|yes|1)\b",
            body_text,
        )
        or re.search(
            r"\b(public|broadcast|publication|livestream|monetizable)[_-]?claim\s+(true|yes|1)\b",
            body_text,
        )
        or "public_broadcast_claim" in body_text
        or re.search(r"\bclaims?_(public|broadcast|publication|livestream)\b", body_text)
    )


def explicit_money_claim(note: TaskNote, body_text: str) -> bool:
    frontmatter = note.frontmatter
    claim_keys = {
        "monetary_claim",
        "money_claim",
        "revenue_claim",
        "grant_claim",
        "support_claim",
        "monetizable_claim",
    }
    if any(
        key in frontmatter and frontmatter[key] not in (None, False, "false") for key in claim_keys
    ):
        return True
    return bool(
        re.search(
            r"\b(revenue|grant|support|monetary|money)[_-]?claim\s*(?::|=)\s*(true|yes|1)\b",
            body_text,
        )
        or re.search(
            r"\b(revenue|grant|support|monetary|money)[_-]?claim\s+(true|yes|1)\b",
            body_text,
        )
        or re.search(r"\bclaims?_(revenue|grant|support|monetary|money)\b", body_text)
    )


def explicit_audience_claim(note: TaskNote, body_text: str) -> bool:
    frontmatter = note.frontmatter
    claim_keys = {"audience_claim", "engagement_claim", "viewer_claim", "trend_claim"}
    if any(
        key in frontmatter and frontmatter[key] not in (None, False, "false") for key in claim_keys
    ):
        return True
    return bool(
        re.search(
            r"\b(audience|engagement|viewer|trend)[_-]?claim\s*(?::|=)\s*(true|yes|1)\b",
            body_text,
        )
        or re.search(
            r"\b(audience|engagement|viewer|trend)[_-]?claim\s+(true|yes|1)\b",
            body_text,
        )
        or re.search(r"\bclaims?_(audience|engagement|viewer|trend)\b", body_text)
    )


def explicit_selected_without_success(note: TaskNote, body_text: str) -> bool:
    frontmatter = note.frontmatter
    selected = any_truthy_mapping_key(frontmatter, {"selected", "recruited", "commanded"})
    success = any_truthy_mapping_key(
        frontmatter,
        {"success", "succeeded", "witnessed", "completed", "delivered"},
    )
    body_selected = bool(
        re.search(r"\b(selected|recruited|commanded)\s*(?::|=)\s*(true|yes|1)\b", body_text)
        or re.search(r"\b(selected|recruited|commanded)\s+(true|yes|1)\b", body_text)
    )
    body_success = bool(
        re.search(r"\b(success|succeeded|witnessed|completed|delivered)\b", body_text)
    )
    return (selected or body_selected) and not (success or body_success)


def explicit_rights_block(note: TaskNote, body_text: str) -> bool:
    frontmatter = note.frontmatter
    rights_values = [
        str(value).lower()
        for key, value in frontmatter.items()
        if "rights" in str(key).lower() or "privacy" in str(key).lower()
    ]
    if any(value in {"blocked", "denied", "failed", "unsafe"} for value in rights_values):
        return True
    return bool(
        re.search(r"\b(rights|privacy)[_-]?(state|gate)?:?\s*(blocked|denied|failed)\b", body_text)
    )


def explicit_private_audio_public_claim(note: TaskNote, body_text: str) -> bool:
    frontmatter = note.frontmatter
    if any_truthy_mapping_key(
        frontmatter, {"private_audio_public_claim", "private_audio_route_leak"}
    ):
        return True
    has_private_audio = "private audio" in body_text or "private_audio" in body_text
    has_public_claim = explicit_public_claim(note, body_text)
    return has_private_audio and has_public_claim


def explicit_usb_semantic_claim(note: TaskNote, body_text: str) -> bool:
    frontmatter = note.frontmatter
    if any_truthy_mapping_key(frontmatter, {"usb_semantic_reliability_claim"}):
        return True
    return bool(
        "usb" in body_text
        and "bandwidth" in body_text
        and (
            re.search(r"\bproves? semantic (reliability|truth)\b", body_text)
            or "semantic_reliability_claim" in body_text
        )
    )


def explicit_missing_telemetry(note: TaskNote, body_text: str) -> bool:
    frontmatter = note.frontmatter
    telemetry = str(
        frontmatter.get("telemetry_state") or frontmatter.get("telemetry") or ""
    ).lower()
    return telemetry == "missing" or bool(
        re.search(r"\btelemetry[_-]?(state)?:?\s*missing\b", body_text)
    )


def any_truthy_mapping_key(mapping: JsonDict, names: set[str]) -> bool:
    return any(str(key).lower() in names and truthy(value) for key, value in mapping.items())


def task_blockers(note: TaskNote) -> list[str]:
    blockers = normalize_list(note.frontmatter.get("blocked_reason"))
    blockers.extend(normalize_list(note.frontmatter.get("blockers")))
    blockers.extend(normalize_list(note.frontmatter.get("hard_vetoes")))
    return [blocker for blocker in blockers if blocker and blocker.lower() != "null"]


def is_blocked(note: TaskNote) -> bool:
    tags = {tag.lower() for tag in normalize_list(note.frontmatter.get("tags"))}
    if note.status == "blocked" or task_blockers(note):
        return True
    active_statuses = {"claimed", "in_progress", "pr_open", "closed", "done", "completed"}
    return "blocked" in tags and note.status not in active_statuses


def stale_blocker(note: TaskNote, now: datetime) -> bool:
    if not is_blocked(note):
        return False
    updated_at = parse_iso_datetime(note.frontmatter.get("updated_at"))
    if updated_at is None:
        return True
    return now - updated_at > timedelta(days=STALE_BLOCKER_DAYS)


def family_values_from_vector(vector: BraidVector) -> JsonDict:
    return {
        "engagement": normalized(vector.engagement),
        "monetary": normalized(vector.monetary),
        "research": normalized(vector.research),
        "tree_effect": normalized(vector.tree_effect),
    }


def normalized(value: float | None) -> float:
    if value is None:
        return 0.0
    return round(max(0.0, min(value, 10.0)) / 10.0, 2)


def mode_ceiling_for_reasons(
    note: TaskNote,
    review_reasons: list[str],
    witness_summary: JsonDict,
) -> str:
    if any(reason in review_reasons for reason in NEGATIVE_REASON_ORDER):
        return "private"
    if is_blocked(note):
        return "private"
    if witness_summary["downgraded"] and any(
        word in note_text_for_detection(note)
        for word in ("public", "broadcast", "audience", "revenue", "monetiz", "livestream")
    ):
        return "private"
    if note.source_class == "closed_artifact":
        return "dry_run"
    return "private"


def max_public_claim_for_mode(mode_ceiling: str) -> str:
    if mode_ceiling == "public_live":
        return "runtime_marker_present_not_quality_or_truth_claim"
    if mode_ceiling == "public_archive":
        return "archived_artifact_existence_only"
    if mode_ceiling == "dry_run":
        return "internal_evidence_summary_only"
    return "none"


def task_row(
    note: TaskNote,
    *,
    hygiene: HygieneRead,
    witnesses: list[WitnessRead],
    witness_summary: JsonDict,
    now: datetime,
) -> JsonDict:
    if note.parse_error is not None:
        return parse_error_row(note, now)

    vector = braid_vector_from_frontmatter(note.frontmatter)
    recomputed = recompute_braid_score(vector)
    declared = vector.declared_score
    score_delta = None
    review_reasons: list[str] = []
    if declared is not None and recomputed is not None:
        score_delta = round(abs(declared - recomputed), 2)
        if score_delta > SCORE_DRIFT_THRESHOLD:
            review_reasons.append("score_delta_gt_1")

    if hygiene.status != "present":
        review_reasons.append(hygiene.error or "hygiene_state_missing")

    blockers = task_blockers(note)
    blocked = is_blocked(note)
    effective_score = declared if declared is not None else recomputed
    if blocked and effective_score is not None and effective_score >= HIGH_BRAID_THRESHOLD:
        review_reasons.append("blocked_high_braid")
    if stale_blocker(note, now):
        review_reasons.append("possible_stale_blocker")

    review_reasons.extend(negative_claim_reasons(note, witnesses))
    if (
        witness_summary["downgraded"]
        and effective_score is not None
        and effective_score >= HIGH_BRAID_THRESHOLD
    ):
        review_reasons.append("live_witness_downgrade")
    review_reasons = list(dict.fromkeys(review_reasons))

    hard_vetoes = blockers + [
        reason for reason in review_reasons if reason in NEGATIVE_REASON_ORDER
    ]
    mode_ceiling = mode_ceiling_for_reasons(note, review_reasons, witness_summary)
    max_public_claim = "none" if hard_vetoes else max_public_claim_for_mode(mode_ceiling)

    claimability_reason = "planning_value_only_wsjf_primary"
    if hard_vetoes:
        claimability_reason = "deny_wins:" + ",".join(hard_vetoes)
    elif hygiene.status != "present":
        claimability_reason = hygiene.error or "hygiene_state_missing"
    elif "live_witness_downgrade" in review_reasons:
        claimability_reason = "live_witness_downgrade"

    wsjf = as_float(note.frontmatter.get("wsjf"))
    priority = str(note.frontmatter.get("priority") or "").lower()
    implementation_gap = "none"
    if hard_vetoes:
        implementation_gap = "gate_blocked"
    elif "live_witness_downgrade" in review_reasons:
        implementation_gap = "runtime_witness_missing_or_degraded"
    elif note.status in {"offered", "claimed", "in_progress"}:
        implementation_gap = "planning_or_in_progress"

    row = {
        "kind": "value_node",
        "task_id": note.task_id,
        "title": str(note.frontmatter.get("title") or note.path.stem),
        "status": note.status,
        "priority": priority,
        "wsjf": wsjf,
        "dispatch_sort": {
            "primary": "wsjf",
            "wsjf": wsjf,
            "braid_tiebreak": effective_score,
        },
        "braid_vector": vector.as_dict(),
        "braid_declared": declared,
        "braid_recomputed": recomputed,
        "score_delta": score_delta,
        "evidence_sources": evidence_sources_for_task(note, hygiene, witnesses),
        "blockers": blockers,
        "review_reason": review_reasons,
        "value_node": {
            "id": note.task_id,
            "kind": "cc_task",
            "refs": [str(note.path)],
            "status": note.status,
        },
        "horizon": horizon_scores(effective_score, note.status),
        "claimability_reason": claimability_reason,
        "source_class": note.source_class,
        "mode_ceiling": mode_ceiling,
        "max_public_claim": max_public_claim,
        "realized": realized_values(note),
        "potential": family_values_from_vector(vector),
        "option_value": normalized(effective_score),
        "risk": round(
            min(1.0, max(0.0, vector.risk_penalty / 10.0 + (0.2 if hard_vetoes else 0.0))), 2
        ),
        "gate_posture": {
            "hard_vetoes": hard_vetoes,
            "dependency_truth": "unknown"
            if note.source_class == "planning_task"
            else "closed_artifact",
            "lane_fit": str(note.frontmatter.get("assigned_to") or "unknown"),
            "evidence_ceiling": mode_ceiling,
            "deny_wins": bool(hard_vetoes),
            "trend_can_upgrade_claim_confidence": False,
        },
        "implementation_gap": implementation_gap,
    }
    return row


def parse_error_row(note: TaskNote, now: datetime) -> JsonDict:
    return {
        "kind": "value_node",
        "task_id": note.path.stem,
        "title": note.path.stem,
        "status": "parse_error",
        "priority": "",
        "wsjf": None,
        "dispatch_sort": {"primary": "wsjf", "wsjf": None, "braid_tiebreak": None},
        "braid_vector": {},
        "braid_declared": None,
        "braid_recomputed": None,
        "score_delta": None,
        "evidence_sources": [{"source_class": note.source_class, "path": str(note.path)}],
        "blockers": [note.parse_error or "parse_error"],
        "review_reason": ["malformed_frontmatter"],
        "value_node": {
            "id": note.path.stem,
            "kind": "cc_task",
            "refs": [str(note.path)],
            "status": "parse_error",
        },
        "horizon": {"now": 0.0, "d7": 0.0, "d30": 0.0, "d90": 0.0},
        "claimability_reason": "malformed_frontmatter",
        "source_class": note.source_class,
        "mode_ceiling": "private",
        "max_public_claim": "none",
        "realized": {family: 0.0 for family in VALUE_FAMILIES},
        "potential": {family: 0.0 for family in VALUE_FAMILIES},
        "option_value": 0.0,
        "risk": 1.0,
        "gate_posture": {
            "hard_vetoes": [note.parse_error or "parse_error"],
            "dependency_truth": "unknown",
            "lane_fit": "unknown",
            "evidence_ceiling": "private",
            "deny_wins": True,
            "trend_can_upgrade_claim_confidence": False,
        },
        "implementation_gap": "parse_error",
        "generated_at": isoformat_z(now),
    }


def evidence_sources_for_task(
    note: TaskNote,
    hygiene: HygieneRead,
    witnesses: list[WitnessRead],
) -> list[JsonDict]:
    sources: list[JsonDict] = [
        {
            "source_class": note.source_class,
            "path": str(note.path),
            "status": note.status,
        },
        {
            "source_class": "relay_incident"
            if hygiene.status != "present"
            else "repo_implementation",
            "path": str(hygiene.path),
            "status": hygiene.status,
        },
    ]
    live_sources = [witness.as_dict() for witness in witnesses[:8]]
    sources.extend(live_sources)
    return sources


def realized_values(note: TaskNote) -> JsonDict:
    if note.source_class == "closed_artifact" or note.status in {"closed", "done", "completed"}:
        return {family: 0.5 for family in VALUE_FAMILIES}
    return {family: 0.0 for family in VALUE_FAMILIES}


def horizon_scores(score: float | None, status: str) -> JsonDict:
    base = normalized(score)
    if status in {"closed", "done", "completed"}:
        return {"now": base, "d7": base, "d30": base, "d90": base}
    return {
        "now": round(base * 0.25, 2),
        "d7": round(base * 0.50, 2),
        "d30": base,
        "d90": base,
    }


def anchor_rows(witnesses: list[WitnessRead], now: datetime) -> list[JsonDict]:
    anchors = {
        "executive-function-os": "executive_function_os",
        "voice-grounding-research": "voice_grounding_research",
        "semantic-affordance-economy": "semantic_affordance_economy",
        "visual-reverie-path": "visual_reverie_path",
        "livestream-studio-stack": "livestream_studio_stack",
        "monetary-safety-rail": "monetary_safety_rail",
        "publication-tree-effect": "publication_tree_effect",
        "research-instrument-mesh": "research_instrument_mesh",
        "governance-rail": "governance_rail",
    }
    hygiene_like = WitnessRead(
        witness_id="cc_hygiene_state",
        label="cc hygiene state",
        path=str(DEFAULT_HYGIENE_STATE),
        family="governance_rail",
        source_class="repo_implementation",
        status="ok",
        reasons=("task_graph_surface",),
        observed_at=isoformat_z(now),
        mode_ceiling="dry_run",
        max_public_claim="internal_evidence_summary_only",
    )
    family_witnesses = [*witnesses, hygiene_like]
    rows: list[JsonDict] = []
    for anchor_id, family in anchors.items():
        relevant = [witness for witness in family_witnesses if witness.family == family]
        bad = [witness for witness in relevant if witness.status in BAD_WITNESS_STATUSES]
        ok_count = sum(1 for witness in relevant if witness.status == "ok")
        total = len(relevant)
        realized = round(ok_count / total, 2) if total else 0.0
        risk = round(len(bad) / total, 2) if total else 1.0
        mode_ceiling = "dry_run" if relevant and not bad else "private"
        reasons = [reason for witness in bad for reason in witness.reasons]
        claimability = (
            "live_witnessed_presence_only"
            if mode_ceiling != "private"
            else "witness_gap:" + ",".join(reasons[:4] or ["missing_witness_family"])
        )
        rows.append(
            {
                "kind": "value_node",
                "task_id": anchor_id,
                "title": anchor_id.replace("-", " ").title(),
                "status": "implementation_state",
                "priority": "",
                "wsjf": None,
                "dispatch_sort": {"primary": "wsjf", "wsjf": None, "braid_tiebreak": realized * 10},
                "braid_vector": {},
                "braid_declared": None,
                "braid_recomputed": round(realized * 10, 2),
                "score_delta": None,
                "evidence_sources": [witness.as_dict() for witness in relevant],
                "blockers": [witness.witness_id for witness in bad],
                "review_reason": ["live_witness_downgrade"] if bad else [],
                "value_node": {
                    "id": anchor_id,
                    "kind": "implementation_anchor",
                    "refs": [witness.path for witness in relevant],
                    "status": "implementation_state",
                },
                "horizon": {"now": realized, "d7": realized, "d30": realized, "d90": realized},
                "claimability_reason": claimability,
                "source_class": "live_runtime" if relevant else "planning_task",
                "mode_ceiling": mode_ceiling,
                "max_public_claim": max_public_claim_for_mode(mode_ceiling),
                "realized": {family_name: realized for family_name in VALUE_FAMILIES},
                "potential": {family_name: 1.0 for family_name in VALUE_FAMILIES},
                "option_value": realized,
                "risk": risk,
                "gate_posture": {
                    "hard_vetoes": [witness.witness_id for witness in bad],
                    "dependency_truth": "witnessed" if relevant and not bad else "unknown",
                    "lane_fit": "operator_dashboard",
                    "evidence_ceiling": mode_ceiling,
                    "deny_wins": bool(bad),
                    "trend_can_upgrade_claim_confidence": False,
                },
                "implementation_gap": "none" if not bad else "runtime_witness_missing_or_degraded",
            }
        )
    return rows


def build_snapshot(
    *,
    task_root: Path = DEFAULT_TASK_ROOT,
    hygiene_path: Path = DEFAULT_HYGIENE_STATE,
    now: datetime | None = None,
    witness_specs: list[WitnessSpec] | None = None,
    include_systemd: bool = True,
) -> JsonDict:
    current_time = now or utc_now()
    snapshot_id = f"braid-{isoformat_z(current_time).replace(':', '').replace('-', '')}"
    notes = load_task_notes(task_root)
    hygiene = load_hygiene_state(hygiene_path)
    witnesses = collect_witnesses(
        current_time,
        witness_specs=witness_specs,
        include_systemd=include_systemd,
    )
    witness_summary = summarize_witnesses(witnesses)
    rows = [
        task_row(
            note,
            hygiene=hygiene,
            witnesses=witnesses,
            witness_summary=witness_summary,
            now=current_time,
        )
        for note in notes
    ]
    rows.extend(anchor_rows(witnesses, current_time))
    return {
        "snapshot_id": snapshot_id,
        "generated_at": isoformat_z(current_time),
        "policy": {
            "dispatch_sort_key": "wsjf",
            "braid_authority": "advisory_dashboard_only",
            "trend_can_upgrade_claim_confidence": False,
            "task_state_mutation": False,
        },
        "task_root": str(task_root),
        "hygiene": hygiene.as_dict(),
        "witness_summary": witness_summary,
        "witnesses": [witness.as_dict() for witness in witnesses],
        "rows": rows,
    }


def sort_key_wsjf_then_braid(row: JsonDict) -> tuple[float, float]:
    wsjf = row.get("wsjf")
    braid = row.get("braid_declared") or row.get("braid_recomputed")
    return (
        float(wsjf) if isinstance(wsjf, int | float) and not math.isnan(wsjf) else -1.0,
        float(braid) if isinstance(braid, int | float) and not math.isnan(braid) else -1.0,
    )


def task_rows(snapshot: JsonDict) -> list[JsonDict]:
    return [
        row
        for row in snapshot["rows"]
        if isinstance(row.get("value_node"), dict) and row["value_node"].get("kind") == "cc_task"
    ]


def render_dashboard(snapshot: JsonDict, *, limit: int = 12) -> str:
    rows = task_rows(snapshot)
    offered = sorted(
        [
            row
            for row in rows
            if row.get("status") == "offered" and str(row.get("priority")).lower() in {"p0", "p1"}
        ],
        key=sort_key_wsjf_then_braid,
        reverse=True,
    )[:limit]
    blocked = sorted(
        [
            row
            for row in rows
            if (
                row.get("status") == "blocked"
                or "blocked_high_braid" in row.get("review_reason", [])
                or "possible_stale_blocker" in row.get("review_reason", [])
            )
        ],
        key=sort_key_wsjf_then_braid,
        reverse=True,
    )[:limit]
    deltas = sorted(
        [row for row in rows if "score_delta_gt_1" in row.get("review_reason", [])],
        key=lambda row: float(row.get("score_delta") or 0.0),
        reverse=True,
    )[:limit]
    anchors = [
        row
        for row in snapshot["rows"]
        if isinstance(row.get("value_node"), dict)
        and row["value_node"].get("kind") == "implementation_anchor"
    ]
    degraded_witnesses = [
        witness for witness in snapshot["witnesses"] if witness["status"] in BAD_WITNESS_STATUSES
    ][:limit]

    lines = [
        "# Braided Value Snapshot",
        "",
        f"Generated: `{snapshot['generated_at']}`",
        f"Snapshot: `{snapshot['snapshot_id']}`",
        "",
        "> WSJF remains the dispatch sort key. Braid scores are advisory and do not "
        "authorize public, monetary, or research-truth claims. Deny-wins gates and "
        "evidence ceilings remain binding.",
        "",
        "## Gate Summary",
        "",
        f"- Hygiene state: `{snapshot['hygiene']['status']}` (`{snapshot['hygiene']['path']}`)",
        f"- Witnesses downgraded: `{snapshot['witness_summary']['downgraded']}` / "
        f"`{snapshot['witness_summary']['total']}`",
        "- Trend, audience, and revenue signals cannot upgrade claim confidence.",
        "",
        "## Top Offered P0/P1 Tasks (WSJF Primary)",
        "",
        table(
            offered,
            columns=("task_id", "priority", "wsjf", "braid_declared", "claimability_reason"),
        ),
        "",
        "## Blocked High-Braid Or Stale-Blocker Tasks",
        "",
        table(
            blocked,
            columns=("task_id", "status", "wsjf", "braid_declared", "review_reason"),
        ),
        "",
        "## Score Delta Review (> 1.0)",
        "",
        table(
            deltas,
            columns=("task_id", "wsjf", "braid_declared", "braid_recomputed", "score_delta"),
        ),
        "",
        "## Runtime Witness Downgrades",
        "",
        witness_table(degraded_witnesses),
        "",
        "## Implementation-State Braid",
        "",
        table(
            anchors,
            columns=("task_id", "braid_recomputed", "mode_ceiling", "claimability_reason"),
        ),
        "",
        "## Snapshot Output",
        "",
        f"- Ledger: `{DEFAULT_LEDGER}`",
        "- Task state mutation: `false`",
        "- Public/live behavior changes: `false`",
        "",
    ]
    return "\n".join(lines)


def table(rows: list[JsonDict], columns: tuple[str, ...]) -> str:
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    if not rows:
        return "\n".join([header, separator, "| " + " | ".join("-" for _ in columns) + " |"])
    rendered = [header, separator]
    for row in rows:
        rendered.append(
            "| " + " | ".join(format_table_value(row.get(column)) for column in columns) + " |"
        )
    return "\n".join(rendered)


def witness_table(rows: list[JsonDict]) -> str:
    columns = ("witness_id", "family", "status", "reasons")
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    if not rows:
        return "\n".join([header, separator, "| " + " | ".join("-" for _ in columns) + " |"])
    rendered = [header, separator]
    for row in rows:
        rendered.append(
            "| " + " | ".join(format_table_value(row.get(column)) for column in columns) + " |"
        )
    return "\n".join(rendered)


def format_table_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "-"
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    text = str(value).replace("\n", " ")
    return text.replace("|", "\\|")


def write_outputs(snapshot: JsonDict, *, dashboard_path: Path, ledger_path: Path) -> None:
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)
    dashboard_path.write_text(render_dashboard(snapshot), encoding="utf-8")
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        for row in snapshot["rows"]:
            payload = {
                "snapshot_id": snapshot["snapshot_id"],
                "generated_at": snapshot["generated_at"],
                "policy": snapshot["policy"],
                **row,
            }
            handle.write(json.dumps(payload, sort_keys=True) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", type=Path, default=DEFAULT_TASK_ROOT)
    parser.add_argument("--hygiene-state", type=Path, default=DEFAULT_HYGIENE_STATE)
    parser.add_argument("--dashboard-path", type=Path, default=DEFAULT_DASHBOARD)
    parser.add_argument("--ledger-path", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--now", help="UTC ISO timestamp for deterministic runs.")
    parser.add_argument(
        "--no-write", action="store_true", help="Print summary JSON without writing files."
    )
    parser.add_argument(
        "--skip-systemd", action="store_true", help="Skip read-only systemd probes."
    )
    parser.add_argument(
        "--verify-auto-gtm-predictions",
        action="store_true",
        help=(
            "Verify the seven Auto-GTM cc-tasks compute braid scores within "
            "+/- 0.1 of the spec's predicted re-ranking. Exits non-zero on "
            "any drift. Implies --no-write."
        ),
    )
    parser.add_argument(
        "--verify-v1-stability",
        action="store_true",
        help=(
            "Verify all braid_schema=1 tasks compute identically to their "
            "declared braid_score frontmatter (within +/- 0.1). Exits "
            "non-zero on drift. Implies --no-write."
        ),
    )
    parser.add_argument(
        "--verify-auto-gtm-predictions-v2",
        action="store_true",
        help=(
            "Verify the seven Auto-GTM cc-tasks compute braid v2.0 scores "
            "within +/- 0.1 of the formula-derived spec table. Exits "
            "non-zero on drift OR when a task's braid_schema is not '2'. "
            "Implies --no-write."
        ),
    )
    parser.add_argument(
        "--predictions-tolerance",
        type=float,
        default=0.1,
        help="Tolerance (delta) for verification modes (default: 0.1).",
    )
    return parser


# Predicted v1.1 re-ranking for the seven Auto-GTM batch tasks, derived
# from the v1.1 formula × frontmatter dimensions snapshotted 2026-05-01T15:10Z.
# Source of truth: docs/superpowers/specs/2026-05-01-braid-schema-v11-design.md
# §Predicted re-ranking. Hardcoded here so the CI / verification runs
# don't depend on parsing the spec markdown.
#
# History: the first draft of the spec carried scratch predictions
# (wyoming=8.0, refusal-brief=8.5, etc.) authored before formula
# weights were finalized. Those values were unreachable from the
# formula even with maxed-out new dimensions. cc-task
# `braid-v11-spec-doc-and-prediction-reconcile` resolved the audit
# discrepancy by adopting formula-derived values as canonical.
SPEC_AUTO_GTM_PREDICTIONS: dict[str, float] = {
    "wyoming-llc-dba-legal-entity-bootstrap": 6.28,
    "citable-nexus-front-door-static-site": 6.88,
    "publication-bus-monetization-rails-surfaces": 5.70,
    "immediate-q2-2026-grant-submission-batch": 5.85,
    "refusal-brief-article-50-case-study": 7.50,
    "eu-ai-act-art-50-c2pa-watermark-fingerprint-mvp": 5.97,
    "auto-clip-shorts-livestream-pipeline": 5.03,
}


# V1 stability carveout: v1 tasks whose declared `braid_score` predates
# the formal v1 formula's inclusion in cc-readme.md and was operator-set
# or hand-scored against an earlier weighting. Per cc-readme invariant
# ("no retro-scoring"), the declared values stay as authored. The
# verifier exits 0 when every NON-carveout v1 task passes ±0.1 tolerance.
#
# Adding a new v1 task after 2026-05-02 that fails the check signals a
# real drift (formula change, frontmatter typo, runner bug) and is NOT
# auto-carved-out — the carveout is reviewed (and pruned wherever a task
# transitions to v1.1 or its declared score is operator-revised) at
# every braid schema bump.
#
# Source of truth: docs/superpowers/specs/2026-05-01-braid-schema-v11-design.md
# §V1 stability and carveout.
# Predicted v2.0 re-ranking for the seven Auto-GTM batch tasks. Per the
# v1.1 reconcile precedent (cc-task
# `braid-v11-spec-doc-and-prediction-reconcile`), the spec §3.6 worked
# examples in
# `docs/superpowers/specs/2026-05-04-braid-v2-and-wsjf-expansion-design.md`
# are illustrative — formula-derived values are canonical. These values
# were computed by running the v2 formula (ρ=-2.0, β=1.3, default weights,
# witness_freshness=1.0) over each task's frontmatter dimensions at the
# same NOW reference (2026-05-01T15:10Z) used for SPEC_AUTO_GTM_PREDICTIONS.
#
# Verifier sub-cases per task:
#   - ``braid_schema`` must equal ``'2'`` — fails otherwise.
#   - All five base dimensions populated.
#   - No Layer 1 gate fires (deny_wins, strain >= 3, deadline-zero,
#     mode_ceiling/max_public_claim violation).
#   - Computed score within ±0.1 of the formula-derived value below.
#
# Until vault tasks migrate to ``braid_schema: 2``, this verifier exits
# non-zero with informative per-task FAIL lines. That is the spike's
# intended behavior — the formula ships in this PR; vault migration is
# Phase E proper.
SPEC_AUTO_GTM_PREDICTIONS_V2: dict[str, float] = {
    "wyoming-llc-dba-legal-entity-bootstrap": 6.97,
    "citable-nexus-front-door-static-site": 7.87,
    "publication-bus-monetization-rails-surfaces": 6.31,
    "immediate-q2-2026-grant-submission-batch": 5.95,
    "refusal-brief-article-50-case-study": 8.83,
    "eu-ai-act-art-50-c2pa-watermark-fingerprint-mvp": 6.04,
    "auto-clip-shorts-livestream-pipeline": 5.38,
}


BRAID_V1_STABILITY_CARVEOUT: frozenset[str] = frozenset(
    {
        "gcp-youtube-quota-extension-runner",
        "github-public-claim-evidence-gate",
        "github-readme-profile-current-project-refresh",
        "multimodal-environmental-evidence-envelope",
        "operator-dossier-value-braid-adapter",
        "playwright-grant-submission-runner",
        "private-to-public-bridge-governor",
        "public-package-surface-claim-discipline",
        "wyoming-llc-bootstrap-runner",
        "antigravity-unified-self-grounding-tranche-revalidation",
        "aperture-registry-reference-slice",
        "braided-value-formal-model-and-wsjf-calibration",
        "braided-value-snapshot-runner-and-dashboard",
        "conversion-target-readiness-threshold-matrix",
        "daimonion-private-voice-broadcast-leak-hard-stop",
        "daimonion-quarantine-drift-watchdog",
        "github-public-surface-live-state-reconcile",
        "github-publication-log-value-braid-adapter",
        "grafana-panel-import-runner",
        "operator-predictive-dossier-productization-contract",
        "operator-quality-posterior-read-model",
        "orcid-config-write-automation",
        "private-voice-restore-witness-ladder",
        "productization-blocker-edge-refresh-2026-05-01",
        "runway-bigpitch-trailer-and-submit",
        "self-grounding-ontology-formalization",
        "temporal-deictic-reference-resolver",
        "unified-awareness-route-claim-envelope",
    }
)


def _verify_auto_gtm_predictions(
    *, task_root: Path, now: datetime, tolerance: float = 0.1
) -> tuple[int, list[str]]:
    """Compare each Auto-GTM task's runner-computed v1.1 score to the spec table.

    Returns ``(exit_code, lines)``. ``exit_code == 0`` only when EVERY task
    matches the spec prediction within ``tolerance``. ``lines`` carries
    human-readable per-task pass/fail records.
    """

    notes_by_id: dict[str, TaskNote] = {}
    for note in load_task_notes(task_root):
        notes_by_id[note.task_id] = note
    # Also walk closed/ for tasks that have already shipped (e.g.,
    # citable-nexus-front-door-static-site landed before the migration).
    closed_root = task_root / "closed"
    if closed_root.exists():
        for note in load_task_notes(closed_root):
            notes_by_id.setdefault(note.task_id, note)

    lines: list[str] = []
    failures = 0
    for task_id, predicted in SPEC_AUTO_GTM_PREDICTIONS.items():
        note = notes_by_id.get(task_id)
        if note is None:
            lines.append(f"FAIL {task_id}: task not found in vault")
            failures += 1
            continue
        vector = braid_vector_from_frontmatter(note.frontmatter)
        if not vector.is_v11:
            lines.append(f"FAIL {task_id}: braid_schema is {vector.schema!r}, expected '1.1'")
            failures += 1
            continue
        computed = recompute_braid_score(vector, now=now)
        if computed is None:
            lines.append(f"FAIL {task_id}: incomplete dimensions, score not computable")
            failures += 1
            continue
        delta = computed - predicted
        if abs(delta) > tolerance:
            lines.append(
                f"FAIL {task_id}: computed={computed:.2f} predicted={predicted:.2f} "
                f"delta={delta:+.2f} (tolerance +/-{tolerance})"
            )
            failures += 1
        else:
            lines.append(
                f"OK   {task_id}: computed={computed:.2f} predicted={predicted:.2f} "
                f"delta={delta:+.2f}"
            )
    return (1 if failures > 0 else 0), lines


def _verify_auto_gtm_predictions_v2(
    *, task_root: Path, now: datetime, tolerance: float = 0.1
) -> tuple[int, list[str]]:
    """Compare each Auto-GTM task's runner-computed v2.0 score to the formula-derived table.

    Mirrors ``_verify_auto_gtm_predictions`` (v1.1) but routes to v2.
    Per the v1.1 reconcile precedent, the spec table values are
    illustrative — the formula is canonical and predictions are
    formula-derived at NOW = 2026-05-01T15:10Z.

    Returns ``(exit_code, lines)``. ``exit_code == 0`` only when every
    task is on ``braid_schema: 2`` AND its computed score matches the
    table within ``tolerance``. Per the spike's stated behavior, this
    will exit non-zero until vault tasks migrate to schema=2 in Phase E
    proper — the FAIL lines clearly identify which migration step is
    missing.
    """

    notes_by_id: dict[str, TaskNote] = {}
    for note in load_task_notes(task_root):
        notes_by_id[note.task_id] = note
    closed_root = task_root / "closed"
    if closed_root.exists():
        for note in load_task_notes(closed_root):
            notes_by_id.setdefault(note.task_id, note)

    lines: list[str] = []
    failures = 0
    for task_id, predicted in SPEC_AUTO_GTM_PREDICTIONS_V2.items():
        note = notes_by_id.get(task_id)
        if note is None:
            lines.append(f"FAIL {task_id}: task not found in vault")
            failures += 1
            continue
        vector = braid_vector_from_frontmatter(note.frontmatter)
        if not vector.is_v2:
            lines.append(f"FAIL {task_id}: braid_schema is {vector.schema!r}, expected '2'")
            failures += 1
            continue
        computed = recompute_braid_score(vector, now=now)
        if computed is None:
            lines.append(
                f"FAIL {task_id}: score is None (incomplete dimensions or Layer 1 gate fired)"
            )
            failures += 1
            continue
        delta = computed - predicted
        if abs(delta) > tolerance:
            lines.append(
                f"FAIL {task_id}: computed={computed:.2f} predicted={predicted:.2f} "
                f"delta={delta:+.2f} (tolerance +/-{tolerance})"
            )
            failures += 1
        else:
            lines.append(
                f"OK   {task_id}: computed={computed:.2f} predicted={predicted:.2f} "
                f"delta={delta:+.2f}"
            )
    return (1 if failures > 0 else 0), lines


def _verify_v1_stability(*, task_root: Path, tolerance: float = 0.1) -> tuple[int, list[str]]:
    """Verify v1 tasks compute identically to their declared braid_score.

    Walks ``active/`` and ``closed/`` for every task with
    ``braid_schema=1`` and a populated ``braid_score``; recomputes via
    the v1 formula; reports drift.
    """

    lines: list[str] = []
    failures = 0
    checked = 0
    notes: list[TaskNote] = list(load_task_notes(task_root))
    closed_root = task_root / "closed"
    if closed_root.exists():
        notes.extend(load_task_notes(closed_root))
    seen: set[str] = set()
    carved = 0
    for note in notes:
        if note.task_id in seen:
            continue
        seen.add(note.task_id)
        vector = braid_vector_from_frontmatter(note.frontmatter)
        if vector.is_v11:
            continue
        if vector.declared_score is None or not vector.complete:
            continue
        computed = recompute_braid_score(vector)
        if computed is None:
            continue
        delta = computed - vector.declared_score
        if abs(delta) > tolerance:
            if note.task_id in BRAID_V1_STABILITY_CARVEOUT:
                carved += 1
                continue
            lines.append(
                f"FAIL {note.task_id}: computed={computed:.2f} "
                f"declared={vector.declared_score:.2f} delta={delta:+.2f}"
            )
            failures += 1
        else:
            checked += 1
    if not lines:
        lines.append(
            f"OK   v1 stability: {checked} v1 task(s) within +/- {tolerance}; "
            f"{carved} carveout exempt"
        )
    return (1 if failures > 0 else 0), lines


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    now = parse_iso_datetime(args.now) if args.now else utc_now()
    if now is None:
        parser.error("--now must be an ISO timestamp")
    if args.verify_auto_gtm_predictions:
        exit_code, lines = _verify_auto_gtm_predictions(
            task_root=args.task_root, now=now, tolerance=args.predictions_tolerance
        )
        for line in lines:
            print(line)
        return exit_code
    if args.verify_v1_stability:
        exit_code, lines = _verify_v1_stability(
            task_root=args.task_root, tolerance=args.predictions_tolerance
        )
        for line in lines:
            print(line)
        return exit_code
    if args.verify_auto_gtm_predictions_v2:
        exit_code, lines = _verify_auto_gtm_predictions_v2(
            task_root=args.task_root, now=now, tolerance=args.predictions_tolerance
        )
        for line in lines:
            print(line)
        return exit_code
    snapshot = build_snapshot(
        task_root=args.task_root,
        hygiene_path=args.hygiene_state,
        now=now,
        include_systemd=not args.skip_systemd,
    )
    if args.no_write:
        print(
            json.dumps(
                {
                    "snapshot_id": snapshot["snapshot_id"],
                    "generated_at": snapshot["generated_at"],
                    "rows": len(snapshot["rows"]),
                    "hygiene": snapshot["hygiene"],
                    "witness_summary": snapshot["witness_summary"],
                    "policy": snapshot["policy"],
                },
                sort_keys=True,
            )
        )
        return 0
    write_outputs(snapshot, dashboard_path=args.dashboard_path, ledger_path=args.ledger_path)
    print(
        json.dumps(
            {
                "snapshot_id": snapshot["snapshot_id"],
                "dashboard_path": str(args.dashboard_path),
                "ledger_path": str(args.ledger_path),
                "rows": len(snapshot["rows"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
