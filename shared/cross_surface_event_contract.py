"""Cross-surface fanout contract helpers for ResearchVehiclePublicEvent.

This module is intentionally not an adapter. It gives downstream surface
adapters a typed aperture registry and a deterministic fanout decision object
that can be written as an event or reported as health.
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.research_vehicle_public_event import (
    EventType,
    PrivacyClass,
    PublicEventSurfacePolicy,
    ResearchVehiclePublicEvent,
    RightsClass,
    Surface,
)

type CrossSurfaceAperture = Literal[
    "youtube",
    "youtube_channel_trailer",
    "omg_statuslog",
    "omg_weblog",
    "arena",
    "mastodon",
    "bluesky",
    "discord",
    "shorts",
    "archive",
    "replay",
]

type FanoutAction = Literal[
    "publish",
    "link",
    "embed",
    "redact",
    "hold",
    "archive",
    "replay",
]

type FanoutDecision = Literal["allow", "redact", "hold", "deny"]
type FanoutHealthStatus = Literal["ok", "degraded", "blocked"]
type SurfaceReference = Literal["public_url", "frame_ref", "chapter_ref"]
type ApertureReality = Literal[
    "active_canonical",
    "active_legacy",
    "active_artifact",
    "active_archive",
    "inactive",
    "missing_unit",
    "credential_blocked",
    "unavailable",
    "operator_review",
    "refused",
]

ALL_FANOUT_ACTIONS: tuple[FanoutAction, ...] = (
    "publish",
    "link",
    "embed",
    "redact",
    "hold",
    "archive",
    "replay",
)

_PUBLIC_SAFE_RIGHTS: frozenset[RightsClass] = frozenset(
    {"operator_original", "operator_controlled", "third_party_attributed", "platform_embedded"}
)
_PUBLIC_SAFE_PRIVACY: frozenset[PrivacyClass] = frozenset({"public_safe", "aggregate_only"})
_NON_BROADCAST_EGRESS_BYPASS_EVENTS: frozenset[EventType] = frozenset(
    {
        "omg.weblog",
        "velocity.digest",
        "governance.enforcement",
    }
)


class CrossSurfaceApertureContract(BaseModel):
    """A machine-readable contract row for one public aperture."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aperture_id: CrossSurfaceAperture
    display_name: str
    target_surfaces: tuple[Surface, ...]
    allowed_event_types: tuple[EventType, ...]
    allowed_actions: tuple[FanoutAction, ...]
    current_reality: ApertureReality
    publication_contract: str | None
    child_task: str
    health_owner: str
    requires_human_review: bool = False
    requires_one_reference: tuple[SurfaceReference, ...] = Field(default_factory=tuple)


class CrossSurfaceFanoutDecision(BaseModel):
    """Policy-aware result for one event x aperture x action."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    decision_id: str
    source_event_id: str
    source_event_type: EventType
    target_aperture: CrossSurfaceAperture
    target_surfaces: list[Surface]
    requested_action: FanoutAction
    resolved_action: FanoutAction
    decision: FanoutDecision
    reasons: list[str]
    health_status: FanoutHealthStatus
    health_ref: str
    failure_event_type: Literal["fanout.decision"] | None
    failure_event_id: str | None
    child_task: str
    dry_run: bool
    surface_policy_snapshot: PublicEventSurfacePolicy

    def to_json_line(self) -> str:
        """Serialize as deterministic JSONL for failure-as-event sinks."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True) + "\n"


_YOUTUBE_EVENTS: tuple[EventType, ...] = (
    "broadcast.boundary",
    "programme.boundary",
    "condition.changed",
    "caption.segment",
    "cuepoint.candidate",
    "chapter.marker",
    "metadata.update",
    "channel_section.candidate",
)
_SOCIAL_EVENTS: tuple[EventType, ...] = (
    "broadcast.boundary",
    "chronicle.high_salience",
    "omg.weblog",
    "velocity.digest",
    "governance.enforcement",
    "shorts.upload",
    "aesthetic.frame_capture",
    "publication.artifact",
)
_ARCHIVE_EVENTS: tuple[EventType, ...] = (
    "broadcast.boundary",
    "programme.boundary",
    "condition.changed",
    "chronicle.high_salience",
    "aesthetic.frame_capture",
    "caption.segment",
    "cuepoint.candidate",
    "chapter.marker",
    "shorts.candidate",
    "shorts.upload",
    "metadata.update",
    "channel_section.candidate",
    "arena_block.candidate",
    "omg.statuslog",
    "omg.weblog",
    "velocity.digest",
    "governance.enforcement",
    "publication.artifact",
    "archive.segment",
    "monetization.review",
    "fanout.decision",
)

CROSS_SURFACE_APERTURES: tuple[CrossSurfaceApertureContract, ...] = (
    CrossSurfaceApertureContract(
        aperture_id="youtube",
        display_name="YouTube",
        target_surfaces=(
            "youtube_description",
            "youtube_cuepoints",
            "youtube_chapters",
            "youtube_captions",
            "youtube_channel_sections",
        ),
        allowed_event_types=_YOUTUBE_EVENTS,
        allowed_actions=("publish", "link", "embed", "redact", "hold", "archive", "replay"),
        current_reality="active_legacy",
        publication_contract="youtube-description/youtube-chapters/youtube-title",
        child_task="youtube-research-translation-ledger",
        health_owner="youtube-public-event-adapter",
        requires_one_reference=("public_url", "chapter_ref"),
    ),
    # Channel trailer is a separate aperture rather than a sub-surface of
    # `youtube` because it has a strictly narrower action set (link/embed
    # only — never `publish` of new content; the trailer points at an
    # already-published live broadcast URL) and an independent reality
    # gate (channel id + OAuth write scope + quota), distinct from the
    # rest of YouTube. Keeping it separate prevents the youtube aperture's
    # `publish` action from inadvertently leaking onto the trailer surface.
    CrossSurfaceApertureContract(
        aperture_id="youtube_channel_trailer",
        display_name="YouTube Channel Trailer",
        target_surfaces=("youtube_channel_trailer",),
        allowed_event_types=("broadcast.boundary",),
        allowed_actions=("link", "embed", "redact", "hold"),
        current_reality="credential_blocked",
        publication_contract="channel-trailer",
        child_task="youtube-channel-trailer-public-event-reconcile",
        health_owner="youtube-channel-trailer-public-event-reconcile",
        requires_one_reference=("public_url",),
    ),
    CrossSurfaceApertureContract(
        aperture_id="omg_statuslog",
        display_name="OMG statuslog",
        target_surfaces=("omg_statuslog",),
        allowed_event_types=("broadcast.boundary", "chronicle.high_salience", "omg.statuslog"),
        allowed_actions=("publish", "link", "redact", "hold"),
        current_reality="credential_blocked",
        publication_contract="omg-lol-statuslog",
        child_task="omg-statuslog-public-event-adapter",
        health_owner="omg-statuslog-public-event-adapter",
    ),
    CrossSurfaceApertureContract(
        aperture_id="omg_weblog",
        display_name="OMG weblog",
        target_surfaces=("omg_weblog",),
        allowed_event_types=("omg.weblog", "publication.artifact"),
        allowed_actions=("publish", "link", "redact", "hold", "archive"),
        current_reality="operator_review",
        publication_contract="omg-lol-weblog",
        child_task="omg-weblog-rss-public-event-adapter",
        health_owner="omg-weblog-rss-public-event-adapter",
        requires_human_review=True,
    ),
    CrossSurfaceApertureContract(
        aperture_id="arena",
        display_name="Are.na",
        target_surfaces=("arena",),
        allowed_event_types=(
            "arena_block.candidate",
            "aesthetic.frame_capture",
            "chronicle.high_salience",
            "governance.enforcement",
            "omg.weblog",
            "publication.artifact",
            "velocity.digest",
        ),
        allowed_actions=("publish", "link", "embed", "redact", "hold", "archive"),
        current_reality="credential_blocked",
        publication_contract="arena-post",
        child_task="arena-public-event-unit-and-block-shape",
        health_owner="arena-public-event-unit-and-block-shape",
        requires_one_reference=("public_url", "frame_ref"),
    ),
    CrossSurfaceApertureContract(
        aperture_id="mastodon",
        display_name="Mastodon",
        target_surfaces=("mastodon",),
        allowed_event_types=_SOCIAL_EVENTS,
        allowed_actions=("publish", "link", "redact", "hold"),
        current_reality="active_canonical",
        publication_contract="mastodon-post",
        child_task="mastodon-public-event-adapter",
        health_owner="mastodon-public-event-adapter",
    ),
    CrossSurfaceApertureContract(
        aperture_id="bluesky",
        display_name="Bluesky",
        target_surfaces=("bluesky",),
        allowed_event_types=_SOCIAL_EVENTS,
        allowed_actions=("publish", "link", "embed", "redact", "hold"),
        current_reality="active_canonical",
        publication_contract="bluesky-post",
        child_task="bluesky-public-event-adapter",
        health_owner="bluesky-public-event-adapter",
    ),
    CrossSurfaceApertureContract(
        aperture_id="discord",
        display_name="Discord",
        target_surfaces=("discord",),
        allowed_event_types=("broadcast.boundary", "chronicle.high_salience", "shorts.upload"),
        allowed_actions=("publish", "link", "embed", "redact", "hold"),
        # Retired 2026-05-01 per cc-task discord-public-event-activation-or-retire;
        # constitutional refusal in docs/refusal-briefs/leverage-discord-community.md.
        # `refused` (vs the prior `inactive`) signals the operator disposition is
        # final, not "waiting on creds bootstrap".
        current_reality="refused",
        publication_contract="discord-webhook",
        child_task="discord-public-event-activation-or-retire",
        health_owner="leverage-REFUSED-discord-community",
    ),
    CrossSurfaceApertureContract(
        aperture_id="shorts",
        display_name="YouTube Shorts",
        target_surfaces=("youtube_shorts",),
        allowed_event_types=("shorts.candidate", "shorts.upload"),
        allowed_actions=("publish", "link", "embed", "redact", "hold", "archive"),
        current_reality="unavailable",
        publication_contract=None,
        child_task="shorts-public-event-adapter",
        health_owner="shorts-public-event-adapter",
        requires_one_reference=("public_url", "frame_ref"),
    ),
    CrossSurfaceApertureContract(
        aperture_id="archive",
        display_name="Archive",
        target_surfaces=("archive",),
        allowed_event_types=_ARCHIVE_EVENTS,
        allowed_actions=("archive", "link", "redact", "hold"),
        current_reality="active_archive",
        publication_contract=None,
        child_task="archive-replay-public-event-link-adapter",
        health_owner="hls-archive-rotate",
        requires_one_reference=("public_url", "frame_ref", "chapter_ref"),
    ),
    CrossSurfaceApertureContract(
        aperture_id="replay",
        display_name="Replay",
        target_surfaces=("replay",),
        allowed_event_types=(
            "broadcast.boundary",
            "programme.boundary",
            "chapter.marker",
            "archive.segment",
            "aesthetic.frame_capture",
            "shorts.upload",
            "publication.artifact",
        ),
        allowed_actions=("replay", "link", "embed", "redact", "hold"),
        current_reality="missing_unit",
        publication_contract=None,
        child_task="archive-replay-public-event-link-adapter",
        health_owner="archive-replay-public-event-link-adapter",
        requires_one_reference=("public_url", "frame_ref", "chapter_ref"),
    ),
)

_APERTURE_BY_ID: dict[CrossSurfaceAperture, CrossSurfaceApertureContract] = {
    contract.aperture_id: contract for contract in CROSS_SURFACE_APERTURES
}


def get_aperture_contract(aperture_id: CrossSurfaceAperture) -> CrossSurfaceApertureContract:
    """Return the static contract row for a first-class public aperture."""
    return _APERTURE_BY_ID[aperture_id]


def cross_surface_contract_payload() -> dict[str, object]:
    """Return a schema-shaped registry payload for downstream adapters."""
    return {
        "schema_version": 1,
        "actions": list(ALL_FANOUT_ACTIONS),
        "failure_event_type": "fanout.decision",
        "health_contract": {
            "ok": "target aperture may perform the resolved action",
            "degraded": "target aperture must hold, redact, dry-run, or wait for review",
            "blocked": "target aperture must not publish and should emit/report the decision",
        },
        "apertures": [contract.model_dump(mode="json") for contract in CROSS_SURFACE_APERTURES],
    }


def decide_cross_surface_fanout(
    event: ResearchVehiclePublicEvent,
    target_aperture: CrossSurfaceAperture,
    requested_action: FanoutAction,
) -> CrossSurfaceFanoutDecision:
    """Resolve one event-driven fanout decision without performing publication."""

    contract = get_aperture_contract(target_aperture)
    decision_id = cross_surface_decision_id(
        event.event_id,
        target_aperture=target_aperture,
        requested_action=requested_action,
    )
    target_surfaces = _eligible_surfaces(event, contract)
    blockers = _fanout_blockers(
        event=event,
        contract=contract,
        requested_action=requested_action,
        target_surfaces=target_surfaces,
    )
    decision, resolved_action, health_status = _resolve_decision(
        requested_action=requested_action,
        blockers=blockers,
    )
    failure_event_id = None
    failure_event_type: Literal["fanout.decision"] | None = None
    if blockers and requested_action != "hold":
        failure_event_type = "fanout.decision"
        failure_event_id = _sanitize_id(f"{decision_id}:failure")

    return CrossSurfaceFanoutDecision(
        decision_id=decision_id,
        source_event_id=event.event_id,
        source_event_type=event.event_type,
        target_aperture=target_aperture,
        target_surfaces=list(target_surfaces),
        requested_action=requested_action,
        resolved_action=resolved_action,
        decision=decision,
        reasons=blockers or ["policy_allowed"],
        health_status=health_status,
        health_ref=f"cross_surface.{target_aperture}.{decision}",
        failure_event_type=failure_event_type,
        failure_event_id=failure_event_id,
        child_task=contract.child_task,
        dry_run=bool(blockers and requested_action != "hold"),
        surface_policy_snapshot=event.surface_policy,
    )


def cross_surface_decision_id(
    event_id: str,
    *,
    target_aperture: CrossSurfaceAperture,
    requested_action: FanoutAction,
) -> str:
    """Stable idempotency key for one fanout decision."""
    return _sanitize_id(f"csf:{event_id}:{target_aperture}:{requested_action}")


def _eligible_surfaces(
    event: ResearchVehiclePublicEvent,
    contract: CrossSurfaceApertureContract,
) -> tuple[Surface, ...]:
    allowed = set(event.surface_policy.allowed_surfaces)
    denied = set(event.surface_policy.denied_surfaces)
    return tuple(
        surface
        for surface in contract.target_surfaces
        if surface in allowed and surface not in denied
    )


def _fanout_blockers(
    *,
    event: ResearchVehiclePublicEvent,
    contract: CrossSurfaceApertureContract,
    requested_action: FanoutAction,
    target_surfaces: tuple[Surface, ...],
) -> list[str]:
    if requested_action == "hold":
        return []

    blockers: list[str] = []
    if requested_action not in contract.allowed_actions:
        blockers.append("action_not_supported")
    if event.event_type not in contract.allowed_event_types:
        blockers.append("event_type_not_allowed")
    if not target_surfaces:
        if set(contract.target_surfaces) & set(event.surface_policy.denied_surfaces):
            blockers.append("surface_denied")
        else:
            blockers.append("surface_not_allowed")
    if event.rights_class not in _PUBLIC_SAFE_RIGHTS:
        blockers.append("rights_blocked")
    if event.privacy_class not in _PUBLIC_SAFE_PRIVACY:
        blockers.append("privacy_blocked")
    if event.surface_policy.requires_provenance and not event.provenance.token:
        blockers.append("missing_provenance")
    if requested_action in {"publish", "link", "embed"}:
        if (
            event.event_type not in _NON_BROADCAST_EGRESS_BYPASS_EVENTS
            and event.surface_policy.requires_egress_public_claim
            and not event.surface_policy.claim_live
        ):
            blockers.append("egress_blocked")
    if requested_action == "archive" and not event.surface_policy.claim_archive:
        blockers.append("archive_claim_blocked")
    if requested_action == "replay" and not event.surface_policy.claim_archive:
        blockers.append("replay_claim_blocked")
    if contract.requires_human_review or event.surface_policy.requires_human_review:
        blockers.append("human_review_required")
    if contract.requires_one_reference and not any(
        _event_has_reference(event, reference) for reference in contract.requires_one_reference
    ):
        blockers.append("missing_surface_reference")
    if event.surface_policy.dry_run_reason:
        blockers.append(f"upstream_hold:{event.surface_policy.dry_run_reason}")
    return list(dict.fromkeys(blockers))


def _resolve_decision(
    *,
    requested_action: FanoutAction,
    blockers: list[str],
) -> tuple[FanoutDecision, FanoutAction, FanoutHealthStatus]:
    if requested_action == "hold":
        return "hold", "hold", "ok"
    if not blockers:
        return "allow", requested_action, "ok"
    if "human_review_required" in blockers and len(blockers) == 1:
        return "hold", "hold", "degraded"
    hard_denies = {
        "action_not_supported",
        "event_type_not_allowed",
        "surface_denied",
        "surface_not_allowed",
        "rights_blocked",
        "privacy_blocked",
        "missing_provenance",
    }
    if hard_denies & set(blockers):
        return "deny", "hold", "blocked"
    return "hold", "hold", "degraded"


def _event_has_reference(event: ResearchVehiclePublicEvent, reference: SurfaceReference) -> bool:
    if reference == "public_url":
        return bool(event.public_url)
    if reference == "frame_ref":
        return event.frame_ref is not None
    if reference == "chapter_ref":
        return event.chapter_ref is not None
    return False


def _sanitize_id(raw: str) -> str:
    result = re.sub(r"[^a-z0-9_:-]+", "_", raw.lower()).strip("_:")
    if not result or not result[0].isalpha():
        return f"csf:{result}"
    return result


__all__ = [
    "ALL_FANOUT_ACTIONS",
    "ApertureReality",
    "CROSS_SURFACE_APERTURES",
    "CrossSurfaceAperture",
    "CrossSurfaceApertureContract",
    "CrossSurfaceFanoutDecision",
    "FanoutAction",
    "FanoutDecision",
    "FanoutHealthStatus",
    "SurfaceReference",
    "cross_surface_contract_payload",
    "cross_surface_decision_id",
    "decide_cross_surface_fanout",
    "get_aperture_contract",
]
