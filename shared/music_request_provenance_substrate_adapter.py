"""Music request / provenance substrate adapter.

Projects operator-private ``music.request`` impingements plus the current
music provenance manifest into a fail-closed substrate candidate. The adapter
does not control a player, mutate live audio routing, publish publicly, or
claim monetization. It only produces structured evidence for downstream
private-control, health, and provenance reviewers.

Spec: ``config/adapter-tranche-selection-memo.json``
Cc-task: ``music-request-provenance-substrate-adapter``
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from shared.music.provenance import MusicManifestAsset, is_broadcast_safe
from shared.research_vehicle_public_event import (
    PublicEventProvenance,
    PublicEventSource,
    PublicEventSurfacePolicy,
    ResearchVehiclePublicEvent,
    RightsClass,
)

MUSIC_REQUEST_SUBSTRATE_ID: Literal["music_request_sidechat"] = "music_request_sidechat"
MUSIC_PROVENANCE_SUBSTRATE_ID: Literal["music_provenance"] = "music_provenance"

PRODUCER: Literal["shared.music_request_provenance_substrate_adapter"] = (
    "shared.music_request_provenance_substrate_adapter"
)
TASK_ANCHOR: Literal["music-request-provenance-substrate-adapter"] = (
    "music-request-provenance-substrate-adapter"
)

MUSIC_REQUEST_TOKEN: Literal["music.request"] = "music.request"

DEFAULT_FRESHNESS_TTL_S: float = float(
    os.environ.get("HAPAX_MUSIC_REQUEST_SUBSTRATE_FRESHNESS_TTL_S", "30.0")
)
DEFAULT_PROVENANCE_TTL_S: float = float(
    os.environ.get("HAPAX_MUSIC_PROVENANCE_SUBSTRATE_FRESHNESS_TTL_S", "30.0")
)

SUBSTRATE_REFS: tuple[Literal["music_request_sidechat"], Literal["music_provenance"]] = (
    MUSIC_REQUEST_SUBSTRATE_ID,
    MUSIC_PROVENANCE_SUBSTRATE_ID,
)

RejectionReason = Literal[
    "missing_request_route",
    "stale_request",
    "duplicate",
    "missing_track",
]

PublicRisk = Literal[
    "missing_provenance_token",
    "missing_provenance_manifest",
    "invalid_provenance_manifest",
    "provenance_manifest_mismatch",
    "missing_provenance_observed_at",
    "stale_provenance_manifest",
    "music_request_route_unhealthy",
    "music_provenance_not_broadcast_safe",
    "music_content_risk_blocks_public_claim",
    "missing_audio_safety",
    "missing_egress_public_claim",
    "public_ready_private_control_only",
]


@dataclass(frozen=True)
class MusicRequestProvenanceCandidate:
    """One structured music request/provenance substrate candidate.

    ``event`` is intentionally conservative: it is a private-control
    ``monetization.review``/health record, not a public dispatch record.
    ``public_claim_gate_ready`` and ``monetization_gate_ready`` classify
    downstream readiness, while the event's surface policy keeps public and
    monetized claims false in this adapter.
    """

    event: ResearchVehiclePublicEvent
    request_id: str
    track_id: str
    title: str
    artist: str
    provenance_token: str | None
    substrate_refs: tuple[Literal["music_request_sidechat"], Literal["music_provenance"]]
    structured_impingement: dict[str, object]
    public_risk: PublicRisk
    public_claim_gate_ready: bool
    monetization_gate_ready: bool
    dry_run_reason: str | None


@dataclass(frozen=True)
class MusicRequestProvenanceRejection:
    """One request that could not become a substrate candidate."""

    request_id: str | None
    reason: RejectionReason
    detail: str = ""
    substrate_refs: tuple[Literal["music_request_sidechat"], Literal["music_provenance"]] = (
        SUBSTRATE_REFS
    )


@dataclass(frozen=True)
class _RequestView:
    request_id: str
    timestamp: float
    source: str
    interrupt_token: str
    selection_source: str
    track: Mapping[str, Any]


def project_music_request_provenance_substrate(
    requests: Iterable[Mapping[str, Any]],
    *,
    now: float,
    provenance_manifest: MusicManifestAsset | Mapping[str, Any] | None,
    provenance_observed_at: float | None,
    route_health: bool = True,
    audio_safe: bool = False,
    egress_public_claim: bool = False,
    freshness_ttl_s: float = DEFAULT_FRESHNESS_TTL_S,
    provenance_ttl_s: float = DEFAULT_PROVENANCE_TTL_S,
    seen_ids: Iterable[str] = (),
) -> tuple[list[MusicRequestProvenanceCandidate], list[MusicRequestProvenanceRejection]]:
    """Split music request impingements into substrate candidates/rejections.

    Gates applied before candidate creation:
    1. Route shape: operator sidechat + ``music.request`` interrupt token.
    2. Request freshness: ``now - timestamp <= freshness_ttl_s``.
    3. Idempotency: request id absent from ``seen_ids`` and this call.
    4. Track payload present.

    Provenance, audio-safety, egress, and content-risk failures do not touch
    live audio. They become dry-run/private-only candidates with explicit
    reasons so downstream health surfaces can explain the no-op.
    """

    candidates: list[MusicRequestProvenanceCandidate] = []
    rejections: list[MusicRequestProvenanceRejection] = []
    seen = set(seen_ids)
    manifest, manifest_error = _coerce_manifest(provenance_manifest)

    for request in requests:
        view = _extract_request(request)
        if isinstance(view, MusicRequestProvenanceRejection):
            rejections.append(view)
            continue

        if not _route_is_supported(view):
            rejections.append(
                MusicRequestProvenanceRejection(
                    request_id=view.request_id,
                    reason="missing_request_route",
                    detail=(
                        "expected source='operator.sidechat', "
                        "interrupt_token='music.request', selection_source='sidechat'"
                    ),
                )
            )
            continue

        lag_s = now - view.timestamp
        if lag_s > freshness_ttl_s:
            rejections.append(
                MusicRequestProvenanceRejection(
                    request_id=view.request_id,
                    reason="stale_request",
                    detail=f"lag_s={lag_s:.2f} exceeds ttl={freshness_ttl_s:.2f}",
                )
            )
            continue

        if view.request_id in seen:
            rejections.append(
                MusicRequestProvenanceRejection(
                    request_id=view.request_id,
                    reason="duplicate",
                    detail=f"request_id={view.request_id}",
                )
            )
            continue
        seen.add(view.request_id)

        if not view.track:
            rejections.append(
                MusicRequestProvenanceRejection(
                    request_id=view.request_id,
                    reason="missing_track",
                    detail="content.track missing or not an object",
                )
            )
            continue

        candidates.append(
            _build_candidate(
                view,
                now=now,
                request_lag_s=lag_s,
                manifest=manifest,
                manifest_error=manifest_error,
                provenance_observed_at=provenance_observed_at,
                provenance_ttl_s=provenance_ttl_s,
                route_health=route_health,
                audio_safe=audio_safe,
                egress_public_claim=egress_public_claim,
            )
        )

    return candidates, rejections


def _extract_request(
    request: Mapping[str, Any],
) -> _RequestView | MusicRequestProvenanceRejection:
    request_id = _string(request.get("id"))
    if request_id is None:
        request_id = _stable_request_id(request)
    timestamp = _float(request.get("timestamp"))
    if timestamp is None:
        return MusicRequestProvenanceRejection(
            request_id=request_id,
            reason="missing_request_route",
            detail="timestamp missing or non-numeric",
        )
    content = _mapping(request.get("content"))
    track = _mapping(content.get("track")) if content is not None else None
    return _RequestView(
        request_id=request_id,
        timestamp=timestamp,
        source=_string(request.get("source")) or "",
        interrupt_token=_string(request.get("interrupt_token")) or "",
        selection_source=_string(content.get("selection_source")) if content else "",
        track=track or {},
    )


def _route_is_supported(view: _RequestView) -> bool:
    return (
        view.source == "operator.sidechat"
        and view.interrupt_token == MUSIC_REQUEST_TOKEN
        and view.selection_source == "sidechat"
    )


def _build_candidate(
    view: _RequestView,
    *,
    now: float,
    request_lag_s: float,
    manifest: MusicManifestAsset | None,
    manifest_error: str | None,
    provenance_observed_at: float | None,
    provenance_ttl_s: float,
    route_health: bool,
    audio_safe: bool,
    egress_public_claim: bool,
) -> MusicRequestProvenanceCandidate:
    title = _string(view.track.get("title")) or "unknown title"
    artist = _string(view.track.get("artist")) or "unknown artist"
    track_id = _string(view.track.get("path")) or _string(view.track.get("track_id")) or "unknown"
    source = _string(view.track.get("source")) or "unknown"
    token = _string(view.track.get("provenance_token"))
    music_provenance = _string(view.track.get("music_provenance"))
    license_ref = _string(view.track.get("music_license"))

    public_risk = _public_risk(
        token=token,
        manifest=manifest,
        manifest_error=manifest_error,
        provenance_observed_at=provenance_observed_at,
        provenance_ttl_s=provenance_ttl_s,
        now=now,
        route_health=route_health,
        audio_safe=audio_safe,
        egress_public_claim=egress_public_claim,
    )
    dry_run_reason = None if public_risk == "public_ready_private_control_only" else public_risk
    public_ready = public_risk == "public_ready_private_control_only"
    monetization_ready = (
        public_ready
        and manifest is not None
        and manifest.tier
        in {
            "tier_0_owned",
            "tier_1_platform_cleared",
        }
    )

    event = _build_event(
        view=view,
        title=title,
        artist=artist,
        track_id=track_id,
        source=source,
        token=token,
        music_provenance=music_provenance,
        license_ref=license_ref,
        now=now,
        request_lag_s=request_lag_s,
        manifest=manifest,
        public_risk=public_risk,
        dry_run_reason=dry_run_reason,
    )

    structured_impingement: dict[str, object] = {
        "id": view.request_id,
        "source": view.source,
        "interrupt_token": view.interrupt_token,
        "selection_source": view.selection_source,
        "substrate_refs": list(SUBSTRATE_REFS),
        "track": {
            "track_id": track_id,
            "title": title,
            "artist": artist,
            "source": source,
            "music_provenance": music_provenance,
            "music_license": license_ref,
            "provenance_token": token,
        },
    }
    return MusicRequestProvenanceCandidate(
        event=event,
        request_id=view.request_id,
        track_id=track_id,
        title=title,
        artist=artist,
        provenance_token=token,
        substrate_refs=SUBSTRATE_REFS,
        structured_impingement=structured_impingement,
        public_risk=public_risk,
        public_claim_gate_ready=public_ready,
        monetization_gate_ready=monetization_ready,
        dry_run_reason=dry_run_reason,
    )


def _public_risk(
    *,
    token: str | None,
    manifest: MusicManifestAsset | None,
    manifest_error: str | None,
    provenance_observed_at: float | None,
    provenance_ttl_s: float,
    now: float,
    route_health: bool,
    audio_safe: bool,
    egress_public_claim: bool,
) -> PublicRisk:
    if token is None:
        return "missing_provenance_token"
    if manifest_error is not None:
        return "invalid_provenance_manifest"
    if manifest is None:
        return "missing_provenance_manifest"
    if manifest.token != token:
        return "provenance_manifest_mismatch"
    if provenance_observed_at is None:
        return "missing_provenance_observed_at"
    if now - provenance_observed_at > provenance_ttl_s:
        return "stale_provenance_manifest"
    if not route_health:
        return "music_request_route_unhealthy"
    if not manifest.broadcast_safe or not is_broadcast_safe(manifest.music_provenance):
        return "music_provenance_not_broadcast_safe"
    if manifest.tier in {"unknown", "tier_4_risky"}:
        return "music_content_risk_blocks_public_claim"
    if not audio_safe:
        return "missing_audio_safety"
    if not egress_public_claim:
        return "missing_egress_public_claim"
    return "public_ready_private_control_only"


def _build_event(
    *,
    view: _RequestView,
    title: str,
    artist: str,
    track_id: str,
    source: str,
    token: str | None,
    music_provenance: str | None,
    license_ref: str | None,
    now: float,
    request_lag_s: float,
    manifest: MusicManifestAsset | None,
    public_risk: PublicRisk,
    dry_run_reason: str | None,
) -> ResearchVehiclePublicEvent:
    evidence_refs = _unique_evidence_refs(
        [
            f"music_request:{view.request_id}",
            f"substrate:{MUSIC_REQUEST_SUBSTRATE_ID}",
            f"substrate:{MUSIC_PROVENANCE_SUBSTRATE_ID}",
            f"track:{_short_digest(track_id)}",
            f"manifest_token:{token}" if token else None,
            f"music_provenance:{music_provenance}" if music_provenance else None,
            f"music_license:{license_ref}" if license_ref else None,
            f"public_risk:{public_risk}",
        ]
    )
    surface_policy = PublicEventSurfacePolicy(
        allowed_surfaces=["health", "monetization"],
        denied_surfaces=[
            "youtube_description",
            "youtube_cuepoints",
            "youtube_chapters",
            "youtube_captions",
            "youtube_shorts",
            "archive",
            "replay",
            "mastodon",
            "bluesky",
            "discord",
        ],
        claim_live=False,
        claim_archive=False,
        claim_monetizable=False,
        requires_egress_public_claim=True,
        requires_audio_safe=True,
        requires_provenance=True,
        requires_human_review=True,
        rate_limit_key="music.request.provenance",
        redaction_policy="redact_private",
        fallback_action="dry_run" if dry_run_reason else "private_only",
        dry_run_reason=dry_run_reason,
    )
    rights_class = _rights_class(manifest)
    return ResearchVehiclePublicEvent(
        event_id=f"monetization_review:music_request:{_short_digest(view.request_id)}",
        event_type="monetization.review",
        occurred_at=_iso_from_epoch(view.timestamp),
        broadcast_id=None,
        programme_id=None,
        condition_id=None,
        source=PublicEventSource(
            producer=PRODUCER,
            substrate_id=MUSIC_REQUEST_SUBSTRATE_ID,
            task_anchor=TASK_ANCHOR,
            evidence_ref=f"music_request:{view.request_id}",
            freshness_ref=(
                f"music_request.lag_s={request_lag_s:.2f};music_provenance={public_risk}"
            ),
        ),
        salience=0.35,
        state_kind="monetization_state",
        rights_class=rights_class,
        privacy_class="operator_private",
        provenance=PublicEventProvenance(
            token=token,
            generated_at=_iso_from_epoch(now),
            producer=PRODUCER,
            evidence_refs=evidence_refs,
            rights_basis=_rights_basis(manifest, public_risk),
            citation_refs=[],
        ),
        public_url=None,
        frame_ref=None,
        chapter_ref=None,
        attribution_refs=_attribution_refs(
            title=title,
            artist=artist,
            source=source,
            manifest=manifest,
        ),
        surface_policy=surface_policy,
    )


def _rights_class(manifest: MusicManifestAsset | None) -> RightsClass:
    if manifest is None or manifest.token is None:
        return "unknown"
    if manifest.tier in {"unknown", "tier_4_risky"}:
        return "third_party_uncleared"
    if manifest.tier in {"tier_0_owned", "tier_1_platform_cleared"}:
        return "operator_controlled"
    return "third_party_attributed"


def _rights_basis(manifest: MusicManifestAsset | None, public_risk: PublicRisk) -> str:
    if manifest is None:
        return f"music provenance unavailable; public_risk={public_risk}"
    return (
        f"music_provenance={manifest.music_provenance}; "
        f"tier={manifest.tier}; broadcast_safe={manifest.broadcast_safe}; "
        f"public_risk={public_risk}"
    )


def _attribution_refs(
    *,
    title: str,
    artist: str,
    source: str,
    manifest: MusicManifestAsset | None,
) -> list[str]:
    refs = [
        f"music_artist:{_short_digest(artist)}",
        f"music_title:{_short_digest(title)}",
        f"music_source:{source}",
    ]
    if manifest is not None and manifest.license:
        refs.append(f"music_license:{manifest.license}")
    return refs


def _coerce_manifest(
    manifest: MusicManifestAsset | Mapping[str, Any] | None,
) -> tuple[MusicManifestAsset | None, str | None]:
    if manifest is None:
        return None, None
    if isinstance(manifest, MusicManifestAsset):
        return manifest, None
    try:
        return MusicManifestAsset.model_validate(manifest), None
    except Exception:
        return None, "invalid_provenance_manifest"


def _mapping(value: object) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _stable_request_id(request: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(repr(sorted(request.items())).encode("utf-8")).hexdigest()
    return f"missing-id-{digest[:12]}"


def _short_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _unique_evidence_refs(values: Iterable[str | None]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        if value:
            seen.setdefault(value, None)
    return list(seen)


def _iso_from_epoch(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, tz=UTC).isoformat()


__all__ = [
    "DEFAULT_FRESHNESS_TTL_S",
    "DEFAULT_PROVENANCE_TTL_S",
    "MUSIC_PROVENANCE_SUBSTRATE_ID",
    "MUSIC_REQUEST_SUBSTRATE_ID",
    "MUSIC_REQUEST_TOKEN",
    "MusicRequestProvenanceCandidate",
    "MusicRequestProvenanceRejection",
    "PRODUCER",
    "PublicRisk",
    "RejectionReason",
    "SUBSTRATE_REFS",
    "TASK_ANCHOR",
    "project_music_request_provenance_substrate",
]
