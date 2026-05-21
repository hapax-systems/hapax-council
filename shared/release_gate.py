"""Release/ops gates for Authority-Case SDLC.

Release candidate record, ORR-lite gate, rollback validator,
public-currentness witness, and publication surface gates.

ISAP: SLICE-006-RELEASE-OPS (CASE-SDLC-REFORM-001)
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

RiskTier = Literal["T0", "T1", "T2", "T3"]
ReleaseMethod = Literal["merge_pr", "service_restart", "hot_reload", "rebuild", "uv_publish"]
RollbackMethod = Literal["revert_commit", "service_restart", "config_restore", "yank_package"]
PublicSurfaceTier = Literal["FULL_AUTO", "CONDITIONAL_ENGAGE", "REFUSED", "INTERNAL"]

AVSDLC_EVIDENCE_FRESHNESS_SECONDS = 7 * 24 * 60 * 60
AVSDLC_AXES = {
    "aesthetic",
    "theoretical",
    "visual",
    "audio",
    "audiovisual",
    "dramaturgical",
    "interactional",
    "accessibility",
    "research-validity",
    "public-currentness",
    "provenance",
}
AVSDLC_AXIS_FIELDS = (
    "avsdlc_axes",
    "impacted_axes",
    "quality_axes",
    "aesthetic_axes",
    "impact_axes",
)
AVSDLC_NO_AXIS_VALUES = {"none", "no-impact", "unimpacted", "not-applicable", "n/a", "na"}
AVSDLC_DOSSIER_FIELDS = (
    "avsdlc_dossier",
    "avsdlc_quality_dossier",
    "quality_dossier",
    "quality_dossier_ref",
    "release_dossier",
)
AVSDLC_TIMESTAMP_FIELDS = (
    "avsdlc_evidence_collected_at",
    "avsdlc_dossier_updated_at",
    "quality_dossier_updated_at",
    "witness_collected_at",
    "evidence_updated_at",
)
AVSDLC_AXIS_EVIDENCE_FIELDS = {
    "aesthetic": ("aesthetic_witness", "review_witness", "operator_review"),
    "visual": ("visual_witness", "visual_witnesses", "screenshots", "screenshot_evidence"),
    "audio": (
        "audio_witness",
        "audio_witnesses",
        "audio_measurement",
        "audio_routing_witness",
    ),
    "audiovisual": ("audiovisual_witness", "sync_witness", "runtime_media_witness"),
    "theoretical": ("theoretical_claim_map", "claim_map"),
    "research-validity": ("theoretical_claim_map", "claim_map", "research_validity_witness"),
    "public-currentness": ("public_currentness_witness", "public_currentness_receipt"),
    "provenance": ("provenance_witness", "provenance_receipt"),
    "dramaturgical": ("dramaturgical_witness", "review_witness"),
    "interactional": ("interaction_witness", "interaction_trace", "review_witness"),
    "accessibility": ("accessibility_witness", "accessibility_check"),
}

_AXIS_ALIASES = {
    "research_validity": "research-validity",
    "public_currentness": "public-currentness",
    "av": "audiovisual",
    "audio-visual": "audiovisual",
}
_VISUAL_MARKERS = (
    "studio_compositor",
    "compositor",
    "visual",
    "frontend",
    "react",
    "shader",
    "glsl",
    "canvas",
    "screenshot",
    "frame-capture",
)
_AESTHETIC_MARKERS = (
    "aesthetic",
    "design-language",
    "palette",
    "homage",
    "assets/aesthetic-library",
    "aesthetic_library",
)
_AUDIO_MARKERS = (
    "audio",
    "pipewire",
    "wireplumber",
    "tts",
    "voice",
    "lufs",
    "l-12",
    "broadcast-normalized",
)
_AUDIOVISUAL_MARKERS = ("audiovisual", "watchalong", "livestream", "stream", "broadcast")
_THEORETICAL_MARKERS = ("theoretical", "theory", "claim-map", "research-positioning")
_RUNTIME_MEDIA_MARKERS = (
    "runtime_media",
    "live_surface",
    "livestream",
    "broadcast",
    "studio_compositor",
    "compositor",
    "pipewire",
    "wireplumber",
    "tts",
)


class ReleaseCandidateRecord(BaseModel):
    """Structured record for a release candidate."""

    case_id: str
    slice_id: str = ""
    pr_number: int | None = None
    branch: str = ""
    commit_sha: str = ""
    risk_tier: RiskTier = "T0"
    release_method: ReleaseMethod = "merge_pr"
    deploy_scope: list[str] = Field(
        default_factory=list,
        description="Paths/services affected by this release",
    )
    rollback_method: RollbackMethod = "revert_commit"
    rollback_trigger: str = (
        "CI failure, service crash, or >10% false positives on legitimate operations"
    )
    readback_plan: str = Field(
        default="",
        description="What runtime signal confirms successful deployment",
    )
    orr_lite_passed: bool = False
    evidence_ids: list[str] = Field(default_factory=list)
    created_utc: float = Field(default_factory=time.time)
    notes: str = ""


class OrrLiteResult(BaseModel):
    """Result of an ORR-lite (Operational Readiness Review lite) check."""

    case_id: str
    checks: dict[str, bool] = Field(default_factory=dict)
    passed: bool = False
    blockers: list[str] = Field(default_factory=list)
    timestamp_utc: float = Field(default_factory=time.time)
    reviewer: str = ""


class RollbackPlan(BaseModel):
    """Validated rollback plan for a release."""

    case_id: str
    trigger: str
    method: RollbackMethod
    affected_services: list[str] = Field(default_factory=list)
    emergency_env_var: str = ""
    pre_release_snapshot: str = Field(
        default="",
        description="Commit SHA or state snapshot to revert to",
    )
    non_git_surfaces: list[str] = Field(
        default_factory=list,
        description="Vault, PyPI, ledger entries that need special rollback",
    )
    validated: bool = False
    validation_notes: str = ""


class PublicCurrentnessWitness(BaseModel):
    """Witness record for public-currentness gate."""

    case_id: str
    public_surfaces_touched: list[str] = Field(default_factory=list)
    no_public_surfaces: bool = False
    publication_tier: PublicSurfaceTier = "INTERNAL"
    claim_safe: bool = False
    notes: str = ""


class AvsdlcReleaseGateResult(BaseModel):
    """Result of the mechanical AVSDLC release evidence gate."""

    required: bool = False
    passed: bool = True
    impacted_axes: list[str] = Field(default_factory=list)
    inferred_axes: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    stale_fields: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    timestamp_utc: float = Field(default_factory=time.time)


def _is_nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (list, tuple, set)):
        return any(_is_nonempty(item) for item in value)
    if isinstance(value, dict):
        return bool(value)
    text = str(value).strip()
    return bool(text and text.lower() not in {"null", "none", "~", "[]", "{}"})


def _values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(_values(item))
        return out
    if isinstance(value, dict):
        return [str(key) for key in value if _is_nonempty(key)]
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "~"}:
        return []
    if "," in text:
        return [part.strip().strip("'\"") for part in text.split(",") if part.strip()]
    return [text.strip("[]'\" ")]


def _normalize_axis(raw: str) -> str | None:
    text = raw.strip().lower().replace("_", "-").replace(" ", "-")
    text = _AXIS_ALIASES.get(text, text)
    return text if text in AVSDLC_AXES else None


def _explicit_axes(frontmatter: Mapping[str, Any]) -> list[str]:
    axes: set[str] = set()
    for field_name in AVSDLC_AXIS_FIELDS:
        for value in _values(frontmatter.get(field_name)):
            axis = _normalize_axis(value)
            if axis:
                axes.add(axis)
    return sorted(axes)


def _declares_no_axes(frontmatter: Mapping[str, Any]) -> bool:
    for field_name in AVSDLC_AXIS_FIELDS:
        if field_name not in frontmatter:
            continue
        raw = frontmatter.get(field_name)
        if raw == []:
            return True
        values = raw if isinstance(raw, (list, tuple, set)) else [raw]
        for value in values:
            text = str(value or "").strip().lower().replace("_", "-").replace(" ", "-")
            if text in AVSDLC_NO_AXIS_VALUES:
                return True
    return False


def _joined_text(frontmatter: Mapping[str, Any], field_names: tuple[str, ...]) -> str:
    values: list[str] = []
    for field_name in field_names:
        values.extend(_values(frontmatter.get(field_name)))
    return "\n".join(values).lower()


def _infer_axes(frontmatter: Mapping[str, Any]) -> list[str]:
    text = _joined_text(
        frontmatter,
        ("mutation_surface", "mutation_surfaces", "mutation_scope_refs", "tags", "paths"),
    )
    axes: set[str] = set()
    if any(marker in text for marker in _VISUAL_MARKERS):
        axes.add("visual")
    if any(marker in text for marker in _AESTHETIC_MARKERS):
        axes.add("aesthetic")
    if any(marker in text for marker in _AUDIO_MARKERS):
        axes.add("audio")
    if any(marker in text for marker in _AUDIOVISUAL_MARKERS):
        axes.add("audiovisual")
    if any(marker in text for marker in _THEORETICAL_MARKERS):
        axes.add("theoretical")
    if any(
        _truthy(frontmatter, field_name)
        for field_name in (
            "runtime_media_impact",
            "runtime_media_witness_required",
            "runtime_witness_required",
        )
    ):
        axes.add("audiovisual")
    return sorted(axes)


def _has_any_field(frontmatter: Mapping[str, Any], names: tuple[str, ...]) -> bool:
    return any(_is_nonempty(frontmatter.get(name)) for name in names)


def _first_present_field(
    frontmatter: Mapping[str, Any], names: tuple[str, ...]
) -> tuple[str, Any] | None:
    for name in names:
        value = frontmatter.get(name)
        if _is_nonempty(value):
            return name, value
    return None


def _truthy(frontmatter: Mapping[str, Any], name: str) -> bool:
    value = frontmatter.get(name)
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "required"}


def _as_epoch(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _now_epoch(now: float | datetime | None) -> float:
    if now is None:
        return time.time()
    if isinstance(now, datetime):
        parsed = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        return parsed.timestamp()
    return float(now)


def _freshness_seconds(frontmatter: Mapping[str, Any]) -> int:
    for field_name in ("avsdlc_freshness_seconds", "evidence_freshness_seconds"):
        value = frontmatter.get(field_name)
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return AVSDLC_EVIDENCE_FRESHNESS_SECONDS


def _runtime_media_required(frontmatter: Mapping[str, Any], axes: list[str]) -> bool:
    if any(
        _truthy(frontmatter, field_name)
        for field_name in (
            "runtime_media_impact",
            "runtime_media_witness_required",
            "runtime_witness_required",
        )
    ):
        return True
    if not {"visual", "audio", "audiovisual"} & set(axes):
        return False
    text = _joined_text(
        frontmatter, ("mutation_surface", "mutation_surfaces", "mutation_scope_refs")
    )
    return any(marker in text for marker in _RUNTIME_MEDIA_MARKERS)


def evaluate_avsdlc_release_gate(
    frontmatter: Mapping[str, Any],
    *,
    now: float | datetime | None = None,
) -> AvsdlcReleaseGateResult:
    """Evaluate the mechanical AVSDLC evidence gate for one request/task note.

    The gate is intentionally data-only: explicit AVSDLC axes trigger hard
    dossier, witness, and freshness requirements. If an obvious media/runtime
    mutation is present without axes, the result fails at the classification
    gate instead of inferring a release pass.
    """

    timestamp = _now_epoch(now)
    explicit_axes = _explicit_axes(frontmatter)
    declared_no_axes = _declares_no_axes(frontmatter)
    inferred_axes = _infer_axes(frontmatter)
    if inferred_axes and not explicit_axes and not declared_no_axes:
        return AvsdlcReleaseGateResult(
            required=True,
            passed=False,
            impacted_axes=inferred_axes,
            inferred_axes=inferred_axes,
            required_fields=["avsdlc_axes"],
            missing_fields=["avsdlc_axes"],
            blockers=["avsdlc_axes_missing:" + ",".join(inferred_axes)],
            timestamp_utc=timestamp,
        )

    if not explicit_axes:
        return AvsdlcReleaseGateResult(
            required=False,
            passed=True,
            inferred_axes=inferred_axes,
            timestamp_utc=timestamp,
        )

    required_fields: set[str] = {"avsdlc_dossier", "avsdlc_evidence_collected_at"}
    missing_fields: list[str] = []
    stale_fields: list[str] = []

    if not _has_any_field(frontmatter, AVSDLC_DOSSIER_FIELDS):
        missing_fields.append("avsdlc_dossier")

    for axis in explicit_axes:
        evidence_fields = AVSDLC_AXIS_EVIDENCE_FIELDS.get(axis, ())
        if evidence_fields:
            label = evidence_fields[0]
            required_fields.add(label)
            if not _has_any_field(frontmatter, evidence_fields):
                missing_fields.append(label)

    if _runtime_media_required(frontmatter, explicit_axes):
        required_fields.add("runtime_media_witness")
        if not _has_any_field(frontmatter, ("runtime_media_witness", "production_witness")):
            missing_fields.append("runtime_media_witness")

    timestamp_field = _first_present_field(frontmatter, AVSDLC_TIMESTAMP_FIELDS)
    if timestamp_field is None:
        missing_fields.append("avsdlc_evidence_collected_at")
    else:
        field_name, value = timestamp_field
        parsed = _as_epoch(value)
        if parsed is None or timestamp - parsed > _freshness_seconds(frontmatter):
            stale_fields.append(field_name)

    blockers = [f"missing:{field}" for field in sorted(set(missing_fields))]
    blockers.extend(f"stale:{field}" for field in sorted(set(stale_fields)))
    return AvsdlcReleaseGateResult(
        required=True,
        passed=not blockers,
        impacted_axes=explicit_axes,
        inferred_axes=inferred_axes,
        required_fields=sorted(required_fields),
        missing_fields=sorted(set(missing_fields)),
        stale_fields=sorted(set(stale_fields)),
        blockers=blockers,
        timestamp_utc=timestamp,
    )


# ── ORR-lite check logic ──────────────────────────────────────────────


def run_orr_lite(
    case_id: str,
    pr_number: int | None = None,
    risk_tier: RiskTier = "T0",
    has_tests: bool = False,
    ci_green: bool = False,
    has_readback_plan: bool = False,
    has_rollback_plan: bool = False,
    has_evidence: bool = False,
    has_review: bool = False,
    has_axiom_scan: bool = False,
    reviewer: str = "",
) -> OrrLiteResult:
    checks: dict[str, bool] = {}
    blockers: list[str] = []

    checks["tests_pass"] = has_tests
    if not has_tests:
        blockers.append("Tests not passing or not run")

    checks["ci_green"] = ci_green
    if not ci_green:
        blockers.append("CI not green")

    checks["readback_plan_exists"] = has_readback_plan
    if not has_readback_plan and risk_tier in ("T1", "T2", "T3"):
        blockers.append(f"Readback plan required for {risk_tier}")

    checks["rollback_plan_exists"] = has_rollback_plan
    if not has_rollback_plan:
        blockers.append("No rollback plan")

    checks["evidence_sufficient"] = has_evidence
    if not has_evidence:
        blockers.append("Evidence ledger incomplete for tier")

    if risk_tier in ("T2", "T3"):
        checks["review_complete"] = has_review
        if not has_review:
            blockers.append(f"Independent review required for {risk_tier}")
        checks["axiom_scan_passed"] = has_axiom_scan
        if not has_axiom_scan:
            blockers.append(f"Axiom scan required for {risk_tier}")

    return OrrLiteResult(
        case_id=case_id,
        checks=checks,
        passed=len(blockers) == 0,
        blockers=blockers,
        reviewer=reviewer,
    )


def validate_rollback_plan(plan: RollbackPlan) -> list[str]:
    """Return list of validation issues. Empty = valid."""
    issues: list[str] = []
    if not plan.trigger:
        issues.append("Rollback trigger not defined")
    if not plan.pre_release_snapshot:
        issues.append("No pre-release snapshot SHA defined")
    if plan.non_git_surfaces and not plan.validation_notes:
        issues.append(f"Non-git surfaces ({', '.join(plan.non_git_surfaces)}) need rollback notes")
    return issues


def check_public_currentness(witness: PublicCurrentnessWitness) -> list[str]:
    """Return list of gate violations. Empty = gate passes."""
    issues: list[str] = []
    if witness.no_public_surfaces:
        return []
    if not witness.public_surfaces_touched:
        issues.append("Public surfaces not enumerated")
    if witness.publication_tier == "REFUSED":
        issues.append("Publication tier is REFUSED — cannot release to public")
    if not witness.claim_safe:
        issues.append("Public claims not verified as safe")
    return issues
