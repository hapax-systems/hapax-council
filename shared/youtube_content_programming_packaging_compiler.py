"""YouTube content-programming packaging compiler.

The compiler is a deterministic read-side adapter: it turns one eligible
content programme run plus readiness-gated conversion candidates into
YouTube-native packaging records. It does not publish, upload, schedule, or
debit quota. Missing surface evidence blocks the whole package.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.content_programme_run_store import ContentProgrammeRunEnvelope
from shared.conversion_broker import ConversionCandidate, ConversionTargetType
from shared.conversion_target_readiness import PUBLIC_READINESS_STATES
from shared.format_public_event_adapter import ProgrammeBoundaryEvent
from shared.youtube_packaging_claim_policy import (
    ClaimClass,
    PackagingClaim,
    PackagingPayload,
    PolicyVerdict,
    evaluate_payload,
)

type PackageStatus = Literal["compiled", "blocked"]
type ThumbnailShape = Literal[
    "tier_grid",
    "bracket",
    "verdict_stamp",
    "comparison",
    "refusal_card",
    "confidence_meter",
]
type PlacementKind = Literal["playlist", "channel_section"]
type PackagingFieldKind = Literal[
    "title",
    "description",
    "thumbnail_text",
    "chapter",
    "caption",
    "shorts_caption",
    "channel_section",
]
type ShortsFocus = Literal[
    "rank_reversal",
    "refusal",
    "correction",
    "confidence_collapse",
    "grounding_moment",
]


class YouTubePackagingSurface(StrEnum):
    """YouTube surface gates required before a package can be emitted."""

    METADATA = "metadata"
    CHAPTERS = "chapters"
    CAPTIONS = "captions"
    CUEPOINTS = "cuepoints"
    SHORTS = "shorts"
    QUOTA = "quota"
    RIGHTS = "rights"
    MONETIZATION = "monetization"


REQUIRED_SURFACES: tuple[YouTubePackagingSurface, ...] = (
    YouTubePackagingSurface.METADATA,
    YouTubePackagingSurface.CHAPTERS,
    YouTubePackagingSurface.CAPTIONS,
    YouTubePackagingSurface.CUEPOINTS,
    YouTubePackagingSurface.SHORTS,
    YouTubePackagingSurface.QUOTA,
    YouTubePackagingSurface.RIGHTS,
    YouTubePackagingSurface.MONETIZATION,
)

_YOUTUBE_TARGETS: Mapping[YouTubePackagingSurface, ConversionTargetType] = {
    YouTubePackagingSurface.METADATA: "youtube_vod",
    YouTubePackagingSurface.CHAPTERS: "youtube_chapter",
    YouTubePackagingSurface.CAPTIONS: "youtube_caption",
    YouTubePackagingSurface.SHORTS: "youtube_shorts",
}
_PUBLIC_SAFE_RIGHTS = {"operator_original", "cleared", "platform_embed_only"}
_PUBLIC_SAFE_PRIVACY = {"public_safe", "aggregate_only"}
_SHORTS_FOCUS_BOUNDARIES: Mapping[str, ShortsFocus] = {
    "refusal.issued": "refusal",
    "correction.made": "correction",
    "uncertainty.marked": "confidence_collapse",
    "evidence.observed": "grounding_moment",
}
_PRIVATE_SENTINEL_RE = re.compile(r"PRIVATE_SENTINEL_DO_NOT_PUBLISH_[A-Z0-9_]+")


class YouTubePackagingModel(BaseModel):
    """Strict immutable base for compiler records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class YouTubePackagingSurfaceGate(YouTubePackagingModel):
    """Evidence that one YouTube packaging surface is usable or known-blocked."""

    surface: YouTubePackagingSurface
    available: bool
    state_detail: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    unavailable_reasons: tuple[str, ...] = Field(default_factory=tuple)


class YouTubePackagingReadiness(YouTubePackagingModel):
    """Readiness snapshot for all YouTube packaging surfaces."""

    captured_at: datetime
    source: str = Field(min_length=1)
    gates: tuple[YouTubePackagingSurfaceGate, ...]


class YouTubeTitleCandidate(YouTubePackagingModel):
    text: str = Field(min_length=1, max_length=100)
    format_name: str = Field(min_length=1)
    epistemic_test: str = Field(min_length=1)
    policy_verdict: PolicyVerdict


class YouTubeThumbnailBrief(YouTubePackagingModel):
    shape: ThumbnailShape
    headline: str = Field(min_length=1, max_length=80)
    visual_elements: tuple[str, ...] = Field(min_length=1)
    source_refs: tuple[str, ...] = Field(default_factory=tuple)
    policy_verdict: PolicyVerdict


class YouTubeDescription(YouTubePackagingModel):
    text: str = Field(min_length=1)
    public_event_refs: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    policy_verdict: PolicyVerdict


class YouTubeChapter(YouTubePackagingModel):
    label: str = Field(min_length=1, max_length=100)
    timecode: str = Field(pattern=r"^\d{2}:\d{2}(?::\d{2})?$")
    boundary_id: str = Field(min_length=1)
    derived_from_programme_boundary: Literal[True] = True
    policy_verdict: PolicyVerdict


class YouTubeCaptionLine(YouTubePackagingModel):
    platform_text: str = Field(min_length=1)
    source_boundary_id: str = Field(min_length=1)
    internal_claim_refs: tuple[str, ...] = Field(default_factory=tuple)
    internal_provenance_refs: tuple[str, ...] = Field(default_factory=tuple)
    internal_uncertainty: str = Field(min_length=1)
    policy_verdict: PolicyVerdict


class YouTubeShortsCandidate(YouTubePackagingModel):
    focus: ShortsFocus
    title: str = Field(min_length=1, max_length=100)
    hook_text: str = Field(min_length=1, max_length=120)
    source_boundary_ids: tuple[str, ...] = Field(min_length=1)
    source_refs: tuple[str, ...] = Field(default_factory=tuple)
    generic_viral_cut_allowed: Literal[False] = False
    policy_verdict: PolicyVerdict


class YouTubePlacement(YouTubePackagingModel):
    kind: PlacementKind
    label: str = Field(min_length=1, max_length=120)
    rationale: str = Field(min_length=1)
    source_refs: tuple[str, ...] = Field(default_factory=tuple)
    policy_verdict: PolicyVerdict


class YouTubePackagingCompileResult(YouTubePackagingModel):
    """Compiled YouTube package, or a fail-closed blocked result."""

    schema_version: Literal[1] = 1
    package_id: str
    status: PackageStatus
    source_run_id: str
    source_programme_id: str
    format_id: str
    generated_at: datetime
    surface_policy_reasons: tuple[str, ...]
    blocked_reasons: tuple[str, ...] = Field(default_factory=tuple)
    title_candidates: tuple[YouTubeTitleCandidate, ...] = Field(default_factory=tuple)
    thumbnail_briefs: tuple[YouTubeThumbnailBrief, ...] = Field(default_factory=tuple)
    description: YouTubeDescription | None = None
    chapters: tuple[YouTubeChapter, ...] = Field(default_factory=tuple)
    captions: tuple[YouTubeCaptionLine, ...] = Field(default_factory=tuple)
    shorts_candidates: tuple[YouTubeShortsCandidate, ...] = Field(default_factory=tuple)
    placements: tuple[YouTubePlacement, ...] = Field(default_factory=tuple)


def compile_youtube_content_programming_package(
    *,
    run: ContentProgrammeRunEnvelope,
    boundary_events: Sequence[ProgrammeBoundaryEvent],
    conversion_candidates: Sequence[ConversionCandidate],
    readiness: YouTubePackagingReadiness,
    generated_at: datetime | None = None,
) -> YouTubePackagingCompileResult:
    """Compile one YouTube package or return a fail-closed blocked result."""

    generated = generated_at or datetime.now(tz=UTC)
    reasons = _surface_policy_reasons(readiness, conversion_candidates)
    blockers = _compile_blockers(
        run=run,
        boundary_events=boundary_events,
        conversion_candidates=conversion_candidates,
        readiness=readiness,
    )
    if blockers:
        return _blocked_result(
            run=run,
            generated_at=generated,
            reasons=reasons,
            blockers=blockers,
        )

    public_event_refs = _public_event_refs(conversion_candidates)
    format_name = _format_name(run.format_id)
    titles = _compile_titles(run, format_name, public_event_refs)
    thumbnails = _compile_thumbnail_briefs(run, boundary_events, format_name)
    description = _compile_description(run, boundary_events, public_event_refs)
    chapters = _compile_chapters(boundary_events, public_event_refs)
    captions = _compile_captions(run, boundary_events, public_event_refs)
    shorts = _compile_shorts(boundary_events, public_event_refs)
    placements = _compile_placements(run, format_name, public_event_refs)
    policy_blockers = _policy_blockers(
        titles=titles,
        thumbnails=thumbnails,
        description=description,
        chapters=chapters,
        captions=captions,
        shorts=shorts,
        placements=placements,
    )
    if policy_blockers:
        return _blocked_result(
            run=run,
            generated_at=generated,
            reasons=reasons,
            blockers=policy_blockers,
        )
    return YouTubePackagingCompileResult(
        package_id=_sanitize_id(f"youtube-package:{run.run_id}:{generated.isoformat()}"),
        status="compiled",
        source_run_id=run.run_id,
        source_programme_id=run.programme_id,
        format_id=run.format_id,
        generated_at=generated,
        surface_policy_reasons=tuple(reasons),
        title_candidates=titles,
        thumbnail_briefs=thumbnails,
        description=description,
        chapters=chapters,
        captions=captions,
        shorts_candidates=shorts,
        placements=placements,
    )


def _compile_blockers(
    *,
    run: ContentProgrammeRunEnvelope,
    boundary_events: Sequence[ProgrammeBoundaryEvent],
    conversion_candidates: Sequence[ConversionCandidate],
    readiness: YouTubePackagingReadiness,
) -> tuple[str, ...]:
    blockers: list[str] = []
    gates = {gate.surface: gate for gate in readiness.gates}
    for surface in REQUIRED_SURFACES:
        gate = gates.get(surface)
        if gate is None:
            blockers.append(f"{surface.value} surface gate missing")
            continue
        if not gate.available:
            detail = ", ".join(gate.unavailable_reasons) or gate.state_detail
            blockers.append(f"{surface.value} unavailable: {detail}")

    if run.rights_privacy_public_mode.rights_state not in _PUBLIC_SAFE_RIGHTS:
        blockers.append(
            f"rights state blocks YouTube packaging: {run.rights_privacy_public_mode.rights_state}"
        )
    if run.rights_privacy_public_mode.privacy_state not in _PUBLIC_SAFE_PRIVACY:
        blockers.append(
            "privacy state blocks YouTube packaging: "
            f"{run.rights_privacy_public_mode.privacy_state}"
        )
    for surface, target_type in _YOUTUBE_TARGETS.items():
        candidate = _ready_candidate_for_target(conversion_candidates, target_type)
        if candidate is None:
            blockers.append(f"{surface.value} conversion candidate not public-ready")

    if not _public_event_refs(conversion_candidates):
        blockers.append("missing publication-bus public_event_ref")
    if not _boundary_chapters(boundary_events):
        blockers.append("chapters unavailable: no programme-boundary chapter policy")
    if not _shorts_boundaries(boundary_events):
        blockers.append(
            "shorts unavailable: no rank reversal/refusal/correction/collapse/grounding boundary"
        )
    if not boundary_events:
        blockers.append("metadata unavailable: no programme boundaries supplied")
    return tuple(_dedupe(blockers))


def _compile_titles(
    run: ContentProgrammeRunEnvelope,
    format_name: str,
    public_event_refs: tuple[str, ...],
) -> tuple[YouTubeTitleCandidate, ...]:
    epistemic_test = _epistemic_test(run.grounding_question)
    title_texts = (
        _truncate_title(f"{format_name}: {epistemic_test}"),
        _truncate_title(f"{format_name} evidence test: {epistemic_test}"),
    )
    return tuple(
        YouTubeTitleCandidate(
            text=text,
            format_name=format_name,
            epistemic_test=epistemic_test,
            policy_verdict=_verdict(
                "title",
                text,
                _claims(
                    (text, ClaimClass.DESCRIPTIVE, None),
                    (f"Programme run {run.run_id}", ClaimClass.RUN_RESULT, public_event_refs[0]),
                ),
            ),
        )
        for text in title_texts
    )


def _compile_thumbnail_briefs(
    run: ContentProgrammeRunEnvelope,
    boundary_events: Sequence[ProgrammeBoundaryEvent],
    format_name: str,
) -> tuple[YouTubeThumbnailBrief, ...]:
    shape = _thumbnail_shape(run.format_id, boundary_events)
    headline = _truncate(f"{format_name} / evidence check", 80)
    elements = _thumbnail_elements(shape)
    source_refs = tuple(f"ProgrammeBoundaryEvent:{event.boundary_id}" for event in boundary_events)
    return (
        YouTubeThumbnailBrief(
            shape=shape,
            headline=headline,
            visual_elements=elements,
            source_refs=source_refs,
            policy_verdict=_verdict("thumbnail_text", headline),
        ),
    )


def _compile_description(
    run: ContentProgrammeRunEnvelope,
    boundary_events: Sequence[ProgrammeBoundaryEvent],
    public_event_refs: tuple[str, ...],
) -> YouTubeDescription:
    latest_boundary = boundary_events[-1]
    evidence_refs = _evidence_refs(run, boundary_events)
    text = "\n".join(
        (
            f"{_format_name(run.format_id)} run: {run.grounding_question}",
            f"Epistemic test: {_epistemic_test(run.grounding_question)}",
            f"Scope: {latest_boundary.claim_shape.scope_limit}",
            f"Uncertainty: {latest_boundary.claim_shape.uncertainty}",
            f"Programme run: {run.run_id}",
            f"Public event: {public_event_refs[0]}",
        )
    )
    return YouTubeDescription(
        text=text,
        public_event_refs=public_event_refs,
        evidence_refs=evidence_refs,
        policy_verdict=_verdict(
            "description",
            text,
            _claims(
                (text, ClaimClass.DESCRIPTIVE, None),
                (f"Programme run {run.run_id}", ClaimClass.RUN_RESULT, public_event_refs[0]),
                (f"Archive state for {run.run_id}", ClaimClass.ARCHIVE, public_event_refs[0]),
            ),
        ),
    )


def _compile_chapters(
    boundary_events: Sequence[ProgrammeBoundaryEvent],
    public_event_refs: tuple[str, ...],
) -> tuple[YouTubeChapter, ...]:
    chapters: list[YouTubeChapter] = []
    for boundary in _boundary_chapters(boundary_events):
        label = boundary.cuepoint_chapter_policy.chapter_label or _boundary_label(boundary)
        text = _truncate(label, 100)
        chapters.append(
            YouTubeChapter(
                label=text,
                timecode=boundary.cuepoint_chapter_policy.timecode or "00:00",
                boundary_id=boundary.boundary_id,
                policy_verdict=_verdict(
                    "chapter",
                    text,
                    _claims((text, ClaimClass.RUN_RESULT, public_event_refs[0])),
                ),
            )
        )
    return tuple(chapters)


def _compile_captions(
    run: ContentProgrammeRunEnvelope,
    boundary_events: Sequence[ProgrammeBoundaryEvent],
    public_event_refs: tuple[str, ...],
) -> tuple[YouTubeCaptionLine, ...]:
    captions: list[YouTubeCaptionLine] = []
    claim_refs = tuple(claim.claim_id for claim in run.claims)
    provenance_refs = _evidence_refs(run, boundary_events)
    for boundary in boundary_events:
        platform_text = _platform_caption_text(boundary.summary)
        captions.append(
            YouTubeCaptionLine(
                platform_text=platform_text,
                source_boundary_id=boundary.boundary_id,
                internal_claim_refs=claim_refs,
                internal_provenance_refs=provenance_refs,
                internal_uncertainty=boundary.claim_shape.uncertainty,
                policy_verdict=_verdict(
                    "caption",
                    platform_text,
                    _claims((platform_text, ClaimClass.RUN_RESULT, public_event_refs[0])),
                ),
            )
        )
    return tuple(captions)


def _compile_shorts(
    boundary_events: Sequence[ProgrammeBoundaryEvent],
    public_event_refs: tuple[str, ...],
) -> tuple[YouTubeShortsCandidate, ...]:
    candidates: list[YouTubeShortsCandidate] = []
    for boundary in _shorts_boundaries(boundary_events):
        focus = _shorts_focus(boundary)
        hook = _shorts_hook(boundary, focus)
        title = _truncate_title(f"{_shorts_focus_label(focus)}: {_boundary_label(boundary)}")
        candidates.append(
            YouTubeShortsCandidate(
                focus=focus,
                title=title,
                hook_text=hook,
                source_boundary_ids=(boundary.boundary_id,),
                source_refs=tuple(f"ProgrammeBoundaryEvent:{boundary.boundary_id}" for _ in (0,)),
                policy_verdict=_verdict(
                    "shorts_caption",
                    hook,
                    _claims((hook, ClaimClass.RUN_RESULT, public_event_refs[0])),
                ),
            )
        )
    return tuple(candidates)


def _compile_placements(
    run: ContentProgrammeRunEnvelope,
    format_name: str,
    public_event_refs: tuple[str, ...],
) -> tuple[YouTubePlacement, ...]:
    playlist = "Autonomous Content Programming"
    section = f"{format_name} grounding runs"
    refs = (f"ContentProgrammeRunEnvelope:{run.run_id}", public_event_refs[0])
    return (
        YouTubePlacement(
            kind="playlist",
            label=playlist,
            rationale="Programme packaging belongs with other autonomous content-programming runs.",
            source_refs=refs,
            policy_verdict=_verdict("channel_section", playlist),
        ),
        YouTubePlacement(
            kind="channel_section",
            label=section,
            rationale="Channel section placement is format-recognizable and evidence-scoped.",
            source_refs=refs,
            policy_verdict=_verdict("channel_section", section),
        ),
    )


def _policy_blockers(
    *,
    titles: Sequence[YouTubeTitleCandidate],
    thumbnails: Sequence[YouTubeThumbnailBrief],
    description: YouTubeDescription,
    chapters: Sequence[YouTubeChapter],
    captions: Sequence[YouTubeCaptionLine],
    shorts: Sequence[YouTubeShortsCandidate],
    placements: Sequence[YouTubePlacement],
) -> tuple[str, ...]:
    blockers: list[str] = []
    verdicts: Iterable[tuple[str, PolicyVerdict]] = (
        *((f"title:{item.text}", item.policy_verdict) for item in titles),
        *((f"thumbnail:{item.headline}", item.policy_verdict) for item in thumbnails),
        ("description", description.policy_verdict),
        *((f"chapter:{item.boundary_id}", item.policy_verdict) for item in chapters),
        *((f"caption:{item.source_boundary_id}", item.policy_verdict) for item in captions),
        *((f"shorts:{item.source_boundary_ids[0]}", item.policy_verdict) for item in shorts),
        *((f"placement:{item.label}", item.policy_verdict) for item in placements),
    )
    for label, verdict in verdicts:
        if verdict.allowed:
            continue
        details = ", ".join(verdict.blocker_details) or ", ".join(verdict.blockers)
        blockers.append(f"packaging policy blocked {label}: {details}")
    return tuple(blockers)


def _blocked_result(
    *,
    run: ContentProgrammeRunEnvelope,
    generated_at: datetime,
    reasons: Sequence[str],
    blockers: Sequence[str],
) -> YouTubePackagingCompileResult:
    return YouTubePackagingCompileResult(
        package_id=_sanitize_id(f"youtube-package:{run.run_id}:{generated_at.isoformat()}:blocked"),
        status="blocked",
        source_run_id=run.run_id,
        source_programme_id=run.programme_id,
        format_id=run.format_id,
        generated_at=generated_at,
        surface_policy_reasons=tuple(reasons),
        blocked_reasons=tuple(_dedupe(blockers)),
    )


def _surface_policy_reasons(
    readiness: YouTubePackagingReadiness,
    conversion_candidates: Sequence[ConversionCandidate],
) -> tuple[str, ...]:
    reasons = [
        f"{gate.surface.value}: {'available' if gate.available else 'unavailable'}"
        f" ({gate.state_detail})"
        for gate in readiness.gates
    ]
    for candidate in conversion_candidates:
        if str(candidate.target_type).startswith("youtube_"):
            state = "ready" if _candidate_is_ready(candidate) else "blocked"
            reasons.append(f"{candidate.target_type}: {state} ({candidate.readiness_state})")
    return tuple(_dedupe(reasons))


def _ready_candidate_for_target(
    conversion_candidates: Sequence[ConversionCandidate],
    target_type: ConversionTargetType,
) -> ConversionCandidate | None:
    for candidate in conversion_candidates:
        if candidate.target_type == target_type and _candidate_is_ready(candidate):
            return candidate
    return None


def _candidate_is_ready(candidate: ConversionCandidate) -> bool:
    return (
        candidate.ready_for_publication_bus
        and candidate.blocked_reason is None
        and candidate.publication_bus_event_ref is not None
        and candidate.readiness_state in PUBLIC_READINESS_STATES
    )


def _public_event_refs(
    conversion_candidates: Sequence[ConversionCandidate],
) -> tuple[str, ...]:
    return tuple(
        _dedupe(
            candidate.publication_bus_event_ref
            for candidate in conversion_candidates
            if candidate.publication_bus_event_ref and _candidate_is_ready(candidate)
        )
    )


def _boundary_chapters(
    boundary_events: Sequence[ProgrammeBoundaryEvent],
) -> tuple[ProgrammeBoundaryEvent, ...]:
    return tuple(
        boundary
        for boundary in boundary_events
        if boundary.cuepoint_chapter_policy.vod_chapter_allowed
        and boundary.cuepoint_chapter_policy.chapter_label
        and boundary.cuepoint_chapter_policy.timecode
    )


def _shorts_boundaries(
    boundary_events: Sequence[ProgrammeBoundaryEvent],
) -> tuple[ProgrammeBoundaryEvent, ...]:
    return tuple(boundary for boundary in boundary_events if _shorts_focus(boundary) is not None)


def _shorts_focus(boundary: ProgrammeBoundaryEvent) -> ShortsFocus | None:
    if boundary.boundary_type == "comparison.resolved":
        return "rank_reversal" if _contains_reversal(boundary.summary) else "grounding_moment"
    if boundary.boundary_type in _SHORTS_FOCUS_BOUNDARIES:
        return _SHORTS_FOCUS_BOUNDARIES[boundary.boundary_type]
    if _contains_reversal(boundary.summary):
        return "rank_reversal"
    if _contains_confidence_collapse(boundary.summary):
        return "confidence_collapse"
    if _contains_grounding_moment(boundary.summary):
        return "grounding_moment"
    return None


def _thumbnail_shape(
    format_id: str,
    boundary_events: Sequence[ProgrammeBoundaryEvent],
) -> ThumbnailShape:
    lowered = format_id.lower()
    if any(boundary.boundary_type == "refusal.issued" for boundary in boundary_events):
        return "refusal_card"
    if "tier" in lowered or "ranking" in lowered:
        return "tier_grid"
    if "bracket" in lowered:
        return "bracket"
    if "comparison" in lowered or "review" in lowered:
        return "comparison"
    if "refusal" in lowered:
        return "refusal_card"
    if "audit" in lowered or "correction" in lowered:
        return "verdict_stamp"
    return "confidence_meter"


def _thumbnail_elements(shape: ThumbnailShape) -> tuple[str, ...]:
    elements = {
        "tier_grid": ("ranked rows", "evidence chips", "uncertainty marker"),
        "bracket": ("pairwise bracket", "winner path", "criterion labels"),
        "verdict_stamp": ("bounded verdict stamp", "source refs", "confidence badge"),
        "comparison": ("two-column comparison", "criterion ticks", "refusal slot"),
        "refusal_card": ("refusal reason card", "blocked-surface icons", "next evidence needed"),
        "confidence_meter": ("confidence meter", "provenance rail", "scope boundary"),
    }
    return elements[shape]


def _claims(
    *items: tuple[str, ClaimClass, str | None],
) -> tuple[PackagingClaim, ...]:
    return tuple(
        PackagingClaim(text=text, claim_class=claim_class, public_event_ref=event_ref)
        for text, claim_class, event_ref in items
    )


def _verdict(
    field_kind: PackagingFieldKind,
    field_text: str,
    claims: tuple[PackagingClaim, ...] = (),
) -> PolicyVerdict:
    payload = PackagingPayload(
        field_kind=field_kind,
        field_text=field_text,
        claims=claims,
    )
    return evaluate_payload(payload)


def _format_name(format_id: str) -> str:
    labels = {
        "tier_list": "Tier List",
        "ranking": "Ranking",
        "bracket": "Bracket",
        "review": "Review",
        "comparison": "Comparison",
        "react_commentary": "React Commentary",
        "watch_along": "Watch-Along",
        "explainer": "Explainer",
        "rundown": "Rundown",
        "refusal_breakdown": "Refusal Breakdown",
        "evidence_audit": "Claim Audit",
        "claim_audit": "Claim Audit",
    }
    return labels.get(format_id, format_id.replace("_", " ").replace("-", " ").title())


def _epistemic_test(grounding_question: str) -> str:
    text = grounding_question.strip().rstrip("?")
    if not text:
        return "what the evidence can support"
    if len(text) <= 72:
        return text[0].lower() + text[1:]
    return _truncate(text[0].lower() + text[1:], 72)


def _boundary_label(boundary: ProgrammeBoundaryEvent) -> str:
    if boundary.cuepoint_chapter_policy.chapter_label:
        return boundary.cuepoint_chapter_policy.chapter_label
    return boundary.boundary_type.replace(".", " ").replace("_", " ").title()


def _shorts_hook(boundary: ProgrammeBoundaryEvent, focus: ShortsFocus) -> str:
    focus_text = _shorts_focus_label(focus).lower()
    summary = _platform_caption_text(boundary.summary)
    return _truncate(f"{focus_text}: {summary}", 120)


def _shorts_focus_label(focus: ShortsFocus) -> str:
    return {
        "rank_reversal": "Rank reversal",
        "refusal": "Refusal",
        "correction": "Correction",
        "confidence_collapse": "Confidence collapse",
        "grounding_moment": "Grounding moment",
    }[focus]


def _platform_caption_text(text: str) -> str:
    cleaned = _PRIVATE_SENTINEL_RE.sub("[private reference removed]", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return _truncate(cleaned or "Programme boundary recorded.", 160)


def _contains_reversal(text: str) -> bool:
    return bool(re.search(r"\b(reversal|flipped|overturned|upset)\b", text, re.IGNORECASE))


def _contains_confidence_collapse(text: str) -> bool:
    return bool(re.search(r"\b(confidence collapsed|confidence drop|uncertain)\b", text, re.I))


def _contains_grounding_moment(text: str) -> bool:
    return bool(re.search(r"\b(grounding|evidence observed|witness)\b", text, re.I))


def _evidence_refs(
    run: ContentProgrammeRunEnvelope,
    boundary_events: Sequence[ProgrammeBoundaryEvent],
) -> tuple[str, ...]:
    refs = (
        *run.wcs.evidence_envelope_refs,
        *run.gate_refs.grounding_gate_refs,
        *(ref for boundary in boundary_events for ref in boundary.evidence_refs),
    )
    return tuple(_dedupe(refs))


def _truncate_title(text: str) -> str:
    return _truncate(text, 100)


def _truncate(text: str, max_len: int) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 3].rstrip() + "..."


def _sanitize_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]+", "-", value).strip("-")


def _dedupe(items: Iterable[str | None]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.append(item)
    return seen


__all__ = [
    "REQUIRED_SURFACES",
    "ThumbnailShape",
    "YouTubeCaptionLine",
    "YouTubeChapter",
    "YouTubeDescription",
    "YouTubePackagingCompileResult",
    "YouTubePackagingReadiness",
    "YouTubePackagingSurface",
    "YouTubePackagingSurfaceGate",
    "YouTubePlacement",
    "YouTubeShortsCandidate",
    "YouTubeThumbnailBrief",
    "YouTubeTitleCandidate",
    "compile_youtube_content_programming_package",
]
