"""Operator predictive dossier productization contract (Phase 1).

Typed atomic row schema for the operator predictive dossier — the
private, evidence-bearing prediction ledger that supports feature
specification, WSJF / value-braid calibration, and product development
without copying raw private histories into prompts or public surfaces.

Phase 1 delivers the row type vocabulary, the atomic row model, the
fail-closed validators (raw transcript / secret / browser-store /
biometric / side-chat / non-operator-person leakage detection), the
prompt-visible render rules (redacted, ceiling-respecting), and unit
tests covering the acceptance criteria. Subsequent phases extend the
ingestion surface (transcripts → evidence rows), hook the value-braid
adapter, and wire the semantic-recruitment recall path.

Spec: ``hapax-research/specs/2026-05-01-operator-predictive-dossier-productization-spine.md``
Parent audit: ``hapax-research/audits/2026-05-01-operator-predictive-dossier-value-braid-fleet-synthesis.md``
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Type literals — every enum the spec calls out as required vocabulary.
# Keep these tight; do not add ad-hoc values. Phase-2 expansion goes
# through the spec, not through Python literals.
# ---------------------------------------------------------------------------

type RowStatus = Literal["active", "stale", "superseded", "blocked"]

type Vertical = Literal[
    "research",
    "management",
    "studio",
    "personal",
    "health",
]

type OperatorDimension = Literal[
    "identity",
    "neurocognitive",
    "values",
    "communication_style",
    "relationships",
    "work_patterns",
    "energy_and_attention",
    "information_seeking",
    "creative_process",
    "tool_usage",
    "communication_patterns",
]

type ConstraintLabel = Literal[
    "operator_labor",
    "resource_contention",
    "privacy",
    "rights",
    "public_mode",
]

type OutcomeKind = Literal[
    "preference",
    "behavior",
    "attention",
    "energy",
    "communication",
    "creative_flow",
    "feature_need",
    "risk",
]

type TemporalBand = Literal[
    "impression",
    "retention_tick",
    "retention_session",
    "protention_minutes",
    "now",
    "d7",
    "d30",
    "d90",
    "strategic",
]

type UncertaintyReason = Literal[
    "missing_evidence",
    "stale_evidence",
    "conflicting_evidence",
    "inferred_only",
    "low_support",
]

type SourceClass = Literal[
    "raw_primary",
    "governed_authored",
    "derivative_summary",
    "volatile_sensitive",
]

# Tier-1 = sufficient on its own; Tier-2+ = needs at least one
# independent corroborating source per the spec's evidence policy.
TIER_1_SOURCE_CLASSES: frozenset[SourceClass] = frozenset({"governed_authored"})

type Authority = Literal[
    "operator_declared",
    "runtime_witness",
    "repo_implementation",
    "closed_artifact",
    "relay_status",
    "planning",
    "hypothesis",
]

type ModeCeiling = Literal[
    "private",
    "dry_run",
    "public_archive",
    "public_live",
    "public_monetizable",
]

type ConsentLabel = Literal["operator_only", "person_adjacent", "consent_required"]
type PrivacyLabel = Literal["private", "redacted", "public_safe"]
type ClaimAuthority = Literal["unknown", "provisional", "assertable", "grounding_act"]

type RecruitmentRelation = Literal[
    "provides_evidence_for",
    "biases",
    "vetoes",
    "requires",
]

# Mode ceilings that must NEVER appear in prompt-visible renderings.
NEVER_PROMPT_VISIBLE_CEILINGS: frozenset[ModeCeiling] = frozenset()

# Privacy labels that may render in a prompt-visible summary. ``private``
# rows can render with redaction (``privacy_label="private"`` requires
# the redacted summary path). ``redacted`` is post-redaction; ``public_safe``
# is only set after full review.
PROMPT_VISIBLE_PRIVACY_LABELS: frozenset[PrivacyLabel] = frozenset({"redacted", "public_safe"})

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class DossierModel(BaseModel):
    """Frozen-by-default base, mirrors the matrix module's idiom."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SignalObservation(DossierModel):
    """One observed or derived signal feeding the row's context clause."""

    name: str = Field(min_length=1)
    value: str = Field(min_length=1)
    observed_at: datetime
    source_ref: str = Field(min_length=1)


class EvidenceRef(DossierModel):
    """Pointer to an evidence artifact backing one row.

    The pointer is an excerpt anchor (line / event id), not the raw
    content. Raw content stays in its store; the row only references
    it by class + path + observed_at. ``volatile_sensitive`` rows must
    never have their excerpts inlined; the renderer will refuse.
    """

    path: str = Field(min_length=1)
    source_class: SourceClass
    observed_at: datetime
    excerpt_pointer: str = Field(min_length=1)


class ProductSpec(DossierModel):
    """What the row implies for product / feature / task work."""

    implication: str = Field(min_length=1)
    acceptance_signal: str = Field(min_length=1)
    negative_constraint: str = Field(min_length=1)


class ValueBraid(DossierModel):
    """Post-gate value-braid scoring vector + ceilings.

    Per the spec's anti-overclaim policy, value-braid scores from this
    packet cannot upgrade truth, rights, consent, egress, public,
    monetization, or research-validity gates. The ledger surfaces the
    score; downstream gates are sovereign.
    """

    engagement: int = Field(ge=0, le=10)
    monetary: int = Field(ge=0, le=10)
    research: int = Field(ge=0, le=10)
    tree_effect: int = Field(ge=0, le=10)
    evidence_confidence: int = Field(ge=0, le=10)
    risk_penalty: float = Field(ge=0.0)
    mode_ceiling: ModeCeiling
    hard_vetoes: tuple[str, ...] = ()


class SemanticRecruitment(DossierModel):
    """Recruitment metadata for the affordance pipeline.

    When ``dossier_row_recruitable=False`` (the safer default) the row
    cannot enter the semantic-recruitment retrieval path at all. Phase
    2+ flips selected rows on per spec; Phase 1 leaves them all off.
    """

    dossier_row_recruitable: bool
    embedded_description: str = Field(min_length=1)
    domain_tags: tuple[str, ...] = ()
    family_tags: tuple[str, ...] = ()
    relations: tuple[RecruitmentRelation, ...] = ()
    target_affordance_ids: tuple[str, ...] = ()


class Governance(DossierModel):
    """Per-row governance ceilings. ``deny_wins`` is non-overridable."""

    consent_label: ConsentLabel
    privacy_label: PrivacyLabel
    claim_authority: ClaimAuthority
    deny_wins: Literal[True] = True


class CalibrationCounter(DossierModel):
    """Calibration counters updated by outcome-feedback (Phase 2+)."""

    supporting_observations: int = Field(default=0, ge=0)
    contradicting_observations: int = Field(default=0, ge=0)
    corrections: int = Field(default=0, ge=0)
    last_confirmed_at: datetime | None = None


class Prediction(DossierModel):
    """The falsifiable then-clause + its temporal posture."""

    outcome_kind: OutcomeKind
    statement: str = Field(min_length=1)
    temporal_band: TemporalBand
    probability: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainty_reason: UncertaintyReason
    calibration: CalibrationCounter = Field(default_factory=CalibrationCounter)


class RowContext(DossierModel):
    """The condition (if-clause) + signal observations + constraints."""

    condition: str = Field(min_length=1)
    signals: tuple[SignalObservation, ...] = ()
    constraints: tuple[ConstraintLabel, ...] = ()


class DossierRow(DossierModel):
    """One atomic operator-predictive-dossier row.

    All fourteen sub-blocks from the spec are required. The row is
    sufficient (per the spec's sufficiency test) when:

    - condition is non-empty (testable);
    - prediction.statement is non-empty (falsifiable);
    - temporal_band is named;
    - evidence has ≥1 ref carrying source_class;
    - probability ≠ confidence (distinct fields, both required);
    - uncertainty_reason is named;
    - product_spec.implication AND negative_constraint are non-empty;
    - value_braid is post-gate;
    - governance ceilings are explicit;
    - calibration counters exist (zero-valued OK pre-feedback).

    Pydantic validation ensures all required fields are present;
    ``model_validator`` enforces the cross-field invariants that single
    fields cannot.
    """

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]+$")
    status: RowStatus
    verticals: tuple[Vertical, ...] = Field(min_length=1)
    operator_dimensions: tuple[OperatorDimension, ...] = Field(min_length=1)
    context: RowContext
    prediction: Prediction
    evidence_refs: tuple[EvidenceRef, ...] = Field(min_length=1)
    freshness_half_life_days: float = Field(gt=0.0)
    authority: Authority
    product_spec: ProductSpec
    value_braid: ValueBraid
    semantic_recruitment: SemanticRecruitment
    governance: Governance

    @model_validator(mode="after")
    def _validate_evidence_sufficiency(self) -> Self:
        """Spec §"Evidence Policy": every claim-affecting row needs
        either one Tier-1 source or two independent sources."""

        if self.status not in {"active"}:
            return self  # stale / superseded / blocked rows aren't claim-affecting
        tier_1 = [r for r in self.evidence_refs if r.source_class in TIER_1_SOURCE_CLASSES]
        if tier_1:
            return self
        # No tier-1: require at least 2 independent (distinct path) refs.
        distinct_paths = {r.path for r in self.evidence_refs}
        if len(distinct_paths) < 2:
            msg = (
                f"row {self.id!r} is active but lacks Tier-1 evidence and has only "
                f"{len(distinct_paths)} independent source(s); needs ≥2 independent "
                "or 1 Tier-1 (governed_authored) source per spec evidence policy"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _validate_governance_consistency(self) -> Self:
        """Public claim authority cannot exceed mode ceiling.

        A row whose ``value_braid.mode_ceiling`` is ``private`` must not
        carry ``governance.claim_authority`` of ``assertable`` or
        ``grounding_act`` — those imply prompt-visible authoritative
        speech and would be a category error against the private ceiling.
        """

        ceiling = self.value_braid.mode_ceiling
        authority = self.governance.claim_authority
        if ceiling == "private" and authority in {"assertable", "grounding_act"}:
            msg = (
                f"row {self.id!r}: claim_authority={authority!r} is incompatible with "
                f"mode_ceiling={ceiling!r}; private ceiling caps authority at provisional"
            )
            raise ValueError(msg)
        return self


class OperatorPredictiveDossier(DossierModel):
    """Container for atomic rows + manifest-level metadata."""

    schema_version: Literal[1] = 1
    subject: Literal["operator"] = "operator"
    generated_at: datetime
    rows: tuple[DossierRow, ...]

    def by_id(self) -> dict[str, DossierRow]:
        return {row.id: row for row in self.rows}

    def active_rows(self) -> tuple[DossierRow, ...]:
        return tuple(row for row in self.rows if row.status == "active")

    def for_vertical(self, vertical: Vertical) -> tuple[DossierRow, ...]:
        return tuple(row for row in self.active_rows() if vertical in row.verticals)

    def for_operator_dimension(
        self,
        dimension: OperatorDimension,
    ) -> tuple[DossierRow, ...]:
        return tuple(row for row in self.active_rows() if dimension in row.operator_dimensions)


# ---------------------------------------------------------------------------
# Fail-closed leak detection — refuse to render rows whose evidence or
# product-spec text contains raw transcripts, secrets, browser-store
# data, biometrics, side-chat, or non-operator-person material.
# ---------------------------------------------------------------------------


# Keep these patterns conservative. Matching is case-insensitive on the
# rendered text (statement / implication / negative_constraint /
# embedded_description). Matches in evidence_refs.path are only flagged
# when the path appears under a forbidden tree; the path itself is fine
# as a pointer.

# Raw transcript markers — codex / claude conversation captures.
_RAW_TRANSCRIPT_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\b(?:user|assistant)\s*:\s*", re.IGNORECASE),
    re.compile(r"<\|im_start\|>|<\|im_end\|>"),
    re.compile(r"\bToolUseBlock\b|\bToolResultBlock\b"),
)

# Secret-shaped markers.
_SECRET_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{35}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
)

# Browser-store / personal data shapes.
_BROWSER_STORE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bcookies?\.sqlite\b", re.IGNORECASE),
    re.compile(r"\b(?:Login|History) Data\b"),
    re.compile(r"\bChrome Safe Storage\b"),
)

# Biometric data shapes.
_BIOMETRIC_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bheart_rate_bpm\s*[:=]\s*\d+\b", re.IGNORECASE),
    re.compile(r"\bhrv_ms\s*[:=]\s*\d+\b", re.IGNORECASE),
    re.compile(r"\bblood_pressure\b", re.IGNORECASE),
    re.compile(r"\bskin_temperature\b", re.IGNORECASE),
)

# Side-chat — DM transcripts, person-named conversations.
_SIDE_CHAT_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bDM(?:\s+with|\s+from|\s+thread)\b", re.IGNORECASE),
    re.compile(r"\b#dm-\b", re.IGNORECASE),
    re.compile(r"\bSlack\s+thread\b", re.IGNORECASE),
)


class LeakFinding(DossierModel):
    """One detected leak in a row's prompt-visible surface."""

    row_id: str
    surface: str  # "statement" / "implication" / "negative_constraint" / "embedded_description"
    leak_kind: Literal[
        "raw_transcript",
        "secret",
        "browser_store",
        "biometric",
        "side_chat",
        "non_operator_person",
    ]
    pattern_excerpt: str = Field(min_length=1)


def detect_leaks(
    row: DossierRow,
    *,
    non_operator_person_names: Sequence[str] = (),
) -> tuple[LeakFinding, ...]:
    """Scan a row's prompt-visible surfaces for leak patterns.

    The four surfaces inspected are: ``prediction.statement``,
    ``product_spec.implication``, ``product_spec.negative_constraint``,
    and ``semantic_recruitment.embedded_description``. Evidence refs
    are checked separately by ``detect_evidence_ref_leaks``.
    """

    findings: list[LeakFinding] = []
    surfaces = {
        "statement": row.prediction.statement,
        "implication": row.product_spec.implication,
        "negative_constraint": row.product_spec.negative_constraint,
        "embedded_description": row.semantic_recruitment.embedded_description,
    }
    for surface_name, text in surfaces.items():
        for kind, patterns in _PATTERN_GROUPS.items():
            for pattern in patterns:
                m = pattern.search(text)
                if m:
                    findings.append(
                        LeakFinding(
                            row_id=row.id,
                            surface=surface_name,
                            leak_kind=kind,  # type: ignore[arg-type]
                            pattern_excerpt=m.group(0)[:80],
                        )
                    )
                    break  # one finding per (surface, kind) is enough
        for name in non_operator_person_names:
            if not name.strip():
                continue
            if re.search(rf"\b{re.escape(name)}\b", text, flags=re.IGNORECASE):
                findings.append(
                    LeakFinding(
                        row_id=row.id,
                        surface=surface_name,
                        leak_kind="non_operator_person",
                        pattern_excerpt=name[:80],
                    )
                )
    return tuple(findings)


_PATTERN_GROUPS: dict[str, tuple[re.Pattern, ...]] = {
    "raw_transcript": _RAW_TRANSCRIPT_PATTERNS,
    "secret": _SECRET_PATTERNS,
    "browser_store": _BROWSER_STORE_PATTERNS,
    "biometric": _BIOMETRIC_PATTERNS,
    "side_chat": _SIDE_CHAT_PATTERNS,
}


def detect_evidence_ref_leaks(row: DossierRow) -> tuple[LeakFinding, ...]:
    """``volatile_sensitive`` evidence refs must not have inline excerpts —
    only abstract pointers (event IDs, line numbers). Flag any row whose
    volatile evidence carries a path-shaped excerpt that looks like raw
    content."""

    findings: list[LeakFinding] = []
    for ref in row.evidence_refs:
        if ref.source_class != "volatile_sensitive":
            continue
        # Heuristic: an excerpt longer than 64 chars or containing
        # newlines is suspicious for a volatile_sensitive ref.
        if len(ref.excerpt_pointer) > 64 or "\n" in ref.excerpt_pointer:
            findings.append(
                LeakFinding(
                    row_id=row.id,
                    surface=f"evidence:{ref.path}",
                    leak_kind="raw_transcript",
                    pattern_excerpt=ref.excerpt_pointer[:80],
                )
            )
    return tuple(findings)


# ---------------------------------------------------------------------------
# Render path — only the safe, redacted, ceiling-respecting summary.
# Raw rows never enter prompts; only the rendered summary may.
# ---------------------------------------------------------------------------


class RowRendering(DossierModel):
    """Prompt-safe rendering of one dossier row."""

    row_id: str
    summary: str
    refused: bool
    refusal_reasons: tuple[str, ...] = ()
    leak_findings: tuple[LeakFinding, ...] = ()


def render_row_for_prompt(
    row: DossierRow,
    *,
    requested_ceiling: ModeCeiling = "private",
    non_operator_person_names: Sequence[str] = (),
) -> RowRendering:
    """Render a row as a prompt-safe summary, fail-closed on leaks /
    ceiling mismatches.

    Refuses (returns ``refused=True``) when:

    - the row's ``value_braid.mode_ceiling`` is below the requested
      ceiling (e.g. caller wants ``public_live`` but row is ``private``);
    - the row's ``governance.privacy_label`` is not in
      ``PROMPT_VISIBLE_PRIVACY_LABELS`` and the requested ceiling is
      anything but ``private`` / ``dry_run``;
    - any leak pattern fires against the prompt-visible surfaces;
    - the row status is not ``active``.
    """

    refusal_reasons: list[str] = []
    if row.status != "active":
        refusal_reasons.append(f"row status is {row.status!r}, not 'active'")

    if not _ceiling_allows(row.value_braid.mode_ceiling, requested_ceiling):
        refusal_reasons.append(
            f"row mode_ceiling {row.value_braid.mode_ceiling!r} is below requested "
            f"ceiling {requested_ceiling!r}"
        )

    if requested_ceiling not in {"private", "dry_run"} and (
        row.governance.privacy_label not in PROMPT_VISIBLE_PRIVACY_LABELS
    ):
        refusal_reasons.append(
            f"privacy_label {row.governance.privacy_label!r} is not prompt-safe at "
            f"requested ceiling {requested_ceiling!r}"
        )

    leaks = detect_leaks(row, non_operator_person_names=non_operator_person_names)
    leaks = leaks + detect_evidence_ref_leaks(row)
    if leaks:
        refusal_reasons.append(f"{len(leaks)} leak finding(s) detected in prompt-visible surfaces")

    if refusal_reasons:
        return RowRendering(
            row_id=row.id,
            summary="",
            refused=True,
            refusal_reasons=tuple(refusal_reasons),
            leak_findings=leaks,
        )

    summary_lines = [
        f"[{row.id}] ({row.status}, {row.authority})",
        f"  if: {row.context.condition}",
        f"  predict ({row.prediction.outcome_kind}, "
        f"{row.prediction.temporal_band}, "
        f"p={row.prediction.probability:.2f}, "
        f"conf={row.prediction.confidence:.2f}, "
        f"uncertainty={row.prediction.uncertainty_reason}): "
        f"{row.prediction.statement}",
        f"  implies: {row.product_spec.implication}",
        f"  negative-constraint: {row.product_spec.negative_constraint}",
    ]
    return RowRendering(
        row_id=row.id,
        summary="\n".join(summary_lines),
        refused=False,
    )


_CEILING_ORDER: tuple[ModeCeiling, ...] = (
    "private",
    "dry_run",
    "public_archive",
    "public_live",
    "public_monetizable",
)


def _ceiling_allows(row_ceiling: ModeCeiling, requested: ModeCeiling) -> bool:
    """A row may render at the requested ceiling iff the row's ceiling
    is at or above the requested level."""

    return _CEILING_ORDER.index(row_ceiling) >= _CEILING_ORDER.index(requested)


def render_dossier_for_prompt(
    dossier: OperatorPredictiveDossier,
    *,
    requested_ceiling: ModeCeiling = "private",
    non_operator_person_names: Sequence[str] = (),
    verticals: Iterable[Vertical] | None = None,
) -> tuple[RowRendering, ...]:
    """Render every active row in the dossier; downstream code decides
    which to include in the actual prompt."""

    selected = dossier.active_rows()
    if verticals is not None:
        wanted = set(verticals)
        selected = tuple(row for row in selected if set(row.verticals) & wanted)
    return tuple(
        render_row_for_prompt(
            row,
            requested_ceiling=requested_ceiling,
            non_operator_person_names=non_operator_person_names,
        )
        for row in selected
    )


def empty_dossier(generated_at: datetime | None = None) -> OperatorPredictiveDossier:
    """Convenience: an empty dossier (used as fail-safe default)."""

    return OperatorPredictiveDossier(
        generated_at=generated_at or datetime.now(tz=UTC),
        rows=(),
    )
